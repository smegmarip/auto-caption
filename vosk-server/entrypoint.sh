#!/bin/bash

set -e

MODEL_DIR="/opt/vosk-models"

echo "Checking for Vosk models in $MODEL_DIR..."

# Check if models directory is empty or missing required models
REQUIRED_MODELS=("en" "es" "ja" "pt" "ru" "fr" "de" "nl")
MODELS_EXIST=true

for lang in "${REQUIRED_MODELS[@]}"; do
    if [ ! -d "$MODEL_DIR/$lang" ]; then
        echo "Model '$lang' not found"
        MODELS_EXIST=false
        break
    fi
done

if [ "$MODELS_EXIST" = false ]; then
    echo "Models not found or incomplete. Downloading models (~12GB)..."
    echo "This is a one-time operation. Future container starts will be fast."
    /opt/download_models.sh
else
    echo "All models found. Skipping download."
fi

# Start Vosk server
echo "Starting Vosk server..."
exec python -m vosk_server --interface 0.0.0.0 --port 2700 --model-path /opt/vosk-models
