import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "upstream-status"


def test_upstream_status_is_read_only_and_reports_json():
    source = SCRIPT.read_text(encoding="utf-8")
    forbidden = ("git merge", "git rebase", "git push", "git reset", "git checkout")
    assert all(command not in source for command in forbidden)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(ROOT), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode in (0, 2)
    payload = json.loads(result.stdout)
    assert payload["baseline"]["commit"] == "9d5c0319149bfb69ce22a35f37cf17debaa5f14b"
    assert payload["baseline"]["branch"] == "dev"
    assert [item["branch"] for item in payload["upstream"]["refs"]] == ["main", "dev"]


def test_upstream_base_is_machine_readable():
    payload = json.loads((ROOT / "UPSTREAM_BASE").read_text(encoding="utf-8"))
    assert payload["repository"] == "https://github.com/odysseus-dev/odysseus"
    assert len(payload["commit"]) == 40
