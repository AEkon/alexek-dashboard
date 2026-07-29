# Deployment Guide for Squarespace Job Dashboard

## 🎯 Overview
Since you use Squarespace for hosting, you'll need a hybrid approach:
- **Backend API**: Host on a separate service (Railway, Render, DigitalOcean, etc.)
- **Frontend**: Can be hosted on Squarespace, Netlify, Vercel, or combined with backend

## 🚀 Quick Start

### 1. Local Testing First
```bash
# Terminal 1: Start backend
cd backend
pip install -r requirements.txt
python -m main

# Terminal 2: Start frontend
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000` to test everything works.

### 2. Backend Deployment (Required)

Since Squarespace can't host Python APIs, choose one:

#### Option A: Railway (Recommended - Free tier available)
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

#### Option B: Render.com (Free tier available)
- Create account at render.com
- Connect GitHub repo
- Deploy as "Web Service" with Python
- Set environment variables if needed

#### Option C: DigitalOcean VPS
```bash
# SSH into your VPS
ssh user@your-vps-ip

# Install dependencies
sudo apt update
sudo apt install python3-pip python3-venv nginx

# Clone and setup
git clone your-repo
cd dashboard/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run with gunicorn
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 main:app
```

### 3. Frontend Deployment

#### Option A: Deploy with Backend (Simplest)
Many services (Railway, Render) let you deploy both together.

#### Option B: Separate Frontend
```bash
# Build for production
cd frontend
npm run build

# Deploy dist/ folder to:
# - Netlify: drag and drop
# - Vercel: vercel deploy
# - Or embed in your Squarespace site
```

### 4. Domain Configuration

#### Subdomain Approach (Recommended)
- `dashboard.yourdomain.com` → Backend API
- `www.yourdomain.com` → Your Squarespace site (with embedded dashboard)

#### Embed in Squarespace
1. Build the frontend: `npm run build`
2. Upload `dist/` contents to a static host
3. Embed in Squarespace using Code Block or Embed Block

## 🔧 Environment Variables

Set these in your hosting service:
```bash
# No secrets required for basic operation
# Optional: Add API keys for extended features
```

## 🌐 DNS Setup

1. Go to your domain registrar
2. Add A record: `dashboard.yourdomain.com` → your backend IP
3. Or use CNAME: `dashboard.yourdomain.com` → your hosting service

## ✅ Testing Deployment

```bash
# Test backend health
curl https://your-backend-url.com/health

# Test jobs endpoint
curl https://your-backend-url.com/api/jobs

# Test frontend
open https://your-frontend-url.com
```

## 📱 Current Project Status

**✅ Complete:**
- Database schema with jobs table
- Squarespace job scraper (Upwork RSS + Reddit)
- API endpoints with filtering and search
- React frontend with dashboard UI
- Per-card refresh architecture

**🎯 Ready for:**
- Backend deployment to Railway/Render/DigitalOcean
- Frontend deployment or Squarespace integration
- Domain configuration

## 🎨 Dashboard Features

Your dashboard includes:
- **Job Monitoring**: Scrapes Upwork + Reddit for Squarespace jobs
- **Smart Filtering**: Ad-hoc/short-term job detection
- **Rate Extraction**: Parses budget information
- **Keyword Search**: Full-text search across jobs
- **Real-time Stats**: New jobs, short-term count, recent activity
- **Sortable Tables**: Click any column header to sort
- **Direct Links**: View jobs directly on source platforms

## 🔄 Next Steps

1. **Deploy backend** → Railway/Render (10 minutes)
2. **Update frontend API URL** → Change proxy target in vite.config.ts
3. **Deploy frontend** → Same service or separate
4. **Configure domain** → Point dashboard.yourdomain.com
5. **Test live** → Verify job scraping and display

The scraper will automatically fetch new Squarespace jobs every time you click "Refresh" on your dashboard!