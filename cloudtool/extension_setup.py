"""Prepare static helper files separately from credentials and browser profiles."""
import json
import sys
import shutil
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
from .browser_token_model import BrowserTokenRequest
from .permissions import PRESETS,RULE_PERMISSIONS

EXTENSION_FILES=('manifest.json','catalog.js','form.js','assistant.js','bridge.js','popup.html','popup.js','popup.css','icons/16.png','icons/48.png','icons/128.png')

def setup_url(name,advanced=True):
    request=BrowserTokenRequest(name,PRESETS['常用管理'],tuple(RULE_PERMISSIONS) if advanced else ())
    url=urlsplit(request.url());query=dict(parse_qsl(url.query))
    query['clouddesk_setup']='full' if advanced else 'basic'
    return urlunsplit((url.scheme,url.netloc,url.path,urlencode(query),''))

def extension_source():
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'browser_extension'

def prepare_extension(root,source=None):
    source=Path(source) if source is not None else extension_source()
    for name in EXTENSION_FILES:
        if not (source/name).is_file(): raise ValueError('助手文件不完整，请重新解压完整程序。')
    manifest=json.loads((source/'manifest.json').read_text('utf-8'))
    if manifest.get('manifest_version')!=3: raise ValueError('助手版本无效')
    target=Path(root)/'permission-helper'
    # Keep this path stable: unpacked extensions refer to their original folder.
    target.mkdir(parents=True,exist_ok=True)
    for name in EXTENSION_FILES:
        destination=target/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,destination)
    return target
