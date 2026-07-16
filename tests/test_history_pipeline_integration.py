from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import pytest

import civ5studio.application.controller as controller_module
from civ5studio.application.advanced_operations import AdvancedOperationResult
from civ5studio.application.controller import ApplicationController
from civ5studio.application.install import InstallResult
from civ5studio.application.project_history import ProjectHistoryPersistenceError
from civ5studio.application.workspace import ProjectWorkspace
from civ5studio.domain.history import ProjectHistoryError
from civ5studio.ui.build_pipeline import BuildPipelineWidget
from civ5studio.ui.history_dialog import ProjectHistoryDialog
from civ5studio.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _workspace(tmp_path: Path, sample_project) -> ProjectWorkspace:
    project = deepcopy(sample_project)
    project.art.assets.clear()
    return ProjectWorkspace.create(tmp_path / "History Integration", project)


def test_controller_undo_redo_and_named_snapshot_survive_workspace_reopen(
    tmp_path: Path, sample_project
) -> None:
    _app()
    workspace = _workspace(tmp_path, sample_project)
    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(workspace.project_path)
    project_page = window.pages[0]

    project_page.author.setText("First history author")  # type: ignore[attr-defined]
    controller._history_timer.stop()
    controller._record_history(label="First author")
    controller.create_snapshot("First author checkpoint")
    snapshot_id = controller.history.snapshots[-1].snapshot_id

    project_page.author.setText("Second history author")  # type: ignore[attr-defined]
    controller._history_timer.stop()
    controller._record_history(label="Second author")
    assert controller.history.can_undo

    controller.undo()
    assert project_page.author.text() == "First history author"  # type: ignore[attr-defined]
    assert window.is_dirty
    controller.redo()
    assert project_page.author.text() == "Second history author"  # type: ignore[attr-defined]
    assert controller.save_project(False)
    assert not window.is_dirty
    assert (workspace.control_root / "history" / "project-history.json").is_file()

    reopened_window = MainWindow()
    reopened = ApplicationController(reopened_window)
    assert reopened.open_path(workspace.project_path)
    assert len(reopened.history.entries) == 1
    assert not reopened.history.can_undo
    assert {item.snapshot_id for item in reopened.history.snapshots} == {snapshot_id}

    restored = reopened.history.restore_snapshot(snapshot_id)
    reopened._apply_history_state(restored, "Restored test snapshot")
    reopened_project_page = reopened_window.pages[0]
    assert reopened_project_page.author.text() == "First history author"  # type: ignore[attr-defined]
    assert reopened_window.is_dirty
    persisted = reopened.history_store.load()  # type: ignore[union-attr]
    persisted_author = persisted.current_state["project"]["author"]
    assert persisted_author == "First history author"
    window.deleteLater()
    reopened_window.deleteLater()


def test_controller_history_state_portabilizes_only_workspace_owned_paths(
    tmp_path: Path, sample_project
) -> None:
    _app()
    workspace = _workspace(tmp_path, sample_project)
    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(workspace.project_path)
    inside = workspace.root / "Assets" / "Source" / "Icon.png"
    outside = tmp_path / "External" / "Icon.png"
    state = {
        "art": {"inside": str(inside), "outside": str(outside)},
        "description": "ordinary text",
    }

    portable = controller._to_history_state(state)

    inside_value = portable["art"]["inside"]  # type: ignore[index]
    outside_value = portable["art"]["outside"]  # type: ignore[index]
    assert inside_value == "civ5studio-workspace://Assets/Source/Icon.png"
    assert outside_value == str(outside)
    assert controller._from_history_state(portable) == state
    with pytest.raises(ProjectHistoryError, match="unsafe workspace path"):
        controller._from_history_state(
            {"art": "civ5studio-workspace://../Outside/Icon.png"}
        )
    window.deleteLater()


def test_history_dialog_exposes_current_marker_comparison_and_section_restore() -> None:
    _app()
    dialog = ProjectHistoryDialog(
        entries=[
            {
                "label": "Opened project",
                "created_utc": "2026-07-15T10:00:00+00:00",
                "digest": "a" * 64,
                "current": True,
            }
        ],
        snapshots=[
            {
                "snapshot_id": "snapshot-1",
                "label": "Before build",
                "reason": "before_build",
                "created_utc": "2026-07-15T10:01:00+00:00",
                "comparison": {
                    "total_changes": 2,
                    "modified_sections": ["art", "project"],
                    "changed_paths": ["/art/icon", "/project/mod_name"],
                },
            }
        ],
    )

    assert "← current" in dialog.timeline.item(0).text()
    assert "·" in dialog.snapshot_list.item(0).text()
    assert dialog.restore_button.isEnabled()
    assert "2 change(s)" in dialog.comparison.text()
    assert "art, project" in dialog.comparison.text()
    dialog.section_combo.setCurrentIndex(dialog.section_combo.findData("art"))
    dialog._restore()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selected_snapshot_id == "snapshot-1"
    assert dialog.selected_section == "art"
    dialog.deleteLater()


def test_controller_history_dialog_restores_only_selected_section(monkeypatch) -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    project_page = window.pages[0]
    civilization_page = window.pages[1]
    project_page.author.setText("Snapshot author")  # type: ignore[attr-defined]
    civilization_page.name.setText("Snapshot civilization")  # type: ignore[attr-defined]
    controller._history_timer.stop()
    controller._record_history(label="Snapshot source")
    snapshot = controller.history.create_snapshot("Selective restore")

    project_page.author.setText("Current author")  # type: ignore[attr-defined]
    civilization_page.name.setText("Current civilization")  # type: ignore[attr-defined]
    controller._history_timer.stop()
    controller._record_history(label="Current edit")
    captured: dict[str, object] = {}

    class SelectingDialog:
        def __init__(self, *, entries, snapshots, parent) -> None:
            captured["entries"] = entries
            captured["snapshots"] = snapshots
            self.selected_snapshot_id = snapshot.snapshot_id
            self.selected_section = "civilization"

        def exec(self) -> int:
            return 1

    monkeypatch.setattr(controller_module, "ProjectHistoryDialog", SelectingDialog)
    controller.show_history()

    assert project_page.author.text() == "Current author"  # type: ignore[attr-defined]
    assert civilization_page.name.text() == "Snapshot civilization"  # type: ignore[attr-defined]
    assert window.is_dirty
    entries = captured["entries"]
    snapshots = captured["snapshots"]
    assert sum(bool(item["current"]) for item in entries) == 1  # type: ignore[arg-type]
    assert snapshots[0]["comparison"]["total_changes"] >= 2  # type: ignore[index]
    window.deleteLater()


def test_pipeline_invalidates_every_recorded_stage_and_resets_cleanly() -> None:
    _app()
    pipeline = BuildPipelineWidget()
    terminal = {
        "audit": "PASS",
        "validate": "PASS",
        "build": "PASS",
        "install": "PASS",
        "launch": "REQUESTED",
        "analyze": "COMPLETE",
    }
    for stage, status in terminal.items():
        assert pipeline.set_stage(stage, status, f"{stage} result")

    pipeline.invalidate_after_edit()
    assert {stage: pipeline.status(stage) for stage in terminal} == {
        stage: "STALE" for stage in terminal
    }
    pipeline.reset()
    assert all(pipeline.status(stage) == "NOT RUN" for stage in terminal)
    pipeline.deleteLater()


def test_stale_async_completion_cannot_resurrect_install_or_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    monkeypatch.setattr(controller_module.QMessageBox, "information", lambda *args: None)

    window.review_page.set_pipeline_stage("install", "RUNNING", "Installing old revision")
    window.review_page.invalidate_after_edit()
    controller._install_finished(
        InstallResult(tmp_path / "Old Build", None), controller._project_revision - 1
    )
    assert window.review_page.pipeline.status("install") == "STALE"
    assert "install completed" in window.review_page.pipeline.stages["install"].detail.text()
    assert not window.review_page.pipeline.set_stage(
        "install", "PASS", "Late callback must not resurrect this result"
    )
    assert window.review_page.pipeline.status("install") == "STALE"

    window.review_page.set_pipeline_stage("analyze", "RUNNING", "Analyzing old revision")
    window.review_page.invalidate_after_edit()
    controller._diagnostics_finished(
        AdvancedOperationResult("Old log result"), controller._project_revision - 1
    )
    assert window.review_page.pipeline.status("analyze") == "STALE"

    window.review_page.set_pipeline_stage("install", "RUNNING", "New current install")
    controller._install_finished(
        InstallResult(tmp_path / "Current Build", None), controller._project_revision
    )
    assert window.review_page.pipeline.status("install") == "PASS"
    window.deleteLater()


def test_steam_handoff_never_marks_runtime_pass(monkeypatch) -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    window.review_page.set_pipeline_stage("install", "PASS", "Current build installed")
    window.review_page.runtime_status.setCurrentText("PASS")
    assert window.review_page.pipeline.status("launch") == "PASS"
    opened: list[str] = []

    monkeypatch.setattr(
        controller_module.QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Open,
    )
    monkeypatch.setattr(
        controller_module,
        "QDesktopServices",
        SimpleNamespace(openUrl=lambda url: opened.append(url.toString()) or True),
    )

    controller.launch_civilization_v()

    assert opened == ["steam://rungameid/8930"]
    assert window.review_page.pipeline.status("launch") == "REQUESTED"
    assert window.review_page.runtime_status.currentText() == "NOT RUN"
    assert "NOT RUN" in window.review_page.pipeline.stages["launch"].detail.text()
    window.review_page.runtime_status.setCurrentText("PASS")
    window.review_page.runtime_status.setCurrentText("NOT RUN")
    assert window.review_page.pipeline.status("launch") == "NOT RUN"
    window.deleteLater()


def test_unreadable_workspace_history_is_never_replaced_on_open_or_save(
    tmp_path: Path, sample_project
) -> None:
    _app()
    workspace = _workspace(tmp_path, sample_project)
    history_path = workspace.control_root / "history" / "project-history.json"
    history_path.parent.mkdir()
    original = b'{"snapshots": [broken history'
    history_path.write_bytes(original)
    window = MainWindow()
    controller = ApplicationController(window)

    assert controller.open_path(workspace.project_path)
    assert controller._history_persistence_blocked
    assert controller.history_store is None
    assert history_path.read_bytes() == original
    assert controller.save_project(False)
    assert history_path.read_bytes() == original
    controller.create_snapshot("Session-only checkpoint")
    assert "session only" in window.statusBar().currentMessage()
    assert history_path.read_bytes() == original
    window.deleteLater()


def test_snapshot_write_failure_is_reported_as_memory_only(monkeypatch) -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)

    class FailingStore:
        path = Path("C:/unwritable/project-history.json")

        def save(self, _history):
            raise ProjectHistoryPersistenceError("simulated disk failure")

    controller.history_store = FailingStore()  # type: ignore[assignment]
    controller.create_snapshot("Important checkpoint")

    message = window.statusBar().currentMessage()
    assert "memory only" in message
    assert "could not be persisted" in message
    window.deleteLater()


def test_successful_save_clears_stale_build_and_install_readiness(
    tmp_path: Path, sample_project
) -> None:
    _app()
    workspace = _workspace(tmp_path, sample_project)
    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(workspace.project_path)
    build = tmp_path / "Validated Build"
    build.mkdir()
    controller.last_build_path = build
    window.review_page.set_pipeline_stage(
        "build", "PASS", "Old build", artifact_path=str(build)
    )
    window.review_page.install_button.setProperty("ready", True)
    window.review_page.install_button.setEnabled(True)

    assert controller.save_project(False)

    assert controller.last_build_path is None
    assert window.review_page.pipeline.status("build") == "NOT RUN"
    assert window.review_page.install_button.property("ready") is False
    assert not window.review_page.install_button.isEnabled()
    window.deleteLater()


def test_operation_presave_preserves_prior_command_center_stages(
    tmp_path: Path, sample_project
) -> None:
    _app()
    workspace = _workspace(tmp_path, sample_project)
    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(workspace.project_path)
    window.review_page.set_pipeline_stage("audit", "PASS", "Audit is current")

    assert controller._save_values(
        window.collect_values(), False, preserve_review=True
    )
    assert window.review_page.pipeline.status("audit") == "PASS"
    window.review_page.set_pipeline_stage(
        "validate", "PASS", "Validation is current"
    )
    assert controller._save_values(
        window.collect_values(), False, preserve_review=True
    )
    assert window.review_page.pipeline.status("audit") == "PASS"
    assert window.review_page.pipeline.status("validate") == "PASS"
    window.deleteLater()
