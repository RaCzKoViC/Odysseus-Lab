# Project Core

Last updated: lab@5c16773e | 2026-09-13

## Scope

This spec covers `core/database.py`, `src/project_scope.py`,
`src/project_paths.py`, `routes/project/`, session linkage in
`routes/session_routes.py`, and the minimal frontend in
`static/js/projects.js`.

Odysseus-Lab 0.2 adds Projects as an optional owner-scoped container around
existing conversations and a managed workspace. It does not replace sessions,
folders, model endpoints, tasks, agents, memory, or document storage.

## Source of truth

The SQL `projects` table is the only project registry. Filesystem directories
under `DATA_DIR/projects/` contain workspace files, not authoritative project
metadata.

Each project has:

- UUID `id`;
- normalized storage `owner`;
- `name`, `description`, `status`, and `sort_order`;
- allowlisted `settings`;
- a managed `default_workspace_path`.

`status` is `active` or `archived`. Deletion through the 0.2.0 API is a soft
archive and never deletes conversations or workspace files.

## Compatibility

`sessions.project_id` is nullable and uses `ON DELETE SET NULL`. Existing
sessions remain unassigned after migration. APIs without a project filter keep
their previous all-session behavior.

Authentication-disabled mode stores Projects under the existing
`__odysseus_local__` owner bucket. Authenticated routes always apply strict
owner equality; matching a project UUID never bypasses owner checks.

## Managed workspace

The default layout is:

```text
DATA_DIR/
  projects/
    <project-uuid>/
      workspace/
```

The `projects` root, UUID directory, and workspace must be real directories.
Symlinks are rejected. File listing skips hidden entries and symlinks, limits
depth and item count, and never traverses another project.

External workspace registration, shell confinement, and repository management
are deferred. The existing trusted-admin shell boundary remains unchanged.

## API

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{id}
PATCH  /api/projects/{id}
DELETE /api/projects/{id}
GET    /api/projects/{id}/overview
GET    /api/projects/{id}/sessions
PUT    /api/projects/{id}/sessions/{session_id}
DELETE /api/projects/{id}/sessions/{session_id}
GET    /api/projects/{id}/files
```

Cross-owner project and session access returns 404. Unknown project settings
are rejected and settings never hold credentials.

## 0.2.x extension points

Later 0.2 releases may add nullable `project_id` to tasks, crew members,
documents, and memory records. Model endpoints remain owner/global
infrastructure referenced by project settings; they are not duplicated.

## Current Gaps

- Project settings are persisted but memory/model integration begins in 0.2.1.
- External repository roots are not registered in 0.2.0.
- The managed Files tab is read-only.
- Project tasks, agents, artifacts, and memory counters are not yet included in
  Overview.
