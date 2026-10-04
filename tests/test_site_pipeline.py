import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from cloudtool.siteadmin.models import Credentials, parse_sites
from cloudtool.siteadmin.client import SiteClient
from cloudtool.siteadmin.pipeline import SitePipeline, PipelineSteps
from cloudtool.siteadmin.pipeline_api import STAGES
from cloudtool.siteadmin.pipeline_store import PipelineStore
from cloudtool.siteadmin.template_usage import TemplateUsage
from cloudtool.storage import Store
from test_templates import TemplateServer
from test_siteadmin import Unlimited


class PipelineServer(TemplateServer):
    def __init__(self):
        super().__init__()
        self.generated=0; self.tasks={}; self.submissions=[]; self.reads=[]; self.fail=set()
        self.unknown=False; self.poll_timeout=False; self.preview_fail=set(); self.detect_calls=[]
        self.pages=2; self.publish_previews=[]

    def __call__(self,request):
        path=request.url.path
        body=json.loads(request.content) if request.content and 'json' in request.headers.get('content-type','') else {}
        def ok(data):return httpx.Response(200,json={'code':0,'data':data})
        if path=='/api/tdk/lexicon/generate':
            self.generated+=1
            return ok(dict(title=f'站点标题{self.generated}',description=f'描述{self.generated}',keywords=f'词{self.generated}'))
        if path.startswith('/api/tasks/'):
            task_id=int(path.split('/')[3]); task=self.tasks[task_id]
            if path.endswith('/items'):
                items=[dict(id=i+1,rel_path=f'{i}.html',status='failed' if i==0 else 'success',message='编码错误' if i==0 else '') for i in range(task['total'])]
                return ok(dict(list=items,total=len(items)))
            self.reads.append(task_id)
            if self.poll_timeout:
                self.poll_timeout=False;raise httpx.ReadTimeout('simulated',request=request)
            return ok(dict(task=task,running=False,progress=task['total']))
        if path.endswith('/pages'):
            allrows=[dict(id=i+1,rel_path=f'{i}.html') for i in range(self.pages)]
            page=int(request.url.params.get('page',1));size=int(request.url.params.get('size',200))
            return ok(dict(list=allrows[(page-1)*size:page*size],total=len(allrows)))
        if path=='/api/stat/detect':
            self.detect_calls.append(body)
            return ok(dict(files=[dict(rel_path=p,deletable=1,review=1) for p in body['rel_paths']]))
        if path=='/api/publish/preview':
            self.publish_previews.append(body['site_id'])
            return ok(dict(expect_digest='snapshot',diff=dict(digest='snapshot',added=2,modified=0,deleted=0,unchanged=0)))
        if path.endswith('/preview'):
            stage=path.split('/')[2]
            return ok(dict(files=2,failed=int((body['site_id'],stage) in self.preview_fail),results=[]))
        if path.endswith(('/apply','/clean')):
            stage='stat_clean' if path=='/api/stat/clean' else path.split('/')[2]
            assert body['async'] is True
            self.submissions.append((body['site_id'],stage,body))
            task_id=len(self.tasks)+1; failed=(body['site_id'],stage) in self.fail
            self.tasks[task_id]=dict(id=task_id,site_id=body['site_id'],type=stage,status='partial' if failed else 'success',
                                    total=len(body.get('rel_paths',[])) or self.pages,succeeded=1,failed=int(failed),needs_review=0)
            if self.unknown:
                self.unknown=False;raise httpx.ReadTimeout('submitted but response lost',request=request)
            return ok(dict(task_id=task_id,async_=True,**{'async':True}))
        result=super().__call__(request)
        if path.endswith('/scan'):
            for row in self.rows:row['page_count']=self.pages
        return result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.server=PipelineServer()
        self.client=SiteClient(Credentials('https://test.invalid','admin','test secret'),httpx.MockTransport(self.server))
        self.client.limiter=Unlimited();self.addCleanup(self.client.close)
        self.store=Store(self.root,self.client.key);self.addCleanup(self.store.close)
        self.usage=TemplateUsage(self.root);self.addCleanup(self.usage.close)
        self.db=PipelineStore(self.root);self.addCleanup(self.db.close)
        self.flow=SitePipeline(self.client,self.store,self.usage,self.db)
        self.events=[]
        self.sites=parse_sites('one.com\ntwo.com')
        self.server.rows=[dict(s.body(),id=i+1,page_count=2) for i,s in enumerate(self.sites)]

    def preview(self,sites=None,**kwargs):
        return self.flow.preview_job(sites or self.sites,**kwargs)(lambda *e:self.events.append(e))

    def execute(self,plan):
        self.flow.execute_job(plan,1)(lambda *e:self.events.append(e))

    def test_tdk_allocated_before_mutations_order_and_completed_skip(self):
        plan,issues=self.preview();self.assertFalse(issues)
        self.assertEqual(self.server.generated,2);self.assertFalse(self.server.submissions)
        self.assertNotEqual(plan.actions[0].body['tdk'],plan.actions[7].body['tdk'])
        self.execute(plan)
        self.assertEqual([(i,s) for i,s,_ in self.server.submissions],[(i,s) for i in (1,2) for s in STAGES])
        self.assertFalse(self.server.steps)
        self.assertTrue(all(b.get('skip_tdk') is True for _,s,b in self.server.submissions if s=='convert'))
        self.assertTrue(all(b.get('template')=='{{title}}' for _,s,b in self.server.submissions if s=='h1'))
        self.assertTrue(all(b.get('include_review') is False for _,s,b in self.server.submissions if s=='stat_clean'))
        plan,_=self.preview();self.execute(plan)
        self.assertEqual(len(self.server.submissions),14);self.assertEqual(self.server.generated,2)
        other=PipelineStore(self.root)
        try:self.assertEqual(other.allocation(self.client.key,'one.com'),plan.actions[0].body['tdk'])
        finally:other.close()

    def test_failed_tdk_blocks_only_own_site_and_retry_reuses_values(self):
        self.server.fail.add((1,'tdk'))
        plan,_=self.preview();self.execute(plan)
        self.assertEqual([s for i,s,_ in self.server.submissions if i==1],['tdk'])
        self.assertEqual([s for i,s,_ in self.server.submissions if i==2],list(STAGES))
        self.assertIn('编码错误',self.db.step(self.client.key,'one.com','tdk')['detail'])
        first=self.server.submissions[0][2]
        self.server.fail.clear();plan,_=self.preview();self.execute(plan)
        self.assertEqual(self.server.submissions[8][2],first)
        self.assertEqual(self.server.generated,2)

    def test_unknown_submission_is_not_replayed_and_can_attach_task(self):
        self.server.unknown=True
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(self.db.step(self.client.key,'one.com','tdk')['state'],'submitting')
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(len(self.server.submissions),1)
        self.flow.attach_task_job('one.com','tdk',1)(None)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES))

    def test_poll_timeout_resumes_original_task_without_reupload(self):
        self.server.poll_timeout=True
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(self.db.step(self.client.key,'one.com','tdk')['task_id'],1)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES))

    def test_conversion_retry_only_failed_files(self):
        self.server.fail.add((1,'convert'))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.server.fail.clear()
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        conversions=[b for _,s,b in self.server.submissions if s=='convert']
        self.assertEqual(len(conversions),2)
        self.assertEqual(conversions[1]['rel_paths'],['0.html'])
        self.assertEqual(self.db.step(self.client.key,'one.com','placeholder')['state'],'done')

    def test_preview_failure_blocks_write_and_following_stages(self):
        self.server.preview_fail.add((1,'h1'))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES[:4]))

    def test_stat_detection_batches_every_page_not_first_200(self):
        self.server.pages=251
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([len(b['rel_paths']) for b in self.server.detect_calls],[100,100,51])
        clean=next(b for _,s,b in self.server.submissions if s=='stat_clean')
        self.assertEqual(len(clean['rel_paths']),251)

    def test_new_upload_scan_then_tdk(self):
        self.server.rows=[]
        sources=self.root/'sources';sources.mkdir()
        folder=sources/'template';folder.mkdir();(folder/'index.html').write_text('<html><body>hello</body></html>')
        plan,issues=self.preview(self.sites[:1],root=str(sources),upload=True)
        self.assertFalse(issues);self.assertEqual(len(plan.actions),12)
        self.execute(plan)
        self.assertEqual(self.server.steps,['upload-template','sync','scan'])
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES))
        plan,_=self.preview(self.sites[:1],root=str(sources),upload=True);self.execute(plan)
        self.assertEqual(self.server.steps,['upload-template','sync','scan'])

    def test_remote_site_changed_blocks_processing(self):
        plan,_=self.preview(self.sites[:1]);self.server.rows[0]['primary_domain']='*.changed.com'
        self.execute(plan);self.assertFalse(self.server.submissions)

    def test_old_six_step_checkpoints_only_add_publication(self):
        from cloudtool.models import Plan
        plan,_=self.preview(self.sites[:1])
        self.execute(Plan(plan.owner,plan.actions[:-1]))
        self.assertEqual(len(self.server.submissions),6)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES))
        self.assertEqual(self.server.publish_previews,[1])
        self.assertEqual(self.server.submissions[-1][2]['expect_digest'],'snapshot')

    def test_failed_publish_never_replays_successful_processing_or_publication(self):
        self.server.fail.add((1,'publish'))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES))
        self.assertEqual(self.server.publish_previews,[1])
        self.assertEqual(self.db.step(self.client.key,'one.com','publish')['state'],'failed')

    def test_publish_timeout_preserves_id_and_resumes_without_resubmitting(self):
        original=self.server.__call__
        def transport(request):
            response=original(request)
            if request.url.path=='/api/publish/apply':self.server.poll_timeout=True
            return response
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(self.db.step(self.client.key,'one.com','publish')['state'],'running')
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(len(self.server.submissions),7)
        self.assertEqual(self.db.step(self.client.key,'one.com','publish')['state'],'done')

    def test_publish_unknown_submission_requires_task_reconciliation(self):
        original=self.server.__call__
        def transport(request):
            if request.url.path=='/api/publish/apply':self.server.unknown=True
            return original(request)
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(len(self.server.submissions),7)
        self.assertEqual(self.db.step(self.client.key,'one.com','publish')['state'],'submitting')
        self.flow.attach_task_job('one.com','publish',7)(None)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(len(self.server.submissions),7)
        self.assertEqual(self.db.step(self.client.key,'one.com','publish')['state'],'done')

    def test_invalid_publish_preview_does_not_submit(self):
        original=self.server.__call__
        def transport(request):
            if request.url.path=='/api/publish/preview':
                return httpx.Response(200,json={'code':0,'data':{'expect_digest':''}})
            return original(request)
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES[:-1]))

    def test_allocation_duplicate_rejected_and_owner_isolated(self):
        self.preview(self.sites[:1]);tdk=self.db.allocation(self.client.key,'one.com')
        with self.assertRaises(ValueError):self.db.allocate(self.client.key,'other.com',tdk)
        self.assertIsNone(self.db.allocation('another-account','one.com'))

    def test_cancel_retains_task_id_and_resumes_without_submission(self):
        original=self.server.__call__
        def transport(request):
            response=original(request)
            if request.url.path=='/api/tasks/1':
                self.client.cancel.set()
                data=response.json();data['data']['task']['status']='running'
                return httpx.Response(200,json=data)
            return response
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1])
        from cloudtool.models import Cancelled
        try:self.execute(plan)
        except Cancelled:pass
        self.assertEqual(len(self.server.submissions),1)
        self.assertEqual(self.db.step(self.client.key,'one.com','tdk')['task_id'],1)
        self.assertEqual(self.db.step(self.client.key,'one.com','tdk')['state'],'running')
        self.client.cancel.clear();self.client.http.close()
        self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(self.server))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],list(STAGES))

    def test_wrong_task_identity_cannot_be_attached(self):
        self.server.unknown=True;plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.server.tasks[1]['site_id']=2
        with self.assertRaisesRegex(ValueError,'身份不匹配'):self.flow.attach_task_job('one.com','tdk',1)(None)
        self.assertEqual(self.db.step(self.client.key,'one.com','tdk')['state'],'submitting')

    def test_incomplete_conversion_items_never_replay_full_site(self):
        self.server.fail.add((1,'convert'));plan,_=self.preview(self.sites[:1]);self.execute(plan)
        original=self.server.__call__
        def transport(request):
            if request.url.path.endswith('/items'):
                return httpx.Response(200,json={'code':0,'data':{'list':[],'total':0}})
            return original(request)
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual([s for _,s,_ in self.server.submissions],['tdk','convert'])

    def test_rejected_conversion_retry_keeps_failed_file_scope(self):
        self.server.fail.add((1,'convert'));plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.server.fail.clear();original=self.server.__call__;rejected=[]
        def transport(request):
            if request.url.path=='/api/convert/apply' and not rejected:
                rejected.append(True)
                return httpx.Response(400,json={'code':1,'message':'站点忙'})
            return original(request)
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        retries=[b for _,s,b in self.server.submissions if s=='convert']
        self.assertEqual(retries[-1]['rel_paths'],['0.html'])

    def test_success_with_review_count_blocks_downstream(self):
        original=self.server.__call__
        def transport(request):
            response=original(request)
            if request.url.path=='/api/tasks/1':
                data=response.json();data['data']['task']['needs_review']=1
                return httpx.Response(200,json=data)
            return response
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview(self.sites[:1]);self.execute(plan)
        self.assertEqual(len(self.server.submissions),1)
        self.assertEqual(self.db.step(self.client.key,'one.com','tdk')['state'],'failed')

    def test_two_site_workers_progress_independently_while_tdk_running(self):
        released=threading.Event();original=self.server.__call__
        def transport(request):
            response=original(request)
            if request.url.path=='/api/placeholder/apply':
                if json.loads(request.content)['site_id']==2:released.set()
            if request.url.path.startswith('/api/tasks/') and not request.url.path.endswith('/items'):
                data=response.json();task=data['data']['task']
                if task['site_id']==1 and task['type']=='tdk' and not released.is_set():
                    task['status']='running';return httpx.Response(200,json=data)
            return response
        self.client.http.close();self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(transport))
        plan,_=self.preview()
        with patch.object(PipelineSteps,'poll_interval',.005),patch.object(PipelineSteps,'wait_limit',3):
            self.flow.execute_job(plan,2)(lambda *e:self.events.append(e))
        operations=[(i,s) for i,s,_ in self.server.submissions]
        self.assertLess(operations.index((2,'placeholder')),operations.index((1,'convert')))
        self.assertEqual(self.db.step(self.client.key,'one.com','placeholder')['state'],'done')
