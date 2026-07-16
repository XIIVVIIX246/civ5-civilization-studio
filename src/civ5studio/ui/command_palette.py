"""Small keyboard-first command palette for the desktop workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import MUTED


@dataclass(frozen=True, slots=True)
class PaletteCommand:
    command_id: str
    label: str
    category: str
    callback: Callable[[], None]
    keywords: str = ""


class CommandPalette(QDialog):
    """Searches commands locally and invokes only an explicit user selection."""

    def __init__(
        self,
        commands: Iterable[PaletteCommand],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Go to anything")
        self.setAccessibleName("Go to anything command palette")
        self.setAccessibleDescription(
            "Search project actions and press Enter to run the selected command."
        )
        self.setModal(True)
        self.resize(660, 470)
        self._commands = list(commands)
        layout = QVBoxLayout(self)
        title = QLabel("Go to any step, field, or project action")
        title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        subtitle = QLabel(
            "Type to filter, then press Enter. Nothing runs until you choose a command."
        )
        subtitle.setStyleSheet(f"color: {MUTED};")
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Try: art, Lua, validate, leader name, snapshot..."
        )
        self.search.setAccessibleName("Command search")
        self.search.setAccessibleDescription(
            "Type one or more words. Use Up and Down to choose a result, then press Enter."
        )
        self.search.setClearButtonEnabled(True)
        self.results = QListWidget()
        self.results.setAccessibleName("Matching commands")
        self.results.setAccessibleDescription(
            "Filtered commands. Activate a command with Enter or a double-click."
        )
        self.status = QLabel()
        self.status.setAccessibleName("Command result count")
        self.status.setStyleSheet(f"color: {MUTED};")
        title.setBuddy(self.search)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.search)
        layout.addWidget(self.status)
        layout.addWidget(self.results, 1)
        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._invoke_current)
        self.results.itemActivated.connect(lambda _item: self._invoke_current())
        self.search.installEventFilter(self)
        self._refresh("")

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self.search.clear()
        # `clear()` emits only when text actually changes. Refresh explicitly
        # so reusing the dialog always restores the full list and first row.
        self._refresh("")
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _refresh(self, query: str) -> None:
        tokens = [token.casefold() for token in query.split() if token.strip()]
        self.results.clear()
        for index, command in enumerate(self._commands):
            haystack = " ".join(
                (command.label, command.category, command.command_id, command.keywords)
            ).casefold()
            if tokens and not all(token in haystack for token in tokens):
                continue
            item = QListWidgetItem(f"{command.label}    ·    {command.category}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)
        count = self.results.count()
        self.status.setText(f"{count} matching command{'s' if count != 1 else ''}")

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
            count = self.results.count()
            if count and key in {
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
                Qt.Key.Key_PageUp,
                Qt.Key.Key_PageDown,
            }:
                row = max(0, self.results.currentRow())
                if key == Qt.Key.Key_Up:
                    row = max(0, row - 1)
                elif key == Qt.Key.Key_Down:
                    row = min(count - 1, row + 1)
                elif key == Qt.Key.Key_PageUp:
                    row = max(0, row - 10)
                else:
                    row = min(count - 1, row + 10)
                self.results.setCurrentRow(row)
                self.results.scrollToItem(self.results.currentItem())
                return True
        return super().eventFilter(watched, event)

    def _invoke_current(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not 0 <= index < len(self._commands):
            return
        callback = self._commands[index].callback
        self.accept()
        callback()
