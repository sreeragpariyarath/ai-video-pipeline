from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .engine import GeminiEngine, MockEngine
from .gemini import DEFAULT_MODEL, GeminiClient, GeminiError
from .schemas import Hook, ResearchBundle, ScenePlan, Script
from .validation import validate_job


ROOT = Path(__file__).resolve().parents[1]
JOBS_DIR = ROOT / "output" / "jobs"
DEFAULT_OUT = JOBS_DIR / "latest.json"
DEFAULT_TARGET_SECONDS = 35.0


def slugify(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug[:64] or "video-topic"


def build_job(
    topic: str,
    research: ResearchBundle,
    hook: Hook,
    script: Script,
    plan: ScenePlan,
    *,
    provider: str,
    model: str,
    mode: str,
    target_seconds: float,
) -> dict:
    now = datetime.now(timezone.utc)
    scenes = []
    for index, scene in enumerate(plan.scenes, start=1):
        visual = {
            "component": scene.visual.component,
            "headline": scene.visual.headline,
        }
        if scene.visual.subheadline:
            visual["subheadline"] = scene.visual.subheadline
        if scene.visual.items:
            visual["items"] = scene.visual.items
        scenes.append(
            {
                "id": f"scene-{index:02d}",
                "type": scene.type,
                "durationSeconds": round(scene.durationSeconds, 2),
                "narration": scene.narration.strip(),
                "visual": visual,
                "sources": scene.sources,
            }
        )

    total_seconds = round(
        sum(scene["durationSeconds"] for scene in scenes), 2
    )
    return {
        "schemaVersion": 2,
        "jobId": f"{slugify(topic)}-{now.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:6]}",
        "createdAt": now.isoformat(),
        "topic": topic,
        "status": "scripted",
        "format": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "targetDurationSeconds": target_seconds,
        },
        "generation": {"provider": provider, "model": model, "mode": mode},
        "research": {
            "summary": research.summary,
            "facts": [fact.model_dump() for fact in research.facts],
            "sources": [source.model_dump() for source in research.sources],
        },
        "hook": {"text": hook.text, "alternatives": hook.alternatives},
        "script": {
            "narration": script.narration,
            "beats": script.beats,
            "wordCount": len(script.narration.split()),
        },
        "scenes": scenes,
        "durationSeconds": total_seconds,
    }


def _atomic_write_json(job: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(job, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def save_job(job: dict, path: Path) -> Path:
    if path.exists():
        raise FileExistsError(
            f"Job file already exists: {path}. Refusing to overwrite an existing job."
        )
    _atomic_write_json(job, path)
    return path


def write_latest(job: dict, path: Path) -> Path:
    _atomic_write_json(job, path)
    return path


def run(
    topic: str,
    *,
    mock: bool = False,
    model: str | None = None,
    target_seconds: float = DEFAULT_TARGET_SECONDS,
    out_path: Path = DEFAULT_OUT,
) -> tuple[dict, Path]:
    topic = topic.strip()
    if not topic:
        raise ValueError("Topic must not be empty.")
    if target_seconds <= 0:
        raise ValueError("Target duration must be greater than 0.")

    print(f"AI Video Factory - {'offline mock' if mock else 'Gemini'}")
    print(f"[1/7] Topic accepted: {topic}")

    if mock:
        engine = MockEngine()
        provider, model_name, mode = "offline", "mock", "mock"
    else:
        client = GeminiClient(model=model)
        engine = GeminiEngine(client)
        provider, model_name, mode = "google", client.model, "live"

    print("[2/7] Research & fact collection ...")
    research = engine.research(topic, target_seconds)
    print(f"      {len(research.facts)} facts, {len(research.sources)} sources")

    print("[3/7] Hook generation ...")
    hook = engine.hook(topic, research)
    print(f"      {hook.text}")

    print("[4/7] Script writing ...")
    script = engine.write_script(topic, research, hook, target_seconds)
    print(f"      {len(script.narration.split())} words")

    print("[5/7] Scene breakdown ...")
    plan = engine.breakdown(topic, research, hook, script, target_seconds)
    plan_seconds = sum(scene.durationSeconds for scene in plan.scenes)
    print(f"      {len(plan.scenes)} scenes, {plan_seconds:g}s")

    job = build_job(
        topic,
        research,
        hook,
        script,
        plan,
        provider=provider,
        model=model_name,
        mode=mode,
        target_seconds=target_seconds,
    )

    print("[6/7] JSON validation ...")
    summary = validate_job(job)
    print(
        f"      passed ({summary['sceneCount']} scenes, "
        f"{summary['durationSeconds']}s, {summary['sourceCount']} sources)"
    )

    print("[7/7] Save job ...")
    job_path = save_job(job, JOBS_DIR / f"{job['jobId']}.json")
    latest_path = write_latest(job, out_path)
    print(f"      {job_path}")
    print(f"      {latest_path}")
    print(f"\nCreated job: {job['jobId']}")
    return job, latest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.pipeline",
        description="Topic -> research -> hook -> script -> scenes -> validated job JSON.",
    )
    parser.add_argument("topic", nargs="+", help="Video topic (quote multi-word topics).")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run offline with deterministic placeholder data (no API key needed).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Gemini model (default: $GEMINI_MODEL or {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--target-seconds",
        type=float,
        default=DEFAULT_TARGET_SECONDS,
        help=f"Target video duration in seconds (default: {DEFAULT_TARGET_SECONDS:g}).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=(
            "Destination for the latest-job copy (relative paths resolve against the "
            f"repo root; default: {DEFAULT_OUT}). Each job is also archived as "
            "output/jobs/<jobId>.json."
        ),
    )
    args = parser.parse_args(argv)
    out_path = args.out if args.out.is_absolute() else ROOT / args.out

    try:
        run(
            " ".join(args.topic),
            mock=args.mock,
            model=args.model,
            target_seconds=args.target_seconds,
            out_path=out_path,
        )
    except (GeminiError, ValueError, OSError) as exc:
        print(f"\nPipeline failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
