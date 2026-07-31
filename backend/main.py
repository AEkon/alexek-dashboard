from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote
from dotenv import load_dotenv

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db import default_db_path, init_db, is_scraper_running, log_scrape_start, log_scrape_end
from scrapers import squarespace_jobs, forum_questions
from auth import (
    COOKIE_NAME,
    auth_configured,
    auth_required_in_env,
    credentials_valid,
    create_session_token,
    session_cookie_kwargs,
    verify_session_token,
)

app = FastAPI(title="Personal Dashboard API")

# Load environment variables from .env file
load_dotenv()

# Mount static files for frontend.
# Vite emits /assets/*; also expose /static for the same build output.
app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Global database connection
db: Optional[sqlite3.Connection] = None
scheduler = AsyncIOScheduler()

PUBLIC_PATHS = {"/health", "/login", "/api/login"}


@app.middleware("http")
async def password_protect(request: Request, call_next):
    """Cookie session auth; /health and /login stay public."""
    path = request.url.path.rstrip("/") or "/"
    if path in PUBLIC_PATHS or path == "/health":
        return await call_next(request)

    if not auth_configured():
        if auth_required_in_env():
            return JSONResponse(
                {"detail": "DASHBOARD_PASSWORD is not configured"},
                status_code=503,
            )
        return await call_next(request)

    user = verify_session_token(request.cookies.get(COOKIE_NAME))
    if user:
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)

    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    return RedirectResponse(url=f"/login?next={quote(next_url, safe='')}", status_code=303)

async def scheduled_refresh_jobs():
    """Periodic Freelancer scrape (skips if a run is already in progress)."""
    global db
    if not db:
        return
    if is_scraper_running(db, "jobs"):
        print("Scheduled scrape skipped: already running")
        return
    print("Scheduled job scrape starting...")
    await refresh_jobs_background(db)


@app.on_event("startup")
async def startup():
    """Initialize database and scrape scheduler."""
    global db
    try:
        db_path = default_db_path()
        print("Starting Squarespace Job Dashboard API...")
        print(f"Database path: {db_path}")
        db = init_db(db_path)

        # Clear scrapes interrupted by a previous process crash/redeploy
        db.execute(
            """UPDATE scrape_log
               SET status = 'failed',
                   finished_at = ?,
                   error = COALESCE(error, 'interrupted by restart')
               WHERE status = 'running'""",
            (datetime.utcnow().isoformat(),),
        )
        db.commit()
        print("Database initialized successfully")

        interval = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))
        if interval > 0:
            scheduler.add_job(
                scheduled_refresh_jobs,
                "interval",
                minutes=interval,
                id="jobs_scrape",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
            print(f"Scrape scheduler started: every {interval} minute(s)")
            if os.getenv("SCRAPE_ON_STARTUP", "1") == "1":
                asyncio.create_task(scheduled_refresh_jobs())

            # Add forum refresh scheduler
            forum_interval = int(os.getenv("FORUM_SCRAPE_INTERVAL_MINUTES", "30"))
            if forum_interval > 0:
                scheduler.add_job(
                    scheduled_refresh_forum,
                    "interval",
                    minutes=forum_interval,
                    id="forum_scrape",
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
                print(f"Forum scraper started: every {forum_interval} minute(s)")
                if os.getenv("FORUM_SCRAPE_ON_STARTUP", "1") == "1":
                    asyncio.create_task(scheduled_refresh_forum())
        else:
            print("Scrape scheduler disabled (SCRAPE_INTERVAL_MINUTES=0)")

        print("API ready to serve requests")
    except Exception as e:
        print(f"Startup error: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    """Stop scheduler and close database connection."""
    global db
    if scheduler.running:
        scheduler.shutdown(wait=False)
    if db:
        db.close()

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": default_db_path(),
        "scrape_interval_minutes": int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30")),
    }

@app.get("/login")
async def login_page(request: Request):
    """Serve the branded login page (no Basic Auth popup)."""
    if auth_configured() and verify_session_token(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(url="/", status_code=303)
    login_path = os.path.join("static", "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    raise HTTPException(status_code=404, detail="Login page missing")

@app.post("/api/login")
async def api_login(payload: dict):
    """Validate credentials and set an HttpOnly session cookie."""
    if not auth_configured():
        if auth_required_in_env():
            raise HTTPException(status_code=503, detail="DASHBOARD_PASSWORD is not configured")
        # Local without password: no-op success
        return {"status": "ok"}

    username = str(payload.get("username", ""))
    password = str(payload.get("password", ""))
    if not credentials_valid(username, password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session_token(username)
    response = JSONResponse({"status": "ok"})
    response.set_cookie(**session_cookie_kwargs(token))
    return response

@app.post("/api/logout")
async def api_logout():
    """Clear the session cookie."""
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response

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

CLOSED_JOB_STATUSES = ("won", "lost", "no_reply")
ALLOWED_JOB_STATUSES = {"new", "interested", "applied", "skipped", "archived", "gone", *CLOSED_JOB_STATUSES}
QUERY_JOB_STATUSES = ALLOWED_JOB_STATUSES | {"closed"}


@app.get("/api/jobs")
async def get_jobs(
    job_type: Optional[str] = None,
    status: str = "new",
    outcome: Optional[str] = None,
    limit: int = 50,
    source: Optional[str] = None,
):
    """Get Squarespace jobs with optional filtering.
    Callers: frontend App.tsx. status=closed aggregates won/lost/no_reply; outcome narrows.
    User: Implement outcome tracking plan.
    """
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if status not in QUERY_JOB_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {sorted(QUERY_JOB_STATUSES)}",
        )

    where_conditions = []
    values: list = []

    if status == "closed":
        if outcome:
            if outcome not in CLOSED_JOB_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid outcome. Allowed: {list(CLOSED_JOB_STATUSES)}",
                )
            where_conditions.append("status = ?")
            values.append(outcome)
        else:
            placeholders = ",".join("?" for _ in CLOSED_JOB_STATUSES)
            where_conditions.append(f"status IN ({placeholders})")
            values.extend(CLOSED_JOB_STATUSES)
    else:
        where_conditions.append("status = ?")
        values.append(status)

    if job_type:
        where_conditions.append("job_type = ?")
        values.append(job_type)

    if source:
        where_conditions.append("source = ?")
        values.append(source)

    where_clause = " AND ".join(where_conditions)
    values.append(limit)

    jobs = db.execute(
        f"""SELECT * FROM jobs
           WHERE {where_clause}
           ORDER BY
             CASE WHEN priority_score IS NULL THEN 1 ELSE 0 END,
             priority_score DESC,
             posted_date DESC
           LIMIT ?""",
        values,
    ).fetchall()

    return [dict(job) for job in jobs]

@app.get("/api/jobs/search")
async def search_jobs(q: str, status: str = "new", limit: int = 50):
    """Search jobs by keywords in title or description."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if status not in QUERY_JOB_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(QUERY_JOB_STATUSES)}")

    search_pattern = f"%{q}%"
    if status == "closed":
        placeholders = ",".join("?" for _ in CLOSED_JOB_STATUSES)
        jobs = db.execute(
            f"""SELECT * FROM jobs
               WHERE status IN ({placeholders})
               AND (title LIKE ? OR description LIKE ? OR keyword_matches LIKE ?)
               ORDER BY posted_date DESC
               LIMIT ?""",
            (*CLOSED_JOB_STATUSES, search_pattern, search_pattern, search_pattern, limit),
        ).fetchall()
    else:
        jobs = db.execute(
            """SELECT * FROM jobs
               WHERE status = ?
               AND (title LIKE ? OR description LIKE ? OR keyword_matches LIKE ?)
               ORDER BY posted_date DESC
               LIMIT ?""",
            (status, search_pattern, search_pattern, search_pattern, limit),
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
        if key == "status":
            if value not in ALLOWED_JOB_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status. Allowed: {sorted(ALLOWED_JOB_STATUSES)}",
                )
            set_clauses.append("status = ?")
            values.append(value)
        elif key == "job_type":
            set_clauses.append("job_type = ?")
            values.append(value)
        elif key == "earnings_usd":
            try:
                amount = None if value in (None, "") else float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="earnings_usd must be a number")
            if amount is not None and amount < 0:
                raise HTTPException(status_code=400, detail="earnings_usd must be >= 0")
            set_clauses.append("earnings_usd = ?")
            values.append(amount)

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

async def refresh_forum_background(conn: sqlite3.Connection):
    """Background task to refresh forum questions."""
    log_id = log_scrape_start(conn, "forum_questions")

    try:
        results = await forum_questions.scrape(conn)
        total = results.get("total_questions", 0)
        errors = results.get("errors", [])
        error_summary = "; ".join(errors) if errors else None

        # Use 'success' if we got any results or no errors, 'failed' otherwise
        status = "success" if total > 0 or not errors else "failed"
        log_scrape_end(conn, log_id, status, total, error_summary)

    except Exception as e:
        log_scrape_end(conn, log_id, "failed", 0, str(e))
        print(f"Forum refresh failed: {e}")

async def scheduled_refresh_forum():
    """Scheduled task to refresh forum questions."""
    if db:
        await refresh_forum_background(db)

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

    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    weekly_row = db.execute(
        """SELECT COALESCE(SUM(earnings_usd), 0) AS total
           FROM jobs
           WHERE status = 'won'
             AND earnings_usd IS NOT NULL
             AND COALESCE(updated_at, created_at) >= ?""",
        (week_ago,),
    ).fetchone()
    weekly_revenue = float(weekly_row["total"] or 0) if weekly_row else 0.0

    return {
        "by_status": {row["status"]: row["count"] for row in status_counts},
        "by_source": {row["source"]: row["count"] for row in source_counts},
        "by_type": {row["job_type"]: row["count"] for row in type_counts},
        "recent_7days": recent_count,
        "weekly_revenue_usd": weekly_revenue,
    }

@app.get("/api/forum/questions")
async def get_forum_questions(
    status: str = "new",
    source: Optional[str] = None,
    limit: int = 50
):
    """Get forum questions with filtering."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Get all unsolved questions (Squarespace RSS doesn't provide comment counts)
    query = "SELECT * FROM forum_questions WHERE status = ?"
    params = [status]

    if source:
        query += " AND source = ?"
        params.append(source)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    questions = db.execute(query, params).fetchall()
    return [dict(q) for q in questions]

@app.post("/api/forum/refresh")
async def refresh_forum(background_tasks: BackgroundTasks):
    """Trigger forum scraping in background."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    if is_scraper_running(db, "forum_questions"):
        return {"status": "already_running"}

    background_tasks.add_task(forum_questions.scrape, db)
    return {"status": "refreshing"}

@app.patch("/api/forum/questions/{question_id}")
async def update_forum_question(question_id: int, updates: dict):
    """Update forum question status or add answer URL."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Validate question exists
    question = db.execute("SELECT id FROM forum_questions WHERE id = ?", (question_id,)).fetchone()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Build update dynamically
    allowed_fields = ["status", "answered_at", "answer_url", "comments_count"]
    update_parts = []
    params = []

    for field in allowed_fields:
        if field in updates:
            update_parts.append(f"{field} = ?")
            params.append(updates[field])

    if not update_parts:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    params.append(question_id)
    db.execute(
        f"UPDATE forum_questions SET {', '.join(update_parts)}, updated_at = ? WHERE id = ?",
        params + [datetime.utcnow().isoformat()]
    )
    db.commit()

    return {"status": "updated"}

@app.get("/api/forum/stats")
async def get_forum_stats():
    """Get forum statistics."""
    if not db:
        raise HTTPException(status_code=503, detail="Database not initialized")

    # Get counts by status
    status_counts = db.execute("""
        SELECT status, COUNT(*) as count
        FROM forum_questions
        GROUP BY status
    """).fetchall()

    # Get total count for debugging
    total_count = db.execute("SELECT COUNT(*) FROM forum_questions").fetchone()

    # Get counts by source
    source_counts = db.execute("""
        SELECT source, COUNT(*) as count
        FROM forum_questions
        WHERE status = 'new'
        GROUP BY source
    """).fetchall()

    stats = {
        "by_status": {row["status"]: row["count"] for row in status_counts},
        "by_source": {row["source"]: row["count"] for row in source_counts},
        "_debug": {"total_questions": total_count[0]}
    }

    print(f"📊 Forum stats: {stats}")
    return stats

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
        or full_path == "login"
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