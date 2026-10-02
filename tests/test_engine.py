import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import httpx

from cloudtool.models import Action, Plan, ApiError, Cancelled, fingerprint
from cloudtool.credentials import Vault
from cloudtool.storage import Store
from cloudtool.api_client import Client, RateLimiter
from cloudtool.execution import execute, bounded_map
from cloudtool.cloudflare import Cloudflare, domains, dns_payload, parse_records


class FastLimiter:
    def __init__(self):
        self.delays = []

    def acquire(self, cancel):
        if cancel.is_set():
            raise Cancelled()

    def defer(self, value):
        self.delays.append(value)


def response(result, **kwargs):
    return httpx.Response(200, json={"success": True, "result": result, **kwargs})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.resources = []

    def tearDown(self):
        for obj in reversed(self.resources):
            obj.close()
        self.temp.cleanup()

    def client(self, handler, token="TOKEN_A"):
        c = Client(token, transport=httpx.MockTransport(handler), global_limiter=FastLimiter())
        c.limiter = FastLimiter()
        self.resources.append(c)
        return c

    def store(self, token="TOKEN_A"):
        s = Store(self.root, fingerprint(token))
        self.resources.append(s)
        return s

    def test_token_database_and_headers_are_isolated(self):
        seen = []
        def handler(req):
            seen.append(req.headers["Authorization"])
            return response([])
        a, b = self.client(handler), self.client(handler, "TOKEN_B")
        sa, sb = self.store(), self.store("TOKEN_B")
        sa.cache("zones", [{"name": "a.example"}])
        sb.cache("zones", [{"name": "b.example"}])
        a.get("/zones")
        b.get("/zones")
        self.assertEqual(seen, ["Bearer TOKEN_A", "Bearer TOKEN_B"])
        self.assertNotEqual(sa.path, sb.path)
        self.assertEqual(sa.cached("zones")[0]["name"], "a.example")
        self.assertEqual(sb.cached("zones")[0]["name"], "b.example")
        with self.assertRaises(ValueError):
            execute(b, sb, Plan(a.key, [Action("x", "DELETE", "/zones/x")]), 2, lambda *x: None)
        self.assertEqual(sb.history(), [])

    def test_encrypted_vault_and_duplicate_token(self):
        vault = Vault(self.root)
        p = vault.add("A", "private-secret-token", "strong-password-123")
        self.assertEqual(vault.token(p, "strong-password-123"), "private-secret-token")
        with self.assertRaises(ValueError):
            vault.token(p, "wrong-password")
        self.assertNotIn("private-secret-token", vault.path.read_text("utf-8"))
        with self.assertRaises(ValueError):
            vault.add("duplicate", "private-secret-token", "strong-password-123")

    def test_pagination_all_pages(self):
        pages = []
        def handler(req):
            page = int(req.url.params["page"])
            pages.append(page)
            return response([{"id": page}], result_info={"total_pages": 3})
        self.assertEqual(len(self.client(handler).all("/zones")), 3)
        self.assertEqual(pages, [1, 2, 3])

    def test_429_uses_retry_after(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"success": False}) if len(seen) == 1 else response({"id": "ok"})
        c = self.client(handler)
        self.assertEqual(c.request("POST", "/zones", {})["result"]["id"], "ok")
        self.assertEqual(c.limiter.delays, [7.0])
        self.assertEqual(c.global_limiter.delays, [7.0])

    def test_write_timeout_not_replayed(self):
        seen = []
        def handler(req):
            seen.append(req)
            raise httpx.ReadTimeout("timeout", request=req)
        c = self.client(handler)
        with self.assertRaises(ApiError) as err:
            c.request("POST", "/zones", {})
        self.assertTrue(err.exception.uncertain)
        self.assertEqual(len(seen), 1)

    def test_write_5xx_not_replayed(self):
        calls = []
        c = self.client(lambda req: calls.append(req) or httpx.Response(503))
        with self.assertRaises(ApiError) as err:
            c.request("PATCH", "/zones/x/settings/ssl", {"value": "strict"})
        self.assertTrue(err.exception.uncertain)
        self.assertEqual(len(calls), 1)

    def test_403_not_retried_and_secret_redacted(self):
        calls = []
        c = self.client(lambda req: calls.append(req) or httpx.Response(403, json={"success": False, "errors": [{"message": "TOKEN_A denied"}]}))
        with self.assertRaises(ApiError) as err:
            c.get("/zones")
        self.assertNotIn("TOKEN_A", str(err.exception))
        self.assertEqual(len(calls), 1)

    def test_cancel_before_request(self):
        calls = []
        c = self.client(lambda req: calls.append(req) or response([]))
        c.cancel.set()
        with self.assertRaises(Cancelled):
            c.get("/zones")
        self.assertEqual(calls, [])

    def test_limiter_bounds_and_cancel(self):
        limiter = RateLimiter(40)
        cancel = threading.Event()
        start = time.monotonic()
        for _ in range(5):
            limiter.acquire(cancel)
        self.assertGreaterEqual(time.monotonic() - start, 0.095)
        limiter.defer(20)
        timer = threading.Timer(0.02, cancel.set)
        timer.start()
        with self.assertRaises(Cancelled):
            limiter.acquire(cancel)
        timer.join()

    def test_guard_prevents_stale_write(self):
        calls = []
        c = self.client(lambda req: calls.append(req.method) or response({"value": "changed"}))
        s = self.store()
        a = Action("example.com", "PATCH", "/zones/x/settings/ssl", {"value": "strict"}, {"value": "full"}, "/zones/x/settings/ssl")
        execute(c, s, Plan(c.key, [a]), 2, lambda *x: None)
        self.assertEqual(calls, ["GET"])
        self.assertEqual(s.history()[0]["state"], "失败")

    def test_same_zone_failure_stops_remaining_other_zone_continues(self):
        calls = []
        def handler(req):
            calls.append(req.url.path)
            if req.url.path.endswith("bad"):
                return httpx.Response(403, json={"success": False, "errors": []})
            return response({})
        c, s = self.client(handler), self.store()
        actions = [Action("a", "POST", "/zones/bad"), Action("a", "POST", "/zones/skipped"), Action("b", "POST", "/zones/good")]
        execute(c, s, Plan(c.key, actions), 2, lambda *x: None)
        self.assertNotIn("/client/v4/zones/skipped", calls)
        self.assertEqual({r["state"] for r in s.history()}, {"失败", "未执行", "成功"})

    def test_crash_recovery_marks_unknown_without_replay(self):
        s = self.store()
        s.record(Action("x", "POST", "/zones"), "batch", "执行中")
        s.record(Action("y", "POST", "/zones"), "batch", "等待中")
        s2 = self.store()
        self.assertEqual({r["state"] for r in s2.history()}, {"结果未知", "未执行"})

    def test_expired_plan_rejected(self):
        c, s = self.client(lambda req: response([])), self.store()
        with self.assertRaises(ValueError):
            execute(c, s, Plan(c.key, [], created=time.time()-901), 1, lambda *x: None)

    def test_completed_plan_cannot_replay(self):
        calls = []
        c, s = self.client(lambda req: calls.append(req) or response({})), self.store()
        plan = Plan(c.key, [Action("example.com", "POST", "/zones")])
        execute(c, s, plan, 1, lambda *x: None)
        with self.assertRaises(ValueError):
            execute(c, s, plan, 1, lambda *x: None)
        self.assertEqual(len(calls), 1)

    def test_wrong_store_cannot_receive_other_token_history(self):
        c = self.client(lambda req: response({}))
        wrong_store = self.store("TOKEN_B")
        with self.assertRaises(ValueError):
            execute(c, wrong_store, Plan(c.key, [Action("x", "DELETE", "/zones/x")]), 1, lambda *x: None)
        self.assertEqual(wrong_store.history(), [])

    def test_history_summary_avoids_large_snapshots_but_detail_keeps_them(self):
        s = self.store()
        a = Action("example.com", "PATCH", "/zones/z", {"records": ["data"] * 10000}, {"previous": "snapshot"})
        s.record(a, "batch", "成功", "x" * 4000)
        summary = s.history(include_payload=False)[0]
        self.assertNotIn("body", summary)
        self.assertNotIn("before", summary)
        self.assertEqual(len(summary["detail"]), 300)
        detail = s.history_detail(summary["id"])
        self.assertEqual(len(json.loads(detail["body"])["records"]), 10000)
        self.assertEqual(json.loads(detail["before"]), {"previous": "snapshot"})

    def test_domain_and_csv_validation(self):
        self.assertEqual(domains("EXAMPLE.COM\nexample.com\n"), ["example.com"])
        with self.assertRaises(ValueError):
            domains("https://example.com")
        records = parse_records("zone,name,type,content,ttl,proxied\nexample.com,www,A,192.0.2.1,1,true")
        body = dns_payload(records[0], "example.com")
        self.assertEqual(body["name"], "www.example.com")
        self.assertIs(body["proxied"], True)
        with self.assertRaises(ValueError):
            dns_payload({"type": "AAAA", "content": "192.0.2.1"}, "example.com")

    def test_dns_add_plan_only_reads_and_skips_exact(self):
        old = {"id": "r1", "name": "www.example.com", "type": "A", "content": "192.0.2.1", "ttl": 1}
        calls = []
        c = self.client(lambda req: calls.append(req.method) or response([old], result_info={"total_pages": 1}))
        p = Cloudflare(c, self.store())
        plan = p.plan([{"id": "z", "name": "example.com"}], "dns_add", {"record": old})
        self.assertEqual(plan.actions, [])
        self.assertEqual(calls, ["GET"])

    def test_dns_upsert_ambiguous_rejected(self):
        old = {"id": "r1", "name": "www.example.com", "type": "A", "content": "192.0.2.1"}
        c = self.client(lambda req: response([old, {**old, "id": "r2"}], result_info={"total_pages": 1}))
        with self.assertRaises(ValueError):
            Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "dns_upsert", {"record": old})

    def test_import_scope_rejected(self):
        c = self.client(lambda req: response([]))
        with self.assertRaises(ValueError):
            Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "dns_add", {"records": '[{"zone":"another.com","content":"192.0.2.1"}]'})

    def test_proxy_skips_non_proxiable(self):
        data = [{"id": "a", "name": "example.com", "type": "A", "proxiable": True, "proxied": False},
                {"id": "txt", "name": "example.com", "type": "TXT", "proxiable": False}]
        c = self.client(lambda req: response(data, result_info={"total_pages": 1}))
        plan = Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "dns_proxy", {"proxied": True})
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].body, {"proxied": True})

    def test_settings_use_individual_endpoints(self):
        calls = []
        c = self.client(lambda req: calls.append(str(req.url)) or response({"value": "off", "editable": True}))
        plan = Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "settings", {"values": {"always_use_https": "on", "http3": "on"}})
        self.assertEqual(len(plan.actions), 2)
        self.assertTrue(all("/settings/" in x for x in calls))

    def test_deprecated_settings_blocked(self):
        c = self.client(lambda req: response({}))
        with self.assertRaises(ValueError):
            Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "settings", {"values": {"minify": {"js": "on"}}})

    def test_rules_append_preserves_existing_and_drops_metadata(self):
        old = {"id": "set", "phase": "http_request_firewall_custom", "rules": [{"id": "r1", "version": "2", "expression": "true", "action": "block", "enabled": True}]}
        c = self.client(lambda req: response(old))
        plan = Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "rules_add", {
            "kind": "规则集", "phase": "http_request_firewall_custom", "rules": [{"expression": "false", "action": "block"}]})
        self.assertEqual(len(plan.actions), 1)
        a = plan.actions[0]
        self.assertEqual(a.method, "PUT")
        self.assertEqual(len(a.body["rules"]), 2)
        self.assertEqual(a.body["rules"][0]["id"], "r1")
        self.assertNotIn("version", a.body["rules"][0])

    def test_purge_chunks_at_100(self):
        c = self.client(lambda req: response({}))
        plan = Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "purge", {"body": {"files": [f"https://example.com/{n}" for n in range(201)]}})
        self.assertEqual([len(a.body["files"]) for a in plan.actions], [100, 100, 1])

    def test_dns_native_batch_chunks_and_guard(self):
        records = [{"id": str(i), "type": "A", "name": f"r{i}.example.com", "content": "192.0.2.1", "proxied": False, "proxiable": True} for i in range(205)]
        calls = []
        def handler(req):
            calls.append(req.method)
            if req.method == "GET":
                return response(records, result_info={"total_pages": 1})
            return response({})
        c, s = self.client(handler), self.store()
        plan = Cloudflare(c, s).plan([{"id": "z", "name": "example.com"}], "dns_proxy", {"proxied": True, "dns_batch": True})
        self.assertEqual([len(a.body["patches"]) for a in plan.actions], [100, 100, 5])
        execute(c, s, plan, 4, lambda *x: None)
        self.assertEqual(calls.count("POST"), 3)
        self.assertEqual({r["state"] for r in s.history()}, {"成功"})

    def test_batch_stale_record_blocks_write(self):
        old = {"id": "r1", "name": "example.com", "type": "A", "content": "192.0.2.1"}
        calls = []
        c = self.client(lambda req: calls.append(req.method) or response([{**old, "content": "192.0.2.2"}], result_info={"total_pages": 1}))
        s = self.store()
        action = Action("example.com", "POST", "/zones/z/dns_records/batch", {"deletes": [{"id": "r1"}]}, [old], "/zones/z/dns_records", guard_kind="dns_batch")
        execute(c, s, Plan(c.key, [action]), 1, lambda *x: None)
        self.assertEqual(calls, ["GET"])
        self.assertEqual(s.history()[0]["state"], "失败")

    def test_custom_hostname_delete_uses_resolved_id(self):
        old = {"id": "h1", "hostname": "customer.example.com"}
        c = self.client(lambda req: response(old if req.url.path.endswith("h1") else [old], result_info={"total_pages": 1}))
        plan = Cloudflare(c, self.store()).plan([{"id": "z", "name": "example.com"}], "hostname_delete", {"payloads": [{"hostname": "customer.example.com"}]})
        self.assertTrue(plan.actions[0].path.endswith("/custom_hostnames/h1"))
        self.assertEqual(plan.actions[0].before, old)

    def test_bounded_concurrency_5000_items(self):
        lock = threading.Lock()
        active = maximum = 0
        def run(n):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.0001)
            with lock:
                active -= 1
            return n
        values = list(bounded_map(run, range(5000), 4, threading.Event()))
        self.assertEqual(set(values), set(range(5000)))
        self.assertLessEqual(maximum, 4)


if __name__ == "__main__":
    unittest.main()
