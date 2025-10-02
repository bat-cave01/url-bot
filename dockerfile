FROM python:3.11-slim-bookworm

WORKDIR /app

# ✅ Install build tools needed for tgcrypto
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# ✅ Copy dependencies and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Copy your bot source code
COPY . .

# ✅ Start your bot
CMD ["python", "bot.py"]
