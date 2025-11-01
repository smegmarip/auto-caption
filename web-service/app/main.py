import os
import logging
import requests
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from app.models import (
    CaptionRequest, CaptionResponse, HealthResponse,
    TaskStartResponse, TaskStatusResponse
)
from app.utils import validate_video_path, find_existing_srt, save_srt_file, read_srt_file
from app.transcription import transcribe_video
from app.translation import translate_srt
from app.task_manager import task_manager, TaskStage

# Configure logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
WHISPER_SERVER_URL = os.getenv('WHISPER_SERVER_URL', 'http://whisper-server:2800')
LIBRETRANSLATE_URL = os.getenv('LIBRETRANSLATE_URL', 'http://libretranslate:5000')

# Thread pool for background task execution (queue with max 4 workers)
executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="caption-worker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Auto-Caption service starting up...")
    logger.info(f"Whisper server: {WHISPER_SERVER_URL}")
    logger.info(f"LibreTranslate: {LIBRETRANSLATE_URL}")
    logger.info(f"Task executor: {executor._max_workers} workers")

    # Ensure temp directory exists
    os.makedirs('/tmp/auto-caption', exist_ok=True)

    yield

    # Shutdown
    logger.info("Auto-Caption service shutting down...")
    logger.info("Shutting down task executor...")
    executor.shutdown(wait=True, cancel_futures=False)
    logger.info("Task executor shutdown complete")


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

        # Whisper did the work (either transcription or translation to English)
        translation_service = "whisper"
        if translate_to_english:
            logger.info(f"Whisper translated from {request.language} to English")
        else:
            logger.info(f"Whisper transcribed in {detected_language}")

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


def generate_caption_background(
    task_id: str,
    video_path: str,
    language: str = None,
    translate_to: str = None
):
    """
    Background worker function for caption generation.
    Runs in thread pool executor and updates task status.

    Args:
        task_id: Task ID for status tracking
        video_path: Path to video file
        language: Source language code, or None for auto-detection
        translate_to: Optional target language code
    """
    lang_str = language if language else "auto-detect"
    logger.info(f"Task {task_id} started: video={video_path}, lang={lang_str}, translate={translate_to}")
    translation_service = None

    try:
        # Determine target language for file check
        target_lang = translate_to or language

        # Check for existing SRT
        existing_srt = find_existing_srt(video_path, target_lang)

        if existing_srt:
            logger.info(f"Task {task_id}: Using cached SRT file: {existing_srt}")
            try:
                srt_content = read_srt_file(existing_srt)

                # Complete immediately with cached result
                task_manager.complete_task(task_id, {
                    "caption_path": existing_srt,
                    "cached": True,
                    "translation_service": None
                })
                logger.info(f"Task {task_id} completed (cached)")
                return

            except Exception as e:
                logger.warning(f"Task {task_id}: Failed to read cached SRT, regenerating: {e}")
                # Continue to generate new SRT

        # Stage 1: Extract audio (10% of progress: 0-10%)
        task_manager.update_progress(task_id, 0.05, TaskStage.EXTRACTING_AUDIO)
        logger.info(f"Task {task_id}: Extracting audio...")
        task_manager.update_progress(task_id, 0.10, TaskStage.EXTRACTING_AUDIO)

        # Stage 2: Transcribe with Whisper (65% or 85% of progress)
        # Progress from 10% to 75% (if just transcribing) or 95% (if translating to English)
        # Whisper server will update progress internally via streaming
        logger.info(f"Task {task_id}: Starting transcription...")

        # Check if we need to translate to English using Whisper
        translate_to_english = (
            translate_to == 'en' and
            (language is None or language != 'en')
        )

        srt_content, detected_language, lang_probability = transcribe_video(
            video_path,
            language,
            WHISPER_SERVER_URL,
            translate_to_english=translate_to_english,
            task_id=task_id,
            task_manager=task_manager
        )

        if not srt_content:
            raise ValueError("Transcription produced no results")

        # Use detected language for subsequent operations if language was None
        source_lang = detected_language if language is None else language

        # Whisper did the work (either transcription or translation to English)
        translation_service = "whisper"
        if translate_to_english:
            logger.info(f"Task {task_id}: Whisper translated from {source_lang} to English")
            # Whisper handled 85% (transcription + translation), now at 95%
            task_manager.update_progress(task_id, 0.95, TaskStage.TRANSCRIBING)
        else:
            logger.info(f"Task {task_id}: Whisper transcribed in {detected_language}")
            # Whisper handled 65% (transcription only), now at 75%
            task_manager.update_progress(task_id, 0.75, TaskStage.TRANSCRIBING)

        logger.info(f"Task {task_id}: Transcription complete ({len(srt_content)} chars)")

        # Stage 3: Optional translation with LibreTranslate (20% of progress: 75-95%)
        # Use detected source language for translation
        if translate_to and translate_to != 'en' and translate_to != source_lang:
            task_manager.update_progress(task_id, 0.75, TaskStage.TRANSLATING)
            logger.info(f"Task {task_id}: Translating from {source_lang} to {translate_to}...")

            srt_content, translation_service = translate_srt(
                srt_content,
                source_lang,
                translate_to,
                LIBRETRANSLATE_URL
            )

            task_manager.update_progress(task_id, 0.95, TaskStage.TRANSLATING)
            logger.info(f"Task {task_id}: Translation complete using {translation_service}")

        # Stage 4: Save SRT file (5% of progress)
        task_manager.update_progress(task_id, 0.97, TaskStage.SAVING)
        logger.info(f"Task {task_id}: Saving SRT file...")

        srt_path = save_srt_file(video_path, target_lang, srt_content)

        logger.info(f"Task {task_id}: SRT saved to {srt_path}")

        # Complete task with result
        task_manager.complete_task(task_id, {
            "caption_path": srt_path,
            "cached": False,
            "translation_service": translation_service
        })

        logger.info(f"Task {task_id} completed successfully")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        task_manager.fail_task(task_id, str(e))


@app.post("/auto-caption/start", response_model=TaskStartResponse)
async def start_caption_task(request: CaptionRequest):
    """
    Start an async caption generation task.

    This endpoint immediately returns a task ID and processes the request
    in the background. Use /auto-caption/status/{task_id} to poll progress.

    Args:
        request: CaptionRequest with video_path, language, and optional translate_to

    Returns:
        TaskStartResponse with task_id and initial status
    """
    logger.info(
        f"Starting async caption task: video={request.video_path}, "
        f"lang={request.language}, translate={request.translate_to}"
    )

    # Validate video file exists before queuing task
    try:
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

    # Create task
    task_id = task_manager.create_task()

    # Submit to background executor (queued automatically)
    executor.submit(
        generate_caption_background,
        task_id,
        request.video_path,
        request.language,
        request.translate_to
    )

    logger.info(f"Task {task_id} queued")

    return TaskStartResponse(
        task_id=task_id,
        status="queued"
    )


@app.get("/auto-caption/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Get the status of an async caption generation task.

    Poll this endpoint to track task progress. When status is "completed",
    the result field will contain the caption_path and other metadata.

    Args:
        task_id: Task ID returned from /auto-caption/start

    Returns:
        TaskStatusResponse with current task status, progress, and result
    """
    task = task_manager.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )

    # Convert task to dict for response
    task_dict = task.to_dict()

    return TaskStatusResponse(**task_dict)


@app.get("/")
async def root():
    """Root endpoint with service information"""
    return {
        "service": "Auto-Caption",
        "version": "2.0.0",
        "description": "Automatic subtitle generation from video files using Whisper AI",
        "endpoints": {
            "health": "/health",
            "auto_caption": "POST /auto-caption (legacy sync endpoint)",
            "start_task": "POST /auto-caption/start (async task start)",
            "task_status": "GET /auto-caption/status/{task_id} (async task polling)"
        }
    }
