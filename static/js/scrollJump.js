// static/js/scrollJump.js
//
// Floating jump arrows for long replies. While the user scrolls inside a long
// message, a small arrow appears above the composer: scrolling down shows a
// down arrow that jumps to the end of that reply; scrolling back up shows an up
// arrow that jumps to the start of the message. The arrows fade out once
// scrolling stops so they never sit over the text permanently.
//
// The shell's existing scroll-to-bottom control (#scroll-bottom-btn, styled by
// .scroll-nav-btn) is reused as the down arrow, so there is one scroll
// navigation component rather than two. The decision logic is a pure function
// (computeJumpState) so it can be unit tested without a DOM.

export const IDLE_HIDE_MS = 1800;
// A message counts as "long" when it is taller than this share of the viewport.
export const LONG_MESSAGE_RATIO = 0.8;
// Pixels of tolerance before the start/end of a message counts as reached.
export const EDGE_SLACK = 32;

/**
 * Decide which arrow (if any) to show.
 *
 * @param {object} s
 * @param {'up'|'down'|null} s.direction  last scroll direction
 * @param {number} s.scrollTop            scroll offset of the history box
 * @param {number} s.clientHeight         visible height of the history box
 * @param {number} s.msgTop               top of the current message (box coords)
 * @param {number} s.msgBottom            bottom of the current message (box coords)
 * @returns {'up'|'down'|'none'}
 */
export function computeJumpState({ direction, scrollTop, clientHeight, msgTop, msgBottom }) {
  if (!direction || !(clientHeight > 0)) return 'none';
  const msgHeight = msgBottom - msgTop;
  if (!(msgHeight > clientHeight * LONG_MESSAGE_RATIO)) return 'none';
  if (direction === 'down') {
    const viewBottom = scrollTop + clientHeight;
    return msgBottom > viewBottom + EDGE_SLACK ? 'down' : 'none';
  }
  if (direction === 'up') {
    return msgTop < scrollTop - EDGE_SLACK ? 'up' : 'none';
  }
  return 'none';
}

const DOWN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/><line x1="12" y1="4" x2="12" y2="15"/></svg>';
const UP_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 15 12 9 18 15"/><line x1="12" y1="20" x2="12" y2="9"/></svg>';

// The message whose box straddles the vertical middle of the viewport; falls
// back to the last message that starts above the middle.
function pickCurrentMessage(box) {
  const boxRect = box.getBoundingClientRect();
  const centerY = boxRect.top + box.clientHeight / 2;
  let best = null;
  for (const m of box.querySelectorAll('.msg')) {
    const r = m.getBoundingClientRect();
    if (r.top <= centerY && r.bottom >= centerY) return m;
    if (r.top <= centerY) best = m;
  }
  return best;
}

function makeButton(existing, id, cls, label, icon) {
  const btn = existing || document.createElement('button');
  btn.type = 'button';
  btn.id = id;
  btn.className = 'scroll-nav-btn ' + cls;
  btn.title = label;
  btn.setAttribute('aria-label', label);
  btn.innerHTML = icon;
  return btn;
}

export function initScrollJump(box = document.getElementById('chat-history')) {
  if (!box || box._scrollJumpWired) return null;
  box._scrollJumpWired = true;
  const container = box.parentElement || document.body;

  const wrap = document.createElement('div');
  wrap.className = 'scroll-jump';
  wrap.id = 'scroll-jump';
  const upBtn = makeButton(null, 'scroll-top-btn', 'scroll-jump-up', 'Jump to the start of this message', UP_ICON);
  const downBtn = makeButton(document.getElementById('scroll-bottom-btn'), 'scroll-bottom-btn', 'scroll-jump-down', 'Jump to the end of this reply', DOWN_ICON);
  wrap.appendChild(upBtn);
  wrap.appendChild(downBtn);
  container.appendChild(wrap);

  let lastTop = box.scrollTop;
  let direction = null;
  let target = null; // { top, bottom } of the current message in box coordinates
  let raf = 0;
  let hideTimer = 0;
  let hovering = false;

  function place() {
    // Sit just above the composer, whatever height it currently has.
    const bar = container.querySelector('.chat-input-bar');
    const cRect = container.getBoundingClientRect();
    const bottom = bar ? Math.max(90, cRect.bottom - bar.getBoundingClientRect().top + 14) : 150;
    wrap.style.setProperty('--scroll-jump-bottom', bottom + 'px');
  }

  function show(which) {
    upBtn.classList.toggle('show', which === 'up');
    downBtn.classList.toggle('show', which === 'down');
    if (which !== 'none') place();
    clearTimeout(hideTimer);
    if (which !== 'none') hideTimer = setTimeout(() => { if (!hovering) show('none'); }, IDLE_HIDE_MS);
  }

  function evaluate() {
    raf = 0;
    const msg = pickCurrentMessage(box);
    if (!msg) { show('none'); return; }
    const boxRect = box.getBoundingClientRect();
    const r = msg.getBoundingClientRect();
    const top = box.scrollTop + (r.top - boxRect.top);
    target = { top, bottom: top + r.height };
    show(computeJumpState({
      direction,
      scrollTop: box.scrollTop,
      clientHeight: box.clientHeight,
      msgTop: target.top,
      msgBottom: target.bottom,
    }));
  }

  box.addEventListener('scroll', () => {
    const top = box.scrollTop;
    if (top > lastTop + 1) direction = 'down';
    else if (top < lastTop - 1) direction = 'up';
    lastTop = top;
    if (!raf) raf = requestAnimationFrame(evaluate);
  }, { passive: true });

  wrap.addEventListener('mouseenter', () => { hovering = true; clearTimeout(hideTimer); });
  wrap.addEventListener('mouseleave', () => {
    hovering = false;
    show(upBtn.classList.contains('show') ? 'up' : (downBtn.classList.contains('show') ? 'down' : 'none'));
  });

  const smooth = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  downBtn.addEventListener('click', () => {
    if (!target) return;
    box.scrollTo({ top: Math.max(0, target.bottom - box.clientHeight + 16), behavior: smooth });
    show('none');
  });
  upBtn.addEventListener('click', () => {
    if (!target) return;
    box.scrollTo({ top: Math.max(0, target.top - 12), behavior: smooth });
    show('none');
  });

  return { evaluate, show };
}

if (typeof document !== 'undefined' && document.getElementById('chat-history')) {
  initScrollJump();
}
