"""Durable URL frontier and capture history. One connection per controller job."""
import json
import sqlite3
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import contextmanager
from .models import site_folder, local_path
from .artifacts import workspace
from .paths import original_path, unique_path


class Repository:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'captures.sqlite3', timeout=20)
        self.db.row_factory = sqlite3.Row
        self.batch_depth = 0
        self.path_cache = {}
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, seed TEXT, output TEXT, settings TEXT,
              state TEXT, detail TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS urls (
              task TEXT, url TEXT, kind TEXT, depth INTEGER, path TEXT,
              state TEXT DEFAULT 'pending', size INTEGER DEFAULT 0,
              hash TEXT DEFAULT '', mime TEXT DEFAULT '', final_url TEXT DEFAULT '',
              error TEXT DEFAULT '', PRIMARY KEY(task,url));
            CREATE INDEX IF NOT EXISTS frontier ON urls(task,state,kind);
            CREATE INDEX IF NOT EXISTS claim_order ON urls(task,state,CASE kind WHEN 'asset' THEN 0 ELSE 1 END,depth);
            CREATE INDEX IF NOT EXISTS content_lookup ON urls(task,hash,mime,state);
            CREATE TABLE IF NOT EXISTS warnings (
              task TEXT, message TEXT, UNIQUE(task,message));
        ''')
        columns = {r[1] for r in self.db.execute('PRAGMA table_info(tasks)')}
        for name, declaration in (('purge_pending', 'INTEGER DEFAULT 0'), ('deleted', 'INTEGER DEFAULT 0'), ('revision', 'INTEGER DEFAULT 0'), ('work', "TEXT DEFAULT ''"), ('published', 'INTEGER DEFAULT 0'),
                                  ('started_at', 'TEXT'), ('ended_at', 'TEXT'),
                                  ('elapsed_seconds', 'REAL'), ('transferred_bytes', 'INTEGER DEFAULT 0')):
            if name not in columns:
                self.db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {declaration}')
        self.db.commit()
        self.db.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)')
        if 'required_style' not in {r[1] for r in self.db.execute('PRAGMA table_info(urls)')}:
            self.db.execute('ALTER TABLE urls ADD COLUMN required_style INTEGER DEFAULT 0')
        self.db.commit()

    def require_style(self, key, url):
        self.db.execute('UPDATE urls SET required_style=1 WHERE task=? AND url=?', (key, url))
        if not self.batch_depth:
            self.db.commit()

    def preference(self, key, value=None):
        if value is not None:
            self.db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)', (key, value))
            self.db.commit()
        row = self.db.execute('SELECT value FROM preferences WHERE key=?', (key,)).fetchone()
        return row[0] if row else ''

    @staticmethod
    def pending_input(root, text=None):
        """Small atomic draft file avoids contending with the download database."""
        path = Path(root) / 'pending-input.json'
        if text is not None:
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(text, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
            return text
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))

    def save_metrics(self, key, values, ended_at=None):
        self.db.execute('UPDATE tasks SET started_at=?,elapsed_seconds=?,transferred_bytes=?,ended_at=? WHERE id=?',
                        (values['started_at'], values['elapsed_seconds'], values['transferred_bytes'], ended_at, key))
        self.db.commit()

    def close(self):
        self.db.close()

    def create(self, urls, output, settings):
        parent = Path(output).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        ids = []
        for url in urls:
            key = uuid4().hex
            folder = parent / site_folder(url, key)
            work = workspace(folder, key)
            work.mkdir(parents=True, exist_ok=False)
            self.db.execute('INSERT INTO tasks(id,seed,output,settings,state,detail,created) VALUES(?,?,?,?,?,?,?)',
                            (key, url, str(folder), json.dumps(settings), '等待', '', datetime.now(timezone.utc).isoformat()))
            self.set_work(key, str(work), False)
            self.add(key, url, 'page', 0, url)
            ids.append(key)
        self.db.commit()
        return ids

    def tasks(self, include_deleted=False):
        tasks = [dict(r) for r in self.db.execute('SELECT * FROM tasks ' + ('' if include_deleted else 'WHERE deleted=0 ') + 'ORDER BY created DESC')]
        aliases = {r['task']: r['final_url'] for r in self.db.execute('SELECT u.task,u.final_url FROM urls u JOIN tasks t ON t.id=u.task AND t.seed=u.url WHERE u.final_url != ?',( '',))}
        sizes = {r['task']: r['bytes'] for r in self.db.execute("SELECT task,SUM(size) AS bytes FROM (SELECT task,path,MAX(size) AS size FROM urls WHERE state='done' GROUP BY task,path) GROUP BY task")}
        for task in tasks:
            task['template_bytes'] = sizes.get(task['id'], 0)
            task['aliases'] = [aliases[task['id']]] if task['id'] in aliases else []
        return tasks

    def task(self, key):
        return dict(self.db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone())

    def update_task(self, key, state, detail=''):
        self.db.execute('UPDATE tasks SET state=?,detail=?,revision=revision+1,ended_at=CASE WHEN ? IN (?,?,?) THEN NULL ELSE ended_at END WHERE id=?', (state, detail, state, '等待', '采集中', '整理中', key))
        self.db.commit()

    def delete_task(self, key):
        # Keep the identity and saved-file ledger for deduplication; hide the task.
        self.db.execute('UPDATE tasks SET deleted=1,purge_pending=1,revision=revision+1 WHERE id=?', (key,))
        self.db.commit()

    def set_work(self, key, path, published):
        self.db.execute('UPDATE tasks SET work=?,published=? WHERE id=?', (path, int(published), key))
        self.db.commit()

    def upgrade_settings(self, key, overrides=None):
        values = json.loads(self.task(key)['settings'])
        if overrides:
            values.update({k: v for k, v in overrides.items() if k not in ('lightweight', 'layout')})
        values.update(budget=None, depth=max(1, min(3, values['depth'])), policy_version=2)
        self.db.execute('UPDATE tasks SET settings=? WHERE id=?', (json.dumps(values), key))
        self.db.commit()
        return values

    def clear_warnings(self, key):
        self.db.execute('DELETE FROM warnings WHERE task=?', (key,))
        self.db.commit()

    def rows(self, key):
        return [dict(r) for r in self.db.execute('SELECT * FROM urls WHERE task=?', (key,))]

    def add(self, key, url, kind, depth, seed):
        if key not in self.path_cache:
            layout = json.loads(self.task(key)['settings']).get('layout', 'hashed')
            paths = {r['url']: r['path'] for r in self.rows(key)}
            occupied = {p.casefold() for p in paths.values()}
            directories = {str(parent).casefold() for p in paths.values() for parent in PurePosixPath(p).parents if str(parent) != '.'}
            self.path_cache[key] = (layout, paths, occupied, directories)
        layout, paths, occupied, directories = self.path_cache[key]
        if url in paths:
            return
        path = (unique_path(original_path(url, kind, seed), url, occupied, directories)
                if layout == 'original' else local_path(url, kind, seed))
        self.db.execute('INSERT OR IGNORE INTO urls(task,url,kind,depth,path) VALUES(?,?,?,?,?)',
                        (key, url, kind, depth, path))
        paths[url] = path
        occupied.add(path.casefold())
        directories.update(str(p).casefold() for p in PurePosixPath(path).parents if str(p) != '.')
        if not self.batch_depth:
            self.db.commit()

    @contextmanager
    def discovery_batch(self):
        """One synchronous document discovery is committed as a unit; never await inside."""
        self.batch_depth += 1
        try:
            yield
        except BaseException:
            self.db.rollback()
            self.path_cache.clear()
            raise
        else:
            if self.batch_depth == 1:
                self.db.commit()
        finally:
            self.batch_depth -= 1

    def set_url(self, key, url, **fields):
        allowed = {'state', 'size', 'hash', 'mime', 'final_url', 'error', 'path'}
        if not fields.keys() <= allowed:
            raise ValueError('Unknown URL field')
        if 'path' in fields and key in self.path_cache:
            layout, paths, occupied, directories = self.path_cache[key]
            paths[url] = fields['path']
            occupied.add(fields['path'].casefold())
            directories.update(str(p).casefold() for p in PurePosixPath(fields['path']).parents if str(p) != '.')
        self.db.execute('UPDATE urls SET ' + ','.join(k + '=?' for k in fields) + ' WHERE task=? AND url=?',
                        (*fields.values(), key, url))
        self.db.commit()

    def asset_path(self, key, url, path):
        if key in self.path_cache:
            _, paths, occupied, directories = self.path_cache[key]
            if paths.get(url) != path:
                return unique_path(path, url, occupied, directories)
        return path

    def claim(self, key):
        row = self.db.execute("SELECT * FROM urls WHERE task=? AND state='pending' ORDER BY CASE kind WHEN 'asset' THEN 0 ELSE 1 END, depth, rowid LIMIT 1", (key,)).fetchone()
        if row:
            self.set_url(key, row['url'], state='running')
            return dict(row)

    def duplicate(self, key, digest, mime):
        row = self.db.execute("SELECT path FROM urls WHERE task=? AND hash=? AND mime=? AND state='done' LIMIT 1", (key, digest, mime)).fetchone()
        return row[0] if row else None

    def warn(self, key, text):
        self.db.execute('INSERT OR IGNORE INTO warnings VALUES(?,?)', (key, text[:2000]))
        if not self.batch_depth:
            self.db.commit()

    def warnings(self, key):
        return [r[0] for r in self.db.execute('SELECT message FROM warnings WHERE task=?', (key,))]
