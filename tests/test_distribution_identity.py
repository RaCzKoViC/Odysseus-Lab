import asyncio
import json
from pathlib import Path

from src.constants import (
    APP_DISTRIBUTION,
    APP_VERSION,
    PRODUCT_DISPLAY_NAME,
    PRODUCT_NAME,
    REPOSITORY_URL,
    UPSTREAM_REPOSITORY,
    UPSTREAM_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]


def test_lab_distribution_metadata_is_explicit():
    assert PRODUCT_NAME == "Odysseus-Lab"
    assert PRODUCT_DISPLAY_NAME == "Odysseus - Lab"
    assert APP_VERSION == "0.2.2"
    assert APP_DISTRIBUTION == "lab"
    assert REPOSITORY_URL.endswith("/RaCzKoViC/Odysseus-Lab")
    assert UPSTREAM_VERSION == "1.0.3"
    assert UPSTREAM_REPOSITORY.endswith("/odysseus-dev/odysseus")


def test_pwa_manifest_uses_lab_identity():
    manifest = json.loads((ROOT / "static" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == PRODUCT_DISPLAY_NAME
    assert manifest["short_name"] == PRODUCT_DISPLAY_NAME


def test_version_route_is_additive():
    from app import app

    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/version")
    payload = asyncio.run(route.endpoint())

    assert payload["version"] == APP_VERSION
    assert payload["product"] == PRODUCT_NAME
    assert payload["distribution"] == APP_DISTRIBUTION
    assert payload["upstream"]["version"] == UPSTREAM_VERSION
