#!/usr/bin/env python3

import os
import json
import tempfile
from faster_whisper import WhisperModel
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Configuration
MODEL_NAME = os.getenv('WHISPER_MODEL', 'large-v3')
DEVICE = os.getenv('WHISPER_DEVICE', 'cuda')
COMPUTE_TYPE = os.getenv('WHISPER_COMPUTE_TYPE', 'float16')

# Initialize model (loaded on first request to save startup time)
model = None


def get_model():
    """Lazy load Whisper model."""
    global model
    if model is None:
        print(f"Loading Whisper model: {MODEL_NAME} on {DEVICE} with {COMPUTE_TYPE}")
        model = WhisperModel(
            MODEL_NAME,
            device=DEVICE,
            compute_type=COMPUTE_TYPE,
            download_root="/opt/models"
        )
        print(f"Model loaded successfully")
    return model


@app.route('/', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "message": "Whisper HTTP server is running",
        "model": MODEL_NAME,
        "device": DEVICE
    })


@app.route('/transcribe', methods=['POST'])
def transcribe():
    """
    Transcribe audio file to text with word-level timestamps.

    Request:
        - Body: Audio file (WAV, MP3, MP4, etc.)
        - Query params:
            - language: Source language code (optional, auto-detected if not specified)
            - task: 'transcribe' or 'translate' (default: transcribe)

    Returns:
        JSON with segments and word-level timestamps
    """
    try:
        # Get parameters
        language = request.args.get('language', None)
        task = request.args.get('task', 'transcribe')

        # Get audio data
        audio_data = request.data
        if not audio_data:
            return jsonify({"error": "No audio data provided"}), 400

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix='.audio', delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_path = temp_file.name

        try:
            # Load model
            whisper_model = get_model()

            # Transcribe
            print(f"Transcribing audio: language={language}, task={task}")
            segments, info = whisper_model.transcribe(
                temp_path,
                language=language,
                task=task,
                word_timestamps=True,
                vad_filter=True,  # Voice activity detection to skip silence
                vad_parameters={
                    "threshold": 0.5,
                    "min_speech_duration_ms": 250,
                    "min_silence_duration_ms": 2000
                }
            )

            # Convert segments to list (generator)
            segments_list = list(segments)

            # Extract word-level data
            words = []
            for segment in segments_list:
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        words.append({
                            "word": word.word.strip(),
                            "start": word.start,
                            "end": word.end,
                            "probability": word.probability
                        })

            # Extract segment-level data
            segments_data = []
            for segment in segments_list:
                segments_data.append({
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "avg_logprob": segment.avg_logprob,
                    "no_speech_prob": segment.no_speech_prob
                })

            print(f"Transcription complete: {len(words)} words, {len(segments_data)} segments")
            print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")

            return jsonify({
                "words": words,
                "segments": segments_data,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration
            })

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        print(f"Transcription error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500


@app.route('/transcribe/srt', methods=['POST'])
def transcribe_srt():
    """
    Transcribe audio file and return SRT format directly.

    Request:
        - Body: Audio file (WAV, MP3, MP4, etc.)
        - Query params:
            - language: Source language code (optional, auto-detected if not specified)
            - task: 'transcribe' or 'translate' (default: transcribe)

    Returns:
        SRT subtitle content as plain text
    """
    try:
        # Get parameters
        language = request.args.get('language', None)
        task = request.args.get('task', 'transcribe')

        # Get audio data
        audio_data = request.data
        if not audio_data:
            return jsonify({"error": "No audio data provided"}), 400

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix='.audio', delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_path = temp_file.name

        try:
            # Load model
            whisper_model = get_model()

            # Transcribe
            print(f"Transcribing audio to SRT: language={language}, task={task}")
            segments, info = whisper_model.transcribe(
                temp_path,
                language=language,
                task=task,
                word_timestamps=False,  # Segment-level is fine for SRT
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.5,
                    "min_speech_duration_ms": 250,
                    "min_silence_duration_ms": 2000
                }
            )

            # Convert to SRT format
            srt_lines = []
            segment_count = 0
            for i, segment in enumerate(segments, start=1):
                # Format timestamps (SRT format: HH:MM:SS,mmm)
                start_time = format_srt_timestamp(segment.start)
                end_time = format_srt_timestamp(segment.end)

                srt_lines.append(str(i))
                srt_lines.append(f"{start_time} --> {end_time}")
                srt_lines.append(segment.text.strip())
                srt_lines.append("")  # Blank line between entries
                segment_count = i

            srt_content = "\n".join(srt_lines)

            print(f"SRT generation complete: {segment_count} segments")
            print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")

            return jsonify({
                "srt_content": srt_content,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": info.duration,
                "segment_count": segment_count
            })

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        print(f"SRT transcription error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"SRT transcription failed: {str(e)}"}), 500


def format_srt_timestamp(seconds):
    """Format seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


if __name__ == '__main__':
    print("=" * 60)
    print("Whisper HTTP Server")
    print("=" * 60)
    print(f"Model: {MODEL_NAME}")
    print(f"Device: {DEVICE}")
    print(f"Compute Type: {COMPUTE_TYPE}")
    print(f"Model will be loaded on first request...")
    print("\nAvailable endpoints:")
    print("  GET  /                - Health check")
    print("  POST /transcribe      - Transcribe with word timestamps (JSON)")
    print("  POST /transcribe/srt  - Transcribe and return SRT format")
    print("\nQuery parameters:")
    print("  language - Source language code (optional, auto-detected)")
    print("  task     - 'transcribe' or 'translate' (default: transcribe)")
    print("=" * 60)

    app.run(host='0.0.0.0', port=2800, threaded=True)
