"""Offscreen GUI smoke; uses only fake tokens, reserved domains and MockTransport."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx
from PySide6.QtWidgets import QApplication, QPlainTextEdit
from cloudtool.ui import Window, configure_app
from cloudtool.models import Plan, Action
from cloudtool.storage import Store
from cloudtool.api_client import Client
from cloudtool.cloudflare import Cloudflare


def run():
    app = QApplication([])
    configure_app(app)
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(Path(tmp))
        failures = []
        w.error = failures.append
        p = w.vault.add("演示配置 · 不连接真实账户", "DEMO_FAKE_TOKEN_A", "demo-password-123")
        p2 = w.vault.add("隔离测试 B", "DEMO_FAKE_TOKEN_B", "demo-password-123")
        w.unlocked_passwords = {p["id"]: "demo-password-123", p2["id"]: "demo-password-123"}
        w.load_profiles(p["id"])
        assert w.client.key == p["id"]
        rows = [{"id": str(i).zfill(32), "name": f"project-{i}.example.com", "status": "active" if i % 3 else "pending", "account": {"name": "演示 Account", "id": "a"*32}, "name_servers": ["alice.ns.cloudflare.com", "bob.ns.cloudflare.com"]} for i in range(1, 7)]
        w.zones_ready(rows)
        w.show()
        app.processEvents()
        target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tmp)
        target.mkdir(parents=True, exist_ok=True)
        w.grab().save(str(target / "界面-域名.png"))
        for i in range(1, 13):
            w.nav.setCurrentRow(i)
            app.processEvents()
            assert w.forms.currentIndex() == i - 1
        w.nav.setCurrentRow(2)
        w.zone_table.selectAll()
        w.scope.setPlainText("project-1.example.com\nproject-2.example.com")
        w.dns_content.setText("192.0.2.10")
        w.dns_proxy.setChecked(True)
        plan = Plan(w.client.key, [Action(z["name"], "POST", "/zones/" + z["id"] + "/dns_records", {"type": "A", "name": z["name"], "content": "192.0.2.10", "ttl": 1, "proxied": True}, summary="添加 A @ → 192.0.2.10") for z in rows[:2]])
        w.plan_ready(plan)
        app.processEvents()
        w.grab().save(str(target / "界面-DNS批量.png"))
        w.tokens.setCurrentIndex(1)
        app.processEvents()
        assert w.plan is None
        assert w.zone_model.rowCount() == 0
        assert w.scope.toPlainText() == ""
        assert w.dns_content.text() == ""
        assert w.history_model.rowCount() == 0
        assert w.client.key != p["id"]
        # Worker lifecycle and event loop responsiveness on a delayed, mocked read.
        w.client.close()
        def handler(req):
            time.sleep(0.15)
            return httpx.Response(200, json={"success": True, "result": rows, "result_info": {"total_pages": 1}})
        w.client = Client("DEMO_FAKE_TOKEN_B", transport=httpx.MockTransport(handler))
        w.provider = Cloudflare(w.client, w.store)
        w.refresh_zones()
        ticks = 0
        deadline = time.monotonic() + 5
        while w.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
            ticks += 1
        assert not w.busy and len(w.zones_data) == 6
        assert ticks > 10, ticks
        assert not failures, failures
        w.close()
        app.processEvents()
        print(json.dumps({"forms": 12, "token_switch_isolated": True, "background_read_ui_ticks": ticks, "screenshots": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    run()
