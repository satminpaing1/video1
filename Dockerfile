# Python 3.9 ကို အခြေခံမယ်
FROM python:3.9-slim

# FFmpeg နဲ့ Node.js ကို မဖြစ်မနေ Install လုပ်ခိုင်းမယ်
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs && \
    rm -rf /var/lib/apt/lists/*

# Work Directory သတ်မှတ်မယ်
WORKDIR /app

# Requirements တွေကို Install လုပ်မယ်
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ကုဒ်တွေအားလုံးကို ကူးထည့်မယ်
COPY . .

# App ကို Run မယ်
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
