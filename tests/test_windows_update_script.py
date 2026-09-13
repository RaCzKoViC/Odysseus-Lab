from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_update_script_uses_safe_docker_update_flow():
    script = (ROOT / "update_windows.bat").read_text(encoding="utf-8")
    lowered = script.lower()

    assert 'pushd "%~dp0"' in lowered
    assert "where git" in lowered
    assert "where docker" in lowered
    assert "docker compose version" in lowered
    assert "git pull --ff-only" in lowered
    assert "docker compose up -d --build" in lowered
    assert "odysseus-compose-backup snapshot" in lowered
    assert lowered.index("odysseus-compose-backup snapshot") < lowered.index("git pull --ff-only")
    assert "/api/ready" in lowered
    assert "previous_sha" in lowered
    assert "compose_file" in lowered
    assert "docker image prune -f" in lowered
    assert "pause" in lowered


def test_posix_update_script_is_safe_and_origin_only():
    script = (ROOT / "scripts" / "update-lab.sh").read_text(encoding="utf-8")

    assert "git pull --ff-only origin main" in script
    assert "odysseus-compose-backup snapshot" in script
    assert script.index("odysseus-compose-backup snapshot") < script.index(
        "git pull --ff-only origin main"
    )
    assert "/api/ready" in script
    assert "upstream" not in script
    assert "git reset" not in script
