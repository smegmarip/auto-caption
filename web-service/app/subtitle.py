import logging
from typing import List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SubtitleCue:
    """Represents a single subtitle cue"""
    index: int
    start_time: float
    end_time: float
    text: str


def format_timestamp(seconds: float) -> str:
    """
    Convert seconds to SRT timestamp format: HH:MM:SS,mmm

    Args:
        seconds: Time in seconds (can be float)

    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def group_words_into_cues(words: List[Dict], max_chars: int = 42, max_duration: float = 5.0) -> List[SubtitleCue]:
    """
    Group words from Vosk output into subtitle cues.

    Args:
        words: List of word dictionaries from Vosk with 'word', 'start', 'end' keys
        max_chars: Maximum characters per cue (default 42 for readability)
        max_duration: Maximum duration per cue in seconds

    Returns:
        List of SubtitleCue objects
    """
    if not words:
        logger.warning("No words provided for grouping")
        return []

    cues = []
    current_text = []
    current_start = words[0]['start']
    current_length = 0
    cue_index = 1

    for i, word in enumerate(words):
        word_text = word['word']
        word_length = len(word_text)

        # Check if adding this word would exceed limits
        next_length = current_length + word_length + (1 if current_text else 0)  # +1 for space
        duration = word['end'] - current_start

        # Create new cue if we exceed max_chars or max_duration
        if current_text and (next_length > max_chars or duration > max_duration):
            # Save current cue
            cues.append(SubtitleCue(
                index=cue_index,
                start_time=current_start,
                end_time=words[i - 1]['end'],
                text=' '.join(current_text)
            ))

            # Start new cue
            cue_index += 1
            current_text = [word_text]
            current_start = word['start']
            current_length = word_length
        else:
            # Add word to current cue
            current_text.append(word_text)
            current_length = next_length

    # Add final cue
    if current_text:
        cues.append(SubtitleCue(
            index=cue_index,
            start_time=current_start,
            end_time=words[-1]['end'],
            text=' '.join(current_text)
        ))

    logger.info(f"Grouped {len(words)} words into {len(cues)} subtitle cues")
    return cues


def vosk_json_to_srt(vosk_result: Dict) -> str:
    """
    Convert Vosk JSON result to SRT format.

    Vosk result format:
    {
        "result": [
            {"conf": 0.96, "end": 1.02, "start": 0.0, "word": "hello"},
            {"conf": 0.95, "end": 2.50, "start": 1.10, "word": "world"},
            ...
        ]
    }

    SRT format:
    1
    00:00:00,000 --> 00:00:02,000
    First subtitle line

    2
    00:00:02,000 --> 00:00:05,500
    Second subtitle line

    Args:
        vosk_result: Dictionary containing Vosk transcription result

    Returns:
        SRT formatted string
    """
    if 'result' not in vosk_result:
        logger.error("Invalid Vosk result: missing 'result' key")
        raise ValueError("Invalid Vosk result format")

    words = vosk_result['result']

    if not words:
        logger.warning("Vosk result contains no words")
        return ""

    # Group words into subtitle cues
    cues = group_words_into_cues(words)

    # Convert to SRT format
    srt_lines = []
    for cue in cues:
        srt_lines.append(str(cue.index))
        srt_lines.append(
            f"{format_timestamp(cue.start_time)} --> {format_timestamp(cue.end_time)}"
        )
        srt_lines.append(cue.text)
        srt_lines.append("")  # Blank line between cues

    srt_content = '\n'.join(srt_lines)
    logger.info(f"Generated SRT content with {len(cues)} cues")

    return srt_content


def parse_srt(srt_content: str) -> List[SubtitleCue]:
    """
    Parse SRT content into SubtitleCue objects.

    Args:
        srt_content: SRT formatted string

    Returns:
        List of SubtitleCue objects
    """
    cues = []
    blocks = srt_content.strip().split('\n\n')

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0])
            timing = lines[1]
            text = '\n'.join(lines[2:])

            # Parse timing: 00:00:00,000 --> 00:00:02,000
            times = timing.split(' --> ')
            start_time = parse_timestamp(times[0])
            end_time = parse_timestamp(times[1])

            cues.append(SubtitleCue(
                index=index,
                start_time=start_time,
                end_time=end_time,
                text=text
            ))
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse SRT block: {e}")
            continue

    logger.info(f"Parsed {len(cues)} subtitle cues from SRT")
    return cues


def parse_timestamp(timestamp: str) -> float:
    """
    Parse SRT timestamp to seconds.

    Format: HH:MM:SS,mmm

    Args:
        timestamp: SRT timestamp string

    Returns:
        Time in seconds (float)
    """
    # Replace comma with dot for milliseconds
    timestamp = timestamp.replace(',', '.')

    parts = timestamp.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])

    return hours * 3600 + minutes * 60 + seconds
