"""Keep unfinished captures separate from accepted site folders, without deleting data."""
from pathlib import Path
from .models import site_folder

CACHE_NAME = '.clouddesk-capture-work'


def workspace(output, key):
    output = Path(output).absolute()
    return output.parent / CACHE_NAME / key


def checked(task, path):
    output = Path(task['output']).absolute()
    if output.name != site_folder(task['seed'], task['id']):
        raise ValueError('采集目录身份不匹配，停止移动文件，请检查任务记录')
    path = Path(path).absolute()
    if path not in (output, workspace(output, task['id'])):
        raise ValueError('采集缓存路径异常，停止移动文件')
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('采集目录含链接，停止移动文件')
    return path


def settle(repo, task, publish):
    source = checked(task, task.get('work') or task['output'])
    if not source.exists() and Path(task['output']).exists():
        source = checked(task, task['output'])
    target = checked(task, task['output'] if publish else workspace(task['output'], task['id']))
    if source != target:
        if target.exists() and source.exists():
            raise ValueError('目标目录已存在，未覆盖；请检查采集目录后重试')
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    repo.set_work(task['id'], str(target), publish)
    if not publish:
        target.mkdir(parents=True, exist_ok=True)
    elif source.parent.name == CACHE_NAME:
        try:
            source.parent.rmdir()
        except OSError:
            pass
    return target


def clear_cache(repo, task):
    """Only remove verified unpublished task data; never remove accepted output."""
    import shutil
    import re
    if task['published'] or task['state'] in ('采集中', '整理中', '等待'):
        raise ValueError('只能清理已停止且未生成模板的任务缓存')
    key = task['id']
    if not re.fullmatch(r'[0-9a-f]{32}', key):
        raise ValueError('任务编号无效')
    cache = checked(task, workspace(task['output'], key))
    sources = repo.root / 'sources' / key
    for folder in (cache, sources):
        for item in (folder, *folder.parents):
            if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                raise ValueError('缓存目录包含链接，停止清理')
        if folder.exists():
            for item in folder.rglob('*'):
                if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                    raise ValueError('缓存内包含链接，停止清理')
    for folder in (cache, sources):
        if folder.exists():
            shutil.rmtree(folder)
    try:
        cache.parent.rmdir()
    except OSError:
        pass
    repo.db.execute("UPDATE urls SET state='pending',size=0,hash='',error='' WHERE task=?", (key,))
    repo.update_task(key, '已清理', '此任务断点缓存已清理；记录保留，继续采集将重新下载。')


# Serialize cleanup requested by the UI and by a finishing worker.
from threading import RLock
_purge_lock = RLock()


def purge_task(repo, key):
    import shutil
    import re
    with _purge_lock:
        task = repo.task(key)
        if not task.get('purge_pending'):
            return
        if not re.fullmatch(r'[0-9a-f]{32}', key):
            raise ValueError('任务编号无效，停止删除')
        folders = [checked(task, task['output']), checked(task, workspace(task['output'], key)), repo.root / 'sources' / key]
        try:
            for folder in folders:
                for item in (folder, *folder.parents):
                    if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                        raise ValueError('任务目录包含链接，停止删除')
                if folder.exists():
                    for item in folder.rglob('*'):
                        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                            raise ValueError('任务目录内包含链接，停止删除')
            for folder in folders:
                if folder.exists():
                    shutil.rmtree(folder)
            repo.db.execute('UPDATE tasks SET purge_pending=0,published=0,work=? WHERE id=?', ('',key))
            repo.db.execute('DELETE FROM urls WHERE task=?',(key,))
            repo.db.execute('DELETE FROM warnings WHERE task=?',(key,))
            repo.db.commit()
        except (OSError, ValueError) as exc:
            repo.db.execute('UPDATE tasks SET deleted=0,purge_pending=0 WHERE id=?',(key,))
            repo.update_task(key, '删除失败', '未能完全删除目录，请关闭占用文件后重试：' + str(exc))
            raise


def purge_at(root, key):
    """Background filesystem cleanup with a thread-owned database connection."""
    from .repository import Repository
    repo = Repository(root)
    try:
        purge_task(repo, key)
    finally:
        repo.close()
