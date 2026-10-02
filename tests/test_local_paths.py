import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cloudtool.local_paths import local_data_root
from cloudtool.credentials import Vault

class LocalPathsTests(unittest.TestCase):
    def test_another_machine_starts_without_tokens_or_browser_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {'LOCALAPPDATA': str(Path(tmp)/'machine-a')}):
                first = local_data_root()
                vault = Vault(first)
                vault.add('test', 'FAKE_LOCAL_ONLY_TOKEN', 'test-password-123')
            with patch.dict(os.environ, {'LOCALAPPDATA': str(Path(tmp)/'machine-b')}):
                second = local_data_root()
                self.assertNotEqual(first, second)
                self.assertEqual(Vault(second).profiles, [])

    def test_no_fallback_to_portable_program_folder(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError): local_data_root()

if __name__ == '__main__': unittest.main()
