import os
import logging
import requests
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.models import CaptionRequest, CaptionResponse, HealthResponse
from app.utils import validate_video_path, find_existing_srt, save_srt_file, read_srt_file
from app.transcription import transcribe_video
from app.subtitle import vosk_json_to_srt
from app.translation import translate_srt

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
VOSK_SERVER_URL = os.getenv('VOSK_SERVER_URL', 'http://vosk-server:2700')
LIBRETRANSLATE_URL = os.getenv('LIBRETRANSLATE_URL', 'http://libretranslate:5000')
DEEPL_API_KEY = os.getenv('DEEPL_API_KEY', '')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Auto-Caption service starting up...")
    logger.info(f"Vosk server: {VOSK_SERVER_URL}")
    logger.info(f"LibreTranslate: {LIBRETRANSLATE_URL}")
    logger.info(f"DeepL API key configured: {bool(DEEPL_API_KEY)}")

    # Ensure temp directory exists
    os.makedirs('/tmp/auto-caption', exist_ok=True)

    yield

    # Shutdown
    logger.info("Auto-Caption service shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Auto-Caption Service",
    description="Automatic subtitle generation from video files using Vosk speech recognition",
    version="1.0.0",
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
    vosk_available = False
    libretranslate_available = False

    # Check Vosk server
    try:
        response = requests.get(f"{VOSK_SERVER_URL}/", timeout=5)
        vosk_available = response.status_code == 200
    except Exception as e:
        logger.warning(f"Vosk health check failed: {e}")

    # Check LibreTranslate
    try:
        response = requests.get(f"{LIBRETRANSLATE_URL}/languages", timeout=5)
        libretranslate_available = response.status_code == 200
    except Exception as e:
        logger.warning(f"LibreTranslate health check failed: {e}")

    return HealthResponse(
        status="healthy" if vosk_available else "degraded",
        vosk_available=vosk_available,
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

    # Step 3 & 4: Extract audio and transcribe
    try:
        logger.info("Starting transcription...")
        vosk_result = transcribe_video(
            request.video_path,
            request.language,
            VOSK_SERVER_URL
        )

        # Convert to SRT
        srt_content = vosk_json_to_srt(vosk_result)

        if not srt_content:
            raise ValueError("Transcription produced no results")

    except ConnectionError as e:
        logger.error(f"Vosk server connection error: {e}")
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

    # Step 5: Optional translation
    if request.translate_to and request.translate_to != request.language:
        logger.info(f"Translating from {request.language} to {request.translate_to}")

        if not DEEPL_API_KEY:
            logger.warning("DeepL API key not configured, skipping DeepL")

        try:
            srt_content, translation_service = translate_srt(
                srt_content,
                request.language,
                request.translate_to,
                DEEPL_API_KEY,
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
