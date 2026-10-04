import unittest
import httpx
import test_templates as fixtures
from cloudtool.siteadmin.template_management import TemplateManagement
from cloudtool.siteadmin.template_usage import TemplateUsage


class ManagementTests(unittest.TestCase):
    setUp=fixtures.TemplateTests.setUp
    preview=fixtures.TemplateTests.preview

    def completed(self):
        plan,_=self.preview('a.com')
        self.flow.execute_job(plan)(lambda *args:None)
        return self.usage.rows()[0]

    def test_release_deleted_site_and_reassign_preserves_history(self):
        entry=self.completed();manager=TemplateManagement(self.client,self.usage)
        self.server.rows=[]
        self.assertIn('疑似已删除',manager.list_job(None)[0]['management_state'])
        manager.release_job(entry)(None)
        self.assertEqual(self.usage.rows(),[])
        self.assertEqual(len(self.usage.releases(self.client.key)),1)
        with self.assertRaises(ValueError):manager.release_job(entry)(None)
        plan,_=self.preview('new.com')
        self.assertEqual(plan.actions[0].body['template']['digest'],entry['digest'])
        self.flow.execute_job(plan)(lambda *args:None)
        self.assertEqual(self.usage.rows()[0]['target'],'new.com')
        reopened=TemplateUsage(self.root/'ledger')
        try:self.assertEqual(reopened.releases(self.client.key)[0]['target'],'a.com')
        finally:reopened.close()

    def test_existing_empty_site_cannot_release(self):
        entry=self.completed()
        self.server.rows[0]['page_count']=0
        with self.assertRaises(ValueError):TemplateManagement(self.client,self.usage).release_job(entry)(None)
        self.assertEqual(self.usage.rows(),[entry]);self.assertEqual(self.usage.releases(),[])

    def test_network_failure_does_not_release(self):
        entry=self.completed();manager=TemplateManagement(self.client,self.usage)
        self.client.sites=lambda:(_ for _ in ()).throw(httpx.ConnectError('offline'))
        with self.assertRaises(httpx.ConnectError):manager.release_job(entry)(None)
        self.assertEqual(self.usage.rows(),[entry])

    def test_changed_binding_and_other_account_cannot_release(self):
        entry=self.completed();manager=TemplateManagement(self.client,self.usage)
        foreign=dict(entry,owner='other')
        with self.assertRaises(ValueError):manager.release_job(foreign)(None)
        self.usage.set(entry['digest'],entry['owner'],'uploaded',entry['site_id'])
        self.server.rows=[]
        with self.assertRaises(ValueError):manager.release_job(entry)(None)
        self.assertEqual(self.usage.releases(),[])

    def test_reappearing_site_blocks_preview_and_execution(self):
        entry=self.completed();old=list(self.server.rows);self.server.rows=[]
        manager=TemplateManagement(self.client,self.usage);manager.release_job(entry)(None)
        plan,_=self.preview('new.com')
        self.server.rows=old
        with self.assertRaises(ValueError):self.preview('new.com')
        self.flow.execute_job(plan)(lambda *args:None)
        self.assertEqual(len(self.server.rows),1);self.assertEqual(self.usage.rows(),[])

    def test_id_or_code_still_present_blocks_release(self):
        entry=self.completed();manager=TemplateManagement(self.client,self.usage)
        self.server.rows[0]['id']=999
        with self.assertRaises(ValueError):manager.release_job(entry)(None)
        self.server.rows[0]['id']=entry['site_id'];self.server.rows[0]['code']='renamed.com'
        with self.assertRaises(ValueError):manager.release_job(entry)(None)
