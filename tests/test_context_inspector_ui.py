from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_context_inspector_is_wired_to_existing_pill():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    chat = (ROOT / "static" / "js" / "chat.js").read_text(encoding="utf-8")

    assert "/static/context-inspector.css" in html
    assert 'id="chat-context-pill"' in html
    assert 'aria-haspopup="dialog"' in html
    assert 'aria-expanded="false"' in html
    assert "import contextInspector from './contextInspector.js" in chat
    assert "contextInspector.toggleContextInspector" in chat
    assert "/context_breakdown" not in chat


def test_context_inspector_is_accessible_and_content_safe():
    source = (ROOT / "static" / "js" / "contextInspector.js").read_text(
        encoding="utf-8"
    )

    assert "dialog.setAttribute('role', 'dialog')" in source
    assert "dialog.setAttribute('aria-modal', 'true')" in source
    assert "Close Context Inspector" in source
    assert "event.key === 'Escape'" in source
    assert "item.textContent = text" in source
    assert "innerHTML" not in source
    assert "Trusted" in source
    assert "Untrusted" in source
    assert "/context_breakdown" in source


def test_context_inspector_exposes_only_honest_actions():
    source = (ROOT / "static" / "js" / "contextInspector.js").read_text(
        encoding="utf-8"
    )

    assert "Compact conversation" in source
    assert "Open Memory" in source
    assert "Agent settings" in source
    assert "Schemas" in source
    assert "Route" in source
    for unsupported in ("Remove block", "Trust override", "Lock block"):
        assert unsupported not in source


def test_context_inspector_has_mobile_bottom_sheet():
    css = (ROOT / "static" / "context-inspector.css").read_text(encoding="utf-8")

    assert "@media (max-width: 768px)" in css
    assert "max-height: 72dvh" in css
    assert "min-height: 44px" in css
