# 🚀 Railway Deployment Guide - hq.alexek.com

## 🎯 Deployment Overview
Deploy your Squarespace Job Dashboard to Railway with the custom domain `hq.alexek.com`

## 📋 Prerequisites
- GitHub account with your dashboard code pushed
- Railway account (free tier available)
- Domain access to configure DNS for alexek.com

## 🚀 Step-by-Step Deployment

### 1. Push Code to GitHub

```bash
cd /Users/alex/Work/alexek-dashboard

# Initialize git if needed
git init
git add .
git commit -m "Initial Squarespace Job Dashboard"

# Create GitHub repo and push
gh repo create alexek-dashboard --public --source=.
git push -u origin master
```

### 2. Deploy to Railway

#### Option A: Via Railway CLI (Recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login to Railway
railway login

# Initialize project
railway init

# Deploy backend
railway up
```

#### Option B: Via Railway Dashboard

1. Go to [railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your `alexek-dashboard` repository
4. Railway will detect Python and auto-configure

### 3. Configure Backend Service

Railway will automatically:
- Detect `requirements.txt` and install dependencies
- Use `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set up health checks at `/health`
- Provide a URL like `https://your-project-name.up.railway.app`

### 4. Add Custom Domain (hq.alexek.com)

#### In Railway Dashboard:
1. Go to your project → Settings → Domains
2. Click "Add Domain" → `hq.alexek.com`
3. Railway will show you DNS records to add

#### Configure DNS (at your domain registrar):
```
Type: CNAME
Name: hq
Target: your-project-name.up.railway.app
TTL: 3600
```

**Or for A record:**
```
Type: A
Name: hq
Target: Railway-provided IP
TTL: 3600
```

### 5. Update Frontend Configuration

The frontend is already configured to work with Railway:

**For local development:**
```bash
cd frontend
npm run dev  # Uses Vite proxy to localhost:8000
```

**For production:**
- Frontend uses relative paths (`/api/jobs`)
- Works perfectly when served from same domain as backend
- No API base URL changes needed!

### 6. Deploy Frontend (Two Options)

#### Option A: Serve from Railway (Recommended)

Add this to your `railway.json`:

```json
{
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "python -m uvicorn main:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health"
  },
  "addons": [
    "static-frontend"
  ]
}
```

Then add a `static` folder with your built frontend:

```bash
cd frontend
npm run build
cp -r dist ../static/
git add static/
git commit -m "Add frontend build"
git push
```

#### Option B: Separate Frontend Deployment

Deploy frontend to Netlify/Vercel and update Railway backend URL.

### 7. Test Deployment

```bash
# Test backend health
curl https://hq.alexek.com/health

# Test jobs endpoint
curl https://hq.alexek.com/api/jobs

# Test frontend
open https://hq.alexek.com
```

## 🔧 Environment Variables (Optional)

If needed, add in Railway dashboard:

```bash
# No secrets required for basic operation
# Optional: Add API keys for extended features
```

## 📊 Railway Features

Your deployment includes:
- **Auto-scaling**: Handles traffic spikes automatically
- **SSL/HTTPS**: Automatic SSL certificates
- **Health monitoring**: Restarts on crashes
- **Deploy previews**: Test changes before production
- **Logs**: Built-in logging and monitoring

## 🔄 Continuous Deployment

Every push to GitHub triggers automatic Railway deployment:

```bash
git add .
git commit -m "Update dashboard"
git push
# Railway auto-deploys
```

## 📱 Access Your Dashboard

- **Production**: https://hq.alexek.com
- **Health check**: https://hq.alexek.com/health
- **API docs**: https://hq.alexek.com/docs (FastAPI auto-docs)

## 🎯 What You Get

**Live Dashboard Features:**
- ✅ Real-time Squarespace job monitoring
- ✅ Upwork + Reddit job scraping
- ✅ Smart filtering and search
- ✅ Rate extraction and statistics
- ✅ Responsive mobile design
- ✅ Automatic SSL/HTTPS
- ✅ Custom domain branding

**Next Steps:**
1. Click "Refresh" to scrape initial jobs
2. Set up cron job for automatic refresh (optional)
3. Share your dashboard link with others!

## 💡 Pro Tips

- **Database**: SQLite stored in Railway filesystem (persistent)
- **Backups**: Railway maintains filesystem across deployments
- **Monitoring**: Check Railway dashboard for usage metrics
- **Scaling**: Free tier handles thousands of requests/day

Your Squarespace Job Dashboard is now live at **hq.alexek.com**! 🎉