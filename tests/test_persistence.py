import json
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from orchestrator import pipeline
from orchestrator.validation import validate_job

from conftest import TOPIC, make_job


@pytest.fixture
def jobs_dir(tmp_path, monkeypatch):
    directory = tmp_path / "jobs"
    monkeypatch.setattr(pipeline, "JOBS_DIR", directory)
    return directory


def test_job_id_format():
    job = make_job()
    assert re.fullmatch(
        r"why-is-netflix-cheaper-than-cable-tv-\d{20}-[0-9a-f]{6}", job["jobId"]
    )


def test_job_ids_unique_across_rapid_generation():
    ids = [make_job()["jobId"] for _ in range(50)]
    assert len(set(ids)) == 50


def test_save_job_writes_complete_json_without_temp_leftovers(tmp_path):
    job = make_job()
    path = tmp_path / "nested" / "job.json"
    assert pipeline.save_job(job, path) == path
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == job
    assert [p.name for p in path.parent.iterdir()] == ["job.json"]


def test_save_job_refuses_to_overwrite_existing_job(tmp_path):
    path = tmp_path / "job.json"
    pipeline.save_job(make_job(), path)
    original = path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        pipeline.save_job(make_job(), path)
    assert path.read_text(encoding="utf-8") == original


def test_write_latest_replaces_previous_copy_atomically(tmp_path):
    path = tmp_path / "latest.json"
    pipeline.write_latest(make_job(), path)
    newer = make_job()
    assert pipeline.write_latest(newer, path) == path
    assert json.loads(path.read_text(encoding="utf-8")) == newer
    assert [p.name for p in tmp_path.iterdir()] == ["latest.json"]


def test_failed_replace_cleans_temp_and_leaves_no_destination(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(pipeline.os, "replace", boom)
    path = tmp_path / "job.json"
    with pytest.raises(OSError, match="simulated replace failure"):
        pipeline.save_job(make_job(), path)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_failed_fsync_cleans_temp_and_leaves_no_destination(tmp_path, monkeypatch):
    def boom(fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(pipeline.os, "fsync", boom)
    path = tmp_path / "job.json"
    with pytest.raises(OSError, match="simulated fsync failure"):
        pipeline.save_job(make_job(), path)
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_run_writes_job_archive_and_latest(jobs_dir, tmp_path):
    latest = tmp_path / "latest.json"
    job, returned = pipeline.run(TOPIC, mock=True, out_path=latest)
    assert returned == latest
    validate_job(job)
    archive = jobs_dir / f"{job['jobId']}.json"
    assert json.loads(archive.read_text(encoding="utf-8")) == job
    assert json.loads(latest.read_text(encoding="utf-8")) == job
    assert [p.name for p in jobs_dir.iterdir()] == [archive.name]
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["latest.json"]


def test_failed_job_write_never_updates_latest(jobs_dir, tmp_path, monkeypatch):
    latest = tmp_path / "latest.json"
    latest.write_text('{"previous": true}\n', encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(pipeline.os, "replace", boom)
    with pytest.raises(OSError, match="simulated disk failure"):
        pipeline.run(TOPIC, mock=True, out_path=latest)
    assert latest.read_text(encoding="utf-8") == '{"previous": true}\n'
    assert list(jobs_dir.glob("*.json")) == []
    assert list(jobs_dir.glob("*.tmp")) == []


def test_failed_latest_write_keeps_job_archive(jobs_dir, tmp_path, monkeypatch):
    latest = tmp_path / "latest.json"
    real_replace = pipeline.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) > 1:
            raise OSError("simulated latest failure")
        return real_replace(src, dst)

    monkeypatch.setattr(pipeline.os, "replace", flaky)
    with pytest.raises(OSError, match="simulated latest failure"):
        pipeline.run(TOPIC, mock=True, out_path=latest)
    archives = list(jobs_dir.glob("*.json"))
    assert len(archives) == 1
    validate_job(json.loads(archives[0].read_text(encoding="utf-8")))
    assert not latest.exists()
    assert list(jobs_dir.glob("*.tmp")) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_concurrent_saves_produce_unique_complete_jobs(jobs_dir):
    def work(_):
        job = make_job()
        pipeline.save_job(job, jobs_dir / f"{job['jobId']}.json")
        return job

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(work, range(8)))
    ids = [job["jobId"] for job in jobs]
    assert len(set(ids)) == 8
    files = sorted(jobs_dir.glob("*.json"))
    assert len(files) == 8
    for path in files:
        job = json.loads(path.read_text(encoding="utf-8"))
        validate_job(job)
        assert path.name == f"{job['jobId']}.json"
    assert list(jobs_dir.glob("*.tmp")) == []


def test_cli_relative_out_resolves_against_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "JOBS_DIR", tmp_path / "jobs")
    code = pipeline.main(["--mock", "--out", "custom/latest.json", TOPIC])
    assert code == 0
    assert (tmp_path / "custom" / "latest.json").exists()
    assert len(list((tmp_path / "jobs").glob("*.json"))) == 1


def test_cli_absolute_out_is_used_as_given(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "JOBS_DIR", tmp_path / "jobs")
    out = tmp_path / "elsewhere" / "abs.json"
    code = pipeline.main(["--mock", "--out", str(out), TOPIC])
    assert code == 0
    assert out.exists()


def test_cli_default_out_writes_latest_and_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(pipeline, "DEFAULT_OUT", tmp_path / "jobs" / "latest.json")
    code = pipeline.main(["--mock", TOPIC])
    assert code == 0
    assert (tmp_path / "jobs" / "latest.json").exists()
    assert len(list((tmp_path / "jobs").glob("*.json"))) == 2


def test_cli_write_failure_exits_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "JOBS_DIR", tmp_path / "jobs")

    def boom(src, dst):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(pipeline.os, "replace", boom)
    code = pipeline.main(["--mock", "--out", str(tmp_path / "latest.json"), TOPIC])
    assert code == 1
    assert "Pipeline failed: simulated disk failure" in capsys.readouterr().err
    assert not (tmp_path / "latest.json").exists()