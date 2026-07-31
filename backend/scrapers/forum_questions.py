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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import html
import os

from db import log_scrape_start, log_scrape_end, is_scraper_running
from notify import send_whatsapp

USER_AGENT = "alexek-dashboard/1.0 (+https://hq.alexek.com)"

# CSS/JS/Design keywords for filtering
FORUM_KEYWORDS = [
    "css", "javascript", "js", "custom css", "code injection",
    "design", "customization", "template", "style", "layout",
    "responsive", "mobile", "header", "footer", "navigation",
    "squarespace", "website", "page", "section", "block"
]

def is_forum_question(title: str, description: str = "") -> bool:
    """Check if post matches CSS/JS/design criteria."""
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
        # No previous scrape, use default time window
        return datetime.utcnow() - timedelta(days=7)  # Default to 7 days

def generate_ai_answer(question: Dict) -> Optional[str]:
    """Generate AI answer suggestion using Groq API (free tier)."""
    print(f"🤖 Attempting AI answer generation for: {question.get('title', '')[:50]}...")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("✗ GROQ_API_KEY not set in environment")
        print("  Get your free API key at: https://console.groq.com/")
        return None

    title = question.get("title", "")
    description = question.get("description", "")

    # Create a simple prompt based on the question content
    question_text = f"{title}. {description[:200]}".strip() if description else title
    prompt = f"""As a Squarespace expert, provide a brief, helpful answer to this forum question: "{question_text}"

If the question is about CSS/JS code, provide a simple solution. If it's about design/configuration, give clear guidance.
Keep your answer under 2 sentences and be practical."""

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
            model="llama-3.1-8b-instant",  # Fast, free tier model
            messages=[
                {"role": "system", "content": "You are a Squarespace expert who provides practical, concise answers to CSS/JS questions."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.6,
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

    now = datetime.utcnow().isoformat()

    # Check if exists
    existing = db.execute(
        "SELECT id, comments_count, status FROM forum_questions WHERE source = ? AND source_id = ?",
        (source, source_id)
    ).fetchone()

    if existing:
        # Update if comments count changed or status changed
        db.execute("""
            UPDATE forum_questions
            SET title = ?, description = ?, url = ?, comments_count = ?,
                ai_answer = ?, answer_generated_at = ?, updated_at = ?
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
        return "updated"
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

async def scrape_squarespace_rss(db, client: httpx.AsyncClient, cutoff_time: datetime) -> Tuple[int, int, List[Dict]]:
    """Scrape Squarespace forum RSS feed. Returns (rows, new_questions, new_questions_for_alert)."""
    rows = 0
    new_questions = 0
    new_questions_for_alert = []

    # Squarespace forum RSS feed for code customization
    rss_url = "https://forum.squarespace.com/forum/39-customize-with-code.xml"

    try:
        print(f"📡 Fetching Squarespace forum RSS: {rss_url}")
        print(f"🕐 Filtering questions since: {cutoff_time.isoformat()}")

        resp = await client.get(rss_url, timeout=30)
        if resp.status_code != 200:
            print(f"✗ Failed to fetch Squarespace RSS: HTTP {resp.status_code}")
            return 0, 0, []

        feed = feedparser.parse(resp.content)
        if not feed.entries:
            print("✗ No entries found in Squarespace RSS feed")
            return 0, 0, []

        print(f"✓ Found {len(feed.entries)} entries in Squarespace RSS feed")

        for entry in feed.entries:
            title = clean_html(entry.get("title", ""))
            description = clean_html(entry.get("summary") or entry.get("description", ""))
            link = entry.get("link", "")
            published = entry.get("published") or entry.get("updated") or datetime.utcnow().isoformat()

            # Parse the published date
            try:
                if isinstance(published, str):
                    # Try parsing ISO format
                    try:
                        published_dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    except ValueError:
                        # Try parsing feedparser format
                        published_dt = datetime.strptime(published, '%a, %d %b %Y %H:%M:%S %z')
                else:
                    published_dt = published
            except Exception as e:
                print(f"Error parsing date {published}: {e}")
                continue

            # Check if this is newer than our cutoff time
            if published_dt < cutoff_time:
                continue

            if not title or not link:
                continue

            # Filter for CSS/JS/design questions only
            if not is_forum_question(title, description):
                continue

            # Generate source_id from URL
            source_id = re.sub(r"[^\w-]", "", link.rstrip("/").split("/")[-1])[:80] or link[-50:]

            # Check if already exists
            existing = db.execute(
                "SELECT id FROM forum_questions WHERE source = ? AND source_id = ?",
                ("squarespace_forum", source_id)
            ).fetchone()

            if existing:
                rows += 1
                continue

            # Build question data
            question_data = {
                "source": "squarespace_forum",
                "source_id": source_id,
                "title": title,
                "description": description[:1000],  # Limit description length
                "url": link,
                "comments_count": 0,  # Don't track comment counts for RSS
                "created_at": published_dt.isoformat() if published_dt else datetime.utcnow().isoformat()
            }

            # Generate AI answer
            print(f"Generating AI answer for: {title[:50]}...")
            ai_answer = generate_ai_answer(question_data)
            if ai_answer:
                question_data["ai_answer"] = ai_answer
                question_data["answer_generated_at"] = datetime.utcnow().isoformat()
                print(f"✓ AI answer generated for: {title[:30]}")
            else:
                print(f"✗ No AI answer generated for: {title[:30]}")

            status = await upsert_question(db, question_data)
            if status == "inserted":
                new_questions += 1
                new_questions_for_alert.append({
                    "title": title,
                    "url": link,
                    "description": description[:200],
                    "ai_answer": ai_answer,
                    "source": "squarespace_forum"
                })
            rows += 1

    except Exception as e:
        print(f"✗ Error scraping Squarespace RSS: {e}")

    return rows, new_questions, new_questions_for_alert

async def scrape_stackoverflow(db, client: httpx.AsyncClient, cutoff_time: datetime) -> Tuple[int, int, List[Dict]]:
    """Scrape Stack Overflow for Squarespace CSS/JS questions. Returns (rows, new_questions, new_questions_for_alert)."""
    rows = 0
    new_questions = 0
    new_questions_for_alert = []

    # Search terms for Squarespace CSS/JS questions
    search_tags = ['squarespace', 'css', 'javascript']

    try:
        for tag in search_tags:
            print(f"🔍 Searching Stack Overflow for: {tag}")

            # Stack Exchange API - search for recent questions with these tags
            api_url = f"https://api.stackexchange.com/2.3/questions"
            params = {
                'order': 'desc',
                'sort': 'creation',
                'tagged': tag,
                'site': 'stackoverflow',
                'filter': 'withbody',  # Include question body
                'pagesize': 50,
                'fromdate': int(cutoff_time.timestamp())  # Since cutoff time
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

                    source_id = str(question_id)

                    # Check if already exists
                    existing = db.execute(
                        "SELECT id FROM forum_questions WHERE source = ? AND source_id = ?",
                        ("stackoverflow", source_id)
                    ).fetchone()

                    if existing:
                        rows += 1
                        continue

                    # Build question data
                    question_data = {
                        "source": "stackoverflow",
                        "source_id": source_id,
                        "title": title,
                        "description": description[:1000],  # Limit description length
                        "url": f"https://stackoverflow.com/questions/{question_id}",
                        "comments_count": answer_count,
                        "created_at": datetime.fromtimestamp(creation_date).isoformat() if creation_date else datetime.utcnow().isoformat()
                    }

                    # Generate AI answer
                    print(f"Generating AI answer for: {title[:50]}...")
                    ai_answer = generate_ai_answer(question_data)
                    if ai_answer:
                        question_data["ai_answer"] = ai_answer
                        question_data["answer_generated_at"] = datetime.utcnow().isoformat()
                        print(f"✓ AI answer generated for: {title[:30]}")
                    else:
                        print(f"✗ No AI answer generated for: {title[:30]}")

                    status = await upsert_question(db, question_data)
                    if status == "inserted":
                        new_questions += 1
                        new_questions_for_alert.append({
                            "title": title,
                            "url": f"https://stackoverflow.com/questions/{question_id}",
                            "description": description[:200],
                            "ai_answer": ai_answer,
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
        "stackoverflow": 0,
        "total_questions": 0,
        "new_questions": 0,
        "status": "running",
        "errors": []
    }

    all_new_questions = []  # Collect all new questions for alerts

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            # Scrape Squarespace forum RSS
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

            # Scrape Stack Overflow
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
    """Clean up old forum questions based on retention rules."""
    # Get retention settings from environment variables
    new_days = int(os.getenv("FORUM_RETENTION_NEW_DAYS", "30"))      # Keep 'new' questions for 30 days
    answered_days = int(os.getenv("FORUM_RETENTION_ANSWERED_DAYS", "90"))  # Keep 'answered' for 90 days
    archived_days = int(os.getenv("FORUM_RETENTION_ARCHIVED_DAYS", "7"))   # Keep 'archived' for 7 days

    cutoff_new = (datetime.utcnow() - timedelta(days=new_days)).isoformat()
    cutoff_answered = (datetime.utcnow() - timedelta(days=answered_days)).isoformat()
    cutoff_archived = (datetime.utcnow() - timedelta(days=archived_days)).isoformat()

    # Delete old new questions
    conn.execute(
        "DELETE FROM forum_questions WHERE status = 'new' AND created_at < ?",
        (cutoff_new,),
    )

    # Delete old answered questions
    conn.execute(
        "DELETE FROM forum_questions WHERE status = 'answered' AND COALESCE(answered_at, created_at) < ?",
        (cutoff_answered,),
    )

    # Delete old archived questions
    conn.execute(
        "DELETE FROM forum_questions WHERE status = 'archived' AND COALESCE(updated_at, created_at) < ?",
        (cutoff_archived,),
    )

    conn.commit()
    print(f"Forum cleanup completed: new<{new_days}d, answered<{answered_days}d, archived<{archived_days}d")