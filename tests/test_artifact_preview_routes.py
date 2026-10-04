"""The artifact preview endpoint and the policy that makes it safe.

An artifact has to be able to run its own scripts, which the app's own
Content-Security-Policy forbids - so the preview is served from its own path
with its own policy, into a frame with no same-origin privilege. These tests
pin both halves of that bargain: the permissive policy is only on this path,
and the markup only comes back to whoever stored it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.middleware import SecurityHeadersMiddleware
from routes.artifact import setup_artifact_routes
from src.artifacts import preview_store


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(setup_artifact_routes())
    preview_store._clear()
    with TestClient(app) as test_client:
        yield test_client
    preview_store._clear()


def test_stored_markup_comes_back_as_a_document(client):
    page = "<!DOCTYPE html><html><body><h1>Hi</h1></body></html>"
    created = client.post("/api/artifact/preview", json={"html": page})
    assert created.status_code == 200
    token = created.json()["token"]
    assert created.json()["url"] == f"/api/artifact/preview/{token}"

    served = client.get(f"/api/artifact/preview/{token}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/html")
    assert "<h1>Hi</h1>" in served.text
    # Served copies carry the beacon; the artifact's own source does not.
    assert "__odysseusArtifact" in served.text


def test_the_preview_path_carries_its_own_policy(client):
    token = client.post("/api/artifact/preview", json={"html": "<p>x</p>"}).json()["token"]
    served = client.get(f"/api/artifact/preview/{token}")
    csp = served.headers["content-security-policy"]

    # What makes the artifact work: its own inline script may run.
    assert "script-src 'unsafe-inline'" in csp
    # What keeps it harmless: it may not call home, submit anywhere, or be
    # framed by anyone but this app.
    assert "connect-src 'none'" in csp
    assert "form-action 'none'" in csp
    assert "frame-ancestors 'self'" in csp
    # Opaque origin even when opened top-level ("Open in tab"): the sandbox
    # comes with the response, and it never grants allow-same-origin.
    sandbox = next(d.strip() for d in csp.split(";") if d.strip().startswith("sandbox"))
    assert "allow-scripts" in sandbox
    assert "allow-same-origin" not in sandbox
    assert served.headers["x-frame-options"] == "SAMEORIGIN"
    assert served.headers["cache-control"] == "no-store"


def test_other_paths_keep_the_strict_policy(client):
    """The relaxed policy is for this path and no other."""
    other = client.post("/api/artifact/preview", json={"html": "<p>x</p>"})
    csp = other.headers["content-security-policy"]
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]


def test_an_empty_artifact_is_refused(client):
    assert client.post("/api/artifact/preview", json={"html": "   "}).status_code == 400


def test_an_oversized_artifact_is_refused(client):
    huge = "<p>" + ("x" * (2 * 1024 * 1024 + 10)) + "</p>"
    assert client.post("/api/artifact/preview", json={"html": huge}).status_code == 413


def test_an_unknown_or_expired_token_is_not_found(client):
    assert client.get("/api/artifact/preview/nope").status_code == 404


def test_previews_belong_to_whoever_stored_them():
    """One user's preview URL does not render for another."""
    store = type(preview_store)()
    token = store.put("<p>mine</p>", owner="alice")
    assert store.get(token, owner="alice") == "<p>mine</p>"
    assert store.get(token, owner="bob") is None


def test_the_store_expires_and_stays_bounded():
    import time

    from src.artifacts import preview_store as module_store
    from src.artifacts.preview_store import PreviewStore

    store = PreviewStore()
    token = store.put("<p>x</p>", owner="alice")
    entry = store._entries[token]
    entry.created_at = time.time() - (60 * 60 * 2)
    assert store.get(token, owner="alice") is None

    for _ in range(60):
        store.put("<p>x</p>", owner="alice")
    assert store._size() <= 40
    assert module_store is not store


# ── The library: what the user chose to keep ──────────────────────────────


@pytest.fixture
def library_client(tmp_path, monkeypatch):
    """A client with its own database file, so the library tests never see
    the developer's own saved artifacts.

    Isolation goes through monkeypatch rather than importlib.reload: reloading
    core.database (and the auth/owner helpers) left the whole process pointing
    at this test's temporary engine and at fresh model classes, so tests that
    ran later (calendar, manage_tasks owner scope, session image cleanup)
    failed against the wrong database. monkeypatch undoes everything here.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import core.database as database

    # The library is owner-scoped through the same helper the rest of the
    # Lab uses, which 401s when it cannot name an owner. Local no-login mode
    # is what gives it one, and is how the app actually runs here. The
    # AUTH_ENABLED flag is read at call time, so no module reload is needed.
    monkeypatch.setenv("AUTH_ENABLED", "false")

    engine = create_engine(
        f"sqlite:///{tmp_path / 'lib.db'}",
        connect_args={"check_same_thread": False},
    )
    database.SavedArtifact.__table__.create(bind=engine)
    monkeypatch.setattr(
        database,
        "SessionLocal",
        sessionmaker(autocommit=False, autoflush=False, bind=engine),
    )

    app = FastAPI()
    app.include_router(setup_artifact_routes())
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_an_artifact_is_kept_only_when_it_is_saved(library_client):
    assert library_client.get("/api/artifacts").json()["artifacts"] == []

    saved = library_client.post(
        "/api/artifacts",
        json={"title": "Notatnik", "kind": "html", "lang": "html", "code": "<h1>x</h1>"},
    )
    assert saved.status_code == 200
    assert saved.json()["replaced"] is False

    rows = library_client.get("/api/artifacts").json()["artifacts"]
    assert [r["title"] for r in rows] == ["Notatnik"]


def test_saving_the_same_title_again_revises_it(library_client):
    library_client.post("/api/artifacts", json={"title": "Notatnik", "code": "v1"})
    again = library_client.post("/api/artifacts", json={"title": "Notatnik", "code": "v2"})
    assert again.json()["replaced"] is True

    rows = library_client.get("/api/artifacts").json()["artifacts"]
    assert len(rows) == 1
    assert rows[0]["code"] == "v2"


def test_an_empty_artifact_is_not_saved(library_client):
    assert library_client.post("/api/artifacts", json={"title": "x", "code": " "}).status_code == 400


def test_selected_artifacts_are_deleted_and_the_rest_stay(library_client):
    ids = []
    for title in ("one", "two", "three"):
        ids.append(library_client.post("/api/artifacts", json={"title": title, "code": title}).json()["artifact"]["id"])

    removed = library_client.post("/api/artifacts/delete", json={"ids": ids[:2]})
    assert removed.json()["deleted"] == 2

    left = [r["title"] for r in library_client.get("/api/artifacts").json()["artifacts"]]
    assert left == ["three"]


def test_deleting_nothing_is_allowed(library_client):
    assert library_client.post("/api/artifacts/delete", json={"ids": []}).json()["deleted"] == 0


def test_a_saved_artifact_can_be_edited_in_place(library_client):
    created = library_client.post("/api/artifacts", json={"title": "Notatnik", "code": "old"}).json()["artifact"]
    updated = library_client.patch(f"/api/artifacts/{created['id']}", json={"code": "new", "title": "Notatnik 2"})
    assert updated.status_code == 200
    assert updated.json()["artifact"]["code"] == "new"
    assert updated.json()["artifact"]["title"] == "Notatnik 2"


def test_editing_something_that_is_not_there_is_a_404(library_client):
    assert library_client.patch("/api/artifacts/nope", json={"code": "x"}).status_code == 404
