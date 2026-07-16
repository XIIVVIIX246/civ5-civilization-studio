from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import civ5studio.application.controller as controller_module
from civ5studio.application.controller import ApplicationController
from civ5studio.application.workflow import WorkflowMode, WorkflowResult
from civ5studio.application.workspace import ProjectWorkspace
from civ5studio.domain import load_project
from civ5studio.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_controller_populates_bundled_bnw_choices() -> None:
    _app()
    window = MainWindow()
    controller = ApplicationController(window)
    civilization = window.pages[1]
    mechanics = window.pages[3]
    assert civilization.base_civ.count() >= 40  # type: ignore[attr-defined]
    rows = mechanics.uniques.values()  # type: ignore[attr-defined]
    assert rows[0]["base_template"].startswith("UNIT_")
    assert rows[1]["base_template"].startswith("BUILDING_")
    recipe_labels = {
        mechanics.recipe.itemText(index)  # type: ignore[attr-defined]
        for index in range(mechanics.recipe.count())  # type: ignore[attr-defined]
    }
    assert "Worker speed modifier" in recipe_labels
    assert "Wonder production modifier" in recipe_labels
    assert "Military production modifier" not in recipe_labels
    implementation_labels = {
        mechanics.mechanic_level.itemText(index)  # type: ignore[attr-defined]
        for index in range(mechanics.mechanic_level.count())  # type: ignore[attr-defined]
    }
    assert "Tested Lua recipe" not in implementation_labels
    assert "Lua idea (not compiled)" in implementation_labels
    assert window.lua_effects_page.slot_combos[0].count() == 200
    assert window.lua_effects_page.category_filter.count() > 10
    assert window.lua_effects_page.values() == {"selections": []}
    assert window.is_dirty is False
    assert controller.project is None
    window.deleteLater()


def test_controller_opens_canonical_project_without_dialog(tmp_path: Path) -> None:
    _app()
    sample = Path(__file__).resolve().parents[1] / "samples" / "kingdom_of_lithuania.civ5project.json"
    project_path = tmp_path / sample.name
    shutil.copy2(sample, project_path)
    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(project_path)
    assert window.project_path == project_path.resolve()
    assert window.collect_values()["project"]["mod_name"] == "Kingdom of Lithuania"
    assert window.is_dirty is False
    window.deleteLater()


def test_controller_uses_workspace_autosave_and_atomic_save(tmp_path: Path) -> None:
    _app()
    sample = (
        Path(__file__).resolve().parents[1]
        / "samples"
        / "kingdom_of_lithuania.civ5project.json"
    )
    project = deepcopy(load_project(sample))
    project.art.assets.clear()
    workspace = ProjectWorkspace.create(tmp_path / "Lithuania Project", project)

    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(workspace.project_path)
    assert controller.workspace is not None
    project_page = window.pages[0]
    project_page.author.setText("Autosaved Author")  # type: ignore[attr-defined]
    assert window.is_dirty

    controller._autosave_workspace()
    assert workspace.recovery_status().available
    assert controller.save_project(False)
    assert not workspace.recovery_status().available
    assert workspace.load().authors == "Autosaved Author"
    assert workspace.list_backups()
    window.deleteLater()


def test_stale_build_result_cannot_be_installed_after_project_edit(
    tmp_path: Path,
) -> None:
    _app()
    sample = (
        Path(__file__).resolve().parents[1]
        / "samples"
        / "kingdom_of_lithuania.civ5project.json"
    )
    project_path = tmp_path / sample.name
    shutil.copy2(sample, project_path)
    build_path = tmp_path / "stale-build"
    build_path.mkdir()
    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(project_path)
    assert controller.project is not None
    project_id = controller.project.project_id
    revision = controller._project_revision

    window.pages[0].author.setText("Edited while build ran")  # type: ignore[attr-defined]
    assert controller._project_revision > revision
    controller._operation_finished(
        WorkflowResult(
            WorkflowMode.BUILD,
            "PASS",
            "Old build passed",
            (),
            build_path=build_path,
        ),
        project_id,
        revision,
    )

    assert controller.last_build_path is None
    assert window.advanced_page.test_generated_mod_root.text() != str(build_path)
    window.deleteLater()


def test_save_as_copies_imported_snapshot_before_adopting_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    _app()
    sample = (
        Path(__file__).resolve().parents[1]
        / "samples"
        / "kingdom_of_lithuania.civ5project.json"
    )
    project = deepcopy(load_project(sample))
    project.art.assets.clear()
    project.extensions["existing_mod_import"] = {"evidence": "test"}
    source = ProjectWorkspace.create(tmp_path / "Imported Source", project)
    destination_parent = tmp_path / "Save As Parent"
    destination_parent.mkdir()

    window = MainWindow()
    controller = ApplicationController(window)
    assert controller.open_path(source.project_path)
    opened_source = controller.workspace
    assert opened_source is not None
    calls: list[tuple[ProjectWorkspace, ProjectWorkspace]] = []

    def record_copy(_project, old_workspace, new_workspace):
        calls.append((old_workspace, new_workspace))
        assert controller.workspace is opened_source
        return None

    monkeypatch.setattr(controller_module, "copy_imported_snapshot", record_copy)
    monkeypatch.setattr(
        controller_module.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(destination_parent),
    )
    monkeypatch.setattr(
        controller_module.QMessageBox,
        "critical",
        lambda *_args: (_ for _ in ()).throw(AssertionError(str(_args[-1]))),
    )

    assert controller.save_project(True)
    assert len(calls) == 1
    assert calls[0][0] is opened_source
    assert calls[0][1] is controller.workspace
    assert controller.workspace is not opened_source
    window.deleteLater()
