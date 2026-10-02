"""Local saved-token display. Receives one decrypted value; no API or persistence."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QApplication
from .ui_components import label, line, button

class TokenViewDialog(QDialog):
    def __init__(self, profile_name, token, parent=None):
        super().__init__(parent)
        self.setWindowTitle('查看已保存的 Token')
        self.resize(660, 250)
        layout = QVBoxLayout(self)
        title = label('当前配置：' + profile_name, 'sectionTitle')
        title.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(title)
        layout.addWidget(label('读取的是本机已加密保存的 Token，不会向 Cloudflare 查询或修改令牌。'))
        self.value = line()
        self.value.setReadOnly(True)
        self.value.setEchoMode(QLineEdit.EchoMode.Password)
        self.value.setText(token)
        layout.addWidget(self.value)
        self.status = label('默认隐藏；点击“显示明文”可查看完整 Token。')
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.reveal = button('显示明文', self.toggle)
        row.addWidget(self.reveal)
        row.addWidget(button('复制 Token', self.copy))
        row.addStretch()
        row.addWidget(button('关闭', self.accept))
        layout.addLayout(row)

    def toggle(self):
        show = self.value.echoMode() == QLineEdit.EchoMode.Password
        self.value.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)
        self.reveal.setText('隐藏明文' if show else '显示明文')

    def copy(self):
        QApplication.clipboard().setText(self.value.text())
        self.status.setText('Token 已复制。')

    def done(self, result):
        self.value.setEchoMode(QLineEdit.EchoMode.Password)
        self.value.clear()
        super().done(result)
