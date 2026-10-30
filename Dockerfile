FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the platform package, including its vendored IQ Option client.
COPY trading_platform/ /app/trading_platform/

# Copy application code
COPY trading_platform/apps/main.py /app/trading_platform/apps/main.py
COPY trading_platform/scripts/harvest_market_data.py /app/trading_platform/scripts/harvest_market_data.py

# Create data directory for persistent storage
RUN mkdir -p ./data
VOLUME ["./data"]

# Set default data directory
ENV DATA_DIR=./data

# Run the bot
CMD ["python3", "-m", "trading_platform.apps.main"]

