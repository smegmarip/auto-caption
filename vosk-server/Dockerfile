FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install vosk-server
RUN pip install --no-cache-dir vosk-server

# Create model directory
RUN mkdir -p /opt/vosk-models

# Copy scripts
COPY download_models.sh /opt/download_models.sh
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/download_models.sh /opt/entrypoint.sh

# Set working directory
WORKDIR /opt

# Expose Vosk server port
EXPOSE 2700

# Use entrypoint to download models on first run
ENTRYPOINT ["/opt/entrypoint.sh"]
