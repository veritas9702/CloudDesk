"""Offline site plugin GUI and lifecycle verification."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication,QMessageBox,QFileDialog,QDialog
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
    def wait():
        deadline=time.monotonic()+10;idle=0
        while time.monotonic()<deadline:
            app.processEvents();time.sleep(.02)
            idle=idle+1 if not page.busy and not page.pending_tab else 0
            if idle>=5:return
        raise AssertionError('GUI job did not settle')
    source=Path(temp)/'templates';source.mkdir()
    for name in ('used','available'):
        folder=source/name;folder.mkdir();(folder/'index.html').write_text(name)
    from cloudtool.siteadmin.templates import digest
    used=dict(path=str(source/'used'),digest=digest(source/'used',page.client.cancel),name='used')
    page.usage.reserve(used,page.client.key,'c.com')
    server.rows=[dict(id=16,code='aa.com',name='aa.com',primary_domain='aa.com',link_protocol='https',page_count=0)]
    page.tabs.setCurrentIndex(1);wait();page.sites_table.selectRow(0)
    with patch.object(QFileDialog,'getExistingDirectory',return_value=str(source/'used')), patch.object(QMessageBox,'warning') as warning:
        page.assign_template();wait()
        assert warning.call_count==1
        assert 'c.com' in str(warning.call_args)
        assert page.tabs.currentIndex()==1 and page.plan is None
        assert not server.steps
        shell.grab().save(str(output/'assignment-rejected.png'))
    with patch.object(QFileDialog,'getExistingDirectory',return_value=str(source/'available')):
        page.assign_template();wait()
    assert page.tabs.currentIndex()==0 and len(page.plan.actions)==5
    assert page.execute_button.isEnabled() and page.domains.toPlainText()=='aa.com'
    assert 'available' in page.config_summary.text()
    server.fail_upload=True
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
    wait();assert server.steps==['upload-template']
    page.tabs.setCurrentIndex(1);wait();page.sites_table.selectRow(0)
    assert page.resume_button.isEnabled() and not page.assign_button.isEnabled()
    with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted):page.resume_button.click()
    wait();assert page.tabs.currentIndex()==0 and len(page.plan.actions)==5
    server.fail_upload=False
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
    wait();assert server.steps==['upload-template','upload-template','sync','scan']
    assert len(server.rows)==1
    assert next(r for r in page.plan_model.rows if r['stage']=='upload')['progress']=='100%' 
    page.tabs.setCurrentIndex(3);wait()
    target_index=next(i for i,r in enumerate(page.template_panel.model.rows) if r['target']=='aa.com')
    page.template_panel.view.selectRow(target_index)
    assert page.template_panel.release_button.isEnabled()
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QMessageBox,'warning') as warning:
        page.template_panel.release_button.click();wait()
        assert warning.call_count==1
    assert any(r['target']=='aa.com' for r in page.usage.rows())
    server.rows=[]
    with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QMessageBox,'information') as notice:
        page.template_panel.release_button.click()
        wait();assert notice.call_count==1
    assert not any(r['target']=='aa.com' for r in page.usage.rows())
    page.read_templates();wait()
    assert any(r['kind']=='released' for r in page.template_panel.model.rows)
    shell.grab().save(str(output/'template-management.png'))
    shell.close();app.processEvents()
print('Manual assignment GUI: occupied template stays in list with reason; available template previews and executes on existing site.')
