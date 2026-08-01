"""Forum question scraper.

Monitors multiple sources for Squarespace CSS/JS questions and generates
AI-powered answer suggestions using Groq API (free tier).

Callers: backend/main.py refresh_forum_background → scrape()
APIs: Stack Exchange API, Squarespace forum RSS feeds, Groq API
Schema: forum_questions (source, source_id, title, ai_answer, status, ...)
"""
import re
import httpx
import feedparser
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import html
import os

from db import log_scrape_start, log_scrape_end, is_scraper_running
from notify import send_whatsapp

# Browser-like UA — forum.squarespace.com Cloudflare often blocks custom bots.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# CSS/JS/Design keywords for filtering
FORUM_KEYWORDS = [
    "css", "javascript", "js", "custom css", "code injection", "code block",
    "design", "customization", "template", "style", "layout", "font",
    "responsive", "mobile", "header", "footer", "navigation", "menu",
    "squarespace", "website", "page", "section", "block", "spacing",
    "gallery", "slideshow", "animation", "hover", "fluid engine",
]

# Forum 39 (Customize with code) RSS has been stuck ~2024 — keep it last as a long shot.
# Active categories below are what actually post fresh CSS/design questions.
DEFAULT_SQUARESPACE_FEEDS = [
    ("squarespace_pages", "https://forum.squarespace.com/forum/42-pages-content.xml"),
    ("squarespace_design", "https://forum.squarespace.com/forum/45-site-design-styles.xml"),
    ("squarespace_media", "https://forum.squarespace.com/forum/41-images-videos.xml"),
    ("squarespace_commerce", "https://forum.squarespace.com/forum/40-commerce.xml"),
    ("squarespace_seo", "https://forum.squarespace.com/forum/43-seo.xml"),
    ("squarespace_code", "https://forum.squarespace.com/forum/39-customize-with-code.xml"),
]

REDDIT_FEEDS = [
    ("reddit_squarespace", "https://www.reddit.com/r/squarespace/new/.rss"),
]


def configured_squarespace_feeds() -> List[Tuple[str, str]]:
    """FORUM_RSS_URLS=source|url,source|url  or legacy FORUM_RSS_URL=url."""
    multi = os.getenv("FORUM_RSS_URLS", "").strip()
    if multi:
        feeds = []
        for part in multi.split(","):
            part = part.strip()
            if not part:
                continue
            if "|" in part:
                source, url = part.split("|", 1)
                feeds.append((source.strip(), url.strip()))
            else:
                feeds.append(("squarespace_forum", part))
        if feeds:
            return feeds
    legacy = os.getenv("FORUM_RSS_URL", "").strip()
    if legacy:
        return [("squarespace_forum", legacy)]
    return list(DEFAULT_SQUARESPACE_FEEDS)


def is_forum_question(title: str, description: str = "", *, require_keyword: bool = True) -> bool:
    """Check if post matches CSS/JS/design criteria."""
    if not require_keyword:
        return True
    text = f"{title} {description}".lower()
    return any(keyword in text for keyword in FORUM_KEYWORDS)

def clean_html(text: str) -> str:
    """Strip HTML tags and decode entities."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_last_scrape_time(conn) -> Optional[datetime]:
    """Get the last successful forum scrape time."""
    try:
        row = conn.execute(
            """SELECT started_at FROM scrape_log
               WHERE scraper = 'forum_questions' AND status = 'success'
               ORDER BY started_at DESC LIMIT 1"""
        ).fetchone()

        if row and row["started_at"]:
            # Parse ISO datetime
            try:
                return datetime.fromisoformat(row["started_at"].replace('Z', '+00:00'))
            except ValueError:
                return None
        return None
    except Exception as e:
        print(f"Error getting last scrape time: {e}")
        return None

def get_time_filter(conn) -> datetime:
    """Get the cutoff time for filtering questions based on last successful scrape."""
    last_scrape = get_last_scrape_time(conn)

    if last_scrape:
        # Use last scrape time, but add some overlap to catch any missed questions
        return last_scrape - timedelta(hours=2)  # 2 hour overlap
    else:
        # No previous scrape, use default time window (timezone-aware)
        from datetime import timezone
        return datetime.now(timezone.utc) - timedelta(days=7)  # Default to 7 days

SYSTEM_PROMPT = """You write short Squarespace forum replies that sound like a helpful expert peer — not a chatbot.

Rules:
- Speak in first person ("I'd try…", "You can…") as a forum reply Alex could post.
- Prefer concrete steps: which panel, which selector, which setting, or a minimal code snippet.
- If the question lacks a URL, template, or screenshot needed to answer well, say what to check first.
- Do not invent Squarespace features that do not exist.
- No greetings, sign-offs, markdown headings, or "As an AI".
- 2–4 short sentences max. One short code block only when CSS/JS is clearly required."""


def generate_ai_answer(question: Dict) -> Optional[str]:
    """Generate AI answer suggestion using Groq API (free tier). Called on demand only."""
    print(f"🤖 Attempting AI answer generation for: {question.get('title', '')[:50]}...")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("✗ GROQ_API_KEY not set in environment")
        print("  Get your free API key at: https://console.groq.com/")
        return None

    title = (question.get("title") or "").strip()
    description = (question.get("description") or "").strip()
    source = question.get("source") or "forum"
    url = question.get("url") or ""

    prompt = f"""Write a draft forum reply for this Squarespace {source.replace('_', ' ')} question.

Title: {title}

Question details:
{description[:1200] if description else '(no body provided — answer from the title only)'}

Source link (for context, do not paste unless useful): {url or 'n/a'}

Focus on the most likely fix. If CSS/JS is needed, give the smallest working snippet and where to paste it (Custom CSS, Code Injection, or Code Block)."""

    # Initialize Groq client (lazy load - only for first call)
    if not hasattr(generate_ai_answer, '_client'):
        try:
            from groq import Groq
            print("🔄 Initializing Groq client...")
            generate_ai_answer._client = Groq(api_key=api_key)
            print("✓ Groq client initialized successfully")
        except ImportError as ie:
            print(f"✗ groq package not installed: {ie}")
            print("  Install with: pip install groq")
            return None
        except Exception as client_error:
            print(f"✗ Failed to initialize Groq client: {client_error}")
            return None

    client = generate_ai_answer._client

    # Generate response with proper error handling
    try:
        print("🧠 Generating AI response via Groq...")
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=280,
            temperature=0.45,
            stop=["\n\n\n", "###", "User:", "Question:"]
        )

        if response and response.choices and len(response.choices) > 0:
            answer = response.choices[0].message.content.strip()
            if answer and len(answer) > 10:  # Ensure meaningful answer
                print(f"✓ AI answer generated: {answer[:50]}...")
                return answer
            else:
                print("✗ Generated answer too short or empty")
                return None
        else:
            print("✗ Unexpected response format from Groq API")
            print(f"  Response type: {type(response)}")
            return None

    except Exception as api_error:
        print(f"✗ Groq API request failed: {api_error}")
        print(f"  Error type: {type(api_error).__name__}")
        # Check for common API errors
        error_str = str(api_error).lower()
        if "authentication" in error_str or "unauthorized" in error_str:
            print("  Check your GROQ_API_KEY is valid")
        elif "rate" in error_str or "limit" in error_str:
            print("  Rate limit reached - try again later")
        elif "credits" in error_str or "balance" in error_str:
            print("  Account credits exhausted - check your Groq account")
        return None

async def upsert_question(db, question_data: Dict) -> str:
    """Insert or update forum question."""
    source = question_data.get("source", "unknown")
    source_id = question_data.get("source_id", "")

    now = datetime.now(timezone.utc).isoformat()

    # Check if exists and get AI answer status
    existing = db.execute(
        "SELECT id, comments_count, status, ai_answer FROM forum_questions WHERE source = ? AND source_id = ?",
        (source, source_id)
    ).fetchone()

    if existing:
        # Check if existing post needs AI answer generation
        needs_ai_answer = existing["ai_answer"] is None and question_data.get("ai_answer") is not None

        # Update if comments count changed, status changed, or needs AI answer
        if needs_ai_answer or existing["comments_count"] != question_data.get("comments_count", 0) or existing["status"] != question_data.get("status", "new"):
            db.execute("""
                UPDATE forum_questions
                SET title = ?, description = ?, url = ?, comments_count = ?,
                    ai_answer = COALESCE(?, ai_answer),
                    answer_generated_at = COALESCE(?, answer_generated_at),
                    updated_at = ?
                WHERE source = ? AND source_id = ?
            """, (
                question_data.get("title", ""),
                question_data.get("description", ""),
                question_data.get("url", ""),
                question_data.get("comments_count", 0),
                question_data.get("ai_answer"),
                question_data.get("answer_generated_at"),
                now,
                source, source_id
            ))
            return "updated" if needs_ai_answer else "updated_no_ai"
        return "skipped"
    else:
        # Insert new
        db.execute("""
            INSERT INTO forum_questions (
                source, source_id, title, description, url, comments_count,
                ai_answer, answer_generated_at, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            source, source_id,
            question_data.get("title", ""),
            question_data.get("description", ""),
            question_data.get("url", ""),
            question_data.get("comments_count", 0),
            question_data.get("ai_answer"),
            question_data.get("answer_generated_at"),
            question_data.get("status", "new"),
            question_data.get("created_at", now),
            now
        ))
        return "inserted"

def parse_entry_datetime(entry) -> Optional[datetime]:
    """Parse published/updated from feedparser entry into aware UTC datetime."""
    published = entry.get("published") or entry.get("updated")
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc)
        except Exception:
            pass
    if not published:
        return None
    if isinstance(published, datetime):
        published_dt = published
    else:
        try:
            published_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        except ValueError:
            try:
                published_dt = datetime.strptime(str(published), "%a, %d %b %Y %H:%M:%S %z")
            except ValueError:
                return None
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)
    else:
        published_dt = published_dt.astimezone(timezone.utc)
    return published_dt


async def ingest_rss_feed(
    db,
    client: httpx.AsyncClient,
    *,
    source: str,
    rss_url: str,
    cutoff_time: datetime,
    require_keyword: bool = True,
) -> Tuple[int, int, List[Dict]]:
    """Fetch one RSS/Atom feed and upsert matching questions."""
    rows = 0
    new_questions = 0
    new_for_alert: List[Dict] = []

    if cutoff_time.tzinfo is None:
        cutoff_time = cutoff_time.replace(tzinfo=timezone.utc)

    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    # Always scan at least the last 24h of the feed (retention window), even if
    # the last scrape was more recent — avoids missing items when a feed recovers.
    effective_cutoff = min(cutoff_time, twenty_four_hours_ago)

    try:
        print(f"📡 Fetching {source}: {rss_url}")
        resp = await client.get(rss_url, timeout=30)
        if resp.status_code != 200:
            print(f"✗ Failed {source}: HTTP {resp.status_code}")
            return 0, 0, []

        feed = feedparser.parse(resp.content)
        if not feed.entries:
            print(f"✗ No entries in {source}")
            return 0, 0, []

        print(f"✓ {source}: {len(feed.entries)} entries")

        for entry in feed.entries:
            title = clean_html(entry.get("title", ""))
            description = clean_html(entry.get("summary") or entry.get("description", ""))
            link = entry.get("link", "")
            published_dt = parse_entry_datetime(entry)
            if not published_dt:
                continue

            if published_dt < twenty_four_hours_ago:
                continue
            if published_dt < effective_cutoff:
                continue
            if not title or not link:
                continue
            if not is_forum_question(title, description, require_keyword=require_keyword):
                continue

            source_id = re.sub(r"[^\w-]", "", link.rstrip("/").split("/")[-1])[:80] or link[-50:]
            existing = db.execute(
                "SELECT id FROM forum_questions WHERE source = ? AND source_id = ?",
                (source, source_id),
            ).fetchone()
            if existing:
                rows += 1
                continue

            print(f"🆕 [{source}] {title[:40]}...")
            question_data = {
                "source": source,
                "source_id": source_id,
                "title": title,
                "description": description[:1000],
                "url": link,
                "comments_count": 0,
                "created_at": published_dt.isoformat(),
            }
            status = await upsert_question(db, question_data)
            if status == "inserted":
                new_questions += 1
                new_for_alert.append({
                    "title": title,
                    "url": link,
                    "description": description[:200],
                    "ai_answer": None,
                    "source": source,
                })
            rows += 1

    except Exception as e:
        print(f"✗ Error scraping {source}: {e}")

    return rows, new_questions, new_for_alert


async def scrape_squarespace_rss(db, client: httpx.AsyncClient, cutoff_time: datetime) -> Tuple[int, int, List[Dict]]:
    """Scrape active Squarespace forum category RSS feeds."""
    rows = 0
    new_questions = 0
    new_for_alert: List[Dict] = []

    # Design/pages forums are already on-topic — still keyword-filter commerce/seo/media
    # but keep keywords broad enough that layout/CSS asks pass.
    for source, url in configured_squarespace_feeds():
        r, n, alerts = await ingest_rss_feed(
            db, client, source=source, rss_url=url, cutoff_time=cutoff_time, require_keyword=True
        )
        rows += r
        new_questions += n
        new_for_alert.extend(alerts)

    return rows, new_questions, new_for_alert


async def scrape_reddit(db, client: httpx.AsyncClient, cutoff_time: datetime) -> Tuple[int, int, List[Dict]]:
    """Scrape Reddit Squarespace new posts via public RSS."""
    rows = 0
    new_questions = 0
    new_for_alert: List[Dict] = []
    for source, url in REDDIT_FEEDS:
        r, n, alerts = await ingest_rss_feed(
            db, client, source=source, rss_url=url, cutoff_time=cutoff_time, require_keyword=True
        )
        rows += r
        new_questions += n
        new_for_alert.extend(alerts)
    return rows, new_questions, new_for_alert


async def scrape_stackoverflow(db, client: httpx.AsyncClient, cutoff_time: datetime) -> Tuple[int, int, List[Dict]]:
    """Scrape Stack Overflow for Squarespace CSS/JS questions. Returns (rows, new_questions, new_questions_for_alert)."""
    rows = 0
    new_questions = 0
    new_questions_for_alert = []

    # Only Squarespace-tagged questions (optionally AND css / javascript).
    # Bare css/javascript tags drown the feed in unrelated SO noise.
    search_tags = ['squarespace', 'squarespace;css', 'squarespace;javascript']

    try:
        for tag in search_tags:
            print(f"🔍 Searching Stack Overflow for: {tag}")

            api_url = f"https://api.stackexchange.com/2.3/questions"
            params = {
                'order': 'desc',
                'sort': 'creation',
                'tagged': tag,
                'site': 'stackoverflow',
                'filter': 'withbody',
                'pagesize': 50,
                'fromdate': int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp()),
            }

            try:
                resp = await client.get(api_url, params=params, timeout=30)
                if resp.status_code != 200:
                    print(f"Failed to fetch Stack Overflow: HTTP {resp.status_code}")
                    continue

                data = resp.json()
                questions = data.get('items', [])

                print(f"Found {len(questions)} questions for tag: {tag}")

                for question in questions:
                    title = question.get('title', '')
                    body = question.get('body', '')
                    question_id = question.get('question_id')
                    creation_date = question.get('creation_date')
                    answer_count = question.get('answer_count', 0)
                    is_answered = question.get('is_answered', False)

                    # Skip if already has answers (we want unanswered questions)
                    if answer_count > 0 or is_answered:
                        continue

                    # Clean HTML from body
                    description = clean_html(body)

                    # Check if this is CSS/JS/design related
                    if not is_forum_question(title, description):
                        continue

                    # 24-hour retention policy: skip if older than 24 hours
                    if creation_date:
                        created_dt = datetime.fromtimestamp(creation_date, tz=timezone.utc)
                        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
                        if created_dt < twenty_four_hours_ago:
                            print(f"⏭️ Skipping Stack Overflow question older than 24h: {title[:30]}...")
                            continue

                    source_id = str(question_id)

                    existing = db.execute(
                        "SELECT id FROM forum_questions WHERE source = ? AND source_id = ?",
                        ("stackoverflow", source_id)
                    ).fetchone()

                    if existing:
                        rows += 1
                        continue

                    # Build question data (AI answers are generated on demand from the UI)
                    question_data = {
                        "source": "stackoverflow",
                        "source_id": source_id,
                        "title": title,
                        "description": description[:1000],  # Limit description length
                        "url": f"https://stackoverflow.com/questions/{question_id}",
                        "comments_count": answer_count,
                        "created_at": datetime.fromtimestamp(creation_date, tz=timezone.utc).isoformat() if creation_date else datetime.now(timezone.utc).isoformat()
                    }

                    status = await upsert_question(db, question_data)
                    if status == "inserted":
                        new_questions += 1
                        new_questions_for_alert.append({
                            "title": title,
                            "url": f"https://stackoverflow.com/questions/{question_id}",
                            "description": description[:200],
                            "ai_answer": question_data.get("ai_answer"),
                            "source": "stackoverflow"
                        })
                    rows += 1

            except Exception as e:
                print(f"Error scraping Stack Overflow for tag {tag}: {e}")
                continue

    except Exception as e:
        print(f"Error in Stack Overflow scraping: {e}")

    return rows, new_questions, new_questions_for_alert

def format_forum_alert(question: Dict) -> str:
    """Format a forum question for WhatsApp alert."""
    title = question.get("title") or "New forum question"
    source = question.get("source", "unknown")
    url = question.get("url") or ""
    ai_answer = question.get("ai_answer")

    lines = [f"📱 {source.title()}: {title}"]
    if ai_answer:
        lines.append(f"💡 AI: {ai_answer[:100]}...")
    if url:
        lines.append(f"🔗 {url}")

    return "\n".join(lines)

def format_forum_digest(questions: List[Dict]) -> str:
    """Format multiple forum questions for WhatsApp digest."""
    if not questions:
        return ""

    lines = [f"📱 {len(questions)} new Squarespace forum question(s):"]
    for i, question in enumerate(questions, 1):
        title = (question.get("title") or "Untitled")[:80]
        source = question.get("source", "unknown")
        url = question.get("url") or ""
        lines.append(f"{i}. [{source}] {title}")
        if url:
            lines.append(f"   {url}")

    return "\n".join(lines)

async def notify_new_forum_questions(questions: List[Dict]) -> Optional[str]:
    """Send WhatsApp alerts for new forum questions."""
    if not questions:
        return None

    # Check if forum alerts are enabled
    if not os.getenv("FORUM_ALERTS_ENABLED", "1") == "1":
        return "Forum alerts disabled"

    try:
        # Check if digest mode is enabled
        if os.getenv("FORUM_ALERT_DIGEST", "1") == "1":
            # Send digest
            text = format_forum_digest(questions)
        else:
            # Send individual alerts
            texts = [format_forum_alert(q) for q in questions]
            text = "\n\n---\n\n".join(texts)

        error = await send_whatsapp(text)
        return error
    except Exception as e:
        return str(e)

async def backfill_ai_answers(db) -> int:
    """Generate AI answers for existing questions that don't have them."""
    questions_without_ai = db.execute(
        "SELECT id, source, source_id, title, description, url FROM forum_questions WHERE ai_answer IS NULL LIMIT 20"
    ).fetchall()

    if not questions_without_ai:
        print("✓ No existing questions need AI answers")
        return 0

    print(f"🔄 Backfilling AI answers for {len(questions_without_ai)} existing questions...")

    backfilled_count = 0
    for question in questions_without_ai:
        question_data = {
            "source": question["source"],
            "source_id": question["source_id"],
            "title": question["title"],
            "description": question["description"],
            "url": question["url"]
        }

        print(f"🤖 Generating AI answer for: {question['title'][:30]}...")
        ai_answer = generate_ai_answer(question_data)
        if ai_answer:
            db.execute(
                "UPDATE forum_questions SET ai_answer = ?, answer_generated_at = ? WHERE id = ?",
                (ai_answer, datetime.now(timezone.utc).isoformat(), question["id"])
            )
            backfilled_count += 1
            print(f"✓ AI answer generated for: {question['title'][:30]}")
        else:
            print(f"✗ No AI answer generated for: {question['title'][:30]}")

    db.commit()
    return backfilled_count

async def scrape(db) -> Dict[str, object]:
    """Main entry point - scrape all configured forum sources."""
    if is_scraper_running(db, "forum_questions"):
        return {"status": "already_running", "results": {}, "total": 0, "new": 0}

    log_id = log_scrape_start(db, "forum_questions")

    # Get time filter based on last successful scrape
    cutoff_time = get_time_filter(db)
    print(f"🕐 Using time filter: since {cutoff_time.isoformat()}")

    results = {
        "squarespace_forum": 0,
        "reddit": 0,
        "stackoverflow": 0,
        "total_questions": 0,
        "new_questions": 0,
        "status": "running",
        "errors": [],
        "feeds": [url for _, url in configured_squarespace_feeds()],
    }

    all_new_questions = []  # Collect all new questions for alerts

    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
        ) as client:
            try:
                count, new_q, new_for_alert = await scrape_squarespace_rss(db, client, cutoff_time)
                results["squarespace_forum"] = count
                results["total_questions"] += count
                results["new_questions"] += new_q
                all_new_questions.extend(new_for_alert)
            except Exception as scrape_error:
                error_msg = f"Squarespace forum scraping failed: {str(scrape_error)}"
                results["errors"].append(error_msg)
                print(error_msg)

            try:
                count, new_q, new_for_alert = await scrape_reddit(db, client, cutoff_time)
                results["reddit"] = count
                results["total_questions"] += count
                results["new_questions"] += new_q
                all_new_questions.extend(new_for_alert)
            except Exception as scrape_error:
                error_msg = f"Reddit scraping failed: {str(scrape_error)}"
                results["errors"].append(error_msg)
                print(error_msg)

            try:
                count, new_q, new_for_alert = await scrape_stackoverflow(db, client, cutoff_time)
                results["stackoverflow"] = count
                results["total_questions"] += count
                results["new_questions"] += new_q
                all_new_questions.extend(new_for_alert)
            except Exception as scrape_error:
                error_msg = f"Stack Overflow scraping failed: {str(scrape_error)}"
                results["errors"].append(error_msg)
                print(error_msg)

        db.commit()

        # AI answers are generated on demand from the UI — no scrape-time backfill

        # Send WhatsApp alerts for new forum questions
        if all_new_questions:
            try:
                alert_error = await notify_new_forum_questions(all_new_questions)
                if alert_error:
                    results["errors"].append(f"Alert failed: {alert_error}")
                    print(f"WhatsApp alert error: {alert_error}")
                else:
                    print(f"✓ Sent WhatsApp alerts for {len(all_new_questions)} new forum questions")
            except Exception as alert_error:
                error_msg = f"Forum alert error: {str(alert_error)}"
                results["errors"].append(error_msg)
                print(error_msg)

        # Clean up old forum questions
        try:
            purge_forum_questions(db)
        except Exception as cleanup_error:
            print(f"Cleanup error: {cleanup_error}")

        # Log final results
        print(f"📊 Final results: {results}")

        # Determine overall status
        if results["total_questions"] > 0:
            results["status"] = "success"
            status_to_log = "success"
        elif results["errors"]:
            results["status"] = "failed"
            status_to_log = "failed"
        else:
            results["status"] = "success"  # No questions found but no errors
            status_to_log = "success"

        error_summary = "; ".join(results["errors"]) if results["errors"] else None
        log_scrape_end(db, log_id, status_to_log, results["total_questions"], error_summary)

    except Exception as e:
        error_msg = str(e)
        results["errors"].append(f"Fatal error: {error_msg}")
        results["status"] = "failed"
        log_scrape_end(db, log_id, "failed", 0, error_msg)

    return results

def purge_forum_questions(conn) -> None:
    """Clean up forum questions older than 24 hours."""
    # Delete all questions older than 24 hours regardless of status
    twenty_four_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    deleted_count = conn.execute(
        "DELETE FROM forum_questions WHERE created_at < ?",
        (twenty_four_hours_ago,)
    ).rowcount

    conn.commit()
    print(f"Forum cleanup completed: deleted {deleted_count} questions older than 24 hours")