---
layout: default
---

# Odysseus-Lab operations

This runbook covers the supported 0.1 Foundation path: a local Docker Compose
deployment with optional host Ollama. Native Windows remains a lightweight app
path; it does not launch the bundled ChromaDB, SearXNG, or ntfy services.

## Install

```bash
git clone https://github.com/RaCzKoViC/Odysseus-Lab.git
cd Odysseus-Lab
cp .env.example .env
docker compose up -d --build
```

Wait until Compose reports the `odysseus` service healthy, then check:

```bash
curl --fail http://127.0.0.1:7000/api/health
curl --fail http://127.0.0.1:7000/api/ready
curl --fail http://127.0.0.1:7000/api/version
```

The temporary administrator password is printed by
`docker compose logs odysseus`. Change it after the first login.

## Diagnostics

Run the read-only Foundation doctor from the repository root:

```bash
./scripts/odysseus-doctor
./scripts/odysseus-doctor --json
./scripts/odysseus-doctor --strict
```

The report checks Python, the data directory, Compose configuration, application
liveness/readiness/runtime, Ollama, ChromaDB, and SearXNG. URLs are sanitized
before display. `--strict` also treats an unavailable optional service as a
failure.

On native Windows, run `venv\Scripts\python.exe scripts\odysseus-doctor --strict`.
The health and readiness probes require the application's JSON success signals;
an HTML login page or `ready: false` with HTTP 200 is a failure. A missing data
directory is also a failure. Relative `ODYSSEUS_DATA_DIR` paths resolve against
the selected `--repo`, not the shell's current directory.

`AUTH_REQUIRED` on `app_runtime` means its HTTP 401 requires an authenticated
session. The doctor does not load saved credentials or check those protected
details. This expected restriction does not degrade an otherwise healthy report,
including with `--strict`. Authentication errors on public health/readiness or
other services remain failures.

Authenticated administrators can inspect the deeper service report at
`GET /api/diagnostics/services` and bounded log tail at
`GET /api/diagnostics/logs`.

### Ollama

Native installations normally use `http://127.0.0.1:11434/v1`. A Docker
container reaches the host through:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

Ollama must accept the Docker-host connection:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Keep port 11434 private; do not expose it to the public internet.

## Backup

The existing app-data command remains compatible with upstream:

```bash
./scripts/odysseus-backup snapshot
./scripts/odysseus-backup verify backups/odysseus-backup-TIMESTAMP.tar.gz
```

For a complete Compose backup, including the separate ChromaDB volume, use:

```bash
./scripts/odysseus-compose-backup snapshot
```

The command briefly stops running `odysseus` and `chromadb` services, creates a
single bundle containing `app-data.tar.gz`, `chromadb.tar.gz`, and a checksummed
manifest, then restarts only the services that were running. A Compose
`chromadb` container must already exist so the actual volume can be identified.
The archive operations use a separate, digest-pinned Python helper image because
the ChromaDB image has no Python interpreter. The helper is downloaded and
checked before services stop; its volume access runs with networking disabled.

Backups contain the application encryption key, sessions, provider tokens,
documents, and vector data. Store them as secrets. The `backups/` path is
gitignored, but that is not encryption.

Restore is destructive and requires explicit confirmation:

```bash
./scripts/odysseus-compose-backup restore backups/odysseus-compose-TIMESTAMP.tar.gz --yes
```

The command verifies exact bundle members and SHA-256 checksums before touching
state. App data is staged before replacement and the previous data directory is
retained as `data.before-restore-TIMESTAMP`. ChromaDB is restored only while the
service is stopped and its pre-restore volume contents are used for rollback if
volume extraction fails.

If `APP_DATA_DIR` points to a custom host bind directory, the Compose backup
passes that path to the compatible app-data backup format. Keep it outside the
repository if it is shared with another deployment.

## Update

Updates pull only the Lab `origin/main`. Upstream synchronization is a separate
review process described in [`upstream.md`](upstream.md).

Linux/macOS Docker:

```bash
git checkout main
./scripts/update-lab.sh
```

Windows Docker:

```bat
update_windows.bat
```

Both paths validate prerequisites, show the active Compose configuration, create
a full pre-update backup, use `git pull --ff-only`, rebuild, and wait for
`/api/ready`. They print the previous commit and restore command if an update
fails; they never reset the repository automatically.

Persist GPU overlays in `.env` so updates reuse them:

```env
COMPOSE_FILE=docker-compose.yml:docker/gpu.nvidia.yml
```

On Windows, use semicolons between Compose files.

## Required branch protection

After the checks have run once, protect `main` and require pull requests plus:

- `Python syntax (compileall)`
- `JS syntax (node --check)`
- `Python tests (pytest, 3.11)`
- `Python tests (pytest, 3.14)`
- `Docker Compose configuration`
- `Windows Foundation smoke`
- `Docker stack readiness`
- `gitleaks`
- `actionlint`
- `zizmor (Actions SAST)`
- `hadolint (Dockerfile lint)`
- `pip-audit (private gate / public advisory)`

Trivy remains advisory. CodeQL is skipped while this private repository lacks
GitHub Advanced Security. If GHAS is enabled later, add the repository variable
`ODYSSEUS_ENABLE_CODEQL=true`; do not also enable CodeQL default setup.

GitHub Pages is intentionally skipped while the repository is private. GHCR
publishes a private, lower-case `ghcr.io/raczkovic/odysseus-lab` image from
`main`.

## Release checklist

1. Run `python -m pytest -q` and the security slice
   `python -m pytest -m area_security -q`.
2. Run actionlint, zizmor, gitleaks, hadolint, and the blocking pip audit.
3. Start a clean Compose stack and require `/api/ready` to return 200.
4. Run the doctor and verify it contains no credentials.
5. Create, verify, and restore a disposable full Compose backup.
6. Confirm every required check is green before assigning the `0.1.0` tag.
