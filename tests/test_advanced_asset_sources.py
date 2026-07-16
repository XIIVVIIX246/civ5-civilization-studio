from __future__ import annotations

from pathlib import Path
import struct
import wave

import pytest

import civ5studio.application.audio_assets as audio_assets_module
import civ5studio.application.advanced_content as advanced_content_module
import civ5studio.application.unit_art_package as unit_art_package_module
from civ5studio.application.advanced_content import _resolve_source
from civ5studio.application.audio_assets import (
    AudioAssetSpec,
    AudioRole,
    inspect_audio_source,
)
from civ5studio.application.unit_art_package import (
    GR2_MAGIC,
    inspect_unit_art_package,
)


def _dds(path: Path) -> None:
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    path.write_bytes(header + b"texture")


def test_unit_art_package_validates_local_and_engine_references(tmp_path: Path) -> None:
    package = tmp_path / "Assets/Source/UnitArt"
    package.mkdir(parents=True)
    (package / "unit.fxsxml").write_text(
        '<Asset><Mesh file="unit.gr2"/><Animation file="Assets/Units/Warrior/Warrior_Idle.gr2"/></Asset>',
        encoding="utf-8",
    )
    (package / "unit.gr2").write_bytes(GR2_MAGIC + b"\0unit.dds\0")
    _dds(package / "unit.dds")

    report = inspect_unit_art_package(
        tmp_path, "Assets/Source/UnitArt", "unit.fxsxml"
    )
    assert report.is_valid, report.issues
    assert report.local_references == ("unit.dds", "unit.gr2")
    assert report.engine_references == ("Assets/Units/Warrior/Warrior_Idle.gr2",)
    assert set(report.sha256) == {"unit.dds", "unit.fxsxml", "unit.gr2"}
    assert any(issue.code == "unit-art.runtime-required" for issue in report.issues)


def test_unit_art_package_rejects_missing_gr2_texture_reference(tmp_path: Path) -> None:
    package = tmp_path / "ArtPackage"
    package.mkdir()
    (package / "unit.fxsxml").write_text(
        '<Asset><Mesh file="unit.gr2"/></Asset>', encoding="utf-8"
    )
    (package / "unit.gr2").write_bytes(GR2_MAGIC + b"\0missing.dds\0")
    report = inspect_unit_art_package(tmp_path, "ArtPackage", "unit.fxsxml")
    assert not report.is_valid
    assert any(issue.code == "unit-art.reference-missing" for issue in report.issues)


def test_unit_art_package_preserves_and_rejects_parent_traversal_reference(
    tmp_path: Path,
) -> None:
    package = tmp_path / "ArtPackage"
    package.mkdir()
    (package / "unit.fxsxml").write_text(
        '<Asset><Mesh file="./../outside.gr2"/></Asset>', encoding="utf-8"
    )
    (package / "unit.gr2").write_bytes(GR2_MAGIC)
    _dds(package / "unit.dds")

    report = inspect_unit_art_package(tmp_path, "ArtPackage", "unit.fxsxml")

    assert not report.is_valid
    assert report.local_references == ("../outside.gr2",)
    assert any(issue.code == "unit-art.reference-path" for issue in report.issues)


def test_unit_art_package_rejects_reparse_project_root_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked_parent = tmp_path / "linked-parent"
    project = linked_parent / "project"
    package = project / "ArtPackage"
    package.mkdir(parents=True)
    original = unit_art_package_module._is_link_or_reparse
    monkeypatch.setattr(
        unit_art_package_module,
        "_is_link_or_reparse",
        lambda path: path == linked_parent or original(path),
    )

    report = inspect_unit_art_package(project, "ArtPackage", "unit.fxsxml")

    assert not report.is_valid
    assert {issue.code for issue in report.issues} == {"unit-art.project-root-link"}


def test_unit_art_package_rejects_reparse_package_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    linked_parent = project / "linked-parent"
    package = linked_parent / "ArtPackage"
    package.mkdir(parents=True)
    original = unit_art_package_module._is_link_or_reparse
    monkeypatch.setattr(
        unit_art_package_module,
        "_is_link_or_reparse",
        lambda path: path == linked_parent or original(path),
    )

    report = inspect_unit_art_package(
        project, "linked-parent/ArtPackage", "unit.fxsxml"
    )

    assert not report.is_valid
    assert {issue.code for issue in report.issues} == {"unit-art.package-link"}


def test_unit_art_package_does_not_read_nested_reparse_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "ArtPackage"
    package.mkdir()
    (package / "unit.fxsxml").write_text(
        '<Asset><Mesh file="unit.gr2"/></Asset>', encoding="utf-8"
    )
    (package / "unit.gr2").write_bytes(GR2_MAGIC + b"\0unit.dds\0")
    linked = package / "unit.dds"
    _dds(linked)
    original_link_check = unit_art_package_module._is_link_or_reparse
    original_read_bytes = Path.read_bytes
    monkeypatch.setattr(
        unit_art_package_module,
        "_is_link_or_reparse",
        lambda path: path == linked or original_link_check(path),
    )

    def guarded_read(path: Path) -> bytes:
        assert path != linked, "linked/reparse unit-art entry was read"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)

    report = inspect_unit_art_package(tmp_path, "ArtPackage", "unit.fxsxml")

    assert not report.is_valid
    assert any(issue.code == "unit-art.symlink" for issue in report.issues)


def test_advanced_source_rejects_reparse_ancestor_before_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    linked_parent = tmp_path / "linked-parent"
    source = linked_parent / "audio" / "peace.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    original = advanced_content_module._is_link_or_reparse
    monkeypatch.setattr(
        advanced_content_module,
        "_is_link_or_reparse",
        lambda path: path == linked_parent or original(path),
    )

    with pytest.raises(ValueError, match="link or junction"):
        _resolve_source(str(source), workspace, None, expect_directory=False)


def test_advanced_source_rechecks_resolved_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "peace.wav"
    source.write_bytes(b"source")
    calls = 0
    original = advanced_content_module._path_contains_link_or_reparse

    def changed_after_resolution(path: Path) -> bool:
        nonlocal calls
        if path == source:
            calls += 1
            return calls > 1
        return original(path)

    monkeypatch.setattr(
        advanced_content_module,
        "_path_contains_link_or_reparse",
        changed_after_resolution,
    )

    with pytest.raises(ValueError, match="link or junction"):
        _resolve_source(str(source), workspace, None, expect_directory=False)


def test_audio_source_validates_project_owned_wave(tmp_path: Path) -> None:
    audio = tmp_path / "Assets/Source/peace.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(44100)
        target.writeframes(b"\0\0\0\0" * 441)
    result = inspect_audio_source(
        tmp_path, AudioAssetSpec(AudioRole.PEACE_MUSIC, "Assets/Source/peace.wav")
    )
    assert result.is_valid
    assert result.format == "wave"
    assert result.duration_seconds == 0.01
    assert len(result.sha256) == 64


def test_audio_source_rejects_renamed_non_mp3(tmp_path: Path) -> None:
    source = tmp_path / "fake.mp3"
    source.write_bytes(b"not an mp3")
    result = inspect_audio_source(
        tmp_path, AudioAssetSpec(AudioRole.WAR_MUSIC, "fake.mp3")
    )
    assert not result.is_valid
    assert any(issue.code == "audio.mp3-header" for issue in result.issues)


def test_audio_source_rejects_reparse_entry_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "Assets" / "Source" / "peace.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"not read")
    original = audio_assets_module._is_link_or_reparse
    monkeypatch.setattr(
        audio_assets_module,
        "_is_link_or_reparse",
        lambda path: path == source or original(path),
    )

    result = inspect_audio_source(
        tmp_path, AudioAssetSpec(AudioRole.PEACE_MUSIC, "Assets/Source/peace.wav")
    )

    assert not result.is_valid
    assert any(issue.code == "audio.path" for issue in result.issues)
