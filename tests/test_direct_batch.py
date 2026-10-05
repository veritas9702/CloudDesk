import json
import threading
import unittest
from unittest.mock import patch
import httpx
from cloudtool.models import Cancelled
from cloudtool.siteadmin.direct_batch import DirectBatch
from cloudtool.siteadmin.recovery_policy import template_failure
from cloudtool.siteadmin import template_workflow
import test_site_pipeline as pipeline_fixtures
import test_site_rebuild as rebuild_fixtures


class DirectTests(unittest.TestCase):
    def setUp(self):
        self.f=pipeline_fixtures.PipelineTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;self.flow=DirectBatch(f.client,f.store,f.usage,f.db)
        self.calls=[];self.events=[]
        def request(req):
            self.calls.append((req.method,req.url.path,str(req.url.query)))
            return f.server(req)
        f.client.http.close();f.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(request))
    def run_batch(self,**kwargs):
        self.flow.job(self.f.sites,**kwargs)(lambda *e:self.events.append(e))
    def test_one_login_snapshot_tdk_first_complete_and_resume(self):
        f=self.f
        original=f.server.__call__
        def request(req):
            self.calls.append((req.method,req.url.path,''))
            if req.url.path.endswith('/apply'):self.assertEqual(f.server.generated,2)
            return original(req)
        f.client.http.close();f.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(request))
        self.run_batch(workers=2)
        self.assertEqual(sum(p=='/api/auth/login' for _,p,_ in self.calls),1)
        self.assertEqual(sum(p=='/api/sites' for _,p,_ in self.calls),1)
        self.assertEqual(len(f.server.submissions),14)
        self.assertTrue(all(f.db.step(f.client.key,s.code,'publish')['state']=='done' for s in f.sites))
        self.run_batch(workers=2)
        self.assertEqual(len(f.server.submissions),14)
    def test_first_site_executes_while_next_template_is_checked_and_allocations_unique(self):
        f=self.f;f.server.rows=[]
        root=f.root/'templates';root.mkdir()
        for name in ('a','b'):
            folder=root/name;folder.mkdir();(folder/'index.html').write_text('<html><body>'+name+'</body></html>')
        first_published=threading.Event();original=f.server.__call__;digest=template_workflow.digest
        def request(req):
            response=original(req)
            if req.url.path=='/api/publish/apply':first_published.set()
            return response
        f.client.http.close();f.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(request))
        def slow(path,*args,**kwargs):
            if path.name=='b':self.assertTrue(first_published.wait(5),'first site was blocked by later template validation')
            return digest(path,*args,**kwargs)
        with patch.object(template_workflow,'digest',side_effect=slow):self.run_batch(root=str(root),upload=True,workers=2)
        self.assertEqual(len({r['digest'] for r in f.usage.rows()}),2)
        self.assertEqual(len(f.server.submissions),14)
    def test_non_template_failure_does_not_rebuild_or_stop_other_site(self):
        self.f.server.fail.add((1,'tdk'))
        with patch('cloudtool.siteadmin.direct_batch.RebuildWorkflow') as rebuild:
            self.run_batch(root=str(self.f.root),rebuild=True)
            rebuild.assert_not_called()
        self.assertEqual(self.f.db.step(self.f.client.key,'two.com','publish')['state'],'done')
    def test_cancel_before_site_execution_preserves_tdk_without_remote_mutation(self):
        original=self.flow.pipeline.allocate_tdk
        def allocate(target):
            result=original(target);self.f.client.cancel.set();return result
        with patch.object(self.flow.pipeline,'allocate_tdk',side_effect=allocate):
            with self.assertRaises(Cancelled):self.run_batch()
        self.assertFalse(self.f.server.submissions)
        self.assertIsNotNone(self.f.db.allocation(self.f.client.key,'one.com'))
    def test_template_failure_rebuilds_once_then_publishes(self):
        r=rebuild_fixtures.RebuildTests();r.setUp();self.addCleanup(r.doCleanups)
        f=r.fixture;f.usage.set(r.old['digest'],f.client.key,'done',1)
        r.server.fail.add((1,'h1'))
        DirectBatch(f.client,f.store,f.usage,f.db).job(f.sites[:1],str(r.sources),True,rebuild=True)(lambda *e:None)
        self.assertEqual(r.server.deleted,[1])
        self.assertEqual(f.db.step(f.client.key,'one.com','publish')['state'],'done')
        self.assertEqual(f.db.allocation(f.client.key,'one.com'),r.tdk)
    def test_failure_policy_rejects_infrastructure_and_ambiguous_errors(self):
        self.assertTrue(template_failure('h1','失败','about.html：未找到 <body>，无法注入'))
        for stage,state,detail in [('sync','失败','ZR JS 注入失败 1 个文件'),
                ('h1','结果未知','缺少 <body>'),('publish','失败','编码错误'),
                ('h1','失败','HTTP 503：缺少 <body>'),('upload','失败','权限不足')]:
            self.assertFalse(template_failure(stage,state,detail))
