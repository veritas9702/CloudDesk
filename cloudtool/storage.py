"""Per-token SQLite cache and audit repository."""
import json
import sqlite3
import threading
import time
from pathlib import Path
from .models import canonical

class Store:
    """A separate database per token, never a shared zone or job namespace."""
    def __init__(self, root, key):
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("无效的隔离标识")
        self.key = key
        self.path = Path(root) / key / "state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS cache (name TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, created REAL);
        CREATE TABLE IF NOT EXISTS audit (
            id TEXT PRIMARY KEY, batch TEXT, target TEXT, method TEXT, path TEXT,
            body TEXT, before_json TEXT, state TEXT, detail TEXT, updated REAL);
        CREATE INDEX IF NOT EXISTS audit_updated ON audit(updated DESC);
        """)
        self.conn.execute("UPDATE audit SET state='结果未知',detail='程序曾中断；请读取远端核实，禁止直接重放' WHERE state='执行中'")
        self.conn.execute("UPDATE audit SET state='未执行',detail='程序曾中断；请重新生成计划' WHERE state='等待中'")
        self.conn.commit()

    def cache(self, name, value):
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (name, canonical(value)))

    def cached(self, name, default=None):
        with self.lock:
            row = self.conn.execute("SELECT value FROM cache WHERE name=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def record(self, action, batch, state, detail=""):
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO audit VALUES (?,?,?,?,?,?,?,?,?,?)", (
                action.id, batch, action.target, action.method, action.path,
                canonical(action.body), canonical(action.before), state, detail, time.time()))

    def history(self, include_payload=True):
        with self.lock:
            if not include_payload:
                rows = self.conn.execute("SELECT id,target,method,path,state,substr(detail,1,300),updated,batch FROM audit ORDER BY updated DESC LIMIT 5000").fetchall()
                return [dict(zip(["id", "target", "method", "path", "state", "detail", "updated", "batch"], r)) for r in rows]
            rows = self.conn.execute("SELECT target,method,path,state,detail,updated,body,before_json,batch FROM audit ORDER BY updated DESC LIMIT 5000").fetchall()
        return [dict(zip(["target", "method", "path", "state", "detail", "updated", "body", "before", "batch"], r)) for r in rows]

    def history_detail(self, aid):
        with self.lock:
            row = self.conn.execute("SELECT target,method,path,state,detail,updated,body,before_json,batch FROM audit WHERE id=?", (aid,)).fetchone()
        return dict(zip(["target", "method", "path", "state", "detail", "updated", "body", "before", "batch"], row)) if row else {}

    def close(self):
        self.conn.close()

    def claim_batch(self, batch):
        """Atomically prevent replay; hide SQLite details from the executor."""
        try:
            with self.lock, self.conn:
                self.conn.execute('INSERT INTO batches VALUES (?,?)', (batch, time.time()))
        except sqlite3.IntegrityError:
            raise ValueError('此计划已开始执行过，请读取远端并重新生成计划') from None

    def stop_waiting(self, batch):
        with self.lock, self.conn:
            rows = self.conn.execute("SELECT id FROM audit WHERE batch=? AND state='等待中'", (batch,)).fetchall()
            self.conn.execute("UPDATE audit SET state='未执行',detail='调度已停止' WHERE batch=? AND state='等待中'", (batch,))
        return [row[0] for row in rows]
