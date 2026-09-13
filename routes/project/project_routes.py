"""Owner-scoped Project Core CRUD and conversation assignment."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func

from core.database import Project, Session as DbSession, SessionLocal, utcnow_naive
from src.auth_helpers import require_user
from src.owner_identity import DEFAULT_LOCAL_OWNER
from src.project_paths import (
    MAX_FILE_ENTRIES,
    cleanup_empty_project_root,
    ensure_project_workspace,
    list_project_workspace,
)
from src.project_scope import get_owned_project, project_query, storage_owner


ALLOWED_SETTINGS = {
    "default_endpoint_id",
    "default_model",
    "default_crew_member_id",
    "memory_mode",
    "instructions",
}
MEMORY_MODES = {"inherit", "project_only", "project_plus_global"}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    status: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


def _owner(request: Request) -> str:
    return storage_owner(require_user(request))


def _validate_settings(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Project settings must be an object")
    unknown = sorted(set(raw) - ALLOWED_SETTINGS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported project setting(s): {', '.join(unknown)}",
        )
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"Project setting {key} must be text")
        value = value.strip()
        if key == "memory_mode" and value not in MEMORY_MODES:
            raise HTTPException(status_code=422, detail="Invalid project memory mode")
        if key == "instructions" and len(value) > 8000:
            raise HTTPException(status_code=422, detail="Project instructions are too long")
        if key != "instructions" and len(value) > 500:
            raise HTTPException(status_code=422, detail=f"Project setting {key} is too long")
        clean[key] = value
    return clean


def _serialize(project: Project, *, session_count: Optional[int] = None) -> dict[str, Any]:
    payload = project.to_dict()
    if session_count is not None:
        payload["session_count"] = session_count
    return payload


def _session_for_owner(db, owner: str, session_id: str) -> DbSession:
    query = db.query(DbSession).filter(DbSession.id == session_id)
    if owner == DEFAULT_LOCAL_OWNER:
        query = query.filter(
            (DbSession.owner == None) | (DbSession.owner == DEFAULT_LOCAL_OWNER)  # noqa: E711
        )
    else:
        query = query.filter(DbSession.owner == owner)
    session = query.first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _sync_cached_session(session_id: str, project_id: Optional[str]) -> None:
    from core.models import get_session_manager

    manager = get_session_manager()
    if manager is None:
        return
    cached = getattr(manager, "sessions", {}).get(session_id)
    if cached is not None:
        cached.project_id = project_id


def setup_project_routes() -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])

    @router.get("")
    def list_projects(request: Request, include_archived: bool = Query(default=False)):
        owner = _owner(request)
        db = SessionLocal()
        try:
            projects = project_query(
                db,
                owner,
                include_archived=include_archived,
            ).order_by(Project.sort_order, Project.updated_at.desc()).all()
            counts = dict(
                db.query(DbSession.project_id, func.count(DbSession.id))
                .filter(DbSession.project_id.in_([project.id for project in projects]))
                .group_by(DbSession.project_id)
                .all()
            ) if projects else {}
            return [_serialize(project, session_count=counts.get(project.id, 0)) for project in projects]
        finally:
            db.close()

    @router.post("", status_code=201)
    def create_project(request: Request, body: ProjectCreate):
        owner = _owner(request)
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Project name is required")
        settings = _validate_settings(body.settings)
        project_id = str(uuid.uuid4())
        workspace = ensure_project_workspace(project_id)
        db = SessionLocal()
        try:
            duplicate = (
                db.query(Project.id)
                .filter(Project.owner == owner, func.lower(Project.name) == name.casefold())
                .first()
            )
            if duplicate:
                raise HTTPException(status_code=409, detail="A project with this name already exists")
            project = Project(
                id=project_id,
                owner=owner,
                name=name,
                description=body.description.strip(),
                status="active",
                settings=settings,
                default_workspace_path=str(workspace),
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            return _serialize(project, session_count=0)
        except HTTPException:
            db.rollback()
            cleanup_empty_project_root(project_id)
            raise
        except Exception:
            db.rollback()
            cleanup_empty_project_root(project_id)
            raise HTTPException(status_code=500, detail="Failed to create project")
        finally:
            db.close()

    @router.get("/{project_id}")
    def get_project(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            count = db.query(func.count(DbSession.id)).filter(
                DbSession.project_id == project.id
            ).scalar() or 0
            return _serialize(project, session_count=count)
        finally:
            db.close()

    @router.patch("/{project_id}")
    def update_project(request: Request, project_id: str, body: ProjectUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            values = body.model_dump(exclude_unset=True)
            if "name" in values:
                name = (values["name"] or "").strip()
                if not name:
                    raise HTTPException(status_code=422, detail="Project name is required")
                duplicate = (
                    db.query(Project.id)
                    .filter(
                        Project.owner == owner,
                        Project.id != project.id,
                        func.lower(Project.name) == name.casefold(),
                    )
                    .first()
                )
                if duplicate:
                    raise HTTPException(status_code=409, detail="A project with this name already exists")
                project.name = name
            if "description" in values:
                project.description = (values["description"] or "").strip()
            if "status" in values:
                if values["status"] not in {"active", "archived"}:
                    raise HTTPException(status_code=422, detail="Invalid project status")
                project.status = values["status"]
            if "settings" in values:
                project.settings = _validate_settings(values["settings"] or {})
            project.updated_at = utcnow_naive()
            db.commit()
            db.refresh(project)
            return _serialize(project)
        except HTTPException:
            db.rollback()
            raise
        finally:
            db.close()

    @router.delete("/{project_id}")
    def archive_project(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            project.status = "archived"
            project.updated_at = utcnow_naive()
            db.commit()
            return {"ok": True, "id": project.id, "status": "archived"}
        finally:
            db.close()

    @router.get("/{project_id}/overview")
    def project_overview(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            sessions = (
                db.query(DbSession)
                .filter(DbSession.project_id == project.id)
                .order_by(DbSession.last_message_at.desc(), DbSession.updated_at.desc())
                .limit(5)
                .all()
            )
            return {
                "project": _serialize(project, session_count=(
                    db.query(func.count(DbSession.id))
                    .filter(DbSession.project_id == project.id)
                    .scalar() or 0
                )),
                "recent_sessions": [
                    {
                        "id": session.id,
                        "name": session.name,
                        "model": session.model,
                        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                    }
                    for session in sessions
                ],
            }
        finally:
            db.close()

    @router.get("/{project_id}/sessions")
    def project_sessions(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            sessions = (
                db.query(DbSession)
                .filter(DbSession.project_id == project.id, DbSession.archived == False)  # noqa: E712
                .order_by(DbSession.last_message_at.desc(), DbSession.updated_at.desc())
                .all()
            )
            return [
                {
                    "id": session.id,
                    "name": session.name,
                    "model": session.model,
                    "folder": session.folder,
                    "project_id": session.project_id,
                    "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                }
                for session in sessions
            ]
        finally:
            db.close()

    @router.put("/{project_id}/sessions/{session_id}")
    def attach_session(request: Request, project_id: str, session_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id)
            session = _session_for_owner(db, owner, session_id)
            session.project_id = project.id
            session.updated_at = utcnow_naive()
            db.commit()
            _sync_cached_session(session.id, project.id)
            return {"ok": True, "session_id": session.id, "project_id": project.id}
        finally:
            db.close()

    @router.delete("/{project_id}/sessions/{session_id}")
    def detach_session(request: Request, project_id: str, session_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            session = _session_for_owner(db, owner, session_id)
            if session.project_id != project.id:
                raise HTTPException(status_code=404, detail="Session not found in project")
            session.project_id = None
            session.updated_at = utcnow_naive()
            db.commit()
            _sync_cached_session(session.id, None)
            return {"ok": True, "session_id": session.id, "project_id": None}
        finally:
            db.close()

    @router.get("/{project_id}/files")
    def project_files(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
        finally:
            db.close()
        entries = list_project_workspace(project.id)
        return {
            "project_id": project.id,
            "workspace": project.default_workspace_path,
            "entries": entries,
            "truncated": len(entries) >= MAX_FILE_ENTRIES,
        }

    return router
