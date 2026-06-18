from __future__ import annotations

import argparse
import ctypes
import json
import re
import time
from pathlib import Path
from dataclasses import dataclass
from ctypes import wintypes


PDH_HQUERY = wintypes.HANDLE
PDH_HCOUNTER = wintypes.HANDLE

ERROR_SUCCESS = 0
PDH_MORE_DATA = 0x800007D2
PDH_NO_DATA = 0x800007D5
PDH_FMT_DOUBLE = 0x00000200
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_PATH = 260
GW_OWNER = 4

INSTANCE_PID_RE = re.compile(r"pid_?(\d+)", re.IGNORECASE)
INSTANCE_PHYS_RE = re.compile(r"phys_(\d+)", re.IGNORECASE)
INSTANCE_ENGINE_RE = re.compile(r"engtype_([^_\\/)]+)", re.IGNORECASE)
INSTANCE_ENGINE_FALLBACK_RE = re.compile(
    r"(^|[^a-z])(3D|VideoDecode|Decode|VideoEncode|Encode)([^a-z]|$)",
    re.IGNORECASE,
)


class PDH_FMT_COUNTERVALUE_DOUBLE(ctypes.Structure):
    _fields_ = [
        ("CStatus", wintypes.DWORD),
        ("doubleValue", ctypes.c_double),
    ]


class PDH_FMT_COUNTERVALUE_ITEM_DOUBLE(ctypes.Structure):
    _fields_ = [
        ("szName", wintypes.LPWSTR),
        ("FmtValue", PDH_FMT_COUNTERVALUE_DOUBLE),
    ]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass(slots=True)
class ProcessGpuUsage:
    pid: int
    name: str
    phys_indexes: tuple[int, ...]
    three_d: float
    decoder: float
    encoder: float


@dataclass(slots=True)
class SnapshotDiagnostics:
    raw_instances: list[str]
    unresolved_instances: list[str]
    engine_labels: list[str]
    missing_name_pids: list[int]


@dataclass(slots=True)
class WindowBounds:
    left: int
    top: int
    width: int
    height: int
    title: str

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.left + self.width, self.top + self.height)


LAST_SNAPSHOT_DIAGNOSTICS = SnapshotDiagnostics(
    raw_instances=[],
    unresolved_instances=[],
    engine_labels=[],
    missing_name_pids=[],
)


def _configure_pdh() -> ctypes.WinDLL:
    pdh = ctypes.WinDLL("pdh")
    pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(PDH_HQUERY)]
    pdh.PdhOpenQueryW.restype = wintypes.DWORD
    pdh.PdhCollectQueryData.argtypes = [PDH_HQUERY]
    pdh.PdhCollectQueryData.restype = wintypes.DWORD
    pdh.PdhGetFormattedCounterArrayW.argtypes = [
        PDH_HCOUNTER,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    pdh.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
    pdh.PdhCloseQuery.argtypes = [PDH_HQUERY]
    pdh.PdhCloseQuery.restype = wintypes.DWORD
    if hasattr(pdh, "PdhAddEnglishCounterW"):
        pdh.PdhAddEnglishCounterW.argtypes = [
            PDH_HQUERY,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(PDH_HCOUNTER),
        ]
        pdh.PdhAddEnglishCounterW.restype = wintypes.DWORD
    pdh.PdhAddCounterW.argtypes = [
        PDH_HQUERY,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(PDH_HCOUNTER),
    ]
    pdh.PdhAddCounterW.restype = wintypes.DWORD
    return pdh


PDH = _configure_pdh()
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
USER32 = ctypes.WinDLL("user32", use_last_error=True)

KERNEL32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
KERNEL32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
KERNEL32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
KERNEL32.Process32FirstW.restype = wintypes.BOOL
KERNEL32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
KERNEL32.Process32NextW.restype = wintypes.BOOL
KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
KERNEL32.CloseHandle.restype = wintypes.BOOL

USER32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
USER32.EnumWindows.restype = wintypes.BOOL
USER32.IsWindowVisible.argtypes = [wintypes.HWND]
USER32.IsWindowVisible.restype = wintypes.BOOL
USER32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
USER32.GetWindow.restype = wintypes.HWND
USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
USER32.GetWindowRect.restype = wintypes.BOOL
USER32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
USER32.GetWindowTextLengthW.restype = ctypes.c_int
USER32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
USER32.GetWindowTextW.restype = ctypes.c_int
USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
USER32.GetWindowThreadProcessId.restype = wintypes.DWORD


def _check_pdh_status(status: int, action: str) -> None:
    if status != ERROR_SUCCESS:
        raise RuntimeError(f"{action} failed with PDH status 0x{status:08x}")


class GpuEngineCounterReader:
    def __init__(self) -> None:
        self.query = PDH_HQUERY()
        self.counter = PDH_HCOUNTER()

        status = PDH.PdhOpenQueryW(None, None, ctypes.byref(self.query))
        _check_pdh_status(status, "PdhOpenQueryW")

        counter_path = "\\GPU Engine(*)\\Utilization Percentage"
        add_counter = getattr(PDH, "PdhAddEnglishCounterW", None)
        if add_counter is not None:
            status = add_counter(self.query, counter_path, None, ctypes.byref(self.counter))
        else:
            status = PDH.PdhAddCounterW(self.query, counter_path, None, ctypes.byref(self.counter))
        if status != ERROR_SUCCESS:
            PDH.PdhCloseQuery(self.query)
            _check_pdh_status(status, "PdhAddCounter")

        status = PDH.PdhCollectQueryData(self.query)
        _check_pdh_status(status, "PdhCollectQueryData")

    def close(self) -> None:
        if self.query:
            PDH.PdhCloseQuery(self.query)
            self.query = PDH_HQUERY()

    def collect(self) -> list[tuple[str, float]]:
        status = PDH.PdhCollectQueryData(self.query)
        _check_pdh_status(status, "PdhCollectQueryData")

        buffer_size = wintypes.DWORD(0)
        item_count = wintypes.DWORD(0)
        status = PDH.PdhGetFormattedCounterArrayW(
            self.counter,
            PDH_FMT_DOUBLE,
            ctypes.byref(buffer_size),
            ctypes.byref(item_count),
            None,
        )
        if status == PDH_NO_DATA:
            return []
        if status not in (ERROR_SUCCESS, PDH_MORE_DATA):
            _check_pdh_status(status, "PdhGetFormattedCounterArrayW")
        if buffer_size.value == 0 or item_count.value == 0:
            return []

        raw_buffer = ctypes.create_string_buffer(buffer_size.value)
        status = PDH.PdhGetFormattedCounterArrayW(
            self.counter,
            PDH_FMT_DOUBLE,
            ctypes.byref(buffer_size),
            ctypes.byref(item_count),
            raw_buffer,
        )
        _check_pdh_status(status, "PdhGetFormattedCounterArrayW")

        items_ptr = ctypes.cast(raw_buffer, ctypes.POINTER(PDH_FMT_COUNTERVALUE_ITEM_DOUBLE))
        return [
            ((items_ptr[index].szName or ""), float(items_ptr[index].FmtValue.doubleValue))
            for index in range(item_count.value)
        ]


def list_process_names() -> dict[int, str]:
    snapshot = KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")

    process_names: dict[int, str] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not KERNEL32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return process_names
        while True:
            name = entry.szExeFile
            if name:
                process_names[int(entry.th32ProcessID)] = name.rsplit(".", 1)[0]
            if not KERNEL32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
        return process_names
    finally:
        KERNEL32.CloseHandle(snapshot)


def parse_counter_instance(instance_name: str) -> tuple[int | None, str | None]:
    pid_match = INSTANCE_PID_RE.search(instance_name)
    engine_match = INSTANCE_ENGINE_RE.search(instance_name)

    pid = int(pid_match.group(1)) if pid_match else None
    engine: str | None = None
    if engine_match:
        engine = engine_match.group(1)
    else:
        fallback_match = INSTANCE_ENGINE_FALLBACK_RE.search(instance_name)
        if fallback_match:
            engine = fallback_match.group(2)
    if engine:
        engine = engine.strip().lower()
    return pid, engine


def parse_physical_gpu_index(instance_name: str) -> int | None:
    match = INSTANCE_PHYS_RE.search(instance_name)
    if not match:
        return None
    return int(match.group(1))


def collect_gpu_usage_snapshot(reader: GpuEngineCounterReader, phys_index: int | None = None) -> list[ProcessGpuUsage]:
    global LAST_SNAPSHOT_DIAGNOSTICS

    per_pid: dict[int, dict[str, float | set[int]]] = {}
    raw_instances: list[str] = []
    unresolved_instances: list[str] = []
    engine_labels: list[str] = []

    for instance_name, value in reader.collect():
        if len(raw_instances) < 30:
            raw_instances.append(f"{instance_name} || value={value:.2f}")
        pid, engine = parse_counter_instance(instance_name)
        sample_phys_index = parse_physical_gpu_index(instance_name)
        if engine and len(engine_labels) < 30:
            engine_labels.append(engine)
        if pid is None or not engine:
            if len(unresolved_instances) < 20:
                unresolved_instances.append(instance_name)
            continue
        if phys_index is not None and sample_phys_index != phys_index:
            continue

        metrics = per_pid.setdefault(pid, {"three_d": 0.0, "decoder": 0.0, "encoder": 0.0, "phys_indexes": set()})
        if sample_phys_index is not None:
            phys_indexes = metrics["phys_indexes"]
            assert isinstance(phys_indexes, set)
            phys_indexes.add(sample_phys_index)
        if "3d" in engine:
            metrics["three_d"] += value
        elif "decode" in engine:
            metrics["decoder"] += value
        elif "encode" in engine:
            metrics["encoder"] += value

    process_names = list_process_names()
    missing_name_pids: list[int] = []
    usages: list[ProcessGpuUsage] = []
    for pid, metrics in per_pid.items():
        name = process_names.get(pid)
        if not name:
            missing_name_pids.append(pid)
            name = f"pid-{pid}"
        phys_indexes = metrics["phys_indexes"]
        assert isinstance(phys_indexes, set)
        usages.append(
            ProcessGpuUsage(
                pid=pid,
                name=name,
                phys_indexes=tuple(sorted(phys_indexes)),
                three_d=round(metrics["three_d"], 2),
                decoder=round(metrics["decoder"], 2),
                encoder=round(metrics["encoder"], 2),
            )
        )

    LAST_SNAPSHOT_DIAGNOSTICS = SnapshotDiagnostics(
        raw_instances=raw_instances,
        unresolved_instances=unresolved_instances,
        engine_labels=engine_labels,
        missing_name_pids=missing_name_pids,
    )
    return usages


def is_game_like_process(
    usage: ProcessGpuUsage,
    three_d_threshold: float,
    decoder_threshold: float,
    encoder_threshold: float,
) -> bool:
    return (
        usage.three_d >= three_d_threshold
        and usage.decoder <= decoder_threshold
        and usage.encoder <= encoder_threshold
    )


def load_detected_process_names(mapping_path: Path | None = None) -> dict[str, str]:
    if mapping_path is None:
        mapping_path = Path(__file__).with_name("detected_processes.json")
    try:
        raw = json.loads(mapping_path.read_text(encoding="utf-8"))
        print(f"raw: {raw}")
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        normalized[key] = value
    return normalized


def wait_for_game_process(
    three_d_threshold: float = 15.0,
    decoder_threshold: float = 10.0,
    encoder_threshold: float = 10.0,
    phys_index: int | None = None,
    sample_interval_seconds: float = 0.1,
    detected_processes_file: Path | None = None,
) -> dict[str, str | None]:
    if detected_processes_file is None:
        detected_processes_file = Path(__file__).resolve().parent.parent / "detected_processes.json"
    reader = GpuEngineCounterReader()
    try:
        # PDH rate counters need a short interval between samples for stable values.
        if sample_interval_seconds > 0:
            time.sleep(sample_interval_seconds)
        candidates = get_top_game_candidates(
            reader,
            three_d_threshold=three_d_threshold,
            decoder_threshold=decoder_threshold,
            phys_index=phys_index,
            encoder_threshold=encoder_threshold,
            limit=1,
        )
        process_name = candidates[0].name if candidates else None
        process_names = load_detected_process_names(mapping_path=detected_processes_file)
        real_name = process_names.get(process_name) if process_name else None
        return {
            "process": process_name,
            "name": real_name,
        }
    finally:
        reader.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-shot game process detection based on GPU engine usage")
    parser.add_argument("--three-d-threshold", type=float, default=15.0, help="Minimum 3D utilization percentage")
    parser.add_argument("--decoder-threshold", type=float, default=10.0, help="Maximum decoder utilization percentage")
    parser.add_argument("--encoder-threshold", type=float, default=10.0, help="Maximum encoder utilization percentage")
    parser.add_argument("--phys-index", type=int, default=None, help="Optional physical GPU index filter")
    parser.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=0.1,
        help="Sampling interval before the single snapshot, in seconds",
    )
    parser.add_argument(
        "--detected-processes-file",
        type=str,
        default=None,
        help="Optional path to detected process mapping JSON file",
    )
    args = parser.parse_args()
    detected_processes_file = Path(args.detected_processes_file) if args.detected_processes_file else None

    result = wait_for_game_process(
        three_d_threshold=args.three_d_threshold,
        decoder_threshold=args.decoder_threshold,
        encoder_threshold=args.encoder_threshold,
        phys_index=args.phys_index,
        sample_interval_seconds=args.sample_interval_seconds,
        detected_processes_file=detected_processes_file,
    )
    print(json.dumps(result, ensure_ascii=False, indent=4))
    return 0


def find_game_process(
    reader: GpuEngineCounterReader,
    *,
    matched_since: dict[int, float],
    sustained_seconds: float,
    three_d_threshold: float,
    decoder_threshold: float,
    phys_index: int | None,
    encoder_threshold: float = 10.0,
) -> ProcessGpuUsage | None:
    now = time.monotonic()
    snapshot = collect_gpu_usage_snapshot(reader, phys_index=phys_index)
    currently_matched: set[int] = set()
    best_match: ProcessGpuUsage | None = None
    for usage in sorted(snapshot, key=lambda item: item.three_d, reverse=True):
        if not is_game_like_process(
            usage,
            three_d_threshold=three_d_threshold,
            decoder_threshold=decoder_threshold,
            encoder_threshold=encoder_threshold,
        ):
            continue
        currently_matched.add(usage.pid)
        matched_since.setdefault(usage.pid, now)
        if now - matched_since[usage.pid] >= sustained_seconds and best_match is None:
            best_match = usage
    for pid in list(matched_since):
        if pid not in currently_matched:
            matched_since.pop(pid, None)
    return best_match


def get_top_game_candidates(
    reader: GpuEngineCounterReader,
    *,
    three_d_threshold: float,
    decoder_threshold: float,
    phys_index: int | None,
    encoder_threshold: float = 10.0,
    limit: int = 5,
) -> list[ProcessGpuUsage]:
    snapshot = collect_gpu_usage_snapshot(reader, phys_index=phys_index)
    matched = [
        usage
        for usage in snapshot
        if is_game_like_process(
            usage,
            three_d_threshold=three_d_threshold,
            decoder_threshold=decoder_threshold,
            encoder_threshold=encoder_threshold,
        )
    ]
    matched.sort(key=lambda item: item.three_d, reverse=True)
    return matched[:limit]


def get_window_bounds_for_pid(pid: int) -> WindowBounds | None:
    windows: list[tuple[int, WindowBounds]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, lparam: int) -> bool:
        del lparam
        window_pid = wintypes.DWORD(0)
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if int(window_pid.value) != pid:
            return True
        if not USER32.IsWindowVisible(hwnd):
            return True
        if USER32.GetWindow(hwnd, GW_OWNER):
            return True
        rect = RECT()
        if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 200 or height < 120:
            return True
        title = _get_window_title(hwnd)
        area = width * height
        windows.append(
            (
                area,
                WindowBounds(
                    left=int(rect.left),
                    top=int(rect.top),
                    width=width,
                    height=height,
                    title=title,
                ),
            )
        )
        return True

    USER32.EnumWindows(callback_type(callback), 0)
    if not windows:
        return None
    windows.sort(key=lambda item: item[0], reverse=True)
    return windows[0][1]


def _get_window_title(hwnd: int) -> str:
    length = USER32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


if __name__ == "__main__":
    raise SystemExit(main())