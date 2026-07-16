from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import civ5studio.build.service as build_service_module
from civ5studio.build import (
    BuildInProgress,
    BuildMode,
    BuildService,
    UnsafeBuildPath,
    package_clean,
    zip_inventory,
)
from civ5studio.locking import FileMutationLock


def _directory_inventory(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != ".civ5studio-generated.json"
        )
    )


def test_available_build_publishes_atomically_and_zip_has_parity(sample_project, tmp_path):
    service = BuildService()
    result = service.build(sample_project, tmp_path, mode=BuildMode.AVAILABLE)
    assert result.published_path.is_dir()
    assert result.package_path and result.package_path.is_file()
    assert _directory_inventory(result.published_path) == result.inventory
    assert zip_inventory(result.package_path) == result.inventory
    marker = json.loads(
        (result.published_path / ".civ5studio-generated.json").read_text(encoding="utf-8")
    )
    assert marker["project_id"] == sample_project.project_id
    assert marker["mode"] == "available"
    assert marker["marker_version"] == 2
    assert set(marker["sha256"]) == set(result.inventory)
    for relative in result.inventory:
        assert marker["sha256"][relative] == hashlib.sha256(
            (result.published_path / relative).read_bytes()
        ).hexdigest()

    second = service.build(sample_project, tmp_path, create_zip=False)
    assert second.backup_path and second.backup_path.is_dir()
    assert (second.backup_path / ".civ5studio-generated.json").is_file()
    assert second.published_path == result.published_path


def test_unmarked_destination_is_never_deleted_or_replaced(sample_project, tmp_path):
    target = tmp_path / "generated" / "Kingdom_Of_Lithuania"
    target.mkdir(parents=True)
    sentinel = target / "user-file.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    with pytest.raises(UnsafeBuildPath, match="unmarked"):
        BuildService().build(sample_project, tmp_path, create_zip=False)
    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_workspace_marker_prevents_cross_project_reuse(sample_project, tmp_path):
    service = BuildService()
    service.build(sample_project, tmp_path, create_zip=False)
    other = deepcopy(sample_project)
    other.project_id = "7de997a4-3906-40ea-bdf0-174ec8ed4882"
    with pytest.raises(UnsafeBuildPath, match="different"):
        service.build(other, tmp_path, create_zip=False)


def test_clean_packager_refuses_overwrite(sample_project, tmp_path):
    result = BuildService().build(sample_project, tmp_path, create_zip=False)
    destination = tmp_path / "package.zip"
    package_clean(result.published_path, destination)
    with pytest.raises(UnsafeBuildPath, match="overwrite"):
        package_clean(result.published_path, destination)


def test_clean_packager_rejects_reparse_inputs_before_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked_parent = tmp_path / "linked-parent"
    root = linked_parent / "nested-root"
    root.mkdir(parents=True)
    destination = tmp_path / "package.zip"
    original = build_service_module._is_link_or_reparse
    monkeypatch.setattr(
        build_service_module,
        "_is_link_or_reparse",
        lambda path: path == linked_parent or original(path),
    )

    with pytest.raises(UnsafeBuildPath, match="root cannot be a link or junction"):
        package_clean(root, destination)

    assert not destination.exists()


def test_clean_packager_rejects_reparse_destination_before_creating_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "mod"
    root.mkdir()
    (root / "data.xml").write_text("<GameData />", encoding="utf-8")
    linked_parent = tmp_path / "linked-destination"
    linked_parent.mkdir()
    destination = linked_parent / "package.zip"
    original = build_service_module._is_link_or_reparse
    monkeypatch.setattr(
        build_service_module,
        "_is_link_or_reparse",
        lambda path: path == linked_parent or original(path),
    )

    with pytest.raises(
        UnsafeBuildPath, match="destination cannot be a link or junction"
    ):
        package_clean(root, destination)

    assert not destination.exists()


def test_clean_packager_rejects_nested_reparse_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "mod"
    root.mkdir()
    safe = root / "safe.xml"
    safe.write_text("<GameData />", encoding="utf-8")
    linked = root / "linked.xml"
    linked.write_text("outside evidence", encoding="utf-8")
    destination = tmp_path / "package.zip"
    original_link_check = build_service_module._is_link_or_reparse
    original_read_bytes = Path.read_bytes

    monkeypatch.setattr(
        build_service_module,
        "_is_link_or_reparse",
        lambda path: path == linked or original_link_check(path),
    )

    def guarded_read(path: Path) -> bytes:
        assert path != linked, "linked/reparse entry was read"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)

    with pytest.raises(UnsafeBuildPath, match="contains a link or junction"):
        package_clean(root, destination)

    assert not destination.exists()


def test_clean_packager_link_check_recognizes_windows_reparse_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = SimpleNamespace(
        st_mode=0,
        st_file_attributes=build_service_module.stat.FILE_ATTRIBUTE_REPARSE_POINT,
    )
    monkeypatch.setattr(Path, "lstat", lambda _path: metadata)

    assert build_service_module._is_link_or_reparse(tmp_path)


def test_concurrent_build_for_same_workspace_is_rejected(sample_project, tmp_path):
    service = BuildService()
    with FileMutationLock(tmp_path / ".civ5studio-build.lock", label="test build"):
        with pytest.raises(BuildInProgress, match="already running"):
            service.build(sample_project, tmp_path, create_zip=False)


def test_build_rejects_windows_paths_that_civ_v_cannot_load(sample_project, tmp_path):
    deep_root = tmp_path / ("very-long-project-segment-" * 7)
    with pytest.raises(UnsafeBuildPath, match="MAX_PATH"):
        BuildService().build(sample_project, deep_root, create_zip=False)
    assert not deep_root.exists()
