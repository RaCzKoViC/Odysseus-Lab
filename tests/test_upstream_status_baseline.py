"""upstream-status measures drift from UPSTREAM_BASE, not from an unrelated merge-base.

Regression for RaCzKoViC/Odysseus-Lab#21: the Lab history began with a squash
import, so ``HEAD...upstream/dev`` has no common ancestor and reported
"behind ~2090" while the real drift since the baseline was four commits.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upstream-status"

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=_GIT_ENV,
        check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str, **files: str) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    """An upstream repo (main behind dev) and a Lab repo with a squash import."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    baseline = _commit(upstream, "upstream: baseline", **{"app.py": "v1\n", "README.md": "up\n"})
    _commit(upstream, "upstream: touch hotspot", **{"app.py": "v2\n"})
    _git(upstream, "checkout", "-q", "-b", "dev")
    _commit(upstream, "upstream: dev-only change", **{"docs/other.txt": "x\n"})

    lab = tmp_path / "lab"
    lab.mkdir()
    _git(lab, "init", "-q", "-b", "main")
    _commit(
        lab,
        "Import Odysseus repository contents",
        **{
            "app.py": "v1\n",
            "README.md": "lab\n",
            "UPSTREAM_BASE": json.dumps(
                {
                    "repository": "https://github.com/odysseus-dev/odysseus",
                    "branch": "dev",
                    "commit": baseline,
                    "version": "1.0.3",
                    "imported_at": "2026-09-13",
                }
            ),
        },
    )
    _git(lab, "remote", "add", "upstream", str(upstream))
    _git(lab, "fetch", "-q", "upstream", "main", "dev")
    return {"upstream": upstream, "lab": lab, "baseline": baseline}


def _report(lab: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(lab), *extra],
        capture_output=True,
        text=True,
        env=_GIT_ENV,
        check=False,
    )


def test_drift_is_counted_from_the_tracked_baseline(repos):
    result = _report(repos["lab"], "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    refs = {ref["branch"]: ref for ref in payload["upstream"]["refs"]}

    assert refs["main"]["since_baseline"] == 1
    assert refs["dev"]["since_baseline"] == 2
    assert refs["main"]["hotspots_changed"] == ["app.py"]
    assert refs["dev"]["hotspots_changed"] == ["app.py"]
    assert refs["dev"]["baseline_reachable"] is True
    assert payload["hotspots"] == ["app.py", "static/app.js", "src/llm_core.py", "core/database.py"]


def test_unrelated_histories_do_not_produce_bogus_ahead_behind(repos):
    payload = json.loads(_report(repos["lab"], "--json").stdout)
    for ref in payload["upstream"]["refs"]:
        assert ref["shared_history"] is False
        assert ref["lab_ahead"] is None
        assert ref["lab_behind"] is None


def test_text_report_names_drift_and_hotspots(repos):
    result = _report(repos["lab"])
    assert result.returncode == 0, result.stderr
    assert "dev: " in result.stdout
    assert "upstream +2 since baseline" in result.stdout
    assert "hotspots changed: app.py" in result.stdout
    assert "no shared history with Lab HEAD" in result.stdout
    assert "behind 2090" not in result.stdout


def test_unknown_baseline_is_reported_as_unreachable(repos):
    lab = repos["lab"]
    base = json.loads((lab / "UPSTREAM_BASE").read_text(encoding="utf-8"))
    base["commit"] = "0" * 40
    (lab / "UPSTREAM_BASE").write_text(json.dumps(base), encoding="utf-8")

    payload = json.loads(_report(lab, "--json").stdout)
    dev = next(ref for ref in payload["upstream"]["refs"] if ref["branch"] == "dev")
    assert dev["baseline_reachable"] is False
    assert dev["since_baseline"] is None
    assert dev["hotspots_changed"] == []
