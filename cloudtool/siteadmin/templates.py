"""Read-only template inventory, content fingerprints and bounded ZIP creation."""
import hashlib
import os
import stat
import time
import zipfile
import json
from pathlib import Path
from ..models import Cancelled
from ..file_types import binary_type

MAX_ZIP = 300 * 1024 * 1024


def files(root, cancel, progress=None, metadata=None, validate_html=True):
    root = Path(root).absolute()
    if '.clouddesk-capture-work' in root.parts:
        raise ValueError('这是采集断点缓存，尚未通过验收；请回到网站采集继续任务')
    if root.is_symlink() or root.is_junction(): raise ValueError('模板不支持链接或目录联接')
    found = []
    last_report = 0.; total = 0; pending = [root]
    while pending:
        folder = pending.pop()
        if cancel.is_set(): raise Cancelled()
        with os.scandir(folder) as entries:
            for entry in entries:
                if cancel.is_set(): raise Cancelled()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
                    raise ValueError(f'模板包含链接：{entry.name}')
                if progress and time.monotonic()-last_report >= .2:
                    progress(f'扫描 {root.name} · {len(found)} 个文件 / {total/1048576:.1f} MB · {entry.name}')
                    last_report=time.monotonic()
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path));continue
                if not stat.S_ISREG(info.st_mode): raise ValueError('模板包含非常规文件')
                path = Path(entry.path)
                total += info.st_size
                if total > 1024**3: raise ValueError('模板解压体积超过后台 1 GB 上限')
                if validate_html and path.suffix.lower() in ('.html','.htm'):
                    with path.open('rb') as source: actual=binary_type(source.read(32))
                    if actual:raise ValueError(f'{path.relative_to(root)}：扩展名为 HTML，实际为 {actual[0]}；不能上传，请修复文件类型及引用后重试')
                found.append(path)
                if metadata is not None:
                    metadata.append((path.relative_to(root).as_posix(),info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_ino))
                if len(found) > 50000: raise ValueError('模板文件数超过后台 50000 上限，请拆分')
    if not found: raise ValueError(f'空模板目录：{root.name}')
    if not any(p.suffix.lower() in ('.html','.htm') for p in found): raise ValueError(f'{root.name}：未发现 HTML 页面')
    return sorted(found, key=lambda p:p.relative_to(root).as_posix())


def digest(root, cancel, archive=None, progress=None, cache=None):
    root = Path(root).absolute(); result = hashlib.sha256(); total = 0
    metadata=[]
    paths=files(root,cancel,progress,metadata,validate_html=False)
    signature=hashlib.sha256(json.dumps(sorted(metadata),ensure_ascii=False).encode()).hexdigest()
    if cache is not None and archive is None:
        saved=cache.cached_digest(str(root),signature)
        if saved:
            if progress:progress(f'校验 {root.name} · {len(paths)} 个文件未变化，复用指纹；上传前重新校验内容')
            return saved
    last_report = 0.
    for number,path in enumerate(paths,1):
        if cancel.is_set(): raise Cancelled()
        relative = path.relative_to(root).as_posix()
        result.update(relative.encode()); result.update(b'\0')
        content = hashlib.sha256(); size = 0
        output = archive.open(relative, 'w', force_zip64=True) if archive else None
        try:
            with path.open('rb') as source:
                while block := source.read(1024*1024):
                    if cancel.is_set(): raise Cancelled()
                    if size == 0 and path.suffix.lower() in ('.html','.htm'):
                        actual=binary_type(block[:32])
                        if actual:raise ValueError(f'{relative}：扩展名为 HTML，实际为 {actual[0]}；不能上传，请修复文件类型及引用后重试')
                    total += len(block); size += len(block)
                    if total > 1024**3: raise ValueError('模板解压体积超过后台 1 GB 上限')
                    if progress and time.monotonic()-last_report >= .2:
                        progress(f'校验 {root.name} · 文件 {number}/{len(paths)} · 已读取 {total/1048576:.1f} MB · {path.name}')
                        last_report=time.monotonic()
                    content.update(block)
                    if output: output.write(block)
        finally:
            if output: output.close()
        result.update(str(size).encode()+b'\0'+content.digest())
        if archive and archive.fp.tell() > MAX_ZIP: raise ValueError('压缩包超过后台 300 MB 限制')
    value=result.hexdigest()
    if cache is not None and archive is None:cache.save_digest(str(root),signature,value)
    return value


def template_paths(root):
    root = Path(root).expanduser().absolute()
    if not root.is_dir() or root.is_symlink() or root.is_junction(): raise ValueError('请选择真实的模板父目录')
    children = sorted((p for p in root.iterdir() if p.is_dir() and p.name != '.clouddesk-capture-work'),key=lambda p:p.name.casefold())
    if not children:
        if (root / '.clouddesk-capture-work').exists():
            raise ValueError('暂无通过验收的站点模板；请先在网站采集中完成或恢复任务，断点缓存不参与分配')
        raise ValueError('父目录中没有站点子文件夹')
    return children

def inventory(root, cancel):
    return [dict(path=str(p),digest=digest(p,cancel),name=p.name) for p in template_paths(root)]


def pack(template, destination, cancel):
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        actual = digest(template['path'],cancel,archive)
    if actual != template['digest']: raise ValueError('模板内容在预览后变化，请重新预览')
    if Path(destination).stat().st_size > MAX_ZIP: raise ValueError('压缩包超过 300 MB')
