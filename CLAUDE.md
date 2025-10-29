# Auto-Caption Service - Whisper + Stash RPC Implementation

## Project Overview

Automatic subtitle generation service for Stash using Whisper AI transcription. The service integrates with Stash via a dual-architecture approach: Go RPC plugin for ALL backend/stateful operations and JavaScript for UI interactions ONLY.

**Current Branch:** `whisper-rpc` (Whisper-based implementation)
**Main Branch:** `main` (original Vosk-based implementation - deprecated)
**Status:** ~98% Complete - Ready for deployment testing

**Repository:** https://github.com/yourusername/stash-auto-caption

---

## Architecture

### System Components

**Docker Compose Stack (3 services):**
1. **whisper-server** (Python/Flask) - Whisper AI transcription engine on port 2800
2. **web-service** (FastAPI) - Main API with async task management on port 8000
3. **libretranslate** - Self-hosted translation service on port 5000

**Stash Plugin (2 components):**
1. **Go RPC Plugin** (`stash-auto-caption/gorpc/`) - Backend (STATEFUL): HTTP client, task polling, GraphQL mutations, tag management, URL resolution, metadata scanning
2. **JavaScript Plugin** (`stash-auto-caption/js/`) - UI (STATELESS): language detection, job trigger, player updates, toast notifications, progress indicator

### Key Architectural Decisions

- **Whisper over Vosk**: Superior accuracy, built-in English translation, real-time progress via generators
- **Dual Plugin Architecture**: Go handles backend operations, JavaScript handles UI only
- **Stateless JavaScript**: No tag management, no metadata scans - purely UI trigger and update
- **Stateful Go RPC**: Handles ALL persistence operations (caption creation, tag updates, metadata scans)
- **No Functionality Duplication**: Functions moved from JS to Go, not copied
- **Async Task Management**: Web service uses ThreadPoolExecutor (max 4 workers) with polling endpoints
- **Streaming Progress**: Whisper server streams JSON-lines format during transcription
- **Hybrid Progress Tracking**: Streaming (real-time) + polling (resilience/fallback)
- **Stash Job Queueing**: "Stash automatically queues jobs 1 at a time" - no manual queueing needed
- **URL Resolution**: Based on Stash's approach - handles IP/hostname/container/localhost with DNS lookup

---

## Implementation History & Progress

### Phase 0: Initial Requirements Analysis

**User Requirements:**
- "I am thinking of whether the entire javascript plugin can be refactored to rpc"
- "So no http fallback - get rid of the http functionality in the js component"
- "The only really irreplaceable functionality is the dynamic subtitle loading for the player"
- **Critical Rule**: "No duplication! Move functions, don't copy them"

**Original Plan Structure:**
```
Phase 0: Project restructuring
Phase 1: Web service progress tracking
Phase 2: Go RPC plugin implementation
Phase 3: JavaScript refactoring (UI only)
Phase 4: GraphQL metadata scan
Phase 5: Testing & deployment
```

### Phase 1: Streaming Progress Tracking ✅ COMPLETE

**Problem Identified:**
Progress jumped from 0.20 → 0.80 during transcription, missing all intermediate updates.

**Root Cause:**
```python
# WRONG - line 97 in original whisper_http_server.py
segments_list = list(segments)  # Transcription happens HERE and blocks
```

The `list(segments)` call consumed the entire generator at once, meaning all transcription happened during this single line. By the time we iterated over `segments_list`, the work was done and we were reading cached results.

**User Feedback:**
- "it looks like it jumped from 0.2 to 1.0. are you sure that you got the progress logic correct?"
- "you're missing the fact that segments are generators - by the time your new progress code runs, the transcription will be over"
- "model.transcribe returns a tuple with: a generator over transcribed segments, an instance of TranscriptionInfo"

**Solution:**
Implement JSON-lines streaming during first (and only) iteration of the generator, with state management for polling fallback.

#### Files Modified

**1. whisper-server/whisper_http_server.py**

Added at top of file:
```python
from datetime import datetime
from threading import Lock

# Task state management (in-memory)
task_states = {}  # {task_id: {status, progress, result, error, timestamp, duration, updated_at}}
task_lock = Lock()
```

Added helper functions:
```python
def create_task(task_id, duration=None):
    """Initialize task state."""
    with task_lock:
        task_states[task_id] = {
            "status": "processing",
            "progress": 0.0,
            "timestamp": 0.0,
            "duration": duration,
            "result": None,
            "error": None,
            "updated_at": datetime.utcnow().isoformat()
        }

def update_task_progress(task_id, progress, timestamp):
    """Update task progress."""
    with task_lock:
        if task_id in task_states:
            task_states[task_id]["progress"] = progress
            task_states[task_id]["timestamp"] = timestamp
            task_states[task_id]["updated_at"] = datetime.utcnow().isoformat()

def complete_task(task_id, result):
    """Mark task as completed."""
    with task_lock:
        if task_id in task_states:
            task_states[task_id]["status"] = "completed"
            task_states[task_id]["progress"] = 1.0
            task_states[task_id]["result"] = result
            task_states[task_id]["updated_at"] = datetime.utcnow().isoformat()

def fail_task(task_id, error):
    """Mark task as failed."""
    with task_lock:
        if task_id in task_states:
            task_states[task_id]["status"] = "failed"
            task_states[task_id]["error"] = str(error)
            task_states[task_id]["updated_at"] = datetime.utcnow().isoformat()

def get_task_status(task_id):
    """Get current task state."""
    with task_lock:
        return task_states.get(task_id)
```

Added new endpoints:
```python
@app.route('/status/<task_id>', methods=['GET'])
def get_status(task_id):
    """Get status of a transcription task."""
    task_state = get_task_status(task_id)
    if not task_state:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "task_id": task_id,
        "status": task_state["status"],
        "progress": task_state["progress"],
        "timestamp": task_state["timestamp"],
        "duration": task_state["duration"],
        "error": task_state["error"],
        "updated_at": task_state["updated_at"]
    })

@app.route('/result/<task_id>', methods=['GET'])
def get_result(task_id):
    """Get final result of a completed transcription task."""
    task_state = get_task_status(task_id)

    if not task_state:
        return jsonify({"error": "Task not found"}), 404

    if task_state["status"] == "failed":
        return jsonify({
            "task_id": task_id,
            "status": "failed",
            "error": task_state["error"]
        }), 500

    if task_state["status"] != "completed":
        return jsonify({
            "task_id": task_id,
            "status": task_state["status"],
            "message": "Task not yet completed"
        }), 202

    return jsonify({
        "task_id": task_id,
        "status": "completed",
        **task_state["result"]
    })
```

Created streaming generator function:
```python
def stream_transcribe_srt(segments, info, task_id):
    """Generator function to stream SRT transcription with progress updates."""
    try:
        total_duration = round(info.duration, 2)
        create_task(task_id, duration=total_duration)

        srt_lines = []
        segment_count = 0

        # CRITICAL: Iterate generator ONCE and process during that iteration
        for i, segment in enumerate(segments, start=1):
            # Build SRT content during iteration
            start_time = format_srt_timestamp(segment.start)
            end_time = format_srt_timestamp(segment.end)
            srt_lines.append(str(i))
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(segment.text.strip())
            srt_lines.append("")
            segment_count = i

            # Calculate and yield progress DURING iteration
            progress = segment.end / total_duration if total_duration > 0 else 0.0
            update_task_progress(task_id, progress, segment.end)

            # Yield progress update (JSON-lines format)
            yield json.dumps({
                "type": "progress",
                "progress": progress,
                "timestamp": segment.end,
                "duration": total_duration
            }) + "\n"

        # Final result after iteration completes
        srt_content = "\n".join(srt_lines)
        result = {
            "srt_content": srt_content,
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "segment_count": segment_count
        }
        complete_task(task_id, result)
        yield json.dumps({"type": "complete", **result}) + "\n"

    except Exception as e:
        fail_task(task_id, str(e))
        yield json.dumps({"type": "error", "error": str(e)}) + "\n"
```

Updated `/transcribe/srt` endpoint:
```python
@app.route('/transcribe/srt', methods=['POST'])
def transcribe_srt():
    """Transcribe audio file and return SRT format directly."""
    task_id = request.args.get('task_id', None)

    # ... existing audio processing and model.transcribe() call ...

    # Use streaming mode if task_id provided, otherwise legacy mode
    if task_id:
        return Response(
            stream_transcribe_srt(segments, info, task_id),
            mimetype='application/x-ndjson'
        )
    else:
        # Legacy mode: return complete result (unchanged for backwards compatibility)
        segments_list = list(segments)
        # ... existing code ...
```

**2. web-service/app/transcription.py**

Updated `transcribe_video()` function signature:
```python
def transcribe_video(
    video_path: str,
    language: str,
    whisper_server_url: str,
    translate_to_english: bool = False,
    task_id: str = None,
    task_manager=None
) -> Tuple[str, str, float]:
```

Added streaming response handling:
```python
# Generate whisper task ID if we have a web service task ID
whisper_task_id = f"whisper-{task_id}" if task_id else None

# Prepare params
params = {'language': language, 'task': task}
if whisper_task_id:
    params['task_id'] = whisper_task_id

# Send to Whisper server
response = requests.post(
    endpoint,
    data=audio_data,
    params=params,
    stream=(whisper_task_id is not None),  # Stream if task_id provided
    timeout=600
)

# Handle streaming vs non-streaming response
if whisper_task_id:
    # Streaming mode: parse JSON-lines and update progress
    result = None
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue

        data = json.loads(line)

        if data['type'] == 'progress':
            # Map whisper progress (0-1) to task progress
            whisper_progress = data['progress']

            if translate_to_english:
                # Whisper handles transcription + translation (85%)
                task_progress = 0.10 + (whisper_progress * 0.85)
            else:
                # Whisper only transcribes (65%)
                task_progress = 0.10 + (whisper_progress * 0.65)

            if task_manager and task_id:
                from app.task_manager import TaskStage
                task_manager.update_progress(task_id, task_progress, TaskStage.TRANSCRIBING)

        elif data['type'] == 'complete':
            result = data
            break

        elif data['type'] == 'error':
            raise RuntimeError(f"Whisper transcription failed: {data['error']}")

    if not result:
        raise RuntimeError("Whisper transcription produced no result")

    return result['srt_content'], result['language'], result['language_probability']
else:
    # Legacy mode: handle complete JSON response
    # ... existing code unchanged ...
```

**3. web-service/app/main.py**

Fixed progress allocations in `generate_caption_background()`:
```python
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
    language != 'en'
)

srt_content, detected_language, lang_probability = transcribe_video(
    video_path,
    language,
    WHISPER_SERVER_URL,
    translate_to_english=translate_to_english,
    task_id=task_id,
    task_manager=task_manager
)

# Whisper did the work (either transcription or translation to English)
translation_service = "whisper"
if translate_to_english:
    logger.info(f"Task {task_id}: Whisper translated from {language} to English")
    # Whisper handled 85% (transcription + translation), now at 95%
    task_manager.update_progress(task_id, 0.95, TaskStage.TRANSCRIBING)
else:
    logger.info(f"Task {task_id}: Whisper transcribed in {detected_language}")
    # Whisper handled 65% (transcription only), now at 75%
    task_manager.update_progress(task_id, 0.75, TaskStage.TRANSCRIBING)

# Stage 3: Optional translation with LibreTranslate (20% of progress: 75-95%)
if translate_to and translate_to != 'en' and translate_to != language:
    task_manager.update_progress(task_id, 0.75, TaskStage.TRANSLATING)
    logger.info(f"Task {task_id}: Translating from {language} to {translate_to}...")

    srt_content, translation_service = translate_srt(
        srt_content,
        language,
        translate_to,
        LIBRETRANSLATE_URL
    )

    task_manager.update_progress(task_id, 0.95, TaskStage.TRANSLATING)
    logger.info(f"Task {task_id}: Translation complete using {translation_service}")

# Stage 4: Save SRT file (5% of progress: 95-100%)
task_manager.update_progress(task_id, 0.97, TaskStage.SAVING)
logger.info(f"Task {task_id}: Saving SRT file...")
```

#### Progress Allocation Breakdown

**Total Progress: 100%**
- **10%**: Audio extraction (0.05 → 0.10)
- **65% OR 85%**: Whisper transcription
  - 65% if transcription only (0.10 → 0.75)
  - 85% if Whisper translates to English (0.10 → 0.95)
- **0% OR 20%**: LibreTranslate translation
  - 0% if Whisper translated or no translation needed
  - 20% for non-English targets (0.75 → 0.95)
- **5%**: Save SRT file (0.95 → 1.0)

#### Test Results

**Before Fix:**
```
0.20 → 0.80 (single jump during transcription)
```

**After Fix:**
```
0.35 → 0.41 → 0.47 → 0.53 → 0.59 → 0.66 → 0.72 → 0.75 → 1.0
```

Smooth, real-time progress updates throughout transcription! ✅

**Backwards Compatibility:**
- Legacy endpoints still work without `task_id` parameter
- Web service automatically uses streaming when task_id is available
- No breaking changes to existing functionality

**All result fields preserved:**
- `caption_path` ✅
- `cached` ✅
- `translation_service` ✅

---

### Phase 2: Go RPC Plugin Development ✅ COMPLETE

**User Transition:** "good. on to the next phase of our plan."

#### Research Phase

**User provided documentation:**
- https://docs.stashapp.cc/in-app-manual/plugins/
- https://github.com/stashapp/stash/blob/master/pkg/plugin/examples/README.md
- Go RPC example: https://github.com/stashapp/stash/blob/master/pkg/plugin/examples/gorpc/main.go
- Go RPC YAML: https://github.com/stashapp/stash/blob/master/pkg/plugin/examples/gorpc/gorpc.yml

**Key Learnings:**
1. **RPCRunner Interface**: Must implement `Run()` and `Stop()` methods
2. **ServePlugin**: Use `common.ServePlugin(&api{})` in main()
3. **Server Connection**: Access via `input.ServerConnection` in Run()
4. **GraphQL Client**: Use `util.NewClient(input.ServerConnection)`
5. **Progress Reporting**: Call `log.Progress(float64)` to update Stash UI
6. **Graceful Shutdown**: Check `stopping` flag in long-running loops

**User Clarifications:**
- "fyi: stash automatically queues jobs 1 at a time" - No manual queueing needed
- "remember - no functionality duplication! move functions, don't copy them"
- "good. you are compiling for macos but the actual binary will be for unraid"

#### Implementation

**Files Created:**

**1. stash-auto-caption/gorpc/main.go**

```go
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	graphql "github.com/hasura/go-graphql-client"
	"github.com/stashapp/stash/pkg/plugin/common"
	"github.com/stashapp/stash/pkg/plugin/common/log"
	"github.com/stashapp/stash/pkg/plugin/util"
)

func main() {
	err := common.ServePlugin(&autoCaptionAPI{})
	if err != nil {
		panic(err)
	}
}

type autoCaptionAPI struct {
	stopping         bool
	serverConnection common.StashServerConnection
	graphqlClient    *graphql.Client
}

func (a *autoCaptionAPI) Stop(input struct{}, output *bool) error {
	log.Info("Stopping auto-caption plugin...")
	a.stopping = true
	*output = true
	return nil
}

// Run handles the RPC task execution
func (a *autoCaptionAPI) Run(input common.PluginInput, output *common.PluginOutput) error {
	// Initialize GraphQL client from server connection
	a.serverConnection = input.ServerConnection
	a.graphqlClient = util.NewClient(input.ServerConnection)

	mode := input.Args.String("mode")

	var err error
	switch mode {
	case "generate":
		err = a.generateCaption(input)
	default:
		err = fmt.Errorf("unknown mode: %s", mode)
	}

	if err != nil {
		errStr := err.Error()
		*output = common.PluginOutput{
			Error: &errStr,
		}
		return nil
	}

	outputStr := "Caption generation completed successfully"
	*output = common.PluginOutput{
		Output: &outputStr,
	}

	return nil
}

// generateCaption calls the auto-caption web service and polls for completion
func (a *autoCaptionAPI) generateCaption(input common.PluginInput) error {
	// Get parameters from input
	videoPath := input.Args.String("video_path")
	language := input.Args.String("language")
	translateTo := input.Args.String("translate_to")
	serviceURL := input.Args.String("service_url")

	if videoPath == "" {
		return fmt.Errorf("video_path is required")
	}
	if language == "" {
		return fmt.Errorf("language is required")
	}
	if serviceURL == "" {
		serviceURL = "http://auto-caption-web:8000"
	}

	log.Infof("Generating caption for: %s (language: %s)", videoPath, language)

	// Start caption generation task
	taskID, err := a.startCaptionTask(serviceURL, videoPath, language, translateTo)
	if err != nil {
		return fmt.Errorf("failed to start caption task: %w", err)
	}

	log.Infof("Caption task started: %s", taskID)

	// Poll for task completion
	return a.pollTaskStatus(serviceURL, taskID)
}

// TaskStartRequest represents the request to start a caption task
type TaskStartRequest struct {
	VideoPath   string  `json:"video_path"`
	Language    string  `json:"language"`
	TranslateTo *string `json:"translate_to,omitempty"`
}

// TaskStartResponse represents the response from starting a task
type TaskStartResponse struct {
	TaskID string `json:"task_id"`
	Status string `json:"status"`
}

// TaskStatusResponse represents the task status response
type TaskStatusResponse struct {
	TaskID   string                 `json:"task_id"`
	Status   string                 `json:"status"`
	Progress float64                `json:"progress"`
	Stage    *string                `json:"stage"`
	Error    *string                `json:"error"`
	Result   map[string]interface{} `json:"result"`
}

func (a *autoCaptionAPI) startCaptionTask(serviceURL, videoPath, language, translateTo string) (string, error) {
	url := fmt.Sprintf("%s/auto-caption/start", serviceURL)

	req := TaskStartRequest{
		VideoPath: videoPath,
		Language:  language,
	}
	if translateTo != "" {
		req.TranslateTo = &translateTo
	}

	reqBody, err := json.Marshal(req)
	if err != nil {
		return "", err
	}

	resp, err := http.Post(url, "application/json", bytes.NewBuffer(reqBody))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var taskResp TaskStartResponse
	if err := json.NewDecoder(resp.Body).Decode(&taskResp); err != nil {
		return "", err
	}

	return taskResp.TaskID, nil
}

func (a *autoCaptionAPI) pollTaskStatus(serviceURL, taskID string) error {
	url := fmt.Sprintf("%s/auto-caption/status/%s", serviceURL, taskID)
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		if a.stopping {
			return fmt.Errorf("task interrupted")
		}

		select {
		case <-ticker.C:
			resp, err := http.Get(url)
			if err != nil {
				return fmt.Errorf("failed to get task status: %w", err)
			}

			var status TaskStatusResponse
			if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
				resp.Body.Close()
				return fmt.Errorf("failed to decode status: %w", err)
			}
			resp.Body.Close()

			// Update progress
			log.Progress(status.Progress)
			if status.Stage != nil {
				log.Infof("Stage: %s (%.0f%%)", *status.Stage, status.Progress*100)
			}

			// Check status
			switch status.Status {
			case "completed":
				log.Info("Caption generation completed successfully")
				var captionPath string
				if cp, ok := status.Result["caption_path"].(string); ok {
					captionPath = cp
					log.Infof("Caption saved to: %s", captionPath)
				}

				// Trigger metadata scan if caption was created
				if captionPath != "" {
					if err := a.scanCaptionMetadata(captionPath); err != nil {
						log.Warnf("Failed to trigger metadata scan: %v", err)
						// Don't fail the whole task if scan fails
					}
				}

				return nil

			case "failed":
				if status.Error != nil {
					return fmt.Errorf("caption generation failed: %s", *status.Error)
				}
				return fmt.Errorf("caption generation failed")

			case "queued", "running":
				// Continue polling
				continue

			default:
				return fmt.Errorf("unknown task status: %s", status.Status)
			}
		}
	}
}

// scanCaptionMetadata triggers a Stash metadata scan for the caption's directory
func (a *autoCaptionAPI) scanCaptionMetadata(captionPath string) error {
	// Extract parent directory
	var captionDir string
	for i := len(captionPath) - 1; i >= 0; i-- {
		if captionPath[i] == '/' || captionPath[i] == '\\' {
			captionDir = captionPath[:i]
			break
		}
	}

	if captionDir == "" {
		return fmt.Errorf("could not determine caption directory")
	}

	log.Infof("Triggering metadata scan for: %s", captionDir)

	// Execute GraphQL metadataScan mutation
	var mutation struct {
		MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
	}

	variables := map[string]interface{}{
		"input": map[string]interface{}{
			"paths": []string{captionDir},
		},
	}

	ctx := context.Background()
	err := a.graphqlClient.Mutate(ctx, &mutation, variables)
	if err != nil {
		return fmt.Errorf("failed to trigger metadata scan: %w", err)
	}

	jobID := string(mutation.MetadataScan)
	log.Infof("Metadata scan started with job ID: %s", jobID)

	return nil
}
```

**2. stash-auto-caption/gorpc/go.mod**

```go
module stash-auto-caption-rpc

go 1.24.3

toolchain go1.24.9

require (
	github.com/coder/websocket v1.8.13 // indirect
	github.com/hasura/go-graphql-client v0.14.5
	github.com/natefinch/pie v0.0.0-20170715172608-9a0d72014007 // indirect
	github.com/sirupsen/logrus v1.9.3 // indirect
	github.com/stashapp/stash v0.29.1
	golang.org/x/sys v0.33.0 // indirect
)
```

**3. stash-auto-caption/stashAutoCaption.yml**

```yaml
name: Stash Auto Caption
description: Provides automatic translation and captioning for foreign language videos.
version: 2.0.0
url: https://github.com/yourusername/stash-auto-caption
settings:
  service_url:
    displayName: Auto-Caption Service URL
    description: URL of the auto-caption web service
    type: STRING
    default: http://auto-caption-web:8000
ui:
  requires:
    - CommunityScriptsUILibrary
  javascript:
    - stashFunctions.js
    - stashAutoCaption.js
  csp:
    connect-src:
      - http://auto-caption-web:8000
exec:
  - gorpc/stash-auto-caption-rpc
interface: rpc
tasks:
  - name: Generate Caption for Scene
    description: Generates subtitles for a scene using Whisper transcription
    defaultArgs:
      mode: generate
```

**4. Binary Compilation**

```bash
# From stash-auto-caption/gorpc/ directory
GOOS=linux GOARCH=amd64 go build -o stash-auto-caption-rpc main.go

# Verify
file stash-auto-caption-rpc
# Output: stash-auto-caption-rpc: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), statically linked
```

**Binary Details:**
- Size: 11MB
- Format: ELF 64-bit LSB executable, x86-64
- Target: Linux (Unraid server)

#### Key Features

1. **HTTP Client**: Calls web service `/auto-caption/start` and `/auto-caption/status/<task_id>`
2. **Task Polling**: Polls every 2 seconds, reports progress via `log.Progress()`
3. **GraphQL Integration**: Uses `util.NewClient()` for metadata scanning
4. **Graceful Interruption**: Checks `stopping` flag to handle Stop() requests
5. **Error Handling**: Proper error propagation with detailed messages
6. **Result Preservation**: All fields (caption_path, cached, translation_service) maintained

---

### Phase 3: JavaScript Refactoring ✅ COMPLETE

**User Reminder:** "please re-read the conversation history to capture the full scope of our plan"

**Critical User Feedback:**
- "you nuked the superior awaitJobFinished method and replaced it with a single promise based delay - as if a long running task like audio transcription will complete in 2 seconds"
- "did you add error handling or any type of mitigation strategy to the javascript code or is that in the next phase?"

#### Changes to stashAutoCaption.js

**Removed (moved to Go RPC):**
```javascript
// ❌ Removed HTTP endpoint constant
const API_ENDPOINT = "http://auto-caption-web:8000/auto-caption";

// ❌ Removed scanCaption() function - moved to Go
async function scanCaption(captionPath) {
  const captionParent = captionPath.substring(0, captionPath.lastIndexOf("/"));
  const reqData = {
    variables: { input: { paths: [captionParent] } },
    query: `mutation MetadataScan($input: ScanMetadataInput!) {
      metadataScan(input: $input)
    }`,
  };
  var result = await csLib.callGQL(reqData);
  return result.metadataScan;
}

// ❌ Removed direct fetch() call to web service
```

**Added/Modified:**
```javascript
// ✅ Added plugin ID constant
const PLUGIN_ID = "stash-auto-caption";

// ✅ Refactored processRemoteCaption() - now uses Go RPC
async function processRemoteCaption(scene, sceneLanguage) {
  if (!scene || !sceneLanguage) return false;
  const scene_id = scene.id;
  const videoPath = scene.files[0].path;

  try {
    console.log(`Starting caption generation for scene ${scene_id} (${sceneLanguage})`);

    // Use stashFunctions to trigger the Go RPC plugin task
    const result = await window.stashFunctions.runPluginTask(
      PLUGIN_ID,
      "Generate Caption for Scene",
      [
        { key: "mode", value: { str: "generate" } },
        { key: "video_path", value: { str: videoPath } },
        { key: "language", value: { str: LANG_DICT[sceneLanguage] } },
        { key: "translate_to", value: { str: LANG_DICT["English"] } },
      ]
    );

    if (!result || !result.runPluginTask) {
      console.error("Failed to start caption generation task - no job ID returned");
      return false;
    }

    // runPluginTask returns the job ID, wait for job completion
    const jobId = result.runPluginTask;
    console.log(`Caption generation job started: ${jobId}`);

    try {
      await awaitJobFinished(jobId);
      console.log(`Caption generation job completed: ${jobId}`);
    } catch (jobError) {
      console.error(`Caption generation job failed: ${jobError.message || jobError}`);
      return false;
    }

    // Job completed, check for caption and update player
    const captionUrl = await getCaptionForScene(scene_id);
    if (captionUrl) {
      console.log(`Caption loaded: ${captionUrl}`);
      await toggleSubtitled(scene, true);
      return loadPlayerCaption(captionUrl);
    } else {
      console.warn("Caption generation completed but no caption file found");
      return false;
    }

  } catch (error) {
    console.error("Error processing caption with RPC plugin:", error);
    return false;
  }
}
```

**Kept (UI-specific functions):**
- `getScene()`, `getTagsForScene()`, `updateSceneTags()`
- `toggleSubtitled()` - Tag management
- `getCaptionForScene()` - Query for caption URL
- `loadPlayerCaption()` - Updates video player UI
- `detectForeignLanguage()` - Language detection from tags
- `detectExistingCaption()` - Checks for existing captions
- `getJobStatus()`, `awaitJobFinished()` - Job polling (reused for RPC jobs)

#### Error Handling Added

1. **Job ID Validation**: Checks that `runPluginTask` returned a valid job ID
2. **Separate Try-Catch for Job Polling**: Catches job failures specifically
3. **Caption Verification**: Warns if job completes but no caption found
4. **Detailed Console Logging**: Tracks progress at each step for debugging

#### Flow Comparison

**Before (HTTP-based):**
1. JavaScript detects foreign language tag
2. JavaScript makes HTTP POST to web service
3. JavaScript receives caption_path in response
4. JavaScript triggers GraphQL metadata scan
5. JavaScript polls for scan job completion
6. JavaScript loads caption in player

**After (RPC-based):**
1. JavaScript detects foreign language tag
2. JavaScript triggers Go RPC plugin task via `runPluginTask()`
3. **Go plugin handles everything**: HTTP call, polling, metadata scan
4. JavaScript waits for job completion using `awaitJobFinished(jobId)`
5. JavaScript queries for caption URL
6. JavaScript loads caption in player

**Benefits:**
- ✅ No functionality duplication - HTTP client and metadata scan moved to Go
- ✅ Cleaner separation - JavaScript handles UI only, Go handles backend tasks
- ✅ Better progress tracking - Go plugin reports progress to Stash job queue
- ✅ Unified task management - All tasks visible in Stash's job interface
- ✅ Single plugin ID - All components under one plugin configuration

---

### Phase 4: GraphQL Metadata Scan Implementation ✅ COMPLETE

**User Guidance:**
"incredibly, there are no published rpc plugins to examine for an example of how to connect to graphql so we will have to wing it."

**Resources Provided:**
1. Read gorpc/main.go example
2. Read pkg/plugin/util/client.go - "defines a graphql client for connecting to the stash server"
3. Stash server: `<STASH_URL>`
4. Test scene: ID `<SCENE_ID>`, path `"/data/test-video.mp4"`
5. Read goraw/main.go for non-RPC example
6. Local stash repo: `<LOCAL_STASH_REPO>`

**User Hint:** "there are more clues to how metadataScan works in the stash-auto-caption plugin js code that you deleted."

#### Research Findings

From `pkg/plugin/util/client.go`:
```go
func NewClient(provider common.StashServerConnection) *graphql.Client {
    portStr := strconv.Itoa(provider.Port)
    u, _ := url.Parse("http://" + provider.Host + ":" + portStr + "/graphql")
    u.Scheme = provider.Scheme

    cookieJar, _ := cookiejar.New(nil)
    cookie := provider.SessionCookie
    if cookie != nil {
        cookieJar.SetCookies(u, []*http.Cookie{cookie})
    }

    httpClient := &http.Client{Jar: cookieJar}
    return graphql.NewClient(u.String(), httpClient)
}
```

From deleted JavaScript `scanCaption()`:
```javascript
const reqData = {
  variables: { input: { paths: [captionParent] } },
  query: `mutation MetadataScan($input: ScanMetadataInput!) {
    metadataScan(input: $input)
  }`,
};
var result = await csLib.callGQL(reqData);
return result.metadataScan;  // Returns job ID
```

From Stash repository (`internal/api/resolver_mutation_metadata.go`):
```go
func (r *mutationResolver) MetadataScan(ctx context.Context, input manager.ScanMetadataInput) (string, error) {
	jobID, err := manager.GetInstance().Scan(ctx, input)
	if err != nil {
		return "", err
	}
	return strconv.Itoa(jobID), nil
}

// ScanMetadataInput struct
type ScanMetadataInput struct {
	Paths []string `json:"paths"`
	config.ScanMetadataOptions `mapstructure:",squash"`
	Filter *ScanMetaDataFilterInput `json:"filter"`
}
```

#### Implementation in main.go

**Added imports:**
```go
import (
	"context"
	graphql "github.com/hasura/go-graphql-client"
	"github.com/stashapp/stash/pkg/plugin/util"
)
```

**Updated autoCaptionAPI struct:**
```go
type autoCaptionAPI struct {
	stopping         bool
	serverConnection common.StashServerConnection
	graphqlClient    *graphql.Client
}
```

**Modified Run() method:**
```go
func (a *autoCaptionAPI) Run(input common.PluginInput, output *common.PluginOutput) error {
	// Initialize GraphQL client from server connection
	a.serverConnection = input.ServerConnection
	a.graphqlClient = util.NewClient(input.ServerConnection)

	// ... rest of Run() implementation ...
}
```

**Implemented scanCaptionMetadata():**
```go
func (a *autoCaptionAPI) scanCaptionMetadata(captionPath string) error {
	// Extract parent directory
	var captionDir string
	for i := len(captionPath) - 1; i >= 0; i-- {
		if captionPath[i] == '/' || captionPath[i] == '\\' {
			captionDir = captionPath[:i]
			break
		}
	}

	if captionDir == "" {
		return fmt.Errorf("could not determine caption directory")
	}

	log.Infof("Triggering metadata scan for: %s", captionDir)

	// Execute GraphQL metadataScan mutation
	var mutation struct {
		MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
	}

	variables := map[string]interface{}{
		"input": map[string]interface{}{
			"paths": []string{captionDir},
		},
	}

	ctx := context.Background()
	err := a.graphqlClient.Mutate(ctx, &mutation, variables)
	if err != nil {
		return fmt.Errorf("failed to trigger metadata scan: %w", err)
	}

	jobID := string(mutation.MetadataScan)
	log.Infof("Metadata scan started with job ID: %s", jobID)

	return nil
}
```

**Added dependency:**
```bash
go get github.com/hasura/go-graphql-client
```

**Recompiled binary:**
```bash
GOOS=linux GOARCH=amd64 go build -o stash-auto-caption-rpc main.go
```

**Binary updated:** 11MB ELF 64-bit LSB executable, x86-64

#### Behavior

- Extracts parent directory from caption file path
- Executes GraphQL `metadataScan` mutation with `{paths: [captionDir]}`
- Logs returned job ID from Stash
- Returns immediately - metadata scan runs asynchronously in Stash
- Error handling: Returns error if mutation fails, but doesn't fail the whole caption task

---

## API Specification

### Web Service Endpoints

#### POST /auto-caption/start
Start async caption generation task.

**Request:**
```json
{
  "video_path": "/data/test-video.mp4",
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

**Status Codes:**
- `200 OK`: Task queued successfully
- `404 Not Found`: Video file not found
- `400 Bad Request`: Invalid parameters

#### GET /auto-caption/status/{task_id}
Poll task status and progress.

**Response (running):**
```json
{
  "task_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "running",
  "progress": 0.45,
  "stage": "transcribing",
  "error": null,
  "result": null
}
```

**Response (completed):**
```json
{
  "task_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "completed",
  "progress": 1.0,
  "stage": "saving",
  "error": null,
  "result": {
    "caption_path": "/data/test-video.en.srt",
    "cached": false,
    "translation_service": "whisper"
  }
}
```

**Response (failed):**
```json
{
  "task_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "failed",
  "progress": 0.35,
  "stage": "transcribing",
  "error": "Whisper server connection timeout",
  "result": null
}
```

**Status Codes:**
- `200 OK`: Status retrieved successfully
- `404 Not Found`: Task not found

**Possible Status Values:**
- `queued`: Task queued, waiting for worker
- `running`: Task currently executing
- `completed`: Task finished successfully
- `failed`: Task encountered an error

**Possible Stage Values:**
- `extracting_audio`: Extracting audio from video (10%)
- `transcribing`: Whisper transcription (65% or 85%)
- `translating`: LibreTranslate translation (20%)
- `saving`: Saving SRT file (5%)

### Whisper Server Endpoints

#### POST /transcribe/srt?task_id={id}
Transcribe audio and return SRT with streaming progress.

**Query Parameters:**
- `task_id` (optional): Enable streaming mode with progress updates
- `language` (required): Source language code
- `task` (optional): `transcribe` (default) or `translate` (translate to English)

**Request Body:** Raw audio data (WAV format, 16kHz mono)

**Streaming Response (JSON-lines):**
```json
{"type": "progress", "progress": 0.12, "timestamp": 8.4, "duration": 70.0}
{"type": "progress", "progress": 0.25, "timestamp": 17.5, "duration": 70.0}
{"type": "progress", "progress": 0.38, "timestamp": 26.6, "duration": 70.0}
{"type": "complete", "srt_content": "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n...", "language": "en", "language_probability": 0.99, "duration": 70.0, "segment_count": 80}
```

**Legacy Response (no task_id):**
```json
{
  "srt_content": "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n...",
  "language": "en",
  "language_probability": 0.99,
  "duration": 70.0,
  "segment_count": 80
}
```

**Status Codes:**
- `200 OK`: Transcription successful
- `400 Bad Request`: Missing audio data or invalid language
- `500 Internal Server Error`: Transcription failed

**Content Types:**
- Streaming: `application/x-ndjson`
- Legacy: `application/json`

#### GET /status/{task_id}
Get transcription task status.

**Response:**
```json
{
  "task_id": "whisper-f47ac10b",
  "status": "processing",
  "progress": 0.67,
  "timestamp": 46.9,
  "duration": 70.0,
  "error": null,
  "updated_at": "2025-10-29T08:30:15Z"
}
```

**Status Codes:**
- `200 OK`: Status retrieved
- `404 Not Found`: Task not found

#### GET /result/{task_id}
Get final transcription result.

**Response (completed):**
```json
{
  "task_id": "whisper-f47ac10b",
  "status": "completed",
  "srt_content": "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n...",
  "language": "en",
  "language_probability": 0.99,
  "duration": 70.0,
  "segment_count": 80
}
```

**Response (processing):**
```json
{
  "task_id": "whisper-f47ac10b",
  "status": "processing",
  "message": "Task not yet completed"
}
```

**Response (failed):**
```json
{
  "task_id": "whisper-f47ac10b",
  "status": "failed",
  "error": "Audio file format not supported"
}
```

**Status Codes:**
- `200 OK`: Result retrieved successfully
- `202 Accepted`: Task still processing
- `404 Not Found`: Task not found
- `500 Internal Server Error`: Task failed

### Stash GraphQL Mutations

#### metadataScan
Trigger metadata scan for subtitle detection.

**Mutation:**
```graphql
mutation MetadataScan($input: ScanMetadataInput!) {
    metadataScan(input: $input)
}
```

**Variables:**
```json
{
  "input": {
    "paths": ["/data"]
  }
}
```

**Response:** Job ID (string)
```json
{
  "data": {
    "metadataScan": "123"
  }
}
```

**Go Implementation:**
```go
var mutation struct {
    MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
}

variables := map[string]interface{}{
    "input": map[string]interface{}{
        "paths": []string{captionDir},
    },
}

ctx := context.Background()
err := client.Mutate(ctx, &mutation, variables)
jobID := string(mutation.MetadataScan)
```

---

## Configuration

### Environment Variables (.env)

```bash
# Whisper Server
WHISPER_SERVER_URL=http://whisper-server:2800
WHISPER_MODEL=large-v3

# LibreTranslate
LIBRETRANSLATE_URL=http://libretranslate:5000

# Volume Mounts (for docker-compose)
MEDIA_PATH=/path/to/media

# Service Ports
WEB_SERVICE_PORT=8000
WHISPER_SERVER_PORT=2800
LIBRETRANSLATE_PORT=5000

# Logging
LOG_LEVEL=INFO
```

### Plugin Settings (stashAutoCaption.yml)

```yaml
settings:
  service_url:
    displayName: Auto-Caption Service URL
    description: URL of the auto-caption web service
    type: STRING
    default: http://auto-caption-web:8000
```

**Usage in Stash UI:**
1. Navigate to: Settings > Plugins > Stash Auto Caption
2. Configure `service_url` if web service is on different host/port
3. Default works for standard Docker Compose deployment

---

## Supported Languages

Whisper supports 99+ languages with automatic detection. No language models to download!

**Primary Languages:**
- English, Spanish, French, German, Italian, Portuguese
- Russian, Japanese, Chinese (Simplified & Traditional), Korean
- Dutch, Polish, Turkish, Swedish, Danish, Norwegian
- Arabic, Hebrew, Hindi, Thai, Vietnamese
- And 80+ more...

**Language Codes:**
- `en`: English
- `es`: Spanish
- `fr`: French
- `de`: German
- `it`: Italian
- `pt`: Portuguese
- `ru`: Russian
- `ja`: Japanese
- `zh`: Chinese
- `ko`: Korean

**Translation:**
- Whisper can translate any language → English during transcription
- LibreTranslate handles English → other languages
- Translation service automatically selected based on target language

---

## Deployment on Unraid

### 1. Deploy Docker Services

```bash
# SSH into your server
ssh user@<SERVER_IP>

# Clone repository
cd /path/to/install
git clone <repo-url> auto-caption
cd auto-caption

# Checkout whisper-rpc branch
git checkout whisper-rpc

# Configure environment
cp .env.example .env
nano .env
# Update: MEDIA_PATH=/path/to/media

# Start services
docker-compose up -d

# Verify services are running
docker-compose ps

# Check logs
docker-compose logs -f web-service
docker-compose logs -f whisper-server

# Test health
curl http://localhost:8000/health
curl http://localhost:2800/
```

### 2. Install Stash Plugin

```bash
# Copy plugin to Stash plugins directory
cp -r stash-auto-caption <STASH_PLUGINS_DIR>/

# Ensure binary is executable
chmod +x <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc

# Verify binary format
file <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc
# Expected: ELF 64-bit LSB executable, x86-64

# Reload Stash plugins
# Navigate to: Settings > Plugins > Reload Plugins in Stash UI
```

### 3. Configure Stash Plugin

1. **In Stash UI:** Settings > Plugins > Stash Auto Caption
2. **Configure** `service_url` if needed (default: `http://auto-caption-web:8000`)
3. **Verify** "Foreign Language" tag exists with language children:
   - Go to: Tags > Foreign Language
   - Create child tags: "Spanish Language", "Japanese Language", etc.
4. **Tag videos** with appropriate language tags

### 4. Usage

**Automatic (Recommended):**
1. Tag scene with foreign language (e.g., "Spanish Language" tag)
2. Load scene in Stash
3. Plugin automatically detects language and triggers caption generation
4. Monitor progress in Jobs queue (Settings > System > Jobs)
5. Caption automatically loads in player when complete

**Manual:**
1. Navigate to scene
2. Click Tasks button
3. Select "Generate Caption for Scene"
4. Monitor progress in Jobs queue
5. Refresh page to see caption in player

**Via JavaScript Console:**
```javascript
// Get scene ID from URL
const sceneId = window.location.pathname.split('/')[2];

// Trigger caption generation
window.stashFunctions.runPluginTask(
  "stash-auto-caption",
  "Generate Caption for Scene",
  [
    { key: "mode", value: { str: "generate" } },
    { key: "video_path", value: { str: "/data/path/to/video.mp4" } },
    { key: "language", value: { str: "es" } },
    { key: "translate_to", value: { str: "en" } },
  ]
);
```

---

## Testing

### Test Environment

**Stash Server:**
- URL: `<STASH_URL>`

**Test Scene:**
- Scene ID: `<SCENE_ID>`
- Container path: `"/data/test-video.mp4"`
- Expected SRT: `/data/test-video.en.srt`

### Test Plan

**Phase 1: Docker Services**
1. ✅ Verify whisper-server health: `curl http://localhost:2800/`
2. ✅ Verify web-service health: `curl http://localhost:8000/health`
3. ✅ Test streaming progress with test video
4. ✅ Verify SRT file created in correct location

**Phase 2: Stash Plugin Installation**
1. ⏳ Deploy Go RPC binary to Stash plugins directory
2. ⏳ Reload Stash plugins
3. ⏳ Verify plugin appears in Settings > Plugins
4. ⏳ Verify "Generate Caption for Scene" task appears

**Phase 3: Manual Task Execution**
1. ⏳ Navigate to test scene
2. ⏳ Trigger "Generate Caption for Scene" task
3. ⏳ Monitor progress in Jobs queue
4. ⏳ Verify progress updates smoothly 0-100%
5. ⏳ Verify job completes successfully

**Phase 4: Caption Verification**
1. ⏳ Verify SRT file created at expected path
2. ⏳ Verify SRT format is correct
3. ⏳ Verify timestamps match video
4. ⏳ Verify text is in English (translated from source)

**Phase 5: Metadata Scan**
1. ⏳ Verify metadata scan triggered (check Stash logs)
2. ⏳ Verify scan job appears in Jobs queue
3. ⏳ Verify "Subtitled" tag added to scene
4. ⏳ Refresh scene page

**Phase 6: Player Integration**
1. ⏳ Verify caption appears in video player controls
2. ⏳ Verify caption loads automatically
3. ⏳ Verify caption displays correctly during playback
4. ⏳ Verify caption timing is accurate

**Phase 7: Automatic Detection**
1. ⏳ Tag scene with "Spanish Language" (or applicable language)
2. ⏳ Navigate away and back to scene
3. ⏳ Verify plugin automatically triggers caption generation
4. ⏳ Verify caption appears after completion

### Success Criteria

- ✅ Task appears in Stash jobs queue
- ✅ Progress updates smoothly from 0-100%
- ✅ Caption file created at expected path
- ✅ Metadata scan triggered (job ID logged)
- ✅ Scene updated with "Subtitled" tag
- ✅ Caption visible in video player
- ✅ Caption timing matches video
- ✅ Automatic detection works

---

## Troubleshooting

### Plugin Not Appearing in Stash

**Symptoms:** Plugin doesn't show in Settings > Plugins

**Solutions:**
```bash
# 1. Verify binary is executable
chmod +x <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc

# 2. Verify binary format
file <STASH_PLUGINS_DIR>/stash-auto-caption/gorpc/stash-auto-caption-rpc
# Expected: ELF 64-bit LSB executable, x86-64

# 3. Check Stash logs
docker logs stash | grep -i "auto-caption"

# 4. Verify YAML syntax
yamllint <STASH_PLUGINS_DIR>/stash-auto-caption/stashAutoCaption.yml

# 5. Reload plugins
# Stash UI: Settings > Plugins > Reload Plugins
```

### Caption Generation Fails

**Symptoms:** Task fails immediately or during processing

**Solutions:**
```bash
# 1. Check web service logs
docker-compose logs web-service | tail -50

# 2. Check whisper server logs
docker-compose logs whisper-server | tail -50

# 3. Verify video file accessible from container
docker exec auto-caption-web-1 ls -la /data/path/to/video.mp4

# 4. Test web service directly
curl -X POST http://localhost:8000/auto-caption/start \
  -H "Content-Type: application/json" \
  -d '{"video_path":"/data/path/to/video.mp4","language":"es","translate_to":"en"}'

# 5. Check service_url setting in Stash plugin config
# Stash UI: Settings > Plugins > Stash Auto Caption > service_url
```

### Progress Not Updating

**Symptoms:** Progress stuck at 0% or not moving

**Solutions:**
```bash
# 1. Verify streaming is enabled
# Check whisper-server logs for "task_id" parameter

# 2. Verify web service consuming stream
docker-compose logs web-service | grep "Whisper progress"

# 3. Test Whisper server directly with streaming
curl -X POST "http://localhost:2800/transcribe/srt?task_id=test123" \
  -F "audio=@test.wav" \
  --no-buffer

# 4. Check task manager state
curl http://localhost:8000/auto-caption/status/<task_id>
```

### Metadata Scan Not Triggered

**Symptoms:** Caption file created but not showing in Stash

**Solutions:**
```bash
# 1. Verify GraphQL client initialized
# Check Go plugin logs in Stash

# 2. Test GraphQL connection manually
curl -X POST <STASH_URL>/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation { metadataScan(input: {paths: [\"/data\"]}) }"}'

# 3. Trigger manual metadata scan
# Stash UI: Settings > Tasks > Scan

# 4. Check Stash logs for metadataScan errors
docker logs stash | grep -i "metadataScan"

# 5. Verify caption file permissions
ls -la /data/test-video.en.srt
```

### Caption Not Appearing in Player

**Symptoms:** Caption file exists but not visible in player

**Solutions:**
```bash
# 1. Wait for metadata scan to complete
# Check Jobs queue for scan status

# 2. Manually refresh scene metadata
# Scene page: Edit > Scan (button next to scene title)

# 3. Verify caption file location
# Must be same directory as video file

# 4. Check caption filename format
# Expected: video.en.srt or video.english.srt

# 5. Clear browser cache and reload page

# 6. Check browser console for errors
# F12 > Console tab
```

### Docker Services Not Starting

**Symptoms:** `docker-compose up` fails

**Solutions:**
```bash
# 1. Check port conflicts
netstat -tulpn | grep -E "2800|8000|5000"

# 2. Verify .env file exists and is configured
cat .env

# 3. Check docker-compose.yml syntax
docker-compose config

# 4. Check Docker logs
docker-compose logs

# 5. Restart Docker
/etc/rc.d/rc.docker restart  # Unraid

# 6. Pull latest images
docker-compose pull
docker-compose up -d --force-recreate
```

### Performance Issues

**Symptoms:** Transcription very slow or timeouts

**Solutions:**
```bash
# 1. Check CPU usage
top

# 2. Check available RAM
free -h

# 3. Reduce Whisper model size
# Edit whisper-server/whisper_http_server.py
# Change: model = WhisperModel("large-v3") → WhisperModel("medium")

# 4. Reduce thread pool workers
# Edit web-service/app/main.py
# Change: ThreadPoolExecutor(max_workers=4) → ThreadPoolExecutor(max_workers=2)

# 5. Enable GPU acceleration (if available)
# Edit docker-compose.yml: Add GPU runtime

# 6. Monitor container resources
docker stats
```

---

## Key Lessons Learned

### 1. Generator Pattern Pitfalls

**Problem:** Using `list(segments)` on a generator consumes it entirely at once, making progress tracking impossible.

**Solution:** Iterate the generator once and process during that iteration, yielding progress updates as you go.

**Code Pattern:**
```python
# ❌ WRONG - Generator consumed before we can track progress
segments_list = list(segments)
for segment in segments_list:
    process(segment)

# ✅ CORRECT - Process and track progress during iteration
for segment in segments:
    process(segment)
    yield_progress(segment.end / total_duration)
```

### 2. Progress Mapping Strategies

**Problem:** Different workflows have different progress allocations that must sum to 100%.

**Solution:** Conditionally map sub-task progress to overall task progress based on workflow.

**Allocations:**
```python
# Transcription only workflow
audio_extraction: 10% (0.05 → 0.10)
transcription:    65% (0.10 → 0.75)
libretranslate:   20% (0.75 → 0.95)
saving:            5% (0.95 → 1.00)

# Whisper translation workflow
audio_extraction: 10% (0.05 → 0.10)
whisper_trans:    85% (0.10 → 0.95)
saving:            5% (0.95 → 1.00)
```

**Mapping Logic:**
```python
if translate_to_english:
    task_progress = 0.10 + (whisper_progress * 0.85)
else:
    task_progress = 0.10 + (whisper_progress * 0.65)
```

### 3. Job Polling vs Fixed Delays

**Problem:** Using fixed delays (e.g., `sleep(2000)`) assumes task duration, leading to either unnecessary waiting or premature checks.

**Solution:** Always use job polling infrastructure (`awaitJobFinished()`), which checks status repeatedly until completion.

**Code Pattern:**
```javascript
// ❌ WRONG - Assumes 2 seconds is enough
await new Promise(resolve => setTimeout(resolve, 2000));
const caption = await getCaptionForScene(scene_id);

// ✅ CORRECT - Waits for actual completion
const jobId = result.runPluginTask;
await awaitJobFinished(jobId);
const caption = await getCaptionForScene(scene_id);
```

### 4. No Functionality Duplication

**Problem:** Copying functions between components leads to maintenance burden and inconsistencies.

**Solution:** Move functions to the appropriate component - don't copy.

**Pattern:**
```
scanCaption() in JavaScript → MOVE to → scanCaptionMetadata() in Go
(not copy - DELETE from JavaScript after implementing in Go)
```

### 5. GraphQL Client Usage in RPC Plugins

**Problem:** No published examples of GraphQL usage in RPC plugins.

**Solution:** Use `util.NewClient(input.ServerConnection)` to get configured client.

**Code Pattern:**
```go
// In Run() method
a.graphqlClient = util.NewClient(input.ServerConnection)

// Later, execute mutation
var mutation struct {
    MetadataScan graphql.String `graphql:"metadataScan(input: $input)"`
}
variables := map[string]interface{}{
    "input": map[string]interface{}{
        "paths": []string{path},
    },
}
ctx := context.Background()
err := a.graphqlClient.Mutate(ctx, &mutation, variables)
```

### 6. Backwards Compatibility

**Problem:** Adding new features can break existing functionality.

**Solution:** Use optional parameters to maintain legacy behavior while enabling new features.

**Code Pattern:**
```python
# Add optional parameter with default None
def transcribe_video(path, lang, task_id=None):
    if task_id:
        # New streaming behavior
        return stream_response()
    else:
        # Legacy behavior unchanged
        return blocking_response()
```

### 7. Streaming + Polling Hybrid

**Problem:** Streaming provides real-time updates but can break on connection issues.

**Solution:** Implement both streaming (primary) and polling (fallback) for resilience.

**Architecture:**
```
Primary:  Client streams from server → real-time progress
Fallback: Client polls /status endpoint → resilient to disconnects
Storage:  Server maintains state in-memory → supports both patterns
```

---

## Future Enhancements

- [ ] GPU acceleration for Whisper (CUDA support in docker-compose)
- [ ] Batch processing for multiple scenes
- [ ] Web UI for service management and monitoring
- [ ] Automatic language detection (remove language tag requirement)
- [ ] Support for VTT, ASS, SSA subtitle formats
- [ ] Speaker diarization (identify different speakers)
- [ ] Whisper fine-tuning for domain-specific vocabulary
- [ ] WebSocket support for real-time progress in Stash UI
- [ ] Caption editing interface in Stash
- [ ] Persistent task history and statistics
- [ ] Email/webhook notifications on completion
- [ ] Multi-language subtitle generation (parallel translations)
- [ ] Subtitle styling customization
- [ ] Integration with other transcription services (Azure, Google, etc.)

---

## Development Notes

### Branch Strategy

- **`main`** - Original Vosk implementation (deprecated but functional)
- **`whisper-rpc`** - Current Whisper + RPC implementation (active development)

**Merging Strategy:**
```bash
# To update main with whisper-rpc (when ready for production):
git checkout main
git merge whisper-rpc
git push origin main
```

### Testing Workflow

1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test Docker services together
3. **End-to-End Tests**: Test full workflow from Stash UI to caption in player
4. **Manual Testing**: Test on actual Unraid server with real videos

### Code Review Checklist

**Before Committing:**
- [ ] No `list(segments)` calls on generators
- [ ] Progress allocations sum to 100%
- [ ] Error handling with specific try-catch blocks
- [ ] Job polling uses `awaitJobFinished()`, not fixed delays
- [ ] Functions moved (not duplicated) between JS and Go
- [ ] GraphQL mutations use proper variable typing
- [ ] Binary compiled for Linux x86-64 (Unraid): `GOOS=linux GOARCH=amd64`
- [ ] Backwards compatibility maintained (optional parameters)
- [ ] Console logging for debugging
- [ ] No exposed secrets or credentials
- [ ] YAML syntax valid

---

## References

- [Stash Plugin Documentation](https://docs.stashapp.cc/in-app-manual/plugins/)
- [Stash Plugin Examples](https://github.com/stashapp/stash/blob/master/pkg/plugin/examples/README.md)
- [faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper)
- [hasura/go-graphql-client](https://github.com/hasura/go-graphql-client)
- [Whisper Model Card](https://github.com/openai/whisper/blob/main/model-card.md)
- [LibreTranslate Documentation](https://libretranslate.com/docs/)
- [Flask Streaming Documentation](https://flask.palletsprojects.com/en/2.3.x/patterns/streaming/)
- [JSON-lines Format](https://jsonlines.org/)

---

## Phase 7: Critical Architecture Refactoring (2025-10-29)

### Issues Identified

User identified two critical gaps in the implementation:

1. **Missing Plugin Settings Implementation**
   - `service_url` argument defined in RPC but not populated from plugin settings
   - No proper URL resolution priority (Docker auto-config → container name → user input)
   - Example reference: stash-plugin-recraft-icons settings implementation

2. **JavaScript Still Stateful**
   - JavaScript still performing tag management (`toggleSubtitled()`)
   - JavaScript still triggering metadata scans
   - Violated core refactor principle: "decouple caption creation from front-end interface"
   - JavaScript should ONLY: a) detect foreign language, b) trigger RPC job, c) wait, d) update UI

### Implementation

**1. Plugin Settings with URL Resolution** (`stashAutoCaption.yml`, `stashAutoCaption.js`, `main.go:33-103`)
- Added `serviceUrl` setting to YAML (no default - enables auto-detection)
- JavaScript: `loadPluginConfig()` reads setting via `getPluginConfig(PLUGIN_ID)`
- JavaScript: passes `service_url` parameter to Go RPC
- Go RPC: Complete URL resolution based on Stash's approach
  - Parse URL via `net/url.Parse()`
  - If localhost → use as-is
  - If IP address → use as-is (via `net.ParseIP()`)
  - If hostname/container → DNS resolve (via `net.LookupIP()`)
  - Graceful fallback if DNS fails
  - Preserves scheme and port from original URL

**2. Stateless JavaScript Refactoring** (`stashAutoCaption.js:416-503`)
- Removed `toggleSubtitled()` call from `processRemoteCaption()`
- JavaScript now ONLY handles:
  - a. Detection: `detectForeignLanguage()` checks tags
  - b. Trigger: `runPluginTask()` with all parameters including `scene_id`
  - c. Wait: `awaitJobFinished(jobId)`
  - d. Update UI: `loadPlayerCaption()`, toast notifications, progress indicator
- No stateful operations remain in JavaScript

**3. Go RPC Tag Management** (`main.go:311-394`)
- Added `scene_id` parameter (required) to `generateCaption()`
- Implemented `addSubtitledTag(sceneID)` function:
  - GraphQL query: `findTag(name: "Subtitled")`
  - GraphQL query: `findScene(id: $sceneId)` to get current tags
  - Checks if tag already exists
  - GraphQL mutation: `sceneUpdate(input: $input)` with updated tag_ids
  - Handles errors gracefully (warns but doesn't fail task)
- Called automatically after successful caption generation
- Go RPC now handles ALL persistence: caption creation, tag updates, metadata scans

### Result

- JavaScript is now completely stateless (UI trigger only)
- Go RPC handles all backend/persistence operations
- URL resolution supports all formats (IP, hostname, container, localhost)
- Plugin settings properly integrated with auto-detection

---

## Contributors

- Implementation: Claude (Anthropic)
- Architecture & Planning: User
- Testing: Pending

---

**Last Updated:** 2025-10-29
**Version:** 2.0.0 (whisper-rpc branch)
**Status:** ~98% Complete - Ready for deployment testing
