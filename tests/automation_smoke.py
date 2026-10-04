"""Offline UI workflow, token reset and responsive navigation regression."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import time
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.cloudflare import Cloudflare
from cloudtool.storage import Store
from test_automation import FakeCloudflare, ACCOUNT

app = QApplication([]); configure_app(app)
output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
    shell = PlatformWindow(Path(temp)); shell.show(); app.processEvents()
    host = shell.workspaces['cloudflare']; panel = host.automation
    host.client = FakeCloudflare(); host.client.close = lambda: None
    host.client.limiter = SimpleNamespace(rate=2)
    host.store = Store(Path(temp), host.client.key); host.provider = Cloudflare(host.client, host.store)
    host.nav.setCurrentRow(13)
    panel.account.setText(ACCOUNT); panel.domains.setPlainText('example.com\nexample.net')
    panel.values.setPlainText('192.0.2.1'); panel.ssl.setCurrentText('strict')
    for size in ((1160, 850), (1440, 1000)):
        shell.resize(*size); app.processEvents(); app.processEvents()
        assert panel.domains.viewport().height() >= panel.domains.fontMetrics().lineSpacing() * 5
        assert panel.form.width() <= panel.width()
    errors = []; host.error = lambda value: errors.append(str(value))
    def wait():
        deadline = time.monotonic()+10
        while host.busy and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.005)
        app.processEvents()
        assert not host.busy, 'worker failed to finish'
        assert not errors, errors
    panel.preview(); wait()
    assert len(panel.model.rows) == 8 and panel.run_button.isEnabled()
    shell.grab().save(str(output/'automation.png'))
    with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
        panel.execute(); wait()
    assert sum(row['state']=='待手动' for row in panel.model.rows) == 2
    assert not panel.run_button.isEnabled()
    panel.save_template(); assert host.store.cached('onboarding_template')['account'] == ACCOUNT
    host.switch_profile(); assert not panel.account.text() and panel.plan is None and not panel.model.rows
    shell.close(); app.processEvents()
print('Automation UI: preview, execute, manual NS, template isolation and five-line layout passed')
