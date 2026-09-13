<p align="center">
  <img src="assets/branding/odysseus-wordmark.png" alt="Odysseus" width="238">
</p>

<p align="center">
  <strong>Odysseus-Lab — Build. Research. Automate.</strong><br>
  A local-first AI agent and development laboratory.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="website/setup.md">Setup Guide</a> ·
  <a href="CONTRIBUTING.md">Contributing</a> ·
  <a href="ROADMAP.md">Roadmap</a> ·
  <a href="FORK.md">Fork &amp; Upstream</a> ·
  <a href="website/operations.md">Operations</a>
</p>

<p align="center">
  <img src="assets/branding/odysseus-browser.jpg" alt="Odysseus interface">
</p>

---

> **Fork status:** Odysseus-Lab is an independently maintained, upstream-compatible
> distribution based on [Odysseus](https://github.com/odysseus-dev/odysseus).
> Internal command names, environment variables, and data formats remain compatible
> so installations can exchange data and selected upstream changes safely.

## Quick Start

`main` is the integration and release branch for Odysseus-Lab.

```bash
git clone https://github.com/RaCzKoViC/Odysseus-Lab.git
cd Odysseus-Lab
cp .env.example .env
docker compose up -d --build
```

Open `http://localhost:7000` when the containers are healthy. The first admin password is printed in `docker compose logs odysseus`.

Native installs, GPU notes, Windows/macOS instructions, HTTPS, and configuration live in the [setup guide](website/setup.md).

## Features

- **Chat + Agents** — local/API models, tools, MCP, files, shell, skills, and memory.
- **Cookbook** — hardware-aware model recommendations, downloads, and serving.
- **Deep Research** — multi-step web research with source reading and report generation.
- **Compare** — blind side-by-side model testing and synthesis.
- **Documents** — writing-first editor with AI edits, suggestions, Markdown, HTML, CSV, and syntax highlighting.
- **Email** — IMAP/SMTP inbox with triage, tags, summaries, reminders, and reply drafts.
- **Notes, Tasks + Calendar** — reminders, todos, scheduled agent tasks, and CalDAV sync.
- **Extras** — gallery/image editor, themes, uploads, web search, presets, sessions, and 2FA.

## Demo

A full hover-to-play tour is included under [`website/`](website/). GitHub Pages
publishing is intentionally disabled while this repository remains private.

## Contributing

Help is welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), [ROADMAP.md](ROADMAP.md),
and the [upstream synchronization policy](website/upstream.md).

## Security

Odysseus is a self-hosted workspace with powerful local tools. Keep auth enabled, keep private data out of Git, and do not expose raw model/service ports publicly.

- Keep `AUTH_ENABLED=true` for any network-accessible deployment.
- Keep `LOCALHOST_BYPASS=false` outside local development.

Deployment details are in the [setup guide](website/setup.md#security-notes).

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE), [FORK.md](FORK.md), and
[ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md). Operators who make a modified version
available over a network must comply with the AGPL source-availability terms.
