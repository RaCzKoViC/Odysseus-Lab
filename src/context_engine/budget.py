"""One route-aware budget allocator for chat and agent context shaping."""

from __future__ import annotations

import json
import inspect
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from src.context_budget import DEFAULT_BUDGET, DEFAULT_HARD_MAX


@dataclass(frozen=True)
class RouteBudgetPlan:
    model: str
    context_length: int
    context_known: bool
    input_budget: int
    output_reserve: int
    schema_tokens: int
    message_window: int
    tokens_before: int
    tokens_after: int
    messages_before: int
    messages_after: int
    explicit_soft_cap: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "context_length": self.context_length,
            "context_known": self.context_known,
            "input_budget": self.input_budget,
            "output_reserve": self.output_reserve,
            "schema_tokens": self.schema_tokens,
            "message_window": self.message_window,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "messages_before": self.messages_before,
            "messages_after": self.messages_after,
            "explicit_soft_cap": self.explicit_soft_cap,
        }


def estimate_schema_tokens(schemas: Optional[Iterable[dict[str, Any]]]) -> int:
    """Estimate provider tool/MCP schema overhead without a provider tokenizer."""
    if not schemas:
        return 0
    try:
        serialized = json.dumps(list(schemas), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return 0
    return int(len(serialized) * 0.3) + 4


def shape_messages_for_route(
    messages: list[dict[str, Any]],
    *,
    endpoint_url: str,
    model: str,
    fallback_context_length: int = 0,
    output_reserve: int = 512,
    schemas: Optional[Iterable[dict[str, Any]]] = None,
    use_soft_budget: bool = False,
    configured_soft_budget: int = DEFAULT_BUDGET,
    hard_max: int = DEFAULT_HARD_MAX,
    trim_function=None,
    context_length_override: Optional[int] = None,
    context_known_override: Optional[bool] = None,
) -> tuple[list[dict[str, Any]], RouteBudgetPlan]:
    """Trim one route request and return the exact heuristic allocation ledger."""
    from src import context_budget as budget_module
    from src import context_compactor as compactor_module
    from src import model_context

    if context_length_override is None:
        discovered, known = model_context.get_context_length_known(endpoint_url, model)
    else:
        discovered = context_length_override
        known = bool(context_known_override)
    context_length = int(discovered or fallback_context_length or 0)
    if not context_length:
        context_length = int(fallback_context_length or 128000)
    output_reserve = max(0, int(output_reserve or 0))
    schema_tokens = estimate_schema_tokens(schemas)
    explicit = budget_module.budget_is_explicit(configured_soft_budget)
    if use_soft_budget:
        budget_context = model_context.budget_context_for_model(
            endpoint_url,
            model,
            fallback=fallback_context_length,
        )
        input_budget = budget_module.compute_input_token_budget(
            configured_soft_budget,
            budget_context,
            explicit,
            hard_max=max(1, int(hard_max or DEFAULT_HARD_MAX)),
        )
    else:
        input_budget = context_length

    # Preserve the route's context window as the trimmer's first argument and
    # reserve both output and schema overhead inside it. This keeps historical
    # trim extension points stable while making provider tools part of the same
    # allocation.
    message_window = input_budget
    combined_reserve = output_reserve + schema_tokens
    before_tokens = int(model_context.estimate_tokens(messages))
    trimmer = trim_function or compactor_module.trim_for_context
    parameters = inspect.signature(trimmer).parameters
    if "reserve_tokens" in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        shaped = trimmer(
            list(messages),
            message_window,
            reserve_tokens=combined_reserve,
        )
    else:
        shaped = trimmer(list(messages), message_window)
    plan = RouteBudgetPlan(
        model=model or "",
        context_length=context_length,
        context_known=bool(known),
        input_budget=input_budget,
        output_reserve=output_reserve,
        schema_tokens=schema_tokens,
        message_window=message_window,
        tokens_before=before_tokens,
        tokens_after=int(model_context.estimate_tokens(shaped)),
        messages_before=len(messages),
        messages_after=len(shaped),
        explicit_soft_cap=explicit,
    )
    return shaped, plan
