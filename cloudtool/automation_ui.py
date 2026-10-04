"""Onboarding presentation; orchestration stays in automation.py."""
import json
from dataclasses import asdict
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QCheckBox, QMessageBox
from .ui_components import card, label, line, combo, button, DomainEditor, AlignedForm, table, number_input
from .table_model import TableModel
from .credentials import Vault
from .gname.client import GnameClient
from .automation_model import WorkflowOptions, parse_sites
from .automation import OnboardingController
from .models import Cancelled


class AutomationPanel(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host, self.plan, self.consumed = host, None, False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.form = QWidget(); body = QVBoxLayout(self.form)
        body.setContentsMargins(0, 0, 0, 0)
        scope, content = card()
        content.addWidget(label('01  域名与目标账户', 'sectionTitle'))
        content.addWidget(label('一次预览，连续完成：创建 / 复用 Zone → DNS → 站点设置 → 修改 NS。'))
        self.domains = DomainEditor(); self.domains.setPlaceholderText('每行一个域名；逐行配对模式填写：example.com,192.0.2.1')
        content.addWidget(self.domains)
        fields = AlignedForm()
        self.account = line('Cloudflare Account ID，32 位十六进制')
        self.registrar = combo([])
        fields.addRow('目标 Account ID', self.account)
        fields.addRow('', button('读取可见 Account ID', host.read_accounts))
        fields.addRow('修改域名 NS', self.registrar)
        content.addLayout(fields)
        content.addWidget(button('刷新 GNAME 账户列表', self.refresh_accounts))
        content.addWidget(label('自动修改 NS 需先在 GNAME 模块添加账户；其他注册商选择手动修改，流程会列出所需 NS。'))
        body.addWidget(scope)
        settings, content = card()
        content.addWidget(label('02  接入配置', 'sectionTitle'))
        fields = AlignedForm()
        self.dns = QCheckBox('添加或更新 DNS'); self.dns.setChecked(True)
        self.mode = combo(['统一解析值', '逐行配对', '循环解析值'])
        self.values = DomainEditor(); self.values.setPlaceholderText('统一模式填一个值；循环模式每行一个值；逐行配对时忽略此框')
        self.hosts = line('@,www'); self.hosts.setText('@,www')
        self.kind = combo(['A', 'AAAA', 'CNAME', 'TXT'])
        self.proxy = QCheckBox('使用 Cloudflare 代理（仅 A / AAAA / CNAME）')
        self.ssl = combo(['保持不变', 'strict', 'full', 'flexible', 'off'])
        self.rewrites = combo(['保持不变', 'on', 'off'])
        self.online = combo(['保持不变', 'on', 'off'])
        for title, widget in [('DNS', self.dns), ('分配方式', self.mode), ('解析值', self.values), ('主机记录', self.hosts), ('记录类型', self.kind), ('代理', self.proxy), ('SSL 模式', self.ssl), ('HTTPS 重写', self.rewrites), ('Always Online', self.online)]:
            fields.addRow(title, widget)
        content.addLayout(fields)
        content.addWidget(label('权限：Zone Edit；配置解析需 DNS Edit；修改设置需 Zone Settings Edit。资源范围必须覆盖目标账户的新 Zone。', 'notice'))
        content.addWidget(label('新 Zone 只配置本页指定的记录，不迁移原有邮件等解析。切换 NS 前请核对完整解析及原注册商 DNSSEC 配置。'))
        templates = QHBoxLayout()
        templates.addWidget(button('保存配置模板', self.save_template))
        templates.addWidget(button('读取配置模板', self.load_template))
        content.addLayout(templates)
        body.addWidget(settings); body.addStretch()
        scroll.setWidget(self.form); layout.addWidget(scroll, 1)
        self.controls = QWidget(); bar = QHBoxLayout(self.controls); bar.setContentsMargins(0, 4, 0, 4)
        self.workers = number_input(1, 8, 2, ' 个')
        self.rate = number_input(0.1, 4, 2, ' 次/秒', decimals=1, width=120)
        bar.addWidget(label('并发域名')); bar.addWidget(self.workers)
        bar.addWidget(label('请求上限')); bar.addWidget(self.rate); bar.addStretch()
        bar.addWidget(button('查看 / 导出明细', self.details))
        bar.addWidget(button('① 生成流程预览', self.preview, True))
        self.run_button = button('② 确认并执行', self.execute, True); bar.addWidget(self.run_button)
        layout.addWidget(self.controls)
        self.status = label('先填写配置并预览；预览只读取信息，不会修改远端。')
        layout.addWidget(self.status)
        self.model = TableModel([('target','域名'), ('summary','步骤'), ('state','状态'), ('detail','结果')])
        self.results = table(self.model); self.results.setMinimumHeight(140); self.results.setMaximumHeight(220)
        self.results.setColumnWidth(0, 180); self.results.setColumnWidth(1, 260)
        self.results.doubleClicked.connect(self.details)
        layout.addWidget(self.results)
        self.refresh_accounts()
        for widget in (self.account, self.hosts): widget.textChanged.connect(self.invalidate)
        for widget in (self.domains, self.values): widget.textChanged.connect(self.invalidate)
        for widget in (self.mode, self.kind, self.registrar, self.ssl, self.rewrites, self.online): widget.currentIndexChanged.connect(self.invalidate)
        for widget in (self.dns, self.proxy): widget.toggled.connect(self.invalidate)
        self.invalidate()

    def refresh_accounts(self):
        selected = self.registrar.currentData()
        self.registrar.clear(); self.registrar.addItem('手动修改 NS（生成操作清单）', '')
        for profile in Vault(self.host.root / 'gname').profiles:
            self.registrar.addItem('GNAME · ' + profile['label'], profile['id'])
        self.registrar.setCurrentIndex(max(0, self.registrar.findData(selected)))

    def invalidate(self, *_):
        self.plan = None; self.run_button.setEnabled(False)
        self.status.setText('参数已更改，请生成流程预览。')

    def reset(self):
        self.invalidate(); self.model.reset([])
        self.domains.clear(); self.values.clear(); self.account.clear()
        self.hosts.setText('@,www'); self.mode.setCurrentIndex(0); self.kind.setCurrentIndex(0)
        self.dns.setChecked(True); self.proxy.setChecked(False)
        for widget in (self.ssl, self.rewrites, self.online, self.registrar): widget.setCurrentIndex(0)

    def set_busy(self, busy):
        self.form.setEnabled(not busy); self.controls.setEnabled(not busy)
        self.run_button.setEnabled(not busy and self.plan is not None and not self.consumed)

    def options(self):
        setting = lambda w: '' if w.currentIndex() == 0 else w.currentText()
        return WorkflowOptions(self.account.text().strip(),
            parse_sites(self.domains.toPlainText(), self.mode.currentText(), self.values.toPlainText(), self.dns.isChecked()),
            tuple(dict.fromkeys(h.strip() for h in self.hosts.text().split(',') if h.strip())),
            self.kind.currentText(), self.dns.isChecked(), self.proxy.isChecked(),
            setting(self.ssl), setting(self.rewrites), setting(self.online), self.registrar.currentData() or '').validate()

    def job(self, options, preview=None):
        registrar = None
        if options.registrar:
            vault = Vault(self.host.root / 'gname')
            profile = next((p for p in vault.profiles if p['id'] == options.registrar), None)
            if profile is None: raise ValueError('GNAME 账户已移除，请重新选择')
            registrar = GnameClient(*json.loads(vault.token(profile)))
        controller = OnboardingController(self.host.client, self.host.store, self.host.provider, registrar)
        task = controller.preview_job(options, self.workers.value()) if preview is None else controller.execute_job(preview, self.workers.value())
        def run(emit):
            try: return task(emit)
            except Cancelled: raise
            except Exception as exc: raise ValueError(controller.safe(exc)) from None
            finally:
                if registrar: registrar.close()
        return run

    def preview(self):
        try:
            self.host.require(); self.invalidate()
            self.host.rate.setValue(self.rate.value())
            self.host.start_job(self.job(self.options()), self.previewed, '正在读取自动化流程所需信息…')
        except Exception as exc: self.host.error(exc)

    def previewed(self, plan):
        self.plan, self.consumed = plan, False
        self.model.reset([dict(id=a.id, target=a.target, summary=a.summary, state='待确认', detail='') for a in plan.steps])
        self.row_by_id = {row['id']: i for i, row in enumerate(self.model.rows)}
        self.status.setText(f'{len(plan.options.sites)} 个域名 · {len(plan.steps)} 个步骤。请查看明细后执行；预览 15 分钟有效。')
        self.host.status.setText('自动化预览完成，尚未修改远端。')

    def execute(self):
        if not self.plan or self.consumed: return
        if QMessageBox.question(self, '执行自动化接入', f'将处理 {len(self.plan.options.sites)} 个域名，可能更新已有 DNS 和站点设置。\n'
            + ('最后会修改 GNAME NS，请确认已准备完整解析及 DNSSEC 配置。' if self.plan.options.registrar else '其他注册商 NS 需按结果手动修改。')
            + '\n单个域名失败会停止其后续步骤，已完成操作不会自动回滚。继续？') != QMessageBox.StandardButton.Yes: return
        try:
            task = self.job(self.plan.options, self.plan)
            self.host.rate.setValue(self.rate.value())
            self.consumed = True
            self.host.start_job(task, self.finished, '自动化接入正在执行…')
        except Exception as exc: self.host.error(exc)

    def consume_events(self, events):
        changed = False
        for aid, (state, detail) in events.items():
            index = getattr(self, 'row_by_id', {}).get(aid)
            if index is not None and index < len(self.model.rows):
                self.model.rows[index].update(state=state, detail=detail); changed = True
        if changed:
            self.model.dataChanged.emit(self.model.index(0, 2), self.model.index(len(self.model.rows)-1, 3))

    def finished(self, _):
        self.host.flush_events()
        counts = {}
        for row in self.model.rows: counts[row['state']] = counts.get(row['state'], 0) + 1
        message = '流程结束 · ' + ' / '.join(f'{key} {value}' for key, value in counts.items())
        self.status.setText(message); self.host.status.setText(message)

    def details(self, *_):
        if not self.plan: return
        self.host.show_json('自动化流程明细', dict(preview=asdict(self.plan), results=self.model.rows))

    def save_template(self):
        try:
            self.host.require()
            data = {name: getattr(self, name).text() for name in ('account', 'hosts')}
            data.update({name: getattr(self, name).currentIndex() for name in ('mode', 'kind', 'ssl', 'rewrites', 'online')})
            data.update(dns=self.dns.isChecked(), proxy=self.proxy.isChecked())
            self.host.store.cache('onboarding_template', data)
            self.status.setText('配置已保存到当前 Token；不保存域名、解析值或注册商凭据。')
        except Exception as exc: self.host.error(exc)

    def load_template(self):
        try:
            self.host.require(); data = self.host.store.cached('onboarding_template', {})
            if not data: raise ValueError('当前 Token 尚未保存配置模板')
            for name in ('account', 'hosts'): getattr(self, name).setText(data[name])
            for name in ('mode', 'kind', 'ssl', 'rewrites', 'online'): getattr(self, name).setCurrentIndex(data[name])
            self.dns.setChecked(data['dns']); self.proxy.setChecked(data['proxy'])
        except Exception as exc: self.host.error(exc)
