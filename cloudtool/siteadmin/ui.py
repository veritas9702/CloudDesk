"""Site workspace view; credentials, API and workflow rules live in their own layers."""
import json
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QDialog, QDialogButtonBox,
    QLineEdit, QCheckBox, QMessageBox, QFileDialog, QTabWidget, QPlainTextEdit, QHeaderView, QInputDialog, QApplication)
from ..ui_components import card, label, line, combo, button, AlignedForm, DomainEditor, table, number_input
from ..credentials import Vault
from ..storage import Store
from ..table_model import TableModel
from ..workspace_jobs import WorkspaceJobs
from .models import Credentials, parse_sites
from .client import SiteClient
from .controller import SiteController
from .template_usage import TemplateUsage
from .template_workflow import TemplateWorkflow
from .recovery import RecoveryController, LABELS
from .template_management import TemplateManagement
from .template_panel import TemplatePanel
from .pipeline_store import PipelineStore
from .pipeline import SitePipeline
from .pipeline_api import STAGES, TITLES
from .site_catalog import SiteCatalog, domain_lines, imported_sites, site_visit_url
from .site_table import SiteTableModel
from .rebuild import RebuildWorkflow


class AccountDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent); self.setWindowTitle('添加站点后台'); self.resize(580, 370)
        layout = QVBoxLayout(self); form = AlignedForm()
        self.name = line('本机备注'); self.url = line('https://后台地址 或 http://IP')
        self.username = line('管理员账号'); self.password = line('密码')
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        for title, field in [('名称', self.name), ('后台地址', self.url), ('账号', self.username), ('密码', self.password)]: form.addRow(title, field)
        layout.addLayout(form)
        layout.addWidget(label('账号密码使用 Windows 本机用户加密；登录会话仅在内存中保存。复制程序不会携带账户。'))
        layout.addWidget(label('支持截图中的 SSM 静态站点群管理台。HTTP 地址会明文传输账号密码，建议后台启用 HTTPS。', 'notice'))
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept); controls.rejected.connect(self.reject); layout.addWidget(controls)


class SitePage(QWidget):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root); self.vault = Vault(self.root)
        self.usage = TemplateUsage(self.root)
        self.pipeline_store = PipelineStore(self.root)
        self.client = self.store = self.controller = self.plan = self.job = None
        self.busy = False; self.index_by_id = {}; self.pending_tab = False
        self.all_sites=[];self.auto_sites_text=None;self.imported_sites={}
        layout = QVBoxLayout(self); layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(label('站点后台 · 批量建站', 'heading'))
        self.account_card, content = card(); bar = QHBoxLayout()
        self.accounts = combo([]); bar.addWidget(label('操作后台')); bar.addWidget(self.accounts, 1)
        bar.addWidget(button('添加后台', self.add_account)); bar.addWidget(button('移除配置', self.remove_account))
        bar.addWidget(button('打开后台网页', self.open_browser)); content.addLayout(bar)
        self.identity = label('任务通过接口自动登录；“打开后台网页”使用浏览器自己的登录会话。'); content.addWidget(self.identity)
        layout.addWidget(self.account_card)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs, 1)
        work = QWidget(); body = QVBoxLayout(work); body.setContentsMargins(0, 6, 0, 0)
        self.input_card, content = card()
        columns=QHBoxLayout(); left=QVBoxLayout(); right=QVBoxLayout()
        domain_bar=QHBoxLayout();domain_title=label('01  域名 · 每行一个', 'sectionTitle');domain_title.setFixedHeight(26);domain_bar.addWidget(domain_title)
        domain_bar.addStretch();self.auto_fill=QCheckBox('自动填充未发布');self.auto_fill.setChecked(True);domain_bar.addWidget(self.auto_fill)
        self.fill_button=button('填入未发布',lambda:self.read_sites(True));domain_bar.addWidget(self.fill_button);left.addLayout(domain_bar)
        self.domains=DomainEditor(); self.domains.setPlaceholderText('example.com\nexample.net')
        left.addWidget(self.domains)
        template_title=label('02  模板与站点设置', 'sectionTitle');template_title.setFixedHeight(26);right.addWidget(template_title)
        self.with_template=QCheckBox('上传模板（支持已有空站点）→ 同步 → 扫描'); right.addWidget(self.with_template)
        self.with_pipeline=QCheckBox('TDK → 转换 → 清理 → 外链 → H1 → 占位符 → 发布')
        self.with_pipeline.setToolTip('新站可同时勾选上传模板；已有模板会跳过上传。先固定 TDK，六步全部成功后发布上线；失败不发布。')
        row=QHBoxLayout(); self.template_root=line('模板父目录（包含多个站点文件夹）')
        row.addWidget(self.template_root,1); self.choose_button=button('选择目录',self.choose_templates); row.addWidget(self.choose_button); right.addLayout(row)
        row=QHBoxLayout(); self.wildcard=QCheckBox('泛域名 *.域名'); self.wildcard.setChecked(True)
        self.protocol=combo(['https','http']); row.addWidget(self.wildcard); row.addStretch(); row.addWidget(label('外链协议'));row.addWidget(self.protocol);right.addLayout(row)
        right.addWidget(self.with_pipeline)
        columns.addLayout(left,1);columns.addLayout(right,1);content.addLayout(columns)
        self.config_scroll=self.input_card;body.addWidget(self.input_card)
        self.config_summary = label('填写域名 → 预览分配 → 确认执行；失败后可恢复未完成流程。')
        body.addWidget(self.config_summary)
        self.toolbar = QWidget(); row = QHBoxLayout(self.toolbar); row.setContentsMargins(0, 4, 0, 4)
        self.workers = number_input(1, 4, 1, ' 个'); self.rate = number_input(.1, 4, 2, ' 次/秒', decimals=1, width=120)
        row.addWidget(label('并发站点')); row.addWidget(self.workers); row.addWidget(label('请求上限')); row.addWidget(self.rate); row.addStretch()
        self.config_toggle=button('收起配置',self.toggle_config);row.addWidget(self.config_toggle)
        row.addWidget(button('① 登录并预览', self.preview, True))
        self.execute_button = button('② 确认执行', self.execute_plan, True); row.addWidget(self.execute_button)
        body.addWidget(self.toolbar)
        self.plan_model = TableModel([('target','域名'), ('summary','操作'), ('state','状态'), ('progress','进度'), ('detail','结果')], centered=True)
        self.plan_table = table(self.plan_model); self.plan_table.setColumnWidth(0,220); self.plan_table.setColumnWidth(1,300); self.plan_table.setColumnWidth(2,90); self.plan_table.setColumnWidth(3,90)
        result_bar = QHBoxLayout(); result_title=label('执行步骤', 'sectionTitle'); result_title.setWordWrap(False); result_bar.addWidget(result_title); result_bar.addStretch()
        self.auto_rebuild=QCheckBox('失败自动重建一次');self.toolbar.layout().insertWidget(4,self.auto_rebuild)
        self.recover_button = button('重试 / 恢复未完成流程', self.recover)
        result_bar.addWidget(button('结果汇总 / 处理失败', self.show_batch_result))
        result_bar.addWidget(button('核对 TDK', self.show_tdk))
        result_bar.addWidget(button('核对加工任务 ID', self.attach_pipeline_task))
        result_bar.addWidget(self.recover_button)
        result_bar.addWidget(button('导出结果', lambda: self.export(self.plan_model.rows)))
        body.addLayout(result_bar); self.plan_table.setMinimumHeight(150); body.addWidget(self.plan_table, 1)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(72)
        self.details.setPlaceholderText('失败原因和处理建议会显示在这里，也可点击任一步骤查看详情。')
        body.addWidget(self.details)
        self.plan_table.selectionModel().currentRowChanged.connect(lambda *_: self.show_detail())
        self.tabs.addTab(work, '批量建站')
        self.sites_model=SiteTableModel([('id','ID'),('code','编码'),('name','名称'),('primary_domain','主域名 ↗'),('page_count','页面数'),('publication','发布状态'),('binding','本机模板'),('link_protocol','协议')],centered=True)
        self.history_model=TableModel([('time','时间'),('target','域名'),('operation','步骤'),('state','状态'),('detail','结果')],centered=True)
        for title,model,callback in [('站点列表',self.sites_model,self.read_sites),('任务记录',self.history_model,self.read_history)]:
            page=QWidget();column=QVBoxLayout(page);column.setContentsMargins(0,6,0,0)
            bar=QHBoxLayout();hint=label('点击主域名访问 www；发布状态以后台为准' if model is self.sites_model else '本机账户独立保存执行记录；打开此页自动读取。');hint.setWordWrap(False);bar.addWidget(hint)
            bar.addStretch(); refresh = button('加载站点' if model is self.sites_model else '刷新记录',callback); bar.addWidget(refresh)
            if model is self.sites_model: self.load_sites_button = refresh
            else: self.refresh_history_button = refresh
            if model is self.sites_model:
                self.assign_button=button('分配模板',self.assign_template,True);bar.addWidget(self.assign_button)
                self.resume_button=button('继续 / 恢复',self.resume_selected);bar.addWidget(self.resume_button)
                self.process_button=button('加工并发布',self.process_selected);bar.addWidget(self.process_button)
                self.copy_domains_button=button('复制全部域名',self.copy_domains);bar.addWidget(self.copy_domains_button)
            bar.addWidget(button('导出',lambda checked=False,m=model:self.export(m.rows)));column.addLayout(bar)
            if model is self.sites_model:
                self.assignment_notice=label('选择具体模板文件夹后，会校验占用状态并生成预览。','notice');column.addWidget(self.assignment_notice)
            view=table(model);view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);column.addWidget(view,1)
            if model is self.sites_model:
                self.sites_table=view
                view.clicked.connect(self.visit_site)
                view.selectionModel().currentRowChanged.connect(lambda *_:self.update_site_actions())
            else:
                self.history_table=view;self.history_details=QPlainTextEdit();self.history_details.setReadOnly(True);self.history_details.setMaximumHeight(90)
                column.addWidget(self.history_details);view.selectionModel().currentRowChanged.connect(self.show_history_detail)
            self.tabs.addTab(page,title)
        self.template_panel=TemplatePanel(self.read_templates,self.release_template,self.recover)
        self.tabs.addTab(self.template_panel,'模板管理')
        row = QHBoxLayout(); self.status = label('添加后台账号，填写域名后生成预览。'); row.addWidget(self.status,1)
        self.cancel_button = button('取消任务', lambda: None); self.cancel_button.setEnabled(False); row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.jobs = WorkspaceJobs(self, [self.account_card,self.input_card,self.toolbar,self.template_panel], self.cancel_button,self.status,self.consume)
        self.accounts.currentIndexChanged.connect(self.select_account)
        self.domains.textChanged.connect(self.invalidate); self.wildcard.toggled.connect(self.invalidate); self.protocol.currentIndexChanged.connect(self.invalidate)
        self.with_template.toggled.connect(self.invalidate);self.template_root.textChanged.connect(self.invalidate)
        self.with_pipeline.toggled.connect(self.invalidate)
        self.auto_rebuild.toggled.connect(self.invalidate)
        self.tabs.currentChanged.connect(self.load_tab)
        self.reload_accounts()

    def error(self, error): QMessageBox.warning(self, '操作提示', self.client.safe(error) if self.client else str(error))
    def update_actions(self):
        self.execute_button.setEnabled(not self.busy and bool(self.plan and self.plan.actions))
        self.recover_button.setEnabled(not self.busy and self.client is not None)
        self.update_site_actions()
        self.load_sites_button.setEnabled(not self.busy and self.controller is not None)
        self.load_sites_button.setText('处理中…' if self.busy else '加载站点')
        self.refresh_history_button.setEnabled(not self.busy and self.store is not None)
        self.fill_button.setEnabled(not self.busy and self.client is not None)
        self.auto_rebuild.setEnabled(not self.busy)
        self.copy_domains_button.setEnabled(not self.busy and bool(self.all_sites))
        if not self.busy and self.pending_tab:
            self.pending_tab=False
            QTimer.singleShot(0,lambda:self.load_tab(self.tabs.currentIndex()))
    def invalidate(self, *_):
        self.plan = None
        self.config_summary.setText('配置已修改，请重新预览；下方保留上次结果。勾选上传模板可为已有空站点补配模板。')
        self.update_actions()

    def reload_accounts(self, selected=None):
        self.accounts.blockSignals(True); self.accounts.clear()
        for profile in self.vault.profiles: self.accounts.addItem(profile['label'], profile['id'])
        if selected: self.accounts.setCurrentIndex(self.accounts.findData(selected))
        self.accounts.blockSignals(False); self.select_account()

    def select_account(self, *_):
        if getattr(self, 'result_dialog', None): self.result_dialog.close()
        if self.busy: return
        if self.client: self.client.close()
        if self.store: self.store.close()
        self.client = self.store = self.controller = None
        self.all_sites=[];self.auto_sites_text=None;self.imported_sites={}
        self.invalidate(); self.domains.clear(); self.index_by_id = {}
        self.with_template.setChecked(False);self.with_pipeline.setChecked(False);self.auto_rebuild.setChecked(False);self.template_root.clear()
        self.config_scroll.setVisible(True);self.config_toggle.setText('收起配置'); self.details.clear()
        for model in (self.plan_model, self.sites_model, self.history_model): model.reset([])
        self.template_panel.show_rows([])
        self.history_details.clear()
        self.assignment_notice.setText('选择具体模板文件夹后，会校验占用状态并生成预览。')
        self.identity.setText('选择后台后自动登录；账户数据彼此隔离。')
        key = self.accounts.currentData()
        if not key: return
        try:
            profile = next(p for p in self.vault.profiles if p['id'] == key)
            credentials = Credentials.decode(self.vault.token(profile))
            self.client = SiteClient(credentials); self.store = Store(self.root, key)
            self.controller = SiteController(self.client,self.store)
            self.identity.setText(f'{credentials.url} · {credentials.username} · 接口自动登录 / 浏览器会话独立')
            self.update_actions()
            self.load_tab(self.tabs.currentIndex())
        except Exception as exc: self.error(exc)

    def add_account(self):
        dialog = AccountDialog(self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted: return
            credentials = Credentials(dialog.url.text(),dialog.username.text(),dialog.password.text())
            profile = self.vault.add(dialog.name.text(), credentials.encode())
            self.reload_accounts(profile['id'])
        except Exception as exc: self.error(exc)
        finally: dialog.password.clear(); dialog.deleteLater()

    def remove_account(self):
        key = self.accounts.currentData()
        if key and QMessageBox.question(self,'移除本机配置','只移除本机保存的凭据，不删除远端站点。继续？') == QMessageBox.StandardButton.Yes:
            try: self.vault.remove(key); self.reload_accounts()
            except Exception as exc: self.error(exc)

    def open_browser(self):
        if self.client: QDesktopServices.openUrl(QUrl(self.client.credentials.url + '/sites'))
        else: self.error('请先添加后台')

    def start(self, function, done, failed=None):
        if self.busy:
            self.status.setText('已有任务正在处理，请查看当前进度；可取消后重试。')
            return
        if not self.client: self.error('请先添加后台'); return
        self.client.limiter.rate = self.rate.value()
        try: self.jobs.start(function,done,failed)
        except Exception as exc: self.error(exc)

    def preview(self):
        if not self.controller: self.error('请先添加后台'); return
        try:
            self.invalidate()
            if self.auto_rebuild.isChecked() and (not self.with_pipeline.isChecked() or not self.template_root.text().strip()):
                raise ValueError('自动重建需勾选六步加工，并选择含备用模板的父目录')
            sites=parse_sites(self.domains.toPlainText(),self.wildcard.isChecked(),self.protocol.currentText())
            sites=tuple(self.imported_sites.get(site.code,site) for site in sites)
            self.index_by_id={}
            self.plan_model.reset([dict(target=site.code,summary='准备预览',state='等待',progress='—',detail='等待后台检查') for site in sites])
            self.config_summary.setText(f'正在逐域名预览：{len(sites)} 个域名；模板按需校验，预览不修改后台。')
            if self.with_pipeline.isChecked():
                if self.with_template.isChecked() and not self.template_root.text().strip(): raise ValueError('请选择模板父目录')
                job=SitePipeline(self.client,self.store,self.usage,self.pipeline_store).preview_job(
                    sites,self.template_root.text().strip(),self.with_template.isChecked())
            elif self.with_template.isChecked():
                if not self.template_root.text().strip(): raise ValueError('请选择模板父目录')
                job=TemplateWorkflow(self.client,self.store,self.usage).preview_job(sites,self.template_root.text().strip())
            else: job=self.controller.preview_job(sites)
            if self.auto_rebuild.isChecked():
                original_job=job;root=self.template_root.text().strip()
                def job(emit):
                    result=original_job(emit)
                    if not result[0].actions and result[1]:
                        return RebuildWorkflow(self.client,self.store,self.usage,self.pipeline_store).preview_job([r['target'] for r in result[1]],root)(emit)
                    return result
            self.start(job,self.show_plan,self.preview_failed)
        except Exception as exc: self.error(exc)

    def preview_failed(self, message):
        self.jobs.flush()
        self.plan = None
        for row in self.plan_model.rows:
            if row.get('summary') == '准备预览':
                row.update(state='未生成计划',detail=message)
        self.plan_model.reset(self.plan_model.rows)
        self.config_summary.setText('预览未完成，尚未执行后台修改；请根据下方原因重试。')
        self.status.setText(message)

    def show_plan(self, result):
        self.jobs.flush()  # Drain provisional domain events before installing final action rows.
        self.plan, skipped = result
        self.index_by_id = {a.id:i for i,a in enumerate(self.plan.actions)}
        def detail(action):
            data=action.body
            if action.method=='REBUILD':return f"删除旧站点 ID {data['old_id']} 后使用替换模板：{data['template']['path']}；只重建一次，TDK 保留"
            if action.method=='PIPELINE':
                if action.path=='tdk':
                    return '已保存分配 · Title：'+data['tdk']['title']+' · Description：'+data['tdk']['description']+' · Keywords：'+data['tdk']['keywords']
                if action.path=='publish':
                    return '六步全部成功后校验工作副本并异步发布上线；已发布步骤跳过，结果未知仅核对原任务'
                return '仅在前置步骤成功后执行；预览 / 检测通过后异步处理全站，重试保留 TDK 与已完成步骤'
            if action.method=='WORKFLOW':
                return f"模板：{data['template']['path']} → {data['site']['primary_domain']} · {data['site']['link_protocol']}"
            return f"编码 / 名称：{data['code']} · 主域名：{data['primary_domain']} · {data['link_protocol']}"
        self.plan_model.reset([dict(action_id=a.id,target=a.target,summary=a.summary,stage=a.path,progress="—",state='待确认',detail=detail(a)) for a in self.plan.actions] + skipped)
        self.config_summary.setText(f'当前计划：{len({a.target for a in self.plan.actions})} 个站点 · {len(self.plan.actions)} 个步骤 · 已完成步骤在执行时自动跳过')
        self.status.setText(f'预览完成：{len({a.target for a in self.plan.actions})} 个站点 / {len(self.plan.actions)} 个步骤，跳过 {len(skipped)} 个。请核对模板分配后执行。')

    def execute_plan(self):
        if self.busy or not self.plan or not self.plan.actions: return
        workflow=self.plan.actions[0].method=='WORKFLOW'
        processing=any(a.method=='PIPELINE' for a in self.plan.actions)
        rebuilding=any(a.method=='REBUILD' for a in self.plan.actions)
        note='将上传分配的模板、解压、替换工作目录并扫描。已有空站点会复用。' if workflow else '已有站点不会覆盖。'
        if processing:
            note=('将处理工作副本：先应用已分配 TDK，再转换（保留 TDK）、安全清理统计代码、改写外链、注入 H1 和占位符。'
                  '\n六步全部成功后自动发布上线；已有模板跳过上传。取消只停止客户端调度，已提交后台任务继续并保留 ID。')
        if rebuilding or processing and self.auto_rebuild.isChecked():
            note+='\n已启用一次重建：会删除失败的未发布站点及远端目录，换用其他通过预检的本地模板，重新创建并执行全部流程。第二次失败停止，导出报告人工处理。'
        if rebuilding:
            note+='\n重建站点六步加工全部成功后发布上线。'
        if QMessageBox.question(self,'确认工作流',f'在 {self.client.credentials.url} 执行 {len(self.plan.actions)} 个步骤？\n{note}\n已完成操作不会自动回滚。') != QMessageBox.StandardButton.Yes: return
        recovery=RebuildWorkflow(self.client,self.store,self.usage,self.pipeline_store)
        controller=recovery if rebuilding else (SitePipeline(self.client,self.store,self.usage,self.pipeline_store) if processing else (TemplateWorkflow(self.client,self.store,self.usage) if workflow else self.controller))
        job = controller.execute_job(self.plan,self.workers.value())
        if processing and self.auto_rebuild.isChecked():
            job=recovery.after_job(job,[r['target'] for r in self.plan_model.rows if r['state']=='需处理'],self.template_root.text().strip(),self.workers.value())
        self.plan = None
        def done(_):
            self.jobs.flush()
            outcomes=self.batch_outcomes()
            success=sum(r['state']=='成功' for r in outcomes)
            message=f'执行结束：{len(outcomes)} 个域名，成功 {success}，需处理 {len(outcomes)-success}。单个域名失败不影响其余域名。'
            self.status.setText(message);self.config_summary.setText(message)
            if any(r['state']!='成功' for r in outcomes):self.show_batch_result()
        self.start(job, done)

    def batch_outcomes(self):
        groups={}
        for row in self.plan_model.rows:groups.setdefault(row['target'],[]).append(row)
        result=[]
        for target,rows in groups.items():
            issue=next((r for r in rows if r['state'] in ('失败','结果未知','需处理')),None)
            if issue is None:issue=next((r for r in rows if r['state'] not in ('成功','已跳过')),None)
            result.append(dict(target=target,state=issue['state'] if issue else '成功',
                               detail=(issue.get('summary','')+'：'+issue.get('detail','')) if issue else '全部步骤已完成或已跳过'))
            if issue and self.client and self.pipeline_store.rebuild(self.client.key,target):
                result[-1]['detail']+='\n已使用一次重建机会；不再自动重建，请导出报告人工处理。'
        return result

    def show_batch_result(self):
        outcomes=self.batch_outcomes()
        if not outcomes:return
        if getattr(self, 'result_dialog', None): self.result_dialog.close()
        dialog=QDialog(self);dialog.setWindowTitle('批次结果 · 按域名处理');dialog.resize(850,480)
        layout=QVBoxLayout(dialog)
        info=QPlainTextEdit();info.setReadOnly(True)
        info.setPlainText('\n\n'.join(f"{r['target']} · {r['state']}\n{r['detail']}" for r in outcomes))
        layout.addWidget(info)
        failures=[r for r in outcomes if r['state']!='成功']
        if failures:
            targets=combo([r['target'] for r in failures]);layout.addWidget(targets)
            hint=label('');layout.addWidget(hint)
            bar=QHBoxLayout()
            recover=button('恢复原模板流程',lambda:self.recover(targets.currentText()))
            replace=button('另选模板并预览',lambda:self.reassign_target(targets.currentText()))
            def changed():
                bound=next((e for e in self.usage.rows() if e['owner']==self.client.key and e['target']==targets.currentText()),None)
                recover.setEnabled(bool(bound) and bound['stage'] in LABELS)
                replace.setEnabled(not bound)
                hint.setText('已上传或已绑定：先核实并恢复原步骤；注入失败无需重新上传。' if bound else '尚未上传或绑定已释放：可以选择较小模板，核对空站点后重新预览。')
            targets.currentIndexChanged.connect(changed);changed()
            bar.addWidget(recover);bar.addWidget(replace);layout.addLayout(bar)
            if any(r.get('stage') in STAGES for r in self.plan_model.rows):
                def resume_processing():
                    if self.busy:return
                    self.domains.setPlainText('\n'.join(r['target'] for r in failures))
                    self.with_pipeline.setChecked(True)
                    dialog.close();self.preview()
                layout.addWidget(button('重新预览未完成六步（保留 TDK）',resume_processing))
            layout.addWidget(button('失败站点换模板重建一次（先预览）',lambda:self.preview_rebuild([r['target'] for r in failures],dialog)))
        layout.addWidget(button('导出汇总',lambda:self.export(outcomes)))
        layout.addWidget(button('关闭',dialog.close))
        dialog.setModal(False);dialog.show()
        self.result_dialog=dialog

    def reassign_target(self,target):
        if self.busy:return
        def ready(rows):
            matches=[r for r in rows if r['code']==target]
            if len(matches)!=1:
                self.error('未找到唯一的已建站点，请在批量建站页填写该域名并选择模板重新预览。');return
            self.sites_model.reset(matches);self.sites_table.selectRow(0)
            QTimer.singleShot(0,self.assign_template)
        self.start(self.controller.list_job,ready,self.error)

    def consume(self, events):
        changed = False
        replacement=events.pop('@rebuild-plan',None)
        if replacement:
            self.details.clear()
            data=json.loads(replacement[1]);targets={r['target'] for r in data['actions']+data['issues']}
            rows=[r for r in self.plan_model.rows if r['target'] not in targets]
            rows.extend(dict(action_id=r['id'],target=r['target'],stage=r['stage'],summary=r['summary'],detail=r['detail'],state='等待',progress='—') for r in data['actions'])
            rows.extend(data['issues']);self.plan_model.reset(rows)
            self.index_by_id={r['action_id']:i for i,r in enumerate(rows) if r.get('action_id')}
        site_updates=[json.loads(detail) for aid,(state,detail) in events.items() if aid.startswith('@site:')]
        if site_updates:
            rows={row['id']:row for row in self.sites_model.rows}
            rows.update({row['id']:row for row in site_updates})
            self.sites_model.reset(list(rows.values()))
        for aid,(state,detail) in events.items():
            if aid.startswith('@site:'):
                continue
            if aid.startswith('@preview:'):
                target=aid.removeprefix('@preview:')
                for row in self.plan_model.rows:
                    if row['target']==target:row.update(state=state,detail=detail);changed=True
                continue
            index = self.index_by_id.get(aid)
            if index is not None:
                try:
                    decoded=json.loads(detail)
                    if isinstance(decoded,str): detail=decoded
                    elif isinstance(decoded,dict) and 'upload_progress' in decoded:
                        percent=decoded['upload_progress']
                        self.plan_model.rows[index]['progress']=f'{percent}%'
                        detail=f"本机上传：{percent}% · {decoded['sent']/1048576:.2f} / {decoded['total']/1048576:.2f} MB"
                        if percent==100: detail+=' · 文件传输结束，等待后台解压结果'
                    elif isinstance(decoded,dict) and 'task_id' in decoded:
                        total=decoded.get('total',0);done=decoded.get('done',0)
                        self.plan_model.rows[index]['progress']=f'{done}/{total}'
                        detail=f"后台任务 #{decoded['task_id']} · {decoded.get('task_status','')} · 失败 {decoded.get('failed',0)}"

                except (ValueError,TypeError): pass
                self.plan_model.rows[index].update(state=state,detail=detail); changed = True
                if state=='成功' and self.plan_model.rows[index].get('stage')=='upload':
                    self.plan_model.rows[index]['progress']='100%' 
                elif state=='成功' and self.plan_model.rows[index].get('stage') in STAGES:
                    self.plan_model.rows[index]['progress']='完成'
                if state in ('失败','结果未知'):
                    self.plan_table.selectRow(index)
        if changed:
            self.plan_model.dataChanged.emit(self.plan_model.index(0,2),self.plan_model.index(len(self.plan_model.rows)-1,4))
            self.show_detail()

    def read_sites(self,force_fill=False):
        if self.busy:
            self.status.setText('已有任务正在处理，站点加载不会重复提交。请等待或取消当前任务。')
            return
        if self.controller:
            self.all_sites=[]
            self.sites_model.reset([])
            self.assignment_notice.setText('正在登录后台并读取站点；具体请求与耗时显示在底部。')
            def done(rows):
                self.jobs.flush()
                owned={r['target']:r for r in self.usage.rows() if r['owner']==self.client.key}
                for row in rows:
                    entry=owned.get(row['code'])
                    row['binding']=('流程已完成' if entry['stage']=='done' else LABELS.get(entry['stage'],'待核实')) if entry else '未分配'
                    row['template_stage']=entry['stage'] if entry else ''
                self.sites_model.reset(rows)
                self.all_sites=[dict(row) for row in rows]
                unpublished=sum(r['publication']=='未发布' for r in rows);unknown=sum(r['publication']=='待核实' for r in rows)
                message = f'已读取 {len(rows)} 个站点 · 未发布 {unpublished} · 待核实 {unknown}；待核实不会自动填入。'
                self.status.setText(message); self.assignment_notice.setText(message)
                if force_fill or self.auto_fill.isChecked():self.fill_unpublished(force_fill)
            def failed(message):
                self.assignment_notice.setText('加载站点失败：' + message + '；可点击“加载站点”重试。')
            self.start(SiteCatalog(self.client).list_job,done,failed)
        else: self.error('请先添加后台')

    def fill_unpublished(self,force=False):
        current=self.domains.toPlainText()
        if not force and current.strip() and current!=self.auto_sites_text:return
        rows=[r for r in self.all_sites if r.get('publication')=='未发布']
        unknown=any(r.get('publication')=='待核实' for r in self.all_sites)
        if unknown and (not rows or not force and current.strip()):
            self.status.setText('部分发布状态无法核实，已保留原输入；可稍后重新加载。');return
        text,invalid=domain_lines(rows)
        if len(text.splitlines())>1000:
            self.status.setText('未发布站点超过 1000 个，请分批处理；输入框未改动');return
        self.imported_sites=imported_sites(rows)
        self.domains.setPlainText(text);self.auto_sites_text=text
        self.config_summary.setText(f'已填入 {len(text.splitlines())} 个未发布站点；沿用各站后台配置。空站点需先补模板，仍需预览并确认执行。'+(f' 无效主域名 {invalid} 个未填入。' if invalid else ''))

    def copy_domains(self):
        text,invalid=domain_lines(self.all_sites)
        if not text:self.status.setText('没有有效主域名，剪贴板未改动');return
        QApplication.clipboard().setText(text)
        self.status.setText(f'已复制全部列表的 {len(text.splitlines())} 个域名，一行一个（已去重、去掉 *.）。'+(f' 跳过 {invalid} 个无效主域名。' if invalid else ''))

    def preview_rebuild(self,targets,dialog=None):
        if self.busy or not self.client:return
        root=self.template_root.text().strip()
        if not root:root=QFileDialog.getExistingDirectory(self,'选择含备用模板的父目录')
        if not root:return
        if dialog:dialog.close()
        self.invalidate()
        self.start(RebuildWorkflow(self.client,self.store,self.usage,self.pipeline_store).preview_job(targets,root),self.show_plan,self.error)

    def read_history(self):
        if self.store:
            def done(rows):
                titles={'pack':'打包模板','create':'创建 / 核对站点','upload':'上传并解压','sync':'同步目录','scan':'扫描','/api/sites':'创建站点'}
                for row in rows:
                    row['time']=datetime.fromtimestamp(row['updated']).strftime('%Y-%m-%d %H:%M:%S')
                    row['operation']=titles.get(row['path'],row['path'])
                self.history_model.reset(rows);self.status.setText(f'已读取 {len(rows)} 条本机执行记录')
            self.start(lambda _:self.store.history(),done)

    def load_tab(self,index):
        if self.busy:
            self.pending_tab=True;return
        if not self.client:return
        if index==1:self.read_sites()
        elif index==2:self.read_history()
        elif index==3:self.read_templates()

    def read_templates(self):
        if not self.client:return
        def done(rows):
            self.template_panel.show_rows(rows)
            self.status.setText(f'模板核实完成：{sum(r["kind"]=="active" for r in rows)} 条当前绑定，{sum(r["kind"]=="released" for r in rows)} 条释放历史。')
        self.start(TemplateManagement(self.client,self.usage).list_job,done,self.error)

    def release_template(self,entry):
        if self.busy or not self.client or not entry:return
        if QMessageBox.question(self,'核实并释放模板',f"重新核实站点 {entry['target']}（ID {entry['site_id']}）是否已删除？\n仅在原后台核实不存在时解除本机模板占用；保留历史，不删除远端内容。")!=QMessageBox.StandardButton.Yes:return
        self.invalidate()
        def done(message):
            self.pending_tab=True
            QMessageBox.information(self,'模板已释放',message)
        self.start(TemplateManagement(self.client,self.usage).release_job(entry),done,self.error)

    def show_history_detail(self,*_):
        index=self.history_table.currentIndex().row()
        if 0<=index<len(self.history_model.rows):
            row=self.history_model.rows[index]
            self.history_details.setPlainText(f"{row['time']} · {row['target']} · {row['operation']} · {row['state']}\n{row['detail']}\n批次：{row['batch']}")

    def assign_template(self):
        if self.busy or not self.client:return
        index=self.sites_table.currentIndex().row()
        if index<0:self.error('请先加载站点，再选中一个空站点');return
        row=dict(self.sites_model.rows[index])
        if row.get('template_stage'):
            self.resume_selected();return
        if row.get('page_count')!=0:self.error('此站点已有页面，不能分配模板覆盖');return
        folder=QFileDialog.getExistingDirectory(self,'选择这个站点要使用的模板文件夹（不是父目录）')
        if not folder:return
        self.invalidate()
        self.assignment_notice.setText(f"正在检查：{row['code']} ← {Path(folder).name}。大模板校验可能需要一些时间，请稍候…")
        def failed(message):
            self.assignment_notice.setText('分配未完成：'+message)
            self.error(message)
        def ready(result):
            self.domains.setPlainText(row['primary_domain'].removeprefix('*.'))
            self.wildcard.setChecked(row['primary_domain'].startswith('*.'))
            self.protocol.setCurrentText(row['link_protocol'])
            self.with_template.setChecked(True)
            self.template_root.setText(str(Path(folder).parent))
            self.tabs.setCurrentIndex(0)
            self.show_plan(result)
            self.assignment_notice.setText('预览已生成，请在批量建站页核对并点击“确认执行”。')
            self.config_summary.setText(f"分配预览：{row['code']} ← {folder}；核对下方步骤后点击“确认执行”。")
        self.start(TemplateWorkflow(self.client,self.store,self.usage).assign_job(row,folder),ready,failed)

    def export(self, rows):
        if not rows: return
        path,_ = QFileDialog.getSaveFileName(self,'导出','site-workflow.json','JSON (*.json)')
        if path:
            try: Path(path).write_text(json.dumps(rows,ensure_ascii=False,indent=2),'utf-8')
            except Exception as exc: self.error(exc)

    def closeEvent(self,event):
        if self.jobs.close(): self.usage.close(); self.pipeline_store.close(); event.accept()
        else: event.ignore()

    def choose_templates(self):
        path=QFileDialog.getExistingDirectory(self,'选择模板父目录',self.template_root.text())
        if path: self.template_root.setText(path)

    def toggle_config(self):
        visible=self.config_scroll.isHidden()
        self.config_scroll.setVisible(visible);self.config_toggle.setText('收起配置' if visible else '展开配置')

    def show_detail(self):
        index=self.plan_table.currentIndex().row()
        if 0 <= index < len(self.plan_model.rows):
            row=self.plan_model.rows[index]
            text=f"{row.get('target','')} · {row.get('summary','')} · {row.get('state','')}\n{row.get('detail','')}"
            if row.get('state') in ('失败','结果未知','未执行'):
                if row.get('stage') in STAGES:
                    text+='\n处理：修正原因后勾选“六步加工”重新预览；保留 TDK，跳过成功步骤并查询已提交任务。缺少任务 ID 时使用“核对加工任务 ID”。'
                else:
                    text+='\n处理：模板流程请点击“重试 / 恢复未完成流程”。结果未知时，先在后台核实是否完成；普通建站可重新生成预览，已存在站点会核对后跳过。'
            self.details.setPlainText(text)

    def show_tdk(self):
        if not self.client:return
        targets=list(dict.fromkeys(r['target'] for r in self.plan_model.rows))
        allocations=[(target,self.pipeline_store.allocation(self.client.key,target)) for target in targets]
        allocations=[(target,tdk) for target,tdk in allocations if tdk]
        if not allocations:self.error('先勾选六步加工并预览，系统会生成并保存每个站点独立的 TDK');return
        dialog=QDialog(self);dialog.setWindowTitle('已保存的站点 TDK · 重试复用');dialog.resize(780,520)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setReadOnly(True)
        text.setPlainText('\n\n'.join(f"{target}\nTitle：{tdk['title']}\nDescription：{tdk['description']}\nKeywords：{tdk['keywords']}" for target,tdk in allocations))
        layout.addWidget(text);layout.addWidget(button('关闭',dialog.accept));dialog.exec();dialog.deleteLater()

    def attach_pipeline_task(self):
        if self.busy or not self.client:return
        entries=[]
        for target in dict.fromkeys(r['target'] for r in self.plan_model.rows):
            for stage,title in zip(STAGES,TITLES):
                saved=self.pipeline_store.step(self.client.key,target,stage)
                if saved.get('state')=='submitting' and not saved.get('task_id'):entries.append((target,stage,title))
        if not entries:self.error('没有缺少任务 ID 的加工步骤；重新预览即可恢复已记录的任务');return
        names=[f'{target} · {title}' for target,stage,title in entries]
        name,ok=QInputDialog.getItem(self,'核对后台任务','选择待核实步骤',names,0,False)
        if not ok:return
        target,stage,_=entries[names.index(name)]
        task_id,ok=QInputDialog.getInt(self,'后台任务 ID','填写后台任务中心对应的任务 ID；客户端会核对站点与操作类型',1,1,2147483647)
        if ok:self.start(SitePipeline(self.client,self.store,self.usage,self.pipeline_store).attach_task_job(target,stage,task_id),lambda message:self.status.setText(message),self.error)

    def update_site_actions(self):
        index=self.sites_table.currentIndex().row()
        row=self.sites_model.rows[index] if 0<=index<len(self.sites_model.rows) else {}
        stage=row.get('template_stage','')
        available=not self.busy and self.client is not None
        self.assign_button.setEnabled(available and bool(row) and not stage and row.get('page_count')==0)
        self.resume_button.setEnabled(available and stage in LABELS)
        self.process_button.setEnabled(available and bool(row) and isinstance(row.get('page_count'),int) and row['page_count']>0)

    def visit_site(self, index):
        if not index.isValid() or self.sites_model.columns[index.column()][0] != 'primary_domain':
            return
        try:
            url = site_visit_url(self.sites_model.rows[index.row()])
            if not QDesktopServices.openUrl(QUrl(url)):
                raise ValueError('未能打开默认浏览器：' + url)
        except ValueError as exc:
            self.error(str(exc))

    def process_selected(self):
        if self.busy:return
        index=self.sites_table.currentIndex().row()
        if not 0<=index<len(self.sites_model.rows):return
        row=self.sites_model.rows[index]
        self.domains.setPlainText(row['code'])
        self.wildcard.setChecked(row['primary_domain'].startswith('*.'))
        self.protocol.setCurrentText(row['link_protocol'])
        self.with_template.setChecked(False);self.with_pipeline.setChecked(True)
        self.tabs.setCurrentIndex(0);self.preview()

    def resume_selected(self):
        if self.busy:return
        index=self.sites_table.currentIndex().row()
        if not 0<=index<len(self.sites_model.rows):self.error('请先选择一个未完成的站点');return
        self.recover(self.sites_model.rows[index]['code'])

    def recover(self,target=None):
        if self.busy or not self.client:return
        controller=RecoveryController(self.client,self.store,self.usage)
        entries=controller.entries()
        if isinstance(target,str):entries=[entry for entry in entries if entry["target"]==target]
        if not entries:
            self.error('没有已绑定的未完成模板流程。若在打包前失败，请修正原因后重新预览。');return
        dialog=QDialog(self);dialog.setWindowTitle('恢复未完成流程');dialog.resize(600,300)
        layout=QVBoxLayout(dialog)
        targets=combo([f"{e['target']} · {LABELS[e['stage']]}" for e in entries]);layout.addWidget(targets)
        note=label('保留原模板和站点绑定。先核对后台，再生成恢复预览；成功步骤不会重复执行。','notice');layout.addWidget(note)
        completed=QCheckBox('我已在后台核实：该步骤已完成且错误已修复，继续下一步')
        layout.addWidget(completed)
        template_info=label('');layout.addWidget(template_info)
        layout.addWidget(label('不勾选时重试未完成步骤。重新上传会覆盖该站点的上传目录；同步会替换工作目录。'))
        def changed():
            completed.setChecked(False)
            template_info.setText('原模板：'+entries[targets.currentIndex()]['path'])
            completed.setEnabled(entries[targets.currentIndex()]['stage'] in ('uploading','syncing','sync_failed','scaning','scanning'))
        targets.currentIndexChanged.connect(changed);changed()
        controls=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('核对并生成恢复预览')
        controls.accepted.connect(dialog.accept);controls.rejected.connect(dialog.reject);layout.addWidget(controls)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.invalidate()
            entry=entries[targets.currentIndex()]
            def ready(result):
                self.tabs.setCurrentIndex(0)
                self.show_plan(result)
                self.config_summary.setText(f"恢复预览：{entry['target']} · 原模板 {Path(entry['path']).name}；核对后点击“确认执行”。")
            self.start(controller.job(entry,completed.isChecked()),ready,self.error)
        dialog.deleteLater()
