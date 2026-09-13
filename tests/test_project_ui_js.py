from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_launchers_and_route_are_wired():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    visibility = (ROOT / "static" / "js" / "ui_visibility.js").read_text(
        encoding="utf-8"
    )

    assert 'id="tool-projects-btn"' in html
    assert 'id="rail-projects"' in html
    assert "projectModule?.initProjectCore" in app
    assert "'/projects': () => projectModule?.openProjects?.()" in app
    assert "/^\\/projects\\/([0-9a-f-]+)$/i" in app
    assert "'tool-projects':       '#tool-projects-btn, #rail-projects'" in visibility


def test_project_pane_has_accessible_tabs_and_close_control():
    source = (ROOT / "static" / "js" / "projects.js").read_text(encoding="utf-8")

    assert "pane.setAttribute('role', 'dialog')" in source
    assert "pane.setAttribute('aria-modal', 'true')" in source
    assert "aria-label=\"Close project workspace\"" in source
    assert "role=\"tablist\"" in source
    assert "role=\"tab\"" in source
    assert "role=\"tabpanel\"" in source
    assert "aria-selected" in source
    assert "event.key === 'Escape'" in source


def test_project_ui_uses_text_content_for_server_values():
    source = (ROOT / "static" / "js" / "projects.js").read_text(encoding="utf-8")

    assert "node.textContent = text" in source
    assert "pane.querySelector('#project-pane-title').textContent = currentProject.name" in source
    assert "innerHTML = currentProject" not in source


def test_project_css_has_mobile_touch_layout():
    css = (ROOT / "static" / "project.css").read_text(encoding="utf-8")

    assert "@media (max-width: 768px)" in css
    assert "min-height: 44px" in css
    assert ".project-pane[hidden]" in css
