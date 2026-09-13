import json
from types import SimpleNamespace

import src.context_engine.manifest as manifest_module
from src.context_engine import build_context_manifest
from src.context_engine.models import CONTEXT_CATEGORY_IDS


class Message:
    def __init__(self, role, content, metadata=None):
        self.role = role
        self.content = content
        self.metadata = metadata or {}

    def to_dict(self):
        payload = {"role": self.role, "content": self.content}
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class Session:
    id = "session-1"
    endpoint_url = "http://localhost:11434/v1/chat/completions"
    model = "qwen"
    project_id = "project-1"

    def __init__(self):
        self.history = [
            Message("system", "Stable instructions"),
            Message("user", "Build the project"),
            Message(
                "assistant",
                "Done",
                {
                    "request_context_tokens": 1024,
                    "context_length": 8192,
                    "usage_source": "real",
                    "memories_used": [{"text": "Use TypeScript"}],
                    "rag_sources": [{"filename": "README.md", "text": "Architecture"}],
                    "tool_events": [{"name": "read_file"}],
                    "context_budget_plan": {
                        "input_budget": 7000,
                        "output_reserve": 1024,
                        "schema_tokens": 320,
                        "message_window": 6680,
                        "tokens_before": 1400,
                        "tokens_after": 1024,
                    },
                },
            ),
        ]

    def get_context_messages(self):
        return [message.to_dict() for message in self.history]


def test_context_manifest_has_stable_categories_and_lenses(monkeypatch):
    monkeypatch.setattr(
        manifest_module,
        "get_context_length_known",
        lambda endpoint, model: (8192, True),
    )
    project = SimpleNamespace(
        id="project-1",
        name="My App",
        description="Local project",
        settings={"memory_mode": "project_only", "instructions": "Keep it local"},
    )

    payload = build_context_manifest(
        Session(),
        owner="alice",
        project=project,
        settings={
            "agent_input_token_budget": 6000,
            "agent_input_token_hard_max": 200000,
        },
    ).to_dict()

    assert [category["id"] for category in payload["categories"]] == list(
        CONTEXT_CATEGORY_IDS
    )
    assert payload["context_profile"]["tier"] == "s"
    assert payload["lenses"]["last_turn"]["used_tokens"] == 1024
    assert payload["lenses"]["last_turn"]["usage_source"] == "real"
    assert payload["budget"]["configured_soft_explicit"] is False
    assert payload["budget"]["effective_soft"] == int(8192 * 0.85)
    assert payload["flags"]["project_memory_mode"] == "project_only"
    assert payload["actions"]["can_compact"] is True
    assert payload["budget"]["schema_tokens"] == 320
    tools = next(
        category for category in payload["categories"] if category["id"] == "tools"
    )
    assert any(item["label"] == "Provider tool schemas" for item in tools["items"])


def test_context_manifest_records_provenance_without_payload_text(monkeypatch):
    monkeypatch.setattr(
        manifest_module,
        "get_context_length_known",
        lambda endpoint, model: (4096, True),
    )

    payload = build_context_manifest(Session(), owner="alice").to_dict()
    serialized = json.dumps(payload)

    memory = next(
        category for category in payload["categories"] if category["id"] == "memory"
    )
    assert memory["items"][0]["provenance"]["source"] == "memory"
    assert memory["items"][0]["trust"] == "untrusted"
    assert "Stable instructions" not in serialized
    assert "Build the project" not in serialized
    assert "password" not in serialized.lower()


def test_unknown_context_window_keeps_conservative_budget(monkeypatch):
    monkeypatch.setattr(
        manifest_module,
        "get_context_length_known",
        lambda endpoint, model: (128000, False),
    )

    payload = build_context_manifest(Session(), settings={}).to_dict()

    assert payload["context_profile"]["tier"] == "unknown"
    assert payload["context_profile"]["confidence"] == "unknown"
    assert payload["budget"]["effective_soft"] == 6000
