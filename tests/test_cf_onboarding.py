import tempfile
import unittest
from pathlib import Path
from cloudtool.cf_onboarding import CFOnboarding, ns_export, record_body
from cloudtool.cloudflare import Cloudflare
from cloudtool.storage import Store
from cloudtool.automation_model import WorkflowOptions, Site
from cloudtool.models import ApiError
from tests.test_automation import FakeCloudflare, ACCOUNT

class Client(FakeCloudflare):
    def __init__(self):
        super().__init__(); self.pending=[]; self.no_accounts=False; self.settings={}
    def all(self,path,params=None,**kwargs):
        if path == '/accounts':
            if self.no_accounts: raise ApiError('forbidden',403)
            return [{'id':ACCOUNT,'name':'My account'}]
        if path == '/zones' and params is None: return list(self.zones.values())
        return super().all(path,params,**kwargs)
    def get(self,path):
        if '/settings/' in path: return {'id':path.split('/')[-1], 'value':self.settings.get(path,'off'), 'editable':True}
        if path.endswith('/scan/review'): return self.pending
        return next(z for z in self.zones.values() if '/zones/'+z['id']==path)

    def request(self, method, path, body=None):
        result = super().request(method,path,body)
        if method == 'PATCH' and '/settings/' in path:self.settings[path]=body['value']
        return result

class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.client=Client(); self.store=Store(Path(self.tmp.name),self.client.key); self.addCleanup(self.store.close)
        self.service=CFOnboarding(self.client,self.store,Cloudflare(self.client,self.store))
    def add(self):
        plan=self.service.preview(WorkflowOptions(ACCOUNT,(Site('example.com'),),dns_enabled=False))
        return self.service.run_onboarding(plan,lambda *args:None)
    def test_add_reuses_zone_and_retains_nameservers(self):
        rows=self.add(); self.add()
        self.assertEqual(sum(path=='/zones' for _,path,_ in self.client.writes),1)
        self.assertEqual(len(self.service.saved()),1)
        self.assertEqual(ns_export(rows),'example.com|a.ns.cloudflare.com,b.ns.cloudflare.com')
        self.assertTrue(any(p.endswith('/scan/trigger') for _,p,_ in self.client.writes))
    def test_scan_failure_keeps_zone_and_ns(self):
        self.client.fail='/scan/trigger'
        rows=self.add()
        self.assertEqual(rows[0]['state'],'待更换 NS / 生效')
        self.assertTrue(ns_export(rows)); self.assertIn('未完成',rows[0]['dns'])
    def test_flexible_applied_once_and_existing_configuration_skipped(self):
        self.add()
        settings=[(p,b) for m,p,b in self.client.writes if '/settings/' in p]
        self.assertEqual(settings,[('/zones/example.com/settings/ssl_automatic_mode',{'value':'custom'}),
                                   ('/zones/example.com/settings/ssl',{'value':'flexible'})])
        self.add()
        self.assertEqual(len([p for _,p,_ in self.client.writes if '/settings/' in p]),2)
    def test_ssl_failure_visible_and_other_domain_continues(self):
        self.client.fail='/zones/example.com/settings/ssl'
        plan=self.service.preview(WorkflowOptions(ACCOUNT,(Site('example.com'),Site('other.com')),dns_enabled=False))
        rows=self.service.run_onboarding(plan,lambda *args:None)
        by_name={r['name']:r for r in rows}
        self.assertEqual(by_name['example.com']['state'],'需处理')
        self.assertIn('mock failure',by_name['example.com']['detail'])
        self.assertIn('SSL 灵活已配置',by_name['other.com']['detail'])
    def test_accounts_and_fallback(self):
        self.assertEqual(self.service.accounts()[0][0]['id'],ACCOUNT)
        self.add(); self.client.no_accounts=True
        accounts,warning=self.service.accounts()
        self.assertEqual(accounts[0]['id'],ACCOUNT); self.assertTrue(warning)
    def test_review_is_read_only_and_selected_records_are_imported(self):
        row=self.add()[0]
        record=dict(id='r1',type='MX',name='example.com',content='mail.example.com',priority=10,ttl=300,created_on='now')
        self.client.pending=[record]; count=len(self.client.writes)
        self.assertEqual(self.service.review(row)['pending'],[record]); self.assertEqual(len(self.client.writes),count)
        self.service.accept(row,[record])
        body=self.client.writes[-1][2]
        self.assertEqual(body,{'accepts':[record_body(record)]}); self.assertNotIn('id',body['accepts'][0])
    def test_existing_dns_not_imported_twice(self):
        row=self.add()[0]
        record=dict(id='r1',type='A',name='example.com',content='192.0.2.1',ttl=300)
        self.client.pending=[record]
        self.client.records['/zones/'+row['id']+'/dns_records']=[dict(record,id='existing')]
        count=len(self.client.writes)
        self.service.accept(row,[record])
        self.assertEqual(len(self.client.writes),count)
    def test_changed_scan_and_wrong_account_block_writes(self):
        row=self.add()[0]; count=len(self.client.writes)
        with self.assertRaises(ValueError): self.service.accept(row,[dict(id='gone')])
        row['account']='b'*32
        with self.assertRaises(ValueError): self.service.trigger(row)
        self.assertEqual(len(self.client.writes),count)
    def test_activation_refresh_and_export_invalid(self):
        row=self.add()[0]; self.client.zones['example.com']['status']='active'
        self.assertEqual(self.service.refresh([row])[0]['state'],'已激活')
        self.assertEqual(ns_export([{'name':'bad.com','id':'x','name_servers':['one']}]),'')
    def test_creation_failure_not_exported(self):
        self.client.fail='/zones'
        rows=self.add(); self.assertEqual(rows[0]['state'],'失败'); self.assertEqual(ns_export(rows),'')

if __name__=='__main__': unittest.main()
