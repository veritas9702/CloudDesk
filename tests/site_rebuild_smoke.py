import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication,QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials
from test_site_rebuild import RebuildTests
from test_siteadmin import Unlimited

app=QApplication([]);configure_app(app)
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
fixture=RebuildTests();fixture.setUp()
try:
    with tempfile.TemporaryDirectory() as temp,patch('cloudtool.credentials.protect',side_effect=lambda value,decrypt=False:value):
        shell=PlatformWindow(Path(temp));shell.open_module('siteadmin');shell.show();app.processEvents()
        page=shell.workspaces['siteadmin'];creds=Credentials('https://test.invalid','admin','test secret')
        profile=page.vault.add('重建测试',creds.encode());page.reload_accounts(profile['id'])
        page.client.http.close();page.client.http=httpx.Client(base_url=creds.url,transport=httpx.MockTransport(fixture.server));page.client.limiter=Unlimited()
        page.usage.reserve(fixture.old,page.client.key,'one.com');page.usage.set(fixture.old['digest'],page.client.key,'done',1)
        fixture.server.fail.add((1,'h1'))
        errors=[];page.error=lambda e:errors.append(str(e))
        def wait():
            deadline=time.monotonic()+20
            while page.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.003)
            app.processEvents();assert not page.busy;assert not errors,errors
        page.domains.setPlainText('one.com');page.template_root.setText(str(fixture.sources))
        page.with_pipeline.setChecked(True);page.auto_rebuild.setChecked(True)
        if '--direct' in sys.argv:
            with patch.object(QMessageBox,'question',side_effect=AssertionError('unexpected confirmation')):page.start_direct()
        else:
            page.preview();wait();assert len(page.plan.actions)==7
            with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):page.execute_plan()
        wait();assert fixture.server.deleted==[1]
        assert len(page.plan_model.rows)==14,page.plan_model.rows
        assert all(r['state']=='成功' for r in page.plan_model.rows),page.plan_model.rows
        assert page.pipeline_store.rebuild(page.client.key,'one.com')
        for size in ((1160,850),(1440,960)):
            shell.resize(*size);app.processEvents();app.processEvents()
            assert page.domains.viewport().height()>=page.domains.fontMetrics().lineSpacing()*5
            shell.grab().save(str(out/f'rebuild-{size[0]}.png'))
        shell.close();app.processEvents()
finally:fixture.doCleanups()
print('Rebuild GUI: initial H1 failure, automatic one-time replacement, dynamic progress and completion passed')
