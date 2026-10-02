"""Regression checks for layer boundaries and immutable background input."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from cloudtool.operations import OperationsController
from cloudtool.permissions import PHASES, RULE_PERMISSIONS, manual_permission_rows, preset_for
from cloudtool.guidance import PERMISSIONS

class LayerTests(unittest.TestCase):
    def test_lower_layers_do_not_import_ui_or_compatibility_facade(self):
        root = Path(__file__).resolve().parents[1] / 'cloudtool'
        for name in ('models', 'credentials', 'storage', 'api_client', 'execution', 'cloudflare', 'operations', 'permissions', 'token_templates', 'public_ip', 'browser_token_model', 'browser_launcher', 'extension_setup'):
            tree = ast.parse((root / (name + '.py')).read_text('utf-8'))
            modules = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(any(m.startswith('PySide6') or m in {'ui', 'guidance', 'browser_token_ui', 'token_view_ui', 'public_ip_ui'} for m in modules), name)

    def test_controller_rejects_mixed_token(self):
        with self.assertRaises(ValueError):
            OperationsController(SimpleNamespace(key='one'), SimpleNamespace(key='two'), None)

    def test_job_owns_input_snapshot_and_rereads_zone(self):
        calls = []
        client = SimpleNamespace(key='one', get=lambda path: calls.append(path) or {'id':'zone', 'name':'fresh.example'})
        provider = SimpleNamespace(plan=lambda zones, op, opts, workers: (zones, op, opts, workers))
        controller = OperationsController(client, SimpleNamespace(key='one'), provider)
        selected = [{'id':'zone', 'name':'old.example'}]
        options = {'record': {'content':'original'}}
        job = controller.preview_job(([], selected), 'dns_add', options, 4)
        selected[0]['id'] = 'changed'
        options['record']['content'] = 'changed'
        zones, op, opts, workers = job(None)
        self.assertEqual(calls, ['/zones/zone'])
        self.assertEqual(zones[0]['name'], 'fresh.example')
        self.assertEqual(opts['record']['content'], 'original')

    def test_permission_registry_is_shared(self):
        self.assertEqual(set(PHASES), set(RULE_PERMISSIONS))
        for row in manual_permission_rows():
            self.assertIn(row, PERMISSIONS)
        self.assertEqual(preset_for(('zones','dns')), 'DNS 基础')
        self.assertEqual(preset_for(('zones','dns','accounts')), '自定义')

if __name__ == '__main__': unittest.main()
