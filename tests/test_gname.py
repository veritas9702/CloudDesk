import ast
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs
import httpx
from cloudtool.gname.models import MODES, Record, parse_records
from cloudtool.gname.client import GnameClient, signed, credential
from cloudtool.gname.controller import GnameController
from cloudtool.models import ApiError, Plan, Action, Cancelled, fingerprint
from cloudtool.storage import Store


class GnameTests(unittest.TestCase):
    def test_official_signature_vector_and_encoding(self):
        params = dict(ym='example.com', value='https://www.example.com')
        # Official prose and PHP code agree; its inline sample hash is stale.
        # This value is independently checked with Windows .NET MD5 on stringB.
        self.assertEqual(signed(params, 'APPID', 'APPKEY', 1234567890)['gntoken'], 'DE70497258244DF6EED2E6BA7579258C')
        expected = 'appid=id&gntime=1&v=%E4%B8%AD+%26%2B%7Ekey'
        self.assertEqual(signed({'v':' 中 &+~ '},'id','key',1)['gntoken'], hashlib.md5(expected.encode()).hexdigest().upper())

    def test_four_modes_and_multi_hosts(self):
        self.assertEqual(len(parse_records('a.com\nb.com', MODES[0], 'www,@', values='192.0.2.1')), 4)
        self.assertEqual(parse_records('a.com|@|MX|mx.a.com|8', MODES[1])[0].mx, 8)
        self.assertEqual(parse_records('a.com,"hello,world"', MODES[2], kind='TXT')[0].value, 'hello,world')
        records = parse_records('a.com\nb.com\nc.com', MODES[3], values='192.0.2.1\n192.0.2.2')
        self.assertEqual([r.value for r in records], ['192.0.2.1','192.0.2.2','192.0.2.1'])

    def test_validation_dedup_and_cname_conflicts(self):
        self.assertEqual(len(parse_records('a.com\na.com', MODES[0], values='192.0.2.1')), 1)
        for text in ('a.com|www|CNAME|b.com\na.com|www|A|192.0.2.1', 'a.com|www|A|bad', 'https://a.com|@|TXT|x'):
            with self.assertRaises(ValueError): parse_records(text, MODES[1])

    def client(self, handler):
        client = GnameClient('APPID', 'SECRET', transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        client.limiter.acquire = lambda _: None
        return client

    @patch('cloudtool.gname.client.GNAME_LIMITER.acquire')
    def test_transport_signed_form_and_pagination(self, _):
        seen = []
        def handler(request):
            p = {k:v[0] for k,v in parse_qs(request.content.decode()).items()}
            seen.append(p)
            self.assertEqual(request.url.scheme, 'https')
            self.assertNotIn('SECRET', request.content.decode())
            signature = p.pop('gntoken')
            self.assertEqual(signature, signed({k:v for k,v in p.items() if k not in ('appid','gntime')}, 'APPID','SECRET',int(p['gntime']))['gntoken'])
            return httpx.Response(200, json={'code':1,'data':[{'id':p['page']}], 'count':2,'pagesize':1})
        client = self.client(handler)
        self.assertEqual(len(client.all('/api/domain/list')), 2)
        self.assertEqual([r['page'] for r in seen], ['1','2'])

    @patch('cloudtool.gname.client.GNAME_LIMITER.acquire')
    def test_unknown_write_never_retried(self, _):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout('SECRET')
        client = self.client(handler)
        with self.assertRaises(ApiError) as raised: client.request('POST','/api/resolution/add',{})
        self.assertTrue(raised.exception.uncertain)
        self.assertNotIn('SECRET', str(raised.exception))
        self.assertEqual(len(calls), 1)

    @patch('cloudtool.gname.client.GNAME_LIMITER.acquire')
    def test_repeated_page_rejected(self, _):
        client = self.client(lambda r: httpx.Response(200,json={'code':1,'data':[{'id':1}],'count':3}))
        with self.assertRaisesRegex(ApiError, '重复'): client.all('/api/domain/list')

    def test_layers_no_qt_or_cloudflare(self):
        root = Path(__file__).parents[1] / 'cloudtool/gname'
        for filename in ('models.py','client.py','controller.py'):
            tree = ast.parse((root/filename).read_text('utf-8'))
            imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            imports += [v.name for n in ast.walk(tree) if isinstance(n, ast.Import) for v in n.names]
            self.assertFalse(any('PySide' in v or v.endswith('ui') or v == 'cloudflare' for v in imports))


class FakeClient:
    def __init__(self):
        self.key = fingerprint(credential('id','key'))
        self.cancel = threading.Event()
        self.rows = [{'id':1,'zjt':'www','lx':'A','jxz':'192.0.2.1','mx':0,'xlid':'0'}]
        self.calls = []
    def all(self, path, params=None): return [dict(r) for r in self.rows]
    def safe(self, exc): return str(exc)
    def request(self, method, path, body):
        self.calls.append((path, body)); return {'result':'ok'}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = FakeClient()
        self.store = Store(Path(self.temp.name)/'gname', self.client.key)
        self.controller = GnameController(self.client, self.store)
    def tearDown(self):
        self.store.close(); self.temp.cleanup()
    def test_conflict_previews_delete_first_and_guard(self):
        desired = (Record('a.com','www','A','192.0.2.2'),)
        with self.assertRaises(ValueError): self.controller.preview_job(desired)(None)
        plan = self.controller.preview_job(desired, True)(None)
        self.assertEqual([a.path for a in plan.actions], ['/api/resolution/delete','/api/resolution/add'])
        self.client.rows[0]['jxz'] = '192.0.2.9'
        self.controller.execute_job(plan)(lambda *args: None)
        self.assertEqual(self.client.calls, [])
        self.assertEqual({r['state'] for r in self.store.history()}, {'失败','未执行'})
    def test_exact_desired_preserved_when_adding_another_value(self):
        records = (Record('a.com','www','A','192.0.2.1'), Record('a.com','www','A','192.0.2.2'))
        plan = self.controller.preview_job(records, True)(None)
        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].path, '/api/resolution/add')
    def test_execute_once_and_wrong_owner(self):
        plan = self.controller.preview_job((Record('a.com','www','A','192.0.2.2'),), True)(None)
        self.controller.execute_job(plan)(lambda *args: None)
        with self.assertRaises(ValueError): self.controller.execute_job(plan)(lambda *args: None)
        plan.owner = 'other'
        with self.assertRaises(ValueError): self.controller.execute_job(plan)(lambda *args: None)
    def test_cancellation_and_isolation(self):
        other = Store(Path(self.temp.name)/'other', fingerprint('other'))
        try:
            with self.assertRaises(ValueError): GnameController(self.client, other)
            plan = self.controller.preview_job((Record('a.com','www','A','192.0.2.2'),), True)(None)
            self.client.cancel.set()
            with self.assertRaises(Cancelled): self.controller.execute_job(plan)(lambda *args: None)
            self.assertEqual(other.history(), [])
            self.assertEqual(self.client.calls, [])
        finally: other.close()


if __name__ == '__main__': unittest.main()
