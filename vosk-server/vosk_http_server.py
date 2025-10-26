#!/usr/bin/env python3

import os
import json
import wave
from vosk import Model, KaldiRecognizer
from flask import Flask, request, jsonify

app = Flask(__name__)

# Base path for models
MODEL_BASE_PATH = "/opt/vosk-models"

# Cache loaded models
models = {}


def get_model(language):
    """Load and cache a model for the given language."""
    if language not in models:
        model_path = os.path.join(MODEL_BASE_PATH, language)
        if not os.path.exists(model_path):
            raise ValueError(f"Model for language '{language}' not found at {model_path}")
        print(f"Loading model for language: {language}")
        models[language] = Model(model_path)
    return models[language]


@app.route('/', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "message": "Vosk HTTP server is running"})


@app.route('/model/<language>', methods=['POST'])
def recognize(language):
    """
    Recognize speech from WAV audio file.

    Args:
        language: Language code (en, es, ja, pt, ru, fr, de, nl, it)

    Request body: WAV audio data (16kHz, mono, PCM)

    Returns:
        JSON with transcription results including timestamps
    """
    try:
        # Get model for language
        model = get_model(language)

        # Get audio data from request
        audio_data = request.data

        if not audio_data:
            return jsonify({"error": "No audio data provided"}), 400

        # Write to temporary file to read with wave module
        temp_file = f"/tmp/temp_audio_{os.getpid()}.wav"
        with open(temp_file, 'wb') as f:
            f.write(audio_data)

        # Open WAV file
        try:
            wf = wave.open(temp_file, "rb")
        except Exception as e:
            os.remove(temp_file)
            return jsonify({"error": f"Invalid WAV file: {str(e)}"}), 400

        # Validate WAV format
        if wf.getnchannels() != 1:
            wf.close()
            os.remove(temp_file)
            return jsonify({"error": "Audio must be mono (1 channel)"}), 400

        if wf.getframerate() != 16000:
            wf.close()
            os.remove(temp_file)
            return jsonify({"error": "Audio must be 16kHz sample rate"}), 400

        # Create recognizer
        rec = KaldiRecognizer(model, wf.getframerate())
        rec.SetWords(True)

        # Process audio
        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                if 'result' in result:
                    results.extend(result['result'])

        # Get final result
        final_result = json.loads(rec.FinalResult())
        if 'result' in final_result:
            results.extend(final_result['result'])

        # Clean up
        wf.close()
        os.remove(temp_file)

        # Return results
        return jsonify({
            "result": results,
            "text": " ".join([word["word"] for word in results])
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Recognition failed: {str(e)}"}), 500


if __name__ == '__main__':
    print("Starting Vosk HTTP server on port 2700...")
    print(f"Model base path: {MODEL_BASE_PATH}")
    print("Available endpoints:")
    print("  GET  /          - Health check")
    print("  POST /model/<language> - Speech recognition")
    print("\nSupported languages: en, es, ja, pt, ru, fr, de, nl, it")

    app.run(host='0.0.0.0', port=2700, threaded=True)
