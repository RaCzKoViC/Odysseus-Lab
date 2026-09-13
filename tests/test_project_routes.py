import uuid

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.database as database
import routes.project.project_routes as project_routes
import src.project_paths as project_paths


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

    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.current_user = request.headers.get("x-test-user", "alice")
        return await call_next(request)

    app.include_router(project_routes.setup_project_routes())
    return TestClient(app), TestSession


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
