"""Reusable presentation-only widgets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .project_health import SEVERITY_LABELS, humanize_location
from .theme import ACCENT, ERROR, MUTED, SUCCESS, WARNING


class SectionCard(QFrame):
    """A consistent titled surface used by every workflow page."""

    def __init__(self, title: str, description: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 18)
        self.body.setSpacing(10)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 13pt; font-weight: 700;")
        self.body.addWidget(heading)
        if description:
            summary = QLabel(description)
            summary.setWordWrap(True)
            summary.setStyleSheet(f"color: {MUTED};")
            self.body.addWidget(summary)


class AssetDropZone(QFrame):
    """Collects a source PNG path without modifying the source file."""

    pathChanged = Signal(str)
    selected = Signal(str, str)

    def __init__(self, role: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self._path = ""
        self.setAcceptDrops(True)
        self.setMinimumSize(190, 185)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "AssetDropZone { background: #151b24; border: 1px dashed #5a687d; border-radius: 7px; }"
            f"AssetDropZone:hover {{ border-color: {ACCENT}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight: 650;")
        self.preview = QLabel("Drop a PNG here")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(105)
        self.preview.setStyleSheet(f"color: {MUTED}; background: #10151d; border-radius: 4px;")
        self.name_label = QLabel("No source selected")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        browse = QPushButton("Choose PNG")
        browse.clicked.connect(self._browse)
        layout.addWidget(self.title)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.name_label)
        layout.addWidget(browse)

    @property
    def path(self) -> str:
        return self._path

    def set_path(self, value: str, emit: bool = False) -> None:
        self._path = value or ""
        path = Path(self._path) if self._path else None
        if path and path.is_file():
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.preview.setText("PNG could not be previewed")
                self.preview.setPixmap(QPixmap())
            else:
                self.preview.setPixmap(
                    pixmap.scaled(
                        150,
                        105,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            self.name_label.setText(path.name)
            self.name_label.setToolTip(str(path))
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Drop a PNG here")
            self.name_label.setText("No source selected")
            self.name_label.setToolTip("")
        if emit:
            self.pathChanged.emit(self._path)
            self.selected.emit(self.role, self._path)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        self.selected.emit(self.role, self._path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(".png"):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.set_path(urls[0].toLocalFile(), emit=True)
            event.acceptProposedAction()

    def _browse(self) -> None:
        value, _ = QFileDialog.getOpenFileName(self, f"Choose {self.title.text()}", "", "PNG images (*.png)")
        if value:
            self.set_path(value, emit=True)


class PreviewIcon(QWidget):
    """Shows a source under a preview-only Firaxis-style circular frame.

    This widget never exposes a rendered image or writes pixels. The decorative
    ring exists only in paintEvent and therefore cannot leak into exports.
    """

    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview_size = size
        self._pixmap = QPixmap()
        self._zoom = 100
        self._offset_x = 0
        self._offset_y = 0
        display = max(46, min(size, 112))
        self.setFixedSize(display + 12, display + 32)

    def set_source(self, path: str) -> None:
        self._pixmap = QPixmap(path) if path else QPixmap()
        self.update()

    def set_transform(self, zoom: int, offset_x: int, offset_y: int) -> None:
        self._zoom, self._offset_x, self._offset_y = zoom, offset_x, offset_y
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width() - 12, self.height() - 28)
        rect = QRectF(6, 4, side, side)
        painter.fillRect(rect, QColor("#10151d"))
        if not self._pixmap.isNull():
            scale = (172 / 256) * (self._zoom / 100)
            art_side = side * scale
            target = QRectF(
                rect.center().x() - art_side / 2 + self._offset_x * side / 200,
                rect.center().y() - art_side / 2 + self._offset_y * side / 200,
                art_side,
                art_side,
            )
            clip = QPainterPath()
            clip.addEllipse(target)
            painter.save()
            painter.setClipPath(clip)
            painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
            painter.restore()
        painter.setPen(QPen(QColor(ACCENT), max(1.5, side / 48)))
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
        painter.setPen(QColor(MUTED))
        painter.drawText(QRectF(0, side + 8, self.width(), 20), Qt.AlignmentFlag.AlignCenter, f"{self.preview_size}px")


class MultiSizePreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.icons = [PreviewIcon(size) for size in (256, 128, 80, 64, 45, 32)]
        for icon in self.icons:
            layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addStretch(1)

    def set_source(self, path: str) -> None:
        for icon in self.icons:
            icon.set_source(path)

    def set_transform(self, zoom: int, offset_x: int, offset_y: int) -> None:
        for icon in self.icons:
            icon.set_transform(zoom, offset_x, offset_y)


class ColorButton(QWidget):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#3f5b91", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(42, 30)
        self.swatch.clicked.connect(self._choose)
        self.label = QLabel()
        layout.addWidget(self.swatch)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self._refresh()

    @property
    def color(self) -> str:
        return self._color.name(QColor.NameFormat.HexRgb)

    def set_color(self, value: str, emit: bool = False) -> None:
        color = QColor(value)
        if color.isValid():
            self._color = color
            self._refresh()
            if emit:
                self.colorChanged.emit(self.color)

    def _refresh(self) -> None:
        self.swatch.setStyleSheet(f"background: {self.color}; border: 1px solid #ccd2dc;")
        self.label.setText(self.color.upper())

    def _choose(self) -> None:
        color = QColorDialog.getColor(self._color, self, "Choose civilization color")
        if color.isValid():
            self.set_color(color.name(), emit=True)


class StringListEditor(QWidget):
    changed = Signal()

    def __init__(self, placeholder: str, minimum_recommended: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.minimum_recommended = minimum_recommended
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(placeholder)
        self.editor.setMinimumHeight(145)
        self.count = QLabel()
        self.count.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.editor)
        layout.addWidget(self.count)
        self.editor.textChanged.connect(self._on_changed)
        self._on_changed()

    def values(self) -> list[str]:
        return [line.strip() for line in self.editor.toPlainText().splitlines() if line.strip()]

    def set_values(self, values: Iterable[str]) -> None:
        self.editor.setPlainText("\n".join(values))

    def _on_changed(self) -> None:
        total = len(self.values())
        state = SUCCESS if total >= self.minimum_recommended else WARNING
        self.count.setText(f"{total} entries · {self.minimum_recommended} recommended")
        self.count.setStyleSheet(f"color: {state};")
        self.changed.emit()


class IssueTree(QTreeWidget):
    issueActivated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Priority", "Field", "What needs attention"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(210)
        self.header().setStretchLastSection(True)
        self.setColumnWidth(0, 90)
        self.setColumnWidth(1, 190)
        self.setAccessibleName("Validation issues; activate a row to open its field")
        self.itemClicked.connect(self._activate)
        self.itemActivated.connect(self._activate)

    def set_issues(self, issues: Iterable[dict[str, str]]) -> None:
        self.clear()
        colors = {"ERROR": ERROR, "WARNING": WARNING, "INFO": MUTED, "PASS": SUCCESS}
        for issue in issues:
            severity = issue.get("severity", issue.get("level", "INFO")).upper()
            location = issue.get("location", issue.get("field", ""))
            item = QTreeWidgetItem(
                [
                    SEVERITY_LABELS.get(severity, "Note"),
                    humanize_location(location),
                    issue.get("message", ""),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, location)
            item.setForeground(0, QColor(colors.get(severity, MUTED)))
            item.setToolTip(1, f"Technical location: {location}")
            detail = issue.get("hint", "") or issue.get("code", "")
            if detail:
                item.setToolTip(2, detail)
            self.addTopLevelItem(item)

    def _activate(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        location = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(location, str):
            self.issueActivated.emit(location)


class LogPanel(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(4000)
        self.setMinimumHeight(180)
        self.setPlaceholderText("Build and validation messages will appear here.")

    def append_message(self, message: str) -> None:
        self.appendPlainText(message.rstrip())
