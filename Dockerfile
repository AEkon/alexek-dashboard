# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Node.js for frontend build
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application
COPY backend/ .

# Build frontend
COPY frontend/package*.json ./frontend/
RUN cd frontend && npm install

COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Create static directory and copy frontend files
RUN mkdir -p static && cp -r frontend/dist/* static/

# Create directory for database
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV DATABASE_PATH=/app/data/dashboard.db
ENV SCRAPE_INTERVAL_MINUTES=30
ENV SCRAPE_ON_STARTUP=1
ENV FORUM_RSS_URLS=squarespace_pages|https://forum.squarespace.com/forum/42-pages-content.xml,squarespace_design|https://forum.squarespace.com/forum/45-site-design-styles.xml,squarespace_media|https://forum.squarespace.com/forum/41-images-videos.xml,squarespace_commerce|https://forum.squarespace.com/forum/40-commerce.xml,squarespace_seo|https://forum.squarespace.com/forum/43-seo.xml
ENV FORUM_SCRAPE_INTERVAL_MINUTES=30
ENV FORUM_SCRAPE_ON_STARTUP=1

# Groq API (free tier) - set GROQ_API_KEY in Railway environment variables
# Get your free key at: https://console.groq.com/

# Expose port
EXPOSE 8000

# Run the application
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT}"]