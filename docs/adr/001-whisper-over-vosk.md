# ADR 001: Whisper Over Vosk for Transcription

**Status:** Accepted
**Date:** 2025-10-29
**Decision Makers:** User, Claude

## Context

The original implementation used Vosk for speech transcription. We needed to evaluate whether Whisper AI would provide better results for automatic caption generation.

## Decision

We decided to replace Vosk with Whisper AI (via faster-whisper) as the transcription engine.

## Rationale

### Advantages of Whisper:
1. **Superior Accuracy**: Whisper provides significantly better transcription quality across multiple languages
2. **Built-in English Translation**: Whisper can directly translate any language to English during transcription
3. **Real-time Progress**: Whisper returns a generator that yields segments, enabling true streaming progress
4. **No Language Models**: Whisper supports 99+ languages without downloading separate models
5. **Active Development**: OpenAI maintains and improves Whisper regularly

### Disadvantages of Vosk:
1. Required downloading separate language models for each language
2. Lower transcription accuracy
3. No built-in translation capabilities
4. Less active development

## Consequences

### Positive:
- Better transcription quality for end users
- Simplified deployment (no language model downloads)
- Built-in translation reduces LibreTranslate dependency for English targets
- Real-time progress tracking possible

### Negative:
- Larger Docker image (Whisper model is ~3GB)
- Higher memory requirements
- Breaking change from main branch

## Implementation

- Created new `whisper-rpc` branch
- Implemented Python Flask server with faster-whisper
- Configured Docker Compose with whisper-server service
- Updated progress allocation: 85% for Whisper (when translating), 65% (when transcribing only)

## References

- [Whisper Model Card](https://github.com/openai/whisper/blob/main/model-card.md)
- [faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper)
