import unittest
import httpx
from cloudtool.siteadmin.client import SiteClient
from cloudtool.siteadmin.models import Credentials
from cloudtool.siteadmin.site_catalog import SiteCatalog,domain_lines,imported_sites,site_visit_url
from test_siteadmin import Unlimited


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.results={1:{'current':None,'list':[]},2:{'current':{'site_id':2,'version':1,'is_current':True},'list':[]},3:{'current':None,'list':[{'version':1}]}}
        self.client=SiteClient(Credentials('https://test.invalid','admin','test secret'),httpx.MockTransport(self.respond))
        self.client.limiter=Unlimited();self.addCleanup(self.client.close)
    def respond(self,request):
        path=request.url.path
        if path.endswith('/login'):data={'access_token':'test token','user':{'role':'admin'}}
        elif path=='/api/sites':data={'list':[dict(id=i,code=f'{i}.com',name=f'{i}.com',primary_domain=f'*.{i}.com',page_count=7,link_protocol='https') for i in (1,2,3)],'total':3}
        else:data=self.results[int(request.url.params['site_id'])]
        return httpx.Response(200,json={'code':0,'data':data})
    def test_publication_uses_versions_not_page_count(self):
        rows=SiteCatalog(self.client).list_job(lambda *e:None)
        self.assertEqual([r['publication'] for r in rows],['未发布','已发布','待核实'])
        self.assertIn('发布历史',rows[2]['publication_detail'])
    def test_missing_or_wrong_identity_is_unknown(self):
        for data in ({'list':[]},{'current':{'site_id':99,'version':1,'is_current':True},'list':[]}):
            self.results[1]=data
            with self.assertRaises(ValueError):self.client.publication(1)
    def test_empty_nil_versions_are_unpublished(self):
        self.results[1]={'list':None,'current':None}
        self.assertEqual(self.client.publication(1),'未发布')
    def test_copy_normalizes_deduplicates_and_keeps_subdomain(self):
        text,invalid=domain_lines([{'primary_domain':d} for d in ('*.Example.COM','example.com.','www.example.com','https://bad.com','')])
        self.assertEqual(text,'example.com\nwww.example.com');self.assertEqual(invalid,2)
    def test_import_preserves_site_code_name_protocol_and_wildcard(self):
        row=dict(id=1,code='custom-code',name='站点一',primary_domain='sub.example.com',link_protocol='http')
        site=imported_sites([row])['sub.example.com']
        self.assertEqual(site.code,'custom-code');self.assertEqual(site.link_protocol,'http');self.assertEqual(site.primary_domain,'sub.example.com')
    def test_streams_rows_and_final_state(self):
        events=[];SiteCatalog(self.client).list_job(lambda *e:events.append(e))
        self.assertEqual(len([e for e in events if e[0].startswith('@site:')]),6)
        self.assertTrue(any(e[0]=='@request' and '3/3' in e[2] for e in events))
    def test_visit_www_normalizes_domain_and_uses_site_protocol(self):
        self.assertEqual(site_visit_url(dict(primary_domain='*.Example.COM.',link_protocol='https')),'https://www.example.com/')
        self.assertEqual(site_visit_url(dict(primary_domain='www.example.com',link_protocol='http')),'http://www.example.com/')
        self.assertEqual(site_visit_url(dict(primary_domain='*.sub.example.com',link_protocol='https')),'https://www.sub.example.com/')
    def test_visit_rejects_invalid_domain_and_protocol(self):
        for row in (dict(primary_domain='https://bad.com'),dict(primary_domain='example.com/path'),
                    dict(primary_domain='example.com',link_protocol='file')):
            with self.assertRaises(ValueError):site_visit_url(row)
