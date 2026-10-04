"""Offline site plugin GUI and lifecycle verification."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication,QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials
from test_siteadmin import Unlimited
from test_templates import TemplateServer as Server

app=QApplication([]);configure_app(app)
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as temp, patch('cloudtool.credentials.protect', side_effect=lambda value,decrypt=False: value):
    shell=PlatformWindow(Path(temp));shell.open_module('siteadmin');shell.show();app.processEvents()
    page=shell.workspaces['siteadmin']
    credentials=Credentials('https://test.invalid','admin','test secret')
    profile=page.vault.add('离线测试后台',credentials.encode());page.reload_accounts(profile['id'])
    page.client.http.close();server=Server()
    page.client.http=httpx.Client(base_url=credentials.url,transport=httpx.MockTransport(server))
    page.client.limiter=Unlimited()
    errors=[];page.error=lambda err:errors.append(str(err))
    def wait():
        deadline=time.monotonic()+10
        while page.busy and time.monotonic()<deadline:
            app.processEvents();time.sleep(.005)
        app.processEvents();assert not page.busy;assert not errors,errors
    page.domains.setPlainText('example.com\nexample.net')
    page.preview();assert not shell.unload_module('siteadmin')
    shell.open_module('cloudflare');wait();shell.open_module('siteadmin')
    assert len(page.plan.actions)==2 and page.execute_button.isEnabled()
    for size in ((1160,850),(1440,960)):
        shell.resize(*size);app.processEvents();app.processEvents()
        assert page.domains.viewport().height()>=page.domains.fontMetrics().lineSpacing()*5
        shell.grab().save(str(output/f'siteadmin-{size[0]}.png'))
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
    wait();assert len(server.rows)==2
    assert all(row['state']=='成功' for row in page.plan_model.rows)
    page.preview();wait();assert not page.plan.actions
    assert all(row['state']=='已跳过' for row in page.plan_model.rows)
    def delayed(request):
        time.sleep(.25)
        return server(request)
    page.client.http.close()
    page.client.http=httpx.Client(base_url=credentials.url,transport=httpx.MockTransport(delayed))
    page.read_sites()
    assert page.busy and not page.load_sites_button.isEnabled()
    page.read_sites()
    assert '重复' in page.status.text() or '正在' in page.status.text()
    wait();assert len(page.sites_model.rows)==2 and page.load_sites_button.isEnabled()
    def broken(request):
        raise httpx.ReadTimeout('offline simulated timeout',request=request)
    page.client.http.close()
    page.client.http=httpx.Client(base_url=credentials.url,transport=httpx.MockTransport(broken))
    page.read_sites();wait()
    assert page.load_sites_button.isEnabled() and '失败' in page.assignment_notice.text()
    page.client.http.close()
    page.client.http=httpx.Client(base_url=credentials.url,transport=httpx.MockTransport(server))
    page.read_sites();wait();assert len(page.sites_model.rows)==2
    templates=Path(temp)/'collected';templates.mkdir()
    for name in ('source-a','source-b'):
        folder=templates/name;folder.mkdir();(folder/'index.html').write_text(name)
    existing_ids=[row['id'] for row in server.rows]
    page.with_template.setChecked(True);page.template_root.setText(str(templates))
    assert page.plan is None and '重新预览' in page.config_summary.text()
    page.preview();wait();assert len(page.plan.actions)==10
    shell.resize(1160,850);app.processEvents();app.processEvents()
    assert page.domains.viewport().height()>=page.domains.fontMetrics().lineSpacing()*5
    shell.grab().save(str(output/'template-workflow.png'))
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
    wait();assert all(row['state']=='成功' for row in page.plan_model.rows)
    assert server.steps==['upload-template','sync','scan']*2
    assert [row['id'] for row in server.rows]==existing_ids
    assert sum(r.method=='POST' and r.url.path=='/api/sites' for r in server.calls)==2
    page.tabs.setCurrentIndex(1);wait();assert len(page.sites_model.rows)==2
    assert all(row['binding']=='流程已完成' for row in page.sites_model.rows)
    shell.grab().save(str(output/'site-list.png'))
    page.tabs.setCurrentIndex(2);wait();assert len(page.history_model.rows)>=10
    assert all(row['time'] and row['operation'] for row in page.history_model.rows)
    page.history_table.selectRow(0);assert page.history_details.toPlainText()
    shell.grab().save(str(output/'site-history.png'))
    page.tabs.setCurrentIndex(0)
    assert page.template_root.isVisible() and page.choose_button.isVisible()
    assert page.template_root.geometry().bottom() < page.input_card.height()
    aid=next(iter(page.index_by_id))
    page.consume({aid:('结果未知','等待后台响应超时（ReadTimeout）。先检查后台解压是否完成，再选择恢复。')})
    assert 'ReadTimeout' in page.details.toPlainText()
    assert page.recover_button.isEnabled()
    page.toggle_config();app.processEvents()
    shell.grab().save(str(output/'workflow-error.png'))
    other=page.vault.add('第二后台',Credentials('https://other.invalid','admin','different').encode())
    page.reload_accounts(other['id']);assert not page.domains.toPlainText() and not page.plan_model.rows
    assert page.store.history()==[]
    assert shell.unload_module('siteadmin');shell.open_module('siteadmin')
    shell.close();app.processEvents()
print('Site plugin GUI: login, preview, execution, duplicate skip, account isolation, switching and lifecycle passed')
