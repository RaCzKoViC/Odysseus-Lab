from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["py311.txt", "py314.txt"])
def test_foundation_constraints_pin_every_resolved_package(name):
    lines = (ROOT / "constraints" / name).read_text(encoding="utf-8").splitlines()
    requirements = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith(("#", "--"))
    ]

    assert requirements
    assert all("==" in line for line in requirements)


def test_runtime_paths_use_matching_constraints():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "-c constraints/py314.txt" in dockerfile
    assert "constraints: py311" in workflow
    assert "constraints: py314" in workflow
