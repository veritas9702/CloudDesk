"""Exercise 200-domain preparation with a live Qt heartbeat, without network."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from cloudtool.crawler.ui import CapturePage

app = QApplication([])
with tempfile.TemporaryDirectory() as temp, patch('cloudtool.crawler.ui.desktop_directory', return_value=str(Path(temp)/'Desktop')):
    page = CapturePage(Path(temp)/'state')
    deadline = time.monotonic() + 10
    while page.initializing and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.005)
    assert not page.initializing and not page.initialization_error
    page.controller.run_job = lambda *args, **kwargs: lambda report: page.controller.snapshot()
    page.domains.setPlainText('\n'.join(f'https://site{i}.test/' for i in range(200)))
    ticks = []
    timer = QTimer(); timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    start = time.monotonic(); page.start(); returned = time.monotonic()-start
    while page.busy and time.monotonic()-start < 30:
        app.processEvents(); time.sleep(.005)
    timer.stop()
    assert not page.busy and len(page.model.rows) == 200
    gaps = [b-a for a,b in zip(ticks,ticks[1:])]
    assert returned < .2 and len(ticks) > 5
    assert max(gaps,default=0) < .5
    print(json.dumps({'domains':200, 'start_return_ms':round(returned*1000,1), 'preparation_seconds':round(time.monotonic()-start,2), 'max_heartbeat_gap_ms':round(max(gaps,default=0)*1000,1)}))
    page.close(); app.processEvents()
