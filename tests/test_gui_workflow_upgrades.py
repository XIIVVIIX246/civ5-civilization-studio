from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

import civ5studio.application.controller as controller_module
from civ5studio.application.controller import ApplicationController
from civ5studio.application.workspace import ProjectWorkspace
from civ5studio.domain import load_project
from civ5studio.ui.build_pipeline import BuildPipelineWidget
from civ5studio.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_problem_navigation_updates_step_health_and_reveals_hidden_field() -> None:
    _app()
    window = MainWindow()
    assert window.mode_combo.currentText() == "Guided (recommended)"
    assert window.mode_combo.currentData() == "guided"
    assert window.pages[0].technical_card.isHidden()  # type: ignore[attr-defined]

    issues = [
        {
            "severity": "ERROR",
            "location": "internal_prefix",
            "message": "Prefix is invalid.",
            "hint": "Use uppercase letters, numbers, and underscores.",
            "code": "id.prefix",
        },
        {
            "severity": "WARNING",
            "location": "lua_effects[0].effect_id",
            "message": "Runtime test is still required.",
        },
    ]
    window.set_live_issues(issues, "One error and one warning")

    assert "1 fix" in window.steps.item(0).text()
    assert "1 tip" in window.steps.item(7).text()
    first_group = window.problems.tree.topLevelItem(0)
    assert first_group.child(0).text(3).startswith("Use uppercase")
    window.problems._item_activated(first_group.child(0))
    assert window.steps.currentRow() == 0
    assert window.mode_combo.currentText() == "Expert controls"
    assert window.mode_combo.currentData() == "expert"
    assert not window.pages[0].technical_card.isHidden()  # type: ignore[attr-defined]
    window.mark_clean()
    window.deleteLater()


def test_live_preview_and_mechanics_workspace_follow_current_draft() -> None:
    _app()
    window = MainWindow()
    civilization = window.pages[1]
    leader = window.pages[2]
    mechanics = window.pages[3]
    civilization.name.setText("Republic of Test")  # type: ignore[attr-defined]
    leader.name.setText("Ada")  # type: ignore[attr-defined]
    mechanics.trait_name.setText("Measured Progress")  # type: ignore[attr-defined]
    window._refresh_preview()

    assert window.civilization_preview.setup.civ_name.text() == "Republic of Test"
    assert "Ada" in window.civilization_preview.setup.leader.text()
    assert "Measured Progress" in window.civilization_preview.setup.trait.text()

    editor = mechanics.uniques  # type: ignore[attr-defined]
    editor.set_reference_catalog(
        [("UNITCLASS_WARRIOR", "UNIT_WARRIOR")],
        [("BUILDINGCLASS_MONUMENT", "BUILDING_MONUMENT")],
        ["YIELD_CULTURE"],
        improvement_templates=["IMPROVEMENT_FARM"],
    )
    editor.donor_search.setText("Warrior")
    assert editor.donor_list.count() == 1
    before = len(editor.values())
    editor._add_selected_donor()
    assert len(editor.values()) == before + 1
    assert editor.selected_cards.count() == len(editor.values())
    assert editor.table.isHidden()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("expert"))
    assert not editor.table.isHidden()
    window.mark_clean()
    window.deleteLater()


def test_quick_start_generates_prefix_template_snapshot_and_compiled_recipe(
    monkeypatch,
) -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    project = window.pages[0]
    project.mod_name.setText("River & Star Union")  # type: ignore[attr-defined]
    assert project.prefix.text() == "RIVER_STAR_UNION"  # type: ignore[attr-defined]

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Apply,
    )
    before_snapshots = len(controller.history.snapshots)
    window._apply_template("tall_culture")
    mechanics = window.pages[3]
    assert mechanics.recipe.currentText() == "Wonder production modifier"  # type: ignore[attr-defined]
    assert mechanics.modifier_value.value() == 15  # type: ignore[attr-defined]
    assert len(controller.history.snapshots) == before_snapshots + 1
    window.mark_clean()
    window.deleteLater()


def test_controller_undo_redo_restores_complete_ui_states() -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    author = window.pages[0].author  # type: ignore[attr-defined]

    author.setText("First Author")
    controller._history_timer.stop()
    controller._record_history(label="First author")
    author.setText("Second Author")
    controller._history_timer.stop()
    controller._record_history(label="Second author")

    controller.undo()
    assert window.pages[0].author.text() == "First Author"  # type: ignore[attr-defined]
    assert window.is_dirty
    controller.redo()
    assert window.pages[0].author.text() == "Second Author"  # type: ignore[attr-defined]
    window.mark_clean()
    window.deleteLater()


def test_named_snapshot_persists_only_in_marked_project_workspace(tmp_path: Path) -> None:
    _app()
    sample = (
        Path(__file__).resolve().parents[1]
        / "samples"
        / "kingdom_of_lithuania.civ5project.json"
    )
    project = deepcopy(load_project(sample))
    project.art.assets.clear()
    workspace = ProjectWorkspace.create(tmp_path / "History Workspace", project)

    first_window = MainWindow()
    first = ApplicationController(first_window)
    assert first.open_path(workspace.project_path)
    first.create_snapshot("Known good editor state")
    history_path = workspace.control_root / "history" / "project-history.json"
    assert history_path.is_file()
    first_window.mark_clean()
    first_window.deleteLater()

    second_window = MainWindow()
    second = ApplicationController(second_window)
    assert second.open_path(workspace.project_path)
    assert [item.label for item in second.history.snapshots] == [
        "Known good editor state"
    ]
    second_window.mark_clean()
    second_window.deleteLater()


def test_pipeline_never_turns_steam_handoff_into_runtime_pass(monkeypatch) -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    monkeypatch.setattr(
        controller_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Open,
    )
    monkeypatch.setattr(
        controller_module.QDesktopServices,
        "openUrl",
        lambda *_args, **_kwargs: True,
    )

    controller.launch_civilization_v()

    assert window.review_page.pipeline.status("launch") == "REQUESTED"
    assert window.review_page.runtime_status.currentText() == "NOT RUN"
    window.review_page.runtime_status.setCurrentText("PASS")
    assert window.review_page.pipeline.status("launch") == "PASS"
    window.mark_clean()
    window.deleteLater()


def test_global_navigation_and_accessibility_actions_are_available() -> None:
    _app()
    window = MainWindow()
    assert window.palette_action.shortcut().toString() == "Ctrl+K"
    assert len(window.step_actions) == 9
    assert [action.shortcut().toString() for action in window.step_actions] == [
        "Alt+1",
        "Alt+2",
        "Alt+3",
        "Alt+4",
        "",
        "Alt+5",
        "",
        "",
        "Alt+6",
    ]
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("expert"))
    assert [action.shortcut().toString() for action in window.step_actions] == [
        f"Alt+{index}" for index in range(1, 10)
    ]
    window._set_text_scale(125)
    assert window.scale_actions[125].isChecked()
    window.high_contrast_action.setChecked(True)
    window._set_high_contrast(True)
    assert "#ffffff" in window.styleSheet()
    window.high_contrast_action.setChecked(False)
    window._set_high_contrast(False)
    window._set_text_scale(100)
    window.mark_clean()
    window.deleteLater()


def test_pipeline_records_session_timing_and_opens_recorded_artifact(
    tmp_path: Path,
) -> None:
    _app()
    artifact = tmp_path / "Validated Build"
    artifact.mkdir()
    pipeline = BuildPipelineWidget()
    opened: list[str] = []
    pipeline.artifactRequested.connect(opened.append)

    assert pipeline.set_stage("build", "RUNNING", "Building current revision")
    stage = pipeline.stages["build"]
    assert stage.meta_label.text().startswith("Started ")
    assert pipeline.set_stage(
        "build", "PASS", "Build complete", artifact_path=str(artifact)
    )
    assert "Updated " in stage.meta_label.text()
    assert "s" in stage.meta_label.text()
    assert not stage.artifact_button.isHidden()
    stage.artifact_button.click()
    assert opened == [str(artifact)]

    pipeline.invalidate_after_edit()
    assert pipeline.status("build") == "STALE"
    assert stage.artifact_path == str(artifact)
    pipeline.reset()
    assert stage.artifact_path == ""
    assert stage.artifact_button.isHidden()
    pipeline.deleteLater()


def test_controller_opens_only_an_existing_displayed_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("evidence", encoding="utf-8")
    window = MainWindow()
    controller = ApplicationController(window)
    opened: list[str] = []
    monkeypatch.setattr(
        controller_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    controller.open_artifact(str(artifact))

    assert len(opened) == 1
    assert Path(opened[0]).resolve() == artifact.resolve()
    assert "Opened artifact" in window.statusBar().currentMessage()
    window.mark_clean()
    window.deleteLater()
