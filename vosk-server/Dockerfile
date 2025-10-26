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

# Copy model download script
COPY download_models.sh /opt/download_models.sh
RUN chmod +x /opt/download_models.sh

# Set working directory
WORKDIR /opt

# Download models on build (this will take time and space ~12GB)
RUN /opt/download_models.sh

# Expose Vosk server port
EXPOSE 2700

# Start Vosk server with all models
# The server will load models on demand based on language parameter
CMD ["python", "-m", "vosk_server", "--interface", "0.0.0.0", "--port", "2700", "--model-path", "/opt/vosk-models"]
