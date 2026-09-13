import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as database
import routes.project.project_routes as project_routes
import src.project_paths as project_paths
from src.memory import MemoryManager


def _client(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    database.Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    monkeypatch.setattr(project_routes, "SessionLocal", TestSession)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(project_paths, "DATA_DIR", str(data))
    monkeypatch.setattr(project_paths, "PROJECTS_DIR", str(data / "projects"))
    monkeypatch.setattr(project_routes, "ensure_project_workspace", project_paths.ensure_project_workspace)
    monkeypatch.setattr(project_routes, "cleanup_empty_project_root", project_paths.cleanup_empty_project_root)
    monkeypatch.setattr(project_routes, "list_project_workspace", project_paths.list_project_workspace)
    memory_manager = MemoryManager(str(data))

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.current_user = request.headers.get("x-test-user", "alice")
        return await call_next(request)

    app.include_router(project_routes.setup_project_routes(memory_manager=memory_manager))
    client = TestClient(app)
    client.memory_manager = memory_manager
    return client, TestSession


def test_project_crud_is_owner_scoped(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    created = client.post(
        "/api/projects",
        headers={"x-test-user": "alice"},
        json={"name": "My App", "description": "Build locally"},
    )
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["owner"] == "alice"
    assert project["status"] == "active"
    assert project["session_count"] == 0
    assert project["default_workspace_path"] == f"projects/{project['id']}/workspace"

    assert client.get(
        f"/api/projects/{project['id']}",
        headers={"x-test-user": "bob"},
    ).status_code == 404

    updated = client.patch(
        f"/api/projects/{project['id']}",
        headers={"x-test-user": "alice"},
        json={
            "name": "My App 2",
            "settings": {"default_model": "qwen", "memory_mode": "inherit"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "My App 2"
    assert updated.json()["settings"]["default_model"] == "qwen"

    archived = client.delete(
        f"/api/projects/{project['id']}",
        headers={"x-test-user": "alice"},
    )
    assert archived.status_code == 200
    assert client.get("/api/projects", headers={"x-test-user": "alice"}).json() == []
    assert len(
        client.get(
            "/api/projects?include_archived=true",
            headers={"x-test-user": "alice"},
        ).json()
    ) == 1


def test_project_rejects_unknown_settings_and_duplicate_names(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    body = {"name": "Research"}
    assert client.post("/api/projects", json=body).status_code == 201
    assert client.post("/api/projects", json={"name": "research"}).status_code == 409
    response = client.post(
        "/api/projects",
        json={"name": "Unsafe", "settings": {"api_key": "secret"}},
    )
    assert response.status_code == 422
    assert "secret" not in response.text


def test_session_assignment_cannot_cross_owners(monkeypatch, tmp_path):
    client, TestSession = _client(monkeypatch, tmp_path)
    project = client.post("/api/projects", json={"name": "App"}).json()
    db = TestSession()
    try:
        alice_session = database.Session(
            id=str(uuid.uuid4()),
            owner="alice",
            name="Alice chat",
            endpoint_url="http://localhost/v1/chat/completions",
            model="model",
        )
        bob_session = database.Session(
            id=str(uuid.uuid4()),
            owner="bob",
            name="Bob chat",
            endpoint_url="http://localhost/v1/chat/completions",
            model="model",
        )
        db.add_all([alice_session, bob_session])
        db.commit()
        alice_id, bob_id = alice_session.id, bob_session.id
    finally:
        db.close()

    attached = client.put(f"/api/projects/{project['id']}/sessions/{alice_id}")
    assert attached.status_code == 200
    assert attached.json()["project_id"] == project["id"]
    assert client.put(f"/api/projects/{project['id']}/sessions/{bob_id}").status_code == 404

    # Even a malformed legacy row cannot leak through a matching project UUID.
    db = TestSession()
    try:
        db.query(database.Session).filter(database.Session.id == bob_id).update(
            {database.Session.project_id: project["id"]},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()

    sessions = client.get(f"/api/projects/{project['id']}/sessions").json()
    assert [item["id"] for item in sessions] == [alice_id]

    detached = client.delete(f"/api/projects/{project['id']}/sessions/{alice_id}")
    assert detached.status_code == 200
    assert client.get(f"/api/projects/{project['id']}/sessions").json() == []


def test_project_files_skip_hidden_entries_and_symlinks(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    project = client.post("/api/projects", json={"name": "Files"}).json()
    workspace = project_paths.ensure_project_workspace(project["id"])
    (workspace / "visible.txt").write_text("ok", encoding="utf-8")
    (workspace / ".secret").write_text("hidden", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    payload = client.get(f"/api/projects/{project['id']}/files").json()
    assert [entry["path"] for entry in payload["entries"]] == ["visible.txt"]


def test_project_agents_are_scoped_and_can_be_default(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    project = client.post("/api/projects", json={"name": "Agents"}).json()

    created = client.post(
        f"/api/projects/{project['id']}/agents",
        json={
            "name": "Developer",
            "personality": "Build and test carefully.",
            "model": "qwen-coder",
            "enabled_tools": ["read_file", "write_file"],
            "is_default": True,
        },
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["project_id"] == project["id"]
    assert agent["is_default"] is True
    assert agent["enabled_tools"] == ["read_file", "write_file"]

    project_after = client.get(f"/api/projects/{project['id']}").json()
    assert project_after["settings"]["default_crew_member_id"] == agent["id"]
    assert client.get(
        f"/api/projects/{project['id']}/agents",
        headers={"x-test-user": "bob"},
    ).status_code == 404

    deleted = client.delete(f"/api/projects/{project['id']}/agents/{agent['id']}")
    assert deleted.status_code == 200
    project_after = client.get(f"/api/projects/{project['id']}").json()
    assert "default_crew_member_id" not in project_after["settings"]


def test_project_bundle_round_trip_is_secret_free(monkeypatch, tmp_path):
    client, TestSession = _client(monkeypatch, tmp_path)
    project = client.post("/api/projects", json={"name": "Portable"}).json()
    agent = client.post(
        f"/api/projects/{project['id']}/agents",
        json={"name": "Builder", "model": "qwen", "is_default": True},
    ).json()
    db = TestSession()
    try:
        session_id = str(uuid.uuid4())
        db.add(
            database.Session(
                id=session_id,
                owner="alice",
                project_id=project["id"],
                name="Project chat",
                endpoint_url="https://user:secret@example.test/v1",
                model="qwen",
                headers={"Authorization": "Bearer secret"},
            )
        )
        db.add(
            database.ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="user",
                content="Build the app",
            )
        )
        db.add(
            database.ScheduledTask(
                id=str(uuid.uuid4()),
                owner="alice",
                project_id=project["id"],
                crew_member_id=agent["id"],
                name="Review",
                prompt="Review progress",
                task_type="llm",
                trigger_type="schedule",
                schedule="daily",
                scheduled_time="09:00",
                endpoint_url="https://token@example.test/v1",
                webhook_token="secret-webhook",
            )
        )
        db.commit()
    finally:
        db.close()
    memory = client.memory_manager.add_entry(
        "Portable memory",
        owner="alice",
        project_id=project["id"],
    )
    client.memory_manager.save([memory])
    workspace = project_paths.ensure_project_workspace(project["id"])
    (workspace / "README.txt").write_text("project file", encoding="utf-8")

    overview = client.get(f"/api/projects/{project['id']}/overview").json()
    assert overview["metrics"]["sessions"] == 1
    assert overview["metrics"]["agents"] == 1
    assert overview["metrics"]["tasks"] == 1
    assert overview["metrics"]["memories"] == 1

    response = client.get(f"/api/projects/{project['id']}/export")

    assert response.status_code == 200, response.text
    bundle = response.json()
    serialized = response.text
    assert bundle["schema"] == "odysseus-project.v1"
    assert "secret" not in serialized
    assert "endpoint_url" not in serialized
    assert len(bundle["sessions"]) == 1
    assert len(bundle["agents"]) == 1
    assert len(bundle["tasks"]) == 1
    assert len(bundle["memories"]) == 1
    assert len(bundle["files"]) == 1

    imported = client.post("/api/projects/import", json=bundle)
    assert imported.status_code == 201, imported.text
    payload = imported.json()
    assert payload["project"]["name"].startswith("Portable (Imported")
    assert payload["imported"] == {
        "sessions": 1,
        "messages": 1,
        "agents": 1,
        "tasks": 1,
        "memories": 1,
        "files": 1,
    }
    db = TestSession()
    try:
        imported_task = db.query(database.ScheduledTask).filter(
            database.ScheduledTask.project_id == payload["project"]["id"]
        ).one()
        assert imported_task.status == "paused"
        assert imported_task.endpoint_url is None
        assert imported_task.webhook_token is None
    finally:
        db.close()


def test_project_import_rejects_traversal_file(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    bundle = {
        "schema": "odysseus-project.v1",
        "project": {"name": "Unsafe", "description": "", "settings": {}},
        "sessions": [],
        "agents": [],
        "tasks": [],
        "memories": [],
        "files": [
            {
                "path": "../escape.txt",
                "encoding": "base64",
                "content": "dGVzdA==",
            }
        ],
    }

    response = client.post("/api/projects/import", json=bundle)

    assert response.status_code == 422
    assert not (tmp_path / "escape.txt").exists()


def test_assign_existing_sessions_and_memories(monkeypatch, tmp_path):
    client, TestSession = _client(monkeypatch, tmp_path)
    project = client.post("/api/projects", json={"name": "Migration"}).json()
    session_id = str(uuid.uuid4())
    db = TestSession()
    try:
        db.add(
            database.Session(
                id=session_id,
                owner="alice",
                name="Legacy chat",
                endpoint_url="",
                model="",
            )
        )
        db.commit()
    finally:
        db.close()
    memory = client.memory_manager.add_entry("Legacy memory", owner="alice")
    client.memory_manager.save([memory])

    assigned = client.post(
        f"/api/projects/{project['id']}/assign",
        json={"session_ids": [session_id], "memory_ids": [memory["id"]]},
    )

    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned_sessions"] == 1
    assert assigned.json()["assigned_memories"] == 1
    db = TestSession()
    try:
        assert db.get(database.Session, session_id).project_id == project["id"]
    finally:
        db.close()
    stored = client.memory_manager.load_all()
    assert stored[0]["project_id"] == project["id"]
