"""Primary guided Civilization Studio window."""

from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QSettings, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .advanced_tools import AdvancedToolsPage
from .beginner import BeginnerGuideDialog
from .civilization_preview import CivilizationPreview
from .command_palette import CommandPalette, PaletteCommand
from .lua_effects import LuaEffectsPage
from .pages import (
    ArtPage,
    CivilizationPage,
    LeaderPage,
    MechanicsPage,
    ProjectPage,
    PromotionsExpansionPackPage,
    ReviewPage,
    WorkflowPage,
)
from .project_health import (
    ProblemsPanel,
    humanize_location,
    indexed_location,
    step_for_location,
)
from .theme import ACCENT, ERROR, MUTED, SUCCESS, WARNING


class MainWindow(QMainWindow):
    """Presentation shell with a plain-dictionary integration seam.

    Persistence, validation, generation, art processing, packaging, and install
    operations are connected by the application controller. This class only
    collects user input and emits requests.
    """

    newRequested = Signal()
    openRequested = Signal()
    saveRequested = Signal(bool)
    auditRequested = Signal(dict)
    validateRequested = Signal(dict)
    buildRequested = Signal(dict)
    installRequested = Signal()
    launchRequested = Signal()
    analyzeLogsRequested = Signal(str, str)
    undoRequested = Signal()
    redoRequested = Signal()
    snapshotRequested = Signal(str)
    historyRequested = Signal()
    openArtifactRequested = Signal(str)

    STEP_NAMES = (
        "1  Start Here",
        "2  Your Civilization",
        "3  Your Leader",
        "4  Abilities & Uniques",
        "5  Promotions Mod (Optional)",
        "6  Artwork",
        "7  Advanced Tools (Optional)",
        "8  Extra Gameplay Effects (Optional)",
        "9  Check, Build & Play",
    )
    GUIDED_PAGE_INDICES = (0, 1, 2, 3, 5, 8)
    OPTIONAL_PAGE_INDICES = (4, 6, 7)
    GUIDED_STEP_NAMES = {
        0: "1  Start Here",
        1: "2  Your Civilization",
        2: "3  Your Leader",
        3: "4  Abilities & Uniques",
        5: "5  Artwork",
        8: "6  Check, Build & Play",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Civ V Civilization Studio")
        self.resize(1320, 860)
        self.setMinimumSize(1040, 680)
        self._project_path: Path | None = None
        self._dirty = False
        self._loading = False
        self._last_issues: list[dict[str, str]] = []
        self._has_validation_result = False
        self._last_auto_prefix = ""
        self._settings = QSettings(
            "Civ V Modding Tools", "Civ V Civilization Studio"
        )
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._build_ui()
        self._build_actions()
        self._connect_signals()
        self.setStatusBar(QStatusBar())
        self._restore_window_state()
        self._mode_changed(self.mode_combo.currentText())
        self.statusBar().showMessage(
            "Ready - choose Create my first civilization or open an existing project"
        )
        self._refresh_preview()
        self._update_step_health()

    def _build_ui(self) -> None:
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setChildrenCollapsible(False)
        root.setObjectName("mainSplitter")
        self.main_splitter = root

        navigation = QFrame()
        navigation.setMinimumWidth(210)
        navigation.setMaximumWidth(380)
        nav_layout = QVBoxLayout(navigation)
        nav_layout.setContentsMargins(0, 0, 0, 16)
        brand = QLabel("CIV V\nCIVILIZATION\nSTUDIO")
        brand.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        brand.setStyleSheet(
            f"font-size: 12pt; font-weight: 800; letter-spacing: 1px; color: {ACCENT};"
            "padding: 22px 18px 6px 18px;"
        )
        tagline = QLabel("MAKE A CUSTOM CIV\nNO CODING REQUIRED")
        tagline.setStyleSheet(
            f"color: {MUTED}; font-size: 8.5pt; font-weight: 650; padding: 0 18px 12px 18px;"
        )
        checklist_label = QLabel("GUIDED CHECKLIST")
        checklist_label.setStyleSheet(
            f"color: {MUTED}; font-size: 8pt; font-weight: 700; padding: 4px 18px 0 18px;"
        )
        self.steps = QListWidget()
        self.steps.setObjectName("stepList")
        self.steps.setAccessibleName("Project workflow steps")
        self.steps.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        for name in self.STEP_NAMES:
            item = QListWidgetItem(name)
            item.setToolTip(f"Open {name.split('  ', 1)[-1]}")
            self.steps.addItem(item)
        self.steps.setCurrentRow(0)
        nav_layout.addWidget(brand)
        nav_layout.addWidget(tagline)
        nav_layout.addWidget(checklist_label)
        nav_layout.addWidget(self.steps, 1)
        self.extras_button = QPushButton("Optional extras...")
        self.extras_button.setToolTip(
            "Promotions Mod, extra gameplay effects, and advanced import or diagnostic tools."
        )
        extras_menu = QMenu(self.extras_button)
        for page_index, label in (
            (4, "Promotions Expansion Pack v9"),
            (7, "Extra Gameplay Effects (up to 2)"),
            (6, "Advanced tools"),
        ):
            action = extras_menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, value=page_index: self._open_optional_page(value)
            )
        self.extras_button.setMenu(extras_menu)
        self.guide_button = QPushButton("Beginner guide")
        self.guide_button.clicked.connect(self.show_beginner_guide)
        nav_layout.addWidget(self.extras_button)
        nav_layout.addWidget(self.guide_button)
        version = QLabel("Brave New World / Expansion2\nPortable project format v5")
        version.setStyleSheet(f"color: {MUTED}; padding: 0 18px;")
        nav_layout.addWidget(version)
        root.addWidget(navigation)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("topHeader")
        header.setStyleSheet("QFrame#topHeader { background: #1d2430; border-bottom: 1px solid #30394a; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)
        self.project_label = QLabel("Untitled project")
        self.project_label.setStyleSheet("font-weight: 650;")
        self.dirty_label = QLabel("")
        self.dirty_label.setStyleSheet(f"color: {ACCENT};")
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Guided (recommended)", "guided")
        self.mode_combo.addItem("Expert controls", "expert")
        self.mode_combo.setToolTip(
            "Guided mode keeps technical Civ V fields out of the way. Expert controls reveal them without changing project data."
        )
        self.mode_combo.setAccessibleName("Editing mode")
        self.template_button = QPushButton("Choose playstyle")
        self.template_button.setToolTip(
            "Choose a safe built-in ability and matching computer-player personality."
        )
        self._build_template_menu()
        self.preview_button = QPushButton("Show preview")
        self.preview_button.setToolTip(
            "Show or hide the live Civ V setup-card and artwork preview."
        )
        self.back_button = QPushButton("Back")
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primaryButton")
        header_layout.addWidget(self.project_label)
        header_layout.addWidget(self.dirty_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.template_button)
        header_layout.addWidget(self.mode_combo)
        header_layout.addWidget(self.preview_button)
        header_layout.addWidget(self.back_button)
        header_layout.addWidget(self.next_button)
        content_layout.addWidget(header)

        self.stack = QStackedWidget()
        self.pages: list[WorkflowPage] = [
            ProjectPage(),
            CivilizationPage(),
            LeaderPage(),
            MechanicsPage(),
            PromotionsExpansionPackPage(),
            ArtPage(),
            AdvancedToolsPage(),
            LuaEffectsPage(),
            ReviewPage(),
        ]
        for page in self.pages:
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(content)
        root.setStretchFactor(0, 0)
        root.setStretchFactor(1, 1)
        root.setSizes([260, 1060])
        self.setCentralWidget(root)

        self.problems = ProblemsPanel()
        self.problems_dock = QDockWidget("Project Problems", self)
        self.problems_dock.setObjectName("problemsDock")
        self.problems_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea
            | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.problems_dock.setWidget(self.problems)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.problems_dock)
        self.problems_dock.setMinimumHeight(155)
        self.problems_dock.hide()

        self.civilization_preview = CivilizationPreview()
        self.preview_dock = QDockWidget("Civilization Preview", self)
        self.preview_dock.setObjectName("civilizationPreviewDock")
        self.preview_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.preview_dock.setWidget(self.civilization_preview)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.preview_dock)
        self.preview_dock.setMinimumWidth(300)
        self.preview_dock.hide()
        self.preview_button.clicked.connect(self._toggle_preview)
        self.preview_dock.visibilityChanged.connect(self._preview_visibility_changed)

    def _toggle_preview(self) -> None:
        self.preview_dock.setVisible(not self.preview_dock.isVisible())

    def _preview_visibility_changed(self, visible: bool) -> None:
        self.preview_button.setText("Hide preview" if visible else "Show preview")

    def _build_template_menu(self) -> None:
        menu = QMenu(self.template_button)
        templates = (
            (
                "naval_trader",
                "Naval Trader",
                "Longer land trade routes and commercially minded AI priorities.",
            ),
            (
                "tall_culture",
                "Tall Cultural Empire",
                "Wonder production with growth and culture priorities.",
            ),
            (
                "conquest",
                "Conquest Specialist",
                "Affordable frontier expansion with aggressive AI priorities.",
            ),
            (
                "diplomatic",
                "Diplomatic Federation",
                "Trade-route resources with diplomacy and expansion priorities.",
            ),
        )
        for template_id, label, description in templates:
            action = menu.addAction(label)
            action.setToolTip(description)
            action.triggered.connect(
                lambda _checked=False, value=template_id: self._apply_template(value)
            )
        self.template_button.setMenu(menu)

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        edit_menu = self.menuBar().addMenu("&Edit")
        view_menu = self.menuBar().addMenu("&View")
        project_menu = self.menuBar().addMenu("&Project")
        help_menu = self.menuBar().addMenu("&Help")

        self.new_action = QAction("&New Project", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.open_action = QAction("&Open Project…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.save_action = QAction("&Save", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_as_action = QAction("Save &As…", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.exit_action = QAction("E&xit", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        file_menu.addActions(
            [self.new_action, self.open_action, self.save_action, self.save_as_action]
        )
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        self.undo_action = QAction("&Undo", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setEnabled(False)
        self.redo_action = QAction("&Redo", self)
        self.redo_action.setShortcuts(
            [QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Shift+Z")]
        )
        self.redo_action.setEnabled(False)
        self.snapshot_action = QAction("Create Named Snapshot…", self)
        self.history_action = QAction("Project History…", self)
        edit_menu.addActions([self.undo_action, self.redo_action])
        edit_menu.addSeparator()
        edit_menu.addActions([self.snapshot_action, self.history_action])

        view_menu.addAction(self.problems_dock.toggleViewAction())
        view_menu.addAction(self.preview_dock.toggleViewAction())
        view_menu.addSeparator()
        self.scale_actions: dict[int, QAction] = {}
        for percent in (90, 100, 110, 125):
            action = QAction(f"Text size {percent}%", self)
            action.setCheckable(True)
            action.setChecked(percent == 100)
            action.triggered.connect(
                lambda _checked=False, value=percent: self._set_text_scale(value)
            )
            view_menu.addAction(action)
            self.scale_actions[percent] = action
        self.high_contrast_action = QAction("High contrast focus indicators", self)
        self.high_contrast_action.setCheckable(True)
        self.high_contrast_action.triggered.connect(self._set_high_contrast)
        view_menu.addAction(self.high_contrast_action)

        self.audit_action = QAction("Check My Progress", self)
        self.validate_action = QAction("Run Final Safety Check", self)
        self.build_action = QAction("Check and Create My Mod", self)
        self.install_action = QAction("Install into Civilization V", self)
        self.launch_action = QAction("Open Civilization V…", self)
        self.analyze_action = QAction("Check Civ V Logs for Problems", self)
        project_menu.addActions(
            [
                self.audit_action,
                self.validate_action,
                self.build_action,
                self.install_action,
            ]
        )
        project_menu.addSeparator()
        project_menu.addActions([self.launch_action, self.analyze_action])

        self.palette_action = QAction("Go to Anything…", self)
        self.palette_action.setShortcut(QKeySequence("Ctrl+K"))
        self.palette_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.beginner_guide_action = QAction("How to Make a Civilization…", self)
        self.beginner_guide_action.setShortcut(QKeySequence("F1"))
        about_action = QAction("About", self)
        help_menu.addAction(self.beginner_guide_action)
        help_menu.addSeparator()
        help_menu.addAction(self.palette_action)
        help_menu.addSeparator()
        help_menu.addAction(about_action)

        self.step_actions: list[QAction] = []
        for index, name in enumerate(self.STEP_NAMES):
            action = QAction(f"Go to {name.split('  ', 1)[-1]}", self)
            action.setShortcut(QKeySequence(f"Alt+{index + 1}"))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(
                lambda _checked=False, row=index: self.steps.setCurrentRow(row)
            )
            self.addAction(action)
            self.step_actions.append(action)

        self.new_action.triggered.connect(self.newRequested)
        self.open_action.triggered.connect(self.openRequested)
        self.save_action.triggered.connect(lambda: self.saveRequested.emit(False))
        self.save_as_action.triggered.connect(lambda: self.saveRequested.emit(True))
        self.exit_action.triggered.connect(self.close)
        self.undo_action.triggered.connect(self.undoRequested)
        self.redo_action.triggered.connect(self.redoRequested)
        self.snapshot_action.triggered.connect(self._request_snapshot)
        self.history_action.triggered.connect(self.historyRequested)
        self.audit_action.triggered.connect(
            lambda: self.auditRequested.emit(self.collect_values())
        )
        self.validate_action.triggered.connect(
            lambda: self.validateRequested.emit(self.collect_values())
        )
        self.build_action.triggered.connect(
            lambda: self.buildRequested.emit(self.collect_values())
        )
        self.install_action.triggered.connect(self.installRequested)
        self.launch_action.triggered.connect(self.launchRequested)
        self.analyze_action.triggered.connect(self._request_log_analysis)
        self.palette_action.triggered.connect(self.show_command_palette)
        self.beginner_guide_action.triggered.connect(self.show_beginner_guide)
        about_action.triggered.connect(self._about)

    def _connect_signals(self) -> None:
        self.steps.currentRowChanged.connect(self._set_step)
        self.back_button.clicked.connect(lambda: self._go_relative(-1))
        self.next_button.clicked.connect(lambda: self._go_relative(1))
        for page in self.pages:
            page.changed.connect(self._page_changed)
        review = self.review_page
        review.auditRequested.connect(lambda: self.auditRequested.emit(self.collect_values()))
        review.validateRequested.connect(lambda: self.validateRequested.emit(self.collect_values()))
        review.buildRequested.connect(lambda: self.buildRequested.emit(self.collect_values()))
        review.installRequested.connect(self.installRequested)
        if hasattr(review, "launchRequested"):
            review.launchRequested.connect(self.launchRequested)  # type: ignore[attr-defined]
        if hasattr(review, "analyzeLogsRequested"):
            review.analyzeLogsRequested.connect(self._request_log_analysis)  # type: ignore[attr-defined]
        review.artifactRequested.connect(self.openArtifactRequested.emit)
        self.problems.issueActivated.connect(self.focus_location)
        if hasattr(review.issues, "issueActivated"):
            review.issues.issueActivated.connect(self.focus_location)
        if hasattr(review, "fixRequested"):
            review.fixRequested.connect(self.focus_location)
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        self.pages[0].mod_name.textChanged.connect(self._sync_auto_prefix)  # type: ignore[attr-defined]
        welcome = self.pages[0].welcome  # type: ignore[attr-defined]
        welcome.startRequested.connect(self._start_guided_project)
        welcome.openRequested.connect(self.openRequested)
        welcome.exampleRequested.connect(self._load_worked_example)
        self._set_step(0)

    def _page_changed(self) -> None:
        self.mark_dirty()
        self._preview_timer.start()
        self._update_step_health()

    @property
    def review_page(self) -> ReviewPage:
        return self.pages[-1]  # type: ignore[return-value]

    @property
    def advanced_page(self) -> AdvancedToolsPage:
        return self.pages[6]  # type: ignore[return-value]

    @property
    def lua_effects_page(self) -> LuaEffectsPage:
        return self.pages[7]  # type: ignore[return-value]

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def is_loading(self) -> bool:
        return self._loading

    @property
    def project_path(self) -> Path | None:
        return self._project_path

    def _is_expert_mode(self) -> bool:
        return self.mode_combo.currentData() == "expert"

    def _visible_page_indices(self) -> list[int]:
        return (
            list(range(len(self.pages)))
            if self._is_expert_mode()
            else list(self.GUIDED_PAGE_INDICES)
        )

    def _go_relative(self, direction: int) -> None:
        visible = self._visible_page_indices()
        current = self.steps.currentRow()
        if current not in visible:
            candidates = (
                [value for value in visible if value < current]
                if direction < 0
                else [value for value in visible if value > current]
            )
            if candidates:
                self.steps.setCurrentRow(
                    max(candidates) if direction < 0 else min(candidates)
                )
            return
        position = visible.index(current)
        target_position = max(0, min(len(visible) - 1, position + direction))
        self.steps.setCurrentRow(visible[target_position])

    def _open_optional_page(self, page_index: int) -> None:
        if page_index not in self.OPTIONAL_PAGE_INDICES:
            return
        self.steps.setCurrentRow(page_index)
        self.statusBar().showMessage(
            "Optional section opened - you can skip it without affecting the guided project"
        )

    def _start_guided_project(self) -> None:
        self.pages[0].welcome.setVisible(False)  # type: ignore[attr-defined]
        self.pages[0].mod_name.setFocus()  # type: ignore[attr-defined]
        self.pages[0].ensureWidgetVisible(self.pages[0].mod_name)  # type: ignore[attr-defined]
        self.statusBar().showMessage(
            "Start with the mod name and creator - technical settings are already handled"
        )

    def _load_worked_example(self) -> None:
        self._loading = True
        try:
            project = self.pages[0]
            project.load_values(  # type: ignore[attr-defined]
                {
                    "mod_name": "River Kingdom Civilization",
                    "prefix": "RIVER_KINGDOM",
                    "version": 1,
                    "author": "Example Creator",
                    "description": "A worked beginner example made with Civ V Civilization Studio.",
                    "affects_saved_games": True,
                    "project_root": project.output_dir.text(),  # type: ignore[attr-defined]
                }
            )
            self.pages[1].load_values(
                {
                    "name": "The River Kingdom",
                    "short_name": "River Kingdom",
                    "adjective": "River",
                    "base_civilization": "CIVILIZATION_AMERICA",
                    "dawn_of_man_quote": "The rivers remember every people who built upon their banks.",
                    "civilopedia": "A fictional worked example. Replace this story with the history of your civilization.",
                    "colors": {"primary": "#27638f", "secondary": "#e8c665"},
                    "city_names": [
                        "Highwater", "Reedhaven", "Three Forks", "Stonebank",
                        "Willow Reach", "Silver Ford", "Delta Gate", "Mist Harbor",
                        "Old Crossing", "Bluewater", "Kingfisher", "Southbank",
                        "Marshlight", "Twin Bridges", "Riverwatch", "Grand Estuary",
                    ],
                    "spy_names": [
                        "Mara", "Ilyan", "Sera", "Tovin", "Neris",
                        "Kallan", "Elya", "Varo", "Miren", "Daro",
                    ],
                }
            )
            self.pages[2].load_values(
                {
                    "name": "Queen Mara",
                    "title": "Keeper of the Rivers",
                    "civilopedia": "Mara united the river cities through trade, law, and careful stewardship.",
                    "flavors": {
                        "offense": 3, "defense": 6, "expansion": 5, "growth": 6,
                        "science": 5, "culture": 5, "diplomacy": 10, "wonder": 5,
                    },
                    "art": {"leader_scene": "", "leader_fallback": ""},
                }
            )
            self.pages[3].load_values(
                {
                    "trait": {
                        "name": "River Confederation",
                        "short_description": "Trade routes strengthen a far-reaching river alliance.",
                        "implementation_class": "Database-native recipe",
                        "recipe": "Trade route resource modifier",
                        "modifier_value": 20,
                        "effect_description": "Trade routes provide a stronger resource bonus.",
                    },
                    "uniques": [
                        {
                            "kind": "unit",
                            "name": "River Guard",
                            "replaces_class": "UNITCLASS_SWORDSMAN",
                            "base_template": "UNIT_SWORDSMAN",
                            "help_text": "A Swordsman replacement trained to defend the river cities.",
                            "strategy_text": "Use River Guards to protect trade routes and crossings.",
                        },
                        {
                            "kind": "building",
                            "name": "Floodplain Shrine",
                            "replaces_class": "BUILDINGCLASS_MONUMENT",
                            "base_template": "BUILDING_MONUMENT",
                            "help_text": "A Monument replacement celebrating the rivers that sustain the kingdom.",
                            "strategy_text": "Build early to establish the kingdom's culture.",
                        },
                    ],
                }
            )
            self.pages[0].welcome.setVisible(False)  # type: ignore[attr-defined]
        finally:
            self._loading = False
        self.mark_dirty()
        self._refresh_preview()
        self._update_step_health()
        self.steps.setCurrentRow(1)
        self.statusBar().showMessage(
            "Worked example loaded - replace its names and add your own artwork"
        )

    def show_beginner_guide(self) -> None:
        dialog = BeginnerGuideDialog(self)
        dialog.exec()

    def _set_step(self, index: int) -> None:
        if index < 0:
            return
        if index in {4, 6}:
            mechanics = self.pages[3].values()
            target = self.pages[index]
            target.set_units(list(mechanics.get("uniques", [])))  # type: ignore[attr-defined]
        self.stack.setCurrentIndex(index)
        visible = self._visible_page_indices()
        self.back_button.setEnabled(any(value < index for value in visible))
        self.next_button.setEnabled(any(value > index for value in visible))
        next_index = next((value for value in visible if value > index), None)
        if next_index is None:
            self.next_button.setText("Guided steps complete")
        else:
            destination = (
                self.GUIDED_STEP_NAMES.get(next_index, self.STEP_NAMES[next_index])
                .split("  ", 1)[-1]
            )
            destination = destination.replace(" & ", " and ")
            self.next_button.setText(f"Continue: {destination}")
        if not self._is_expert_mode() and index in self.GUIDED_PAGE_INDICES:
            position = visible.index(index) + 1
            label = self.GUIDED_STEP_NAMES[index].split("  ", 1)[-1]
            self.statusBar().showMessage(
                f"Guided step {position} of {len(visible)} - {label}"
            )
        else:
            self.statusBar().showMessage(
                f"Optional or expert page - {self.STEP_NAMES[index].split('  ', 1)[-1]}"
            )

    def collect_values(self) -> dict:
        mechanics = self.pages[3].values()
        pep_page = self.pages[4]
        pep_page.set_units(list(mechanics.get("uniques", [])))  # type: ignore[attr-defined]
        advanced_page = self.advanced_page
        advanced_page.set_units(list(mechanics.get("uniques", [])))
        return {
            "schema_version": 1,
            "project": self.pages[0].values(),
            "civilization": self.pages[1].values(),
            "leader": self.pages[2].values(),
            "mechanics": mechanics,
            "promotions_expansion_pack": pep_page.values(),
            "art": self.pages[5].values(),
            "advanced": advanced_page.values(),
            "lua_effects": self.lua_effects_page.values(),
        }

    def load_values(
        self,
        data: dict,
        path: str | Path | None = None,
        *,
        reset_review: bool = True,
    ) -> None:
        self._loading = True
        try:
            page_keys = (
                "project",
                "civilization",
                "leader",
                "mechanics",
                "promotions_expansion_pack",
                "art",
                "advanced",
                "lua_effects",
            )
            for page, key in zip(self.pages[:8], page_keys, strict=True):
                if key in {"promotions_expansion_pack", "advanced"}:
                    mechanics = data.get("mechanics", {})
                    uniques = mechanics.get("uniques", []) if isinstance(mechanics, dict) else []
                    page.set_units(list(uniques) if isinstance(uniques, list) else [])  # type: ignore[attr-defined]
                value = data.get(key, {})
                page.load_values(value if isinstance(value, dict) else {})
            project_values = data.get("project", {})
            show_welcome = (
                not path
                and not str(
                    project_values.get("mod_name", "")
                    if isinstance(project_values, dict)
                    else ""
                ).strip()
            )
            self.pages[0].welcome.setVisible(show_welcome)  # type: ignore[attr-defined]
            if show_welcome:
                self.steps.setCurrentRow(0)
            self.set_project_path(path)
            if reset_review:
                self._last_issues = []
                self._has_validation_result = False
                self.problems.set_issues(
                    [], "Validation will refresh after the project loads."
                )
                self.review_page.reset_results(
                    "Validation will refresh after the project loads."
                )
            self.mark_clean()
        finally:
            self._loading = False
        self._mode_changed(self.mode_combo.currentText())
        self._refresh_preview()
        self._update_step_health()

    def set_project_path(self, path: str | Path | None) -> None:
        self._project_path = Path(path).resolve() if path else None
        if self._project_path:
            self.project_label.setText(self._project_path.stem.replace(".civ5project", ""))
            self.project_label.setToolTip(str(self._project_path))
        else:
            self.project_label.setText("Untitled project")
            self.project_label.setToolTip("")
        self._update_title()

    def set_reference_catalog(
        self,
        *,
        civilizations: list[str],
        unit_templates: list[tuple[str, str]],
        building_templates: list[tuple[str, str]],
        yields: list[str],
        improvement_templates: list[str] | None = None,
        technologies: list[str] | None = None,
        promotions: list[str] | None = None,
        domains: list[str] | None = None,
        trait_recipes: list[dict[str, str]] | None = None,
        lua_effects: list[dict] | None = None,
        promotions_expansion_pack: list[dict] | None = None,
        diplomacy_responses: list[str] | None = None,
    ) -> None:
        """Populate verified BNW choices without coupling pages to domain code."""

        civilization_page = self.pages[1]
        selected = civilization_page.base_civ.currentText()  # type: ignore[attr-defined]
        civilization_page.base_civ.clear()  # type: ignore[attr-defined]
        civilization_page.base_civ.addItems(civilizations)  # type: ignore[attr-defined]
        if selected:
            civilization_page.base_civ.setCurrentText(selected)  # type: ignore[attr-defined]
        mechanics_page = self.pages[3]
        mechanics_page.uniques.set_reference_catalog(  # type: ignore[attr-defined]
            unit_templates,
            building_templates,
            yields,
            improvement_templates=improvement_templates,
            technologies=technologies,
            promotions=promotions,
            domains=domains,
        )
        if trait_recipes is not None:
            mechanics_page.set_trait_recipes(trait_recipes)  # type: ignore[attr-defined]
        if lua_effects is not None:
            self.lua_effects_page.set_catalog(lua_effects)
        if promotions_expansion_pack is not None:
            self.pages[4].set_catalog(promotions_expansion_pack)  # type: ignore[attr-defined]
        if diplomacy_responses is not None:
            self.advanced_page.set_diplomacy_responses(diplomacy_responses)
        self._mode_changed(self.mode_combo.currentText())
        self._update_step_health()

    def mark_dirty(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self.review_page.install_button.setProperty("ready", False)
        self.review_page.install_button.setEnabled(False)
        if hasattr(self.review_page, "invalidate_after_edit"):
            self.review_page.invalidate_after_edit()
        self.dirty_label.setText("● Unsaved changes")
        self._update_title()

    def mark_clean(self) -> None:
        self._dirty = False
        self.dirty_label.setText("")
        self._update_title()
        self._update_step_health()

    def _update_title(self) -> None:
        name = self._project_path.stem if self._project_path else "Untitled"
        marker = " *" if self._dirty else ""
        self.setWindowTitle(f"{name}{marker} — Civ V Civilization Studio")

    def _refresh_preview(self) -> None:
        if not hasattr(self, "civilization_preview"):
            return
        values = self.collect_values()
        self.civilization_preview.set_values(values)
        mechanics = values.get("mechanics", {})
        uniques = mechanics.get("uniques", []) if isinstance(mechanics, dict) else []
        art_page = self.pages[5]
        if hasattr(art_page, "set_external_art_status"):
            art_page.set_external_art_status(  # type: ignore[attr-defined]
                values.get("leader", {}),
                list(uniques) if isinstance(uniques, list) else [],
            )

    def _sync_auto_prefix(self, name: str) -> None:
        if self._loading or self._is_expert_mode():
            return
        project_page = self.pages[0]
        current = project_page.prefix.text().strip()  # type: ignore[attr-defined]
        if current and current != self._last_auto_prefix:
            return
        if not name.strip():
            if current and current == self._last_auto_prefix:
                project_page.prefix.clear()  # type: ignore[attr-defined]
            self._last_auto_prefix = ""
            return
        candidate = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
        if not candidate or not candidate[0].isalpha():
            candidate = f"CUSTOM_{candidate}".strip("_")
        candidate = candidate[:40] or "CUSTOM_CIV"
        self._last_auto_prefix = candidate
        project_page.prefix.setText(candidate)  # type: ignore[attr-defined]

    def _mode_changed(self, label: str) -> None:
        expert = self._is_expert_mode()
        project_page = self.pages[0]
        for page in self.pages:
            if hasattr(page, "set_expert_mode"):
                page.set_expert_mode(expert)  # type: ignore[attr-defined]
        for index in range(self.steps.count()):
            optional = index in self.OPTIONAL_PAGE_INDICES
            self.steps.item(index).setHidden(optional and not expert)
        for index, action in enumerate(getattr(self, "step_actions", [])):
            if expert:
                action.setEnabled(True)
                action.setShortcut(QKeySequence(f"Alt+{index + 1}"))
            elif index in self.GUIDED_PAGE_INDICES:
                action.setEnabled(True)
                guided_position = self.GUIDED_PAGE_INDICES.index(index) + 1
                action.setShortcut(QKeySequence(f"Alt+{guided_position}"))
            else:
                action.setEnabled(False)
                action.setShortcut(QKeySequence())
        self.mode_combo.setToolTip(
            "Expert controls show raw BNW identifiers, individual AI values, and diagnostic stages."
            if expert
            else "Guided mode shows the six steps a new player needs and keeps optional technical tools out of the way."
        )
        if not expert:
            self._sync_auto_prefix(project_page.mod_name.text())  # type: ignore[attr-defined]
            if self.steps.currentRow() in self.OPTIONAL_PAGE_INDICES:
                self.steps.setCurrentRow(3)
        self._set_step(self.steps.currentRow())
        self._update_step_health()
        self.statusBar().showMessage(f"{label} enabled")

    def _apply_template(self, template_id: str) -> None:
        templates = {
            "naval_trader": {
                "label": "Naval Trader",
                "trait": "Maritime Exchange",
                "short": "Trade routes reach farther across a connected commercial realm.",
                "recipe": "Land trade route range bonus",
                "value": 5,
                "effect": "Adds five tiles to verified land trade-route range.",
                "flavors": {"expansion": 7, "growth": 6, "diplomacy": 7, "offense": 4},
            },
            "tall_culture": {
                "label": "Tall Cultural Empire",
                "trait": "Patrons of the Ages",
                "short": "Wonder construction is strengthened in every city.",
                "recipe": "Wonder production modifier",
                "value": 15,
                "effect": "Adds a verified fifteen-percent Wonder production modifier.",
                "flavors": {"culture": 9, "growth": 8, "wonder": 9, "offense": 3},
            },
            "conquest": {
                "label": "Conquest Specialist",
                "trait": "Frontier Administration",
                "short": "New territory can be purchased at lower cost.",
                "recipe": "Plot purchase cost modifier",
                "value": -25,
                "effect": "Reduces the verified plot-purchase cost modifier by twenty-five percent.",
                "flavors": {"offense": 9, "expansion": 8, "defense": 6, "diplomacy": 3},
            },
            "diplomatic": {
                "label": "Diplomatic Federation",
                "trait": "League of Envoys",
                "short": "Trade-route resources reinforce a diplomatic network.",
                "recipe": "Trade route resource modifier",
                "value": 20,
                "effect": "Adds a verified twenty-point trade-route resource modifier.",
                "flavors": {"diplomacy": 10, "expansion": 7, "growth": 6, "offense": 3},
            },
        }
        template = templates.get(template_id)
        if template is None:
            return
        if self._dirty:
            result = QMessageBox.question(
                self,
                "Apply playstyle",
                f"Apply the {template['label']} ability and computer-player personality?\n\n"
                "Your names and artwork will not change. Studio will create a history snapshot first.",
                QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if result != QMessageBox.StandardButton.Apply:
                return
        self.snapshotRequested.emit(f"Before {template['label']} playstyle")
        mechanics = self.pages[3]
        mechanics.trait_name.setText(str(template["trait"]))  # type: ignore[attr-defined]
        mechanics.trait_short.setText(str(template["short"]))  # type: ignore[attr-defined]
        mechanics.mechanic_level.setCurrentText("Database-native recipe")  # type: ignore[attr-defined]
        recipe = str(template["recipe"])
        if mechanics.recipe.findText(recipe) >= 0:  # type: ignore[attr-defined]
            mechanics.recipe.setCurrentText(recipe)  # type: ignore[attr-defined]
        mechanics.modifier_value.setValue(int(template["value"]))  # type: ignore[attr-defined]
        mechanics.effect.setPlainText(str(template["effect"]))  # type: ignore[attr-defined]
        leader = self.pages[2]
        for key, value in dict(template["flavors"]).items():
            if key in leader.flavors:  # type: ignore[attr-defined]
                leader.flavors[key].setValue(int(value))  # type: ignore[attr-defined]
        self.steps.setCurrentRow(3)
        self.statusBar().showMessage(
            f"Applied {template['label']} - ability and leader priorities updated"
        )

    def _step_completion(self) -> list[float]:
        project = self.pages[0].values()
        civilization = self.pages[1].values()
        leader = self.pages[2].values()
        mechanics = self.pages[3].values()
        art = self.pages[5].values()
        uniques = [
            entry
            for entry in mechanics.get("uniques", [])
            if isinstance(entry, dict)
        ]
        leader_art = leader.get("art", {}) if isinstance(leader, dict) else {}
        art_checks = [
            bool(entry.get("source"))
            for entry in art.values()
            if isinstance(entry, dict)
        ]
        if isinstance(leader_art, dict):
            # The square leader portrait is already counted on Artwork. The
            # Leader page owns only the wide diplomacy scene.
            art_checks.append(bool(leader_art.get("leader_scene")))
        for unique in uniques:
            unique_art = unique.get("art", {})
            unique_art = unique_art if isinstance(unique_art, dict) else {}
            required_keys = (
                ("icon_source", "unit_flag_source")
                if unique.get("kind") == "unit"
                else ("icon_source",)
            )
            art_checks.extend(bool(unique_art.get(key)) for key in required_keys)

        def ratio(values: list[bool]) -> float:
            return sum(values) / len(values) if values else 1.0

        return [
            ratio(
                [
                    bool(project.get("mod_name")),
                    bool(project.get("prefix")),
                    bool(project.get("author")),
                ]
            ),
            ratio(
                [
                    bool(civilization.get("name")),
                    bool(civilization.get("short_name")),
                    bool(civilization.get("adjective")),
                    len(civilization.get("city_names", [])) >= 10,
                ]
            ),
            ratio([bool(leader.get("name"))]),
            ratio(
                [
                    bool(mechanics.get("trait", {}).get("name")),
                    bool(mechanics.get("trait", {}).get("short_description")),
                    str(mechanics.get("trait", {}).get("recipe", ""))
                    not in {"", "No database modifier"},
                    len(uniques) >= 2,
                    all(bool(entry.get("name")) for entry in uniques[:2]),
                ]
            ),
            1.0,
            ratio(art_checks),
            1.0,
            1.0,
            1.0 if self._has_validation_result else 0.0,
        ]

    @staticmethod
    def _status_icon(color: str) -> QIcon:
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(2, 2, 10, 10)
        painter.end()
        return QIcon(pixmap)

    def _update_step_health(self) -> None:
        if not hasattr(self, "steps"):
            return
        completion = self._step_completion()
        grouped: dict[int, dict[str, int]] = {
            index: {"ERROR": 0, "WARNING": 0, "INFO": 0}
            for index in range(len(self.pages))
        }
        for issue in self._last_issues:
            location = issue.get("location", issue.get("field", ""))
            severity = issue.get("severity", issue.get("level", "INFO")).upper()
            grouped[step_for_location(location)][severity] = (
                grouped[step_for_location(location)].get(severity, 0) + 1
            )
        for index in range(self.steps.count()):
            item = self.steps.item(index)
            errors = grouped[index].get("ERROR", 0)
            warnings = grouped[index].get("WARNING", 0)
            suffix = ""
            if errors or warnings:
                parts = []
                if errors:
                    parts.append(f"{errors} fix")
                if warnings:
                    parts.append(f"{warnings} tip")
                suffix = "   " + " / ".join(parts)
            elif completion[index] < 1:
                suffix = f"   {round(completion[index] * 100)}%"
            base_name = (
                self.STEP_NAMES[index]
                if self._is_expert_mode()
                else self.GUIDED_STEP_NAMES.get(index, self.STEP_NAMES[index])
            )
            item.setText(f"{base_name}{suffix}")
            if errors:
                color, status = ERROR, f"{errors} item(s) must be fixed"
            elif warnings:
                color, status = WARNING, f"{warnings} suggestion(s)"
            elif completion[index] >= 1:
                color, status = SUCCESS, "ready or optional"
            else:
                color, status = MUTED, f"{round(completion[index] * 100)}% complete"
            item.setIcon(self._status_icon(color))
            item.setData(Qt.ItemDataRole.UserRole, status)
            item.setToolTip(
                f"{base_name.split('  ', 1)[-1]} - {status}"
            )

    def set_live_issues(
        self,
        issues: list[dict[str, str]],
        summary: str,
        can_install: bool = False,
    ) -> None:
        self._last_issues = [dict(issue) for issue in issues]
        self._has_validation_result = True
        self.review_page.set_results(self._last_issues, summary, can_install)
        self.problems.set_issues(self._last_issues, summary)
        self._update_step_health()

    def focus_location(self, location: str) -> None:
        index = step_for_location(location)
        self.steps.setCurrentRow(index)
        target: QWidget | None = None
        value = str(location or "")
        if index == 0:
            page = self.pages[0]
            field = value.rsplit(".", 1)[-1]
            target = {
                "mod_name": page.mod_name,
                "authors": page.author,
                "author": page.author,
                "internal_prefix": page.prefix,
                "prefix": page.prefix,
                "mod_version": page.version,
                "version": page.version,
                "description": page.description,
                "affects_saved_games": page.affects_saves,
            }.get(field, page.mod_name)  # type: ignore[attr-defined]
        elif index == 1:
            page = self.pages[1]
            field = value.rsplit(".", 1)[-1]
            target = {
                "name": page.name,
                "short_name": page.short_name,
                "adjective": page.adjective,
                "base_civilization": page.base_civ,
                "dawn_of_man_quote": page.dom_quote,
                "civilopedia": page.civilopedia,
                "city_names": page.cities.editor,
                "spy_names": page.spies.editor,
                "primary": page.primary_color.swatch,
                "secondary": page.secondary_color.swatch,
            }.get(field, page.name)  # type: ignore[attr-defined]
            if field.startswith("primary_"):
                target = page.primary_color.swatch  # type: ignore[attr-defined]
            elif field.startswith("secondary_"):
                target = page.secondary_color.swatch  # type: ignore[attr-defined]
        elif index == 2:
            page = self.pages[2]
            field = value.rsplit(".", 1)[-1]
            target = {
                "name": page.name,
                "title": page.title,
                "civilopedia": page.civilopedia,
                "leader_scene": page.scene,
                "leader_fallback": page.fallback,
            }.get(field, page.name)  # type: ignore[attr-defined]
        elif index == 3:
            page = self.pages[3]
            collection, row_index, tail = indexed_location(value)
            if row_index is not None and collection in {"units", "buildings", "improvements"}:
                if hasattr(page.uniques, "focus_location"):
                    target = page.uniques.focus_location(collection, row_index, tail)  # type: ignore[attr-defined]
                else:
                    kind = {"units": "unit", "buildings": "building", "improvements": "improvement"}[collection]
                    matches = [
                        row
                        for row, data in enumerate(page.uniques._rows)  # type: ignore[attr-defined]
                        if data.get("kind") == kind
                    ]
                    if row_index < len(matches):
                        page.uniques.table.setCurrentCell(matches[row_index], 1)  # type: ignore[attr-defined]
                        target = page.uniques.table  # type: ignore[attr-defined]
            else:
                field = value.rsplit(".", 1)[-1]
                target = {
                    "name": page.trait_name,
                    "short_description": page.trait_short,
                    "long_description": page.effect,
                    "description": page.effect,
                }.get(field, page.trait_name)  # type: ignore[attr-defined]
        elif index == 4:
            page = self.pages[4]
            pep_match = re.match(
                r"^units\[(\d+)]\.promotions_expansion_pack\[(\d+)]",
                value,
            )
            if pep_match and hasattr(page, "focus_location"):
                target = page.focus_location(  # type: ignore[attr-defined]
                    int(pep_match.group(1)), int(pep_match.group(2))
                )
            else:
                target = page.table  # type: ignore[attr-defined]
        elif index == 5:
            art_page = self.pages[5]
            parts = value.split(".")
            requested_role = parts[1] if len(parts) > 1 else ""
            target = art_page.slots.get(requested_role)  # type: ignore[attr-defined]
            if target is None:
                missing = next(
                    (slot for slot in art_page.slots.values() if not slot.path),  # type: ignore[attr-defined]
                    None,
                )
                target = missing or art_page.preview  # type: ignore[attr-defined]
        elif index == 6:
            target = self.advanced_page
        elif index == 7:
            match = re.search(r"\[(\d+)]", value)
            slot = int(match.group(1)) if match else 0
            target = self.lua_effects_page.slot_combos[min(slot, 1)]
        else:
            target = self.review_page.issues
        if target is not None:
            mechanics_table = self.pages[3].uniques.table  # type: ignore[attr-defined]
            expert_only = target is mechanics_table or mechanics_table.isAncestorOf(target)
            ancestor = target
            hidden_by_parent = False
            while ancestor is not None and ancestor is not self:
                if ancestor.isHidden():
                    hidden_by_parent = True
                    break
                ancestor = ancestor.parentWidget()
            if (
                (hidden_by_parent or expert_only)
                and not self._is_expert_mode()
            ):
                self.mode_combo.setCurrentIndex(self.mode_combo.findData("expert"))
            target.setFocus(Qt.FocusReason.OtherFocusReason)
            page = self.pages[index]
            page.ensureWidgetVisible(target, 40, 40)
            target.setProperty("validationFocus", True)
            target.style().unpolish(target)
            target.style().polish(target)
            QTimer.singleShot(1800, lambda widget=target: self._clear_validation_focus(widget))
        self.statusBar().showMessage(
            f"Opened {self.STEP_NAMES[index].split('  ', 1)[-1]} - {humanize_location(value) if value else 'general issue'}"
        )

    @staticmethod
    def _clear_validation_focus(widget: QWidget) -> None:
        if widget is None:
            return
        widget.setProperty("validationFocus", False)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def set_history_state(
        self,
        *,
        can_undo: bool,
        can_redo: bool,
        undo_label: str = "",
        redo_label: str = "",
    ) -> None:
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)
        self.undo_action.setText(f"Undo {undo_label}" if undo_label else "Undo")
        self.redo_action.setText(f"Redo {redo_label}" if redo_label else "Redo")

    def _request_snapshot(self) -> None:
        label, accepted = QInputDialog.getText(
            self,
            "Create project snapshot",
            "Snapshot label:",
            text="Manual checkpoint",
        )
        if accepted and label.strip():
            self.snapshotRequested.emit(label.strip())

    def _request_log_analysis(self) -> None:
        self.analyzeLogsRequested.emit(
            self.advanced_page.test_civ5_root.text().strip(),
            self.advanced_page.test_generated_mod_root.text().strip(),
        )

    def show_command_palette(self) -> None:
        commands: list[PaletteCommand] = []
        for index, name in enumerate(self.STEP_NAMES):
            label = name.split("  ", 1)[-1]
            commands.append(
                PaletteCommand(
                    f"step.{index}",
                    f"Open {label}",
                    "Workflow",
                    lambda row=index: self.steps.setCurrentRow(row),
                    f"step {index + 1}",
                )
            )
        action_commands = (
            ("save", "Save project", "Project", lambda: self.saveRequested.emit(False), "write"),
            ("audit", "Check my progress", "Build", lambda: self.auditRequested.emit(self.collect_values()), "check"),
            ("validate", "Run final safety check", "Build", lambda: self.validateRequested.emit(self.collect_values()), "strict gate"),
            ("build", "Check and create my mod", "Build", lambda: self.buildRequested.emit(self.collect_values()), "compile"),
            ("install", "Install into Civilization V", "Build", self.installRequested.emit, "mods"),
            ("problems", "Show project problems", "View", lambda: self.problems_dock.show(), "errors warnings"),
            ("preview", "Show civilization preview", "View", lambda: self.preview_dock.show(), "game setup dawn art"),
            ("snapshot", "Create named snapshot", "History", self._request_snapshot, "checkpoint"),
            ("undo", "Undo last edit", "History", self.undoRequested.emit, "revert"),
            ("redo", "Redo edit", "History", self.redoRequested.emit, "restore"),
            ("guide", "Open the beginner guide", "Help", self.show_beginner_guide, "walkthrough glossary"),
            ("quick", "Switch to Guided mode", "View", lambda: self.mode_combo.setCurrentIndex(self.mode_combo.findData("guided")), "simple"),
            ("expert", "Switch to Expert controls", "View", lambda: self.mode_combo.setCurrentIndex(self.mode_combo.findData("expert")), "advanced raw ids"),
        )
        commands.extend(PaletteCommand(*entry) for entry in action_commands)
        field_commands = (
            ("mod name", "mod_name"),
            ("internal prefix", "internal_prefix"),
            ("civilization name", "civilization.name"),
            ("city names", "civilization.city_names"),
            ("leader name", "leader.name"),
            ("trait name", "trait.name"),
            ("art sources", "art"),
            ("Lua effect slot one", "lua_effects[0].effect_id"),
            ("Lua effect slot two", "lua_effects[1].effect_id"),
        )
        for label, location in field_commands:
            commands.append(
                PaletteCommand(
                    f"field.{location}",
                    f"Edit {label}",
                    "Field",
                    lambda value=location: self.focus_location(value),
                )
            )
        CommandPalette(commands, self).exec()

    def _set_text_scale(self, percent: int) -> None:
        percent = min(150, max(80, int(percent)))
        self._settings.setValue("accessibility/textScale", percent)
        for value, action in self.scale_actions.items():
            action.setChecked(value == percent)
        self._apply_accessibility_style(percent, self.high_contrast_action.isChecked())

    def _set_high_contrast(self, enabled: bool) -> None:
        self._settings.setValue("accessibility/highContrast", bool(enabled))
        selected = next(
            (value for value, action in self.scale_actions.items() if action.isChecked()),
            100,
        )
        self._apply_accessibility_style(selected, enabled)

    def _apply_accessibility_style(self, percent: int, high_contrast: bool) -> None:
        size = 10.0 * percent / 100.0
        focus = "#ffffff" if high_contrast else ACCENT
        width = 3 if high_contrast else 2
        self.setStyleSheet(
            f"QMainWindow {{ font-size: {size:.2f}pt; }}"
            f"QWidget[validationFocus='true'] {{ border: {width}px solid {focus}; }}"
            f"QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, "
            f"QTableWidget:focus, QTreeWidget:focus, QListWidget:focus, "
            f"QPushButton:focus, QToolButton:focus, QCheckBox:focus, "
            f"QRadioButton:focus, QSlider:focus {{ border: {width}px solid {focus}; }}"
        )

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        state = self._settings.value("window/state")
        splitter = self._settings.value("window/splitter")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)
        if splitter:
            self.main_splitter.restoreState(splitter)
        # Keep the beginner workspace uncluttered at launch. Both detailed
        # docks remain one click away from the View menu and command palette.
        self.problems_dock.hide()
        self.preview_dock.hide()
        percent = int(self._settings.value("accessibility/textScale", 100))
        high_contrast = str(
            self._settings.value("accessibility/highContrast", "false")
        ).casefold() in {"1", "true", "yes"}
        self.high_contrast_action.setChecked(high_contrast)
        self._set_text_scale(percent)

    def _save_window_state(self) -> None:
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        self._settings.setValue("window/splitter", self.main_splitter.saveState())

    def show_issues(self, issues: list[dict[str, str]], summary: str, can_install: bool = False) -> None:
        self.set_live_issues(issues, summary, can_install)
        self.steps.setCurrentRow(len(self.pages) - 1)

    def append_log(self, message: str) -> None:
        self.review_page.log.append_message(message)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.review_page.set_busy(busy, message)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About Civ V Civilization Studio",
            "Civ V Civilization Studio\n\n"
            "A guided Brave New World custom-civilization builder.\n"
            "Preview frames are never baked into exported art.\n\n"
            "Promotions - Expansion Pack was separately created by Bloublou "
            "and is not bundled.\n\n"
            "Unofficial fan-made tool; not affiliated with or endorsed by "
            "Firaxis Games, 2K, Take-Two Interactive, Aspyr, or Valve.\n\n"
            "Static validation is not an in-game test.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._dirty:
            self._save_window_state()
            event.accept()
            return
        result = QMessageBox.question(
            self,
            "Unsaved project",
            "This project contains unsaved changes. Close without saving?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Discard:
            self._save_window_state()
            event.accept()
        else:
            event.ignore()
