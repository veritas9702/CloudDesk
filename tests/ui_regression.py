"""Layout checks on every page and event-loop latency under real mocked jobs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import time
import tempfile
import json
from pathlib import Path

import httpx
from PySide6.QtCore import QTimer, QPoint
from PySide6.QtWidgets import QApplication, QFormLayout
from cloudtool.ui import Window, GuideDialog, TokenDialog, configure_app
from cloudtool.models import Plan, Action
from cloudtool.storage import Store
from cloudtool.api_client import Client
from cloudtool.execution import execute
from cloudtool.cloudflare import Cloudflare


class Unlimited:
    def acquire(self, event):
        from cloudtool.models import Cancelled
        if event.is_set():
            raise Cancelled()
    def defer(self, seconds):
        pass


def main():
    app = QApplication([])
    configure_app(app)
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    report = {"scale": os.environ.get("QT_SCALE_FACTOR", "1")}
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(Path(tmp))
        failures = []
        w.error = failures.append
        w.show()
        app.processEvents()
        transitions = []
        checks = 0
        for width, height in [(1120, 780), (1390, 940), (1600, 1000)]:
            w.resize(width, height)
            app.processEvents()
            for i in range(1, 13):
                previous = w.form_scrollers[w.forms.currentIndex()]
                previous.verticalScrollBar().setValue(previous.verticalScrollBar().maximum())
                started = time.perf_counter()
                w.nav.setCurrentRow(i)
                app.processEvents()
                transitions.append((time.perf_counter() - started) * 1000)
                scroll = w.form_scrollers[i - 1]
                assert scroll.verticalScrollBar().value() == 0, (i, "scroll carried over")
                assert w.operation_title.isVisible() and w.operation_hint.isVisible()
                assert w.inputs_scroll.horizontalScrollBar().maximum() == 0
                assert w.scope.viewport().height() >= 5 * w.scope.fontMetrics().lineSpacing() + 2 * w.scope.document().documentMargin()
                assert scroll.widget().width() <= scroll.viewport().width(), (i, "horizontal clipping", scroll.widget().width(), scroll.viewport().width())
                form = scroll.widget().findChild(QFormLayout)
                field_edges = []
                previous_bottom = -1
                for row in range(form.rowCount()):
                    left = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                    right = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                    if not left or not right or left.widget().isHidden():
                        continue
                    l, r = left.geometry(), right.geometry()
                    assert left.widget().width() == 116, (i, row, "label width")
                    assert l.right() < r.left(), (i, row, "label overlaps control")
                    assert r.right() <= scroll.widget().width(), (i, row, "field overflows")
                    assert r.top() > previous_bottom, (i, row, "row overlap")
                    previous_bottom = max(l.bottom(), r.bottom())
                    field_edges.append(r.left())
                assert len(set(field_edges)) <= 1, (i, field_edges)
                checks += 1
                if width == 1390:
                    w.grab().save(str(output / f"page-{i:02d}.png"))
        report.update(layout_page_size_checks=checks, max_page_switch_ms=round(max(transitions), 2))
        w.resize(1390, 940)
        guide = GuideDialog(w)
        guide.show()
        app.processEvents()
        assert guide.browser.horizontalScrollBar().maximum() == 0
        guide.grab().save(str(output / "token-guide.png"))
        assert guide.browser.document().toPlainText().count("DNS") >= 2
        guide.close()
        token = TokenDialog(w)
        token.show()
        app.processEvents()
        token.grab().save(str(output / "add-token.png"))
        token.close()
        w.nav.setCurrentRow(3)
        w.grab().save(str(output / "replace.png"))

        # Use the actual executor, audit store and Worker, with HTTP mocked only.
        calls = []
        def handler(req):
            time.sleep(0.004)
            calls.append(req.method)
            return httpx.Response(200, json={"success": True, "result": {"id": "mock"}})
        w.client = Client("MOCK_ONLY", transport=httpx.MockTransport(handler), global_limiter=Unlimited())
        w.client.limiter = Unlimited()
        w.store = Store(Path(tmp) / "tokens", w.client.key)
        w.provider = Cloudflare(w.client, w.store)
        actions = [Action(f"zone-{i % 8}.example", "POST", "/zones", {"name": f"test-{i}.example"}) for i in range(320)]
        w.plan_ready(Plan(w.client.key, actions))
        original_plan = w.plan
        beats = []
        navigation = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
        heartbeat.start()
        switcher = QTimer()
        switcher.setInterval(45)
        def switch():
            i = (w.nav.currentRow() % 12) + 1
            start = time.perf_counter()
            w.nav.setCurrentRow(i)
            navigation.append((time.perf_counter() - start) * 1000)
        switcher.timeout.connect(switch)
        switcher.start()
        w.start_job(lambda emit: execute(w.client, w.store, original_plan, 4, emit), w.executed, "Mock execution")
        assert w.nav.isEnabled() and w.scope.isReadOnly()
        deadline = time.perf_counter() + 30
        while w.busy and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.002)
        app.processEvents()
        assert not w.busy and not failures, failures
        assert len(calls) == 320
        assert w.plan is original_plan, "navigation invalidated running plan"
        assert w.progress.value() == 320
        assert all(r["state"] == "成功" for r in w.plan_model.rows)
        gaps = [(b-a)*1000 for a,b in zip(beats, beats[1:])]
        assert len(beats) > 10 and max(gaps) < 350, (len(beats), max(gaps))
        report.update(real_executor_mock_requests=320, execution_heartbeat_max_gap_ms=round(max(gaps), 2), execution_page_switches=len(navigation))

        # Stress the state-notification path without sending Cloudflare requests.
        actions = [Action(f"z-{i}.example", "POST", "/zones") for i in range(20000)]
        w.plan_ready(Plan(w.client.key, actions))
        beats.clear()
        def storm(emit):
            for n, action in enumerate(actions):
                emit(action.id, "执行中", "working")
                emit(action.id, "成功", "done")
                if n % 100 == 0:
                    time.sleep(0.002)
        w.start_job(storm, w.executed, "Stress status updates")
        deadline = time.perf_counter() + 20
        while w.busy and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert not w.busy
        assert w.progress.value() == 20000
        assert all(r["state"] == "成功" for r in w.plan_model.rows)
        gaps = [(b-a)*1000 for a,b in zip(beats, beats[1:])]
        report.update(status_notifications=40000, stress_heartbeat_max_gap_ms=round(max(gaps), 2))
        assert max(gaps) < 350, max(gaps)
        heartbeat.stop()
        switcher.stop()
        w.close()
        app.processEvents()
    (output / "ui-regression.json").write_text(json.dumps(report, indent=2), "utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
