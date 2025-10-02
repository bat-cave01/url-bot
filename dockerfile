FROM python:3.11-slim-bookworm

WORKDIR /app

# 🔨 Install gcc and build deps for tgcrypto
RUN apt-get update && apt-get install -y \
    gcc \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 🔨 Copy dependencies
COPY requirements.txt .

# 🔨 Install dependencies from requirements.txt (excluding tgcrypto if you want explicit install)
RUN pip install --no-cache-dir -r requirements.txt

# 🔨 Install tgcrypto explicitly
RUN pip install --no-cache-dir tgcrypto

# 🔨 Copy your bot code
COPY . .

# 🔨 Start the bot
CMD ["python", "bot.py"]
