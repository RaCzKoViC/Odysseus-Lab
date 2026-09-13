# Upstream synchronization

Odysseus-Lab is maintained as a conservative distribution of
[Odysseus](https://github.com/odysseus-dev/odysseus). Synchronization is a
reviewed change, not an automatic update.

## Branch policy

- `origin/main` is the Odysseus-Lab integration and release branch.
- `upstream/main` is the preferred source for stable upstream updates.
- `upstream/dev` is monitored for security fixes and selected patches.
- Feature and synchronization work happens on short-lived branches and enters
  `main` through pull requests.

The initial imported baseline is recorded in [`UPSTREAM_BASE`](../UPSTREAM_BASE).

## One-time remote setup

```bash
git remote add upstream https://github.com/odysseus-dev/odysseus.git
git fetch upstream main dev
```

If the remote already exists, verify it rather than replacing it:

```bash
git remote get-url upstream
```

## Review an update

1. Refresh refs without touching the working tree:

   ```bash
   git fetch upstream main dev
   ./scripts/upstream-status
   ```

2. Create a dedicated branch from the current Lab `main`.
3. Inspect the commit and file ranges. Pay particular attention to:
   - `app.py` and route registration;
   - `static/app.js` and top-level UI composition;
   - `src/llm_core.py` and provider behavior;
   - `core/database.py` and persistence migrations;
   - workflows, dependency files, auth, tool permissions, and path confinement.
4. Prefer a normal merge from `upstream/main` when taking a complete stable
   release. Cherry-pick a `dev` commit only when its dependencies are understood.
5. Resolve Lab identity and operations conflicts in favor of the compatibility
   contract in [`FORK.md`](../FORK.md).
6. Run the full Foundation validation and open a pull request.
7. Update `UPSTREAM_BASE` only after the synchronization pull request passes.

## Rules

- Never force-push `main`.
- Never let an update script merge upstream automatically.
- Never discard Lab migrations or security fixes merely to reduce a diff.
- Preserve upstream attribution and AGPL notices.
- Keep synchronization changes separate from new Lab features.
