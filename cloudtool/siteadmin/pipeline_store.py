"""Durable TDK allocations and step checkpoints; no HTTP or UI dependencies."""
import json
import sqlite3
import threading
from pathlib import Path


class PipelineStore:
    def __init__(self, root):
        Path(root).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(root)/'site-pipeline.sqlite3', check_same_thread=False)
        self.lock = threading.RLock()
        self.db.execute('CREATE TABLE IF NOT EXISTS allocations (owner TEXT, target TEXT, data TEXT, PRIMARY KEY(owner,target))')
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS allocation_title ON allocations(owner,json_extract(data,'$.title'))")
        self.db.execute('CREATE TABLE IF NOT EXISTS steps (owner TEXT, target TEXT, stage TEXT, data TEXT, PRIMARY KEY(owner,target,stage))')
        self.db.execute('CREATE TABLE IF NOT EXISTS rebuilds (owner TEXT, target TEXT, data TEXT, PRIMARY KEY(owner,target))')
        self.db.commit()

    def allocation(self, owner, target):
        with self.lock:
            row = self.db.execute('SELECT data FROM allocations WHERE owner=? AND target=?', (owner,target)).fetchone()
            return json.loads(row[0]) if row else None

    def allocate(self, owner, target, tdk):
        with self.lock, self.db:
            old = self.allocation(owner,target)
            if old: return old
            try:
                self.db.execute('INSERT INTO allocations VALUES (?,?,?)', (owner,target,json.dumps(tdk,ensure_ascii=False)))
            except sqlite3.IntegrityError:
                raise ValueError('TDK 标题重复，请重新生成') from None
            return dict(tdk)

    def step(self, owner, target, stage):
        with self.lock:
            row = self.db.execute('SELECT data FROM steps WHERE owner=? AND target=? AND stage=?', (owner,target,stage)).fetchone()
            return json.loads(row[0]) if row else {}

    def save(self, owner, target, stage, **data):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO steps VALUES (?,?,?,?)', (owner,target,stage,json.dumps(data,ensure_ascii=False)))

    def close(self):
        self.db.close()

    def rebuild(self,owner,target):
        with self.lock:
            row=self.db.execute('SELECT data FROM rebuilds WHERE owner=? AND target=?',(owner,target)).fetchone()
            return json.loads(row[0]) if row else None

    def claim_rebuild(self,owner,target,data):
        with self.lock,self.db:
            try:self.db.execute('INSERT INTO rebuilds VALUES (?,?,?)',(owner,target,json.dumps(data,ensure_ascii=False)))
            except sqlite3.IntegrityError:raise ValueError('此站点已使用一次自动重建机会；请导出报告人工处理') from None

    def reset_steps_for_rebuild(self,owner,target):
        with self.lock,self.db:
            if not self.rebuild(owner,target):raise ValueError('尚未登记重建')
            self.db.execute('DELETE FROM steps WHERE owner=? AND target=?',(owner,target))
