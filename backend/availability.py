"""Check whether saved job listings are still open.

Callers: scrapers/squarespace_jobs.scrape() after feed upsert.
Checks jobs in status new/interested (not applied/closed).
Marks unavailable listings as status=gone.
Env: AVAILABILITY_CHECK_LIMIT (default 15).
User: "yes" to availability checks on refresh.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import List, Optional, Tuple

import httpx

USER_AGENT = "alexek-dashboard/1.0 (+https://hq.alexek.com)"

# Phrases that usually mean the Freelancer/Upwork listing is no longer open for bids
GONE_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"this project is closed",
        r"project is closed",
        r"project has been closed",
        r"no longer available",
        r"project was cancelled",
        r"project has been cancelled",
        r"project canceled",
        r"award(ed)? to another",
        r"bidding is closed",
        r"bids are closed",
        r"this job is no longer available",
        r"job posting.*(closed|removed|unavailable)",
        r"page not found",
        r"404\s*-\s*not found",
    )
]


def check_limit() -> int:
    try:
        return max(0, int(os.getenv("AVAILABILITY_CHECK_LIMIT", "15")))
    except ValueError:
        return 15


def listing_looks_gone(status_code: int, body: str) -> bool:
    if status_code in (404, 410, 451):
        return True
    if status_code >= 400:
        return False
    sample = (body or "")[:80000]
    return any(p.search(sample) for p in GONE_PATTERNS)


async def probe_url(client: httpx.AsyncClient, url: str) -> Tuple[bool, Optional[str]]:
    """Return (is_gone, error_or_None)."""
    try:
        resp = await client.get(url)
        # Some sites block bots with 403 — treat as unknown, not gone
        if resp.status_code == 403:
            return False, None
        text = resp.text or ""
        return listing_looks_gone(resp.status_code, text), None
    except Exception as e:
        return False, str(e)


async def mark_unavailable_jobs(db) -> Tuple[int, Optional[str]]:
    """
    Probe open inbox/shortlist jobs and mark gone ones.
    Returns (marked_count, warning_or_None).
    """
    limit = check_limit()
    if limit == 0:
        return 0, None

    rows = db.execute(
        """SELECT id, url FROM jobs
           WHERE status IN ('new', 'interested')
             AND url IS NOT NULL
             AND url != ''
           ORDER BY COALESCE(updated_at, created_at) ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()

    if not rows:
        return 0, None

    marked = 0
    errors: List[str] = []
    now = datetime.utcnow().isoformat()

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for row in rows:
            gone, err = await probe_url(client, row["url"])
            if err:
                errors.append(err)
                continue
            if gone:
                db.execute(
                    "UPDATE jobs SET status = 'gone', updated_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
                marked += 1

    if marked:
        db.commit()

    warning = None
    if errors:
        warning = f"availability probes failed: {len(errors)}"
    return marked, warning
