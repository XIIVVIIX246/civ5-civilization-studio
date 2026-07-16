"""Beginner-facing, presentation-only guidance widgets.

These widgets explain the Studio workflow without reading or changing a
project.  They deliberately expose only Qt signals so the application shell
can decide what each action does.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, MUTED, SUCCESS


GUIDED_STEPS = (
    ("1. Start", "Name the mod and choose a safe gameplay style."),
    ("2. Your civilization", "Add its name, colors, cities, and story."),
    ("3. Your leader", "Introduce the leader and choose an AI personality."),
    ("4. Gameplay", "Choose a special ability and two unique replacements."),
    ("5. Artwork", "Add the pictures the game needs and check every preview."),
    ("6. Check and install", "Let Studio find problems, build the mod, and install it."),
)


class WelcomeCard(QFrame):
    """Friendly first-run choice card for the guided workflow."""

    startRequested = Signal()
    openRequested = Signal()
    exampleRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAccessibleName("Welcome to Civilization Studio")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(12)

        self.title_label = QLabel("Create your first Civilization V civilization")
        self.title_label.setStyleSheet("font-size: 17pt; font-weight: 750;")
        self.intro_label = QLabel(
            "Studio guides you from an idea to an installed Brave New World mod. "
            "You do not need to know XML, SQL, Lua, DDS, or Civ V database names."
        )
        self.intro_label.setWordWrap(True)
        self.intro_label.setStyleSheet(f"color: {MUTED}; font-size: 10.5pt;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.intro_label)

        steps_heading = QLabel("Your six-step path")
        steps_heading.setStyleSheet("font-size: 11.5pt; font-weight: 700;")
        self.steps_label = QLabel(
            "\n".join(f"{name} - {description}" for name, description in GUIDED_STEPS)
        )
        self.steps_label.setWordWrap(True)
        self.steps_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(steps_heading)
        layout.addWidget(self.steps_label)

        self.requirements_label = QLabel(
            "What you need: Civilization V with Brave New World on this Windows PC, "
            "an idea for a civilization, and PNG artwork before the final build. "
            "You can begin now and add unfinished details later."
        )
        self.requirements_label.setWordWrap(True)
        self.requirements_label.setStyleSheet(f"color: {SUCCESS};")
        layout.addWidget(self.requirements_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_button = QPushButton("Create my first civilization")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setAccessibleName("Start a guided civilization project")
        self.example_button = QPushButton("Try a worked example")
        self.example_button.setAccessibleName("Open a worked civilization example")
        self.open_button = QPushButton("Open an existing project")
        self.open_button.setAccessibleName("Open an existing Civilization Studio project")
        actions.addWidget(self.start_button)
        actions.addWidget(self.example_button)
        actions.addStretch(1)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)

        self.start_button.clicked.connect(self.startRequested)
        self.open_button.clicked.connect(self.openRequested)
        self.example_button.clicked.connect(self.exampleRequested)


class BeginnerGuideDialog(QDialog):
    """Offline walkthrough, glossary, and post-build checklist."""

    WALKTHROUGH_TEXT = "\n\n".join(
        f"{name}\n{description}"
        for name, description in (
            (
                "1. Start",
                "Give the mod a name and enter your name or screen name. Studio "
                "creates the technical identifiers for you.",
            ),
            (
                "2. Your civilization",
                "Choose the civilization's full name, short name, adjective, "
                "colors, city names, spy names, and introductory story.",
            ),
            (
                "3. Your leader",
                "Name the leader, optionally add a title and biography, then choose "
                "the simple personality that best matches how the AI should tend to play.",
            ),
            (
                "4. Gameplay",
                "Pick a special ability. Then create two unique units, buildings, or "
                "improvements by choosing the normal Civ V item each one replaces.",
            ),
            (
                "5. Artwork",
                "Choose the requested PNG pictures. Studio makes the Civ V image "
                "sizes and shows previews without adding a gold ring to your files.",
            ),
            (
                "6. Check and install",
                "Use Check and create my mod. Fix any Must fix items, build again, "
                "then install the finished mod into Civilization V.",
            ),
        )
    )

    GLOSSARY_TEXT = "\n\n".join(
        (
            "Brave New World (BNW)\nThe final Civilization V expansion. "
            "Studio builds for this version.",
            "Civilization\nThe playable nation or people you are creating.",
            "Leader\nThe person shown in setup, diplomacy, and the opening screen.",
            "Special ability (trait)\nThe civilization-wide gameplay bonus.",
            "Unique\nA special unit, building, or tile improvement available only "
            "to your civilization.",
            "Replaces / normal item\nThe standard Civ V item that your unique "
            "takes the place of. Studio uses it as a safe starting point.",
            "Dawn of Man\nThe introduction shown when a new game begins.",
            "Alpha emblem\nA simple white emblem on black used to create clean game icons.",
            "Unit flag\nThe small tactical symbol displayed above a unit on the map.",
            "MODS folder\nThe Civilization V folder where installed mods are placed. "
            "Studio can install there for you.",
            "Lua effect\nAn optional scripted gameplay effect. Beginners can skip "
            "these and add them later.",
        )
    )

    AFTER_BUILDING_TEXT = "\n".join(
        (
            "1. Install the validated build into Civilization V.",
            "2. Open Civilization V and choose MODS from the main menu.",
            "3. Enable your civilization and Brave New World, then start a new game.",
            "4. Confirm the civilization, leader, colors, artwork, ability, and uniques appear.",
            "5. Play several turns, test every unique, then save and reload the game.",
            "6. If something fails, exit the game and use Studio's log tools before rebuilding.",
            "",
            "Important: a successful Studio build proves that the files passed static checks. "
            "Only playing the exact installed mod proves that it works in Civilization V.",
        )
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Beginner Guide - Civ V Civilization Studio")
        self.setAccessibleName("Civilization Studio beginner guide")
        self.resize(780, 620)
        self.setMinimumSize(620, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        heading = QLabel("Make a custom civilization, one clear step at a time")
        heading.setStyleSheet("font-size: 16pt; font-weight: 750;")
        note = QLabel(
            "This guide stays inside Studio and uses player-friendly language. "
            "You can return to it whenever a Civ V term is unfamiliar."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(heading)
        layout.addWidget(note)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Beginner guide sections")
        walkthrough_tab, self.walkthrough_label = self._guide_tab(
            self.WALKTHROUGH_TEXT
        )
        glossary_tab, self.glossary_label = self._guide_tab(self.GLOSSARY_TEXT)
        after_building_tab, self.after_building_label = self._guide_tab(
            self.AFTER_BUILDING_TEXT, accent_last=True
        )
        self.tabs.addTab(walkthrough_tab, "Six-step walkthrough")
        self.tabs.addTab(glossary_tab, "Civ V words")
        self.tabs.addTab(after_building_tab, "After building")
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _guide_tab(
        text: str, *, accent_last: bool = False
    ) -> tuple[QScrollArea, QLabel]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 14, 16, 18)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if accent_last:
            label.setStyleSheet(f"color: {ACCENT};")
        content_layout.addWidget(label)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        return scroll, label


class PageCoach(QFrame):
    """Compact page-level explanation with a required/optional badge."""

    def __init__(
        self,
        title: str,
        body: str,
        *,
        required: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._required = bool(required)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(5)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(str(title))
        self.title_label.setStyleSheet("font-size: 11pt; font-weight: 700;")
        self.badge_label = QLabel()
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.setMinimumWidth(72)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.badge_label, 0)
        self.body_label = QLabel(str(body))
        self.body_label.setWordWrap(True)
        self.body_label.setStyleSheet(f"color: {MUTED};")
        layout.addLayout(header)
        layout.addWidget(self.body_label)
        self.set_required(required)
        self._update_accessible_name()

    @property
    def required(self) -> bool:
        return self._required

    def set_required(self, required: bool) -> None:
        self._required = bool(required)
        if self._required:
            self.badge_label.setText("REQUIRED")
            self.badge_label.setStyleSheet(
                f"color: #16191f; background: {ACCENT}; border-radius: 4px; "
                "font-size: 8pt; font-weight: 750; padding: 3px 7px;"
            )
        else:
            self.badge_label.setText("OPTIONAL")
            self.badge_label.setStyleSheet(
                f"color: {SUCCESS}; border: 1px solid {SUCCESS}; border-radius: 4px; "
                "font-size: 8pt; font-weight: 750; padding: 2px 6px;"
            )
        self._update_accessible_name()

    def set_content(self, title: str, body: str) -> None:
        self.title_label.setText(str(title))
        self.body_label.setText(str(body))
        self._update_accessible_name()

    def _update_accessible_name(self) -> None:
        kind = "required" if self._required else "optional"
        self.setAccessibleName(f"{self.title_label.text()} - {kind} guidance")


__all__ = [
    "BeginnerGuideDialog",
    "GUIDED_STEPS",
    "PageCoach",
    "WelcomeCard",
]
