import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as database
import routes.task.task_routes as task_routes


def _client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(task_routes, "SessionLocal", TestSession)
    monkeypatch.setattr(task_routes, "get_current_user", lambda request: "alice")
    scheduler = MagicMock()
    scheduler.ensure_defaults = AsyncMock()
    scheduler.pop_notifications.return_value = []
    app = FastAPI()
    app.include_router(task_routes.setup_task_routes(scheduler))
    return TestClient(app), TestSession


def test_project_task_inherits_model_and_default_agent(monkeypatch):
    client, TestSession = _client(monkeypatch)
    project_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    db = TestSession()
    try:
        db.add(
            database.Project(
                id=project_id,
                owner="alice",
                name="App",
                default_workspace_path=f"projects/{project_id}/workspace",
                settings={
                    "default_model": "qwen-coder",
                    "default_crew_member_id": agent_id,
                },
            )
        )
        db.add(
            database.CrewMember(
                id=agent_id,
                owner="alice",
                project_id=project_id,
                name="Developer",
                is_project_default=True,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/tasks",
        json={
            "name": "Build",
            "prompt": "Implement the feature",
            "task_type": "llm",
            "trigger_type": "event",
            "trigger_event": "manual",
            "trigger_count": 1,
            "project_id": project_id,
        },
    )

    assert response.status_code == 200, response.text
    task = response.json()
    assert task["project_id"] == project_id
    assert task["model"] == "qwen-coder"
    assert task["crew_member_id"] == agent_id
    listed = client.get(f"/api/tasks?project_id={project_id}").json()["tasks"]
    assert [item["id"] for item in listed] == [task["id"]]


def test_project_task_rejects_foreign_project_and_agent(monkeypatch):
    client, TestSession = _client(monkeypatch)
    project_id = str(uuid.uuid4())
    bob_project_id = str(uuid.uuid4())
    bob_agent_id = str(uuid.uuid4())
    db = TestSession()
    try:
        db.add_all(
            [
                database.Project(
                    id=project_id,
                    owner="alice",
                    name="Alice",
                    default_workspace_path=f"projects/{project_id}/workspace",
                ),
                database.Project(
                    id=bob_project_id,
                    owner="bob",
                    name="Bob",
                    default_workspace_path=f"projects/{bob_project_id}/workspace",
                ),
                database.CrewMember(
                    id=bob_agent_id,
                    owner="bob",
                    project_id=bob_project_id,
                    name="Bob agent",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    body = {
        "name": "Build",
        "prompt": "Implement",
        "task_type": "llm",
        "trigger_type": "event",
        "trigger_event": "manual",
        "trigger_count": 1,
    }
    foreign_project = client.post(
        "/api/tasks",
        json={**body, "project_id": bob_project_id},
    )
    assert foreign_project.status_code == 404
    foreign_agent = client.post(
        "/api/tasks",
        json={
            **body,
            "project_id": project_id,
            "crew_member_id": bob_agent_id,
        },
    )
    assert foreign_agent.status_code == 404
