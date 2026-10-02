"""Two-step local helper setup using the user's normal installed browser."""
from pathlib import Path
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QCheckBox,QApplication
from .ui_components import label,line,button,card,AlignedForm,combo
from .local_paths import local_data_root
from .public_ip_ui import PublicIpWidget
from .browser_launcher import open_browser
from .extension_setup import setup_url,prepare_extension


def show_browser_token(parent):
    ancestor=parent
    while ancestor is not None and not hasattr(ancestor,'root'): ancestor=ancestor.parentWidget()
    BrowserTokenDialog(ancestor.root if ancestor else local_data_root(),parent).exec()

class BrowserTokenDialog(QDialog):
    def __init__(self,root,parent=None,*,launcher=open_browser,prepare=prepare_extension,ip_service=None):
        super().__init__(parent)
        self.root,self.launcher,self.prepare=Path(root),launcher,prepare
        self.setWindowTitle('自动填写 Token 权限')
        self.resize(760,680)
        self.closing=False
        layout=QVBoxLayout(self)
        layout.addWidget(label('安装一次助手，以后自动填写权限','heading'))
        form=AlignedForm();self.browser=combo(['Google Chrome','Microsoft Edge'])
        form.addRow('使用浏览器',self.browser);layout.addLayout(form)
        panel,fields=card();layout.addWidget(panel)
        fields.addWidget(label('1  准备助手 · 每台电脑首次一次','sectionTitle'))
        self.install=button('准备助手并打开安装页',self.open_install,True);fields.addWidget(self.install)
        fields.addWidget(label('开启开发者模式 → 点“加载已解压的扩展程序 / Load unpacked” → 粘贴目录并选择。'))
        self.path=line();self.path.setReadOnly(True);self.path.setPlaceholderText('点击上方按钮后自动准备并复制目录')
        fields.addWidget(self.path)
        self.installed=QCheckBox('已在所选浏览器加载并启用 CloudDesk 权限助手');fields.addWidget(self.installed)
        panel,fields=card();layout.addWidget(panel)
        fields.addWidget(label('2  打开创建页 · 自动填写权限','sectionTitle'))
        form=AlignedForm();self.name=line();self.name.setText('CloudDesk');form.addRow('令牌名称',self.name)
        self.permission_mode=combo(['全部功能（含高级规则）','基础管理'])
        form.addRow('权限范围',self.permission_mode)
        self.ip_widget=PublicIpWidget(self,ip_service);self.ip_widget.idle.connect(self.ip_idle)
        form.addRow('公网 IP',self.ip_widget);fields.addLayout(form)
        self.open_button=button('打开网页并填写权限',self.open_form,True);fields.addWidget(self.open_button)
        fields.addWidget(label('等待网页提示“权限已填写并校验”，再检查账号 / 域名范围、填写 IP 白名单并确认创建。'))
        layout.addWidget(label('创建后复制 Token 回工具添加。本机加密保存，复制程序不会携带 Token。'))
        self.status=label('首次仍需在浏览器选择助手目录；工具不会自动确认安装或创建令牌。','notice');layout.addWidget(self.status)
        row=QHBoxLayout();row.addStretch();row.addWidget(button('关闭',self.reject));layout.addLayout(row)
        self.browser.currentIndexChanged.connect(self.refresh)
        self.installed.toggled.connect(self.open_button.setEnabled)
        self.open_button.setEnabled(False)

    def channel(self): return ('chrome','msedge')[self.browser.currentIndex()]

    def refresh(self):
        self.installed.setChecked(False)
        self.status.setText('切换了浏览器，请确认此浏览器已启用助手。')

    def open_install(self):
        try:
            target=self.prepare(self.root)
            self.path.setText(str(target));QApplication.clipboard().setText(str(target))
            self.launcher(self.channel(),'chrome://extensions/' if self.channel()=='chrome' else 'edge://extensions/')
            self.status.setText('目录已复制。请点击 Load unpacked，粘贴目录并选择；已有助手时点击扩展卡片的重新加载按钮。')
        except (ValueError,OSError) as exc: self.status.setText('未完成准备：'+str(exc))

    def open_form(self):
        if not self.installed.isChecked(): return
        try:
            self.launcher(self.channel(),setup_url(self.name.text(),self.permission_mode.currentIndex()==0))
            self.status.setText('已打开网页。仅网页的成功提示代表填写完成；没有提示时请检查助手是否启用。')
        except (ValueError,OSError) as exc: self.status.setText(str(exc))

    def ip_idle(self):
        if self.closing:super().reject()

    def reject(self):
        if self.ip_widget.job is not None:
            self.closing=True;self.ip_widget.cancel.set()
            self.ip_widget.status.setText('正在结束检测…')
        else:super().reject()

    def closeEvent(self,event):
        if self.ip_widget.job is not None:
            self.reject();event.ignore()
        else:super().closeEvent(event)
