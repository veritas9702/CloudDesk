"""Reusable background execution and coalesced progress delivery."""
import threading
from PySide6.QtCore import QThread, Signal
from .models import Cancelled

class Worker(QThread):
    result = Signal(object)
    failure = Signal(str)
    event = Signal(str, str, str)

    def __init__(self, function, sanitize):
        super().__init__()
        self.function, self.sanitize = function, sanitize
        self._event_lock = threading.Lock()
        self._events = {}

    def report(self, aid, state, detail):
        # Coalesce in the producer, before crossing the Qt event queue.
        with self._event_lock:
            self._events[aid] = (state, detail)

    def take_events(self):
        with self._event_lock:
            pending, self._events = self._events, {}
        return pending

    def run(self):
        try:
            self.result.emit(self.function(self.report))
        except Cancelled:
            self.failure.emit("已取消。已发送到平台的请求无法撤回，请查看任务记录。")
        except Exception as exc:
            self.failure.emit(self.sanitize(exc))


