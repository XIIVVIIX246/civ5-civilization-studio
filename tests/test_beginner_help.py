from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from civ5studio.ui.beginner import (
    BeginnerGuideDialog,
    GUIDED_STEPS,
    PageCoach,
    WelcomeCard,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_welcome_card_explains_six_steps_and_emits_plain_actions() -> None:
    _app()
    card = WelcomeCard()
    requested: list[str] = []
    card.startRequested.connect(lambda: requested.append("start"))
    card.openRequested.connect(lambda: requested.append("open"))
    card.exampleRequested.connect(lambda: requested.append("example"))

    assert len(GUIDED_STEPS) == 6
    assert all(name in card.steps_label.text() for name, _description in GUIDED_STEPS)
    assert "Brave New World" in card.requirements_label.text()
    assert "XML" in card.intro_label.text()
    assert card.start_button.objectName() == "primaryButton"

    card.start_button.click()
    card.example_button.click()
    card.open_button.click()
    assert requested == ["start", "example", "open"]
    card.deleteLater()


def test_beginner_guide_has_walkthrough_glossary_and_truthful_test_checklist() -> None:
    _app()
    guide = BeginnerGuideDialog()

    assert guide.tabs.count() == 3
    assert [guide.tabs.tabText(index) for index in range(guide.tabs.count())] == [
        "Six-step walkthrough",
        "Civ V words",
        "After building",
    ]
    walkthrough = guide.walkthrough_label.text()
    assert all(f"{index}." in walkthrough for index in range(1, 7))
    glossary = guide.glossary_label.text()
    for term in ("Brave New World", "Unique", "Dawn of Man", "MODS folder"):
        assert term in glossary
    after = guide.after_building_label.text()
    assert "start a new game" in after
    assert "save and reload" in after
    assert "static checks" in after
    assert "Only playing" in after
    guide.deleteLater()


def test_page_coach_updates_content_and_required_optional_badge() -> None:
    _app()
    coach = PageCoach(
        "Choose your unique unit",
        "Pick the normal Civ V unit that yours will replace.",
        required=True,
    )
    assert coach.required is True
    assert coach.badge_label.text() == "REQUIRED"
    assert "required guidance" in coach.accessibleName()

    coach.set_required(False)
    coach.set_content("Extra music", "You can safely add this later.")
    assert coach.required is False
    assert coach.badge_label.text() == "OPTIONAL"
    assert coach.title_label.text() == "Extra music"
    assert coach.body_label.text() == "You can safely add this later."
    assert coach.accessibleName() == "Extra music - optional guidance"
    coach.deleteLater()
