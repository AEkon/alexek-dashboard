import sqlite3
from datetime import datetime
from typing import Optional

def get_db(db_path: str = "dashboard.db") -> sqlite3.Connection:
    """Get a database connection with proper configuration."""
    conn = sqlite3.connect(db_path, timeout=30)
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

        # Indexes for performance
        "CREATE INDEX IF NOT EXISTS idx_respondables_status ON respondables(status)",
        "CREATE INDEX IF NOT EXISTS idx_respondables_source ON respondables(source)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)",
        "CREATE INDEX IF NOT EXISTS idx_scrape_log_status ON scrape_log(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_posted_date ON jobs(posted_date)",
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
    ]

    for sql in schema_updates:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.commit()

def init_db(db_path: str = "dashboard.db") -> sqlite3.Connection:
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

def is_scraper_running(conn: sqlite3.Connection, scraper_name: str) -> bool:
    """Check if a scraper is currently running."""
    running = conn.execute(
        "SELECT 1 FROM scrape_log WHERE scraper = ? AND status = 'running'",
        (scraper_name,)
    ).fetchone()
    return running is not None