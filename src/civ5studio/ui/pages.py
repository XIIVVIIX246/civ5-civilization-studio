"""Guided workflow pages.

Pages expose plain dictionaries and signals. They do not import build services
or write files, which keeps them testable and prevents accidental destructive
actions from UI event handlers.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QIntValidator, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import MUTED, SUCCESS, WARNING
from .art_studio import ArtStudioWidget
from .beginner import PageCoach, WelcomeCard
from .build_pipeline import BuildPipelineWidget
from .widgets import (
    AssetDropZone,
    ColorButton,
    IssueTree,
    LogPanel,
    SectionCard,
    StringListEditor,
)


def _text(widget: QLineEdit | QPlainTextEdit) -> str:
    return widget.text().strip() if isinstance(widget, QLineEdit) else widget.toPlainText().strip()


class WorkflowPage(QScrollArea):
    changed = Signal()

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.body = QVBoxLayout(self.container)
        self.body.setContentsMargins(28, 24, 28, 28)
        self.body.setSpacing(16)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 19pt; font-weight: 750;")
        summary = QLabel(subtitle)
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color: {MUTED}; font-size: 10.5pt;")
        self.body.addWidget(heading)
        self.body.addWidget(summary)
        self.setWidget(self.container)

    def finish(self) -> None:
        self.body.addStretch(1)

    def values(self) -> dict:
        return {}

    def load_values(self, _data: dict) -> None:
        return


class ProjectPage(WorkflowPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Start Here",
            "Begin with the name players will see. Studio handles the Civ V file structure and technical identifiers for you.",
            parent,
        )
        self.welcome = WelcomeCard()
        self.body.addWidget(self.welcome)
        self.coach = PageCoach(
            "Your first job: name the project",
            "Enter a mod name and your name or screen name. Everything else on this page can safely use its default for now.",
        )
        self.body.addWidget(self.coach)

        card = SectionCard(
            "Project name",
            "This is the name people will see in Civilization V's MODS menu.",
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.mod_name = QLineEdit()
        self.mod_name.setPlaceholderText("Example: The River Kingdom")
        self.mod_name.setAccessibleName("Mod name, required")
        self.author = QLineEdit()
        self.author.setPlaceholderText("Your name or screen name")
        self.author.setAccessibleName("Author name, required")
        form.addRow("Mod name *", self.mod_name)
        form.addRow("Created by *", self.author)
        card.body.addLayout(form)
        self.body.addWidget(card)

        self.technical_card = SectionCard(
            "Technical project details",
            "Expert controls for versioning, identifiers, save-game behavior, and the generated description.",
        )
        technical_form = QFormLayout()
        technical_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("LITHUANIA_CUSTOM")
        self.prefix.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Z][A-Z0-9_]{1,39}"), self))
        self.prefix.setToolTip("Uppercase letters, numbers, and underscores. Reserved Civ V prefixes are normalized during validation.")
        self.version = QSpinBox()
        self.version.setRange(1, 999)
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(95)
        self.description.setPlaceholderText(
            "Optional description shown in the Civilization V mod browser."
        )
        self.affects_saves = QCheckBox("Mark this mod as affecting saved games")
        self.affects_saves.setChecked(True)
        technical_form.addRow("Technical ID", self.prefix)
        technical_form.addRow("Mod version", self.version)
        technical_form.addRow("Mod-browser description", self.description)
        technical_form.addRow("", self.affects_saves)
        self.technical_card.body.addLayout(technical_form)
        self.body.addWidget(self.technical_card)

        self.output_card = SectionCard(
            "Advanced build location",
            "Studio normally uses this safe project-owned location automatically. Change it only when you have a specific reason.",
        )
        row = QHBoxLayout()
        self.output_dir = QLineEdit()
        self.output_dir.setText(str(Path.home() / "Documents" / "Civ5 Civilization Studio Projects"))
        choose = QPushButton("Choose folder")
        choose.clicked.connect(self._choose_output)
        row.addWidget(self.output_dir, 1)
        row.addWidget(choose)
        self.output_card.body.addLayout(row)
        self.body.addWidget(self.output_card)
        self.finish()

        for widget, signal in (
            (self.mod_name, self.mod_name.textChanged),
            (self.prefix, self.prefix.textChanged),
            (self.version, self.version.valueChanged),
            (self.author, self.author.textChanged),
            (self.description, self.description.textChanged),
            (self.affects_saves, self.affects_saves.toggled),
            (self.output_dir, self.output_dir.textChanged),
        ):
            signal.connect(self.changed)

        self.set_expert_mode(False)

    def set_expert_mode(self, expert: bool) -> None:
        self.technical_card.setVisible(bool(expert))
        self.output_card.setVisible(bool(expert))

    def _choose_output(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Choose project root", self.output_dir.text())
        if value:
            self.output_dir.setText(value)

    def values(self) -> dict:
        return {
            "mod_name": _text(self.mod_name),
            "prefix": _text(self.prefix),
            "version": self.version.value(),
            "author": _text(self.author),
            "description": _text(self.description),
            "affects_saved_games": self.affects_saves.isChecked(),
            "project_root": _text(self.output_dir),
        }

    def load_values(self, data: dict) -> None:
        self.mod_name.setText(str(data.get("mod_name", "")))
        self.prefix.setText(str(data.get("prefix", "")))
        self.version.setValue(int(data.get("version", 1) or 1))
        self.author.setText(str(data.get("author", "")))
        self.description.setPlainText(str(data.get("description", "")))
        self.affects_saves.setChecked(bool(data.get("affects_saved_games", True)))
        self.output_dir.setText(str(data.get("project_root", "")))


class CivilizationPage(WorkflowPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Your Civilization",
            "Give your civilization the words, colors, and names players will meet in Brave New World.",
            parent,
        )
        self.coach = PageCoach(
            "Name the people you want to play",
            "The full name appears in setup. The short name appears in tighter spaces, and the adjective describes its people and units.",
        )
        self.body.addWidget(self.coach)
        identity = SectionCard(
            "Civilization name",
            "Example: full name 'The River Kingdom', short name 'River Kingdom', adjective 'River'.",
        )
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("The River Kingdom")
        self.name.setAccessibleName("Civilization full name, required")
        self.short_name = QLineEdit()
        self.short_name.setPlaceholderText("River Kingdom")
        self.short_name.setAccessibleName("Civilization short name, required")
        self.adjective = QLineEdit()
        self.adjective.setPlaceholderText("River")
        self.adjective.setAccessibleName("Civilization adjective, required")
        self.base_civ = QComboBox()
        self.base_civ.setEditable(True)
        self.base_civ.addItems(["CIVILIZATION_AMERICA", "CIVILIZATION_ENGLAND", "CIVILIZATION_GERMANY", "CIVILIZATION_ROME"])
        self.base_civ_label = QLabel("Technical presentation donor")
        self.base_civ_label.setBuddy(self.base_civ)
        self.dom_quote = QPlainTextEdit()
        self.dom_quote.setMaximumHeight(82)
        self.dom_quote.setPlaceholderText(
            "A short welcome shown at the beginning of a new game."
        )
        self.civilopedia = QPlainTextEdit()
        self.civilopedia.setMaximumHeight(120)
        self.civilopedia.setPlaceholderText(
            "Optional history shown in the in-game Civilopedia."
        )
        form.addRow("Full name *", self.name)
        form.addRow("Short name *", self.short_name)
        form.addRow("Adjective *", self.adjective)
        form.addRow(self.base_civ_label, self.base_civ)
        identity.body.addLayout(form)
        self.body.addWidget(identity)

        colors = SectionCard(
            "Player colors",
            "Choose two colors with strong contrast so the map icon and unit flags remain easy to read.",
        )
        color_form = QFormLayout()
        self.primary_color = ColorButton("#8e2430")
        self.secondary_color = ColorButton("#e0bd5a")
        color_form.addRow("Icon color", self.primary_color)
        color_form.addRow("Background color", self.secondary_color)
        colors.body.addLayout(color_form)
        self.body.addWidget(colors)

        lists = SectionCard(
            "Cities and spies",
            "Enter one name per line. The first city becomes the capital. You can begin with a short list and add more later.",
        )
        grid = QGridLayout()
        city_label = QLabel("City names (16 recommended)")
        spy_label = QLabel("Spy names (10 recommended)")
        self.cities = StringListEditor("Vilnius\nKaunas\nTrakai", 16)
        self.spies = StringListEditor("Mindaugas\nBirute\nGediminas", 10)
        grid.addWidget(city_label, 0, 0)
        grid.addWidget(spy_label, 0, 1)
        grid.addWidget(self.cities, 1, 0)
        grid.addWidget(self.spies, 1, 1)
        lists.body.addLayout(grid)
        self.body.addWidget(lists)

        self.story_card = SectionCard(
            "Story and introduction",
            "These words add personality but do not change gameplay.",
        )
        story_form = QFormLayout()
        story_form.addRow("Intro-screen message", self.dom_quote)
        story_form.addRow("In-game history", self.civilopedia)
        self.story_card.body.addLayout(story_form)
        self.body.addWidget(self.story_card)
        self.finish()

        self._last_auto_short_name = ""

        for signal in (
            self.name.textChanged,
            self.short_name.textChanged,
            self.adjective.textChanged,
            self.base_civ.currentTextChanged,
            self.dom_quote.textChanged,
            self.civilopedia.textChanged,
            self.primary_color.colorChanged,
            self.secondary_color.colorChanged,
            self.cities.changed,
            self.spies.changed,
        ):
            signal.connect(self.changed)
        self.name.textChanged.connect(self._suggest_short_name)
        self.set_expert_mode(False)

    def _suggest_short_name(self, value: str) -> None:
        current = self.short_name.text().strip()
        if current and current != self._last_auto_short_name:
            return
        suggestion = value.strip()
        if suggestion.casefold().startswith("the "):
            suggestion = suggestion[4:].strip()
        self._last_auto_short_name = suggestion
        self.short_name.setText(suggestion)

    def set_expert_mode(self, expert: bool) -> None:
        self.base_civ_label.setVisible(bool(expert))
        self.base_civ.setVisible(bool(expert))

    def values(self) -> dict:
        return {
            "name": _text(self.name),
            "short_name": _text(self.short_name),
            "adjective": _text(self.adjective),
            "base_civilization": self.base_civ.currentText().strip(),
            "dawn_of_man_quote": _text(self.dom_quote),
            "civilopedia": _text(self.civilopedia),
            "colors": {"primary": self.primary_color.color, "secondary": self.secondary_color.color},
            "city_names": self.cities.values(),
            "spy_names": self.spies.values(),
        }

    def load_values(self, data: dict) -> None:
        self.name.setText(str(data.get("name", "")))
        self.short_name.setText(str(data.get("short_name", "")))
        self.adjective.setText(str(data.get("adjective", "")))
        self.base_civ.setCurrentText(str(data.get("base_civilization", "CIVILIZATION_AMERICA")))
        self.dom_quote.setPlainText(str(data.get("dawn_of_man_quote", "")))
        self.civilopedia.setPlainText(str(data.get("civilopedia", "")))
        colors = data.get("colors", {}) if isinstance(data.get("colors", {}), dict) else {}
        self.primary_color.set_color(str(colors.get("primary", "#8e2430")))
        self.secondary_color.set_color(str(colors.get("secondary", "#e0bd5a")))
        self.cities.set_values(data.get("city_names", []))
        self.spies.set_values(data.get("spy_names", []))


class LeaderPage(WorkflowPage):
    FLAVORS = ("Offense", "Defense", "Expansion", "Growth", "Science", "Culture", "Diplomacy", "Wonder")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Your Leader",
            "Introduce the person who represents the civilization and choose how the computer-controlled leader tends to play.",
            parent,
        )
        self.coach = PageCoach(
            "Create the face of your civilization",
            "Only the leader's name is required to begin. A title and biography add personality, and the final build will also need a leader scene.",
        )
        self.body.addWidget(self.coach)
        identity = SectionCard("Leader name and story")
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Queen Mara")
        self.name.setAccessibleName("Leader name, required")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Keeper of the Rivers")
        self.title.setAccessibleName("Optional leader title")
        self.civilopedia = QPlainTextEdit()
        self.civilopedia.setMaximumHeight(120)
        self.civilopedia.setPlaceholderText(
            "Optional biography shown in the Civilopedia."
        )
        form.addRow("Leader name *", self.name)
        form.addRow("Title (optional)", self.title)
        form.addRow("Biography", self.civilopedia)
        identity.body.addLayout(form)
        self.body.addWidget(identity)

        self.flavor_card = SectionCard(
            "Computer-player personality",
            "Choose a simple style. Expert mode lets you tune each preference from 1 to 10.",
        )
        personality_row = QHBoxLayout()
        personality_row.addWidget(QLabel("Play style"))
        self.personality = QComboBox()
        self.personality.addItems(
            [
                "Balanced (recommended)",
                "Peaceful builder",
                "Scientific planner",
                "Cultural visionary",
                "Diplomatic partner",
                "Wide expansionist",
                "Aggressive conqueror",
                "Custom expert values",
            ]
        )
        self.personality.setAccessibleName("Leader AI personality preset")
        personality_row.addWidget(self.personality, 1)
        self.flavor_card.body.addLayout(personality_row)
        self.personality_help = QLabel(
            "Balanced leaders value growth, defense, science, culture, and diplomacy evenly."
        )
        self.personality_help.setWordWrap(True)
        self.personality_help.setStyleSheet(f"color: {MUTED};")
        self.flavor_card.body.addWidget(self.personality_help)
        self.flavor_details = QWidget()
        grid = QGridLayout(self.flavor_details)
        grid.setContentsMargins(0, 4, 0, 0)
        self.flavors: dict[str, QSpinBox] = {}
        for index, flavor in enumerate(self.FLAVORS):
            label = QLabel(flavor)
            spin = QSpinBox()
            spin.setRange(1, 10)
            spin.setValue(5)
            spin.valueChanged.connect(self.changed)
            self.flavors[flavor.lower()] = spin
            grid.addWidget(label, index // 4, (index % 4) * 2)
            grid.addWidget(spin, index // 4, (index % 4) * 2 + 1)
        self.flavor_card.body.addWidget(self.flavor_details)
        self.body.addWidget(self.flavor_card)

        self.art_card = SectionCard(
            "Leader scene (needed for the final build)",
            "Choose a wide 16:9 PNG for diplomacy. Add the separate square leader portrait on the Artwork page. Studio never changes either original.",
        )
        row = QHBoxLayout()
        self.scene = AssetDropZone("leader_scene", "Leader scene (16:9)")
        # Preserve this hidden compatibility field so older project files
        # round-trip. New projects choose this portrait once on Artwork.
        self.fallback = AssetDropZone("leader_fallback", "Fallback portrait")
        row.addWidget(self.scene)
        self.art_card.body.addLayout(row)
        self.body.addWidget(self.art_card)
        self.finish()

        self._personality_presets: dict[str, dict[str, int]] = {
            "Balanced (recommended)": {},
            "Peaceful builder": {"offense": 2, "defense": 6, "growth": 8, "wonder": 7},
            "Scientific planner": {"science": 10, "growth": 8, "defense": 6, "offense": 3},
            "Cultural visionary": {"culture": 10, "wonder": 9, "growth": 7, "offense": 3},
            "Diplomatic partner": {"diplomacy": 10, "growth": 6, "defense": 6, "offense": 3},
            "Wide expansionist": {"expansion": 10, "growth": 7, "offense": 6, "wonder": 3},
            "Aggressive conqueror": {"offense": 10, "expansion": 8, "defense": 7, "diplomacy": 2},
        }
        self._personality_descriptions = {
            "Balanced (recommended)": "Balanced leaders value growth, defense, science, culture, and diplomacy evenly.",
            "Peaceful builder": "Prefers growth, defense, and Wonders over early wars.",
            "Scientific planner": "Prioritizes research, growth, and a defensible empire.",
            "Cultural visionary": "Chases culture and Wonders while avoiding unnecessary wars.",
            "Diplomatic partner": "Values alliances, trade, and friendly relations.",
            "Wide expansionist": "Settles many cities and competes strongly for open land.",
            "Aggressive conqueror": "Builds armies, expands by force, and distrusts rivals.",
            "Custom expert values": "This project uses individually tuned expert preferences.",
        }
        self.personality.currentTextChanged.connect(self._personality_changed)

        for signal in (
            self.name.textChanged,
            self.title.textChanged,
            self.civilopedia.textChanged,
            self.scene.pathChanged,
            self.fallback.pathChanged,
        ):
            signal.connect(self.changed)
        self.set_expert_mode(False)

    def _personality_changed(self, label: str) -> None:
        values = self._personality_presets.get(label)
        if values is not None:
            for key, spin in self.flavors.items():
                spin.setValue(int(values.get(key, 5)))
        self.personality_help.setText(
            self._personality_descriptions.get(label, "Choose a play style.")
        )

    def _matching_personality(self) -> str:
        current = {key: spin.value() for key, spin in self.flavors.items()}
        for label, overrides in self._personality_presets.items():
            expected = {key: int(overrides.get(key, 5)) for key in self.flavors}
            if current == expected:
                return label
        return "Custom expert values"

    def set_expert_mode(self, expert: bool) -> None:
        self.flavor_details.setVisible(bool(expert))

    def values(self) -> dict:
        return {
            "name": _text(self.name),
            "title": _text(self.title),
            "civilopedia": _text(self.civilopedia),
            "flavors": {key: spin.value() for key, spin in self.flavors.items()},
            "art": {"leader_scene": self.scene.path, "leader_fallback": self.fallback.path},
        }

    def load_values(self, data: dict) -> None:
        self.name.setText(str(data.get("name", "")))
        self.title.setText(str(data.get("title", "")))
        self.civilopedia.setPlainText(str(data.get("civilopedia", "")))
        flavors = data.get("flavors", {}) if isinstance(data.get("flavors", {}), dict) else {}
        for key, spin in self.flavors.items():
            spin.setValue(int(flavors.get(key, 5)))
        with QSignalBlocker(self.personality):
            self.personality.setCurrentText(self._matching_personality())
        self.personality_help.setText(
            self._personality_descriptions.get(
                self.personality.currentText(), "Choose a play style."
            )
        )
        art = data.get("art", {}) if isinstance(data.get("art", {}), dict) else {}
        self.scene.set_path(str(art.get("leader_scene", "")))
        self.fallback.set_path(str(art.get("leader_fallback", "")))


class SourcePathPicker(QWidget):
    """Compact per-subject source selector used by the unique editors."""

    changed = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(title)
        choose = QPushButton("Choose PNG")
        choose.clicked.connect(self._choose)
        self.path_edit.textChanged.connect(self.changed)
        row.addWidget(self.path_edit, 1)
        row.addWidget(choose)

    @property
    def path(self) -> str:
        return self.path_edit.text().strip()

    def set_path(self, value: str) -> None:
        self.path_edit.setText(value or "")

    def _choose(self) -> None:
        value, _ = QFileDialog.getOpenFileName(
            self, "Choose source art", self.path, "PNG images (*.png)"
        )
        if value:
            self.path_edit.setText(value)


class ReferenceListEditor(QWidget):
    """Repeatable verified Type picker for promotions and similar references."""

    changed = Signal()

    def __init__(
        self, references: list[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.references = list(references)
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["Verified Type"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(125)
        buttons = QHBoxLayout()
        add = QPushButton("Add promotion")
        remove = QPushButton("Remove selected")
        add.clicked.connect(lambda: self.add_row())
        remove.clicked.connect(self._remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def add_row(self, value: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(self.references)
        if value and combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value or (self.references[0] if self.references else ""))
        combo.currentTextChanged.connect(self._changed)
        self.table.setCellWidget(row, 0, combo)
        self._changed()

    def _remove(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def _changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def values(self) -> list[str]:
        result: list[str] = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            if isinstance(combo, QComboBox) and combo.currentText().strip():
                result.append(combo.currentText().strip())
        return result

    def set_values(self, values: list[str]) -> None:
        self._loading = True
        try:
            self.table.setRowCount(0)
            for value in values:
                self.add_row(str(value))
        finally:
            self._loading = False

    def set_references(self, references: list[str]) -> None:
        current = self.values()
        self.references = list(references)
        self.set_values(current)


class ReferenceAmountEditor(QWidget):
    """Structured reference/amount rows; invalid free-form lines cannot disappear."""

    changed = Signal()

    def __init__(
        self,
        key_name: str,
        references: list[str],
        *,
        minimum: int,
        maximum: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key_name = key_name
        self.references = list(references)
        self.minimum = minimum
        self.maximum = maximum
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Verified Type", "Amount"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMaximumHeight(145)
        buttons = QHBoxLayout()
        add = QPushButton("Add row")
        remove = QPushButton("Remove selected")
        add.clicked.connect(lambda: self.add_row())
        remove.clicked.connect(self._remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def add_row(self, value: dict | None = None) -> None:
        value = value or {}
        row = self.table.rowCount()
        self.table.insertRow(row)
        reference = str(value.get(self.key_name, ""))
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(self.references)
        if reference and combo.findText(reference) < 0:
            combo.addItem(reference)
        combo.setCurrentText(reference or (self.references[0] if self.references else ""))
        amount = QSpinBox()
        amount.setRange(self.minimum, self.maximum)
        amount.setValue(int(value.get("amount", 0) or 0))
        combo.currentTextChanged.connect(self._changed)
        amount.valueChanged.connect(self._changed)
        self.table.setCellWidget(row, 0, combo)
        self.table.setCellWidget(row, 1, amount)
        self._changed()

    def _remove(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if rows:
            self._changed()

    def _changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def values(self) -> list[dict[str, int | str]]:
        result: list[dict[str, int | str]] = []
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 0)
            amount = self.table.cellWidget(row, 1)
            if isinstance(combo, QComboBox) and isinstance(amount, QSpinBox):
                result.append(
                    {self.key_name: combo.currentText().strip(), "amount": amount.value()}
                )
        return result

    def set_values(self, values: list[dict]) -> None:
        self._loading = True
        try:
            self.table.setRowCount(0)
            for value in values:
                self.add_row(value)
        finally:
            self._loading = False

    def set_references(self, references: list[str]) -> None:
        current = self.values()
        self.references = list(references)
        self.set_values(current)


class UniqueTable(QWidget):
    """Master/detail editors for every compiler-supported unique field."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit_templates = [("UNITCLASS_SWORDSMAN", "UNIT_SWORDSMAN")]
        self._building_templates = [("BUILDINGCLASS_MONUMENT", "BUILDING_MONUMENT")]
        self._improvement_templates = ["IMPROVEMENT_FARM"]
        self._yields = [
            "YIELD_FOOD", "YIELD_PRODUCTION", "YIELD_GOLD", "YIELD_SCIENCE",
            "YIELD_CULTURE", "YIELD_FAITH",
        ]
        self._domains = ["DOMAIN_LAND", "DOMAIN_SEA", "DOMAIN_AIR"]
        self._technologies: list[str] = []
        self._promotions: list[str] = []
        self._rows: list[dict] = []
        self._active_row = -1
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        workspace.setChildrenCollapsible(False)
        workspace.setMinimumHeight(245)

        donor_panel = QWidget()
        donor_layout = QVBoxLayout(donor_panel)
        donor_layout.setContentsMargins(0, 0, 8, 0)
        donor_title = QLabel("1. Choose a normal Civ V item to start from")
        donor_title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        donor_filters = QHBoxLayout()
        self.donor_search = QLineEdit()
        self.donor_search.setPlaceholderText("Search Swordsman, Monument, Farm...")
        self.donor_kind = QComboBox()
        self.donor_kind.addItems(["All types", "Units", "Buildings", "Improvements"])
        donor_filters.addWidget(self.donor_search, 1)
        donor_filters.addWidget(self.donor_kind)
        self.donor_list = QListWidget()
        self.donor_list.setAccessibleName("Verified BNW donor catalog")
        self.donor_list.setAlternatingRowColors(True)
        self.add_donor_button = QPushButton("Use this as a unique")
        self.add_donor_button.setObjectName("primaryButton")
        donor_layout.addWidget(donor_title)
        donor_layout.addLayout(donor_filters)
        donor_layout.addWidget(self.donor_list, 1)
        donor_layout.addWidget(self.add_donor_button)

        selected_panel = QWidget()
        selected_layout = QVBoxLayout(selected_panel)
        selected_layout.setContentsMargins(8, 0, 0, 0)
        selected_title = QLabel("2. Your civilization's unique items")
        selected_title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        selected_help = QLabel(
            "Choose a card to name it, add its required artwork, or make optional "
            "gameplay changes. Normal stats stay in place until you change a value."
        )
        selected_help.setWordWrap(True)
        selected_help.setStyleSheet(f"color: {MUTED};")
        self.selected_cards = QListWidget()
        self.selected_cards.setAccessibleName("Selected unique components")
        self.selected_cards.setAlternatingRowColors(True)
        selected_layout.addWidget(selected_title)
        selected_layout.addWidget(selected_help)
        selected_layout.addWidget(self.selected_cards, 1)

        workspace.addWidget(donor_panel)
        workspace.addWidget(selected_panel)
        workspace.setSizes([430, 430])
        layout.addWidget(workspace)

        self.expert_table_label = QLabel("Expert donor matrix")
        self.expert_table_label.setStyleSheet(
            f"color: {MUTED}; font-weight: 650; margin-top: 6px;"
        )
        layout.addWidget(self.expert_table_label)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Kind", "Display name", "Replaces class", "Vanilla donor"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(225)
        self.table.itemChanged.connect(self._item_changed)
        self.table.currentCellChanged.connect(self._selection_changed)
        layout.addWidget(self.table)

        self.donor_search.textChanged.connect(self._refresh_donor_browser)
        self.donor_kind.currentTextChanged.connect(self._refresh_donor_browser)
        self.donor_list.itemDoubleClicked.connect(
            lambda _item: self._add_selected_donor()
        )
        self.add_donor_button.clicked.connect(self._add_selected_donor)
        self.selected_cards.currentRowChanged.connect(self._card_selected)

        buttons = QHBoxLayout()
        add_unit = QPushButton("Add a unit")
        add_building = QPushButton("Add a building")
        add_improvement = QPushButton("Add an improvement")
        remove = QPushButton("Remove selected")
        add_unit.clicked.connect(lambda: self.add_row("unit"))
        add_building.clicked.connect(lambda: self.add_row("building"))
        add_improvement.clicked.connect(lambda: self.add_row("improvement"))
        remove.clicked.connect(self._remove)
        buttons.addWidget(add_unit)
        buttons.addWidget(add_building)
        buttons.addWidget(add_improvement)
        buttons.addStretch(1)
        buttons.addWidget(remove)
        layout.addLayout(buttons)

        detail_title = QLabel("3. Name and customize the selected unique")
        detail_title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        layout.addWidget(detail_title)
        self.beginner_summary = QLabel(
            "Choose one of your unique items above. Give every unique its own name. "
            "Before the final build, use the button below to add its required portrait "
            "and, for a unit, its white-on-black unit flag."
        )
        self.beginner_summary.setWordWrap(True)
        self.beginner_summary.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.beginner_summary)

        self.common_container = QWidget()
        common = QFormLayout(self.common_container)
        common.setContentsMargins(0, 0, 0, 0)
        self.key_label = QLabel("Internal key (Expert)")
        self.selected_key = QLineEdit()
        self.selected_key.setPlaceholderText("Stable key used to generate the BNW Type")
        self.selected_key.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"[A-Z][A-Z0-9_]{0,47}"), self.selected_key
            )
        )
        self.selected_key.setToolTip(
            "Uppercase letters, numbers, and underscores; 48 characters maximum. "
            "Changing this stable key changes the generated Civ V Type."
        )
        self.key_label.setBuddy(self.selected_key)
        self.selected_name = QLineEdit()
        self.selected_name.setPlaceholderText("Display name shown in Civilopedia")
        self.help_text = QPlainTextEdit()
        self.help_text.setMaximumHeight(70)
        self.help_text.setPlaceholderText(
            "What players should understand about this unique."
        )
        self.strategy_text = QPlainTextEdit()
        self.strategy_text.setMaximumHeight(70)
        self.prereq_tech = QComboBox()
        self.prereq_tech.setEditable(True)
        common.addRow(self.key_label, self.selected_key)
        common.addRow("Unique name *", self.selected_name)
        common.addRow("What players see", self.help_text)
        layout.addWidget(self.common_container)

        self.expert_common = QWidget()
        expert_common_form = QFormLayout(self.expert_common)
        expert_common_form.setContentsMargins(0, 0, 0, 0)
        expert_common_form.addRow("How players should use it", self.strategy_text)
        expert_common_form.addRow(
            "Unlocked after researching (blank = same as normal item)",
            self.prereq_tech,
        )

        self.detail_stack = QStackedWidget()
        self.unit_panel = QWidget()
        unit_layout = QVBoxLayout(self.unit_panel)
        unit_layout.setContentsMargins(0, 0, 0, 0)
        unit_stats = QGridLayout()
        self.unit_numbers: dict[str, QLineEdit] = {}
        for index, (field, label) in enumerate((
            ("combat", "Combat"), ("ranged_combat", "Ranged combat"),
            ("moves", "Moves"), ("cost", "Cost"),
        )):
            edit = QLineEdit()
            edit.setValidator(QIntValidator(0 if field != "moves" else 1, 100000, edit))
            edit.setPlaceholderText("Same as the normal unit")
            self.unit_numbers[field] = edit
            unit_stats.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            unit_stats.addWidget(edit, index // 2, (index % 2) * 2 + 1)
        unit_layout.addLayout(unit_stats)
        self.promotions = ReferenceListEditor(self._promotions)
        unit_layout.addWidget(QLabel("Free promotions"))
        unit_layout.addWidget(self.promotions)
        unit_art = QFormLayout()
        self.unit_icon = SourcePathPicker("Unique unit portrait PNG")
        self.unit_flag = SourcePathPicker("White-on-black unit flag PNG")
        self.strategic_view = SourcePathPicker("Optional Strategic View PNG")
        unit_art.addRow("Portrait source", self.unit_icon)
        unit_art.addRow("Unit flag source", self.unit_flag)
        unit_art.addRow("Strategic View source", self.strategic_view)
        unit_layout.addLayout(unit_art)

        self.building_panel = QWidget()
        building_layout = QVBoxLayout(self.building_panel)
        building_layout.setContentsMargins(0, 0, 0, 0)
        building_stats = QGridLayout()
        self.building_numbers: dict[str, QLineEdit] = {}
        for index, (field, label) in enumerate((
            ("cost", "Cost"), ("gold_maintenance", "Gold maintenance"),
            ("defense", "Defense"),
            ("extra_city_hit_points", "Extra city hit points"),
        )):
            edit = QLineEdit()
            edit.setValidator(QIntValidator(0, 100000, edit))
            edit.setPlaceholderText("Same as the normal building")
            self.building_numbers[field] = edit
            building_stats.addWidget(QLabel(label), index // 2, (index % 2) * 2)
            building_stats.addWidget(edit, index // 2, (index % 2) * 2 + 1)
        building_layout.addLayout(building_stats)
        changes = QGridLayout()
        self.yield_changes = ReferenceAmountEditor(
            "yield_type", self._yields, minimum=-10000, maximum=100000
        )
        self.domain_experience = ReferenceAmountEditor(
            "domain_type", self._domains, minimum=0, maximum=1000
        )
        changes.addWidget(QLabel("Yield changes"), 0, 0)
        changes.addWidget(QLabel("Free experience by domain"), 0, 1)
        changes.addWidget(self.yield_changes, 1, 0)
        changes.addWidget(self.domain_experience, 1, 1)
        building_layout.addLayout(changes)
        building_art = QFormLayout()
        self.building_icon = SourcePathPicker("Unique building portrait PNG")
        building_art.addRow("Portrait source", self.building_icon)
        building_layout.addLayout(building_art)

        self.improvement_panel = QWidget()
        improvement_layout = QVBoxLayout(self.improvement_panel)
        improvement_layout.setContentsMargins(0, 0, 0, 0)
        improvement_form = QFormLayout()
        self.improvement_civilopedia = QPlainTextEdit()
        self.improvement_civilopedia.setMaximumHeight(70)
        self.improvement_civilopedia.setPlaceholderText(
            "Civilopedia entry (blank uses the help text)"
        )
        improvement_form.addRow("Civilopedia text", self.improvement_civilopedia)
        improvement_layout.addLayout(improvement_form)
        self.improvement_yield_changes = ReferenceAmountEditor(
            "yield_type", self._yields, minimum=-10000, maximum=100000
        )
        improvement_layout.addWidget(QLabel("Yield changes added to donor yields"))
        improvement_layout.addWidget(self.improvement_yield_changes)
        improvement_art = QFormLayout()
        self.improvement_icon = SourcePathPicker("Unique improvement portrait PNG")
        improvement_art.addRow("Portrait source", self.improvement_icon)
        improvement_layout.addLayout(improvement_art)

        self.detail_stack.addWidget(self.unit_panel)
        self.detail_stack.addWidget(self.building_panel)
        self.detail_stack.addWidget(self.improvement_panel)
        self.details_toggle = QPushButton("Add required artwork or change optional stats")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setAccessibleName(
            "Show or hide required unique artwork and optional stat changes"
        )
        self.details_toggle.toggled.connect(self._update_detail_visibility)
        layout.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.optional_details = QWidget()
        optional_layout = QVBoxLayout(self.optional_details)
        optional_layout.setContentsMargins(0, 0, 0, 0)
        optional_layout.addWidget(self.expert_common)
        optional_layout.addWidget(self.detail_stack)
        layout.addWidget(self.optional_details)
        for signal in (
            self.selected_key.textChanged, self.selected_name.textChanged,
            self.help_text.textChanged, self.strategy_text.textChanged,
            self.prereq_tech.currentTextChanged, self.promotions.changed,
            self.yield_changes.changed, self.domain_experience.changed,
            self.unit_icon.changed, self.unit_flag.changed, self.strategic_view.changed,
            self.building_icon.changed,
            self.improvement_civilopedia.textChanged,
            self.improvement_yield_changes.changed,
            self.improvement_icon.changed,
            *(edit.textChanged for edit in self.unit_numbers.values()),
            *(edit.textChanged for edit in self.building_numbers.values()),
        ):
            signal.connect(self._detail_changed)
        self._refresh_donor_browser()
        self.set_expert_mode(False)

    def _update_detail_visibility(self, *_args) -> None:
        self.optional_details.setVisible(
            bool(getattr(self, "_expert_mode", False))
            or self.details_toggle.isChecked()
        )

    @staticmethod
    def _humanize_type(value: str) -> str:
        text = str(value or "").strip()
        for prefix in (
            "UNITCLASS_",
            "BUILDINGCLASS_",
            "IMPROVEMENT_",
            "UNIT_",
            "BUILDING_",
        ):
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
        return text.replace("_", " ").title() or "Unnamed donor"

    def _refresh_donor_browser(self, *_args) -> None:
        query = self.donor_search.text().strip().casefold()
        kind_filter = self.donor_kind.currentText()
        entries: list[dict[str, str]] = []
        if kind_filter in {"All types", "Units"}:
            entries.extend(
                {
                    "kind": "unit",
                    "class": class_name,
                    "donor": donor,
                    "label": self._humanize_type(donor),
                }
                for class_name, donor in self._unit_templates
            )
        if kind_filter in {"All types", "Buildings"}:
            entries.extend(
                {
                    "kind": "building",
                    "class": class_name,
                    "donor": donor,
                    "label": self._humanize_type(donor),
                }
                for class_name, donor in self._building_templates
            )
        if kind_filter in {"All types", "Improvements"}:
            entries.extend(
                {
                    "kind": "improvement",
                    "class": "",
                    "donor": donor,
                    "label": self._humanize_type(donor),
                }
                for donor in self._improvement_templates
            )
        selected = self.donor_list.currentItem()
        selected_donor = (
            str(selected.data(Qt.ItemDataRole.UserRole).get("donor", ""))
            if selected is not None
            and isinstance(selected.data(Qt.ItemDataRole.UserRole), dict)
            else ""
        )
        with QSignalBlocker(self.donor_list):
            self.donor_list.clear()
            selected_row = -1
            for entry in entries:
                haystack = " ".join(entry.values()).casefold()
                if query and not all(token in haystack for token in query.split()):
                    continue
                kind_label = entry["kind"].title()
                item = QListWidgetItem(
                    f"{entry['label']}\n{kind_label} · replaces {self._humanize_type(entry['class']) if entry['class'] else 'civilization-specific'}"
                )
                item.setData(Qt.ItemDataRole.UserRole, dict(entry))
                item.setToolTip(
                    f"Donor: {entry['donor']}\nClass: {entry['class'] or 'none'}"
                )
                self.donor_list.addItem(item)
                if entry["donor"] == selected_donor:
                    selected_row = self.donor_list.count() - 1
            if self.donor_list.count():
                self.donor_list.setCurrentRow(max(0, selected_row))
        self.add_donor_button.setEnabled(self.donor_list.count() > 0)

    def _add_selected_donor(self) -> None:
        item = self.donor_list.currentItem()
        entry = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(entry, dict):
            return
        self.add_row(
            str(entry.get("kind", "unit")),
            {
                "replaces_class": str(entry.get("class", "")),
                "base_template": str(entry.get("donor", "")),
            },
        )

    def _refresh_selected_cards(self) -> None:
        current = self._active_row
        with QSignalBlocker(self.selected_cards):
            self.selected_cards.clear()
            for row in self._rows:
                custom_name = str(row.get("name", "")).strip()
                name = custom_name or self._humanize_type(
                    str(row.get("base_template", ""))
                )
                donor = self._humanize_type(str(row.get("base_template", "")))
                kind = str(row.get("kind", "unique")).title()
                status = (
                    f"{kind} based on {donor}"
                    if custom_name
                    else f"{kind} based on {donor} - needs a unique name"
                )
                item = QListWidgetItem(f"{name}\n{status}")
                item.setToolTip(
                    f"{row.get('base_template', '')}\n"
                    "All blank stats inherit from this verified donor."
                )
                self.selected_cards.addItem(item)
            if 0 <= current < self.selected_cards.count():
                self.selected_cards.setCurrentRow(current)

    def _card_selected(self, row: int) -> None:
        if self._loading or row < 0 or row >= self.table.rowCount():
            return
        self.table.setCurrentCell(row, 1)

    def set_expert_mode(self, expert: bool) -> None:
        self._expert_mode = bool(expert)
        self.expert_table_label.setVisible(bool(expert))
        self.table.setVisible(bool(expert))
        self.key_label.setVisible(bool(expert))
        self.selected_key.setVisible(bool(expert))
        self.details_toggle.setVisible(not expert)
        self._update_detail_visibility()

    def focus_location(
        self, collection: str, collection_index: int, field: str
    ) -> QWidget | None:
        kind = {
            "units": "unit",
            "buildings": "building",
            "improvements": "improvement",
        }.get(collection, "")
        matches = [
            row for row, data in enumerate(self._rows) if data.get("kind") == kind
        ]
        if not 0 <= collection_index < len(matches):
            return self.selected_cards
        row = matches[collection_index]
        self.selected_cards.setCurrentRow(row)
        self.table.setCurrentCell(row, 1)
        common = {
            "key": self.selected_key,
            "name": self.selected_name,
            "help_text": self.help_text,
            "strategy_text": self.strategy_text,
            "prereq_tech": self.prereq_tech,
            "build_prereq_tech": self.prereq_tech,
        }
        if field in common:
            return common[field]
        self.details_toggle.setChecked(True)
        self._update_detail_visibility()
        if field in {
            "replaces_class",
            "replaces_unit_class",
            "replaces_building_class",
        }:
            return self.table.cellWidget(row, 2)
        if field in {
            "base_template",
            "base_unit",
            "base_building",
            "base_improvement",
        }:
            return self.table.cellWidget(row, 3)
        if kind == "unit":
            if field in {"art.icon_source", "icon_source"}:
                return self.unit_icon.path_edit
            if field in {"art.unit_flag_source", "unit_flag_source"}:
                return self.unit_flag.path_edit
            if field in {"art.strategic_view_source", "strategic_view_source"}:
                return self.strategic_view.path_edit
            return self.unit_numbers.get(field, self.promotions)
        if kind == "building":
            if field in {"art.icon_source", "icon_source"}:
                return self.building_icon.path_edit
            return self.building_numbers.get(field, self.yield_changes)
        if kind == "improvement":
            if field in {"art.icon_source", "icon_source"}:
                return self.improvement_icon.path_edit
            return (
                self.improvement_civilopedia
                if field == "civilopedia_text"
                else self.improvement_yield_changes
            )
        return self.selected_cards

    def add_row(self, kind: str, values: dict | None = None) -> None:
        kind = kind if kind in {"unit", "building", "improvement"} else "unit"
        data = self._normalize_row(kind, values or {})
        row = self.table.rowCount()
        self._loading = True
        try:
            self._rows.append(data)
            self.table.insertRow(row)
            kind_item = QTableWidgetItem(kind)
            kind_item.setFlags(kind_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, kind_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(data.get("name", ""))))
            if kind == "unit":
                templates = self._unit_templates
            elif kind == "building":
                templates = self._building_templates
            else:
                templates = [("", value) for value in self._improvement_templates]
            class_combo = QComboBox()
            class_combo.addItems(
                ["Civilization-specific"]
                if kind == "improvement"
                else [item[0] for item in templates]
            )
            class_name = str(data.get("replaces_class", ""))
            if kind != "improvement" and class_name and class_combo.findText(class_name) < 0:
                class_combo.addItem(class_name)
            if kind != "improvement":
                class_combo.setCurrentText(class_name)
            else:
                class_combo.setEnabled(False)
            donor_combo = QComboBox()
            donor_combo.addItems([item[1] for item in templates])
            donor = str(data.get("base_template", ""))
            if donor and donor_combo.findText(donor) < 0:
                donor_combo.addItem(donor)
            donor_combo.setCurrentText(donor)
            class_combo.currentTextChanged.connect(
                lambda text, widget=class_combo: self._class_changed(widget, text)
            )
            donor_combo.currentTextChanged.connect(
                lambda text, widget=donor_combo: self._combo_changed(
                    widget, "base_template", text
                )
            )
            self.table.setCellWidget(row, 2, class_combo)
            self.table.setCellWidget(row, 3, donor_combo)
        finally:
            self._loading = False
        self.table.setCurrentCell(row, 1)
        self._refresh_selected_cards()
        self.changed.emit()

    def _normalize_row(self, kind: str, values: dict) -> dict:
        result = deepcopy(values)
        if kind == "unit":
            templates = self._unit_templates
        elif kind == "building":
            templates = self._building_templates
        else:
            templates = [("", value) for value in self._improvement_templates]
        fallback_class, fallback_donor = templates[0] if templates else ("", "")
        result.update(
            kind=kind,
            name=str(result.get("name", "")),
            replaces_class=str(result.get("replaces_class", fallback_class)),
            base_template=str(result.get("base_template", fallback_donor)),
            help_text=str(result.get("help_text", result.get("effect_summary", ""))),
            strategy_text=str(result.get("strategy_text", result.get("help_text", ""))),
            prereq_tech=str(result.get("prereq_tech", "") or ""),
        )
        if kind == "unit":
            for field in ("combat", "ranged_combat", "moves", "cost"):
                result.setdefault(field, None)
            result["free_promotions"] = list(result.get("free_promotions", []))
            if not any(result.get(field) is not None for field in self.unit_numbers):
                legacy = str(result.get("override", ""))
                if legacy in {"Combat", "RangedCombat", "Moves", "Cost"}:
                    result[{"Combat": "combat", "RangedCombat": "ranged_combat",
                            "Moves": "moves", "Cost": "cost"}[legacy]] = self._maybe_int(
                        result.get("value")
                    )
            result.setdefault("override", "Combat")
        elif kind == "building":
            for field in ("cost", "gold_maintenance", "defense", "extra_city_hit_points"):
                result.setdefault(field, None)
            result["yield_changes"] = list(result.get("yield_changes", []))
            result["domain_free_experience"] = list(
                result.get("domain_free_experience", [])
            )
            if not any(result.get(field) is not None for field in self.building_numbers):
                legacy = str(result.get("override", ""))
                amount = self._maybe_int(result.get("value"))
                mapping = {
                    "Cost": "cost", "GoldMaintenance": "gold_maintenance",
                    "Defense": "defense", "ExtraCityHitPoints": "extra_city_hit_points",
                }
                if legacy in mapping:
                    result[mapping[legacy]] = amount
                elif legacy.startswith("Yield:") and amount is not None:
                    result["yield_changes"] = [
                        {"yield_type": legacy.partition(":")[2], "amount": amount}
                    ]
            result.setdefault("override", "Yield:YIELD_CULTURE")
        else:
            result["replaces_class"] = ""
            result["civilopedia_text"] = str(result.get("civilopedia_text", ""))
            result["yield_changes"] = list(result.get("yield_changes", []))
            result.setdefault("override", "Yield:YIELD_PRODUCTION")
        result["art"] = deepcopy(result.get("art", {})) if isinstance(result.get("art"), dict) else {}
        return result

    def _selection_changed(self, current_row: int, _column: int, *_args) -> None:
        if self._loading:
            return
        self._active_row = current_row
        with QSignalBlocker(self.selected_cards):
            self.selected_cards.setCurrentRow(current_row)
        self._load_detail(current_row)

    def _load_detail(self, row: int) -> None:
        self._loading = True
        try:
            enabled = 0 <= row < len(self._rows)
            self.detail_stack.setEnabled(enabled)
            if not enabled:
                return
            data = self._rows[row]
            kind = str(data.get("kind", "unique")).title()
            donor = self._humanize_type(str(data.get("base_template", "")))
            name = str(data.get("name", "")).strip()
            self.beginner_summary.setText(
                f"{kind} based on {donor}. "
                + (
                    "Its normal stats are inherited. Add its required artwork below "
                    "before the final build."
                    if name
                    else "Give it a unique name, then add its required artwork below. "
                    "Its normal stats are inherited."
                )
            )
            self.selected_key.setText(str(data.get("key", "")))
            self.selected_name.setText(str(data.get("name", "")))
            self.help_text.setPlainText(str(data.get("help_text", "")))
            self.strategy_text.setPlainText(str(data.get("strategy_text", "")))
            self.prereq_tech.clear()
            self.prereq_tech.addItem("")
            self.prereq_tech.addItems(self._technologies)
            tech = str(data.get("prereq_tech", "") or "")
            if tech and self.prereq_tech.findText(tech) < 0:
                self.prereq_tech.addItem(tech)
            self.prereq_tech.setCurrentText(tech)
            art = data.get("art", {}) if isinstance(data.get("art"), dict) else {}
            if data["kind"] == "unit":
                self.detail_stack.setCurrentWidget(self.unit_panel)
                for field, edit in self.unit_numbers.items():
                    edit.setText(self._number_text(data.get(field)))
                self.promotions.set_values(list(data.get("free_promotions", [])))
                self.unit_icon.set_path(str(art.get("icon_source", "")))
                self.unit_flag.set_path(str(art.get("unit_flag_source", "")))
                self.strategic_view.set_path(str(art.get("strategic_view_source", "")))
            elif data["kind"] == "building":
                self.detail_stack.setCurrentWidget(self.building_panel)
                for field, edit in self.building_numbers.items():
                    edit.setText(self._number_text(data.get(field)))
                self.yield_changes.set_values(list(data.get("yield_changes", [])))
                self.domain_experience.set_values(
                    list(data.get("domain_free_experience", []))
                )
                self.building_icon.set_path(str(art.get("icon_source", "")))
            else:
                self.detail_stack.setCurrentWidget(self.improvement_panel)
                self.improvement_civilopedia.setPlainText(
                    str(data.get("civilopedia_text", ""))
                )
                self.improvement_yield_changes.set_values(
                    list(data.get("yield_changes", []))
                )
                self.improvement_icon.set_path(str(art.get("icon_source", "")))
        finally:
            self._loading = False

    def _detail_changed(self, *_args) -> None:
        self._store_detail(True)

    def _store_detail(self, emit: bool) -> None:
        if self._loading or not 0 <= self._active_row < len(self._rows):
            return
        data = self._rows[self._active_row]
        key = self.selected_key.text().strip()
        if key:
            data["key"] = key
        else:
            data.pop("key", None)
        new_name = self.selected_name.text().strip()
        if data.get("name") != new_name:
            data["name"] = new_name
            item = self.table.item(self._active_row, 1)
            if item is not None:
                with QSignalBlocker(self.table):
                    item.setText(new_name)
        data["help_text"] = self.help_text.toPlainText().strip()
        data["strategy_text"] = self.strategy_text.toPlainText().strip()
        data["prereq_tech"] = self.prereq_tech.currentText().strip()
        art = data.get("art", {}) if isinstance(data.get("art"), dict) else {}
        if data["kind"] == "unit":
            for field, edit in self.unit_numbers.items():
                data[field] = self._maybe_int(edit.text())
            data["free_promotions"] = self.promotions.values()
            art.update(
                icon_source=self.unit_icon.path,
                unit_flag_source=self.unit_flag.path,
                strategic_view_source=self.strategic_view.path,
            )
        elif data["kind"] == "building":
            for field, edit in self.building_numbers.items():
                data[field] = self._maybe_int(edit.text())
            data["yield_changes"] = self.yield_changes.values()
            data["domain_free_experience"] = self.domain_experience.values()
            art["icon_source"] = self.building_icon.path
        else:
            data["civilopedia_text"] = (
                self.improvement_civilopedia.toPlainText().strip()
            )
            data["yield_changes"] = self.improvement_yield_changes.values()
            art["icon_source"] = self.improvement_icon.path
        data["art"] = art
        if emit:
            self._refresh_selected_cards()
            self.changed.emit()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or not 0 <= item.row() < len(self._rows):
            return
        if item.column() == 1:
            self._rows[item.row()]["name"] = item.text().strip()
            if item.row() == self._active_row:
                with QSignalBlocker(self.selected_name):
                    self.selected_name.setText(item.text().strip())
            self._refresh_selected_cards()
            self.changed.emit()

    def _widget_row(self, widget: QWidget, column: int) -> int:
        return next(
            (row for row in range(self.table.rowCount())
             if self.table.cellWidget(row, column) is widget),
            -1,
        )

    def _class_changed(self, widget: QComboBox, text: str) -> None:
        row = self._widget_row(widget, 2)
        if self._loading or not 0 <= row < len(self._rows):
            return
        self._rows[row]["replaces_class"] = text.strip()
        templates = (
            self._unit_templates
            if self._rows[row]["kind"] == "unit"
            else self._building_templates
        )
        if self._rows[row]["kind"] == "improvement":
            return
        donor = next((value for key, value in templates if key == text), "")
        donor_combo = self.table.cellWidget(row, 3)
        if donor and isinstance(donor_combo, QComboBox):
            donor_combo.setCurrentText(donor)
        self._refresh_selected_cards()
        self.changed.emit()

    def _combo_changed(self, widget: QComboBox, field: str, text: str) -> None:
        row = self._widget_row(widget, 3)
        if self._loading or not 0 <= row < len(self._rows):
            return
        self._rows[row][field] = text.strip()
        self._refresh_selected_cards()
        self.changed.emit()

    def _remove(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        self._loading = True
        try:
            for row in rows:
                self.table.removeRow(row)
                self._rows.pop(row)
        finally:
            self._loading = False
        self._active_row = -1
        if self._rows:
            self.table.setCurrentCell(min(rows[-1] if rows else 0, len(self._rows) - 1), 1)
        else:
            self._load_detail(-1)
        if rows:
            self._refresh_selected_cards()
            self.changed.emit()

    def values(self) -> list[dict]:
        self._store_detail(False)
        result = deepcopy(self._rows)
        for row in result:
            override, value = self._legacy_override(row)
            row["override"] = override
            row["value"] = value
        return result

    def set_values(self, values: list[dict]) -> None:
        self._loading = True
        try:
            self.table.setRowCount(0)
            self._rows = []
            self._active_row = -1
        finally:
            self._loading = False
        for entry in values:
            self.add_row(str(entry.get("kind", "unit")), entry)
        if not values:
            self._load_detail(-1)
        self._refresh_selected_cards()

    def set_reference_catalog(
        self,
        unit_templates: list[tuple[str, str]],
        building_templates: list[tuple[str, str]],
        yields: list[str],
        *,
        improvement_templates: list[str] | None = None,
        technologies: list[str] | None = None,
        promotions: list[str] | None = None,
        domains: list[str] | None = None,
    ) -> None:
        current = self.values()
        self._unit_templates = unit_templates or self._unit_templates
        self._building_templates = building_templates or self._building_templates
        self._improvement_templates = (
            improvement_templates or self._improvement_templates
        )
        self._yields = yields or self._yields
        self._technologies = list(technologies or self._technologies)
        self._promotions = list(promotions or self._promotions)
        self._domains = list(domains or self._domains)
        self.yield_changes.set_references(self._yields)
        self.improvement_yield_changes.set_references(self._yields)
        self.domain_experience.set_references(self._domains)
        self.promotions.set_references(self._promotions)
        self.set_values(current)
        self._refresh_donor_browser()

    @staticmethod
    def _maybe_int(value: object) -> int | None:
        text = str(value or "").strip()
        try:
            return int(text) if text else None
        except ValueError:
            return None

    @staticmethod
    def _number_text(value: object) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _legacy_override(row: dict) -> tuple[str, str]:
        if row.get("kind") == "unit":
            for label, field in (("Combat", "combat"), ("RangedCombat", "ranged_combat"),
                                 ("Moves", "moves"), ("Cost", "cost")):
                if row.get(field) is not None:
                    return label, str(row[field])
            return str(row.get("override", "Combat")), ""
        if row.get("kind") == "improvement":
            changes = row.get("yield_changes", [])
            if changes:
                first = changes[0]
                return f"Yield:{first.get('yield_type', '')}", str(first.get("amount", ""))
            return "Yield:YIELD_PRODUCTION", ""
        for label, field in (("Cost", "cost"), ("GoldMaintenance", "gold_maintenance"),
                             ("Defense", "defense"),
                             ("ExtraCityHitPoints", "extra_city_hit_points")):
            if row.get(field) is not None:
                return label, str(row[field])
        changes = row.get("yield_changes", [])
        if changes:
            first = changes[0]
            return f"Yield:{first.get('yield_type', '')}", str(first.get("amount", ""))
        return str(row.get("override", "Yield:YIELD_CULTURE")), ""


class MechanicsPage(WorkflowPage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Abilities & Uniques",
            "Choose one civilization-wide ability and normally two special units, buildings, or improvements.",
            parent,
        )
        self.coach = PageCoach(
            "Build the parts that make your civilization special",
            "For a first project, choose a built-in trait bonus and rename the two starter uniques. Blank stat fields safely keep the normal Civ V values.",
        )
        self.body.addWidget(self.coach)
        trait = SectionCard(
            "Special ability",
            "The ability applies to the whole civilization. Built-in bonuses are the safest choices for a first mod.",
        )
        form = QFormLayout()
        self.trait_name = QLineEdit()
        self.trait_name.setPlaceholderText("Example: Children of the Great River")
        self.trait_name.setAccessibleName("Civilization special ability name, required")
        self.trait_short = QLineEdit()
        self.trait_short.setPlaceholderText(
            "One short sentence players will see in setup"
        )
        self.trait_short.setAccessibleName(
            "Civilization special ability summary, required"
        )
        self._trait_recipes: dict[str, dict[str, str]] = {}
        self._last_auto_effect = ""
        self.mechanic_level = QComboBox()
        self.mechanic_level.addItems(
            [
                "Database-native recipe",
                "Lua idea (not compiled)",
                "Custom code / DLL required",
            ]
        )
        self.recipe = QComboBox()
        self.recipe.addItem("Choose a built-in bonus...", "No database modifier")
        self.recipe.setAccessibleName("Built-in trait bonus")
        self.modifier_value = QSpinBox()
        self.modifier_value.setRange(-1000, 1000)
        self.modifier_value.setValue(10)
        self.modifier_value.setSuffix(" bonus")
        self.modifier_value.setToolTip(
            "Numeric value written to the selected verified Traits column. "
            "Boolean recipes treat any non-zero value as enabled."
        )
        self.effect = QPlainTextEdit()
        self.effect.setMaximumHeight(100)
        self.effect.setPlaceholderText(
            "Studio suggests this from the selected bonus. You may rewrite it in plain language."
        )
        self.recipe_help = QLabel(
            "Choose a built-in bonus to see what it does."
        )
        self.recipe_help.setWordWrap(True)
        self.recipe_help.setStyleSheet(f"color: {MUTED};")
        self.recipe_status = QLabel(
            "No modifier selected. Only registry-backed fields are offered as compiled recipes."
        )
        self.recipe_status.setWordWrap(True)
        self.recipe_status.setStyleSheet(f"color: {MUTED};")
        self.mechanic_level_label = QLabel("How this effect is built")
        self.mechanic_level_label.setBuddy(self.mechanic_level)
        self.recipe_status_label = QLabel("Technical build status")
        self.recipe_status_label.setBuddy(self.recipe_status)
        form.addRow("Ability name *", self.trait_name)
        form.addRow("Setup-screen summary *", self.trait_short)
        form.addRow("Built-in trait bonus", self.recipe)
        form.addRow("What this bonus does", self.recipe_help)
        form.addRow("Bonus amount", self.modifier_value)
        form.addRow("Player-facing explanation", self.effect)
        form.addRow(self.mechanic_level_label, self.mechanic_level)
        form.addRow(self.recipe_status_label, self.recipe_status)
        trait.body.addLayout(form)
        self.body.addWidget(trait)

        uniques = SectionCard(
            "Unique units, buildings, and improvements",
            "Every unique starts from a normal Civ V item. Choose what it is based "
            "on, give it a new name, add its required artwork, and change stats only "
            "when you want to.",
        )
        self.uniques = UniqueTable()
        self.uniques.add_row("unit", {"replaces_class": "UNITCLASS_SWORDSMAN", "base_template": "UNIT_SWORDSMAN"})
        self.uniques.add_row("building", {"replaces_class": "BUILDINGCLASS_MONUMENT", "base_template": "BUILDING_MONUMENT"})
        uniques.body.addWidget(self.uniques)
        self.body.addWidget(uniques)
        self.finish()

        self.mechanic_level.currentTextChanged.connect(self._implementation_changed)
        self.recipe.currentTextChanged.connect(self._recipe_changed)

        for signal in (
            self.trait_name.textChanged,
            self.trait_short.textChanged,
            self.mechanic_level.currentTextChanged,
            self.recipe.currentTextChanged,
            self.modifier_value.valueChanged,
            self.effect.textChanged,
            self.uniques.changed,
        ):
            signal.connect(self.changed)
        self.set_expert_mode(False)

    def set_expert_mode(self, expert: bool) -> None:
        self.mechanic_level_label.setVisible(bool(expert))
        self.mechanic_level.setVisible(bool(expert))
        self.recipe_status_label.setVisible(bool(expert))
        self.recipe_status.setVisible(bool(expert))
        self.uniques.set_expert_mode(expert)

    def set_trait_recipes(self, recipes: list[dict[str, str]]) -> None:
        selected = str(self.recipe.currentData() or self.recipe.currentText())
        self._trait_recipes = {
            str(item.get("label", "")): dict(item)
            for item in recipes
            if item.get("label")
        }
        self._implementation_changed(self.mechanic_level.currentText(), selected)

    def _implementation_changed(self, _label: str, selected: str | None = None) -> None:
        previous = selected if selected is not None else str(
            self.recipe.currentData() or self.recipe.currentText()
        )
        with QSignalBlocker(self.recipe):
            self.recipe.clear()
            if self.mechanic_level.currentText().startswith("Database"):
                self.recipe.addItem(
                    "Choose a built-in bonus...", "No database modifier"
                )
                for label in self._trait_recipes:
                    self.recipe.addItem(label, label)
                requested = (
                    previous
                    if previous in self._trait_recipes
                    else "No database modifier"
                )
                selected_index = self.recipe.findData(requested)
                self.recipe.setCurrentIndex(max(0, selected_index))
                self.modifier_value.setEnabled(True)
            else:
                self.recipe.addItem(
                    "Unimplemented Lua mechanic"
                    if self.mechanic_level.currentText().startswith("Lua idea")
                    else "Unimplemented custom mechanic",
                    "Unimplemented Lua mechanic"
                    if self.mechanic_level.currentText().startswith("Lua idea")
                    else "Unimplemented custom mechanic",
                )
                self.modifier_value.setEnabled(False)
        self._recipe_changed(self.recipe.currentText())
        self.changed.emit()

    def _recipe_changed(self, label: str) -> None:
        recipe_key = str(self.recipe.currentData() or label)
        recipe = self._trait_recipes.get(recipe_key)
        if recipe is not None:
            summary = str(recipe.get("summary", "")).strip()
            self.recipe_help.setText(
                summary or "This is a Studio-supported built-in trait bonus."
            )
            current_effect = self.effect.toPlainText().strip()
            if summary and (
                not current_effect or current_effect == self._last_auto_effect
            ):
                self._last_auto_effect = summary
                self.effect.setPlainText(summary)
            self.recipe_status.setText(
                f"Compiled database recipe: {recipe.get('storage_path', '')}."
            )
            self.recipe_status.setStyleSheet(f"color: {SUCCESS};")
        elif self.mechanic_level.currentText().startswith("Database"):
            self.recipe_help.setText(
                "Choose a built-in bonus to see what it does."
            )
            if recipe_key and recipe_key != "No database modifier":
                self.recipe_status.setText(
                    "Unregistered legacy field preserved. Validation will reject it unless "
                    "the bundled BNW schema verifies the column."
                )
                self.recipe_status.setStyleSheet(f"color: {WARNING};")
            else:
                self.recipe_status.setText(
                    "No modifier selected. Only registry-backed fields are offered as compiled recipes."
                )
                self.recipe_status.setStyleSheet(f"color: {MUTED};")
        else:
            self.recipe_status.setText(
                "Not compiled. Audit lists this effect and strict release blocks it."
            )
            self.recipe_status.setStyleSheet(f"color: {WARNING};")

    def values(self) -> dict:
        return {
            "trait": {
                "name": _text(self.trait_name),
                "short_description": _text(self.trait_short),
                "implementation_class": self.mechanic_level.currentText(),
                "recipe": str(
                    self.recipe.currentData() or self.recipe.currentText()
                ).strip(),
                "modifier_value": self.modifier_value.value(),
                "effect_description": _text(self.effect),
            },
            "uniques": self.uniques.values(),
        }

    def load_values(self, data: dict) -> None:
        trait = data.get("trait", {}) if isinstance(data.get("trait", {}), dict) else {}
        self.trait_name.setText(str(trait.get("name", "")))
        self.trait_short.setText(str(trait.get("short_description", "")))
        self.mechanic_level.setCurrentText(str(trait.get("implementation_class", "Database-native recipe")))
        requested_recipe = str(trait.get("recipe", "No database modifier"))
        requested_index = self.recipe.findData(requested_recipe)
        if requested_recipe and requested_index < 0:
            self.recipe.addItem(requested_recipe, requested_recipe)
            requested_index = self.recipe.count() - 1
        self.recipe.setCurrentIndex(max(0, requested_index))
        self.modifier_value.setValue(int(trait.get("modifier_value", 10)))
        self.effect.setPlainText(str(trait.get("effect_description", "")))
        self.uniques.set_values(list(data.get("uniques", [])))


class PromotionsExpansionPackPage(WorkflowPage):
    """Optional assignment surface isolated from the vanilla promotion picker."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Promotions Expansion Pack (Optional)",
            "Skip this for a first project. Enable it only when you want abilities from Promotions - Expansion Pack v9 on your unique units.",
            parent,
        )
        self.coach = PageCoach(
            "This requires Bloublou's separate mod",
            "Promotions - Expansion Pack was created by Bloublou and is not bundled with Studio. If enabled, every player must separately subscribe to and enable v9 from Steam Workshop.",
            required=False,
        )
        self.body.addWidget(self.coach)
        self._loading = False
        self._catalog: list[dict] = []
        self._units: list[dict] = []

        dependency = SectionCard(
            "Turn on the optional connection",
            "Studio records the exact v9 requirement automatically when this is enabled.",
        )
        self.enabled = QCheckBox(
            "Enable Promotions - Expansion Pack v9 integration"
        )
        self.identity = QLabel(
            '<a href="https://steamcommunity.com/sharedfiles/filedetails/?id=84863495">'
            "Get Promotions - Expansion Pack v9 by Bloublou on Steam Workshop</a><br>"
            "Separate download required; the mod is not bundled.  |  "
            "Mod ID: 0d764575-8028-4350-a363-c1ffb88b6a9a  |  Version: 9"
        )
        self.identity.setOpenExternalLinks(True)
        self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.identity.setStyleSheet(f"color: {MUTED};")
        dependency.body.addWidget(self.enabled)
        dependency.body.addWidget(self.identity)
        self.body.addWidget(dependency)

        assignments = SectionCard(
            "Unique unit promotions",
            "Choose a unique unit and one promotion per row. Display names and "
            "help below are read-only metadata derived from the referenced mod.",
        )
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Unique unit", "PEP v9 promotion"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(280)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add promotion assignment")
        self.remove_button = QPushButton("Remove selected")
        self.add_button.clicked.connect(lambda: self.add_assignment())
        self.remove_button.clicked.connect(self._remove_selected)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        self.help_label = QLabel("Select an assignment to view its verified help text.")
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet(f"color: {MUTED};")
        assignments.body.addWidget(self.table)
        assignments.body.addLayout(buttons)
        assignments.body.addWidget(self.help_label)
        self.body.addWidget(assignments)
        self.finish()

        self.enabled.toggled.connect(self._enabled_changed)
        self.table.currentCellChanged.connect(self._selection_changed)
        self._enabled_changed(False)

    def set_expert_mode(self, expert: bool) -> None:
        self.identity.setVisible(True)

    @staticmethod
    def _readable_help(value: object) -> str:
        text = str(value or "")
        text = text.replace("[NEWLINE]", "\n")
        text = text.replace("[ICON_STRENGTH]", "Strength")
        text = text.replace("[ICON_MOVES]", "Movement")
        text = text.replace("[ICON_RANGE_STRENGTH]", "Ranged Strength")
        text = re.sub(r"\[COLOR_[^]]+]", "", text)
        text = text.replace("[ENDCOLOR]", "")
        text = re.sub(
            r"\[ICON_([A-Z0-9_]+)]",
            lambda match: match.group(1).replace("_", " ").title(),
            text,
        )
        return " ".join(text.split())

    def set_catalog(self, entries: list[dict]) -> None:
        current = self.values()["assignments"]
        self._catalog = [dict(item) for item in entries]
        self._replace_assignments(current)

    def set_units(self, unique_rows: list[dict]) -> None:
        units = []
        for raw in unique_rows:
            if not isinstance(raw, dict) or str(raw.get("kind", "")).lower() != "unit":
                continue
            index = len(units)
            units.append(
                {
                    "unit_key": str(raw.get("key", "")).strip(),
                    "original_key": str(
                        raw.get("original_key", raw.get("key", ""))
                    ).strip(),
                    "unit_name": str(raw.get("name", "")).strip(),
                    "unit_index": index,
                }
            )
        if units == self._units:
            return
        current = self.values()["assignments"]
        self._units = units
        self._replace_assignments(current)

    def add_assignment(self, value: dict | None = None) -> None:
        assignment = dict(value or {})
        row = self.table.rowCount()
        self.table.insertRow(row)

        unit_combo = QComboBox()
        for unit in self._units:
            name = unit["unit_name"] or f"Unique unit {unit['unit_index'] + 1}"
            key = unit["unit_key"]
            label = f"{name} ({key})" if key else name
            unit_combo.addItem(label, dict(unit))
        requested_key = str(assignment.get("unit_key", "")).strip()
        requested_original = str(
            assignment.get("original_unit_key", requested_key)
        ).strip()
        requested_name = str(assignment.get("unit_name", "")).strip()
        requested_index = assignment.get("unit_index")
        unit_position = -1
        if requested_key:
            unit_position = next(
                (
                    index
                    for index in range(unit_combo.count())
                    if unit_combo.itemData(index).get("unit_key") == requested_key
                ),
                -1,
            )
        if unit_position < 0 and requested_original:
            unit_position = next(
                (
                    index
                    for index in range(unit_combo.count())
                    if unit_combo.itemData(index).get("original_key")
                    == requested_original
                ),
                -1,
            )
        if unit_position < 0 and requested_name:
            name_matches = [
                index
                for index in range(unit_combo.count())
                if unit_combo.itemData(index).get("unit_name") == requested_name
            ]
            if len(name_matches) == 1:
                unit_position = name_matches[0]
        if unit_position < 0 and requested_index is not None:
            index_match = next(
                (
                    index
                    for index in range(unit_combo.count())
                    if unit_combo.itemData(index).get("unit_index")
                    == requested_index
                ),
                -1,
            )
            if index_match >= 0:
                candidate = unit_combo.itemData(index_match)
                if not requested_name or candidate.get("unit_name") == requested_name:
                    unit_position = index_match
        if (requested_key or requested_name) and unit_position < 0:
            preserved = {
                "unit_key": requested_key,
                "original_key": requested_original,
                "unit_name": requested_name,
                "unit_index": requested_index if requested_index is not None else -1,
            }
            label = requested_name or requested_key or "deleted unique unit"
            unit_combo.addItem(f"Unknown preserved: {label}", preserved)
            unit_position = unit_combo.count() - 1
        if unit_combo.count():
            unit_combo.setCurrentIndex(max(0, unit_position))

        promotion_combo = QComboBox()
        for item in self._catalog:
            promotion_type = str(item.get("type", ""))
            display_name = str(item.get("display_name", ""))
            promotion_combo.addItem(display_name or promotion_type, promotion_type)
        requested_promotion = str(assignment.get("promotion_type", "")).strip()
        promotion_position = next(
            (
                index
                for index in range(promotion_combo.count())
                if promotion_combo.itemData(index) == requested_promotion
            ),
            -1,
        )
        if requested_promotion and promotion_position < 0:
            promotion_combo.addItem(requested_promotion, requested_promotion)
            promotion_position = promotion_combo.count() - 1
        if promotion_combo.count():
            promotion_combo.setCurrentIndex(max(0, promotion_position))

        unit_combo.currentIndexChanged.connect(self._assignment_changed)
        promotion_combo.currentIndexChanged.connect(self._assignment_changed)
        self.table.setCellWidget(row, 0, unit_combo)
        self.table.setCellWidget(row, 1, promotion_combo)
        self.table.setCurrentCell(row, 0)
        if not self._loading:
            self.changed.emit()

    def values(self) -> dict:
        assignments = []
        for row in range(self.table.rowCount()):
            unit_combo = self.table.cellWidget(row, 0)
            promotion_combo = self.table.cellWidget(row, 1)
            if not isinstance(unit_combo, QComboBox) or not isinstance(
                promotion_combo, QComboBox
            ):
                continue
            unit = unit_combo.currentData()
            promotion = promotion_combo.currentData()
            if isinstance(unit, dict) and promotion:
                assignments.append(
                    {
                        "unit_key": str(unit.get("unit_key", "")),
                        "original_unit_key": str(
                            unit.get("original_key", unit.get("unit_key", ""))
                        ),
                        "unit_name": str(unit.get("unit_name", "")),
                        "unit_index": int(unit.get("unit_index", 0)),
                        "promotion_type": str(promotion),
                    }
                )
        return {"enabled": self.enabled.isChecked(), "assignments": assignments}

    def load_values(self, data: dict) -> None:
        self._loading = True
        try:
            self.enabled.setChecked(bool(data.get("enabled", False)))
            assignments = data.get("assignments", [])
            self._replace_assignments(
                list(assignments) if isinstance(assignments, list) else []
            )
        finally:
            self._loading = False
        self._enabled_changed(self.enabled.isChecked())

    def _replace_assignments(self, assignments: list[dict]) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.table.setRowCount(0)
            for assignment in assignments:
                if isinstance(assignment, dict):
                    self.add_assignment(assignment)
        finally:
            self._loading = was_loading
        self._update_help()

    def _remove_selected(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            self.table.removeRow(row)
        self._update_help()
        if rows and not self._loading:
            self.changed.emit()

    def _enabled_changed(self, enabled: bool) -> None:
        self.table.setEnabled(enabled)
        self.add_button.setEnabled(enabled and bool(self._units) and bool(self._catalog))
        self.remove_button.setEnabled(enabled)
        if not self._loading:
            self.changed.emit()

    def _assignment_changed(self, *_args) -> None:
        self._update_help()
        if not self._loading:
            self.changed.emit()

    def _selection_changed(self, *_args) -> None:
        self._update_help()

    def _update_help(self) -> None:
        row = self.table.currentRow()
        combo = self.table.cellWidget(row, 1) if row >= 0 else None
        promotion_type = combo.currentData() if isinstance(combo, QComboBox) else ""
        entry = next(
            (
                item
                for item in self._catalog
                if item.get("type") == promotion_type
            ),
            None,
        )
        if entry:
            self.help_label.setText(
                f"{entry.get('display_name')}\n"
                f"{self._readable_help(entry.get('help_text', ''))}"
            )
        elif promotion_type:
            self.help_label.setText(
                f"Unknown preserved promotion type: {promotion_type}"
            )
        else:
            self.help_label.setText(
                "Select an assignment to view its verified help text."
            )

    def focus_location(
        self, unit_index: int, promotion_index: int
    ) -> QWidget:
        """Focus the exact PEP assignment represented by a domain path."""

        if not self.enabled.isChecked():
            return self.enabled
        matching_rows: list[int] = []
        for row in range(self.table.rowCount()):
            unit_combo = self.table.cellWidget(row, 0)
            unit = unit_combo.currentData() if isinstance(unit_combo, QComboBox) else None
            if isinstance(unit, dict) and int(unit.get("unit_index", -1)) == unit_index:
                matching_rows.append(row)
        if 0 <= promotion_index < len(matching_rows):
            row = matching_rows[promotion_index]
            self.table.setCurrentCell(row, 1)
            target = self.table.cellWidget(row, 1)
            if isinstance(target, QWidget):
                return target
        return self.enabled if not self.enabled.isChecked() else self.table


class ArtPage(WorkflowPage):
    ROLES = (
        ("civilization_icon", "Civilization portrait - square PNG"),
        ("civilization_alpha", "White emblem on black - square PNG"),
        ("leader_portrait", "Leader portrait - square PNG"),
        ("dawn_of_man", "Opening-screen artwork - 4:3 PNG"),
        ("map_image", "Setup map image - portrait PNG"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Artwork",
            "Choose ordinary PNG pictures. Studio creates the DDS files and Civ V icon sizes without changing your originals.",
            parent,
        )
        self.coach = PageCoach(
            "Add each picture once",
            "Use 1024 x 1024 PNGs for round icons when possible. Do not add a gold ring or frame - Civilization V draws its own frame.",
        )
        self.body.addWidget(self.coach)
        self.art_status = QLabel("0 of 5 main pictures added")
        self.art_status.setWordWrap(True)
        self.art_status.setStyleSheet(f"color: {WARNING}; font-weight: 700;")
        self.body.addWidget(self.art_status)
        self.all_art_status = QLabel(
            "Other artwork checklist: add the leader scene on Your Leader and each "
            "unique item's artwork on Abilities & Uniques."
        )
        self.all_art_status.setWordWrap(True)
        self.all_art_status.setStyleSheet(f"color: {MUTED};")
        self.body.addWidget(self.all_art_status)
        sources = SectionCard(
            "Core artwork",
            "Every item below is needed for the final build. The checklist also "
            "shows artwork added on the Leader and Abilities & Uniques pages.",
        )
        grid = QGridLayout()
        self.slots: dict[str, AssetDropZone] = {}
        for index, (role, title) in enumerate(self.ROLES):
            slot = AssetDropZone(role, title)
            slot.pathChanged.connect(self.changed)
            slot.pathChanged.connect(self._update_art_status)
            slot.selected.connect(self._select)
            self.slots[role] = slot
            grid.addWidget(slot, index // 4, index % 4)
        sources.body.addLayout(grid)
        self.body.addWidget(sources)

        preview = SectionCard(
            "Crop and preview",
            "Choose a picture above, then drag to move it or use the mouse wheel to zoom. The safe-area guide and gold frame are previews only.",
        )
        self.current_role = "civilization_icon"
        self.transforms: dict[str, dict[str, int]] = {role: {"zoom": 100, "offset_x": 0, "offset_y": 0} for role, _ in self.ROLES}
        self.selection_label = QLabel("Civilization portrait")
        self.selection_label.setStyleSheet("font-weight: 650;")
        preview.body.addWidget(self.selection_label)
        self.studio = ArtStudioWidget()
        self.studio.set_zoom_range(60, 160, emit=False)
        self.studio.set_offset_range(-100, 100, emit=False)
        self.preview = self.studio.previews
        preview.body.addWidget(self.studio)
        note = QLabel(
            "Original PNGs stay untouched - the preview ring is never exported - Studio checks every generated DDS file"
        )
        note.setStyleSheet(f"color: {SUCCESS};")
        preview.body.addWidget(note)
        self.body.addWidget(preview)
        self.finish()
        self.studio.transformChanged.connect(self._transform_changed)
        self._update_art_status()

    def _update_art_status(self, *_args) -> None:
        ready = sum(1 for slot in self.slots.values() if slot.path)
        missing = len(self.slots) - ready
        self.art_status.setText(
            f"{ready} of {len(self.slots)} main pictures added"
            + (" - ready for picture checks" if not missing else f" - {missing} still missing")
        )
        self.art_status.setStyleSheet(
            f"color: {SUCCESS if not missing else WARNING}; font-weight: 700;"
        )

    def set_external_art_status(self, leader: dict, uniques: list[dict]) -> None:
        leader_art = leader.get("art", {}) if isinstance(leader, dict) else {}
        leader_scene_ready = (
            bool(leader_art.get("leader_scene"))
            if isinstance(leader_art, dict)
            else False
        )
        unique_required = 0
        unique_ready = 0
        checklist = [
            f"{'Ready' if leader_scene_ready else 'Missing'} - Leader scene "
            "(add on Your Leader)"
        ]
        for unique in uniques:
            if not isinstance(unique, dict):
                continue
            art = unique.get("art", {})
            art = art if isinstance(art, dict) else {}
            if unique.get("kind") == "unit":
                required_keys = ("icon_source", "unit_flag_source")
            else:
                required_keys = ("icon_source",)
            unique_required += len(required_keys)
            ready_count = sum(bool(art.get(key)) for key in required_keys)
            unique_ready += ready_count
            unique_name = str(unique.get("name", "")).strip() or "Unnamed unique"
            needed = (
                "portrait and unit flag"
                if unique.get("kind") == "unit"
                else "portrait"
            )
            checklist.append(
                f"{'Ready' if ready_count == len(required_keys) else 'Missing'} - "
                f"{unique_name}: {needed} (add on Abilities & Uniques)"
            )
        total_required = 1 + unique_required
        total_ready = int(leader_scene_ready) + unique_ready
        missing = total_required - total_ready
        self.all_art_status.setText(
            "Other artwork checklist\n"
            + "\n".join(checklist)
            + (
                "\nEverything in this checklist is ready."
                if not missing
                else f"\n{missing} file{'s' if missing != 1 else ''} still missing."
            )
        )
        self.all_art_status.setStyleSheet(
            f"color: {SUCCESS if not missing else WARNING};"
        )

    def _select(self, role: str, path: str) -> None:
        self.current_role = role
        title = dict(self.ROLES).get(role, role)
        self.selection_label.setText(title)
        transform = self.transforms[role]
        self.studio.set_source(path)
        self.studio.set_transform(transform)

    def _transform_changed(self, transform: dict[str, int]) -> None:
        self.transforms[self.current_role] = {
            "zoom": int(transform.get("zoom", 100)),
            "offset_x": int(transform.get("offset_x", 0)),
            "offset_y": int(transform.get("offset_y", 0)),
        }
        self.changed.emit()

    def values(self) -> dict:
        return {
            role: {"source": slot.path, "transform": dict(self.transforms[role])}
            for role, slot in self.slots.items()
        }

    def load_values(self, data: dict) -> None:
        for role, slot in self.slots.items():
            entry = data.get(role, {}) if isinstance(data.get(role, {}), dict) else {}
            slot.set_path(str(entry.get("source", "")))
            transform = entry.get("transform", {}) if isinstance(entry.get("transform", {}), dict) else {}
            self.transforms[role] = {
                "zoom": max(60, min(160, int(transform.get("zoom", 100)))),
                "offset_x": max(-100, min(100, int(transform.get("offset_x", 0)))),
                "offset_y": max(-100, min(100, int(transform.get("offset_y", 0)))),
            }
        self._select(self.current_role, self.slots[self.current_role].path)
        self._update_art_status()


class ReviewPage(WorkflowPage):
    auditRequested = Signal()
    validateRequested = Signal()
    buildRequested = Signal()
    installRequested = Signal()
    launchRequested = Signal()
    analyzeLogsRequested = Signal()
    artifactRequested = Signal(str)
    fixRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Check, Build & Play",
            "Studio checks the project, creates the mod, and installs it into Civilization V. You only need to follow the next highlighted action.",
            parent,
        )
        self.coach = PageCoach(
            "Finish in three steps",
            "1. Check and create the mod. 2. Fix anything marked Must fix. 3. Install it, open Brave New World, and test a new game.",
        )
        self.body.addWidget(self.coach)
        self._last_issues: list[dict[str, str]] = []
        summary = SectionCard("Is the civilization ready?")
        self.summary_label = QLabel(
            "Nothing has been checked yet. Complete the guided pages, then choose Check and create my mod."
        )
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color: {WARNING}; font-weight: 650;")
        self.issues = IssueTree()
        self.issues.setVisible(False)
        self.fix_first_button = QPushButton("Fix the first problem")
        self.fix_first_button.setVisible(False)
        self.fix_first_button.clicked.connect(self._fix_first)
        summary.body.addWidget(self.summary_label)
        summary.body.addWidget(self.fix_first_button, 0, Qt.AlignmentFlag.AlignLeft)
        summary.body.addWidget(self.issues)
        self.body.addWidget(summary)

        actions = SectionCard(
            "Next recommended action",
            "Creating the mod runs the complete safety check first. Installation stays locked until the current build passes.",
        )
        buttons = QHBoxLayout()
        self.build_button = QPushButton("Check and create my mod")
        self.build_button.setObjectName("primaryButton")
        self.install_button = QPushButton("Install into Civilization V")
        self.install_button.setEnabled(False)
        self.launch_button = QPushButton("Open Civilization V...")
        buttons.addWidget(self.build_button)
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.launch_button)
        buttons.addStretch(1)
        actions.body.addLayout(buttons)
        self.body.addWidget(actions)

        self.advanced_card = SectionCard(
            "Expert checks and test evidence",
            "Use these separate stages when diagnosing a project or recording exact manual-test evidence.",
        )
        expert_buttons = QHBoxLayout()
        self.audit_button = QPushButton("Check my progress")
        self.validate_button = QPushButton("Run final safety check")
        self.analyze_button = QPushButton("Check Civ V logs for problems")
        expert_buttons.addWidget(self.audit_button)
        expert_buttons.addWidget(self.validate_button)
        expert_buttons.addWidget(self.analyze_button)
        expert_buttons.addStretch(1)
        self.pipeline = BuildPipelineWidget()
        runtime = QHBoxLayout()
        runtime.addWidget(QLabel("Result of testing this exact mod in BNW"))
        self.runtime_status = QComboBox()
        self.runtime_status.addItems(["NOT RUN", "PASS", "FAIL"])
        self.runtime_status.setToolTip(
            "Session-only user result for the exact installed build. Static validation never changes this to PASS."
        )
        self.runtime_note = QLineEdit()
        self.runtime_note.setPlaceholderText(
            "Optional test note, save/reload result, or diagnostics ZIP hash"
        )
        runtime.addWidget(self.runtime_status)
        runtime.addWidget(self.runtime_note, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log = LogPanel()
        self.advanced_card.body.addLayout(expert_buttons)
        self.advanced_card.body.addWidget(self.pipeline)
        self.advanced_card.body.addLayout(runtime)
        self.advanced_card.body.addWidget(self.progress)
        self.advanced_card.body.addWidget(self.log)
        self.body.addWidget(self.advanced_card)
        self.finish()
        self.audit_button.clicked.connect(self.auditRequested)
        self.validate_button.clicked.connect(self.validateRequested)
        self.build_button.clicked.connect(self.buildRequested)
        self.install_button.clicked.connect(self.installRequested)
        self.launch_button.clicked.connect(self.launchRequested)
        self.analyze_button.clicked.connect(self.analyzeLogsRequested)
        self.runtime_status.currentTextChanged.connect(self._runtime_status_changed)
        self.pipeline.artifactRequested.connect(self.artifactRequested.emit)
        self.set_expert_mode(False)

    def set_expert_mode(self, expert: bool) -> None:
        self.advanced_card.setVisible(bool(expert))

    def _fix_first(self) -> None:
        ranked = sorted(
            self._last_issues,
            key=lambda item: {
                "ERROR": 0,
                "WARNING": 1,
                "INFO": 2,
            }.get(str(item.get("severity", "INFO")).upper(), 3),
        )
        if ranked:
            self.fixRequested.emit(
                str(ranked[0].get("location", ranked[0].get("field", "")))
            )

    def set_busy(self, busy: bool, message: str = "") -> None:
        for button in (
            self.audit_button,
            self.validate_button,
            self.build_button,
            self.install_button,
            self.launch_button,
            self.analyze_button,
        ):
            button.setEnabled(not busy and (button is not self.install_button or self.install_button.property("ready") is True))
        self.progress.setRange(0, 0 if busy else 100)
        if message:
            self.log.append_message(message)

    def set_results(self, issues: list[dict[str, str]], summary: str, can_install: bool = False) -> None:
        self._last_issues = [dict(issue) for issue in issues]
        self.issues.set_issues(issues)
        errors = sum(
            1 for issue in issues
            if str(issue.get("severity", "INFO")).upper() == "ERROR"
        )
        warnings = sum(
            1 for issue in issues
            if str(issue.get("severity", "INFO")).upper() == "WARNING"
        )
        if errors:
            friendly_summary = (
                f"Not ready yet: {errors} item{'s' if errors != 1 else ''} must be fixed. "
                "Choose Fix the first problem and Studio will take you to it."
            )
        elif can_install:
            friendly_summary = "Ready to install. The current generated mod passed Studio's static checks."
        elif warnings:
            friendly_summary = (
                f"No blocking errors. Review {warnings} suggestion{'s' if warnings != 1 else ''} before the final build."
            )
        else:
            friendly_summary = summary or "No current problems were found."
        self.summary_label.setText(friendly_summary)
        self.summary_label.setToolTip(summary)
        self.summary_label.setStyleSheet(
            f"color: {SUCCESS if not errors else WARNING}; font-weight: 650;"
        )
        self.issues.setVisible(bool(issues))
        self.fix_first_button.setVisible(bool(issues))
        self.install_button.setProperty("ready", can_install)
        self.install_button.setEnabled(can_install)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)

    def reset_results(
        self, message: str = "Validation will refresh for the loaded project."
    ) -> None:
        self._last_issues = []
        self.issues.set_issues([])
        self.summary_label.setText(message)
        self.summary_label.setStyleSheet(
            f"color: {WARNING}; font-weight: 650;"
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.clear()
        self.issues.setVisible(False)
        self.fix_first_button.setVisible(False)
        self.reset_pipeline()

    def set_pipeline_stage(
        self,
        stage: str,
        status: str,
        detail: str = "",
        artifact_path: str | None = None,
    ) -> None:
        self.pipeline.set_stage(stage, status, detail, artifact_path)

    def invalidate_after_edit(self) -> None:
        self.pipeline.invalidate_after_edit()
        with QSignalBlocker(self.runtime_status):
            self.runtime_status.setCurrentText("NOT RUN")
        self.runtime_note.clear()

    def reset_pipeline(self) -> None:
        self.pipeline.reset()
        with QSignalBlocker(self.runtime_status):
            self.runtime_status.setCurrentText("NOT RUN")
        self.runtime_note.clear()
        self.install_button.setProperty("ready", False)
        self.install_button.setEnabled(False)

    def _runtime_status_changed(self, status: str) -> None:
        if status == "PASS":
            if self.pipeline.status("launch") == "STALE":
                self.pipeline.set_stage(
                    "launch",
                    "REQUESTED",
                    "User is recording a manual result for the current project revision.",
                )
            self.pipeline.set_stage(
                "launch",
                "PASS",
                "User reports the exact installed build passed manual BNW testing.",
            )
        elif status == "FAIL":
            if self.pipeline.status("launch") == "STALE":
                self.pipeline.set_stage(
                    "launch",
                    "REQUESTED",
                    "User is recording a manual result for the current project revision.",
                )
            self.pipeline.set_stage(
                "launch",
                "FAIL",
                "User reports the exact installed build failed manual BNW testing.",
            )
        elif status == "NOT RUN" and self.pipeline.status("launch") in {
            "PASS",
            "FAIL",
        }:
            self.pipeline.set_stage(
                "launch",
                "NOT RUN",
                "No manual BNW runtime result is recorded for this session.",
            )
