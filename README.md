# AI Video Factory - MVP

Topic -> research -> hook -> script -> scene plan -> validated job JSON.

The Remotion renderer is still a placeholder and does not consume the job JSON yet.

## Pipeline

1. **Research & fact collection** - Gemini with Google Search grounding. Source URLs come from the grounding metadata, then the notes are converted into a structured summary and fact sheet.
2. **Hook generation** - one 1-3 second hook plus two alternatives.
3. **Script writing** - narration sized to the target duration (about 2.4 spoken words per second), limited to the researched facts.
4. **Scene breakdown** - the AI chooses the number of scenes and their durations so they add up to the target, and assigns a visual and per-scene sources.
5. **JSON validation** - schema, scene count, hook/scene duration limits, total-duration tolerance, and source integrity. Invalid jobs are not saved.
6. **Save job** - writes `output/jobs/latest.json`.

## Requirements

- Python 3.10+
- A Gemini API key (free tier works; the default model is `gemini-2.5-flash`)
- Node.js 20+ and FFmpeg only for the renderer

## Setup

```bash
pip install -r requirements.txt
```

Set the API key:

```bash
# macOS / Linux
export GEMINI_API_KEY="your-key"

# Windows PowerShell
$env:GEMINI_API_KEY = "your-key"
```

`GOOGLE_API_KEY` is accepted as a fallback, and `GEMINI_MODEL` overrides the default model. Model and Google Search grounding usage follow your Gemini API quota and pricing.

## Generate a job

```bash
python -m orchestrator.pipeline "Why is Netflix cheaper than cable TV?"
```

Offline smoke test with no API key and placeholder data:

```bash
python -m orchestrator.pipeline --mock "Why is Netflix cheaper than cable TV?"
```

Options: `--model`, `--target-seconds` (default 35), `--out` (default `output/jobs/latest.json`). Use `--help` for details.

## Validation rules

- 3-10 scenes; the first scene is the hook (1-3s); every other scene is 2-12s.
- Scene durations must total the target within `max(2s, 8%)`.
- Research needs at least 3 facts, each citing one of the grounded source URLs.
- Scene citations must come from the research sources.
- Visual components are limited to `AnimatedText` and `SimpleDiagram`.
- A failed validation exits with an error and does not write the job.

## Job shape

```json
{
  "schemaVersion": 2,
  "jobId": "why-is-netflix-cheaper-than-cable-tv-20261120093358",
  "topic": "Why is Netflix cheaper than cable TV?",
  "status": "scripted",
  "format": { "width": 1080, "height": 1920, "fps": 30, "targetDurationSeconds": 35.0 },
  "generation": { "provider": "google", "model": "gemini-2.5-flash", "mode": "live" },
  "research": {
    "summary": "...",
    "facts": [{ "claim": "...", "source": "https://..." }],
    "sources": [{ "title": "...", "url": "https://..." }]
  },
  "hook": { "text": "...", "alternatives": ["...", "..."] },
  "script": { "narration": "...", "beats": ["..."], "wordCount": 84 },
  "scenes": [
    {
      "id": "scene-01",
      "type": "hook",
      "durationSeconds": 2.0,
      "narration": "...",
      "visual": { "component": "AnimatedText", "headline": "..." },
      "sources": []
    }
  ],
  "durationSeconds": 35.0
}
```

## Renderer

```bash
cd renderer
npm install
npm run render
```

The current composition renders a placeholder scene. Connecting the job JSON to Remotion scene components is the next milestone.
