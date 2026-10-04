"""Template disk-size policy; sources/cache copies are not counted twice."""
from .artifacts import checked, workspace, purge_task

DEFAULT_MB = 300

class Oversize(Exception):
    pass

def validate_mb(value):
    if type(value) is not int or not 1 <= value <= 1000000:
        raise ValueError('模板上限应为 1–1000000 MB')
    return value

def limit_mb(repo):
    return validate_mb(int(repo.preference('template_limit_mb') or DEFAULT_MB))

def folder_bytes(folder):
    total = 0
    if folder.exists():
        for path in folder.rglob('*'):
            if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                raise ValueError('模板内包含链接，停止自动清理')
            if path.is_file():
                total += path.stat().st_size
    return total

def exceeds(repo, task, maximum):
    # Both possible locations are identity-checked before inspection/deletion.
    return any(folder_bytes(checked(task, path)) > maximum * 1048576
               for path in (task['output'], workspace(task['output'], task['id'])))

def discard(repo, key, maximum):
    detail = f'模板超过 {maximum} MB 上限，已自动删除模板及断点缓存。'
    repo.update_task(key, '已自动清理', detail)
    repo.delete_task(key)
    purge_task(repo, key)
    return detail
