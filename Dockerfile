FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy and install local iqoptionapi package
COPY iqoptionapi/ /app/iqoptionapi/
RUN pip install --no-cache-dir -e /app/iqoptionapi

# Copy application code
COPY iqoption_bot/ /app/iqoption_bot/
COPY main.py /app/main.py

# Create data directory for persistent storage
RUN mkdir -p ./data
VOLUME ["./data"]

# Set default data directory
ENV DATA_DIR=./data

# Run the bot
CMD ["python3", "main.py"]

