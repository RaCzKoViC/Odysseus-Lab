"""Tests for the readiness / integrity self-check (src/readiness.py)."""

import json
from pathlib import Path

import core.database
import src.readiness as readiness
from src.readiness import check_readiness


ROOT = Path(__file__).resolve().parents[1]


def test_readiness_reports_core_subsystems():
    result = check_readiness()

    assert {"ready", "version", "checks", "timestamp"}.issubset(result.keys())
    checks = result["checks"]
    for name in ("database", "data_dir", "local_first"):
        assert name in checks, f"missing check: {name}"

    # In the dev/test environment the local SQLite DB and data dir are present,
    # so the critical checks must pass and overall readiness must be True.
    assert checks["database"]["ok"] is True, checks["database"]
    assert checks["data_dir"]["ok"] is True, checks["data_dir"]
    assert "path" not in checks["data_dir"]
    assert result["ready"] is True, result


def test_local_first_check_is_informational_never_fatal():
    result = check_readiness()
    lf = result["checks"]["local_first"]
    # local_first reports whether storage stays on-host but must never gate
    # readiness — a remote database is a valid deployment.
    assert lf["ok"] is True
    assert "local" in lf


def test_readiness_failure_details_do_not_expose_paths_or_exceptions(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("postgresql://admin:secret@example.test/database")

    monkeypatch.setattr(core.database, "engine", BrokenEngine())
    monkeypatch.setattr(
        readiness.os,
        "makedirs",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("/private/data/path")),
    )

    result = check_readiness()
    serialized = json.dumps(result)

    assert result["ready"] is False
    assert result["checks"]["database"]["error"] == "database unavailable"
    assert result["checks"]["data_dir"]["error"] == "data directory unavailable"
    assert "secret" not in serialized
    assert "/private/data/path" not in serialized


def test_readiness_route_is_auth_exempt_for_orchestrators():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    auth_block = source.split("AUTH_EXEMPT_EXACT = {", 1)[1].split("}", 1)[0]

    assert '"/api/ready"' in auth_block
