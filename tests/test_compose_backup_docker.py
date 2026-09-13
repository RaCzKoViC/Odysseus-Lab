"""Opt-in real volume regression: ODYSSEUS_TEST_DOCKER=1 python -m pytest -q tests/test_compose_backup_docker.py."""
import json
import os
import uuid

import pytest

from tests.helpers.cli_loader import load_script


@pytest.mark.skipif(os.getenv("ODYSSEUS_TEST_DOCKER") != "1", reason="requires a running Docker engine")
def test_chroma_backup_restore_round_trip_with_python_helper(tmp_path):
    backup = load_script("odysseus-compose-backup")
    backup._prepare_backup_helper(tmp_path)
    volume = "odysseus-backup-test-" + uuid.uuid4().hex
    backup._run(["docker", "volume", "create", volume], cwd=tmp_path)

    def volume_python(code):
        return backup._run(
            ["docker", "run", "--rm", "--pull=never", "--network", "none",
             "--entrypoint", "python", "-v", f"{volume}:/target",
             backup.BACKUP_HELPER_IMAGE, "-c", code],
            cwd=tmp_path,
        )

    try:
        volume_python(
            "from pathlib import Path; p=Path('/target'); "
            "(p/'nested').mkdir(); (p/'nested'/'index.bin').write_bytes(bytes(range(256))); "
            "(p/'.metadata').write_text('original',encoding='utf-8')"
        )
        archive = tmp_path / "chromadb.tar.gz"
        backup._archive_chroma(tmp_path, volume, archive)
        backup._validate_tar_members(archive, "chroma")
        volume_python(
            "from pathlib import Path; p=Path('/target'); "
            "(p/'nested'/'index.bin').write_bytes(b'changed'); "
            "(p/'stale').write_text('must disappear',encoding='utf-8')"
        )
        backup._restore_chroma(tmp_path, volume, archive)
        restored = json.loads(volume_python(
            "from pathlib import Path; import json; p=Path('/target'); "
            "print(json.dumps({f.relative_to(p).as_posix():f.read_bytes().hex() "
            "for f in p.rglob('*') if f.is_file()}))"
        ))
        assert restored == {
            "nested/index.bin": bytes(range(256)).hex(),
            ".metadata": b"original".hex(),
        }
    finally:
        # Only the unique, empty-on-creation test volume is removed.
        backup._run(["docker", "volume", "rm", volume], cwd=tmp_path)
