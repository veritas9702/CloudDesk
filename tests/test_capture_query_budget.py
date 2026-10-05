import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cloudtool.crawler.controller import CaptureController
from cloudtool.crawler.models import Settings
from cloudtool.crawler.repository import Repository


class CaptureQueryBudgetTests(unittest.TestCase):
    def test_metadata_does_not_aggregate_url_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repository(Path(tmp)/'state')
            try:
                queries = []
                repo.db.set_trace_callback(queries.append)
                self.assertEqual(repo.tasks(metrics=False), [])
                self.assertEqual(len(queries), 1)
                self.assertNotIn('urls', queries[0].lower())
            finally:
                repo.close()

    def test_prepare_resolves_redirect_aliases_with_constant_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controller = CaptureController(root/'state')
            keys = controller.create('\n'.join(f'https://s{i}.test/' for i in range(100)), str(root/'out'), Settings())
            repo = Repository(root/'state')
            repo.db.execute('UPDATE urls SET final_url=? WHERE task=?', ('https://redirect.test/', keys[0]))
            repo.db.commit(); repo.close()
            queries = []
            connect = sqlite3.connect
            def traced(*args, **kwargs):
                db = connect(*args, **kwargs)
                db.set_trace_callback(queries.append)
                return db
            with patch('cloudtool.crawler.repository.sqlite3.connect', side_effect=traced):
                ids, skipped, rows = controller.prepare('https://redirect.test/', str(root/'out'), Settings())
            self.assertEqual(ids, [keys[0]])
            self.assertEqual(len(rows), 100)
            alias_queries = [q for q in queries if q.lstrip().upper().startswith('SELECT') and 'final_url' in q]
            # Once to resolve input, once to present the final snapshot, not per task.
            self.assertEqual(len(alias_queries), 2)

    def test_deferred_controller_does_not_open_storage(self):
        with patch('cloudtool.crawler.controller.Repository', side_effect=AssertionError('GUI opened storage')):
            CaptureController('unused', recover=False)
