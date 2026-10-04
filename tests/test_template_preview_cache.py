import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from cloudtool.models import Cancelled
from cloudtool.siteadmin.templates import digest, files, pack
from cloudtool.siteadmin.template_usage import TemplateUsage

class PreviewCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'template';self.root.mkdir()
        (self.root/'index.html').write_text('<html><body>hello</body></html>')
        self.cache=TemplateUsage(Path(self.temp.name)/'state');self.addCleanup(self.cache.close)
        self.cancel=threading.Event()

    def test_second_preview_avoids_content_reads_and_changed_file_invalidates(self):
        first=digest(self.root,self.cancel,cache=self.cache)
        with patch.object(Path,'open',side_effect=AssertionError('unchanged files must not be reread')):
            self.assertEqual(digest(self.root,self.cancel,cache=self.cache),first)
        (self.root/'index.html').write_text('<html><body>changed</body></html>')
        self.assertNotEqual(digest(self.root,self.cancel,cache=self.cache),first)

    def test_added_removed_files_invalidate_and_pack_still_checks_contents(self):
        first=digest(self.root,self.cancel,cache=self.cache)
        asset=self.root/'a.txt';asset.write_text('asset')
        self.assertNotEqual(digest(self.root,self.cancel,cache=self.cache),first)
        asset.unlink();self.assertEqual(digest(self.root,self.cancel,cache=self.cache),first)
        (self.root/'index.html').write_text('changed')
        with self.assertRaisesRegex(ValueError,'预览后变化'):
            pack(dict(path=str(self.root),digest=first),Path(self.temp.name)/'test.zip',self.cancel)

    def test_flat_directory_scan_reports_and_can_cancel_before_reading_all(self):
        for n in range(100): (self.root/f'{n}.txt').write_text('x')
        reports=[]
        def progress(text):reports.append(text);self.cancel.set()
        with self.assertRaises(Cancelled):files(self.root,self.cancel,progress)
        self.assertEqual(len(reports),1)

    def test_binary_html_never_enters_preview_cache(self):
        (self.root/'bad.html').write_bytes(b'GIF87a'+bytes(40))
        with self.assertRaisesRegex(ValueError,'实际为 image/gif'):
            digest(self.root,self.cancel,cache=self.cache)
        self.assertEqual(self.cache.db.execute('SELECT COUNT(*) FROM preview_digest').fetchone()[0],0)
