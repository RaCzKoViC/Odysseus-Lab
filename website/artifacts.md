---
layout: default
---

# Artifacts

An artifact is a deliverable the model wrote - a page, a diagram, a document,
a long piece of code - shown beside the conversation instead of scrolling past
inside it. Odysseus-Lab detects them from the reply itself, so the feature
works with every model the Lab can talk to, including the small local ones
that cannot call a tool or follow a protocol.

## What becomes an artifact

Detection is in `static/js/artifacts.js` and runs on the rendered message, so
it sees exactly what the user sees. A fenced block qualifies when it is:

- a complete HTML page, an SVG drawing, or a Mermaid diagram of four lines or
  more - these render, so a card is worth more than a wall of source;
- Markdown or code of at least fourteen lines (thirty for shell and other
  languages where long output is usually a transcript, not a deliverable);
- anything the model announced itself, via an info string such as
  ```` ```html title="Landing page" ```` - a model that says what it made is
  believed regardless of length.

A block that is still streaming is left alone until it closes, so a
half-written page is never filed and then replaced.

The card's title comes from the content: `<title>`, then an `<h1>` for a page,
then a Markdown heading, then the first named `def`/`class`/`function`, then a
leading comment. `# something` is read as a heading only in Markdown - in
Python or shell it is a remark, not a name. Titles matter beyond labelling:
the library stores one entry per title, so two pages called "HTML page" would
take turns overwriting each other.

An artifact that appears in the reply the user is watching opens by itself
once. One replayed from history does not - reopening a conversation should not
rearrange it.

## Preview: why it is served, not inlined

An interactive page has to run its own scripts. The app's Content-Security
Policy forbids inline script, and a frame built from `srcdoc`, a `blob:` URL
or a `data:` URL inherits the embedding page's policy - so all three render
the markup and silently refuse to run it.

The preview is therefore stored and served from its own path,
`/api/artifact/preview/{token}`, which carries its own policy: inline script
and `cdn.jsdelivr.net` are allowed, `connect-src` and `form-action` are
`'none'`, and `frame-ancestors` is `'self'`. The frame is sandboxed with
`allow-scripts allow-forms allow-modals allow-popups` and, deliberately, no
`allow-same-origin`, so the page runs in an opaque origin: it can do its own
work, and it cannot call home, submit anywhere, reach this app's cookies, or
be framed by anyone else.

Storage is in memory, owner-scoped, capped at forty previews per user and
2 MB each, and expires after an hour. A preview URL belonging to someone else
returns 404, not their markup.

The panel never waits on that bargain to be visible: it renders a static copy
of the artifact immediately, and swaps in the live frame only once the frame
reports back. If framing is blocked - as it is inside some embedded browser
panes - the static render stays and says so.

## The library

The sidebar's **Artifacts** entry is a library of what the user chose to keep.
Nothing is kept automatically: the panel's button says **Save**, or **Update**
when the library already holds that title, and cards whose artifact is kept are
outlined and marked. The badge counts saved artifacts, not the ones on screen.

- **Edit** asks what should change and sends the request through the
  conversation: the description plus the current code, as an ordinary message.
  The model answers with a revision, the detector files it as a new version,
  and the panel shows it. No tool calling, so it works with every model. A
  revision does not overwrite the saved entry by itself - saving stays a
  decision.
- **Wybierz** turns on selection, **Usuń (n)** deletes what is ticked.

Deleting removes the artifact from the library *and* takes its card out of the
conversation, because that is what deleting is for. The transcript itself is
untouched: the code block the card was made from comes back into view, exactly
as the model wrote it, with a quiet **Przywróć jako artefakt** link in case the
deletion was a mistake. Deletions are remembered in `localStorage`, so they
survive a reload; saving the artifact again brings its card back.

## Storage

Saved artifacts live in `saved_artifacts` (`core/database.py`), scoped to the
owner through `storage_owner(require_user(request))` - the same helper the rest
of the Lab uses. Routes are in `routes/artifact/artifact_routes.py`:

| Route | What it does |
| --- | --- |
| `POST /api/artifact/preview` | Store markup, get a URL back |
| `GET /api/artifact/preview/{token}` | Serve it, under the permissive policy |
| `GET /api/artifacts` | List what the owner kept |
| `POST /api/artifacts` | Keep one; same title replaces |
| `PATCH /api/artifacts/{id}` | Edit one in place |
| `POST /api/artifacts/delete` | Delete the selected ones |

## Tests

- `tests/test_artifacts_js.py` runs the detection rules under Node and pins
  what does and does not become an artifact, how things get named, and when a
  card opens by itself.
- `tests/test_artifact_preview_routes.py` pins both halves of the preview
  bargain - the permissive policy is on that path and no other, and markup only
  comes back to whoever stored it - plus the library's create, replace, edit
  and delete behaviour.
