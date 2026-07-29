---
name: scraper-rules
description: Scraper patterns and conventions for data collection
metadata:
  type: reference
---

## Pattern

One file per data source. Each scraper:
1. Fetches from one external source (API, RSS, scrape)
2. Transforms into your schema
3. Upserts into SQLite (respecting the non-zero rule)
4. Returns a count of affected rows

```python
# scrapers/github.py
import os, httpx

async def scrape(db):
    resp = httpx.get(
        "https://api.github.com/notifications",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    )
    rows = 0
    for item in resp.json():
        db.execute("""
            INSERT INTO respondables (source, source_id, title, url, created_at, status)
            VALUES ('github', ?, ?, ?, ?, 'pending')
            ON CONFLICT(source, source_id) DO UPDATE SET title = excluded.title
        """, (item['id'], item['subject']['title'], item['url'], item['updated_at']))
        rows += 1
    db.commit()
    return rows
```

## Scraper Rules

- **All secrets from environment variables.** Never hardcode tokens in code or commands.
- **Idempotent.** Running twice must not create duplicates. Upsert on natural keys.
- **Headless only.** If a scraper needs a browser, Playwright in headless mode. Never pop a visible window — it steals focus and can trigger platform security flags.
- **No concurrent duplicates.** Check `scrape_log` before starting.
- **Log everything.** Write to `scrape_log` on start and on finish (success or failure). You will need this to debug data gaps.