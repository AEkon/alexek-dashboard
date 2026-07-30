"""Forum question scraper.

Monitors Squarespace forums for unanswered CSS/JS questions and generates
AI-powered answer suggestions using Qwen3 8B running locally in Docker.

Callers: backend/main.py refresh_forum_background → scrape()
APIs: Forum RSS feeds, Qwen3 8B local model via llama-cpp-python
Schema: forum_questions (source, source_id, title, ai_answer, status, ...)
"""
import feedparser
import httpx
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus
import html

from db import log_scrape_start, log_scrape_end, is_scraper_running

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

def generate_ai_answer(question: Dict) -> Optional[str]:
    """Generate AI answer suggestion using local Qwen3 8B model."""
    try:
        from llama_cpp import Llama

        model_path = os.getenv("QWEN_MODEL_PATH", "/app/models/qwen3-8b.gguf")
        if not os.path.exists(model_path):
            print(f"Model not found at {model_path}")
            return None

        title = question.get("title", "")
        description = question.get("description", "")
        url = question.get("url", "")

        prompt = f"""Act as Squarespace developer. Provide a 1-line solution with simplified CSS/JS code if needed. Include the URL: {url}"""

        # Initialize model (lazy load - only for first call)
        if not hasattr(generate_ai_answer, '_model'):
            generate_ai_answer._model = Llama(
                model_path=model_path,
                n_ctx=512,
                n_threads=2,
                verbose=False
            )

        model = generate_ai_answer._model

        # Generate response
        response = model(
            prompt,
            max_tokens=300,
            temperature=0.7,
            stop=["\n\n\n", "###", "User:"],
            echo=False
        )

        if response and 'choices' in response and len(response['choices']) > 0:
            return response['choices'][0]['text'].strip()

    except Exception as e:
        print(f"Local AI generation failed: {e}")

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

async def scrape_forum_rss(db, rss_url: str, source_name: str, client: httpx.AsyncClient) -> Tuple[int, int]:
    """Scrape a single forum RSS feed. Returns (rows, new_questions)."""
    rows = 0
    new_questions = 0

    try:
        resp = await client.get(rss_url)
        if resp.status_code != 200:
            return 0, 0

        feed = feedparser.parse(resp.content)
        if not feed.entries:
            return 0, 0

        for entry in feed.entries[:50]:
            title = clean_html(entry.get("title", ""))
            description = clean_html(entry.get("summary") or entry.get("description", ""))
            link = entry.get("link", "")
            comments = 0

            # Try to get comment count from various RSS fields
            if hasattr(entry, 'slash_comments'):
                comments = int(entry.slash_comments) if entry.slash_comments else 0

            published = entry.get("published") or entry.get("updated") or datetime.utcnow().isoformat()

            if not title or not link:
                continue

            # Filter for CSS/JS/design questions only
            if not is_forum_question(title, description):
                continue

            # Only unanswered questions (comments = 0)
            if comments != 0:
                continue

            # Generate source_id from URL
            source_id = re.sub(r"[^\w-]", "", link.rstrip("/").split("/")[-1])[:80] or link[-50:]

            # Check if already exists
            existing = db.execute(
                "SELECT id FROM forum_questions WHERE source = ? AND source_id = ?",
                (source_name, source_id)
            ).fetchone()

            if existing:
                rows += 1
                continue

            # Build question data
            question_data = {
                "source": source_name,
                "source_id": source_id,
                "title": title,
                "description": description,
                "url": link,
                "comments_count": comments,
                "created_at": published
            }

            # Generate AI answer (synchronous local inference)
            ai_answer = generate_ai_answer(question_data)
            if ai_answer:
                question_data["ai_answer"] = ai_answer
                question_data["answer_generated_at"] = datetime.utcnow().isoformat()

            status = await upsert_question(db, question_data)
            if status == "inserted":
                new_questions += 1
            rows += 1

    except Exception as e:
        print(f"Error scraping {source_name}: {e}")

    return rows, new_questions

async def scrape(db) -> Dict[str, object]:
    """Main entry point - scrape all configured forum sources."""
    if is_scraper_running(db, "forum_questions"):
        return {"status": "already_running", "results": {}}

    log_id = log_scrape_start(db, "forum_questions")

    results = {
        "squarespace_forum": 0,
        "total_questions": 0,
        "new_questions": 0
    }

    try:
        forum_rss_url = os.getenv("FORUM_RSS_URL", "")
        if not forum_rss_url:
            results["error"] = "FORUM_RSS_URL not configured"
            log_scrape_end(db, log_id, "failed", 0, "Missing FORUM_RSS_URL")
            return results

        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            count, new_q = await scrape_forum_rss(db, forum_rss_url, "squarespace_forum", client)
            results["squarespace_forum"] = count
            results["total_questions"] += count
            results["new_questions"] += new_q

        db.commit()
        log_scrape_end(db, log_id, "success", results["total_questions"])
        results["status"] = "success"

    except Exception as e:
        log_scrape_end(db, log_id, "failed", 0, str(e))
        results["status"] = "failed"
        results["error"] = str(e)

    return results
