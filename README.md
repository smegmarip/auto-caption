# Auto-Caption Service

**Branch:** `whisper-rpc` (Whisper AI + Stash RPC integration)
**Status:** Production Ready

Dockerized subtitle generation service using Whisper AI for transcription with integrated Stash plugin support via Go RPC backend + JavaScript UI.

## Features

- **Whisper AI Transcription**: High-accuracy speech-to-text with 99+ language support
- **Real-time Progress Tracking**: Streaming progress updates during transcription
- **Built-in English Translation**: Whisper can translate any language → English
- **Stash Plugin Integration**: Dual-architecture (Go RPC backend + Stateless JavaScript UI)
- **Smart Caching**: Checks for existing subtitle files before generating
- **Async Task Management**: Non-blocking job queue with progress reporting
- **RESTful API**: FastAPI-based service with async endpoints
- **Toast Notifications**: Real-time status updates in Stash UI
- **Player Progress Indicator**: Caption icon with real-time percentage display (0-100%)
- **Automatic Tag Management**: Go RPC handles "Subtitled" tag updates
- **Flexible URL Resolution**: Supports IP addresses, hostnames, container names, and localhost

## Architecture

### Docker Services

```
┌────────────────────────────────────────────────────────┐
│                    Stash Instance                      │
└────────────────────┬───────────────────────────────────┘
                     │
                     │ triggers RPC task
                     ▼
         ┌────────────────────────┐
         │  Go RPC Plugin         │
         │  (stash-auto-caption)  │
         │  - HTTP Client         │
         │  - Task Polling        │
         │  - GraphQL Mutations   │
         │  - Tag Management      │
         │  - URL Resolution      │
         └──────────┬─────────────┘
                    │
                    │ HTTP POST/GET
                    ▼
         ┌────────────────────────┐
         │  web-service (FastAPI) │
         │  Port 8000             │
         │  - Async Task Manager  │
         │  - Progress Tracking   │
         └──────┬───────┬─────────┘
                │       │
                │       └─────────────┐
                ▼                     ▼
    ┌────────────────────┐  ┌──────────────────┐
    │  whisper-server    │  │  libretranslate  │
    │  (Flask)           │  │  (Translation)   │
    │  Port 2800         │  │  Port 5000       │
    │  - Whisper AI      │  │  (fallback)      │
    │  - Streaming       │  └──────────────────┘
    └────────────────────┘

         ┌────────────────────────┐
         │  JavaScript Plugin     │
         │  (Stash UI - STATELESS)│
         │  - Language Detection  │
         │  - Job Trigger         │
         │  - Player Integration  │
         │  - Toast Notifications │
         │  - Progress Indicator  │
         └────────────────────────┘
```

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Docker host (Linux, Windows, macOS, or NAS)
- For Stash integration: Stash instance with plugin support

### Installation

1. **Clone repository**:

   ```bash
   git clone <repo-url> auto-caption
   cd auto-caption
   git checkout whisper-rpc
   ```

2. **Configure environment**:

   ```bash
   cp .env.example .env
   nano .env
   ```

   Update:

   ```bash
   # Volume mount to your media directory
   MEDIA_PATH=/path/to/your/media

   # Service ports (defaults are fine)
   WEB_SERVICE_PORT=8000
   WHISPER_SERVER_PORT=2800
   LIBRETRANSLATE_PORT=5000

   # Whisper model (large-v3 for best accuracy)
   WHISPER_MODEL=large-v3
   ```

3. **Start services**:

   ```bash
   docker-compose up -d
   ```

4. **Check health**:
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:2800/
   ```

## Stash Plugin Installation

### 1. Deploy Plugin Files

```bash
# Copy plugin to Stash plugins directory
cp -r stash-auto-caption <STASH_PLUGINS_DIR>/

# Make binary executable
chmod +x <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc

# Verify binary
file <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc
# Expected: ELF 64-bit LSB executable, x86-64
```

### 2. Reload Plugins

In Stash UI:

1. Go to **Settings > Plugins**
2. Click **Reload Plugins**
3. Verify "Stash Auto Caption" appears in plugin list

### 3. Configure Plugin

1. Navigate to **Settings > Plugins > Stash Auto Caption**
2. Configure **Auto-Caption Service URL** (optional):
   - Leave empty for automatic detection (recommended)
   - Or specify custom URL: `http://auto-caption-web:8000`
   - Supports: IP addresses, hostnames, container names, localhost
3. Create required tags:
   - Tag: **Subtitled** (added automatically by plugin after caption generation)
   - Tag: **Foreign Language** (parent tag)
   - Child tags: **Spanish Language**, **Japanese Language**, **French Language**, etc.

### 4. Usage

**Automatic (Recommended):**

1. Tag scene with language (e.g., "Spanish Language")
2. Navigate to scene page
3. Plugin auto-detects foreign language and triggers caption generation
4. Toast notification: "Generating captions for..."
5. Player shows caption icon with live progress percentage (0-100%)
6. Monitor progress in **Jobs** queue
7. Caption loads automatically when complete
8. "Subtitled" tag added automatically by Go RPC plugin

**Manual:**

1. Navigate to scene
2. Click **Tasks** button
3. Select **Generate Caption for Scene**
4. Monitor in Jobs queue

## API Endpoints

### POST /auto-caption/start

Start async caption generation.

**Request:**

```json
{
  "video_path": "/data/movies/video.mp4",
  "language": "es",
  "translate_to": "en"
}
```

**Response:**

```json
{
  "task_id": "abc123",
  "status": "queued"
}
```

### GET /auto-caption/status/{task_id}

Poll task progress.

**Response:**

```json
{
  "task_id": "abc123",
  "status": "running",
  "progress": 0.45,
  "stage": "transcribing",
  "error": null,
  "result": null
}
```

### GET /health

Check service health.

**Response:**

```json
{
  "status": "healthy",
  "whisper_available": true,
  "libretranslate_available": true
}
```

## Supported Languages

Whisper supports **99+ languages** with automatic detection:

**Common Languages:**

- English (en), Spanish (es), French (fr), German (de)
- Italian (it), Portuguese (pt), Russian (ru), Dutch (nl)
- Japanese (ja), Chinese (zh), Korean (ko), Arabic (ar)
- And 80+ more...

**Translation:**

- Whisper: Any language → English (during transcription)
- LibreTranslate: English → other languages (post-processing)

## Configuration

### Environment Variables

| Variable             | Default                      | Description             |
| -------------------- | ---------------------------- | ----------------------- |
| `WHISPER_SERVER_URL` | `http://whisper-server:2800` | Whisper server endpoint |
| `WHISPER_MODEL`      | `large-v3`                   | Whisper model size      |
| `LIBRETRANSLATE_URL` | `http://libretranslate:5000` | Translation service     |
| `MEDIA_PATH`         | `/path/to/media`             | Host media directory    |
| `WEB_SERVICE_PORT`   | `8000`                       | Web service port        |
| `LOG_LEVEL`          | `INFO`                       | Logging verbosity       |

### Plugin Settings

In Stash UI (**Settings > Plugins > Stash Auto Caption**):

- **service_url**: URL of web service (default: `http://auto-caption-web:8000`)

## Project Structure

```
auto-caption/
├── docker-compose.yml              # Orchestrates 3 services
├── .env.example                    # Environment template
├── CLAUDE.md                       # Complete implementation docs
├── README.md                       # This file
├── docs/
│   └── adr/                        # Architecture Decision Records
│
├── whisper-server/
│   ├── Dockerfile                  # Whisper AI container
│   ├── whisper_http_server.py     # Flask server with streaming
│   └── models/                     # Whisper models (auto-downloaded)
│
├── web-service/
│   ├── Dockerfile                  # FastAPI container
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 # API endpoints + task manager
│       ├── models.py               # Pydantic schemas
│       ├── transcription.py        # Whisper client
│       ├── translation.py          # LibreTranslate client
│       ├── task_manager.py         # Async task tracking
│       └── utils.py                # File operations
│
└── stash-auto-caption/
    ├── stash-auto-caption.yml      # Plugin config
    ├── js/
    │   ├── stash-auto-caption.js   # UI plugin (language detection, player)
    │   └── stashFunctions.js       # Utility functions
    └── gorpc/
        ├── main.go                 # Go RPC plugin
        ├── go.mod                  # Dependencies
        └── stash-auto-caption-rpc  # Compiled binary (Linux x86-64)
```

## Workflow

1. **Stash Plugin** detects foreign language tag on scene
2. **JavaScript** triggers Go RPC task via `runPluginTask()`
3. **Go RPC Plugin** calls web service `/auto-caption/start`
4. **Web Service** queues task in ThreadPoolExecutor
5. **Background Worker** extracts audio, calls Whisper server
6. **Whisper Server** transcribes with streaming progress
7. **Web Service** optionally translates, saves SRT file
8. **Go RPC Plugin** triggers Stash metadata scan via GraphQL
9. **Stash** indexes new subtitle file
10. **JavaScript** loads caption in video player

## Performance

### Transcription Speed

- Real-time factor: ~0.1x (10% of video duration)
- Example: 1-hour video = ~6 minutes transcription

### Resource Usage

- **RAM**: ~6GB (4GB Whisper + 2GB LibreTranslate)
- **Disk**: ~5GB (Whisper models + Docker images)
- **CPU**: High during transcription (benefits from multi-core)

### GPU Acceleration

For faster transcription, enable GPU:

1. Edit `whisper-server/whisper_http_server.py`:

   ```python
   model = WhisperModel(MODEL_SIZE, device="cuda", compute_type="float16")
   ```

2. Update `docker-compose.yml`:
   ```yaml
   whisper-server:
     runtime: nvidia
     environment:
       - NVIDIA_VISIBLE_DEVICES=all
   ```

## Troubleshooting

### Services Not Starting

```bash
# Check logs
docker-compose logs web-service
docker-compose logs whisper-server

# Check ports
netstat -tulpn | grep -E "2800|8000|5000"

# Restart services
docker-compose restart
```

### Plugin Not Appearing in Stash

```bash
# Verify binary is executable
chmod +x <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc

# Check Stash logs
docker logs stash | grep "auto-caption"

# Reload plugins in Stash UI
```

### Caption Generation Fails

```bash
# Test web service directly
curl -X POST http://localhost:8000/auto-caption/start \
  -H "Content-Type: application/json" \
  -d '{"video_path":"/data/test.mp4","language":"en"}'

# Check video file accessible
docker exec auto-caption-web-1 ls -la /data/test.mp4
```

### Progress Not Updating

```bash
# Check streaming is enabled
docker-compose logs whisper-server | grep "task_id"

# Verify web service consuming stream
docker-compose logs web-service | grep "progress"
```

## API Documentation

Interactive documentation available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Development

### Testing Locally

```bash
# Build services
docker-compose build

# Start in foreground
docker-compose up

# Run tests
docker-compose exec web-service pytest

# Access shell
docker-compose exec web-service bash
```

### Compiling Go Binary

```bash
cd stash-auto-caption/gorpc
GOOS=linux GOARCH=amd64 go build -o stash-auto-caption-rpc main.go
```

## Documentation

For complete implementation details, see [CLAUDE.md](CLAUDE.md):

- Architecture decisions and rationale
- API specifications with examples
- Troubleshooting guide
- Key lessons learned
- Testing procedures

For detailed architecture decisions, see [Architecture Decision Records (ADRs)](docs/adr/):

- [ADR 001: Whisper Over Vosk](docs/adr/001-whisper-over-vosk.md)
- [ADR 002: Dual Plugin Architecture](docs/adr/002-dual-plugin-architecture.md)
- [ADR 003: Streaming Progress Tracking](docs/adr/003-streaming-progress-tracking.md)
- [ADR 004: GraphQL Client Patterns](docs/adr/004-graphql-client-patterns.md)

## Branch Information

- **`main`**: Original Vosk-based implementation (deprecated)
- **`whisper-rpc`**: Current Whisper + RPC implementation (active)

## Credits

- Transcription: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- Translation: [LibreTranslate](https://libretranslate.com/)
- Stash Integration: [Stash](https://github.com/stashapp/stash)
- Implementation: Claude (Anthropic)

## Support

For issues and questions:

1. Check [CLAUDE.md](CLAUDE.md) for detailed documentation
2. Review Troubleshooting section above
3. Check service logs: `docker-compose logs`

## Future Enhancements

- GPU acceleration for faster transcription
- Batch processing for multiple scenes
- Web UI for service management
- Automatic language detection
- Support for VTT, ASS subtitle formats
- Speaker diarization
- WebSocket progress updates

## License

This project uses:

- **Whisper** - MIT License
- **LibreTranslate** - AGPL-3.0 License
- **FastAPI** - MIT License
- **Stash** - AGPL-3.0 License
