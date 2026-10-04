"""Reusable anonymous IP detection UI; all network work runs in Worker."""
import threading
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QApplication
from .ui_components import line,button,label
from .qt_jobs import Worker
from .public_ip import PublicIpService
from .models import Cancelled

class PublicIpWidget(QWidget):
    idle=Signal()
    def __init__(self,parent=None,service=None):
        super().__init__(parent)
        self.service=service or PublicIpService()
        self.job=None;self.cancel=threading.Event();self.active=True
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(4)
        row=QHBoxLayout();self.ip=line('检测公网出口 IP');self.ip.setReadOnly(True)
        self.detect_button=button('获取公网 IP',self.detect)
        self.copy_button=button('复制 IP',self.copy_ip)
        row.addWidget(self.ip,1);row.addWidget(self.detect_button);row.addWidget(self.copy_button)
        layout.addLayout(row)
        self.status=label('检测后复制到网页的 IP 白名单。代理或网络变化后请重新检测。')
        layout.addWidget(self.status);self.refresh()
    def set_active(self,active):
        self.active=active;self.refresh()
    def refresh(self):
        self.ip.setEnabled(self.active)
        self.detect_button.setEnabled(self.active and self.job is None)
        self.copy_button.setEnabled(self.active and self.job is None and bool(self.ip.text()))
    def detect(self):
        if self.job is not None or not self.active:return
        self.ip.clear();self.cancel.clear();self.status.setText('正在后台检测公网出口 IP…')
        def run(emit):
            try:return self.service.detect(self.cancel)
            except Cancelled:return None
        self.job=Worker(run,lambda exc:'公网 IP 检测失败，请检查网络后重试。')
        self.job.result.connect(self.ready);self.job.failure.connect(self.status.setText)
        self.job.finished.connect(self.finished);self.refresh();self.job.start()
    def ready(self,address):
        if address is not None and not self.cancel.is_set():
            self.ip.setText(address);self.status.setText('已检测，可复制到网页 IP 白名单；此结果是客户端请求的公网出口。')
    def finished(self):
        self.job.deleteLater();self.job=None;self.refresh();self.idle.emit()
    def copy_ip(self):
        if self.active and self.job is None and self.ip.text():
            QApplication.clipboard().setText(self.ip.text());self.status.setText('已复制公网 IP，请粘贴到对应平台的 API IP 白名单。')
