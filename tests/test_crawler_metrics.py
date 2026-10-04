import tempfile
import unittest
from pathlib import Path
from cloudtool.crawler.metrics import Meter, presentation, duration
from cloudtool.crawler.controller import CaptureController


class MetricsTests(unittest.TestCase):
    def test_rate_drops_to_zero_and_resume_excludes_pause(self):
        now = [0.0]
        meter = Meter({}, clock=lambda:now[0])
        meter.add(2048); now[0] = 2
        first = meter.snapshot()
        self.assertEqual(first['speed_kbps'], 1)
        now[0] = 5; meter.snapshot()
        now[0] = 8
        self.assertEqual(meter.snapshot()['speed_kbps'], 0)
        saved = meter.snapshot()
        now[0] = 100
        resumed = Meter(saved, clock=lambda:now[0])
        now[0] = 102
        self.assertEqual(resumed.snapshot()['elapsed_seconds'], 10)
        self.assertEqual(resumed.snapshot()['transferred_bytes'], 2048)

    def test_legacy_timing_is_not_invented(self):
        row = presentation({'state':'已完成'})
        self.assertEqual(row['elapsed'], '未记录')
        self.assertEqual(row['speed'], '未记录')
        self.assertEqual(row['ended'], '—')
        self.assertEqual(duration(3661), '01:01:01')

    def test_default_desktop_and_remembered_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = CaptureController(root / 'state')
            default = controller.output_directory(root / 'RedirectedDesktop')
            self.assertEqual(Path(default), root / 'RedirectedDesktop' / 'WebsiteTemplates')
            self.assertTrue(Path(default).is_dir())
            selected = root / 'chosen'
            controller.remember_output(selected)
            restarted = CaptureController(root / 'state')
            self.assertEqual(Path(restarted.output_directory(root / 'RedirectedDesktop')).resolve(), selected.resolve())

    def test_old_default_switches_to_english_without_moving_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = CaptureController(root / 'state')
            old = root / 'Desktop' / '采集模板'
            controller.remember_output(old)
            (old / 'keep.txt').write_text('keep')
            selected = Path(controller.output_directory(root / 'Desktop'))
            self.assertEqual(selected.name, 'WebsiteTemplates')
            self.assertTrue((old / 'keep.txt').is_file())
