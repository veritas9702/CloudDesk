"""One-click UI: no preview gate, streamed actions, module switching and resume."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials,parse_sites
from test_site_pipeline import PipelineServer
from test_siteadmin import Unlimited

app=QApplication([]);configure_app(app)
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temp,patch('cloudtool.credentials.protect',side_effect=lambda value,decrypt=False:value):
    shell=PlatformWindow(Path(temp));shell.open_module('siteadmin');shell.show();app.processEvents()
    page=shell.workspaces['siteadmin'];credentials=Credentials('https://test.invalid','admin','test secret')
    profile=page.vault.add('一键测试',credentials.encode());page.reload_accounts(profile['id'])
    server=PipelineServer();server.rows=[dict(s.body(),id=i+1,page_count=2) for i,s in enumerate(parse_sites('one.com\ntwo.com'))]
    def request(req):time.sleep(.015);return server(req)
    page.client.http.close();page.client.http=httpx.Client(base_url=credentials.url,transport=httpx.MockTransport(request));page.client.limiter=Unlimited()
    errors=[];page.error=lambda message:errors.append(str(message))
    page.domains.setPlainText('one.com\ntwo.com');page.with_pipeline.setChecked(True)
    ticks=[];timer=QTimer();timer.setInterval(15)
    def tick():
        ticks.append(time.monotonic())
        shell.open_module('siteadmin' if len(ticks)%2 else 'cloudflare')
    timer.timeout.connect(tick)
    def wait():
        deadline=time.monotonic()+20
        while page.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.003)
        app.processEvents();assert not page.busy and not errors,errors
    with patch.object(QMessageBox,'question',side_effect=AssertionError('one click must not require a preview confirmation')):
        timer.start();page.direct_button.click();assert page.busy and page.plan is None;wait();timer.stop()
    shell.open_module('siteadmin');app.processEvents()
    assert len(page.plan_model.rows)==14,page.plan_model.rows
    assert all(r['state']=='成功' for r in page.plan_model.rows),page.plan_model.rows
    assert len(server.submissions)==14 and not page.execute_button.isEnabled()
    page.start_direct();wait();assert len(server.submissions)==14
    assert page.direct_button.isEnabled()
    for size in ((1160,850),(1440,960)):
        shell.resize(*size);app.processEvents();app.processEvents()
        assert page.toolbar.geometry().right()<=page.width()
        shell.grab().save(str(out/f'direct-{size[0]}.png'))
    assert len(ticks)>5
    print(f'One-click UI passed: streamed 14 steps, no confirmation, resume skip, switching max heartbeat {max(b-a for a,b in zip(ticks,ticks[1:])):.3f}s')
    shell.close();app.processEvents()
