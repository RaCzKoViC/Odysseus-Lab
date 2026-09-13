"""Owner-scoped Project Core CRUD and conversation assignment."""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func

from core.database import (
    CrewMember,
    Project,
    Session as DbSession,
    SessionLocal,
    utcnow_naive,
)
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


class ProjectAgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    personality: str = Field(default="", max_length=8000)
    model: str = Field(default="", max_length=500)
    endpoint_url: str = Field(default="", max_length=2000)
    greeting: str = Field(default="", max_length=2000)
    enabled_tools: list[str] = Field(default_factory=list)
    is_default: bool = False


class ProjectAgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    personality: Optional[str] = Field(default=None, max_length=8000)
    model: Optional[str] = Field(default=None, max_length=500)
    endpoint_url: Optional[str] = Field(default=None, max_length=2000)
    greeting: Optional[str] = Field(default=None, max_length=2000)
    enabled_tools: Optional[list[str]] = None
    is_default: Optional[bool] = None


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
    query = _sessions_for_owner(db.query(DbSession), owner).filter(
        DbSession.id == session_id
    )
    session = query.first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _sessions_for_owner(query, owner: str):
    if owner == DEFAULT_LOCAL_OWNER:
        return query.filter(
            (DbSession.owner == None) | (DbSession.owner == DEFAULT_LOCAL_OWNER)  # noqa: E711
        )
    return query.filter(DbSession.owner == owner)


def _sync_cached_session(session_id: str, project_id: Optional[str]) -> None:
    from core.models import get_session_manager

    manager = get_session_manager()
    if manager is None:
        return
    cached = getattr(manager, "sessions", {}).get(session_id)
    if cached is not None:
        cached.project_id = project_id


def _project_agent_query(db, owner: str, project_id: str):
    return db.query(CrewMember).filter(
        CrewMember.owner == owner,
        CrewMember.project_id == project_id,
        CrewMember.is_default_assistant == False,  # noqa: E712
    )


def _validate_tools(tools: list[str]) -> list[str]:
    if len(tools) > 100:
        raise HTTPException(status_code=422, detail="Too many agent tools")
    clean = []
    for tool in tools:
        if not isinstance(tool, str) or not tool.strip() or len(tool.strip()) > 120:
            raise HTTPException(status_code=422, detail="Invalid agent tool name")
        value = tool.strip()
        if value not in clean:
            clean.append(value)
    return clean


def _serialize_agent(agent: CrewMember) -> dict[str, Any]:
    try:
        tools = json.loads(agent.enabled_tools or "[]")
    except (TypeError, json.JSONDecodeError):
        tools = []
    return {
        "id": agent.id,
        "project_id": agent.project_id,
        "name": agent.name,
        "personality": agent.personality or "",
        "model": agent.model or "",
        "endpoint_url": agent.endpoint_url or "",
        "greeting": agent.greeting or "",
        "enabled_tools": tools if isinstance(tools, list) else [],
        "is_default": bool(agent.is_project_default),
        "is_active": bool(agent.is_active),
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


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
                _sessions_for_owner(
                    db.query(DbSession.project_id, func.count(DbSession.id)),
                    owner,
                )
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
        ensure_project_workspace(project_id)
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
                default_workspace_path=f"projects/{project_id}/workspace",
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
            count = _sessions_for_owner(
                db.query(func.count(DbSession.id)), owner
            ).filter(DbSession.project_id == project.id).scalar() or 0
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
                settings = _validate_settings(values["settings"] or {})
                default_agent = settings.get("default_crew_member_id")
                if default_agent and not _project_agent_query(
                    db, owner, project.id
                ).filter(CrewMember.id == default_agent).first():
                    raise HTTPException(status_code=422, detail="Default project agent not found")
                project.settings = settings
            project.updated_at = utcnow_naive()
            db.commit()
            db.refresh(project)
            return _serialize(project)
        except HTTPException:
            db.rollback()
            raise
        finally:
            db.close()

    @router.get("/{project_id}/effective-settings")
    def effective_project_settings(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            settings = project.settings or {}
            return {
                "project_id": project.id,
                "default_endpoint_id": settings.get("default_endpoint_id") or "",
                "default_model": settings.get("default_model") or "",
                "default_crew_member_id": settings.get("default_crew_member_id") or "",
                "memory_mode": settings.get("memory_mode") or "inherit",
                "instructions": settings.get("instructions") or "",
            }
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
                _sessions_for_owner(db.query(DbSession), owner)
                .filter(DbSession.project_id == project.id)
                .order_by(DbSession.last_message_at.desc(), DbSession.updated_at.desc())
                .limit(5)
                .all()
            )
            return {
                "project": _serialize(project, session_count=(
                    _sessions_for_owner(db.query(func.count(DbSession.id)), owner)
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
                _sessions_for_owner(db.query(DbSession), owner)
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
        workspace = ensure_project_workspace(project.id)
        entries = list_project_workspace(project.id)
        return {
            "project_id": project.id,
            "workspace": str(workspace),
            "entries": entries,
            "truncated": len(entries) >= MAX_FILE_ENTRIES,
        }

    @router.get("/{project_id}/agents")
    def list_project_agents(request: Request, project_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            agents = _project_agent_query(db, owner, project.id).order_by(
                CrewMember.is_project_default.desc(),
                CrewMember.sort_order,
                CrewMember.created_at,
            ).all()
            return [_serialize_agent(agent) for agent in agents]
        finally:
            db.close()

    @router.post("/{project_id}/agents", status_code=201)
    def create_project_agent(request: Request, project_id: str, body: ProjectAgentCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id)
            tools = _validate_tools(body.enabled_tools)
            if body.is_default:
                _project_agent_query(db, owner, project.id).update(
                    {CrewMember.is_project_default: False},
                    synchronize_session=False,
                )
            agent = CrewMember(
                id=str(uuid.uuid4()),
                owner=owner,
                project_id=project.id,
                name=body.name.strip(),
                personality=body.personality.strip(),
                model=body.model.strip() or None,
                endpoint_url=body.endpoint_url.strip() or None,
                greeting=body.greeting.strip() or None,
                enabled_tools=json.dumps(tools),
                is_active=True,
                is_default_assistant=False,
                is_project_default=body.is_default,
            )
            db.add(agent)
            db.flush()
            if body.is_default:
                settings = dict(project.settings or {})
                settings["default_crew_member_id"] = agent.id
                project.settings = settings
            db.commit()
            db.refresh(agent)
            return _serialize_agent(agent)
        finally:
            db.close()

    @router.patch("/{project_id}/agents/{agent_id}")
    def update_project_agent(
        request: Request,
        project_id: str,
        agent_id: str,
        body: ProjectAgentUpdate,
    ):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id)
            agent = _project_agent_query(db, owner, project.id).filter(
                CrewMember.id == agent_id
            ).first()
            if agent is None:
                raise HTTPException(status_code=404, detail="Project agent not found")
            values = body.model_dump(exclude_unset=True)
            for field in ("name", "personality", "model", "endpoint_url", "greeting"):
                if field in values:
                    value = (values[field] or "").strip()
                    if field == "name" and not value:
                        raise HTTPException(status_code=422, detail="Agent name is required")
                    setattr(agent, field, value or None)
            if "enabled_tools" in values:
                agent.enabled_tools = json.dumps(_validate_tools(values["enabled_tools"] or []))
            if values.get("is_default") is True:
                _project_agent_query(db, owner, project.id).update(
                    {CrewMember.is_project_default: False},
                    synchronize_session=False,
                )
                agent.is_project_default = True
                settings = dict(project.settings or {})
                settings["default_crew_member_id"] = agent.id
                project.settings = settings
            elif values.get("is_default") is False:
                agent.is_project_default = False
                settings = dict(project.settings or {})
                if settings.get("default_crew_member_id") == agent.id:
                    settings.pop("default_crew_member_id", None)
                    project.settings = settings
            agent.updated_at = utcnow_naive()
            db.commit()
            db.refresh(agent)
            return _serialize_agent(agent)
        finally:
            db.close()

    @router.delete("/{project_id}/agents/{agent_id}")
    def delete_project_agent(request: Request, project_id: str, agent_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            project = get_owned_project(db, owner, project_id, include_archived=True)
            agent = _project_agent_query(db, owner, project.id).filter(
                CrewMember.id == agent_id
            ).first()
            if agent is None:
                raise HTTPException(status_code=404, detail="Project agent not found")
            settings = dict(project.settings or {})
            if settings.get("default_crew_member_id") == agent.id:
                settings.pop("default_crew_member_id", None)
                project.settings = settings
            db.delete(agent)
            db.commit()
            return {"ok": True, "id": agent_id}
        finally:
            db.close()

    return router
