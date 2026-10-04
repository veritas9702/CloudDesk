"""Offline UI integration: preview, TDK visibility, asynchronous execution and resume."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials, parse_sites
from test_siteadmin import Unlimited
from test_site_pipeline import PipelineServer

app=QApplication([]);configure_app(app)
ticks=[];heartbeat=QTimer();heartbeat.setInterval(10);heartbeat.timeout.connect(lambda:ticks.append(time.monotonic()))
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temp, patch('cloudtool.credentials.protect',side_effect=lambda value,decrypt=False:value):
    shell=PlatformWindow(Path(temp));shell.open_module('siteadmin');shell.show();app.processEvents()
    page=shell.workspaces['siteadmin'];credentials=Credentials('https://test.invalid','admin','test secret')
    profile=page.vault.add('六步流程测试后台',credentials.encode());page.reload_accounts(profile['id'])
    server=PipelineServer();server.rows=[dict(s.body(),id=i+1,page_count=2) for i,s in enumerate(parse_sites('one.com\ntwo.com'))]
    def delayed(request):
        time.sleep(.015)
        return server(request)
    page.client.http.close();page.client.http=httpx.Client(base_url=credentials.url,transport=httpx.MockTransport(delayed))
    page.client.limiter=Unlimited();errors=[];page.error=lambda error:errors.append(str(error))
    def wait():
        limit=time.monotonic()+15
        while page.busy and time.monotonic()<limit:app.processEvents();time.sleep(.003)
        app.processEvents();assert not page.busy;assert not errors,errors
    page.domains.setPlainText('one.com\ntwo.com');page.with_pipeline.setChecked(True)
    page.preview();assert page.busy;wait()
    assert len(page.plan.actions)==14 and server.generated==2 and not server.submissions
    assert '站点标题1' in page.plan_model.rows[0]['detail']
    for size in ((1160,850),(1440,960)):
        shell.resize(*size);app.processEvents();app.processEvents()
        assert page.domains.viewport().height()>=page.domains.fontMetrics().lineSpacing()*5
        assert page.with_pipeline.geometry().bottom()<page.input_card.height()
        shell.grab().save(str(output/f'pipeline-preview-{size[0]}.png'))
    ticks.append(time.monotonic());heartbeat.start()
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
    assert page.busy and not page.execute_button.isEnabled()
    for name in ('cloudflare','siteadmin','gname','siteadmin'):
        shell.open_module(name);app.processEvents()
    assert shell.workspaces['siteadmin'] is page
    wait()
    heartbeat.stop()
    assert all(r['state']=='成功' for r in page.plan_model.rows),page.plan_model.rows
    assert len(server.submissions)==14
    shell.grab().save(str(output/'pipeline-complete.png'))
    page.preview();wait()
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
    wait();assert len(server.submissions)==14 and server.generated==2
    page.tabs.setCurrentIndex(1);wait();page.sites_table.selectRow(0)
    with patch('cloudtool.siteadmin.ui.QDesktopServices.openUrl',return_value=True) as opened:
        QTest.mouseClick(page.sites_table.viewport(),Qt.MouseButton.LeftButton,pos=page.sites_table.visualRect(page.sites_model.index(0,3)).center())
        assert opened.call_args.args[0].toString()=='https://www.one.com/'
        page.sites_table.clicked.emit(page.sites_model.index(0,1))
        assert opened.call_count==1
    assert page.process_button.isEnabled();page.process_selected();wait()
    assert len(page.plan.actions)==7 and page.with_pipeline.isChecked() and not page.with_template.isChecked()
    shell.close();app.processEvents()
heartbeat.stop()
assert len(ticks)>5
print(f'Pipeline + publish GUI passed; www links, stable workspace switching, heartbeat max gap {max(b-a for a,b in zip(ticks,ticks[1:])):.3f}s')
