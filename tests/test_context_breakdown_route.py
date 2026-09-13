import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.history.history_routes as history_routes
import src.context_engine.manifest as manifest_module
from core.models import ChatMessage


class Session:
    id = "session-1"
    owner = "alice"
    endpoint_url = "http://localhost:11434/v1/chat/completions"
    model = "qwen"
    project_id = None

    def __init__(self):
        self.history = [
            ChatMessage("user", "private prompt contents"),
            ChatMessage(
                "assistant",
                "response",
                metadata={
                    "request_context_tokens": 512,
                    "context_length": 8192,
                    "memories_used": [{"text": "private memory contents"}],
                },
            ),
        ]

    def get_context_messages(self):
        return [message.to_dict() for message in self.history]


def _endpoint(router):
    return next(
        route.endpoint for route in router.routes
        if route.path == "/api/session/{session_id}/context_breakdown"
    )


def test_context_breakdown_route_returns_secret_free_manifest(monkeypatch):
    session = Session()
    manager = SimpleNamespace(get_session=lambda session_id: session)
    monkeypatch.setattr(history_routes, "_verify_session_owner", lambda *args: None)
    monkeypatch.setattr(history_routes, "effective_user", lambda request: "alice")
    monkeypatch.setattr(
        manifest_module,
        "get_context_length_known",
        lambda endpoint, model: (8192, True),
    )
    router = history_routes.setup_history_routes(manager)

    payload = asyncio.run(_endpoint(router)(request=SimpleNamespace(), session_id=session.id))

    assert payload["session_id"] == session.id
    assert payload["lenses"]["session"]["used_tokens"] > 0
    assert payload["lenses"]["last_turn"]["used_tokens"] == 512
    assert len(payload["categories"]) == 8
    serialized = str(payload)
    assert "private prompt contents" not in serialized
    assert "private memory contents" not in serialized


def test_context_breakdown_preserves_owner_gate(monkeypatch):
    def reject(*args):
        raise HTTPException(404, "Session not found")

    monkeypatch.setattr(history_routes, "_verify_session_owner", reject)
    router = history_routes.setup_history_routes(
        SimpleNamespace(get_session=lambda session_id: Session())
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            _endpoint(router)(request=SimpleNamespace(), session_id="foreign")
        )
    assert exc.value.status_code == 404
