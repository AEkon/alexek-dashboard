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
from urllib.parse import quote_plus
import html
import json

from db import purge_stale_data
from availability import mark_unavailable_jobs
from notify import alert_min_score, notify_new_high_score_jobs

USER_AGENT = "alexek-dashboard/1.0 (+https://hq.alexek.com)"
DESCRIPTION_SNIPPET_LEN = 400

PROPOSAL_SYSTEM = """You write Freelancer.com bids in first person as Alex — like a real freelancer messaging a client, not a marketing page.

WHO ALEX IS (use only the bits that fit THIS job; never paste the whole bio):
Squarespace designer/developer who does custom CSS, HTML, and JavaScript when the drag-and-drop editor isn't enough. Builds clean, responsive sites that stay stable; can handle custom code injection and functionality Squarespace doesn't offer out of the box.

Return ONLY valid JSON:
{"proposal": "string", "bid_amount": number, "days": integer}

VOICE — sound human:
- Lead with THEIR project in sentence one (what you'll fix/build). Yourself second, briefly.
- 4–8 sentences total. Mix short and longer lines. One short paragraph is fine; two max.
- Plain spoken English. Contractions OK (I'll, you're, doesn't).
- One concrete next step (e.g. need editor access + page URL, then ship the CSS fix).
- End with 1–2 specific clarifying questions tied to unclear bits in the listing — peer-to-peer, not "Could you share more details?"
- Light sign-off with just "Alex" if it fits. No signature block.

DO NOT use these phrases (they read as AI/brochure):
bespoke, under the hood, digital solutions, high-end, leverage, seamless, passionate, "as a Squarespace specialist", "I specialize in", "I hope this finds you well", Dear Hiring Manager, "I'm excited to", "perfect fit", "don't hesitate", markdown, bullets.

STILL COVER (without sounding like a checklist):
1. Clear, typo-free writing
2. Proof you read THIS brief — name a concrete detail from title/description
3. How your Squarespace custom-code skills apply + how you'll work
4. Those clarifying questions

Never invent portfolio links, client names, or past project titles.

bid_amount: number only, listing currency (usually USD). Stay in client budget range if present; slightly under mid when competitive. Realistic fixed price if no budget.
days: whole number ≥ 1. Quick CSS/fix 1–2; mid 3–5; redesign/migration 7–14.
"""


def generate_ai_proposal(job: Dict) -> Optional[Dict[str, object]]:
    """Generate Freelancer proposal + bid amount + days via Groq. On-demand only."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("✗ GROQ_API_KEY not set — cannot generate job proposal")
        return None

    title = (job.get("title") or "").strip()
    description = (job.get("description") or "").strip()
    budget = job.get("budget") or "not stated"
    mid = job.get("budget_mid_usd")
    rate_min = job.get("rate_min")
    rate_max = job.get("rate_max")
    currency = (job.get("currency") or "USD").upper()
    effort = job.get("effort_score")
    job_type = job.get("job_type") or "unknown"

    prompt = f"""Write a short, human Freelancer bid for this job. Sound like Alex typing to the client — not a cover letter template.

Title: {title}

Description:
{description[:1500] if description else '(no description)'}

Budget text: {budget}
Mid budget (USD approx): {mid if mid is not None else 'n/a'}
Rate min/max: {rate_min} / {rate_max}
Currency: {currency}
Effort hint (1–10): {effort if effort is not None else 'n/a'}
Job type: {job_type}

Open by addressing their actual ask. Keep it 4–8 sentences. One real next step. End with 1–2 sharp questions. JSON only: proposal, bid_amount, days."""

    if not hasattr(generate_ai_proposal, "_client"):
        try:
            from groq import Groq
            generate_ai_proposal._client = Groq(api_key=api_key)
        except Exception as e:
            print(f"✗ Groq client init failed: {e}")
            return None

    client = generate_ai_proposal._client
    try:
        messages = [
            {"role": "system", "content": PROPOSAL_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                max_tokens=700,
                temperature=0.55,
                response_format={"type": "json_object"},
            )
        except Exception:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                max_tokens=700,
                temperature=0.55,
            )
        raw = (response.choices[0].message.content or "").strip()
        if not raw:
            return None

        # Tolerate fenced ```json blocks if response_format unavailable
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
        proposal = str(data.get("proposal") or "").strip()
        bid = data.get("bid_amount")
        days = data.get("days")

        try:
            bid_amount = float(bid)
        except (TypeError, ValueError):
            return None
        try:
            bid_days = int(days)
        except (TypeError, ValueError):
            return None

        if not proposal or len(proposal) < 40:
            return None
        if bid_amount <= 0:
            return None
        if bid_days < 1:
            bid_days = 1

        return {
            "proposal": proposal,
            "bid_amount": round(bid_amount, 2),
            "days": bid_days,
        }
    except Exception as e:
        print(f"✗ Job proposal generation failed: {e}")
        return None



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

# Multiple keyword feeds catch more Squarespace gigs than a single RSS query.
FREELANCER_FEED_KEYWORDS = [
    "squarespace",
    "squarespace css",
    "squarespace designer",
    "squarespace redesign",
    "squarespace fix",
    "squarespace expert",
]

# Soft optional: PeoplePerHour public search RSS (often empty; never fails the scrape).
PPH_RSS_URL = "https://www.peopleperhour.com/freelance-jobs.rss?q=squarespace"


def freelancer_rss_url(keyword: str) -> str:
    return f"https://www.freelancer.com/rss.xml?keyword={quote_plus(keyword)}"


def detect_job_kind(title: str, description: str, keyword_matches: str = "") -> str:
    """Classify listing for proposal templates + outcome bias: fix|css|redesign|general."""
    text = f"{title} {description} {keyword_matches}".lower()
    if any(p in text for p in ("redesign", "rebrand", "from scratch", "full website", "full site", "migration", "migrate")):
        return "redesign"
    if any(p in text for p in ("custom css", "css fix", "css", "styling", "style")):
        return "css"
    if any(p in text for p in ("quick fix", "bug fix", "small fix", "fix", "tweak", "urgent", "broken")):
        return "fix"
    return "general"


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


def compute_priority(
    budget_mid_usd: Optional[int],
    effort: int,
    outcome_mult: float = 1.0,
) -> Optional[float]:
    """Value per unit effort, optionally scaled by historical outcome multiplier."""
    if not budget_mid_usd or budget_mid_usd <= 0 or effort <= 0:
        return None
    base = budget_mid_usd / float(effort)
    mult = outcome_mult if outcome_mult and outcome_mult > 0 else 1.0
    return round(base * mult, 2)


def load_outcome_kind_multipliers(db) -> Dict[str, float]:
    """
    Bias priority by win rate of similar job kinds (fix/css/redesign/general).
    Needs ≥2 closed outcomes for a kind; otherwise 1.0 (no bias).
    Maps win_rate 0..1 → multiplier ~0.75..1.35.
    """
    try:
        rows = db.execute(
            """SELECT title, description, keyword_matches, status
               FROM jobs
               WHERE status IN ('won', 'lost', 'no_reply')"""
        ).fetchall()
    except Exception:
        return {}

    counts: Dict[str, Dict[str, int]] = {}
    for row in rows:
        kind = detect_job_kind(
            row["title"] or "",
            row["description"] or "",
            row["keyword_matches"] or "",
        )
        bucket = counts.setdefault(kind, {"won": 0, "lost": 0, "no_reply": 0})
        status = row["status"]
        if status in bucket:
            bucket[status] += 1

    multipliers: Dict[str, float] = {}
    for kind, c in counts.items():
        total = c["won"] + c["lost"] + c["no_reply"]
        if total < 2:
            continue
        win_rate = c["won"] / float(total)
        multipliers[kind] = round(0.75 + 0.6 * win_rate, 3)
    return multipliers


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


async def _ingest_freelancer_entries(db, entries, outcome_mults: Dict[str, float], seen_ids: set):
    """Upsert Freelancer feed entries. Mutates seen_ids. Returns (rows, new_jobs)."""
    rows = 0
    new_jobs = []
    for entry in entries[:50]:
        title = clean_html(entry.get("title", ""))
        description = clean_html(entry.get("summary") or entry.get("description", ""))
        link = entry.get("link", "")
        published = entry.get("published") or entry.get("updated") or ""

        if not title or not link:
            continue
        if not is_squarespace_job(title, description):
            continue

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

        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)

        budget_info = parse_budget(f"{title} {description}")
        effort = estimate_effort(title, description)
        mid_usd = int(budget_info["budget_mid_usd"]) if budget_info else None
        keywords = matched_keywords(title, description)
        kind = detect_job_kind(title, description, keywords)
        priority = compute_priority(mid_usd, effort, outcome_mults.get(kind, 1.0))
        job_type = "short-term" if is_short_term_job(title, description) or effort <= 3 else "unknown"
        posted_date = parse_feed_date(published)

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

    return rows, new_jobs


async def scrape_freelancer_rss(db):
    """Scrape multiple Freelancer keyword RSS feeds. Returns (rows, new_jobs)."""
    outcome_mults = load_outcome_kind_multipliers(db)
    seen_ids: set = set()
    rows = 0
    new_jobs = []
    feed_errors: List[str] = []

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        for keyword in FREELANCER_FEED_KEYWORDS:
            url = freelancer_rss_url(keyword)
            try:
                resp = await client.get(url)
            except Exception as e:
                feed_errors.append(f"{keyword}: {e}")
                continue

            if resp.status_code != 200:
                feed_errors.append(f"{keyword}: HTTP {resp.status_code}")
                continue

            content_type = (resp.headers.get("content-type") or "").lower()
            body_prefix = resp.content[:500].lower()
            if "html" in content_type and "xml" not in content_type and b"<rss" not in body_prefix:
                feed_errors.append(f"{keyword}: HTML instead of feed")
                continue

            feed = feedparser.parse(resp.content)
            if not feed.entries and getattr(feed, "bozo", False):
                feed_errors.append(f"{keyword}: parse failed")
                continue

            r, jobs = await _ingest_freelancer_entries(db, feed.entries, outcome_mults, seen_ids)
            rows += r
            new_jobs.extend(jobs)

    db.commit()
    if rows == 0 and feed_errors and not seen_ids:
        raise Exception(f"Freelancer RSS failed: {'; '.join(feed_errors[:3])}")
    if feed_errors:
        print(f"Freelancer feed warnings: {'; '.join(feed_errors[:5])}")
    return rows, new_jobs


async def scrape_peopleperhour_rss(db):
    """Soft-optional PPH feed. Never raises; returns (rows, new_jobs)."""
    outcome_mults = load_outcome_kind_multipliers(db)
    rows = 0
    new_jobs = []
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(PPH_RSS_URL)
        if resp.status_code != 200:
            return 0, []
        feed = feedparser.parse(resp.content)
        if not feed.entries:
            return 0, []

        for entry in feed.entries[:40]:
            title = clean_html(entry.get("title", ""))
            description = clean_html(entry.get("summary") or entry.get("description", ""))
            link = entry.get("link", "")
            published = entry.get("published") or entry.get("updated") or ""
            if not title or not link or not is_squarespace_job(title, description):
                continue

            source_id = re.sub(r"[^\w-]", "", link.rstrip("/").split("/")[-1])[:80] or link[-50:]
            budget_info = parse_budget(f"{title} {description}")
            effort = estimate_effort(title, description)
            mid_usd = int(budget_info["budget_mid_usd"]) if budget_info else None
            keywords = matched_keywords(title, description)
            kind = detect_job_kind(title, description, keywords)
            priority = compute_priority(mid_usd, effort, outcome_mults.get(kind, 1.0))
            if not meets_min_score(priority):
                continue

            action = upsert_job(
                db,
                source="peopleperhour",
                source_id=source_id,
                title=title,
                description=description,
                url=link,
                posted_date=parse_feed_date(published),
                job_type="short-term" if is_short_term_job(title, description) or effort <= 3 else "unknown",
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
    except Exception as e:
        print(f"PeoplePerHour soft-skip: {e}")
        return 0, []
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
    outcome_mults = load_outcome_kind_multipliers(db)
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
        keywords = matched_keywords(title, description)
        kind = detect_job_kind(title, description, keywords)
        priority = compute_priority(mid_usd, effort, outcome_mults.get(kind, 1.0))
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
        "peopleperhour": 0,
        "upwork": 0,
        "total": 0,
        "errors": [],
        "skipped": [],
        "new_jobs": [],
    }
    errors: List[str] = []
    new_jobs: List[dict] = []
    skipped: List[str] = []

    try:
        count, jobs = await scrape_freelancer_rss(db)
        results["freelancer"] = count
        new_jobs.extend(jobs)
    except Exception as e:
        msg = f"freelancer: {e}"
        errors.append(msg)
        print(f"Scraping error: {msg}")

    try:
        count, jobs = await scrape_peopleperhour_rss(db)
        results["peopleperhour"] = count
        new_jobs.extend(jobs)
    except Exception as e:
        print(f"PeoplePerHour soft-skip: {e}")

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
        skipped.append("upwork (missing UPWORK_CLIENT_ID/SECRET/REFRESH_TOKEN)")

    results["total"] = (
        int(results["freelancer"] or 0)
        + int(results["peopleperhour"] or 0)
        + int(results["upwork"] or 0)
    )
    results["errors"] = errors
    results["skipped"] = skipped
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
