"""Provider registry. Additional platforms implement their own adapter and UI factory."""
import importlib.util
import json
import re
import sys
from pathlib import Path

PROVIDERS = {}


def register(key, title, adapter=None, factory=None):
    if key in PROVIDERS:
        raise ValueError(f"Duplicate provider: {key}")
    PROVIDERS[key] = {"title": title, "adapter": adapter, "factory": factory}


def load_plugin(folder):
    """Explicit local opt-in, not automatic execution of arbitrary directories."""
    folder = Path(folder).resolve()
    info = json.loads((folder / 'module.json').read_text('utf-8'))
    key, title = info['id'], info['title']
    if info.get('api_version') != 1 or not re.fullmatch('[a-z][a-z0-9_]{1,39}', key):
        raise ValueError('模块描述格式或 API 版本无效')
    if key in PROVIDERS:
        raise ValueError('模块标识已注册，请先移除原模块')
    entry = (folder / info['entry']).resolve()
    if not entry.is_relative_to(folder) or entry.suffix != '.py' or not entry.is_file():
        raise ValueError('模块入口必须是所选目录内的 Python 文件')
    name = 'clouddesk_plugin_' + key
    spec = importlib.util.spec_from_file_location(name, entry, submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        factory = getattr(module, 'create_workspace')
        if not callable(factory): raise ValueError('模块缺少 create_workspace')
        register(key, str(title)[:60], factory=factory)
        PROVIDERS[key]['external'] = name
    except Exception:
        sys.modules.pop(name, None)
        raise
    return key


