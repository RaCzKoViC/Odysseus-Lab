import json

from tests.helpers.cli_loader import load_script


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
