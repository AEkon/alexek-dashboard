---
name: database-conventions
description: SQLite database configuration, schema evolution, and upsert rules for the dashboard
metadata:
  type: reference
---

## SQLite Configuration

```python
import sqlite3

def get_db(db_path="dashboard.db"):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
```

| Setting | Value | Why |
|---------|-------|-----|
| WAL mode | Always on | Lets reads happen during writes |
| busy_timeout | 30000ms | Prevents "database is locked" when scraper writes overlap with frontend reads |
| row_factory | `sqlite3.Row` | Dict-like access without an ORM |
| Write transactions | `BEGIN IMMEDIATE` | Single writer — claim the lock early, fail fast |

## Schema Evolution

No migration framework. Migrations are ALTER TABLE statements that swallow "already exists" errors. Run on every app startup. Idempotent by design.

```python
def migrate(conn):
    migrations = [
        "ALTER TABLE posts ADD COLUMN engagement_score REAL DEFAULT 0",
        "ALTER TABLE tasks ADD COLUMN source TEXT DEFAULT 'manual'",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
```

## The Upsert Rule: Never Overwrite Non-Zero with Zero

This is the single most important database convention. Scrapers fail — they get rate-limited, time out, return empty responses. If you blindly upsert, a failed scrape at midnight will zero out your real data.

```sql
INSERT INTO posts (id, title, views, likes)
VALUES (?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
  title = excluded.title,
  views = CASE WHEN excluded.views > 0 THEN excluded.views ELSE views END,
  likes = CASE WHEN excluded.likes > 0 THEN excluded.likes ELSE likes END
```

Apply this pattern to every numeric field that comes from an external source. The title (a string) can be overwritten freely; the counts cannot. And for that matter, never put 0 when the answer is really "null" because you don't have data.

## Scrape Logging

```sql
CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY,
    scraper TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT DEFAULT 'running',  -- running | success | failed
    rows_affected INTEGER DEFAULT 0,
    error TEXT
);
```

Before starting a scraper, check if one is already running:

```python
running = db.execute(
    "SELECT 1 FROM scrape_log WHERE scraper = ? AND status = 'running'", (name,)
).fetchone()
if running:
    return {"status": "already_running"}
```