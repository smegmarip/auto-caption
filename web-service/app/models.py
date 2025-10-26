from typing import Optional
from pydantic import BaseModel, Field, field_validator


# Supported languages
SUPPORTED_LANGUAGES = ["en", "es", "ja", "pt", "ru", "fr", "de", "nl", "it"]


class CaptionRequest(BaseModel):
    """Request model for generating captions"""

    video_path: str = Field(
        ...,
        description="Path to the video file (must be within /data)",
        examples=["/data/example.mp4"]
    )
    language: str = Field(
        ...,
        description="Language code for transcription (en, es, ja, pt, ru, fr, de, nl, it)",
        examples=["en"]
    )
    translate_to: Optional[str] = Field(
        None,
        description="Optional language code to translate subtitles to",
        examples=["es"]
    )

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        """Validate language code"""
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Language '{v}' not supported. "
                f"Supported languages: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        return v

    @field_validator("translate_to")
    @classmethod
    def validate_translate_to(cls, v: Optional[str]) -> Optional[str]:
        """Validate translation target language"""
        if v is not None and v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Language '{v}' not supported for translation. "
                f"Supported languages: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        return v


class CaptionResponse(BaseModel):
    """Response model for caption generation"""

    srt_content: str = Field(
        ...,
        description="The generated SRT subtitle content"
    )
    file_path: str = Field(
        ...,
        description="Path where the SRT file was saved"
    )
    cached: bool = Field(
        ...,
        description="Whether the subtitle was retrieved from cache (existing file)"
    )
    translation_service: Optional[str] = Field(
        None,
        description="Translation service used (deepl, libretranslate, or null if no translation)"
    )


class HealthResponse(BaseModel):
    """Response model for health check"""

    status: str = Field(..., description="Service status")
    vosk_available: bool = Field(..., description="Vosk server availability")
    libretranslate_available: bool = Field(..., description="LibreTranslate service availability")
