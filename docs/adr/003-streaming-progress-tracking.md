# ADR 003: Streaming Progress Tracking

**Status:** Accepted
**Date:** 2025-10-29
**Decision Makers:** User, Claude

## Context

Initial Whisper implementation showed progress jumping from 0.20 → 0.80, missing all intermediate updates during transcription.

## Problem

User feedback:
> "it looks like it jumped from 0.2 to 1.0. are you sure that you got the progress logic correct?"

### Root Cause

```python
# WRONG - line 97 in original whisper_http_server.py
segments_list = list(segments)  # Transcription happens HERE and blocks
```

The `list(segments)` call consumed the entire generator at once. By the time we iterated over `segments_list`, transcription was complete and we were reading cached results.

## Decision

Implement JSON-lines streaming during the first (and only) iteration of the generator, with state management for polling fallback.

## Solution Architecture

### Hybrid Approach:
1. **Streaming (Primary)**: Real-time progress via JSON-lines format
2. **Polling (Fallback)**: Status endpoints for resilience

### Key Insight:
> "segments are generators - by the time your new progress code runs, the transcription will be over"

**Critical Pattern:**
```python
# ✅ CORRECT - Process during iteration
for segment in segments:  # Transcription happens DURING this loop
    process(segment)
    yield_progress(segment.end / total_duration)
```

## Implementation

### Whisper Server Changes

**1. Task State Management:**
```python
task_states = {}  # {task_id: {status, progress, result, error, ...}}
task_lock = Lock()
```

**2. Streaming Generator:**
```python
def stream_transcribe_srt(segments, info, task_id):
    """Yield progress during transcription."""
    create_task(task_id, duration=info.duration)

    for i, segment in enumerate(segments, start=1):
        # Build SRT during iteration
        srt_lines.append(format_segment(segment))

        # Calculate and yield progress DURING iteration
        progress = segment.end / info.duration
        update_task_progress(task_id, progress, segment.end)

        # Yield JSON-lines format
        yield json.dumps({
            "type": "progress",
            "progress": progress,
            "timestamp": segment.end,
            "duration": info.duration
        }) + "\n"

    # Final result
    complete_task(task_id, result)
    yield json.dumps({"type": "complete", **result}) + "\n"
```

**3. Endpoint:**
```python
@app.route('/transcribe/srt', methods=['POST'])
def transcribe_srt():
    task_id = request.args.get('task_id', None)

    if task_id:
        return Response(
            stream_transcribe_srt(segments, info, task_id),
            mimetype='application/x-ndjson'
        )
    else:
        # Legacy mode for backwards compatibility
        return jsonify(complete_result)
```

### Web Service Changes

**Consume Stream:**
```python
for line in response.iter_lines(decode_unicode=True):
    data = json.loads(line)

    if data['type'] == 'progress':
        # Map to overall task progress
        task_progress = 0.10 + (data['progress'] * 0.65)
        task_manager.update_progress(task_id, task_progress)

    elif data['type'] == 'complete':
        result = data
        break
```

## Progress Allocation

**Total: 100%**
- **10%**: Audio extraction (0.00 → 0.10)
- **65% OR 85%**: Whisper transcription
  - 65% if transcription only (0.10 → 0.75)
  - 85% if Whisper translates to English (0.10 → 0.95)
- **0% OR 20%**: LibreTranslate translation
  - 0% if Whisper translated or no translation
  - 20% for non-English targets (0.75 → 0.95)
- **5%**: Save SRT file (0.95 → 1.00)

## Results

**Before Fix:**
```
0.20 → 0.80 (single jump)
```

**After Fix:**
```
0.35 → 0.41 → 0.47 → 0.53 → 0.59 → 0.66 → 0.72 → 0.75 → 1.0
```

Smooth, real-time progress updates throughout transcription! ✅

## Consequences

### Positive:
- Real-time progress visibility
- Better user experience
- Resilient with polling fallback
- Backwards compatible (legacy mode)

### Negative:
- More complex implementation
- Requires task state management
- Must handle connection drops

## Key Lessons

### Generator Pattern Pitfall:
```python
# ❌ WRONG - Consumes generator before processing
segments_list = list(segments)
for segment in segments_list:
    process(segment)

# ✅ CORRECT - Process during iteration
for segment in segments:
    process(segment)
    yield_progress()
```

## References

- [Flask Streaming Documentation](https://flask.palletsprojects.com/en/2.3.x/patterns/streaming/)
- [JSON-lines Format](https://jsonlines.org/)
