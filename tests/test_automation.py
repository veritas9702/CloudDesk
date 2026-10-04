"""Workflow integration tests with real provider planning and isolated fake APIs."""
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from cloudtool.automation import OnboardingController
from cloudtool.automation_model import WorkflowOptions, Site, parse_sites
from cloudtool.cloudflare import Cloudflare
from cloudtool.storage import Store
from cloudtool.models import ApiError, Cancelled

ACCOUNT = 'a' * 32


class FakeCloudflare:
    key = 'a' * 64
    def __init__(self):
        self.cancel = threading.Event(); self.zones = {}; self.records = {}; self.writes = []
        self.fail = ''; self.unknown = False
    def safe(self, value): return str(value)
    def all(self, path, params=None, **kwargs):
        if path == '/zones': return [z.copy() for z in self.zones.values() if z['name'] == params['name']]
        return self.records.get(path, [])
    def get(self, path): return {'id': path.split('/')[-1], 'value': 'off', 'editable': True}
    def request(self, method, path, body=None):
        self.writes.append((method, path, body))
        if self.fail and self.fail in path: raise ApiError('mock failure', uncertain=self.unknown)
        if path == '/zones':
            name = body['name']
            self.zones[name] = dict(id=name, name=name, type='full', account={'id': ACCOUNT}, status='pending', name_servers=['a.ns.cloudflare.com', 'b.ns.cloudflare.com'])
        if path.endswith('/dns_records'):
            self.records.setdefault(path, []).append(dict(body, id=str(len(self.writes))))
        return {'result': {'ok': True}}


class FakeRegistrar:
    key = 'b' * 64
    def __init__(self): self.ns = ['old.example.net']; self.writes = []; self.cancel = threading.Event()
    def all(self, *args): return [{'ym': 'example.com', 'ymdns': ','.join(self.ns)}]
    def safe(self, value): return str(value)
    def request(self, method, path, body):
        self.writes.append(body); self.ns = body['dns'].split(','); return {'result': True}


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.client = FakeCloudflare(); self.store = Store(Path(self.temp.name), self.client.key)
        self.addCleanup(self.store.close)
        self.registrar = FakeRegistrar()
        self.controller = OnboardingController(self.client, self.store, Cloudflare(self.client, self.store), self.registrar)
        self.options = WorkflowOptions(ACCOUNT, (Site('example.com', '192.0.2.1'),), ssl='strict', registrar=self.registrar.key)
    def run_plan(self, plan):
        events = {}; self.controller.run(plan, 2, lambda aid, state, detail: events.update({aid:(state,detail)}))
        return {a.path: events[a.id][0] for a in plan.steps}
    def test_preview_has_no_writes_then_orders_dns_before_ns(self):
        preview = self.controller.preview(self.options)
        self.assertEqual(self.client.writes, []); self.assertEqual(self.registrar.writes, [])
        self.assertEqual(self.run_plan(preview), dict(zone='成功', dns='成功', settings='成功', ns='成功'))
        self.assertEqual(self.client.writes[0][1], '/zones')
        self.assertEqual(len(self.registrar.writes), 1)
        self.assertTrue(any('/dns_records' in r[1] for r in self.client.writes))
        with self.assertRaises(ValueError): self.run_plan(preview)
    def test_failure_stops_ns_and_settings(self):
        preview = self.controller.preview(self.options); self.client.fail = '/dns_records'
        states = self.run_plan(preview)
        self.assertEqual(states['dns'], '失败'); self.assertEqual(states['ns'], '未执行')
        self.assertEqual(self.registrar.writes, [])
    def test_uncertain_creation_never_changes_ns(self):
        preview = self.controller.preview(self.options); self.client.fail = '/zones'; self.client.unknown = True
        self.assertEqual(self.run_plan(preview)['zone'], '结果未知'); self.assertEqual(self.registrar.writes, [])
    def test_failed_domain_does_not_stop_other_domains(self):
        self.controller = OnboardingController(self.client, self.store, Cloudflare(self.client, self.store))
        options = replace(self.options, registrar='', sites=(Site('example.com', '192.0.2.1'), Site('example.net', '192.0.2.2')))
        preview = self.controller.preview(options); self.client.fail = '/zones/example.com/dns_records'
        events = {}
        self.controller.run(preview, 2, lambda aid, state, detail: events.update({aid:state}))
        self.assertEqual([events[a.id] for a in preview.steps if a.target=='example.net'], ['成功', '成功', '成功', '待手动'])
        self.assertEqual([events[a.id] for a in preview.steps if a.target=='example.com'][-1], '未执行')
    def test_ns_drift_prevents_overwrite(self):
        preview = self.controller.preview(self.options); self.registrar.ns = ['changed.example.net']
        self.assertEqual(self.run_plan(preview)['ns'], '失败'); self.assertEqual(self.registrar.writes, [])
    def test_manual_ns_and_reuse_without_zone_creation(self):
        self.client.request('POST', '/zones', {'name': 'example.com'})
        self.client.writes.clear()
        self.controller = OnboardingController(self.client, self.store, Cloudflare(self.client, self.store))
        preview = self.controller.preview(replace(self.options, registrar=''))
        self.assertEqual(self.run_plan(preview)['ns'], '待手动')
        self.assertFalse(any(path == '/zones' for _, path, _ in self.client.writes))
    def test_ownership_expiry_and_cancellation(self):
        preview = self.controller.preview(self.options)
        with self.assertRaises(ValueError): self.run_plan(replace(preview, owner='c'*64))
        with self.assertRaises(ValueError): self.run_plan(replace(preview, created=0))
        self.client.cancel.set()
        with self.assertRaises(Cancelled): self.run_plan(preview)
        self.assertEqual(self.client.writes, [])
        self.assertTrue(all(r['state'] == '未执行' for r in self.store.history()))
    def test_input_modes_and_duplicate_rejection(self):
        sites = parse_sites('example.com\nexample.net', '循环解析值', '192.0.2.1\n192.0.2.2')
        self.assertEqual(sites[1].value, '192.0.2.2')
        self.assertEqual(parse_sites('example.com,192.0.2.1', '逐行配对', '')[0], sites[0])
        with self.assertRaises(ValueError): replace(self.options, sites=(sites[0], sites[0])).validate()


if __name__ == '__main__': unittest.main()
