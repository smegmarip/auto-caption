# ADR 005: Batch Caption Generation for Foreign Language Scenes

**Status:** Implemented (Pending Testing)
**Date:** 2025-10-31
**Deciders:** Development Team
**Related ADRs:** [ADR 002: Dual Plugin Architecture](002-dual-plugin-architecture.md), [ADR 003: Streaming Progress Tracking](003-streaming-progress-tracking.md)

## Context

The auto-caption plugin currently generates captions one scene at a time when a user manually triggers the task or when the JavaScript plugin auto-detects a foreign language tag on scene load. For users with large libraries of foreign language content, there was no way to batch process all uncaptioned scenes without manually visiting each scene page or triggering each task individually.

**User Request:** Extend the plugin to run caption generation for all foreign language scenes that do not have subtitles, with proper progress tracking and error handling.

## Decision

We implemented a new **batch caption generation task** that:

1. **Queries Stash** for all scenes tagged with foreign language child tags
2. **Filters scenes** to identify those without existing captions (checks both metadata and filesystem)
3. **Queues individual tasks** via Stash's `RunPluginTask` mutation for each uncaptioned scene
4. **Leverages Stash's job queue** for automatic task management and progress tracking
5. **Supports language auto-detection** for edge cases where multiple language tags exist

### Architecture Choice: External Task Queueing

**Selected Approach:** Separate batch orchestrator task that queues individual caption generation tasks.

**Rejected Alternative:** Internal task runner that processes all scenes within a single job.

**Rationale:**
- **Leverages Stash's infrastructure:** Uses existing job queue, progress tracking, and error handling
- **Granular progress:** Users can see per-scene progress in the Jobs queue
- **Isolated failures:** One scene failing doesn't stop the batch
- **User control:** Can pause/cancel individual jobs
- **Non-blocking:** Doesn't hold up the job queue with a single massive task

## Implementation Details

### 1. Plugin Configuration

**File:** `stash-auto-caption.yml`

Added new task definition:
```yaml
tasks:
  - name: Generate Caption for Scene
    description: Generates subtitles for a scene using Whisper transcription
    defaultArgs:
      mode: generate
  - name: Generate Captions for All Foreign Language Scenes
    description: Generates subtitles for all foreign language scenes without captions
    defaultArgs:
      mode: generateBatch
```

**Task Type:** Domain-wide background task (appears in Stash's Tasks menu)

### 2. Go RPC Implementation

**File:** `stash-auto-caption/gorpc/main.go`

#### New Mode Handler

```go
switch mode {
case "generate":
    err = a.generateCaption(input)
case "generateBatch":
    err = a.generateBatchCaptions(input)
default:
    err = fmt.Errorf("unknown mode: %s", mode)
}
```

#### Core Function: `generateBatchCaptions()`

**Algorithm:**

```
1. Find "Foreign Language" parent tag via allTags query
2. Get all children (e.g., "Spanish Language", "Japanese Language")
3. Filter children to only supported languages (check LANG_DICT)
4. Query scenes with ANY of these language tags (FindScenes with tag filter)
5. For each scene:
   a. Check scene.captions metadata for existing captions
   b. Check filesystem for .srt file (e.g., video.en.srt)
   c. If no captions found, add to processing list
6. For each scene in processing list:
   a. Detect language from scene tags
   b. Queue individual task via RunPluginTask mutation
   c. Log success/failure
7. Return summary (X queued, Y failed)
```

**Key Functions:**

- **`findForeignLanguageTag()`** - Queries `allTags` and finds "Foreign Language" parent with children
- **`findScenesWithLanguageTags()`** - Executes `FindScenes` GraphQL query with tag filter
- **`sceneHasCaption()`** - Checks metadata (`scene.captions`) and filesystem (`.srt` file)
- **`detectSceneLanguage()`** - Maps scene's language tag to language code via `LANG_DICT`
- **`runPluginTaskForScene()`** - Executes `RunPluginTask` mutation to queue individual job

#### Language Detection Logic

```go
// Check scene tags against supported language tags
for _, sceneTag := range scene.Tags {
    for _, langTag := range supportedLangTags {
        if sceneTag.ID == langTag.ID {
            // Extract "Spanish" from "Spanish Language"
            langName := strings.TrimSuffix(langTag.Name, " Language")
            // Return "es" for "Spanish"
            return LANG_DICT[langName]
        }
    }
}
// If multiple languages or no match, return "" for auto-detect
return ""
```

#### Caption Detection Logic (Per User Requirements)

**Priority Order:**

1. **Check metadata:** `scene.captions` array and `scene.paths.caption` URL
2. **Check filesystem:** Look for `.en.srt` file next to video file
3. **Update tag consistency:** "Subtitled" tag updated by existing `generateCaption` function

```go
func (a *autoCaptionAPI) sceneHasCaption(scene *SceneForBatch) bool {
    // Check 1: Caption metadata exists
    if len(scene.Captions) > 0 && scene.Paths != nil && scene.Paths.Caption != nil {
        return true
    }

    // Check 2: .srt file exists on disk
    if len(scene.Files) > 0 {
        videoPath := scene.Files[0].Path
        srtPath := strings.TrimSuffix(videoPath, filepath.Ext(videoPath)) + ".en.srt"
        if _, err := os.Stat(srtPath); err == nil {
            return true
        }
    }

    return false
}
```

#### GraphQL Query Structure

**FindScenes with Tag Filter:**
```go
var query struct {
    FindScenes struct {
        Count  int             `graphql:"count"`
        Scenes []SceneForBatch `graphql:"scenes"`
    } `graphql:"findScenes(scene_filter: $scene_filter, filter: $filter)"`
}

sceneFilter := map[string]interface{}{
    "tags": map[string]interface{}{
        "value":    tagIDs,          // Array of language tag IDs
        "modifier": "INCLUDES",       // Match any of these tags
        "depth":    -1,               // Include all depths
    },
}

filter := map[string]interface{}{
    "per_page": 1000,  // Get up to 1000 scenes
}
```

**RunPluginTask Mutation:**
```go
var mutation struct {
    RunPluginTask graphql.String `graphql:"runPluginTask(plugin_id: $plugin_id, task_name: $task_name, args: $args)"`
}

args := []map[string]interface{}{
    {"key": "mode", "value": map[string]interface{}{"str": "generate"}},
    {"key": "scene_id", "value": map[string]interface{}{"str": sceneID}},
    {"key": "video_path", "value": map[string]interface{}{"str": videoPath}},
    {"key": "language", "value": map[string]interface{}{"str": language}},
    {"key": "translate_to", "value": map[string]interface{}{"str": "en"}},
    {"key": "service_url", "value": map[string]interface{}{"str": serviceURL}},
}
```

### 3. Optional Language Parameter (Auto-Detection)

**Problem:** When a scene has multiple foreign language tags (edge case), we need to either pick one or let Whisper auto-detect.

**Solution:** Made `language` parameter optional throughout the stack.

#### Modified Files

**`web-service/app/models.py`:**
```python
language: Optional[str] = Field(
    None,  # Changed from required to optional
    description="Language code for transcription. If not provided, Whisper will auto-detect.",
    examples=["en"]
)

@field_validator("language")
@classmethod
def validate_language(cls, v: Optional[str]) -> Optional[str]:
    if v is not None and v not in SUPPORTED_LANGUAGES:
        raise ValueError(...)
    return v
```

**`web-service/app/transcription.py`:**
```python
def transcribe_with_whisper(
    audio_path: str,
    language: Optional[str],  # Changed from str to Optional[str]
    whisper_server_url: str,
    ...
) -> Tuple[str, str, float]:
    # Prepare params - only include language if provided
    params = {'task': task}
    if language:
        params['language'] = language  # Omit if None
    if whisper_task_id:
        params['task_id'] = whisper_task_id
```

**`web-service/app/main.py`:**
```python
# Use detected language for subsequent operations
source_lang = detected_language if language is None else language

# Pass detected language to LibreTranslate
if translate_to and translate_to != 'en' and translate_to != source_lang:
    srt_content, translation_service = translate_srt(
        srt_content,
        source_lang,  # Use detected language
        translate_to,
        LIBRETRANSLATE_URL
    )
```

**Whisper Server:** Already supports `language=None` for auto-detection (no changes needed).

### 4. Language Dictionary

**File:** `gorpc/main.go`

```go
var LANG_DICT = map[string]string{
    "English":    "en",
    "Spanish":    "es",
    "French":     "fr",
    "German":     "de",
    "Italian":    "it",
    "Portuguese": "pt",
    "Russian":    "ru",
    "Dutch":      "nl",
    "Japanese":   "ja",
    "Chinese":    "zh",
    "Korean":     "ko",
    "Arabic":     "ar",
}
```

**Mapping Logic:** Tag name "Spanish Language" → "Spanish" → "es"

### 5. Type Definitions

**New Go Types:**

```go
// SceneForBatch - Lightweight scene representation
type SceneForBatch struct {
    ID       graphql.ID     `json:"id"`
    Title    *string        `json:"title"`
    Files    []VideoFile    `json:"files"`
    Tags     []TagFragment  `json:"tags"`
    Captions []CaptionData  `json:"captions"`
    Paths    *ScenePaths    `json:"paths"`
}

// VideoFile - Video file metadata
type VideoFile struct {
    Path     string  `json:"path"`
    Duration float64 `json:"duration"`
}

// CaptionData - Caption metadata
type CaptionData struct {
    LanguageCode string `json:"language_code"`
    CaptionType  string `json:"caption_type"`
}

// ScenePaths - File paths
type ScenePaths struct {
    Screenshot string  `json:"screenshot"`
    Caption    *string `json:"caption,omitempty"`
}

// TagWithChildren - Tag with child tags
type TagWithChildren struct {
    ID       graphql.ID    `json:"id"`
    Name     string        `json:"name"`
    Children []TagFragment `json:"children"`
}
```

## Workflow

### User Journey

```
1. User navigates to Tasks in Stash UI
2. Clicks "Generate Captions for All Foreign Language Scenes"
3. Task immediately returns with summary log:
   - "Found 23 scenes with foreign language tags"
   - "Filtered to 15 scenes without captions"
   - "Queued 15 scenes for caption generation"
   - "Scene X queued (language: es)"
   - "Scene Y queued (language: ja)"
   - "Batch processing complete: 15 tasks queued, 0 failed"
4. User monitors Jobs queue for individual scene progress
5. Each scene shows real-time progress (0-100%)
6. On completion, scene gets "Subtitled" tag
7. Caption appears in video player on next load
```

### System Flow

```
┌─────────────────────────────────────────────────────┐
│ User triggers "Generate Captions for All..."       │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Go RPC Plugin         │
         │ generateBatchCaptions │
         └───────────┬───────────┘
                     │
      ┌──────────────┼──────────────┐
      │              │              │
      ▼              ▼              ▼
  allTags      FindScenes    Check Filesystem
   Query        Query         (os.Stat)
      │              │              │
      └──────────────┼──────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Filter: No Captions   │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ For Each Scene:       │
         │ RunPluginTask         │
         │ (mode=generate)       │
         └───────────┬───────────┘
                     │
      ┌──────────────┼──────────────┐
      │              │              │
      ▼              ▼              ▼
  Job Queue    Job Queue    Job Queue
   (Scene 1)    (Scene 2)    (Scene 3)
      │              │              │
      └──────────────┼──────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Stash Processes       │
         │ One Job at a Time     │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ Caption Generated     │
         │ "Subtitled" Tag Added │
         └───────────────────────┘
```

## Error Handling

### Scene-Level Failures

**Logged but not fatal:**
- Scene has no files: "Scene X: No video files found, skipping"
- Language cannot be detected: "Scene X: Could not detect language, skipping"
- RunPluginTask fails: "Scene X: Failed to queue task: <error>"

**Result:** Other scenes continue processing, failed count incremented.

### Task-Level Failures

**Handled by existing `generateCaption` function:**
- Video file not found
- Audio extraction fails
- Whisper server unavailable
- Transcription timeout

**Result:** Individual job fails, visible in Jobs queue, other jobs continue.

### Batch-Level Failures

**Fatal errors (batch task fails):**
- "Foreign Language" tag not found
- No supported language tags found
- GraphQL query errors

**Result:** Batch task fails immediately with error message.

## Testing Plan

### Prerequisites

1. **Tag Setup:**
   - Create "Foreign Language" parent tag
   - Create child tags: "Spanish Language", "Japanese Language", "French Language"

2. **Test Scenes:**
   - Scene A: Spanish Language tag, no caption
   - Scene B: Japanese Language tag, has caption (skip)
   - Scene C: French Language tag, no caption
   - Scene D: English Language tag (not in Foreign Language parent, skip)
   - Scene E: Spanish Language + Japanese Language (multiple tags, auto-detect)

3. **File System:**
   - Scene B: Create `video.en.srt` file manually
   - Scene F: Has caption metadata but no file (edge case)

### Test Cases

#### TC1: Basic Batch Processing
**Given:** 3 scenes with foreign language tags, 1 already has caption
**When:** User triggers batch task
**Expected:** 2 tasks queued, 1 skipped, both complete successfully

#### TC2: Language Auto-Detection
**Given:** Scene has multiple language tags
**When:** Batch task processes scene
**Expected:** Language is empty, Whisper auto-detects, translation uses detected language

#### TC3: Caption Detection - Filesystem
**Given:** Scene has no caption metadata but `.srt` file exists on disk
**When:** Batch task processes scene
**Expected:** Scene skipped (caption detected via filesystem check)

#### TC4: Caption Detection - Metadata
**Given:** Scene has `captions` array with entries
**When:** Batch task processes scene
**Expected:** Scene skipped (caption detected via metadata)

#### TC5: Empty Library
**Given:** No scenes with foreign language tags
**When:** User triggers batch task
**Expected:** "Found 0 scenes" message, task completes immediately

#### TC6: All Scenes Already Captioned
**Given:** 10 scenes with foreign language tags, all have captions
**When:** User triggers batch task
**Expected:** "No scenes to process - all foreign language scenes already have captions!"

#### TC7: Individual Job Failure
**Given:** 5 scenes queued, 1 video file is corrupt
**When:** Jobs process
**Expected:** 4 jobs complete successfully, 1 job fails (visible in Jobs queue)

#### TC8: Missing Foreign Language Tag
**Given:** "Foreign Language" tag not configured in Stash
**When:** User triggers batch task
**Expected:** Task fails with error: "'Foreign Language' tag not found - please create it in Stash"

#### TC9: Progress Tracking
**Given:** Scene being processed
**When:** User views Jobs queue
**Expected:** Progress updates in real-time (0% → 50% → 100%)

#### TC10: Concurrent Execution
**Given:** User triggers batch task twice quickly
**When:** Both tasks run
**Expected:** Second task queues same scenes again (idempotency not enforced - user responsibility)

### Manual Testing Steps

```bash
# 1. Build Go binary
cd /Users/x/dev/resources/repo/auto-caption/stash-auto-caption/gorpc
GOOS=linux GOARCH=amd64 go build -o stash-auto-caption-rpc main.go
chmod +x stash-auto-caption-rpc

# 2. Restart services
cd /Users/x/dev/resources/repo/auto-caption
docker-compose down
docker-compose up -d

# 3. Reload plugin in Stash
# Stash UI → Settings → Plugins → Reload Plugins

# 4. Verify task appears
# Stash UI → Tasks → Look for "Generate Captions for All Foreign Language Scenes"

# 5. Check logs during execution
docker-compose logs -f web-service
docker-compose logs -f whisper-server
```

### Verification Checklist

- [ ] Task appears in Stash Tasks menu
- [ ] Task triggers without errors
- [ ] Log shows correct scene count ("Found X scenes")
- [ ] Log shows filtered count ("Filtered to Y scenes without captions")
- [ ] Individual jobs appear in Jobs queue
- [ ] Progress updates in real-time for each job
- [ ] Completed jobs show "Subtitled" tag added
- [ ] `.en.srt` files created next to video files
- [ ] Captions load in video player
- [ ] Failed jobs show error messages
- [ ] Scenes with existing captions are skipped

## Performance Considerations

### Scalability

**Query Performance:**
- `FindScenes` limited to 1000 scenes (`per_page: 1000`)
- For libraries >1000 foreign language scenes, pagination not implemented
- **Mitigation:** Document limit, implement pagination if needed

**Memory Usage:**
- All scene data loaded into memory during filtering
- ~1KB per scene × 1000 scenes = ~1MB memory
- **Mitigation:** Acceptable for current use case

**Job Queue:**
- Stash processes jobs sequentially by default
- 100 scenes × 5 min/scene = ~8 hours total processing time
- **Mitigation:** Users can adjust Stash's parallel job limit if desired

### Edge Cases

**Pagination Required:**
- If >1000 scenes, implement pagination in `findScenesWithLanguageTags()`
- Use `page` and `per_page` filter parameters

**Race Condition:**
- Two users trigger batch task simultaneously
- Both queue same scenes (duplicate work)
- **Mitigation:** Acceptable - Stash deduplicates if same job parameters

**Disk Space:**
- 1000 scenes × 50KB SRT = ~50MB disk space
- **Mitigation:** Negligible for modern systems

## Migration Notes

### Backwards Compatibility

**✅ No breaking changes:**
- Existing `generateCaption` mode unchanged
- JavaScript plugin unchanged (still auto-triggers on scene load)
- API endpoints unchanged (language parameter now optional, but still accepts explicit values)

### Deployment Steps

1. Update `stash-auto-caption.yml` (already done)
2. Update `gorpc/main.go` (already done)
3. Update `web-service` files (already done)
4. Rebuild Go binary (pending)
5. Restart Docker services
6. Reload Stash plugin
7. Test batch task

### Rollback Plan

If batch task causes issues:

1. Revert `stash-auto-caption.yml` to remove `generateBatch` task
2. Reload plugin
3. Individual caption generation still works (no changes to that flow)

## Future Enhancements

### Potential Improvements

1. **Pagination Support:** Handle libraries with >1000 foreign language scenes
2. **Resume Capability:** Track processed scenes, skip already-queued jobs
3. **Dry Run Mode:** Preview what would be processed without queuing tasks
4. **Filtering Options:** Allow user to filter by specific language, date range, studio
5. **Batch Progress:** Show overall batch progress (X of Y scenes completed) in addition to per-scene progress
6. **Retry Failed Scenes:** Add "Retry Failed Captions" task to re-process only failed jobs
7. **Scene Limit Parameter:** Allow user to specify max scenes to process (e.g., "process first 50")
8. **Priority Queue:** Allow user to prioritize certain scenes (e.g., most recent, most viewed)

### Code Optimizations

1. **Streaming Scene Processing:** Process scenes incrementally instead of loading all into memory
2. **Concurrent Task Queueing:** Queue multiple RunPluginTask mutations in parallel
3. **Caching:** Cache "Foreign Language" tag lookup across invocations
4. **Logging Levels:** Add debug/info/warn levels for better diagnostics

## References

- [ADR 002: Dual Plugin Architecture](002-dual-plugin-architecture.md) - Architecture decisions for Go RPC + JS split
- [ADR 003: Streaming Progress Tracking](003-streaming-progress-tracking.md) - Progress update implementation
- [ADR 004: GraphQL Client Patterns](004-graphql-client-patterns.md) - GraphQL query patterns
- [Stash Plugin Documentation](https://docs.stashapp.cc/in-app-manual/plugins/)
- [Stash GraphQL Schema](https://github.com/stashapp/stash/blob/master/graphql-server/schema/schema.graphql)
- [grouptags Plugin Example](https://github.com/stashapp/CommunityScripts/tree/master/plugins/grouptags) - Background task reference

## Status

**Current State:** Code implemented, pending build and testing

**Next Steps:**
1. Build Go RPC binary (`stash-auto-caption-rpc`)
2. Deploy to test environment
3. Execute test cases TC1-TC10
4. Document any issues discovered
5. Update CLAUDE.md with feature documentation

**Blockers:**
- Go build failing due to system temp directory permissions (workaround needed)

**Owner:** Development Team
**Last Updated:** 2025-10-31
