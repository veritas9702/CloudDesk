"""Capture view. Domain work runs through the controller on a shared Worker."""
import threading
import json
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QTimer, QUrl, QStandardPaths, Qt, QItemSelectionModel
from PySide6.QtGui import QDesktopServices, QColor, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QPlainTextEdit, QMenu, QCheckBox, QDialog, QDialogButtonBox
from ..ui_components import label, button, line, DomainEditor, number_input, card, table, combo
from ..table_model import TableModel
from ..qt_jobs import Worker
from .controller import CaptureController
from .models import Settings, seeds
from .preview import Preview
from .metrics import presentation
from .task_view import ordered, summary, urls_for, FAILED


def desktop_directory():
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation) or str(Path.home() / 'Desktop')


class CaptureTableModel(TableModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checked = set()

    def flags(self, index):
        flags = super().flags(index)
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.isValid() and index.column() == 0 else flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            key = self.rows[index.row()]['id']
            if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
                self.checked.add(key)
            else:
                self.checked.discard(key)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and index.column() == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if self.rows[index.row()]['id'] in self.checked else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.DisplayRole:
                return ''
        if index.isValid() and self.columns[index.column()][0] == 'template_bytes' and role == Qt.ItemDataRole.DisplayRole:
            return f"{self.rows[index.row()].get('template_bytes', 0) / 1048576:.2f} MB"
        if index.isValid() and index.column() == 1:
            row = self.rows[index.row()]
            if row['state'] not in ('等待', '采集中', '整理中'):
                if role == Qt.ItemDataRole.ForegroundRole:
                    return QColor('#2673b8')
                if role == Qt.ItemDataRole.FontRole:
                    font = QFont()
                    font.setUnderline(True)
                    return font
                if role == Qt.ItemDataRole.ToolTipRole:
                    return '点击在浏览器预览本地采集页面（需要已保存首页）'
        return super().data(index, role)


class CapturePage(QWidget):
    def __init__(self, root):
        super().__init__()
        self.controller = CaptureController(root, recover=False)
        self.initializing = True
        self.initialization_error = False
        self.busy = False
        self.worker = None
        self.cancel = threading.Event()
        self.detail_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='capture-detail')
        self.detail_future = None
        self.detail_requested = None
        self.draft_future = None
        self.draft_requested = None
        self.row_indexes = {}
        self.deleted_ids = set()
        self.finish_message = ''
        self.incoming = queue.Queue()
        self.append_future = None
        self.delete_future = None
        self.delete_refreshing = False
        self.preview = Preview()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        title = label('网站采集 · 本地模板')
        title.setStyleSheet('font-size: 24px; font-weight: 700; color: #172940;')
        heading = QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch()
        self.template_limit_mb = 300
        self.policy_button = button(f'自动清理：超过 {self.template_limit_mb} MB', self.configure_size_policy)
        heading.addWidget(self.policy_button)
        layout.addLayout(heading)
        frame, body = card()
        row = QHBoxLayout()
        left, right = QVBoxLayout(), QVBoxLayout()
        input_header = QHBoxLayout()
        input_title = label('01  网站地址 · 每行一个')
        input_title.setWordWrap(False)
        input_header.addWidget(input_title)
        self.queue_count = label('待处理 0 个')
        self.queue_count.setWordWrap(False)
        input_header.addStretch()
        input_header.addWidget(self.queue_count)
        left.addLayout(input_header)
        self.domains = DomainEditor()
        self.domains.setPlaceholderText('https://example.com\nhttps://example.org\n只采集公开页面及其引用的静态资源')
        left.addWidget(self.domains)
        self.domains.textChanged.connect(self.update_counts)
        right.addWidget(label('02  保存目录与采集范围'))
        output_row = QHBoxLayout()
        self.output = line('选择保存模板的父目录，每个站点独立保存')
        directory_error = ''
        desktop = desktop_directory()
        self.choose_button = button('选择目录', self.choose)
        output_row.addWidget(self.output)
        output_row.addWidget(self.choose_button)
        right.addLayout(output_row)
        settings_row = QHBoxLayout()
        self.depth = combo(['1 层 · 首页', '2 层 · 首页及下级', '3 层 · 再深入一级'])
        self.depth.setCurrentIndex(2)
        self.depth.setToolTip('首页计为第 1 层；图片、CSS、JS 等引用资源不占页面深度')
        self.pages = number_input(1, 10000, 500, ' 页')
        settings_row.addWidget(label('最大深度'))
        settings_row.addWidget(self.depth)
        settings_row.addWidget(label('页面上限'))
        settings_row.addWidget(self.pages)
        settings_row.addStretch()
        right.addLayout(settings_row)
        self.mode = combo(['完整离线 · 保存静态资源', '轻量联网 · 图片等引用原站'])
        right.addWidget(self.mode)
        right.addWidget(label('保留原站目录与编码。轻量模式的图片、字体等需联网加载。'))
        right.addStretch()
        row.addLayout(left, 1)
        row.addLayout(right, 1)
        body.addLayout(row)
        layout.addWidget(frame)
        actions = QHBoxLayout()
        self.sites = number_input(1, 4, 2, ' 个')
        self.connections = number_input(1, 8, 4, ' 个')
        actions.addWidget(label('并行站点'))
        actions.addWidget(self.sites)
        actions.addWidget(label('每站连接'))
        actions.addWidget(self.connections)
        limits = label('总连接 ≤ 8，同一来源 ≤ 4')
        limits.setWordWrap(False)
        actions.addWidget(limits)
        actions.addStretch()
        self.start_button = button('开始采集', self.start, True)
        self.resume_button = button('继续采集', lambda: None)
        self.pause_button = button('暂停并保存', self.pause)
        resume_menu = QMenu(self)
        self.resume_all_button = resume_menu.addAction('继续全部未完成任务', self.resume_all)
        self.resume_selected_action = resume_menu.addAction('继续选中任务', self.resume)
        self.resume_button.setMenu(resume_menu)
        self.start_button.setToolTip('仅处理输入框中的网址；已保存模板自动跳过。')
        self.resume_all_button.setToolTip('将历史未生成模板的任务加入队列；已保存模板不重复采集。')
        for w in (self.start_button, self.resume_button, self.pause_button):
            actions.addWidget(w)
        layout.addLayout(actions)
        self.model = CaptureTableModel([('checked', '选择'), ('seed', '网站'), ('state', '状态'), ('template_bytes', '模板大小'), ('elapsed', '运行耗时'), ('speed', '速度'), ('ended', '结束时间'), ('detail', '采集进度 / 结果')], centered=True)
        self.view = table(self.model)
        for index, width in enumerate((48, 225, 85, 95, 85, 95, 130)):
            self.view.setColumnWidth(index, width)
        self.view.selectionModel().selectionChanged.connect(self.selection_changed)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.task_menu)
        self.view.clicked.connect(self.domain_clicked)
        self.task_counts = label('任务统计')
        layout.addWidget(self.task_counts)
        filters = QHBoxLayout()
        self.state_filter = combo(['全部状态', '失败任务', '部分完成', '已完成', '已暂停', '等待', '采集中'])
        self.state_filter.setFixedWidth(125)
        filters.addWidget(self.state_filter)
        self.size_filter = QCheckBox('仅显示模板大于')
        self.size_limit = number_input(300, 1000000, 1000, ' MB')
        self.size_limit.setToolTip('筛选已保存文件的体积，不是累计网络流量；1 MB = 1024 × 1024 字节。')
        filters.addWidget(self.size_filter)
        filters.addWidget(self.size_limit)
        self.selection_count = label('')
        self.selection_count.setWordWrap(False)
        filters.addWidget(self.selection_count)
        filters.addStretch()
        bulk = button('批量操作', lambda: None)
        bulk_menu = QMenu(bulk)
        bulk_menu.addAction('全选当前结果', lambda: self.check_visible(True))
        bulk_menu.addAction('取消全选', lambda: self.check_visible(False))
        bulk_menu.addSeparator()
        self.delete_checked_button = bulk_menu.addAction('删除勾选任务…', self.delete_checked)
        self.delete_filtered_button = bulk_menu.addAction('删除筛选结果…', self.delete_filtered)
        self.delete_failed_button = bulk_menu.addAction('删除全部失败…', self.delete_failed)
        bulk.setMenu(bulk_menu)
        filters.addWidget(bulk)
        layout.addLayout(filters)
        self.state_filter.currentIndexChanged.connect(self.apply_filter)
        self.size_filter.toggled.connect(self.apply_filter)
        self.size_limit.valueChanged.connect(self.apply_filter)
        self.model.dataChanged.connect(self.check_changed)
        layout.addWidget(self.view, 1)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label('任务与断点保存在本机，切换模块后继续运行。'), 1)
        more = button('更多', lambda: None)
        more_menu = QMenu(more)
        self.folder_button = more_menu.addAction('打开模板目录', self.open_folder)
        self.details_button = button('查看详细报告', self.show_detail)
        self.preview_button = button('本地预览', self.open_preview)
        self.clear_button = more_menu.addAction('清理失败缓存…', self.clear_cache)
        more.setMenu(more_menu)
        toolbar.addWidget(self.preview_button)
        toolbar.addWidget(self.details_button)
        toolbar.addWidget(more)
        layout.addLayout(toolbar)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(125)
        self.detail.setPlaceholderText('选择任务查看保存位置、失败原因和处理建议。已完成表示配置范围内的静态资源下载完成，不代表动态网站功能已复制。')
        layout.addWidget(self.detail)
        self.status = label(directory_error or '默认保存到桌面 WebsiteTemplates，也可选择其他目录；已选路径会在本机记住。')
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.flush)
        self.timer.start()
        self.refresh([])
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(500)
        self.draft_timer.timeout.connect(self.save_draft)
        self.domains.textChanged.connect(lambda: self.draft_timer.start())
        def initialize():
            self.controller.recover()
            output = self.controller.output_directory(desktop)
            limit = self.controller.template_limit()
            rows = self.controller.enforce_template_limit()
            return output, limit, rows, self.controller.pending_input()
        self.initial_future = self.detail_pool.submit(initialize)
        self.status.setText('正在后台恢复采集记录并检查模板，可切换其他模块…')
        self.update_actions()

    def check_changed(self, top, bottom, roles=None):
        # Progress cells must not trigger another full-table selection scan.
        if top.column() == 0:
            self.update_bulk_actions()

    def configure_size_policy(self):
        if self.busy or self.append_future or self.delete_future:
            self.status.setText('请等待当前采集或清理完成后调整模板上限。')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('模板自动清理')
        layout = QVBoxLayout(dialog)
        layout.addWidget(label('超过上限自动停止采集，并删除对应模板和缓存。'))
        value = number_input(1, 1000000, self.template_limit_mb, ' MB')
        layout.addWidget(value)
        layout.addWidget(label('按文件实际总量计算，非 ZIP 大小；保存后也清理已有采集记录中的超限模板。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存并清理超限模板')
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.template_limit_mb = value.value()
            self.policy_button.setText(f'自动清理：超过 {self.template_limit_mb} MB')
            self.delete_future = self.detail_pool.submit(self.controller.enforce_template_limit, self.template_limit_mb)
            self.status.setText('正在后台检查并删除超限模板…')

    def save_draft(self):
        if self.initializing or self.initialization_error:
            return True
        self.draft_requested = self.domains.toPlainText()
        return True

    def update_counts(self):
        pending = set()
        invalid = 0
        for value in self.domains.toPlainText().splitlines():
            if not value.strip():
                continue
            try:
                pending.update(seeds(value))
            except ValueError:
                invalid += 1
        rows = self.model.rows if hasattr(self, 'model') else []
        saved = {url for r in rows if r.get('published') or r['state'] in ('已完成', '部分完成') for url in [r['seed'], *r.get('aliases', [])]}
        pending -= saved
        self.queue_count.setToolTip('仅统计输入框中尚未保存的网址；下方任务统计覆盖全部历史任务，包含不在输入框中的任务。')
        self.queue_count.setText(f'输入剩余 {len(pending)} 个' + (f' · 无效 {invalid} 行' if invalid else ''))
        if hasattr(self, 'task_counts'):
            counts = summary(rows)
            self.task_counts.setText('任务 {total} · 等待 {waiting} · 采集中 {running} · 暂停 {paused} · 失败 {failed} · 部分完成 {partial} · 已完成 {completed}'.format(**counts))

    def domain_clicked(self, index):
        if index.isValid() and index.column() == 1:
            row = self.model.rows[index.row()]
            if row['state'] not in ('等待', '采集中', '整理中'):
                self.preview_task(row['id'])

    def make_task_menu(self, row):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #ffffff; color: #24364b; border: 1px solid #d8e1ed;
                    border-radius: 7px; padding: 6px; }
            QMenu::item { padding: 9px 22px; min-width: 132px; border-radius: 4px; }
            QMenu::item:selected { background: #edf4fc; color: #185e9c; }
            QMenu::item:disabled { color: #9aa7b7; }
            QMenu::separator { height: 1px; background: #e7edf5; margin: 5px 8px; }
        """)
        preview = menu.addAction('预览本地模板')
        preview.setEnabled(row['state'] not in ('等待', '采集中', '整理中'))
        menu.addSeparator()
        delete = menu.addAction('删除任务…')
        return menu, preview, delete

    def task_menu(self, point):
        index = self.view.indexAt(point)
        if not index.isValid():
            return
        self.view.selectRow(index.row())
        row = self.model.rows[index.row()]
        key = row['id']
        menu, preview, delete = self.make_task_menu(row)
        action = menu.exec(self.view.viewport().mapToGlobal(point))
        if action == delete:
            self.delete_task(key)
        elif action == preview:
            self.preview_task(key)
        menu.deleteLater()

    def visible_rows(self):
        state = self.state_filter.currentText()
        def matches(row):
            if state == '失败任务': return row['state'] in FAILED
            if state == '采集中': return row['state'] in {'采集中', '整理中'}
            return state == '全部状态' or row['state'] == state
        return [r for r in self.model.rows if matches(r) and (not self.size_filter.isChecked() or r.get('template_bytes', 0) > self.size_limit.value() * 1048576)]

    def apply_filter(self, *_):
        visible = {r['id'] for r in self.visible_rows()}
        self.model.checked.intersection_update(visible)
        for index, row in enumerate(self.model.rows):
            hidden = row['id'] not in visible
            if self.view.isRowHidden(index) != hidden:
                self.view.setRowHidden(index, hidden)
        self.update_bulk_actions()

    def update_bulk_actions(self, *_):
        if not hasattr(self, 'selection_count'):
            return
        visible = {r['id'] for r in self.visible_rows()}
        checked = self.model.checked & visible
        self.selection_count.setText(f'显示 {len(visible)} / {len(self.model.rows)} · 已勾选 {len(checked)}')
        self.delete_checked_button.setEnabled(bool(checked))
        self.delete_filtered_button.setEnabled((self.size_filter.isChecked() or self.state_filter.currentIndex() != 0) and bool(visible))
        self.delete_failed_button.setEnabled(any(r['state'] in FAILED for r in self.model.rows))

    def check_visible(self, checked):
        self.model.checked = {r['id'] for r in self.visible_rows()} if checked else set()
        if self.model.rows:
            self.model.dataChanged.emit(self.model.index(0, 0), self.model.index(len(self.model.rows)-1, 0))
        self.update_bulk_actions()

    def delete_checked(self):
        self.delete_rows([r for r in self.visible_rows() if r['id'] in self.model.checked], '勾选的任务')

    def delete_filtered(self):
        if self.size_filter.isChecked() or self.state_filter.currentIndex() != 0:
            size = f'，大于 {self.size_limit.value()} MB' if self.size_filter.isChecked() else ''
            self.delete_rows(self.visible_rows(), f'当前筛选结果（{self.state_filter.currentText()}{size}）')

    def delete_failed(self):
        self.delete_rows([r for r in self.model.rows if r['state'] in FAILED], '全部失败任务（不包含部分完成、已完成和运行中任务）')

    def delete_task(self, key):
        self.delete_rows([r for r in self.model.rows if r['id'] == key], '此任务')

    def delete_rows(self, rows, scope):
        if self.delete_future is not None:
            self.status.setText('正在清理模板，请等待完成后再删除。')
            return
        rows = list(rows)
        if not rows:
            return
        total = sum(r.get('template_bytes', 0) for r in rows) / 1048576
        box = QMessageBox(self)
        box.setWindowTitle('确认删除任务和文件')
        box.setText(f'删除{scope}，共 {len(rows)} 个任务？')
        box.setInformativeText(f'模板约 {total:.2f} MB；对应模板目录及断点缓存会一起删除，不可恢复。运行中的任务先停止再清理。')
        box.setDetailedText('\n'.join(r['seed'] + '\n' + r['output'] for r in rows))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            keys = {row['id'] for row in rows}
            self.deleted_ids.update(keys)
            self.preview.close()
            if self.delete_future is None:
                def delete():
                    self.controller.delete_tasks(keys)
                    return self.controller.cleanup_deleted()
                self.delete_future = self.detail_pool.submit(delete)
            self.remove_input_urls(urls_for(rows))
            self.refresh([r for r in self.model.rows if r['id'] not in self.deleted_ids])
            self.detail.clear()
        except Exception as exc:
            self.refresh()
            QMessageBox.warning(self, '删除失败', str(exc))

    def confirm_failed(self, rows):
        failed = [r for r in rows if r['state'] in FAILED]
        if not failed:
            return rows
        box = QMessageBox(self)
        box.setWindowTitle('失败任务是否重试')
        box.setText(f'包含 {len(failed)} 个之前失败或未通过验收的任务。是否重新尝试？')
        box.setInformativeText('重试会复用可用断点；跳过会从输入框移除这些失败网址，历史记录仍保留。')
        retry = box.addButton('重试失败任务', QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton('跳过并移除网址', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == retry:
            return rows
        if box.clickedButton() == skip:
            self.remove_input_urls(urls_for(failed))
            return [r for r in rows if r['state'] not in FAILED]
        return None

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, '选择模板保存父目录', self.output.text())
        if folder:
            try:
                self.controller.remember_output(folder)
                self.output.setText(folder)
            except OSError as exc:
                QMessageBox.warning(self, '保存目录不可用', str(exc))

    def selected(self):
        return [self.model.rows[i.row()] for i in self.view.selectionModel().selectedRows()]

    def update_actions(self):
        selected = self.selected()
        for widget in (self.output, self.choose_button, self.depth, self.pages, self.sites, self.connections, self.mode):
            widget.setEnabled(not self.busy)
        self.domains.setEnabled(not self.initializing and not self.initialization_error)
        self.start_button.setText('加入队列' if self.busy else '开始采集')
        self.start_button.setEnabled(self.append_future is None and self.delete_future is None and not (self.busy and self.cancel.is_set()))
        can_add = self.append_future is None and self.delete_future is None and not (self.busy and self.cancel.is_set())
        self.resume_selected_action.setEnabled(can_add and any(not r.get('published') and r['state'] not in ('等待', '采集中', '整理中', '已完成', '部分完成') for r in selected))
        self.resume_all_button.setEnabled(can_add and any(not r.get('published') and r['state'] not in ('等待', '采集中', '整理中', '已完成', '部分完成') for r in self.model.rows))
        self.resume_button.setEnabled(self.resume_selected_action.isEnabled() or self.resume_all_button.isEnabled())
        self.policy_button.setEnabled(not self.busy and self.append_future is None and self.delete_future is None)
        self.pause_button.setEnabled(self.busy and not self.cancel.is_set())
        published = len(selected) == 1 and bool(selected[0].get('published'))
        self.folder_button.setEnabled(published)
        self.details_button.setEnabled(len(selected) == 1)
        self.preview_button.setEnabled(len(selected) == 1 and selected[0]['state'] not in ('等待', '采集中', '整理中'))
        self.clear_button.setEnabled(not self.busy and len(selected) == 1 and not selected[0].get('published') and selected[0]['state'] != '已清理')
        if self.initializing or self.initialization_error:
            for widget in (self.start_button, self.resume_button, self.resume_all_button,
                           self.policy_button, self.choose_button, self.output):
                widget.setEnabled(False)

    def clear_cache(self):
        selected = self.selected()
        if self.busy or len(selected) != 1:
            return
        task = selected[0]
        answer = QMessageBox.question(self, '清理此任务缓存', task['seed'] + '\n清理后释放断点文件，保留任务记录；下次继续将重新下载。', QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            def clear():
                self.controller.clear_cache(task['id'])
                return self.controller.snapshot()
            self.delete_future = self.detail_pool.submit(clear)
            self.status.setText('正在后台清理缓存…')
            self.update_actions()

    def refresh(self, rows=None):
        selected = {r['id'] for r in self.selected()}
        scroll = self.view.verticalScrollBar().value()
        current = {r['id']: r for r in self.model.rows}
        source = rows if rows is not None else self.controller.snapshot()
        merged = []
        for row in source:
            if row['state'] == '删除失败':
                self.deleted_ids.discard(row['id'])
            old = current.get(row['id'])
            if old and old.get('revision', 0) > row.get('revision', 0):
                row = old
            if not row.get('deleted') and row['id'] not in self.deleted_ids:
                merged.append(presentation(row))
        selection = self.view.selectionModel()
        selection.blockSignals(True)
        try:
            self.model.reset(ordered(merged))
            self.row_indexes = {row['id']: i for i, row in enumerate(self.model.rows)}
            for key in selected:
                if key in self.row_indexes:
                    selection.select(self.model.index(self.row_indexes[key], 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            self.view.verticalScrollBar().setValue(scroll)
        finally:
            selection.blockSignals(False)
        self.apply_filter()
        self.update_counts()
        self.update_actions()

    def selection_changed(self, *_):
        self.update_actions()
        selected = self.selected()
        if len(selected) == 1:
            if not self.busy:
                settings = json.loads(selected[0]['settings'])
                self.depth.setCurrentIndex(max(0, min(2, settings['depth'] - 1)))
                self.pages.setValue(settings['pages'])
            self.show_detail()

    def settings(self):
        return Settings(depth=self.depth.currentIndex() + 1, pages=self.pages.value(), sites=self.sites.value(), connections=self.connections.value(), lightweight=self.mode.currentIndex() == 1, template_limit_mb=self.template_limit_mb)

    def start(self):
        if self.initializing or self.initialization_error:
            return
        try:
            settings = self.settings()
            text, output = self.domains.toPlainText(), self.output.text()
            settings.validate()
            input_urls = set(seeds(text))
            candidates = [r for r in self.model.rows if input_urls.intersection(urls_for([r]))]
            if self.confirm_failed(candidates) is None:
                return
            text = self.domains.toPlainText()
            if not text.strip():
                return
            if self.busy:
                self.append_future = self.detail_pool.submit(self.controller.prepare, text, output, settings)
                self.update_actions()
                self.status.setText('正在后台检查并追加域名，当前采集继续运行…')
                return
            self.cancel.clear()
            self.busy = True
            self.update_actions()
            self.status.setText('正在后台检查已有模板并准备队列…')
            def job(report):
                ids, skipped, rows = self.controller.prepare(text, output, settings)
                report('__tasks__', 'prepared', json.dumps(rows, ensure_ascii=False))
                results = self.controller.run_job(ids, self.cancel, settings=settings, incoming=self.incoming)(report) if ids else rows
                return dict(rows=results, skipped=len(skipped), skipped_urls=skipped)
            self.launch(job)
        except Exception as exc:
            QMessageBox.warning(self, '无法开始', str(exc))

    def resume(self):
        self.resume_rows(self.selected())

    def resume_all(self):
        self.resume_rows(self.model.rows)

    def resume_rows(self, rows):
        rows = self.confirm_failed(rows)
        if rows is None:
            return
        ids = [r['id'] for r in rows if not r.get('published') and r['state'] not in ('等待', '采集中', '整理中', '已完成', '部分完成')]
        if self.busy:
            self.incoming.put(ids)
            self.status.setText(f'已请求将 {len(ids)} 个未完成任务加入队列，等待调度确认。')
        else:
            self.run(ids)

    def run(self, ids):
        if self.busy or not ids:
            return
        self.cancel.clear()
        self.busy = True
        self.update_actions()
        self.status.setText('正在后台采集，可切换其他模块。暂停后可继续，未完成的单文件会重新下载。')
        self.launch(self.controller.run_job(ids, self.cancel, settings=self.settings(), incoming=self.incoming))

    def launch(self, job):
        self.finish_message = ''
        self.worker = Worker(job, lambda exc: str(exc))
        self.worker.result.connect(self.receive_result)
        self.worker.failure.connect(lambda text: self.detail.setPlainText('采集异常：' + text + '\n选择任务后可继续采集。'))
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def receive_result(self, result):
        self.flush()
        if isinstance(result, dict):
            self.finish_message = f'已跳过 {result["skipped"]} 个已保存模板；任务状态已保存。'
            self.remove_saved_inputs([dict(seed=url, state='已完成') for url in result.get('skipped_urls', [])])
            result = result['rows']
        self.refresh(result)
        self.remove_saved_inputs(result)

    def remove_saved_inputs(self, rows):
        saved = {url for r in rows if r.get('published') or r['state'] in ('已完成', '部分完成') for url in [r['seed'], *r.get('aliases', [])]}
        self.remove_input_urls(saved)

    def remove_input_urls(self, saved):
        editor = self.domains
        cursor = editor.textCursor()
        position = cursor.position()
        lines = editor.toPlainText().splitlines()
        kept = []
        for line in lines:
            try:
                matched = bool(seeds(line)) and seeds(line)[0] in saved
            except ValueError:
                matched = False
            if not matched:
                kept.append(line)
        if kept != lines:
            editor.setPlainText('\n'.join(kept))
            cursor = editor.textCursor(); cursor.setPosition(min(position, len(editor.toPlainText())))
            editor.setTextCursor(cursor)

    def flush(self):
        if self.initializing:
            if not self.initial_future.done():
                return
            self.initializing = False
            try:
                output, limit, rows, draft = self.initial_future.result()
                self.output.setText(output)
                self.template_limit_mb = limit
                self.policy_button.setText(f'自动清理：超过 {limit} MB')
                self.refresh(rows)
                self.domains.setPlainText(draft)
                self.remove_saved_inputs(rows)
                self.status.setText('采集记录已恢复，可以开始任务。')
            except Exception as exc:
                self.initialization_error = True
                self.status.setText('采集记录恢复失败，请重新打开模块：' + str(exc))
            self.update_actions()
        self.flush_detail()
        if self.delete_future and self.delete_future.done():
            future, self.delete_future = self.delete_future, None
            try:
                rows = future.result()
                self.delete_refreshing = False
                for row in rows:
                    if row['state'] == '删除失败':
                        self.deleted_ids.discard(row['id'])
                self.refresh(rows)
                self.status.setText('模板清理完成。超限任务及关联文件已移除；删除失败的任务会保留原因。')
            except Exception as exc:
                self.deleted_ids.clear()
                if not self.delete_refreshing:
                    self.delete_refreshing = True
                    self.delete_future = self.detail_pool.submit(self.controller.snapshot)
                else:
                    self.delete_refreshing = False
                self.detail.setPlainText('删除目录失败：' + str(exc))
        if self.append_future and self.append_future.done():
            future, self.append_future = self.append_future, None
            try:
                ids, skipped, rows = future.result()
                self.refresh(rows)
                self.remove_saved_inputs(rows + [dict(seed=url, state='已完成') for url in skipped])
                if ids:
                    if self.busy:
                        self.incoming.put(ids)
                    elif not self.cancel.is_set():
                        self.run(ids)
                self.status.setText(f'已处理追加请求，跳过 {len(skipped)} 个已保存模板。')
            except Exception as exc:
                self.detail.setPlainText('追加失败：' + str(exc))
            self.update_actions()
        if not self.worker:
            return
        events = self.worker.take_events()
        prepared = events.pop('__tasks__', None)
        if prepared:
            self.refresh(json.loads(prepared[1]))
        structural = False
        removed_urls = set()
        for key, (state, raw) in events.items():
            index = self.row_indexes.get(key)
            if index is not None:
                row = self.model.rows[index]
                try:
                    event = json.loads(raw)
                except (ValueError, TypeError):
                    event = dict(detail=raw, metrics={})
                task_data = event.get('task', {})
                if task_data.get('revision', row.get('revision', 0)) < row.get('revision', 0):
                    continue
                before = (row['state'], row.get('ended_at'), row.get('deleted'))
                row.update(task_data)
                row.update(event.get('metrics', {}))
                row.update(state=state, detail=event['detail'])
                row.update(presentation(row))
                structural |= before != (row['state'], row.get('ended_at'), row.get('deleted'))
                self.model.dataChanged.emit(self.model.index(index, 1), self.model.index(index, 7))
                if state == '已自动清理':
                    removed_urls.update({row['seed'], *row.get('aliases', [])})
                elif state in ('已完成', '部分完成'):
                    removed_urls.update({row['seed'], *row.get('aliases', [])})
        if removed_urls:
            self.remove_input_urls(removed_urls)
        if events:
            if structural:
                self.refresh(self.model.rows)
            elif self.size_filter.isChecked():
                self.apply_filter()

    def finished(self):
        self.flush()
        self.worker.deleteLater()
        self.worker = None
        self.busy = False
        if self.deleted_ids and self.delete_future is None:
            self.delete_future = self.detail_pool.submit(self.controller.cleanup_deleted)
        self.update_actions()
        self.status.setText(self.finish_message or '任务状态已保存。选择任务查看报告、继续采集或打开模板目录。')
        pending = []
        while not self.incoming.empty():
            pending.extend(self.incoming.get_nowait())
        if pending and not self.cancel.is_set():
            self.run(list(dict.fromkeys(pending)))

    def pause(self):
        self.cancel.set()
        self.status.setText('正在停止请求并保存断点…')
        self.update_actions()

    def show_detail(self):
        selected = self.selected()
        if len(selected) == 1:
            self.detail_requested = selected[0]['id']
            self.detail.setPlainText(selected[0]['seed'] + '\n' + selected[0].get('detail', '') + '\n正在后台读取详细报告…')

    def flush_detail(self):
        if self.draft_future and self.draft_future.done():
            future, self.draft_future = self.draft_future, None
            try:
                future.result()
            except Exception as exc:
                self.status.setText('待采集列表保存失败：' + str(exc))
        if self.draft_requested is not None and self.draft_future is None:
            text, self.draft_requested = self.draft_requested, None
            self.draft_future = self.detail_pool.submit(self.controller.save_input, text)
        if self.detail_future and self.detail_future.done():
            key, future = self.detail_future_key, self.detail_future
            self.detail_future = None
            selected = self.selected()
            if len(selected) == 1 and selected[0]['id'] == key and self.detail_requested is None:
                try:
                    self.detail.setPlainText(future.result())
                except Exception as exc:
                    self.detail.setPlainText('读取报告失败：' + str(exc))
        if self.detail_requested and self.detail_future is None:
            self.detail_future_key = self.detail_requested
            self.detail_requested = None
            self.detail_future = self.detail_pool.submit(self.controller.detail, self.detail_future_key)

    def open_folder(self):
        selected = self.selected()
        if len(selected) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(selected[0]['output']))

    def open_preview(self):
        selected = self.selected()
        if len(selected) == 1:
            self.preview_task(selected[0]['id'])

    def preview_task(self, key):
        try:
            folder = self.controller.preview_directory(key)
            if not QDesktopServices.openUrl(QUrl(self.preview.open(folder))):
                raise ValueError('无法启动默认浏览器，请检查系统默认浏览器设置。')
            self.status.setText('已在浏览器打开本地预览：' + str(folder))
        except (OSError, ValueError) as exc:
            QMessageBox.information(self, '无法预览', str(exc))

    def closeEvent(self, event):
        if self.initializing or self.busy or self.append_future or self.delete_future:
            self.status.setText('仍有采集或清理任务，请暂停采集并等待清理完成后关闭。')
            event.ignore()
        else:
            if self.draft_future or self.draft_requested is not None:
                self.status.setText('正在保存采集输入，请稍后关闭。')
                event.ignore()
                return
            try:
                # Final small atomic write only; never open SQLite on close.
                if not self.initialization_error:
                    self.controller.save_input(self.domains.toPlainText())
            except (OSError, ValueError) as exc:
                self.status.setText('待采集列表保存失败：' + str(exc))
                event.ignore()
                return
            self.draft_timer.stop()
            self.preview.close()
            self.timer.stop()
            self.detail_pool.shutdown(wait=False, cancel_futures=True)
            event.accept()
