"""Bounded async capture engine; SQLite is the durable queue, files stream to disk."""
import asyncio
import hashlib
import json
import os
import time
import re
import shutil
import queue
from pathlib import Path
from urllib.parse import urlsplit, urljoin, quote
import httpx
from .models import canonical, local_path
from .document import html_document, css_document, svg_document
from .quality import assess, html_problem
from ..file_types import binary_type
from .artifacts import settle, purge_at
from .metrics import Meter, utc_now
from .size_policy import Oversize, exceeds, discard

# Compatibility profile for public sites that reject unknown HTTP clients.
# Keep our product identifier; this does not imply a browser/JavaScript engine.
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 CloudDeskCapture/0.16.1')


class Paused(Exception):
    pass


def checksum(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe_file(root, relative):
    root = Path(root)
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('输出路径离开了采集目录')
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('输出目录不能包含符号链接或目录联接')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class Engine:
    def __init__(self, repo, cancel, report, transport=None):
        self.repo, self.cancel, self.report = repo, cancel, report
        self.transport = transport
        self.global_slots = asyncio.Semaphore(8)
        self.host_slots = {}
        self.meters = {}
        self.checkpoints = {}

    def emit(self, key, state, detail, template_bytes=None):
        meter = self.meters.get(key)
        values = meter.snapshot() if meter else {}
        if meter and time.monotonic() - self.checkpoints.get(key, 0) >= 2:
            self.repo.save_metrics(key, values)
            self.checkpoints[key] = time.monotonic()
        task = self.repo.task(key)
        if template_bytes is not None:
            task['template_bytes'] = max(0, template_bytes)
        self.report(key, state, json.dumps(dict(detail=detail, metrics=values, task=task), ensure_ascii=False))

    async def run(self, ids, incoming=None):
        site_slots = asyncio.Semaphore(min(json.loads(self.repo.task(k)['settings'])['sites'] for k in ids))
        async with httpx.AsyncClient(transport=self.transport, follow_redirects=False,
                                    limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
                                    headers={'User-Agent': USER_AGENT}) as client:
            self.client = client

            async def one(key):
                async with site_slots:
                    if self.repo.task(key).get("deleted"):
                        try:
                            await asyncio.to_thread(purge_at, self.repo.root, key)
                        except (OSError, ValueError) as exc:
                            self.emit(key, '删除失败', str(exc))
                        return
                    if self.cancel.is_set():
                        self.repo.update_task(key, '已暂停', '点击继续采集，从已保存文件恢复')
                        self.emit(key, '已暂停', '点击继续采集，从已保存文件恢复')
                        return
                    try:
                        self.meters[key] = Meter(self.repo.task(key))
                        self.repo.save_metrics(key, self.meters[key].snapshot())
                        capture = Capture(self, self.repo.task(key))
                        await capture.run()
                    except Oversize:
                        try:
                            maximum = capture.settings.get('template_limit_mb', 300)
                            # All download coroutines have exited before deleting their files.
                            await asyncio.to_thread(self.discard_oversize, key, maximum)
                            self.emit(key, '已自动清理', self.repo.task(key)['detail'], 0)
                        except (OSError, ValueError) as exc:
                            self.repo.update_task(key, '删除失败', str(exc))
                    except Exception as exc:
                        self.repo.update_task(key, '采集失败', str(exc)[:1000] + '；修正后选择任务继续采集')
                        self.emit(key, '采集失败', str(exc)[:1000])
                    finally:
                        meter = self.meters.get(key)
                        if meter:
                            task = self.repo.task(key)
                            ended = None if task['state'] == '已暂停' else utc_now()
                            self.repo.save_metrics(key, meter.snapshot(), ended)
                            self.report(key, task['state'], json.dumps(dict(detail=task['detail'], metrics=dict(meter.snapshot(), ended_at=ended), task=self.repo.task(key)), ensure_ascii=False))
                        if self.repo.task(key).get('purge_pending'):
                            try:
                                await asyncio.to_thread(purge_at, self.repo.root, key)
                            except (OSError, ValueError) as exc:
                                self.emit(key, '删除失败', str(exc))
            seen = set()
            active = {}
            def enqueue(key):
                if key in seen or self.repo.task(key).get("deleted"):
                    return
                seen.add(key)
                self.repo.update_task(key, '等待', '已加入队列，等待可用采集名额')
                self.emit(key, '等待', '已加入队列，等待可用采集名额')
                active[asyncio.create_task(one(key))] = key
            for key in ids:
                enqueue(key)
            while active:
                finished, _ = await asyncio.wait(active, timeout=.2, return_when=asyncio.FIRST_COMPLETED)
                for task in finished:
                    seen.discard(active.pop(task))
                    task.result()
                if incoming is not None:
                    while True:
                        try:
                            extra = incoming.get_nowait()
                        except queue.Empty:
                            break
                        for key in extra:
                            enqueue(key)
        return self.repo.tasks()

    def discard_oversize(self, key, maximum):
        from .repository import Repository
        repo = Repository(self.repo.root)
        try: discard(repo, key, maximum)
        finally: repo.close()


class Capture:
    def __init__(self, engine, task):
        self.engine, self.repo, self.task = engine, engine.repo, task
        self.key, self.seed = task['id'], task['seed']
        self.settings = self.repo.upgrade_settings(self.key)
        self.output = settle(self.repo, task, False)
        self.cache = self.repo.root / 'sources' / self.key
        self.cache.mkdir(parents=True, exist_ok=True)
        self.used = 0
        self.known = {}
        self.page_count = 0
        self.done = 0
        self.last_report = 0
        self.host = urlsplit(self.seed).hostname
        self.failed = 0
        self.phase = {}
        self.last_event = '正在连接首页'
        self.last_disk_check = 0
        self.over_limit = False

    def check_size(self):
        if self.used > self.settings.get('template_limit_mb', 300) * 1048576:
            self.over_limit = True
        if self.over_limit: raise Oversize()

    def check(self):
        self.check_size()
        if self.engine.cancel.is_set() or self.repo.task(self.key).get("deleted"):
            raise Paused()

    def progress(self, force=False):
        if force or time.monotonic() - self.last_report > 0.25:
            self.last_report = time.monotonic()
            current = next(iter(self.phase.values()), self.last_event)
            text = f'已保存 {self.done} / 发现 {len(self.known)} · 失败 {self.failed} · {self.used / 1048576:.1f} MB / {self.settings.get("template_limit_mb", 300)} MB · {current}'
            self.engine.emit(self.key, '采集中', text, self.used)

    def discover(self, value, kind, base, depth):
        required_style = kind == 'stylesheet'
        if required_style:
            kind = 'asset'
        url = canonical(value, base)
        if not url or value.startswith('#') or kind in ('link', 'remote'):
            return value
        if kind == 'page':
            if urlsplit(url).hostname != self.host:
                return value
            # Avoid downloading archives/media through navigation links.
            ext = urlsplit(url).path.rsplit('/', 1)[-1].lower()
            if '.' in ext and not ext.endswith(('.html', '.htm', '.php', '.asp', '.aspx', '.jsp', '.shtml')):
                return value
            # Homepage is layer 1; references to assets do not consume a layer.
            if depth >= self.settings['depth']:
                return value
            if url not in self.known and self.page_count >= self.settings['pages']:
                self.repo.warn(self.key, '达到页面数量上限，未采集其余页面')
                return value
        if url not in self.known:
            if len(self.known) >= 20000:
                self.repo.warn(self.key, '达到 20000 个文件上限；可拆分站点范围后采集')
                return value
            self.repo.add(self.key, url, kind, depth, self.seed)
            self.known[url] = kind
            self.page_count += kind == 'page'
        if required_style:
            self.repo.require_style(self.key, url)
        return value

    def parse(self, row, path, base, mime):
        with self.repo.discovery_batch():
            self.parse_document(row, path, base, mime)

    def parse_document(self, row, path, base, mime):
        if path.stat().st_size > 8 * 1024 * 1024:
            if any(t in mime for t in ('html', 'css', 'svg')):
                self.repo.warn(self.key, '超大文本未解析关联资源：' + row['url'])
            return
        resolve = lambda value, kind, origin=base: self.discover(value, kind, origin, row['depth'] + (kind == 'page'))
        if 'html' in mime:
            encoding = re.search(r'charset=["\']?([^;"\'\s]+)', mime)
            html_document(path.read_bytes(), base, resolve, encoding=encoding[1] if encoding else None, lightweight=self.settings.get('lightweight', False))
        elif 'css' in mime:
            # tinycss2 honors CSS @charset and BOM.
            import tinycss2
            tokens, encoding = tinycss2.parse_stylesheet_bytes(path.read_bytes())
            css_document(tinycss2.serialize(tokens), resolve, self.settings.get('lightweight', False))
        elif 'svg' in mime:
            svg_document(path.read_bytes(), resolve)

    async def fetch(self, row):
        try:
            await self._fetch(row)
        finally:
            self.phase.pop(row['url'], None)
            self.progress(force=True)

    async def _fetch(self, row):
        url = row['url']
        path = safe_file(self.output, row['path'])
        part = safe_file(self.output, row['path'] + '.part')
        for attempt in range(self.settings['retries'] + 1):
            received = 0
            installed = False
            try:
                self.check()
                current = url
                for redirect in range(6):
                    host = urlsplit(current).netloc
                    slots = self.engine.host_slots.setdefault(host, asyncio.Semaphore(4))
                    async with self.engine.global_slots, slots:
                        self.check()
                        self.phase[url] = '等待响应：' + host
                        async with self.engine.client.stream('GET', current, timeout=self.settings['timeout']) as response:
                            if response.is_redirect:
                                current = canonical(response.headers.get('location', ''), current)
                                if not current:
                                    raise ValueError('重定向地址无效')
                                if row['kind'] == 'page' and url != self.seed and urlsplit(current).hostname != self.host:
                                    raise ValueError('页面跳转到站外，已停止跟随')
                                continue
                            if response.status_code in (429, 502, 503, 504):
                                retry_after = response.headers.get('retry-after', '')
                                wait = min(60, max(1, int(retry_after))) if retry_after.isdigit() else 2 ** attempt
                                raise Retryable(f'HTTP {response.status_code}，服务器限流或暂时不可用', wait)
                            response.raise_for_status()
                            mime = response.headers.get('content-type', '').lower()
                            if not mime:
                                import mimetypes
                                mime = mimetypes.guess_type(urlsplit(current).path)[0] or ('text/html' if row['kind'] == 'page' else 'application/octet-stream')
                            extensions = {'text/css': '.css', 'text/javascript': '.js', 'application/javascript': '.js', 'image/png': '.png', 'image/jpeg': '.jpg', 'image/svg+xml': '.svg', 'image/webp': '.webp', 'image/gif': '.gif', 'image/avif': '.avif', 'font/woff2': '.woff2', 'font/woff': '.woff', 'font/ttf': '.ttf', 'font/otf': '.otf'}
                            extension = extensions.get(mime.split(';')[0].strip())
                            original_layout = self.settings.get('layout') == 'original'
                            needs_extension = not original_layout or Path(row['path']).suffix.lower() in ('', '.php', '.asp', '.aspx', '.jsp', '.bin')
                            if row['kind'] == 'asset' and extension and needs_extension:
                                proposed = row['path'] + extension if original_layout else str(Path(row['path']).with_suffix(extension)).replace('\\', '/')
                                row['path'] = self.repo.asset_path(self.key, url, proposed)
                                self.repo.set_url(self.key, url, path=row['path'])
                                path = safe_file(self.output, row['path'])
                                part = safe_file(self.output, row['path'] + '.part')
                            digest = hashlib.sha256()
                            with part.open('wb') as stream:
                                async for block in response.aiter_bytes(64 * 1024):
                                    self.check()
                                    if time.monotonic() - self.last_disk_check > 2:
                                        self.last_disk_check = time.monotonic()
                                        if shutil.disk_usage(self.output).free < 64 * 1024 * 1024:
                                            raise OSError('磁盘剩余空间不足 64 MB；释放空间后继续采集')
                                    self.used += len(block)
                                    self.engine.meters[self.key].add(len(block))
                                    received += len(block)
                                    self.check_size()
                                    stream.write(block)
                                    digest.update(block)
                                    self.phase[url] = f'正在下载 {host}：{received / 1048576:.1f} MB'
                                    self.progress()
                            with part.open('rb') as source: actual=binary_type(source.read(32))
                            if actual:
                                mime,extension=actual
                                if row['kind']=='asset' and Path(row['path']).suffix.lower() in ('.html','.htm'):
                                    proposed=row['path']+extension
                                    revised=self.repo.asset_path(self.key,url,proposed)
                                    revised_part=safe_file(self.output,revised+'.part')
                                    part.replace(revised_part);part=revised_part
                                    row['path']=revised;path=safe_file(self.output,revised)
                                    self.repo.set_url(self.key,url,path=revised)
                            if url == self.seed:
                                self.host = urlsplit(current).hostname
                            if 'html' in mime and row['kind'] == 'asset':
                                raise ValueError('资源返回 HTML 页面，可能需要登录或触发验证')
                            if row['kind'] == 'page' and 'html' not in mime:
                                raise ValueError('页面没有返回 HTML，无法作为网站模板')
                            if not received:
                                raise ValueError('服务器返回空文件')
                            if row['kind'] == 'page':
                                with part.open('rb') as html:
                                    problem, reason = html_problem(html.read(256 * 1024))
                                if problem == 'error':
                                    raise ValueError(reason)
                                if problem == 'warning' and url == self.seed:
                                    self.repo.warn(self.key, reason)
                            duplicate = self.repo.duplicate(self.key, digest.hexdigest(), mime) if self.settings.get('layout') != 'original' and ('image/' in mime or 'font/' in mime) and 'svg' not in mime else None
                            if duplicate:
                                part.unlink(missing_ok=True)
                                self.used -= received
                                self.repo.set_url(self.key, url, state='done', size=received, hash=digest.hexdigest(), mime=mime, final_url=current, error='', path=duplicate)
                                self.done += 1
                                return
                            part.replace(path)
                            installed = True
                            if any(t in mime for t in ('html', 'css', 'svg')) and received <= 8 * 1024 * 1024:
                                source = safe_file(self.cache, row['path'])
                                shutil.copyfile(path, source)
                            self.parse(row, path, current, mime)
                            self.repo.set_url(self.key, url, state='done', size=received, hash=digest.hexdigest(), mime=mime, final_url=current, error='')
                            self.done += 1
                            self.progress()
                            return
                    break
                else:
                    raise ValueError('重定向次数过多')
            except Oversize:
                part.unlink(missing_ok=True)
                raise
            except (Paused, asyncio.CancelledError) as exc:
                self.used -= received
                part.unlink(missing_ok=True)
                self.repo.set_url(self.key, url, state='pending')
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return
            except Exception as exc:
                self.used -= received
                part.unlink(missing_ok=True)
                if installed:
                    path.unlink(missing_ok=True)
                    safe_file(self.cache, row['path']).unlink(missing_ok=True)
                retry = isinstance(exc, (httpx.TransportError, Retryable)) and attempt < self.settings['retries']
                if retry:
                    until = time.monotonic() + getattr(exc, 'wait', 2 ** attempt)
                    while time.monotonic() < until and not self.engine.cancel.is_set():
                        self.phase[url] = f'重试 {attempt + 1}/{self.settings["retries"]}，等待 {max(1, int(until-time.monotonic()))} 秒'
                        await asyncio.sleep(0.2)
                    continue
                message = str(exc) or type(exc).__name__
                if isinstance(exc, httpx.TimeoutException):
                    message = '请求超时；检查网络后点击继续采集'
                elif isinstance(exc, httpx.HTTPStatusError):
                    code = exc.response.status_code
                    hints = {403: '服务器拒绝访问；请先在普通浏览器检查网址或稍后重试，不会将错误页保存为模板', 401: '站点要求登录，当前静态采集不支持登录内容', 404: '页面不存在，请检查网址', 429: '请求过快，请稍后重试或降低并发'}
                    message = f'HTTP {code}；' + hints.get(code, '源站响应异常，稍后重试')
                self.failed += 1
                self.last_event = message
                self.repo.set_url(self.key, url, state='failed', error=message[:1000])
                return

    async def run(self):
        if await asyncio.to_thread(exceeds, self.repo, self.task, self.settings.get('template_limit_mb', 300)):
            raise Oversize()
        self.repo.update_task(self.key, '采集中')
        self.repo.clear_warnings(self.key)
        rows = self.repo.rows(self.key)
        counted = set()
        for row in rows:
            if self.engine.cancel.is_set() or self.repo.task(self.key).get("deleted"):
                break
            self.known[row['url']] = row['kind']
            self.page_count += row['kind'] == 'page'
            path = safe_file(self.output, row['path'])
            self.last_event = '正在校验断点文件'
            self.progress()
            if row['state'] == 'done' and path.is_file() and path.stat().st_size == row['size'] and await asyncio.to_thread(checksum, path) == row['hash']:
                if row['path'] not in counted:
                    self.used += row['size']
                    counted.add(row['path'])
                self.done += 1
                if row['url'] == self.seed and row['final_url']:
                    self.host = urlsplit(row['final_url']).hostname
            else:
                state = 'excluded' if row['kind'] == 'page' and row['depth'] >= self.settings['depth'] else 'pending'
                restored_path = row['path'] if self.settings.get('layout') == 'original' else local_path(row['url'], row['kind'], self.seed)
                self.repo.set_url(self.key, row['url'], state=state, size=0, error='', path=restored_path)
        # Rebuild discovery from cached source; old size-limited tasks can continue.
        for row in self.repo.rows(self.key):
            if self.engine.cancel.is_set() or self.repo.task(self.key).get("deleted"):
                break
            if row['state'] == 'done':
                source = safe_file(self.cache, row['path'])
                if source.is_file():
                    self.parse(row, source, row['final_url'] or row['url'], row['mime'])
                    if row['url'] == self.seed:
                        with source.open('rb') as html:
                            problem, reason = html_problem(html.read(256 * 1024))
                        if problem:
                            self.repo.warn(self.key, reason)
                elif row['size'] > 8 * 1024 * 1024:
                    self.parse(row, safe_file(self.output, row['path']), row['final_url'] or row['url'], row['mime'])
                await asyncio.sleep(0)
        # Only a fixed number of coroutines exist, regardless of frontier size.
        active = set()
        try:
            while not self.engine.cancel.is_set() and not self.repo.task(self.key).get("deleted"):
                while len(active) < self.settings['connections']:
                    row = self.repo.claim(self.key)
                    if not row:
                        break
                    active.add(asyncio.create_task(self.fetch(row)))
                if not active:
                    break
                finished, active = await asyncio.wait(active, timeout=1, return_when=asyncio.FIRST_COMPLETED)
                self.progress(force=True)
                await asyncio.gather(*finished)
            if active:
                if self.engine.cancel.is_set() or self.repo.task(self.key).get("deleted"):
                    for task in active: task.cancel()
                    await asyncio.gather(*active, return_exceptions=True)
                else:
                    await asyncio.gather(*active)
        finally:
            for task in active:
                if not task.done(): task.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
        if self.engine.cancel.is_set() or self.repo.task(self.key).get("deleted"):
            self.repo.update_task(self.key, '已暂停', '已保存完整文件；继续时重试未完成文件，不重复下载已校验文件')
            self.engine.emit(self.key, '已暂停', '断点已保存，可继续采集')
            return
        self.engine.emit(self.key, '整理中', '修正本地链接并检查缺失资源')
        self.repo.update_task(self.key, '整理中', '正在修正本地链接，完成后检查模板质量')
        await self.finalize()

    async def finalize(self):
        rows = self.repo.rows(self.key)
        mapping = {r['url']: r['path'] for r in rows if r['state'] == 'done'}
        for r in rows:
            if r['state'] == 'done' and r['final_url']:
                mapping.setdefault(r['final_url'], r['path'])
        for index, row in enumerate(rows):
            await asyncio.sleep(0)
            if index % 25 == 0:
                self.engine.emit(self.key, '整理中', f'正在整理本地链接 {index + 1}/{len(rows)}')
            if self.engine.cancel.is_set() or self.repo.task(self.key).get("deleted"):
                self.repo.update_task(self.key, '已暂停', '本地链接整理暂停，可继续')
                return
            source = safe_file(self.cache, row['path'])
            if row['state'] != 'done' or not source.is_file():
                continue
            path = safe_file(self.output, row['path'])
            base = row['final_url'] or row['url']

            def resolve(value, kind, origin=base):
                if value.startswith('#') or not canonical(value, origin):
                    return value
                absolute = urljoin(origin, value)
                destination = mapping.get(canonical(value, origin))
                if destination:
                    relative = os.path.relpath(self.output / destination, path.parent).replace('\\', '/')
                    fragment = urlsplit(absolute).fragment
                    return quote(relative, safe='/~') + ('#' + fragment if fragment else '')
                return absolute
            mime = row['mime']
            if 'css' in mime:
                import tinycss2
                protocol = re.search(r'charset=["\']?([^;"\'\s]+)', mime)
                tokens, encoding = tinycss2.parse_stylesheet_bytes(source.read_bytes(), protocol_encoding=protocol[1] if protocol else None)
                text = css_document(tinycss2.serialize(tokens), resolve, self.settings.get('lightweight', False))
                if not text.lstrip().lower().startswith('@charset'):
                    text = '@charset "' + encoding.name + '";\n' + text
                data = text.encode(encoding.codec_info.name)
            elif 'svg' in mime:
                data = svg_document(source.read_bytes(), resolve)
            else:
                encoding = re.search(r'charset=["\']?([^;"\'\s]+)', mime)
                data = html_document(source.read_bytes(), base, resolve, rewrite=True, encoding=encoding[1] if encoding else None, lightweight=self.settings.get('lightweight', False))
            delta = len(data) - row['size']
            temp = safe_file(self.output, row['path'] + '.part')
            temp.write_bytes(data)
            temp.replace(path)
            self.used += delta
            self.repo.set_url(self.key, row['url'], size=len(data), hash=hashlib.sha256(data).hexdigest())
        warnings = self.repo.warnings(self.key)
        home = next((r for r in self.repo.rows(self.key) if r['url'] == self.seed and r['state'] == 'done'), None)
        if home and home['path'] != 'index.html' and not (self.output / 'index.html').exists():
            from html import escape
            target = escape(quote(home['path'], safe='/~'), quote=True)
            (self.output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=' + target + '"><a href="' + target + '">打开采集首页</a>', encoding='utf-8')
        if await asyncio.to_thread(exceeds, self.repo, self.repo.task(self.key), self.settings.get('template_limit_mb', 300)):
            raise Oversize()
        verdict = assess(self.seed, self.repo.rows(self.key), warnings, self.used)
        settle(self.repo, self.repo.task(self.key), verdict.publish)
        detail = verdict.detail
        if self.settings.get('lightweight'):
            detail += ' 轻量联网模板：图片、字体和媒体引用原站，离线时不可用。'
        if verdict.state == '采集失败':
            detail = '首页未成功保存，已自动清理任务和关联文件。'
            self.repo.update_task(self.key, '已自动清理', detail)
            self.repo.delete_task(self.key)
            await asyncio.to_thread(purge_at, self.repo.root, self.key)
            self.engine.emit(self.key, '已自动清理', detail, 0)
        else:
            self.repo.update_task(self.key, verdict.state, detail)
            self.engine.emit(self.key, verdict.state, detail, self.used)


class Retryable(Exception):
    def __init__(self, message, wait):
        super().__init__(message)
        self.wait = wait
