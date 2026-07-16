from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import civ5studio.application.project_history as store_module
from civ5studio.application.project_history import (
    ProjectHistoryPersistenceError,
    ProjectHistoryStore,
    UnsafeHistoryPath,
)
from civ5studio.application.workspace import ProjectWorkspace
from civ5studio.domain import CivProject
from civ5studio.domain.history import (
    HistoryBoundaryError,
    InvalidHistoryState,
    ProjectHistory,
    ProjectHistoryError,
    SnapshotReason,
    UnknownSectionError,
    compare_states,
)


def _state(revision: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "project": {"mod_name": "History Nation", "revision": revision},
        "civilization": {"name": f"Nation {revision}", "cities": ["Alpha"]},
        "units": [{"name": "Guard", "combat": 8 + revision}],
    }


def _workspace(tmp_path: Path) -> ProjectWorkspace:
    project = CivProject(
        mod_name="History Nation",
        internal_prefix="HISTORY_NATION",
    )
    return ProjectWorkspace.create(tmp_path / "History Project", project)


def test_complete_states_are_detached_coalesced_and_branch_safely() -> None:
    history = ProjectHistory(max_entries=10)
    original = _state(0)
    history.reset(original)
    original["project"]["revision"] = 99  # type: ignore[index]
    assert history.current_state["project"]["revision"] == 0  # type: ignore[index]

    history.record(_state(1), label="First edit")
    history.record(_state(2), label="Second edit")
    assert history.undo()["project"]["revision"] == 1  # type: ignore[index]
    assert history.can_redo

    duplicate = history.record(_state(1), label="Duplicate label is coalesced")
    assert duplicate.added is False
    assert duplicate.redo_discarded == 0
    assert history.can_redo

    branch = history.record(_state(3), label="Branched edit")
    assert branch.added is True
    assert branch.redo_discarded == 1
    assert not history.can_redo
    with pytest.raises(HistoryBoundaryError, match="later"):
        history.redo()

    detached = history.current_state
    detached["project"]["revision"] = 100  # type: ignore[index]
    assert history.current_state["project"]["revision"] == 3  # type: ignore[index]


def test_history_limit_prunes_oldest_states_and_keeps_cursor_coherent() -> None:
    history = ProjectHistory(max_entries=3)
    history.reset(_state(0))
    for revision in range(1, 5):
        history.record(_state(revision), label=f"Revision {revision}")

    assert [entry.label for entry in history.entries] == [
        "Revision 2",
        "Revision 3",
        "Revision 4",
    ]
    assert history.cursor == 2
    assert history.undo()["project"]["revision"] == 3  # type: ignore[index]
    assert history.undo()["project"]["revision"] == 2  # type: ignore[index]
    with pytest.raises(HistoryBoundaryError, match="earlier"):
        history.undo()


@pytest.mark.parametrize(
    "state",
    [
        ["not", "an", "object"],
        {"bad": {1, 2}},
        {"bad": (1, 2)},
        {"bad": float("nan")},
        {1: "non-string key"},
    ],
)
def test_history_rejects_values_that_cannot_be_safe_json(state: object) -> None:
    history = ProjectHistory()
    with pytest.raises(InvalidHistoryState):
        history.record(state)  # type: ignore[arg-type]


def test_named_and_automatic_snapshots_are_bounded() -> None:
    history = ProjectHistory(max_snapshots=2)
    history.reset(_state(0))
    manual = history.create_snapshot("Stable draft")
    before_import = history.snapshot_before_import(detail="Legacy Mod")
    before_build = history.snapshot_before_build(detail="Release candidate")

    assert manual.snapshot_id not in {item.snapshot_id for item in history.snapshots}
    assert [item.reason for item in history.snapshots] == [
        SnapshotReason.BEFORE_IMPORT,
        SnapshotReason.BEFORE_BUILD,
    ]
    assert before_import.label == "Before import — Legacy Mod"
    assert before_build.label == "Before build — Release candidate"
    with pytest.raises(ProjectHistoryError, match="control"):
        history.create_snapshot("bad\nlabel")


def test_snapshot_and_section_restore_record_complete_result() -> None:
    history = ProjectHistory()
    history.reset(_state(0))
    snapshot = history.create_snapshot("Baseline")
    history.record(_state(4))

    restored_section = history.restore_section(snapshot.snapshot_id, "civilization")
    assert restored_section["civilization"]["name"] == "Nation 0"  # type: ignore[index]
    assert restored_section["project"]["revision"] == 4  # type: ignore[index]

    revised = history.current_state
    revised["units"][0]["combat"] = 99  # type: ignore[index]
    history.record(revised)
    restored_nested = history.restore_section(
        snapshot.snapshot_id, ("units", 0, "combat")
    )
    assert restored_nested["units"][0]["combat"] == 8  # type: ignore[index]
    assert history.current_entry.label.startswith("Restore section /units/0/combat")

    restored_all = history.restore_snapshot(snapshot.snapshot_id)
    assert restored_all == _state(0)
    with pytest.raises(UnknownSectionError, match="not present"):
        history.restore_section(snapshot.snapshot_id, ("units", 8))


def test_compare_summary_reports_top_level_sections_and_bounded_paths() -> None:
    before = {
        "project": {"name": "Old"},
        "removed": True,
        "list": [1, 2],
    }
    after = {
        "project": {"name": "New", "version": 2},
        "added": True,
        "list": [1, 3, 4],
    }

    summary = compare_states(before, after, max_paths=2)

    assert summary.identical is False
    assert summary.total_changes == 6
    assert summary.added_sections == ("added",)
    assert summary.removed_sections == ("removed",)
    assert summary.modified_sections == ("list", "project")
    assert len(summary.changed_paths) == 2
    assert summary.truncated is True
    assert compare_states(before, deepcopy(before)).identical
    type_change = compare_states({"value": True}, {"value": 1})
    assert type_change.total_changes == 1
    assert type_change.modified_sections == ("value",)


def test_versioned_payload_round_trips_and_detects_tampering() -> None:
    project_id = "11111111-1111-4111-8111-111111111111"
    workspace_id = "22222222-2222-4222-8222-222222222222"
    history = ProjectHistory(max_entries=5, max_snapshots=3)
    history.reset(_state(0))
    history.snapshot_before_build(detail="Test")
    history.record(_state(1))
    history.undo()

    payload = history.to_payload(project_id=project_id, workspace_id=workspace_id)
    loaded = ProjectHistory.from_payload(
        payload,
        expected_project_id=project_id,
        expected_workspace_id=workspace_id,
    )
    assert loaded.current_state == _state(0)
    assert loaded.can_redo
    assert loaded.snapshots[0].reason is SnapshotReason.BEFORE_BUILD

    tampered = deepcopy(payload)
    tampered["entries"][0]["state"]["project"]["revision"] = 999
    with pytest.raises(InvalidHistoryState, match="digest"):
        ProjectHistory.from_payload(
            tampered,
            expected_project_id=project_id,
            expected_workspace_id=workspace_id,
        )
    with pytest.raises(InvalidHistoryState, match="different project"):
        ProjectHistory.from_payload(
            payload,
            expected_project_id="33333333-3333-4333-8333-333333333333",
            expected_workspace_id=workspace_id,
        )


def test_store_uses_only_fixed_project_owned_location_and_round_trips(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    store = ProjectHistoryStore(
        workspace, default_max_entries=7, default_max_snapshots=4
    )
    assert store.load().empty
    assert not store.exists()

    history = ProjectHistory(max_entries=7, max_snapshots=4)
    history.reset(_state(0))
    history.snapshot_before_import(detail="Source mod")
    result = store.save(history)

    expected = workspace.control_root / "history" / "project-history.json"
    assert result.path == expected
    assert result.path.is_file()
    assert result.size == result.path.stat().st_size
    assert json.loads(result.path.read_text(encoding="utf-8"))["workspace_id"] == (
        workspace.workspace_id
    )
    loaded = ProjectHistoryStore(ProjectWorkspace.open(workspace.root)).load()
    assert loaded.current_state == _state(0)
    assert loaded.snapshots[0].label == "Before import — Source mod"


def test_atomic_save_failure_preserves_previous_history_and_cleans_own_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    store = ProjectHistoryStore(workspace)
    history = ProjectHistory()
    history.reset(_state(0))
    store.save(history)
    previous = store.path.read_bytes()
    history.record(_state(1))

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)
    with pytest.raises(ProjectHistoryPersistenceError, match="atomically"):
        store.save(history)

    assert store.path.read_bytes() == previous
    assert not list(store.path.parent.glob(".project-history.json.*.tmp"))


def test_store_rejects_unsafe_history_directory_without_removing_it(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    unsafe = workspace.control_root / "history"
    unsafe.write_text("sentinel", encoding="utf-8")

    with pytest.raises(UnsafeHistoryPath, match="not a directory"):
        ProjectHistoryStore(workspace).save(ProjectHistory())

    assert unsafe.read_text(encoding="utf-8") == "sentinel"


def test_store_revalidates_workspace_marker_before_any_history_write(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Unmarked"
    root.mkdir()
    forged = ProjectWorkspace(
        root,
        project_id="11111111-1111-4111-8111-111111111111",
        workspace_id="22222222-2222-4222-8222-222222222222",
        project_file="project.civ5project.json",
    )
    history = ProjectHistory()
    history.reset(_state(0))

    with pytest.raises(UnsafeHistoryPath, match="marked workspace"):
        ProjectHistoryStore(forged).save(history)
    assert not (root / ".civ5studio").exists()
    assert not (root / ".civ5studio" / "history").exists()


def test_store_wraps_workspace_lock_and_marker_failures_for_controller(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    store = ProjectHistoryStore(workspace)
    history = ProjectHistory()
    history.reset(_state(0))

    with workspace.lock():
        with pytest.raises(ProjectHistoryPersistenceError, match="Could not save"):
            store.save(history)

    workspace.marker_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ProjectHistoryPersistenceError, match="Could not load"):
        store.load()
