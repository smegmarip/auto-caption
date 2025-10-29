#!/usr/bin/env python3

import os
import json
import tempfile
from datetime import datetime
from threading import Lock
from faster_whisper import WhisperModel
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Configuration
MODEL_NAME = os.getenv('WHISPER_MODEL', 'large-v3')
DEVICE = os.getenv('WHISPER_DEVICE', 'cuda')
COMPUTE_TYPE = os.getenv('WHISPER_COMPUTE_TYPE', 'float16')

# Initialize model (loaded on first request to save startup time)
model = None

# Task state management (in-memory)
task_states = {}  # {task_id: {status, progress, result, error, timestamp, duration, updated_at}}
task_lock = Lock()


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


# Task state management functions
def create_task(task_id, duration=None):
    """Initialize task state."""
    with task_lock:
        task_states[task_id] = {
            "status": "processing",
            "progress": 0.0,
            "timestamp": 0.0,
            "duration": duration,
            "result": None,
            "error": None,
            "updated_at": datetime.utcnow().isoformat()
        }


def update_task_progress(task_id, progress, timestamp):
    """Update task progress."""
    with task_lock:
        if task_id in task_states:
            task_states[task_id]["progress"] = progress
            task_states[task_id]["timestamp"] = timestamp
            task_states[task_id]["updated_at"] = datetime.utcnow().isoformat()


def complete_task(task_id, result):
    """Mark task as completed."""
    with task_lock:
        if task_id in task_states:
            task_states[task_id]["status"] = "completed"
            task_states[task_id]["progress"] = 1.0
            task_states[task_id]["result"] = result
            task_states[task_id]["updated_at"] = datetime.utcnow().isoformat()


def fail_task(task_id, error):
    """Mark task as failed."""
    with task_lock:
        if task_id in task_states:
            task_states[task_id]["status"] = "failed"
            task_states[task_id]["error"] = str(error)
            task_states[task_id]["updated_at"] = datetime.utcnow().isoformat()


def get_task_status(task_id):
    """Get current task state."""
    with task_lock:
        return task_states.get(task_id)


def stream_transcribe_srt(segments, info, task_id):
    """
    Generator function to stream SRT transcription with progress updates.
    Yields JSON-lines format.
    """
    try:
        # Initialize task state
        total_duration = round(info.duration, 2)
        create_task(task_id, duration=total_duration)

        # Build SRT while streaming progress
        srt_lines = []
        segment_count = 0

        for i, segment in enumerate(segments, start=1):
            # Format SRT entry
            start_time = format_srt_timestamp(segment.start)
            end_time = format_srt_timestamp(segment.end)

            srt_lines.append(str(i))
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(segment.text.strip())
            srt_lines.append("")
            segment_count = i

            # Calculate and yield progress
            progress = segment.end / total_duration if total_duration > 0 else 0.0
            update_task_progress(task_id, progress, segment.end)

            # Yield progress update (JSON-lines format)
            yield json.dumps({
                "type": "progress",
                "progress": progress,
                "timestamp": segment.end,
                "duration": total_duration
            }) + "\n"

        # Build final SRT content
        srt_content = "\n".join(srt_lines)

        # Prepare final result
        result = {
            "srt_content": srt_content,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "segment_count": segment_count
        }

        # Store result and mark complete
        complete_task(task_id, result)

        # Yield completion message
        yield json.dumps({
            "type": "complete",
            **result
        }) + "\n"

        print(f"SRT streaming complete: {segment_count} segments, task_id={task_id}")

    except Exception as e:
        # Mark task as failed
        fail_task(task_id, str(e))
        yield json.dumps({
            "type": "error",
            "error": str(e)
        }) + "\n"
        raise


@app.route('/', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "message": "Whisper HTTP server is running",
        "model": MODEL_NAME,
        "device": DEVICE
    })


@app.route('/status/<task_id>', methods=['GET'])
def get_status(task_id):
    """Get status of a transcription task."""
    task_state = get_task_status(task_id)

    if not task_state:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "task_id": task_id,
        "status": task_state["status"],
        "progress": task_state["progress"],
        "timestamp": task_state["timestamp"],
        "duration": task_state["duration"],
        "error": task_state["error"],
        "updated_at": task_state["updated_at"]
    })


@app.route('/result/<task_id>', methods=['GET'])
def get_result(task_id):
    """Get final result of a completed transcription task."""
    task_state = get_task_status(task_id)

    if not task_state:
        return jsonify({"error": "Task not found"}), 404

    if task_state["status"] == "failed":
        return jsonify({
            "task_id": task_id,
            "status": "failed",
            "error": task_state["error"]
        }), 500

    if task_state["status"] != "completed":
        return jsonify({
            "task_id": task_id,
            "status": task_state["status"],
            "message": "Task not yet completed"
        }), 202

    return jsonify({
        "task_id": task_id,
        "status": "completed",
        **task_state["result"]
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
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.2,              # Lower threshold = more sensitive to speech
                    "min_speech_duration_ms": 100, # Catch brief utterances
                    "min_silence_duration_ms": 500 # Less aggressive silence cuts
                }
            )

            # Process segments from generator (avoids blocking on list())
            words = []
            segments_data = []

            for segment in segments:
                # Extract segment-level data
                segments_data.append({
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "avg_logprob": segment.avg_logprob,
                    "no_speech_prob": segment.no_speech_prob
                })

                # Extract word-level data
                if hasattr(segment, 'words') and segment.words:
                    for word in segment.words:
                        words.append({
                            "word": word.word.strip(),
                            "start": word.start,
                            "end": word.end,
                            "probability": word.probability
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
            - task_id: Optional task ID for streaming progress updates

    Returns:
        - If task_id provided: Streaming JSON-lines with progress updates
        - If no task_id: Single JSON response (legacy mode)
    """
    try:
        # Get parameters
        language = request.args.get('language', None)
        task = request.args.get('task', 'transcribe')
        task_id = request.args.get('task_id', None)

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
                    "threshold": 0.2,              # Lower threshold = more sensitive to speech
                    "min_speech_duration_ms": 100, # Catch brief utterances
                    "min_silence_duration_ms": 500 # Less aggressive silence cuts
                }
            )

            # Use streaming mode if task_id provided, otherwise legacy mode
            if task_id:
                # Streaming mode with progress updates
                return Response(
                    stream_transcribe_srt(segments, info, task_id),
                    mimetype='application/x-ndjson'
                )
            else:
                # Legacy mode: return complete result
                srt_lines = []
                segment_count = 0
                total_duration = round(info.duration, 2)
                last_logged_progress = 0

                for i, segment in enumerate(segments, start=1):
                    # Format timestamps (SRT format: HH:MM:SS,mmm)
                    start_time = format_srt_timestamp(segment.start)
                    end_time = format_srt_timestamp(segment.end)

                    srt_lines.append(str(i))
                    srt_lines.append(f"{start_time} --> {end_time}")
                    srt_lines.append(segment.text.strip())
                    srt_lines.append("")  # Blank line between entries
                    segment_count = i

                    # Log progress every 10%
                    if total_duration > 0:
                        progress_pct = int((segment.end / total_duration) * 100)
                        if progress_pct >= last_logged_progress + 10:
                            print(f"Transcription progress: {progress_pct}% ({segment.end:.1f}s / {total_duration:.1f}s)")
                            last_logged_progress = progress_pct

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
