from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QSpinBox,
    QDoubleSpinBox, QCheckBox, QTableView, QHeaderView, QAbstractItemView,
    QListWidget, QStackedWidget, QTabWidget, QSplitter, QMessageBox, QInputDialog,
    QDialog, QDialogButtonBox, QFileDialog, QProgressBar, QScrollArea, QFrame,
    QSizePolicy, QTextBrowser, QAbstractSpinBox,
)

from .credentials import Vault
from .storage import Store
from .api_client import Client
from .operations import OperationsController
from .table_model import TableModel
from .rule_templates import example_rules
from .cloudflare import Cloudflare, PHASES, SETTINGS, domains
from .providers import PROVIDERS
from .ui_components import combo, line, editor, label, button, card, AlignedForm, DomainEditor
from .qt_jobs import Worker
from .token_view_ui import TokenViewDialog
from .browser_token_ui import BrowserTokenDialog, show_browser_token
from .local_paths import local_data_root
from .guidance import guide_html, PAGE_PERMISSIONS, RULE_PERMISSIONS, TOKEN_URL


STYLE = """
QMainWindow, QDialog { background: #f3f5f9; }
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #202e44; }
QWidget#sidebar { background: #15233a; }
QLabel#brand { color: white; font-size: 25px; font-weight: 700; }
QLabel#sideCaption { color: #a6b5ce; }
QLabel#heading { font-size: 24px; font-weight: 700; }
QLabel#muted { color: #61728a; }
QLabel#notice { color: #92601e; background: #fff4df; border-radius: 6px; padding: 9px; }
QListWidget#navigation { background: transparent; border: none; color: #bfcee4; outline: none; }
QListWidget#navigation::item { padding: 11px 10px; margin: 2px 0; border-radius: 6px; }
QListWidget#navigation::item:selected { background: #304158; color: #ffb15e; }
QPushButton { background: white; border: 1px solid #d9e0ea; padding: 8px 13px; border-radius: 6px; }
QPushButton:hover { border-color: #ed943f; background: #fff9f2; }
QPushButton:disabled { color: #9ba6b6; background: #e9edf2; }
QPushButton#primary { background: #ee8b2d; border-color: #ee8b2d; color: white; font-weight: 600; }
QPushButton#primary:disabled { background: #dbb38d; border-color: #dbb38d; }
QPushButton#danger { color: #bf3e43; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
 background: white; border: 1px solid #d7dfe9; border-radius: 5px; padding: 6px; selection-background-color: #e8a263;
}
QTableView { background: white; alternate-background-color: #f8fafc; border: 1px solid #e1e6ee; gridline-color: #edf0f4; selection-background-color: #ffead3; selection-color: #202e44; }
QHeaderView::section { background: #edf1f7; border: none; padding: 9px; font-weight: 600; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 10px 20px; background: #e9edf4; margin-right: 4px; border-top-left-radius: 5px; border-top-right-radius: 5px; }
QTabBar::tab:selected { background: white; color: #bd661d; }
QProgressBar { border: none; border-radius: 4px; background: #e0e6ee; height: 8px; text-align: center; }
QProgressBar::chunk { background: #ee983f; border-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QWidget#workspace, QWidget#formContent { background: transparent; }
QFrame#card { background: white; border: 1px solid #dce4ef; border-radius: 10px; }
QLabel#sectionTitle { color: #203550; font-size: 16px; font-weight: 700; }
QLabel#step { color: #b66119; font-size: 13px; font-weight: 600; }
QLabel#permission { background: #eff5fc; color: #466483; border-radius: 5px; padding: 7px 10px; }
QLabel#empty { color: #75859a; font-size: 13px; padding: 12px; }
QPushButton { min-height: 20px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 22px; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #e59950; }
QSpinBox, QDoubleSpinBox { padding-right: 6px; }
QScrollBar:vertical { background: #f1f4f8; width: 10px; margin: 0; border-radius: 5px; }
QScrollBar::handle:vertical { background: #c2cede; min-height: 28px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle:vertical { height: 9px; background: #e6ebf3; border-radius: 4px; }
QTableView { border-radius: 5px; }
QProgressBar { min-height: 10px; max-height: 10px; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 26px; border: none; }
"""
STYLE += '\nQComboBox::down-arrow { image: url("' + (Path(__file__).parent / 'assets' / 'chevron.svg').as_posix() + '"); width: 14px; height: 14px; }'


def configure_app(app):
    app.setStyle("Fusion")
    # Offscreen/minimal Windows Qt platforms may not enumerate system fonts.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if not QFontDatabase.families():
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            if (fonts / name).exists():
                QFontDatabase.addApplicationFont(str(fonts / name))
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)


class GuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建 Cloudflare Token · 新手指南")
        self.resize(960, 740)
        self.setMinimumSize(740, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.addWidget(label("创建令牌，先选对权限", "heading"))
        layout.addWidget(label("从 DNS 基础配置开始，再按功能增加权限。可随时在主界面重新打开此指南。"))
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(guide_html())
        layout.addWidget(self.browser, 1)
        row = QHBoxLayout()
        row.addWidget(button("自动配置 Token 权限", lambda: show_browser_token(self), True))
        row.addStretch()
        row.addWidget(button("我知道了", self.accept))
        layout.addLayout(row)


def table(model):
    w = QTableView()
    w.setModel(model)
    w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    w.setAlternatingRowColors(True)
    w.setSortingEnabled(False)
    w.setWordWrap(False)
    w.verticalHeader().hide()
    w.verticalHeader().setDefaultSectionSize(34)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    w.horizontalHeader().setStretchLastSection(True)
    return w


class TokenDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("添加独立 Token")
        self.resize(660, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        layout.addWidget(label("连接你的 Cloudflare", "heading"))
        layout.addWidget(label("第一次使用？DNS 操作需要 Zone → Zone → Read 和 Zone → DNS → Edit。", "permission"))
        layout.addWidget(button("自动配置 Token 权限", lambda: show_browser_token(self), True))
        layout.addWidget(button("查看创建步骤与完整权限清单", lambda: GuideDialog(self).exec()))
        layout.addWidget(label("每个 Token 独立保存域名缓存与操作记录。默认使用主密码加密；也可选择当前 Windows 用户的 DPAPI。"))
        form = AlignedForm()
        self.name = line("例如：生产环境 · 主账号")
        self.token = line("粘贴 Cloudflare API Token")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("配置名称", self.name)
        form.addRow("API Token", self.token)
        self.encryption = combo(["主密码加密 · AES-256-GCM", "Windows 用户加密 · DPAPI"])
        self.password = line("至少 10 个字符；下次启动解锁此 Token 时需要")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.encryption.currentIndexChanged.connect(lambda i: self.password.setEnabled(i == 0))
        form.addRow("凭据保护", self.encryption)
        form.addRow("本地主密码", self.password)
        self.password.setToolTip("自己设置的本地加密密码，不是 Cloudflare 登录密码，也不是 Token")
        layout.addLayout(form)
        layout.addWidget(label("支持用户 Token 和 Account Token；不使用 Global API Key。不要将 Token 发给任何人。"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存 Token")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate_and_accept(self):
        if not self.name.text().strip() or not self.token.text().strip():
            QMessageBox.warning(self, "请补充信息", "请填写配置名称和 Cloudflare API Token。还没有 Token 时，可点击上方权限指南。")
            return
        if self.encryption.currentIndex() == 0 and len(self.password.text()) < 10:
            QMessageBox.warning(self, "设置本地主密码", "请自行设置至少 10 个字符的本地加密密码，用于下次解锁。不是 Cloudflare 登录密码。")
            return
        self.accept()


class Window(QMainWindow):
    def __init__(self, root=None):
        super().__init__()
        self.setWindowTitle("CloudDesk · 云平台工具箱")
        self.resize(1390, 940)
        self.setMinimumSize(1120, 780)
        self.root = Path(root) if root is not None else local_data_root()
        self.vault = Vault(self.root)
        self.client = self.store = self.provider = self.job = self.plan = None
        self.zones_data = []
        self.events = {}
        self.completed_ids = set()
        self.form_scrollers = []
        self.page_metadata = []
        self.busy = False
        self.unlocked_passwords = {}
        self.plan_consumed = False
        self.build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flush_events)
        self.timer.start(100)
        self.load_profiles()

    def build(self):
        shell = QWidget()
        self.setCentralWidget(shell)
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 26, 18, 20)
        sl.addWidget(label("CloudDesk", "brand"))
        sl.addWidget(label("云平台工具箱  /  DESKTOP", "sideCaption"))
        sl.addSpacing(20)
        self.platform = combo([p["title"] for p in PROVIDERS.values()])
        sl.addWidget(self.platform)
        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        self.nav.addItems(["域名总览 / 导出", "添加域名 / Zone", "DNS 添加 / 更新", "解析替换 / Replace", "删除解析 / 清空", "删除域名 / Zone", "解析代理状态", "SSL / TLS 证书", "SSL 自定义主机名", "清除缓存 / 配置", "传输优化", "页面 / WAF 规则", "其他设置"])
        self.nav.currentRowChanged.connect(self.navigate)
        sl.addWidget(self.nav, 1)
        sl.addWidget(label("TOKEN 隔离  ·  本地运行\nv0.10.4  /  Cloudflare API v4", "sideCaption"))
        outer.addWidget(side)
        main = QWidget()
        main.setObjectName("workspace")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(24, 22, 24, 18)
        ml.setSpacing(10)
        heading = QHBoxLayout()
        heading.addWidget(label("Cloudflare 工作空间", "heading"))
        heading.addStretch()
        heading.addWidget(button("自动配置 Token", lambda: BrowserTokenDialog(self.root, self).exec(), True))
        heading.addWidget(button("权限指南", self.show_guide))
        ml.addLayout(heading)
        account_card, account_layout = card()
        self.account_bar = QWidget()
        bar = QHBoxLayout(self.account_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(QLabel("操作 Token"))
        self.tokens = QComboBox()
        self.tokens.setMinimumWidth(220)
        self.tokens.currentIndexChanged.connect(self.switch_profile)
        bar.addWidget(self.tokens, 1)
        bar.addWidget(button("添加 Token", self.add_profile))
        bar.addWidget(button("查看 Token", self.view_profile))
        bar.addWidget(button("移除配置", self.remove_profile))
        self.refresh_btn = button("读取域名", self.refresh_zones, True)
        bar.addWidget(self.refresh_btn)
        account_layout.addWidget(self.account_bar)
        self.identity = label("请添加 Token；凭据仅发送至 api.cloudflare.com")
        account_layout.addWidget(self.identity)
        ml.addWidget(account_card)
        self.tabs = QTabWidget()
        ml.addWidget(self.tabs, 1)
        self.build_zones()
        self.build_workspace()
        self.build_history()
        foot = QHBoxLayout()
        self.status = label("第一次使用：查看 Token 指南 → 添加 Token → 读取域名")
        self.status.setMaximumHeight(42)
        foot.addWidget(self.status, 1)
        self.cancel_btn = button("取消当前任务", self.cancel_job)
        self.cancel_btn.setEnabled(False)
        foot.addWidget(self.cancel_btn)
        ml.addLayout(foot)
        outer.addWidget(main, 1)
        self.nav.setCurrentRow(0)

    def build_zones(self):
        page, layout = card()
        layout.addWidget(label("域名资源", "sectionTitle"))
        self.zone_filter_timer = QTimer(self)
        self.zone_filter_timer.setSingleShot(True)
        self.zone_filter_timer.setInterval(180)
        self.zone_filter_timer.timeout.connect(self.filter_zones)
        bar = QHBoxLayout()
        self.search = line("筛选域名 / Account / NS")
        self.search.textChanged.connect(lambda: self.zone_filter_timer.start())
        self.zone_state = combo(["全部状态", "active", "pending", "initializing", "moved", "deleted", "deactivated"])
        self.zone_state.currentTextChanged.connect(self.filter_zones)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.zone_state)
        bar.addWidget(button("全选当前结果", lambda: self.zone_table.selectAll()))
        bar.addWidget(button("取消选择", lambda: self.zone_table.clearSelection()))
        bar.addWidget(button("导出当前列表", self.export_zones))
        layout.addLayout(bar)
        layout.addWidget(label("选中要操作的域名，再打开左侧功能。支持 Ctrl / Shift 多选；筛选后选择会重置。"))
        self.zone_empty = label("还没有域名。先按右上角指南创建 Token，再点击“添加 Token”和“读取域名”。", "permission")
        layout.addWidget(self.zone_empty)
        self.zone_model = TableModel([("name", "域名"), ("status", "状态"), ("account_name", "Cloudflare Account"), ("ns", "名称服务器 / NS"), ("id", "Zone ID")])
        self.zone_table = table(self.zone_model)
        self.zone_table.setColumnWidth(0, 235)
        self.zone_table.setColumnWidth(2, 180)
        self.zone_table.setColumnWidth(3, 240)
        layout.addWidget(self.zone_table, 1)
        self.zone_count = label("0 个域名")
        layout.addWidget(self.zone_count)
        self.tabs.addTab(page, "域名与选择")

    def build_workspace(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        self.inputs = QWidget()
        il = QVBoxLayout(self.inputs)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(10)
        scope_card, scope_layout = card()
        scope_heading = QHBoxLayout()
        scope_heading.addWidget(label("01  操作范围", "sectionTitle"))
        scope_heading.addStretch()
        scope_note = label("填写域名优先；留空使用列表选择")
        scope_note.setWordWrap(False)
        scope_heading.addWidget(scope_note)
        scope_layout.addLayout(scope_heading)
        self.scope = DomainEditor(5)
        self.scope.setPlaceholderText("操作域名，每行一个；留空则使用“域名与选择”中选中的域名。添加 Zone 时必须填写。")
        scope_layout.addWidget(self.scope)
        il.addWidget(scope_card)
        self.scope.textChanged.connect(self.invalidate)
        split = QSplitter(Qt.Orientation.Vertical)
        self.workspace_split = split
        split.setChildrenCollapsible(False)
        parameters, parameter_layout = card()
        title_row = QHBoxLayout()
        title_row.addWidget(label("02", "step"))
        self.operation_title = label("参数设置", "sectionTitle")
        title_row.addWidget(self.operation_title, 1)
        title_row.addWidget(button("所需权限", self.show_guide))
        parameter_layout.addLayout(title_row)
        self.operation_hint = label("")
        parameter_layout.addWidget(self.operation_hint)
        self.permission_hint = label("", "permission")
        parameter_layout.addWidget(self.permission_hint)
        self.forms = QStackedWidget()
        self.forms.setMinimumHeight(105)
        self.forms.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        parameter_layout.addWidget(self.forms, 1)
        self.execution_controls = QWidget()
        params = QHBoxLayout(self.execution_controls)
        params.setContentsMargins(0, 8, 0, 0)
        params.setSpacing(10)
        self.workers = QSpinBox()
        self.workers.setRange(1, 12)
        self.workers.setValue(4)
        self.workers.setFixedWidth(68)
        self.workers.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0.2, 3.0)
        self.rate.setSingleStep(0.2)
        self.rate.setValue(2.0)
        self.rate.setFixedWidth(72)
        self.rate.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        params.addWidget(QLabel("并发域名"))
        params.addWidget(self.workers)
        params.addWidget(QLabel("请求 / 秒"))
        params.addWidget(self.rate)
        self.batch_dns = QCheckBox("DNS 原生批处理")
        self.batch_dns.setChecked(True)
        self.batch_dns.setToolTip("每个域名最多 100 条记录合并为一个请求；可关闭以使用逐条请求")
        self.batch_dns.toggled.connect(self.invalidate)
        params.addWidget(self.batch_dns)
        params.addStretch()
        self.preview_btn = button("① 生成操作预览", self.preview, True)
        params.addWidget(self.preview_btn)
        parameter_layout.addWidget(self.execution_controls)
        il.addWidget(parameters, 1)
        # A short window scrolls the input section instead of squeezing domain lines.
        self.inputs_scroll = QScrollArea()
        self.inputs_scroll.setWidgetResizable(True)
        self.inputs_scroll.setWidget(self.inputs)
        split.addWidget(self.inputs_scroll)
        bottom, bl = card()
        self.task_card = bottom
        controls = QHBoxLayout()
        self.plan_label = label("03  执行计划 · 尚未生成", "sectionTitle")
        controls.addWidget(self.plan_label, 1)
        controls.addWidget(button("查看 / 导出详情", self.plan_details))
        self.toggle_task_btn = button("展开", lambda: self.set_task_expanded(not self.task_expanded))
        controls.addWidget(self.toggle_task_btn)
        self.execute_btn = button("② 确认并执行", self.execute_plan, True)
        self.execute_btn.setEnabled(False)
        controls.addWidget(self.execute_btn)
        bl.addLayout(controls)
        self.plan_empty = label("先填写参数并生成预览；核对后才会向 Cloudflare 提交更改。", "empty")
        bl.addWidget(self.plan_empty)
        self.plan_model = TableModel([("target", "域名"), ("method", "请求"), ("summary", "操作内容"), ("state", "状态"), ("detail", "结果")])
        self.plan_table = table(self.plan_model)
        self.plan_table.setColumnWidth(0, 190)
        self.plan_table.setColumnWidth(1, 70)
        self.plan_table.setColumnWidth(2, 270)
        self.plan_table.doubleClicked.connect(self.action_details)
        bl.addWidget(self.plan_table, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        bl.addWidget(self.progress)
        split.addWidget(bottom)
        split.setSizes([500, 205])
        layout.addWidget(split)
        self.tabs.addTab(page, "批量操作")
        self.create_forms()
        self.set_task_expanded(False)
        for widget in self.forms.findChildren(QLineEdit):
            widget.textChanged.connect(self.invalidate)
        for widget in self.forms.findChildren(QPlainTextEdit):
            widget.textChanged.connect(self.invalidate)
        for widget in self.forms.findChildren(QComboBox):
            widget.currentIndexChanged.connect(self.invalidate)
        for widget in self.forms.findChildren(QSpinBox):
            widget.valueChanged.connect(self.invalidate)
        for widget in self.forms.findChildren(QCheckBox):
            widget.toggled.connect(self.invalidate)
        self.zone_table.selectionModel().selectionChanged.connect(self.invalidate)

    def set_task_expanded(self, expanded):
        self.task_expanded = expanded
        self.plan_table.setVisible(expanded)
        self.progress.setVisible(expanded)
        self.plan_empty.setVisible(expanded and not self.plan_model.rows)
        self.toggle_task_btn.setText("收起" if expanded else "展开")
        self.task_card.setMinimumHeight(175 if expanded else 68)
        self.task_card.setMaximumHeight(16777215 if expanded else 68)
        if expanded:
            self.workspace_split.setSizes([max(360, self.workspace_split.height()-215), 215])

    def form(self, title, hint):
        page = QWidget()
        page.setObjectName("formContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 10, 10)
        fields = AlignedForm()
        layout.addLayout(fields)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.viewport().setAutoFillBackground(False)
        self.forms.addWidget(scroll)
        self.form_scrollers.append(scroll)
        self.page_metadata.append((title, hint))
        return fields, layout

    def create_forms(self):
        # Form index == navigation index - 1.
        f, layout = self.form("批量添加域名", "创建 Full Zone。添加后仍需到域名注册商修改 NS；账户由 Account ID 明确指定。")
        self.account_id = line("Cloudflare Account ID，32 位十六进制")
        f.addRow("目标 Account ID", self.account_id)
        f.addRow(button("读取可见 Accounts", self.read_accounts))

        f, layout = self.form("DNS 批量添加与更新", "可对多个域名应用同一模板，也可导入每个域名不同的记录。更新匹配“完整名称 + 类型”，有多个匹配则拒绝覆盖。")
        self.dns_mode = combo(["添加（跳过相同记录）", "添加或更新（唯一匹配）"])
        self.dns_type = combo(["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA", "HTTPS", "SVCB"])
        self.dns_name = line("@、www、* 或完整名称")
        self.dns_name.setText("@")
        self.dns_content = line("记录值；SRV / CAA 等复杂记录请用 JSON data 字段")
        self.dns_ttl = QSpinBox()
        self.dns_ttl.setRange(1, 86400)
        self.dns_ttl.setValue(1)
        self.dns_proxy = QCheckBox("开启代理（A / AAAA / CNAME）")
        self.dns_priority = QSpinBox()
        self.dns_priority.setRange(0, 65535)
        self.dns_priority.setValue(10)
        f.addRow("模式", self.dns_mode)
        names = QHBoxLayout()
        self.dns_type.setFixedWidth(112)
        names.addWidget(self.dns_type)
        names.addSpacing(12)
        names.addWidget(QLabel("记录名称"))
        names.addWidget(self.dns_name, 1)
        f.addRow("记录类型", names)
        f.addRow("记录值", self.dns_content)
        extra = QHBoxLayout()
        self.dns_ttl.setFixedWidth(95)
        self.dns_priority.setFixedWidth(95)
        self.dns_ttl.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.dns_priority.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        extra.addWidget(self.dns_ttl)
        extra.addWidget(QLabel("TTL 秒（1 = 自动）"))
        extra.addSpacing(12)
        extra.addWidget(self.dns_priority)
        extra.addWidget(QLabel("MX 优先级"))
        extra.addStretch()
        f.addRow("生存时间 / MX", extra)
        f.addRow("代理", self.dns_proxy)
        self.dns_import_toggle = QCheckBox("使用 CSV / JSON 批量记录（高级）")
        f.addRow("批量导入", self.dns_import_toggle)
        self.dns_import = editor("", 90)
        self.dns_import.setPlaceholderText('可选 JSON 数组 / CSV，填写后优先使用导入内容。CSV 表头：zone,name,type,content,ttl,proxied,priority\nexample.com,www,A,192.0.2.1,1,true,10')
        f.addRow("批量记录", self.dns_import)
        f.setRowVisible(self.dns_import, False)
        self.dns_import_toggle.toggled.connect(lambda enabled, form=f: form.setRowVisible(self.dns_import, enabled))
        dns_buttons = QHBoxLayout()
        dns_buttons.addWidget(button("导入 CSV / JSON 文件", self.import_records))
        dns_buttons.addWidget(button("读取 / 导出 DNS 记录", lambda: self.inspect("DNS")))
        f.addRow(dns_buttons)
        self.filters = {}
        for kind, title, hint in [
            ("replace", "解析值批量替换", "精确匹配旧记录值；可同时限制名称与类型。"),
            ("delete", "删除解析 / 清空记录", "名称、类型、记录值均不限制时，将删除目标域名的全部 DNS 记录。请检查预览。"),
        ]:
            f, layout = self.form(title, hint)
            self.make_filters(f, kind)
            if kind == "replace":
                self.replace_new = line("替换后的完整记录值")
                f.addRow("新值", self.replace_new)
        f, layout = self.form("删除域名 / Zone", "将删除上方域名范围内的整个 Zone。此操作不能通过本工具自动恢复。执行时必须输入确认短语。")
        layout.insertWidget(1, label("本页无需额外参数。请在上方选择域名，生成预览后核对 Token、域名和 DELETE 请求。", "notice"))
        f, layout = self.form("批量修改代理状态", "仅处理 API 标记为可代理的 DNS 记录；跳过 TXT / MX 等不可代理类型。")
        self.make_filters(f, "proxy")
        self.proxy_value = combo(["开启代理", "关闭代理"])
        f.addRow("目标状态", self.proxy_value)
        self.settings_ui = {}
        self.make_settings("SSL/TLS", "SSL / TLS 边缘证书", "按设置项读取并修改，支持 Strict、最低 TLS、HTTPS 跳转等。")

        f, layout = self.form("SSL 自定义主机名", "Cloudflare for SaaS 功能。需要相应权限、套餐及主机名验证；不是普通 DNS 记录。")
        self.hostname_mode = combo(["添加", "修改", "删除"])
        self.hostname_json = editor('[\n  {"hostname": "customer.example.com", "ssl": {"method": "txt", "type": "dv"}}\n]', 120)
        f.addRow("操作", self.hostname_mode)
        f.addRow("主机名列表 JSON", self.hostname_json)
        f.addRow(button("读取自定义主机名 / 验证状态", lambda: self.inspect("自定义主机名")))

        f, layout = self.make_settings("缓存", "清除缓存 / 配置", "清缓存支持全部、URL、标签、主机名、前缀；可用方式与限额由 Cloudflare 套餐决定。")
        self.cache_mode = combo(["修改缓存设置", "清除缓存"])
        self.cache_mode.currentIndexChanged.connect(self.update_permissions)
        f.insertRow(0, "操作", self.cache_mode)
        self.purge_json = editor('{"purge_everything": true}', 65)
        f.addRow("清缓存 JSON", self.purge_json)
        self.make_settings("传输优化", "传输优化", "支持 HTTP/2、HTTP/3、0-RTT、Early Hints 等。已弃用的 Auto Minify / Brotli 开关不再发送请求。")

        f, layout = self.form("页面规则 / WAF / Rulesets", "复制采用追加模式并保留原表达式中的域名；不会自动改写字符串。跨账户引用 ID、套餐限制须自行核对。删除仅作用于当前 Zone 阶段入口规则。")
        self.rules_kind = combo(["规则集", "页面规则"])
        self.rules_mode = combo(["添加规则", "从源域名复制", "删除规则"])
        self.rules_phase = combo(PHASES.keys())
        self.rules_kind.currentIndexChanged.connect(self.update_permissions)
        self.rules_phase.currentIndexChanged.connect(self.update_permissions)
        r = QHBoxLayout()
        r.addWidget(self.rules_kind)
        r.addWidget(self.rules_mode)
        r.addWidget(self.rules_phase)
        f.addRow("类型 / 操作 / 阶段", r)
        self.rules_source = line("复制时填写源域名，源域名不能在目标范围中")
        self.rules_ids = line("删除时填写规则 ID，以空格或换行分隔；留空删除该类型/阶段全部规则")
        f.addRow("复制源域名", self.rules_source)
        f.addRow("删除规则 ID", self.rules_ids)
        self.rules_json = editor('[\n  {"action": "managed_challenge", "expression": "(ip.src eq 192.0.2.1)", "description": "Example", "enabled": true}\n]', 110)
        f.addRow("规则 JSON 数组", self.rules_json)
        btns = QHBoxLayout()
        btns.addWidget(button("载入当前类型模板", self.rule_template))
        btns.addWidget(button("读取当前规则", self.inspect_rules))
        f.addRow(btns)
        self.make_settings("其他设置", "其他 Zone 设置", "提供常用设置及 JSON 批量修改。高级字段须使用官方 setting ID，读取失败会阻止整个计划生成。")

    def make_filters(self, f, kind):
        name = line("留空匹配全部名称；@ 匹配根域名；* 匹配通配符记录")
        typ = combo(["全部", "A", "AAAA", "CNAME", "TXT", "MX", "NS", "SRV", "CAA", "HTTPS", "SVCB"])
        content = line("精确记录值；留空不限制（替换操作必填）")
        f.addRow("记录名称", name)
        f.addRow("记录类型", typ)
        f.addRow("当前记录值", content)
        f.addRow(button("读取 DNS 记录", lambda: self.inspect("DNS")))
        self.filters[kind] = (name, typ, content)

    def make_settings(self, key, title, hint):
        f, layout = self.form(title, hint)
        setting = combo(SETTINGS[key].keys())
        value = QComboBox()
        value.setEditable(True)

        def values():
            value.clear()
            value.addItems([json.dumps(v, ensure_ascii=False) for v in SETTINGS[key][setting.currentText()]])
        setting.currentTextChanged.connect(values)
        values()
        advanced = editor("", 70)
        advanced.setPlaceholderText('可选，填写后优先使用 JSON 对象，例如 {"ssl":"strict","always_use_https":"on"}')
        f.addRow("设置项", setting)
        f.addRow("JSON 值", value)
        f.addRow("批量设置 JSON", advanced)
        f.addRow(button("读取当前设置值", lambda: self.inspect("设置", {"setting": setting.currentText()})))
        self.settings_ui[key] = (setting, value, advanced)
        return f, layout

    def build_history(self):
        page, layout = card()
        layout.addWidget(label("独立任务记录", "sectionTitle"))
        row = QHBoxLayout()
        row.addWidget(label("当前 Token 的最近 5,000 条执行记录。详情含修改前快照；历史记录不会自动重放。"), 1)
        row.addWidget(button("刷新记录", self.history))
        row.addWidget(button("导出记录", self.export_history))
        layout.addLayout(row)
        self.history_model = TableModel([("target", "域名"), ("method", "请求"), ("state", "状态"), ("time", "时间"), ("detail", "结果")])
        self.history_table = table(self.history_model)
        self.history_table.doubleClicked.connect(self.history_detail)
        layout.addWidget(self.history_table)
        self.tabs.addTab(page, "任务记录")

    def navigate(self, index):
        if not hasattr(self, "forms") or index < 0:
            return
        # Navigation is view-only. Input changes, not page switches, invalidate plans.
        if index == 0:
            self.tabs.setCurrentIndex(0)
        else:
            self.forms.setCurrentIndex(index - 1)
            self.operation_title.setText(self.page_metadata[index - 1][0])
            self.operation_hint.setText(self.page_metadata[index - 1][1])
            self.update_permissions()
            scroll = self.form_scrollers[index - 1]
            scroll.verticalScrollBar().setValue(0)
            QTimer.singleShot(0, lambda s=scroll: s.verticalScrollBar().setValue(0))
            self.tabs.setCurrentIndex(1)

    def show_guide(self):
        GuideDialog(self).exec()

    def update_permissions(self, *_):
        index = self.nav.currentRow()
        text = PAGE_PERMISSIONS.get(index, PAGE_PERMISSIONS[0])
        if index == 11:
            permission = "Page Rules" if self.rules_kind.currentText() == "页面规则" else RULE_PERMISSIONS[self.rules_phase.currentText()]
            text = f"Zone → {permission} → Edit + Zone → Zone → Read"
        elif index == 9:
            text = "Zone → " + ("Cache Purge → Purge" if self.cache_mode.currentIndex() == 1 else "Zone Settings → Edit") + " + Zone → Zone → Read"
        self.permission_hint.setText("所需权限：" + text)

    def invalidate(self, *_):
        if self.busy:
            return
        self.plan = None
        if hasattr(self, "execute_btn"):
            self.execute_btn.setEnabled(False)
            self.plan_label.setText("03  执行计划 · 请生成新预览")

    def load_profiles(self, selected=None):
        self.tokens.blockSignals(True)
        self.tokens.clear()
        for p in self.vault.profiles:
            self.tokens.addItem(p["label"], p["id"])
        if selected:
            self.tokens.setCurrentIndex(self.tokens.findData(selected))
        self.tokens.blockSignals(False)
        self.switch_profile()

    def switch_profile(self, *_):
        if self.busy:
            return
        if self.client:
            self.client.close()
        if self.store:
            self.store.close()
        self.client = self.store = self.provider = None
        self.plan = None
        self.events.clear()
        self.scope.clear()
        self.account_id.clear()
        self.dns_import.clear()
        self.dns_import_toggle.setChecked(False)
        self.dns_content.clear()
        self.dns_name.setText("@")
        self.dns_type.setCurrentIndex(0)
        self.dns_mode.setCurrentIndex(0)
        self.dns_ttl.setValue(1)
        self.dns_priority.setValue(10)
        self.dns_proxy.setChecked(False)
        self.rules_source.clear()
        self.rules_ids.clear()
        self.rules_json.clear()
        self.hostname_json.clear()
        self.purge_json.setPlainText('{"purge_everything": true}')
        for widgets in self.filters.values():
            widgets[0].clear()
            widgets[1].setCurrentIndex(0)
            widgets[2].clear()
        self.replace_new.clear()
        for _, _, advanced in self.settings_ui.values():
            advanced.clear()
        self.plan_model.reset([])
        self.completed_ids.clear()
        self.set_task_expanded(False)
        self.history_model.reset([])
        self.zone_model.reset([])
        self.zones_data = []
        self.execute_btn.setEnabled(False)
        self.progress.setValue(0)
        self.identity.setText("请添加 Token；凭据仅发送至 api.cloudflare.com")
        key = self.tokens.currentData()
        if not key:
            return
        try:
            profile = next(p for p in self.vault.profiles if p["id"] == key)
            token = self.unlock_profile(profile)
            if token is None:
                return
            self.store = Store(self.root / "tokens", key)
            self.client = Client(token)
            self.provider = Cloudflare(self.client, self.store)
            self.zones_data = self.store.cached("zones", [])
            self.filter_zones()
            self.history()
            self.identity.setText(f"独立配置：{profile['label']}  ·  隔离标识 {key[:10]}  ·  本地缓存，请读取域名刷新")
        except Exception as exc:
            self.error(str(exc))

    def unlock_profile(self, profile):
        """One unlock path for connecting and displaying locally saved credentials."""
        key = profile['id']
        password = self.unlocked_passwords.get(key)
        if profile.get('encryption') == 'aes-gcm' and password is None:
            password, ok = QInputDialog.getText(self, '解锁 Token', f"请输入“{profile['label']}”的加密主密码：", QLineEdit.EchoMode.Password)
            if not ok:
                return None
        token = self.vault.token(profile, password)
        if password is not None:
            self.unlocked_passwords[key] = password
        return token

    def view_profile(self):
        key = self.tokens.currentData()
        profile = next((p for p in self.vault.profiles if p['id'] == key), None)
        if profile is None:
            self.status.setText('请先添加并选择一个本地 Token 配置。')
            return
        try:
            token = self.unlock_profile(profile)
            if token is not None:
                TokenViewDialog(profile['label'], token, self).exec()
        except Exception:
            self.error('无法解锁此 Token，请检查本地主密码或当前 Windows 用户。')

    def add_profile(self):
        dialog = TokenDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                password = dialog.password.text() if dialog.encryption.currentIndex() == 0 else None
                profile = self.vault.add(dialog.name.text(), dialog.token.text(), password)
                if password is not None:
                    self.unlocked_passwords[profile["id"]] = password
                dialog.token.clear()
                dialog.password.clear()
                self.load_profiles(profile["id"])
            except Exception as exc:
                self.error(str(exc))

    def remove_profile(self):
        key = self.tokens.currentData()
        if key and QMessageBox.question(self, "移除配置", "移除本地 Token 凭据？独立缓存和审计记录保留，不会修改 Cloudflare。") == QMessageBox.StandardButton.Yes:
            self.vault.remove(key)
            self.unlocked_passwords.pop(key, None)
            self.load_profiles()

    def require(self):
        if not self.provider:
            raise ValueError("请先添加并选择 API Token")

    def start_job(self, fn, done, message):
        if self.busy:
            return
        self.require()
        self.busy = True
        self.client.cancel.clear()
        self.client.limiter.rate = self.rate.value()
        self.zone_filter_timer.stop()
        for w in [self.account_bar, self.execution_controls, self.zone_table, self.search, self.zone_state]:
            w.setEnabled(False)
        self.scope.setReadOnly(True)
        for scroll in self.form_scrollers:
            scroll.widget().setEnabled(False)
        self.execute_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status.setText(message)
        self.job = Worker(fn, self.client.safe)
        self.job.result.connect(done)
        self.job.failure.connect(self.job_error)
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def job_finished(self):
        self.flush_events()
        self.busy = False
        for w in [self.account_bar, self.execution_controls, self.zone_table, self.search, self.zone_state]:
            w.setEnabled(True)
        self.scope.setReadOnly(False)
        for scroll in self.form_scrollers:
            scroll.widget().setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.execute_btn.setEnabled(bool(self.plan and self.plan.actions and not self.plan_consumed))
        self.history()
        old = self.job
        self.job = None
        if old:
            old.deleteLater()

    def job_error(self, message):
        if "403" in message or "10000" in message:
            message += "\n\n请核对 Token 的功能编辑权限、区域资源范围、IP 限制和有效期。可打开右上角“Token 创建与权限指南”。"
        self.status.setText(message)
        if not message.startswith("已取消"):
            self.error(message)

    def cancel_job(self):
        if self.client and self.busy:
            self.client.cancel.set()
            self.status.setText("正在取消：停止新请求，等待已发送的请求返回（最长约 30 秒）…")
            self.cancel_btn.setEnabled(False)

    def error(self, message):
        QMessageBox.warning(self, "操作提示", str(message))

    def refresh_zones(self):
        try:
            self.require()
            self.invalidate()
            self.start_job(self.operations().zones_job, self.zones_ready, "正在分页读取域名…")
        except Exception as exc:
            self.error(str(exc))

    def zones_ready(self, zones):
        self.zones_data = zones
        self.filter_zones()
        self.identity.setText(f"独立配置：{self.tokens.currentText()}  ·  隔离标识 {self.client.key[:10]}  ·  已读取 {len(zones)} 个域名")
        self.status.setText("域名读取完成")

    def filter_zones(self, *_):
        query = self.search.text().strip().lower()
        state = self.zone_state.currentText()
        rows = []
        for z in self.zones_data:
            row = {**z, "account_name": z.get("account", {}).get("name", ""), "ns": ", ".join(z.get("name_servers", []))}
            if state != "全部状态" and z.get("status") != state:
                continue
            if query and query not in (row["name"] + row["account_name"] + row["ns"]).lower():
                continue
            rows.append(row)
        self.zone_model.reset(rows)
        self.zone_count.setText(f"显示 {len(rows)} / 共 {len(self.zones_data)} 个域名")
        self.zone_empty.setVisible(not self.zones_data)

    def scope_snapshot(self):
        names = domains(self.scope.toPlainText())
        selected = [self.zone_model.rows[x.row()] for x in self.zone_table.selectionModel().selectedRows()]
        if not names and not selected:
            raise ValueError("请输入域名，或在域名总览中选择目标")
        return names, selected

    def operations(self):
        self.require()
        return OperationsController(self.client, self.store, self.provider)

    def collect(self):
        i = self.nav.currentRow()
        if i == 1:
            names = domains(self.scope.toPlainText())
            if not names:
                raise ValueError("添加域名需要在上方输入域名，每行一个")
            return "zone_add", {"names": names, "account": self.account_id.text()}
        if i == 2:
            return ("dns_add" if self.dns_mode.currentIndex() == 0 else "dns_upsert"), {
                "records": self.dns_import.toPlainText() if self.dns_import_toggle.isChecked() else "", "record": {
                    "type": self.dns_type.currentText(), "name": self.dns_name.text(),
                    "content": self.dns_content.text().strip(), "ttl": self.dns_ttl.value(),
                    "proxied": self.dns_proxy.isChecked(), "priority": self.dns_priority.value()}}
        if i in {3, 4, 6}:
            kind = {3: "replace", 4: "delete", 6: "proxy"}[i]
            name, typ, content = self.filters[kind]
            return "dns_" + kind, {"filter_name": name.text(), "filter_type": typ.currentText(),
                "filter_content": content.text(), "new_content": self.replace_new.text(), "proxied": self.proxy_value.currentIndex() == 0}
        if i == 5:
            return "zone_delete", {}
        if i in {7, 9, 10, 12}:
            if i == 9 and self.cache_mode.currentIndex() == 1:
                return "purge", {"body": json.loads(self.purge_json.toPlainText())}
            key = {7: "SSL/TLS", 9: "缓存", 10: "传输优化", 12: "其他设置"}[i]
            setting, value, advanced = self.settings_ui[key]
            values = json.loads(advanced.toPlainText()) if advanced.toPlainText().strip() else {setting.currentText(): json.loads(value.currentText())}
            return "settings", {"values": values}
        if i == 8:
            return ["hostname_add", "hostname_edit", "hostname_delete"][self.hostname_mode.currentIndex()], {"payloads": json.loads(self.hostname_json.toPlainText())}
        if i == 11:
            return ["rules_add", "rules_copy", "rules_delete"][self.rules_mode.currentIndex()], {
                "kind": self.rules_kind.currentText(), "phase": PHASES[self.rules_phase.currentText()],
                "source": self.rules_source.text(), "ids": self.rules_ids.text(),
                "rules": json.loads(self.rules_json.toPlainText()) if self.rules_mode.currentIndex() == 0 else []}
        raise ValueError("请先从左侧选择一个批量操作")

    def preview(self):
        try:
            self.require()
            op, options = self.collect()
            options["dns_batch"] = self.batch_dns.isChecked()
            scope = None if op == "zone_add" else self.scope_snapshot()
            workers = self.workers.value()
            self.plan = None
            self.plan_consumed = False
            self.plan_model.reset([])
            self.start_job(self.operations().preview_job(scope, op, options, workers), self.plan_ready, "正在读取远端并生成预览；此阶段不写入 Cloudflare…")
        except Exception as exc:
            self.error(str(exc))

    def plan_ready(self, plan):
        self.plan = plan
        self.plan_consumed = False
        self.completed_ids.clear()
        self.plan_model.reset([{"id": a.id, "target": a.target, "method": a.method, "summary": a.summary, "state": "待确认", "detail": a.path} for a in plan.actions])
        self.row_by_id = {a.id: i for i, a in enumerate(plan.actions)}
        self.plan_label.setText(f"03  执行计划 · {len(plan.actions)} 个请求 / {len(set(a.target for a in plan.actions))} 个域名")
        self.plan_empty.setVisible(not plan.actions)
        self.set_task_expanded(bool(plan.actions))
        self.progress.setRange(0, max(1, len(plan.actions)))
        self.progress.setValue(0)
        self.status.setText("预览完成，请检查明细后执行" if plan.actions else "没有需要更改的项目")

    def execute_plan(self):
        if not self.plan or self.plan_consumed or self.busy:
            return
        plan = self.plan
        count = len(plan.actions)
        text = f"Token：{self.tokens.currentText()}\n域名：{len(set(a.target for a in plan.actions))} 个\n写入请求：{count} 个\n\n操作会真实修改 Cloudflare；批量任务不保证跨请求原子性。"
        destructive = any(a.method == "DELETE" or (a.method == "PUT" and "/rulesets/" in a.path)
                          or (a.path.endswith("/dns_records/batch") and (a.body or {}).get("deletes")) for a in plan.actions)
        if destructive:
            answer, ok = QInputDialog.getText(self, "确认删除 / 规则集修改", text + f"\n请输入 APPLY {count} 继续：")
            if not ok or answer != f"APPLY {count}":
                return
        elif QMessageBox.question(self, "确认批量执行", text) != QMessageBox.StandardButton.Yes:
            return
        self.plan_consumed = True
        workers = self.workers.value()
        try:
            self.start_job(self.operations().execute_job(plan, workers), self.executed, "正在执行；同一域名顺序执行，不同域名并发…")
        except Exception as exc:
            self.error(str(exc))

    def queue_event(self, aid, state, detail):
        self.events[aid] = (state, detail)

    def flush_events(self):
        if self.job:
            self.events.update(self.job.take_events())
        if not self.events:
            return
        pending, self.events = self.events, {}
        changed = []
        for aid, (state, detail) in pending.items():
            idx = getattr(self, "row_by_id", {}).get(aid)
            if idx is None or idx >= len(self.plan_model.rows):
                continue
            self.plan_model.rows[idx].update(state=state, detail=detail)
            if state in {"成功", "失败", "结果未知", "未执行"}:
                self.completed_ids.add(aid)
            changed.append(idx)
        if changed:
            first = max(0, self.plan_table.rowAt(0))
            last = self.plan_table.rowAt(self.plan_table.viewport().height() - 1)
            last = last if last >= 0 else min(len(self.plan_model.rows) - 1, first + 50)
            self.plan_model.dataChanged.emit(self.plan_model.index(first, 3), self.plan_model.index(last, 4))
        self.progress.setValue(len(self.completed_ids))

    def executed(self, _):
        self.flush_events()
        counts = {}
        for row in self.plan_model.rows:
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        self.status.setText("执行结束 · " + " / ".join(f"{k} {v}" for k, v in counts.items()) + "；再次操作请重新生成预览")

    def inspect(self, kind, options=None):
        try:
            self.require()
            scope, workers = self.scope_snapshot(), self.workers.value()
            self.start_job(self.operations().inspect_job(scope, kind, options or {}, workers), lambda result: self.show_json(kind + " · 读取结果", result), "正在读取配置…")
        except Exception as exc:
            self.error(str(exc))

    def inspect_rules(self):
        self.inspect(self.rules_kind.currentText(), {"phase": PHASES[self.rules_phase.currentText()]})

    def read_accounts(self):
        try:
            self.start_job(self.operations().accounts_job, lambda data: self.show_json("可见 Accounts：将目标 id 填入 Account ID", data), "正在读取 Accounts（需要账户读取权限）…")
        except Exception as exc:
            self.error(str(exc))

    def show_json(self, title, data):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        layout.addWidget(view)
        layout.addWidget(button("导出 JSON", lambda: self.save_text(text, "JSON (*.json)", "details.json")))
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def action_details(self, index):
        if self.plan and index.row() < len(self.plan.actions):
            a = self.plan.actions[index.row()]
            self.show_json("请求详情与修改前快照", {**vars(a), "result": self.plan_model.rows[index.row()]})

    def plan_details(self):
        if self.plan:
            self.show_json("完整执行计划（不含 Token）", {"created": self.plan.created, "batch": self.plan.batch,
                "token_label": self.tokens.currentText(), "actions": [vars(a) for a in self.plan.actions]})

    def import_records(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入 DNS 记录", "", "记录文件 (*.csv *.json);;所有文件 (*)")
        if path:
            try:
                if Path(path).stat().st_size > 10 * 1024 * 1024:
                    raise ValueError("单次导入上限 10 MB，请分批")
                self.dns_import.setPlainText(Path(path).read_text("utf-8-sig"))
                self.dns_import_toggle.setChecked(True)
            except Exception as exc:
                self.error(str(exc))

    def rule_template(self):
        rules = example_rules(self.rules_kind.currentText(), self.rules_phase.currentText())
        self.rules_json.setPlainText(json.dumps(rules, ensure_ascii=False, indent=2))

    def history(self):
        if self.busy:
            return
        rows = self.store.history(include_payload=False) if self.store else []
        for row in rows:
            row["time"] = time.strftime("%m-%d %H:%M:%S", time.localtime(row["updated"]))
        self.history_model.reset(rows)

    def history_detail(self, index):
        if self.busy:
            self.status.setText("任务执行时可查看当前计划详情；历史快照在任务结束后可打开。")
            return
        if self.store and index.isValid():
            aid = self.history_model.rows[index.row()]["id"]
            self.start_job(lambda _: self.store.history_detail(aid), lambda data: self.show_json("执行记录详情", data), "读取历史快照…")

    def save_text(self, text, filters, filename):
        path, _ = QFileDialog.getSaveFileName(self, "导出", filename, filters)
        if path:
            try:
                Path(path).write_text(text, "utf-8-sig")
            except Exception as exc:
                self.error(str(exc))

    def export_zones(self):
        import io
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["域名", "状态", "Account", "NS", "Zone ID"])
        for row in self.zone_model.rows:
            values = [str(row.get(k, "")) for k in ["name", "status", "account_name", "ns", "id"]]
            writer.writerow(["'" + x if x.startswith(("=", "+", "-", "@", "\t", "\r")) else x for x in values])
        self.save_text(buffer.getvalue(), "CSV (*.csv)", "cloudflare-zones.csv")

    def export_history(self):
        if self.busy:
            self.status.setText("当前任务完成后可导出完整历史；任务进度可在执行计划中查看。")
            return
        try:
            self.start_job(lambda _: json.dumps(self.store.history(), ensure_ascii=False, indent=2),
                           lambda text: self.save_text(text, "JSON (*.json)", "cloudflare-history.json"), "正在准备历史导出…")
        except Exception as exc:
            self.error(str(exc))

    def closeEvent(self, event):
        if self.busy:
            self.cancel_job()
            self.status.setText("正在安全停止。任务结束后可关闭窗口；已完成的修改保留。")
            event.ignore()
            return
        if self.client:
            self.client.close()
        if self.store:
            self.store.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    configure_app(app)
    if "--self-check" in sys.argv:
        import tempfile
        destination = Path(sys.argv[sys.argv.index("--self-check") + 1])
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            from .extension_setup import prepare_extension
            helper = prepare_extension(Path(temp))
            assert (helper / 'catalog.js').is_file()
            window = Window(Path(temp))
            profile = window.vault.add("Self-check", "FAKE_DIAGNOSTIC_TOKEN", "diagnostic-password-123")
            assert window.vault.token(profile, "diagnostic-password-123") == "FAKE_DIAGNOSTIC_TOKEN"
            window.show()
            def finish():
                window.grab().save(str(destination / "packaged-window.png"))
                (destination / "self-check.json").write_text(json.dumps({"ok": True, "frozen": bool(getattr(sys, "frozen", False)), "forms": window.forms.count(), "encrypted_vault": True, "font_families": len(QFontDatabase.families())}), "utf-8")
                window.close()
                app.quit()
            QTimer.singleShot(200, finish)
            return app.exec()
    # A single instance prevents competing writes and duplicate local job recovery.
    from PySide6.QtCore import QLockFile
    root = local_data_root()
    root.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(root / "application.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.information(None, "CloudDesk", "CloudDesk 已在运行，请使用现有窗口。")
        return 1
    try:
        window = Window(root)
    except Exception as exc:
        QMessageBox.critical(None, "启动失败", f"无法读取本地配置：{exc}")
        return 1
    window.show()
    result = app.exec()
    lock.unlock()
    return result
