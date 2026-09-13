from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
PRIVATE_FEATURE_GUARD = (
    "github.event.repository.private == false || "
    "vars.ODYSSEUS_ENABLE_CODEQL == 'true'"
)


def test_code_scanning_uploads_are_guarded_for_private_repositories():
    codeql = (WORKFLOWS / "codeql.yml").read_text(encoding="utf-8")
    trivy = (WORKFLOWS / "container-trivy.yml").read_text(encoding="utf-8")

    assert PRIVATE_FEATURE_GUARD in codeql
    upload_section = trivy.split("- name: Upload Trivy results", 1)[1]
    assert PRIVATE_FEATURE_GUARD in upload_section
    assert "github/codeql-action/upload-sarif@" in upload_section


def test_private_repository_keeps_local_security_gates():
    dependency = (WORKFLOWS / "dependency-review.yml").read_text(encoding="utf-8")
    trivy = (WORKFLOWS / "container-trivy.yml").read_text(encoding="utf-8")

    assert "continue-on-error: ${{ github.event.repository.private == false }}" in dependency
    assert "Scan image with Trivy" in trivy
    assert trivy.index("Scan image with Trivy") < trivy.index("Upload Trivy results")
