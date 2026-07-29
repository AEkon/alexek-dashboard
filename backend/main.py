from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional

from db import init_db, is_scraper_running, log_scrape_start, log_scrape_end
from scrapers import squarespace_jobs

app = FastAPI(title="Personal Dashboard API")

# Mount static files for frontend.
# Vite emits /assets/*; also expose /static for the same build output.
app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Global database connection
db: Optional[sqlite3.Connection] = None

@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    global db
    try:
        print("Starting Squarespace Job Dashboard API...")
        db = init_db()
        print("Database initialized successfully")
        print("API ready to serve requests")
    except Exception as e:
        print(f"Startup error: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    """Close database connection on shutdown."""
    global db
    if db:
        db.close()

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/api/tasks")
async def get_tasks():
    """Get all open tasks."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    tasks = db.execute(
        "SELECT * FROM tasks WHERE status = 'open' ORDER BY priority ASC, created_at DESC"
    ).fetchall()

    return [dict(task) for task in tasks]

@app.post("/api/refresh/tasks")
async def refresh_tasks(background_tasks: BackgroundTasks):
    """Trigger task refresh (placeholder for actual scraper)."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Check if already running
    if is_scraper_running(db, "tasks"):
        return {"status": "already_running"}

    # Start background task
    background_tasks.add_task(refresh_tasks_background, db)
    return {"status": "refreshing"}

async def refresh_tasks_background(conn: sqlite3.Connection):
    """Background task to refresh tasks (placeholder)."""
    log_id = log_scrape_start(conn, "tasks")

    try:
        # Placeholder: In real implementation, this would call actual scraper
        # For now, just simulate success
        log_scrape_end(conn, log_id, "success", rows_affected=0)
    except Exception as e:
        log_scrape_end(conn, log_id, "failed", error=str(e))

@app.get("/api/respondables")
async def get_respondables():
    """Get all pending respondables."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    respondables = db.execute(
        "SELECT * FROM respondables WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()

    return [dict(item) for item in respondables]

@app.post("/api/refresh/respondables")
async def refresh_respondables(background_tasks: BackgroundTasks):
    """Trigger respondables refresh (placeholder for actual scraper)."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if is_scraper_running(db, "respondables"):
        return {"status": "already_running"}

    background_tasks.add_task(refresh_respondables_background, db)
    return {"status": "refreshing"}

async def refresh_respondables_background(conn: sqlite3.Connection):
    """Background task to refresh respondables (placeholder)."""
    log_id = log_scrape_start(conn, "respondables")

    try:
        # Placeholder: In real implementation, this would call actual scraper
        log_scrape_end(conn, log_id, "success", rows_affected=0)
    except Exception as e:
        log_scrape_end(conn, log_id, "failed", error=str(e))

@app.get("/api/posts")
async def get_posts():
    """Get all posts."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    posts = db.execute(
        "SELECT * FROM posts ORDER BY created_at DESC"
    ).fetchall()

    return [dict(post) for post in posts]

@app.post("/api/refresh/posts")
async def refresh_posts(background_tasks: BackgroundTasks):
    """Trigger posts refresh (placeholder for actual scraper)."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if is_scraper_running(db, "posts"):
        return {"status": "already_running"}

    background_tasks.add_task(refresh_posts_background, db)
    return {"status": "refreshing"}

async def refresh_posts_background(conn: sqlite3.Connection):
    """Background task to refresh posts (placeholder)."""
    log_id = log_scrape_start(conn, "posts")

    try:
        # Placeholder: In real implementation, this would call actual scraper
        log_scrape_end(conn, log_id, "success", rows_affected=0)
    except Exception as e:
        log_scrape_end(conn, log_id, "failed", error=str(e))

@app.get("/api/jobs")
async def get_jobs(job_type: Optional[str] = None, status: str = "new", limit: int = 50, source: Optional[str] = None):
    """Get Squarespace jobs with optional filtering."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Build query with filters
    where_conditions = ["status = ?"]
    values = [status]

    if job_type:
        where_conditions.append("job_type = ?")
        values.append(job_type)

    if source:
        where_conditions.append("source = ?")
        values.append(source)

    where_clause = " AND ".join(where_conditions)
    values.append(limit)  # For LIMIT

    jobs = db.execute(
        f"""SELECT * FROM jobs
           WHERE {where_clause}
           ORDER BY posted_date DESC
           LIMIT ?""",
        values
    ).fetchall()

    return [dict(job) for job in jobs]

@app.get("/api/jobs/search")
async def search_jobs(q: str, limit: int = 50):
    """Search jobs by keywords in title or description."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    search_pattern = f"%{q}%"
    jobs = db.execute(
        """SELECT * FROM jobs
           WHERE status = 'new'
           AND (title LIKE ? OR description LIKE ? OR keyword_matches LIKE ?)
           ORDER BY posted_date DESC
           LIMIT ?""",
        (search_pattern, search_pattern, search_pattern, limit)
    ).fetchall()

    return [dict(job) for job in jobs]

@app.patch("/api/jobs/{job_id}")
async def update_job(job_id: int, updates: dict):
    """Update job status or other fields."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Build dynamic UPDATE statement
    set_clauses = []
    values = []

    for key, value in updates.items():
        if key in ["status", "job_type"]:
            set_clauses.append(f"{key} = ?")
            values.append(value)

    if set_clauses:
        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(job_id)

        sql = f"UPDATE jobs SET {', '.join(set_clauses)} WHERE id = ?"
        db.execute(sql, values)
        db.commit()

        return {"status": "updated"}

    return {"status": "no_changes"}

@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int):
    """Delete a job (mark as archived)."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    db.execute(
        "UPDATE jobs SET status = 'archived', updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), job_id)
    )
    db.commit()

    return {"status": "archived"}

@app.post("/api/refresh/jobs")
async def refresh_jobs(background_tasks: BackgroundTasks):
    """Trigger Squarespace job refresh."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if is_scraper_running(db, "jobs"):
        return {"status": "already_running"}

    background_tasks.add_task(refresh_jobs_background, db)
    return {"status": "refreshing"}

async def refresh_jobs_background(conn: sqlite3.Connection):
    """Background task to refresh Squarespace jobs."""
    log_id = log_scrape_start(conn, "jobs")

    try:
        rows_affected, warning = await squarespace_jobs.scrape(conn)
        # Partial success still counts as success; keep warnings in error column
        log_scrape_end(
            conn,
            log_id,
            "success",
            rows_affected=rows_affected,
            error=warning,
        )
    except Exception as e:
        log_scrape_end(conn, log_id, "failed", error=str(e))

@app.get("/api/jobs/stats")
async def get_jobs_stats():
    """Get statistics about Squarespace jobs."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Get counts by status
    status_counts = db.execute("""
        SELECT status, COUNT(*) as count
        FROM jobs
        GROUP BY status
    """).fetchall()

    # Get counts by source
    source_counts = db.execute("""
        SELECT source, COUNT(*) as count
        FROM jobs
        WHERE status = 'new'
        GROUP BY source
    """).fetchall()

    # Get short-term vs unknown
    type_counts = db.execute("""
        SELECT job_type, COUNT(*) as count
        FROM jobs
        WHERE status = 'new'
        GROUP BY job_type
    """).fetchall()

    # Recent activity (last 7 days)
    recent_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
    recent_count = db.execute(
        "SELECT COUNT(*) FROM jobs WHERE posted_date >= ?",
        (recent_date,)
    ).fetchone()[0]

    return {
        "by_status": {row["status"]: row["count"] for row in status_counts},
        "by_source": {row["source"]: row["count"] for row in source_counts},
        "by_type": {row["job_type"]: row["count"] for row in type_counts},
        "recent_7days": recent_count
    }

@app.get("/api/scrape-log")
async def get_scrape_log():
    """Get recent scrape log entries."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    logs = db.execute(
        """SELECT * FROM scrape_log
           ORDER BY started_at DESC
           LIMIT 50"""
    ).fetchall()

    return [dict(log) for log in logs]

@app.post("/api/tasks")
async def create_task(task: dict):
    """Create a new task."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    cursor = db.execute(
        """INSERT INTO tasks (title, status, priority, created_at)
           VALUES (?, ?, ?, ?)""",
        (task.get("title", "Untitled"), task.get("status", "open"),
         task.get("priority", 5), datetime.utcnow().isoformat())
    )
    db.commit()

    return {"id": cursor.lastrowid, "status": "created"}

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, updates: dict):
    """Update an existing task."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Build dynamic UPDATE statement
    set_clauses = []
    values = []

    for key, value in updates.items():
        if key in ["title", "status", "priority"]:
            set_clauses.append(f"{key} = ?")
            values.append(value)

    if set_clauses:
        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(task_id)

        sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?"
        db.execute(sql, values)
        db.commit()

        return {"status": "updated"}

    return {"status": "no_changes"}

# Serve frontend for all non-API routes (SPA fallback).
# Must not intercept /assets or /static — those are mounted above.
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve the React frontend for all non-API routes."""
    # Never return index.html for API/health/static asset paths
    if (
        full_path.startswith("api/")
        or full_path.startswith("assets/")
        or full_path.startswith("static/")
        or full_path == "health"
        or full_path.startswith("health/")
    ):
        raise HTTPException(status_code=404, detail="Not found")

    # If the path looks like a real file under static/, serve it
    candidate = os.path.join("static", full_path)
    if full_path and os.path.isfile(candidate):
        return FileResponse(candidate)

    # SPA client-side routing fallback
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="Frontend not built")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)