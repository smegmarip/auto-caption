# Auto-Caption Service - Implementation Plan

## Character/Video Calculation
**DeepL Free Tier Analysis:**
- 500,000 characters ÷ 1,020 chars/min = ~490 minutes (~8 hours of video)
- ~4 full movies per month (2 hours each)
- ~16 TV episodes per month (30 min each)
- **Strategy:** Use DeepL as primary, LibreTranslate as fallback when quota exhausted

## Architecture Overview

**Docker Compose stack with 3 services:**
1. **web-service** (FastAPI) - Main API endpoint on port 8000
2. **vosk-server** - Speech recognition engine (internal network only)
3. **libretranslate** - Translation fallback service (internal network only)

## Project Structure

```
auto-caption/
├── docker-compose.yml
├── .env.example
├── README.md
├── web-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py              # FastAPI endpoints
│       ├── models.py            # Request/response schemas
│       ├── subtitle.py          # SRT generation/parsing
│       ├── transcription.py     # Vosk client
│       ├── translation.py       # DeepL + LibreTranslate
│       └── utils.py             # File operations
└── vosk-server/
    ├── Dockerfile
    ├── entrypoint.sh            # Downloads models on first run
    ├── download_models.sh       # Downloads 8 large models (~12GB)
    └── models/                  # Model storage (host-mounted, ~12GB)
```

## API Endpoint Specification

### POST /auto-caption

**Request Body:**
```json
{
  "video_path": "/shared/media/movie.mp4",
  "language": "es",
  "translate_to": "en"  // optional
}
```

**Response:**
```json
{
  "srt_content": "1\n00:00:00,000 --> 00:00:02,000\nHola mundo\n\n...",
  "file_path": "/shared/media/movie.es.srt",
  "cached": false,
  "translation_service": "deepl"  // or "libretranslate" or null
}
```

## Supported Languages

### Vosk Models (Large/Server versions)
- **English** - vosk-model-en-us-0.22 (1.8GB, 5.69% WER)
- **Spanish** - vosk-model-es-0.42 (1.4GB, 7.50% WER)
- **Japanese** - vosk-model-ja-0.22 (1GB, 8.40% char error)
- **Portuguese** - vosk-model-pt-fb-v0.1.1 (1.6GB)
- **Russian** - vosk-model-ru-0.42 (1.8GB, 4.5% WER)
- **French** - vosk-model-fr-0.22 (1.4GB, 14.72% WER)
- **German** - vosk-model-de-0.21 (1.9GB)
- **Dutch** - vosk-model-nl-spraakherkenning-0.6 (860MB, 20.40% WER)

**Total model storage: ~12GB**

## Subtitle Generation Workflow

### Step-by-step Process

**a. Validate request**
- Check video file exists at video_path
- Validate language is supported
- Validate translate_to language (if provided)

**b. Check for existing subtitle**
- Pattern: `^{filename}.*\.{lang}(?:lish)?\..*\.srt$`
- Examples: `movie.en.srt`, `movie.english.srt`, `movie.es.forced.srt`
- If found AND no translation needed: return cached file
- If found AND translation needed: check for translated version

**c. Extract audio via FFmpeg**
- Command: `ffmpeg -i {video_path} -ar 16000 -ac 1 -f wav {temp_audio}.wav`
- Downsample to 16kHz mono WAV (Vosk requirement)
- Use temporary directory for intermediate files

**d. Submit audio to vosk-server**
- HTTP POST to `http://vosk-server:2700/recognize`
- Stream audio file to Vosk endpoint
- Specify language model via API

**e. Parse Vosk JSON response**
- Format: `{"result": [{"conf": 0.96, "end": 1.02, "start": 0.0, "word": "hello"}]}`
- Extract timing and text segments
- Group words into subtitle cues (max ~42 chars per line)

**f. Convert JSON → SRT format**
- SRT format:
  ```
  1
  00:00:00,000 --> 00:00:02,000
  First subtitle line

  2
  00:00:02,000 --> 00:00:05,500
  Second subtitle line
  ```
- Proper timing format: HH:MM:SS,mmm
- Sequential numbering
- Blank line between cues

**g. (Optional) Translate**
- If `translate_to` parameter provided:
  1. Try DeepL API first
  2. Track character usage for quota management
  3. If DeepL fails/quota exceeded: fallback to LibreTranslate
  4. Preserve timestamps, only translate text content
  5. Return which service was used in response

**h. Save .srt file**
- Naming convention: `{video_basename}.{lang}.srt`
- Save to same directory as video file
- If translation: `{video_basename}.{translate_to}.srt`

**i. Return response**
- JSON with SRT content, file path, cached flag, translation service used

## Implementation Steps

### 1. Core Infrastructure
- [ ] Create docker-compose.yml with 3 services
- [ ] Configure volume mount: Unraid share → /shared/media
- [ ] Create .env.example for DeepL API key, host paths
- [ ] Set up health checks for all services
- [ ] Configure internal Docker network

### 2. Vosk Server Container
- [ ] Create Dockerfile based on alphacep/vosk-server
- [ ] Write download_models.sh script for 8 large models
- [ ] Configure multi-language model loading
- [ ] Set up model directory structure
- [ ] Expose port 2700 (internal only)

### 3. LibreTranslate Container
- [ ] Use official libretranslate/libretranslate image
- [ ] Configure language pairs
- [ ] Set up persistent model storage
- [ ] Expose port 5000 (internal only)

### 4. FastAPI Web Service - Core Setup
- [ ] Create Dockerfile with Python 3.11+
- [ ] Install dependencies: fastapi, uvicorn, ffmpeg-python, requests, deepl
- [ ] Create requirements.txt
- [ ] Set up FastAPI app with CORS for video.js client
- [ ] Configure logging

### 5. FastAPI Web Service - API Layer
- [ ] Define Pydantic models for request/response (models.py)
- [ ] Implement POST /auto-caption endpoint (main.py)
- [ ] Add request validation
- [ ] Implement error handling and HTTP status codes
- [ ] Add health check endpoint: GET /health

### 6. Subtitle Workflow - File Operations (utils.py)
- [ ] Implement video file existence check
- [ ] Implement existing SRT file search with regex
- [ ] Implement SRT file saving logic
- [ ] Add file path sanitization

### 7. Subtitle Workflow - Transcription (transcription.py)
- [ ] Implement FFmpeg audio extraction
- [ ] Create Vosk server client (HTTP requests)
- [ ] Parse Vosk JSON response
- [ ] Group words into subtitle cues

### 8. Subtitle Workflow - SRT Generation (subtitle.py)
- [ ] Implement JSON to SRT converter
- [ ] Format timestamps correctly
- [ ] Handle line wrapping (max chars per line)
- [ ] Parse existing SRT files (for caching)

### 9. Translation Layer (translation.py)
- [ ] Implement DeepL API client
- [ ] Add character usage tracking/logging
- [ ] Implement LibreTranslate client
- [ ] Create fallback logic with error handling
- [ ] Translate SRT content while preserving timing

### 10. Testing & Documentation
- [ ] Create README.md with:
  - Setup instructions
  - Unraid Docker deployment guide
  - API documentation with examples
  - Environment variable reference
- [ ] Test each language model
- [ ] Test translation workflow (DeepL + fallback)
- [ ] Test SRT caching logic
- [ ] Test error scenarios (missing files, quota exceeded, etc.)

## Technologies & Dependencies

### Web Service (Python)
- **fastapi** - Web framework with async support
- **uvicorn** - ASGI server
- **pydantic** - Request/response validation
- **deepl** - DeepL API client
- **requests** - HTTP client for Vosk/LibreTranslate
- **ffmpeg-python** - FFmpeg wrapper

### System Dependencies
- **FFmpeg** - Audio extraction and conversion

### Docker Services
- **Vosk Server** - Speech-to-text engine
- **LibreTranslate** - Self-hosted translation service

## Configuration

### Environment Variables (.env)
```bash
# DeepL API
DEEPL_API_KEY=your_free_api_key_here

# Volume Mounts (for docker-compose)
UNRAID_MEDIA_PATH=/mnt/user/media

# Service Ports
WEB_SERVICE_PORT=8000
VOSK_SERVER_PORT=2700  # internal only
LIBRETRANSLATE_PORT=5000  # internal only

# Logging
LOG_LEVEL=INFO
```

## Deployment on Unraid

1. Clone repository to Unraid appdata
2. Copy .env.example to .env and configure
3. Run `docker-compose up -d` to start all services
4. Access API at `http://{unraid-ip}:8000`
5. Monitor logs: `docker-compose logs -f web-service`

## Future Enhancements (Not in Initial Scope)

- Automatic language detection (instead of requiring language parameter)
- Support for more subtitle formats (VTT, ASS, SSA)
- Batch processing endpoint for multiple videos
- WebSocket support for real-time progress updates
- Model caching/preloading optimization
- GPU acceleration for Vosk (if available)
