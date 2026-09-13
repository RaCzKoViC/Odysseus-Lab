import src.context_engine.budget as budget_module
import src.model_context as model_context
from src.context_engine.budget import estimate_schema_tokens, shape_messages_for_route


def _messages(chars=12000):
    return [
        {"role": "system", "content": "Stable policy"},
        {"role": "user", "content": "x" * chars},
    ]


def test_schema_tokens_reduce_route_message_window(monkeypatch):
    monkeypatch.setattr(
        model_context,
        "get_context_length_known",
        lambda endpoint, model: (8192, True),
    )
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file " * 100,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    shaped, plan = shape_messages_for_route(
        _messages(),
        endpoint_url="http://localhost/v1",
        model="local",
        schemas=schemas,
        output_reserve=1024,
    )

    assert plan.schema_tokens == estimate_schema_tokens(schemas)
    assert plan.message_window == 8192
    assert plan.tokens_after <= (
        plan.message_window - plan.output_reserve - plan.schema_tokens
    )
    assert shaped[-1]["role"] == "user"


def test_agent_unknown_window_keeps_conservative_soft_budget(monkeypatch):
    monkeypatch.setattr(
        model_context,
        "get_context_length_known",
        lambda endpoint, model: (128000, False),
    )
    monkeypatch.setattr(
        model_context,
        "budget_context_for_model",
        lambda endpoint, model, fallback=0: 0,
    )

    _, plan = shape_messages_for_route(
        _messages(),
        endpoint_url="http://localhost/v1",
        model="unknown",
        use_soft_budget=True,
        configured_soft_budget=6000,
        hard_max=200000,
        output_reserve=1024,
    )

    assert plan.context_known is False
    assert plan.input_budget == 6000
    assert plan.message_window == 6000


def test_agent_known_window_scales_from_same_allocator(monkeypatch):
    monkeypatch.setattr(
        model_context,
        "get_context_length_known",
        lambda endpoint, model: (16384, True),
    )
    monkeypatch.setattr(
        model_context,
        "budget_context_for_model",
        lambda endpoint, model, fallback=0: 16384,
    )

    _, plan = shape_messages_for_route(
        _messages(),
        endpoint_url="http://localhost/v1",
        model="known",
        use_soft_budget=True,
        configured_soft_budget=6000,
        output_reserve=1024,
    )

    assert plan.input_budget == int(16384 * 0.85)
    assert plan.explicit_soft_cap is False


def test_explicit_budget_is_honored(monkeypatch):
    monkeypatch.setattr(
        model_context,
        "get_context_length_known",
        lambda endpoint, model: (16384, True),
    )
    monkeypatch.setattr(
        model_context,
        "budget_context_for_model",
        lambda endpoint, model, fallback=0: 16384,
    )

    _, plan = shape_messages_for_route(
        _messages(),
        endpoint_url="http://localhost/v1",
        model="known",
        use_soft_budget=True,
        configured_soft_budget=4096,
        output_reserve=512,
    )

    assert plan.input_budget == 4096
    assert plan.explicit_soft_cap is True
