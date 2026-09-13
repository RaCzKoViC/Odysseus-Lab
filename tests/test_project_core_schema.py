import os
import sqlite3
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.database as database
import src.project_paths as project_paths
from src.project_scope import apply_project_scope, get_owned_project


def test_project_model_and_session_link_are_additive():
    project_table = database.Project.__table__
    session_table = database.Session.__table__

    assert project_table.name == "projects"
    assert project_table.c.owner.nullable is False
    assert session_table.c.project_id.nullable is True
    assert not session_table.c.project_id.foreign_keys


def test_project_migration_preserves_existing_sessions(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, owner TEXT, name TEXT)"
        )
        connection.execute(
            "INSERT INTO sessions (id, owner, name) VALUES ('legacy', 'alice', 'Chat')"
        )
    test_engine = create_engine(f"sqlite:///{db_path}")
    database.Project.__table__.create(bind=test_engine)
    monkeypatch.setattr(database, "engine", test_engine)

    database._migrate_project_core()
    database._migrate_project_core()

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sessions)")
        }
        row = connection.execute(
            "SELECT id, owner, project_id FROM sessions WHERE id = 'legacy'"
        ).fetchone()
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(sessions)")
        }
    assert "project_id" in columns
    assert row == ("legacy", "alice", None)
    assert "ix_sessions_project_id" in indexes
    assert "ix_sessions_owner_project" in indexes


def test_project_scope_is_strictly_owner_scoped():
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    alice_id = str(uuid.uuid4())
    bob_id = str(uuid.uuid4())
    db.add_all(
        [
            database.Project(
                id=alice_id,
                owner="alice",
                name="Alice",
                default_workspace_path="/tmp/alice",
            ),
            database.Project(
                id=bob_id,
                owner="bob",
                name="Bob",
                default_workspace_path="/tmp/bob",
            ),
        ]
    )
    db.commit()
    try:
        assert get_owned_project(db, "alice", alice_id).name == "Alice"
        with pytest.raises(Exception) as exc:
            get_owned_project(db, "alice", bob_id)
        assert getattr(exc.value, "status_code", None) == 404
    finally:
        db.close()


def test_managed_workspace_rejects_symlink_escape(monkeypatch, tmp_path):
    data = tmp_path / "data"
    projects = data / "projects"
    data.mkdir()
    projects.mkdir()
    monkeypatch.setattr(project_paths, "DATA_DIR", str(data))
    monkeypatch.setattr(project_paths, "PROJECTS_DIR", str(projects))
    project_id = str(uuid.uuid4())
    root = projects / project_id
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, root / "workspace")

    with pytest.raises(RuntimeError, match="real directory"):
        project_paths.ensure_project_workspace(project_id)


def test_apply_project_scope_preserves_unfiltered_legacy_mode():
    engine = create_engine("sqlite:///:memory:")
    database.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        query = apply_project_scope(
            db.query(database.Session),
            database.Session,
            "alice",
            None,
        )
        assert "sessions.project_id IS NULL" not in str(query.statement)
        assert "sessions.owner" in str(query.statement)
    finally:
        db.close()
