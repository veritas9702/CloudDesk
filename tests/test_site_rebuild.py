import json
import tempfile
import unittest
from pathlib import Path
import httpx
from cloudtool.siteadmin.rebuild import RebuildWorkflow,validate_injection_template
from cloudtool.siteadmin.templates import digest
from cloudtool.models import Plan
import test_site_pipeline as fixtures
from test_site_pipeline import PipelineServer


class RebuildServer(PipelineServer):
    def __init__(self):super().__init__();self.deleted=[];self.published=False;self.delete_timeout=False
    def __call__(self,request):
        if request.url.path=='/api/publish/versions':
            site_id=int(request.url.params['site_id'])
            return httpx.Response(200,json={'code':0,'data':{'current':dict(site_id=site_id,version=1,is_current=True) if self.published else None,'list':[]}})
        if request.method=='DELETE':
            site_id=int(request.url.path.split('/')[-1]);body=json.loads(request.content)
            row=next(r for r in self.rows if r['id']==site_id)
            assert body['confirm_code']==row['code']
            self.deleted.append(site_id);self.rows.remove(row)
            if self.delete_timeout:raise httpx.ReadTimeout('lost delete reply',request=request)
            return httpx.Response(200,json={'code':0,'data':{'code':row['code']}})
        result=super().__call__(request)
        if request.method=='POST' and request.url.path=='/api/sites':
            self.rows[-1]['id']+=100
            data=result.json();data['data']['id']=self.rows[-1]['id'];return httpx.Response(200,json=data)
        return result


class RebuildTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PipelineTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.server=RebuildServer();self.server.rows=f.server.rows[:1]
        f.client.http.close();f.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(self.server))
        self.flow=RebuildWorkflow(f.client,f.store,f.usage,f.db)
        self.sources=f.root/'templates';self.sources.mkdir()
        old=self.sources/'old';old.mkdir();(old/'index.html').write_text('<html><body>old</body></html>')
        self.old=dict(path=str(old),digest=digest(old,f.client.cancel),name='old')
        f.usage.reserve(self.old,f.client.key,'one.com');f.usage.set(self.old['digest'],f.client.key,'syncing',1)
        good=self.sources/'new';good.mkdir();(good/'index.html').write_text('<html><body>new</body></html>')
        self.tdk=f.db.allocate(f.client.key,'one.com',dict(title='固定标题',description='固定描述',keywords='固定关键词'))
    def preview(self):return self.flow.preview_job(['one.com'],str(self.sources))(lambda *e:None)
    def test_rebuild_delete_create_upload_scan_six_steps_preserves_tdk(self):
        f=self.fixture;plan,issues=self.preview();self.assertFalse(issues)
        self.assertEqual(len(plan.actions),14);self.assertFalse(self.server.deleted)
        self.flow.execute_job(plan)(lambda *e:None)
        self.assertEqual(self.server.deleted,[1]);self.assertEqual(self.server.steps,['upload-template','sync','scan'])
        self.assertEqual(f.db.allocation(f.client.key,'one.com'),self.tdk)
        self.assertEqual(f.db.step(f.client.key,'one.com','placeholder')['state'],'done')
        self.assertNotEqual(f.usage.entry(f.client.key,'one.com')['site_id'],1)
        self.assertEqual(f.usage.excluded()[0]['digest'],self.old['digest'])
        second,issues=self.preview();self.assertFalse(second.actions);self.assertIn('已重建过一次',issues[0]['detail'])
    def test_missing_body_template_skipped_before_any_delete(self):
        (self.sources/'new'/'index.html').write_text('<html>missing body</html>')
        plan,issues=self.preview();self.assertFalse(plan.actions);self.assertIn('缺少 <body>',issues[0]['detail'])
        self.assertFalse(self.server.deleted)
    def test_template_change_after_preview_never_deletes(self):
        plan,_=self.preview();(self.sources/'new'/'index.html').write_text('<body>changed</body>')
        self.flow.execute_job(plan)(lambda *e:None)
        self.assertFalse(self.server.deleted);self.assertIsNone(self.fixture.db.rebuild(self.fixture.client.key,'one.com'))
    def test_published_site_never_automatically_deleted(self):
        self.server.published=True;plan,issues=self.preview()
        self.assertFalse(plan.actions);self.assertIn('发布',issues[0]['detail']);self.assertFalse(self.server.deleted)
    def test_unconfirmed_publication_blocks_rebuild_even_if_version_not_yet_visible(self):
        f=self.fixture
        f.db.save(f.client.key,'one.com','publish',state='submitting',task_id=0)
        plan,issues=self.preview()
        self.assertFalse(plan.actions);self.assertIn('发布任务',issues[0]['detail'])
        self.assertFalse(self.server.deleted)
    def test_unknown_delete_does_not_create_or_repeat(self):
        plan,_=self.preview();self.server.delete_timeout=True
        self.flow.execute_job(plan)(lambda *e:None)
        self.assertEqual(self.server.deleted,[1]);self.assertFalse(self.server.steps)
        plan,issues=self.preview();self.assertFalse(plan.actions);self.assertIn('已重建过一次',issues[0]['detail'])
    def test_second_failure_stops_without_third_attempt(self):
        self.server.fail.add((101,'h1'));plan,_=self.preview()
        self.flow.execute_job(plan)(lambda *e:None)
        self.assertEqual(self.fixture.db.step(self.fixture.client.key,'one.com','h1')['state'],'failed')
        plan,issues=self.preview();self.assertFalse(plan.actions);self.assertTrue(issues)
        self.assertEqual(self.server.deleted,[1])
    def test_automatic_followup_includes_initial_preview_failure(self):
        events=[]
        self.flow.after_job(lambda emit:None,['one.com'],str(self.sources),1)(lambda *e:events.append(e))
        self.assertEqual(self.server.deleted,[1]);self.assertTrue(any(e[0]=='@rebuild-plan' for e in events))
    def test_body_in_script_does_not_pass_preflight(self):
        file=self.sources/'new'/'index.html';file.write_text('<script>var x="<body>";</script>')
        with self.assertRaisesRegex(ValueError,'body'):validate_injection_template(file.parent,self.fixture.client.cancel)
    def test_replacement_claimed_elsewhere_before_execution_keeps_original_site(self):
        plan,_=self.preview();template=plan.actions[0].body['template']
        f=self.fixture;f.usage.reserve(template,f.client.key,'another.com')
        self.flow.execute_job(plan)(lambda *e:None)
        self.assertFalse(self.server.deleted)
        self.assertEqual(f.usage.entry(f.client.key,'one.com')['site_id'],1)
    def test_replacement_reservation_blocks_other_target(self):
        plan,_=self.preview();template=plan.actions[0].body['template'];f=self.fixture
        f.usage.reserve_replacement(template,f.client.key,'one.com','ticket')
        with self.assertRaisesRegex(ValueError,'预留'):f.usage.reserve(template,f.client.key,'another.com')
        f.usage.release_replacements('ticket')
        f.usage.reserve(template,f.client.key,'another.com')
