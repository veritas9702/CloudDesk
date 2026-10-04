"""Machine-local allocation ledger; stores no credentials or remote responses."""
import sqlite3
import time
import threading


class TemplateUsage:
    def __init__(self, root):
        root.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(root/'template-usage.sqlite3',check_same_thread=False)
        self.db.row_factory=sqlite3.Row; self.lock=threading.Lock()
        self.db.execute('CREATE TABLE IF NOT EXISTS usage (digest TEXT PRIMARY KEY, path TEXT UNIQUE, owner TEXT, target TEXT, stage TEXT, site_id INTEGER, UNIQUE(owner,target))')
        self.db.execute('CREATE TABLE IF NOT EXISTS releases (id INTEGER PRIMARY KEY AUTOINCREMENT, digest TEXT, path TEXT, owner TEXT, target TEXT, stage TEXT, site_id INTEGER, released REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS quarantine (digest TEXT PRIMARY KEY,path TEXT,reason TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS preview_digest (path TEXT PRIMARY KEY,signature TEXT,digest TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS replacements (digest TEXT PRIMARY KEY,path TEXT UNIQUE,owner TEXT,target TEXT,ticket TEXT,UNIQUE(owner,target))')
        self.db.commit()

    def rows(self):
        with self.lock: return [dict(r) for r in self.db.execute('SELECT * FROM usage')]

    def cached_digest(self,path,signature):
        with self.lock:
            row=self.db.execute('SELECT digest FROM preview_digest WHERE path=? AND signature=?',(path,signature)).fetchone()
            return row[0] if row else None

    def save_digest(self,path,signature,value):
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO preview_digest VALUES(?,?,?)',(path,signature,value))

    def entry(self, owner, target):
        with self.lock:
            row=self.db.execute('SELECT * FROM usage WHERE owner=? AND target=?',(owner,target)).fetchone()
            return dict(row) if row else None

    def reserve(self, template, owner, target, reservation=''):
        with self.lock,self.db:
            if self.db.execute('SELECT 1 FROM quarantine WHERE digest=? OR path=?',(template['digest'],template['path'])).fetchone():
                raise ValueError('此模板已因失败隔离，不能再次自动分配')
            claim=self.db.execute('SELECT * FROM replacements WHERE digest=? OR path=?',(template['digest'],template['path'])).fetchone()
            if claim and (claim['owner'],claim['target'],claim['ticket'])!=(owner,target,reservation):
                raise ValueError('模板已为其他重建流程预留')
            rows=self.db.execute('SELECT * FROM usage WHERE digest=? OR path=? OR (owner=? AND target=?)',
                (template['digest'],template['path'],owner,target)).fetchall()
            if rows:
                if len(rows)!=1 or any(rows[0][k]!=v for k,v in dict(digest=template['digest'],path=template['path'],owner=owner,target=target).items()):
                    raise ValueError('模板已分配或内容发生变化，请重新预览')
                return dict(rows[0])
            self.db.execute('INSERT INTO usage VALUES (?,?,?,?,?,?)',(template['digest'],template['path'],owner,target,'reserved',0))
            return dict(digest=template['digest'],path=template['path'],owner=owner,target=target,stage='reserved',site_id=0)

    def excluded(self):
        with self.lock:return [dict(r) for r in self.db.execute("SELECT * FROM quarantine UNION ALL SELECT digest,path,'重建预留' AS reason FROM replacements")]

    def reserve_replacement(self,template,owner,target,ticket):
        with self.lock,self.db:
            for table in ('usage','quarantine'):
                if self.db.execute(f'SELECT 1 FROM {table} WHERE digest=? OR path=?',(template['digest'],template['path'])).fetchone():
                    raise ValueError('替换模板已被使用或隔离，尚未删除原站点')
            try:self.db.execute('INSERT INTO replacements VALUES (?,?,?,?,?)',(template['digest'],template['path'],owner,target,ticket))
            except sqlite3.IntegrityError:raise ValueError('替换模板或目标站点已被另一重建流程预留') from None

    def release_replacements(self,ticket):
        with self.lock,self.db:self.db.execute('DELETE FROM replacements WHERE ticket=?',(ticket,))

    def quarantine(self,entry,reason):
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO quarantine VALUES (?,?,?)',(entry['digest'],entry['path'],reason))

    def set(self,digest,owner,stage,site_id):
        with self.lock,self.db:
            self.db.execute('UPDATE usage SET stage=?,site_id=? WHERE digest=? AND owner=?',(stage,site_id,digest,owner))

    def close(self): self.db.close()

    def release_unstarted(self,digest,owner,target):
        with self.lock,self.db:
            self.db.execute("DELETE FROM usage WHERE digest=? AND owner=? AND target=? AND stage='reserved' AND site_id=0",(digest,owner,target))

    def recover(self,entry,stage,site_id):
        with self.lock,self.db:
            result=self.db.execute('UPDATE usage SET stage=?,site_id=? WHERE digest=? AND owner=? AND target=? AND stage=? AND site_id=?',
                (stage,site_id,entry['digest'],entry['owner'],entry['target'],entry['stage'],entry['site_id']))
            if result.rowcount!=1: raise ValueError('任务状态已变化，请重新打开恢复窗口')

    def releases(self,owner=None):
        with self.lock:
            if owner is None:return [dict(r) for r in self.db.execute('SELECT * FROM releases ORDER BY id DESC')]
            return [dict(r) for r in self.db.execute('SELECT * FROM releases WHERE owner=? ORDER BY id DESC',(owner,))]

    def release_verified(self,entry):
        """Atomically archive the old allocation and release only the verified snapshot."""
        with self.lock,self.db:
            current=self.db.execute('SELECT * FROM usage WHERE digest=?',(entry['digest'],)).fetchone()
            if not current or dict(current)!=entry:raise ValueError('模板绑定已变化，请重新核实')
            self.db.execute('INSERT INTO releases (digest,path,owner,target,stage,site_id,released) VALUES (?,?,?,?,?,?,?)',
                (entry['digest'],entry['path'],entry['owner'],entry['target'],entry['stage'],entry['site_id'],time.time()))
            self.db.execute('DELETE FROM usage WHERE digest=?',(entry['digest'],))
