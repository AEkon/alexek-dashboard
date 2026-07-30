# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install llama-cpp-python for local Qwen3 8B inference
RUN pip install --no-cache-dir llama-cpp-python

# Download Qwen3 8B GGUF model
RUN mkdir -p /app/models && \
    curl -L -o /app/models/qwen3-8b.gguf "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/qwen3-8b-q4_k_m.gguf" || \
    echo "Model download failed - will use fallback API"

# Copy backend application
COPY backend/ .

# Copy frontend static files
COPY static/ ./static/

# Create directory for database
RUN mkdir -p /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV DATABASE_PATH=/app/data/dashboard.db
ENV SCRAPE_INTERVAL_MINUTES=30
ENV SCRAPE_ON_STARTUP=1
ENV FORUM_RSS_URL=https://forum.squarespace.com/forum/39-customize-with-code.xml
ENV FORUM_SCRAPE_INTERVAL_MINUTES=30
ENV FORUM_SCRAPE_ON_STARTUP=1
ENV QWEN_MODEL_PATH=/app/models/qwen3-8b.gguf

# Expose port
EXPOSE 8000

# Run the application
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT}"]