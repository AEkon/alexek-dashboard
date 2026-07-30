"""Squarespace job scrapers.

Callers: backend/main.py refresh_jobs_background → scrape().
APIs: Freelancer RSS; optional Upwork GraphQL via env.
Schema: jobs (source, source_id, title, ...), scrape_log.
User: "Implement the plan" (job triage + lean DB).
"""
import feedparser
import httpx
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import html

from db import purge_stale_data
from availability import mark_unavailable_jobs
from notify import alert_min_score, notify_new_high_score_jobs

USER_AGENT = "alexek-dashboard/1.0 (+https://hq.alexek.com)"
DESCRIPTION_SNIPPET_LEN = 400


def meets_min_score(priority_score) -> bool:
    """Only persist/alert jobs at or above ALERT_MIN_SCORE (default 50)."""
    if priority_score is None:
        return False
    try:
        return float(priority_score) >= alert_min_score()
    except (TypeError, ValueError):
        return False

# Phrase matches recorded as enrichment; bare "squarespace" is enough to include a job.
SQUARESPACE_KEYWORDS = [
    "squarespace designer",
    "squarespace fix",
    "squarespace custom css",
    "squarespace expert",
    "squarespace help",
    "squarespace website",
    "squarespace development",
    "squarespace template",
    "squarespace redesign",
    "squarespace",
]

SHORT_TERM_INDICATORS = [
    "ad-hoc",
    "short-term",
    "one-time",
    "single project",
    "quick fix",
    "micro project",
    "small job",
    "hourly",
    "fixed price",
]

FREELANCER_RSS_URL = "https://www.freelancer.com/rss.xml?keyword=squarespace"


def is_squarespace_job(title: str, description: str) -> bool:
    """True if the listing mentions Squarespace."""
    return "squarespace" in f"{title} {description}".lower()


def matched_keywords(title: str, description: str) -> str:
    combined = f"{title} {description}".lower()
    hits = [kw for kw in SQUARESPACE_KEYWORDS if kw.lower() in combined]
    return ", ".join(hits) if hits else "squarespace"


def is_short_term_job(title: str, description: str) -> bool:
    combined = f"{title} {description}".lower()
    return any(indicator in combined for indicator in SHORT_TERM_INDICATORS)


def clean_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^<]+?>", "", text or "")).strip()


def parse_feed_date(published: str) -> str:
    if not published:
        return datetime.utcnow().isoformat()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            return datetime.strptime(published, fmt).isoformat()
        except ValueError:
            continue
    return datetime.utcnow().isoformat()


# Rough FX → USD for ranking only (not accounting-grade)
FX_TO_USD = {
    "USD": 1.0,
    "GBP": 1.27,
    "EUR": 1.08,
    "AUD": 0.65,
    "CAD": 0.73,
    "INR": 0.012,
    "SGD": 0.74,
    "NZD": 0.60,
}

# Effort heuristics: base 5, adjust by signals in title+description
EFFORT_HIGH = [
    ("migration", 3),
    ("migrate", 3),
    ("redesign", 3),
    ("rebrand", 2),
    ("from scratch", 3),
    ("full website", 3),
    ("full site", 3),
    ("entire website", 3),
    ("ecommerce", 2),
    ("e-commerce", 2),
    ("member area", 2),
    ("membership", 2),
    ("custom code", 2),
    ("developer mode", 2),
    ("multi-page", 2),
    ("multipage", 2),
    ("branding", 1),
    ("wordpress to squarespace", 3),
]

EFFORT_LOW = [
    ("quick fix", -3),
    ("bug fix", -3),
    ("css fix", -3),
    ("custom css", -2),
    ("small fix", -3),
    ("minor", -2),
    ("tweak", -2),
    ("mobile", -1),
    ("responsive", -1),
    ("seo", -1),
    ("optimization", -1),
    ("optimise", -1),
    ("optimize", -1),
    ("one page", -2),
    ("landing page", -1),
    ("quick", -2),
    ("simple", -2),
    ("urgent", -1),
]


def parse_budget(text: str) -> Optional[Dict[str, object]]:
    """Parse Freelancer-style Budget: $30 - $250 USD (and £/€ variants)."""
    if not text:
        return None

    patterns = [
        # Budget: $30 - $250 USD
        r"[Bb]udget:\s*([$£€]?)\s*([\d,]+(?:\.\d+)?)\s*[-–—to]+\s*([$£€]?)\s*([\d,]+(?:\.\d+)?)\s*([A-Z]{3})?",
        # Budget: $250 USD
        r"[Bb]udget:\s*([$£€]?)\s*([\d,]+(?:\.\d+)?)\s*([A-Z]{3})?",
        # ($30 - $250 USD) already covered by first; also bare range
        r"([$£€])\s*([\d,]+(?:\.\d+)?)\s*[-–—]\s*([$£€]?)\s*([\d,]+(?:\.\d+)?)\s*([A-Z]{3})?",
        # Hourly $75/hr
        r"([$£€])\s*([\d,]+(?:\.\d+)?)\s*/\s*hr",
    ]

    symbol_currency = {"$": "USD", "£": "GBP", "€": "EUR"}

    def to_int(raw: str) -> int:
        return int(float(raw.replace(",", "")))

    for i, pattern in enumerate(patterns):
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groups()
        try:
            if i in (0, 2) and len(groups) >= 4 and groups[3] and groups[1]:
                sym1, amin, sym2, amax = groups[0], groups[1], groups[2], groups[3]
                curr = (groups[4] if len(groups) > 4 else None) or symbol_currency.get(sym1) or symbol_currency.get(sym2) or "USD"
                rate_min, rate_max = to_int(amin), to_int(amax)
            elif i == 1:
                sym1, amin, curr = groups[0], groups[1], groups[2]
                curr = curr or symbol_currency.get(sym1) or "USD"
                rate_min = rate_max = to_int(amin)
            elif i == 3:
                sym1, amin = groups[0], groups[1]
                curr = symbol_currency.get(sym1) or "USD"
                rate_min = rate_max = to_int(amin)
            else:
                continue

            if rate_min > rate_max:
                rate_min, rate_max = rate_max, rate_min

            fx = FX_TO_USD.get(curr.upper(), 1.0)
            mid = (rate_min + rate_max) / 2.0
            mid_usd = int(round(mid * fx))
            display = f"{symbol_currency.get(curr, '') or ''}{rate_min}-{rate_max} {curr}".strip()
            if curr == "USD":
                display = f"${rate_min}-${rate_max}"
            elif curr == "GBP":
                display = f"£{rate_min}-£{rate_max}"
            elif curr == "EUR":
                display = f"€{rate_min}-€{rate_max}"
            else:
                display = f"{rate_min}-{rate_max} {curr}"

            return {
                "rate_min": rate_min,
                "rate_max": rate_max,
                "currency": curr.upper(),
                "budget": display,
                "budget_mid_usd": mid_usd,
            }
        except (ValueError, IndexError, TypeError):
            continue
    return None


def estimate_effort(title: str, description: str) -> int:
    """Estimate work difficulty 1–10 from listing text."""
    text = f"{title} {description}".lower()
    score = 5
    for phrase, delta in EFFORT_HIGH:
        if phrase in text:
            score += delta
    for phrase, delta in EFFORT_LOW:
        if phrase in text:
            score += delta
    # Longer briefs tend to mean more scope
    if len(description) > 1200:
        score += 1
    if len(description) > 2000:
        score += 1
    return max(1, min(10, score))


def compute_priority(budget_mid_usd: Optional[int], effort: int) -> Optional[float]:
    """Value per unit effort. Higher = better cost vs work."""
    if not budget_mid_usd or budget_mid_usd <= 0 or effort <= 0:
        return None
    return round(budget_mid_usd / float(effort), 2)


def extract_rate(text: str) -> Optional[Dict[str, int]]:
    """Backward-compatible wrapper around parse_budget."""
    parsed = parse_budget(text)
    if not parsed:
        return None
    return {"rate_min": int(parsed["rate_min"]), "rate_max": int(parsed["rate_max"])}


def upsert_job(
    db,
    *,
    source: str,
    source_id: str,
    title: str,
    description: str,
    url: str,
    posted_date: str,
    job_type: str,
    keyword_matches: str,
    rate_min: Optional[int] = None,
    rate_max: Optional[int] = None,
    currency: str = "USD",
    budget: Optional[str] = None,
    budget_mid_usd: Optional[int] = None,
    effort_score: Optional[int] = None,
    priority_score: Optional[float] = None,
) -> str:
    """Insert or update a job. Preserves triage status. Returns inserted|updated|noop."""
    snippet = (description or "")[:DESCRIPTION_SNIPPET_LEN]
    now = datetime.utcnow().isoformat()

    existing = db.execute(
        """SELECT title, description, url, posted_date, job_type,
                  rate_min, rate_max, currency, keyword_matches,
                  budget, budget_mid_usd, effort_score, priority_score
           FROM jobs WHERE source = ? AND source_id = ?""",
        (source, source_id),
    ).fetchone()

    if existing:
        same = (
            existing["title"] == title
            and (existing["description"] or "") == snippet
            and existing["url"] == url
            and existing["posted_date"] == posted_date
            and existing["job_type"] == job_type
            and existing["rate_min"] == rate_min
            and existing["rate_max"] == rate_max
            and (existing["currency"] or "USD") == currency
            and (existing["keyword_matches"] or "") == (keyword_matches or "")
            and (existing["budget"] or None) == budget
            and existing["budget_mid_usd"] == budget_mid_usd
            and existing["effort_score"] == effort_score
            and existing["priority_score"] == priority_score
        )
        if same:
            return "noop"

        # Never overwrite triage status on scrape updates
        db.execute(
            """UPDATE jobs SET
                title = ?, description = ?, url = ?, posted_date = ?, job_type = ?,
                rate_min = ?, rate_max = ?, currency = ?, keyword_matches = ?,
                budget = ?, budget_mid_usd = ?, effort_score = ?, priority_score = ?,
                updated_at = ?
               WHERE source = ? AND source_id = ?""",
            (
                title,
                snippet,
                url,
                posted_date,
                job_type,
                rate_min,
                rate_max,
                currency,
                keyword_matches,
                budget,
                budget_mid_usd,
                effort_score,
                priority_score,
                now,
                source,
                source_id,
            ),
        )
        return "updated"

    db.execute(
        """
        INSERT INTO jobs (
            source, source_id, title, description, url, posted_date, job_type,
            rate_min, rate_max, currency, keyword_matches, status, created_at, updated_at,
            budget, budget_mid_usd, effort_score, priority_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source,
            source_id,
            title,
            snippet,
            url,
            posted_date,
            job_type,
            rate_min,
            rate_max,
            currency,
            keyword_matches,
            "new",
            now,
            now,
            budget,
            budget_mid_usd,
            effort_score,
            priority_score,
        ),
    )
    return "inserted"


async def scrape_freelancer_rss(db):
    """Scrape Freelancer.com public RSS for Squarespace projects. Returns (rows, new_jobs)."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(FREELANCER_RSS_URL)

    if resp.status_code != 200:
        raise Exception(f"Freelancer RSS HTTP {resp.status_code}")

    content_type = (resp.headers.get("content-type") or "").lower()
    body_prefix = resp.content[:500].lower()
    if "html" in content_type and "xml" not in content_type and b"<rss" not in body_prefix:
        raise Exception("Freelancer RSS returned HTML instead of a feed")

    feed = feedparser.parse(resp.content)
    if not feed.entries and getattr(feed, "bozo", False):
        raise Exception(f"Freelancer RSS parse failed: {getattr(feed, 'bozo_exception', 'unknown')}")

    rows = 0
    new_jobs = []
    for entry in feed.entries[:50]:
        title = clean_html(entry.get("title", ""))
        description = clean_html(entry.get("summary") or entry.get("description", ""))
        link = entry.get("link", "")
        published = entry.get("published") or entry.get("updated") or ""

        if not title or not link:
            continue
        if not is_squarespace_job(title, description):
            continue

        budget_info = parse_budget(f"{title} {description}")
        effort = estimate_effort(title, description)
        mid_usd = int(budget_info["budget_mid_usd"]) if budget_info else None
        priority = compute_priority(mid_usd, effort)
        job_type = "short-term" if is_short_term_job(title, description) or effort <= 3 else "unknown"
        keywords = matched_keywords(title, description)
        posted_date = parse_feed_date(published)

        source_id = None
        guid = str(entry.get("id") or entry.get("guid") or "")
        guid_match = re.search(r"Freelancer_project_(\d+)", guid)
        id_match = re.search(r"/projects/(\d+)", link)
        if guid_match:
            source_id = guid_match.group(1)
        elif id_match:
            source_id = id_match.group(1)
        else:
            source_id = re.sub(r"[^\w-]", "", link.rstrip("/").split("/")[-1])[:80] or link[-50:]

        if not meets_min_score(priority):
            continue

        action = upsert_job(
            db,
            source="freelancer",
            source_id=source_id,
            title=title,
            description=description,
            url=link,
            posted_date=posted_date,
            job_type=job_type,
            keyword_matches=keywords,
            rate_min=int(budget_info["rate_min"]) if budget_info else None,
            rate_max=int(budget_info["rate_max"]) if budget_info else None,
            currency=str(budget_info["currency"]) if budget_info else "USD",
            budget=str(budget_info["budget"]) if budget_info else None,
            budget_mid_usd=mid_usd,
            effort_score=effort,
            priority_score=priority,
        )
        if action != "noop":
            rows += 1
        if action == "inserted":
            new_jobs.append({
                "title": title,
                "url": link,
                "budget": str(budget_info["budget"]) if budget_info else None,
                "priority_score": priority,
            })

    db.commit()
    return rows, new_jobs


def upwork_configured() -> bool:
    return bool(
        os.getenv("UPWORK_CLIENT_ID")
        and os.getenv("UPWORK_CLIENT_SECRET")
        and os.getenv("UPWORK_REFRESH_TOKEN")
    )


async def scrape_upwork_graphql(db):
    """Scrape Upwork via GraphQL when OAuth credentials are configured. Returns (rows, new_jobs)."""
    if not upwork_configured():
        return 0, []

    client_id = os.environ["UPWORK_CLIENT_ID"]
    client_secret = os.environ["UPWORK_CLIENT_SECRET"]
    refresh_token = os.environ["UPWORK_REFRESH_TOKEN"]

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        token_resp = await client.post(
            "https://www.upwork.com/api/v3/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise Exception(f"Upwork token refresh HTTP {token_resp.status_code}: {token_resp.text[:200]}")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise Exception("Upwork token response missing access_token")

        query = """
        query search($searchExpression_eq: String!) {
          marketplaceJobPostingsSearch(
            marketPlaceJobFilter: { searchExpression_eq: $searchExpression_eq }
            searchType: USER_JOBS_SEARCH
            sortAttributes: [{ field: RECENCY }]
          ) {
            edges {
              node {
                id
                title
                description
                ciphertext
                publishedDateTime
                job {
                  id
                }
              }
            }
          }
        }
        """
        gql_resp = await client.post(
            "https://api.upwork.com/graphql",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": {"searchExpression_eq": "squarespace"}},
        )
        if gql_resp.status_code != 200:
            raise Exception(f"Upwork GraphQL HTTP {gql_resp.status_code}: {gql_resp.text[:300]}")

        payload = gql_resp.json()
        if payload.get("errors"):
            raise Exception(f"Upwork GraphQL errors: {payload['errors']}")

        edges = (
            payload.get("data", {})
            .get("marketplaceJobPostingsSearch", {})
            .get("edges")
            or []
        )

    rows = 0
    new_jobs = []
    for edge in edges[:50]:
        node = edge.get("node") or {}
        title = clean_html(node.get("title") or "")
        description = clean_html(node.get("description") or "")
        ciphertext = node.get("ciphertext") or ""
        job_id = str((node.get("job") or {}).get("id") or node.get("id") or ciphertext)
        if not title or not job_id:
            continue
        if not is_squarespace_job(title, description):
            continue

        url = f"https://www.upwork.com/jobs/{ciphertext}" if ciphertext else f"https://www.upwork.com/jobs/~{job_id}"
        posted_date = node.get("publishedDateTime") or datetime.utcnow().isoformat()
        budget_info = parse_budget(f"{title} {description}")
        effort = estimate_effort(title, description)
        mid_usd = int(budget_info["budget_mid_usd"]) if budget_info else None
        priority = compute_priority(mid_usd, effort)
        job_type = "short-term" if is_short_term_job(title, description) or effort <= 3 else "unknown"

        if not meets_min_score(priority):
            continue

        action = upsert_job(
            db,
            source="upwork",
            source_id=job_id[:80],
            title=title,
            description=description,
            url=url,
            posted_date=posted_date,
            job_type=job_type,
            keyword_matches=matched_keywords(title, description),
            rate_min=int(budget_info["rate_min"]) if budget_info else None,
            rate_max=int(budget_info["rate_max"]) if budget_info else None,
            currency=str(budget_info["currency"]) if budget_info else "USD",
            budget=str(budget_info["budget"]) if budget_info else None,
            budget_mid_usd=mid_usd,
            effort_score=effort,
            priority_score=priority,
        )
        if action != "noop":
            rows += 1
        if action == "inserted":
            new_jobs.append({
                "title": title,
                "url": url,
                "budget": str(budget_info["budget"]) if budget_info else None,
                "priority_score": priority,
            })

    db.commit()
    return rows, new_jobs


async def scrape_all(db) -> Dict[str, object]:
    """Run configured sources independently; collect counts, new jobs, and errors."""
    results: Dict[str, object] = {
        "freelancer": 0,
        "upwork": 0,
        "total": 0,
        "errors": [],
        "skipped": [],
        "new_jobs": [],
    }
    errors: List[str] = []
    new_jobs: List[dict] = []

    try:
        count, jobs = await scrape_freelancer_rss(db)
        results["freelancer"] = count
        new_jobs.extend(jobs)
    except Exception as e:
        msg = f"freelancer: {e}"
        errors.append(msg)
        print(f"Scraping error: {msg}")

    if upwork_configured():
        try:
            count, jobs = await scrape_upwork_graphql(db)
            results["upwork"] = count
            new_jobs.extend(jobs)
        except Exception as e:
            msg = f"upwork: {e}"
            errors.append(msg)
            print(f"Scraping error: {msg}")
    else:
        results["skipped"] = ["upwork (missing UPWORK_CLIENT_ID/SECRET/REFRESH_TOKEN)"]

    results["total"] = int(results["freelancer"] or 0) + int(results["upwork"] or 0)
    results["errors"] = errors
    results["new_jobs"] = new_jobs
    return results


async def scrape(db) -> Tuple[int, Optional[str]]:
    """
    Main scrape entrypoint.
    Returns (rows_affected, error_message_or_None).
    Raises when Freelancer fails and zero rows were written.
    """
    results = await scrape_all(db)
    total = int(results["total"] or 0)
    errors: List[str] = list(results.get("errors") or [])
    error_msg = "; ".join(errors) if errors else None

    if total == 0 and errors and int(results.get("freelancer") or 0) == 0:
        raise Exception(error_msg or "All job sources failed")

    purge_stale_data(db)

    gone_count, avail_warn = await mark_unavailable_jobs(db)
    if avail_warn:
        error_msg = f"{error_msg}; {avail_warn}" if error_msg else avail_warn
    if gone_count:
        print(f"Marked {gone_count} job(s) as gone")

    alert_err = await notify_new_high_score_jobs(list(results.get("new_jobs") or []))
    if alert_err:
        error_msg = f"{error_msg}; alerts: {alert_err}" if error_msg else f"alerts: {alert_err}"

    return total, error_msg
