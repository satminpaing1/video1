# Python base image
FROM python:3.9-slim

# Install FFmpeg (Crucial for MP3)
RUN apt-get update && \
    apt-get install -y ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# --- အဓိက ပြင်ဆင်ထားသည့်နေရာ ---
# ကွင်းစကွင်းပိတ် [ ] တွေ မထည့်ရပါ။ ဒါမှ $PORT အလုပ်လုပ်ပါမည်။
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
