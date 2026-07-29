---
name: frontend-patterns
description: Frontend interaction patterns including sorting, filtering, and refresh mechanisms
metadata:
  type: reference
---

## Per-Card Refresh Architecture

This is the core pattern that makes the dashboard feel alive without polling:

- Each visual **section** of the dashboard maps to a **data source**
- Each section has a **GET endpoint** (fetch current data) and a **POST endpoint** (re-scrape that source)
- Each section has a **refresh icon** in its header that hits the POST endpoint
- The frontend updates just that section's state on success

```python
@app.get("/api/tasks")
async def get_tasks():
    return db.execute("SELECT * FROM tasks WHERE status = 'open' ORDER BY priority").fetchall()

@app.post("/api/refresh/tasks")
async def refresh_tasks(background_tasks: BackgroundTasks):
    background_tasks.add_task(scrapers.tasks.sync_from_source)
    return {"status": "refreshing"}
```

Long-running refreshes (scraping, API calls) should return 202 immediately and run in a background thread. Track status in a `scrape_log` table so the UI can show a spinner and the system can prevent duplicate concurrent runs.

## Sortable Table Headers

```tsx
const [sortKey, setSortKey] = useState('created_at');
const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

const toggleSort = (key: string) => {
  if (sortKey === key) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
  else { setSortKey(key); setSortDir('asc'); }
};

// In the table header:
<th onClick={() => toggleSort('title')} style={{ cursor: 'pointer' }}>
  Title {sortKey === 'title' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
</th>
```

## Filter Pills

```tsx
const [activeFilter, setActiveFilter] = useState<string | null>(null);
const platforms = [...new Set(data.map(d => d.platform))];

// Render:
{platforms.map(p => (
  <button
    key={p}
    className={`filter-pill ${activeFilter === p ? 'active' : ''}`}
    onClick={() => setActiveFilter(activeFilter === p ? null : p)}
  >
    {p}
  </button>
))}
```

## Expandable Rows

Lazy-load detail on first expand — don't fetch detail for every row on page load.

## Per-Card Refresh

```tsx
const [refreshing, setRefreshing] = useState(false);

const handleRefresh = async () => {
  setRefreshing(true);
  await fetch('/api/refresh/tasks', { method: 'POST' });
  const res = await fetch('/api/tasks');
  setTasks(await res.json());
  setRefreshing(false);
};

// In the section header:
<button onClick={handleRefresh} disabled={refreshing}>
  {refreshing ? '↻' : '⟳'}
</button>
```