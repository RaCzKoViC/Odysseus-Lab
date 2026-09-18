"""GET /api/cookbook/hf-gguf-files must degrade to ``{"ok": false}`` on errors.

Regression for RaCzKoViC/Odysseus-Lab#19 (upstream odysseus-dev/odysseus#6341):
the ``except`` branch logged with an undefined name, so any Hugging Face
failure escaped the handler as a ``NameError`` and the client received 500.
"""
import httpx
import pytest

import routes.cookbook_routes as cookbook_routes


def _hf_gguf_files_endpoint():
    router = cookbook_routes.setup_cookbook_routes()
    for route in router.routes:
        if route.path == "/api/cookbook/hf-gguf-files" and "GET" in route.methods:
            return route.endpoint
    raise AssertionError("GET /api/cookbook/hf-gguf-files route not found")


class _FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *args, **kwargs):
        raise httpx.ConnectError("network unreachable")


class _StatusClient(_FailingClient):
    def __init__(self, *args, **kwargs):
        pass

    async def get(self, *args, **kwargs):
        return httpx.Response(status_code=503, request=httpx.Request("GET", "https://huggingface.co"))


@pytest.mark.asyncio
async def test_transport_failure_returns_ok_false(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    endpoint = _hf_gguf_files_endpoint()

    result = await endpoint(repo_id="org/model", owner="admin")

    assert result == {"ok": False, "files": [], "error": "HF API request failed"}


@pytest.mark.asyncio
async def test_non_200_status_returns_ok_false(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _StatusClient)
    endpoint = _hf_gguf_files_endpoint()

    result = await endpoint(repo_id="org/model", owner="admin")

    assert result == {"ok": False, "files": [], "error": "HF API HTTP 503"}
