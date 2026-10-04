"""Compact platform navigation and independent workspace lifecycle."""
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QStackedWidget, QFrame, QPushButton, QButtonGroup, QMessageBox)
from .providers import PROVIDERS, register
from .ui_components import label

SHELL_STYLE = """
QFrame#platformHeader { background: #ffffff; border-bottom: 1px solid #dde4ee; }
QLabel#appMark { background: #ed8b2d; color: white; border-radius: 8px; font-size: 14px; font-weight: 700; }
QLabel#appTitle { color: #172940; font-size: 19px; font-weight: 700; }
QFrame#platformSwitch { background: #eef2f7; border-radius: 9px; }
QPushButton[platformSwitch="true"] { background: transparent; border: none; border-radius: 7px; color: #6c7c91; min-height: 0; padding: 7px 22px; font-weight: 600; }
QPushButton[platformSwitch="true"]:hover { background: #e4eaf2; color: #243a55; }
QPushButton[platformSwitch="true"]:checked { background: #ffffff; color: #c5681d; border: 1px solid #dce3eb; }
"""


def builtin_modules():
    from .ui import Window
    from .gname.ui import GnamePage
    PROVIDERS['cloudflare']['factory'] = lambda root: Window(root, embedded=True)
    if 'gname' not in PROVIDERS:
        register('gname', 'GNAME', factory=GnamePage)
    if 'siteadmin' not in PROVIDERS:
        from .siteadmin.ui import SitePage
        register('siteadmin', '站点后台', factory=SitePage)
    if 'crawler' not in PROVIDERS:
        from .crawler.ui import CapturePage
        register('crawler', '网站采集', factory=CapturePage)


class PlatformWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        builtin_modules()
        self.root = Path(root)
        self.workspaces = {}
        self.platform_buttons = {}
        self.setWindowTitle('CloudDesk · 多平台工具箱')
        self.resize(1440, 960)
        self.setMinimumSize(1160, 820)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName('platformHeader')
        header.setFixedHeight(62)
        header.setStyleSheet(SHELL_STYLE)
        row = QHBoxLayout(header)
        row.setContentsMargins(20, 10, 24, 10)
        row.setSpacing(0)
        brand = QWidget()
        brand.setFixedWidth(224)
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)
        mark = label('CD', 'appMark')
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(32, 32)
        brand_row.addWidget(mark)
        brand_row.addWidget(label('CloudDesk', 'appTitle'))
        brand_row.addStretch()
        row.addWidget(brand)
        switch = QFrame()
        switch.setObjectName('platformSwitch')
        self.switch_layout = QHBoxLayout(switch)
        self.switch_layout.setContentsMargins(4, 4, 4, 4)
        self.switch_layout.setSpacing(3)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        row.addWidget(switch)
        row.addStretch()
        status = label('本地加密  ·  独立账户', 'muted')
        status.setWordWrap(False)
        row.addWidget(status)
        layout.addWidget(header)
        self.pages = QStackedWidget()
        self.pages.currentChanged.connect(self.sync_selection)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self.refresh_modules()
        self.open_module('cloudflare')
        self.open_module('gname')
        self.open_module('cloudflare')

    def refresh_modules(self):
        for key, widget in list(self.platform_buttons.items()):
            if key not in PROVIDERS:
                self.button_group.removeButton(widget)
                self.switch_layout.removeWidget(widget)
                widget.deleteLater()
                del self.platform_buttons[key]
        for key, info in PROVIDERS.items():
            if info.get('factory') and key not in self.platform_buttons:
                widget = QPushButton(info['title'])
                widget.setProperty('platformSwitch', True)
                widget.setCheckable(True)
                widget.setCursor(Qt.CursorShape.PointingHandCursor)
                widget.setToolTip('切换平台，后台任务继续运行')
                widget.clicked.connect(lambda checked=False, key=key: self.open_module(key))
                self.button_group.addButton(widget)
                self.switch_layout.addWidget(widget)
                self.platform_buttons[key] = widget
        self.sync_selection()

    def sync_selection(self, index=None):
        page = self.pages.currentWidget()
        for key, workspace in self.workspaces.items():
            if workspace is page and key in self.platform_buttons:
                self.platform_buttons[key].setChecked(True)

    def open_module(self, key):
        if key in self.workspaces:
            self.pages.setCurrentWidget(self.workspaces[key])
            self.sync_selection()
            return
        info = PROVIDERS[key]
        try:
            root = self.root if key in ('cloudflare', 'gname') else self.root / 'modules' / key
            page = info['factory'](root)
            if not isinstance(page, QWidget) or not hasattr(page, 'busy'):
                raise ValueError('模块必须返回具有 busy 状态和安全 closeEvent 的 QWidget')
            if key == 'cloudflare': page.platform.hide()
            self.workspaces[key] = page
            self.pages.addWidget(page)
            self.pages.setCurrentWidget(page)
        except Exception as exc:
            self.sync_selection()
            QMessageBox.warning(self, '平台加载失败', str(exc))

    def unload_module(self, key):
        """Developer lifecycle API; deliberately absent from the product UI."""
        page = self.workspaces.get(key)
        if page is None: return True
        if page.busy or not page.close(): return False
        self.pages.removeWidget(page)
        del self.workspaces[key]
        page.deleteLater()
        self.sync_selection()
        return True

    def remove_plugin(self, key):
        """Developer API for unregistering an idle external module."""
        info = PROVIDERS.get(key, {})
        if not info.get('external') or not self.unload_module(key): return False
        name = info['external']
        del PROVIDERS[key]
        for loaded in tuple(sys.modules):
            if loaded == name or loaded.startswith(name + '.'):
                sys.modules.pop(loaded, None)
        self.refresh_modules()
        return True

    def closeEvent(self, event):
        if any(page.busy for page in self.workspaces.values()):
            QMessageBox.information(self, '仍有后台任务', '请先在各平台取消或等待任务结束。平台切换不会停止任务。')
            event.ignore()
            return
        for page in tuple(self.workspaces.values()):
            if not page.close():
                event.ignore()
                return
        event.accept()
