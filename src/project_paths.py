"""Project-owned filesystem paths.

Project metadata remains in SQL. This module owns only the managed workspace
layout under ``DATA_DIR/projects/<uuid>/workspace`` and never follows symlinks.
"""

from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any

from src.constants import DATA_DIR, PROJECTS_DIR


MAX_FILE_ENTRIES = 500
MAX_SCAN_DEPTH = 8


def normalize_project_id(project_id: str) -> str:
    value = str(project_id or "").strip()
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid project id") from exc
    if str(parsed) != value.lower():
        raise ValueError("invalid project id")
    return str(parsed)


def _ensure_real_directory(path: Path, *, mode: int = 0o700) -> Path:
    if os.path.lexists(path):
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RuntimeError(f"{path.name} must be a real directory")
    else:
        path.mkdir(mode=mode, parents=False)
    try:
        path.chmod(mode)
    except OSError:
        pass
    return path


def ensure_projects_root() -> Path:
    data_root = Path(DATA_DIR).expanduser().resolve()
    projects = Path(PROJECTS_DIR).expanduser()
    if projects.name != "projects" or projects.parent.resolve() != data_root:
        raise RuntimeError("projects root must be the canonical child of DATA_DIR")
    data_root.mkdir(parents=True, exist_ok=True)
    return _ensure_real_directory(projects)


def project_root(project_id: str) -> Path:
    project_id = normalize_project_id(project_id)
    return ensure_projects_root() / project_id


def ensure_project_workspace(project_id: str) -> Path:
    root = project_root(project_id)
    _ensure_real_directory(root)
    workspace = _ensure_real_directory(root / "workspace")
    if workspace.resolve() != (ensure_projects_root() / project_id / "workspace"):
        raise RuntimeError("project workspace escaped its managed root")
    return workspace


def cleanup_empty_project_root(project_id: str) -> None:
    """Remove a newly-created project tree only when it contains no user files."""
    try:
        root = project_root(project_id)
        workspace = root / "workspace"
        if workspace.is_dir() and not any(workspace.iterdir()):
            workspace.rmdir()
        if root.is_dir() and not any(root.iterdir()):
            root.rmdir()
    except (OSError, RuntimeError, ValueError):
        return


def remove_project_root(project_id: str) -> None:
    """Remove a newly-created import target after a failed transaction."""
    root = project_root(project_id)
    if root.is_symlink() or root.resolve().parent != ensure_projects_root().resolve():
        raise RuntimeError("project root escaped its managed directory")
    shutil.rmtree(root)


def list_project_workspace(project_id: str) -> list[dict[str, Any]]:
    workspace = ensure_project_workspace(project_id)
    entries: list[dict[str, Any]] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > MAX_SCAN_DEPTH or len(entries) >= MAX_FILE_ENTRIES:
            return
        try:
            children = sorted(
                os.scandir(directory),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            return
        for child in children:
            if len(entries) >= MAX_FILE_ENTRIES:
                return
            try:
                if child.is_symlink() or child.name.startswith("."):
                    continue
                child_path = Path(child.path)
                relative = child_path.relative_to(workspace).as_posix()
                if child.is_dir(follow_symlinks=False):
                    entries.append({"path": relative, "name": child.name, "type": "directory"})
                    walk(child_path, depth + 1)
                elif child.is_file(follow_symlinks=False):
                    entries.append(
                        {
                            "path": relative,
                            "name": child.name,
                            "type": "file",
                            "size": child.stat(follow_symlinks=False).st_size,
                        }
                    )
            except (OSError, ValueError):
                continue

    walk(workspace, 0)
    return entries
