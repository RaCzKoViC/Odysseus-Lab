// Artifacts — a deliverable the model produced, shown beside the chat.
//
// The point of this module is that it works with EVERY model, including the
// small local ones that cannot call a tool and will never follow a protocol.
// Nothing here depends on function calling, on a provider feature, or on the
// model having been told anything: an artifact is recognised from the text of
// the reply, the same way a reader recognises one. A model that does announce
// its work (```html title="Landing page") gets a better title out of it, and
// that is the only difference.
//
// Two layers, on purpose:
//
//   * pure functions (detectArtifacts, classifyBlock, deriveTitle, ...) that
//     take text and return data. Those carry the rules and are unit-tested in
//     tests/test_artifacts_js.py without a browser.
//   * a thin DOM layer that watches the chat, upgrades qualifying code blocks
//     into cards, and opens the panel. It observes rather than hooks, so
//     chat.js, chatRenderer.js and markdown.js stay untouched (FORK.md: keep
//     changes additive, leave the hotspots alone).

// ── Rules ──────────────────────────────────────────────────────────────────

/** Languages that are a thing in themselves: they render, so they preview. */
export const RENDERABLE_LANGS = new Set([
  'html', 'svg', 'mermaid', 'markdown', 'md',
]);

/** Languages that are a deliverable once there is enough of them. */
export const CODE_LANGS = new Set([
  'javascript', 'js', 'jsx', 'typescript', 'ts', 'tsx', 'vue', 'svelte',
  'python', 'py', 'rust', 'rs', 'go', 'java', 'kotlin', 'swift', 'c', 'h',
  'cpp', 'c++', 'cc', 'csharp', 'cs', 'php', 'ruby', 'rb', 'lua', 'r',
  'sql', 'css', 'scss', 'less', 'json', 'yaml', 'yml', 'toml', 'xml',
  'dockerfile', 'makefile', 'ini', 'csv', 'tsv', 'latex', 'tex',
]);

/**
 * Languages that are usually a few commands to paste, not a deliverable.
 * The chat already gives these a Run button; turning `pip install x` into an
 * artifact would be noise. They can still qualify, but only when long enough
 * that they are clearly a script.
 */
export const SHELL_LANGS = new Set([
  'bash', 'sh', 'shell', 'zsh', 'fish', 'console', 'powershell', 'ps1', 'bat', 'cmd',
]);

/** A renderable block is an artifact from this many lines up. */
export const MIN_LINES_RENDERABLE = 4;
/** A code block is an artifact from this many lines up. */
export const MIN_LINES_CODE = 14;
/** A shell script, or a block with no language at all, needs this many. */
export const MIN_LINES_LOOSE = 30;

/** Text that means "this is a whole document", whatever its length. */
const DOCUMENT_MARKERS = [
  /<!doctype\s+html/i,
  /<html[\s>]/i,
  /<svg[\s>]/i,
  /^\s*graph\s+(TD|LR|RL|BT)\b/im,
  /^\s*sequenceDiagram\b/im,
  /^\s*flowchart\s+/im,
  /^\s*classDiagram\b/im,
  /^\s*gantt\b/im,
  /^\s*erDiagram\b/im,
  /^\s*pie\s+title\b/im,
];

/** Kinds an artifact can be, which is what the panel switches on. */
export const KIND_HTML = 'html';
export const KIND_SVG = 'svg';
export const KIND_MERMAID = 'mermaid';
export const KIND_MARKDOWN = 'markdown';
export const KIND_CODE = 'code';

const LANG_ALIASES = {
  js: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  py: 'python',
  rs: 'rust',
  rb: 'ruby',
  yml: 'yaml',
  'c++': 'cpp',
  cc: 'cpp',
  cs: 'csharp',
  md: 'markdown',
  ps1: 'powershell',
};

/** Normalise the fence's info string to a bare language token. */
export function normalizeLang(lang) {
  const raw = String(lang || '').trim().toLowerCase();
  if (!raw) return '';
  const head = raw.split(/[\s:,;]/)[0];
  return LANG_ALIASES[head] || head;
}

function looksLikeDocument(code) {
  return DOCUMENT_MARKERS.some((re) => re.test(code));
}

function lineCount(code) {
  if (!code) return 0;
  return code.replace(/\s+$/, '').split('\n').length;
}

/**
 * What kind of artifact a block would make, and whether it makes one at all.
 *
 * Returns `{ kind, lang, lines, qualifies, reason }`. `reason` says which
 * rule answered, which is what the tests pin down and what makes a surprise
 * ("why is this a card?") answerable.
 */
export function classifyBlock({ lang, code, explicitTitle = '' } = {}) {
  const normalized = normalizeLang(lang);
  const body = String(code || '');
  const lines = lineCount(body);
  const doc = looksLikeDocument(body);

  let kind = KIND_CODE;
  if (normalized === 'html') kind = KIND_HTML;
  else if (normalized === 'svg') kind = KIND_SVG;
  else if (normalized === 'mermaid') kind = KIND_MERMAID;
  else if (normalized === 'markdown') kind = KIND_MARKDOWN;
  else if (!normalized && doc) {
    // An unfenced-language block that is plainly a document still renders.
    if (/<svg[\s>]/i.test(body)) kind = KIND_SVG;
    else if (/<!doctype\s+html|<html[\s>]/i.test(body)) kind = KIND_HTML;
    else kind = KIND_MERMAID;
  }

  // A title the model gave us is a statement of intent; take it at its word.
  if (explicitTitle) {
    return { kind, lang: normalized, lines, qualifies: true, reason: 'declared' };
  }
  if (doc) {
    return { kind, lang: normalized, lines, qualifies: true, reason: 'document' };
  }
  if (RENDERABLE_LANGS.has(normalized)) {
    return {
      kind, lang: normalized, lines,
      qualifies: lines >= MIN_LINES_RENDERABLE,
      reason: 'renderable',
    };
  }
  if (SHELL_LANGS.has(normalized)) {
    return {
      kind, lang: normalized, lines,
      qualifies: lines >= MIN_LINES_LOOSE,
      reason: 'shell',
    };
  }
  if (CODE_LANGS.has(normalized)) {
    return {
      kind, lang: normalized, lines,
      qualifies: lines >= MIN_LINES_CODE,
      reason: 'code',
    };
  }
  return {
    kind, lang: normalized, lines,
    qualifies: lines >= MIN_LINES_LOOSE,
    reason: normalized ? 'unknown-language' : 'no-language',
  };
}

/**
 * Pull a title out of the fence's info string.
 *
 * Understands what models actually write when asked for one:
 *   ```html title="Landing page"
 *   ```html title=Landing page
 *   ```python filename=solver.py
 *   ```artifact:html Landing page
 * Anything else is just a language and yields no title.
 */
export function parseInfoString(info) {
    const raw = String(info || '').trim();
  if (!raw) return { lang: '', title: '' };

  let rest = raw;
  let lang = '';

  const artifactPrefix = /^artifact\s*[:=]?\s*/i;
  if (artifactPrefix.test(rest)) {
    rest = rest.replace(artifactPrefix, '');
    const parts = rest.split(/\s+/);
    lang = parts.shift() || '';
    return { lang: normalizeLang(lang), title: parts.join(' ').replace(/^["']|["']$/g, '') };
  }

  const head = rest.split(/\s+/)[0] || '';
  lang = normalizeLang(head);
  rest = rest.slice(head.length).trim();
  if (!rest) return { lang, title: '' };

  const keyed = rest.match(/\b(?:title|name|filename|file)\s*[:=]\s*(?:"([^"]+)"|'([^']+)'|(\S.*?))\s*$/i);
  if (keyed) {
    return { lang, title: (keyed[1] || keyed[2] || keyed[3] || '').trim() };
  }
  // A bare trailing phrase after the language is a title often enough
  // (```html Landing page) to be worth taking, as long as it is not a flag.
  if (!rest.startsWith('{') && !rest.startsWith('[') && !/^[-=]/.test(rest)) {
    return { lang, title: rest.replace(/^["']|["']$/g, '') };
  }
  return { lang, title: '' };
}

const KIND_FALLBACK_TITLE = {
  [KIND_HTML]: 'HTML page',
  [KIND_SVG]: 'SVG image',
  [KIND_MERMAID]: 'Diagram',
  [KIND_MARKDOWN]: 'Document',
  [KIND_CODE]: 'Code',
};

/**
 * A name for the thing, taken from the thing itself when the model did not
 * give one: the <title>, the first heading, the first function or class,
 * the first comment. Failing all of that, what kind of artifact it is.
 */
export function deriveTitle({ kind, lang, code, explicitTitle = '' } = {}) {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  if (explicitTitle) return clean(explicitTitle);
  const body = String(code || '');

  const htmlTitle = body.match(/<title[^>]*>([^<]{1,120})<\/title>/i);
  if (htmlTitle) return clean(htmlTitle[1]);

  const svgTitle = body.match(/<svg[^>]*>[\s\S]{0,400}?<title[^>]*>([^<]{1,120})<\/title>/i);
  if (svgTitle) return clean(svgTitle[1]);

  // A page with a heading and no <title> is the common shape of a model's
  // answer, and "HTML page" is not a name: the library replaces by title, so
  // three such pages from one reply would overwrite each other in turn.
  if (kind === KIND_HTML) {
    const h1 = body.match(/<h1[^>]*>([\s\S]{1,120}?)<\/h1>/i);
    if (h1) {
      const text = clean(h1[1].replace(/<[^>]+>/g, ' '));
      if (text) return text;
    }
  }

  // Markdown only: in Python, shell or YAML a leading `# something` is a
  // comment, and reading it as a heading would title a script after its
  // first remark instead of what it defines.
  const heading = body.match(/^\s{0,3}#{1,3}\s+(.{1,120})$/m);
  if (heading && kind === KIND_MARKDOWN) return clean(heading[1]);

  const named = body.match(
    /^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|struct|interface|type)\s+([A-Za-z_][\w]*)/m,
  );
  if (named) return clean(named[1]);

  const comment = body.match(/^\s*(?:\/\/|#|--|\/\*|<!--)\s*(.{3,80}?)\s*(?:\*\/|-->)?\s*$/m);
  if (comment) return clean(comment[1]);

  // Nothing in the content named it, so say what it is. A language only
  // helps for plain code ("Python snippet"); for the kinds that render, the
  // kind is already the better word than the language that produced it.
  if (kind === KIND_CODE && lang) {
    return clean(`${lang.charAt(0).toUpperCase()}${lang.slice(1)} snippet`);
  }
  return clean(KIND_FALLBACK_TITLE[kind] || 'Artifact');
}

/** The identity the library uses: same kind, same name, same artifact. */
export function artifactKey(artifact) {
  return artifact && artifact.key
    ? artifact.key
    : `${(artifact && artifact.kind) || KIND_CODE}:${titleKey(artifact && artifact.title)}`;
}

/** Two titles name the same artifact when they differ only in noise. */
export function titleKey(title) {
  return String(title || '')
    .toLowerCase()
    .replace(/\.[a-z0-9]{1,6}$/, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

// The closing fence is its own group so an unterminated block - a reply that
// is still streaming - can be told apart from a finished one.
const FENCE_RE = /(^|\n)([ \t]{0,3})(`{3,}|~{3,})([^\n]*)\n([\s\S]*?)(\n[ \t]{0,3}\3[ \t]*(?=\n|$)|$)/g;

/**
 * Every artifact in one message, in the order they appear.
 *
 * The parser is deliberate about unterminated fences: a reply that is still
 * streaming ends mid-block, and that block is an artifact-in-progress rather
 * than nothing. Callers that care pass `{ complete: false }` on those.
 */
export function detectArtifacts(text, { messageId = '' } = {}) {
  const src = String(text || '');
  const found = [];
  let match;
  FENCE_RE.lastIndex = 0;
  while ((match = FENCE_RE.exec(src)) !== null) {
    const info = match[4] || '';
    const code = (match[5] || '').replace(/\s+$/, '');
    if (!code.trim()) continue;
    const { lang, title: explicitTitle } = parseInfoString(info);
    const verdict = classifyBlock({ lang, code, explicitTitle });
    if (!verdict.qualifies) continue;
    const title = deriveTitle({ kind: verdict.kind, lang: verdict.lang, code, explicitTitle });
    // Group 6 is the closing fence, empty when the block ran off the end of
    // the text: the model is still writing it.
    const complete = Boolean((match[6] || '').trim());
    found.push({
      id: `${messageId || 'msg'}-${found.length}`,
      index: found.length,
      kind: verdict.kind,
      lang: verdict.lang,
      title,
      declared: verdict.reason === 'declared',
      reason: verdict.reason,
      lines: verdict.lines,
      code,
      complete,
    });
  }
  return found;
}

/**
 * Number the artifacts of a conversation the way a reader would: the same
 * deliverable, rewritten, is version 2 of it - not a second artifact.
 * `seen` is a Map carried across messages by the caller.
 */
export function assignVersions(artifacts, seen = new Map()) {
  return artifacts.map((artifact) => {
    const key = `${artifact.kind}:${titleKey(artifact.title)}`;
    const version = (seen.get(key) || 0) + 1;
    seen.set(key, version);
    return { ...artifact, key, version };
  });
}

/**
 * Should the panel open by itself for this artifact?
 *
 * Yes when it was just made in the conversation the user is watching - that
 * is the whole request. No when the page is merely replaying history, or the
 * user closed the panel for this very artifact (closing it means "not now",
 * and re-opening it on the next token would be a fight).
 */
const HIDDEN_STORAGE_KEY = 'odysseus.lab.artifacts.hidden';

function loadHiddenKeys() {
  try {
    const raw = window.localStorage.getItem(HIDDEN_STORAGE_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    // Private windows and blocked storage are not an error worth failing on:
    // the deletion simply lasts for this page instead of forever.
    return new Set();
  }
}

function persistHiddenKeys() {
  try {
    window.localStorage.setItem(HIDDEN_STORAGE_KEY, JSON.stringify([...state.hidden]));
  } catch {
    /* see loadHiddenKeys */
  }
}

export function shouldAutoOpen({ isLive, isHistoryReplay, dismissedKeys = [], key = '' } = {}) {
  if (!isLive || isHistoryReplay) return false;
  return !dismissedKeys.includes(key);
}

// ── Browser layer ──────────────────────────────────────────────────────────
// Everything below needs a DOM. Guarded so the module stays importable in
// node for the tests above.

const HAS_DOM = typeof document !== 'undefined' && typeof window !== 'undefined';

const state = {
  panel: null,
  current: null,
  bySession: new Map(),
  dismissed: new Set(),
  replayed: false,
  observer: null,
  // Messages that streamed in front of the user. A reply being written
  // carries the class `streaming` (chat.js); replaying history never does,
  // which is exactly the difference between "just made" and "already there".
  liveMessages: new WeakSet(),
  knownCards: new Set(),
  // Artifacts the user deleted. Deleting is meant to get rid of the thing,
  // so the card goes as well - and it has to stay gone after a reload, or
  // the next visit to the conversation quietly undoes the deletion.
  hidden: loadHiddenKeys(),
  // Titles the library already holds. Saving stays a decision the user
  // makes - nothing is kept automatically - but they should not have to
  // remember what they already kept, or guess whether pressing Save adds a
  // copy or replaces one.
  savedTitles: new Set(),
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function iconFor(kind) {
  if (kind === KIND_HTML) return '🌐';
  if (kind === KIND_SVG) return '🖼️';
  if (kind === KIND_MERMAID) return '📈';
  if (kind === KIND_MARKDOWN) return '📄';
  return '📦';
}

function labelFor(artifact) {
  const kind = artifact.kind === KIND_CODE ? (artifact.lang || 'code') : artifact.kind;
  const lines = artifact.lines === 1 ? '1 line' : `${artifact.lines} lines`;
  return artifact.version > 1 ? `${kind} · ${lines} · v${artifact.version}` : `${kind} · ${lines}`;
}

/** The card that stands in for the block inside the message. */
export function buildArtifactCard(artifact, onOpen) {
  const card = el('button', 'artifact-card');
  card.type = 'button';
  card.setAttribute('data-artifact-kind', artifact.kind);
  card.setAttribute('data-artifact-key', artifactKey(artifact));
  card.setAttribute('aria-label', `Open artifact: ${artifact.title}`);

  // A picture of the thing beats a word for it. What renders gets a real,
  // scaled-down rendering of itself; what does not gets its first lines.
  const thumb = buildThumbnail(artifact);

  const body = el('span', 'artifact-card-body');
  body.appendChild(el('span', 'artifact-card-title', artifact.title));
  body.appendChild(el('span', 'artifact-card-meta', labelFor(artifact)));

  // No "Open" pill: the card is the button, and the width it cost is width
  // the transcript gets back. The accessible name above still says what
  // pressing it does.
  card.append(thumb, body);
  card.addEventListener('click', () => onOpen(artifact));
  return card;
}

/**
 * Size the thumbnail is rendered at before being scaled into the card.
 *
 * Narrow on purpose: a page rendered at desktop width and then shrunk to a
 * 46 px stamp turns into a white square - its heading lands at under two
 * pixels. Rendered at phone width, the same shrink keeps the shape of the
 * thing recognisable, which is the only job a stamp this size has.
 */
const THUMB_RENDER_WIDTH = 360;
const THUMB_RENDER_HEIGHT = 250;

/**
 * A small picture of the artifact for the card.
 *
 * Rendered with `srcdoc`, deliberately: it needs no network request (so it
 * survives environments that block framed URLs) and it inherits the page's
 * CSP, which means the artifact's scripts do NOT run in it. For a thumbnail
 * that is the right trade - it is a still of the layout, not a live copy,
 * and nothing in it can act.
 */
export function buildThumbnail(artifact) {
  const shell = el('span', 'artifact-card-thumb');
  shell.setAttribute('data-kind', artifact.kind);

  if (artifact.kind === KIND_HTML || artifact.kind === KIND_SVG) {
    const frame = document.createElement('iframe');
    frame.className = 'artifact-thumb-frame';
    frame.setAttribute('sandbox', '');           // no scripts, no forms, nothing
    frame.setAttribute('tabindex', '-1');
    frame.setAttribute('aria-hidden', 'true');
    frame.setAttribute('scrolling', 'no');
    frame.width = String(THUMB_RENDER_WIDTH);
    frame.height = String(THUMB_RENDER_HEIGHT);
    frame.srcdoc = previewDocument(artifact);
    shell.appendChild(frame);
    return shell;
  }

  // Everything else reads rather than renders: show what it starts with.
  const lines = artifact.code.split('\n').slice(0, 6).join('\n');
  const pre = el('pre', 'artifact-thumb-text', lines);
  shell.appendChild(pre);
  return shell;
}

// ── The panel ──────────────────────────────────────────────────────────────

function panelSkeleton() {
  const panel = el('aside', 'artifact-panel');
  panel.id = 'artifact-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Artifact');

  const head = el('header', 'artifact-head');
  const titleWrap = el('div', 'artifact-head-title');
  const title = el('h2', 'artifact-title', 'Artifact');
  const meta = el('span', 'artifact-meta', '');
  titleWrap.append(title, meta);

  const tabs = el('div', 'artifact-tabs');
  const previewTab = el('button', 'artifact-tab is-active', 'Preview');
  previewTab.type = 'button';
  const codeTab = el('button', 'artifact-tab', 'Code');
  codeTab.type = 'button';
  tabs.append(previewTab, codeTab);

  const actions = el('div', 'artifact-actions');
  const versions = el('div', 'artifact-versions');
  const saveBtn = el('button', 'artifact-action artifact-save', 'Save');
  saveBtn.type = 'button';
  saveBtn.title = 'Keep this artifact in the library';
  const copyBtn = el('button', 'artifact-action', 'Copy');
  copyBtn.type = 'button';
  copyBtn.title = 'Copy the source';
  const downloadBtn = el('button', 'artifact-action', 'Download');
  downloadBtn.type = 'button';
  const newTabBtn = el('button', 'artifact-action', 'Open in tab');
  newTabBtn.type = 'button';
  const closeBtn = el('button', 'artifact-close', '\u00d7');
  closeBtn.type = 'button';
  closeBtn.title = 'Close (Esc)';
  closeBtn.setAttribute('aria-label', 'Close artifact');
  actions.append(versions, saveBtn, copyBtn, downloadBtn, newTabBtn, closeBtn);

  head.append(titleWrap, tabs, actions);

  const bodyEl = el('div', 'artifact-body');
  const preview = el('div', 'artifact-preview');
  const code = el('pre', 'artifact-code');
  code.hidden = true;
  bodyEl.append(preview, code);

  panel.append(head, bodyEl);
  return { panel, title, meta, previewTab, codeTab, versions, saveBtn, copyBtn, downloadBtn, newTabBtn, closeBtn, preview, code };
}

function ensurePanel() {
  if (state.panel) return state.panel;
  const parts = panelSkeleton();
  state.panel = parts;
  document.body.appendChild(parts.panel);

  parts.previewTab.addEventListener('click', () => showTab('preview'));
  parts.codeTab.addEventListener('click', () => showTab('code'));
  parts.closeBtn.addEventListener('click', () => closeArtifact({ dismissed: true }));
  parts.copyBtn.addEventListener('click', async () => {
    if (!state.current) return;
    try {
      await navigator.clipboard.writeText(state.current.code);
      parts.copyBtn.textContent = 'Copied';
      setTimeout(() => { parts.copyBtn.textContent = 'Copy'; }, 1200);
    } catch { /* clipboard denied — the Code tab still shows the source */ }
  });
  parts.saveBtn.addEventListener('click', async () => {
    if (!state.current) return;
    const replacing = state.savedTitles.has(state.current.title);
    parts.saveBtn.disabled = true;
    const kept = await saveArtifact(state.current);
    parts.saveBtn.textContent = kept ? (replacing ? 'Updated' : 'Saved') : 'Failed';
    setTimeout(() => {
      parts.saveBtn.disabled = false;
      syncSaveButton();
    }, 1400);
  });
  parts.downloadBtn.addEventListener('click', () => downloadArtifact(state.current));
  parts.newTabBtn.addEventListener('click', () => openArtifactInTab(state.current));

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.panel && document.body.classList.contains('artifact-open')) {
      closeArtifact({ dismissed: true });
    }
  });
  return parts;
}

function showTab(which) {
  const parts = state.panel;
  if (!parts) return;
  const isPreview = which === 'preview';
  parts.previewTab.classList.toggle('is-active', isPreview);
  parts.codeTab.classList.toggle('is-active', !isPreview);
  parts.preview.hidden = !isPreview;
  parts.code.hidden = isPreview;
}

const EXTENSION = {
  [KIND_HTML]: 'html',
  [KIND_SVG]: 'svg',
  [KIND_MERMAID]: 'mmd',
  [KIND_MARKDOWN]: 'md',
};

const CODE_EXTENSION = {
  javascript: 'js', typescript: 'ts', python: 'py', rust: 'rs', ruby: 'rb',
  csharp: 'cs', powershell: 'ps1', markdown: 'md', yaml: 'yml',
};

function fileNameFor(artifact) {
  const base = (artifact.title || 'artifact')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'artifact';
  const ext = EXTENSION[artifact.kind] || CODE_EXTENSION[artifact.lang] || artifact.lang || 'txt';
  return `${base}.${ext}`;
}

function downloadArtifact(artifact) {
  if (!artifact) return;
  const blob = new Blob([artifact.code], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileNameFor(artifact);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/**
 * Markup for the sandboxed frame. An SVG or a Mermaid diagram is wrapped in
 * the smallest page that centres it; an HTML artifact is served as written,
 * because a page the model wrote is the artifact.
 */
export function previewDocument(artifact) {
  if (!artifact) return '';
  if (artifact.kind === KIND_HTML) {
    const hasShell = /<html[\s>]/i.test(artifact.code);
    return hasShell ? artifact.code : `<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;padding:16px;font:14px/1.5 system-ui,sans-serif;color:#111;background:#fff}</style>
</head><body>${artifact.code}</body></html>`;
  }
  if (artifact.kind === KIND_SVG) {
    return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;display:grid;place-items:center;background:#fff}svg{max-width:100%;max-height:100%}</style>
</head><body>${artifact.code}</body></html>`;
  }
  if (artifact.kind === KIND_MERMAID) {
    const source = artifact.code.replace(/<\/script>/gi, '<\\/script>');
    return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%;display:grid;place-items:center;background:#fff}</style>
</head><body><pre class="mermaid">${source.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))}</pre>
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({ startOnLoad: true });
<\/script></body></html>`;
  }
  return '';
}

async function renderPreview(artifact) {
  const parts = ensurePanel();
  const host = parts.preview;
  host.textContent = '';

  if (artifact.kind === KIND_MARKDOWN || artifact.kind === KIND_CODE) {
    // Markdown and code are read, not run: no frame, no server round trip.
    const pre = el('pre', 'artifact-plain');
    pre.textContent = artifact.code;
    host.appendChild(pre);
    return;
  }

  const html = previewDocument(artifact);
  if (!html) return;

  // Draw it at once from `srcdoc`, which needs no request and therefore
  // always works, and try for the live version underneath. Waiting for the
  // live frame before showing anything meant a blank panel for as long as
  // the attempt took - and a permanently blank one wherever framing a URL
  // is refused.
  showStaticFallback(host, null, artifact);

  const frame = document.createElement('iframe');
  frame.className = 'artifact-frame';
  // No allow-same-origin: the frame runs in an opaque origin and cannot
  // reach this app's cookies, storage, DOM or API. allow-forms/modals keep
  // ordinary pages usable inside it.
  frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-modals allow-popups');
  frame.setAttribute('title', artifact.title || 'Artifact preview');
  frame.style.display = 'none';
  host.appendChild(frame);
  const seq = ++previewSeq;

  try {
    const response = await fetch('/api/artifact/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ html }),
    });
    if (!response.ok) throw new Error(`preview ${response.status}`);
    const data = await response.json();
    // The frame reports for itself that it rendered (the served copy carries
    // a beacon). `load` alone would not do: a frame blocked by a policy or an
    // extension fires it too, on the error page it got instead, and the panel
    // would sit there showing nothing with no way to say why.
    let live = false;
    const showLive = () => {
      // Not for an artifact the user has already moved on from.
      if (live || seq !== previewSeq || !frame.isConnected) return;
      live = true;
      host.querySelectorAll('.artifact-static').forEach((node) => node.remove());
      frame.style.display = '';
    };
    const onMessage = (event) => {
      if (event.source === frame.contentWindow && event.data?.__odysseusArtifact === 'ready') {
        window.removeEventListener('message', onMessage);
        showLive();
      }
    };
    window.addEventListener('message', onMessage);
    frame.src = data.url;
    state.current = { ...artifact, previewUrl: data.url };
    // The wait decides when to stop saying nothing about the live copy - not
    // whether it may still arrive. A slow machine, a cold server or a phone
    // can take longer than this, and a frame that reports in late is still a
    // frame that works: it replaces the still whenever it gets here.
    setTimeout(() => {
      if (!live && seq === previewSeq) annotateStatic(host, data.url);
    }, LIVE_FRAME_WAIT_MS);
  } catch (error) {
    // The still is already up; the tab link is what we cannot offer.
    frame.remove();
    annotateStatic(host, null);
  }
}

/** Say that the rendering on screen is a still, and where the live one is. */
function annotateStatic(host, url) {
  const wrap = host.querySelector('.artifact-static');
  if (!wrap || wrap.querySelector('.artifact-static-banner')) return;
  const banner = el('div', 'artifact-static-banner');
  banner.appendChild(el('span', null, 'Static preview - scripts do not run in this view.'));
  if (url) {
    const link = el('a', 'artifact-note-link', 'Open the live version in a tab');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener';
    banner.appendChild(link);
  }
  wrap.insertBefore(banner, wrap.firstChild);
}

/**
 * The live frame never reported in - some browsers and extensions refuse to
 * frame a served URL at all. Rather than an apology in an empty panel, show
 * the artifact rendered from `srcdoc`, which needs no request. Its scripts
 * cannot run there (the page's CSP reaches into a srcdoc frame), so the
 * banner says so and points at the tab, where they do.
 */
/**
 * How long the panel waits before admitting it is showing a still.
 *
 * Only about the message: the live frame replaces the still whenever it
 * reports in, however long that takes.
 */
const LIVE_FRAME_WAIT_MS = 2500;

/** Which preview the panel is on, so a late frame for an earlier one is
 *  ignored instead of appearing over the artifact now on screen. */
let previewSeq = 0;

function showStaticFallback(host, url, artifact) {
  if (host.querySelector('.artifact-static')) return;
  host.querySelectorAll('iframe.artifact-frame').forEach((frame) => frame.remove());

  const wrap = el('div', 'artifact-static');

  const frame = document.createElement('iframe');
  frame.className = 'artifact-frame';
  frame.setAttribute('sandbox', '');
  frame.setAttribute('title', `${artifact.title} (static preview)`);
  frame.srcdoc = previewDocument(artifact);

  wrap.appendChild(frame);
  host.appendChild(wrap);
}

function openArtifactInTab(artifact) {
  if (!artifact) return;
  if (artifact.previewUrl) {
    window.open(artifact.previewUrl, '_blank', 'noopener');
    return;
  }
  const blob = new Blob([artifact.code], { type: 'text/plain;charset=utf-8' });
  window.open(URL.createObjectURL(blob), '_blank', 'noopener');
}

function renderVersions(artifact) {
  const parts = ensurePanel();
  parts.versions.textContent = '';
  const siblings = (state.bySession.get(artifact.key) || []).filter((a) => a.complete !== false);
  if (siblings.length < 2) return;
  siblings.forEach((sibling) => {
    const pill = el('button', 'artifact-version', `v${sibling.version}`);
    pill.type = 'button';
    pill.classList.toggle('is-active', sibling.version === artifact.version);
    pill.addEventListener('click', () => openArtifact(sibling));
    parts.versions.appendChild(pill);
  });
}

/** Show an artifact in the panel. */
export function openArtifact(artifact) {
  if (!artifact) return;
  const parts = ensurePanel();
  // Clicking a card is an instruction, so a key dismissed earlier stops
  // counting: the panel opens and stays until it is closed again.
  state.dismissed.delete(artifact.key);
  state.current = artifact;
  parts.title.textContent = artifact.title;
  parts.meta.textContent = labelFor(artifact);
  parts.code.textContent = artifact.code;
  renderVersions(artifact);
  syncSaveButton();
  showTab(artifact.kind === KIND_MARKDOWN || artifact.kind === KIND_CODE ? 'code' : 'preview');
  document.body.classList.add('artifact-open');
  renderPreview(artifact);
  document.querySelectorAll('.artifact-card.is-open').forEach((card) => card.classList.remove('is-open'));
  const card = document.querySelector(`.artifact-card[data-artifact-id="${artifact.id}"]`);
  if (card) card.classList.add('is-open');
}

export function closeArtifact({ dismissed = false } = {}) {
  document.body.classList.remove('artifact-open');
  if (dismissed && state.current?.key) state.dismissed.add(state.current.key);
  if (state.panel) state.panel.preview.textContent = '';
  document.querySelectorAll('.artifact-card.is-open').forEach((card) => card.classList.remove('is-open'));
  state.current = null;
}

// ── Watching the chat ──────────────────────────────────────────────────────

function messageText(messageEl) {
  // The rendered message is the only source there is, and it is enough: the
  // fenced blocks survive rendering as <pre class="code-block"><code>.
  const parts = [];
  messageEl.querySelectorAll('pre.code-block').forEach((pre) => {
    const code = pre.querySelector('code');
    if (!code) return;
    const lang = code.getAttribute('data-lang') || '';
    parts.push(`\`\`\`${lang}\n${code.textContent}\n\`\`\``);
  });
  return parts.join('\n\n');
}

function upgradeMessage(messageEl, { isHistoryReplay }) {
  // Live means this very reply was written in front of the user.
  const isLive = state.liveMessages.has(messageEl);
  const blocks = Array.from(messageEl.querySelectorAll('pre.code-block:not([data-artifact-checked])'));
  if (!blocks.length) return;

  const messageId = messageEl.getAttribute('data-artifact-msg')
    || `m${Math.random().toString(36).slice(2, 9)}`;
  messageEl.setAttribute('data-artifact-msg', messageId);

  blocks.forEach((pre, index) => {
    pre.setAttribute('data-artifact-checked', '1');
    const codeEl = pre.querySelector('code');
    if (!codeEl) return;
    const lang = codeEl.getAttribute('data-lang') || '';
    const code = codeEl.textContent || '';
    const verdict = classifyBlock({ lang, code });
    if (!verdict.qualifies) return;

    const title = deriveTitle({ kind: verdict.kind, lang: verdict.lang, code });
    const key = `${verdict.kind}:${titleKey(title)}`;
    // Deleted here means deleted on the way back too: the block stays an
    // ordinary code block. One quiet link offers it back, because deleting
    // the wrong thing should cost a click, not the artifact.
    if (state.hidden.has(key)) {
      offerRestore(pre, key);
      return;
    }
    const siblings = state.bySession.get(key) || [];
    const artifact = {
      id: `${messageId}-${index}`,
      kind: verdict.kind,
      lang: verdict.lang,
      lines: verdict.lines,
      reason: verdict.reason,
      title,
      code,
      key,
      version: siblings.length + 1,
      complete: true,
    };
    state.bySession.set(key, [...siblings, artifact]);

    const card = buildArtifactCard(artifact, openArtifact);
    card.setAttribute('data-artifact-id', artifact.id);
    pre.classList.add('is-artifact-source');
    pre.hidden = true;
    pre.parentNode.insertBefore(card, pre);

    state.knownCards.add(artifact.id);
    refreshArtifactCount();
    if (shouldAutoOpen({
      isLive,
      isHistoryReplay,
      dismissedKeys: Array.from(state.dismissed),
      key: artifact.key,
    })) {
      openArtifact(artifact);
    }
  });
}

/**
 * Take deleted artifacts out of the conversation.
 *
 * The transcript itself is untouched: the code block the card was made from
 * comes back into view, exactly as the model wrote it. What goes away is the
 * offer to open it as an artifact - which is what the user asked to be rid
 * of when they deleted it.
 */
export function hideArtifacts(keys) {
  const gone = keys.map((key) => String(key || '')).filter(Boolean);
  if (!gone.length) return;
  gone.forEach((key) => state.hidden.add(key));
  persistHiddenKeys();

  const chat = document.getElementById('chat-container');
  if (chat) {
    gone.forEach((key) => {
      chat.querySelectorAll(`.artifact-card[data-artifact-key="${CSS.escape(key)}"]`)
        .forEach((card) => {
          const source = card.nextElementSibling;
          state.knownCards.delete(card.getAttribute('data-artifact-id'));
          card.remove();
          if (source && source.classList.contains('is-artifact-source')) {
            source.hidden = false;
            source.classList.remove('is-artifact-source');
            // Offer the way back now, not only after the next reload.
            offerRestore(source, key);
          }
        });
      state.bySession.delete(key);
    });
  }
  if (state.current && gone.includes(artifactKey(state.current))) closeArtifact();
}

/** A one-line way back for an artifact that was deleted. */
function offerRestore(pre, key) {
  if (pre.previousElementSibling?.classList.contains('artifact-restore')) return;
  const link = el('button', 'artifact-restore', 'Przywr\u00f3\u0107 jako artefakt');
  link.type = 'button';
  link.title = 'Show this block as an artifact card again';
  link.addEventListener('click', () => {
    state.hidden.delete(key);
    persistHiddenKeys();
    const message = pre.closest('.msg-ai');
    link.remove();
    if (!message) return;
    // Only this block: re-reading the whole message would rebuild the cards
    // that are already there and count them as new versions of themselves.
    pre.removeAttribute('data-artifact-checked');
    upgradeMessage(message, { isHistoryReplay: true });
  });
  pre.parentNode.insertBefore(link, pre);
}

function scan({ isHistoryReplay }) {
  const container = document.getElementById('chat-container');
  if (!container) return;

  // A different conversation is on screen when none of the cards we made are
  // in the document any more. Its artifacts are not this one's.
  if (state.knownCards.size) {
    const stillHere = [...state.knownCards].some(
      (id) => document.querySelector(`.artifact-card[data-artifact-id="${id}"]`),
    );
    if (!stillHere) {
      state.knownCards.clear();
      state.bySession.clear();
      state.dismissed.clear();
      if (state.current) closeArtifact();
    }
  }

  container.querySelectorAll('.msg-ai').forEach((messageEl) => {
    upgradeMessage(messageEl, { isHistoryReplay });
  });
}

let scanTimer = null;
function scheduleScan() {
  if (scanTimer) clearTimeout(scanTimer);
  // A streaming reply mutates constantly; settle before deciding, so a
  // half-written block is not filed as an artifact and then replaced.
  scanTimer = setTimeout(() => {
    scanTimer = null;
    scan({ isHistoryReplay: false });
  }, 260);
}

/** Every artifact of the conversation on screen, newest last. */
export function currentArtifacts() {
  const all = [];
  state.bySession.forEach((versions) => all.push(...versions));
  return all;
}

/** The session the chat is on, as far as the URL knows. */
function currentSessionId() {
  const hash = (window.location.hash || '').replace(/^#/, '');
  return /^[0-9a-f-]{8,}$/i.test(hash) ? hash : '';
}

/** Keep this artifact past the conversation that made it. */
export async function saveArtifact(artifact) {
  if (state.hidden.delete(artifactKey(artifact))) persistHiddenKeys();
  try {
    const response = await fetch('/api/artifacts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: artifact.title,
        kind: artifact.kind,
        lang: artifact.lang,
        code: artifact.code,
        session_id: currentSessionId(),
      }),
    });
    if (!response.ok) return false;
    await refreshArtifactCount();
    return true;
  } catch {
    return false;
  }
}

/** What the library holds. */
async function fetchSavedArtifacts() {
  try {
    const response = await fetch('/api/artifacts');
    if (!response.ok) return [];
    const data = await response.json();
    return (data.artifacts || []).map((row) => ({ ...row, saved: true, version: 1, lines: (row.code || '').split('\n').length }));
  } catch {
    return [];
  }
}

/** The badge counts what is kept, not what happens to be on screen. */
async function refreshArtifactCount() {
  const saved = await fetchSavedArtifacts();
  state.savedTitles = new Set(saved.map((row) => row.title));
  const badge = document.getElementById('artifact-count');
  if (badge) {
    badge.textContent = String(saved.length);
    badge.hidden = saved.length === 0;
  }
  markSavedCards();
  syncSaveButton();
}

/** Mark the cards whose artifact is already kept. */
function markSavedCards() {
  document.querySelectorAll('.artifact-card').forEach((card) => {
    const title = card.querySelector('.artifact-card-title')?.textContent || '';
    card.classList.toggle('is-saved', state.savedTitles.has(title));
  });
}

/**
 * The button says what pressing it will do: add this artifact to the
 * library, or replace the copy already in it. A revision that came back
 * from Edit lands here as "Update" - visible, and still a decision.
 */
function syncSaveButton() {
  const parts = state.panel;
  if (!parts || !state.current) return;
  const known = state.savedTitles.has(state.current.title);
  parts.saveBtn.textContent = known ? 'Update' : 'Save';
  parts.saveBtn.title = known
    ? `Replace "${state.current.title}" in the library with this version`
    : 'Keep this artifact in the library';
}

/**
 * The sidebar list: what this conversation has produced, as cards, with the
 * same thumbnails as in the transcript. It is a way back to an artifact
 * scrolled far out of view - the transcript stays the place they live.
 */
export async function openArtifactList() {
  const existing = document.getElementById('artifact-list-panel');
  if (existing) {
    existing.remove();
    return;
  }
  const panel = el('aside', 'artifact-panel artifact-list-panel');
  panel.id = 'artifact-list-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Saved artifacts');

  const head = el('header', 'artifact-head');
  const titleWrap = el('div', 'artifact-head-title');
  titleWrap.appendChild(el('h2', 'artifact-title', 'Artifacts'));
  const subtitle = el('span', 'artifact-meta', 'saved');
  titleWrap.appendChild(subtitle);

  const actions = el('div', 'artifact-actions');
  const selectBtn = el('button', 'artifact-action', 'Wybierz');
  selectBtn.type = 'button';
  selectBtn.title = 'Select artifacts to delete';
  const deleteBtn = el('button', 'artifact-action artifact-danger', 'Usu\u0144');
  deleteBtn.type = 'button';
  deleteBtn.hidden = true;
  const close = el('button', 'artifact-close', '\u00d7');
  close.type = 'button';
  close.setAttribute('aria-label', 'Close the artifact library');
  close.addEventListener('click', () => panel.remove());
  actions.append(selectBtn, deleteBtn, close);
  head.append(titleWrap, actions);

  const list = el('div', 'artifact-list');
  panel.append(head, list);
  document.body.appendChild(panel);

  const selection = new Set();
  let selecting = false;
  // What is on screen right now, so a deletion can name what it removed.
  let shown = [];

  function renderDeleteLabel() {
    deleteBtn.textContent = selection.size
      ? `Usu\u0144 (${selection.size})`
      : 'Usu\u0144';
    deleteBtn.disabled = selection.size === 0;
  }

  async function draw() {
    const items = await fetchSavedArtifacts();
    shown = items;
    subtitle.textContent = items.length === 1 ? '1 saved' : `${items.length} saved`;
    list.textContent = '';
    if (!items.length) {
      list.appendChild(el('p', 'artifact-list-empty',
        'Empty. Open an artifact in the chat and press Save to keep it here.'));
      return;
    }
    items.forEach((artifact) => {
      const row = el('div', 'artifact-row');
      row.setAttribute('data-id', artifact.id);

      if (selecting) {
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.className = 'artifact-pick';
        box.checked = selection.has(artifact.id);
        box.setAttribute('aria-label', `Select ${artifact.title}`);
        box.addEventListener('change', () => {
          if (box.checked) selection.add(artifact.id);
          else selection.delete(artifact.id);
          renderDeleteLabel();
        });
        row.appendChild(box);
      }

      const card = buildArtifactCard(artifact, (chosen) => {
        if (selecting) return;
        panel.remove();
        openArtifact(chosen);
      });
      row.appendChild(card);

      const editBtn = el('button', 'artifact-action artifact-edit', 'Edit');
      editBtn.type = 'button';
      editBtn.title = 'Describe the changes to make';
      editBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        openEditDialog(artifact, panel);
      });
      row.appendChild(editBtn);

      list.appendChild(row);
    });
  }

  selectBtn.addEventListener('click', () => {
    selecting = !selecting;
    selection.clear();
    selectBtn.classList.toggle('is-active', selecting);
    selectBtn.textContent = selecting ? 'Anuluj' : 'Wybierz';
    deleteBtn.hidden = !selecting;
    renderDeleteLabel();
    draw();
  });

  deleteBtn.addEventListener('click', async () => {
    if (!selection.size) return;
    const ids = [...selection];
    const keys = shown.filter((row) => selection.has(row.id)).map(artifactKey);
    deleteBtn.disabled = true;
    try {
      await fetch('/api/artifacts/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids }),
      });
      hideArtifacts(keys);
    } finally {
      selection.clear();
      selecting = false;
      selectBtn.classList.remove('is-active');
      selectBtn.textContent = 'Wybierz';
      deleteBtn.hidden = true;
      await draw();
      await refreshArtifactCount();
    }
  });

  renderDeleteLabel();
  await draw();
}

/**
 * Ask what should change, then ask the model for it.
 *
 * The revision goes through the conversation rather than through an API:
 * the model rewrites the artifact in its reply, the detector picks the new
 * version up, and the panel shows it - which is the only way this can work
 * for every model, including the ones that cannot call a tool.
 */
export function openEditDialog(artifact, parentPanel) {
  document.getElementById('artifact-edit-dialog')?.remove();

  const wrap = el('div', 'artifact-edit-dialog');
  wrap.id = 'artifact-edit-dialog';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-label', `Changes to ${artifact.title}`);

  wrap.appendChild(el('h3', 'artifact-edit-title', artifact.title));
  wrap.appendChild(el('p', 'artifact-edit-hint', 'Co ma si\u0119 zmieni\u0107?'));

  const input = document.createElement('textarea');
  input.className = 'artifact-edit-input';
  input.rows = 4;
  input.placeholder = 'np. dodaj tryb ciemny i zapis do localStorage';
  wrap.appendChild(input);

  const row = el('div', 'artifact-edit-actions');
  const cancel = el('button', 'artifact-action', 'Anuluj');
  cancel.type = 'button';
  cancel.addEventListener('click', () => wrap.remove());
  const send = el('button', 'artifact-action artifact-primary', 'Wdr\u00f3\u017c zmiany');
  send.type = 'button';
  send.addEventListener('click', () => {
    const instruction = input.value.trim();
    if (!instruction) {
      input.focus();
      return;
    }
    const sent = requestArtifactRevision(artifact, instruction);
    wrap.remove();
    if (sent && parentPanel) parentPanel.remove();
  });
  row.append(cancel, send);
  wrap.appendChild(row);

  document.body.appendChild(wrap);
  input.focus();
}

/**
 * Put the revision request into the composer and send it.
 *
 * Driving the composer is deliberate: it is the same path a typed message
 * takes, so the request carries the conversation's model, project and
 * settings with it, and the reply lands in the transcript where the
 * artifact belongs.
 */
export function buildRevisionPrompt(artifact, instruction) {
  const fence = '```';
  return [
    `Popraw artefakt "${artifact.title}". Zmiany do wdro\u017cenia:`,
    instruction,
    '',
    'Odpowiedz ca\u0142ym poprawionym plikiem w jednym bloku kodu, bez skr\u00f3t\u00f3w.',
    '',
    `${fence}${artifact.lang || artifact.kind}`,
    artifact.code,
    fence,
  ].join('\n');
}

function requestArtifactRevision(artifact, instruction) {
  const composer = document.querySelector('#message, #message-input, #chat-form textarea');
  if (!composer) return false;
  composer.value = buildRevisionPrompt(artifact, instruction);
  composer.dispatchEvent(new Event('input', { bubbles: true }));
  const send = document.querySelector('#chat-form button[type="submit"], .send-btn');
  if (send) {
    send.click();
    return true;
  }
  composer.focus();
  return false;
}

/**
 * Start watching the chat.
 *
 * The first pass is history: whatever is already on screen becomes cards
 * without the panel opening. Everything after it is the conversation the
 * user is in, and a new artifact there opens by itself - which is the point
 * of the feature.
 */
export function initArtifacts() {
  if (!HAS_DOM || state.observer) return;
  const container = document.getElementById('chat-container');
  if (!container) return;

  scan({ isHistoryReplay: true });
  state.replayed = true;
  refreshArtifactCount();

  const sidebarButton = document.getElementById('tool-artifacts-btn');
  if (sidebarButton) {
    sidebarButton.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      openArtifactList();
    });
  }

  state.observer = new MutationObserver(() => {
    // Record who is streaming on every mutation, not on the debounced scan:
    // by the time the scan runs the reply may already be finished and the
    // class gone, and then nothing would ever count as live.
    document
      .querySelectorAll('.msg-ai.streaming')
      .forEach((messageEl) => state.liveMessages.add(messageEl));
    scheduleScan();
  });
  state.observer.observe(container, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class'],
  });
}

if (HAS_DOM) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initArtifacts());
  } else {
    initArtifacts();
  }
}

export { state as _artifactState };
