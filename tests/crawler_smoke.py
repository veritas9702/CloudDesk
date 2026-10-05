"""Real loopback HTTP, Qt lifecycle and compact/minimum layout smoke."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import time
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        time.sleep(.04)
        data = b'<html><head><title>Capture test</title><link rel="stylesheet" href="/style.css"></head><body><h1>Local fixture</h1><img src="/image.png"></body></html>'
        mime = 'text/html'
        if self.path == '/style.css': data, mime = b'body{color:navy}', 'text/css'
        if self.path == '/image.png': data, mime = b'fake image fixture', 'image/png'
        self.send_response(200); self.send_header('Content-Type', mime); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


app = QApplication([]); configure_app(app)
output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=True)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory() as temp, patch('cloudtool.credentials.protect', side_effect=lambda value, decrypt=False:value), patch('cloudtool.crawler.ui.desktop_directory', side_effect=lambda: str(Path(temp) / 'Desktop')):
        shell = PlatformWindow(Path(temp) / 'state')
        shell.open_module('crawler'); shell.show(); app.processEvents()
        page = shell.workspaces['crawler']
        deadline = time.monotonic() + 10
        while page.initializing and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert not page.initializing and not page.initialization_error
        assert Path(page.output.text()) == Path(temp) / 'Desktop' / 'WebsiteTemplates'
        assert Path(page.output.text()).is_dir()
        page.domains.setPlainText(f'http://127.0.0.1:{server.server_port}/')
        page.output.setText(str(Path(temp) / 'templates'))
        for width, height in ((1160, 820), (1440, 960)):
            shell.resize(width, height); app.processEvents(); app.processEvents()
            assert page.domains.viewport().height() >= page.domains.fontMetrics().lineSpacing() * 5
            assert page.output.isVisible() and page.start_button.isVisible()
            shell.grab().save(str(output / f'crawler-{width}.png'))
        prepare = page.controller.prepare
        def slow_prepare(*args):
            time.sleep(.5)
            return prepare(*args)
        page.controller.prepare = slow_prepare
        ticks = []
        heartbeat = QTimer(); heartbeat.setInterval(20)
        heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
        heartbeat.start()
        started = time.monotonic()
        page.start()
        assert time.monotonic() - started < .2, 'start blocked UI'
        assert page.busy and not shell.unload_module('crawler')
        shell.open_module('siteadmin'); shell.open_module('gname'); shell.open_module('cloudflare')
        deadline = time.monotonic() + 20
        while page.busy and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert not page.busy
        heartbeat.stop()
        assert len(ticks) >= 10, 'UI heartbeat stopped during preparation'
        assert page.model.rows[0]['state'] == '已完成', page.model.rows
        assert page.model.rows[0]['ended'] != '—'
        assert page.model.rows[0]['elapsed'] != '未记录'
        assert not page.domains.toPlainText().strip(), 'saved domain remains in input'
        assert '输入剩余 0 个' in page.queue_count.text()
        page.domains.setPlainText(f'http://127.0.0.1:{server.server_port}/')
        assert '输入剩余 0 个' in page.queue_count.text(), 'saved seed counted as pending'
        page.start()
        deadline = time.monotonic() + 10
        while page.busy and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert len(page.model.rows) == 1 and '1' in page.status.text(), 'saved capture duplicated'
        assert not page.domains.toPlainText().strip()
        page.domains.setPlainText(f'http://127.0.0.1:{server.server_port}/two')
        page.start()
        deadline = time.monotonic() + 10
        while len(page.model.rows) < 2 and page.busy and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert page.domains.isEnabled() and page.busy
        page.domains.appendPlainText(f'http://127.0.0.1:{server.server_port}/three')
        page.start()
        deadline = time.monotonic() + 20
        while (page.busy or page.append_future) and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert len(page.model.rows) == 3 and all(r['state'] == '已完成' for r in page.model.rows), page.model.rows
        assert not page.domains.toPlainText().strip()
        shell.open_module('crawler'); page.view.selectRow(0); page.show_detail(); app.processEvents()
        shell.grab().save(str(output / 'crawler-complete.png'))
        page.domains.setPlainText('https://pending.example/\nhttps://failed.example/')
        assert shell.unload_module('crawler')
        shell.open_module('crawler'); app.processEvents()
        deadline = time.monotonic() + 10
        while shell.workspaces['crawler'].initializing and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        assert shell.workspaces['crawler'].model.rows[0]['state'] == '已完成'
        assert shell.workspaces['crawler'].domains.toPlainText() == 'https://pending.example/\nhttps://failed.example/'
        assert Path(shell.workspaces['crawler'].output.text()).resolve() == (Path(temp) / 'templates').resolve()
        deadline = time.monotonic() + 10
        while shell.workspaces['crawler'].delete_future and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert shell.workspaces['crawler'].delete_future is None
        shell.close(); app.processEvents()
finally:
    server.shutdown(); server.server_close()
print('Crawler smoke OK: real HTTP, four modules, persistence, layout, lifecycle')
