"""Searchable two-slot selector for compiled civilization Lua effects.

The page consumes plain catalog dictionaries supplied by the application
controller.  It deliberately does not import domain models or write files.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .pages import WorkflowPage
from .beginner import PageCoach
from .theme import MUTED, SUCCESS, WARNING
from .widgets import SectionCard


class LuaEffectsPage(WorkflowPage):
    """Choose at most two catalog-backed effects for one civilization."""

    MAX_SELECTIONS = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Extra Gameplay Effects (Optional)",
            "Choose up to two extra scripted bonuses. Studio creates the code, but you must test every selected effect in a new Brave New World game.",
            parent,
        )
        self._expert_mode = False
        self.coach = PageCoach(
            "Safe to skip for your first civilization",
            "The built-in trait bonus on Abilities & Uniques is enough for a complete civilization. Come back here when you want an additional advanced effect.",
            required=False,
        )
        self.body.addWidget(self.coach)
        self._loading = False
        self._catalog: dict[str, dict] = {}
        self._ordered_ids: list[str] = []
        self._slot_states: list[dict] = [{}, {}]
        self._overflow_selections: list[dict] = []
        self._favorite_ids: set[str] = set()
        self._recent_ids: list[str] = []
        self._preview_effect_id = ""
        self._active_slot_index = 0

        self.browse_card = SectionCard(
            "Browse 200 ready-made effects",
            "Search in plain language, preview what an effect does, then place it in Effect 1 or Effect 2. Favorites and recent choices are only browsing aids.",
        )
        browse_filters = QGridLayout()
        browse_filters.setColumnStretch(1, 1)
        browse_filters.setColumnStretch(3, 1)
        self.category_filter = QComboBox()
        self.category_filter.addItem("All categories", "")
        self.trigger_filter = QComboBox()
        self.trigger_filter.addItem("All triggers", "")
        self.origin_filter = QComboBox()
        self.origin_filter.addItem("All origins", "")
        self.timing_filter = QComboBox()
        self.timing_filter.addItem("All timing", "")
        self.catalog_search = QLineEdit()
        self.catalog_search.setClearButtonEnabled(True)
        self.catalog_search.setPlaceholderText(
            "Try: coastal, conquest, faith, policy, healing..."
        )
        self.favorites_only = QCheckBox("Favorites only (0)")
        self.recent_only = QCheckBox("Recent only (0)")
        self.view_mode = QComboBox()
        self.view_mode.addItem("Card view", "cards")
        self.view_mode.addItem("Compact list", "list")
        self.catalog_count = QLabel("Catalog has not been loaded yet.")
        self.catalog_count.setStyleSheet(f"color: {MUTED};")
        browse_filters.addWidget(QLabel("Category"), 0, 0)
        browse_filters.addWidget(self.category_filter, 0, 1)
        browse_filters.addWidget(QLabel("Trigger"), 0, 2)
        browse_filters.addWidget(self.trigger_filter, 0, 3)
        browse_filters.addWidget(QLabel("Origin"), 1, 0)
        browse_filters.addWidget(self.origin_filter, 1, 1)
        browse_filters.addWidget(QLabel("Timing"), 1, 2)
        browse_filters.addWidget(self.timing_filter, 1, 3)
        browse_filters.addWidget(QLabel("Find effects"), 2, 0)
        browse_filters.addWidget(self.catalog_search, 2, 1, 1, 3)
        filter_toggles = QHBoxLayout()
        filter_toggles.addWidget(self.favorites_only)
        filter_toggles.addWidget(self.recent_only)
        filter_toggles.addStretch(1)
        filter_toggles.addWidget(QLabel("Display"))
        filter_toggles.addWidget(self.view_mode)
        self.browse_card.body.addLayout(browse_filters)
        self.browse_card.body.addLayout(filter_toggles)
        self.browse_card.body.addWidget(self.catalog_count)

        self.effect_browser = QListWidget()
        self.effect_browser.setAccessibleName("Lua effect catalog explorer")
        self.effect_browser.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        self.effect_browser.setMinimumHeight(270)
        self.effect_browser.setWordWrap(True)
        self.effect_browser.setUniformItemSizes(True)
        self.effect_list = self.effect_browser
        self.browse_card.body.addWidget(self.effect_browser)

        browser_preview = QFrame()
        browser_preview.setFrameShape(QFrame.Shape.StyledPanel)
        browser_preview_layout = QVBoxLayout(browser_preview)
        browser_preview_layout.setContentsMargins(12, 10, 12, 10)
        preview_heading = QLabel("Effect preview")
        preview_heading.setStyleSheet("font-weight: 650;")
        self.explorer_details = QLabel(
            "Select an effect to see its description, provenance, and runtime cadence."
        )
        self.explorer_details.setWordWrap(True)
        self.explorer_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.explorer_details.setStyleSheet(f"color: {MUTED};")
        self.explorer_compatibility = QLabel(
            "Compatibility guidance appears after an effect is selected."
        )
        self.explorer_compatibility.setWordWrap(True)
        self.explorer_compatibility.setStyleSheet(f"color: {MUTED};")
        browser_actions = QHBoxLayout()
        self.favorite_button = QPushButton("Add favorite")
        self.favorite_button.setCheckable(True)
        self.favorite_button.setEnabled(False)
        self.use_slot_buttons: list[QPushButton] = []
        browser_actions.addWidget(self.favorite_button)
        browser_actions.addStretch(1)
        for slot_index in range(self.MAX_SELECTIONS):
            button = QPushButton(f"Use as Effect {slot_index + 1}")
            button.setEnabled(False)
            button.clicked.connect(
                lambda _checked=False, slot_index=slot_index: self._assign_preview(
                    slot_index
                )
            )
            self.use_slot_buttons.append(button)
            browser_actions.addWidget(button)
        browser_preview_layout.addWidget(preview_heading)
        browser_preview_layout.addWidget(self.explorer_details)
        browser_preview_layout.addWidget(self.explorer_compatibility)
        browser_preview_layout.addLayout(browser_actions)
        self.browse_card.body.addWidget(browser_preview)
        self.body.addWidget(self.browse_card)

        selection = SectionCard(
            "Compare two civilization effects",
            "Selections are shown side by side, versioned, and saved in the portable "
            "project. Compatibility is enforced from catalog declarations; synergy "
            "guidance is advisory and should be balance-tested in Brave New World.",
        )
        self.slot_combos: list[QComboBox] = []
        self.clear_buttons: list[QPushButton] = []
        self.detail_labels: list[QLabel] = []
        slots = QHBoxLayout()
        slots.setSpacing(12)
        for slot_index in range(self.MAX_SELECTIONS):
            slot = QFrame()
            slot.setFrameShape(QFrame.Shape.StyledPanel)
            slot_layout = QVBoxLayout(slot)
            slot_layout.setContentsMargins(12, 10, 12, 10)
            heading = QLabel(f"Effect {slot_index + 1}")
            heading.setStyleSheet("font-weight: 650;")
            combo = QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setMinimumContentsLength(30)
            combo.setAccessibleName(f"Lua effect slot {slot_index + 1}")
            combo.lineEdit().setPlaceholderText("Choose or type to search the catalog")
            completer = combo.completer()
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            clear = QPushButton("Clear slot")
            clear.setEnabled(False)
            details = QLabel("No effect selected.")
            details.setWordWrap(True)
            details.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            details.setStyleSheet(f"color: {MUTED};")
            slot_layout.addWidget(heading)
            slot_layout.addWidget(combo)
            slot_layout.addWidget(clear, 0, Qt.AlignmentFlag.AlignLeft)
            slot_layout.addWidget(details)
            slot_layout.addStretch(1)
            slots.addWidget(slot, 1)
            self.slot_combos.append(combo)
            self.clear_buttons.append(clear)
            self.detail_labels.append(details)
            combo.currentIndexChanged.connect(
                lambda index, slot_index=slot_index: self._selection_changed(
                    slot_index, index
                )
            )
            clear.clicked.connect(
                lambda _checked=False, slot_index=slot_index: self.clear_slot(
                    slot_index
                )
            )
            combo.completer().activated[str].connect(
                lambda text, slot_index=slot_index: self._commit_combo_text(
                    slot_index, text
                )
            )
            combo.lineEdit().editingFinished.connect(
                lambda slot_index=slot_index: self._commit_combo_text(
                    slot_index, self.slot_combos[slot_index].currentText()
                )
            )
        self.pair_status = QLabel("0 of 2 effects selected.")
        self.pair_status.setWordWrap(True)
        self.pair_status.setStyleSheet(f"color: {MUTED}; font-weight: 650;")
        self.pair_guidance = QLabel(
            "Choose a second effect to see advisory synergy and coverage guidance."
        )
        self.pair_guidance.setWordWrap(True)
        self.pair_guidance.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.pair_guidance.setStyleSheet(f"color: {MUTED};")
        selection.body.addLayout(slots)
        selection.body.addWidget(self.pair_status)
        selection.body.addWidget(self.pair_guidance)
        self.remove_overflow_button = QPushButton(
            "Remove extra preserved selections"
        )
        self.remove_overflow_button.setVisible(False)
        self.remove_overflow_button.clicked.connect(self._remove_overflow)
        selection.body.addWidget(self.remove_overflow_button)
        self.body.addWidget(selection)

        self.runtime_card = SectionCard(
            "Technical testing contract",
            "Extra effects run through Studio's guarded BNW script. A project using them is conservatively marked as affecting saves and single-player only until the exact build is tested.",
        )
        caveat = QLabel(
            "Test the generated civilization in Brave New World / Expansion2. "
            "The manifest records each effect ID, version, trigger, origin, and runtime notes."
        )
        caveat.setWordWrap(True)
        caveat.setStyleSheet(f"color: {WARNING};")
        self.runtime_card.body.addWidget(caveat)
        self.body.addWidget(self.runtime_card)
        self.finish()

        self.category_filter.currentIndexChanged.connect(self._filter_changed)
        self.trigger_filter.currentIndexChanged.connect(self._filter_changed)
        self.origin_filter.currentIndexChanged.connect(self._filter_changed)
        self.timing_filter.currentIndexChanged.connect(self._filter_changed)
        self.catalog_search.textChanged.connect(self._filter_changed)
        self.favorites_only.toggled.connect(self._filter_changed)
        self.recent_only.toggled.connect(self._filter_changed)
        self.view_mode.currentIndexChanged.connect(self._view_mode_changed)
        self.effect_browser.currentItemChanged.connect(
            self._browser_selection_changed
        )
        self.effect_browser.itemDoubleClicked.connect(
            self._browser_item_activated
        )
        self.favorite_button.clicked.connect(self._toggle_favorite)
        self._configure_browser_view()
        self.set_expert_mode(False)

    def set_expert_mode(self, expert: bool) -> None:
        self._expert_mode = bool(expert)
        self.runtime_card.setVisible(bool(expert))

    def set_catalog(self, entries: list[dict]) -> None:
        """Replace the plain-dictionary catalog without changing selections."""

        self._catalog = {}
        self._ordered_ids = []
        for raw in entries:
            if not isinstance(raw, dict):
                continue
            item = deepcopy(raw)
            effect_id = str(item.get("effect_id", "")).strip()
            if not effect_id or effect_id in self._catalog:
                continue
            item["effect_id"] = effect_id
            self._catalog[effect_id] = item
            self._ordered_ids.append(effect_id)

        categories = sorted(
            {
                str(item.get("category", "")).strip()
                for item in self._catalog.values()
                if str(item.get("category", "")).strip()
            },
            key=str.casefold,
        )
        triggers = sorted(
            {
                str(item.get("trigger", "")).strip()
                for item in self._catalog.values()
                if str(item.get("trigger", "")).strip()
            },
            key=str.casefold,
        )
        origins = sorted(
            {
                str(item.get("origin", "")).strip()
                for item in self._catalog.values()
                if str(item.get("origin", "")).strip()
            },
            key=str.casefold,
        )
        timings = sorted(
            {self._timing_key(item) for item in self._catalog.values()},
            key=lambda value: self._timing_label(value).casefold(),
        )
        self._populate_filter(
            self.category_filter, "All categories", categories
        )
        self._populate_filter(self.trigger_filter, "All triggers", triggers)
        self._populate_filter(
            self.origin_filter,
            "All origins",
            origins,
            display=self._display_origin,
        )
        self._populate_filter(
            self.timing_filter,
            "All timing",
            timings,
            display=self._timing_label,
        )
        self._favorite_ids.intersection_update(self._catalog)
        self._recent_ids = [
            effect_id
            for effect_id in self._recent_ids
            if effect_id in self._catalog
        ]
        if self._preview_effect_id not in self._catalog:
            self._preview_effect_id = ""
        self._update_filter_labels()
        self._rebuild_combos()

    def values(self) -> dict:
        return {
            "selections": [
                deepcopy(state)
                for state in self._slot_states
                if str(state.get("effect_id", "")).strip()
            ]
            + deepcopy(self._overflow_selections)
        }

    def load_values(self, data: dict) -> None:
        raw = data.get("selections", []) if isinstance(data, dict) else []
        selections = [deepcopy(item) for item in raw if isinstance(item, dict)]
        self._loading = True
        try:
            self._slot_states = [{}, {}]
            for index, selection in enumerate(selections[: self.MAX_SELECTIONS]):
                self._slot_states[index] = self._selection_state(selection)
                self._record_recent(
                    str(self._slot_states[index].get("effect_id", ""))
                )
            self._overflow_selections = deepcopy(
                selections[self.MAX_SELECTIONS :]
            )
            self._rebuild_combos()
        finally:
            self._loading = False

    def clear_slot(self, slot_index: int) -> None:
        if not 0 <= slot_index < self.MAX_SELECTIONS:
            return
        if not self._slot_states[slot_index]:
            return
        self._active_slot_index = slot_index
        self._slot_states[slot_index] = (
            self._selection_state(self._overflow_selections.pop(0))
            if self._overflow_selections
            else {}
        )
        self._record_recent(
            str(self._slot_states[slot_index].get("effect_id", ""))
        )
        self._rebuild_combos()
        if not self._loading:
            self.changed.emit()

    def _filter_changed(self, *_args) -> None:
        self._rebuild_combos()

    def _selection_changed(self, slot_index: int, item_index: int) -> None:
        if self._loading or item_index < 0:
            return
        self._active_slot_index = slot_index
        combo = self.slot_combos[slot_index]
        effect_id = str(combo.itemData(item_index) or "").strip()
        if not effect_id:
            return
        self._assign_effect(slot_index, effect_id)

    def _assign_effect(self, slot_index: int, effect_id: str) -> bool:
        """Assign a known, compatible effect without changing generation shape."""

        effect_id = str(effect_id).strip()
        if not 0 <= slot_index < self.MAX_SELECTIONS:
            return False
        if effect_id not in self._catalog:
            return False
        self._active_slot_index = slot_index
        current_id = str(
            self._slot_states[slot_index].get("effect_id", "")
        ).strip()
        if effect_id == current_id:
            self._record_recent(effect_id)
            self._rebuild_browser()
            return True
        other_id = str(
            self._slot_states[1 - slot_index].get("effect_id", "")
        ).strip()
        if other_id and not self._are_compatible(effect_id, other_id):
            self._update_explorer_preview(effect_id)
            return False
        entry = self._catalog[effect_id]
        defaults = entry.get("default_parameters", {})
        self._slot_states[slot_index] = {
            "instance_id": str(uuid4()),
            "effect_id": effect_id,
            "effect_version": self._integer(entry.get("version"), 1),
            "parameters": deepcopy(defaults if isinstance(defaults, dict) else {}),
        }
        self._record_recent(effect_id)
        self._rebuild_combos()
        if not self._loading:
            self.changed.emit()
        return True

    def _assign_preview(self, slot_index: int) -> None:
        if self._preview_effect_id:
            self._assign_effect(slot_index, self._preview_effect_id)

    def _browser_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        effect_id = (
            str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
            if current is not None
            else ""
        )
        self._preview_effect_id = effect_id
        self._update_explorer_preview(effect_id)

    def _browser_item_activated(self, item: QListWidgetItem) -> None:
        effect_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not effect_id:
            return
        empty_slots = [
            index for index, state in enumerate(self._slot_states) if not state
        ]
        slot_index = empty_slots[0] if empty_slots else self._active_slot_index
        self._assign_effect(slot_index, effect_id)

    def _toggle_favorite(self, _checked: bool = False) -> None:
        effect_id = self._preview_effect_id
        if effect_id not in self._catalog:
            return
        if effect_id in self._favorite_ids:
            self._favorite_ids.remove(effect_id)
        else:
            self._favorite_ids.add(effect_id)
        self._update_filter_labels()
        self._rebuild_combos()

    def _record_recent(self, effect_id: str) -> None:
        effect_id = str(effect_id).strip()
        if effect_id not in self._catalog:
            return
        self._recent_ids = [
            recent_id
            for recent_id in self._recent_ids
            if recent_id != effect_id
        ]
        self._recent_ids.insert(0, effect_id)
        del self._recent_ids[12:]
        self._update_filter_labels()

    def _view_mode_changed(self, *_args) -> None:
        self._configure_browser_view()
        self._rebuild_browser()

    def _configure_browser_view(self) -> None:
        cards = str(self.view_mode.currentData() or "cards") == "cards"
        self.effect_browser.setMovement(QListView.Movement.Static)
        self.effect_browser.setResizeMode(QListView.ResizeMode.Adjust)
        self.effect_browser.setSpacing(6 if cards else 2)
        self.effect_browser.setViewMode(
            QListView.ViewMode.IconMode if cards else QListView.ViewMode.ListMode
        )
        self.effect_browser.setWrapping(cards)
        self.effect_browser.setGridSize(QSize(270, 92) if cards else QSize())

    def _rebuild_browser(self) -> None:
        if not hasattr(self, "effect_browser"):
            return
        visible_ids = self._filtered_catalog_ids()
        requested_preview = self._preview_effect_id
        cards = str(self.view_mode.currentData() or "cards") == "cards"
        selected_item: QListWidgetItem | None = None
        with QSignalBlocker(self.effect_browser):
            self.effect_browser.clear()
            for effect_id in visible_ids:
                entry = self._catalog[effect_id]
                item = QListWidgetItem(self._browser_item_text(entry, cards))
                item.setData(Qt.ItemDataRole.UserRole, effect_id)
                item.setToolTip(self._browser_tooltip(entry))
                item.setSizeHint(QSize(258, 80) if cards else QSize(0, 32))
                self.effect_browser.addItem(item)
                if effect_id == requested_preview:
                    selected_item = item
            if selected_item is None and self.effect_browser.count():
                selected_item = self.effect_browser.item(0)
            if selected_item is not None:
                self.effect_browser.setCurrentItem(selected_item)
        self._preview_effect_id = (
            str(selected_item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if selected_item is not None
            else ""
        )
        categories = {
            str(item.get("category", "")).strip()
            for item in self._catalog.values()
            if str(item.get("category", "")).strip()
        }
        self.catalog_count.setText(
            f"Showing {len(visible_ids)} of {len(self._catalog)} versioned effects "
            f"across {len(categories)} categories - {len(self._favorite_ids)} favorite(s), "
            f"{len(self._recent_ids)} recent."
        )
        self._update_explorer_preview(self._preview_effect_id)

    def _update_explorer_preview(self, effect_id: str) -> None:
        entry = self._catalog.get(effect_id)
        if entry is None:
            self.explorer_details.setText(
                "No effects match the current filters. Clear a filter to continue browsing."
            )
            self.explorer_details.setStyleSheet(f"color: {MUTED};")
            self.explorer_compatibility.setText(
                "Compatibility guidance appears after an effect is selected."
            )
            self.explorer_compatibility.setStyleSheet(f"color: {MUTED};")
            self.favorite_button.setEnabled(False)
            self.favorite_button.setChecked(False)
            self.favorite_button.setText("Add favorite")
            for slot_index, button in enumerate(self.use_slot_buttons):
                button.setEnabled(False)
                button.setText(f"Use as Effect {slot_index + 1}")
            return

        label = str(entry.get("label", effect_id)).strip() or effect_id
        category = str(entry.get("category", "Uncategorized")).strip()
        trigger = str(entry.get("trigger", "Unspecified")).strip()
        timing = self._timing_label(self._timing_key(entry))
        origin = self._display_origin(str(entry.get("origin", "")))
        inspiration = str(entry.get("inspiration", "")).strip()
        description = str(entry.get("description", "")).strip()
        runtime_notes = str(entry.get("runtime_notes", "")).strip()
        provenance = origin + (f" - {inspiration}" if inspiration else "")
        preview_lines = [
            f"{label} ({effect_id})",
            description,
            f"Category: {category} - Trigger: {trigger} - Timing: {timing}",
            f"Origin: {provenance}",
        ]
        if runtime_notes:
            preview_lines.append(f"Runtime note: {runtime_notes}")
        self.explorer_details.setText("\n".join(preview_lines))
        self.explorer_details.setStyleSheet(f"color: {SUCCESS};")

        slot_messages: list[str] = []
        any_blocked = False
        for slot_index, button in enumerate(self.use_slot_buttons):
            current_id = str(
                self._slot_states[slot_index].get("effect_id", "")
            ).strip()
            other_id = str(
                self._slot_states[1 - slot_index].get("effect_id", "")
            ).strip()
            if effect_id == current_id:
                button.setEnabled(False)
                button.setText(f"Selected in Effect {slot_index + 1}")
                slot_messages.append(
                    f"Effect {slot_index + 1}: already selected."
                )
            elif other_id and not self._are_compatible(effect_id, other_id):
                button.setEnabled(False)
                button.setText(f"Blocked for Effect {slot_index + 1}")
                other_label = self._effect_name(other_id)
                slot_messages.append(
                    f"Effect {slot_index + 1}: blocked by {other_label}."
                )
                any_blocked = True
            else:
                button.setEnabled(True)
                button.setText(f"Use as Effect {slot_index + 1}")
                action = "replace the current choice" if current_id else "available"
                slot_messages.append(f"Effect {slot_index + 1}: {action}.")
        self.explorer_compatibility.setText(
            "Deterministic catalog compatibility - " + " ".join(slot_messages)
        )
        self.explorer_compatibility.setStyleSheet(
            f"color: {WARNING if any_blocked else SUCCESS};"
        )
        favorite = effect_id in self._favorite_ids
        self.favorite_button.setEnabled(True)
        self.favorite_button.setChecked(favorite)
        self.favorite_button.setText(
            "Remove favorite" if favorite else "Add favorite"
        )

    def _rebuild_combos(self) -> None:
        for slot_index, combo in enumerate(self.slot_combos):
            selected_id = str(
                self._slot_states[slot_index].get("effect_id", "")
            ).strip()
            with QSignalBlocker(combo):
                combo.clear()
                for effect_id in self._visible_ids(slot_index):
                    entry = self._catalog[effect_id]
                    combo.addItem(self._entry_label(entry), effect_id)
                if selected_id and selected_id not in self._catalog:
                    combo.addItem(
                        f"Unknown preserved effect ({selected_id})", selected_id
                    )
                selected_index = combo.findData(selected_id) if selected_id else -1
                combo.setCurrentIndex(selected_index)
                combo.setEnabled(bool(self._catalog) or bool(selected_id))
                if selected_index < 0 and combo.lineEdit() is not None:
                    combo.lineEdit().clear()
            self.clear_buttons[slot_index].setEnabled(bool(selected_id))
            self._update_details(slot_index)
        self._update_status()
        self._rebuild_browser()

    def _commit_combo_text(self, slot_index: int, text: str) -> None:
        """Commit a completer or exact typed label without accepting free text."""

        query = str(text).strip().casefold()
        if not query:
            return
        combo = self.slot_combos[slot_index]
        matches = [
            index
            for index in range(combo.count())
            if query
            in {
                combo.itemText(index).strip().casefold(),
                str(combo.itemData(index) or "").strip().casefold(),
                str(
                    self._catalog.get(str(combo.itemData(index) or ""), {}).get(
                        "label", ""
                    )
                )
                .strip()
                .casefold(),
            }
        ]
        if len(matches) == 1:
            combo.setCurrentIndex(matches[0])

    def _remove_overflow(self) -> None:
        if not self._overflow_selections:
            return
        self._overflow_selections = []
        self._update_status()
        if not self._loading:
            self.changed.emit()

    @staticmethod
    def _selection_state(selection: dict) -> dict:
        effect_id = str(selection.get("effect_id", "")).strip()
        if not effect_id:
            return {}
        state = deepcopy(selection)
        state["instance_id"] = (
            str(selection.get("instance_id", "")).strip() or str(uuid4())
        )
        state["effect_id"] = effect_id
        try:
            state["effect_version"] = int(selection.get("effect_version", 1))
        except (TypeError, ValueError):
            state["effect_version"] = 1
        state["parameters"] = deepcopy(
            selection.get("parameters", {})
            if isinstance(selection.get("parameters", {}), dict)
            else {}
        )
        return state

    def _visible_ids(self, slot_index: int) -> list[str]:
        selected_id = str(
            self._slot_states[slot_index].get("effect_id", "")
        ).strip()
        other_id = str(
            self._slot_states[1 - slot_index].get("effect_id", "")
        ).strip()
        visible: list[str] = []
        for effect_id in self._ordered_ids:
            entry = self._catalog[effect_id]
            if effect_id != selected_id:
                if effect_id == other_id:
                    continue
                if other_id and not self._are_compatible(effect_id, other_id):
                    continue
                if not self._entry_matches_filters(entry):
                    continue
            visible.append(effect_id)
        return visible

    def _filtered_catalog_ids(self) -> list[str]:
        return [
            effect_id
            for effect_id in self._ordered_ids
            if self._entry_matches_filters(self._catalog[effect_id])
        ]

    def _entry_matches_filters(self, entry: dict) -> bool:
        effect_id = str(entry.get("effect_id", "")).strip()
        category = str(self.category_filter.currentData() or "").strip()
        trigger = str(self.trigger_filter.currentData() or "").strip()
        origin = str(self.origin_filter.currentData() or "").strip()
        timing = str(self.timing_filter.currentData() or "").strip()
        if category and str(entry.get("category", "")).strip() != category:
            return False
        if trigger and str(entry.get("trigger", "")).strip() != trigger:
            return False
        if origin and str(entry.get("origin", "")).strip() != origin:
            return False
        if timing and self._timing_key(entry) != timing:
            return False
        if self.favorites_only.isChecked() and effect_id not in self._favorite_ids:
            return False
        if self.recent_only.isChecked() and effect_id not in self._recent_ids:
            return False
        query_words = tuple(
            word
            for word in self.catalog_search.text().strip().casefold().split()
            if word
        )
        search_text = self._search_text(entry)
        return not query_words or all(word in search_text for word in query_words)

    def _are_compatible(self, first_id: str, second_id: str) -> bool:
        if first_id == second_id:
            return False
        first = self._catalog.get(first_id)
        second = self._catalog.get(second_id)
        if first is None or second is None:
            return False
        first_conflicts = self._conflict_ids(first)
        second_conflicts = self._conflict_ids(second)
        return second_id not in first_conflicts and first_id not in second_conflicts

    def _update_details(self, slot_index: int) -> None:
        state = self._slot_states[slot_index]
        effect_id = str(state.get("effect_id", "")).strip()
        label = self.detail_labels[slot_index]
        if not effect_id:
            label.setText("No effect selected.")
            label.setStyleSheet(f"color: {MUTED};")
            return
        entry = self._catalog.get(effect_id)
        if entry is None:
            label.setText(
                f"Unknown catalog ID {effect_id!r} is preserved for validation; "
                "it will not be silently compiled."
            )
            label.setStyleSheet(f"color: {WARNING};")
            return
        origin = str(entry.get("origin", "Studio original")).replace("_", " ")
        inspiration = str(entry.get("inspiration", "")).strip()
        provenance = origin.title()
        if inspiration:
            provenance += f" - {inspiration}"
        notes = str(entry.get("runtime_notes", "")).strip()
        selected_version = self._integer(state.get("effect_version"), 1)
        catalog_version = self._integer(entry.get("version"), 1)
        version_text = (
            f"Selection v{selected_version} / Catalog v{catalog_version}"
            if selected_version != catalog_version
            else f"Catalog v{catalog_version}"
        )
        text = (
            f"{entry.get('description', '')}\n"
            f"Category: {entry.get('category', '')} - Trigger: {entry.get('trigger', '')} "
            f"- Timing: {self._timing_label(self._timing_key(entry))} - {version_text}\n"
            f"Origin: {provenance}"
        )
        if selected_version != catalog_version:
            text += (
                "\nVersion mismatch: validation will block. Clear this slot and "
                "reselect the effect to accept the current catalog version."
            )
        if notes:
            text += f"\nRuntime note: {notes}"
        label.setText(text)
        label.setStyleSheet(
            f"color: {WARNING if selected_version != catalog_version else SUCCESS};"
        )

    def _update_status(self) -> None:
        selected = [
            str(state.get("effect_id", "")).strip()
            for state in self._slot_states
            if str(state.get("effect_id", "")).strip()
        ]
        overflow_count = len(self._overflow_selections)
        self.remove_overflow_button.setVisible(bool(overflow_count))
        if overflow_count:
            self.pair_status.setText(
                f"This project contains {overflow_count} extra effect selection(s). "
                "Only two can be edited here; strict validation will reject the overflow."
            )
            self.pair_status.setStyleSheet(
                f"color: {WARNING}; font-weight: 650;"
            )
            self.pair_guidance.setText(
                "Compatibility cannot be certified while preserved overflow selections "
                "remain. Remove the extras or reopen the project in a tool that supports them."
            )
            self.pair_guidance.setStyleSheet(f"color: {WARNING};")
        elif len(selected) == 2 and not self._are_compatible(*selected):
            self.pair_status.setText(
                "The preserved pair is incompatible or contains an unknown effect. "
                "Clear one slot before release."
            )
            self.pair_status.setStyleSheet(
                f"color: {WARNING}; font-weight: 650;"
            )
            self.pair_guidance.setText(
                "Compatibility: blocked by a deterministic catalog rule (or an unknown "
                "preserved ID). Clear one slot before generation."
            )
            self.pair_guidance.setStyleSheet(f"color: {WARNING};")
        elif len(selected) == 2:
            self.pair_status.setText(
                "2 of 2 effects selected - catalog compatibility check passed."
            )
            self.pair_status.setStyleSheet(
                f"color: {SUCCESS}; font-weight: 650;"
            )
            self.pair_guidance.setText(self._synergy_guidance(*selected))
            self.pair_guidance.setStyleSheet(f"color: {SUCCESS};")
        else:
            self.pair_status.setText(f"{len(selected)} of 2 effects selected.")
            self.pair_status.setStyleSheet(
                f"color: {MUTED}; font-weight: 650;"
            )
            if selected:
                entry = self._catalog.get(selected[0])
                timing = (
                    self._timing_label(self._timing_key(entry))
                    if entry is not None
                    else "unknown timing"
                )
                self.pair_guidance.setText(
                    f"Current coverage: {timing}. Choose a second effect to compare "
                    "cadence, triggers, and thematic overlap. Synergy advice is advisory."
                )
            else:
                self.pair_guidance.setText(
                    "Choose a second effect to see advisory synergy and coverage guidance."
                )
            self.pair_guidance.setStyleSheet(f"color: {MUTED};")

    def _populate_filter(
        self,
        combo: QComboBox,
        all_label: str,
        values: list[str],
        *,
        display=None,
    ) -> None:
        selected = str(combo.currentData() or "")
        label_for = display or (lambda value: value)
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem(all_label, "")
            for value in values:
                combo.addItem(str(label_for(value)), value)
            selected_index = combo.findData(selected)
            combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)

    def _update_filter_labels(self) -> None:
        self.favorites_only.setText(
            f"Favorites only ({len(self._favorite_ids)})"
        )
        self.recent_only.setText(f"Recent only ({len(self._recent_ids)})")

    def _synergy_guidance(self, first_id: str, second_id: str) -> str:
        first = self._catalog.get(first_id)
        second = self._catalog.get(second_id)
        if first is None or second is None:
            return (
                "Compatibility cannot be certified for an unknown preserved effect. "
                "Synergy guidance is unavailable."
            )
        first_trigger = str(first.get("trigger", "")).strip()
        second_trigger = str(second.get("trigger", "")).strip()
        first_timing = self._timing_key(first)
        second_timing = self._timing_key(second)
        shared_tags = sorted(
            self._tags(first).intersection(self._tags(second)), key=str.casefold
        )
        if first_trigger and first_trigger == second_trigger:
            advice = (
                f"focused pairing; both effects respond to {first_trigger}, so rewards "
                "may arrive in the same gameplay moment"
            )
        elif shared_tags:
            advice = (
                "thematic pairing through shared tags "
                + ", ".join(shared_tags[:4])
            )
        elif first_timing == second_timing:
            advice = (
                f"parallel {self._timing_label(first_timing).lower()} cadence across "
                "different triggers"
            )
        else:
            advice = (
                f"complementary coverage across {self._timing_label(first_timing).lower()} "
                f"and {self._timing_label(second_timing).lower()} timing"
            )
        return (
            "Compatibility: deterministic catalog check passed. "
            f"Synergy (advisory): {advice}. Test pacing and reward totals in BNW."
        )

    def _effect_name(self, effect_id: str) -> str:
        entry = self._catalog.get(effect_id)
        if entry is None:
            return effect_id or "the unknown preserved effect"
        return str(entry.get("label", effect_id)).strip() or effect_id

    @staticmethod
    def _tags(entry: dict) -> set[str]:
        raw_tags = entry.get("tags", [])
        if not isinstance(raw_tags, (list, tuple, set, frozenset)):
            return set()
        return {str(tag).strip() for tag in raw_tags if str(tag).strip()}

    @staticmethod
    def _conflict_ids(entry: dict) -> set[str]:
        raw = entry.get("incompatible_effect_ids", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set, frozenset)):
            return set()
        return {str(value).strip() for value in raw if str(value).strip()}

    @staticmethod
    def _display_origin(origin: str) -> str:
        value = str(origin).strip()
        return value.replace("_", " ").title() if value else "Unspecified"

    @staticmethod
    def _timing_key(entry: dict) -> str:
        primitive = str(entry.get("primitive_id", "")).strip()
        if primitive in {"player_turn_reward", "unit_heal_turn"}:
            return "every_turn"
        if primitive in {
            "golden_age_started_reward",
            "city_connection_reward",
            "war_state_reward",
        }:
            return "tracked_turn_check"
        trigger = str(entry.get("trigger", "")).casefold()
        if "state transition" in trigger:
            return "tracked_turn_check"
        if "playerdoturn" in trigger:
            return "every_turn"
        return "immediate_event"

    @staticmethod
    def _timing_label(timing: str) -> str:
        return {
            "every_turn": "Every turn",
            "tracked_turn_check": "Tracked turn check",
            "immediate_event": "Immediate event",
        }.get(str(timing), str(timing).replace("_", " ").title())

    def _browser_item_text(self, entry: dict, cards: bool) -> str:
        label = str(entry.get("label", entry.get("effect_id", ""))).strip()
        category = str(entry.get("category", "Uncategorized")).strip()
        trigger = str(entry.get("trigger", "Unspecified")).strip()
        timing = self._timing_label(self._timing_key(entry))
        origin = self._display_origin(str(entry.get("origin", "")))
        if cards:
            return f"{label}\n{category} | {timing}\n{trigger} | {origin}"
        return f"{label} | {category} | {trigger} | {timing}"

    def _browser_tooltip(self, entry: dict) -> str:
        description = str(entry.get("description", "")).strip()
        return (
            f"{description}\nTrigger: {entry.get('trigger', '')}\n"
            f"Timing: {self._timing_label(self._timing_key(entry))}\n"
            f"Origin: {self._display_origin(str(entry.get('origin', '')))}"
        )

    @staticmethod
    def _entry_label(entry: dict) -> str:
        return f"{entry.get('label', entry.get('effect_id', ''))}  -  {entry.get('category', '')}"

    def _search_text(self, entry: dict) -> str:
        tags = self._tags(entry)
        return " ".join(
            [
                str(entry.get("effect_id", "")),
                str(entry.get("label", "")),
                str(entry.get("category", "")),
                str(entry.get("description", "")),
                str(entry.get("trigger", "")),
                str(entry.get("primitive_id", "")),
                str(entry.get("origin", "")),
                str(entry.get("inspiration", "")),
                str(entry.get("runtime_notes", "")),
                self._timing_label(self._timing_key(entry)),
                *(str(tag) for tag in tags),
            ]
        ).casefold()

    @staticmethod
    def _integer(value: object, default: int) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
