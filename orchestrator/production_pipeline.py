from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from .claim_synthesis import ClaimSynthesizer, MockClaimSynthesizer
from .claim_verifier import ClaimVerifier, MockClaimVerifier
from .evidence_extractor import EvidenceExtraction, MockEvidenceExtraction
from .gemini import DEFAULT_MODEL, GeminiClient, GeminiError
from .page_fetcher import PageFetcher
from .quality_schemas import QualityReport, ResourceUsage
from .research_orchestrator import ResearchOrchestrator, ResearchResult
from .research_planner import MockResearchPlanner, ResearchPlanner
from .research_schemas import ResearchPackage
from .scene_planner import MockScenePlanner, ScenePlanner
from .scene_schemas import ScenePlan
from .scene_validation import validate_scene_coverage
from .script_generator import MockScriptGenerator, ScriptGenerator
from .script_schemas import VideoFormat, VideoScript
from .search_provider import MockSearchProvider
from .source_discovery import SourceDiscovery
from .tavily_provider import TavilySearchProvider


class ResearchComponent(Protocol):
    def research(self, topic: str, *, target_seconds: float) -> ResearchResult: ...


class ScriptComponent(Protocol):
    def generate(
        self, package: ResearchPackage, *, format: VideoFormat, target_seconds: float
    ) -> VideoScript: ...


class SceneComponent(Protocol):
    def plan(self, script: VideoScript) -> ScenePlan: ...


class ProductionArtifacts(BaseModel):
    mode: Literal["live", "mock"]
    research: ResearchPackage
    quality: QualityReport
    usage: ResourceUsage
    script: VideoScript
    scene_plan: ScenePlan


class ProductionPipeline:
    """Thin workflow coordinator over independently replaceable stage components."""

    def __init__(
        self,
        researcher: ResearchComponent,
        script_generator: ScriptComponent,
        scene_planner: SceneComponent,
        *,
        mode: Literal["live", "mock"] = "live",
    ):
        self._researcher = researcher
        self._script_generator = script_generator
        self._scene_planner = scene_planner
        self._mode = mode

    def generate(
        self, topic: str, *, format: VideoFormat = "short", target_seconds: float = 35.0
    ) -> ProductionArtifacts:
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("Topic must be a non-empty string.")
        research_result = self._researcher.research(
            topic.strip(), target_seconds=target_seconds
        )
        if research_result.quality.status == "insufficient":
            raise ValueError("Research quality is insufficient to create a script.")
        script = self._script_generator.generate(
            research_result.package, format=format, target_seconds=target_seconds
        )
        scene_plan = self._scene_planner.plan(script)
        validate_scene_coverage(scene_plan, script, research_result.package)
        return ProductionArtifacts(
            mode=self._mode,
            research=research_result.package,
            quality=research_result.quality,
            usage=research_result.usage,
            script=script,
            scene_plan=scene_plan,
        )


def build_production_pipeline(
    *, mock: bool = False, model: str | None = None
) -> ProductionPipeline:
    if mock:
        researcher = ResearchOrchestrator(
            MockResearchPlanner(),
            SourceDiscovery(MockSearchProvider()),
            MockEvidenceExtraction(),
            MockClaimSynthesizer(),
            MockClaimVerifier(),
        )
        return ProductionPipeline(
            researcher,
            MockScriptGenerator(),
            MockScenePlanner(),
            mode="mock",
        )

    client = GeminiClient(model=model)
    researcher = ResearchOrchestrator(
        ResearchPlanner(client),
        SourceDiscovery(TavilySearchProvider()),
        EvidenceExtraction(PageFetcher(), client),
        ClaimSynthesizer(client),
        ClaimVerifier(client),
    )
    return ProductionPipeline(
        researcher,
        ScriptGenerator(client),
        ScenePlanner(client),
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:48] or "video"


def _write_json(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")


def save_artifacts(artifacts: ProductionArtifacts, output_root: Path) -> Path:
    now = datetime.now(timezone.utc)
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = f"{_slug(artifacts.scene_plan.script_id)}-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
    job_dir = output_root / run_id
    job_dir.mkdir(exist_ok=False)
    _write_json(job_dir / "research.json", artifacts.research.model_dump_json(indent=2))
    _write_json(
        job_dir / "run_metadata.json",
        json.dumps(
            {
                "mode": artifacts.mode,
                "script_id": artifacts.script.script_id,
                "scene_plan_id": artifacts.scene_plan.scene_plan_id,
                "format": artifacts.script.format,
                "target_seconds": artifacts.script.target_seconds,
                "created_at": now.isoformat(),
            },
            indent=2,
        ),
    )
    _write_json(job_dir / "quality.json", artifacts.quality.model_dump_json(indent=2))
    _write_json(job_dir / "usage.json", artifacts.usage.model_dump_json(indent=2))
    _write_json(job_dir / "script.json", artifacts.script.model_dump_json(indent=2))
    _write_json(job_dir / "scene_plan.json", artifacts.scene_plan.model_dump_json(indent=2))
    _write_json(
        job_dir / "render_props.json",
        json.dumps({"plan": artifacts.scene_plan.model_dump(mode="json")}, indent=2),
    )
    return job_dir


def render_artifacts(job_dir: Path) -> Path:
    renderer_dir = Path(__file__).resolve().parents[1] / "renderer"
    output = job_dir / "final.mp4"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    command = [
        npm,
        "run",
        "render",
        "--",
        "Main",
        str(output.resolve()),
        f"--props={str((job_dir / 'render_props.json').resolve())}",
    ]
    subprocess.run(command, cwd=renderer_dir, check=True)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.production_pipeline",
        description="Research, write, plan, validate, and optionally render a video.",
    )
    parser.add_argument("topic", nargs="+", help="Video topic.")
    parser.add_argument("--mock", action="store_true", help="Use deterministic offline components.")
    parser.add_argument("--model", default=None, help=f"Gemini model (default: {DEFAULT_MODEL}).")
    parser.add_argument("--format", choices=("short", "mid_form", "long_form"), default="short")
    parser.add_argument("--target-seconds", type=float, default=35.0)
    parser.add_argument("--output-root", type=Path, default=Path("output/production"))
    parser.add_argument("--render", action="store_true", help="Render final.mp4 with Remotion.")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    output_root = args.output_root if args.output_root.is_absolute() else root / args.output_root

    try:
        pipeline = build_production_pipeline(mock=args.mock, model=args.model)
        artifacts = pipeline.generate(
            " ".join(args.topic), format=args.format, target_seconds=args.target_seconds
        )
        job_dir = save_artifacts(artifacts, output_root)
        label = "Mock research quality" if artifacts.mode == "mock" else "Research quality"
        print(f"{label}: {artifacts.quality.status}")
        if artifacts.quality.warnings:
            print(f"Quality warnings: {len(artifacts.quality.warnings)}")
        print(f"Script: {job_dir / 'script.json'}")
        print(f"Scene plan: {job_dir / 'scene_plan.json'}")
        if args.render:
            print(f"Video: {render_artifacts(job_dir)}")
        return 0
    except (GeminiError, RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Production pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
