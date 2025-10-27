import os
import logging
import tempfile
import requests
import ffmpeg
from typing import Dict, Tuple

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
    language: str,
    whisper_server_url: str,
    translate_to_english: bool = False
) -> Tuple[str, str, float]:
    """
    Send audio file to Whisper server for transcription and get SRT directly.

    Args:
        audio_path: Path to audio file
        language: Source language code (e.g., 'en', 'es', 'pt')
        whisper_server_url: URL of Whisper server
        translate_to_english: If True, translate to English (uses Whisper's translate task)

    Returns:
        Tuple of (srt_content, detected_language, language_probability)

    Raises:
        ConnectionError: If cannot connect to Whisper server
        RuntimeError: If transcription fails
    """
    task = 'translate' if translate_to_english else 'transcribe'
    logger.info(f"Transcribing with Whisper (language: {language}, task: {task})")

    # Whisper server SRT endpoint
    endpoint = f"{whisper_server_url}/transcribe/srt"

    try:
        # Read audio file
        with open(audio_path, 'rb') as audio_file:
            audio_data = audio_file.read()

        # Send to Whisper server
        response = requests.post(
            endpoint,
            data=audio_data,
            params={
                'language': language,
                'task': task
            },
            timeout=600  # 10 minutes timeout for long videos
        )

        response.raise_for_status()

        # Parse JSON response
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
    language: str,
    whisper_server_url: str,
    translate_to_english: bool = False
) -> Tuple[str, str, float]:
    """
    Complete transcription pipeline: extract audio and transcribe with Whisper.

    Args:
        video_path: Path to video file
        language: Source language code
        whisper_server_url: URL of Whisper server
        translate_to_english: If True, translate to English using Whisper

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
            translate_to_english
        )
        return result
    except Exception as e:
        # Ensure audio file is cleaned up on error
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise
