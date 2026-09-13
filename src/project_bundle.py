"""Portable, secret-free Project Core export/import bundles."""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException

from core.database import (
    ChatMessage,
    CrewMember,
    ScheduledTask,
    Session,
    utcnow_naive,
)
from src.owner_identity import DEFAULT_LOCAL_OWNER
from src.project_paths import ensure_project_workspace, list_project_workspace


SCHEMA = "odysseus-project.v1"
MAX_BUNDLE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES_BYTES = 10 * 1024 * 1024
MAX_ITEMS = 5000


def _owner_query(query, model, owner: str):
    if owner == DEFAULT_LOCAL_OWNER:
        return query.filter(
            (model.owner == None) | (model.owner == DEFAULT_LOCAL_OWNER)  # noqa: E711
        )
    return query.filter(model.owner == owner)


def _safe_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(422, "Project bundle contains non-text data")
    if len(value) > limit:
        raise HTTPException(413, "Project bundle text field is too large")
    return value


def export_project_bundle(db, project, owner: str, memory_manager=None) -> dict[str, Any]:
    sessions = _owner_query(
        db.query(Session), Session, owner
    ).filter(Session.project_id == project.id).all()
    session_ids = [session.id for session in sessions]
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id.in_(session_ids))
        .order_by(ChatMessage.timestamp)
        .all()
        if session_ids else []
    )
    messages_by_session: dict[str, list[dict[str, Any]]] = {
        session_id: [] for session_id in session_ids
    }
    for message in messages:
        messages_by_session.setdefault(message.session_id, []).append(
            {
                "role": message.role,
                "content": message.content,
                "timestamp": message.timestamp.isoformat() if message.timestamp else None,
            }
        )

    agents = _owner_query(
        db.query(CrewMember), CrewMember, owner
    ).filter(CrewMember.project_id == project.id).all()
    tasks = _owner_query(
        db.query(ScheduledTask), ScheduledTask, owner
    ).filter(ScheduledTask.project_id == project.id).all()
    if memory_manager is None:
        memories = []
    elif owner == DEFAULT_LOCAL_OWNER:
        memories = [
            entry for entry in memory_manager.load_all()
            if entry.get("project_id") == project.id
            and entry.get("owner") in (None, DEFAULT_LOCAL_OWNER)
        ]
    else:
        memories = memory_manager.load(
            owner=owner,
            project_id=project.id,
            mode="project_only",
        )

    workspace = ensure_project_workspace(project.id)
    files = []
    total = 0
    for entry in list_project_workspace(project.id):
        if entry["type"] != "file":
            continue
        path = workspace / entry["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            continue
        size = int(entry.get("size") or 0)
        if size > MAX_FILE_BYTES or total + size > MAX_FILES_BYTES:
            continue
        data = path.read_bytes()
        total += len(data)
        files.append(
            {
                "path": entry["path"],
                "encoding": "base64",
                "content": base64.b64encode(data).decode("ascii"),
            }
        )

    bundle = {
        "schema": SCHEMA,
        "project": {
            "name": project.name,
            "description": project.description or "",
            "settings": project.settings or {},
        },
        "sessions": [
            {
                "source_id": session.id,
                "name": session.name,
                "model": session.model,
                "rag": bool(session.rag),
                "folder": session.folder,
                "mode": session.mode,
                "messages": messages_by_session.get(session.id, []),
            }
            for session in sessions
        ],
        "agents": [
            {
                "source_id": agent.id,
                "name": agent.name,
                "personality": agent.personality or "",
                "model": agent.model or "",
                "greeting": agent.greeting or "",
                "enabled_tools": agent.enabled_tools or "[]",
                "is_default": bool(agent.is_project_default),
            }
            for agent in agents
        ],
        "tasks": [
            {
                "name": task.name,
                "prompt": task.prompt or "",
                "task_type": task.task_type or "llm",
                "action": task.action,
                "schedule": task.schedule,
                "scheduled_time": task.scheduled_time,
                "scheduled_day": task.scheduled_day,
                "trigger_type": task.trigger_type or "schedule",
                "trigger_event": task.trigger_event,
                "trigger_count": task.trigger_count,
                "model": task.model or "",
                "crew_source_id": task.crew_member_id,
                "notifications_enabled": bool(task.notifications_enabled),
            }
            for task in tasks
        ],
        "memories": [
            {
                "text": memory.get("text", ""),
                "source": memory.get("source", "user"),
                "category": memory.get("category", "project"),
                "pinned": bool(memory.get("pinned")),
            }
            for memory in memories
        ],
        "files": files,
    }
    if len(json.dumps(bundle, ensure_ascii=False).encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Project bundle exceeds the 20 MB limit")
    return bundle


def validate_project_bundle(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise HTTPException(422, "Unsupported project bundle")
    try:
        size = len(json.dumps(bundle, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Project bundle is not valid JSON data")
    if size > MAX_BUNDLE_BYTES:
        raise HTTPException(413, "Project bundle exceeds the 20 MB limit")

    project = bundle.get("project")
    if not isinstance(project, dict):
        raise HTTPException(422, "Project bundle is missing project metadata")
    project["name"] = _safe_text(project.get("name"), 120).strip()
    project["description"] = _safe_text(project.get("description"), 4000)
    if not project["name"]:
        raise HTTPException(422, "Imported project name is required")
    if not isinstance(project.get("settings", {}), dict):
        raise HTTPException(422, "Imported project settings must be an object")

    for key in ("sessions", "agents", "tasks", "memories", "files"):
        rows = bundle.get(key, [])
        if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
            raise HTTPException(422, f"Invalid project bundle {key}")
    total_files = 0
    for item in bundle.get("files", []):
        if not isinstance(item, dict):
            raise HTTPException(422, "Invalid project file")
        path = PurePosixPath(_safe_text(item.get("path"), 500))
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or any(part.startswith(".") for part in path.parts)
        ):
            raise HTTPException(422, "Unsafe project file path")
        if item.get("encoding") != "base64":
            raise HTTPException(422, "Unsupported project file encoding")
        try:
            decoded = base64.b64decode(item.get("content", ""), validate=True)
        except (ValueError, TypeError):
            raise HTTPException(422, "Invalid project file content")
        if len(decoded) > MAX_FILE_BYTES:
            raise HTTPException(413, "Project file exceeds the 2 MB limit")
        total_files += len(decoded)
        if total_files > MAX_FILES_BYTES:
            raise HTTPException(413, "Project files exceed the 10 MB limit")
    return bundle


def import_project_contents(
    db,
    project,
    owner: str,
    bundle: dict[str, Any],
    memory_manager=None,
    memory_vector=None,
) -> dict[str, int]:
    bundle = validate_project_bundle(bundle)
    session_map: dict[str, str] = {}
    agent_map: dict[str, str] = {}
    counts = {"sessions": 0, "messages": 0, "agents": 0, "tasks": 0, "memories": 0, "files": 0}

    for row in bundle.get("agents", []):
        if not isinstance(row, dict):
            raise HTTPException(422, "Invalid project agent")
        agent_id = str(uuid.uuid4())
        source_id = _safe_text(row.get("source_id"), 100)
        if source_id:
            agent_map[source_id] = agent_id
        enabled_tools = row.get("enabled_tools", "[]")
        if not isinstance(enabled_tools, str):
            enabled_tools = json.dumps(enabled_tools)
        agent = CrewMember(
            id=agent_id,
            owner=owner,
            project_id=project.id,
            name=_safe_text(row.get("name"), 120).strip() or "Imported agent",
            personality=_safe_text(row.get("personality"), 8000),
            model=_safe_text(row.get("model"), 500) or None,
            greeting=_safe_text(row.get("greeting"), 2000) or None,
            enabled_tools=enabled_tools[:10000],
            is_active=True,
            is_default_assistant=False,
            is_project_default=bool(row.get("is_default")),
        )
        db.add(agent)
        counts["agents"] += 1

    settings = dict(project.settings or {})
    source_default_agent = settings.get("default_crew_member_id")
    if source_default_agent in agent_map:
        settings["default_crew_member_id"] = agent_map[source_default_agent]
    else:
        settings.pop("default_crew_member_id", None)
    project.settings = settings

    for row in bundle.get("sessions", []):
        if not isinstance(row, dict):
            raise HTTPException(422, "Invalid project session")
        session_id = str(uuid.uuid4())
        source_id = _safe_text(row.get("source_id"), 100)
        if source_id:
            session_map[source_id] = session_id
        session = Session(
            id=session_id,
            owner=None if owner == DEFAULT_LOCAL_OWNER else owner,
            project_id=project.id,
            name=_safe_text(row.get("name"), 500),
            endpoint_url="",
            model=_safe_text(row.get("model"), 500),
            rag=bool(row.get("rag")),
            archived=False,
            folder=_safe_text(row.get("folder"), 500) or None,
            mode=_safe_text(row.get("mode"), 50) or None,
            headers={},
        )
        db.add(session)
        counts["sessions"] += 1
        messages = row.get("messages", [])
        if not isinstance(messages, list) or len(messages) > MAX_ITEMS:
            raise HTTPException(422, "Invalid project session messages")
        for message in messages:
            if not isinstance(message, dict):
                raise HTTPException(422, "Invalid project message")
            role = _safe_text(message.get("role"), 50)
            if role not in {"system", "user", "assistant", "tool"}:
                raise HTTPException(422, "Invalid project message role")
            db.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    role=role,
                    content=_safe_text(message.get("content"), 2_000_000),
                    timestamp=utcnow_naive(),
                )
            )
            counts["messages"] += 1

    for row in bundle.get("tasks", []):
        if not isinstance(row, dict):
            raise HTTPException(422, "Invalid project task")
        db.add(
            ScheduledTask(
                id=str(uuid.uuid4()),
                owner=None if owner == DEFAULT_LOCAL_OWNER else owner,
                project_id=project.id,
                name=_safe_text(row.get("name"), 500) or "Imported task",
                prompt=_safe_text(row.get("prompt"), 200_000),
                task_type=_safe_text(row.get("task_type"), 50) or "llm",
                action=_safe_text(row.get("action"), 200) or None,
                schedule=_safe_text(row.get("schedule"), 50) or None,
                scheduled_time=_safe_text(row.get("scheduled_time"), 20) or None,
                scheduled_day=row.get("scheduled_day") if isinstance(row.get("scheduled_day"), int) else None,
                trigger_type=_safe_text(row.get("trigger_type"), 50) or "schedule",
                trigger_event=_safe_text(row.get("trigger_event"), 200) or None,
                trigger_count=row.get("trigger_count") if isinstance(row.get("trigger_count"), int) else None,
                model=_safe_text(row.get("model"), 500) or None,
                crew_member_id=agent_map.get(row.get("crew_source_id")),
                status="paused",
                notifications_enabled=bool(row.get("notifications_enabled", True)),
            )
        )
        counts["tasks"] += 1

    imported_memories = []
    if memory_manager is not None:
        for row in bundle.get("memories", []):
            if not isinstance(row, dict):
                raise HTTPException(422, "Invalid project memory")
            entry = memory_manager.add_entry(
                _safe_text(row.get("text"), 5000),
                source=_safe_text(row.get("source"), 100) or "import",
                category=_safe_text(row.get("category"), 100) or "project",
                owner=None if owner == DEFAULT_LOCAL_OWNER else owner,
                project_id=project.id,
            )
            if row.get("pinned"):
                entry["pinned"] = True
            imported_memories.append(entry)
            counts["memories"] += 1

    workspace = ensure_project_workspace(project.id)
    for item in bundle.get("files", []):
        relative = PurePosixPath(item["path"])
        target = workspace.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(item["content"], validate=True))
        counts["files"] += 1

    if imported_memories:
        existing = memory_manager.load_all_for_update()
        existing.extend(imported_memories)
        memory_manager.save(existing)
        if memory_vector is not None and getattr(memory_vector, "healthy", False):
            for entry in imported_memories:
                memory_vector.add(
                    entry["id"],
                    entry["text"],
                    owner=entry.get("owner"),
                    project_id=project.id,
                )
    return counts
