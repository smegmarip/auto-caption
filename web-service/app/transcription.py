import os
import logging
import tempfile
import requests
import ffmpeg
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


def extract_audio(video_path: str) -> str:
    """
    Extract audio from video file to temporary file.
    Whisper accepts various audio formats, so we don't need strict conversion.

    Args:
        video_path: Path to video file

    Returns:
        Path to temporary audio file

    Raises:
        RuntimeError: If FFmpeg extraction fails
    """
    # Create temp file for audio (using .mp3 for smaller size)
    temp_audio = tempfile.NamedTemporaryFile(
        suffix='.mp3',
        delete=False,
        dir='/tmp/auto-caption'
    )
    temp_audio_path = temp_audio.name
    temp_audio.close()

    logger.info(f"Extracting audio from {video_path} to {temp_audio_path}")

    try:
        # Extract audio (Whisper handles various formats and sample rates)
        (
            ffmpeg
            .input(video_path)
            .output(
                temp_audio_path,
                acodec='libmp3lame',
                ac=1,  # Mono for smaller size
                ar='16000',  # 16kHz is sufficient for speech
                q='2'  # Good quality
            )
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )

        logger.info(f"Audio extracted successfully: {temp_audio_path}")
        return temp_audio_path

    except ffmpeg.Error as e:
        logger.error(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
        # Clean up temp file on error
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        raise RuntimeError(f"Failed to extract audio from video: {e}")


def transcribe_with_whisper(
    audio_path: str,
    language: Optional[str],
    whisper_server_url: str,
    translate_to_english: bool = False,
    task_id: str = None,
    task_manager=None
) -> Tuple[str, str, float]:
    """
    Send audio file to Whisper server for transcription and get SRT directly.

    Args:
        audio_path: Path to audio file
        language: Source language code (e.g., 'en', 'es', 'pt'), or None for auto-detection
        whisper_server_url: URL of Whisper server
        translate_to_english: If True, translate to English (uses Whisper's translate task)
        task_id: Optional task ID for progress updates
        task_manager: Optional TaskManager instance for progress updates

    Returns:
        Tuple of (srt_content, detected_language, language_probability)

    Raises:
        ConnectionError: If cannot connect to Whisper server
        RuntimeError: If transcription fails
    """
    import time
    import json

    task = 'translate' if translate_to_english else 'transcribe'
    lang_str = language if language else "auto-detect"
    logger.info(f"Transcribing with Whisper (language: {lang_str}, task: {task})")

    # Whisper server SRT endpoint
    endpoint = f"{whisper_server_url}/transcribe/srt"

    try:
        # Read audio file
        with open(audio_path, 'rb') as audio_file:
            audio_data = audio_file.read()

        # Generate whisper task ID if we have a web service task ID
        whisper_task_id = f"whisper-{task_id}" if task_id else None

        # Prepare params - only include language if provided
        params = {'task': task}
        if language:
            params['language'] = language
        if whisper_task_id:
            params['task_id'] = whisper_task_id

        # Send to Whisper server
        response = requests.post(
            endpoint,
            data=audio_data,
            params=params,
            stream=(whisper_task_id is not None),  # Stream if task_id provided
            timeout=600  # 10 minutes timeout for long videos
        )

        response.raise_for_status()

        # Handle streaming vs non-streaming response
        if whisper_task_id:
            # Streaming mode: parse JSON-lines and update progress
            result = None
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                try:
                    data = json.loads(line)

                    if data['type'] == 'progress':
                        # Map whisper progress (0-1) to task progress
                        whisper_progress = data['progress']
                        if translate_to_english:
                            # Whisper handles transcription + translation (85%)
                            task_progress = 0.10 + (whisper_progress * 0.85)
                        else:
                            # Whisper only transcribes (65%)
                            task_progress = 0.10 + (whisper_progress * 0.65)

                        if task_manager and task_id:
                            from app.task_manager import TaskStage
                            task_manager.update_progress(task_id, task_progress, TaskStage.TRANSCRIBING)

                    elif data['type'] == 'complete':
                        result = data

                    elif data['type'] == 'error':
                        raise RuntimeError(data['error'])

                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON line: {line}, error: {e}")
                    continue

            if not result:
                raise RuntimeError("No completion message received from Whisper server")

        else:
            # Legacy mode: single JSON response
            result = response.json()

        if 'srt_content' not in result:
            logger.error(f"Unexpected Whisper response: {result}")
            raise RuntimeError("Invalid response from Whisper server")

        srt_content = result['srt_content']
        detected_language = result.get('language', language)
        language_probability = result.get('language_probability', 0.0)
        segment_count = result.get('segment_count', 0)

        logger.info(
            f"Transcription complete: {segment_count} segments, "
            f"detected language: {detected_language} ({language_probability:.2%})"
        )

        return srt_content, detected_language, language_probability

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Cannot connect to Whisper server at {whisper_server_url}: {e}")
        raise ConnectionError(f"Whisper server unavailable at {whisper_server_url}")

    except requests.exceptions.Timeout as e:
        logger.error(f"Whisper server timeout: {e}")
        raise RuntimeError("Transcription timeout - video may be too long")

    except requests.exceptions.RequestException as e:
        logger.error(f"Whisper server error: {e}")
        raise RuntimeError(f"Transcription failed: {e}")

    finally:
        # Clean up audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)
            logger.debug(f"Removed temporary audio file: {audio_path}")


def transcribe_video(
    video_path: str,
    language: Optional[str],
    whisper_server_url: str,
    translate_to_english: bool = False,
    task_id: str = None,
    task_manager=None
) -> Tuple[str, str, float]:
    """
    Complete transcription pipeline: extract audio and transcribe with Whisper.

    Args:
        video_path: Path to video file
        language: Source language code, or None for auto-detection
        whisper_server_url: URL of Whisper server
        translate_to_english: If True, translate to English using Whisper
        task_id: Optional task ID for progress updates
        task_manager: Optional TaskManager instance for progress updates

    Returns:
        Tuple of (srt_content, detected_language, language_probability)

    Raises:
        RuntimeError: If extraction or transcription fails
        ConnectionError: If cannot connect to Whisper server
    """
    # Extract audio
    audio_path = extract_audio(video_path)

    try:
        # Transcribe with Whisper
        result = transcribe_with_whisper(
            audio_path,
            language,
            whisper_server_url,
            translate_to_english,
            task_id,
            task_manager
        )
        return result
    except Exception as e:
        # Ensure audio file is cleaned up on error
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise
