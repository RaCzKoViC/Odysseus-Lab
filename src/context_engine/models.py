"""Provider-agnostic Context Engine data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


CONTEXT_CATEGORY_IDS = (
    "system",
    "conversation",
    "memory",
    "project",
    "files_rag",
    "knowledge",
    "tools",
    "mcp",
)


@dataclass(frozen=True)
class ContextProfile:
    model: str
    context_tokens: int
    context_known: bool
    tier: str
    source: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "context_tokens": self.context_tokens,
            "context_known": self.context_known,
            "tier": self.tier,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ContextItem:
    id: str
    category: str
    label: str
    tokens_estimated: int
    trust: str
    origin: str
    source: str
    owner: Optional[str] = None
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    protected: bool = False
    controls: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "label": self.label,
            "tokens": self.tokens_estimated,
            "trust": self.trust,
            "provenance": {
                "origin": self.origin,
                "source": self.source,
                "owner": self.owner,
                "project_id": self.project_id,
                "session_id": self.session_id,
            },
            "protected": self.protected,
            "controls": self.controls,
        }


@dataclass
class ContextManifest:
    session_id: str
    profile: ContextProfile
    budget: dict[str, Any]
    lenses: dict[str, Any]
    items: list[ContextItem]
    flags: dict[str, Any]
    actions: dict[str, Any]
    generated_at: str
    estimation: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        categories = []
        session_tokens = max(1, int(self.lenses["session"].get("used_tokens") or 0))
        for category_id in CONTEXT_CATEGORY_IDS:
            rows = [item for item in self.items if item.category == category_id]
            used = sum(item.tokens_estimated for item in rows)
            categories.append(
                {
                    "id": category_id,
                    "label": category_id.replace("_", " / ").title(),
                    "used_tokens": used,
                    "percent_of_session": round((used / session_tokens) * 100, 1),
                    "trust": (
                        "mixed"
                        if {item.trust for item in rows} == {"trusted", "untrusted"}
                        else next(iter({item.trust for item in rows}), "trusted")
                    ),
                    "items": [item.to_dict() for item in rows],
                }
            )
        return {
            "session_id": self.session_id,
            "context_profile": self.profile.to_dict(),
            "budget": self.budget,
            "lenses": self.lenses,
            "categories": categories,
            "flags": self.flags,
            "actions": self.actions,
            "generated_at": self.generated_at,
            "estimation": self.estimation,
        }
