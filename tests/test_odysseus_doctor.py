import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.helpers.cli_loader import load_script


@pytest.fixture(scope="module")
def doctor_http_server():
    responses = {
        "/health": (200, b'{"status":"healthy"}'),
        "/ready": (200, b'{"ready":true}'),
        "/not-ready": (200, b'{"ready":false}'),
        "/numeric-ready": (200, b'{"ready":1}'),
        "/empty": (200, b'{}'),
        "/array": (200, b'[]'),
        "/login": (200, b'<html>private-response-content</html>'),
        "/private": (401, b'{"error":"login required"}'),
        "/forbidden": (403, b'{}'),
        "/unavailable": (503, b'{"ready":false}'),
        "/invalid-encoding": (200, b'\xff'),
        "/oversized": (200, b'{"ready":true,"extra":"' + b'x' * 16384 + b'"}'),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            status, body = responses[self.path]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("name,path,expected", [
    ("app_health", "/health", "ok"),
    ("app_ready", "/ready", "ok"),
    ("app_ready", "/not-ready", "down"),
    ("app_ready", "/numeric-ready", "down"),
    ("app_health", "/empty", "down"),
    ("app_ready", "/array", "down"),
    ("app_ready", "/redirect", "down"),
    ("app_health", "/login", "down"),
    ("app_ready", "/invalid-encoding", "down"),
    ("app_ready", "/oversized", "down"),
    ("app_runtime", "/private", "auth_required"),
    ("app_ready", "/private", "down"),
    ("ollama", "/private", "down"),
    ("app_runtime", "/forbidden", "down"),
    ("app_ready", "/unavailable", "down"),
])
def test_doctor_checks_actual_http_responses(doctor_http_server, name, path, expected):
    doctor = load_script("odysseus-doctor")

    check = doctor.http_probe(name, doctor_http_server + path, 2)

    assert check["status"] == expected
    assert "private-response-content" not in json.dumps(check)


def test_doctor_accepts_protected_runtime_without_hiding_service_failures(monkeypatch, tmp_path, capsys):
    doctor = load_script("odysseus-doctor")
    monkeypatch.setattr(doctor, "python_check", lambda: doctor.result("python", "ok", "ok"))
    monkeypatch.setattr(doctor, "data_check", lambda root: doctor.result("data", "ok", "ok"))
    monkeypatch.setattr(doctor, "compose_check", lambda root, timeout: doctor.result("compose", "ok", "ok"))
    failed = set()

    def fake_probe(name, url, timeout):
        status = "down" if name in failed else "auth_required" if name == "app_runtime" else "ok"
        return doctor.result(name, status, "controlled")

    monkeypatch.setattr(doctor, "http_probe", fake_probe)
    assert doctor.main(["--repo", str(tmp_path), "--strict", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["overall"] == "ok"
    failed.add("ollama")
    assert doctor.main(["--repo", str(tmp_path), "--strict", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["overall"] == "degraded"
    failed.add("app_ready")
    assert doctor.main(["--repo", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["overall"] == "down"


def test_doctor_requires_an_existing_data_directory(monkeypatch, tmp_path):
    doctor = load_script("odysseus-doctor")
    monkeypatch.delenv("ODYSSEUS_DATA_DIR", raising=False)

    assert doctor.data_check(tmp_path)["status"] == "down"
    (tmp_path / "data").write_text("not a directory", encoding="utf-8")
    assert doctor.data_check(tmp_path)["status"] == "down"


def test_doctor_resolves_relative_data_directory_against_selected_repo(monkeypatch, tmp_path):
    doctor = load_script("odysseus-doctor")
    repo = tmp_path / "repo"
    data = repo / "custom-data"
    data.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ODYSSEUS_DATA_DIR", "custom-data")

    check = doctor.data_check(repo)

    assert check["status"] == "ok"
    assert check["meta"]["path"] == str(data.resolve())


def test_doctor_redacts_url_credentials_and_query():
    doctor = load_script("odysseus-doctor")

    safe = doctor.safe_url("https://user:secret@example.com:8443/v1?api_key=hidden#fragment")

    assert safe == "https://example.com:8443/v1"
    assert "secret" not in safe
    assert "api_key" not in safe


def test_doctor_rolls_optional_failures_up_as_degraded(monkeypatch, tmp_path):
    doctor = load_script("odysseus-doctor")
    monkeypatch.setattr(doctor, "python_check", lambda: doctor.result("python", "ok", "ok"))
    monkeypatch.setattr(doctor, "data_check", lambda root: doctor.result("data", "ok", "ok"))
    monkeypatch.setattr(doctor, "compose_check", lambda root, timeout: doctor.result("compose", "disabled", "not installed"))

    def fake_probe(name, url, timeout):
        status = "down" if name == "ollama" else "ok"
        return doctor.result(name, status, "controlled", url=doctor.safe_url(url))

    monkeypatch.setattr(doctor, "http_probe", fake_probe)
    report = doctor.collect(tmp_path, "http://127.0.0.1:7000", 0.1)

    assert report["overall"] == "degraded"
    assert {item["name"] for item in report["checks"]} >= {
        "app_health",
        "app_ready",
        "ollama",
        "chromadb",
        "searxng",
    }


def test_doctor_json_output_never_contains_credentials(monkeypatch, capsys):
    doctor = load_script("odysseus-doctor")
    report = {
        "product": "Odysseus-Lab",
        "version": "0.1",
        "overall": "ok",
        "checks": [
            doctor.result(
                "ollama",
                "ok",
                "HTTP 200",
                url=doctor.safe_url("http://token:secret@localhost:11434/v1?key=value"),
            )
        ],
    }
    monkeypatch.setattr(doctor, "collect", lambda *args: report)

    assert doctor.main(["--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["overall"] == "ok"
    assert "secret" not in output
    assert "token" not in output
    assert "key=value" not in output
