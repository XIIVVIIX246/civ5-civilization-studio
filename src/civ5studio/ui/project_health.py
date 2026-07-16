"""Validation navigation and workflow-health presentation helpers.

The widgets in this module consume the plain issue dictionaries already used
by the controller.  They never validate projects themselves; their only job is
to make an existing report actionable inside the guided workflow.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import ERROR, MUTED, SUCCESS, WARNING


STEP_LABELS = (
    "Start Here",
    "Your Civilization",
    "Your Leader",
    "Abilities & Uniques",
    "Promotions Mod (Optional)",
    "Artwork",
    "Advanced Tools (Optional)",
    "Extra Gameplay Effects (Optional)",
    "Check, Build & Play",
)


SEVERITY_LABELS = {
    "ERROR": "Must fix",
    "WARNING": "Suggestion",
    "INFO": "Note",
    "PASS": "Note",
}


_LOCATION_LABELS = {
    "advanced": "Optional tools",
    "affects_saved_games": "Affects saved games",
    "application": "Application",
    "art": "Artwork",
    "assets": "Art assets",
    "atlas": "Icon atlas",
    "audio": "Audio",
    "authors": "Author",
    "base_building": "Vanilla building template",
    "base_civilization": "Vanilla civilization defaults",
    "base_improvement": "Vanilla improvement template",
    "base_unit": "Vanilla unit template",
    "build": "Build package",
    "buildings": "Unique buildings",
    "city_names": "City names",
    "civilization": "Civilization",
    "civilopedia": "Civilopedia text",
    "colors": "Civilization colors",
    "combat": "Combat strength",
    "compatibility": "Compatibility",
    "cost": "Production cost",
    "database": "Game database",
    "dawn_of_man_quote": "Dawn of Man quote",
    "defense": "Defense strength",
    "description": "Description",
    "diplomacy": "Diplomacy text",
    "effect_id": "Effect choice",
    "effect_version": "Effect version",
    "extra_city_hit_points": "Extra city hit points",
    "extensions": "Optional tools",
    "existing_mod_import": "Existing mod import",
    "free_promotions": "Free promotions",
    "gold_maintenance": "Gold maintenance",
    "help": "Help text",
    "icon_source": "Unique portrait PNG",
    "improvements": "Unique improvements",
    "internal_prefix": "Internal project ID",
    "leader": "Leader",
    "leader_portrait": "Leader portrait",
    "leader_scene": "Leader scene",
    "localization": "Translated text",
    "lua_effects": "Lua effects",
    "map_image": "Setup map image",
    "mechanics": "Trait and unique components",
    "mod_name": "Mod name",
    "mod_version": "Mod version",
    "modinfo": "Mod information file",
    "moves": "Movement points",
    "name": "Name",
    "options": "Project options",
    "package": "Player package",
    "parameters": "Effect settings",
    "prereq_tech": "Required technology",
    "primary_blue": "Primary color - blue channel",
    "primary_green": "Primary color - green channel",
    "primary_red": "Primary color - red channel",
    "project_format": "Project file format",
    "promotions_expansion_pack": "Promotions Expansion Pack",
    "ranged_combat": "Ranged combat strength",
    "replaces_building_class": "Building class being replaced",
    "replaces_unit_class": "Unit class being replaced",
    "secondary_blue": "Secondary color - blue channel",
    "secondary_green": "Secondary color - green channel",
    "secondary_red": "Secondary color - red channel",
    "short_description": "Short description",
    "short_name": "Short civilization name",
    "source_png": "Source PNG",
    "source": "Source PNG",
    "spy_names": "Spy names",
    "sql": "Generated game data",
    "strategy": "Strategy text",
    "trait": "Civilization trait",
    "unit_art": "Custom unit art",
    "units": "Unique units",
    "unit_flag_source": "Unit flag PNG",
    "xml": "Generated XML",
    "yield_changes": "Yield changes",
}


_INDEXED_LOCATION_LABELS = {
    "assets": "Art asset",
    "assignments": "Promotion assignment",
    "buildings": "Unique building",
    "city_names": "City name",
    "diplomacy": "Diplomacy line",
    "domain_free_experience": "Domain experience bonus",
    "free_promotions": "Free promotion",
    "improvements": "Unique improvement",
    "localization": "Translation",
    "lua_effects": "Lua effect",
    "parameters": "Effect setting",
    "promotions_expansion_pack": "Promotion Pack assignment",
    "spy_names": "Spy name",
    "units": "Unique unit",
    "yield_changes": "Yield change",
}


_INITIALISMS = {
    "ai": "AI",
    "bnw": "BNW",
    "dds": "DDS",
    "dll": "DLL",
    "fxsxml": "FXSXML",
    "gr2": "GR2",
    "id": "ID",
    "lua": "Lua",
    "png": "PNG",
    "sql": "SQL",
    "xml": "XML",
}


def _fallback_location_label(value: str) -> str:
    words = re.split(r"[_-]+", value.strip())
    return " ".join(
        _INITIALISMS.get(word.casefold(), word.capitalize()) for word in words if word
    )


def humanize_location(location: str) -> str:
    """Turn a validator path into a label a first-time modder can understand.

    The returned text is presentation-only. Callers must retain the original
    location separately because click-to-fix navigation depends on the exact
    validator path.
    """

    raw = str(location or "").strip()
    if not raw:
        return "General project setting"

    labels: list[str] = []
    for segment in raw.split("."):
        match = re.fullmatch(r"([^\[\]]+)(?:\[(\d+)])?", segment)
        if match is None:
            labels.append(_fallback_location_label(segment))
            continue
        key = match.group(1).casefold()
        index = match.group(2)
        if index is not None:
            singular = _INDEXED_LOCATION_LABELS.get(
                key,
                _LOCATION_LABELS.get(key, _fallback_location_label(key)).rstrip("s"),
            )
            labels.append(f"{singular} {int(index) + 1}")
        else:
            labels.append(_LOCATION_LABELS.get(key, _fallback_location_label(key)))

    # Avoid phrases such as "Artwork > Art asset 1" where the indexed child
    # already says exactly what the user needs to find.
    if len(labels) >= 2 and labels[0] == "Artwork" and labels[1].startswith("Art asset "):
        labels.pop(0)
    return " › ".join(label for label in labels if label)


def step_for_location(location: str) -> int:
    """Return the workflow step most likely to own a validation location."""

    value = str(location or "").strip().casefold()
    if re.match(r"^units\[\d+]\.promotions_expansion_pack(?:\[\d+])?", value):
        return 4
    if value.startswith(("civilization", "colors")):
        return 1
    if value.startswith("leader"):
        return 2
    if value.startswith(("trait", "units", "buildings", "improvements", "mechanics")):
        return 3
    if value.startswith(("promotions_expansion", "pep", "external_promotions")):
        return 4
    if value.startswith(("art", "assets", "dds", "atlas")):
        return 5
    if value.startswith(
        (
            "advanced",
            "audio",
            "compatibility",
            "diplomacy",
            "extensions.existing_mod_import",
            "localization",
            "metadata",
            "unit_art",
        )
    ):
        return 6
    if value.startswith(("lua_effect", "lua-effects", "lua")):
        return 7
    if value.startswith(
        (
            "application",
            "build",
            "database",
            "modinfo",
            "package",
            "sql",
            "xml",
        )
    ):
        return 8
    return 0


def indexed_location(location: str) -> tuple[str, int | None, str]:
    """Split ``units[2].combat`` into a collection, index, and tail."""

    match = re.match(r"^([A-Za-z0-9_-]+)\[(\d+)](?:\.(.*))?$", str(location or ""))
    if not match:
        return str(location or ""), None, ""
    return match.group(1), int(match.group(2)), match.group(3) or ""


class ProblemsPanel(QWidget):
    """Grouped, persistent project problems with click-to-fix navigation."""

    issueActivated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._issues: list[dict[str, str]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        self.summary = QLabel("No validation results yet.")
        self.summary.setStyleSheet(f"color: {MUTED}; font-weight: 650;")
        self.first_button = QPushButton("Go to first issue")
        self.first_button.setEnabled(False)
        self.first_button.clicked.connect(self._activate_first)
        header.addWidget(self.summary, 1)
        header.addWidget(self.first_button)
        layout.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(
            ["Severity", "Field", "What needs attention", "Suggested correction"]
        )
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAccessibleName("Project validation problems")
        self.tree.setColumnWidth(0, 105)
        self.tree.setColumnWidth(1, 230)
        self.tree.setColumnWidth(2, 390)
        self.tree.header().setStretchLastSection(True)
        self.tree.itemClicked.connect(self._item_activated)
        self.tree.itemActivated.connect(self._item_activated)
        layout.addWidget(self.tree, 1)

    @property
    def issues(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(issue) for issue in self._issues)

    def set_issues(self, issues: Iterable[dict[str, str]], summary: str = "") -> None:
        self._issues = [dict(issue) for issue in issues]
        self.tree.clear()
        grouped: dict[int, list[tuple[int, dict[str, str]]]] = defaultdict(list)
        for issue_index, issue in enumerate(self._issues):
            location = issue.get("location", issue.get("field", ""))
            grouped[step_for_location(location)].append((issue_index, issue))

        colors = {"ERROR": ERROR, "WARNING": WARNING, "INFO": MUTED, "PASS": SUCCESS}
        for step_index in sorted(grouped):
            entries = grouped[step_index]
            errors = sum(
                1
                for _, issue in entries
                if issue.get("severity", issue.get("level", "INFO")).upper() == "ERROR"
            )
            warnings = sum(
                1
                for _, issue in entries
                if issue.get("severity", issue.get("level", "INFO")).upper() == "WARNING"
            )
            group = QTreeWidgetItem(
                [
                    "",
                    f"{step_index + 1}. {STEP_LABELS[step_index]}",
                    f"{errors} must fix, {warnings} suggestion(s), {len(entries)} total",
                    "",
                ]
            )
            group.setExpanded(True)
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(group)
            for issue_index, issue in entries:
                severity = issue.get("severity", issue.get("level", "INFO")).upper()
                location = issue.get("location", issue.get("field", ""))
                message = issue.get("message", "")
                hint = issue.get("hint", "")
                correction = hint or "Open this field and apply the validator's stated requirement."
                child = QTreeWidgetItem(
                    [
                        SEVERITY_LABELS.get(severity, "Note"),
                        humanize_location(location),
                        message,
                        correction,
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, location)
                child.setData(0, Qt.ItemDataRole.UserRole + 1, issue_index)
                child.setForeground(0, QColor(colors.get(severity, MUTED)))
                child.setToolTip(1, f"Technical location: {location}")
                detail = hint or issue.get("code", "")
                if detail:
                    child.setToolTip(2, detail)
                group.addChild(child)

        errors = sum(
            1
            for issue in self._issues
            if issue.get("severity", issue.get("level", "INFO")).upper() == "ERROR"
        )
        warnings = sum(
            1
            for issue in self._issues
            if issue.get("severity", issue.get("level", "INFO")).upper() == "WARNING"
        )
        if summary:
            self.summary.setText(summary)
        elif self._issues:
            self.summary.setText(
                f"{errors} must fix and {warnings} suggestion(s). Select one to open it."
            )
        else:
            self.summary.setText(
                "No current problems. Use Check and create my mod for the complete safety check."
            )
        self.summary.setStyleSheet(
            f"color: {ERROR if errors else WARNING if warnings else SUCCESS}; font-weight: 650;"
        )
        self.first_button.setEnabled(bool(self._issues))

    def _activate_first(self) -> None:
        ranked = sorted(
            self._issues,
            key=lambda item: (
                {"ERROR": 0, "WARNING": 1, "INFO": 2}.get(
                    item.get("severity", item.get("level", "INFO")).upper(), 3
                ),
                step_for_location(item.get("location", item.get("field", ""))),
            ),
        )
        if ranked:
            self.issueActivated.emit(ranked[0].get("location", ranked[0].get("field", "")))

    def _item_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        location = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(location, str):
            self.issueActivated.emit(location)
