FROM python:3.12-slim

# Install system dependencies for tgcrypto and other Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .

# Upgrade pip and install dependencies (including tgcrypto)
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Copy the rest of the project
COPY . .

# Expose port if you are running Flask/other API
EXPOSE 8080

# Command to start your bot
CMD ["python", "main.py"]
