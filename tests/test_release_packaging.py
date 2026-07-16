from __future__ import annotations

import json
from pathlib import Path
import zipfile

from civ5studio.release import RELEASE_MANIFEST_NAME, package_windows_release


def _artifact(root: Path) -> Path:
    target = root / "Civ5-Civilization-Studio-0.1.0-windows-x64"
    (target / "runtime").mkdir(parents=True)
    (target / "Studio.exe").write_bytes(b"frozen-executable")
    (target / "runtime" / "library.zip").write_bytes(b"runtime")
    return target


def test_windows_release_package_is_deterministic_and_self_describing(tmp_path: Path):
    first_root = _artifact(tmp_path / "first")
    second_root = _artifact(tmp_path / "second")
    first = package_windows_release(
        first_root,
        tmp_path / "first.zip",
        version="0.1.0",
        git_commit="abc123",
    )
    second = package_windows_release(
        second_root,
        tmp_path / "second.zip",
        version="0.1.0",
        git_commit="abc123",
    )
    assert first["sha256"] == second["sha256"]
    manifest = json.loads(
        (first_root / RELEASE_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["application_version"] == "0.1.0"
    assert manifest["git_commit"] == "abc123"
    assert "not a Civilization V in-game test" in manifest["validation_boundary"]
    with zipfile.ZipFile(first["zip"]) as archive:
        assert any(
            name.endswith(f"/{RELEASE_MANIFEST_NAME}")
            for name in archive.namelist()
        )


def test_release_packager_refuses_overwrite(tmp_path: Path):
    root = _artifact(tmp_path)
    destination = tmp_path / "release.zip"
    package_windows_release(
        root, destination, version="0.1.0", git_commit="abc123"
    )
    try:
        package_windows_release(
            root, destination, version="0.1.0", git_commit="abc123"
        )
    except ValueError as exc:
        assert "overwrite" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Existing release artifacts must not be overwritten")
