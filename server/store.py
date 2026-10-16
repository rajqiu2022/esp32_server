import contextlib
import json
import sqlite3
import time
import uuid

DEFAULT_PROMPT = """你叫小智，是一个语气温和、自然、有耐心的中文聊天伙伴。
平时每次用一两句话回答，需要解释时再展开。可以陪我聊天、讨论想法、练习口语。
不要每句话都追问，也不要假装有现实经历或已完成没有工具支持的操作。
记不住以前的事情时要直说，不要编造。适合语音朗读，不使用复杂表格或长篇列表。"""
DEFAULT_MODEL = {"provider": "ollama", "base_url": "http://127.0.0.1:11434/v1",
                 "model": "qwen2.5:3b", "api_key": "", "temperature": 0.7, "max_tokens": 512}


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), expires INTEGER);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL,
                    voice TEXT NOT NULL, rate INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS devices(mac TEXT PRIMARY KEY, name TEXT NOT NULL,
                    agent_id TEXT NOT NULL REFERENCES agents(id), enrollment_key TEXT UNIQUE NOT NULL,
                    client_id TEXT, last_seen INTEGER, created_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, device_id TEXT REFERENCES devices(mac),
                    agent_id TEXT NOT NULL REFERENCES agents(id), session_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_time ON messages(created_at);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,created_at);
            """)
            if not db.execute("SELECT 1 FROM agents").fetchone():
                db.execute("INSERT INTO agents VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, "小智 · 日常伙伴",
                           DEFAULT_PROMPT, "zh-CN-XiaoxiaoNeural", 0, int(time.time())))
            db.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", ("model", json.dumps(DEFAULT_MODEL)))

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).rowcount

    def setting(self, key, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def save_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
