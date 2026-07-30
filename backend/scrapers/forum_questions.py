"""Forum question scraper.

Monitors Squarespace forums for unanswered CSS/JS questions and generates
AI-powered answer suggestions using Qwen3 8B running locally in Docker.

Callers: backend/main.py refresh_forum_background → scrape()
APIs: Squarespace forum web scraping, Qwen3 8B local model via llama-cpp-python
Schema: forum_questions (source, source_id, title, ai_answer, status, ...)
"""
import re
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import html
import os

from db import log_scrape_start, log_scrape_end, is_scraper_running, purge_stale_data

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
    print(f"🤖 Attempting AI answer generation for: {question.get('title', '')[:50]}...")

    try:
        from llama_cpp import Llama
        print("✓ llama-cpp-python imported successfully")
    except ImportError as ie:
        print(f"✗ llama-cpp-python not installed: {ie}")
        print("  Install with: pip install llama-cpp-python")
        return None
    except Exception as e:
        print(f"✗ Import error: {e}")
        return None

    model_path = os.getenv("QWEN_MODEL_PATH", "/app/models/qwen3-8b.gguf")
    print(f"📂 Model path: {model_path}")

    if not os.path.exists(model_path):
        print(f"✗ Model file not found at: {model_path}")
        print("  Solutions:")
        print("  1. Download Qwen3 8B GGUF model to that path")
        print("  2. Set QWEN_MODEL_PATH environment variable to correct location")
        print("  3. Place model file at /app/models/qwen3-8b.gguf")
        return None

    title = question.get("title", "")
    description = question.get("description", "")

    # Create a simple prompt based on the question content
    question_text = f"{title}. {description[:200]}".strip() if description else title
    prompt = f"""As a Squarespace expert, provide a brief, helpful answer to this forum question: "{question_text}"

If the question is about CSS/JS code, provide a simple solution. If it's about design/configuration, give clear guidance.
Keep your answer under 2 sentences and be practical."""

    # Initialize model (lazy load - only for first call)
    if not hasattr(generate_ai_answer, '_model'):
        try:
            print("🔄 Loading AI model (first time)...")
            generate_ai_answer._model = Llama(
                model_path=model_path,
                n_ctx=512,
                n_threads=2,
                verbose=False
            )
            print("✓ Local AI model loaded successfully")
        except Exception as model_error:
            print(f"✗ Failed to load AI model: {model_error}")
            print("  This could be due to:")
            print("  - Incompatible model format")
            print("  - insufficient memory")
            print("  - CPU architecture mismatch")
            return None

    model = generate_ai_answer._model

    # Generate response with proper error handling
    try:
        print("🧠 Generating AI response...")
        response = model(
            prompt,
            max_tokens=150,
            temperature=0.6,
            stop=["\n\n\n", "###", "User:", "Question:"],
            echo=False
        )

        if response and hasattr(response, 'choices') and len(response['choices']) > 0:
            answer = response['choices'][0]['text'].strip()
            if answer and len(answer) > 10:  # Ensure meaningful answer
                print(f"✓ AI answer generated: {answer[:50]}...")
                return answer
            else:
                print("✗ Generated answer too short or empty")
                return None
        else:
            print("✗ Unexpected response format from model")
            print(f"  Response type: {type(response)}")
            print(f"  Response attributes: {dir(response) if response else 'None'}")
            return None

    except Exception as generation_error:
        print(f"✗ Model generation failed: {generation_error}")
        print(f"  Error type: {type(generation_error).__name__}")
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

async def scrape_squarespace_forum(db, client: httpx.AsyncClient) -> Tuple[int, int]:
    """Scrape Squarespace forum for unanswered CSS/JS questions. Returns (rows, new_questions)."""
    rows = 0
    new_questions = 0

    # Squarespace forum URLs - focusing on recent discussions across all categories
    forum_urls = [
        "https://forum.squarespace.com/categories/custom-css.14/",
        "https://forum.squarespace.com/categories/javascript.15/",
        "https://forum.squarespace.com/categories/design-styles.16/",
        "https://forum.squarespace.com/categories/developer-platform.17/"
    ]

    try:
        for forum_url in forum_urls:
            print(f"Scraping forum: {forum_url}")

            try:
                resp = await client.get(forum_url, timeout=30)
                if resp.status_code != 200:
                    print(f"Failed to fetch {forum_url}: HTTP {resp.status_code}")
                    continue

                soup = BeautifulSoup(resp.content, 'html.parser')

                # Find recent discussion threads - adjust selectors based on actual HTML structure
                # These selectors may need to be adjusted based on the actual forum structure
                discussion_links = soup.find_all('a', href=re.compile(r'/discussion/\d+/'))

                print(f"Found {len(discussion_links)} discussion threads")

                for link in discussion_links[:25]:  # Limit to 25 per category
                    href = link.get('href', '')
                    if not href:
                        continue

                    # Build full URL
                    full_url = urljoin(forum_url, href)

                    # Generate source_id from URL
                    source_id = re.sub(r"[^\w-]", "", href.rstrip("/").split("/")[-1])[:80]

                    # Check if already exists
                    existing = db.execute(
                        "SELECT id FROM forum_questions WHERE source = ? AND source_id = ?",
                        ("squarespace_forum", source_id)
                    ).fetchone()

                    if existing:
                        rows += 1
                        continue

                    # Get the discussion page to extract full details
                    try:
                        discussion_resp = await client.get(full_url, timeout=20)
                        if discussion_resp.status_code != 200:
                            continue

                        discussion_soup = BeautifulSoup(discussion_resp.content, 'html.parser')

                        # Extract title
                        title_elem = discussion_soup.find('h1') or discussion_soup.find('title')
                        title = clean_html(title_elem.get_text()) if title_elem else "Unknown Title"

                        # Extract description/content
                        content_elem = discussion_soup.find('div', class_='discussion-content') or \
                                     discussion_soup.find('div', class_='post-content')

                        description = ""
                        if content_elem:
                            description = clean_html(content_elem.get_text())

                        # Check if this is CSS/JS/design related
                        if not is_forum_question(title, description):
                            continue

                        # Build question data
                        question_data = {
                            "source": "squarespace_forum",
                            "source_id": source_id,
                            "title": title,
                            "description": description[:1000],  # Limit description length
                            "url": full_url,
                            "comments_count": 0,  # Will be determined by user triage
                            "created_at": datetime.utcnow().isoformat()
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
                        rows += 1

                    except Exception as e:
                        print(f"Error fetching discussion {full_url}: {e}")
                        continue

            except Exception as e:
                print(f"Error scraping forum {forum_url}: {e}")
                continue

    except Exception as e:
        print(f"Error in forum scraping: {e}")

    return rows, new_questions

async def scrape(db) -> Dict[str, object]:
    """Main entry point - scrape all configured forum sources."""
    if is_scraper_running(db, "forum_questions"):
        return {"status": "already_running", "results": {}, "total": 0, "new": 0}

    log_id = log_scrape_start(db, "forum_questions")

    results = {
        "squarespace_forum": 0,
        "total_questions": 0,
        "new_questions": 0,
        "status": "running",
        "errors": []
    }

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            try:
                count, new_q = await scrape_squarespace_forum(db, client)
                results["squarespace_forum"] = count
                results["total_questions"] += count
                results["new_questions"] += new_q
            except Exception as scrape_error:
                error_msg = f"Forum scraping failed: {str(scrape_error)}"
                results["errors"].append(error_msg)
                print(error_msg)

        db.commit()

        # Clean up old forum questions (similar to jobs system)
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
    from datetime import timedelta

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