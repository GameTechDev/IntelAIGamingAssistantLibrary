from __future__ import annotations

import argparse
import atexit
import base64
import ctypes
import contextlib
import io
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ctypes import wintypes

try:
    from .game_detection import GpuEngineCounterReader, ProcessGpuUsage, get_top_game_candidates, get_window_bounds_for_pid, list_process_names, wait_for_game_process
    from .game_walkthrough_downloader import GamerskyWalkthroughDownloader
    from .walkthrough_service_importer import WalkthroughServiceImporter
except ImportError:
    # Support direct script execution: python game_client.py
    from game_detection import GpuEngineCounterReader, ProcessGpuUsage, get_top_game_candidates, get_window_bounds_for_pid, list_process_names, wait_for_game_process
    from game_walkthrough_downloader import GamerskyWalkthroughDownloader
    from walkthrough_service_importer import WalkthroughServiceImporter

try:
    from PIL import Image, ImageGrab, ImageTk
except ImportError:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageGrab = None
    ImageTk = None

try:
    import keyboard  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dependency
    keyboard = None


_GLOBAL_LOG_LOCK = threading.Lock()
_GLOBAL_LOG_FILE_HANDLE: io.TextIOWrapper | None = None
_ORIGINAL_STDOUT: io.TextIOBase | None = None
_ORIGINAL_STDERR: io.TextIOBase | None = None
_SCRIPT_DIR = Path(__file__).resolve().parent.parent


class _TeeTextStream:
    def __init__(self, primary: io.TextIOBase, secondary: io.TextIOBase, lock: threading.Lock) -> None:
        self._primary = primary
        self._secondary = secondary
        self._lock = lock
        self.encoding = getattr(primary, "encoding", "utf-8")

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            value = str(value)
        with self._lock:
            written = self._primary.write(value)
            self._secondary.write(value)
        return written

    def flush(self) -> None:
        with self._lock:
            self._primary.flush()
            self._secondary.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._primary, "isatty", lambda: False)())


class _FileOnlyTextStream:
    def __init__(self, secondary: io.TextIOBase, lock: threading.Lock) -> None:
        self._secondary = secondary
        self._lock = lock
        self.encoding = getattr(secondary, "encoding", "utf-8")

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            value = str(value)
        with self._lock:
            return self._secondary.write(value)

    def flush(self) -> None:
        with self._lock:
            self._secondary.flush()

    def isatty(self) -> bool:
        return False


def _resolve_daily_log_path(base_path: Path) -> Path:
    now = datetime.now().strftime("%Y-%m-%d")
    suffix = base_path.suffix or ".log"
    stem = base_path.stem if base_path.suffix else base_path.name
    return base_path.with_name(f"{stem}-{now}{suffix}")


def _install_global_log_capture(log_path: Path, *, mirror_to_console: bool, daily_split: bool) -> Path:
    global _GLOBAL_LOG_FILE_HANDLE, _ORIGINAL_STDOUT, _ORIGINAL_STDERR

    if _GLOBAL_LOG_FILE_HANDLE is not None:
        return log_path

    resolved_path = log_path.expanduser()
    if daily_split:
        resolved_path = _resolve_daily_log_path(resolved_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    _GLOBAL_LOG_FILE_HANDLE = resolved_path.open("a", encoding="utf-8", buffering=1)

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    _ORIGINAL_STDOUT = original_stdout
    _ORIGINAL_STDERR = original_stderr
    if mirror_to_console:
        sys.stdout = _TeeTextStream(original_stdout, _GLOBAL_LOG_FILE_HANDLE, _GLOBAL_LOG_LOCK)  # type: ignore[assignment]
        sys.stderr = _TeeTextStream(original_stderr, _GLOBAL_LOG_FILE_HANDLE, _GLOBAL_LOG_LOCK)  # type: ignore[assignment]
    else:
        sys.stdout = _FileOnlyTextStream(_GLOBAL_LOG_FILE_HANDLE, _GLOBAL_LOG_LOCK)  # type: ignore[assignment]
        sys.stderr = _FileOnlyTextStream(_GLOBAL_LOG_FILE_HANDLE, _GLOBAL_LOG_LOCK)  # type: ignore[assignment]

    def _close_log_file() -> None:
        global _GLOBAL_LOG_FILE_HANDLE
        handle = _GLOBAL_LOG_FILE_HANDLE
        _GLOBAL_LOG_FILE_HANDLE = None
        if _ORIGINAL_STDOUT is not None:
            sys.stdout = _ORIGINAL_STDOUT
        if _ORIGINAL_STDERR is not None:
            sys.stderr = _ORIGINAL_STDERR
        if handle is None:
            return
        with contextlib.suppress(Exception):
            handle.flush()
        with contextlib.suppress(Exception):
            handle.close()

    atexit.register(_close_log_file)
    return resolved_path


def _install_global_exception_logging() -> None:
    def _sys_excepthook(exc_type, exc_value, exc_tb) -> None:
        print("[game-client] uncaught exception (main thread):", file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        thread_name = getattr(args.thread, "name", "unknown")
        print(f"[game-client] uncaught exception (thread={thread_name}):", file=sys.stderr)
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=sys.stderr)

    def _unraisablehook(unraisable) -> None:
        object_repr = repr(getattr(unraisable, "object", None))
        err_msg = getattr(unraisable, "err_msg", None) or "unraisable exception"
        print(f"[game-client] {err_msg}: object={object_repr}", file=sys.stderr)
        exc_type = getattr(unraisable, "exc_type", None)
        exc_value = getattr(unraisable, "exc_value", None)
        exc_tb = getattr(unraisable, "exc_traceback", None)
        if exc_type is not None:
            traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)

    sys.excepthook = _sys_excepthook
    threading.excepthook = _thread_excepthook
    sys.unraisablehook = _unraisablehook


@dataclass(slots=True)
class GameVisionClientConfig:
    user_id: str = "game-user"
    poll_interval_seconds: float = 1.0
    analysis_interval_seconds: float = 1.0
    three_d_threshold: float = 20.0
    decoder_threshold: float = 10.0
    encoder_threshold: float = 10.0
    phys_index: int | None = None
    detect_process_name: str | None = None
    detect_process_fallback_gpu: bool = False
    walkthrough_bootstrap_enabled: bool = False
    walkthrough_base_url: str = "http://127.0.0.1:9190"
    walkthrough_game_name: str | None = None
    walkthrough_max_images_per_guide: int = 3
    walkthrough_timeout_seconds: float = 10.0
    walkthrough_query_topk: int = 1
    walkthrough_query_threshold: float = 0.88
    walkthrough_query_threshold_2: float = 0.01
    walkthrough_confirm_hit_count: int = 2
    walkthrough_overlay_hold_seconds: float = 10.0
    walkthrough_screenshot_interval_seconds: float | None = None
    walkthrough_match_score_threshold: float = 0.7
    walkthrough_display_debug_details: bool = False
    walkthrough_download_dir: str = (_SCRIPT_DIR / "walkthrough").as_posix()
    walkthrough_bootstrap_once: bool = True
    walkthrough_rebootstrap_on_query_miss: bool = False
    walkthrough_log_file_path: str | None = None
    detected_scene_file: str = "detected_scene.json"
    overlay_width: int = 430
    overlay_height: int = 420
    overlay_margin: int = 24
    overlay_title: str = "Game Vision"
    overlay_alpha: float = 0.90
    toggle_hotkey: str = "ctrl+shift+g"


class DraggableOverlayWindow:
    def __init__(
        self,
        root: tk.Tk,
        *,
        width: int,
        height: int,
        margin: int,
        title: str,
        alpha: float,
        debug_details: bool,
    ) -> None:
        self.root = root
        self.margin = margin
        self._debug_details = bool(debug_details)
        self.min_width = 320
        self.min_height = 260
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", max(0.4, min(alpha, 1.0)))
        self.window.configure(bg="#111318")
        self.window.geometry(self._default_geometry(width=width, height=height))
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._resize_origin_x = 0
        self._resize_origin_y = 0
        self._resize_start_width = width
        self._resize_start_height = height
        self._resize_start_x = 0
        self._resize_start_y = 0
        self._resize_edge: str | None = None
        self._resize_border = 6
        self._resize_grips: dict[str, tk.Frame] = {}

        shell = tk.Frame(self.window, bg="#111318", highlightbackground="#3a475a", highlightthickness=1)
        shell.pack(fill="both", expand=True)

        self.header = tk.Frame(shell, bg="#1a2230", cursor="fleur")
        self.header.pack(fill="x")
        self.title_label = tk.Label(
            self.header,
            text=title,
            anchor="w",
            bg="#1a2230",
            fg="#f2f6ff",
            padx=12,
            pady=8,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        self.title_label.pack(side="left", fill="x", expand=True)
        self.close_button = tk.Button(
            self.header,
            text="×",
            command=root.quit,
            bg="#1a2230",
            fg="#edf2ff",
            activebackground="#9f2d2d",
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=6,
            font=("Segoe UI Symbol", 12, "bold"),
            cursor="hand2",
        )
        self.close_button.pack(side="right")
        self.status_label = tk.Label(
            self.header,
            text="等待中",
            anchor="e",
            bg="#1a2230",
            fg="#9bb4d1",
            padx=12,
            pady=8,
            font=("Microsoft YaHei UI", 9),
        )
        self.status_label.pack(side="right", padx=(0, 4))

        body = tk.Frame(shell, bg="#111318")
        body.pack(fill="both", expand=True)
        self.body = body
        self.text = tk.Text(
            body,
            wrap="word",
            bg="#111318",
            fg="#edf2ff",
            insertbackground="#edf2ff",
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=12,
            font=("Microsoft YaHei UI", 20),
        )
        scrollbar = tk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.text.configure(state="disabled")
        self._inline_images: list[object] = []
        self._inline_images_height = 0

        self._create_resize_grips()
        self.window.bind("<Configure>", self._on_window_configure)

        for widget in (self.header, self.title_label, self.status_label):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

    def show(self) -> None:
        self.window.deiconify()

    def hide(self) -> None:
        self.window.withdraw()

    def is_visible(self) -> bool:
        return self.window.state() != "withdrawn"

    def set_title(self, title: str) -> None:
        self.title_label.configure(text=title)

    def set_status(self, value: str) -> None:
        self.status_label.configure(text=value)

    def replace_text(
        self,
        value: str,
        image_bytes: bytes | None = None,
        image_bytes_list: list[bytes] | None = None,
    ) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self._inline_images = []
        self._inline_images_height = 0
        images_to_render = [item for item in (image_bytes_list or []) if item]
        if not images_to_render and image_bytes is not None:
            images_to_render = [image_bytes]
        if images_to_render and Image is not None and ImageTk is not None:
            self.window.update_idletasks()
            max_width = max(140, self.text.winfo_width() - 32)
            max_height = 220
            inserted_header = False
            for raw_bytes in images_to_render:
                try:
                    image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
                    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                    rendered_height = int(image.height)
                    photo = ImageTk.PhotoImage(image)
                except Exception:
                    continue
                self._inline_images.append(photo)
                if self._debug_details and not inserted_header:
                    self.text.insert("end", "\n\n[场景配图]\n")
                    inserted_header = True
                else:
                    self.text.insert("end", "\n")
                self.text.image_create("end", image=photo)
                self._inline_images_height += rendered_height + 10
            if self._inline_images_height > 0:
                self._inline_images_height += 20
        # For full guide rendering, keep viewport at the top so source/url header is visible.
        self.text.see("1.0")
        self.text.configure(state="disabled")

    def compact_to_one_line(self) -> None:
        self.window.update_idletasks()
        header_height = self.header.winfo_height() or self.header.winfo_reqheight()
        line_height = tkfont.Font(font=self.text.cget("font")).metrics("linespace")
        target_height = max(86, int(header_height + line_height + 26))
        self._set_window_height(target_height)

    def fit_to_content(self) -> None:
        self.window.update_idletasks()
        header_height = self.header.winfo_height() or self.header.winfo_reqheight()
        content_height = self._measure_rendered_content_height()
        max_height = int(self.root.winfo_screenheight())
        target_height = min(max_height, max(120, int(header_height + content_height)))
        self._set_window_height(target_height)

    def _measure_rendered_content_height(self) -> int:
        self.window.update_idletasks()
        line_height = tkfont.Font(font=self.text.cget("font")).metrics("linespace")
        images_height = max(0, int(self._inline_images_height))
        try:
            displayline_result = self.text.count("1.0", "end-1c", "displaylines")
            if isinstance(displayline_result, tuple) and displayline_result:
                displayline_count = max(1, int(displayline_result[0]))
                text_height = (displayline_count * line_height) + 26
                return int(text_height + images_height)
        except Exception:
            pass

        try:
            line_count = max(1, int(self.text.index("end-1c").split(".", 1)[0]))
        except Exception:
            line_count = 1
        text_height = (line_count * line_height) + 26
        return int(text_height + images_height)

    def append_text(self, value: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", value)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _set_window_height(self, target_height: int) -> None:
        current_width = max(280, self.window.winfo_width())
        current_x = self.window.winfo_x()
        current_y = self.window.winfo_y()
        screen_height = max(1, int(self.root.winfo_screenheight()))

        clamped_height = max(1, min(int(target_height), screen_height))
        next_y = int(current_y)
        if next_y < 0:
            next_y = 0
        if next_y + clamped_height > screen_height:
            next_y = max(0, screen_height - clamped_height)

        self.window.geometry(f"{current_width}x{clamped_height}+{current_x}+{next_y}")

    def _default_geometry(self, *, width: int, height: int) -> str:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        position_x = max(0, screen_width - width - self.margin)
        position_y = self.margin
        return f"{width}x{height}+{position_x}+{position_y}"

    def _start_drag(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_origin_x = int(event.x_root - self.window.winfo_x())
        self._drag_origin_y = int(event.y_root - self.window.winfo_y())

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        next_x = int(event.x_root - self._drag_origin_x)
        next_y = int(event.y_root - self._drag_origin_y)
        self.window.geometry(f"+{next_x}+{next_y}")

    def _start_resize(self, event: tk.Event[tk.Misc], edge: str) -> None:
        self._resize_origin_x = int(event.x_root)
        self._resize_origin_y = int(event.y_root)
        self._resize_start_x = self.window.winfo_x()
        self._resize_start_y = self.window.winfo_y()
        self._resize_start_width = self.window.winfo_width()
        self._resize_start_height = self.window.winfo_height()
        self._resize_edge = edge

    def _resize(self, event: tk.Event[tk.Misc]) -> None:
        if not self._resize_edge:
            return
        delta_x = int(event.x_root - self._resize_origin_x)
        delta_y = int(event.y_root - self._resize_origin_y)
        edge = self._resize_edge
        next_x = self._resize_start_x
        next_y = self._resize_start_y
        next_width = self._resize_start_width
        next_height = self._resize_start_height

        if "e" in edge:
            next_width = max(self.min_width, self._resize_start_width + delta_x)
        if "s" in edge:
            next_height = max(self.min_height, self._resize_start_height + delta_y)
        if "w" in edge:
            proposed_width = self._resize_start_width - delta_x
            next_width = max(self.min_width, proposed_width)
            next_x = self._resize_start_x + (self._resize_start_width - next_width)
        if "n" in edge:
            proposed_height = self._resize_start_height - delta_y
            next_height = max(self.min_height, proposed_height)
            next_y = self._resize_start_y + (self._resize_start_height - next_height)

        self.window.geometry(f"{next_width}x{next_height}+{next_x}+{next_y}")

    def _stop_resize(self, event: tk.Event[tk.Misc]) -> None:
        del event
        self._resize_edge = None

    def _create_resize_grips(self) -> None:
        grips = {
            "n": ("sb_v_double_arrow", {"x": self._resize_border, "y": 0, "relwidth": 1.0, "width": -self._resize_border * 2, "height": self._resize_border}),
            "s": ("sb_v_double_arrow", {"x": self._resize_border, "rely": 1.0, "y": -self._resize_border, "relwidth": 1.0, "width": -self._resize_border * 2, "height": self._resize_border}),
            "w": ("sb_h_double_arrow", {"x": 0, "y": self._resize_border, "width": self._resize_border, "relheight": 1.0, "height": -self._resize_border * 2}),
            "e": ("sb_h_double_arrow", {"relx": 1.0, "x": -self._resize_border, "y": self._resize_border, "width": self._resize_border, "relheight": 1.0, "height": -self._resize_border * 2}),
            "nw": ("size_nw_se", {"x": 0, "y": 0, "width": self._resize_border, "height": self._resize_border}),
            "ne": ("size_ne_sw", {"relx": 1.0, "x": -self._resize_border, "y": 0, "width": self._resize_border, "height": self._resize_border}),
            "sw": ("size_ne_sw", {"x": 0, "rely": 1.0, "y": -self._resize_border, "width": self._resize_border, "height": self._resize_border}),
            "se": ("size_nw_se", {"relx": 1.0, "rely": 1.0, "x": -self._resize_border, "y": -self._resize_border, "width": self._resize_border, "height": self._resize_border}),
        }
        for edge, (cursor, place_kwargs) in grips.items():
            grip = tk.Frame(self.window, bg="#111318", cursor=cursor, highlightthickness=0, borderwidth=0)
            grip.place(**place_kwargs)
            grip.lift()
            grip.bind("<ButtonPress-1>", lambda event, edge_name=edge: self._start_resize(event, edge_name))
            grip.bind("<B1-Motion>", self._resize)
            grip.bind("<ButtonRelease-1>", self._stop_resize)
            self._resize_grips[edge] = grip

    def _on_window_configure(self, event: tk.Event[tk.Misc]) -> None:
        del event
        for grip in self._resize_grips.values():
            grip.lift()


@dataclass(slots=True)
class GameVisionClient:
    config: GameVisionClientConfig = field(default_factory=GameVisionClientConfig)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)
    _ui_queue: queue.SimpleQueue = field(default_factory=queue.SimpleQueue, init=False)
    _overlay: DraggableOverlayWindow | None = field(default=None, init=False)
    _root: tk.Tk | None = field(default=None, init=False)
    _last_detected_pid: int | None = field(default=None, init=False)
    _last_status_text: str = field(default="等待检测游戏进程...", init=False)
    _overlay_hidden: bool = field(default=False, init=False)
    _hotkey_handle: object | None = field(default=None, init=False)
    _monitor_phase: str = field(default="gpu", init=False)
    _walkthrough_queue: queue.SimpleQueue = field(default_factory=queue.SimpleQueue, init=False)
    _walkthrough_worker_started: bool = field(default=False, init=False)
    _walkthrough_seen_processes: set[tuple[str, int]] = field(default_factory=set, init=False)
    _walkthrough_pending_count: int = field(default=0, init=False)
    _walkthrough_synced_count: int = field(default=0, init=False)
    _walkthrough_failed_count: int = field(default=0, init=False)
    _walkthrough_last_message: str = field(default="", init=False)
    _walkthrough_progress_text: str = field(default="", init=False)
    _overlay_main_text: str = field(default="", init=False)
    _walkthrough_query_client: WalkthroughServiceImporter | None = field(default=None, init=False)
    _walkthrough_downloader: GamerskyWalkthroughDownloader | None = field(default=None, init=False)
    _walkthrough_identity_by_process: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    _walkthrough_pending_processes: set[str] = field(default_factory=set, init=False)
    _walkthrough_ready_instances: set[str] = field(default_factory=set, init=False)
    _walkthrough_scene_map_by_instance: dict[str, Path] = field(default_factory=dict, init=False)
    _walkthrough_scene_map_cache_by_instance: dict[str, tuple[Path, float, dict[str, object]]] = field(default_factory=dict, init=False)
    _walkthrough_last_bootstrap_at: dict[str, float] = field(default_factory=dict, init=False)
    _walkthrough_bootstrap_started_processes: set[str] = field(default_factory=set, init=False)
    _walkthrough_state_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _walkthrough_log_file_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _overlay_last_image_bytes_list: list[bytes] = field(default_factory=list, init=False)
    _walkthrough_scene_hit_streak: int = field(default=0, init=False)
    _walkthrough_last_scene_hit_at: float = field(default=0.0, init=False)
    _walkthrough_overlay_active: bool = field(default=False, init=False)
    _walkthrough_overlay_scene_key: tuple[str, str] | None = field(default=None, init=False)
    _walkthrough_query_miss_logged_since_last_hit: bool = field(default=False, init=False)
    _walkthrough_query_frame_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _walkthrough_query_inflight: bool = field(default=False, init=False)
    _walkthrough_latest_query_frame: dict[str, object] | None = field(default=None, init=False)
    _debug_screenshot_queue: queue.SimpleQueue = field(default_factory=queue.SimpleQueue, init=False)
    _debug_screenshot_worker_started: bool = field(default=False, init=False)
    _toast_window: tk.Toplevel | None = field(default=None, init=False)
    _toast_hide_after_id: str | None = field(default=None, init=False)
    _toast_anim_after_id: str | None = field(default=None, init=False)
    _last_external_window_snapshot: tuple[tuple[int, int, int, int], str] | None = field(default=None, init=False)

    def run_forever(self) -> None:
        self._ensure_runtime_dependencies()
        self._start_debug_screenshot_worker_if_needed()
        root = tk.Tk()
        root.withdraw()
        root.title("Game Vision")
        root.report_callback_exception = self._report_tk_exception
        self._root = root
        self._overlay = DraggableOverlayWindow(
            root,
            width=self.config.overlay_width,
            height=self.config.overlay_height,
            margin=self.config.overlay_margin,
            title=self.config.overlay_title,
            alpha=self.config.overlay_alpha,
            debug_details=bool(self.config.walkthrough_display_debug_details),
        )
        self._overlay_main_text = "等待检测游戏进程...\n\n检测到符合条件的游戏后，会每秒自动截图并分析。"
        self._overlay.replace_text(self._compose_overlay_body())
        self._overlay.set_status(f"待机(GPU监测) | {self.config.toggle_hotkey} 切换")

        root.protocol("WM_DELETE_WINDOW", self.stop)
        self._start_walkthrough_worker_if_needed()
        self._register_global_hotkey()
        root.after(40, self._pump_ui_queue)
        threading.Thread(target=self._game_loop_with_async_walkthrough, name="game-vision-loop", daemon=True).start()
        try:
            root.mainloop()
        finally:
            self._unregister_global_hotkey()
            if self._walkthrough_query_client is not None:
                self._walkthrough_query_client.close()

    def stop(self) -> None:
        self._stop_event.set()
        self._unregister_global_hotkey()
        root = self._root
        if root is None:
            return

        def _close_ui() -> None:
            overlay = self._overlay
            self._overlay = None
            self._root = None
            if overlay is not None:
                with contextlib.suppress(Exception):
                    overlay.window.destroy()
            with contextlib.suppress(Exception):
                root.destroy()

        self._ui_queue.put(_close_ui)

    def _shutdown_due_to_process_exit(self, process_name: str, *, reason: str) -> None:
        self._log_walkthrough_message(
            f"[walkthrough] process exit trigger process={process_name} reason={reason}"
        )
        self._handle_detected_process_exit(process_name, reason=reason)
        self.stop()

    def _handle_detected_process_exit(self, process_name: str, *, reason: str = "unknown") -> None:
        countdown_seconds = 5
        message = f"检测到进程已退出: {process_name}，原因: {reason}，程序将在 {countdown_seconds} 秒后退出。"
        self._log_walkthrough_message(f"[walkthrough] {message}")
        for remaining in range(countdown_seconds, 0, -1):
            self._ui_queue.put(
                lambda value=process_name, seconds=remaining, reason_text=reason: self._update_overlay(
                    title=self.config.overlay_title,
                    status="进程已退出",
                    text=(
                        f"检测到进程已退出: {value}\n"
                        f"退出原因: {reason_text}\n"
                        f"程序将在 {seconds} 秒后退出。"
                    ),
                    replace=True,
                )
            )
            if remaining < countdown_seconds:
                self._log_walkthrough_message(
                    f"[walkthrough] process exited: {process_name}, reason={reason}, shutdown in {remaining} second(s)"
                )
            if self._stop_event.wait(1.0):
                return
        self._log_walkthrough_message(
            f"[walkthrough] process exited: {process_name}, reason={reason}, shutting down now"
        )

    def _pump_ui_queue(self) -> None:
        if self._root is None:
            return
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            callback()
        if not self._stop_event.is_set():
            self._root.after(40, self._pump_ui_queue)

    def _game_loop_with_async_walkthrough(self) -> None:
        # Step 1: if walkthrough_game_name is explicitly set, skip process detection.
        process_name: str = ""
        game_name: str = ""
        configured_game_name = (
            self.config.walkthrough_game_name.strip()
            if isinstance(self.config.walkthrough_game_name, str)
            else ""
        )
        if configured_game_name:
            game_name = configured_game_name
            process_name = configured_game_name
            self._ui_queue.put(
                lambda value=configured_game_name: self._update_overlay(
                    title=self.config.overlay_title,
                    status="直连识别",
                    text=(
                        f"已指定 walkthrough_game_name: {value}\n"
                        "跳过进程检测，直接对当前聚焦窗口进行场景识别。"
                    ),
                    replace=True,
                )
            )
        else:
            # Keep polling wait_for_game_process every 3 seconds until name is available.
            while not self._stop_event.is_set():
                try:
                    result = wait_for_game_process(
                        three_d_threshold=self.config.three_d_threshold,
                        decoder_threshold=self.config.decoder_threshold,
                        encoder_threshold=self.config.encoder_threshold,
                        phys_index=self.config.phys_index,
                        sample_interval_seconds=max(0.01, float(self.config.poll_interval_seconds)),
                        detected_processes_file=Path(__file__).resolve().parent.parent / "detected_processes.json",
                    )
                except Exception as exc:
                    self._log_exception("wait_for_game_process failed", exc)
                    self._ui_queue.put(
                        lambda value=str(exc): self._update_overlay(
                            title=self.config.overlay_title,
                            status="检测异常",
                            text=f"wait_for_game_process 异常: {value}\n3秒后重试...",
                            replace=True,
                        )
                    )
                    if self._stop_event.wait(3.0):
                        return
                    continue
                process_name = str(result.get("process") or "").strip()
                game_name = str(result.get("name") or "").strip()
                if game_name:
                    break

                waiting_text = (
                    f"已检测到进程: {process_name}，但未解析到游戏名(name为空)。\n"
                    "3秒后重试 wait_for_game_process..."
                    if process_name
                    else "等待检测游戏进程并解析游戏名...\n3秒后重试 wait_for_game_process..."
                )
                self._ui_queue.put(
                    lambda value=waiting_text: self._update_overlay(
                        title=self.config.overlay_title,
                        status="等待游戏名",
                        text=value,
                        replace=True,
                    )
                )
                if self._stop_event.wait(3.0):
                    return

        if self._stop_event.is_set():
            return

        if (not configured_game_name) and process_name and (not self._is_process_name_alive(process_name)):
            self._shutdown_due_to_process_exit(process_name, reason="pre_loop_name_gone")
            return

        instance_id = game_name
        output_root = Path(self.config.walkthrough_download_dir).expanduser()
        if not output_root.is_absolute():
            output_root = _SCRIPT_DIR / output_root
        output_root = output_root.resolve()
        json_path = output_root / self._safe_game_dir_name(game_name) / "text_images.json"
        # 通过服务端实例列表判断攻略是否存在，不依赖本地磁盘文件。
        walkthrough_exists = self._vision_instance_exists(instance_id)

        if walkthrough_exists:
            # 直接进入截屏查询，后台线程更新攻略
            resolved_scene_map_path = self._resolve_scene_text_map_for_instance(instance_id)
            if resolved_scene_map_path is not None:
                self._walkthrough_scene_map_by_instance[instance_id] = resolved_scene_map_path
            self._walkthrough_ready_instances.add(instance_id)
            def _notify_walkthrough_update():
                self._ui_queue.put(
                    lambda value=game_name, instance=instance_id: self._notify_walkthrough_updated(
                        game_name=value,
                        instance_id=instance,
                    )
                )
            def _background_update():
                try:
                    downloader = GamerskyWalkthroughDownloader(
                        base_output_dir=output_root,
                        timeout=max(1, int(self.config.walkthrough_timeout_seconds)),
                        progress_callback=None,
                    )
                    downloader.download_walkthrough(game_name)
                    json_path2 = output_root / self._safe_game_dir_name(game_name) / "text_images.json"
                    importer = self._get_walkthrough_query_client()
                    import_summary = importer.sync_from_json(instance_id=instance_id, json_file_path=json_path2)
                    scene_map_path2 = self._resolve_imported_scene_text_map_path(
                        instance_id=instance_id,
                        preferred_path=str(getattr(import_summary, "scene_text_map_file", "") or "").strip(),
                        json_path=json_path2,
                    )
                    if scene_map_path2 is not None:
                        self._walkthrough_scene_map_by_instance[instance_id] = scene_map_path2
                        self._walkthrough_ready_instances.add(instance_id)
                    _notify_walkthrough_update()
                except Exception as exc:
                    self._log_exception(f"walkthrough async update failed game={game_name}", exc)
            threading.Thread(target=_background_update, name="walkthrough-bg-update", daemon=True).start()
        else:
            # 没有攻略，按原有流程下载并导入
            try:
                json_path = self._download_walkthrough_with_overlay(game_name)
            except Exception as exc:
                self._log_exception(f"walkthrough download failed game={game_name}", exc)
                self._ui_queue.put(
                    lambda value=str(exc): self._update_overlay(
                        title=self.config.overlay_title,
                        status="下载失败(继续运行)",
                        text=(
                            f"下载攻略失败: {value}\n"
                            "将继续执行截屏查询流程（可能命中率受影响）。"
                        ),
                        replace=True,
                    )
                )
            if json_path is not None and json_path.exists():
                try:
                    import_summary = self._import_walkthrough_with_overlay(instance_id=instance_id, json_path=json_path)
                    scene_map_path = self._resolve_imported_scene_text_map_path(
                        instance_id=instance_id,
                        preferred_path=str(getattr(import_summary, "scene_text_map_file", "") or "").strip(),
                        json_path=json_path,
                    )
                    if scene_map_path is not None:
                        self._walkthrough_scene_map_by_instance[instance_id] = scene_map_path
                    self._walkthrough_ready_instances.add(instance_id)
                    self._ui_queue.put(
                        lambda value=game_name: self._update_overlay(
                            title=f"{self.config.overlay_title} | {value}",
                            status="攻略已就绪",
                            text=(
                                f"游戏: {value}\n实例: {instance_id}\n"
                                f"文本导入: {import_summary.texts_inserted} (缓存 {import_summary.texts_skipped})\n"
                                f"场景导入: {import_summary.vision_scenes_inserted} (缓存 {import_summary.vision_scenes_skipped})\n\n"
                                "开始截屏查询场景..."
                            ),
                            replace=True,
                        )
                    )
                except Exception as exc:
                    self._log_exception(f"walkthrough import failed instance={instance_id}", exc)
                    self._ui_queue.put(
                        lambda value=str(exc): self._update_overlay(
                            title=self.config.overlay_title,
                            status="导入失败(继续运行)",
                            text=(
                                f"导入攻略失败: {value}\n"
                                "将继续执行截屏查询流程（可能命中率受影响）。"
                            ),
                            replace=True,
                        )
                    )
            else:
                self._ui_queue.put(
                    lambda value=game_name: self._update_overlay(
                        title=f"{self.config.overlay_title} | {value}",
                        status="无攻略运行",
                        text=(
                            f"游戏: {value}\n实例: {instance_id}\n"
                            "下载攻略失败，已跳过导入。\n"
                            "继续执行截屏查询流程。"
                        ),
                        replace=True,
                    )
                )

        # Step 4: screenshot query loop.
        if configured_game_name:
            focused_usage = ProcessGpuUsage(
                pid=0,
                name=configured_game_name,
                phys_indexes=(),
                three_d=0.0,
                decoder=0.0,
                encoder=0.0,
            )
            self._show_scene_recognizing_overlay(configured_game_name)
            last_focused_window_title = ""
            while not self._stop_event.is_set():
                focused_window = self._get_focused_window_snapshot()
                if focused_window is None:
                    if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                        return
                    continue

                bbox, window_title = focused_window
                if window_title != last_focused_window_title:
                    last_focused_window_title = window_title
                image_base64 = self._capture_window_base64(bbox)
                if not image_base64:
                    if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                        return
                    continue

                image_bytes = base64.b64decode(image_base64)
                hint = self._query_walkthrough_hint(image_bytes, instance_id=instance_id)
                if bool(hint.get("hit")):
                    scene_id = str(hint.get("scene_id") or "").strip()
                    scene_text = str(hint.get("answer") or "").strip()
                    if scene_id and scene_text:
                        self._append_detected_scene(scene_id=scene_id, text=scene_text)

                self._handle_walkthrough_hint_result(
                    usage=focused_usage,
                    window_title=window_title,
                    instance_id=instance_id,
                    hint=hint,
                    now=time.monotonic(),
                    hold_seconds=max(0.0, float(self.config.walkthrough_overlay_hold_seconds)),
                    required_hits=max(1, int(self.config.walkthrough_confirm_hit_count)),
                )

                if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                    return

        # Process-based screenshot query loop. Exit the whole program if process exits.
        normalized_process_name = self._normalize_process_name(process_name)
        active_pid: int | None = None
        self._show_scene_recognizing_overlay(process_name)
        while not self._stop_event.is_set():
            if active_pid is not None and not self._is_pid_alive(active_pid):
                self._shutdown_due_to_process_exit(process_name, reason="query_loop_pid_gone")
                return

            if normalized_process_name and not self._is_process_name_alive(process_name):
                self._shutdown_due_to_process_exit(process_name, reason="query_loop_name_gone")
                return

            usage = self._find_usage_by_process_name(normalized_process_name) if normalized_process_name else None
            if usage is None:
                # 如果无法再按进程名定位到对应 PID，且名称也不存活，则认为游戏已退出。
                if normalized_process_name and not self._is_process_name_alive(process_name):
                    self._shutdown_due_to_process_exit(process_name, reason="usage_missing_name_gone")
                    return
                if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                    return
                continue
            active_pid = int(usage.pid)

            window = get_window_bounds_for_pid(usage.pid)
            if window is None:
                if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                    return
                continue

            image_base64 = self._capture_window_base64(window.bbox)
            if not image_base64:
                if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                    return
                continue

            image_bytes = base64.b64decode(image_base64)
            hint = self._query_walkthrough_hint(image_bytes, instance_id=instance_id)
            if bool(hint.get("hit")):
                scene_id = str(hint.get("scene_id") or "").strip()
                scene_text = str(hint.get("answer") or "").strip()
                if scene_id and scene_text:
                    self._append_detected_scene(scene_id=scene_id, text=scene_text)

            self._handle_walkthrough_hint_result(
                usage=usage,
                window_title=window.title or "未见",
                instance_id=instance_id,
                hint=hint,
                now=time.monotonic(),
                hold_seconds=max(0.0, float(self.config.walkthrough_overlay_hold_seconds)),
                required_hits=max(1, int(self.config.walkthrough_confirm_hit_count)),
            )

            if self._stop_event.wait(max(0.2, self._resolve_loop_interval_seconds(locked=True))):
                return

    def _is_process_name_alive(self, process_name: str) -> bool:
        normalized_target = self._normalize_process_name(process_name)
        if not normalized_target:
            return False
        try:
            names = list_process_names()
        except OSError:
            return False
        for current_name in names.values():
            if self._normalize_process_name(current_name) == normalized_target:
                return True
        return False

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            names = list_process_names()
        except OSError:
            return False
        return int(pid) in names

    def _download_walkthrough_with_overlay(self, game_name: str) -> Path:
        output_root = Path(self.config.walkthrough_download_dir).expanduser()
        if not output_root.is_absolute():
            output_root = _SCRIPT_DIR / output_root
        output_root = output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        self.config.walkthrough_download_dir = output_root.as_posix()

        self._ui_queue.put(
            lambda value=game_name, target=output_root.as_posix(): self._update_overlay(
                title=f"{self.config.overlay_title} | {value}",
                status="下载攻略中",
                text=(
                    f"游戏: {value}\n"
                    f"下载目录: {target}\n\n"
                    "正在下载攻略，请稍候..."
                ),
                replace=True,
            )
        )

        def on_progress(message: str) -> None:
            self._set_walkthrough_progress(
                process_name=game_name,
                status="下载攻略中",
                detail=message,
            )

        downloader = GamerskyWalkthroughDownloader(
            base_output_dir=output_root,
            timeout=max(1, int(self.config.walkthrough_timeout_seconds)),
            progress_callback=on_progress,
        )
        downloader.download_walkthrough(game_name)
        json_path = output_root / self._safe_game_dir_name(game_name) / "text_images.json"
        if not json_path.exists():
            raise RuntimeError(f"下载后未找到 text_images.json: {json_path}")
        return json_path

    def _import_walkthrough_with_overlay(self, *, instance_id: str, json_path: Path):
        self._set_walkthrough_progress(
            process_name=instance_id,
            status="导入攻略中",
            detail=f"实例: {instance_id}\nJSON: {json_path.as_posix()}",
        )

        def on_progress(line: str) -> None:
            text = line.strip()
            if not text:
                return
            self._set_walkthrough_progress(
                process_name=instance_id,
                status="导入攻略中",
                detail=text,
            )

        class _ProgressStream:
            def __init__(self, callback) -> None:
                self._callback = callback
                self._buffer = ""

            def write(self, value: str) -> int:
                if not isinstance(value, str) or not value:
                    return 0
                merged = value.replace("\r", "\n")
                self._buffer += merged
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    if line.strip():
                        self._callback(line)
                return len(value)

            def flush(self) -> None:
                if self._buffer.strip():
                    self._callback(self._buffer)
                self._buffer = ""

        importer = self._get_walkthrough_query_client()
        stream = _ProgressStream(on_progress)
        with contextlib.redirect_stdout(stream):
            summary = importer.sync_from_json(instance_id=instance_id, json_file_path=json_path)
        stream.flush()
        return summary

    def _append_detected_scene(self, *, scene_id: str, text: str) -> None:
        from datetime import datetime, timezone
        output_path = Path(self.config.detected_scene_file).expanduser()
        payload: list[dict[str, str]]
        try:
            raw = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else []
            payload = raw if isinstance(raw, list) else []
        except Exception:
            payload = []

        now = datetime.now(timezone.utc).astimezone()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f %z")
        payload.append(
            {
                "scene_id": scene_id,
                "text": text,
                "timestamp": timestamp,
            }
        )
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _resolve_loop_interval_seconds(self, *, locked: bool) -> float:
        if not locked:
            return max(0.01, float(self.config.poll_interval_seconds))
        configured = self.config.walkthrough_screenshot_interval_seconds
        if configured is None:
            configured = self.config.analysis_interval_seconds
        return max(0.01, float(configured))

    def _normalize_process_name(self, value: str | None) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized.endswith(".exe"):
            normalized = normalized[:-4]
        return normalized or None

    def _find_usage_by_process_name(self, normalized_name: str) -> ProcessGpuUsage | None:
        try:
            process_names = list_process_names()
        except OSError:
            return None
        matching_pids = [
            pid
            for pid, name in process_names.items()
            if isinstance(name, str) and self._normalize_process_name(name) == normalized_name
        ]
        if not matching_pids:
            return None
        preferred_pid = next((pid for pid in matching_pids if get_window_bounds_for_pid(pid) is not None), matching_pids[0])
        display_name = process_names.get(preferred_pid) or normalized_name
        return ProcessGpuUsage(
            pid=preferred_pid,
            name=display_name,
            phys_indexes=(),
            three_d=0.0,
            decoder=0.0,
            encoder=0.0,
        )

    def _is_process_still_alive(self, usage: ProcessGpuUsage) -> bool:
        try:
            names = list_process_names()
        except OSError:
            return False
        current_name = names.get(usage.pid)
        return (
            isinstance(current_name, str)
            and self._normalize_process_name(current_name) == self._normalize_process_name(usage.name)
        )

    def _handle_no_game(self, reader: GpuEngineCounterReader) -> None:
        candidates = get_top_game_candidates(
            reader,
            three_d_threshold=self.config.three_d_threshold,
            decoder_threshold=self.config.decoder_threshold,
            phys_index=self.config.phys_index,
            encoder_threshold=self.config.encoder_threshold,
            limit=3,
        )
        lines = ["等待检测游戏进程..."]
        if candidates:
            lines.append("")
            lines.append("当前最接近游戏特征的进程:")
            for item in candidates:
                lines.append(f"- {item.name} pid={item.pid} 3D={item.three_d:.1f}% Decode={item.decoder:.1f}%")
        text = "\n".join(lines)
        if text == self._last_status_text:
            return
        self._last_status_text = text
        self._last_detected_pid = None
        self._ui_queue.put(lambda value=text: self._update_overlay(title=self.config.overlay_title, status="待机", text=value, replace=True))

    def _handle_no_named_process(self, target_process_name: str) -> None:
        text = f"等待进程名匹配: {target_process_name}\n\n检测到该进程后将直接开始截图分析，不依赖 GPU 阈值。"
        if text == self._last_status_text:
            return
        self._last_status_text = text
        self._last_detected_pid = None
        self._ui_queue.put(
            lambda value=text: self._update_overlay(
                title=self.config.overlay_title,
                status="待机(进程名监测)",
                text=value,
                replace=True,
            )
        )

    def _handle_no_hybrid_match(self, reader: GpuEngineCounterReader, target_process_name: str) -> None:
        candidates = get_top_game_candidates(
            reader,
            three_d_threshold=self.config.three_d_threshold,
            decoder_threshold=self.config.decoder_threshold,
            phys_index=self.config.phys_index,
            encoder_threshold=self.config.encoder_threshold,
            limit=3,
        )
        lines = [
            f"等待进程名匹配: {target_process_name}",
            "",
            "混合监测模式已开启: 先按进程名查找，找不到时参考 GPU 候选。",
        ]
        if candidates:
            lines.append("")
            lines.append("当前 GPU 候选进程:")
            for item in candidates:
                lines.append(f"- {item.name} pid={item.pid} 3D={item.three_d:.1f}% Decode={item.decoder:.1f}%")
        text = "\n".join(lines)
        if text == self._last_status_text:
            return
        self._last_status_text = text
        self._last_detected_pid = None
        self._ui_queue.put(
            lambda value=text: self._update_overlay(
                title=self.config.overlay_title,
                status="待机(混合监测)",
                text=value,
                replace=True,
            )
        )

    def _analyze_game_frame(self, usage: ProcessGpuUsage) -> None:
        now = time.monotonic()
        hold_seconds = max(0.0, float(self.config.walkthrough_overlay_hold_seconds))
        required_hits = max(1, int(self.config.walkthrough_confirm_hit_count))
        window = get_window_bounds_for_pid(usage.pid)
        if window is None:
            self._clear_pending_walkthrough_query_frame()
            self._reset_walkthrough_scene_hit_streak()
            text = f"已检测到游戏进程 {usage.name} (pid={usage.pid})，但暂时没有找到可截图的顶层窗口。"
            if self._should_keep_walkthrough_overlay(now=now, hold_seconds=hold_seconds):
                return
            if text == self._last_status_text:
                return
            self._last_status_text = text
            self._ui_queue.put(lambda value=text: self._update_overlay(title=f"{self.config.overlay_title} | {usage.name}", status="窗口缺失", text=value, replace=True))
            return
        image_base64 = self._capture_window_base64(window.bbox)
        if not image_base64:
            return
        image_bytes = base64.b64decode(image_base64)
        self._enqueue_debug_screenshot(image_bytes)
        instance_id = self._ensure_walkthrough_instance_for_usage(usage)
        if not instance_id:
            self._clear_pending_walkthrough_query_frame()
            self._reset_walkthrough_scene_hit_streak()
            waiting_text = (
                f"已检测到游戏进程 {usage.name} (pid={usage.pid})，截图功能已启动。\n"
                "攻略实例尚未就绪，等待自动下载/导入完成后再进行匹配。"
            )
            if self._should_keep_walkthrough_overlay(now=now, hold_seconds=hold_seconds):
                return
            if waiting_text != self._last_status_text:
                self._last_status_text = waiting_text
                self._ui_queue.put(
                    lambda value=waiting_text: self._update_overlay(
                        title=f"{self.config.overlay_title} | {usage.name}",
                        status="截图已启动",
                        text=value,
                        replace=True,
                    )
                )
            return
        if self._use_latest_frame_query_mode():
            self._enqueue_latest_walkthrough_query_frame(
                usage=usage,
                window_title=window.title or "未见",
                image_bytes=image_bytes,
                instance_id=instance_id,
                hold_seconds=hold_seconds,
                required_hits=required_hits,
            )
            return

        hint = self._query_walkthrough_hint(image_bytes, instance_id=instance_id)
        self._handle_walkthrough_hint_result(
            usage=usage,
            window_title=window.title or "未见",
            instance_id=instance_id,
            hint=hint,
            now=now,
            hold_seconds=hold_seconds,
            required_hits=required_hits,
        )

    def _handle_walkthrough_hint_result(
        self,
        *,
        usage: ProcessGpuUsage,
        window_title: str,
        instance_id: str,
        hint: dict[str, object],
        now: float,
        hold_seconds: float,
        required_hits: int,
    ) -> None:
        if not bool(hint.get("hit")):
            self._reset_walkthrough_scene_hit_streak()
            self._handle_walkthrough_query_miss(usage, instance_id=instance_id, hint=hint)
            self._show_scene_recognizing_overlay(
                usage.name,
                now=now,
                hold_seconds=hold_seconds,
            )
            return
        # A successful hit resets miss-log throttling, so the next miss can be logged once.
        self._walkthrough_query_miss_logged_since_last_hit = False
        score = float(hint.get("score") or 0.0)
        score_threshold = max(0.0, min(1.0, float(self.config.walkthrough_match_score_threshold)))
        if score < score_threshold:
            self._reset_walkthrough_scene_hit_streak()
            self._show_scene_recognizing_overlay(
                usage.name,
                now=now,
                hold_seconds=hold_seconds,
            )
            return
        answer = str(hint.get("answer") or "").strip()
        if not answer:
            self._reset_walkthrough_scene_hit_streak()
            self._show_scene_recognizing_overlay(
                usage.name,
                now=now,
                hold_seconds=hold_seconds,
            )
            return
        self._walkthrough_last_scene_hit_at = now
        self._walkthrough_scene_hit_streak += 1
        should_render_walkthrough = self._walkthrough_overlay_active or self._walkthrough_scene_hit_streak >= required_hits
        if not should_render_walkthrough:
            self._show_scene_recognizing_overlay(
                usage.name,
                now=now,
                hold_seconds=hold_seconds,
            )
            return
        self._walkthrough_overlay_active = True
        scene_id = str(hint.get("scene_id") or "未知")
        scene_key = (instance_id, scene_id)
        # Same scene in active overlay: skip full redraw to avoid image flicker.
        if self._walkthrough_overlay_scene_key == scene_key:
            return

        top_image_bytes_list = self._load_scene_image_bytes_list(hint)

        source = str(hint.get("source") or "").strip() or "游民星空"
        url = str(hint.get("url") or "").strip()
        url_text = url if url else "未提供"
        self._last_detected_pid = usage.pid
        self._last_status_text = ""
        text = self._build_walkthrough_overlay_text(
            answer=answer,
            source=source,
            url=url_text,
            usage=usage,
            window_title=window_title,
            score=score,
            scene_id=scene_id,
        )
        title = f"{self.config.overlay_title} | {usage.name}"
        status = "已更新" if self.config.walkthrough_display_debug_details else "攻略"
        self._walkthrough_overlay_scene_key = scene_key
        self._ui_queue.put(
            lambda value=text, image_bytes_list=top_image_bytes_list: self._update_overlay(
                title=title,
                status=status,
                text=value,
                replace=True,
                image_bytes_list=image_bytes_list,
                fit_content_height=True,
            )
        )

    def _build_walkthrough_overlay_text(
        self,
        *,
        answer: str,
        source: str,
        url: str,
        usage: ProcessGpuUsage,
        window_title: str,
        score: float,
        scene_id: str,
    ) -> str:
        if not self.config.walkthrough_display_debug_details:
            return (
                f"出处: {source}\n\n"
                f"URL: {url}\n\n"
                f"攻略:\n{answer}"
            )
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        return (
            f"时间: {timestamp}\n"
            f"进程: {usage.name} (pid={usage.pid})\n"
            f"窗口: {window_title or '未见'}\n"
            f"场景ID: {scene_id}\n"
            f"匹配分数: {score:.3f}\n"
            f"出处: {source}\n\n"
            f"URL: {url}\n\n"
            f"攻略:\n{answer}"
        )

    def _use_latest_frame_query_mode(self) -> bool:
        return self.config.walkthrough_screenshot_interval_seconds is not None

    def _enqueue_latest_walkthrough_query_frame(
        self,
        *,
        usage: ProcessGpuUsage,
        window_title: str,
        image_bytes: bytes,
        instance_id: str,
        hold_seconds: float,
        required_hits: int,
    ) -> None:
        frame = {
            "usage": usage,
            "window_title": window_title,
            "image_bytes": image_bytes,
            "instance_id": instance_id,
            "hold_seconds": hold_seconds,
            "required_hits": required_hits,
        }
        should_start_worker = False
        with self._walkthrough_query_frame_lock:
            self._walkthrough_latest_query_frame = frame
            if not self._walkthrough_query_inflight:
                self._walkthrough_query_inflight = True
                should_start_worker = True
        if not should_start_worker:
            return
        threading.Thread(
            target=self._walkthrough_latest_query_worker_loop,
            name="game-walkthrough-query-worker",
            daemon=True,
        ).start()

    def _walkthrough_latest_query_worker_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._walkthrough_query_frame_lock:
                frame = self._walkthrough_latest_query_frame
                self._walkthrough_latest_query_frame = None
            if not isinstance(frame, dict):
                with self._walkthrough_query_frame_lock:
                    self._walkthrough_query_inflight = False
                return

            usage = frame.get("usage")
            if not isinstance(usage, ProcessGpuUsage):
                continue
            window_title = str(frame.get("window_title") or "未见")
            image_bytes = frame.get("image_bytes")
            if not isinstance(image_bytes, (bytes, bytearray)):
                continue
            instance_id = str(frame.get("instance_id") or "").strip()
            if not instance_id:
                continue
            hold_seconds = max(0.0, float(frame.get("hold_seconds") or 0.0))
            required_hits = max(1, int(frame.get("required_hits") or 1))

            hint = self._query_walkthrough_hint(bytes(image_bytes), instance_id=instance_id)
            self._handle_walkthrough_hint_result(
                usage=usage,
                window_title=window_title,
                instance_id=instance_id,
                hint=hint,
                now=time.monotonic(),
                hold_seconds=hold_seconds,
                required_hits=required_hits,
            )

    def _clear_pending_walkthrough_query_frame(self) -> None:
        with self._walkthrough_query_frame_lock:
            self._walkthrough_latest_query_frame = None

    def _reset_walkthrough_scene_hit_streak(self) -> None:
        self._walkthrough_scene_hit_streak = 0

    def _should_keep_walkthrough_overlay(self, *, now: float, hold_seconds: float) -> bool:
        if not self._walkthrough_overlay_active:
            return False
        if self._walkthrough_last_scene_hit_at <= 0:
            self._walkthrough_overlay_active = False
            self._walkthrough_overlay_scene_key = None
            return False
        if now - self._walkthrough_last_scene_hit_at <= hold_seconds:
            return True
        self._walkthrough_overlay_active = False
        self._walkthrough_overlay_scene_key = None
        self._overlay_last_image_bytes_list = []
        return False

    def _query_walkthrough_hint(self, image_bytes: bytes, *, instance_id: str) -> dict[str, object]:
        if not instance_id.strip():
            return {"hit": False, "reason": "missing_instance_id"}
        client = self._get_walkthrough_query_client()
        temp_path = self._write_temp_query_image(image_bytes)
        try:
            hits = client.query_vision(
                instance_id=instance_id,
                image_path=temp_path,
                topk=max(1, self.config.walkthrough_query_topk),
                threshold=max(0.0, min(1.0, self.config.walkthrough_query_threshold)),
                threshold_2=max(0.0, min(1.0, self.config.walkthrough_query_threshold_2)),
            )
        except Exception as exc:
            self._log_walkthrough_message(f"[walkthrough] vision_query_failed instance={instance_id} error={exc}")
            return {"hit": False, "reason": "vision_query_failed"}
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        if not hits:
            return {"hit": False, "reason": "vision_no_hit"}
        top = hits[0]
        scene_id = str(top.scene_id or "").strip()
        if not scene_id:
            return {"hit": False, "reason": "vision_top1_missing_scene_id"}
        scene_entry = self._load_scene_entry(instance_id=instance_id, scene_id=scene_id)
        if scene_entry is None:
            return {"hit": False, "reason": "scene_text_map_missing"}
        answer = str(scene_entry.get("text") or "").strip()
        if not answer:
            return {"hit": False, "reason": "scene_top1_empty_text"}
        source = str(scene_entry.get("source") or "").strip() or "游民星空GamerSky"
        return {
            "hit": True,
            "score": float(top.score),
            "scene_id": scene_id,
            "picture_id": str(top.picture_id or "").strip(),
            "answer": answer,
            "url": str(scene_entry.get("url") or "").strip(),
            "source": source,
            "image_refs": list(scene_entry.get("images") or []),
            "reason": "ok",
        }

    def _load_scene_entry(self, *, instance_id: str, scene_id: str) -> dict[str, object] | None:
        payload = self._load_scene_text_map_payload(instance_id)
        if payload is None:
            return None
        answer = ""
        url = ""
        scene_id_to_text = payload.get("scene_id_to_text")
        if isinstance(scene_id_to_text, dict):
            answer = str(scene_id_to_text.get(scene_id) or "").strip()
        image_refs: list[str] = []
        scenes = payload.get("scenes")
        if isinstance(scenes, list):
            for item in scenes:
                if not isinstance(item, dict):
                    continue
                if str(item.get("scene_id") or "").strip() != scene_id:
                    continue
                if not answer:
                    answer = str(item.get("text") or "").strip()
                url = str(item.get("url") or "").strip()
                images_value = item.get("images")
                if isinstance(images_value, list):
                    image_refs = [str(value).strip() for value in images_value if str(value).strip()]
                break
        return {"text": answer, "images": image_refs, "url": url, "source": "游民星空"}

    def _load_scene_text_map_payload(self, instance_id: str) -> dict[str, object] | None:
        scene_map_path = self._resolve_scene_text_map_for_instance(instance_id)
        if scene_map_path is None:
            return None
        try:
            mtime = scene_map_path.stat().st_mtime
        except OSError:
            return None
        cached = self._walkthrough_scene_map_cache_by_instance.get(instance_id)
        if cached is not None:
            cached_path, cached_mtime, cached_payload = cached
            if cached_path == scene_map_path and cached_mtime == mtime:
                return cached_payload
        try:
            payload = json.loads(scene_map_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log_walkthrough_message(
                f"[walkthrough] scene_text_map_read_failed instance={instance_id} path={scene_map_path} error={exc}"
            )
            return None
        if not isinstance(payload, dict):
            return None
        self._walkthrough_scene_map_cache_by_instance[instance_id] = (scene_map_path, mtime, payload)
        return payload

    def _resolve_scene_text_map_for_instance(self, instance_id: str) -> Path | None:
        scene_map_path = self._walkthrough_scene_map_by_instance.get(instance_id)
        if scene_map_path is not None and scene_map_path.exists():
            return scene_map_path
        candidate_roots = [
            self._walkthrough_download_root(),
            self._walkthrough_data_root(),
        ]
        for root in candidate_roots:
            if not root.exists():
                continue
            for candidate in root.glob("*/scene_text_map.json"):
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("instance_id") or "").strip() != instance_id:
                    continue
                self._walkthrough_scene_map_by_instance[instance_id] = candidate
                return candidate
        return None

    def _load_scene_image_bytes_list(self, hint: dict[str, object]) -> list[bytes]:
        raw_refs = hint.get("image_refs")
        if not isinstance(raw_refs, list):
            return []
        image_bytes_list: list[bytes] = []
        max_images = max(1, int(self.config.walkthrough_max_images_per_guide))
        for raw_ref in raw_refs:
            image_ref = str(raw_ref).strip()
            if not image_ref:
                continue
            image_path = self._resolve_walkthrough_image_path(image_ref)
            if image_path is None:
                continue
            try:
                image_bytes_list.append(image_path.read_bytes())
            except Exception:
                continue
            if len(image_bytes_list) >= max_images:
                break
        return image_bytes_list

    def _resolve_walkthrough_image_path(self, image_ref: str) -> Path | None:
        raw = image_ref.replace("\\", "/")
        ref_path = Path(raw)
        if ref_path.is_absolute() and ref_path.exists():
            return ref_path

        download_root = self._walkthrough_download_root()
        candidates: list[Path] = []
        candidates.append(ref_path)
        candidates.append(download_root / ref_path)
        if raw.startswith("images/"):
            for game_dir in download_root.iterdir() if download_root.exists() else []:
                if game_dir.is_dir():
                    candidates.append(game_dir / ref_path)
        else:
            candidates.append(self._walkthrough_data_root() / ref_path)
            candidates.append(self._walkthrough_cache_root() / ref_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _get_walkthrough_query_client(self) -> WalkthroughServiceImporter:
        if self._walkthrough_query_client is None:
            self._walkthrough_query_client = WalkthroughServiceImporter(
                host=self.config.walkthrough_base_url,
                timeout=max(1.0, float(self.config.walkthrough_timeout_seconds)),
            )
        return self._walkthrough_query_client

    def _vision_instance_exists(self, instance_id: str) -> bool:
        target = str(instance_id or "").strip()
        if not target:
            return False
        try:
            instance_ids = self._get_walkthrough_query_client().list_vision_instance_ids()
        except Exception as exc:
            self._log_walkthrough_message(
                f"[walkthrough] list vision instances failed instance={target} error={exc}"
            )
            return False
        return target in instance_ids

    def _notify_walkthrough_updated(self, *, game_name: str, instance_id: str) -> None:
        self._walkthrough_overlay_active = False
        self._walkthrough_overlay_scene_key = None
        self._walkthrough_last_scene_hit_at = 0.0
        self._walkthrough_scene_hit_streak = 0
        self._show_toast_notification(
            title="攻略更新通知",
            message=f"游戏: {game_name}\n实例: {instance_id}\n攻略已更新完毕。",
            duration_ms=5000,
        )

    def _show_toast_notification(self, *, title: str, message: str, duration_ms: int = 5000) -> None:
        root = self._root
        if root is None:
            return
        try:
            root.update_idletasks()
            if self._toast_hide_after_id is not None:
                with contextlib.suppress(Exception):
                    root.after_cancel(self._toast_hide_after_id)
                self._toast_hide_after_id = None
            if self._toast_anim_after_id is not None:
                with contextlib.suppress(Exception):
                    root.after_cancel(self._toast_anim_after_id)
                self._toast_anim_after_id = None
            if self._toast_window is not None and self._toast_window.winfo_exists():
                self._toast_window.destroy()

            toast = tk.Toplevel(root)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            toast.attributes("-alpha", 0.97)
            toast.configure(bg="#0f141d")

            frame = tk.Frame(toast, bg="#0f141d", highlightbackground="#3f4f6a", highlightthickness=1)
            frame.pack(fill="both", expand=True)

            title_label = tk.Label(
                frame,
                text=title,
                anchor="w",
                bg="#0f141d",
                fg="#e8f1ff",
                padx=12,
                pady=8,
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            title_label.pack(fill="x")

            message_label = tk.Label(
                frame,
                text=message,
                justify="left",
                anchor="w",
                bg="#0f141d",
                fg="#c9d8ee",
                padx=12,
                pady=0,
                font=("Microsoft YaHei UI", 9),
                wraplength=420,
            )
            message_label.pack(fill="x", pady=(0, 10))

            toast.update_idletasks()
            width = max(280, toast.winfo_reqwidth())
            height = max(92, toast.winfo_reqheight())
            margin = max(16, int(self.config.overlay_margin))
            x = max(0, root.winfo_screenwidth() - width - margin)
            target_y = max(0, root.winfo_screenheight() - height - margin)
            hidden_y = root.winfo_screenheight() + 8
            toast.geometry(f"{width}x{height}+{x}+{hidden_y}")
            toast.lift()

            self._toast_window = toast

            def _slide_to(*, start_y: int, end_y: int, duration: int, on_done=None) -> None:
                steps = max(1, int(duration / 15))
                delta = (end_y - start_y) / float(steps)
                state = {"i": 0}

                def _tick() -> None:
                    if self._toast_window is not toast or not toast.winfo_exists():
                        self._toast_anim_after_id = None
                        return
                    state["i"] += 1
                    if state["i"] >= steps:
                        next_y = end_y
                    else:
                        next_y = int(start_y + delta * state["i"])
                    toast.geometry(f"{width}x{height}+{x}+{next_y}")
                    if state["i"] >= steps:
                        self._toast_anim_after_id = None
                        if callable(on_done):
                            on_done()
                        return
                    self._toast_anim_after_id = root.after(15, _tick)

                _tick()

            def _destroy_toast() -> None:
                if self._toast_window is toast:
                    self._toast_window = None
                self._toast_hide_after_id = None
                self._toast_anim_after_id = None
                if toast.winfo_exists():
                    toast.destroy()

            def _start_hide_animation() -> None:
                self._toast_hide_after_id = None
                _slide_to(start_y=target_y, end_y=hidden_y, duration=220, on_done=_destroy_toast)

            _slide_to(start_y=hidden_y, end_y=target_y, duration=220)
            self._toast_hide_after_id = root.after(max(1000, int(duration_ms)), _start_hide_animation)
        except Exception as exc:
            self._log_walkthrough_message(f"[walkthrough] toast notify failed error={exc}")

    def _get_walkthrough_downloader(self) -> GamerskyWalkthroughDownloader:
        if self._walkthrough_downloader is None:
            self._walkthrough_downloader = GamerskyWalkthroughDownloader(
                base_output_dir=self.config.walkthrough_download_dir,
                timeout=max(1, int(self.config.walkthrough_timeout_seconds)),
            )
        return self._walkthrough_downloader

    def _write_temp_query_image(self, image_bytes: bytes) -> Path:
        tmp_dir = Path("temp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="vision-query-", suffix=".jpg", dir=tmp_dir, delete=False) as handle:
            handle.write(image_bytes)
            return Path(handle.name)

    def _ensure_walkthrough_instance_for_usage(self, usage: ProcessGpuUsage) -> str | None:
        process_key = usage.name.strip().lower()
        if not process_key:
            return None
        with self._walkthrough_state_lock:
            identity = self._walkthrough_identity_by_process.get(process_key)
            if identity is not None:
                instance_id = identity.get("instance_id", "").strip()
                if instance_id and instance_id in self._walkthrough_ready_instances:
                    return instance_id
        started = self._request_walkthrough_bootstrap(
            usage.name,
            int(usage.pid),
            reason="initial_missing_instance",
            detail="已进入后台下载队列，正在准备搜索攻略。",
            min_interval_seconds=0.0,
        )
        if started:
            self._log_walkthrough_message(f"[walkthrough] bootstrap scheduled process={usage.name} pid={usage.pid} reason=initial_missing_instance")
        return None

    def _handle_walkthrough_query_miss(self, usage: ProcessGpuUsage, *, instance_id: str, hint: dict[str, object]) -> None:
        reason = str(hint.get("reason") or "unknown")
        if not self._walkthrough_query_miss_logged_since_last_hit:
            self._log_walkthrough_message(
                f"[walkthrough] query miss process={usage.name} pid={usage.pid} instance={instance_id} reason={reason}"
            )
            self._walkthrough_query_miss_logged_since_last_hit = True
        if not self.config.walkthrough_rebootstrap_on_query_miss:
            return
        if reason not in {"vision_no_hit", "scene_text_map_missing", "scene_top1_empty_text"}:
            return
        self._request_walkthrough_bootstrap(
            usage.name,
            int(usage.pid),
            reason=f"query_miss:{reason}",
            detail=(
                f"实例 {instance_id} 查询未命中，正在重新下载攻略。\n"
                f"原因: {reason}"
            ),
            min_interval_seconds=60.0,
        )

    def _request_walkthrough_bootstrap(
        self,
        process_name: str,
        pid: int,
        *,
        reason: str,
        detail: str,
        min_interval_seconds: float,
    ) -> bool:
        process_key = process_name.strip().lower()
        if not process_key:
            return False
        now = time.monotonic()
        with self._walkthrough_state_lock:
            if process_key in self._walkthrough_pending_processes:
                return False
            if self.config.walkthrough_bootstrap_once and process_key in self._walkthrough_bootstrap_started_processes:
                return False
            last_started_at = self._walkthrough_last_bootstrap_at.get(process_key, 0.0)
            if min_interval_seconds > 0 and now - last_started_at < min_interval_seconds:
                return False
            self._walkthrough_pending_processes.add(process_key)
            self._walkthrough_last_bootstrap_at[process_key] = now
            self._walkthrough_bootstrap_started_processes.add(process_key)
            self._walkthrough_pending_count += 1
        self._walkthrough_last_message = f"queued {process_name} pid={pid}"
        self._set_walkthrough_progress(
            process_name=process_name,
            status="攻略排队中",
            detail=f"进程: {process_name}\nPID: {pid}\n{detail}",
        )
        self._record_walkthrough_event(
            event="walkthrough_sync_queued",
            message=f"排队攻略同步: {process_name} (pid={pid})",
            metadata={"process_name": process_name, "pid": pid, "reason": reason},
        )
        threading.Thread(
            target=self._bootstrap_walkthrough_instance,
            args=(process_name, int(pid)),
            name="game-walkthrough-bootstrap",
            daemon=True,
        ).start()
        return True

    def _bootstrap_walkthrough_instance(self, process_name: str, pid: int) -> None:
        process_key = process_name.strip().lower()
        try:
            self._log_walkthrough_message(f"[walkthrough] bootstrap start process={process_name} pid={pid}")
            identity = self._resolve_walkthrough_identity(process_name=process_name, pid=pid)
            game_name = identity["game_name"]
            instance_id = identity["instance_id"]
            self._set_walkthrough_progress(
                process_name=process_name,
                status="攻略同步中",
                detail=f"进程: {process_name}\n游戏: {game_name}\n阶段: 下载攻略",
            )
            downloader = self._get_walkthrough_downloader()
            downloader.download_walkthrough(game_name)
            json_path = self._resolve_walkthrough_json_path(game_name)
            json_stats = self._normalize_walkthrough_json_for_import(json_path)

            self._set_walkthrough_progress(
                process_name=process_name,
                status="攻略同步中",
                detail=f"进程: {process_name}\n游戏: {game_name}\n阶段: 导入服务",
            )
            importer = self._get_walkthrough_query_client()
            import_summary = importer.sync_from_json(instance_id=instance_id, json_file_path=json_path)
            knowledge_id = import_summary.knowledge_id
            scene_map_path = self._resolve_imported_scene_text_map_path(
                instance_id=instance_id,
                preferred_path=str(getattr(import_summary, "scene_text_map_file", "") or "").strip(),
                json_path=json_path,
            )
            guides_found = int(json_stats["entries"])
            texts_saved = int(import_summary.texts_inserted)
            texts_cached = int(import_summary.texts_skipped)
            images_saved = int(import_summary.vision_scenes_inserted)
            images_cached = int(import_summary.vision_scenes_skipped)
            texts_available = texts_saved + texts_cached
            images_available = images_saved + images_cached
            with self._walkthrough_state_lock:
                was_ready = bool(instance_id) and instance_id in self._walkthrough_ready_instances
            data_ready = bool(instance_id) and bool(scene_map_path) and ((texts_available > 0 and images_available > 0) or was_ready)
            if instance_id:
                with self._walkthrough_state_lock:
                    self._walkthrough_identity_by_process[process_key] = {
                        "game_name": game_name,
                        "instance_id": instance_id,
                        "knowledge_id": str(knowledge_id or "").strip(),
                    }
                    if scene_map_path is not None:
                        self._walkthrough_scene_map_by_instance[instance_id] = scene_map_path
                    if data_ready:
                        self._walkthrough_ready_instances.add(instance_id)
                    else:
                        self._walkthrough_ready_instances.discard(instance_id)
            if data_ready:
                self._walkthrough_synced_count += 1
                self._walkthrough_last_message = f"ok {process_name} pid={pid}"
                self._set_walkthrough_progress(
                    process_name=process_name,
                    status="攻略已就绪",
                    detail=(
                        f"游戏: {game_name}\n实例: {instance_id or '未命名'}\n"
                        f"攻略 {guides_found} 条，文本 {texts_saved}（缓存 {texts_cached}），"
                        f"场景 {images_saved}（缓存 {images_cached}）。"
                    ),
                )
                self._record_walkthrough_event(
                    event="walkthrough_sync_success",
                    message=(
                        f"攻略同步完成: process={process_name} pid={pid} game={game_name} "
                        f"guides={guides_found} texts={texts_saved} images={images_saved} "
                        f"texts_cached={texts_cached} images_cached={images_cached}"
                    ),
                    metadata={
                        "process_name": process_name,
                        "pid": int(pid),
                        "game_name": game_name,
                        "source_json": json_path.as_posix(),
                        "guides_found": guides_found,
                        "texts_saved": texts_saved,
                        "images_saved": images_saved,
                        "texts_cached": texts_cached,
                        "images_cached": images_cached,
                        "knowledge_id": knowledge_id,
                        "instance_id": instance_id,
                        "scene_text_map_file": scene_map_path.as_posix() if scene_map_path is not None else "",
                    },
                )
                self._log_walkthrough_message(f"[walkthrough] synced guides for process={process_name} pid={pid} instance={instance_id}")
            else:
                self._walkthrough_failed_count += 1
                self._walkthrough_last_message = f"wait {process_name} pid={pid}"
                self._set_walkthrough_progress(
                    process_name=process_name,
                    status="等待攻略入库",
                    detail=(
                        f"游戏: {game_name}\n实例: {instance_id or '未命名'}\n"
                        f"本轮未完成 text/scene 就绪: 文本 {texts_saved}（缓存 {texts_cached}），"
                        f"场景 {images_saved}（缓存 {images_cached}）。\n"
                        "截图查询已暂停，等待下一轮下载完成。"
                    ),
                )
                self._record_walkthrough_event(
                    event="walkthrough_sync_incomplete",
                    message=(
                        f"攻略同步未就绪: process={process_name} pid={pid} game={game_name} "
                        f"guides={guides_found} texts={texts_saved} images={images_saved} "
                        f"texts_cached={texts_cached} images_cached={images_cached}"
                    ),
                    metadata={
                        "process_name": process_name,
                        "pid": int(pid),
                        "game_name": game_name,
                        "guides_found": guides_found,
                        "texts_saved": texts_saved,
                        "images_saved": images_saved,
                        "texts_cached": texts_cached,
                        "images_cached": images_cached,
                        "knowledge_id": knowledge_id,
                        "instance_id": instance_id,
                        "scene_text_map_file": scene_map_path.as_posix() if scene_map_path is not None else "",
                    },
                )
                self._log_walkthrough_message(
                    f"[walkthrough] sync incomplete process={process_name} pid={pid} instance={instance_id} "
                    f"texts={texts_saved} images={images_saved} texts_cached={texts_cached} images_cached={images_cached}"
                )
        except Exception as exc:
            self._walkthrough_failed_count += 1
            self._walkthrough_last_message = f"err {process_name} pid={pid}"
            self._set_walkthrough_progress(
                process_name=process_name,
                status="攻略同步失败",
                detail=f"进程: {process_name} (pid={pid})\n错误: {exc}",
            )
            self._record_walkthrough_event(
                event="walkthrough_sync_failed",
                message=f"攻略同步失败: process={process_name} pid={pid} error={exc}",
                metadata={"process_name": process_name, "pid": int(pid), "error": str(exc)},
            )
            self._log_walkthrough_message(f"[walkthrough] sync failed process={process_name} pid={pid} error={exc}")
        finally:
            with self._walkthrough_state_lock:
                self._walkthrough_pending_processes.discard(process_key)
            self._walkthrough_pending_count = max(0, self._walkthrough_pending_count - 1)

    def _capture_window_base64(self, bbox: tuple[int, int, int, int]) -> str | None:
        if ImageGrab is None:
            return None
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _get_focused_window_snapshot(self) -> tuple[tuple[int, int, int, int], str] | None:
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return self._last_external_window_snapshot

        try:
            hwnd = int(user32.GetForegroundWindow())
        except Exception:
            return self._last_external_window_snapshot
        if hwnd <= 0:
            return self._last_external_window_snapshot
        if self._is_internal_overlay_window(hwnd):
            return self._last_external_window_snapshot

        rect = wintypes.RECT()
        try:
            ok = bool(user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)))
        except Exception:
            return self._last_external_window_snapshot
        if not ok:
            return self._last_external_window_snapshot

        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
        if right - left <= 1 or bottom - top <= 1:
            return self._last_external_window_snapshot

        title = "未见"
        try:
            length = max(0, int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd))))
            if length > 0:
                text_buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(wintypes.HWND(hwnd), text_buf, len(text_buf))
                title = text_buf.value.strip() or "未见"
        except Exception:
            pass
        snapshot = ((left, top, right, bottom), title)
        self._last_external_window_snapshot = snapshot
        return snapshot

    def _is_internal_overlay_window(self, hwnd: int) -> bool:
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return False

        try:
            current_pid = int(os.getpid())
            owner_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(wintypes.HWND(int(hwnd)), ctypes.byref(owner_pid))
            if int(owner_pid.value) == current_pid:
                return True
        except Exception:
            pass

        ga_root = 2
        try:
            root_hwnd = int(user32.GetAncestor(wintypes.HWND(int(hwnd)), ga_root))
        except Exception:
            root_hwnd = int(hwnd)

        candidates: list[tk.Misc | None] = [
            self._root,
            getattr(self._overlay, "window", None),
            self._toast_window,
        ]
        for widget in candidates:
            if widget is None:
                continue
            try:
                if not bool(widget.winfo_exists()):
                    continue
                candidate_hwnd = int(widget.winfo_id())
                try:
                    candidate_root_hwnd = int(user32.GetAncestor(wintypes.HWND(candidate_hwnd), ga_root))
                except Exception:
                    candidate_root_hwnd = candidate_hwnd
                if int(hwnd) == candidate_hwnd or root_hwnd == candidate_root_hwnd:
                    return True
            except Exception:
                continue
        return False

    def _update_overlay(
        self,
        *,
        title: str,
        status: str,
        text: str,
        replace: bool,
        image_bytes: bytes | None = None,
        image_bytes_list: list[bytes] | None = None,
        compact_one_line: bool = False,
        fit_content_height: bool = False,
    ) -> None:
        if self._overlay is None:
            return
        self._overlay.set_title(title)
        self._overlay.set_status(self._compose_overlay_status(status))
        if replace:
            self._overlay_main_text = text
            next_images = [item for item in (image_bytes_list or []) if item]
            if not next_images and image_bytes is not None:
                next_images = [image_bytes]
            self._overlay_last_image_bytes_list = next_images
        else:
            self._overlay_main_text = f"{self._overlay_main_text}{text}"
        self._overlay.replace_text(
            self._compose_overlay_body(),
            image_bytes_list=self._overlay_last_image_bytes_list,
        )
        if compact_one_line:
            self._overlay.compact_to_one_line()
        elif fit_content_height:
            self._overlay.fit_to_content()

    def _show_scene_recognizing_overlay(
        self,
        process_name: str,
        *,
        now: float | None = None,
        hold_seconds: float | None = None,
    ) -> None:
        effective_now = time.monotonic() if now is None else now
        effective_hold = (
            max(0.0, float(self.config.walkthrough_overlay_hold_seconds))
            if hold_seconds is None
            else max(0.0, float(hold_seconds))
        )
        if self._should_keep_walkthrough_overlay(now=effective_now, hold_seconds=effective_hold):
            return
        label = process_name or "未知进程"
        if self._last_status_text == "场景识别中":
            return
        self._last_status_text = "场景识别中"
        self._walkthrough_progress_text = ""
        self._ui_queue.put(
            lambda value=label: self._update_overlay(
                title=f"{self.config.overlay_title} | {value}",
                status="场景识别中",
                text="场景识别中",
                replace=True,
                compact_one_line=True,
            )
        )

    def _compose_overlay_status(self, status: str) -> str:
        base = f"{status}"
        if self.config.walkthrough_bootstrap_enabled:
            base = (
                f"{base} | 攻略 p{self._walkthrough_pending_count}/ok{self._walkthrough_synced_count}/err{self._walkthrough_failed_count}"
            )
        return f"{base} | {self.config.toggle_hotkey} 切换"

    def _append_overlay_text(self, text: str) -> None:
        if self._overlay is None:
            return
        self._overlay_main_text = f"{self._overlay_main_text}{text}"
        self._overlay.replace_text(self._compose_overlay_body())

    def _compose_overlay_body(self) -> str:
        parts: list[str] = []
        if self._overlay_main_text:
            parts.append(self._overlay_main_text)
        if self._walkthrough_progress_text:
            parts.append(f"[攻略同步进度]\n{self._walkthrough_progress_text}")
        return "\n\n".join(part for part in parts if part).strip()

    def _handle_walkthrough_progress(self, payload: dict[str, object]) -> None:
        process_name = str(payload.get("process_name") or "未知进程")
        stage = str(payload.get("stage") or "working")
        message = str(payload.get("message") or "")
        detail = self._format_walkthrough_progress_detail(stage=stage, payload=payload)
        status = "攻略同步中"
        if stage == "done":
            status = "攻略已就绪"
        elif "failed" in stage:
            status = "攻略同步失败"
        self._set_walkthrough_progress(process_name=process_name, status=status, detail=detail or message)

    def _set_walkthrough_progress(self, *, process_name: str, status: str, detail: str) -> None:
        message = detail.strip()
        self._walkthrough_last_message = message or self._walkthrough_last_message
        self._ui_queue.put(
            lambda value=message, process=process_name, overlay_status=status: self._update_walkthrough_progress_overlay(
                process_name=process,
                status=overlay_status,
                detail=value,
            )
        )

    def _update_walkthrough_progress_overlay(self, *, process_name: str, status: str, detail: str) -> None:
        self._walkthrough_progress_text = detail.strip()
        if self._overlay is None:
            return
        self._overlay.set_title(f"{self.config.overlay_title} | {process_name}")
        self._overlay.set_status(self._compose_overlay_status(status))
        self._overlay.replace_text(self._compose_overlay_body(), image_bytes_list=self._overlay_last_image_bytes_list)

    def _resolve_imported_scene_text_map_path(self, *, instance_id: str, preferred_path: str, json_path: Path) -> Path | None:
        candidates: list[Path] = []
        if preferred_path:
            preferred = Path(preferred_path)
            if not preferred.is_absolute():
                candidates.append(preferred)
                candidates.append(json_path.parent / preferred)
            candidates.append(preferred.expanduser())
        candidates.append(json_path.with_name("scene_text_map.json"))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        self._log_walkthrough_message(
            f"[walkthrough] scene_text_map_missing instance={instance_id} json={json_path} preferred={preferred_path or '-'}"
        )
        return None

    def _walkthrough_download_root(self) -> Path:
        return Path(self.config.walkthrough_download_dir).expanduser()

    @staticmethod
    def _walkthrough_data_root() -> Path:
        return Path("data") / "walkthrough"

    @staticmethod
    def _walkthrough_cache_root() -> Path:
        return Path("caches") / "walkthrough"

    def _format_walkthrough_progress_detail(self, *, stage: str, payload: dict[str, object]) -> str:
        message = str(payload.get("message") or "").strip()
        process_name = str(payload.get("process_name") or "未知进程")
        game_name = str(payload.get("game_name") or "").strip()
        instance_id = str(payload.get("instance_id") or "").strip()
        guide_index = int(payload.get("guide_index") or 0)
        guides_total = int(payload.get("guides_total") or 0)
        image_index = int(payload.get("image_index") or 0)
        images_total = int(payload.get("images_total") or 0)
        texts_saved = int(payload.get("texts_saved") or 0)
        images_saved = int(payload.get("images_saved") or 0)
        guides_found = int(payload.get("guides_found") or 0)
        lines = [f"进程: {process_name}"]
        if game_name:
            lines.append(f"游戏: {game_name}")
        if instance_id:
            lines.append(f"实例: {instance_id}")
        lines.append(f"阶段: {message or stage}")
        if guide_index and guides_total:
            lines.append(f"攻略进度: {guide_index}/{guides_total}")
        elif guides_found:
            lines.append(f"攻略候选: {guides_found}")
        if image_index and images_total:
            lines.append(f"配图进度: {image_index}/{images_total}")
        if texts_saved or images_saved:
            lines.append(f"已入库: 文本 {texts_saved}，配图 {images_saved}")
        return "\n".join(lines)

    def _register_global_hotkey(self) -> None:
        if keyboard is None or self._hotkey_handle is not None:
            return

        def on_hotkey() -> None:
            self._ui_queue.put(self._toggle_overlay_visibility)

        hotkey = self.config.toggle_hotkey.strip() or "ctrl+shift+g"
        self._hotkey_handle = keyboard.add_hotkey(hotkey, on_hotkey, suppress=False, trigger_on_release=False)

    def _unregister_global_hotkey(self) -> None:
        if keyboard is None or self._hotkey_handle is None:
            return
        try:
            keyboard.remove_hotkey(self._hotkey_handle)
        finally:
            self._hotkey_handle = None

    def _toggle_overlay_visibility(self) -> None:
        overlay = self._overlay
        if overlay is None:
            return
        if overlay.is_visible():
            overlay.hide()
            self._overlay_hidden = True
            return
        overlay.show()
        self._overlay_hidden = False

    def _start_debug_screenshot_worker_if_needed(self) -> None:
        if self._debug_screenshot_worker_started:
            return
        self._debug_screenshot_worker_started = True
        threading.Thread(
            target=self._debug_screenshot_worker_loop,
            name="game-debug-screenshot-writer",
            daemon=True,
        ).start()

    def _enqueue_debug_screenshot(self, image_bytes: bytes) -> None:
        if not image_bytes:
            return
        self._debug_screenshot_queue.put(image_bytes)

    def _debug_screenshot_worker_loop(self) -> None:
        output_path = self._resolve_debug_screenshot_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        while not self._stop_event.is_set():
            try:
                latest = self._debug_screenshot_queue.get(timeout=0.5)
            except Exception:
                continue

            # Keep only the newest frame when producer is faster than disk writes.
            while True:
                try:
                    latest = self._debug_screenshot_queue.get_nowait()
                except queue.Empty:
                    break

            try:
                tmp_path = output_path.with_suffix(".tmp")
                if Image is not None:
                    img = Image.open(io.BytesIO(latest)).convert("RGB")
                    img.save(tmp_path, format="JPEG", quality=90)
                else:
                    tmp_path.write_bytes(latest)
                tmp_path.replace(output_path)
            except Exception as exc:
                self._log_walkthrough_message(f"[walkthrough] debug screenshot write failed path={output_path} error={exc}")

    @staticmethod
    def _resolve_debug_screenshot_path() -> Path:
        return Path("caches") / "screenshot.jpg"

    def _start_walkthrough_worker_if_needed(self) -> None:
        if not self.config.walkthrough_bootstrap_enabled or self._walkthrough_worker_started:
            return
        self._walkthrough_worker_started = True

    def _enqueue_walkthrough_bootstrap(self, usage: ProcessGpuUsage) -> None:
        if not self.config.walkthrough_bootstrap_enabled or not self._walkthrough_worker_started:
            return
        key = (usage.name.lower(), usage.pid)
        if key in self._walkthrough_seen_processes:
            return
        self._walkthrough_seen_processes.add(key)
        self._walkthrough_pending_count += 1
        self._walkthrough_last_message = f"queued {usage.name} pid={usage.pid}"
        self._set_walkthrough_progress(
            process_name=usage.name,
            status="攻略排队中",
            detail=f"进程: {usage.name}\nPID: {usage.pid}\n已进入后台下载队列，等待工作线程处理。",
        )
        self._record_walkthrough_event(
            event="walkthrough_sync_queued",
            message=f"排队攻略同步: {usage.name} (pid={usage.pid})",
            metadata={"process_name": usage.name, "pid": usage.pid},
        )
        self._walkthrough_queue.put((usage.name, usage.pid))


    def _walkthrough_worker_loop(self) -> None:
        # Legacy queue mode is no longer used; bootstrap runs via _request_walkthrough_bootstrap directly.
        while not self._stop_event.is_set():
            try:
                process_name, pid = self._walkthrough_queue.get(timeout=0.5)
            except Exception:
                continue
            try:
                self._bootstrap_walkthrough_instance(process_name, int(pid))
            except Exception as exc:
                self._walkthrough_failed_count += 1
                self._walkthrough_last_message = f"err {process_name} pid={pid}"
                self._set_walkthrough_progress(
                    process_name=process_name,
                    status="攻略同步失败",
                    detail=f"进程: {process_name} (pid={pid})\n错误: {exc}",
                )
                self._record_walkthrough_event(
                    event="walkthrough_sync_failed",
                    message=f"攻略同步失败: process={process_name} pid={pid} error={exc}",
                    metadata={"process_name": process_name, "pid": int(pid), "error": str(exc)},
                )
                self._log_walkthrough_message(f"[walkthrough] sync failed process={process_name} pid={pid} error={exc}")
            finally:
                self._walkthrough_pending_count = max(0, self._walkthrough_pending_count - 1)

    def _resolve_walkthrough_identity(self, *, process_name: str, pid: int) -> dict[str, str]:
        configured_game_name = self.config.walkthrough_game_name.strip() if isinstance(self.config.walkthrough_game_name, str) else ""
        game_name = configured_game_name or process_name
        instance_id = self._slug_text(game_name) or self._slug_text(process_name) or f"game-{pid}"
        return {"game_name": game_name, "instance_id": instance_id}

    def _resolve_walkthrough_json_path(self, game_name: str) -> Path:
        safe_game_name = self._safe_game_dir_name(game_name)
        path = self._walkthrough_download_root() / safe_game_name / "text_images.json"
        if not path.exists():
            raise RuntimeError(f"downloaded walkthrough json not found: {path}")
        return path

    def _normalize_walkthrough_json_for_import(self, json_path: Path) -> dict[str, int]:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"failed to read walkthrough json: {json_path}, error={exc}") from exc
        if not isinstance(payload, list):
            raise RuntimeError(f"invalid walkthrough json format: {json_path}")

        normalized: list[dict[str, object]] = []
        merged_image_only = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            images_raw = item.get("images")
            images = [str(value).strip() for value in images_raw if str(value).strip()] if isinstance(images_raw, list) else []
            if text:
                normalized.append({"text": text, "images": images})
                continue
            if images and normalized:
                last_images = normalized[-1].get("images")
                if isinstance(last_images, list):
                    last_images.extend(images)
                merged_image_only += 1
                continue
            if images:
                normalized.append({"text": "场景截图参考", "images": images})
                merged_image_only += 1

        json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=4), encoding="utf-8")
        return {"entries": len(normalized), "merged_image_only": merged_image_only}

    @staticmethod
    def _safe_game_dir_name(name: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
        return cleaned or "unknown_game"

    @staticmethod
    def _slug_text(value: str) -> str:
        lowered = value.strip().lower()
        lowered = re.sub(r"\.exe$", "", lowered)
        lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", lowered)
        return lowered.strip("-")


    def _log_walkthrough_message(self, message: str) -> None:
        if not isinstance(message, str) or not message.strip():
            return
        print(message, file=sys.stderr)

    def _log_exception(self, context_message: str, exc: BaseException) -> None:
        self._log_walkthrough_message(f"[walkthrough] {context_message}: {exc}")
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)

    def _report_tk_exception(self, exc: type[BaseException], val: BaseException, tb) -> None:
        print("[game-client] uncaught exception (tk callback):", file=sys.stderr)
        traceback.print_exception(exc, val, tb, file=sys.stderr)

    def _resolve_walkthrough_log_file_path(self) -> Path | None:
        raw = self.config.walkthrough_log_file_path
        if not isinstance(raw, str) or not raw.strip():
            return None
        return Path(raw).expanduser()

    def _record_walkthrough_event(self, *, event: str, message: str, metadata: dict[str, object]) -> None:
        try:
            payload = {
                "event": event,
                "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                **metadata,
            }
        except Exception as exc:
            self._log_walkthrough_message(f"[walkthrough] memory write failed event={event} error={exc}")

    def _ensure_runtime_dependencies(self) -> None:
        if ImageGrab is None:
            raise RuntimeError("Missing dependency: Pillow. Install with `python -m pip install -e .[desktop]`.")
        if keyboard is None:
            raise RuntimeError("Missing dependency: keyboard. Install with `python -m pip install -e .[desktop]`.")


def build_game_parser() -> argparse.ArgumentParser:
    default_walkthrough_dir = (_SCRIPT_DIR / "walkthrough").as_posix()
    parser = argparse.ArgumentParser(prog="mini-agent-game")
    parser.add_argument("run", nargs="?", default="run")
    parser.add_argument("--user-id", default="game-user")
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--analysis-interval-seconds", type=float, default=1.0)
    parser.add_argument("--three-d-threshold", type=float, default=20.0)
    parser.add_argument("--decoder-threshold", type=float, default=10.0)
    parser.add_argument("--encoder-threshold", type=float, default=10.0)
    parser.add_argument("--phys-index", type=int, default=None)
    parser.add_argument("--detect-process-name", default=None)
    parser.add_argument("--detect-process-fallback-gpu", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--walkthrough-bootstrap-enabled", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--walkthrough-base-url", default="http://127.0.0.1:9190")
    parser.add_argument("--walkthrough-game-name", default=None)
    parser.add_argument("--walkthrough-max-images-per-guide", type=int, default=3)
    parser.add_argument("--walkthrough-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--walkthrough-query-topk", type=int, default=1)
    parser.add_argument("--walkthrough-query-threshold", type=float, default=0.88)
    parser.add_argument("--walkthrough-query-threshold-2", type=float, default=0.01)
    parser.add_argument("--walkthrough-confirm-hit-count", type=int, default=2)
    parser.add_argument("--walkthrough-overlay-hold-seconds", type=float, default=10.0)
    parser.add_argument("--walkthrough-screenshot-interval-seconds", type=float, default=None)
    parser.add_argument("--walkthrough-match-score-threshold", type=float, default=0.7)
    parser.add_argument("--walkthrough-display-debug-details", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--walkthrough-download-dir", default=default_walkthrough_dir)
    parser.add_argument("--walkthrough-log-file-path", default="logs/game_client.log")
    parser.add_argument("--log-daily-split", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--log-to-console", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--toggle-hotkey", default="ctrl+shift+g")
    return parser


def main() -> None:
    parser = build_game_parser()
    args = parser.parse_args()
    log_path = _install_global_log_capture(
        Path(str(args.walkthrough_log_file_path or "logs/game_client.log")),
        mirror_to_console=bool(args.log_to_console),
        daily_split=bool(args.log_daily_split),
    )
    _install_global_exception_logging()
    print(f"[game-client] logging to {log_path.as_posix()}")
    client = GameVisionClient(
        config=GameVisionClientConfig(
            user_id=args.user_id,
            poll_interval_seconds=args.poll_interval_seconds,
            analysis_interval_seconds=args.analysis_interval_seconds,
            three_d_threshold=args.three_d_threshold,
            decoder_threshold=args.decoder_threshold,
            encoder_threshold=args.encoder_threshold,
            phys_index=args.phys_index,
            detect_process_name=args.detect_process_name,
            detect_process_fallback_gpu=bool(args.detect_process_fallback_gpu),
            walkthrough_bootstrap_enabled=bool(args.walkthrough_bootstrap_enabled),
            walkthrough_base_url=args.walkthrough_base_url,
            walkthrough_game_name=args.walkthrough_game_name,
            walkthrough_max_images_per_guide=max(1, int(args.walkthrough_max_images_per_guide)),
            walkthrough_timeout_seconds=max(1.0, float(args.walkthrough_timeout_seconds)),
            walkthrough_query_topk=max(1, int(args.walkthrough_query_topk)),
            walkthrough_query_threshold=max(0.0, min(1.0, float(args.walkthrough_query_threshold))),
            walkthrough_query_threshold_2=max(0.0, min(1.0, float(args.walkthrough_query_threshold_2))),
            walkthrough_confirm_hit_count=max(1, int(args.walkthrough_confirm_hit_count)),
            walkthrough_overlay_hold_seconds=max(0.0, float(args.walkthrough_overlay_hold_seconds)),
            walkthrough_screenshot_interval_seconds=(
                None if args.walkthrough_screenshot_interval_seconds is None else max(0.01, float(args.walkthrough_screenshot_interval_seconds))
            ),
            walkthrough_match_score_threshold=max(0.0, min(1.0, float(args.walkthrough_match_score_threshold))),
            walkthrough_display_debug_details=bool(args.walkthrough_display_debug_details),
            walkthrough_download_dir=str(args.walkthrough_download_dir),
            walkthrough_log_file_path=str(log_path),
            toggle_hotkey=args.toggle_hotkey,
        )
    )
    client.run_forever()


if __name__ == "__main__":
    main()