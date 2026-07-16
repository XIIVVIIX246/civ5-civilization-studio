"""Optional advanced-workflow tools for Civilization Studio.

This module contains presentation widgets only.  File inspection, copying,
generation, and diagnostics are delegated to application services through Qt
signals so opening this page cannot mutate a mod or a game installation.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .pages import WorkflowPage
from .beginner import PageCoach
from .theme import ERROR, MUTED, SUCCESS, WARNING
from .widgets import SectionCard


SUPPORTED_LOCALES = (
    "en_US",
    "DE_DE",
    "ES_ES",
    "FR_FR",
    "IT_IT",
    "JA_JP",
    "KO_KR",
    "PL_PL",
    "RU_RU",
    "ZH_Hant_HK",
)


class AdvancedToolsPage(WorkflowPage):
    """Advanced editors and non-destructive service launch points."""

    TAB_LABELS = (
        "Import Existing Mod",
        "Diplomacy & Localization",
        "Custom 3D Unit Art",
        "Audio & Music",
        "Game Test & Logs",
        "Compatibility",
    )
    SUPPORTED_LOCALES = SUPPORTED_LOCALES

    importModRequested = Signal(str, str)
    analyzeLogsRequested = Signal(str, str)
    exportDiagnosticsRequested = Signal(str, str, str)
    scanCompatibilityRequested = Signal(str)
    importLocalizationCsvRequested = Signal(str)
    exportLocalizationCsvRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Advanced Tools (Optional)",
            "Import inspection, diplomacy text, 3D unit art, sound, logs, and compatibility tools for experienced mod authors.",
            parent,
        )
        self._loading = False
        self._units: list[dict] = []
        self._diplomacy_responses: list[str] = []

        self.coach = PageCoach(
            "You can skip this entire page",
            "None of these tools is required for a first custom civilization. Return after the basic civilization builds successfully.",
            required=False,
        )
        self.body.addWidget(self.coach)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("advancedToolsTabs")
        self.tabs.setMinimumHeight(620)
        self.tabs.addTab(self._build_import_tab(), self.TAB_LABELS[0])
        self.tabs.addTab(self._build_localization_tab(), self.TAB_LABELS[1])
        self.tabs.addTab(self._build_unit_art_tab(), self.TAB_LABELS[2])
        self.tabs.addTab(self._build_audio_tab(), self.TAB_LABELS[3])
        self.tabs.addTab(self._build_diagnostics_tab(), self.TAB_LABELS[4])
        self.tabs.addTab(self._build_compatibility_tab(), self.TAB_LABELS[5])
        self.body.addWidget(self.tabs)
        self.finish()

    # ------------------------------------------------------------------
    # Tab construction

    def _build_import_tab(self) -> QWidget:
        tab, layout = self._tab_container()
        card = SectionCard(
            "Snapshot an existing mod for inspection",
            "Choose a source mod and a destination parent for a new read-only evidence workspace.",
        )
        form = QFormLayout()
        self.import_source = QLineEdit()
        self.import_source.setPlaceholderText("Existing mod folder")
        form.addRow(
            "Source mod",
            self._path_picker(
                self.import_source,
                "Choose existing mod",
                directory=True,
            ),
        )
        self.import_destination_parent = QLineEdit()
        self.import_destination_parent.setPlaceholderText(
            "Parent folder for the new inspection workspace"
        )
        form.addRow(
            "Destination parent",
            self._path_picker(
                self.import_destination_parent,
                "Choose workspace parent",
                directory=True,
            ),
        )
        card.body.addLayout(form)
        truth = QLabel(
            "The source is read-only. Import copies source bytes into a new marked "
            "workspace as immutable inspection evidence; it never edits or deletes "
            "the original mod. Snapshot SQL, XML, Lua, DLL, and art are not included "
            "in generated builds, and imported workspaces cannot pass strict release."
        )
        self._style_truth(truth)
        card.body.addWidget(truth)
        self.import_button = QPushButton("Create inspection snapshot")
        self.import_button.setObjectName("primaryButton")
        self.import_button.clicked.connect(self._request_import)
        card.body.addWidget(self.import_button)
        self.import_result = self._result_box()
        card.body.addWidget(self.import_result)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _build_localization_tab(self) -> QWidget:
        tab, layout = self._tab_container()

        diplomacy = SectionCard(
            "English diplomacy responses",
            "Write the friendly English line used for each verified diplomacy response ID.",
        )
        self.diplomacy_table = QTableWidget(0, 2)
        self.diplomacy_table.setHorizontalHeaderLabels(["Response ID", "English line"])
        self.diplomacy_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.diplomacy_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.diplomacy_table.verticalHeader().setVisible(False)
        self.diplomacy_table.itemChanged.connect(self._table_changed)
        diplomacy.body.addWidget(self.diplomacy_table)
        diplomacy_buttons = QHBoxLayout()
        self.diplomacy_add_button = QPushButton("Add response")
        self.diplomacy_remove_button = QPushButton("Remove selected")
        self.diplomacy_add_button.clicked.connect(
            lambda: self.add_diplomacy_response()
        )
        self.diplomacy_remove_button.clicked.connect(
            lambda: self._remove_selected_rows(self.diplomacy_table)
        )
        diplomacy_buttons.addWidget(self.diplomacy_add_button)
        diplomacy_buttons.addWidget(self.diplomacy_remove_button)
        diplomacy_buttons.addStretch(1)
        diplomacy.body.addLayout(diplomacy_buttons)
        layout.addWidget(diplomacy)

        localization = SectionCard(
            "Additional localized text",
            "Add a locale, TXT_KEY tag, and text. Locale choices match BNW's supported language folders.",
        )
        self.localization_table = QTableWidget(0, 3)
        self.localization_table.setHorizontalHeaderLabels(["Locale", "Tag", "Text"])
        self.localization_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.localization_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.localization_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.localization_table.verticalHeader().setVisible(False)
        self.localization_table.itemChanged.connect(
            self._localization_item_changed
        )
        localization.body.addWidget(self.localization_table)
        buttons = QHBoxLayout()
        self.localization_add_button = QPushButton("Add localized text")
        self.localization_remove_button = QPushButton("Remove selected")
        self.localization_import_button = QPushButton("Import CSV...")
        self.localization_export_button = QPushButton("Export CSV...")
        self.localization_add_button.clicked.connect(
            lambda: self.add_localization_entry()
        )
        self.localization_remove_button.clicked.connect(
            lambda: self._remove_selected_rows(self.localization_table)
        )
        self.localization_import_button.clicked.connect(
            self._request_localization_import
        )
        self.localization_export_button.clicked.connect(
            self._request_localization_export
        )
        buttons.addWidget(self.localization_add_button)
        buttons.addWidget(self.localization_remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.localization_import_button)
        buttons.addWidget(self.localization_export_button)
        localization.body.addLayout(buttons)
        note = QLabel(
            "Text generation can be checked statically, but diplomacy timing, "
            "speaker context, and line selection still require a manual BNW test."
        )
        self._style_truth(note)
        localization.body.addWidget(note)
        self.localization_result = self._result_box()
        self.localization_result.setMaximumHeight(90)
        localization.body.addWidget(self.localization_result)
        layout.addWidget(localization)
        layout.addStretch(1)
        return tab

    def _build_unit_art_tab(self) -> QWidget:
        tab, layout = self._tab_container()
        card = SectionCard(
            "Custom 3D unit art assignments",
            "Attach one validated, project-owned FXSXML package to each current unique unit.",
        )
        self.unit_art_table = QTableWidget(0, 5)
        self.unit_art_table.setHorizontalHeaderLabels(
            ["Unique unit", "Source folder", "Root FXSXML", "Scale", "Z offset"]
        )
        self.unit_art_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.unit_art_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.unit_art_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.unit_art_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.unit_art_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.unit_art_table.verticalHeader().setVisible(False)
        card.body.addWidget(self.unit_art_table)

        buttons = QHBoxLayout()
        self.unit_art_add_button = QPushButton("Add assignment")
        self.unit_art_remove_button = QPushButton("Remove selected")
        self.unit_art_folder_button = QPushButton("Choose row folder")
        self.unit_art_fxsxml_button = QPushButton("Choose row FXSXML")
        self.unit_art_add_button.clicked.connect(
            lambda: self.add_unit_art_assignment()
        )
        self.unit_art_remove_button.clicked.connect(
            lambda: self._remove_selected_rows(self.unit_art_table)
        )
        self.unit_art_folder_button.clicked.connect(self._choose_unit_art_folder)
        self.unit_art_fxsxml_button.clicked.connect(self._choose_unit_art_fxsxml)
        buttons.addWidget(self.unit_art_add_button)
        buttons.addWidget(self.unit_art_remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.unit_art_folder_button)
        buttons.addWidget(self.unit_art_fxsxml_button)
        card.body.addLayout(buttons)

        warning = QLabel(
            "Static checks cannot prove Granny skeleton, animation, material, or "
            "Nexus compatibility. Build output must be tested with the exact unit in BNW."
        )
        self._style_truth(warning, warning=True)
        card.body.addWidget(warning)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _build_audio_tab(self) -> QWidget:
        tab, layout = self._tab_container()
        card = SectionCard(
            "Civilization audio",
            "Select portable source files for leader music and the Dawn of Man speech.",
        )
        form = QFormLayout()
        self.peace_music = QLineEdit()
        self.war_music = QLineEdit()
        self.dawn_of_man_speech = QLineEdit()
        for edit, label, title in (
            (self.peace_music, "Peace music", "Choose peace music"),
            (self.war_music, "War music", "Choose war music"),
            (
                self.dawn_of_man_speech,
                "Dawn of Man speech",
                "Choose Dawn of Man speech",
            ),
        ):
            edit.textChanged.connect(self._field_changed)
            form.addRow(
                label,
                self._path_picker(
                    edit,
                    title,
                    file_filter="Audio files (*.wav *.mp3);;All files (*)",
                ),
            )
        card.body.addLayout(form)
        warning = QLabel(
            "Container and registration checks are static. Playback, volume, "
            "looping, and codec behavior require a manual test in BNW."
        )
        self._style_truth(warning, warning=True)
        card.body.addWidget(warning)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _build_diagnostics_tab(self) -> QWidget:
        tab, layout = self._tab_container()
        card = SectionCard(
            "Game test assistant",
            "Inspect the current Civ V logs against a generated mod, then export a diagnostic packet if needed.",
        )
        form = QFormLayout()
        self.test_civ5_root = QLineEdit()
        self.test_generated_mod_root = QLineEdit()
        self.diagnostics_destination = QLineEdit()
        form.addRow(
            "Civ V user-data root",
            self._path_picker(
                self.test_civ5_root,
                "Choose Civ V user-data root",
                directory=True,
            ),
        )
        form.addRow(
            "Generated mod",
            self._path_picker(
                self.test_generated_mod_root,
                "Choose generated mod",
                directory=True,
            ),
        )
        form.addRow(
            "Diagnostic ZIP",
            self._path_picker(
                self.diagnostics_destination,
                "Choose diagnostic ZIP",
                save=True,
                file_filter="ZIP archives (*.zip)",
            ),
        )
        card.body.addLayout(form)
        actions = QHBoxLayout()
        self.analyze_logs_button = QPushButton("Analyze logs")
        self.export_diagnostics_button = QPushButton("Export diagnostics")
        self.analyze_logs_button.clicked.connect(self._request_log_analysis)
        self.export_diagnostics_button.clicked.connect(
            self._request_diagnostics_export
        )
        actions.addWidget(self.analyze_logs_button)
        actions.addWidget(self.export_diagnostics_button)
        actions.addStretch(1)
        card.body.addLayout(actions)
        truth = QLabel(
            "This tool reads logs and generated files only. It does not launch "
            "Civ V or claim an in-game pass; reproduce and verify the scenario manually."
        )
        self._style_truth(truth)
        card.body.addWidget(truth)
        self.diagnostics_result = self._result_box()
        card.body.addWidget(self.diagnostics_result)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    def _build_compatibility_tab(self) -> QWidget:
        tab, layout = self._tab_container()
        card = SectionCard(
            "Installed-mod compatibility scan",
            "Look for overlapping database Types, files, and load-order risks in a MODS folder.",
        )
        self.compatibility_mods_root = QLineEdit()
        form = QFormLayout()
        form.addRow(
            "MODS folder",
            self._path_picker(
                self.compatibility_mods_root,
                "Choose MODS folder",
                directory=True,
            ),
        )
        card.body.addLayout(form)
        self.scan_compatibility_button = QPushButton("Scan compatibility")
        self.scan_compatibility_button.clicked.connect(
            self._request_compatibility_scan
        )
        card.body.addWidget(self.scan_compatibility_button)
        truth = QLabel(
            "The scan is read-only and identifies evidence, not guaranteed "
            "compatibility. Enable the intended mod set and perform a manual BNW test."
        )
        self._style_truth(truth)
        card.body.addWidget(truth)
        self.compatibility_result = self._result_box()
        card.body.addWidget(self.compatibility_result)
        layout.addWidget(card)
        layout.addStretch(1)
        return tab

    # ------------------------------------------------------------------
    # Persisted values

    def values(self) -> dict:
        localization_entries: dict[str, dict[str, str]] = {}
        for row in range(self.localization_table.rowCount()):
            locale_widget = self.localization_table.cellWidget(row, 0)
            tag_item = self.localization_table.item(row, 1)
            text_item = self.localization_table.item(row, 2)
            if not isinstance(locale_widget, QComboBox) or tag_item is None:
                continue
            locale = locale_widget.currentText()
            tag = tag_item.text().strip()
            if locale in self.SUPPORTED_LOCALES and tag:
                localization_entries.setdefault(locale, {})[tag] = (
                    text_item.text() if text_item is not None else ""
                )

        diplomacy_text: dict[str, str] = {}
        for row in range(self.diplomacy_table.rowCount()):
            response_widget = self.diplomacy_table.cellWidget(row, 0)
            line_item = self.diplomacy_table.item(row, 1)
            if not isinstance(response_widget, QComboBox):
                continue
            response_id = str(response_widget.currentData() or "").strip()
            if response_id:
                diplomacy_text[response_id] = (
                    line_item.text() if line_item is not None else ""
                )

        assignments: list[dict] = []
        for row in range(self.unit_art_table.rowCount()):
            unit_widget = self.unit_art_table.cellWidget(row, 0)
            folder_widget = self.unit_art_table.cellWidget(row, 1)
            fxsxml_widget = self.unit_art_table.cellWidget(row, 2)
            scale_widget = self.unit_art_table.cellWidget(row, 3)
            z_widget = self.unit_art_table.cellWidget(row, 4)
            if not (
                isinstance(unit_widget, QComboBox)
                and isinstance(folder_widget, QLineEdit)
                and isinstance(fxsxml_widget, QLineEdit)
                and isinstance(scale_widget, QDoubleSpinBox)
                and isinstance(z_widget, QDoubleSpinBox)
            ):
                continue
            unit = unit_widget.currentData()
            if not isinstance(unit, dict):
                unit = {"unit_key": "", "unit_name": "", "unit_index": -1}
            assignments.append(
                {
                    "unit_key": str(unit.get("unit_key", "")),
                    "unit_name": str(unit.get("unit_name", "")),
                    "unit_index": self._as_int(unit.get("unit_index"), -1),
                    "source_folder": folder_widget.text().strip(),
                    "fxsxml": fxsxml_widget.text().strip(),
                    "scale": scale_widget.value(),
                    "z_offset": z_widget.value(),
                }
            )

        return {
            "diplomacy_text": diplomacy_text,
            "localization": {"entries": localization_entries},
            "unit_art": {"assignments": assignments},
            "audio": {
                "peace_music": self.peace_music.text().strip(),
                "war_music": self.war_music.text().strip(),
                "dawn_of_man_speech": self.dawn_of_man_speech.text().strip(),
            },
        }

    def load_values(self, data: dict) -> None:
        if not isinstance(data, dict):
            data = {}
        self._loading = True
        try:
            diplomacy = data.get("diplomacy_text", {})
            self._replace_diplomacy_rows(
                diplomacy if isinstance(diplomacy, dict) else {}
            )

            localization = data.get("localization", {})
            entries = (
                localization.get("entries", {})
                if isinstance(localization, dict)
                else {}
            )
            self.localization_table.setRowCount(0)
            if isinstance(entries, dict):
                for locale in self.SUPPORTED_LOCALES:
                    locale_entries = entries.get(locale, {})
                    if not isinstance(locale_entries, dict):
                        continue
                    for tag, text in locale_entries.items():
                        self.add_localization_entry(locale, str(tag), str(text))

            unit_art = data.get("unit_art", {})
            assignments = (
                unit_art.get("assignments", [])
                if isinstance(unit_art, dict)
                else []
            )
            self._replace_unit_art_assignments(
                assignments if isinstance(assignments, list) else []
            )

            audio = data.get("audio", {})
            if not isinstance(audio, dict):
                audio = {}
            self.peace_music.setText(str(audio.get("peace_music", "")))
            self.war_music.setText(str(audio.get("war_music", "")))
            self.dawn_of_man_speech.setText(
                str(audio.get("dawn_of_man_speech", ""))
            )
        finally:
            self._loading = False

    # ------------------------------------------------------------------
    # Diplomacy and localization editors

    def set_diplomacy_responses(self, responses: list[str]) -> None:
        current = self.values()["diplomacy_text"]
        self._diplomacy_responses = self._unique_nonempty(responses)
        self._replace_diplomacy_rows(current)

    def add_diplomacy_response(
        self, response_id: str = "", text: str = ""
    ) -> None:
        requested = str(response_id).strip()
        used = {
            str(widget.currentData() or "").strip()
            for row in range(self.diplomacy_table.rowCount())
            if isinstance(
                (widget := self.diplomacy_table.cellWidget(row, 0)), QComboBox
            )
        }
        if not requested:
            requested = next(
                (value for value in self._diplomacy_responses if value not in used),
                "",
            )
        if requested and requested in used:
            self.set_localization_result(
                f"Diplomacy response {requested} already has a row.", True
            )
            return
        row = self.diplomacy_table.rowCount()
        self.diplomacy_table.insertRow(row)
        combo = QComboBox()
        for value in self._diplomacy_responses:
            combo.addItem(value, value)
        position = combo.findData(requested) if requested else -1
        if requested and position < 0:
            combo.addItem(f"Unknown preserved: {requested}", requested)
            position = combo.count() - 1
        if combo.count() == 0:
            combo.addItem("No verified response IDs loaded", requested)
            position = 0
        combo.setCurrentIndex(max(0, position))
        combo.setProperty("last_response_id", str(combo.currentData() or ""))
        combo.currentIndexChanged.connect(
            lambda _index, widget=combo: self._diplomacy_response_changed(widget)
        )
        self.diplomacy_table.setCellWidget(row, 0, combo)
        self.diplomacy_table.setItem(row, 1, QTableWidgetItem(str(text)))
        self.diplomacy_table.setCurrentCell(row, 1)
        if not self._loading:
            self.changed.emit()

    def add_localization_entry(
        self, locale: str = "en_US", tag: str = "", text: str = ""
    ) -> None:
        locale = locale if locale in self.SUPPORTED_LOCALES else "en_US"
        tag = str(tag)
        if tag and self._localization_key_exists(locale, tag):
            self.set_localization_result(
                f"Localization entry {locale}/{tag} already has a row.", True
            )
            return
        row = self.localization_table.rowCount()
        self.localization_table.insertRow(row)
        combo = QComboBox()
        combo.addItems(self.SUPPORTED_LOCALES)
        combo.setCurrentText(locale)
        combo.setProperty("last_locale", locale)
        combo.currentTextChanged.connect(
            lambda _text, widget=combo: self._localization_locale_changed(widget)
        )
        self.localization_table.setCellWidget(row, 0, combo)
        tag_item = QTableWidgetItem(tag)
        tag_item.setData(Qt.ItemDataRole.UserRole, tag)
        self.localization_table.setItem(row, 1, tag_item)
        self.localization_table.setItem(row, 2, QTableWidgetItem(str(text)))
        self.localization_table.setCurrentCell(row, 1)
        if not self._loading:
            self.changed.emit()

    def set_localization_entries(self, entries: dict) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.localization_table.setRowCount(0)
            for locale in self.SUPPORTED_LOCALES:
                values = entries.get(locale, {}) if isinstance(entries, dict) else {}
                if not isinstance(values, dict):
                    continue
                for tag, text in values.items():
                    self.add_localization_entry(locale, str(tag), str(text))
        finally:
            self._loading = was_loading
        if not self._loading:
            self.changed.emit()

    def set_localization_result(self, text: str, is_error: bool = False) -> None:
        self._set_result(self.localization_result, text, is_error)

    def _replace_diplomacy_rows(self, values: dict) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.diplomacy_table.setRowCount(0)
            for response_id, line in values.items():
                self.add_diplomacy_response(str(response_id), str(line))
        finally:
            self._loading = was_loading

    # ------------------------------------------------------------------
    # Unit art editor

    def set_units(self, units: list[dict]) -> None:
        current = self.values()["unit_art"]["assignments"]
        normalized: list[dict] = []
        for raw in units:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind", "unit")).strip().lower()
            if kind and kind != "unit":
                continue
            fallback_index = len(normalized)
            normalized.append(
                {
                    "unit_key": str(raw.get("unit_key", raw.get("key", ""))),
                    "unit_name": str(raw.get("unit_name", raw.get("name", ""))),
                    "unit_index": self._as_int(
                        raw.get("unit_index", fallback_index), fallback_index
                    ),
                }
            )
        self._units = normalized
        self._replace_unit_art_assignments(current)

    def add_unit_art_assignment(self, value: dict | None = None) -> None:
        assignment = dict(value or {})
        requested_unit = {
            "unit_key": str(assignment.get("unit_key", "")),
            "unit_name": str(assignment.get("unit_name", "")),
            "unit_index": self._as_int(assignment.get("unit_index"), -1),
        }
        row = self.unit_art_table.rowCount()
        self.unit_art_table.insertRow(row)

        unit_combo = QComboBox()
        for unit in self._units:
            unit_combo.addItem(self._unit_label(unit), dict(unit))
        match = self._find_unit(requested_unit)
        if match is not None:
            position = next(
                index
                for index in range(unit_combo.count())
                if unit_combo.itemData(index) == match
            )
        else:
            preserved = dict(requested_unit)
            label = (
                f"Unresolved: {self._unit_label(preserved)}"
                if any(
                    (
                        preserved["unit_key"],
                        preserved["unit_name"],
                        preserved["unit_index"] >= 0,
                    )
                )
                else "No unit selected"
            )
            unit_combo.addItem(label, preserved)
            position = unit_combo.count() - 1
        unit_combo.setCurrentIndex(position)
        unit_combo.currentIndexChanged.connect(self._field_changed)

        folder = QLineEdit(str(assignment.get("source_folder", "")))
        fxsxml = QLineEdit(str(assignment.get("fxsxml", "")))
        folder.setPlaceholderText("Project-owned package folder")
        fxsxml.setPlaceholderText("Root .fxsxml file")
        folder.textChanged.connect(self._field_changed)
        fxsxml.textChanged.connect(self._field_changed)

        scale = QDoubleSpinBox()
        scale.setRange(0.01, 100.0)
        scale.setDecimals(4)
        scale.setSingleStep(0.05)
        scale.setValue(self._as_float(assignment.get("scale"), 1.0))
        scale.valueChanged.connect(self._field_changed)
        z_offset = QDoubleSpinBox()
        z_offset.setRange(-100.0, 100.0)
        z_offset.setDecimals(4)
        z_offset.setSingleStep(0.05)
        z_offset.setValue(self._as_float(assignment.get("z_offset"), 0.0))
        z_offset.valueChanged.connect(self._field_changed)

        for column, widget in enumerate(
            (unit_combo, folder, fxsxml, scale, z_offset)
        ):
            self.unit_art_table.setCellWidget(row, column, widget)
        self.unit_art_table.setCurrentCell(row, 0)
        if not self._loading:
            self.changed.emit()

    def _replace_unit_art_assignments(self, assignments: list) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.unit_art_table.setRowCount(0)
            for assignment in assignments:
                if isinstance(assignment, dict):
                    self.add_unit_art_assignment(assignment)
        finally:
            self._loading = was_loading

    def _find_unit(self, requested: dict) -> dict | None:
        key = str(requested.get("unit_key", ""))
        name = str(requested.get("unit_name", ""))
        index = self._as_int(requested.get("unit_index"), -1)
        if key:
            match = next((unit for unit in self._units if unit["unit_key"] == key), None)
            if match is not None:
                return match
        if name:
            match = next(
                (unit for unit in self._units if unit["unit_name"] == name), None
            )
            if match is not None:
                return match
        if index >= 0:
            return next(
                (unit for unit in self._units if unit["unit_index"] == index), None
            )
        return None

    @staticmethod
    def _unit_label(unit: dict) -> str:
        name = str(unit.get("unit_name", "")).strip()
        key = str(unit.get("unit_key", "")).strip()
        index = AdvancedToolsPage._as_int(unit.get("unit_index"), -1)
        if name and key:
            return f"{name} ({key})"
        if name or key:
            return name or key
        return f"Unique unit {index + 1}" if index >= 0 else "Unknown unit"

    def _choose_unit_art_folder(self) -> None:
        row = self.unit_art_table.currentRow()
        edit = self.unit_art_table.cellWidget(row, 1) if row >= 0 else None
        if isinstance(edit, QLineEdit):
            self._choose_path(edit, "Choose 3D art package", directory=True)

    def _choose_unit_art_fxsxml(self) -> None:
        row = self.unit_art_table.currentRow()
        edit = self.unit_art_table.cellWidget(row, 2) if row >= 0 else None
        if isinstance(edit, QLineEdit):
            self._choose_path(
                edit,
                "Choose root FXSXML",
                file_filter="Civ V unit art (*.fxsxml);;All files (*)",
            )

    # ------------------------------------------------------------------
    # Operational actions and result display

    def _request_import(self) -> None:
        self.importModRequested.emit(
            self.import_source.text().strip(),
            self.import_destination_parent.text().strip(),
        )

    def _request_log_analysis(self) -> None:
        self.analyzeLogsRequested.emit(
            self.test_civ5_root.text().strip(),
            self.test_generated_mod_root.text().strip(),
        )

    def _request_diagnostics_export(self) -> None:
        self.exportDiagnosticsRequested.emit(
            self.test_civ5_root.text().strip(),
            self.test_generated_mod_root.text().strip(),
            self.diagnostics_destination.text().strip(),
        )

    def _request_compatibility_scan(self) -> None:
        self.scanCompatibilityRequested.emit(
            self.compatibility_mods_root.text().strip()
        )

    def _request_localization_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import localization CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if path:
            self.importLocalizationCsvRequested.emit(path)

    def _request_localization_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export localization CSV",
            "localization.csv",
            "CSV files (*.csv)",
        )
        if path:
            self.exportLocalizationCsvRequested.emit(path)

    def set_import_result(self, text: str, is_error: bool = False) -> None:
        self._set_result(self.import_result, text, is_error)

    def set_diagnostics_result(self, text: str, is_error: bool = False) -> None:
        self._set_result(self.diagnostics_result, text, is_error)

    def set_compatibility_result(self, text: str, is_error: bool = False) -> None:
        self._set_result(self.compatibility_result, text, is_error)

    # ------------------------------------------------------------------
    # Small UI helpers

    @staticmethod
    def _tab_container() -> tuple[QWidget, QVBoxLayout]:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)
        return tab, layout

    def _path_picker(
        self,
        edit: QLineEdit,
        title: str,
        *,
        directory: bool = False,
        save: bool = False,
        file_filter: str = "All files (*)",
    ) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        choose = QPushButton("Choose")
        choose.clicked.connect(
            lambda: self._choose_path(
                edit,
                title,
                directory=directory,
                save=save,
                file_filter=file_filter,
            )
        )
        row.addWidget(edit, 1)
        row.addWidget(choose)
        return holder

    def _choose_path(
        self,
        edit: QLineEdit,
        title: str,
        *,
        directory: bool = False,
        save: bool = False,
        file_filter: str = "All files (*)",
    ) -> None:
        start = edit.text().strip()
        if directory:
            value = QFileDialog.getExistingDirectory(self, title, start)
        elif save:
            value, _ = QFileDialog.getSaveFileName(
                self, title, start, file_filter
            )
        else:
            value, _ = QFileDialog.getOpenFileName(
                self, title, start, file_filter
            )
        if value:
            edit.setText(value)

    def _remove_selected_rows(self, table: QTableWidget) -> None:
        selected = {index.row() for index in table.selectedIndexes()}
        if not selected and table.currentRow() >= 0:
            selected.add(table.currentRow())
        rows = sorted(selected, reverse=True)
        for row in rows:
            table.removeRow(row)
        if rows and not self._loading:
            self.changed.emit()

    def _table_changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def _diplomacy_response_changed(self, combo: QComboBox) -> None:
        if self._loading:
            return
        row = next(
            (
                index
                for index in range(self.diplomacy_table.rowCount())
                if self.diplomacy_table.cellWidget(index, 0) is combo
            ),
            -1,
        )
        selected = str(combo.currentData() or "").strip()
        duplicate = any(
            index != row
            and isinstance(
                (other := self.diplomacy_table.cellWidget(index, 0)), QComboBox
            )
            and str(other.currentData() or "").strip() == selected
            for index in range(self.diplomacy_table.rowCount())
        )
        if selected and duplicate:
            previous = str(combo.property("last_response_id") or "")
            with QSignalBlocker(combo):
                combo.setCurrentIndex(max(0, combo.findData(previous)))
            self.set_localization_result(
                f"Diplomacy response {selected} already has a row; the duplicate "
                "selection was reverted.",
                True,
            )
            return
        combo.setProperty("last_response_id", selected)
        self.changed.emit()

    def _localization_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        if item.column() == 1:
            combo = self.localization_table.cellWidget(item.row(), 0)
            locale = combo.currentText() if isinstance(combo, QComboBox) else ""
            tag = item.text().strip()
            if tag and self._localization_key_exists(
                locale, tag, exclude_row=item.row()
            ):
                previous = str(item.data(Qt.ItemDataRole.UserRole) or "")
                with QSignalBlocker(self.localization_table):
                    item.setText(previous)
                self.set_localization_result(
                    f"Localization entry {locale}/{tag} already has a row; the "
                    "duplicate tag was reverted.",
                    True,
                )
                return
            item.setData(Qt.ItemDataRole.UserRole, tag)
        self.changed.emit()

    def _localization_locale_changed(self, combo: QComboBox) -> None:
        if self._loading:
            return
        row = next(
            (
                index
                for index in range(self.localization_table.rowCount())
                if self.localization_table.cellWidget(index, 0) is combo
            ),
            -1,
        )
        tag_item = self.localization_table.item(row, 1) if row >= 0 else None
        locale = combo.currentText()
        tag = tag_item.text().strip() if tag_item is not None else ""
        if tag and self._localization_key_exists(locale, tag, exclude_row=row):
            previous = str(combo.property("last_locale") or "en_US")
            with QSignalBlocker(combo):
                combo.setCurrentText(previous)
            self.set_localization_result(
                f"Localization entry {locale}/{tag} already has a row; the "
                "duplicate locale was reverted.",
                True,
            )
            return
        combo.setProperty("last_locale", locale)
        self.changed.emit()

    def _localization_key_exists(
        self, locale: str, tag: str, *, exclude_row: int = -1
    ) -> bool:
        for row in range(self.localization_table.rowCount()):
            if row == exclude_row:
                continue
            combo = self.localization_table.cellWidget(row, 0)
            item = self.localization_table.item(row, 1)
            if (
                isinstance(combo, QComboBox)
                and item is not None
                and combo.currentText() == locale
                and item.text().strip() == tag
            ):
                return True
        return False

    def _field_changed(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    @staticmethod
    def _result_box() -> QPlainTextEdit:
        result = QPlainTextEdit()
        result.setReadOnly(True)
        result.setMaximumHeight(145)
        result.setPlaceholderText("No operation has been run.")
        return result

    @staticmethod
    def _set_result(
        widget: QPlainTextEdit, value: str, is_error: bool
    ) -> None:
        widget.setPlainText(str(value))
        widget.setStyleSheet(f"color: {ERROR if is_error else SUCCESS};")

    @staticmethod
    def _style_truth(label: QLabel, warning: bool = False) -> None:
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {WARNING if warning else MUTED};")

    @staticmethod
    def _unique_nonempty(values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = str(raw).strip()
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    @staticmethod
    def _as_int(value: object, default: int) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_float(value: object, default: float) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
