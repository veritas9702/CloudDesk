"""Per-site active time and rolling transfer rate, independent of UI/network."""
from collections import deque
from datetime import datetime, timezone
import time


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def duration(seconds):
    if seconds is None:
        return '未记录'
    seconds = int(max(0, seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def local_time(value):
    return datetime.fromisoformat(value).astimezone().strftime('%m-%d %H:%M:%S') if value else '—'


class Meter:
    def __init__(self, task, clock=time.monotonic):
        self.clock = clock
        self.start = clock()
        self.base_seconds = task.get('elapsed_seconds') or 0
        self.base_bytes = task.get('transferred_bytes') or 0
        self.started_at = task.get('started_at') or utc_now()
        self.received = 0
        self.samples = deque([(self.start, 0)])

    def add(self, count):
        self.received += count

    def snapshot(self):
        now = self.clock()
        self.samples.append((now, self.received))
        while len(self.samples) > 2 and self.samples[1][0] <= now - 3:
            self.samples.popleft()
        first, count = self.samples[0]
        elapsed = self.base_seconds + max(0, now - self.start)
        total = self.base_bytes + self.received
        speed = (self.received - count) / max(.001, now - first) / 1024
        return dict(started_at=self.started_at, elapsed_seconds=elapsed,
                    transferred_bytes=total, speed_kbps=speed,
                    average_kbps=total / max(.001, elapsed) / 1024)


def presentation(task):
    result = dict(task)
    result['elapsed'] = duration(task.get('elapsed_seconds'))
    average = task.get('transferred_bytes', 0) / max(.001, task.get('elapsed_seconds') or 0) / 1024
    active = task.get('state') in ('采集中', '整理中')
    speed = task.get('speed_kbps', 0) if active else average
    result['speed'] = (('均 ' if not active else '') + f'{speed:.0f} KB/s') if task.get('elapsed_seconds') is not None else '未记录'
    result['ended'] = local_time(task.get('ended_at'))
    return result
