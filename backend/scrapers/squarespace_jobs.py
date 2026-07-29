import feedparser
import httpx
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import html

# Keywords for filtering Squarespace jobs
SQUARESPACE_KEYWORDS = [
    'squarespace designer',
    'squarespace fix',
    'squarespace custom css',
    'squarespace expert',
    'squarespace help',
    'squarespace website',
    'squarespace development',
    'squarespace template',
    'squarespace redesign'
]

# Additional short-term/ad-hoc indicators
SHORT_TERM_INDICATORS = [
    'ad-hoc',
    'short-term',
    'one-time',
    'single project',
    'quick fix',
    'micro project',
    'small job',
    'hourly',
    'fixed price'
]

def is_squarespace_job(title: str, description: str) -> bool:
    """Check if job is Squarespace-related based on keywords."""
    combined_text = f"{title} {description}".lower()
    return any(keyword.lower() in combined_text for keyword in SQUARESPACE_KEYWORDS)

def is_short_term_job(title: str, description: str) -> bool:
    """Check if job appears to be short-term/ad-hoc."""
    combined_text = f"{title} {description}".lower()
    return any(indicator.lower() in combined_text for indicator in SHORT_TERM_INDICATORS)

def extract_rate(text: str) -> Optional[Dict[str, int]]:
    """Extract rate information from job text."""
    # Look for patterns like "$50-100", "$75/hr", "fixed price $500"
    rate_patterns = [
        r'\$(\d+)-\$(\d+)',  # Range: $50-100
        r'\$(\d+)\s*/\s*hr',  # Hourly: $75/hr
        r'\$(\d+)\s*/\s*hour',  # Hourly: $75/hour
        r'fixed price.*?\$(\d+)',  # Fixed price
        r'budget.*?\$(\d+)',  # Budget
    ]

    for pattern in rate_patterns:
        match = re.search(pattern, text.lower())
        if match:
            try:
                if '-' in match.group(0):
                    # Range: $50-100
                    rate_min = int(match.group(1))
                    rate_max = int(match.group(2))
                    return {'rate_min': rate_min, 'rate_max': rate_max}
                else:
                    # Single value
                    rate = int(match.group(1))
                    return {'rate_min': rate, 'rate_max': rate}
            except (ValueError, IndexError):
                continue

    return None

async def scrape_upwork_rss(db) -> int:
    """Scrape Upwork RSS feed for Squarespace jobs."""
    upwork_rss_url = "https://www.upwork.com/feed/job/feed?search=squarespace"

    try:
        resp = httpx.get(upwork_rss_url, timeout=30, follow_redirects=True)
        feed = feedparser.parse(resp.content)

        rows = 0
        for entry in feed.entries[:50]:  # Limit to most recent 50 jobs
            title = entry.get('title', '')
            description = entry.get('description', '')
            link = entry.get('link', '')
            published = entry.get('published', '')

            if not is_squarespace_job(title, description):
                continue

            # Parse and clean description
            clean_description = html.unescape(re.sub('<[^<]+?>', '', description))

            # Extract rate info
            rate_info = extract_rate(f"{title} {description}")

            # Determine job type
            job_type = 'short-term' if is_short_term_job(title, clean_description) else 'unknown'

            # Find matching keywords
            matched_keywords = [kw for kw in SQUARESPACE_KEYWORDS if kw.lower() in f"{title} {clean_description}".lower()]
            keyword_matches = ', '.join(matched_keywords)

            # Parse date
            try:
                if published:
                    posted_date = datetime.strptime(published, '%a, %d %b %Y %H:%M:%S %z').isoformat()
                else:
                    posted_date = datetime.utcnow().isoformat()
            except ValueError:
                posted_date = datetime.utcnow().isoformat()

            # Generate source ID from URL
            source_id = re.sub(r'[^\w\s-]', '', link.split('/')[-1])[:50]

            # Insert with non-zero upsert rule
            db.execute("""
                INSERT INTO jobs (source, source_id, title, description, url, posted_date, job_type, rate_min, rate_max, currency, keyword_matches, status, created_at, updated_at)
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
                    updated_at = ?,
                    status = CASE WHEN status = 'archived' THEN 'archived' ELSE excluded.status END
            """, (
                'upwork', source_id, title, clean_description, link, posted_date, job_type,
                rate_info.get('rate_min') if rate_info else None,
                rate_info.get('rate_max') if rate_info else None,
                'USD', keyword_matches, 'new', datetime.utcnow().isoformat(), datetime.utcnow().isoformat()
            ))
            rows += 1

        db.commit()
        return rows

    except Exception as e:
        raise Exception(f"Upwork RSS scrape failed: {str(e)}")

async def scrape_reddit_freelance(db) -> int:
    """Scrape Reddit r/freelance_forhire for Squarespace jobs."""
    reddit_url = "https://www.reddit.com/r/freelance_forhire/search.json?q=squarespace&restrict_sr=1&sort=new"

    try:
        resp = httpx.get(reddit_url, timeout=30, headers={'User-Agent': 'Dashboard/1.0'})
        data = resp.json()

        rows = 0
        for post in data.get('data', {}).get('children', [])[:25]:
            post_data = post.get('data', {})
            title = post_data.get('title', '')
            selftext = post_data.get('selftext', '')
            url = f"https://reddit.com{post_data.get('permalink', '')}"
            created_utc = post_data.get('created_utc', 0)

            if not is_squarespace_job(title, selftext):
                continue

            # Combine title and selftext for analysis
            full_text = f"{title} {selftext}"
            clean_description = html.unescape(selftext[:500]) if selftext else title

            # Determine job type
            job_type = 'short-term' if is_short_term_job(title, clean_description) else 'unknown'

            # Find matching keywords
            matched_keywords = [kw for kw in SQUARESPACE_KEYWORDS if kw.lower() in full_text.lower()]
            keyword_matches = ', '.join(matched_keywords)

            # Convert UTC timestamp to ISO format
            try:
                posted_date = datetime.fromtimestamp(created_utc).isoformat()
            except (ValueError, TypeError):
                posted_date = datetime.utcnow().isoformat()

            # Generate source ID
            source_id = str(post_data.get('id', ''))

            # Insert with non-zero upsert rule
            db.execute("""
                INSERT INTO jobs (source, source_id, title, description, url, posted_date, job_type, keyword_matches, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    url = excluded.url,
                    posted_date = excluded.posted_date,
                    job_type = excluded.job_type,
                    keyword_matches = excluded.keyword_matches,
                    updated_at = ?,
                    status = CASE WHEN status = 'archived' THEN 'archived' ELSE excluded.status END
            """, (
                'reddit', source_id, title, clean_description, url, posted_date, job_type,
                keyword_matches, 'new', datetime.utcnow().isoformat(), datetime.utcnow().isoformat()
            ))
            rows += 1

        db.commit()
        return rows

    except Exception as e:
        raise Exception(f"Reddit scrape failed: {str(e)}")

async def scrape_all(db) -> Dict[str, int]:
    """Scrape all job sources and return counts."""
    results = {
        'upwork': 0,
        'reddit': 0,
        'total': 0
    }

    try:
        results['upwork'] = await scrape_upwork_rss(db)
        results['reddit'] = await scrape_reddit_freelance(db)
        results['total'] = results['upwork'] + results['reddit']

    except Exception as e:
        # If one source fails, continue with others
        print(f"Scraping error: {str(e)}")

    return results

async def scrape(db) -> int:
    """Main scrape function for job monitoring."""
    try:
        results = await scrape_all(db)
        return results['total']
    except Exception as e:
        raise Exception(f"Job scrape failed: {str(e)}")