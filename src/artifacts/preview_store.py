"""Short-lived store for artifact previews.

An artifact lives in the message that produced it, so there is nothing here
to persist: the browser re-derives artifacts from the conversation every time
it renders one. What the browser cannot do by itself is *run* an HTML
artifact. Rendering it inline would put the model's markup inside the app's
own document, and rendering it from a `srcdoc` or `blob:` frame does not help
either - both inherit the page's Content-Security-Policy, which forbids the
inline scripts that make an interactive artifact interactive.

So the page hands the markup back to the server and gets a URL for it. That
URL is served from an endpoint with its own CSP (see core/middleware.py) into
a sandboxed frame with no same-origin privilege: the artifact runs its own
scripts and can reach nothing of the app - no cookies, no storage, no DOM, no
API. The entries are per-user, capped, and expire, because this is a viewport
onto a message, not a filing cabinet.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

#: How long a preview URL stays good. Long enough to open, edit the chat and
#: come back; short enough that a machine left running does not accumulate.
PREVIEW_TTL_SECONDS = 60 * 60

#: Per-user ceiling. Each new preview evicts the oldest beyond this.
MAX_PREVIEWS_PER_USER = 40

#: Refuse markup larger than this outright (bytes of UTF-8).
MAX_PREVIEW_BYTES = 2 * 1024 * 1024


@dataclass
class PreviewEntry:
    token: str
    owner: str
    html: str
    created_at: float

    def expired(self, now: Optional[float] = None) -> bool:
        return (now or time.time()) - self.created_at > PREVIEW_TTL_SECONDS


class PreviewStore:
    """In-memory previews, keyed by an unguessable token."""

    def __init__(self) -> None:
        self._entries: Dict[str, PreviewEntry] = {}
        self._lock = threading.Lock()

    def put(self, html: str, owner: str = "") -> str:
        """Store `html` for `owner` and return the token that reads it back."""
        body = html or ""
        if len(body.encode("utf-8", errors="ignore")) > MAX_PREVIEW_BYTES:
            raise ValueError("artifact preview is too large")
        token = secrets.token_urlsafe(24)
        entry = PreviewEntry(token=token, owner=owner or "", html=body, created_at=time.time())
        with self._lock:
            self._entries[token] = entry
            self._evict_locked(owner or "")
        return token

    def get(self, token: str, owner: str = "") -> Optional[str]:
        """The markup behind `token`, or None when it is gone or not yours.

        The owner check is what keeps one user's preview URL from rendering
        in another's browser; an empty owner (single-user/local mode) matches
        only entries stored the same way.
        """
        now = time.time()
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            if entry.expired(now):
                self._entries.pop(token, None)
                return None
            if entry.owner != (owner or ""):
                return None
            return entry.html

    def _evict_locked(self, owner: str) -> None:
        now = time.time()
        for token, entry in list(self._entries.items()):
            if entry.expired(now):
                self._entries.pop(token, None)
        mine = sorted(
            (e for e in self._entries.values() if e.owner == owner),
            key=lambda e: e.created_at,
        )
        for entry in mine[:-MAX_PREVIEWS_PER_USER] if len(mine) > MAX_PREVIEWS_PER_USER else []:
            self._entries.pop(entry.token, None)

    # Test seams -----------------------------------------------------------
    def _size(self) -> int:
        with self._lock:
            return len(self._entries)

    def _clear(self) -> None:
        with self._lock:
            self._entries.clear()


#: Process-wide store. One per app, like the other in-memory services.
preview_store = PreviewStore()
