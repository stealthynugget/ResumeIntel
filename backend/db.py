import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("RESUMEINTEL_DB", Path(__file__).resolve().parents[1] / "data" / "resumeintel_balanced.db"))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS candidates (
          id INTEGER PRIMARY KEY, external_id TEXT UNIQUE, name TEXT, category TEXT,
          source_type TEXT NOT NULL, checksum TEXT NOT NULL UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY, candidate_id INTEGER NOT NULL REFERENCES candidates(id),
          filename TEXT, text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spans (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
          candidate_id INTEGER NOT NULL REFERENCES candidates(id),
          start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, page INTEGER,
          text TEXT NOT NULL, embedding BLOB
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS spans_fts USING fts5(text, content='spans', content_rowid='id');
        CREATE TRIGGER IF NOT EXISTS spans_ai AFTER INSERT ON spans BEGIN
          INSERT INTO spans_fts(rowid,text) VALUES(new.id,new.text);
        END;
        CREATE TABLE IF NOT EXISTS jobs (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL,
          requirements_version INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requirements (
          id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
          label TEXT NOT NULL, kind TEXT NOT NULL, mandatory INTEGER NOT NULL,
          UNIQUE(job_id,label,kind)
        );
        CREATE TABLE IF NOT EXISTS match_runs (
          id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
          requirements_version INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          trace_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results (
          run_id INTEGER NOT NULL REFERENCES match_runs(id), candidate_id INTEGER NOT NULL REFERENCES candidates(id),
          rank INTEGER NOT NULL, match_index REAL NOT NULL, mandatory_status TEXT NOT NULL,
          score_json TEXT NOT NULL, assessments_json TEXT NOT NULL, trace_json TEXT NOT NULL,
          PRIMARY KEY(run_id,candidate_id)
        );
        CREATE TABLE IF NOT EXISTS ai_reviews (
          run_id INTEGER NOT NULL REFERENCES match_runs(id),
          candidate_id INTEGER NOT NULL REFERENCES candidates(id),
          model TEXT NOT NULL, prompt_version INTEGER NOT NULL,
          payload_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(run_id,candidate_id,model,prompt_version)
        );
        CREATE INDEX IF NOT EXISTS idx_spans_candidate ON spans(candidate_id);
        CREATE INDEX IF NOT EXISTS idx_requirements_job ON requirements(job_id);
        CREATE TABLE IF NOT EXISTS import_jobs (
          id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, filename TEXT NOT NULL,
          limit_rows INTEGER, status TEXT NOT NULL DEFAULT 'queued', total_rows INTEGER,
          processed_rows INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0,
          duplicate INTEGER NOT NULL DEFAULT 0, invalid INTEGER NOT NULL DEFAULT 0,
          failed INTEGER NOT NULL DEFAULT 0, error TEXT,
          started_at TEXT, finished_at TEXT, duration_seconds REAL,
          peak_rss_mb REAL
        );
        CREATE TABLE IF NOT EXISTS import_job_rows (
          job_id INTEGER NOT NULL REFERENCES import_jobs(id), row_number INTEGER NOT NULL,
          status TEXT NOT NULL, detail TEXT, candidate_id INTEGER,
          PRIMARY KEY(job_id,row_number)
        );
        CREATE INDEX IF NOT EXISTS idx_import_job_rows_status ON import_job_rows(job_id,status);
        """)
        for table in ("candidates", "jobs", "match_runs", "import_jobs"):
            columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            if "owner_user_id" not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN owner_user_id INTEGER REFERENCES users(id)")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','recruiter')),
          active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS login_attempts (
          id INTEGER PRIMARY KEY, email TEXT NOT NULL, ip TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts(email,ip,created_at);
        CREATE TABLE IF NOT EXISTS chat_conversations (
          id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL REFERENCES users(id),
          run_id INTEGER NOT NULL REFERENCES match_runs(id),
          candidate_id INTEGER NOT NULL REFERENCES candidates(id),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id),
          role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]',
          response_kind TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_chat_owner ON chat_conversations(owner_user_id,updated_at);
        CREATE TABLE IF NOT EXISTS assistant_conversations (
          id INTEGER PRIMARY KEY, owner_user_id INTEGER NOT NULL REFERENCES users(id),
          scope TEXT NOT NULL CHECK(scope IN ('general','corpus','run','candidate')),
          run_id INTEGER REFERENCES match_runs(id), candidate_id INTEGER REFERENCES candidates(id),
          created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS assistant_messages (
          id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES assistant_conversations(id),
          role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL, citations_json TEXT NOT NULL DEFAULT '[]',
          response_kind TEXT, suggested_actions_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_assistant_owner ON assistant_conversations(owner_user_id,updated_at);
        """)
        if "ai_enabled" not in {row["name"] for row in db.execute("PRAGMA table_info(users)")}:
            db.execute("ALTER TABLE users ADD COLUMN ai_enabled INTEGER NOT NULL DEFAULT 1")
        db.execute("""INSERT OR IGNORE INTO assistant_conversations
            (id,owner_user_id,scope,run_id,candidate_id,created_at,updated_at)
            SELECT id,owner_user_id,'candidate',run_id,candidate_id,created_at,updated_at
            FROM chat_conversations""")
        db.execute("""INSERT OR IGNORE INTO assistant_messages
            (id,conversation_id,role,content,citations_json,response_kind,created_at)
            SELECT m.id,m.conversation_id,m.role,m.content,m.citations_json,m.response_kind,m.created_at
            FROM chat_messages m JOIN assistant_conversations c ON c.id=m.conversation_id""")


def interrupt_running_imports():
    # A server restart cannot resume its old thread; the persisted source can be retried.
    with connect() as db:
        db.execute("UPDATE import_jobs SET status='interrupted', error='Worker stopped before completion' WHERE status='running'")
