# AI Video Factory

AI Video Factory creates typed, inspectable artifacts for a short-form explainer video and can render a silent MP4 from the scene plan.

## Component flow

```text
ResearchPlanner → SourceDiscovery → EvidenceExtraction
→ ClaimSynthesizer → ClaimVerifier → QualityEvaluator
→ ScriptGenerator → ScenePlanner → ScenePlan validation → Remotion
```

Each stage has a distinct component and schema. `ProductionPipeline` coordinates the research, script, and scene components through injectable interfaces. The CLI saves `research.json`, `quality.json`, `usage.json`, `script.json`, `scene_plan.json`, and renderer props in a unique output folder.

The original `orchestrator.pipeline` API remains for compatibility with the first MVP job format. New runs should use `orchestrator.production_pipeline` and the renderer-facing `ScenePlan`.

## Requirements

- Python 3.10+
- Node.js 20+ and npm
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and `TAVILY_API_KEY` for live runs
- Remotion's packaged video tooling for MP4 output; availability is confirmed by the actual render

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Install renderer dependencies:

```bash
cd renderer
npm install
cd ..
```

Live provider keys are read from environment variables. PowerShell example:

```powershell
$env:GEMINI_API_KEY = "your-key"
$env:TAVILY_API_KEY = "your-key"
```

## Generate and render

Generate validated artifacts without rendering:

```bash
python -m orchestrator.production_pipeline "Why is Netflix cheaper than cable TV?"
```

Render the scene plan to a silent MP4:

```bash
python -m orchestrator.production_pipeline --render "Why is Netflix cheaper than cable TV?"
```

Offline deterministic pipeline run (mock research content is illustrative, not factual):

```bash
python -m orchestrator.production_pipeline --mock --render "Why is Netflix cheaper than cable TV?"
```

Options include `--format short|mid_form|long_form`, `--target-seconds`, `--model`, and `--output-root`. Each run creates a new directory under `output/production` by default and never overwrites a prior run.

The renderer supports controlled title/text, statistic, comparison, process, diagram, timeline, illustration-placeholder, and conclusion scenes with timed overlays, deterministic motion, and portrait/landscape output. See [Phase 5 in the project plan](docs/PLAN.md#8-phase-5--remotion-renderer) for the supported visual vocabulary and limitations. To render the synthetic showcase locally, run `cd renderer`, `npm install`, and `npm run render:sample`; this writes `renderer/sample-output.mp4`. Phase 5 does not add voice/audio, sourced/licensed artwork, or automated render QC.
