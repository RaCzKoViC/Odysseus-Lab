"""Owner-first project scoping shared by routes and execution layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException

from core.database import Project
from src.owner_identity import effective_storage_owner
from src.project_paths import normalize_project_id


@dataclass(frozen=True)
class ExecutionScope:
    owner: Optional[str]
    project_id: Optional[str] = None
    session_id: Optional[str] = None


def storage_owner(user: Optional[str]) -> str:
    owner = effective_storage_owner(user)
    if not owner:
        raise HTTPException(status_code=401, detail="Authentication required")
    return owner


def project_query(db, owner: str, *, include_archived: bool = False):
    query = db.query(Project).filter(Project.owner == owner)
    if not include_archived:
        query = query.filter(Project.status == "active")
    return query


def get_owned_project(
    db,
    owner: str,
    project_id: str,
    *,
    include_archived: bool = False,
) -> Project:
    try:
        project_id = normalize_project_id(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    project = project_query(
        db,
        owner,
        include_archived=include_archived,
    ).filter(Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def apply_project_scope(
    query,
    model_cls,
    owner: Optional[str],
    project_id: Optional[str],
    *,
    include_all_when_unset: bool = True,
):
    """Apply strict owner/project filters without exposing shared NULL rows."""
    if owner:
        query = query.filter(model_cls.owner == owner)
    if project_id is None and include_all_when_unset:
        return query
    if project_id is None:
        return query.filter(model_cls.project_id == None)  # noqa: E711
    try:
        normalized = normalize_project_id(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found")
    return query.filter(model_cls.project_id == normalized)
