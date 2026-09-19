"""Artifact preview endpoints (Lab layer).

Two routes, and only because an artifact has to be able to run:

* ``POST /api/artifact/preview`` takes the markup the browser derived from a
  message and returns a token for it.
* ``GET  /api/artifact/preview/{token}`` serves that markup as its own
  document, under the relaxed Content-Security-Policy set for this path in
  core/middleware.py, to be framed with ``sandbox="allow-scripts"``.

The sandbox attribute is what makes the relaxed policy safe: without
``allow-same-origin`` the frame gets an opaque origin, so the artifact's
scripts have no access to the app's cookies, storage, DOM or API - only to
themselves. The relaxed policy in turn is what makes the artifact *work*: a
page framed under the app's own CSP could not run the inline script that an
interactive artifact is made of.

Artifacts themselves are not stored here. They are derived from the
conversation by the browser, which is what lets them work with every model
rather than only the ones that can call a tool.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from core.database import SavedArtifact, get_db
from src.artifacts import preview_store
from src.auth_helpers import get_current_user, require_user
from src.project_scope import storage_owner


class ArtifactPreviewCreate(BaseModel):
    html: str = Field(default="", description="Markup to render in the sandboxed frame")


class ArtifactSave(BaseModel):
    title: str = Field(default="Artifact")
    kind: str = Field(default="code")
    lang: str = Field(default="")
    code: str = Field(default="")
    session_id: str = Field(default="")


class ArtifactUpdate(BaseModel):
    title: Optional[str] = None
    code: Optional[str] = None


class ArtifactDelete(BaseModel):
    ids: List[str] = Field(default_factory=list)


#: Tells the panel that the frame really rendered. A frame that is blocked
#: still fires `load` on the error page it gets instead, so "did it work?"
#: cannot be answered from the parent side alone - and a preview that
#: silently shows nothing is worse than one that says it could not.
_READY_BEACON = (
    "<script>try{parent.postMessage({__odysseusArtifact:'ready'},'*')}"
    "catch(e){}</script>"
)


def _with_ready_beacon(html: str) -> str:
    """Append the beacon to the served copy, leaving the artifact's own
    source untouched (the Code tab shows what the model wrote)."""
    body = html or ""
    lowered = body.lower()
    index = lowered.rfind("</body>")
    if index != -1:
        return body[:index] + _READY_BEACON + body[index:]
    return body + _READY_BEACON


def setup_artifact_routes() -> APIRouter:
    router = APIRouter()

    @router.post("/api/artifact/preview")
    async def create_artifact_preview(request: Request, req: ArtifactPreviewCreate):
        """Stash markup for framing and return `{token, url}`."""
        user = get_current_user(request) or ""
        html = req.html or ""
        if not html.strip():
            raise HTTPException(status_code=400, detail="empty artifact")
        try:
            token = preview_store.put(html, owner=user)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        return JSONResponse({"token": token, "url": f"/api/artifact/preview/{token}"})

    @router.get("/api/artifact/preview/{token}")
    async def read_artifact_preview(request: Request, token: str):
        """Serve stashed markup as a standalone document."""
        user = get_current_user(request) or ""
        html = preview_store.get(token, owner=user)
        if html is None:
            raise HTTPException(status_code=404, detail="preview expired")
        response = HTMLResponse(content=_with_ready_beacon(html))
        # The document is a rendering of one message, never a cacheable page.
        response.headers["Cache-Control"] = "no-store"
        return response

    def _owner(request: Request) -> str:
        """Whose library this is.

        Resolved the way every other owner-scoped Lab route resolves it
        (projects, sessions): storage_owner maps the no-login modes onto one
        stable identity. Reading the username straight off the request does
        not - it answers differently depending on whether a session cookie
        happened to be present, and a library that hides what you saved a
        moment ago is worse than no library.
        """
        return storage_owner(require_user(request))

    @router.get("/api/artifacts")
    async def list_saved_artifacts(request: Request):
        """The library: what this user chose to keep, newest first."""
        owner = _owner(request)
        db = next(get_db())
        try:
            rows = (
                db.query(SavedArtifact)
                .filter(SavedArtifact.owner == owner)
                .order_by(SavedArtifact.created_at.desc())
                .all()
            )
            return JSONResponse({"artifacts": [row.to_dict() for row in rows]})
        finally:
            db.close()

    @router.post("/api/artifacts")
    async def save_artifact(request: Request, req: ArtifactSave):
        """Keep one artifact. Saving the same title twice replaces it, so
        revising a kept artifact updates the entry instead of piling up
        near-identical copies."""
        owner = _owner(request)
        if not (req.code or "").strip():
            raise HTTPException(status_code=400, detail="empty artifact")
        db = next(get_db())
        try:
            existing = (
                db.query(SavedArtifact)
                .filter(SavedArtifact.owner == owner, SavedArtifact.title == req.title)
                .first()
            )
            if existing is not None:
                existing.code = req.code
                existing.kind = req.kind or existing.kind
                existing.lang = req.lang or existing.lang
                existing.session_id = req.session_id or existing.session_id
                db.commit()
                db.refresh(existing)
                return JSONResponse({"artifact": existing.to_dict(), "replaced": True})

            row = SavedArtifact(
                id=str(uuid.uuid4()),
                owner=owner,
                session_id=req.session_id or None,
                title=req.title or "Artifact",
                kind=req.kind or "code",
                lang=req.lang or "",
                code=req.code,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return JSONResponse({"artifact": row.to_dict(), "replaced": False})
        finally:
            db.close()

    @router.patch("/api/artifacts/{artifact_id}")
    async def update_saved_artifact(request: Request, artifact_id: str, req: ArtifactUpdate):
        owner = _owner(request)
        db = next(get_db())
        try:
            row = (
                db.query(SavedArtifact)
                .filter(SavedArtifact.id == artifact_id, SavedArtifact.owner == owner)
                .first()
            )
            if row is None:
                raise HTTPException(status_code=404, detail="artifact not found")
            if req.title is not None:
                row.title = req.title
            if req.code is not None:
                row.code = req.code
            db.commit()
            db.refresh(row)
            return JSONResponse({"artifact": row.to_dict()})
        finally:
            db.close()

    @router.post("/api/artifacts/delete")
    async def delete_saved_artifacts(request: Request, req: ArtifactDelete):
        """Remove the selected artifacts. Deleting nothing is not an error -
        the button is allowed to be pressed with an empty selection."""
        owner = _owner(request)
        if not req.ids:
            return JSONResponse({"deleted": 0})
        db = next(get_db())
        try:
            deleted = (
                db.query(SavedArtifact)
                .filter(SavedArtifact.owner == owner, SavedArtifact.id.in_(req.ids))
                .delete(synchronize_session=False)
            )
            db.commit()
            return JSONResponse({"deleted": int(deleted)})
        finally:
            db.close()

    return router
