import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cloudtool.extension_setup import prepare_extension,setup_url,EXTENSION_FILES
from cloudtool.browser_launcher import open_browser
from urllib.parse import urlsplit,parse_qs

class ExtensionSetupTests(unittest.TestCase):
 def test_deployment_contains_only_static_files_and_preserves_credentials(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);secret=root/'profiles.json';secret.write_text('untouched')
   target=prepare_extension(root)
   self.assertEqual(secret.read_text(),'untouched')
   self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()},set(EXTENSION_FILES))
   self.assertEqual(prepare_extension(root),target)
 def test_missing_asset_does_not_create_partial_install(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   with self.assertRaises(ValueError):prepare_extension(root/'local',root/'missing')
   self.assertFalse((root/'local').exists())
 def test_browser_only_accepts_own_install_page(self):
  with patch('cloudtool.browser_launcher.browser_executable',return_value='chrome.exe'),patch('cloudtool.browser_launcher.subprocess.Popen') as call:
   open_browser('chrome','chrome://extensions/')
   self.assertEqual(call.call_args.args[0],['chrome.exe','chrome://extensions/'])
   for url in ('edge://extensions/','chrome://settings/','https://dash.cloudflare.com.evil.test','file:///c:/x'):
    with self.assertRaises(ValueError):open_browser('chrome',url)
 def test_advanced_plan_uses_marker_not_invented_cf_permission_keys(self):
  query=parse_qs(urlsplit(setup_url('test',True)).query)
  self.assertEqual(query['clouddesk_setup'],['full'])
  self.assertNotIn('WAF',query['permissionGroupKeys'][0])
