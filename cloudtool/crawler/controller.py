"""Application use cases. UI never manipulates download state directly."""
import asyncio
import json
import threading
from pathlib import Path
from .repository import Repository
from .models import seeds, Settings
from .engine import Engine
from .quality import assess
from .artifacts import settle, clear_cache, purge_task
from .metrics import presentation, local_time


class CaptureController:
    def template_limit(self):
        from .size_policy import limit_mb
        repo = Repository(self.root)
        try: return limit_mb(repo)
        finally: repo.close()

    def enforce_template_limit(self, maximum=None):
        from .size_policy import limit_mb, validate_mb, exceeds, discard
        with self.prepare_lock:
            repo = Repository(self.root)
            try:
                if maximum is not None:
                    repo.preference('template_limit_mb', str(validate_mb(maximum)))
                maximum = limit_mb(repo)
                for task in repo.tasks(metrics=False):
                    if task['state'] in ('等待', '采集中', '整理中'): continue
                    try:
                        if exceeds(repo, task, maximum): discard(repo, task['id'], maximum)
                    except (OSError, ValueError) as exc:
                        repo.update_task(task['id'], '删除失败', str(exc))
                return repo.tasks()
            finally: repo.close()

    def __init__(self, root, *, recover=True):
        self.root = Path(root)
        self.prepare_lock = threading.Lock()
        if recover:
            self.recover()

    def recover(self):
        """Disk recovery belongs on a worker when used by the desktop view."""
        repo = Repository(self.root)
        try:
            for task in repo.tasks(include_deleted=True, metrics=False):
                if task.get('purge_pending'):
                    try:
                        purge_task(repo, task['id'])
                    except (OSError, ValueError):
                        pass
            # An interrupted process leaves a recoverable task, never a fake success.
            for task in repo.tasks(metrics=False):
                if task['state'] in ('采集中', '整理中', '等待'):
                    repo.update_task(task['id'], '已暂停', '上次运行中断；选择任务后点击继续采集')
                elif not task['work'] or task['published']:
                    rows = repo.rows(task['id'])
                    sizes = {r['path']:r['size'] for r in rows if r['state'] == 'done'}
                    verdict = assess(task['seed'], rows, repo.warnings(task['id']), sum(sizes.values()))
                    try:
                        if not task['work'] or not verdict.publish:
                            settle(repo, task, verdict.publish)
                            repo.update_task(task['id'], verdict.state, verdict.detail)
                    except (OSError, ValueError) as exc:
                        repo.update_task(task['id'], '需检查目录', str(exc))
        finally:
            repo.close()

    def snapshot(self):
        repo = Repository(self.root)
        try:
            return repo.tasks()
        finally:
            repo.close()

    def pending_input(self, text=None):
        draft = Repository.pending_input(self.root, text)
        if draft is None:
            # First upgrade restores unfinished jobs from existing history.
            draft = '\n'.join(dict.fromkeys(t['seed'] for t in reversed(self.snapshot()) if not t['published']))
        repo = Repository(self.root)
        try:
            removed = {t['seed'] for t in repo.tasks(include_deleted=True, metrics=False)
                       if t.get('deleted') and t['state'] == '已自动清理'}
        finally:
            repo.close()
        kept = []
        for value in draft.splitlines():
            try:
                if set(seeds(value)) & removed: continue
            except ValueError:
                pass
            kept.append(value)
        return '\n'.join(kept)

    def save_input(self, text):
        """Saving an editor draft must not open or scan the capture database."""
        Repository.pending_input(self.root, text)

    def create(self, text, output, settings):
        urls = seeds(text)
        values = settings.validate()
        if not output.strip():
            raise ValueError('请先选择模板保存目录')
        repo = Repository(self.root)
        try:
            ids = repo.create(urls, output, values)
            repo.preference('output_directory', str(Path(output).resolve()))
            return ids
        finally:
            repo.close()

    def prepare(self, text, output, settings):
        """Reuse recorded captures; called by the background worker, never the view."""
        with self.prepare_lock:
            return self._prepare(text, output, settings)

    def _prepare(self, text, output, settings):
        urls = seeds(text)
        settings.validate()
        if not output.strip():
            raise ValueError('请先选择模板保存目录')
        repo = Repository(self.root)
        try:
            existing = {}
            aliases = repo.home_aliases()
            for task in repo.tasks(include_deleted=True, metrics=False):
                if task.get('deleted') and not task['published']:
                    continue
                existing.setdefault(task['seed'], task)
                home = aliases.get(task['id'])
                if home:
                    existing.setdefault(home, task)
            run, skipped, fresh = [], [], []
            for url in urls:
                task = existing.get(url)
                if not task:
                    fresh.append(url)
                elif task['published'] and self.saved_files_exist(repo, task):
                    skipped.append(url)
                else:
                    run.append(task['id'])
            if fresh:
                run.extend(repo.create(fresh, output, settings.validate()))
            repo.preference('output_directory', str(Path(output).resolve()))
            return list(dict.fromkeys(run)), skipped, repo.tasks()
        finally:
            repo.close()

    @staticmethod
    def saved_files_exist(repo, task):
        folder = Path(task['output'])
        if not (folder / 'index.html').is_file():
            return False
        try:
            return all((folder / row['path']).stat().st_size == row['size']
                       for row in repo.db.execute("SELECT DISTINCT path,size FROM urls WHERE task=? AND state='done'", (task['id'],)))
        except OSError:
            return False

    def output_directory(self, desktop):
        repo = Repository(self.root)
        try:
            chosen = repo.preference('output_directory')
            if chosen and Path(chosen).resolve() == (Path(desktop) / '采集模板').resolve():
                chosen = ''
            folder = Path(chosen or Path(desktop) / 'WebsiteTemplates')
            folder.mkdir(parents=True, exist_ok=True)
            return str(folder)
        finally:
            repo.close()

    def preview_directory(self, key):
        repo = Repository(self.root)
        try:
            task = repo.task(key)
            if task.get('deleted') or task['state'] in ('等待', '采集中', '整理中'):
                raise ValueError('此任务仍在执行，请结束或暂停后预览。')
            folder = Path(task['output'] if task['published'] else (task['work'] or task['output']))
            if not (folder / 'index.html').is_file():
                raise ValueError('此任务没有已保存的首页文件，无法预览；可查看详细报告并重试。')
            return folder
        finally:
            repo.close()

    def delete_task(self, key):
        self.delete_tasks([key])

    def delete_tasks(self, keys):
        with self.prepare_lock:
            repo = Repository(self.root)
            try:
                repo.db.executemany('UPDATE tasks SET deleted=1,purge_pending=1,revision=revision+1 WHERE id=?', ((key,) for key in set(keys)))
                repo.db.commit()
            finally:
                repo.close()

    def cleanup_deleted(self):
        repo = Repository(self.root)
        try:
            for task in repo.tasks(include_deleted=True, metrics=False):
                if task.get('purge_pending') and task['state'] not in ('等待', '采集中', '整理中'):
                    purge_task(repo, task['id'])
            return repo.tasks()
        finally:
            repo.close()

    def clear_cache(self, key):
        repo = Repository(self.root)
        try:
            clear_cache(repo, repo.task(key))
        finally:
            repo.close()

    def remember_output(self, folder):
        path = Path(folder).resolve()
        path.mkdir(parents=True, exist_ok=True)
        repo = Repository(self.root)
        try:
            repo.preference('output_directory', str(path))
        finally:
            repo.close()

    def run_job(self, ids, cancel, transport=None, settings=None, incoming=None):
        ids = tuple(ids)
        def job(report):
            repo = Repository(self.root)
            try:
                for key in ids:
                    repo.upgrade_settings(key, settings.validate() if settings else None)
                asyncio.run(Engine(repo, cancel, report, transport).run(ids, incoming))
                for task in repo.tasks(include_deleted=True, metrics=False):
                    if task.get('purge_pending'):
                        try:
                            purge_task(repo, task['id'])
                        except (OSError, ValueError):
                            pass
                return repo.tasks()
            finally:
                repo.close()
        return job

    def detail(self, key):
        repo = Repository(self.root)
        try:
            task = repo.task(key)
            rows = repo.db.execute("SELECT url,error FROM urls WHERE task=? AND state='failed' LIMIT 200", (key,)).fetchall()
            errors = [r['url'] + '\n  ' + r['error'] for r in rows]
            warnings = repo.warnings(key)
            location = ('模板目录：' + task['output']) if task['published'] else ('尚未生成模板；断点缓存：' + (task['work'] or task['output']))
            display = presentation(task)
            average = (f'{task.get("transferred_bytes", 0) / max(.001, task["elapsed_seconds"]) / 1024:.0f} KB/s'
                       if task.get('elapsed_seconds') is not None else '未记录')
            timing = f'开始：{local_time(task.get("started_at"))}　结束：{display["ended"]}　运行耗时：{display["elapsed"]}　平均速度：{average}'
            return '\n'.join([task['seed'], location, timing, task['detail'],
                              '任务编号：' + key + '；.clouddesk-capture-work 为按任务隔离的断点缓存，可用“清理失败缓存”释放空间。',
                              '剩余时间：页面和资源仍可能继续发现，暂不提供不可靠的完成倒计时。' if task['state'] in ('采集中', '整理中') else '',
                              '失败文件（最多显示 200 项；继续采集会重试全部失败项）：', *errors,
                              '范围与完整性提示：', *warnings,
                              '说明：JS 文件会保存，但不执行脚本发现运行时接口。需要登录、验证码或动态接口的网站可能无法离线完整还原。'])
        finally:
            repo.close()
