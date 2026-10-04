"""Actual SSM wire contracts via MockTransport, without touching a live server."""
import json
import tempfile
import unittest
from pathlib import Path
import httpx
from cloudtool.siteadmin.models import Credentials, parse_sites, server_url
from cloudtool.siteadmin.client import SiteClient
from cloudtool.siteadmin.controller import SiteController
from cloudtool.storage import Store
from cloudtool.models import ApiError, Cancelled


class Unlimited:
    def acquire(self,cancel):
        if cancel.is_set(): raise Cancelled()


class Server:
    def __init__(self): self.rows=[]; self.calls=[]; self.fail=''; self.role='admin'; self.change=False
    def __call__(self,request):
        self.calls.append(request)
        path = request.url.path
        if path == '/api/auth/login':
            assert json.loads(request.content) == {'username':'admin','password':'test secret'}
            return httpx.Response(200,json={'code':0,'data':{'access_token':'ACCESS_SECRET','refresh_token':'REFRESH_SECRET','user':{'role':self.role},'must_change_password':self.change}})
        assert request.headers['Authorization']=='Bearer ACCESS_SECRET'
        if request.method == 'GET':
            return httpx.Response(200,json={'code':0,'data':{'list':self.rows,'total':len(self.rows)}})
        if self.fail=='timeout': raise httpx.ReadTimeout('sent',request=request)
        if self.fail=='server': return httpx.Response(500,json={'code':500,'message':'failure'})
        row=dict(json.loads(request.content),id=len(self.rows)+1)
        self.rows.append(row)
        return httpx.Response(200,json={'code':0,'data':row})


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.server=Server(); self.client=SiteClient(Credentials('https://test.invalid','admin','test secret'),transport=httpx.MockTransport(self.server))
        self.client.limiter=Unlimited(); self.addCleanup(self.client.close)
        self.store=Store(Path(self.temp.name),self.client.key); self.addCleanup(self.store.close)
        self.controller=SiteController(self.client,self.store)
    def preview(self): return self.controller.preview_job(parse_sites('example.com\nexample.net'))(None)[0]
    def test_defaults_normalization_and_duplicates(self):
        sites=parse_sites('Example.com\n*.example.com\nexample.net')
        self.assertEqual(len(sites),2); self.assertEqual(sites[0].primary_domain,'*.example.com')
        self.assertEqual(sites[0].code,'example.com')
        with self.assertRaises(ValueError): parse_sites('https://example.com')
    def test_credentials_spaces_and_origin_validation(self):
        value=Credentials('https://test.invalid/login','admin',' test secret ').encode()
        self.assertEqual(Credentials.decode(value).password,' test secret ')
        self.assertEqual(server_url('http://127.0.0.1:8080/sites'),'http://127.0.0.1:8080')
        for url in ('file:///tmp','https://user:pass@test.invalid','https://test.invalid/?token=x'):
            with self.assertRaises(ValueError): server_url(url)
    def test_preview_no_create_execution_and_skip(self):
        plan=self.preview(); self.assertEqual(self.server.rows,[])
        self.controller.execute_job(plan,2)(lambda *args:None)
        self.assertEqual(len(self.server.rows),2)
        plan2,skipped=self.controller.preview_job(parse_sites('example.com\nexample.net'))(None)
        self.assertEqual(plan2.actions,[]); self.assertEqual(len(skipped),2)
        with self.assertRaises(ValueError): self.controller.execute_job(plan)(lambda *args:None)
    def test_conflict_and_remote_change(self):
        plan=self.preview()
        self.server.rows=[dict(id=1,code='example.com',name='other',primary_domain='*.example.com',link_protocol='https')]
        with self.assertRaises(ValueError): self.preview()
        self.controller.execute_job(plan)(lambda *args:None)
        rows=self.store.history()
        self.assertTrue(any(r['target']=='example.com' and r['state']=='失败' for r in rows))
        self.assertTrue(any(r['target']=='example.net' and r['state']=='成功' for r in rows))
    def test_unknown_write_not_retried(self):
        plan=self.preview(); self.server.fail='timeout'
        self.controller.execute_job(plan)(lambda *args:None)
        self.assertEqual(sum(r.method=='POST' and r.url.path=='/api/sites' for r in self.server.calls),2)
        self.assertTrue(all(r['state']=='结果未知' for r in self.store.history()))
    def test_redaction_and_list_projection(self):
        self.client.login()
        self.assertNotIn('test secret',self.client.safe('test secret ACCESS_SECRET REFRESH_SECRET'))
        self.assertNotIn('ACCESS_SECRET',self.client.safe('ACCESS_SECRET'))
        self.server.rows=[dict(id=1,code='example.com',primary_domain='*.example.com',baidu_push_token='DO_NOT_EXPORT')]
        self.assertNotIn('baidu_push_token',self.client.sites()[0])
    def test_admin_and_initial_password(self):
        self.server.role='operator'
        with self.assertRaises(ApiError): self.preview()
        self.server.role='admin';self.server.change=True
        with self.assertRaises(ApiError): self.preview()
    def test_redirect_not_followed(self):
        self.client.http.close()
        self.client.http=httpx.Client(base_url='https://test.invalid',transport=httpx.MockTransport(lambda _:httpx.Response(302,headers={'Location':'https://other.invalid'})))
        with self.assertRaises(ApiError): self.client.login()
    def test_account_boundary(self):
        with self.assertRaises(ValueError): SiteController(self.client,type('Store',(),{'key':'other'})())


if __name__=='__main__': unittest.main()
