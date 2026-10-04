"""Concurrent provider execution, cancellation isolation and plugin lifecycle."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.providers import load_plugin
from cloudtool.providers import PROVIDERS
from cloudtool.api_client import Client
from cloudtool.cloudflare import Cloudflare
from cloudtool.gname.client import GnameClient
from cloudtool.gname.controller import GnameController
from cloudtool.models import Action, Plan, Cancelled
from cloudtool.storage import Store
from cloudtool.execution import execute


class Unlimited:
    def acquire(self, event):
        if event.is_set(): raise Cancelled()
    def defer(self, delay): pass


def main():
    app = QApplication([]); configure_app(app)
    output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=True)
    report = {}
    with tempfile.TemporaryDirectory() as temp, ExitStack() as cleanup:
        root = Path(temp)
        shell = PlatformWindow(root); shell.show(); app.processEvents()
        cleanup.callback(shell.close)
        cf, gn = shell.workspaces['cloudflare'], shell.workspaces['gname']
        assert cf.vault.root == root and gn.vault.root == root / 'gname'
        for size in ((1160, 850), (1440, 1000)):
            shell.resize(*size); app.processEvents()
            for mode in range(4):
                shell.pages.setCurrentWidget(gn); gn.mode.setCurrentIndex(mode); app.processEvents()
                assert gn.scope.viewport().height() >= 5 * gn.scope.fontMetrics().lineSpacing()
                assert gn.input_panel.width() <= gn.width()
        shell.grab().save(str(output/'gname.png'))
        shell.pages.setCurrentWidget(cf); app.processEvents()
        shell.grab().save(str(output/'cloudflare-tabs.png'))
        calls = {'cf':0, 'gn':0}
        def cf_request(request):
            calls['cf'] += 1; time.sleep(.012)
            return httpx.Response(200,json={'success':True,'result':{}})
        def gn_request(request):
            calls['gn'] += 1; time.sleep(.012)
            return httpx.Response(200,json={'code':1,'data':1})
        cf.client = Client('FAKE_CF', transport=httpx.MockTransport(cf_request), global_limiter=Unlimited())
        cf.client.limiter = Unlimited()
        cf.store = Store(root, cf.client.key)
        cf.provider = Cloudflare(cf.client, cf.store)
        gn.client = GnameClient('FAKE_ID', 'FAKE_KEY', transport=httpx.MockTransport(gn_request))
        gn.client.limiter = Unlimited()
        gn.store = Store(root/'gname', gn.client.key)
        gn.controller = GnameController(gn.client, gn.store)
        cp = Plan(cf.client.key,[Action(f'cf{i}.com','POST','/zones/z/dns_records',{}) for i in range(180)])
        gp = Plan(gn.client.key,[Action(f'gn{i}.com','POST','/api/resolution/add',{'ym':f'gn{i}.com'}) for i in range(180)])
        cf.plan_ready(cp); gn.show_plan(gp)
        beats = []; switched = []; simultaneous = []
        ticker = QTimer()
        def tick():
            beats.append(time.monotonic())
            simultaneous.append(cf.busy and gn.busy)
            shell.pages.setCurrentIndex(len(beats) % 2)
            switched.append(shell.pages.currentIndex())
            if calls['gn'] >= 4 and not gn.client.cancel.is_set(): gn.cancel_job()
        ticker.timeout.connect(tick); ticker.start(10)
        with patch('cloudtool.gname.client.GNAME_LIMITER', Unlimited()):
            cf.start_job(lambda emit: execute(cf.client, cf.store, cp, 2, emit), lambda _:None, 'test')
            gn.start_job(gn.controller.execute_job(gp, 2), lambda _:None)
            with patch.object(QMessageBox, 'information'):
                assert shell.unload_module('gname') is False
            deadline = time.monotonic() + 15
            while (cf.busy or gn.busy) and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.002)
        ticker.stop(); app.processEvents()
        assert not cf.busy and not gn.busy
        assert any(simultaneous) and len(set(switched)) == 2
        assert calls['cf'] == 180 and 0 < calls['gn'] < 180, calls
        assert not cf.client.cancel.is_set()
        assert all(r['target'].startswith('cf') for r in cf.store.history())
        assert all(r['target'].startswith('gn') for r in gn.store.history())
        report.update(calls=calls, simultaneous=True, page_switches=len(beats),
                      max_heartbeat_ms=round(max(b-a for a,b in zip(beats,beats[1:]))*1000,2))
        assert report['max_heartbeat_ms'] < 500
        assert shell.unload_module('gname')
        shell.open_module('gname')
        assert shell.workspaces['cloudflare'] is cf
        plugin = root/'plugin'; plugin.mkdir()
        (plugin/'module.json').write_text(json.dumps(dict(id='demo',title='Demo',api_version=1,entry='entry.py')))
        (plugin/'entry.py').write_text('from PySide6.QtWidgets import QWidget\ndef create_workspace(root):\n w=QWidget(); w.busy=False; return w\n')
        key = load_plugin(plugin); shell.refresh_modules(); shell.open_module(key)
        assert shell.pages.count() == 3
        shell.remove_plugin(key)
        assert key not in PROVIDERS and shell.pages.count() == 2
        report['hotplug'] = True
        cleanup.pop_all()
        shell.close(); app.processEvents()
    (output/'report.json').write_text(json.dumps(report,indent=2),'utf-8')
    print(json.dumps(report))


if __name__ == '__main__': main()
