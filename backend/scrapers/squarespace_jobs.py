"""Squarespace job scrapers.

Callers: backend/main.py refresh_jobs_background → scrape().
APIs: Freelancer RSS; optional Upwork GraphQL via env.
Schema: jobs (source, source_id, title, ...), scrape_log.
User: "ok implement" (Freelancer RSS, drop Reddit, Upwork behind env).
"""
import feedparser
import httpx
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import html

USER_AGENT = "alexek-dashboard/1.0 (+https://hq.alexek.com)"

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


def extract_rate(text: str) -> Optional[Dict[str, int]]:
    rate_patterns = [
        r"\$(\d+)-\$?(\d+)",
        r"\$(\d+)\s*/\s*hr",
        r"\$(\d+)\s*/\s*hour",
        r"fixed price.*?\$(\d+)",
        r"budget.*?\$(\d+)",
    ]
    for pattern in rate_patterns:
        match = re.search(pattern, text.lower())
        if not match:
            continue
        try:
            if len(match.groups()) >= 2 and match.group(2):
                return {"rate_min": int(match.group(1)), "rate_max": int(match.group(2))}
            rate = int(match.group(1))
            return {"rate_min": rate, "rate_max": rate}
        except (ValueError, IndexError):
            continue
    return None


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
) -> None:
    now = datetime.utcnow().isoformat()
    db.execute(
        """
        INSERT INTO jobs (
            source, source_id, title, description, url, posted_date, job_type,
            rate_min, rate_max, currency, keyword_matches, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            url = excluded.url,
            posted_date = excluded.posted_date,
            job_type = excluded.job_type,
            rate_min = CASE WHEN excluded.rate_min > 0 THEN excluded.rate_min ELSE rate_min END,
            rate_max = CASE WHEN excluded.rate_max > 0 THEN excluded.rate_max ELSE rate_max END,
            keyword_matches = excluded.keyword_matches,
            updated_at = excluded.updated_at,
            status = CASE WHEN status = 'archived' THEN 'archived' ELSE excluded.status END
        """,
        (
            source,
            source_id,
            title,
            description,
            url,
            posted_date,
            job_type,
            rate_min,
            rate_max,
            "USD",
            keyword_matches,
            "new",
            now,
            now,
        ),
    )


async def scrape_freelancer_rss(db) -> int:
    """Scrape Freelancer.com public RSS for Squarespace projects."""
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
    for entry in feed.entries[:50]:
        title = clean_html(entry.get("title", ""))
        description = clean_html(entry.get("summary") or entry.get("description", ""))
        link = entry.get("link", "")
        published = entry.get("published") or entry.get("updated") or ""

        if not title or not link:
            continue
        if not is_squarespace_job(title, description):
            continue

        rate_info = extract_rate(f"{title} {description}")
        job_type = "short-term" if is_short_term_job(title, description) else "unknown"
        keywords = matched_keywords(title, description)
        posted_date = parse_feed_date(published)

        source_id = None
        id_match = re.search(r"/projects/(\d+)", link)
        if id_match:
            source_id = id_match.group(1)
        else:
            source_id = re.sub(r"[^\w-]", "", link.rstrip("/").split("/")[-1])[:80] or link[-50:]

        upsert_job(
            db,
            source="freelancer",
            source_id=source_id,
            title=title,
            description=description[:2000],
            url=link,
            posted_date=posted_date,
            job_type=job_type,
            keyword_matches=keywords,
            rate_min=rate_info.get("rate_min") if rate_info else None,
            rate_max=rate_info.get("rate_max") if rate_info else None,
        )
        rows += 1

    db.commit()
    return rows


def upwork_configured() -> bool:
    return bool(
        os.getenv("UPWORK_CLIENT_ID")
        and os.getenv("UPWORK_CLIENT_SECRET")
        and os.getenv("UPWORK_REFRESH_TOKEN")
    )


async def scrape_upwork_graphql(db) -> int:
    """Scrape Upwork via GraphQL when OAuth credentials are configured."""
    if not upwork_configured():
        return 0

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
        rate_info = extract_rate(f"{title} {description}")
        job_type = "short-term" if is_short_term_job(title, description) else "unknown"

        upsert_job(
            db,
            source="upwork",
            source_id=job_id[:80],
            title=title,
            description=description[:2000],
            url=url,
            posted_date=posted_date,
            job_type=job_type,
            keyword_matches=matched_keywords(title, description),
            rate_min=rate_info.get("rate_min") if rate_info else None,
            rate_max=rate_info.get("rate_max") if rate_info else None,
        )
        rows += 1

    db.commit()
    return rows


async def scrape_all(db) -> Dict[str, object]:
    """Run configured sources independently; collect counts and errors."""
    results: Dict[str, object] = {
        "freelancer": 0,
        "upwork": 0,
        "total": 0,
        "errors": [],
        "skipped": [],
    }
    errors: List[str] = []

    try:
        results["freelancer"] = await scrape_freelancer_rss(db)
    except Exception as e:
        msg = f"freelancer: {e}"
        errors.append(msg)
        print(f"Scraping error: {msg}")

    if upwork_configured():
        try:
            results["upwork"] = await scrape_upwork_graphql(db)
        except Exception as e:
            msg = f"upwork: {e}"
            errors.append(msg)
            print(f"Scraping error: {msg}")
    else:
        results["skipped"] = ["upwork (missing UPWORK_CLIENT_ID/SECRET/REFRESH_TOKEN)"]

    results["total"] = int(results["freelancer"] or 0) + int(results["upwork"] or 0)
    results["errors"] = errors
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

    return total, error_msg
