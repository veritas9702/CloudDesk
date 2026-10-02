"""Machine-local state is never resolved relative to the portable program."""
import os
from pathlib import Path

def local_data_root():
    location = os.environ.get('LOCALAPPDATA')
    if not location:
        raise RuntimeError('无法定位 Windows 本机用户数据目录，未在程序目录写入凭据。')
    return Path(location) / 'CloudDesk'
