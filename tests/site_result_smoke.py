"""Offline failure-summary and recovery-choice regression."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QPushButton,QComboBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.siteadmin.models import Credentials
app=QApplication([]);configure_app(app)
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp,patch('cloudtool.credentials.protect',side_effect=lambda value,decrypt=False:value):
    shell=PlatformWindow(Path(tmp));shell.open_module('siteadmin');shell.show()
    page=shell.workspaces['siteadmin']
    credentials=Credentials('https://test.invalid','admin','test secret')
    profile=page.vault.add('Offline',credentials.encode());page.reload_accounts(profile['id'])
    page.usage.reserve(dict(digest='a'*64,path=str(Path(tmp)/'template')),page.client.key,'penthink.com')
    page.usage.set('a'*64,page.client.key,'sync_failed',20)
    page.plan_model.reset([
        dict(target='penthink.com',summary='同步目录',state='失败',detail='目录已同步，ZR JS 注入失败 1 个文件'),
        dict(target='ledslimlightbox.com',summary='打包模板',state='失败',detail='压缩包超过后台 300 MB 限制'),
        dict(target='ledslimlightbox.com',summary='上传模板',state='未执行',detail='打包失败'),
        dict(target='next.example',summary='扫描页面',state='成功',detail='完成')])
    assert len(page.batch_outcomes())==3
    page.show_batch_result();app.processEvents()
    dialog=page.result_dialog
    buttons={b.text():b for b in dialog.findChildren(QPushButton)}
    assert buttons['恢复原模板流程'].isEnabled() and not buttons['另选模板并预览'].isEnabled()
    dialog.findChild(QComboBox).setCurrentIndex(1);app.processEvents()
    assert not buttons['恢复原模板流程'].isEnabled() and buttons['另选模板并预览'].isEnabled()
    dialog.grab().save(str(output/'batch-result.png'))
    dialog.close();shell.close();app.processEvents()
print('Batch summary: domain grouping, known sync failure recovery, pack failure template selection passed')
