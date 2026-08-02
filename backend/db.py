# Callers: main.py, scrapers/squarespace_jobs.py (purge_stale_data).
# Schema: jobs, scrape_log. User: "Implement the plan" (job triage + lean DB).
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

def default_db_path() -> str:
    """Prefer DATABASE_PATH, then /app/data (Docker/Railway volume), else local file."""
    env = os.getenv("DATABASE_PATH")
    if env:
        return env
    if os.path.isdir("/app/data"):
        return "/app/data/dashboard.db"
    return "dashboard.db"


def get_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a database connection with proper configuration."""
    path = db_path or default_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # check_same_thread=False: shared conn used by API + background scheduler
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def migrate(conn: sqlite3.Connection) -> None:
    """Run database migrations idempotently."""
    migrations = [
        # Core scrape logging table
        """CREATE TABLE IF NOT EXISTS scrape_log (
            id INTEGER PRIMARY KEY,
            scraper TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            rows_affected INTEGER DEFAULT 0,
            error TEXT
        )""",

        # Respondables table - things that need human response
        """CREATE TABLE IF NOT EXISTS respondables (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT,
            url TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'pending',
            UNIQUE(source, source_id)
        )""",

        # Tasks table - working set
        """CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            priority INTEGER DEFAULT 5,
            source TEXT DEFAULT 'manual',
            created_at TEXT NOT NULL,
            updated_at TEXT
        )""",

        # Posts table - content tracking
        """CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT UNIQUE,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            created_at TEXT,
            scraped_at TEXT
        )""",

        # Jobs table - Squarespace job monitoring
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            url TEXT NOT NULL,
            posted_date TEXT,
            job_type TEXT DEFAULT 'unknown',
            rate_min INTEGER,
            rate_max INTEGER,
            currency TEXT DEFAULT 'USD',
            keyword_matches TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(source, source_id)
        )""",

        # Forum questions table - forum monitoring with AI answers
        """CREATE TABLE IF NOT EXISTS forum_questions (
            id INTEGER PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            url TEXT NOT NULL,
            comments_count INTEGER DEFAULT 0,
            ai_answer TEXT,
            answer_generated_at TEXT,
            status TEXT DEFAULT 'new',
            answered_at TEXT,
            answer_url TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            UNIQUE(source, source_id)
        )""",

        # Indexes for performance
        "CREATE INDEX IF NOT EXISTS idx_respondables_status ON respondables(status)",
        "CREATE INDEX IF NOT EXISTS idx_respondables_source ON respondables(source)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)",
        "CREATE INDEX IF NOT EXISTS idx_scrape_log_status ON scrape_log(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date)",
        "CREATE INDEX IF NOT EXISTS idx_forum_questions_status ON forum_questions(status)",
        "CREATE INDEX IF NOT EXISTS idx_forum_questions_source ON forum_questions(source)",
        "CREATE INDEX IF NOT EXISTS idx_forum_questions_comments_count ON forum_questions(comments_count)",

        # Durable WhatsApp alert ledger — survives job row delete/re-insert
        """CREATE TABLE IF NOT EXISTS job_alert_sent (
            alert_key TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL
        )""",
    ]

    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # Already exists

    # Schema evolution - ALTER TABLE statements
    schema_updates = [
        "ALTER TABLE posts ADD COLUMN engagement_score REAL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN source TEXT DEFAULT 'manual'",
        "ALTER TABLE respondables ADD COLUMN metadata TEXT",
        "ALTER TABLE jobs ADD COLUMN budget TEXT",
        "ALTER TABLE jobs ADD COLUMN client_location TEXT",
        "ALTER TABLE jobs ADD COLUMN remote_ok BOOLEAN DEFAULT 1",
        "ALTER TABLE jobs ADD COLUMN effort_score INTEGER",
        "ALTER TABLE jobs ADD COLUMN priority_score REAL",
        "ALTER TABLE jobs ADD COLUMN budget_mid_usd INTEGER",
        "ALTER TABLE jobs ADD COLUMN earnings_usd REAL",
        "ALTER TABLE jobs ADD COLUMN ai_proposal TEXT",
        "ALTER TABLE jobs ADD COLUMN ai_bid_amount REAL",
        "ALTER TABLE jobs ADD COLUMN ai_bid_days INTEGER",
        "ALTER TABLE jobs ADD COLUMN proposal_generated_at TEXT",
        "CREATE INDEX IF NOT EXISTS idx_jobs_priority_score ON jobs(priority_score)",
    ]

    for sql in schema_updates:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Seed alert ledger from current jobs so redeploys don't re-ping old gigs
    try:
        conn.execute(
            """INSERT OR IGNORE INTO job_alert_sent (alert_key, sent_at)
               SELECT 'source:' || source || ':' || source_id,
                      COALESCE(created_at, ?)
               FROM jobs""",
            (datetime.utcnow().isoformat(),),
        )
        conn.execute(
            """INSERT OR IGNORE INTO job_alert_sent (alert_key, sent_at)
               SELECT 'url:' || url, COALESCE(created_at, ?)
               FROM jobs
               WHERE url IS NOT NULL AND TRIM(url) != ''""",
            (datetime.utcnow().isoformat(),),
        )
    except sqlite3.OperationalError:
        pass

    conn.commit()

def init_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Initialize the database and return connection."""
    conn = get_db(db_path)
    migrate(conn)
    return conn

def log_scrape_start(conn: sqlite3.Connection, scraper_name: str) -> int:
    """Log the start of a scrape operation."""
    cursor = conn.execute(
        "INSERT INTO scrape_log (scraper, started_at, status) VALUES (?, ?, 'running')",
        (scraper_name, datetime.utcnow().isoformat())
    )
    conn.commit()
    return cursor.lastrowid

def log_scrape_end(conn: sqlite3.Connection, log_id: int, status: str, rows_affected: int = 0, error: Optional[str] = None) -> None:
    """Log the end of a scrape operation."""
    conn.execute(
        """UPDATE scrape_log
           SET finished_at = ?, status = ?, rows_affected = ?, error = ?
           WHERE id = ?""",
        (datetime.utcnow().isoformat(), status, rows_affected, error, log_id)
    )
    conn.commit()

def purge_stale_data(conn: sqlite3.Connection) -> None:
    """Drop stale inbox/discarded/outcome jobs and cap scrape_log to keep the volume small."""
    new_days = int(os.getenv("JOB_RETENTION_NEW_DAYS", "21"))
    discard_days = int(os.getenv("JOB_RETENTION_DISCARD_DAYS", "7"))
    outcome_days = int(os.getenv("JOB_RETENTION_OUTCOME_DAYS", "30"))
    won_days = int(os.getenv("JOB_RETENTION_WON_DAYS", "90"))
    log_keep = int(os.getenv("SCRAPE_LOG_KEEP", "48"))

    cutoff_new = (datetime.utcnow() - timedelta(days=new_days)).isoformat()
    cutoff_discard = (datetime.utcnow() - timedelta(days=discard_days)).isoformat()
    cutoff_outcome = (datetime.utcnow() - timedelta(days=outcome_days)).isoformat()
    cutoff_won = (datetime.utcnow() - timedelta(days=won_days)).isoformat()

    conn.execute(
        "DELETE FROM jobs WHERE status = 'new' AND posted_date < ?",
        (cutoff_new,),
    )
    # Drop low-score inbox rows (same bar as scrape insert / WhatsApp alerts)
    try:
        min_score = float(os.getenv("ALERT_MIN_SCORE", "50"))
    except ValueError:
        min_score = 50.0
    conn.execute(
        """DELETE FROM jobs
           WHERE status = 'new'
             AND (priority_score IS NULL OR priority_score < ?)""",
        (min_score,),
    )
    conn.execute(
        """DELETE FROM jobs
           WHERE status IN ('skipped', 'archived', 'gone')
             AND COALESCE(updated_at, created_at) < ?""",
        (cutoff_discard,),
    )
    conn.execute(
        """DELETE FROM jobs
           WHERE status IN ('lost', 'no_reply')
             AND COALESCE(updated_at, created_at) < ?""",
        (cutoff_outcome,),
    )
    conn.execute(
        """DELETE FROM jobs
           WHERE status = 'won'
             AND COALESCE(updated_at, created_at) < ?""",
        (cutoff_won,),
    )
    conn.execute(
        """DELETE FROM scrape_log
           WHERE id NOT IN (
             SELECT id FROM scrape_log ORDER BY id DESC LIMIT ?
           )""",
        (log_keep,),
    )
    conn.commit()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass


def is_scraper_running(conn: sqlite3.Connection, scraper_name: str) -> bool:
    """Check if a scraper is currently running."""
    running = conn.execute(
        "SELECT 1 FROM scrape_log WHERE scraper = ? AND status = 'running'",
        (scraper_name,)
    ).fetchone()
    return running is not None


def job_alert_keys(job: dict) -> list:
    """Stable keys used to suppress duplicate WhatsApp alerts."""
    keys = []
    source = (job.get("source") or "").strip()
    source_id = str(job.get("source_id") or "").strip()
    if source and source_id:
        keys.append(f"source:{source}:{source_id}")
    url = (job.get("url") or "").strip()
    if url:
        keys.append(f"url:{url}")
    return keys


def job_already_alerted(conn: sqlite3.Connection, job: dict) -> bool:
    keys = job_alert_keys(job)
    if not keys:
        return False
    placeholders = ",".join("?" for _ in keys)
    row = conn.execute(
        f"SELECT 1 FROM job_alert_sent WHERE alert_key IN ({placeholders}) LIMIT 1",
        keys,
    ).fetchone()
    return row is not None


def mark_jobs_alerted(conn: sqlite3.Connection, jobs: list) -> None:
    now = datetime.utcnow().isoformat()
    for job in jobs:
        for key in job_alert_keys(job):
            conn.execute(
                "INSERT OR IGNORE INTO job_alert_sent (alert_key, sent_at) VALUES (?, ?)",
                (key, now),
            )
    conn.commit()
