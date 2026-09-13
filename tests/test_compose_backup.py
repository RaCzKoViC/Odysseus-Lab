import json
import tarfile
from pathlib import Path

import pytest

from tests.helpers.cli_loader import load_script


def test_compose_bundle_manifest_and_checksums_round_trip(tmp_path):
    backup = load_script("odysseus-compose-backup")
    stage = tmp_path / "stage"
    restored = tmp_path / "restored"
    stage.mkdir()
    restored.mkdir()
    (stage / "app-data.tar.gz").write_bytes(b"app-state")
    (stage / "chromadb.tar.gz").write_bytes(b"chroma-state")
    manifest = {
        "schema": "odysseus-compose-backup.v1",
        "created_at": "2026-09-13T00:00:00+00:00",
        "artifacts": {
            name: {"sha256": backup._sha256(stage / name)}
            for name in ("app-data.tar.gz", "chromadb.tar.gz")
        },
    }
    bundle = tmp_path / "bundle.tar.gz"

    backup._write_bundle(stage, bundle, manifest)
    loaded = backup._extract_bundle(bundle, restored)

    assert loaded == manifest
    assert (restored / "app-data.tar.gz").read_bytes() == b"app-state"
    assert (restored / "chromadb.tar.gz").read_bytes() == b"chroma-state"


def test_compose_bundle_rejects_checksum_mismatch(tmp_path):
    backup = load_script("odysseus-compose-backup")
    stage = tmp_path / "stage"
    restored = tmp_path / "restored"
    stage.mkdir()
    restored.mkdir()
    (stage / "app-data.tar.gz").write_bytes(b"app-state")
    (stage / "chromadb.tar.gz").write_bytes(b"chroma-state")
    manifest = {
        "schema": "odysseus-compose-backup.v1",
        "created_at": "2026-09-13T00:00:00+00:00",
        "artifacts": {
            "app-data.tar.gz": {"sha256": "0" * 64},
            "chromadb.tar.gz": {"sha256": backup._sha256(stage / "chromadb.tar.gz")},
        },
    }
    bundle = tmp_path / "bundle.tar.gz"
    backup._write_bundle(stage, bundle, manifest)

    with pytest.raises(backup.BackupError, match="checksum mismatch"):
        backup._extract_bundle(bundle, restored)


def test_compose_bundle_rejects_extra_members(tmp_path):
    backup = load_script("odysseus-compose-backup")
    bundle = tmp_path / "bundle.tar.gz"
    extra = tmp_path / "extra"
    extra.write_text("unexpected", encoding="utf-8")
    with tarfile.open(bundle, "w:gz") as archive:
        archive.add(extra, arcname="unexpected.txt")

    with pytest.raises(backup.BackupError, match="exactly"):
        backup._extract_bundle(bundle, tmp_path / "restore")


def test_compose_restore_requires_explicit_confirmation(tmp_path, capsys):
    backup = load_script("odysseus-compose-backup")
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(b"unused")

    assert backup.main(["--repo", str(tmp_path), "restore", str(bundle)]) == 1
    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert "--yes" in payload["error"]


def test_compose_snapshot_restarts_services_after_failure(monkeypatch, tmp_path):
    backup = load_script("odysseus-compose-backup")
    data = tmp_path / "data"
    data.mkdir()
    restarted = []
    monkeypatch.setattr(backup.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(backup, "_data_dir", lambda root: data)
    monkeypatch.setattr(backup, "_chroma_volume", lambda root: "project_chromadb-data")
    monkeypatch.setattr(backup, "_prepare_backup_helper", lambda root: None)
    monkeypatch.setattr(backup, "_stop_running", lambda root, services: ["odysseus", "chromadb"])
    monkeypatch.setattr(backup, "_restart", lambda root, services: restarted.extend(services))
    monkeypatch.setattr(
        backup,
        "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(backup.BackupError("snapshot failed")),
    )

    with pytest.raises(backup.BackupError, match="snapshot failed"):
        backup.snapshot(tmp_path, tmp_path / "out.tar.gz")

    assert restarted == ["odysseus", "chromadb"]


@pytest.mark.parametrize("operation", ["snapshot", "restore"])
def test_unavailable_backup_helper_does_not_stop_services(monkeypatch, tmp_path, operation):
    backup = load_script("odysseus-compose-backup")
    data = tmp_path / "data"
    data.mkdir()
    stopped = []
    monkeypatch.setattr(backup.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(backup, "_data_dir", lambda root: data)
    monkeypatch.setattr(backup, "_chroma_volume", lambda root: "project_chromadb-data")
    monkeypatch.setattr(backup, "_stop_running", lambda root, services: stopped.extend(services))
    monkeypatch.setattr(
        backup, "_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(backup.BackupError("helper unavailable")),
    )

    with pytest.raises(backup.BackupError, match="helper unavailable"):
        getattr(backup, operation)(tmp_path, tmp_path / "bundle.tar.gz")

    assert stopped == []
