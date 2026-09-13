import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    ROOT / "docker-compose.yml",
    ROOT / "docker-compose.gpu-nvidia.yml",
    ROOT / "docker-compose.gpu-amd.yml",
)


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda path: path.name)
def test_foundation_service_images_are_immutable(path):
    text = path.read_text(encoding="utf-8")

    for image in ("chromadb/chroma", "binwiederhier/ntfy"):
        match = re.search(rf"image:\s*docker\.io/{re.escape(image)}@sha256:([0-9a-f]{{64}})", text)
        assert match, f"{image} must use an immutable digest in {path.name}"

    assert "chromadb/chroma:latest" not in text
    assert re.search(r"binwiederhier/ntfy(?:\s|$)", text) is None


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda path: path.name)
def test_application_healthcheck_uses_readiness(path):
    text = path.read_text(encoding="utf-8")
    service = text.split("\n  chromadb:", 1)[0]

    assert "healthcheck:" in service
    assert "http://127.0.0.1:7000/api/ready" in service
    assert "start_period: 45s" in service


def test_ci_smoke_target_skips_only_optional_image_wheels():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    overlay = (ROOT / "docker" / "foundation-smoke.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "FROM runtime-base AS foundation-runtime" in dockerfile
    assert "FROM runtime-base AS production" in dockerfile
    production = dockerfile.split("FROM runtime-base AS production", 1)[1]
    assert "COPY --from=realesrgan-wheels" in production
    assert "target: foundation-runtime" in overlay
    assert "docker-compose.yml:docker/foundation-smoke.yml" in workflow
