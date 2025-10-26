import os
import logging
import tempfile
import requests
import ffmpeg
from typing import Dict

logger = logging.getLogger(__name__)


def extract_audio(video_path: str) -> str:
    """
    Extract audio from video file and convert to 16kHz mono WAV.

    Args:
        video_path: Path to video file

    Returns:
        Path to temporary WAV file

    Raises:
        RuntimeError: If FFmpeg extraction fails
    """
    # Create temp file for audio
    temp_audio = tempfile.NamedTemporaryFile(
        suffix='.wav',
        delete=False,
        dir='/tmp/auto-caption'
    )
    temp_audio_path = temp_audio.name
    temp_audio.close()

    logger.info(f"Extracting audio from {video_path} to {temp_audio_path}")

    try:
        # Extract and downsample audio to 16kHz mono WAV (Vosk requirement)
        (
            ffmpeg
            .input(video_path)
            .output(
                temp_audio_path,
                acodec='pcm_s16le',  # PCM 16-bit little-endian
                ac=1,                 # Mono
                ar='16000',           # 16kHz sample rate
                format='wav'
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


def transcribe_audio(audio_path: str, language: str, vosk_server_url: str) -> Dict:
    """
    Send audio file to Vosk server for transcription.

    Args:
        audio_path: Path to WAV audio file
        language: Language code (e.g., 'en', 'es')
        vosk_server_url: URL of Vosk server

    Returns:
        Vosk JSON result with transcription

    Raises:
        ConnectionError: If cannot connect to Vosk server
        RuntimeError: If transcription fails
    """
    logger.info(f"Transcribing audio with Vosk (language: {language})")

    # Vosk server endpoint
    endpoint = f"{vosk_server_url}/model/{language}"

    try:
        # Read audio file
        with open(audio_path, 'rb') as audio_file:
            audio_data = audio_file.read()

        # Send to Vosk server
        response = requests.post(
            endpoint,
            data=audio_data,
            headers={'Content-Type': 'audio/x-wav'},
            timeout=300  # 5 minutes timeout for long videos
        )

        response.raise_for_status()

        # Parse JSON response
        result = response.json()

        if 'result' not in result:
            logger.error(f"Unexpected Vosk response: {result}")
            raise RuntimeError("Invalid response from Vosk server")

        word_count = len(result.get('result', []))
        logger.info(f"Transcription complete: {word_count} words recognized")

        return result

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Cannot connect to Vosk server at {vosk_server_url}: {e}")
        raise ConnectionError(f"Vosk server unavailable at {vosk_server_url}")

    except requests.exceptions.Timeout as e:
        logger.error(f"Vosk server timeout: {e}")
        raise RuntimeError("Transcription timeout - video may be too long")

    except requests.exceptions.RequestException as e:
        logger.error(f"Vosk server error: {e}")
        raise RuntimeError(f"Transcription failed: {e}")

    finally:
        # Clean up audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)
            logger.debug(f"Removed temporary audio file: {audio_path}")


def transcribe_video(video_path: str, language: str, vosk_server_url: str) -> Dict:
    """
    Complete transcription pipeline: extract audio and transcribe.

    Args:
        video_path: Path to video file
        language: Language code
        vosk_server_url: URL of Vosk server

    Returns:
        Vosk JSON result with transcription

    Raises:
        RuntimeError: If extraction or transcription fails
        ConnectionError: If cannot connect to Vosk server
    """
    # Extract audio
    audio_path = extract_audio(video_path)

    try:
        # Transcribe
        result = transcribe_audio(audio_path, language, vosk_server_url)
        return result
    except Exception as e:
        # Ensure audio file is cleaned up on error
        if os.path.exists(audio_path):
            os.remove(audio_path)
        raise
