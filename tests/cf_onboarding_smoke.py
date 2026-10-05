"""Offline UI regression for account selection and manual NS onboarding."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.cloudflare import Cloudflare
from cloudtool.storage import Store
from tests.test_cf_onboarding import Client
app=QApplication([]); configure_app(app)
out=Path(sys.argv[1]); out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
    shell=PlatformWindow(Path(temp)); shell.show(); app.processEvents()
    host=shell.workspaces['cloudflare']; panel=host.onboarding
    host.client=Client(); host.client.close=lambda:None; host.client.limiter=SimpleNamespace(rate=2)
    host.store=Store(Path(temp),host.client.key); host.provider=Cloudflare(host.client,host.store)
    errors=[]; host.error=lambda text:errors.append(str(text))
    def wait():
        deadline=time.monotonic()+15
        while host.busy and time.monotonic()<deadline:
            app.processEvents(); time.sleep(.01)
        app.processEvents()
        assert not host.busy and not errors,errors
    host.nav.setCurrentRow(1); wait()
    assert panel.accounts.currentData()=='a'*32
    panel.domains.setPlainText('example.com\nexample.net'); panel.preview(); wait()
    assert panel.execute_button.isEnabled()
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes): panel.execute()
    wait(); assert len(panel.model.rows)==2
    panel.copy_ns(); assert 'example.com|a.ns.cloudflare.com,b.ns.cloudflare.com' in app.clipboard().text()
    host.client.zones['example.com']['status']='active'
    panel.refresh(); wait()
    panel.copy_ns()
    expected='example.net|a.ns.cloudflare.com,b.ns.cloudflare.com'
    assert app.clipboard().text()==expected
    with patch.object(host,'save_text') as saved:
        panel.export_ns();assert saved.call_args.args[0]==expected
    with patch.object(host.client,'get',wraps=host.client.get) as reads:
        panel.refresh();wait()
        assert [call.args[0] for call in reads.call_args_list]==['/zones/example.net']
    active_index=next(i for i,r in enumerate(panel.model.rows) if r['name']=='example.com')
    panel.results.selectRow(active_index)
    with patch.object(host.client,'get',wraps=host.client.get) as reads:
        panel.refresh('selected');wait()
        assert [call.args[0] for call in reads.call_args_list]==['/zones/example.com']
    with patch.object(host.client,'get',wraps=host.client.get) as reads:
        panel.refresh('all');wait()
        assert len(reads.call_args_list)==2
    host.client.zones['example.net']['status']='active'
    panel.refresh();wait()
    panel.copy_ns();assert errors and '没有待激活' in errors.pop()
    assert app.clipboard().text()==expected

    for size in [(1160,850),(1440,1000)]:
        shell.resize(*size); app.processEvents(); shell.grab().save(str(out/f'onboarding-{size[0]}.png'))
    panel.configure(); assert host.nav.currentRow()==2 and 'example.com' in host.scope.toPlainText()
    host.switch_profile(); assert not panel.model.rows and not panel.accounts.count()
    shell.close(); app.processEvents()
print('CF onboarding UI passed: accounts, preview, add, scan, NS export, refresh, batch handoff and token reset')
