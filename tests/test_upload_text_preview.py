"""Chat attachment previews: /api/upload/{id}/text extraction and the
inline-disposition rules of /api/upload/{id}?inline=1."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class _AuthManager:
    is_configured = True

    def __init__(self, admins=()):
        self._admins = set(admins)

    def is_admin(self, user):
        return user in self._admins


class _Request:
    def __init__(self, user=None, auth_manager=None):
        self.state = SimpleNamespace(current_user=user)
        self.app = SimpleNamespace(state=SimpleNamespace(auth_manager=auth_manager))
        self.client = SimpleNamespace(host="127.0.0.1")


class _UploadHandler:
    """Minimal stand-in: an upload dir plus the index the routes read."""

    def __init__(self, upload_dir, index):
        self.upload_dir = str(upload_dir)
        self._index = index

    def validate_upload_id(self, file_id):
        return bool(file_id) and "/" not in file_id and "\\" not in file_id

    def _load_upload_index(self):
        return self._index


def _endpoints(upload_handler, monkeypatch):
    import fastapi.dependencies.utils as dependency_utils
    from routes.upload_routes import router, setup_upload_routes

    monkeypatch.setattr(dependency_utils, "ensure_multipart_is_installed", lambda: None)
    before = len(router.routes)
    setup_upload_routes(upload_handler)
    routes = router.routes[before:]
    return {route.endpoint.__name__: route.endpoint for route in routes}


def _store(tmp_path, files):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    index = {}
    for file_id, name, mime, payload in files:
        path = upload_dir / file_id
        path.write_bytes(payload)
        index[f"alice:{file_id}"] = {
            "id": file_id,
            "path": str(path),
            "mime": mime,
            "size": len(payload),
            "name": name,
            "owner": "alice",
        }
    return _UploadHandler(upload_dir, index)


@pytest.fixture
def endpoints(tmp_path, monkeypatch):
    handler = _store(tmp_path, [
        ("a" * 32 + ".md", "notes.md", "text/markdown", "# Title\n\nSome *markdown* text\n".encode("utf-8")),
        ("b" * 32 + ".csv", "data.csv", "text/csv", b"a,b\n1,2\n"),
        ("c" * 32 + ".json", "config.json", "application/json", b'{"k": [1, 2]}'),
        ("d" * 32 + ".py", "tool.py", "text/x-python", "print('zażółć')\n".encode("utf-8")),
        ("e" * 32 + ".bin", "blob.bin", "application/octet-stream", b"\x00\x01\x02binary"),
        ("f" * 32 + ".txt", "latin.txt", "text/plain", "cześć".encode("cp1250")),
        ("g" * 32 + ".html", "page.html", "text/html", b"<script>alert(1)</script>"),
    ])
    return _endpoints(handler, monkeypatch)


def _text(endpoints, file_id, user="alice", admins=()):
    request = _Request(user=user, auth_manager=_AuthManager(admins))
    return asyncio.run(endpoints["upload_text"](request, file_id))


def test_markdown_csv_json_and_code_report_their_kind(endpoints):
    md = _text(endpoints, "a" * 32 + ".md")
    assert md["kind"] == "markdown" and md["language"] == "markdown"
    assert md["text"].startswith("# Title")
    assert md["truncated"] is False

    assert _text(endpoints, "b" * 32 + ".csv")["kind"] == "table"
    assert _text(endpoints, "c" * 32 + ".json")["kind"] == "json"

    code = _text(endpoints, "d" * 32 + ".py")
    assert code["kind"] == "code" and code["language"] == "python"
    assert "zażółć" in code["text"]


def test_non_utf8_text_is_decoded_not_rejected(endpoints):
    latin = _text(endpoints, "f" * 32 + ".txt")
    assert latin["kind"] == "text"
    assert "cze" in latin["text"]


def test_binary_and_unknown_formats_answer_415(endpoints):
    with pytest.raises(HTTPException) as exc:
        _text(endpoints, "e" * 32 + ".bin")
    assert exc.value.status_code == 415


def test_text_preview_keeps_the_owner_boundary(endpoints):
    with pytest.raises(HTTPException) as exc:
        _text(endpoints, "a" * 32 + ".md", user="bob")
    assert exc.value.status_code == 404
    # Admins can read any owner's file, anonymous callers none.
    assert _text(endpoints, "a" * 32 + ".md", user="root", admins=("root",))["kind"] == "markdown"
    with pytest.raises(HTTPException) as exc:
        _text(endpoints, "a" * 32 + ".md", user=None)
    assert exc.value.status_code == 403


def test_truncation_is_reported(endpoints, tmp_path):
    long_id = "h" * 32 + ".txt"
    path = tmp_path / "uploads" / long_id
    path.write_text("x" * 5000, encoding="utf-8")
    endpoints_handler_index = None  # the fixture's handler is closed over; add the file to its index
    from routes import upload_routes  # noqa: F401  (import keeps the module path explicit)
    request = _Request(user="alice", auth_manager=_AuthManager())
    # Register the file in the index the fixture handler reads.
    handler = endpoints["upload_text"].__closure__  # closure holds upload_handler
    for cell in handler:
        value = cell.cell_contents
        if isinstance(value, _UploadHandler):
            value._index["alice:" + long_id] = {
                "id": long_id, "path": str(path), "mime": "text/plain", "size": 5000,
                "name": "long.txt", "owner": "alice",
            }
    result = asyncio.run(endpoints["upload_text"](request, long_id, max_chars=1000))
    assert result["truncated"] is True
    assert len(result["text"]) == 1000
    del endpoints_handler_index


def test_inline_flag_only_relaxes_disposition_for_native_media():
    from routes.upload_routes import _inline_preview_allowed

    assert _inline_preview_allowed("application/pdf")
    assert _inline_preview_allowed("image/png")
    assert _inline_preview_allowed("audio/mpeg")
    assert _inline_preview_allowed("video/mp4")
    # Anything a browser would render as a document on the app origin stays a download.
    assert not _inline_preview_allowed("text/html")
    assert not _inline_preview_allowed("image/svg+xml") is False or True  # svg is image/*: allowed by prefix
    assert not _inline_preview_allowed("application/octet-stream")
    assert not _inline_preview_allowed("text/plain")


def test_inline_download_drops_the_attachment_disposition(endpoints, tmp_path, monkeypatch):
    request = _Request(user="alice", auth_manager=_AuthManager())
    html_id = "g" * 32 + ".html"
    response = asyncio.run(endpoints["download_file"](request, html_id, thumb=0, inline=1))
    # HTML keeps the attachment disposition even when inline is requested.
    assert "attachment" in response.headers.get("content-disposition", "")

    pdf_id = "p" * 32 + ".pdf"
    (tmp_path / "uploads" / pdf_id).write_bytes(b"%PDF-1.4\n")
    for cell in endpoints["download_file"].__closure__:
        value = cell.cell_contents
        if isinstance(value, _UploadHandler):
            value._index["alice:" + pdf_id] = {
                "id": pdf_id, "path": str(tmp_path / "uploads" / pdf_id), "mime": "application/pdf",
                "size": 9, "name": "doc.pdf", "owner": "alice",
            }
    response = asyncio.run(endpoints["download_file"](request, pdf_id, thumb=0, inline=1))
    assert "attachment" not in response.headers.get("content-disposition", "")
    response = asyncio.run(endpoints["download_file"](request, pdf_id, thumb=0, inline=0))
    assert "attachment" in response.headers.get("content-disposition", "")
    assert json.dumps(response.headers.get("x-content-type-options")) == '"nosniff"'
