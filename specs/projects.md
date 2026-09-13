# Project Core

Last updated: lab@5c16773e | 2026-09-13

## Scope

This spec covers `core/database.py`, `src/project_scope.py`,
`src/project_paths.py`, `routes/project/`, session linkage in
`routes/session_routes.py`, project tasks in `routes/task/`, project memory in
`src/memory.py`, and the frontend in `static/js/projects.js`.

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
- a portable managed `default_workspace_path` relative to `DATA_DIR`.

`status` is `active` or `archived`. Deletion through the 0.2.0 API is a soft
archive and never deletes conversations or workspace files.

## Compatibility

`sessions.project_id` is nullable and application-validated. It deliberately
does not use a database foreign key because supported tools and tests create
the sessions table in isolation. Existing sessions remain unassigned after
migration. APIs without a project filter keep their previous all-session
behavior.

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
GET    /api/projects/{id}/export
POST   /api/projects/import
POST   /api/projects/{id}/assign
GET    /api/projects/{id}/agents
POST   /api/projects/{id}/agents
PATCH  /api/projects/{id}/agents/{agent_id}
DELETE /api/projects/{id}/agents/{agent_id}
```

Cross-owner project and session access returns 404. Unknown project settings
are rejected and settings never hold credentials.

Project bundles use `odysseus-project.v1`. They include project metadata,
sanitized conversations, paused task definitions, agents, project memories,
and bounded managed-workspace files. Credentials, endpoint URLs, request
headers, webhook tokens, and message metadata are never exported. Import
validates total size, per-file size, base64, relative paths, message roles, and
owner stamping before persistence.

The assignment API moves explicitly selected owner sessions and memories into a
project. It defaults to unassigned-only and rejects cross-owner or already
assigned records rather than silently moving them.

## 0.2.x extension points

0.2.1 adds nullable `project_id` to scheduled tasks, task runs, CrewMember
agents, and JSON memory records. Project settings reference model endpoints and
default models; endpoint rows remain owner/global infrastructure and are not
duplicated. Memory visibility is `inherit`, `project_plus_global`, or
`project_only`, with `inherit` preserving the 0.2.0 behavior.

## Current Gaps

- External repository roots are not registered in 0.2.x.
- The managed Files tab is read-only.
- Rich artifact types are not yet included in project bundles.
