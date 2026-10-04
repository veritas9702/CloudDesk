"""Manual-registrar onboarding UI; all network work runs through the host worker."""
from copy import deepcopy
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication, QDialog, QTableWidget, QTableWidgetItem, QMessageBox, QCheckBox
from .ui_components import label, line, combo, button, DomainEditor, table
from .table_model import TableModel
from .automation_model import WorkflowOptions, parse_sites
from .cf_onboarding import CFOnboarding, ns_export


class CFOnboardingPanel(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host, self.plan, self.owner = host, None, None
        layout = QVBoxLayout(self)
        layout.addWidget(label('添加域名 → 核对并导入原 DNS → 导出 NS → 注册商修改 → 检查接入', 'sectionTitle'))
        bar = QHBoxLayout()
        self.accounts = combo([])
        bar.addWidget(label('Cloudflare 账户')); bar.addWidget(self.accounts, 1)
        bar.addWidget(button('读取账户', self.load_accounts))
        self.manual = QCheckBox('手动填写 ID'); bar.addWidget(self.manual)
        self.account_id = line('仅无法读取账户时填写 Account ID'); self.account_id.hide()
        self.manual.toggled.connect(self.account_id.setVisible)
        layout.addLayout(bar); layout.addWidget(self.account_id)
        self.domains = DomainEditor(); self.domains.setPlaceholderText('每行一个域名，例如 example.com；已存在的域名会复用')
        self.domains.setMaximumHeight(130); layout.addWidget(self.domains)
        bar = QHBoxLayout()
        bar.addWidget(button('① 预览添加', self.preview, True))
        self.execute_button = button('② 确认添加并扫描', self.execute, True); bar.addWidget(self.execute_button)
        bar.addWidget(button('刷新接入状态', self.refresh)); bar.addStretch()
        layout.addLayout(bar)
        self.notice = label('添加后自动设置 SSL 灵活。需要 Zone Edit、DNS Edit、Zone Settings Edit；读取账户需要 Account Read。')
        self.notice.setWordWrap(True); layout.addWidget(self.notice)
        self.model = TableModel([('name','域名'), ('state','接入状态'), ('ns','分配的 DNS 服务器'), ('dns','原解析核对'), ('detail','详情')])
        self.results = table(self.model); layout.addWidget(self.results, 1)
        self.results.setColumnWidth(0,180); self.results.setColumnWidth(2,290)
        self.results.doubleClicked.connect(lambda _: self.host.show_json("域名接入详情", self.model.rows[self.results.currentIndex().row()]))
        bar = QHBoxLayout()
        for title, callback in [('核对选中域名 DNS', self.review), ('重新扫描选中域名', self.rescan), ('复制全部 NS', self.copy_ns), ('导出 NS', self.export_ns), ('进入批量配置', self.configure)]:
            bar.addWidget(button(title, callback))
        layout.addLayout(bar)
        text = label('扫描无法保证找全邮件、子域名等记录。请与原服务商逐项核对，补齐后再修改 NS；同时核对原 DNSSEC / DS 配置。NS 格式：域名|ns1,ns2', 'notice')
        text.setWordWrap(True); layout.addWidget(text)
        self.domains.textChanged.connect(self.invalidate)
        self.accounts.currentIndexChanged.connect(self.invalidate)
        self.account_id.textChanged.connect(self.invalidate)
        self.manual.toggled.connect(self.invalidate)
        self.invalidate()

    def controller(self):
        self.host.require()
        return CFOnboarding(self.host.client, self.host.store, self.host.provider)

    def invalidate(self, *_):
        self.plan = None
        self.execute_button.setEnabled(False)

    def reset(self):
        self.owner = None; self.accounts.clear(); self.account_id.clear(); self.domains.clear()
        self.model.reset([]); self.invalidate()

    def activate(self):
        if not self.host.provider or self.host.busy: return
        if self.owner != self.host.client.key:
            self.owner = self.host.client.key
            self.show_rows(self.controller().saved())
            self.load_accounts()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.activate)

    def set_busy(self, busy):
        self.setEnabled(not busy)
        self.execute_button.setEnabled(not busy and self.plan is not None)

    def job(self, fn, done, message):
        try:
            self.host.start_job(fn, done, message)
        except Exception as exc:
            self.host.error(str(exc))

    def load_accounts(self):
        try: controller = self.controller()
        except Exception as exc: self.host.error(str(exc)); return
        self.job(lambda emit: controller.accounts(), self.accounts_loaded, '正在读取 Cloudflare 账户…')

    def accounts_loaded(self, result):
        accounts, warning = result
        previous = self.accounts.currentData()
        self.accounts.clear()
        if len(accounts) != 1: self.accounts.addItem('未读取到可用账户' if not accounts else '请选择目标账户', None)
        for account in accounts: self.accounts.addItem(account.get('name', account['id']), account['id'])
        if previous and self.accounts.findData(previous) >= 0: self.accounts.setCurrentIndex(self.accounts.findData(previous))
        summary = f'账户读取完成：{len(accounts)} 个。'
        selection = '已自动选择唯一账户。' if len(accounts) == 1 else ('请选择域名要加入的 Cloudflare 账户。' if accounts else '')
        self.notice.setText(summary + selection + warning)
        self.host.status.setText(summary + selection + warning)

    def preview(self):
        try:
            controller = self.controller()
            account = self.account_id.text().strip() if self.manual.isChecked() else self.accounts.currentData()
            if not account: raise ValueError('请先读取并选择 Cloudflare 账户')
            options = WorkflowOptions(account, tuple(parse_sites(self.domains.toPlainText(), '统一解析值', '', False)), dns_enabled=False)
            self.job(controller.preview_job(options), self.previewed, '正在检查已有域名并生成接入预览…')
        except Exception as exc: self.host.error(str(exc))

    def previewed(self, plan):
        self.plan = plan
        existing = sum(z is not None for z in plan.zones.values())
        self.notice.setText(f'预览：共 {len(plan.options.sites)} 个域名，复用 {existing} 个，新建 {len(plan.options.sites)-existing} 个。全部设置 SSL 灵活（需 Zone Settings Edit），再扫描原 DNS；扫描结果需另行核对导入。')

    def execute(self):
        if not self.plan: return
        plan = self.plan
        if QMessageBox.question(self, '确认添加域名', self.notice.text() + '\n继续？') != QMessageBox.StandardButton.Yes: return
        controller = self.controller(); self.invalidate()
        self.job(lambda emit: controller.run_onboarding(plan, emit), self.show_rows, '正在添加域名并提交原 DNS 扫描…')

    def show_rows(self, rows):
        self.model.reset([dict(r, ns=', '.join(r.get('name_servers', []))) for r in rows])
        if self.host.busy:
            self.host.status.setText(f'已更新 {len(rows)} 个域名的接入结果；核对 DNS 后可导出 NS。')

    def selected(self):
        index = self.results.currentIndex()
        if not index.isValid(): raise ValueError('请先选择一个域名')
        row = deepcopy(self.model.rows[index.row()]); row.pop('ns', None)
        if not row.get('id'): raise ValueError('该域名尚未添加成功，请重新预览添加')
        return row

    def refresh(self):
        try:
            controller = self.controller(); rows = deepcopy(self.model.rows)
            self.job(lambda emit: controller.refresh(rows), self.show_rows, '正在检查 Cloudflare 接入状态…')
        except Exception as exc:
            self.host.error(str(exc))

    def rescan(self):
        try: row = self.selected(); controller = self.controller()
        except Exception as exc: self.host.error(str(exc)); return
        self.job(lambda emit: controller.trigger(row), lambda _: self.notice.setText('扫描已提交，请稍后点击“核对 DNS”。'), '正在重新提交扫描…')

    def review(self):
        try: row = self.selected(); controller = self.controller()
        except Exception as exc: self.host.error(str(exc)); return
        self.job(lambda emit: controller.review(row), lambda data: QTimer.singleShot(0, lambda: self.review_dialog(row, data)), '正在读取已存在的解析和扫描结果…')

    def review_dialog(self, row, data):
        # Defer until the host worker has released its busy state.
        if self.host.busy:
            QTimer.singleShot(50, lambda: self.review_dialog(row, data)); return
        dialog = QDialog(self); dialog.setWindowTitle(row['name'] + ' · 原 DNS 核对'); dialog.resize(1000,600)
        layout = QVBoxLayout(dialog)
        note = label(f"现有解析 {len(data['existing'])} 条；扫描发现 {len(data['pending'])} 条。扫描仍可能发现新记录，可关闭后再次读取。勾选要导入的记录；未勾选的保留待核对。")
        note.setWordWrap(True); layout.addWidget(note)
        records = [(False,r) for r in data['existing']] + [(True,r) for r in data['pending']]
        grid = QTableWidget(len(records), 6); grid.setHorizontalHeaderLabels(['选择 / 来源','类型','名称','内容 / 数据','TTL','优先级'])
        grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i,(pending,r) in enumerate(records):
            item = QTableWidgetItem('扫描待导入' if pending else '已存在')
            if pending: item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable); item.setCheckState(Qt.CheckState.Unchecked)
            grid.setItem(i,0,item)
            for j,value in enumerate((r.get('type',''),r.get('name',''),r.get('content',r.get('data','')),r.get('ttl',''),r.get('priority','')),1): grid.setItem(i,j,QTableWidgetItem(str(value)))
        grid.resizeColumnsToContents(); layout.addWidget(grid)
        bar = QHBoxLayout()
        def select_all():
            for i,(pending,_) in enumerate(records):
                if pending: grid.item(i,0).setCheckState(Qt.CheckState.Checked)
        bar.addWidget(button('勾选全部扫描记录', select_all))
        def accept():
            selected = [r for i,(pending,r) in enumerate(records) if pending and grid.item(i,0).checkState() == Qt.CheckState.Checked]
            if not selected: return
            if QMessageBox.question(dialog, '确认导入', f'将 {len(selected)} 条勾选记录添加到 Cloudflare？') != QMessageBox.StandardButton.Yes: return
            dialog.accept(); controller = self.controller()
            self.job(lambda emit: controller.accept(row, selected), self.show_rows, '正在导入已核对的 DNS…')
        bar.addWidget(button('导入勾选记录', accept, True)); bar.addWidget(button('关闭',dialog.reject)); layout.addLayout(bar)
        dialog.exec()

    def copy_ns(self):
        text = ns_export(self.model.rows)
        if not text: self.host.error('尚无可导出的 NS，请先添加域名'); return
        QApplication.clipboard().setText(text)
        self.notice.setText('已复制每个域名对应的 NS，可粘贴到注册商批量修改页面。修改前请先核对原解析。')

    def export_ns(self):
        text = ns_export(self.model.rows)
        if not text: self.host.error('尚无可导出的 NS'); return
        self.host.save_text(text, 'Text (*.txt)', 'cloudflare-nameservers.txt')

    def configure(self):
        names = [r['name'] for r in self.model.rows if r.get('id')]
        if not names: self.host.error('请先添加域名'); return
        self.host.scope.setPlainText('\n'.join(dict.fromkeys(names)))
        self.host.nav.setCurrentRow(2)
