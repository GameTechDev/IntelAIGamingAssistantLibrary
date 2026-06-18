
import os
import io
import time
import json
import requests

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


def init_knowledge(instance_id: str):
    
    url = f"http://{HOST}/knowledge/service/init/{instance_id}"
    resp_data = request_api(url)
    return resp_data

def list_knowledge_instances() -> dict:
    url = f"http://{HOST}/knowledge/service/list"
    resp_data = request_api(url, method='GET')
    return resp_data

def insert_knowledge(instance_id: str, knowledge_id: str, texts: list[str], texts_id: list[str], texts_metadata: dict = None) -> dict:
    
    url = f"http://{HOST}/knowledge/knowledge/insert/{instance_id}/{knowledge_id}"
    files = [ ("texts", open(text, "rb")) for text in texts ]
    data = { "texts_id": texts_id }
    if texts_metadata is not None and len(texts_metadata) > 0:
        data["texts_metadata"] = texts_metadata
    
    print(f'[Files] {texts}')
    print(f'[Data] {data}')

    try:
        resp_data = request_api(url, data=data, files=files, content_type_is_json=False)
    finally:
        for f in files:
            f[1].close()

    return resp_data

def list_knowledge_knowledgebase(instance_id: str) -> dict:
    
    url = f"http://{HOST}/knowledge/knowledge/list/{instance_id}"
    resp_data = request_api(url, method='GET')
    return resp_data

def list_knowledge_knowledgebase_texts(instance_id: str, knowledge_id: str) -> dict:
    
    url = f"http://{HOST}/knowledge/knowledge/text/list/{instance_id}/{knowledge_id}"
    resp_data = request_api(url, method='GET')
    return resp_data

def delete_knowledge(instance_id: str) -> dict:
    
    url = f"http://{HOST}/knowledge/service/delete/{instance_id}"
    resp_data = request_api(url)
    return resp_data

def delete_knowledge_knowledgebase(instance_id: str, knowledge_id: str) -> dict:
    
    url = f"http://{HOST}/knowledge/knowledge/delete/{instance_id}/{knowledge_id}"
    resp_data = request_api(url)
    return resp_data

def delete_knowledge_text(instance_id: str, knowledge_id: str, texts_id: list[str]) -> dict:
    
    url = f"http://{HOST}/knowledge/knowledge/text/delete/{instance_id}/{knowledge_id}"
    data = { "texts_id": texts_id }
    print(f'[Data] {data}')

    resp_data = request_api(url, data=data)
    return resp_data

def build_knowledge(instance_id: str, full_build=False) -> dict:
    
    url = f"http://{HOST}/knowledge/service/build/{instance_id}"
    headers = { "Accept": "text/event-stream" }
    data = json.dumps({'full_build': full_build})
    
    print(f'[URL] {url}')
    print(f'[Data] {data}')
    
    resp = requests.post(url, headers=headers, data=data, stream=True)
    
    resp_data = None
    with Progress() as progress:
        task: TaskID = None
        task_text: TaskID = None
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
                    percent = data.get('percent', 0)
                    text_id = data.get('text_id')
                    
                    if event_name == 'build_init' and task is None:
                        task = progress.add_task('Building', total=None)
                        task_text = progress.add_task('', total=None)
                    elif task is not None:
                        if event_name == 'build_progress':
                            progress.update(task, description=f"Building {text_id}", total=total, completed=current)
                            progress.update(task_text, total=100, completed=percent)
                        elif fin:
                            progress.remove_task(task_text)
                            if code == 'ok':
                                progress.update(task, description=f"Build finished")
                            else:
                                progress.update(task, description=f"Build failed")
    
    return resp_data

def query_knowledge(instance_id: str, text: str, knowledge_id: list[str] = None, knowledge_id_op: str = 'or', texts_id: list[str] = None, texts_id_op: str = 'or', scenes_name: list[str] = None, scenes_name_op: str = 'orc', extra_info: dict[str, dict[str, str]] = None, system_message: str = None, prompt_template: str = None) -> dict:
    
    url = f"http://{HOST}/knowledge/service/query/{instance_id}"
    print(f'[URL] {url}')
    
    data = { "text": text }
    if knowledge_id is not None:
        data["knowledge_id"] = knowledge_id
        data["knowledge_id_op"] = knowledge_id_op
    
    if texts_id is not None:
        data["texts_id"] = texts_id
        data["texts_id_op"] = texts_id_op
    
    if scenes_name is not None:
        data["scenes_name"] = scenes_name
        data["scenes_name_op"] = scenes_name_op
    
    if extra_info is not None:
        data["extra_info"] = extra_info
    
    if system_message is not None:
        data["system_message"] = system_message
    
    if prompt_template is not None:
        data["prompt_template"] = prompt_template
    
    print(f'[Data] {data}')
    
    headers = { "Accept": "text/event-stream" }
    resp = requests.post(url, headers=headers, data=json.dumps(data), stream=True)
    
    first_resp_data = None
    resp_data = None
    full_message = None
    for chunk in resp.iter_content(chunk_size=1024):
        resp_str = chunk.decode("utf-8")
        lines = resp_str.split('\n')
        for line in lines:
            if line.startswith('data: '):
                resp_data = json.loads(line.lstrip('data:').strip())
                print(f"resp_data: {resp_data}")
                
                if first_resp_data is None:
                    first_resp_data = resp_data
                
                data = resp_data.get('data', {})
                message = data.get('message')
                if message is not None and len(message) > 0:
                    if full_message is None:
                        full_message = message
                    else:
                        full_message = f"{full_message}{message}"
                
    
    return resp_data, full_message, first_resp_data
