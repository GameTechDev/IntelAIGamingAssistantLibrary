import json
from typing import Any

import requests

HOST = "127.0.0.1:9190"
TIMEOUT = 60


def request_api(
    url: str,
    method: str = "post",
    data: dict[str, Any] | None = None,
    files: dict | None = None,
    content_type_is_json: bool = True,
) -> dict:
    method = method.upper()
    print(f"[URL] {url}")
    print(f"[Method] {method}")
    if data is not None:
        print(f"[Data] {data}")

    if method == "GET":
        resp = requests.get(url, timeout=TIMEOUT)
    else:
        request_data: str | dict[str, Any] | None = data
        if content_type_is_json and data is not None:
            request_data = json.dumps(data, ensure_ascii=False)
        resp = requests.post(url, data=request_data, files=files, timeout=TIMEOUT)

    try:
        content = resp.json()
    except Exception:
        content = {"code": "non-json", "status": resp.status_code, "text": resp.text}

    print(f"[Status] {resp.status_code}")
    print(f"[Response] {content}")
    return content


def set_mmr_enable(enable: bool | None = None) -> dict:
    url = f"http://{HOST}/mmr/service/enable"
    data = {"enable": enable}
    return request_api(url, method="post", data=data)


def init_mmr(instance_id: str) -> dict:
    url = f"http://{HOST}/mmr/service/init"
    data = {"instance_id": instance_id}
    return request_api(url, method="post", data=data)


def list_mmr_instances() -> dict:
    url = f"http://{HOST}/mmr/service/list"
    return request_api(url, method="get")


def delete_mmr(instance_id: str) -> dict:
    url = f"http://{HOST}/mmr/service/delete"
    data = {"instance_id": instance_id}
    return request_api(url, method="post", data=data)


def build_mmr(instance_id: str) -> dict:
    url = f"http://{HOST}/mmr/service/build"
    data = {"instance_id": instance_id}
    return request_api(url, method="post", data=data)


def list_mmr_records(instance_id: str) -> dict:
    url = f"http://{HOST}/mmr/record/list"
    data = {"instance_id": instance_id}
    return request_api(url, method="post", data=data)


def delete_mmr_record(instance_id: str, record_id: str) -> dict:
    url = f"http://{HOST}/mmr/record/delete"
    data = {"instance_id": instance_id, "record_id": record_id}
    return request_api(url, method="post", data=data)


def insert_mmr_record(
    instance_id: str,
    text: str,
    info: dict[str, Any],
    image_path: str | None = None,
) -> dict:
    url = f"http://{HOST}/mmr/record/insert"
    payload = {"instance_id": instance_id, "text": text, "info": info}
    form_data = {"data": json.dumps(payload, ensure_ascii=False)}

    if image_path is None:
        return request_api(url, method="post", data=form_data, content_type_is_json=False)

    with open(image_path, "rb") as f:
        files = {"filedata": ("sample.png", f, "image/png")}
        return request_api(url, method="post", data=form_data, files=files, content_type_is_json=False)


def query_mmr(
    instance_id: str,
    text: str = "",
    image_path: str | None = None,
    topk: int = 1,
    threshold: float = 0.0,
) -> dict:
    url = f"http://{HOST}/mmr/service/query"
    payload = {
        "instance_id": instance_id,
        "text": text,
        "topk": topk,
        "threshold": threshold,
    }
    form_data = {"data": json.dumps(payload, ensure_ascii=False)}

    if image_path is None:
        return request_api(url, method="post", data=form_data, content_type_is_json=False)

    with open(image_path, "rb") as f:
        files = {"filedata": ("query.png", f, "image/png")}
        return request_api(url, method="post", data=form_data, files=files, content_type_is_json=False)
