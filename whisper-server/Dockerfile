FROM nvidia/cuda:12.4.1-cudnn9-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /opt

# Install Python packages
RUN pip3 install --no-cache-dir \
    faster-whisper==1.0.3 \
    flask==3.0.0 \
    flask-cors==4.0.0

# Create model cache directory
RUN mkdir -p /opt/models

# Copy server script
COPY whisper_http_server.py /opt/whisper_http_server.py

# Expose port
EXPOSE 2800

# Set environment variables
ENV WHISPER_MODEL=large-v3
ENV WHISPER_DEVICE=cuda
ENV WHISPER_COMPUTE_TYPE=float16

# Run server
CMD ["python3", "/opt/whisper_http_server.py"]
