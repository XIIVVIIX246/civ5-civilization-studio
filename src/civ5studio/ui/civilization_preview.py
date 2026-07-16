"""Presentation-only BNW-inspired previews for the current project draft."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, MUTED


def _source(data: dict, role: str) -> str:
    art = data.get("art", {}) if isinstance(data.get("art"), dict) else {}
    entry = art.get(role, {}) if isinstance(art.get(role), dict) else {}
    return str(entry.get("source", ""))


class FramedPortrait(QWidget):
    """Circular portrait whose decorative ring exists only in paintEvent."""

    def __init__(self, size: int = 112, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pixmap = QPixmap()
        self._primary = QColor("#8e2430")
        self._secondary = QColor("#e0bd5a")

    def set_preview(self, path: str, primary: str, secondary: str) -> None:
        self._pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        self._primary = QColor(primary) if QColor(primary).isValid() else QColor("#8e2430")
        self._secondary = QColor(secondary) if QColor(secondary).isValid() else QColor("#e0bd5a")
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(7, 7, self.width() - 14, self.height() - 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._secondary)
        painter.drawEllipse(rect)
        inner = rect.adjusted(8, 8, -8, -8)
        painter.setBrush(self._primary)
        painter.drawEllipse(inner)
        clip = QPainterPath()
        clip.addEllipse(inner.adjusted(3, 3, -3, -3))
        painter.save()
        painter.setClipPath(clip)
        if self._pixmap.isNull():
            painter.fillRect(inner, self._primary)
            painter.setPen(self._secondary)
            font = painter.font()
            font.setBold(True)
            font.setPointSize(max(12, self.width() // 5))
            painter.setFont(font)
            painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, "CIV")
        else:
            painter.drawPixmap(inner, self._pixmap, QRectF(self._pixmap.rect()))
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(ACCENT), 2.2))
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))


class SetupCard(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        top = QGridLayout()
        self.portrait = FramedPortrait(112)
        self.civ_name = QLabel("Unnamed Civilization")
        self.civ_name.setWordWrap(True)
        self.civ_name.setStyleSheet("font-size: 14pt; font-weight: 750;")
        self.leader = QLabel("Leader: Unnamed")
        self.leader.setStyleSheet(f"color: {MUTED};")
        top.addWidget(self.portrait, 0, 0, 2, 1)
        top.addWidget(self.civ_name, 0, 1)
        top.addWidget(self.leader, 1, 1)
        layout.addLayout(top)
        self.trait = QLabel("Trait: not named")
        self.trait.setWordWrap(True)
        self.trait.setStyleSheet(f"color: {ACCENT}; font-weight: 650;")
        self.uniques = QLabel("Unique roster has not been configured.")
        self.uniques.setWordWrap(True)
        layout.addWidget(self.trait)
        layout.addWidget(self.uniques)
        layout.addStretch(1)

    def set_values(self, data: dict) -> None:
        civ = data.get("civilization", {}) if isinstance(data.get("civilization"), dict) else {}
        leader = data.get("leader", {}) if isinstance(data.get("leader"), dict) else {}
        mechanics = data.get("mechanics", {}) if isinstance(data.get("mechanics"), dict) else {}
        trait = mechanics.get("trait", {}) if isinstance(mechanics.get("trait"), dict) else {}
        colors = civ.get("colors", {}) if isinstance(civ.get("colors"), dict) else {}
        self.civ_name.setText(str(civ.get("name") or civ.get("short_name") or "Unnamed Civilization"))
        self.leader.setText(f"Leader: {leader.get('name') or 'Unnamed'}")
        self.trait.setText(f"Trait: {trait.get('name') or 'not named'}")
        rows = mechanics.get("uniques", []) if isinstance(mechanics.get("uniques"), list) else []
        labels = [str(row.get("name") or row.get("base_template") or row.get("kind", "Unique")).strip() for row in rows if isinstance(row, dict)]
        self.uniques.setText("Unique roster\n" + ("  ·  ".join(labels) if labels else "Not configured"))
        self.portrait.set_preview(
            _source(data, "civilization_icon"),
            str(colors.get("primary", "#8e2430")),
            str(colors.get("secondary", "#e0bd5a")),
        )


class DawnPreview(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")
        self.setMinimumHeight(300)
        self._scene = QPixmap()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addStretch(1)
        self.heading = QLabel("The Dawn of a New Civilization")
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet("font-size: 14pt; font-weight: 750;")
        self.quote = QLabel("Add a Dawn of Man quote to preview it here.")
        self.quote.setWordWrap(True)
        self.quote.setStyleSheet("font-style: italic;")
        layout.addWidget(self.heading)
        layout.addWidget(self.quote)

    def set_values(self, data: dict) -> None:
        civ = data.get("civilization", {}) if isinstance(data.get("civilization"), dict) else {}
        leader = data.get("leader", {}) if isinstance(data.get("leader"), dict) else {}
        leader_art = leader.get("art", {}) if isinstance(leader.get("art"), dict) else {}
        dawn_source = _source(data, "dawn_of_man")
        leader_source = str(leader_art.get("leader_scene", ""))
        scene = (
            dawn_source
            if dawn_source and Path(dawn_source).is_file()
            else leader_source
        )
        self._scene = QPixmap(scene) if scene and Path(scene).is_file() else QPixmap()
        self.heading.setText(
            f"{leader.get('name') or 'Your leader'} of {civ.get('short_name') or civ.get('name') or 'your civilization'}"
        )
        self.quote.setText(str(civ.get("dawn_of_man_quote") or "Add a Dawn of Man quote to preview it here."))
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self.rect()
        if self._scene.isNull():
            painter.fillRect(rect, QColor("#182130"))
        else:
            scaled = self._scene.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            source_x = max(0, (scaled.width() - rect.width()) // 2)
            source_y = max(0, (scaled.height() - rect.height()) // 2)
            painter.drawPixmap(rect, scaled, QRectF(source_x, source_y, rect.width(), rect.height()))
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0.0, QColor(8, 11, 16, 45))
        gradient.setColorAt(0.55, QColor(8, 11, 16, 120))
        gradient.setColorAt(1.0, QColor(8, 11, 16, 235))
        painter.fillRect(rect, gradient)


class AssetSummary(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewSurface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.unit_grid = QGridLayout()
        self.unit_grid.setSpacing(6)
        layout.addLayout(self.unit_grid)
        layout.addStretch(1)

    def set_values(self, data: dict) -> None:
        art = data.get("art", {}) if isinstance(data.get("art"), dict) else {}
        roles = (
            ("civilization_icon", "Civilization portrait"),
            ("civilization_alpha", "Alpha emblem"),
            ("leader_portrait", "Leader portrait"),
            ("dawn_of_man", "Dawn of Man"),
            ("map_image", "Setup map"),
        )
        lines = []
        for role, label in roles:
            entry = art.get(role, {}) if isinstance(art.get(role), dict) else {}
            source = str(entry.get("source", ""))
            lines.append(f"{'✓' if source and Path(source).is_file() else '○'}  {label}")
        lines.append("")
        lines.append("Preview frames are presentation-only. Exported art never receives a gold ring.")
        self.status.setText("\n".join(lines))
        while self.unit_grid.count():
            item = self.unit_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        mechanics = (
            data.get("mechanics", {})
            if isinstance(data.get("mechanics"), dict)
            else {}
        )
        uniques = mechanics.get("uniques", [])
        unit_rows = [
            row
            for row in uniques
            if isinstance(row, dict) and row.get("kind") == "unit"
        ] if isinstance(uniques, list) else []
        for column, row in enumerate(unit_rows[:3]):
            unit_art = row.get("art", {}) if isinstance(row.get("art"), dict) else {}
            title = QLabel(str(row.get("name") or row.get("base_template") or "Unique unit"))
            title.setWordWrap(True)
            title.setStyleSheet("font-weight: 650;")
            self.unit_grid.addWidget(title, 0, column)
            for asset_row, (key, label) in enumerate(
                (
                    ("icon_source", "Portrait"),
                    ("unit_flag_source", "Unit flag"),
                    ("strategic_view_source", "Strategic View"),
                ),
                start=1,
            ):
                source = str(unit_art.get(key, ""))
                preview = QLabel(f"○ {label}")
                preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                preview.setMinimumSize(78, 58)
                preview.setStyleSheet("background: #10151d; border-radius: 4px;")
                if source and Path(source).is_file():
                    pixmap = QPixmap(source)
                    if not pixmap.isNull():
                        preview.setPixmap(
                            pixmap.scaled(
                                72,
                                52,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                        preview.setToolTip(f"{label}: {source}")
                self.unit_grid.addWidget(preview, asset_row, column)


class CivilizationPreview(QWidget):
    """Three linked previews backed solely by the current plain UI dictionary."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        note = QLabel("Live preview · presentation only")
        note.setStyleSheet(f"color: {MUTED};")
        self.tabs = QTabWidget()
        self.setup = SetupCard()
        self.dawn = DawnPreview()
        self.assets = AssetSummary()
        self.tabs.addTab(self.setup, "Setup Card")
        self.tabs.addTab(self.dawn, "Dawn of Man")
        self.tabs.addTab(self.assets, "Asset Check")
        layout.addWidget(note)
        layout.addWidget(self.tabs, 1)

    def set_values(self, data: dict) -> None:
        self.setup.set_values(data)
        self.dawn.set_values(data)
        self.assets.set_values(data)
