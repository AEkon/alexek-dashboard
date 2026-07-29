# 🎯 Squarespace Job Dashboard

A custom dashboard that monitors freelance job boards for Squarespace-related work, filtering for ad-hoc and short-term opportunities.

## ✨ Features

- **Smart Job Monitoring**: Scrapes Upwork RSS and Reddit r/freelance_forhire
- **Intelligent Filtering**: Automatically detects short-term/ad-hoc Squarespace jobs
- **Rate Extraction**: Parses budget information from postings
- **Real-time Search**: Full-text search across titles, descriptions, and keywords
- **Live Statistics**: Track new jobs, short-term opportunities, and recent activity
- **Sortable Tables**: Click any column to sort ascending/descending
- **Direct Integration**: Click through to view jobs on original platforms

## 🏗️ Architecture

**Backend**: Python 3.12+ / FastAPI / SQLite (WAL mode)
**Frontend**: React / TypeScript / Vite
**Design**: Information-dense, 4-color palette, avoids AI design patterns

## 🚀 Quick Start

### Local Development

```bash
# Install backend dependencies
cd backend
pip install -r requirements.txt

# Start backend (port 8000)
python -m main

# Install frontend dependencies
cd frontend
npm install

# Start frontend (port 3000)
npm run dev
```

Visit `http://localhost:3000` to see your dashboard!

### First Run

1. Start both servers as above
2. Click "Refresh" on the dashboard to scrape initial jobs
3. Wait 3-5 seconds for scraping to complete
4. Browse Squarespace opportunities with filtering and search

## 🎨 Design System

Uses a disciplined 4-color palette:
- **Primary** (#722F37): Headers, emphasis
- **Accent** (#2A9D8F): Interactive elements, links
- **Highlight** (#C4813D): Warnings, important info
- **Background** (#FAF0E6): Page background

Follows strict rules: information density over whitespace, every table sortable, filter pills over dropdowns, no AI slop patterns.

## 📊 API Endpoints

- `GET /health` - Health check
- `GET /api/jobs` - Get jobs (filter by job_type, source, status, limit)
- `GET /api/jobs/search?q=term` - Search jobs
- `GET /api/jobs/stats` - Job statistics
- `POST /api/refresh/jobs` - Trigger background scraping
- `PATCH /api/jobs/{id}` - Update job status
- `DELETE /api/jobs/{id}` - Archive job

## 🔍 Squarespace Keywords

Automatically filters for:
- "Squarespace designer", "Squarespace fix"
- "Squarespace custom CSS", "Squarespace expert"
- "Squarespace help", "Squarespace website"
- "Squarespace development", "Squarespace template"

## 🌐 Deployment

Since you use Squarespace hosting, deploy the backend API to Railway, Render, or DigitalOcean. See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed instructions.

## 📁 Project Structure

```
├── backend/
│   ├── main.py              # FastAPI server
│   ├── db.py               # SQLite database layer
│   ├── scrapers/
│   │   └── squarespace_jobs.py  # Job scraper
│   └── requirements.txt    # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── App.tsx         # React dashboard
│   │   ├── App.css         # Design system CSS
│   │   └── main.tsx        # Entry point
│   ├── index.html          # HTML shell
│   └── package.json        # Node dependencies
├── .claude/rules/          # Reference patterns
│   ├── database-conventions.md
│   ├── design-system.md
│   ├── frontend-patterns.md
│   └── scraper-rules.md
└── DEPLOYMENT.md           # Deployment guide
```

## 🎯 Built For

Personal dashboard monitoring for Squarespace professionals who want to:
- Find ad-hoc Squarespace work quickly
- Monitor multiple job sources in one place
- Filter for short-term opportunities
- Track market activity and rates

## ⚡ Performance

- SQLite WAL mode for concurrent reads/writes
- Idempotent migrations run on every startup
- Non-zero upsert rule prevents data corruption
- Background scraping doesn't block UI
- Responsive design for mobile and desktop

Built following the "Build a Custom Dashboard with Claude Code" patterns.