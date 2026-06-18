
import io
import time
import json
import requests

from typing import Any

from rich.progress import Progress, TaskID

HOST = "127.0.0.1:9190"

def download_file(resp: requests.Response, stream: bool = False):
    headers = resp.headers
    content_length = headers.get('content-length')
    
    if stream and content_length is not None:
        file_size = int(content_length)
        file_size_mb = file_size / 1024 / 1024
        downloaded_size = 0
        start_time = time.time()
        
        message = None
        
        content = io.BytesIO()
        with Progress() as progress:
            task: TaskID = progress.add_task(f'Start downloading file', total=file_size)
            for chunk in resp.iter_content(1024*8):
                downloaded_size += content.write(chunk)
                downloaded_size_mb = downloaded_size / 1024 / 1024
                elapsed_time = time.time() - start_time
                if elapsed_time == 0:
                    elapsed_time = 1
                speed_bytes = downloaded_size / elapsed_time
                speed_mb = speed_bytes / 1024 / 1024
                
                message = f'({downloaded_size_mb:.2f}M/{file_size_mb:.2f}M, {speed_mb:.2f}M/s)'
                progress.update(task, description=message, completed=downloaded_size)
            
            message = f'{message} done'
            
            progress.update(task, description=message)
        
        return content.getvalue()
    else:
        return resp.content
    

def request_api(url: str, method: str = 'post', headers: dict | None = None, data: str | dict | None = None, files: list | None = None, stream: bool = False, content_type_is_json = True) -> dict:
    method = method.upper()
    print(f'[URL] {url}')
    print(f'[Method] {method}')
    
    if headers is not None and len(headers) > 0:
        print(f'[Headers] {headers}')
    
    if data is not None and len(data) > 0:
        print(f'[Data] {data}')
    
    if files is not None and len(files) > 0:
        print(f'[Files] {files}')
    
    resp = None
    if method == 'GET':
        resp = requests.get(url, headers=headers, stream=stream)
    else:
        if content_type_is_json:
            data = json.dumps(data, ensure_ascii=False)
        
        resp = requests.post(url, headers=headers, data=data, files=files, stream=stream)
    
    content = None
    if resp is not None:
        resp_headers = resp.headers
        print(f'[Response Headers] {resp_headers}')
        
        resp_content_type = resp_headers.get('content-type')
        if resp_content_type == 'application/json':
            content = resp.json()
            print(f'<resp> content: {content}')
        else:
            content = download_file(resp, stream)
            print(f'<resp> content-length: {len(content)}')
    
    return content


def init_instance(instance_id: str):
    url = f"http://{HOST}/memory/service/init"
    data = { "instance_id": instance_id }
    resp_data = request_api(url, 'post', data=data)
    return resp_data

def list_instance():
    url = f"http://{HOST}/memory/service/list"
    resp_data = request_api(url, 'get')
    return resp_data

def delete_instance(instance_id: str):
    url = f"http://{HOST}/memory/service/delete"
    data = { "instance_id": instance_id }
    resp_data = request_api(url, 'post', data=data)
    return resp_data

def list_record(instance_id: str, indices: list[int] | int | None = None, tags: list[str] | None = None, tags_op: str = "&&", keys: list[str] | None = None, props: list[str] | None = None, return_image_data: bool = False):
    url = f"http://{HOST}/memory/record/list"
    data = { "instance_id": instance_id, "indices": indices, "tags": tags, "tags_op": tags_op, "keys": keys, "props": props, "return_image_data": return_image_data }
    resp_data = request_api(url, 'post', data=data)
    return resp_data

def delete_record(instance_id: str, record_id: str):
    url = f"http://{HOST}/memory/record/delete"
    data = { "instance_id": instance_id, "record_id": record_id }
    resp_data = request_api(url, 'post', data=data)
    return resp_data

def insert_record(instance_id: str, record_id: str, info: dict[str, Any], tags: list[str] | None = None, emb_props: list[str] | None = None, images: list[str] | None = None):
    url = f"http://{HOST}/memory/record/insert"
    data = { "instance_id": instance_id, "record_id": record_id, "info": info, "tags": tags, "emb_props": emb_props }
    data = {'data': json.dumps(data, ensure_ascii=False)}
    files = None if images is None else [ ("images", open(image, 'rb')) for image in images ]
    resp_data = request_api(url, 'post', data=data, files=files, content_type_is_json=False)
    if images is not None:
        [ f[1].close() for f in files ]
    return resp_data

def search_instance(instance_id: str, conditions: list[dict[str, Any]], tags: list[str] | None = None, tags_op: str = "&&", agg: dict | None = None, keys: list[str] | None = None, props: list[str] | None = None, return_image_data: bool = False):
    url = f"http://{HOST}/memory/service/search"
    data = { "instance_id": instance_id, "conditions": conditions, "tags": tags, "tags_op": tags_op, "agg": agg, "keys": keys, "props": props, "return_image_data": return_image_data }
    resp_data = request_api(url, 'post', data=data)
    return resp_data

def search_text(instance_id: str, text: str, topk: int = 5, threshold: float = 0.5, tags: list[str] | None = None, tags_op: str = "&&", keys: list[str] | None = None, props: list[str] | None = None, return_image_data: bool = False):
    url = f"http://{HOST}/memory/service/search/text"
    data = { "instance_id": instance_id, "text": text, "topk": topk, "threshold": threshold, "tags": tags, "tags_op": tags_op, "keys": keys, "props": props, "return_image_data": return_image_data }
    resp_data = request_api(url, 'post', data=data)
    return resp_data

def search_image(instance_id: str, image: str, topk: int = 5, threshold: float = 0.92, threshold_2: float = 0.15, tags: list[str] | None = None, tags_op: str = "&&", keys: list[str] | None = None, props: list[str] | None = None, return_image_data: bool = False):
    url = f"http://{HOST}/memory/service/search/image"
    data = { "instance_id": instance_id, "topk": topk, "threshold": threshold, "threshold_2": threshold_2, "tags": tags, "tags_op": tags_op, "keys": keys, "props": props, "return_image_data": return_image_data }
    data = { "data": json.dumps(data, ensure_ascii=False) }
    files = [ ("image", open(image, 'rb')) ]
    resp_data = request_api(url, 'post', data=data, files=files, content_type_is_json=False)
    [ f[1].close() for f in files ]
    return resp_data

def build_instance(instance_id: str):
    url = f"http://{HOST}/memory/service/build"
    data = { "instance_id": instance_id }
    resp_data = request_api(url, 'post', data=data)
    return resp_data
