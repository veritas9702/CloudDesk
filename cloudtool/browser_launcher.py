"""Launch a normal installed browser, without debug flags or profile access."""
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

def browser_executable(browser):
    if browser not in ('chrome','msedge'): raise ValueError('请选择 Chrome 或 Edge')
    executable='chrome.exe' if browser=='chrome' else 'msedge.exe'
    candidates=[]
    if os.name=='nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive,'Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\'+executable) as key:
                    candidates.append(Path(winreg.QueryValue(key,None).strip('"')))
            except OSError: pass
    relative=Path('Google/Chrome/Application/chrome.exe' if browser=='chrome' else 'Microsoft/Edge/Application/msedge.exe')
    candidates.extend(Path(os.environ[key])/relative for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA') if os.environ.get(key))
    for path in candidates:
        if path.name.lower()==executable and path.is_file(): return path
    raise ValueError(('Google Chrome' if browser=='chrome' else 'Microsoft Edge')+' 未安装或无法定位，请选择已安装的浏览器。')

def open_browser(browser,url):
    parsed=urlsplit(url)
    extension_page={'chrome':'chrome://extensions/','msedge':'edge://extensions/'}.get(browser)
    if url != extension_page and (parsed.scheme!='https' or parsed.netloc!='dash.cloudflare.com'):
        raise ValueError('不支持的浏览器目标地址')
    subprocess.Popen([str(browser_executable(browser)),url],close_fds=True)
