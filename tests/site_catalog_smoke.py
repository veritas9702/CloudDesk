import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials
from test_site_catalog import CatalogTests
from test_siteadmin import Unlimited

app=QApplication([]);configure_app(app)
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
fixture=CatalogTests();fixture.setUp()
with tempfile.TemporaryDirectory() as temp,patch('cloudtool.credentials.protect',side_effect=lambda value,decrypt=False:value):
    shell=PlatformWindow(Path(temp));shell.open_module('siteadmin');shell.show();app.processEvents()
    page=shell.workspaces['siteadmin'];creds=Credentials('https://test.invalid','admin','test secret')
    profile=page.vault.add('列表测试',creds.encode());page.reload_accounts(profile['id'])
    page.client.http.close();page.client.http=httpx.Client(base_url=creds.url,transport=httpx.MockTransport(fixture.respond));page.client.limiter=Unlimited()
    errors=[];page.error=lambda e:errors.append(str(e))
    def wait():
        deadline=time.monotonic()+10
        while page.busy and time.monotonic()<deadline:app.processEvents();time.sleep(.003)
        app.processEvents();assert not page.busy;assert not errors,errors
    page.read_sites();wait()
    assert page.domains.toPlainText()=='1.com'
    assert [r['publication'] for r in page.sites_model.rows]==['未发布','已发布','待核实']
    page.copy_domains();assert QApplication.clipboard().text()=='1.com\n2.com\n3.com'
    page.domains.setPlainText('manual.com');page.read_sites();wait();assert page.domains.toPlainText()=='manual.com'
    page.read_sites(True);wait();assert page.domains.toPlainText()=='1.com'
    page.auto_fill.setChecked(False);page.domains.clear();page.read_sites();wait();assert not page.domains.toPlainText()
    page.auto_fill.setChecked(True);page.fill_unpublished();assert page.domains.toPlainText()=='1.com'
    for size in ((1160,850),(1440,960)):
        shell.resize(*size);page.tabs.setCurrentIndex(0);app.processEvents();app.processEvents()
        assert page.domains.viewport().height()>=page.domains.fontMetrics().lineSpacing()*5
        shell.grab().save(str(out/f'catalog-input-{size[0]}.png'))
        page.tabs.setCurrentIndex(1);wait();app.processEvents()
        assert page.copy_domains_button.isVisible()
        shell.grab().save(str(out/f'catalog-list-{size[0]}.png'))
    page.sites_model.reset(page.sites_model.rows[:1]);page.copy_domains()
    assert QApplication.clipboard().text()=='1.com\n2.com\n3.com'
    other=page.vault.add('第二后台',Credentials('https://other.invalid','admin','different').encode())
    page.tabs.setCurrentIndex(0);page.reload_accounts(other['id'])
    assert page.all_sites==[] and page.imported_sites=={} and not page.copy_domains_button.isEnabled()
    shell.close();app.processEvents()
fixture.doCleanups()
print('Catalog GUI: verified unpublished fill, manual input protection, complete clipboard export, account isolation and layouts passed')
