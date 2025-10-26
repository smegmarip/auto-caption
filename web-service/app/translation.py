import logging
import requests
import deepl
from typing import Tuple
from app.subtitle import parse_srt, SubtitleCue

logger = logging.getLogger(__name__)


# Language code mapping: our codes -> DeepL codes
DEEPL_LANG_MAP = {
    'en': 'EN',
    'es': 'ES',
    'ja': 'JA',
    'pt': 'PT-BR',  # Brazilian Portuguese
    'ru': 'RU',
    'fr': 'FR',
    'de': 'DE',
    'nl': 'NL',
    'it': 'IT'
}

# LibreTranslate uses standard codes
LIBRETRANSLATE_LANG_MAP = {
    'en': 'en',
    'es': 'es',
    'ja': 'ja',
    'pt': 'pt',
    'ru': 'ru',
    'fr': 'fr',
    'de': 'de',
    'nl': 'nl',
    'it': 'it'
}


def translate_with_deepl(
    text: str,
    source_lang: str,
    target_lang: str,
    api_key: str
) -> Tuple[str, bool]:
    """
    Translate text using DeepL API.

    Args:
        text: Text to translate
        source_lang: Source language code
        target_lang: Target language code
        api_key: DeepL API key

    Returns:
        Tuple of (translated_text, success)
    """
    try:
        translator = deepl.Translator(api_key)

        # Map to DeepL language codes
        deepl_source = DEEPL_LANG_MAP.get(source_lang, source_lang.upper())
        deepl_target = DEEPL_LANG_MAP.get(target_lang, target_lang.upper())

        logger.info(f"Translating with DeepL: {deepl_source} -> {deepl_target}")

        result = translator.translate_text(
            text,
            source_lang=deepl_source,
            target_lang=deepl_target
        )

        translated_text = result.text
        logger.info(f"DeepL translation successful ({len(text)} -> {len(translated_text)} chars)")

        return translated_text, True

    except deepl.exceptions.QuotaExceededException:
        logger.warning("DeepL quota exceeded")
        return "", False

    except deepl.exceptions.AuthorizationException:
        logger.error("DeepL API key invalid or unauthorized")
        return "", False

    except Exception as e:
        logger.error(f"DeepL translation failed: {e}")
        return "", False


def translate_with_libretranslate(
    text: str,
    source_lang: str,
    target_lang: str,
    libretranslate_url: str
) -> Tuple[str, bool]:
    """
    Translate text using LibreTranslate service.

    Args:
        text: Text to translate
        source_lang: Source language code
        target_lang: Target language code
        libretranslate_url: URL of LibreTranslate service

    Returns:
        Tuple of (translated_text, success)
    """
    try:
        # Map to LibreTranslate language codes
        lt_source = LIBRETRANSLATE_LANG_MAP.get(source_lang, source_lang)
        lt_target = LIBRETRANSLATE_LANG_MAP.get(target_lang, target_lang)

        logger.info(f"Translating with LibreTranslate: {lt_source} -> {lt_target}")

        endpoint = f"{libretranslate_url}/translate"

        response = requests.post(
            endpoint,
            json={
                'q': text,
                'source': lt_source,
                'target': lt_target,
                'format': 'text'
            },
            timeout=60
        )

        response.raise_for_status()
        result = response.json()

        translated_text = result.get('translatedText', '')
        logger.info(f"LibreTranslate translation successful ({len(text)} -> {len(translated_text)} chars)")

        return translated_text, True

    except requests.exceptions.RequestException as e:
        logger.error(f"LibreTranslate translation failed: {e}")
        return "", False

    except Exception as e:
        logger.error(f"LibreTranslate unexpected error: {e}")
        return "", False


def translate_srt(
    srt_content: str,
    source_lang: str,
    target_lang: str,
    deepl_api_key: str,
    libretranslate_url: str
) -> Tuple[str, str]:
    """
    Translate SRT subtitle content, preserving timing.

    Uses DeepL as primary service, falls back to LibreTranslate if DeepL fails.

    Args:
        srt_content: Original SRT content
        source_lang: Source language code
        target_lang: Target language code
        deepl_api_key: DeepL API key
        libretranslate_url: URL of LibreTranslate service

    Returns:
        Tuple of (translated_srt_content, service_used)

    Raises:
        RuntimeError: If both translation services fail
    """
    logger.info(f"Translating SRT from {source_lang} to {target_lang}")

    # Parse SRT into cues
    cues = parse_srt(srt_content)

    if not cues:
        logger.warning("No subtitle cues to translate")
        return srt_content, "none"

    # Extract all text for batch translation
    texts = [cue.text for cue in cues]
    combined_text = '\n'.join(texts)

    logger.info(f"Translating {len(cues)} subtitle cues ({len(combined_text)} chars)")

    # Try DeepL first
    translated_text, success = translate_with_deepl(
        combined_text,
        source_lang,
        target_lang,
        deepl_api_key
    )

    service_used = "deepl"

    # Fall back to LibreTranslate if DeepL fails
    if not success:
        logger.warning("DeepL failed, falling back to LibreTranslate")
        translated_text, success = translate_with_libretranslate(
            combined_text,
            source_lang,
            target_lang,
            libretranslate_url
        )
        service_used = "libretranslate"

    if not success:
        raise RuntimeError("Both DeepL and LibreTranslate translation failed")

    # Split translated text back into lines
    translated_lines = translated_text.split('\n')

    # Ensure we have the same number of lines (some translations might add/remove newlines)
    if len(translated_lines) != len(texts):
        logger.warning(
            f"Translation line count mismatch: {len(texts)} -> {len(translated_lines)}. "
            "Adjusting..."
        )
        # Pad or trim to match original count
        while len(translated_lines) < len(texts):
            translated_lines.append("")
        translated_lines = translated_lines[:len(texts)]

    # Rebuild SRT with translated text but original timing
    from app.subtitle import format_timestamp

    srt_lines = []
    for i, cue in enumerate(cues):
        srt_lines.append(str(cue.index))
        srt_lines.append(
            f"{format_timestamp(cue.start_time)} --> {format_timestamp(cue.end_time)}"
        )
        srt_lines.append(translated_lines[i])
        srt_lines.append("")  # Blank line between cues

    translated_srt = '\n'.join(srt_lines)

    logger.info(f"Translation complete using {service_used}")

    return translated_srt, service_used
