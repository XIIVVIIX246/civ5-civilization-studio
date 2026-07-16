from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_inno_installer_is_per_user_uninstallable_and_preserves_json_defaults() -> None:
    text = (ROOT / "packaging/Civ5CivilizationStudio.iss").read_text(
        encoding="utf-8"
    )
    assert "PrivilegesRequired=lowest" in text
    assert "{localappdata}\\Programs" in text
    assert "UninstallDisplayIcon=" in text
    assert "recursesubdirs" in text
    assert "SupportedTypes" in text
    assert 'ValueName: ".json"' in text
    assert "Software\\Classes\\.json" not in text


def test_installer_builder_requires_traceable_release_and_optional_signing() -> None:
    text = (ROOT / "tools/build_installer.ps1").read_text(encoding="utf-8")
    assert "status --porcelain --untracked-files=all" in text
    assert "RELEASE_MANIFEST.json" in text
    assert "SigningCertificateSha1" in text
    assert "signtool.exe" in text
    assert "verify /pa /v" in text
    assert "UNSIGNED_NO_CERTIFICATE" in text
    assert "SIGNED_AND_VERIFIED" in text
    assert "Windows Kits\\10\\bin" in text


def test_release_workflow_builds_installer_with_optional_secret_certificate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "choco install innosetup" in workflow
    assert "WINDOWS_SIGNING_PFX_BASE64" in workflow
    assert "Import-PfxCertificate" in workflow
    assert "./tools/build_installer.ps1" in workflow
