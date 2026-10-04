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
    panel.refresh(); wait()
    for size in [(1160,850),(1440,1000)]:
        shell.resize(*size); app.processEvents(); shell.grab().save(str(out/f'onboarding-{size[0]}.png'))
    panel.configure(); assert host.nav.currentRow()==2 and 'example.com' in host.scope.toPlainText()
    host.switch_profile(); assert not panel.model.rows and not panel.accounts.count()
    shell.close(); app.processEvents()
print('CF onboarding UI passed: accounts, preview, add, scan, NS export, refresh, batch handoff and token reset')
