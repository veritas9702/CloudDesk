"""Stress GUI delivery independently of network/server speed; use temporary data only."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget
from cloudtool.crawler.controller import CaptureController
from cloudtool.crawler.ui import CapturePage
from cloudtool.qt_jobs import Worker

app = QApplication([])
gui_thread = threading.get_ident()
original_recover = CaptureController.recover
def slow_recovery(controller):
    assert threading.get_ident() != gui_thread, 'recovery ran on the GUI thread'
    time.sleep(.6)  # Simulate busy disk/database, not a fast empty-history case.
    original_recover(controller)

with tempfile.TemporaryDirectory() as temp, patch.object(CaptureController, 'recover', slow_recovery), patch('cloudtool.crawler.ui.desktop_directory', return_value=str(Path(temp)/'Desktop')):
    ticks = []
    heartbeat = QTimer(); heartbeat.setInterval(20)
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start()
    started = time.monotonic()
    page = CapturePage(Path(temp)/'state')
    construction = time.monotonic()-started
    stack = QStackedWidget(); stack.addWidget(page); stack.addWidget(QWidget())
    stack.resize(1200, 850); stack.show()
    switches = []
    switcher = QTimer(); switcher.setInterval(40)
    def switch():
        start = time.monotonic()
        stack.setCurrentIndex(1-stack.currentIndex())
        switches.append(time.monotonic()-start)
    switcher.timeout.connect(switch); switcher.start()
    deadline = time.monotonic()+10
    while page.initializing and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.002)
    assert not page.initializing and not page.initialization_error
    assert construction < .5 and len(ticks)>10, (construction, len(ticks))
    rows = [dict(id=str(i),seed=f'https://s{i}.test/',state='采集中' if i<500 else '已完成',
                 output='',settings='{}',detail='',revision=0,template_bytes=0,
                 elapsed_seconds=1,transferred_bytes=0,created='',published=False)
            for i in range(10000)]
    page.refresh(rows)
    worker = Worker(lambda report: None, str)
    page.worker = worker
    flush_times = []
    # Metrics only: 500 active rows, 10,000 historical rows, 10 update bursts.
    # The old implementation rescanned all rows once per dataChanged signal.
    with patch.object(page, 'apply_filter', wraps=page.apply_filter) as filters, patch.object(page, 'refresh', wraps=page.refresh) as resets:
        for burst in range(10):
            for i in range(500):
                worker.report(str(i),'采集中',json.dumps(dict(detail='下载中',metrics=dict(template_bytes=burst*1024))))
            start = time.monotonic(); page.flush(); flush_times.append(time.monotonic()-start)
            until = time.monotonic()+.04
            while time.monotonic()<until:
                app.processEvents(); time.sleep(.002)
        assert filters.call_count == 0 and resets.call_count == 0
    # Terminal events must still reorder and refresh counts correctly.
    worker.report('0','采集失败',json.dumps(dict(detail='fixture error',metrics={})))
    page.flush()
    assert page.model.rows[page.row_indexes['0']]['state']=='采集失败'
    assert '失败 1' in page.task_counts.text()
    page.worker = None
    heartbeat.stop(); switcher.stop()
    gaps = [b-a for a,b in zip(ticks,ticks[1:])]
    assert max(flush_times)<.3 and max(gaps)<.5, (max(flush_times),max(gaps))
    assert len(switches)>10
    assert page.close()
    stack.close()
    print(json.dumps(dict(history_rows=10000,active_rows=500,bursts=10,
                         construction_ms=round(construction*1000,1),
                         max_flush_ms=round(max(flush_times)*1000,1),
                         max_heartbeat_gap_ms=round(max(gaps)*1000,1),
                         switches=len(switches),max_switch_ms=round(max(switches)*1000,1))))
