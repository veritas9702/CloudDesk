import unittest,tempfile
from pathlib import Path
from cloudtool.cloudflare import Cloudflare
from cloudtool.storage import Store
from tests.test_automation import FakeCloudflare,ACCOUNT

class BatchFeedbackTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.client=FakeCloudflare();self.store=Store(Path(self.tmp.name),self.client.key);self.addCleanup(self.store.close)
  self.provider=Cloudflare(self.client,self.store)
  self.zone={'id':'z','name':'example.com'}
 def test_multiple_record_names_match_root_and_wildcard(self):
  self.client.records['/zones/z/dns_records']=[{'id':str(i),'type':'A','name':n,'content':'192.0.2.1'} for i,n in enumerate(['example.com','*.example.com','www.example.com'])]
  events=[]
  plan=self.provider.plan([self.zone],'dns_replace',{'filter_name':'@, *','filter_type':'A','filter_content':'192.0.2.1','new_content':'192.0.2.2'},emit=lambda *args:events.append(args))
  self.assertEqual(len(plan.actions),2);self.assertEqual({a.path for a in plan.actions},{'/zones/z/dns_records/0','/zones/z/dns_records/1'})
  self.assertEqual(events[0][1],'读取中');self.assertEqual(events[-1][1],'已检查')
 def test_empty_dns_gives_actionable_reason_without_writes(self):
  plan=self.provider.plan([self.zone],'dns_replace',{'filter_name':'@,*','filter_type':'A','filter_content':'192.0.2.1','new_content':'192.0.2.2'})
  self.assertFalse(plan.actions);self.assertIn('没有 DNS 记录',plan.notes[0]['detail']);self.assertFalse(self.client.writes)
 def test_empty_filter_rejected_even_when_no_records(self):
  with self.assertRaises(ValueError):self.provider.plan([self.zone],'dns_replace',{'filter_content':''})
 def test_manual_ssl_disables_automatic_before_setting_mode(self):
  plan=self.provider.plan([self.zone],'settings',{'values':{'ssl_automatic_mode':'custom','ssl':'strict'}})
  self.assertEqual([a.path for a in plan.actions],['/zones/z/settings/ssl_automatic_mode','/zones/z/settings/ssl'])
  self.assertEqual([a.body for a in plan.actions],[{'value':'custom'},{'value':'strict'}])
 def test_automatic_ssl_only_changes_automatic_setting(self):
  plan=self.provider.plan([self.zone],'settings',{'values':{'ssl_automatic_mode':'auto'}})
  self.assertEqual(len(plan.actions),1);self.assertEqual(plan.actions[0].body,{'value':'auto'})

if __name__=='__main__':unittest.main()
