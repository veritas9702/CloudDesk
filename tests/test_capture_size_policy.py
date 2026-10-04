import tempfile
import threading
import unittest
from pathlib import Path
import httpx
from cloudtool.crawler.controller import CaptureController
from cloudtool.crawler.models import Settings
from cloudtool.crawler.repository import Repository
from cloudtool.crawler.artifacts import workspace
from cloudtool.crawler.size_policy import exceeds


class SizePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = CaptureController(self.root/'state')

    def test_stream_limit_deletes_only_oversize_site_and_continues(self):
        ids = self.controller.create('https://large.test/\nhttps://small.test/', str(self.root/'out'), Settings(template_limit_mb=1))
        async def handler(request):
            if request.url.host == 'large.test':
                content = b'<html><body>' + b'x' * (2*1048576) + b'</body></html>'
            else: content = b'<html><body>small page</body></html>'
            return httpx.Response(200,headers={'content-type':'text/html'},content=content)
        self.controller.run_job(ids, threading.Event(), httpx.MockTransport(handler))(lambda *_:None)
        repo = Repository(self.root/'state')
        try:
            large, small = (repo.task(k) for k in ids)
            self.assertTrue(large['deleted']);self.assertEqual(large['state'],'已自动清理')
            self.assertFalse(Path(large['output']).exists())
            self.assertFalse(workspace(large['output'],ids[0]).exists())
            self.assertFalse((repo.root/'sources'/ids[0]).exists())
            self.assertEqual(small['state'],'已完成')
            self.assertTrue(Path(small['output']).is_dir())
        finally:repo.close()

    def test_existing_exact_boundary_keep_over_delete_and_persist(self):
        ids=self.controller.create('https://keep.test/\nhttps://delete.test/',str(self.root/'out'),Settings())
        repo=Repository(self.root/'state')
        try:
            for offset,key in enumerate(ids):
                task=repo.task(key);folder=Path(task['output']);folder.mkdir(parents=True,exist_ok=True)
                (folder/'asset.bin').write_bytes(b'x'*(1048576+offset))
                repo.update_task(key,'已暂停')
            self.assertFalse(exceeds(repo,repo.task(ids[0]),1))
        finally:repo.close()
        unrelated=self.root/'out'/'unregistered';unrelated.mkdir();(unrelated/'keep').write_text('keep')
        rows=self.controller.enforce_template_limit(1)
        self.assertEqual([r['id'] for r in rows],[ids[0]])
        self.assertTrue((unrelated/'keep').exists())
        self.assertEqual(CaptureController(self.root/'state').template_limit(),1)

    def test_bad_identity_does_not_delete_directory(self):
        key=self.controller.create('https://safe.test/',str(self.root/'out'),Settings())[0]
        outside=self.root/'important';outside.mkdir();(outside/'keep').write_bytes(b'x'*1048577)
        repo=Repository(self.root/'state')
        repo.db.execute("UPDATE tasks SET output=?,state='已暂停' WHERE id=?",(str(outside),key));repo.db.commit();repo.close()
        rows=self.controller.enforce_template_limit(1)
        self.assertEqual(rows[0]['state'],'删除失败');self.assertTrue((outside/'keep').exists())

    def test_resume_oversize_is_deleted_before_network(self):
        key=self.controller.create('https://resume.test/',str(self.root/'out'),Settings(template_limit_mb=1))[0]
        repo=Repository(self.root/'state');task=repo.task(key);repo.close()
        folder=workspace(task['output'],key);folder.mkdir(parents=True,exist_ok=True)
        (folder/'large.bin').write_bytes(b'x'*1048577)
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(500)
        self.controller.run_job([key],threading.Event(),httpx.MockTransport(handler))(lambda *_:None)
        self.assertEqual(calls,[]);self.assertFalse(folder.exists());self.assertEqual(self.controller.snapshot(),[])
