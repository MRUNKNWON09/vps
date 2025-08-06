FROM python:3.11.13-slim

# Set working directory
WORKDIR /app

# Install system packages and CLI tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    nano \
    vim \
    unzip \
    zip \
    tar \
    net-tools \
    iputils-ping \
    procps \
    htop \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies
COPY requirements.txt .

# Install Python packages
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Environment setup
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Expose the port Render will use
EXPOSE 8000

# Start the app using Gunicorn with Eventlet
CMD ["gunicorn", "-k", "gevent", "-w", "1", "app:app", "--bind", "0.0.0.0:8000"]
