import io
import json
import tempfile
import threading
import unittest
import zipfile
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import httpx
from cloudtool.siteadmin.templates import inventory,pack
from cloudtool.siteadmin.template_usage import TemplateUsage
from cloudtool.siteadmin.template_workflow import TemplateWorkflow
from cloudtool.siteadmin.models import Credentials,parse_sites
from cloudtool.siteadmin.client import SiteClient
from cloudtool.storage import Store
from cloudtool.models import Cancelled
from test_siteadmin import Server,Unlimited


class TemplateServer(Server):
    def __init__(self): super().__init__();self.steps=[];self.archives=[];self.fail_upload=False
    def __call__(self,request):
        path=request.url.path
        if path.endswith(('/upload-template','/sync','/scan')):
            self.steps.append(path.rsplit('/',1)[1])
            if path.endswith('/upload-template'):
                if self.fail_upload: raise httpx.ReadTimeout('upload timeout',request=request)
                message=BytesParser(policy=default).parsebytes(('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.content)
                data=next(message.iter_parts()).get_payload(decode=True)
                with zipfile.ZipFile(io.BytesIO(data)) as archive: self.archives.append(archive.namelist())
            return httpx.Response(200,json={'code':0,'data':{'file_count':2,'total':1}})
        result=super().__call__(request)
        for row in self.rows: row.setdefault('page_count',0)
        return result


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.sources=self.root/'sources';self.sources.mkdir()
        for name in ('collected-a','collected-b'):
            path=self.sources/name;path.mkdir();(path/'index.html').write_text(name);(path/'style.css').write_text('body{}')
        self.server=TemplateServer();self.client=SiteClient(Credentials('https://test.invalid','admin','test secret'),transport=httpx.MockTransport(self.server))
        self.client.limiter=Unlimited();self.addCleanup(self.client.close)
        self.store=Store(self.root/'data',self.client.key);self.addCleanup(self.store.close)
        self.usage=TemplateUsage(self.root/'ledger');self.addCleanup(self.usage.close)
        self.flow=TemplateWorkflow(self.client,self.store,self.usage)
    def preview(self,text='new-a.com\nnew-b.com'):
        return self.flow.preview_job(parse_sites(text),str(self.sources))(None)
    def test_end_to_end_order_distinct_domains_and_persistent_usage(self):
        plan,skipped=self.preview();self.assertEqual(len(plan.actions),10)
        self.assertEqual(self.server.rows,[]);self.assertEqual(self.usage.rows(),[])
        self.flow.execute_job(plan,1)(lambda *args:None)
        self.assertEqual(self.server.steps,['upload-template','sync','scan']*2)
        self.assertEqual([r['code'] for r in self.server.rows],['new-a.com','new-b.com'])
        self.assertTrue(all(set(a)=={'index.html','style.css'} for a in self.server.archives))
        self.assertTrue(all(r['stage']=='done' for r in self.usage.rows()))
        self.assertEqual(len(self.preview()[1]),2)
        with self.assertRaises(ValueError):self.preview('another-new.com')
        other=TemplateUsage(self.root/'ledger');self.assertEqual(len(other.rows()),2);other.close()
    def test_preview_hashes_only_needed_templates_and_reports_early(self):
        from unittest.mock import patch
        from cloudtool.siteadmin.templates import digest
        for name in ('unused-c','unused-d'):
            folder=self.sources/name;folder.mkdir();(folder/'index.html').write_text(name)
        events=[]
        with patch('cloudtool.siteadmin.template_workflow.digest',wraps=digest) as hashing:
            plan,_=self.flow.preview_job(parse_sites('a.com'),str(self.sources))(lambda *e:events.append(e))
        self.assertEqual(hashing.call_count,1)
        self.assertEqual(len(plan.actions),5)
        self.assertTrue(any(e[0]=='@preview:a.com' and e[1]=='预览就绪' for e in events))
        self.assertTrue(any(e[0]=='@request' and '校验' in e[2] for e in events))

    def test_completed_preview_does_not_scan_library(self):
        from unittest.mock import patch
        plan,_=self.preview('a.com');self.flow.execute_job(plan)(lambda *e:None)
        with patch('cloudtool.siteadmin.template_workflow.template_paths',side_effect=AssertionError('unnecessary scan')):
            plan,skipped=self.preview('a.com')
        self.assertFalse(plan.actions);self.assertEqual(len(skipped),1)

    def test_disappearing_candidate_does_not_abort_other_templates(self):
        from unittest.mock import patch
        from cloudtool.siteadmin.templates import digest
        def hashing(path,*args,**kwargs):
            if path.name=='collected-a':raise FileNotFoundError('template removed during preview')
            return digest(path,*args,**kwargs)
        with patch('cloudtool.siteadmin.template_workflow.digest',side_effect=hashing):
            plan,_=self.preview('a.com')
        self.assertEqual(plan.actions[0].body['template']['name'],'collected-b')

    def test_preview_streams_first_domain_before_hashing_second(self):
        from unittest.mock import patch
        from cloudtool.siteadmin.templates import digest
        events=[]
        def hashing(path,*args,**kwargs):
            if path.name=='collected-b':
                self.assertTrue(any(e[0]=='@preview:new-a.com' and e[1]=='预览就绪' for e in events))
            return digest(path,*args,**kwargs)
        with patch('cloudtool.siteadmin.template_workflow.digest',side_effect=hashing):
            plan,_=self.flow.preview_job(parse_sites('new-a.com\nnew-b.com'),str(self.sources))(lambda *e:events.append(e))
        self.assertEqual(len(plan.actions),10)

    def test_binary_disguised_as_html_is_rejected_before_upload(self):
        folder=self.sources/'collected-a'
        (folder/'code.html').write_bytes(b'GIF87a'+bytes(100))
        with self.assertRaisesRegex(ValueError,'code.html.*image/gif'):
            inventory(self.sources,threading.Event())
        self.assertEqual(self.server.steps,[])
        plan,_=self.preview('a.com')
        self.assertEqual(plan.actions[0].body['template']['name'],'collected-b')

    def test_failed_pack_continues_next_domain(self):
        from unittest.mock import patch
        original=pack
        def failing(template,*args):
            if template['name']=='collected-a':raise ValueError('压缩包超过后台 300 MB 限制')
            return original(template,*args)
        plan,_=self.preview()
        with patch('cloudtool.siteadmin.template_workflow.pack',side_effect=failing):
            self.flow.execute_job(plan,1)(lambda *args:None)
        self.assertEqual([r['code'] for r in self.server.rows],['new-b.com'])
        self.assertEqual(self.server.steps,['upload-template','sync','scan'])
        self.assertEqual(self.usage.rows()[0]['target'],'new-b.com')

    def test_unknown_upload_continues_and_preview_skips_unresolved(self):
        original=self.client.template_step
        def failure(site,stage,*args,**kwargs):
            if site==1 and stage=='upload-template':raise httpx.ReadTimeout('simulated')
            return original(site,stage,*args,**kwargs)
        self.client.template_step=failure
        plan,_=self.preview();self.flow.execute_job(plan,1)(lambda *args:None)
        ledger={r['target']:r['stage'] for r in self.usage.rows()}
        self.assertEqual(ledger,{'new-a.com':'uploading','new-b.com':'done'})
        later,issues=self.preview()
        self.assertEqual(later.actions,[])
        self.assertEqual({r['state'] for r in issues},{'需处理','已跳过'})

    def test_sync_injection_failure_recovers_without_reupload(self):
        from cloudtool.models import ApiError
        from cloudtool.siteadmin.recovery import RecoveryController
        original=self.client.template_step
        def failure(site,stage,*args,**kwargs):
            if site==1 and stage=='sync':raise ApiError('HTTP 400：同步已完成，但 ZR JS 注入失败 1 个文件')
            return original(site,stage,*args,**kwargs)
        self.client.template_step=failure
        plan,_=self.preview();self.flow.execute_job(plan,1)(lambda *args:None)
        self.assertEqual({r['target']:r['stage'] for r in self.usage.rows()},
                         {'new-a.com':'sync_failed','new-b.com':'done'})
        self.assertTrue(any(r['state']=='失败' and r['path']=='sync' for r in self.store.history()))
        self.client.template_step=original
        recovery=RecoveryController(self.client,self.store,self.usage)
        plan,_=recovery.job(recovery.entries()[0])(None)
        uploaded=self.server.steps.count('upload-template')
        self.flow.execute_job(plan)(lambda *args:None)
        self.assertEqual(self.server.steps.count('upload-template'),uploaded)
        self.assertTrue(all(r['stage']=='done' for r in self.usage.rows()))

    def test_insufficient_templates_no_remote_mutation(self):
        plan,issues=self.preview('a.com\nb.com\nc.com')
        self.assertEqual(len(plan.actions),10)
        self.assertEqual([r['target'] for r in issues],['c.com'])
        self.assertEqual(self.server.rows,[])
    def test_identical_copies_are_one_template(self):
        (self.sources/'collected-b'/'index.html').write_text('collected-a')
        plan,issues=self.preview()
        self.assertEqual(len(plan.actions),5)
        self.assertEqual(len(issues),1)
    def test_changed_template_before_execute_no_site_created(self):
        plan,_=self.preview('a.com');(self.sources/'collected-a'/'index.html').write_text('changed')
        self.flow.execute_job(plan)(lambda *args:None)
        self.assertEqual(self.server.rows,[])
        self.assertTrue(any(r['state']=='失败' for r in self.store.history()))
        self.assertEqual(self.usage.rows(),[])
    def test_upload_unknown_stops_sync_and_cannot_reallocate(self):
        plan,_=self.preview('a.com');self.server.fail_upload=True
        self.flow.execute_job(plan)(lambda *args:None)
        self.assertEqual(self.server.steps,['upload-template'])
        with self.assertRaises(ValueError):self.preview('a.com')
        plan2,_=self.preview('b.com')
        self.assertEqual(plan2.actions[0].body['template']['name'],'collected-b')
    def test_parallel_sites_serialize_uploads(self):
        import time
        plan,_=self.preview();original=self.client.template_step
        lock=threading.Lock();active=0;peak=0
        def step(site,stage,archive=None,progress=None):
            nonlocal active,peak
            if stage!='upload-template':return original(site,stage,archive,progress)
            with lock:active+=1;peak=max(peak,active)
            try:
                time.sleep(.1)
                return original(site,stage,archive,progress)
            finally:
                with lock:active-=1
        self.client.template_step=step;events=[]
        self.flow.execute_job(plan,2)(lambda *e:events.append(e))
        self.assertEqual(peak,1)
        self.assertEqual(sum(e[1]=='排队中' for e in events),2)
        self.assertTrue(all(r['stage']=='done' for r in self.usage.rows()))

    def test_upload_progress_is_per_action_and_precedes_success(self):
        plan,_=self.preview();events=[]
        self.flow.execute_job(plan,2)(lambda *event:events.append(event))
        for action in (a for a in plan.actions if a.path=='upload'):
            own=[(state,detail) for aid,state,detail in events if aid==action.id]
            progress=[json.loads(detail) for state,detail in own if detail.startswith('{"upload_progress"')]
            self.assertTrue(progress)
            self.assertEqual(progress[0]['sent'],0)
            self.assertEqual(progress[-1]['upload_progress'],100)
            self.assertEqual(progress[-1]['sent'],progress[-1]['total'])
            self.assertEqual(own[-1][0],'成功')
            self.assertTrue(all(0<=p['sent']<=p['total'] for p in progress))

    def test_assign_selected_template_to_existing_site(self):
        self.server.rows=[dict(id=42,code='a.com',name='Custom name',primary_domain='*.a.com',link_protocol='http',page_count=0)]
        plan,_=self.flow.assign_job(self.server.rows[0],str(self.sources/'collected-b'))(None)
        self.flow.execute_job(plan)(lambda *args:None)
        self.assertEqual(len(self.server.rows),1)
        self.assertEqual(self.usage.rows()[0]['site_id'],42)
        self.assertEqual(self.server.steps,['upload-template','sync','scan'])
        restored=Store(self.root/'data',self.client.key)
        try:
            history=restored.history()
            self.assertEqual(len(history),5)
            self.assertTrue(all(row['state']=='成功' for row in history))
        finally:restored.close()
        with self.assertRaises(ValueError):self.flow.assign_job(self.server.rows[0],str(self.sources/'collected-a'))(None)

    def test_assign_missing_or_populated_site_does_not_create(self):
        row=dict(id=42,code='a.com',name='a.com',primary_domain='*.a.com',link_protocol='https',page_count=0)
        with self.assertRaises(ValueError):self.flow.assign_job(row,str(self.sources/'collected-a'))(None)
        self.assertEqual(self.server.rows,[])
        row['page_count']=3
        with self.assertRaises(ValueError):self.flow.assign_job(row,str(self.sources/'collected-a'))(None)

    def test_explicit_recovery(self):
        from cloudtool.siteadmin.recovery import RecoveryController
        plan,_=self.preview('a.com');self.server.fail_upload=True
        self.flow.execute_job(plan)(lambda *args:None)
        recovery=RecoveryController(self.client,self.store,self.usage)
        entry=recovery.entries()[0]
        self.assertIn('ReadTimeout',str(self.store.history()))
        self.store.history=lambda *args,**kwargs:[]  # Display history may no longer contain old tasks.
        next_plan,_=recovery.job(entry)(None)
        self.server.fail_upload=False
        self.flow.execute_job(next_plan)(lambda *args:None)
        self.assertEqual(len(self.server.rows),1)
        self.assertEqual(self.server.steps,['upload-template','upload-template','sync','scan'])
        self.assertEqual(self.usage.rows()[0]['digest'],entry['digest'])
        with self.assertRaises(ValueError): recovery.job(entry)(None)

    def test_verified_upload_skips_reupload(self):
        from cloudtool.siteadmin.recovery import RecoveryController
        plan,_=self.preview('a.com');self.server.fail_upload=True
        self.flow.execute_job(plan)(lambda *args:None)
        recovery=RecoveryController(self.client,self.store,self.usage)
        next_plan,_=recovery.job(recovery.entries()[0],completed=True)(None)
        self.flow.execute_job(next_plan)(lambda *args:None)
        self.assertEqual(self.server.steps,['upload-template','sync','scan'])
        self.assertEqual(self.usage.rows()[0]['stage'],'done')

    def test_recovery_rejects_replaced_site(self):
        from cloudtool.siteadmin.recovery import RecoveryController
        plan,_=self.preview('a.com');self.server.fail_upload=True
        self.flow.execute_job(plan)(lambda *args:None)
        recovery=RecoveryController(self.client,self.store,self.usage)
        entry=recovery.entries()[0];self.server.rows[0]['id']=999
        with self.assertRaises(ValueError):recovery.job(entry)(None)
        self.assertEqual(self.usage.rows()[0]['stage'],'uploading')

    def test_reservation_conflict_and_cancelled_pack(self):
        template=inventory(self.sources,threading.Event())[0]
        self.usage.reserve(template,'one','a.com')
        with self.assertRaises(ValueError):self.usage.reserve(template,'two','b.com')
        stop=threading.Event();stop.set()
        with self.assertRaises(Cancelled):pack(template,self.root/'temp.zip',stop)
    def test_existing_populated_site_rejected(self):
        self.server.rows=[dict(id=1,code='a.com',name='a.com',primary_domain='*.a.com',link_protocol='https',page_count=1)]
        # Avoid mock automatically clearing count.
        self.client.sites=lambda *args:self.server.rows
        with self.assertRaises(ValueError):self.preview('a.com')
    def test_resume_after_completed_upload_does_not_upload_again(self):
        plan,_=self.preview('a.com')
        upload=next(a.id for a in plan.actions if a.path=='upload')
        def emit(aid,state,detail):
            if aid==upload and state=='成功':self.client.cancel.set()
        try:self.flow.execute_job(plan)(emit)
        except Cancelled:pass
        self.assertEqual(self.usage.rows()[0]['stage'],'uploaded')
        self.client.cancel.clear()
        next_plan,_=self.preview('a.com')
        self.flow.execute_job(next_plan)(lambda *args:None)
        self.assertEqual(self.server.steps,['upload-template','sync','scan'])
        self.assertEqual(self.usage.rows()[0]['stage'],'done')


if __name__=='__main__':unittest.main()
