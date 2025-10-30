# Auto-Caption Service - Whisper + Stash RPC Implementation

## Project Overview

Automatic subtitle generation service for Stash using Whisper AI transcription. The service integrates with Stash via a dual-architecture approach: Go RPC plugin for ALL backend/stateful operations and JavaScript for UI interactions ONLY.

**Current Branch:** `whisper-rpc` (Whisper-based implementation)
**Main Branch:** `main` (original Vosk-based implementation - deprecated)
**Status:** Production Ready
**Repository:** https://github.com/yourusername/stash-auto-caption

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Stash instance running
- ~4GB disk space (Whisper model)

### Deployment

```bash
# 1. Clone and configure
git clone <repo-url> auto-caption
cd auto-caption
git checkout whisper-rpc
cp .env.example .env
# Edit .env: Set MEDIA_PATH=/path/to/media

# 2. Start services
docker-compose up -d

# 3. Install Stash plugin
cp -r stash-auto-caption <STASH_PLUGINS_DIR>/
chmod +x <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc

# 4. Reload plugins in Stash UI
# Settings > Plugins > Reload Plugins
```

### Usage

**Automatic (Recommended):**
1. Tag scene with foreign language (e.g., "Spanish Language")
2. Load scene in Stash
3. Plugin automatically generates captions
4. Monitor progress in Jobs queue
5. Caption loads in player when complete

**Manual:**
1. Scene page > Tasks > "Generate Caption for Scene"
2. Monitor Jobs queue
3. Refresh to see caption

---

## Architecture

### System Components

**Docker Compose Stack:**
1. **whisper-server** (Python/Flask) - Whisper AI transcription on port 2800
2. **web-service** (FastAPI) - Async task management on port 8000
3. **libretranslate** - Translation service on port 5000

**Stash Plugin:**
1. **Go RPC** (`gorpc/`) - Backend: HTTP client, GraphQL, tag management, metadata scans
2. **JavaScript** (`js/`) - UI only: language detection, job trigger, player updates

### Key Design Decisions

See detailed ADRs in [`docs/adr/`](docs/adr/):
- [ADR 001: Whisper Over Vosk](docs/adr/001-whisper-over-vosk.md)
- [ADR 002: Dual Plugin Architecture](docs/adr/002-dual-plugin-architecture.md)
- [ADR 003: Streaming Progress Tracking](docs/adr/003-streaming-progress-tracking.md)
- [ADR 004: GraphQL Client Patterns](docs/adr/004-graphql-client-patterns.md)

### Core Principles

1. **Stateless JavaScript**: No tag management or metadata scans - purely UI
2. **Stateful Go RPC**: All persistence operations (captions, tags, scans)
3. **No Duplication**: Functions moved from JS to Go, never copied
4. **Streaming Progress**: Real-time updates via JSON-lines format
5. **Type Safety**: GraphQL queries use proper `graphql.ID` types

---

## API Reference

### Web Service Endpoints

#### POST /auto-caption/start
Start caption generation task.

**Request:**
```json
{
  "video_path": "/data/video.mp4",
  "language": "es",
  "translate_to": "en"
}
```

**Response:**
```json
{
  "task_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "queued"
}
```

#### GET /auto-caption/status/{task_id}
Poll task status.

**Response:**
```json
{
  "task_id": "...",
  "status": "running",
  "progress": 0.45,
  "stage": "transcribing",
  "result": null
}
```

**Status Values:** `queued`, `running`, `completed`, `failed`
**Stage Values:** `extracting_audio`, `transcribing`, `translating`, `saving`

### Whisper Server Endpoints

#### POST /transcribe/srt?task_id={id}
Transcribe audio with streaming progress.

**Query Params:**
- `task_id` (optional): Enable streaming mode
- `language` (required): Source language code
- `task`: `transcribe` or `translate` (to English)

**Streaming Response (JSON-lines):**
```json
{"type": "progress", "progress": 0.25, "timestamp": 17.5, "duration": 70.0}
{"type": "complete", "srt_content": "...", "language": "en", ...}
```

---

## Configuration

### Environment Variables (.env)

```bash
# Services
WHISPER_SERVER_URL=http://whisper-server:2800
WHISPER_MODEL=large-v3
LIBRETRANSLATE_URL=http://libretranslate:5000

# Paths
MEDIA_PATH=/path/to/media

# Ports
WEB_SERVICE_PORT=8000
WHISPER_SERVER_PORT=2800
LIBRETRANSLATE_PORT=5000
```

### Plugin Settings (Stash UI)

**Settings > Plugins > Stash Auto Caption:**
- `serviceUrl`: Auto-Caption Service URL (leave empty for auto-detection)

Default: `http://auto-caption-web:8000`

---

## Supported Languages

Whisper supports 99+ languages with automatic detection:

**Primary:** English, Spanish, French, German, Italian, Portuguese, Russian, Japanese, Chinese, Korean, Dutch, Polish, Turkish, Swedish, Arabic, Hebrew, Hindi, Thai, Vietnamese

**Translation:**
- Whisper: Any language → English (during transcription)
- LibreTranslate: English → other languages

---

## Development

### Building Go RPC Binary

```bash
cd stash-auto-caption/gorpc
GOOS=linux GOARCH=amd64 go build -o stash-auto-caption-rpc main.go
```

**Target:** Linux x86-64 (for Unraid/Docker)

### Project Structure

```
auto-caption/
├── docker-compose.yml
├── .env
├── whisper-server/          # Whisper AI service
│   └── whisper_http_server.py
├── web-service/             # FastAPI service
│   ├── app/
│   │   ├── main.py
│   │   ├── transcription.py
│   │   └── task_manager.py
│   └── requirements.txt
├── stash-auto-caption/      # Stash plugin
│   ├── gorpc/
│   │   ├── main.go
│   │   ├── go.mod
│   │   └── stash-auto-caption-rpc
│   ├── js/
│   │   ├── stashFunctions.js
│   │   └── stash-auto-caption.js
│   └── stash-auto-caption.yml
└── docs/
    └── adr/                 # Architecture Decision Records
```

### GraphQL Patterns

When adding GraphQL queries/mutations:

1. Check schema: `stash/graphql/schema/schema.graphql`
2. Use `graphql.ID` for ID fields, not `graphql.String`
3. Create input structs with `json` tags
4. Match return types exactly
5. See [ADR 004](docs/adr/004-graphql-client-patterns.md) for patterns

**Example:**
```go
type SceneUpdateInput struct {
    ID     graphql.ID   `json:"id"`
    TagIds []graphql.ID `json:"tag_ids"`
}

var mutation struct {
    SceneUpdate struct {
        ID graphql.ID
    } `graphql:"sceneUpdate(input: $input)"`
}

input := SceneUpdateInput{
    ID:     graphql.ID(sceneID),
    TagIds: tagIDs,
}

variables := map[string]interface{}{
    "input": input,
}

err := client.Mutate(ctx, &mutation, variables)
```

---

## Troubleshooting

### Plugin Not Appearing

```bash
# Check binary format
file stash-auto-caption/gorpc/stash-auto-caption-rpc
# Expected: ELF 64-bit LSB executable, x86-64

# Make executable
chmod +x stash-auto-caption/gorpc/stash-auto-caption-rpc

# Reload plugins
# Stash UI: Settings > Plugins > Reload Plugins
```

### Caption Generation Fails

```bash
# Check web service logs
docker-compose logs web-service

# Check whisper server logs
docker-compose logs whisper-server

# Test web service
curl -X POST http://localhost:8000/auto-caption/start \
  -H "Content-Type: application/json" \
  -d '{"video_path":"/data/video.mp4","language":"es","translate_to":"en"}'
```

### Progress Not Updating

Check that streaming is enabled (requires `task_id` parameter).

### Caption Not Appearing

1. Wait for metadata scan job to complete
2. Manually refresh: Scene page > Edit > Scan
3. Caption must be in same directory as video
4. Filename format: `video.en.srt`

---

## Key Lessons

### Generator Pitfall
```python
# ❌ WRONG - Consumes entire generator
segments_list = list(segments)

# ✅ CORRECT - Process during iteration
for segment in segments:
    process(segment)
    yield_progress()
```

### GraphQL Types
```go
// ❌ WRONG - String for IDs
ID graphql.String

// ✅ CORRECT - Use graphql.ID
ID graphql.ID
```

### No Duplication
Functions must be **moved** from JavaScript to Go, never copied. Single source of truth.

---

## Future Enhancements

- [ ] GPU acceleration (CUDA support)
- [ ] Batch processing
- [ ] Web UI for monitoring
- [ ] Speaker diarization
- [ ] WebSocket progress updates
- [ ] Multi-language subtitle generation
- [ ] Integration with other transcription services

---

## References

- [Stash Plugin Documentation](https://docs.stashapp.cc/in-app-manual/plugins/)
- [Stash RPC Example](https://github.com/stashapp/stash/blob/master/pkg/plugin/examples/gorpc/main.go)
- [Whisper Model Card](https://github.com/openai/whisper/blob/main/model-card.md)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [hasura/go-graphql-client](https://github.com/hasura/go-graphql-client)

---

**Last Updated:** 2025-10-30
**Version:** 2.0.0 (whisper-rpc branch)
**Status:** Production Ready
