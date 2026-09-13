const CATEGORY_ORDER = [
  'system',
  'conversation',
  'memory',
  'project',
  'files_rag',
  'knowledge',
  'tools',
  'mcp',
];

let inspector = null;
let trigger = null;

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function formatTokens(value, estimated = true) {
  const number = Number(value || 0);
  return `${estimated ? '~' : ''}${number.toLocaleString()}`;
}

export function closeContextInspector() {
  if (!inspector) return;
  inspector.remove();
  inspector = null;
  if (trigger) {
    trigger.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.focus();
  }
  trigger = null;
}

function positionInspector(dialog, pill) {
  if (window.innerWidth <= 768) return;
  const rect = pill.getBoundingClientRect();
  dialog.style.top = `${Math.round(rect.bottom + 8)}px`;
  dialog.style.left = `${Math.max(8, Math.round(rect.left - 170))}px`;
  requestAnimationFrame(() => {
    const popup = dialog.getBoundingClientRect();
    if (popup.right > window.innerWidth - 8) {
      dialog.style.left = `${Math.max(8, window.innerWidth - popup.width - 8)}px`;
    }
    if (popup.bottom > window.innerHeight - 8) {
      dialog.style.top = `${Math.max(8, rect.top - popup.height - 8)}px`;
    }
  });
}

function lensButton(label, lens, active, render) {
  const button = node('button', 'context-inspector-lens', label);
  button.type = 'button';
  button.dataset.lens = lens;
  button.setAttribute('aria-pressed', String(active));
  button.addEventListener('click', () => render(lens));
  return button;
}

function renderCategory(category, estimated) {
  const details = node('details', 'context-inspector-category');
  const summary = node('summary');
  const label = node('span', 'context-inspector-category-label', category.label);
  const meta = node(
    'span',
    'context-inspector-category-meta',
    `${formatTokens(category.used_tokens, estimated)} · ${category.trust}`,
  );
  summary.append(label, meta);
  details.appendChild(summary);
  const list = node('ul', 'context-inspector-items');
  list.setAttribute('role', 'list');
  if (!category.items.length) {
    const empty = node('li', 'context-inspector-empty', 'No persisted items');
    list.appendChild(empty);
  } else {
    category.items.forEach((item) => {
      const row = node('li', 'context-inspector-item');
      const title = node('span', '', item.label);
      const provenance = item.provenance || {};
      const source = node(
        'span',
        'context-inspector-item-source',
        `${provenance.origin || 'unknown'} · ${provenance.source || 'unknown'} · ${formatTokens(item.tokens, estimated)}`,
      );
      const trust = node(
        'span',
        `context-inspector-trust ${item.trust === 'untrusted' ? 'untrusted' : ''}`,
        item.trust === 'untrusted' ? 'Untrusted' : 'Trusted',
      );
      row.append(title, source, trust);
      list.appendChild(row);
    });
  }
  details.appendChild(list);
  return details;
}

function buildInspector(payload, callbacks) {
  const dialog = node('section', 'context-inspector');
  dialog.id = 'context-inspector';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-label', 'Context Inspector');
  dialog.tabIndex = -1;

  const header = node('header', 'context-inspector-header');
  const title = node('div', 'context-inspector-title', 'Context Inspector');
  const close = node('button', 'context-inspector-close', '×');
  close.type = 'button';
  close.setAttribute('aria-label', 'Close Context Inspector');
  close.addEventListener('click', closeContextInspector);
  header.append(title, close);
  dialog.appendChild(header);

  const lensControls = node('div', 'context-inspector-lenses');
  const summary = node('div', 'context-inspector-summary');
  const categories = node('div', 'context-inspector-categories');
  const budget = payload.budget || {};

  const render = (lensName) => {
    lensControls.replaceChildren(
      lensButton('Session', 'session', lensName === 'session', render),
      lensButton('Last turn', 'last_turn', lensName === 'last_turn', render),
    );
    const lens = payload.lenses?.[lensName] || {};
    const estimated = lens.usage_source !== 'real';
    summary.replaceChildren();
    const usage = node('div', 'context-inspector-usage');
    usage.append(
      node('strong', '', `${formatTokens(lens.used_tokens, estimated)} / ${formatTokens(lens.limit_tokens, false)}`),
      node('span', '', `${Number(lens.percent || 0).toFixed(1)}%`),
    );
    const bar = node('div', 'context-inspector-bar');
    const fill = node('div', 'context-inspector-fill');
    fill.style.width = `${Math.max(0, Math.min(100, Number(lens.percent || 0)))}%`;
    bar.appendChild(fill);
    const profile = payload.context_profile || {};
    const budgetText = budget.configured_soft_explicit
      ? `Explicit budget ${formatTokens(budget.effective_soft, false)}`
      : `Auto budget ${formatTokens(budget.effective_soft, false)} · ${profile.tier || 'unknown'} profile`;
    summary.append(usage, bar, node('div', 'context-inspector-budget', budgetText));
    categories.replaceChildren();
    CATEGORY_ORDER.forEach((id) => {
      const category = payload.categories?.find((item) => item.id === id);
      if (category) categories.appendChild(renderCategory(category, true));
    });
  };

  dialog.append(lensControls, summary, categories);

  const footer = node('footer', 'context-inspector-actions');
  if (payload.actions?.can_compact) {
    const compact = node('button', 'context-inspector-action primary', 'Compact conversation');
    compact.type = 'button';
    compact.addEventListener('click', async () => {
      compact.disabled = true;
      const ok = await callbacks.onCompact?.();
      if (!ok) compact.disabled = false;
    });
    footer.appendChild(compact);
  }
  const memory = node('button', 'context-inspector-action', 'Open Memory');
  memory.type = 'button';
  memory.addEventListener('click', () => {
    closeContextInspector();
    document.getElementById('tool-memory-btn')?.click();
  });
  const settings = node('button', 'context-inspector-action', 'Agent settings');
  settings.type = 'button';
  settings.addEventListener('click', () => {
    closeContextInspector();
    document.getElementById('user-bar-settings')?.click();
  });
  footer.append(memory, settings);
  dialog.appendChild(footer);
  render('session');
  dialog.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeContextInspector();
    }
  });
  return dialog;
}

export async function toggleContextInspector({
  sessionId,
  pill,
  onCompact,
}) {
  if (inspector) {
    closeContextInspector();
    return;
  }
  if (!sessionId || !pill) return;
  const response = await fetch(
    `/api/session/${encodeURIComponent(sessionId)}/context_breakdown`,
    { credentials: 'same-origin' },
  );
  if (!response.ok) throw new Error(`Context breakdown failed (${response.status})`);
  const payload = await response.json();
  inspector = buildInspector(payload, { onCompact });
  trigger = pill;
  pill.classList.add('open');
  pill.setAttribute('aria-expanded', 'true');
  document.body.appendChild(inspector);
  positionInspector(inspector, pill);
  inspector.focus();
}

export function isContextInspectorOpen() {
  return Boolean(inspector);
}

export default {
  toggleContextInspector,
  closeContextInspector,
  isContextInspectorOpen,
};
