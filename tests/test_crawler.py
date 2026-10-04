"""Offline capture tests: graph completeness, budgets, restart, errors and bounds."""
import asyncio
from collections import Counter
import json
from pathlib import Path
import tempfile
import threading
import unittest
import httpx
from cloudtool.crawler.controller import CaptureController
from cloudtool.crawler.repository import Repository
from cloudtool.crawler.models import Settings, canonical, local_path


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = CaptureController(self.root / 'state')
        self.cancel = threading.Event()
        self.calls = Counter()
        self.bad = False
        self.docs = {
            '/': ('text/html', b'<html><head><link rel="stylesheet" href="/main.css"></head><body><a href="/about?q=1#top">About</a><a href="https://elsewhere.invalid/">external</a><img src="/photo.jpg"><img srcset="/a.png 1x, /b.png 2x"><script src="/app.js"></script><img src="/logo.svg"></body></html>'),
            '/about': ('text/html', '<html><head><meta charset="utf-8"></head><body>中文页面<a href="/">Home</a></body></html>'.encode()),
            '/main.css': ('text/css', b'@import "extra.css";body {background:url("/bg.png")}'),
            '/extra.css': ('text/css', b'@font-face {src:url("/font.woff2")}'),
            '/photo.jpg': ('image/jpeg', b'jpg'), '/a.png': ('image/png', b'a'),
            '/b.png': ('image/png', b'b'), '/bg.png': ('image/png', b'bg'),
            '/font.woff2': ('font/woff2', b'font'), '/app.js': ('application/javascript', b'console.log(1)'),
            '/logo.svg': ('image/svg+xml', b'<svg xmlns="http://www.w3.org/2000/svg"><image href="/a.png"/></svg>'),
        }

    async def handler(self, request):
        self.calls[str(request.url)] += 1
        await asyncio.sleep(0.001)
        if self.bad and request.url.path == '/a.png':
            return httpx.Response(404)
        mime, content = self.docs.get(request.url.path, ('text/plain', b'not found'))
        return httpx.Response(200, headers={'content-type': mime}, content=content)

    def create(self, text='https://example.test', **kwargs):
        return self.controller.create(text, str(self.root / 'output'), Settings(**kwargs))

    def run_ids(self, ids, report=lambda *_: None):
        return self.controller.run_job(ids, self.cancel, httpx.MockTransport(self.handler))(report)

    def test_binary_asset_with_html_name_is_saved_as_image(self):
        self.docs['/']=('text/html',b'<html><img src="/code.html"></html>')
        self.docs['/code.html']=('text/html',b'GIF87a'+bytes(50))
        task=self.run_ids(self.create())[0]
        folder=Path(task['output'])
        self.assertTrue((folder/'code.html.gif').is_file())
        self.assertFalse((folder/'code.html').exists())
        self.assertIn('code.html.gif',(folder/'index.html').read_text())

    def test_assets_rewriting_and_resume_does_not_redownload(self):
        ids = self.create()
        tasks = self.run_ids(ids)
        self.assertEqual(tasks[0]['state'], '已完成', tasks)
        self.assertGreater(tasks[0]['elapsed_seconds'], 0)
        self.assertTrue(tasks[0]['ended_at'])
        self.assertGreater(tasks[0]['transferred_bytes'], 0)
        repo = Repository(self.root / 'state')
        rows = repo.rows(ids[0]); repo.close()
        self.assertEqual(len(rows), 11)
        folder = Path(tasks[0]['output'])
        html = (folder / 'index.html').read_text('utf-8')
        self.assertIn('photo.jpg', html)
        self.assertIn('#top', html)
        self.assertNotIn('https://elsewhere.invalid/', self.calls)
        for row in rows:
            if row['mime'] == 'text/css':
                self.assertNotIn('url("/bg.png")', (folder / row['path']).read_text())
        before = self.calls.copy()
        self.controller = CaptureController(self.root / 'state')
        self.run_ids(ids)
        self.assertEqual(self.calls, before)
        saved = self.controller.snapshot()[0]
        self.assertGreaterEqual(saved['elapsed_seconds'], tasks[0]['elapsed_seconds'])
        self.assertEqual(saved['transferred_bytes'], tasks[0]['transferred_bytes'])

    def test_failed_resource_is_reported_and_only_failed_retried(self):
        self.bad = True
        ids = self.create()
        task = self.run_ids(ids)[0]
        self.assertEqual(task['state'], '部分完成')
        self.assertTrue(Path(task['output']).exists())
        self.assertIn('404', self.controller.detail(ids[0]))
        before = self.calls.copy()
        self.bad = False
        self.assertEqual(self.run_ids(ids)[0]['state'], '已完成')
        changed = [key for key in self.calls if self.calls[key] != before[key]]
        self.assertEqual(changed, ['https://example.test/a.png'])

    def test_pause_and_process_restart(self):
        ids = self.create()
        def progress(*_):
            self.cancel.set()
        self.assertEqual(self.run_ids(ids, progress)[0]['state'], '已暂停')
        self.cancel.clear()
        self.controller = CaptureController(self.root / 'state')
        self.assertEqual(self.run_ids(ids)[0]['state'], '已完成')

    def test_old_budget_and_single_file_limit_are_removed_on_resume(self):
        self.docs['/photo.jpg'] = ('image/jpeg', b'x' * (33 * 1024 * 1024))
        ids = self.create(budget=1024 * 1024)
        repo = Repository(self.root / 'state')
        old = Settings().__dict__.copy(); old['budget'] = 1024 * 1024
        repo.db.execute('UPDATE tasks SET settings=? WHERE id=?', (json.dumps(old), ids[0])); repo.db.commit(); repo.close()
        task = self.run_ids(ids)[0]
        self.assertEqual(task['state'], '已完成')
        total = sum(p.stat().st_size for p in Path(task['output']).rglob('*') if p.is_file())
        self.assertGreater(total, 32 * 1024 * 1024)
        self.assertIsNone(json.loads(task['settings'])['budget'])
        self.assertFalse(list(Path(task['output']).rglob('*.part')))

    def test_pages_limit_keeps_page_assets(self):
        ids = self.create(pages=1)
        task = self.run_ids(ids)[0]
        self.assertEqual(task['state'], '部分完成')
        self.assertIn('https://example.test/photo.jpg', self.calls)
        self.assertNotIn('https://example.test/about?q=1', self.calls)

    def test_corrupted_completed_file_is_redownloaded(self):
        ids = self.create()
        task = self.run_ids(ids)[0]
        repo = Repository(self.root / 'state')
        row = next(r for r in repo.rows(ids[0]) if r['url'].endswith('photo.jpg')); repo.close()
        (Path(task['output']) / row['path']).write_bytes(b'corrupt')
        self.run_ids(ids)
        self.assertEqual(self.calls[row['url']], 2)

    def test_url_identity_is_query_sensitive_and_windows_safe(self):
        self.assertEqual(canonical('HTTPS://Example.com:443/a#x'), 'https://example.com/a')
        self.assertNotEqual(local_path('https://a.test/?x=1', 'page', ''), local_path('https://a.test/?x=2', 'page', ''))
        self.assertEqual(canonical('file:///C:/secret'), '')

    def test_header_encoding_svg_case_and_duplicate_images(self):
        self.docs['/about'] = ('text/html; charset=gbk', '<html><body>中文标题</body></html>'.encode('gbk'))
        self.docs['/b.png'] = self.docs['/a.png']
        self.docs['/logo.svg'] = ('image/svg+xml', b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><image href="/a.png"/></svg>')
        ids = self.create()
        task = self.run_ids(ids)[0]
        repo = Repository(self.root / 'state'); rows = repo.rows(ids[0]); repo.close()
        by_url = {r['url']:r for r in rows}
        self.assertNotEqual(by_url['https://example.test/a.png']['path'], by_url['https://example.test/b.png']['path'])
        output = Path(task['output'])
        self.assertIn('中文标题', (output / by_url['https://example.test/about?q=1']['path']).read_text('gbk'))
        self.assertIn('viewBox', (output / by_url['https://example.test/logo.svg']['path']).read_text('utf-8'))

    def test_extensionless_assets_work_in_preview_and_existing_packer(self):
        self.docs['/'] = ('text/html', b'<html><head><link rel="stylesheet" href="/style?id=2"></head><body>test</body></html>')
        self.docs['/style'] = ('text/css', b'body {color:red}')
        ids = self.create()
        task = self.run_ids(ids)[0]
        self.assertEqual(task['state'], '已完成')
        repo = Repository(self.root / 'state'); rows = repo.rows(ids[0]); repo.close()
        self.assertTrue(next(r for r in rows if r['kind'] == 'asset')['path'].endswith('.css'))
        from cloudtool.siteadmin.templates import inventory, pack
        templates = inventory(self.root / 'output', self.cancel)
        pack(templates[0], self.root / 'template.zip', self.cancel)
        self.assertTrue((self.root / 'template.zip').is_file())

    def test_retry_transient_server_error(self):
        original = self.handler
        attempts = 0
        async def handler(request):
            nonlocal attempts
            if request.url.path == '/a.png':
                attempts += 1
                if attempts == 1:
                    return httpx.Response(503, headers={'retry-after':'1'})
            return await original(request)
        self.handler = handler
        task = self.run_ids(self.create())[0]
        self.assertEqual(task['state'], '已完成')
        self.assertEqual(attempts, 2)

    def test_multisite_global_connections_bounded(self):
        active = 0
        peak = 0
        original = self.handler
        async def handler(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.005)
            result = await original(request)
            active -= 1
            return result
        self.handler = handler
        ids = self.create('https://one.test\nhttps://two.test\nhttps://three.test', sites=3, connections=8)
        self.run_ids(ids)
        self.assertLessEqual(peak, 8)
        self.assertGreater(peak, 1)

    def test_homepage_403_is_failure_not_partial_or_output(self):
        self.handler = lambda request: httpx.Response(403)
        ids = self.create()
        self.controller.pending_input('https://example.test/\nhttps://keep.test/')
        self.assertEqual(self.run_ids(ids), [])
        repo = Repository(self.root / 'state')
        task = repo.task(ids[0]); self.assertEqual(repo.rows(ids[0]), []); repo.close()
        self.assertEqual(task['state'], '已自动清理')
        self.assertTrue(task['deleted'])
        self.assertFalse((self.root / 'state' / 'sources' / ids[0]).exists())
        self.assertEqual(self.controller.pending_input(), 'https://keep.test/')
        self.assertFalse(Path(task['output']).exists())
        self.assertFalse(task['published'])

    def test_depth_one_to_three_counts_homepage_and_keeps_assets(self):
        self.docs['/about'] = ('text/html', b'<a href="/third">third</a>')
        self.docs['/third'] = ('text/html', b'<a href="/fourth">fourth</a>')
        for depth in (1, 2, 3):
            with self.subTest(depth=depth):
                self.calls.clear()
                ids = self.create(depth=depth)
                task = next(t for t in self.run_ids(ids) if t['id'] == ids[0])
                self.assertEqual(task['state'], '已完成')
                self.assertIn('https://example.test/photo.jpg', self.calls)
                self.assertEqual('https://example.test/about?q=1' in self.calls, depth >= 2)
                self.assertEqual('https://example.test/third' in self.calls, depth >= 3)
                self.assertNotIn('https://example.test/fourth', self.calls)
        for depth in (0,4):
            with self.assertRaises(ValueError): Settings(depth=depth).validate()

    def test_large_partial_has_output_but_cache_cannot_be_allocated(self):
        self.bad = True
        self.docs['/photo.jpg'] = ('image/jpeg', b'x' * (3 * 1024 * 1024))
        task = self.run_ids(self.create())[0]
        self.assertEqual(task['state'], '部分完成')
        self.assertTrue(Path(task['output']).is_dir())
        self.docs['/photo.jpg'] = ('image/jpeg', b'tiny')
        ids = self.create()
        task = next(t for t in self.run_ids(ids) if t['id'] == ids[0])
        from cloudtool.siteadmin.templates import files, inventory
        self.docs['/'] = ('text/html', b'<title>Access Denied</title>')
        failed_ids = self.create()
        remaining = self.run_ids(failed_ids)
        self.assertNotIn(failed_ids[0], [t['id'] for t in remaining])
        self.assertFalse((self.root / 'state' / 'sources' / failed_ids[0]).exists())
        self.assertEqual(len(inventory(self.root / 'output', self.cancel)), 2)

    def test_error_page_200_and_dynamic_shell_are_not_templates(self):
        for html, state in ((b'<title>Technical Difficulties</title>', '采集失败'), (b'<html><div id="app"></div><script src="/app.js"></script></html>', '未通过验收')):
            self.docs['/'] = ('text/html', html)
            ids = self.create()
            result = self.run_ids(ids)
            if state == '采集失败':
                self.assertNotIn(ids[0], [t['id'] for t in result])
                continue
            task = next(t for t in result if t['id'] == ids[0])
            self.assertEqual(task['state'], state)
            self.assertFalse(Path(task['output']).exists())

    def test_heartbeat_while_waiting_for_response(self):
        original = self.handler
        async def delayed(request):
            if request.url.path == '/': await asyncio.sleep(1.2)
            return await original(request)
        self.handler = delayed
        events = []
        self.run_ids(self.create(), lambda *args: events.append(args))
        self.assertTrue(any('等待响应' in event[2] for event in events))

    def test_legacy_zero_result_migrates_without_deleting_data(self):
        ids = self.create()
        repo = Repository(self.root / 'state'); task = repo.task(ids[0])
        old = Path(task['output']); old.mkdir()
        (old / 'user-note.txt').write_text('keep me')
        Path(task['work']).rmdir()
        repo.db.execute("UPDATE tasks SET work='',state='部分完成' WHERE id=?", (ids[0],))
        repo.set_url(ids[0], task['seed'], state='failed', error='HTTP 403')
        repo.close()
        controller = CaptureController(self.root / 'state')
        task = controller.snapshot()[0]
        self.assertEqual(task['state'], '采集失败')
        self.assertFalse(old.exists())
        self.assertEqual((Path(task['work']) / 'user-note.txt').read_text(), 'keep me')

    def test_missing_text_source_keeps_verified_local_page(self):
        ids = self.create(); self.run_ids(ids)
        (self.root / 'state' / 'sources' / ids[0] / 'index.html').unlink()
        task = self.run_ids(ids)[0]
        self.assertEqual(task['state'], '已完成')
        self.assertEqual(self.calls['https://example.test/'], 1)
        self.assertFalse(any('/assets/' in url for url in self.calls))

    def test_pause_cancels_waiting_http_request_promptly(self):
        import time
        async def delayed(request):
            await asyncio.sleep(10)
            return httpx.Response(200, headers={'content-type':'text/html'}, content=b'<html>OK</html>')
        self.handler = delayed
        def progress(*args):
            if '等待响应' in args[2]: self.cancel.set()
        started = time.monotonic()
        task = self.run_ids(self.create(), progress)[0]
        self.assertEqual(task['state'], '已暂停')
        self.assertLess(time.monotonic() - started, 5)

    def test_public_site_compatible_user_agent_keeps_product_identity(self):
        original = self.handler
        async def compatible(request):
            agent = request.headers['user-agent']
            self.assertIn('CloudDeskCapture/', agent)
            if not agent.startswith('Mozilla/5.0'):
                return httpx.Response(403)
            return await original(request)
        self.handler = compatible
        self.assertEqual(self.run_ids(self.create())[0]['state'], '已完成')


    def test_css_encoding_and_subdirectory_entry_are_preserved(self):
        self.docs['/zh/'] = ('text/html; charset=gbk', '<html><head><link rel="stylesheet" href="/template/1/style.css"></head><body>中文首页</body></html>'.encode('gbk'))
        self.docs['/template/1/style.css'] = ('text/css; charset=gbk', '/* 中文样式 */ body { color: red }'.encode('gbk'))
        task = self.run_ids(self.create('https://example.test/zh/'))[0]
        self.assertEqual(task['state'], '已完成')
        output = Path(task['output'])
        self.assertIn('中文首页', (output/'zh/index.html').read_text('gbk'))
        self.assertIn('中文样式', (output/'template/1/style.css').read_text('gbk'))
        self.assertIn('zh/index.html', (output/'index.html').read_text('utf-8'))
        before = self.calls.copy()
        self.run_ids([task['id']])
        self.assertEqual(self.calls, before)
        self.assertTrue((output/'zh/index.html').is_file())

    def test_stylesheet_failure_is_quarantined_and_cache_can_be_cleared(self):
        original = self.handler
        async def blocked(request):
            if request.url.path == '/main.css':
                return httpx.Response(403)
            return await original(request)
        self.handler = blocked
        key = self.create()[0]
        task = self.run_ids([key])[0]
        self.assertEqual(task['state'], '未通过验收')
        self.assertFalse(Path(task['output']).exists())
        self.assertTrue(Path(task['work']).exists())
        self.assertIn('样式', task['detail'])
        self.controller.clear_cache(key)
        self.assertFalse(Path(task['work']).exists())
        self.assertFalse(Path(task['work']).parent.exists())
        self.assertEqual(self.controller.snapshot()[0]['state'], '已清理')
        self.handler = original
        task = self.run_ids([key])[0]
        self.assertEqual(task['state'], '已完成')
        with self.assertRaises(ValueError):
            self.controller.clear_cache(key)
        self.assertTrue(Path(task['output']).exists())

    def test_extensionless_stylesheet_failure_and_old_published_result(self):
        self.docs['/'] = ('text/html', b'<html><link rel="stylesheet" href="/style?id=2"><body>valid content</body></html>')
        original = self.handler
        async def blocked(request):
            if request.url.path == '/style': return httpx.Response(403)
            return await original(request)
        self.handler = blocked
        key = self.create()[0]
        task = self.run_ids([key])[0]
        self.assertFalse(task['published'])
        from cloudtool.crawler.artifacts import settle
        repo = Repository(self.root / 'state')
        try:
            settle(repo, repo.task(key), True)
            repo.update_task(key, '部分完成', 'old version')
        finally:
            repo.close()
        self.controller = CaptureController(self.root / 'state')
        task = self.controller.snapshot()[0]
        self.assertFalse(task['published'])
        self.assertEqual(task['state'], '未通过验收')
        self.assertFalse(Path(task['output']).exists())

    def test_prepare_skips_saved_and_reuses_missing_or_failed_tasks(self):
        ids, skipped, _ = self.controller.prepare('https://example.test', str(self.root/'output'), Settings())
        self.assertEqual(skipped, [])
        task = self.run_ids(ids)[0]
        before = self.calls.copy()
        again, skipped, rows = self.controller.prepare('https://example.test\nhttps://example.test/', str(self.root/'other'), Settings())
        self.assertEqual(again, [])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(before, self.calls)
        (Path(task['output'])/'photo.jpg').unlink()
        again, skipped, rows = self.controller.prepare('https://example.test', str(self.root/'other'), Settings())
        self.assertEqual(again, ids)
        self.assertEqual(len(rows), 1)
        self.run_ids(again)
        self.assertEqual(self.calls['https://example.test/photo.jpg'], 2)

    def test_concurrent_append_reuses_same_record(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.controller.prepare, 'https://example.test/', str(self.root/'output'), Settings()) for _ in range(2)]
            results = [f.result() for f in futures]
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(len(self.controller.snapshot()), 1)

    def test_discovery_batch_commits_and_rolls_back(self):
        key = self.create()[0]
        repo = Repository(self.root / 'state')
        try:
            with repo.discovery_batch():
                repo.add(key, 'https://example.test/ok', 'page', 1, 'https://example.test/')
            with self.assertRaises(ValueError):
                with repo.discovery_batch():
                    repo.add(key, 'https://example.test/bad', 'page', 1, 'https://example.test/')
                    raise ValueError('parse failed')
            rows = repo.rows(key)
            self.assertTrue(any(r['url'].endswith('/ok') for r in rows))
            self.assertFalse(any(r['url'].endswith('/bad') for r in rows))
        finally:
            repo.close()

    def test_lightweight_keeps_pages_styles_scripts_and_remote_media(self):
        ids = self.create(lightweight=True)
        task = self.run_ids(ids)[0]
        self.assertEqual(task['state'], '已完成')
        for path in ('/main.css', '/extra.css', '/app.js', '/about?q=1'):
            self.assertIn('https://example.test' + path, self.calls)
        for path in ('/photo.jpg', '/a.png', '/b.png', '/bg.png', '/font.woff2', '/logo.svg'):
            self.assertNotIn('https://example.test' + path, self.calls)
        folder = Path(task['output'])
        self.assertIn('https://example.test/photo.jpg', (folder / 'index.html').read_text('utf-8'))
        css = '\n'.join(p.read_text('utf-8') for p in folder.rglob('*.css'))
        self.assertIn('https://example.test/bg.png', css)
        self.assertIn('https://example.test/font.woff2', css)
        self.assertIn('轻量联网', task['detail'])
        before = self.calls.copy()
        self.controller.run_job(ids, self.cancel, httpx.MockTransport(self.handler), Settings())(lambda *_: None)
        self.assertEqual(self.calls, before)
        self.assertTrue(json.loads(self.controller.snapshot()[0]['settings'])['lightweight'])


if __name__ == '__main__':
    unittest.main()


class QueueStateTests(unittest.TestCase):
    def test_resumed_tasks_report_waiting_before_running(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = CaptureController(root/'state')
            ids = controller.create('https://a.test/\nhttps://b.test/', str(root/'output'), Settings(sites=1))
            repo = Repository(root/'state')
            for key in ids:
                repo.update_task(key, '已暂停')
            repo.close()
            events = []
            async def handler(request):
                await asyncio.sleep(.01)
                return httpx.Response(200, headers={'content-type':'text/html'}, content=b'<html><body>Hello static content</body></html>')
            controller.run_job(ids, threading.Event(), transport=httpx.MockTransport(handler))(lambda key,state,raw: events.append((key,state)))
            for key in ids:
                states = [state for item,state in events if item == key]
                self.assertEqual(states[0], '等待')
                self.assertIn('采集中', states)

    def test_snapshot_exposes_confirmed_redirect_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = CaptureController(root/'state')
            key = controller.create('http://a.test/', str(root/'out'), Settings())[0]
            repo = Repository(root/'state')
            repo.set_url(key, 'http://a.test/', final_url='https://a.test/')
            repo.close()
            self.assertEqual(controller.snapshot()[0]['aliases'], ['https://a.test/'])


class DeleteTaskTests(unittest.TestCase):
    def test_deleted_pending_task_is_not_started(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            controller=CaptureController(root/'state')
            key=controller.create('https://deleted.test/',str(root/'out'),Settings())[0]
            controller.delete_task(key)
            calls=[]
            def handler(request):
                calls.append(request)
                return httpx.Response(200)
            controller.run_job([key],threading.Event(),transport=httpx.MockTransport(handler))(lambda *args: None)
            self.assertEqual(calls,[])
            self.assertEqual(controller.snapshot(),[])
            self.assertEqual(CaptureController(root/'state').snapshot(),[])


class DeleteFilesTests(unittest.TestCase):
    def test_delete_removes_only_owned_output_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            controller=CaptureController(root/'state')
            key=controller.create('https://remove.test/',str(root/'out'),Settings())[0]
            repo=Repository(root/'state')
            task=repo.task(key)
            repo.update_task(key,'已暂停')
            repo.close()
            output=Path(task['output']); output.mkdir()
            (output/'index.html').write_text('local')
            other=root/'out'/'keep';other.mkdir();(other/'note').write_text('keep')
            controller.delete_task(key)
            controller.cleanup_deleted()
            self.assertFalse(output.exists())
            self.assertFalse(Path(task['work']).exists())
            self.assertTrue((other/'note').exists())
            self.assertEqual(controller.snapshot(),[])

    def test_running_delete_finishes_cleanup_and_other_site_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            controller=CaptureController(root/'state')
            ids=controller.create('https://remove.test/\nhttps://keep.test/',str(root/'out'),Settings())
            task=controller.snapshot()[-1]
            deleted=[]
            def report(key,state,raw):
                if key==ids[0] and state=='采集中' and not deleted:
                    deleted.append(key)
                    controller.delete_task(key)
            async def handler(request):
                await asyncio.sleep(.001)
                return httpx.Response(200,headers={'content-type':'text/html'},content=b'<html><body>Saved static page</body></html>')
            rows=controller.run_job(ids,threading.Event(),transport=httpx.MockTransport(handler))(report)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['state'],'已完成')
            self.assertFalse(Path(task['work']).exists())


class TemplateSizeTests(unittest.TestCase):
    def test_size_counts_unique_saved_paths_not_transfer_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            controller=CaptureController(root/'state')
            key=controller.create('https://size.test/',str(root/'out'),Settings())[0]
            repo=Repository(root/'state')
            repo.set_url(key,'https://size.test/',state='done',size=10)
            repo.add(key,'https://size.test/a','asset',1,'https://size.test/')
            repo.set_url(key,'https://size.test/a',state='done',size=10,path='index.html')
            repo.add(key,'https://size.test/b','asset',1,'https://size.test/')
            repo.set_url(key,'https://size.test/b',state='failed',size=999)
            repo.close()
            self.assertEqual(controller.snapshot()[0]['template_bytes'],10)
