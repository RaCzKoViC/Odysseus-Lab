---
layout: default
---

# Security CI guide

This project runs a set of automated security checks on pull requests and
selected branch pushes. This page explains what each one does, whether it can
block a merge, and the few one-time settings you should turn on to get the full
benefit.

## What runs, and why

Most checks live in files under `.github/workflows/`. CodeQL uses the
checked-in advanced configuration in `.github/workflows/codeql.yml`. They run
automatically; you do not start them.

| Check | What it protects against | Blocks a merge? |
|---|---|---|
| **Secret scan** (gitleaks) | An API key, token, or password being committed by mistake or on purpose | Yes |
| **Workflow security** (actionlint + zizmor) | A broken or insecure automation file that could leak the repo's access token | Yes |
| **Dependency review** | A pull request that adds a software library with a known security hole | Yes (public repositories) |
| **pip-audit** | Known security holes in the Python libraries already used | Yes on private repositories; advisory on public repositories |
| **Container scan: hadolint** | Mistakes and insecure patterns in the `Dockerfile` | Yes |
| **Container scan: Trivy** | Known security holes in the Docker image | No (advisory) |
| **CodeQL** | Real bugs in the app's own code: injection, auth mistakes, path traversal | Advisory; skipped in private repositories without GHAS |

"Blocks a merge" means a red X appears on the pull request and, once you enable
the setting below, the **Merge** button is disabled until it is fixed.

"Advisory" means it reports problems into the repository's **Security** tab so
you can review them on your own schedule, but it never stops a merge. These are
advisory on purpose: they often flag long-standing issues in other people's
libraries, not something a given pull request introduced.

## Where results appear

- **Checks tab of a pull request**: the pass/fail of each check. A green tick is
  good; a red X needs attention.
- **Security tab of the repository**: detailed findings from the advisory
  scanners (Trivy and CodeQL). This is your dashboard.

## If a check fails

- **Secret scan failed**: a real credential may have been committed. Treat it as
  leaked: rotate (regenerate) that key or token immediately, then remove it from
  the file. Do not just delete the commit; assume it was seen.
- **Dependency review failed**: the pull request adds a library with a known
  vulnerability. Ask the contributor to use a patched version, or decline the
  change.
- **hadolint / workflow security failed**: the contributor changed the
  `Dockerfile` or an automation file in a way the linter rejects. Ask them to
  address the message shown in the failed check.

## One-time settings to turn on

These two settings unlock the full value. You only do them once.

### 1. Require the blocking checks before merging

This makes the **Merge** button refuse to work until the gating checks pass.

1. Go to the repository on GitHub.
2. Click **Settings** (top right of the repo).
3. In the left sidebar, click **Branches**.
4. Under **Branch protection rules**, click **Add branch ruleset** (or **Add
   rule**), and set the branch name pattern to `main`.
5. Enable **Require status checks to pass before merging**.
6. In the search box that appears, add these checks by name:
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
   - `pip-audit (private gate / public advisory)` for a private repository, or
     `dependency-review (PR gate)` for a public repository.

   Leave Trivy and CodeQL advisory. CodeQL requires GitHub Advanced Security
   for a private repository.
7. Also enable **Require a pull request before merging**. Enable Code Owner
   review only after assigning owners in `.github/CODEOWNERS`.
8. Click **Create** / **Save changes**.

Note: a check name only appears in the list after it has run at least once, so
let the workflows run on one pull request first, then add them here.

### 2. Turn on the Security tab features

1. **Settings -> Code security** (or **Code security and analysis**).
2. Turn on **Dependency graph** (usually on by default for public repos) -- this
   powers Dependency review and Dependabot.
3. Turn on **Dependabot alerts** and **Dependabot security updates**.
4. On a private repository, CodeQL requires GitHub Advanced Security. After
   enabling it, add the repository variable `ODYSSEUS_ENABLE_CODEQL=true`.
   Keep **Default setup** disabled because CodeQL is configured by
   `.github/workflows/codeql.yml`; enabling both modes causes duplicate setup.

## Keeping it current

`.github/dependabot.yml` opens small weekly pull requests to update Python and
npm packages, the Docker base image, and the pinned automation actions
themselves. Review and merge those like any other pull request; they keep the
project patched without manual tracking.
