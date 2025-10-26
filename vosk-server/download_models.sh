#!/bin/bash

set -e

MODEL_DIR="/opt/vosk-models"
cd "$MODEL_DIR"

echo "Downloading Vosk models... This will take a while (~13GB total)"

# English - 1.8GB
echo "Downloading English model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip
unzip -q vosk-model-en-us-0.22.zip
rm vosk-model-en-us-0.22.zip
mv vosk-model-en-us-0.22 en

# Spanish - 1.4GB
echo "Downloading Spanish model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-es-0.42.zip
unzip -q vosk-model-es-0.42.zip
rm vosk-model-es-0.42.zip
mv vosk-model-es-0.42 es

# Japanese - 1GB
echo "Downloading Japanese model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-ja-0.22.zip
unzip -q vosk-model-ja-0.22.zip
rm vosk-model-ja-0.22.zip
mv vosk-model-ja-0.22 ja

# Portuguese - 1.6GB
echo "Downloading Portuguese model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-pt-fb-v0.1.1-20220516_2113.zip
unzip -q vosk-model-pt-fb-v0.1.1-20220516_2113.zip
rm vosk-model-pt-fb-v0.1.1-20220516_2113.zip
mv vosk-model-pt-fb-v0.1.1-20220516_2113 pt

# Russian - 1.8GB
echo "Downloading Russian model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip
unzip -q vosk-model-ru-0.42.zip
rm vosk-model-ru-0.42.zip
mv vosk-model-ru-0.42 ru

# French - 1.4GB
echo "Downloading French model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-fr-0.22.zip
unzip -q vosk-model-fr-0.22.zip
rm vosk-model-fr-0.22.zip
mv vosk-model-fr-0.22 fr

# German - 1.9GB
echo "Downloading German model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-de-0.21.zip
unzip -q vosk-model-de-0.21.zip
rm vosk-model-de-0.21.zip
mv vosk-model-de-0.21 de

# Dutch - 860MB
echo "Downloading Dutch model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-nl-spraakherkenning-0.6.zip
unzip -q vosk-model-nl-spraakherkenning-0.6.zip
rm vosk-model-nl-spraakherkenning-0.6.zip
mv vosk-model-nl-spraakherkenning-0.6 nl

# Italian - 1.2GB
echo "Downloading Italian model..."
wget -q --show-progress https://alphacephei.com/vosk/models/vosk-model-it-0.22.zip
unzip -q vosk-model-it-0.22.zip
rm vosk-model-it-0.22.zip
mv vosk-model-it-0.22 it

echo "All models downloaded successfully!"
ls -lh "$MODEL_DIR"
