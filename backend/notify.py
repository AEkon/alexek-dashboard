"""WhatsApp alerts via CallMeBot.

Callers: scrapers/squarespace_jobs.scrape() after new inserts.
Env: WHATSAPP_PHONE, WHATSAPP_APIKEY, ALERT_MIN_SCORE (default 50; also gates DB inserts), ALERT_MAX_PER_SCRAPE (default 5).
No data files. User: "CallMeBot api key: 3556567" — key must live in Railway env only.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"


def alerts_configured() -> bool:
    return bool(os.getenv("WHATSAPP_PHONE") and os.getenv("WHATSAPP_APIKEY"))


def alert_min_score() -> float:
    try:
        return float(os.getenv("ALERT_MIN_SCORE", "50"))
    except ValueError:
        return 50.0


def alert_max_per_scrape() -> int:
    try:
        return max(0, int(os.getenv("ALERT_MAX_PER_SCRAPE", "5")))
    except ValueError:
        return 5


def format_job_alert(job: Dict[str, Any]) -> str:
    title = job.get("title") or "New Squarespace job"
    score = job.get("priority_score")
    budget = job.get("budget") or "Budget n/a"
    url = job.get("url") or ""
    score_bit = f"Score {score}" if score is not None else "Score n/a"
    return f"New gig: {title}\n{score_bit} · {budget}\n{url}"


async def send_whatsapp(text: str) -> Optional[str]:
    """Send one WhatsApp message. Returns error string or None on success."""
    phone = (os.getenv("WHATSAPP_PHONE") or "").strip()
    apikey = (os.getenv("WHATSAPP_APIKEY") or "").strip()
    if not phone or not apikey:
        return "WhatsApp not configured"

    params = {
        "phone": phone.replace(" ", ""),
        "text": text,
        "apikey": apikey,
    }
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(CALLMEBOT_URL, params=params)
        if resp.status_code >= 400:
            return f"CallMeBot HTTP {resp.status_code}: {resp.text[:200]}"
        body = (resp.text or "").lower()
        if "error" in body and "api" in body:
            return f"CallMeBot: {resp.text[:200]}"
        return None
    except Exception as e:
        return str(e)


async def notify_new_high_score_jobs(jobs: List[Dict[str, Any]]) -> Optional[str]:
    """Alert for newly inserted jobs at/above ALERT_MIN_SCORE. Caps per scrape."""
    if not alerts_configured() or not jobs:
        return None

    threshold = alert_min_score()
    cap = alert_max_per_scrape()
    if cap == 0:
        return None

    eligible = [
        j
        for j in jobs
        if j.get("priority_score") is not None and float(j["priority_score"]) >= threshold
    ]
    eligible.sort(key=lambda j: float(j.get("priority_score") or 0), reverse=True)
    eligible = eligible[:cap]

    errors: List[str] = []
    for job in eligible:
        err = await send_whatsapp(format_job_alert(job))
        if err:
            errors.append(err)
    if errors:
        return "; ".join(errors[:3])
    return None
