import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as database
import routes.session_routes as session_routes


def test_project_defaults_apply_to_new_session(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    project_id = str(uuid.uuid4())
    endpoint_id = str(uuid.uuid4())
    db = TestSession()
    try:
        db.add(
            database.ModelEndpoint(
                id=endpoint_id,
                name="Local",
                base_url="http://127.0.0.1:11434/v1",
                owner="alice",
                is_enabled=True,
            )
        )
        db.add(
            database.Project(
                id=project_id,
                owner="alice",
                name="App",
                default_workspace_path=f"projects/{project_id}/workspace",
                settings={
                    "default_endpoint_id": endpoint_id,
                    "default_model": "qwen-coder",
                },
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(session_routes, "SessionLocal", TestSession)
    monkeypatch.setattr(session_routes, "effective_user", lambda request: "alice")
    monkeypatch.setattr(
        session_routes,
        "_reject_raw_endpoint_url_for_non_admin",
        lambda *args, **kwargs: None,
    )
    manager = MagicMock()
    manager.create_session.side_effect = lambda **kwargs: SimpleNamespace(
        name=kwargs["name"],
        headers={},
    )
    router = session_routes.setup_session_routes(manager, {})
    endpoint = [
        route.endpoint for route in router.routes
        if route.path == "/api/session" and "POST" in route.methods
    ][-1]
    request = MagicMock()
    request.state.api_token = False

    response = endpoint(
        request=request,
        name="Project chat",
        endpoint_url="",
        model="",
        rag=None,
        skip_validation="true",
        api_key="",
        endpoint_id="",
        project_id=project_id,
    )

    call = manager.create_session.call_args.kwargs
    assert call["project_id"] == project_id
    assert call["model"] == "qwen-coder"
    assert call["endpoint_url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert response.project_id == project_id
