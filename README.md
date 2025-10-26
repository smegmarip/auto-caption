# Auto-Caption Service

Dockerized Python service for generating subtitles from local video files using Vosk speech recognition and optional translation with DeepL/LibreTranslate.

## Features

- **Automatic Speech Recognition**: Transcribe video files using Vosk with high-accuracy large models
- **Multi-language Support**: 8 languages supported (EN, ES, JA, PT, RU, FR, DE, NL)
- **Smart Caching**: Checks for existing subtitle files before generating new ones
- **Translation**: Optional translation with DeepL (primary) and LibreTranslate (fallback)
- **RESTful API**: FastAPI-based service with JSON responses
- **Docker Compose**: Easy deployment with 3-service architecture

## Architecture

```
┌─────────────────┐
│  video.js       │
│  or JavaScript  │
│  Client         │
└────────┬────────┘
         │ HTTP POST
         ▼
┌─────────────────┐
│  web-service    │◄──────┐
│  (FastAPI)      │       │
│  Port 8000      │       │
└────┬───────┬────┘       │
     │       │            │
     │       └────────────┤
     │                    │
     ▼                    ▼
┌─────────────┐    ┌──────────────┐
│ vosk-server │    │libretranslate│
│ (internal)  │    │  (internal)  │
└─────────────┘    └──────────────┘
```

## Supported Languages

| Language   | Code | Model Size | Accuracy (WER) |
|------------|------|------------|----------------|
| English    | en   | 1.8GB      | 5.69%          |
| Spanish    | es   | 1.4GB      | 7.50%          |
| Japanese   | ja   | 1GB        | 8.40%          |
| Portuguese | pt   | 1.6GB      | ~10%           |
| Russian    | ru   | 1.8GB      | 4.5%           |
| French     | fr   | 1.4GB      | 14.72%         |
| German     | de   | 1.9GB      | ~13%           |
| Dutch      | nl   | 860MB      | 20.40%         |

**Total model storage required: ~12GB**

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Unraid server with media share (or any Docker host)
- DeepL API key (free tier: 500k chars/month) - [Sign up here](https://www.deepl.com/pro-api)

### Installation

1. **Clone or copy this repository to your system**

2. **Create `.env` file**:
   ```bash
   cp .env.example .env
   ```

3. **Edit `.env` with your configuration**:
   ```bash
   # DeepL API key (get free key at https://www.deepl.com/pro-api)
   DEEPL_API_KEY=your_api_key_here

   # Path to your Unraid media share
   UNRAID_MEDIA_PATH=/mnt/user/media

   # Web service port (default: 8000)
   WEB_SERVICE_PORT=8000

   # Logging level
   LOG_LEVEL=INFO
   ```

4. **Build and start services**:
   ```bash
   docker-compose up -d
   ```

   **Note**: First start will download Vosk models (~12GB) to `vosk-server/models/`. This is a one-time operation taking 20-40 minutes. Models are persisted on the host, so subsequent container restarts are instant.

5. **Check service health**:
   ```bash
   curl http://localhost:8000/health
   ```

## API Usage

### Endpoint: POST /auto-caption

Generate subtitles from a video file.

**Request Body**:
```json
{
  "video_path": "/shared/media/movies/example.mp4",
  "language": "en",
  "translate_to": "es"
}
```

**Parameters**:
- `video_path` (required): Path to video file (must be within `/shared/media`)
- `language` (required): Source language code for transcription
- `translate_to` (optional): Target language code for translation

**Response**:
```json
{
  "srt_content": "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n...",
  "file_path": "/shared/media/movies/example.en.srt",
  "cached": false,
  "translation_service": "deepl"
}
```

**Response Fields**:
- `srt_content`: Complete SRT subtitle content
- `file_path`: Path where SRT file was saved
- `cached`: Whether subtitle was retrieved from existing file
- `translation_service`: Translation service used (`deepl`, `libretranslate`, or `null`)

### Examples

#### Basic Transcription (No Translation)
```bash
curl -X POST http://localhost:8000/auto-caption \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "/shared/media/movies/movie.mp4",
    "language": "en"
  }'
```

#### Transcription with Translation
```bash
curl -X POST http://localhost:8000/auto-caption \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "/shared/media/movies/movie.mp4",
    "language": "es",
    "translate_to": "en"
  }'
```

#### Using from JavaScript/video.js
```javascript
fetch('http://localhost:8000/auto-caption', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    video_path: '/shared/media/movies/movie.mp4',
    language: 'en',
    translate_to: 'es'
  })
})
.then(response => response.json())
.then(data => {
  console.log('SRT file saved:', data.file_path);
  // Use data.srt_content with video.js
});
```

### Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "vosk_available": true,
  "libretranslate_available": true
}
```

## Subtitle Caching

The service automatically checks for existing subtitle files before generating new ones. It searches for files matching:

**Pattern**: `{video_name}.*\.{lang}(?:lish)?\..*\.srt$`

**Examples**:
- `movie.en.srt`
- `movie.english.srt`
- `movie.es.forced.srt`
- `movie.pt.sdh.srt`

If found, the cached file is returned immediately (unless translation is requested to a different language).

## Translation Services

### DeepL (Primary)

- **Quality**: Superior translation quality
- **Free Tier**: 500,000 characters/month
- **Calculation**: ~490 minutes of video (~8 hours)
- **Equivalent**: ~4 full movies or ~16 TV episodes per month

Get your free API key: https://www.deepl.com/pro-api

### LibreTranslate (Fallback)

- **Quality**: Good quality, self-hosted
- **Limits**: Unlimited (runs in Docker)
- **Usage**: Automatically used when DeepL quota exhausted or fails

## Unraid Deployment

### Option 1: Docker Compose (Recommended)

1. **Install Compose Manager plugin** (if not installed):
   - Go to Apps → Search "Compose Manager"
   - Install the plugin

2. **Copy project to Unraid**:
   ```bash
   # From your Mac
   scp -r /Users/x/dev/resources/repo/auto-caption root@unraid-ip:/mnt/user/appdata/
   ```

3. **Configure `.env`**:
   ```bash
   cd /mnt/user/appdata/auto-caption
   cp .env.example .env
   nano .env
   ```

4. **Start with Compose Manager**:
   - Open Compose Manager UI
   - Add Stack → Browse to `/mnt/user/appdata/auto-caption`
   - Click "Compose Up"

### Option 2: Docker CLI

```bash
# SSH to Unraid
ssh root@unraid-ip

# Navigate to project
cd /mnt/user/appdata/auto-caption

# Start services (first run downloads models to vosk-server/models/)
docker-compose up -d

# View logs (watch model download progress on first run)
docker-compose logs -f vosk-server

# View web service logs
docker-compose logs -f web-service

# Stop services
docker-compose down
```

### Port Forwarding

If accessing from other devices on your LAN, ensure port 8000 is accessible:
- Go to Settings → Network Settings
- Check firewall rules if connections fail

## Project Structure

```
auto-caption/
├── docker-compose.yml          # Orchestrates 3 services
├── .env.example                # Environment configuration template
├── CLAUDE.md                   # Implementation plan
├── README.md                   # This file
│
├── vosk-server/
│   ├── Dockerfile              # Vosk server container
│   ├── entrypoint.sh           # Downloads models on first run
│   ├── download_models.sh      # Downloads 8 language models
│   └── models/                 # Model storage (host-mounted, ~12GB)
│
└── web-service/
    ├── Dockerfile              # FastAPI web service container
    ├── requirements.txt        # Python dependencies
    └── app/
        ├── main.py             # FastAPI endpoints
        ├── models.py           # Request/response schemas
        ├── subtitle.py         # SRT generation/parsing
        ├── transcription.py    # Vosk client + FFmpeg
        ├── translation.py      # DeepL + LibreTranslate
        └── utils.py            # File operations
```

## Workflow

The service follows this workflow for each caption request:

1. **Validate Request** - Check video file exists and parameters are valid
2. **Check Cache** - Search for existing SRT file in target language
3. **Extract Audio** - Use FFmpeg to extract and downsample audio to 16kHz mono WAV
4. **Transcribe** - Send audio to Vosk server for speech recognition
5. **Convert to SRT** - Transform Vosk JSON output to SRT format with proper timing
6. **Translate** (optional) - Translate subtitles using DeepL → LibreTranslate fallback
7. **Save File** - Write SRT file to video directory with language suffix
8. **Return Response** - Send JSON response with SRT content and metadata

## Troubleshooting

### Service won't start

Check logs:
```bash
docker-compose logs vosk-server
docker-compose logs web-service
docker-compose logs libretranslate
```

### Vosk server not ready

Vosk server needs time to load models. Wait 1-2 minutes after startup, then check:
```bash
curl http://localhost:2700/
```

### Video file not found

Ensure:
1. Video path in request starts with `/shared/media`
2. `UNRAID_MEDIA_PATH` in `.env` is correct
3. Volume mount in `docker-compose.yml` is correct

Example mapping:
- Host: `/mnt/user/media/movies/example.mp4`
- Container: `/shared/media/movies/example.mp4`
- Request: `{"video_path": "/shared/media/movies/example.mp4"}`

### Translation failing

1. **Check DeepL API key**:
   ```bash
   # View current config
   docker-compose exec web-service env | grep DEEPL
   ```

2. **Check quota usage**: Log in to DeepL dashboard

3. **LibreTranslate not running**:
   ```bash
   docker-compose restart libretranslate
   curl http://localhost:5000/languages
   ```

### FFmpeg errors

Ensure video file is readable and in a supported format. Most common formats (MP4, MKV, AVI, MOV) are supported.

## Performance

### Transcription Speed
- Real-time factor: ~0.1-0.3x (10-30% of video duration)
- Example: 1-hour video takes ~6-18 minutes to transcribe

### Resource Usage
- **RAM**: ~6GB total (4GB Vosk + 2GB LibreTranslate)
- **Disk**: ~12GB for Vosk models + Docker images
- **CPU**: Moderate during transcription

## Development

### Local Testing

```bash
# Build services
docker-compose build

# Start services
docker-compose up

# Run tests (if you add them)
docker-compose exec web-service pytest

# Access container shell
docker-compose exec web-service bash
```

### Environment Variables

| Variable              | Default                     | Description                      |
|-----------------------|-----------------------------|----------------------------------|
| `DEEPL_API_KEY`       | (required)                  | DeepL API authentication key     |
| `UNRAID_MEDIA_PATH`   | `/mnt/user/media`           | Host path to media files         |
| `WEB_SERVICE_PORT`    | `8000`                      | Port for FastAPI web service     |
| `LOG_LEVEL`           | `INFO`                      | Logging level                    |
| `VOSK_SERVER_URL`     | `http://vosk-server:2700`   | Vosk server URL (internal)       |
| `LIBRETRANSLATE_URL`  | `http://libretranslate:5000`| LibreTranslate URL (internal)    |

## API Documentation

Once running, interactive API documentation is available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## License

This project uses:
- **Vosk** - Apache 2.0 License
- **LibreTranslate** - AGPL-3.0 License
- **DeepL API** - Commercial (free tier available)
- **FastAPI** - MIT License

## Credits

- Speech recognition powered by [Vosk](https://alphacephei.com/vosk/)
- Translation by [DeepL](https://www.deepl.com/) and [LibreTranslate](https://libretranslate.com/)
- Inspired by [Transloadit DevTip](https://transloadit.com/devtips/automatic-spoken-language-detection-with-curl-open-source/)

## Support

For issues and feature requests, refer to the CLAUDE.md implementation plan or check:
- Vosk documentation: https://alphacephei.com/vosk/
- FastAPI documentation: https://fastapi.tiangolo.com/
- DeepL API docs: https://www.deepl.com/docs-api

## Future Enhancements

- Automatic language detection
- Support for VTT, ASS, SSA subtitle formats
- Batch processing endpoint
- WebSocket for real-time progress updates
- GPU acceleration for Vosk
- Model caching optimization
