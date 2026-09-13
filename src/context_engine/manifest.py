"""Build a read-only context manifest from persisted session state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.context_budget import (
    DEFAULT_BUDGET,
    DEFAULT_HARD_MAX,
    budget_is_explicit,
    compute_input_token_budget,
)
from src.context_engine.models import ContextItem, ContextManifest, ContextProfile
from src.model_context import estimate_tokens, get_context_length_known


def _tier(context_tokens: int, known: bool) -> str:
    if not known:
        return "unknown"
    if context_tokens <= 4096:
        return "xs"
    if context_tokens <= 8192:
        return "s"
    if context_tokens <= 16384:
        return "m"
    return "l"


def _profile(endpoint_url: str, model: str) -> ContextProfile:
    context_tokens, known = get_context_length_known(endpoint_url, model)
    return ContextProfile(
        model=model or "",
        context_tokens=int(context_tokens or 0),
        context_known=bool(known),
        tier=_tier(int(context_tokens or 0), bool(known)),
        source="runtime_discovery" if known else "default_fallback",
        confidence="provider_reported" if known else "unknown",
    )


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return dict(message)
    if hasattr(message, "to_dict"):
        return message.to_dict()
    return {
        "role": getattr(message, "role", ""),
        "content": getattr(message, "content", ""),
        "metadata": getattr(message, "metadata", None),
    }


def _token_estimate(content: Any, role: str = "user") -> int:
    return int(estimate_tokens([{"role": role, "content": content or ""}]))


def _safe_label(row: Any, fallback: str) -> str:
    if not isinstance(row, dict):
        return fallback
    for key in ("title", "name", "filename", "label"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:160]
    return fallback


def _metadata_items(
    metadata: dict[str, Any],
    *,
    owner: Optional[str],
    project_id: Optional[str],
    session_id: str,
) -> list[ContextItem]:
    items: list[ContextItem] = []
    groups = (
        ("memories_used", "memory", "Saved memory", "memory"),
        ("rag_sources", "files_rag", "RAG source", "rag"),
        ("web_sources", "knowledge", "Web source", "web"),
        ("research_sources", "knowledge", "Research source", "research"),
    )
    for field, category, fallback, source in groups:
        rows = metadata.get(field)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows[:100]):
            if source == "memory" and isinstance(row, dict):
                category_name = str(row.get("category") or "").strip()
                label = f"Saved memory: {category_name}" if category_name else fallback
            else:
                label = _safe_label(row, fallback)
            text = row.get("text") if isinstance(row, dict) else ""
            items.append(
                ContextItem(
                    id=f"last-turn:{field}:{index}",
                    category=category,
                    label=label,
                    tokens_estimated=_token_estimate(text or label),
                    trust="untrusted",
                    origin="external" if source in {"web", "research"} else "owner",
                    source=source,
                    owner=owner,
                    project_id=project_id,
                    session_id=session_id,
                    controls={"open": category == "memory"},
                )
            )
    tool_events = metadata.get("tool_events")
    if isinstance(tool_events, list):
        for index, event in enumerate(tool_events[:100]):
            name = _safe_label(event, "Tool call")
            items.append(
                ContextItem(
                    id=f"last-turn:tool:{index}",
                    category="tools",
                    label=name,
                    tokens_estimated=_token_estimate(event),
                    trust="untrusted",
                    origin="tool",
                    source="tool_event",
                    owner=owner,
                    project_id=project_id,
                    session_id=session_id,
                )
            )
    return items


def build_context_manifest(
    session,
    *,
    owner: Optional[str] = None,
    project: Any = None,
    settings: Optional[dict[str, Any]] = None,
) -> ContextManifest:
    settings = settings or {}
    messages = [_message_dict(message) for message in session.get_context_messages()]
    profile = _profile(session.endpoint_url, session.model)
    session_tokens = int(estimate_tokens(messages))
    percent = (
        round((session_tokens / profile.context_tokens) * 100, 1)
        if profile.context_tokens else 0.0
    )
    percent = max(0.0, min(100.0, percent))
    project_id = getattr(session, "project_id", None)
    project_settings = (
        dict(getattr(project, "settings", None) or {})
        if project is not None else {}
    )

    items: list[ContextItem] = []
    latest_assistant_metadata: dict[str, Any] = {}
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        metadata = message.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if role == "assistant":
            latest_assistant_metadata = metadata
        if role == "system":
            category = "system"
            label = "Conversation summary" if metadata.get("compacted") else "System instructions"
            trust = "untrusted" if metadata.get("trusted") is False else "trusted"
        elif role == "tool" or message.get("tool_calls"):
            category = "tools"
            label = "Tool result" if role == "tool" else "Tool call"
            trust = "untrusted"
        else:
            category = "conversation"
            label = "User message" if role == "user" else "Assistant message"
            trust = "untrusted" if metadata.get("trusted") is False else "trusted"
        items.append(
            ContextItem(
                id=f"message:{index}",
                category=category,
                label=label,
                tokens_estimated=_token_estimate(message.get("content"), role=role),
                trust=trust,
                origin="session",
                source=str(metadata.get("source") or "history"),
                owner=owner,
                project_id=project_id,
                session_id=session.id,
                protected=bool(metadata.get("_protected")),
            )
        )

    items.extend(
        _metadata_items(
            latest_assistant_metadata,
            owner=owner,
            project_id=project_id,
            session_id=session.id,
        )
    )
    persisted_budget_plan = latest_assistant_metadata.get("context_budget_plan")
    persisted_budget_plan = (
        persisted_budget_plan if isinstance(persisted_budget_plan, dict) else {}
    )
    schema_tokens = int(persisted_budget_plan.get("schema_tokens") or 0)
    if schema_tokens:
        items.append(
            ContextItem(
                id="last-turn:tool-schemas",
                category="tools",
                label="Provider tool schemas",
                tokens_estimated=schema_tokens,
                trust="trusted",
                origin="server",
                source="route_budget",
                owner=owner,
                project_id=project_id,
                session_id=session.id,
            )
        )
    if project is not None:
        project_text = "\n".join(
            value for value in (
                getattr(project, "name", ""),
                getattr(project, "description", ""),
                project_settings.get("instructions", ""),
            )
            if isinstance(value, str) and value
        )
        items.append(
            ContextItem(
                id=f"project:{project.id}",
                category="project",
                label=getattr(project, "name", "Project"),
                tokens_estimated=_token_estimate(project_text),
                trust="trusted",
                origin="project",
                source="project_settings",
                owner=owner,
                project_id=project.id,
                session_id=session.id,
            )
        )

    configured = int(settings.get("agent_input_token_budget") or DEFAULT_BUDGET)
    hard_max = int(settings.get("agent_input_token_hard_max") or DEFAULT_HARD_MAX)
    explicit = budget_is_explicit(configured)
    effective = compute_input_token_budget(
        configured,
        profile.context_tokens if profile.context_known else 0,
        explicit,
        hard_max=hard_max,
    )
    actual_last = int(
        latest_assistant_metadata.get("request_context_tokens")
        or latest_assistant_metadata.get("input_tokens")
        or 0
    )
    last_limit = int(latest_assistant_metadata.get("context_length") or profile.context_tokens)
    last_percent = (
        round((actual_last / last_limit) * 100, 1)
        if actual_last and last_limit else 0.0
    )
    compacted = sum(
        1 for message in messages
        if isinstance(message.get("metadata"), dict)
        and message["metadata"].get("compacted")
    )
    visible = sum(
        1 for message in getattr(session, "history", [])
        if not (getattr(message, "metadata", None) or {}).get("hidden")
    )

    budget_payload = {
        "configured_soft": configured,
        "configured_soft_explicit": explicit,
        "hard_max": hard_max,
        "effective_soft": effective,
        "headroom": 0.85,
    }
    if persisted_budget_plan:
        budget_payload.update(
            {
                "route_input_budget": persisted_budget_plan.get("input_budget"),
                "output_reserve": persisted_budget_plan.get("output_reserve"),
                "schema_tokens": persisted_budget_plan.get("schema_tokens"),
                "message_window": persisted_budget_plan.get("message_window"),
                "tokens_before": persisted_budget_plan.get("tokens_before"),
                "tokens_after": persisted_budget_plan.get("tokens_after"),
            }
        )

    return ContextManifest(
        session_id=session.id,
        profile=profile,
        budget=budget_payload,
        lenses={
            "session": {
                "used_tokens": session_tokens,
                "limit_tokens": profile.context_tokens,
                "percent": percent,
                "message_count": visible,
                "context_message_count": len(messages),
                "compacted_messages": compacted,
            },
            "last_turn": {
                "used_tokens": actual_last,
                "limit_tokens": last_limit,
                "percent": last_percent,
                "context_trimmed": bool(latest_assistant_metadata.get("context_trimmed")),
                "tokens_before_trim": (
                    latest_assistant_metadata.get("context_tokens_before_trim")
                    or persisted_budget_plan.get("tokens_before")
                ),
                "tokens_after_trim": (
                    latest_assistant_metadata.get("context_tokens_after_trim")
                    or persisted_budget_plan.get("tokens_after")
                ),
                "usage_source": latest_assistant_metadata.get("usage_source") or "estimated",
            },
        },
        items=items,
        flags={
            "memory_enabled": settings.get("memory_enabled", True),
            "skills_enabled": settings.get("skills_enabled", True),
            "project_id": project_id,
            "project_memory_mode": project_settings.get("memory_mode", "inherit"),
        },
        actions={
            "can_compact": session_tokens > 0,
            "should_compact": percent >= 70,
            "auto_compact_threshold": 85,
            "compact_url": f"/api/session/{session.id}/compact",
        },
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
