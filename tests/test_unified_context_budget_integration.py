from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_paths_use_shared_route_allocator():
    helpers = (ROOT / "routes" / "chat_helpers.py").read_text(encoding="utf-8")
    routes = (ROOT / "routes" / "chat_routes.py").read_text(encoding="utf-8")

    assert "from src.context_engine.budget import shape_messages_for_route" in helpers
    assert "from src.context_engine.budget import shape_messages_for_route" in routes
    assert "messages, route_budget_plan = shape_messages_for_route(" in helpers
    assert "request_messages, budget_plan = shape_messages_for_route(" in routes
    assert '"budget_plans": {}' in routes


def test_agent_allocator_accounts_for_concrete_route_schemas():
    source = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")

    assert "from src.context_engine.budget import shape_messages_for_route" in source
    assert "_schemas_for_route_state(_route_state)" in source
    assert "schemas=schemas" in source
    assert '"context_budget_plan"' in source
    assert "_route_budget_plans" in source


def test_old_direct_trimmers_are_removed_from_chat_and_agent():
    helpers = (ROOT / "routes" / "chat_helpers.py").read_text(encoding="utf-8")
    routes = (ROOT / "routes" / "chat_routes.py").read_text(encoding="utf-8")
    agent = (ROOT / "src" / "agent_loop.py").read_text(encoding="utf-8")

    assert "messages = trim_for_context(messages, context_length)" not in helpers
    assert "request_messages = trim_for_context(candidate_messages" not in routes
    assert "compute_input_token_budget(" not in agent
