"""Exercise actual encrypted-vault startup rather than injecting an active provider."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication, QInputDialog
from cloudtool.credentials import Vault
from cloudtool.ui import Window
from cloudtool.api_client import Client

APP = QApplication.instance() or QApplication([])
PASSWORD = 'test-master-password'

class TokenConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.vault = Vault(self.root)
        self.profile = self.vault.add('Saved token', 'test-token-not-a-real-secret', PASSWORD)
        self.errors = []
        self.error_patch = patch.object(Window, 'error', lambda window, text: self.errors.append(text))
        self.error_patch.start()
        self.window = None
    def tearDown(self):
        if self.window:
            self.window.close(); APP.processEvents()
        self.error_patch.stop(); self.temp.cleanup()
    def startup(self, password='', ok=False):
        with patch.object(QInputDialog,'getText',return_value=(password,ok)):
            self.window=Window(self.root)
        return self.window
    def test_cancelled_startup_retries_existing_token_without_losing_inputs(self):
        window=self.startup()
        self.assertEqual(window.tokens.currentData(),self.profile['id'])
        self.assertIsNone(window.provider)
        self.assertIn('尚未解锁',window.identity.text())
        window.onboarding.domains.setPlainText('example.com')
        with patch.object(QInputDialog,'getText',return_value=(PASSWORD,True)) as prompt:
            window.require()
            window.require()
        self.assertEqual(prompt.call_count,1)
        self.assertEqual(window.client.key,self.profile['id'])
        self.assertIsNotNone(window.provider)
        self.assertEqual(window.onboarding.domains.toPlainText(),'example.com')
    def test_bad_password_can_retry_without_readding(self):
        window=self.startup('wrong-password',True)
        self.assertIsNone(window.provider); self.assertIn('加载失败',window.identity.text())
        with patch.object(QInputDialog,'getText',return_value=(PASSWORD,True)):
            window.reconnect_profile()
        self.assertIsNotNone(window.provider)
        self.assertEqual(len(window.vault.profiles),1)
    def test_cancel_again_has_correct_message(self):
        window=self.startup()
        with patch.object(QInputDialog,'getText',return_value=('',False)):
            with self.assertRaisesRegex(ValueError,'已保存但尚未解锁'): window.require()
        self.assertIsNone(window.client); self.assertIsNone(window.store)
    def test_connection_failure_is_atomic_and_recoverable(self):
        window=self.startup()
        with patch.object(QInputDialog,'getText',return_value=(PASSWORD,True)), patch('cloudtool.ui.Client',side_effect=RuntimeError('test')):
            with self.assertRaises(ValueError): window.require()
        self.assertIsNone(window.client); self.assertIsNone(window.store); self.assertIsNone(window.provider)
        window.require()
        self.assertIsNotNone(window.provider)
    def test_read_accounts_recovers_locked_saved_token(self):
        window=self.startup()
        requests=[]
        def respond(request):
            requests.append(request.url.path)
            return httpx.Response(200,json={'success':True,'result':[{'id':'a'*32,'name':'My account'}]})
        def client(token): return Client(token,transport=httpx.MockTransport(respond))
        with patch.object(QInputDialog,'getText',return_value=(PASSWORD,True)),patch('cloudtool.ui.Client',side_effect=client):
            window.onboarding.load_accounts()
        deadline=time.monotonic()+10
        while window.busy and time.monotonic()<deadline:
            APP.processEvents(); time.sleep(.01)
        APP.processEvents()
        self.assertFalse(window.busy); self.assertFalse(self.errors,self.errors)
        self.assertEqual(window.onboarding.accounts.currentData(),'a'*32)
        self.assertEqual(requests,['/client/v4/accounts'])
        self.assertIn('账户读取完成：1 个',window.status.text())

    def wait_read(self):
        deadline=time.monotonic()+10
        while self.window.busy and time.monotonic()<deadline:
            APP.processEvents();time.sleep(.01)
        APP.processEvents()
        self.assertFalse(self.window.busy)
        self.assertFalse(self.window.cancel_btn.isEnabled())
        self.assertTrue(self.window.account_bar.isEnabled())

    def test_reopen_empty_accounts_fallback_and_repeated_domain_read(self):
        requests=[]
        zone={'id':'z1','name':'example.com','status':'active','account':{'id':'a'*32,'name':'Account'}}
        def respond(request):
            requests.append(request.url.path)
            return httpx.Response(200,json={'success':True,'result':[] if request.url.path.endswith('/accounts') else [zone]})
        def client(token):return Client(token,transport=httpx.MockTransport(respond))
        for _ in range(2):
            with patch('cloudtool.ui.Client',side_effect=client):window=self.startup(PASSWORD,True)
            window.onboarding.load_accounts();self.wait_read()
            self.assertEqual(window.onboarding.accounts.currentData(),'a'*32)
            self.assertIn('账户读取完成：1 个',window.status.text())
            window.tabs.setCurrentWidget(window.onboarding)
            window.onboarding.owner=window.client.key
            window.search.setText('not-visible')
            window.refresh_zones();self.wait_read()
            self.assertEqual(window.tabs.currentIndex(),0)
            self.assertEqual(len(window.zone_model.rows),1)
            self.assertIn('域名读取完成：1 个',window.status.text())
            window.refresh_zones();self.wait_read()
            self.assertFalse(self.errors,self.errors)
            window.close();APP.processEvents();self.window=None

    def test_empty_account_read_and_http_failure_have_terminal_feedback(self):
        failed=[False]
        def respond(request):
            if failed[0]:return httpx.Response(401,json={'success':False,'errors':[{'message':'Invalid token'}]})
            return httpx.Response(200,json={'success':True,'result':[]})
        with patch('cloudtool.ui.Client',side_effect=lambda token:Client(token,transport=httpx.MockTransport(respond))):
            window=self.startup(PASSWORD,True)
        window.onboarding.load_accounts();self.wait_read()
        self.assertIn('账户读取完成：0 个',window.status.text())
        self.assertIn('Account Read',window.onboarding.notice.text())
        failed[0]=True
        window.onboarding.load_accounts();self.wait_read()
        self.assertIn('401',window.status.text());self.assertEqual(len(self.errors),1)
        failed[0]=False
        window.onboarding.load_accounts();self.wait_read()
        self.assertIn('账户读取完成：0 个',window.status.text())

if __name__ == '__main__': unittest.main()
