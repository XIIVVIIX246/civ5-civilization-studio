from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

import civ5studio.application.workspace as workspace_module
from civ5studio.application.workspace import (
    ProjectWorkspace,
    RecoveryError,
    UnsafeWorkspaceError,
    WorkspaceAssetError,
    WorkspaceBusyError,
)
from civ5studio.domain import ArtAssetSpec, ArtRole, CivProject, load_project


def _png(path: Path, color: tuple[int, int, int] = (20, 40, 60)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (24, 24), color).save(path)
    return path


def _project(source: Path | str | None = None) -> CivProject:
    project = CivProject(
        mod_name="Workspace Nation",
        internal_prefix="WORKSPACE_NATION",
    )
    if source is not None:
        project.art.assets.append(
            ArtAssetSpec(
                asset_id="civilization_icon",
                role=ArtRole.CIVILIZATION_ICON,
                source_png=str(source),
            )
        )
    return project


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_create_claims_empty_workspace_and_copies_external_art(tmp_path: Path) -> None:
    external = _png(tmp_path / "external" / "Icon with spaces.png")
    original_hash = _hash(external)
    root = tmp_path / "portable-workspace"

    workspace = ProjectWorkspace.create(root, _project(external))

    loaded = workspace.load()
    relative = loaded.art.assets[0].source_png
    assert relative.startswith("Assets/Source/Icon_with_spaces_")
    assert not Path(relative).is_absolute()
    assert (root / relative).is_file()
    assert _hash(root / relative) == original_hash == _hash(external)
    marker = json.loads(workspace.marker_path.read_text(encoding="utf-8"))
    assert marker["marker_format"] == "civ5studio.workspace"
    assert marker["marker_version"] == 2
    assert marker["project_id"] == loaded.project_id
    assert ProjectWorkspace.open(root).project_path == workspace.project_path
    assert ProjectWorkspace.open_project_file(workspace.project_path).root == root.resolve()


def test_create_never_claims_or_changes_a_nonempty_unmarked_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "not-a-workspace"
    root.mkdir()
    sentinel = root / "keep.txt"
    sentinel.write_text("do not touch", encoding="utf-8")

    with pytest.raises(UnsafeWorkspaceError, match="non-empty unmarked"):
        ProjectWorkspace.create(root, _project())

    assert sentinel.read_text(encoding="utf-8") == "do not touch"
    assert not (root / ".civ5studio").exists()


@pytest.mark.parametrize(
    "filename", ["CON.civ5project.json", "bad?.civ5project.json", "nested/project.civ5project.json"]
)
def test_create_rejects_project_filenames_that_are_not_windows_safe(
    tmp_path: Path, filename: str
) -> None:
    root = tmp_path / filename.replace("/", "_")
    with pytest.raises(UnsafeWorkspaceError):
        ProjectWorkspace.create(
            root,
            _project(),
            project_file=filename,
        )
    assert not root.exists()


def test_create_requires_resolvable_png_sources_and_preserves_partial_input(
    tmp_path: Path,
) -> None:
    project = _project("Art/missing.png")
    root = tmp_path / "workspace"
    with pytest.raises(WorkspaceAssetError, match="missing"):
        ProjectWorkspace.create(root, project)
    assert project.art.assets[0].source_png == "Art/missing.png"
    assert not root.exists()


def test_save_is_atomic_and_retains_only_changed_previous_revisions(
    tmp_path: Path,
) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    original = workspace.load()
    changed = deepcopy(original)
    changed.description = "Second revision"

    result = workspace.save(changed)

    assert result.backup_path is not None and result.backup_path.is_file()
    assert load_project(result.backup_path) == original
    assert workspace.load() == changed
    assert workspace.list_backups() == (result.backup_path,)
    same = workspace.save(changed)
    assert same.backup_path is None
    assert workspace.list_backups() == (result.backup_path,)
    assert not tuple(workspace.root.rglob("*.tmp"))


def test_failed_primary_replace_leaves_previous_document_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    original = workspace.project_path.read_bytes()
    changed = workspace.load()
    changed.description = "Must not be partially published"
    real_replace = workspace_module.os.replace

    def fail_project_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == workspace.project_path:
            raise OSError("simulated interrupted replace")
        real_replace(source, destination)

    monkeypatch.setattr(workspace_module.os, "replace", fail_project_replace)
    with pytest.raises(OSError, match="interrupted replace"):
        workspace.save(changed)

    assert workspace.project_path.read_bytes() == original
    assert not tuple(workspace.root.rglob("*.tmp"))


def test_save_rejects_external_paths_unless_import_is_explicit(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    external = _png(tmp_path / "outside.png")
    project = workspace.load()
    project.art.assets.append(
        ArtAssetSpec(
            asset_id="leader_portrait",
            role=ArtRole.LEADER_PORTRAIT,
            source_png=str(external),
            subject_key="leader",
        )
    )

    with pytest.raises(UnsafeWorkspaceError, match="not portable"):
        workspace.save(project)

    result = workspace.save(project, import_sources=True, require_assets=True)
    assert result.project_path.is_file()
    imported = workspace.load().art.assets[0].source_png
    assert imported.startswith("Assets/Source/")
    assert _hash(workspace.root / imported) == _hash(external)


def test_content_addressed_import_reuses_bytes_and_bounds_long_names(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    source = _png(tmp_path / "external" / (("long_" * 35) + ".png"))

    first = workspace.import_source(source)
    second = workspace.import_source(source)

    assert first.reused is False
    assert second.reused is True
    assert first.relative_path == second.relative_path
    assert len(Path(first.relative_path).name) < 100
    assert first.sha256 == _hash(source)


def test_workspace_lock_rejects_overlapping_mutations(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    with workspace.lock():
        with pytest.raises(WorkspaceBusyError, match="already being changed"):
            workspace.save(workspace.load())


def test_autosave_recovers_with_primary_backup_then_marks_recovery_discarded(
    tmp_path: Path,
) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    primary = workspace.load()
    draft = deepcopy(primary)
    draft.description = "Unsaved recovered work"

    status = workspace.autosave(draft)

    assert status.available is True
    assert status.reason == "available"
    assert status.base_matches_current is True
    assert workspace.load() == primary
    assert workspace.load_recovery() == draft

    recovered = workspace.recover()

    assert recovered.backup_path is not None
    assert load_project(recovered.backup_path) == primary
    assert workspace.load() == draft
    cleared = workspace.recovery_status()
    assert cleared.available is False
    assert cleared.reason == "discarded"


def test_recovery_reports_when_primary_changed_after_autosave(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    autosaved = workspace.load()
    autosaved.description = "Autosaved branch"
    workspace.autosave(autosaved)

    manually_changed = workspace.load()
    manually_changed.description = "Different primary branch"
    workspace.save(manually_changed, clear_recovery=False)

    status = workspace.recovery_status()
    assert status.available is True
    assert status.base_matches_current is False
    assert workspace.load_recovery().description == "Autosaved branch"


def test_orphaned_autosave_is_discoverable_after_metadata_loss(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    draft = workspace.load()
    draft.description = "Survived metadata interruption"
    initial = workspace.autosave(draft)
    assert initial.autosave_path is not None
    workspace._recovery_metadata_path.unlink()

    status = workspace.recovery_status()

    assert status.available is True
    assert status.reason == "orphaned_autosave"
    assert status.orphaned_metadata is True
    assert status.autosave_path == initial.autosave_path


def test_tampered_autosave_is_never_recovered(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    draft = workspace.load()
    draft.description = "Draft"
    status = workspace.autosave(draft)
    assert status.autosave_path is not None
    status.autosave_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RecoveryError, match="SHA-256"):
        workspace.recovery_status()
    with pytest.raises(RecoveryError, match="SHA-256"):
        workspace.recover()


def test_restore_accepts_only_exact_project_owned_backup(tmp_path: Path) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    initial = workspace.load()
    changed = deepcopy(initial)
    changed.description = "Changed"
    saved = workspace.save(changed)
    assert saved.backup_path is not None

    restored = workspace.restore_backup(saved.backup_path)

    assert workspace.load() == initial
    assert restored.backup_path is not None
    external = tmp_path / saved.backup_path.name
    external.write_bytes(saved.backup_path.read_bytes())
    with pytest.raises(UnsafeWorkspaceError, match="project-owned backup"):
        workspace.restore_backup(external)


def test_open_rejects_tampered_workspace_identity_without_touching_files(
    tmp_path: Path,
) -> None:
    workspace = ProjectWorkspace.create(tmp_path / "workspace", _project())
    marker = json.loads(workspace.marker_path.read_text(encoding="utf-8"))
    marker["project_id"] = "36efe3ac-62ba-4199-a92c-39ed94d86138"
    workspace.marker_path.write_text(json.dumps(marker), encoding="utf-8")
    project_before = workspace.project_path.read_bytes()

    with pytest.raises(UnsafeWorkspaceError, match="different project IDs"):
        ProjectWorkspace.open(workspace.root)

    assert workspace.project_path.read_bytes() == project_before
