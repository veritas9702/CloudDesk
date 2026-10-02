import unittest
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from cloudtool.browser_token_model import BrowserTokenRequest
from cloudtool.permissions import PRESETS, RULE_PERMISSIONS

class BrowserTokenTests(unittest.TestCase):
    def test_full_permissions_deduplicate_shared_rule_phases(self):
        rows = BrowserTokenRequest('CloudDesk', PRESETS['常用管理'], tuple(RULE_PERMISSIONS)).permissions()
        self.assertEqual(len(rows), 13)
        self.assertEqual(sum(r.names[0] == 'Transform Rules' for r in rows), 1)
        self.assertFalse(any('API Tokens' in r.names for r in rows))

    def test_basic_and_read_only(self):
        self.assertEqual(len(BrowserTokenRequest('CloudDesk', PRESETS['常用管理'], ()).permissions()), 6)
        rows = BrowserTokenRequest('CloudDesk', ('zones',), ()).permissions()
        self.assertEqual(rows[0].access[0], 'Read')

    def test_invalid_input_rejected_before_browser_launch(self):
        for request in (BrowserTokenRequest('', ('zones',), ()),
                        BrowserTokenRequest('test', ('unknown',), ()),
                        BrowserTokenRequest('test', ('zones',), ('unknown',))):
            with self.assertRaises(ValueError): request.url()

    def test_account_scope_does_not_become_zone_scope(self):
        rows = BrowserTokenRequest('test', ('accounts',), ()).permissions()
        self.assertEqual(rows[-1].scope[0], 'Account')

    def test_explicit_chrome_failure_never_starts_edge(self):
        from cloudtool.browser_launcher import open_browser
        with patch('cloudtool.browser_launcher.browser_executable',return_value='chrome.exe') as resolve:
            with patch('cloudtool.browser_launcher.subprocess.Popen',side_effect=OSError('test failure')) as launch:
                with self.assertRaises(OSError): open_browser('chrome','https://dash.cloudflare.com/profile/api-tokens')
                resolve.assert_called_once_with('chrome')
                self.assertEqual(launch.call_args.args[0],['chrome.exe','https://dash.cloudflare.com/profile/api-tokens'])

if __name__ == '__main__': unittest.main()
