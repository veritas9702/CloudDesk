"""GNAME presentation only: collect input, dispatch controller jobs, render results."""
import csv
import json
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QDialog,
    QDialogButtonBox, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox,
    QTabWidget, QScrollArea, QFileDialog, QMessageBox)
from ..credentials import Vault
from ..storage import Store
from ..qt_jobs import Worker
from ..table_model import TableModel
from ..public_ip_ui import PublicIpWidget
from ..ui_components import combo, line, button, label, card, AlignedForm, DomainEditor, table, number_input
from .client import GnameClient, credential
from .controller import GnameController
from .models import MODES, TYPES, parse_records


class AccountDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('添加 GNAME 账户')
        self.resize(620, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(label('在 GNAME 用户中心 → 经销商 → API 设置申请 APPID / APPKEY，启用域名列表、解析列表、添加/删除解析权限；修改 NS 另需域名修改 DNS 权限。', 'notice'))
        form = AlignedForm()
        self.name, self.appid, self.secret = line('本机备注名称'), line('APPID'), line('APPKEY')
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        for title, widget in [('名称', self.name), ('APPID', self.appid), ('APPKEY', self.secret)]:
            form.addRow(title, widget)
        layout.addLayout(form)
        self.ip = PublicIpWidget(self)
        layout.addWidget(self.ip)
        layout.addWidget(label('凭据使用 Windows 本机用户加密，保存在本机 AppData，不随程序复制。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def done(self, result):
        if self.ip.job is not None:
            self.ip.cancel.set()
            self.ip.status.setText('正在停止 IP 检测，请稍后关闭。')
            return
        super().done(result)


class GnamePage(QWidget):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root) / 'gname'
        self.vault = Vault(self.root)
        self.client = self.store = self.controller = self.job = self.plan = None
        self.busy = False
        self.index_by_id = {}
        self.domains_data = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.addWidget(label('GNAME 工作空间', 'heading'))
        account_card, account_layout = card()
        self.account_card = account_card
        row = QHBoxLayout()
        self.accounts = combo([])
        row.addWidget(label('操作账户'))
        row.addWidget(self.accounts, 1)
        row.addWidget(button('添加账户', self.add_account))
        row.addWidget(button('移除配置', self.remove_account))
        row.addWidget(button('读取域名', self.read_domains, True))
        account_layout.addLayout(row)
        account_layout.addWidget(label('APPID / APPKEY 独立保存；切换平台后，本页任务继续运行。'))
        outer.addWidget(account_card)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.build_operations()
        self.build_domains()
        self.build_history()
        self.build_records()
        self.status = label('添加 GNAME 账户后开始使用。')
        outer.addWidget(self.status)
        self.accounts.currentIndexChanged.connect(self.select_account)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flush)
        self.timer.start(100)
        self.reload_accounts()

    def build_operations(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        inputs = QHBoxLayout(content)
        inputs.setSpacing(12)
        inputs.setContentsMargins(0, 0, 0, 0)
        self.input_panel = content
        scope_card, scope = card()
        scope.addWidget(label('01  操作范围', 'sectionTitle'))
        self.operation = combo(['批量添加 DNS', '批量删除 DNS', '批量修改 NS'])
        self.mode = combo(MODES)
        top = QHBoxLayout()
        top.addWidget(self.operation, 1)
        top.addWidget(button('导入文本', self.import_text))
        scope.addLayout(top)
        scope.addWidget(self.mode)
        self.scope = DomainEditor(5)
        scope.addWidget(self.scope)
        self.hint = label('')
        scope.addWidget(self.hint)
        scope.addStretch()
        inputs.addWidget(scope_card, 4)
        settings_card, settings = card()
        settings.addWidget(label('02  记录设置', 'sectionTitle'))
        form = AlignedForm()
        self.host, self.kind = line('@、www、*；多个以逗号分隔'), combo(TYPES)
        self.host.setText('@')
        self.values = DomainEditor(5)
        self.values.setPlaceholderText('记录值；循环分配时每行一个值；修改 NS 时填 NS 主机名')
        self.mx = number_input(1, 50, 5, width=88)
        self.ttl = number_input(1, 600, 600, ' 秒', width=108)
        self.replace = QCheckBox('删除同名同类型及 CNAME 冲突记录（先预览删除明细）')
        host_row = QHBoxLayout()
        host_row.setSpacing(8)
        host_row.addWidget(self.host, 1)
        self.kind.setFixedWidth(100)
        host_row.addWidget(self.kind)
        form.addRow('主机 / 类型', host_row)
        form.addRow('记录值 / NS', self.values)
        small = QHBoxLayout()
        small.setSpacing(10)
        small.addWidget(label('MX 优先级')); small.addWidget(self.mx)
        small.addWidget(label('TTL')); small.addWidget(self.ttl); small.addStretch()
        form.addRow('参数', small)
        settings.addLayout(form)
        settings.addWidget(self.replace)
        settings.addWidget(label('采用 GNAME 默认线路。普通记录 TTL 为 600 秒，MX 可设 1–600 秒。'))
        settings.addStretch()
        inputs.addWidget(settings_card, 6)
        scroll.setWidget(content)
        layout.addWidget(scroll, 3)
        action_card, action_layout = card()
        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.workers = number_input(1, 8, 2, ' 个')
        self.rate = number_input(0.1, 2, 2, ' 次/秒', decimals=1, width=128)
        controls.addWidget(label('并发域名')); controls.addWidget(self.workers)
        controls.addSpacing(12)
        controls.addWidget(label('请求频率')); controls.addWidget(self.rate)
        controls.addStretch()
        self.preview_button = button('① 生成预览', self.preview, True)
        self.execute_button = button('② 确认执行', self.execute_plan, True)
        self.execute_button.setEnabled(False)
        self.cancel_button = button('取消任务', self.cancel_job)
        self.cancel_button.setEnabled(False)
        for widget in (self.preview_button, self.execute_button, self.cancel_button):
            controls.addWidget(widget)
        action_layout.addLayout(controls)
        layout.addWidget(action_card)
        result_card, results = card()
        result_header = QHBoxLayout()
        self.result_title = label("03  执行结果", "sectionTitle")
        result_header.addWidget(self.result_title, 1)
        result_header.addWidget(button("导出结果", lambda: self.export_rows(self.plan_model.rows)))
        self.result_toggle = button("展开", self.toggle_results)
        result_header.addWidget(self.result_toggle)
        results.addLayout(result_header)
        self.plan_model = TableModel([('target','域名'), ('summary','操作明细'), ('state','状态'), ('detail','结果')])
        self.plan_table = table(self.plan_model)
        self.plan_table.setColumnWidth(0, 180); self.plan_table.setColumnWidth(1, 460)
        self.plan_table.setMinimumHeight(150)
        results.addWidget(self.plan_table)
        self.plan_table.hide()
        self.empty_result = label('生成预览后，在这里核对操作明细与执行结果。')
        results.addWidget(self.empty_result)
        layout.addWidget(result_card)
        self.tabs.addTab(page, '批量操作')
        for widget in (self.scope, self.values): widget.textChanged.connect(self.invalidate)
        self.host.textChanged.connect(self.invalidate)
        for widget in (self.mode, self.kind, self.operation): widget.currentIndexChanged.connect(self.form_changed)
        for widget in (self.mx, self.ttl): widget.valueChanged.connect(self.invalidate)
        self.replace.toggled.connect(self.invalidate)
        self.form_changed()

    def toggle_results(self):
        visible = self.plan_table.isHidden()
        self.plan_table.setVisible(visible)
        self.empty_result.setVisible(not visible)
        self.result_toggle.setText('收起' if visible else '展开')

    def build_domains(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.search = line('筛选域名')
        self.search.textChanged.connect(self.filter_domains)
        layout.addWidget(self.search)
        self.domain_model = TableModel([('ym','域名'), ('ztstr','状态'), ('dqsj','到期时间'), ('ymdns','NS')])
        self.domain_table = table(self.domain_model)
        self.domain_table.setColumnWidth(0, 240)
        layout.addWidget(self.domain_table)
        row = QHBoxLayout()
        row.addWidget(button('全选当前结果', self.domain_table.selectAll))
        row.addWidget(button('将选中域名用于批量操作', self.use_domains))
        row.addWidget(button('读取选中域名 DNS', self.read_records))
        row.addWidget(button('导出当前列表', lambda: self.export_rows(self.domain_model.rows)))
        layout.addLayout(row)
        self.tabs.addTab(page, '域名列表 / 导出')

    def build_history(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.history_model = TableModel([('target','域名'), ('path','操作'), ('state','状态'), ('detail','结果')])
        layout.addWidget(table(self.history_model))
        row = QHBoxLayout()
        row.addWidget(button('刷新任务记录', self.history))
        row.addWidget(button('导出任务记录', lambda: self.export_rows(self.history_model.rows)))
        layout.addLayout(row)
        self.tabs.addTab(page, '任务记录')

    def build_records(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.addWidget(label('在域名列表选中域名后点击“读取选中域名 DNS”，可核实执行结果。'))
        self.record_model = TableModel([('ym','域名'), ('zjt','主机记录'), ('lx','类型'), ('jxz','记录值'), ('xlid','线路'), ('id','记录 ID')])
        layout.addWidget(table(self.record_model))
        layout.addWidget(button('导出 DNS 记录', lambda: self.export_rows(self.record_model.rows)))
        self.tabs.addTab(page, 'DNS 记录')

    def read_records(self):
        if self.busy or not self.controller: return
        names = [self.domain_model.rows[i.row()]['ym'] for i in self.domain_table.selectionModel().selectedRows()]
        try:
            self.start_job(self.controller.inspect_job('\n'.join(names), self.workers.value()), self.show_records)
        except Exception as exc: self.error(exc)

    def show_records(self, rows):
        self.record_model.reset(rows)
        self.tabs.setCurrentIndex(3)
        self.status.setText(f'已读取 {len(rows)} 条 DNS 记录')

    def error(self, exc):
        QMessageBox.warning(self, 'GNAME', self.client.safe(exc) if self.client else str(exc))

    def form_changed(self):
        adding = self.operation.currentIndex() == 0
        dns = self.operation.currentIndex() != 2
        self.mode.setEnabled(adding)
        self.kind.setEnabled(dns); self.host.setEnabled(dns)
        self.replace.setEnabled(adding)
        self.mx.setEnabled(adding)
        self.ttl.setEnabled(adding)
        self.values.setEnabled(self.operation.currentIndex() == 2 or (adding and self.mode.currentIndex() in (0, 3)))
        hints = ['每行一个域名，所有域名使用相同记录值。',
                 '每行：域名|主机记录|类型|记录值|MX优先级（可选）；例如 example.com|www,@|A|192.0.2.1',
                 '每行：域名,记录值；主机记录和类型使用下面的设置。',
                 '每行一个域名；下面每行一个记录值，按顺序循环分配。']
        self.hint.setText(hints[self.mode.currentIndex()] if adding else '每行一个域名；删除使用精确主机记录及类型，修改 NS 使用下面的 NS 主机名。')
        self.scope.setPlaceholderText('example.com\nexample.net\nexample.org' if not adding or self.mode.currentIndex() in (0, 3) else '在此粘贴批量记录…')
        self.invalidate()

    def invalidate(self):
        self.plan = None
        self.execute_button.setEnabled(False)

    def reload_accounts(self):
        self.accounts.blockSignals(True)
        self.accounts.clear()
        for p in self.vault.profiles: self.accounts.addItem(p['label'], p['id'])
        self.accounts.blockSignals(False)
        self.select_account()

    def select_account(self):
        if self.busy: return
        if self.client: self.client.close()
        if self.store: self.store.close()
        self.client = self.store = self.controller = None
        self.invalidate(); self.plan_model.reset([]); self.history_model.reset([])
        self.record_model.reset([])
        self.result_title.setText("03  执行结果")
        self.plan_table.hide()
        self.empty_result.show()
        self.result_toggle.setText("展开")
        self.domains_data = []; self.filter_domains()
        index = self.accounts.currentIndex()
        if index < 0: return
        try:
            appid, appkey = json.loads(self.vault.token(self.vault.profiles[index]))
            self.client = GnameClient(appid, appkey)
            self.store = Store(self.root, self.client.key)
            self.controller = GnameController(self.client, self.store)
            self.status.setText('已选择独立 GNAME 账户；读取域名或填写批量记录。')
        except Exception as exc:
            self.error(exc)

    def add_account(self):
        dialog = AccountDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        try:
            secret = credential(dialog.appid.text(), dialog.secret.text())
            self.vault.add(dialog.name.text(), secret)
            self.reload_accounts()
            self.accounts.setCurrentIndex(self.accounts.count() - 1)
        except Exception as exc: self.error(exc)
        finally: dialog.secret.clear(); dialog.deleteLater()

    def remove_account(self):
        key = self.accounts.currentData()
        if key and QMessageBox.question(self, '移除配置', '移除本机 GNAME 凭据？远端账户不受影响。') == QMessageBox.StandardButton.Yes:
            try: self.vault.remove(key); self.reload_accounts()
            except Exception as exc: self.error(exc)

    def start_job(self, function, callback):
        if self.busy: return
        if not self.client:
            self.error('请先添加并选择 GNAME 账户'); return
        self.client.cancel.clear()
        self.client.limiter.rate = self.rate.value()
        self.busy = True
        self.account_card.setEnabled(False); self.input_panel.setEnabled(False)
        self.preview_button.setEnabled(False); self.execute_button.setEnabled(False)
        self.workers.setEnabled(False); self.rate.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText('后台处理中，可切换到 Cloudflare 继续操作…')
        self.job = Worker(function, self.client.safe)
        self.job.result.connect(callback)
        self.job.failure.connect(self.status.setText)
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def job_finished(self):
        self.flush()
        self.job.deleteLater(); self.job = None; self.busy = False
        self.account_card.setEnabled(True); self.input_panel.setEnabled(True)
        self.preview_button.setEnabled(True); self.cancel_button.setEnabled(False)
        self.workers.setEnabled(True); self.rate.setEnabled(True)
        self.execute_button.setEnabled(bool(self.plan and self.plan.actions))
        if self.status.text().startswith('后台处理中'):
            self.status.setText('读取完成。')

    def flush(self):
        if not self.job: return
        events = self.job.take_events()
        for aid, (state, detail) in events.items():
            i = self.index_by_id.get(aid)
            if i is not None:
                self.plan_model.rows[i].update(state=state, detail=detail)
                self.plan_model.dataChanged.emit(self.plan_model.index(i, 2), self.plan_model.index(i, 3))

    def preview(self):
        if not self.controller: self.error('请先添加账户'); return
        try:
            self.invalidate()
            op = self.operation.currentIndex()
            if op == 0:
                records = parse_records(self.scope.toPlainText(), self.mode.currentText(), self.host.text(),
                                        self.kind.currentText(), self.values.toPlainText(), self.mx.value(), self.ttl.value())
                job = self.controller.preview_job(records, self.replace.isChecked(), self.workers.value())
            elif op == 1:
                job = self.controller.delete_job(self.scope.toPlainText(), self.host.text(), self.kind.currentText(), self.workers.value())
            else:
                job = self.controller.ns_job(self.scope.toPlainText(), self.values.toPlainText())
            self.start_job(job, self.show_plan)
        except Exception as exc: self.error(exc)

    def show_plan(self, plan):
        self.plan = plan
        self.result_title.setText(f'03  执行计划 · {len(plan.actions)} 个请求')
        self.plan_table.setVisible(bool(plan.actions))
        self.empty_result.setVisible(not plan.actions)
        self.result_toggle.setText('收起' if plan.actions else '展开')
        self.index_by_id = {a.id: i for i, a in enumerate(plan.actions)}
        self.plan_model.reset([dict(target=a.target, summary=a.summary, state='待确认', detail='') for a in plan.actions])
        self.status.setText(f'预览完成：{len(plan.actions)} 个请求。请核对明细后确认执行。' if plan.actions else '没有需要执行的变更；已存在的相同记录已跳过。')

    def execute_plan(self):
        if self.busy or not self.plan: return
        if QMessageBox.question(self, '确认 GNAME 变更', f'即将执行 {len(self.plan.actions)} 个请求，包含预览中列出的删除或修改。继续？') != QMessageBox.StandardButton.Yes:
            return
        job = self.controller.execute_job(self.plan, self.workers.value())
        self.plan = None
        self.start_job(job, lambda _: self.status.setText('任务已结束，请检查每条结果；失败或结果未知请先核实远端。'))

    def cancel_job(self):
        if self.client: self.client.cancel.set()
        self.status.setText('正在停止调度；已发送的请求会返回后结束。')

    def read_domains(self):
        if self.controller: self.start_job(lambda _: self.controller.domains(), self.show_domains)
        else: self.error('请先添加账户')

    def show_domains(self, rows):
        self.domains_data = rows; self.filter_domains()
        self.status.setText(f'已读取 {len(rows)} 个域名')
        self.tabs.setCurrentIndex(1)

    def filter_domains(self):
        text = self.search.text().strip().lower()
        self.domain_model.reset([r for r in self.domains_data if text in r.get('ym', '').lower()])

    def use_domains(self):
        if self.busy: return
        names = [self.domain_model.rows[i.row()]['ym'] for i in self.domain_table.selectionModel().selectedRows()]
        self.mode.setCurrentIndex(0)
        self.scope.setPlainText('\n'.join(names)); self.tabs.setCurrentIndex(0)

    def history(self):
        if self.store and not self.busy:
            self.start_job(lambda _: self.store.history(include_payload=False), self.history_model.reset)

    def import_text(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入批量文本', '', '文本 (*.txt *.csv);;所有文件 (*)')
        if path:
            try:
                if Path(path).stat().st_size > 10 * 1024 * 1024: raise ValueError('单次导入上限 10 MB')
                self.scope.setPlainText(Path(path).read_text('utf-8-sig'))
            except Exception as exc: self.error(exc)

    def export_rows(self, rows):
        if not rows: return
        path, _ = QFileDialog.getSaveFileName(self, '导出', 'gname.csv', 'CSV (*.csv)')
        if path:
            try:
                keys = list(rows[0])
                with open(path, 'w', encoding='utf-8-sig', newline='') as output:
                    writer = csv.writer(output); writer.writerow(keys)
                    for row in rows:
                        values = [str(row.get(k, '')) for k in keys]
                        writer.writerow(["'" + v if v.startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in values])
            except Exception as exc: self.error(exc)

    def closeEvent(self, event):
        if self.busy:
            self.cancel_job(); event.ignore(); return
        self.timer.stop()
        if self.client: self.client.close()
        if self.store: self.store.close()
        event.accept()
