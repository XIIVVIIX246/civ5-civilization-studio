from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from civ5studio.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _select_mode(window: MainWindow, mode: str) -> None:
    index = window.mode_combo.findData(mode)
    assert index >= 0
    window.mode_combo.setCurrentIndex(index)


def test_beginner_launch_is_quiet_and_shows_only_the_six_step_path() -> None:
    _app()
    window = MainWindow()

    assert window.mode_combo.currentData() == "guided"
    assert window.problems_dock.isHidden()
    assert window.preview_dock.isHidden()
    assert [
        index for index in range(window.steps.count()) if not window.steps.item(index).isHidden()
    ] == [0, 1, 2, 3, 5, 8]
    assert window.steps.item(5).text().startswith("5  Artwork")
    assert window.steps.item(8).text().startswith("6  Check, Build & Play")
    assert window.next_button.text() == "Continue: Your Civilization"

    window.mark_clean()
    window.deleteLater()


def test_guided_next_and_back_skip_optional_expert_pages() -> None:
    _app()
    window = MainWindow()

    window.steps.setCurrentRow(3)
    assert window.next_button.text() == "Continue: Artwork"
    window.next_button.click()
    assert window.steps.currentRow() == 5
    assert window.next_button.text() == "Continue: Check, Build and Play"
    window.next_button.click()
    assert window.steps.currentRow() == 8
    assert window.next_button.text() == "Guided steps complete"
    window.back_button.click()
    assert window.steps.currentRow() == 5

    window.mark_clean()
    window.deleteLater()


def test_loading_a_blank_new_project_returns_to_start_here() -> None:
    _app()
    window = MainWindow()
    blank = window.collect_values()
    window.steps.setCurrentRow(8)

    window.load_values(blank, None)

    assert window.steps.currentRow() == 0
    assert window.stack.currentIndex() == 0
    assert not window.pages[0].welcome.isHidden()  # type: ignore[attr-defined]
    window.mark_clean()
    window.deleteLater()


def test_worked_example_provides_a_complete_editable_starting_story() -> None:
    _app()
    window = MainWindow()

    window._load_worked_example()
    values = window.collect_values()

    assert values["project"]["mod_name"] == "River Kingdom Civilization"
    assert values["civilization"]["name"] == "The River Kingdom"
    assert len(values["civilization"]["city_names"]) >= 10
    assert values["leader"]["name"] == "Queen Mara"
    assert window.pages[2].personality.currentText() == "Diplomatic partner"  # type: ignore[attr-defined]
    assert values["mechanics"]["trait"]["name"] == "River Confederation"
    assert [row["name"] for row in values["mechanics"]["uniques"]] == [
        "River Guard",
        "Floodplain Shrine",
    ]
    assert window.steps.currentRow() == 1
    assert window.is_dirty
    assert window.pages[0].welcome.isHidden()  # type: ignore[attr-defined]

    window.mark_clean()
    window.deleteLater()


def test_expert_controls_reveal_technical_fields_without_changing_data() -> None:
    _app()
    window = MainWindow()
    project = window.pages[0]
    civilization = window.pages[1]
    uniques = window.pages[3].uniques

    project.mod_name.setText("Friendly Test Civilization")  # type: ignore[attr-defined]
    guided_values = window.collect_values()
    assert project.technical_card.isHidden()  # type: ignore[attr-defined]
    assert civilization.base_civ.isHidden()  # type: ignore[attr-defined]
    assert uniques.table.isHidden()  # type: ignore[attr-defined]

    _select_mode(window, "expert")
    assert not project.technical_card.isHidden()  # type: ignore[attr-defined]
    assert not civilization.base_civ.isHidden()  # type: ignore[attr-defined]
    assert not uniques.table.isHidden()  # type: ignore[attr-defined]
    assert all(not window.steps.item(index).isHidden() for index in range(9))
    assert window.collect_values() == guided_values

    _select_mode(window, "guided")
    assert window.collect_values() == guided_values
    window.mark_clean()
    window.deleteLater()


def test_review_page_presents_one_primary_build_path_in_guided_mode() -> None:
    _app()
    window = MainWindow()
    review = window.review_page

    assert review.build_button.text() == "Check and create my mod"
    assert review.build_button.objectName() == "primaryButton"
    assert review.install_button.text() == "Install into Civilization V"
    assert review.launch_button.text() == "Open Civilization V..."
    assert review.advanced_card.isHidden()

    _select_mode(window, "expert")
    assert not review.advanced_card.isHidden()
    window.mark_clean()
    window.deleteLater()
