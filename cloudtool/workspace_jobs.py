"""Reusable Qt workspace job lifecycle around the shared coalescing Worker."""
import time
from PySide6.QtCore import QObject, QTimer
from .qt_jobs import Worker


class WorkspaceJobs(QObject):
    def __init__(self, owner, controls, cancel_button, status, consume):
        super().__init__(owner)
        self.owner, self.controls = owner, controls
        self.cancel_button, self.status, self.consume = cancel_button, status, consume
        self.timer = QTimer(self); self.timer.timeout.connect(self.flush); self.timer.start(100)
        cancel_button.clicked.connect(self.cancel)

    def start(self, function, done, failed=None):
        owner = self.owner
        if owner.busy: return
        if not owner.client: raise ValueError('请先添加并选择后台账户')
        owner.client.cancel.clear(); owner.busy = True
        for widget in self.controls: widget.setEnabled(False)
        self.cancel_button.setEnabled(True); self.status.setText('正在后台处理，可切换到其他平台…')
        self.started = time.monotonic()
        self.activity = '正在启动任务'
        self.terminal = False
        owner.job = Worker(function, owner.client.safe)
        if hasattr(owner.client, 'progress'): owner.client.progress = owner.job.report
        owner.update_actions()
        def received(value):
            self.terminal = True
            try: done(value)
            except Exception as exc: self.status.setText(owner.client.safe(exc))
        owner.job.result.connect(received)
        def failure(message):
            self.terminal = True
            self.status.setText(message)
        owner.job.failure.connect(failure)
        if failed: owner.job.failure.connect(failed)
        owner.job.finished.connect(self.finished)
        owner.job.start()

    def flush(self):
        if self.owner.job:
            events = self.owner.job.take_events()
            request = events.pop('@request', None)
            if request: self.activity = request[1]
            self.consume(events)
            if not self.terminal:
                self.status.setText(f'已运行 {int(time.monotonic()-self.started)} 秒 · {self.activity}')

    def finished(self):
        self.flush()
        if hasattr(self.owner.client, 'progress'): self.owner.client.progress = None
        self.owner.job.deleteLater(); self.owner.job = None; self.owner.busy = False
        for widget in self.controls: widget.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.owner.update_actions()

    def cancel(self):
        if self.owner.client: self.owner.client.cancel.set()
        if hasattr(self.owner, 'pending_tab'): self.owner.pending_tab = False
        self.activity = '正在停止；等待当前请求返回'
        self.cancel_button.setEnabled(False)
        self.status.setText('正在停止；已发出的请求无法撤回，请等待结果。')

    def close(self):
        if self.owner.busy:
            self.cancel(); return False
        self.timer.stop()
        if self.owner.client: self.owner.client.close()
        if self.owner.store: self.owner.store.close()
        return True
