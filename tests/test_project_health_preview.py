from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from civ5studio.ui.civilization_preview import CivilizationPreview
from civ5studio.ui.main_window import MainWindow
from civ5studio.ui.pages import UniqueTable
from civ5studio.ui.project_health import (
    ProblemsPanel,
    humanize_location,
    indexed_location,
    step_for_location,
)
from civ5studio.ui.widgets import IssueTree


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png(path: Path, color: str) -> str:
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))
    return str(path)


def test_validation_locations_are_plain_language_without_losing_routes() -> None:
    assert humanize_location("units[0].combat") == "Unique unit 1 › Combat strength"
    assert humanize_location("colors.primary_red") == (
        "Civilization colors › Primary color - red channel"
    )
    assert humanize_location("lua_effects[1].effect_id") == (
        "Lua effect 2 › Effect choice"
    )
    assert humanize_location("") == "General project setting"


def test_problem_lists_use_friendly_priorities_and_single_click_routes() -> None:
    _app()
    issue = {
        "severity": "ERROR",
        "location": "units[0].combat",
        "message": "Combat must be a number.",
    }

    panel = ProblemsPanel()
    panel.set_issues([issue])
    child = panel.tree.topLevelItem(0).child(0)
    assert child.text(0) == "Must fix"
    assert child.text(1) == "Unique unit 1 › Combat strength"
    assert child.data(0, Qt.ItemDataRole.UserRole) == "units[0].combat"
    panel_routes: list[str] = []
    panel.issueActivated.connect(panel_routes.append)
    panel.tree.itemClicked.emit(child, 1)
    assert panel_routes == ["units[0].combat"]

    review = IssueTree()
    review.set_issues(
        [
            issue,
            {
                "severity": "WARNING",
                "location": "lua_effects[1].effect_id",
                "message": "Retest this pair in game.",
            },
            {
                "severity": "INFO",
                "location": "colors.primary_red",
                "message": "Color is stored as RGB.",
            },
        ]
    )
    assert [review.topLevelItem(row).text(0) for row in range(3)] == [
        "Must fix",
        "Suggestion",
        "Note",
    ]
    assert review.topLevelItem(1).text(1) == "Lua effect 2 › Effect choice"
    assert review.topLevelItem(1).data(0, Qt.ItemDataRole.UserRole) == (
        "lua_effects[1].effect_id"
    )
    review_routes: list[str] = []
    review.issueActivated.connect(review_routes.append)
    review.itemClicked.emit(review.topLevelItem(1), 1)
    assert review_routes == ["lua_effects[1].effect_id"]
    # Keyboard and double-click activation remain compatible.
    review.itemActivated.emit(review.topLevelItem(2), 1)
    assert review_routes[-1] == "colors.primary_red"

    panel.deleteLater()
    review.deleteLater()


def test_problem_locations_group_and_activate_the_exact_field() -> None:
    _app()
    assert step_for_location("units[2].combat") == 3
    assert step_for_location("units[2].promotions_expansion_pack[0]") == 4
    assert step_for_location("art.assets[0].source_png") == 5
    assert indexed_location("buildings[4].yield_changes[0].amount") == (
        "buildings",
        4,
        "yield_changes[0].amount",
    )

    panel = ProblemsPanel()
    panel.set_issues(
        [
            {"severity": "WARNING", "location": "art.assets[0]", "message": "Art"},
            {"severity": "ERROR", "location": "units[0].combat", "message": "Combat"},
        ]
    )
    activated: list[str] = []
    panel.issueActivated.connect(activated.append)
    panel._activate_first()
    assert activated == ["units[0].combat"]
    assert panel.tree.topLevelItemCount() == 2
    panel.deleteLater()


def test_step_health_and_indexed_mechanics_focus_route() -> None:
    _app()
    window = MainWindow()
    window.set_live_issues(
        [{"severity": "ERROR", "location": "units[0].combat", "message": "Invalid"}],
        "One error",
    )
    assert "1 fix" in window.steps.item(3).text()
    assert window.steps.item(3).data(Qt.ItemDataRole.UserRole) == (
        "1 item(s) must be fixed"
    )
    window.focus_location("units[0].combat")
    assert window.steps.currentRow() == 3
    assert (
        window.pages[3].uniques.unit_numbers["combat"].property("validationFocus")  # type: ignore[attr-defined]
        is True
    )
    window.deleteLater()


def test_missing_art_routes_to_the_exact_beginner_control() -> None:
    _app()
    window = MainWindow()
    editor = window.pages[3].uniques  # type: ignore[attr-defined]

    window.focus_location("leader.art.leader_scene")
    assert window.steps.currentRow() == 2
    assert window.pages[2].scene.property("validationFocus") is True  # type: ignore[attr-defined]

    window.focus_location("units[0].art.icon_source")
    assert window.steps.currentRow() == 3
    assert window.mode_combo.currentData() == "guided"
    assert editor.details_toggle.isChecked()
    assert editor.unit_icon.path_edit.property("validationFocus") is True

    window.focus_location("units[0].art.unit_flag_source")
    assert editor.unit_flag.path_edit.property("validationFocus") is True

    window.focus_location("buildings[0].art.icon_source")
    assert editor.building_icon.path_edit.property("validationFocus") is True

    window.focus_location("art.leader_portrait.source")
    assert window.steps.currentRow() == 5
    assert (
        window.pages[5].slots["leader_portrait"].property("validationFocus")  # type: ignore[attr-defined]
        is True
    )

    window.mark_clean()
    window.deleteLater()


def test_click_to_fix_routes_project_color_donor_and_pep_fields_exactly() -> None:
    _app()
    window = MainWindow()

    window.focus_location("options.affects_saved_games")
    assert window.pages[0].affects_saves.property("validationFocus") is True  # type: ignore[attr-defined]
    window.focus_location("colors.primary_red")
    assert window.pages[1].primary_color.swatch.property("validationFocus") is True  # type: ignore[attr-defined]

    window.focus_location("units[0].base_unit")
    editor = window.pages[3].uniques  # type: ignore[attr-defined]
    donor = editor.table.cellWidget(0, 3)
    assert window.mode_combo.currentText() == "Expert controls"
    assert window.mode_combo.currentData() == "expert"
    assert donor.property("validationFocus") is True
    window.focus_location("units[0].replaces_unit_class")
    replaces = editor.table.cellWidget(0, 2)
    assert replaces.property("validationFocus") is True

    pep = window.pages[4]
    pep.set_catalog(  # type: ignore[attr-defined]
        [{"type": "PROMOTION_TEST", "display_name": "Test", "help_text": "Help"}]
    )
    pep.set_units(editor.values())  # type: ignore[attr-defined]
    pep.enabled.setChecked(True)  # type: ignore[attr-defined]
    pep.add_assignment(  # type: ignore[attr-defined]
        {"unit_index": 0, "promotion_type": "PROMOTION_TEST"}
    )
    window.focus_location("units[0].promotions_expansion_pack[0]")
    promotion = pep.table.cellWidget(0, 1)  # type: ignore[attr-defined]
    assert window.steps.currentRow() == 4
    assert promotion.property("validationFocus") is True

    editor.selected_cards.setCurrentRow(0)
    editor.selected_key.setText("RENAMED_UNIT_ONE")
    first_rename = window.collect_values()
    assert first_rename["promotions_expansion_pack"]["assignments"][0][
        "unit_key"
    ] == "RENAMED_UNIT_ONE"
    editor.selected_key.setText("RENAMED_UNIT_TWO")
    second_rename = window.collect_values()
    assert second_rename["promotions_expansion_pack"]["assignments"][0][
        "unit_key"
    ] == "RENAMED_UNIT_TWO"
    window.deleteLater()


def test_mechanics_donor_browser_adds_filtered_verified_donor() -> None:
    _app()
    editor = UniqueTable()
    editor.set_reference_catalog(
        [("UNITCLASS_WARRIOR", "UNIT_WARRIOR")],
        [("BUILDINGCLASS_MONUMENT", "BUILDING_MONUMENT")],
        ["YIELD_FOOD"],
        improvement_templates=["IMPROVEMENT_FARM", "IMPROVEMENT_MINE"],
    )
    before = len(editor.values())
    editor.donor_kind.setCurrentText("Improvements")
    editor.donor_search.setText("mine")
    assert editor.donor_list.count() == 1
    editor.add_donor_button.click()
    rows = editor.values()
    assert len(rows) == before + 1
    assert rows[-1]["kind"] == "improvement"
    assert rows[-1]["base_template"] == "IMPROVEMENT_MINE"
    editor.deleteLater()


def test_dawn_preview_prefers_dedicated_dawn_art_with_leader_fallback(
    tmp_path: Path,
) -> None:
    _app()
    leader_scene = _png(tmp_path / "leader.png", "#cc0000")
    dawn_scene = _png(tmp_path / "dawn.png", "#0033cc")
    preview = CivilizationPreview()
    data = {
        "civilization": {"name": "Test", "dawn_of_man_quote": "Quote"},
        "leader": {"name": "Leader", "art": {"leader_scene": leader_scene}},
        "art": {"dawn_of_man": {"source": dawn_scene}},
    }
    preview.set_values(data)
    assert preview.dawn._scene.toImage().pixelColor(0, 0).name() == "#0033cc"

    data["art"]["dawn_of_man"]["source"] = ""
    preview.set_values(data)
    assert preview.dawn._scene.toImage().pixelColor(0, 0).name() == "#cc0000"
    preview.deleteLater()
