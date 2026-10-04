import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cloudtool.local_paths import local_data_root
from cloudtool.crawler.controller import CaptureController
from cloudtool.crawler.models import Settings


class PortabilityTests(unittest.TestCase):
    def test_new_windows_user_data_starts_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.dict(os.environ, LOCALAPPDATA=str(root/'computer-a')):
                old_root = local_data_root()
                old = CaptureController(old_root/'crawler')
                old.create('https://example.test/',str(root/'templates'),Settings())
                old.remember_output(root/'custom-output')
                old.pending_input('https://pending.test/')
                self.assertEqual(CaptureController(old_root/'crawler').pending_input(), 'https://pending.test/')
                self.assertEqual(len(old.snapshot()),1)
            with patch.dict(os.environ, LOCALAPPDATA=str(root/'computer-b')):
                new = CaptureController(local_data_root()/'crawler')
                self.assertEqual(new.snapshot(),[])
                self.assertEqual(new.pending_input(), '')
                self.assertEqual(Path(new.output_directory(root/'desktop-b')).name,'WebsiteTemplates')
                self.assertNotEqual(local_data_root(),old_root)

    def test_pending_draft_migrates_and_preserves_explicit_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = CaptureController(root/'data')
            controller.create('https://pending.test/', str(root/'templates'), Settings())
            self.assertEqual(controller.pending_input(), 'https://pending.test/')
            controller.pending_input('https://pending.test/\nnot-yet-finished')
            restored = CaptureController(root/'data')
            self.assertEqual(restored.pending_input(), 'https://pending.test/\nnot-yet-finished')
            restored.pending_input('')
            self.assertEqual(CaptureController(root/'data').pending_input(), '')
