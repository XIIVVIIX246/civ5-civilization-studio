from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from civ5studio.ui.art_studio import ArtStudioWidget
from civ5studio.ui.command_palette import CommandPalette, PaletteCommand
from civ5studio.ui.main_window import MainWindow
from civ5studio.ui.pages import ArtPage
from civ5studio.ui.theme import ACCENT, STYLE_SHEET


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_art_page_enforces_60_to_160_and_synchronizes_every_preview() -> None:
    _app()
    page = ArtPage()
    assert page.studio.zoom_range() == (60, 160)

    page.studio.set_transform(999, 12, -8, emit=True)
    assert page.studio.get_transform() == {
        "zoom": 160,
        "offset_x": 12,
        "offset_y": -8,
    }
    assert page.values()["civilization_icon"]["transform"]["zoom"] == 160
    assert all(
        preview.get_transform() == page.studio.get_transform()
        for preview in page.studio.previews.previews
    )

    page.studio.set_transform(-999, 0, 0, emit=True)
    assert page.studio.get_transform()["zoom"] == 60
    assert page.values()["civilization_icon"]["transform"]["zoom"] == 60
    assert all(
        preview.get_transform()["zoom"] == 60
        for preview in page.studio.previews.previews
    )
    page.deleteLater()


def test_range_change_clamps_existing_transform_and_emits_accepted_value() -> None:
    _app()
    studio = ArtStudioWidget()
    studio.set_transform(300, 3, 4)
    emissions: list[dict[str, int]] = []
    studio.transformChanged.connect(lambda value: emissions.append(dict(value)))

    studio.set_zoom_range(60, 160)

    assert studio.get_transform() == {"zoom": 160, "offset_x": 3, "offset_y": 4}
    assert emissions == [{"zoom": 160, "offset_x": 3, "offset_y": 4}]
    assert all(
        preview.get_transform() == studio.get_transform()
        for preview in studio.previews.previews
    )

    studio.set_transform(700, -5, 6)
    assert studio.get_transform() == {"zoom": 160, "offset_x": -5, "offset_y": 6}
    assert all(
        preview.get_transform() == studio.get_transform()
        for preview in studio.previews.previews
    )
    studio.deleteLater()


def test_command_palette_is_searchable_and_navigable_from_search_field() -> None:
    app = _app()
    invoked: list[str] = []
    commands = [
        PaletteCommand(
            "step.art", "Open Art Studio", "Workflow", lambda: invoked.append("art")
        ),
        PaletteCommand(
            "build.audit", "Audit draft", "Build", lambda: invoked.append("audit")
        ),
        PaletteCommand(
            "build.validate",
            "Validate release",
            "Build",
            lambda: invoked.append("validate"),
        ),
    ]
    palette = CommandPalette(commands)
    palette.show()
    app.processEvents()

    assert palette.search.hasFocus()
    assert palette.search.accessibleName() == "Command search"
    assert palette.results.accessibleName() == "Matching commands"
    assert palette.status.text() == "3 matching commands"
    assert " · " in palette.results.item(0).text()

    QTest.keyClick(palette.search, Qt.Key.Key_Down)
    assert palette.search.hasFocus()
    assert palette.results.currentRow() == 1
    QTest.keyClick(palette.search, Qt.Key.Key_Return)
    assert invoked == ["audit"]
    assert palette.result() == QDialog.DialogCode.Accepted
    palette.deleteLater()


def test_command_palette_token_filter_no_result_and_escape() -> None:
    app = _app()
    invoked: list[str] = []
    palette = CommandPalette(
        [
            PaletteCommand(
                "field.leader",
                "Edit leader name",
                "Field",
                lambda: invoked.append("leader"),
                "identity person",
            ),
            PaletteCommand(
                "field.civilization",
                "Edit civilization name",
                "Field",
                lambda: invoked.append("civilization"),
                "identity nation",
            ),
        ]
    )
    palette.show()
    app.processEvents()
    QTest.keyClicks(palette.search, "leader identity")
    assert palette.results.count() == 1
    assert palette.status.text() == "1 matching command"
    palette.search.selectAll()
    QTest.keyClicks(palette.search, "nothing matches")
    assert palette.results.count() == 0
    assert palette.status.text() == "0 matching commands"
    QTest.keyClick(palette.search, Qt.Key.Key_Return)
    assert invoked == []
    QTest.keyClick(palette.search, Qt.Key.Key_Escape)
    assert palette.result() == QDialog.DialogCode.Rejected
    palette.deleteLater()


def test_guided_expert_modes_shortcuts_and_accessible_navigation() -> None:
    _app()
    window = MainWindow()
    window.set_reference_catalog(
        civilizations=["CIVILIZATION_AMERICA"],
        unit_templates=[("UNITCLASS_WARRIOR", "UNIT_WARRIOR")],
        building_templates=[("BUILDINGCLASS_MONUMENT", "BUILDING_MONUMENT")],
        yields=["YIELD_CULTURE"],
    )
    project = window.pages[0]
    civilization = window.pages[1]
    uniques = window.pages[3].uniques

    assert window.mode_combo.currentText() == "Guided (recommended)"
    assert window.mode_combo.currentData() == "guided"
    assert project.technical_card.isHidden()
    assert civilization.base_civ.isHidden()
    assert uniques.table.isHidden()
    project.mod_name.setText("42nd People's Realm")
    assert project.prefix.text() == "CUSTOM_42ND_PEOPLE_S_REALM"

    window.mode_combo.setCurrentIndex(window.mode_combo.findData("expert"))
    assert not project.technical_card.isHidden()
    assert not civilization.base_civ.isHidden()
    assert not uniques.table.isHidden()
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("guided"))
    assert project.technical_card.isHidden()
    assert civilization.base_civ.isHidden()
    assert uniques.table.isHidden()

    assert window.palette_action.shortcut() == QKeySequence("Ctrl+K")
    assert [action.shortcut() for action in window.step_actions] == [
        QKeySequence("Alt+1"),
        QKeySequence("Alt+2"),
        QKeySequence("Alt+3"),
        QKeySequence("Alt+4"),
        QKeySequence(),
        QKeySequence("Alt+5"),
        QKeySequence(),
        QKeySequence(),
        QKeySequence("Alt+6"),
    ]
    assert window.steps.accessibleName() == "Project workflow steps"
    assert window.mode_combo.accessibleName() == "Editing mode"
    window.show()
    QApplication.processEvents()
    window.steps.setCurrentRow(0)
    QTest.keyClick(window, Qt.Key.Key_5, Qt.KeyboardModifier.AltModifier)
    assert window.steps.currentRow() == 5
    window.mark_clean()
    window.close()
    window.deleteLater()


def test_theme_has_visible_focus_for_text_lists_buttons_checks_and_sliders() -> None:
    assert "QListWidget:focus" in STYLE_SHEET
    assert "QPushButton:focus" in STYLE_SHEET
    assert "QCheckBox:focus" in STYLE_SHEET
    assert "QSlider:focus" in STYLE_SHEET
    assert f"border: 2px solid {ACCENT}" in STYLE_SHEET
