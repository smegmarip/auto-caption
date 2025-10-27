import os
import logging
import requests
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.models import CaptionRequest, CaptionResponse, HealthResponse
from app.utils import validate_video_path, find_existing_srt, save_srt_file, read_srt_file
from app.transcription import transcribe_video
from app.translation import translate_srt

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
WHISPER_SERVER_URL = os.getenv('WHISPER_SERVER_URL', 'http://whisper-server:2800')
LIBRETRANSLATE_URL = os.getenv('LIBRETRANSLATE_URL', 'http://libretranslate:5000')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Auto-Caption service starting up...")
    logger.info(f"Whisper server: {WHISPER_SERVER_URL}")
    logger.info(f"LibreTranslate: {LIBRETRANSLATE_URL}")

    # Ensure temp directory exists
    os.makedirs('/tmp/auto-caption', exist_ok=True)

    yield

    # Shutdown
    logger.info("Auto-Caption service shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Auto-Caption Service",
    description="Automatic subtitle generation from video files using Whisper AI speech recognition",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware for video.js client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint to verify service and dependencies are running.
    """
    whisper_available = False
    libretranslate_available = False

    # Check Whisper server
    try:
        response = requests.get(f"{WHISPER_SERVER_URL}/", timeout=5)
        whisper_available = response.status_code == 200
    except Exception as e:
        logger.warning(f"Whisper health check failed: {e}")

    # Check LibreTranslate
    try:
        response = requests.get(f"{LIBRETRANSLATE_URL}/languages", timeout=5)
        libretranslate_available = response.status_code == 200
    except Exception as e:
        logger.warning(f"LibreTranslate health check failed: {e}")

    return HealthResponse(
        status="healthy" if whisper_available else "degraded",
        whisper_available=whisper_available,
        libretranslate_available=libretranslate_available
    )


@app.post("/auto-caption", response_model=CaptionResponse)
async def generate_caption(request: CaptionRequest):
    """
    Generate subtitles from video file.

    Workflow:
    1. Validate video file exists
    2. Check for existing SRT in requested language
    3. If not found, extract audio and transcribe with Vosk
    4. Convert transcription to SRT format
    5. Optionally translate to target language
    6. Save and return SRT file

    Args:
        request: CaptionRequest with video_path, language, and optional translate_to

    Returns:
        CaptionResponse with SRT content and metadata
    """
    logger.info(
        f"Caption request: video={request.video_path}, "
        f"lang={request.language}, translate={request.translate_to}"
    )

    try:
        # Step 1: Validate video file
        validate_video_path(request.video_path)

    except FileNotFoundError as e:
        logger.error(f"Video file not found: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except (ValueError, PermissionError) as e:
        logger.error(f"Video file validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    # Determine target language for file check
    target_lang = request.translate_to or request.language
    cached = False
    translation_service = None

    # Step 2: Check for existing SRT
    existing_srt = find_existing_srt(request.video_path, target_lang)

    if existing_srt:
        logger.info(f"Using cached SRT file: {existing_srt}")
        try:
            srt_content = read_srt_file(existing_srt)
            cached = True

            return CaptionResponse(
                srt_content=srt_content,
                file_path=existing_srt,
                cached=cached,
                translation_service=translation_service
            )

        except Exception as e:
            logger.warning(f"Failed to read cached SRT, regenerating: {e}")
            # Continue to generate new SRT

    # Step 3 & 4: Extract audio and transcribe with Whisper (gets SRT directly)
    try:
        logger.info("Starting transcription with Whisper...")

        # Check if we need to translate to English using Whisper
        translate_to_english = (
            request.translate_to == 'en' and
            request.language != 'en'
        )

        srt_content, detected_language, lang_probability = transcribe_video(
            request.video_path,
            request.language,
            WHISPER_SERVER_URL,
            translate_to_english=translate_to_english
        )

        if not srt_content:
            raise ValueError("Transcription produced no results")

        # If Whisper translated to English, mark it
        if translate_to_english:
            translation_service = "whisper"
            logger.info(f"Whisper translated from {request.language} to English")

    except ConnectionError as e:
        logger.error(f"Whisper server connection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech recognition service unavailable"
        )
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {str(e)}"
        )

    # Step 5: Optional translation (for non-English targets)
    if request.translate_to and request.translate_to != 'en' and request.translate_to != request.language:
        logger.info(f"Translating from {request.language} to {request.translate_to} using LibreTranslate")

        try:
            srt_content, translation_service = translate_srt(
                srt_content,
                request.language,
                request.translate_to,
                LIBRETRANSLATE_URL
            )

        except RuntimeError as e:
            logger.error(f"Translation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Translation failed: {str(e)}"
            )

    # Step 6: Save SRT file
    try:
        srt_path = save_srt_file(request.video_path, target_lang, srt_content)

    except PermissionError as e:
        logger.error(f"Failed to save SRT file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cannot save subtitle file: {str(e)}"
        )

    logger.info(f"Caption generation complete: {srt_path}")

    return CaptionResponse(
        srt_content=srt_content,
        file_path=srt_path,
        cached=cached,
        translation_service=translation_service
    )


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "Auto-Caption",
        "version": "1.0.0",
        "description": "Automatic subtitle generation from video files",
        "endpoints": {
            "health": "/health",
            "auto_caption": "POST /auto-caption"
        }
    }
