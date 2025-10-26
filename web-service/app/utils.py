import os
import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def validate_video_path(video_path: str) -> None:
    """
    Validate that video file exists and is accessible.

    Args:
        video_path: Path to video file

    Raises:
        FileNotFoundError: If video file doesn't exist
        PermissionError: If video file is not readable
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if not os.path.isfile(video_path):
        raise ValueError(f"Path is not a file: {video_path}")

    if not os.access(video_path, os.R_OK):
        raise PermissionError(f"Video file is not readable: {video_path}")

    logger.info(f"Video file validated: {video_path}")


def find_existing_srt(video_path: str, language: str) -> Optional[str]:
    """
    Search for existing SRT file matching the video and language.

    Pattern: ^filename.*\\.{lang}(?:lish)?\\..*\\.srt$
    Examples:
        - movie.en.srt
        - movie.english.srt
        - movie.es.forced.srt
        - movie.pt.sdh.srt

    Args:
        video_path: Path to video file
        language: Language code (e.g., 'en', 'es')

    Returns:
        Path to existing SRT file or None if not found
    """
    video_dir = os.path.dirname(video_path)
    video_basename = Path(video_path).stem  # filename without extension

    # Escape special regex characters in the filename
    escaped_basename = re.escape(video_basename)

    # Build pattern: filename.*\.{lang}(?:lish)?\..*\.srt$
    # This matches: movie.en.srt, movie.english.srt, movie.es.forced.srt
    pattern = re.compile(
        rf"^{escaped_basename}.*\.{language}(?:lish)?\..*\.srt$",
        re.IGNORECASE
    )

    # Also check for simple pattern: filename.{lang}.srt
    simple_pattern = re.compile(
        rf"^{escaped_basename}\.{language}(?:lish)?\.srt$",
        re.IGNORECASE
    )

    try:
        for filename in os.listdir(video_dir):
            if simple_pattern.match(filename) or pattern.match(filename):
                srt_path = os.path.join(video_dir, filename)
                logger.info(f"Found existing SRT file: {srt_path}")
                return srt_path
    except OSError as e:
        logger.error(f"Error searching directory {video_dir}: {e}")

    logger.info(f"No existing SRT file found for {video_basename} in language {language}")
    return None


def save_srt_file(video_path: str, language: str, srt_content: str) -> str:
    """
    Save SRT content to file in the same directory as video.

    Naming convention: {video_basename}.{lang}.srt

    Args:
        video_path: Path to video file
        language: Language code
        srt_content: SRT subtitle content

    Returns:
        Path to saved SRT file

    Raises:
        PermissionError: If unable to write to directory
    """
    video_dir = os.path.dirname(video_path)
    video_basename = Path(video_path).stem

    # Create SRT filename
    srt_filename = f"{video_basename}.{language}.srt"
    srt_path = os.path.join(video_dir, srt_filename)

    try:
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        logger.info(f"SRT file saved: {srt_path}")
        return srt_path
    except OSError as e:
        logger.error(f"Failed to save SRT file: {e}")
        raise PermissionError(f"Cannot write SRT file to {srt_path}: {e}")


def read_srt_file(srt_path: str) -> str:
    """
    Read SRT file content.

    Args:
        srt_path: Path to SRT file

    Returns:
        SRT file content as string

    Raises:
        FileNotFoundError: If SRT file doesn't exist
    """
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"SRT file not found: {srt_path}")

    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.info(f"SRT file read: {srt_path}")
        return content
    except OSError as e:
        logger.error(f"Failed to read SRT file: {e}")
        raise
