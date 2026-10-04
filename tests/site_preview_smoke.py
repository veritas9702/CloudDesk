"""Preview lifecycle: slow scan cancellation, retry, and enabled confirmation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile,time,sys
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials
from cloudtool.models import Cancelled
from test_templates import TemplateServer
from test_siteadmin import Unlimited

app=QApplication([])
with tempfile.TemporaryDirectory() as tmp, patch('cloudtool.credentials.protect',side_effect=lambda v,decrypt=False:v):
    root=Path(tmp);shell=PlatformWindow(root/'state');shell.open_module('siteadmin');shell.show();app.processEvents()
    page=shell.workspaces['siteadmin'];creds=Credentials('https://test.invalid','admin','test secret')
    profile=page.vault.add('test',creds.encode());page.reload_accounts(profile['id'])
    server=TemplateServer();page.client.http.close()
    page.client.http=httpx.Client(base_url=creds.url,transport=httpx.MockTransport(server));page.client.limiter=Unlimited()
    errors=[];page.error=lambda e:errors.append(str(e))
    templates=root/'templates';folder=templates/'one';folder.mkdir(parents=True)
    (folder/'index.html').write_text('<html><body>Hello</body></html>')
    page.domains.setPlainText('one.test');page.template_root.setText(str(templates));page.with_template.setChecked(True);page.with_pipeline.setChecked(False)
    def wait():
        deadline=time.monotonic()+15
        while page.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
        app.processEvents();assert not page.busy and not errors,errors
    def slow(path,cancel,progress=None,**kw):
        while not cancel.wait(.02):
            if progress:progress('扫描 one · 629 个文件 / 12 MB · index.html')
        raise Cancelled()
    with patch('cloudtool.siteadmin.template_workflow.digest',side_effect=slow):
        page.preview()
        deadline=time.monotonic()+5
        while '629' not in page.status.text() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
        assert '629' in page.status.text()
        assert not page.execute_button.isEnabled() and page.cancel_button.isEnabled()
        page.jobs.cancel();wait()
        assert page.plan is None and not page.execute_button.isEnabled()
        assert all(r['state']=='未生成计划' for r in page.plan_model.rows)
    page.preview();wait()
    assert page.execute_button.isEnabled() and len(page.plan.actions)==5
    page.preview();wait();assert page.execute_button.isEnabled()
    assert server.rows==[] and not server.steps
    shell.close();app.processEvents()
print('Preview cancel/retry/cached preview/confirmation lifecycle passed; no remote writes')
