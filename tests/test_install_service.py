from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

import pytest
from PIL import Image, ImageDraw

import civ5studio.application.install as install_module
from civ5studio.application import (
    InstallInProgress,
    InstallService,
    ProjectWorkflowService,
    WorkflowMode,
)
from civ5studio.build import BuildMode, BuildService
from civ5studio.locking import FileMutationLock


@pytest.fixture
def strict_build_path(sample_project, tmp_path: Path) -> Path:
    project = deepcopy(sample_project)
    source_root = tmp_path / "project"
    for asset in project.art.assets:
        path = source_root / asset.source_png
        path.parent.mkdir(parents=True, exist_ok=True)
        if asset.role.value in {"civilization_alpha", "unit_flag"}:
            image = Image.new("RGB", (256, 256), "black")
            ImageDraw.Draw(image).ellipse((72, 48, 184, 208), fill="white")
        elif asset.role.value in {"leader_scene", "dawn_of_man", "map_image"}:
            image = Image.new("RGB", (400, 300), (80, 100, 120))
        else:
            image = Image.new("RGB", (256, 256), (80, 120, 160))
        image.save(path)
    result = ProjectWorkflowService().run(
        project,
        source_root=source_root,
        output_root=tmp_path / "output",
        mode=WorkflowMode.BUILD,
    )
    assert result.succeeded, [item.to_dict() for item in result.issues]
    assert result.build_path is not None
    return result.build_path


def test_install_keeps_previous_version_as_backup(
    strict_build_path: Path, tmp_path: Path
) -> None:
    mods = tmp_path / "My Games" / "MODS"
    installer = InstallService()
    first = installer.install(strict_build_path, mods)
    assert first.destination.is_dir()
    assert first.backup_path is None
    second = installer.install(strict_build_path, mods)
    assert second.destination.is_dir()
    assert second.backup_path and second.backup_path.is_dir()
    assert list(second.destination.glob("*.modinfo"))


def test_install_rejects_unvalidated_source(tmp_path: Path) -> None:
    source = tmp_path / "unvalidated"
    source.mkdir()
    (source / "fake.modinfo").write_text("<Mod />", encoding="utf-8")
    with pytest.raises(ValueError, match="validated"):
        InstallService().install(source, tmp_path / "MODS")


def test_install_rejects_available_build(sample_project, tmp_path: Path) -> None:
    build = BuildService().build(
        sample_project,
        tmp_path / "workspace",
        mode=BuildMode.AVAILABLE,
        create_zip=False,
    )
    with pytest.raises(ValueError, match="strict_release"):
        InstallService().install(build.published_path, tmp_path / "MODS")


def test_install_rejects_file_changed_after_validation(
    strict_build_path: Path, tmp_path: Path
) -> None:
    modinfo = next(strict_build_path.glob("*.modinfo"))
    modinfo.write_text(
        modinfo.read_text(encoding="utf-8") + "\n<!-- tampered -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        InstallService().install(strict_build_path, tmp_path / "MODS")


def test_install_rejects_unexpected_file_after_validation(
    strict_build_path: Path, tmp_path: Path
) -> None:
    (strict_build_path / "unexpected.txt").write_text("not validated", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory changed"):
        InstallService().install(strict_build_path, tmp_path / "MODS")


def test_install_reverifies_copy_before_replacing_existing_mod(
    strict_build_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mods = tmp_path / "MODS"
    installer = InstallService()
    first = installer.install(strict_build_path, mods)
    sentinel = first.destination / "keep-existing.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    verify = install_module.verify_generated_output

    def tamper_before_copy_verification(
        path: str | Path, *, require_strict_release: bool = False
    ) -> dict[str, object]:
        candidate = Path(path)
        if candidate.name.startswith(".civ5studio-install-"):
            modinfo = next(candidate.glob("*.modinfo"))
            modinfo.write_text(
                modinfo.read_text(encoding="utf-8") + "\n<!-- copy changed -->\n",
                encoding="utf-8",
            )
        return verify(path, require_strict_release=require_strict_release)

    monkeypatch.setattr(
        install_module, "verify_generated_output", tamper_before_copy_verification
    )
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        installer.install(strict_build_path, mods)
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert not list(mods.glob(".civ5studio-install-*"))


def test_install_rejects_concurrent_mutation(
    strict_build_path: Path, tmp_path: Path
) -> None:
    mods = tmp_path / "MODS"
    lock_path = mods / ".civ5studio-install.lock"
    with FileMutationLock(lock_path, label="test install"):
        with pytest.raises(InstallInProgress, match="already running"):
            InstallService().install(strict_build_path, mods)


def test_install_rejects_overlong_destination_before_creating_mods_root(
    strict_build_path: Path, tmp_path: Path
) -> None:
    mods = tmp_path / ("long-segment-" + "a" * 64) / ("b" * 64)
    while len(str(mods.resolve() / strict_build_path.name)) <= 240:
        mods /= "c" * 32

    with pytest.raises(ValueError, match="Install Windows path exceeds"):
        InstallService().install(strict_build_path, mods)

    assert not mods.exists()


def test_install_does_not_remove_preexisting_temporary_collision(
    strict_build_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mods = tmp_path / "MODS"
    collision_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    temporary = mods / f".civ5studio-install-{collision_id}"
    temporary.mkdir(parents=True)
    sentinel = temporary / "owned-by-someone-else.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(install_module.uuid, "uuid4", lambda: collision_id)

    with pytest.raises(FileExistsError):
        InstallService().install(strict_build_path, mods)

    assert sentinel.read_text(encoding="utf-8") == "keep me"
