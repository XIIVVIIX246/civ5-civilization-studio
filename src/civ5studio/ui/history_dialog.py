"""Project-history browser used by the controller-owned history service."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .theme import MUTED, WARNING


class ProjectHistoryDialog(QDialog):
    """Inspect revisions and choose a full or section-level snapshot restore."""

    SECTIONS = (
        ("Entire project", ""),
        ("Project identity", "project"),
        ("Civilization", "civilization"),
        ("Leader", "leader"),
        ("Mechanics", "mechanics"),
        ("Promotions Expansion Pack", "promotions_expansion_pack"),
        ("Art", "art"),
        ("Advanced tools", "advanced"),
        ("Lua effects", "lua_effects"),
    )

    def __init__(
        self,
        *,
        entries: Iterable[dict[str, object]],
        snapshots: Iterable[dict[str, object]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project History")
        self.resize(900, 560)
        self.selected_snapshot_id = ""
        self.selected_section = ""
        self._snapshots = [dict(item) for item in snapshots]
        layout = QVBoxLayout(self)
        heading = QLabel("Undo timeline and named project snapshots")
        heading.setStyleSheet("font-size: 15pt; font-weight: 750;")
        note = QLabel(
            "Undo entries are session history. Named snapshots are retained in a marked "
            "project workspace and can restore one section without touching the others."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(heading)
        layout.addWidget(note)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        timeline_panel = QWidget()
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.setContentsMargins(0, 0, 6, 0)
        timeline_layout.addWidget(QLabel("Recent revisions"))
        self.timeline = QListWidget()
        for entry in entries:
            marker = "  ← current" if entry.get("current") else ""
            item = QListWidgetItem(
                f"{entry.get('label', 'Edit')}{marker}\n{entry.get('created_utc', '')}"
            )
            item.setToolTip(str(entry.get("digest", "")))
            self.timeline.addItem(item)
        timeline_layout.addWidget(self.timeline)

        snapshot_panel = QWidget()
        snapshot_layout = QVBoxLayout(snapshot_panel)
        snapshot_layout.setContentsMargins(6, 0, 0, 0)
        snapshot_layout.addWidget(QLabel("Named snapshots"))
        self.snapshot_list = QListWidget()
        for index, snapshot in enumerate(self._snapshots):
            item = QListWidgetItem(
                f"{snapshot.get('label', 'Snapshot')}\n"
                f"{snapshot.get('reason', 'manual')} · {snapshot.get('created_utc', '')}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.snapshot_list.addItem(item)
        snapshot_layout.addWidget(self.snapshot_list, 1)
        self.comparison = QLabel("Select a snapshot to compare it with the current draft.")
        self.comparison.setWordWrap(True)
        self.comparison.setStyleSheet(f"color: {MUTED};")
        snapshot_layout.addWidget(self.comparison)
        restore_row = QHBoxLayout()
        self.section_combo = QComboBox()
        for label, path in self.SECTIONS:
            self.section_combo.addItem(label, path)
        self.restore_button = QPushButton("Restore selected snapshot")
        self.restore_button.setObjectName("primaryButton")
        self.restore_button.setEnabled(False)
        restore_row.addWidget(self.section_combo, 1)
        restore_row.addWidget(self.restore_button)
        snapshot_layout.addLayout(restore_row)

        splitter.addWidget(timeline_panel)
        splitter.addWidget(snapshot_panel)
        splitter.setSizes([380, 500])
        layout.addWidget(splitter, 1)
        warning = QLabel(
            "Restoring creates a new undo entry; it does not overwrite or delete the snapshot."
        )
        warning.setStyleSheet(f"color: {WARNING};")
        layout.addWidget(warning)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.snapshot_list.currentRowChanged.connect(self._selection_changed)
        self.restore_button.clicked.connect(self._restore)
        if self.snapshot_list.count():
            self.snapshot_list.setCurrentRow(self.snapshot_list.count() - 1)

    def _selection_changed(self, row: int) -> None:
        valid = 0 <= row < len(self._snapshots)
        self.restore_button.setEnabled(valid)
        if not valid:
            self.comparison.setText("Select a snapshot to compare it with the current draft.")
            return
        snapshot = self._snapshots[row]
        changes = snapshot.get("comparison", {})
        if isinstance(changes, dict):
            total = int(changes.get("total_changes", 0) or 0)
            sections = changes.get("modified_sections", [])
            paths = changes.get("changed_paths", [])
            self.comparison.setText(
                f"{total} change(s) since this snapshot.\n"
                f"Sections: {', '.join(str(item) for item in sections) or 'none'}\n"
                f"First changed fields: {', '.join(str(item) for item in paths) or 'none'}"
            )

    def _restore(self) -> None:
        row = self.snapshot_list.currentRow()
        if not 0 <= row < len(self._snapshots):
            return
        self.selected_snapshot_id = str(self._snapshots[row].get("snapshot_id", ""))
        self.selected_section = str(self.section_combo.currentData() or "")
        if self.selected_snapshot_id:
            self.accept()


__all__ = ["ProjectHistoryDialog"]
