"""SQLite persistence. Each method has its own connection for threaded HTTP use."""
import json
import sqlite3
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
def uid(): return uuid.uuid4().hex
def now(): return datetime.now(KST).isoformat(timespec="microseconds")

class Repository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            version = c.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("더 최신 버전의 DB입니다. 앱을 업그레이드해 주세요.")
            c.executescript('''
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,guidelines TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS members(id TEXT PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),member_id TEXT NOT NULL REFERENCES members(id),name TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS prompts(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,family_id TEXT NOT NULL,revision INTEGER NOT NULL,session_id TEXT NOT NULL REFERENCES sessions(id),title TEXT NOT NULL,text TEXT NOT NULL,context TEXT NOT NULL,task TEXT NOT NULL,created_at TEXT NOT NULL,created_day TEXT NOT NULL,engine TEXT NOT NULL,rubric TEXT NOT NULL,score REAL NOT NULL,grade TEXT NOT NULL,result TEXT NOT NULL,UNIQUE(family_id,revision));
            CREATE TABLE IF NOT EXISTS supports(id TEXT PRIMARY KEY,prompt_id TEXT NOT NULL REFERENCES prompts(id),engine TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_prompts_day ON prompts(created_day);
            CREATE INDEX IF NOT EXISTS idx_prompts_session ON prompts(session_id);
            CREATE INDEX IF NOT EXISTS idx_prompts_family ON prompts(family_id,revision);
            PRAGMA user_version=1;
            ''')
            if not c.execute("SELECT 1 FROM projects").fetchone():
                c.execute("INSERT INTO projects VALUES(?,?,?)", (uid(), "개인 연습", ""))
            if not c.execute("SELECT 1 FROM members").fetchone():
                c.execute("INSERT INTO members VALUES(?,?)", (uid(), "나"))

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def bootstrap(self):
        with self.connect() as c:
            return {table: [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in ("projects", "members", "sessions")}

    def create(self, kind, data):
        item = {"id": uid(), "name": data["name"]}
        with self.connect() as c:
            if kind == "projects":
                item["guidelines"] = data.get("guidelines", "")
                c.execute("INSERT INTO projects VALUES(:id,:name,:guidelines)", item)
            elif kind == "members":
                c.execute("INSERT INTO members VALUES(:id,:name)", item)
            elif kind == "sessions":
                item.update(project_id=data["project_id"], member_id=data["member_id"], created_at=now())
                c.execute("INSERT INTO sessions VALUES(:id,:project_id,:member_id,:name,:created_at)", item)
            else:
                raise ValueError("알 수 없는 항목입니다.")
        return item

    def session(self, session_id):
        with self.connect() as c:
            row = c.execute("SELECT s.*,p.guidelines FROM sessions s JOIN projects p ON p.id=s.project_id WHERE s.id=?", (session_id,)).fetchone()
        if row is None: raise ValueError("세션을 먼저 선택해 주세요.")
        return dict(row)

    @staticmethod
    def decode(row):
        if row is None: raise ValueError("기록을 찾을 수 없습니다.")
        d = dict(row)
        d["result"] = json.loads(d["result"])
        return d

    def get(self, prompt_id):
        with self.connect() as c:
            return self.decode(c.execute("SELECT p.*,s.project_id,s.member_id FROM prompts p JOIN sessions s ON s.id=p.session_id WHERE p.id=?", (prompt_id,)).fetchone())

    def by_request(self, request_id):
        with self.connect() as c:
            row = c.execute("SELECT * FROM prompts WHERE request_id=?", (request_id,)).fetchone()
            return self.decode(row) if row else None

    def save(self, payload, result, engine):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            old = c.execute("SELECT * FROM prompts WHERE request_id=?", (payload["request_id"],)).fetchone()
            if old: return self.decode(old)
            parent = None
            if payload.get("parent_id"):
                parent = c.execute("SELECT * FROM prompts WHERE id=?", (payload["parent_id"],)).fetchone()
                if not parent or parent["session_id"] != payload["session_id"]:
                    raise ValueError("같은 세션의 원본만 새 버전으로 저장할 수 있습니다.")
            family = parent["family_id"] if parent else uid()
            revision = c.execute("SELECT COALESCE(MAX(revision),0)+1 FROM prompts WHERE family_id=?", (family,)).fetchone()[0]
            timestamp = now()
            item = {"id": uid(), "request_id": payload["request_id"], "family_id": family, "revision": revision,
                "session_id": payload["session_id"], "title": payload["title"], "text": payload["text"], "context": payload["context"],
                "task": payload["task"], "created_at": timestamp, "created_day": timestamp[:10], "engine": engine,
                "rubric": result["rubric"], "score": result["score"], "grade": result["grade"], "result": json.dumps(result, ensure_ascii=False)}
            cols = ",".join(item)
            c.execute(f"INSERT INTO prompts({cols}) VALUES({','.join('?' for _ in item)})", tuple(item.values()))
            return self.decode(c.execute("SELECT * FROM prompts WHERE id=?", (item["id"],)).fetchone())

    def save_support(self, prompt_id, engine, result):
        with self.connect() as c:
            c.execute("INSERT INTO supports VALUES(?,?,?,?,?)", (uid(), prompt_id, engine, json.dumps(result, ensure_ascii=False), now()))

    def history(self, filters):
        where, args = [], []
        for field in ("project_id", "member_id", "session_id", "engine", "rubric"):
            if filters.get(field):
                prefix = "s" if field in ("project_id", "member_id") else "p"
                where.append(f"{prefix}.{field}=?"); args.append(filters[field])
        for field, op in (("start", ">="), ("end", "<=")):
            if filters.get(field):
                datetime.strptime(filters[field], "%Y-%m-%d")
                where.append(f"p.created_day {op} ?"); args.append(filters[field])
        if filters.get("latest", "1") != "0":
            # Choose latest among the selected population so mode/date filters stay consistent.
            latest = True
        else:
            latest = False
        sql = "SELECT p.*,s.project_id,s.member_id,s.name session_name,m.name member_name,j.name project_name FROM prompts p JOIN sessions s ON s.id=p.session_id JOIN members m ON m.id=s.member_id JOIN projects j ON j.id=s.project_id"
        if where: sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.created_at,p.revision"
        with self.connect() as c:
            rows = [self.decode(r) for r in c.execute(sql, args)]
        if latest:
            families = {}
            for r in rows: families[r["family_id"]] = r
            rows = sorted(families.values(), key=lambda r: (r["created_at"], r["revision"]))
        return rows

    def backup(self):
        import tempfile
        # SQLite backup API includes committed WAL entries; copying the .db alone does not.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "backup.sqlite3"
            with self.connect() as source, closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
                destination.commit()
            return target.read_bytes()
