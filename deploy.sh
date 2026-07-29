#!/bin/bash

# Railway Deployment Script for hq.alexek.com
# This script helps deploy your Squarespace Job Dashboard to Railway

set -e

echo "🚀 Deploying Squarespace Job Dashboard to Railway..."
echo "Domain: hq.alexek.com"
echo ""

# Check if Railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "📦 Installing Railway CLI..."
    npm install -g @railway/cli
fi

# Check if logged in to Railway
if ! railway whoami &> /dev/null; then
    echo "🔐 Please login to Railway..."
    railway login
fi

# Build frontend
echo "🏗️  Building frontend..."
cd frontend
npm install
npm run build
cd ..

# Create static folder for Railway
echo "📁 Preparing static files..."
mkdir -p static
cp -r frontend/dist/* static/

# Initialize Railway project if not already done
if [ ! -f ".railway/project.json" ]; then
    echo "🆕 Initializing Railway project..."
    railway init
fi

# Deploy to Railway
echo "🚀 Deploying to Railway..."
railway up

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Get your Railway URL from: railway dashboard"
echo "2. Add custom domain 'hq.alexek.com' in Railway settings"
echo "3. Configure DNS: CNAME hq → your-project.up.railway.app"
echo "4. Test at: https://hq.alexek.com/health"
echo ""
echo "🎉 Your Squarespace Job Dashboard will be live at hq.alexek.com!"