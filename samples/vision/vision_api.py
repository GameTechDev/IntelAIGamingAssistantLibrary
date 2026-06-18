
import os
import io
import time
import json
import hashlib
import requests

from rich.progress import Progress, TaskID
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

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


def init_vision(instance_id: str):
    
    url = f"http://{HOST}/vision/service/init/{instance_id}"
    resp_data = request_api(url)
    return resp_data

def list_vision_instances() -> dict:
    url = f"http://{HOST}/vision/service/list"
    resp_data = request_api(url, method='GET')
    return resp_data

def insert_vision(instance_id: str, scene_id: str, pictures: list[str], pictures_id: list[str], mode: str='accurate', mask_file: str = None) -> dict:
    
    url = f"http://{HOST}/vision/scene/insert/{instance_id}/{scene_id}"
    files = [ ("pictures", open(pic, "rb")) for pic in pictures ]
    if mask_file is not None:
        files.append(("mask_file", open(mask_file, "rb")))
    
    data = { "pictures_id": pictures_id, "mode": mode }
    print(f'[Files] {pictures}')
    print(f'[Mask] {mask_file}')
    print(f'[Data] {data}')

    try:
        resp_data = request_api(url, data=data, files=files, content_type_is_json=False)
    finally:
        for f in files:
            f[1].close()

    return resp_data

def list_vision_scenes(instance_id: str) -> dict:
    
    url = f"http://{HOST}/vision/scene/list/{instance_id}"
    resp_data = request_api(url, method='GET')
    return resp_data

def list_vision_scene_pictures(instance_id: str, scene_id: str) -> dict:
    
    url = f"http://{HOST}/vision/scene/picture/list/{instance_id}/{scene_id}"
    resp_data = request_api(url, method='GET')
    return resp_data

def delete_vision(instance_id: str) -> dict:
    
    url = f"http://{HOST}/vision/service/delete/{instance_id}"
    resp_data = request_api(url)
    return resp_data

def delete_vision_scene(instance_id: str, scene_id: str) -> dict:
    
    url = f"http://{HOST}/vision/scene/delete/{instance_id}/{scene_id}"
    resp_data = request_api(url)
    return resp_data

def delete_vision_picture(instance_id: str, scene_id: str, pictures_id: list[str]) -> dict:
    
    url = f"http://{HOST}/vision/scene/picture/delete/{instance_id}/{scene_id}"
    print(f'[URL] {url}')
    
    data = { "pictures_id": pictures_id }
    print(f'[Data] {data}')
    
    resp_data = request_api(url, data=data)
    
    return resp_data

def build_vision(instance_id: str, full_build=False) -> dict:
    
    url = f"http://{HOST}/vision/service/build/{instance_id}"
    headers = { "Accept": "text/event-stream" }
    data = json.dumps({'full_build': full_build})
    
    resp = requests.post(url, headers=headers, data=data, stream=True)
    
    resp_data = None
    with Progress() as progress:
        task: TaskID = None
        for chunk in resp.iter_content(chunk_size=1024):
            resp_str = chunk.decode("utf-8")
            lines = resp_str.split('\n')
            for line in lines:
                if line.startswith('data: '):
                    resp_data = json.loads(resp_str.lstrip('data:').strip())
                    code = resp_data.get('code')
                    fin = resp_data.get('fin')
                    data = resp_data.get('data', {})
                    event_name = data.get('event_name')
                    total = data.get('total', 0)
                    current = data.get('current', 0)
                    picture_id = data.get('picture_id')
                    
                    if event_name == 'build_init' and task is None:
                        task = progress.add_task('Building', total=None)
                    elif task is not None:
                        if event_name == 'build_progress':
                            progress.update(task, description=f"Building {picture_id}", total=total, completed=current)
                        elif fin:
                            if code == 'ok':
                                progress.update(task, description=f"Build finished")
                            else:
                                progress.update(task, description=f"Build failed")
    
    return resp_data

def query_vision(instance_id: str, file: str, mask_file: str=None, topk: int=1, threshold: float=0.92, threshold_2: float=0.15) -> dict:
    
    url = f"http://{HOST}/vision/service/query/{instance_id}"
    files = { "file": open(file, "rb") }
    print(f'[URL] {url}')
    
    if mask_file is not None:
        files["mask_file"] = open(mask_file, "rb")
    
    data = { "topk": topk, "threshold": threshold, "threshold_2": threshold_2 }
    
    print(f'[Files] {file}')
    print(f'[Mask] {mask_file}')
    print(f'[Data] {data}')
    
    resp_data = request_api(url, data=data, files=files, content_type_is_json=False)
    
    for f in files.values():
        f.close()
    
    return resp_data

def export_vision(instance_id: str, scene_id: str, stream=True, progress: Progress=None):
    
    url = f"http://{HOST}/vision/scene/export/{instance_id}/{scene_id}"
    print(f'[URL] {url}')
    
    resp = requests.get(url, stream=stream)
    headers = resp.headers
    
    if stream:
        private_data_header = json.loads(headers.get('private-data-header'))
        file_size = private_data_header.get('size')
        file_size_mb = file_size / 1024 / 1024
        downloaded_size = 0
        start_time = time.time()
        iobytes = io.BytesIO()
        
        message = None
        task: TaskID = progress.add_task(f'Start downloading file', total=file_size)
        for chunk in resp.iter_content(1024*1024*8):
            downloaded_size += iobytes.write(chunk)
            downloaded_size_mb = downloaded_size / 1024 / 1024
            elapsed_time = time.time() - start_time
            if elapsed_time == 0:
                elapsed_time = 1
            speed_bytes = downloaded_size / elapsed_time
            speed_mb = speed_bytes / 1024 / 1024
            
            message = f'({downloaded_size_mb:.2f}M/{file_size_mb:.2f}M, {speed_mb:.2f}M/s) {scene_id}'
            
            progress.update(task, description=message, completed=downloaded_size)
        
        content = iobytes.getvalue()
        
        sha256_str = private_data_header.get('sha256')
        sha256 = hashlib.sha256(content)
        if sha256_str == sha256.hexdigest():
            message = f'{message} ok'
        else:
            message = f'{message} modified'
        
        progress.update(task, description=message)
    else:
        content = resp.content
    
    return headers, content

def batch_export_vision(instance_id: str, scenes_id: list[str], stream=True, save_file: str=None):
    
    url = f"http://{HOST}/vision/scene/batch/export/{instance_id}"
    data = { "scenes_id": scenes_id }
    print(f'[URL] {url}')
    print(f'[Data] {data}')
    
    resp_content = request_api(url, data=data, stream=stream)
    
    with open(save_file, 'wb') as f:
        f.write(resp_content)

def import_vision(instance_id: str, scene_id: str, private_data: bytes, progress: Progress=None):
    url = f"http://{HOST}/vision/scene/import/{instance_id}/{scene_id}"
    print(f'[URL] {url}')
    
    fields = { "file": ('private_data', private_data) }
    multipart = MultipartEncoder(fields=fields)
    print(f'[Fields] #private_data={len(private_data)}')
    
    file_size = len(private_data)
    file_size_mb = file_size / 1024 / 1024
    task: TaskID = progress.add_task(f'Start uploading file', total=file_size)
    start_time = time.time()
    def upload_file_callback(monitor: MultipartEncoderMonitor):
        uploaded_size = monitor.bytes_read
        uploaded_size_mb = uploaded_size / 1024 / 1024
        elapsed_time = time.time() - start_time
        if elapsed_time == 0:
            elapsed_time = 1
        
        speed_bytes = uploaded_size / elapsed_time
        speed_mb = speed_bytes / 1024 / 1024
        message = f'({uploaded_size_mb:.2f}M/{file_size_mb:.2f}M, {speed_mb:.2f}M/s) {scene_id}'
        progress.update(task, description=message, completed=uploaded_size)
    
    multipart = MultipartEncoderMonitor(multipart, upload_file_callback)
    resp = requests.post(url, data=multipart, headers={'Content-Type': multipart.content_type})
    resp_data = resp.json()
    
    return resp_data

def batch_import_vision(instance_id: str, scenes_id: list[str], private_data_files: list[str]):
    url = f"http://{HOST}/vision/scene/batch/import/{instance_id}"
    print(f'[URL] {url}')
    
    fields = [("scenes_id", scene_id) for scene_id in scenes_id]
    fields_files = [("files", (os.path.basename(file), open(file, "rb"))) for file in private_data_files ]
    
    fields = fields_files + fields
    print(f'[Fields] {private_data_files}')
    
    multipart = MultipartEncoder(fields=fields)
    
    try:
        with Progress() as progress:
            task: TaskID = progress.add_task(f'Start uploading file')
            start_time = time.time()
            def upload_file_callback(monitor: MultipartEncoderMonitor):
                file_size = monitor.len
                file_size_mb = file_size / 1024 / 1024
                uploaded_size = monitor.bytes_read
                uploaded_size_mb = uploaded_size / 1024 / 1024
                elapsed_time = time.time() - start_time
                if elapsed_time == 0:
                    elapsed_time = 1
                
                speed_bytes = uploaded_size / elapsed_time
                speed_mb = speed_bytes / 1024 / 1024
                message = f'({uploaded_size_mb:.2f}M/{file_size_mb:.2f}M, {speed_mb:.2f}M/s)'
                progress.update(task, description=message, total=file_size, completed=uploaded_size)
            
            multipart = MultipartEncoderMonitor(multipart, upload_file_callback)
            resp = requests.post(url, data=multipart, headers={'Content-Type': multipart.content_type})
            resp_data = resp.json()
    finally:
        for f in fields_files:
            f[1][1].close()
    
    return resp_data
