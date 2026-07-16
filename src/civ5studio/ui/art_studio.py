"""Read-only, direct-manipulation source-art preview widgets.

This module deliberately has no save, export, or filesystem-write API.  It
loads a source PNG into Qt-owned memory and paints checkerboard, safe-zone, and
Firaxis-style frame overlays for presentation only.  Callers retain ownership
of the source file and of any eventual art-generation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QImageReader,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, MUTED, SUCCESS, WARNING


ART_PREVIEW_SIZES = (256, 128, 80, 64, 45, 32)
SAFE_ZONE_DIAMETER_RATIO = 172 / 256
MIN_ZOOM = 25
MAX_ZOOM = 800
MIN_OFFSET = -200
MAX_OFFSET = 200


@dataclass(frozen=True, slots=True)
class ArtTransform:
    """Portable transform matching the existing ArtPage project contract."""

    zoom: int = 100
    offset_x: int = 0
    offset_y: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "zoom": self.zoom,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
        }

    @classmethod
    def coerce(
        cls,
        value: ArtTransform | Mapping[str, object] | int = 100,
        offset_x: int | None = None,
        offset_y: int | None = None,
    ) -> ArtTransform:
        if isinstance(value, ArtTransform):
            zoom = value.zoom
            x = value.offset_x
            y = value.offset_y
        elif isinstance(value, Mapping):
            zoom = _integer(value.get("zoom", 100), 100)
            x = _integer(value.get("offset_x", 0), 0)
            y = _integer(value.get("offset_y", 0), 0)
        else:
            zoom = _integer(value, 100)
            x = _integer(offset_x, 0)
            y = _integer(offset_y, 0)
        return cls(
            zoom=max(MIN_ZOOM, min(MAX_ZOOM, zoom)),
            offset_x=max(MIN_OFFSET, min(MAX_OFFSET, x)),
            offset_y=max(MIN_OFFSET, min(MAX_OFFSET, y)),
        )


def _integer(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return fallback


def _square_rect(widget: QWidget, margin: float = 8.0) -> QRectF:
    width = max(0.0, float(widget.width()) - margin * 2)
    height = max(0.0, float(widget.height()) - margin * 2)
    side = max(0.0, min(width, height))
    return QRectF(
        (widget.width() - side) / 2,
        (widget.height() - side) / 2,
        side,
        side,
    )


def _safe_zone_rect(canvas_rect: QRectF) -> QRectF:
    side = canvas_rect.width() * SAFE_ZONE_DIAMETER_RATIO
    return QRectF(
        canvas_rect.center().x() - side / 2,
        canvas_rect.center().y() - side / 2,
        side,
        side,
    )


def _source_target_rect(
    image: QImage, canvas_rect: QRectF, transform: ArtTransform
) -> QRectF:
    if image.isNull() or canvas_rect.isEmpty():
        return QRectF()
    safe_side = canvas_rect.width() * SAFE_ZONE_DIAMETER_RATIO
    aspect = image.width() / max(1, image.height())
    if aspect >= 1:
        base_width = safe_side
        base_height = safe_side / aspect
    else:
        base_height = safe_side
        base_width = safe_side * aspect
    factor = transform.zoom / 100
    width = base_width * factor
    height = base_height * factor
    center = canvas_rect.center() + QPointF(
        transform.offset_x * canvas_rect.width() / 200,
        transform.offset_y * canvas_rect.height() / 200,
    )
    return QRectF(center.x() - width / 2, center.y() - height / 2, width, height)


def _paint_checkerboard(painter: QPainter, rect: QRectF, cell: int = 12) -> None:
    painter.fillRect(rect, QColor("#d7d9dd"))
    painter.save()
    painter.setClipRect(rect)
    start_x = int(rect.left()) - cell
    start_y = int(rect.top()) - cell
    end_x = int(rect.right()) + cell
    end_y = int(rect.bottom()) + cell
    dark = QColor("#aeb3bb")
    for y in range(start_y, end_y, cell):
        row = (y - start_y) // cell
        for x in range(start_x, end_x, cell):
            column = (x - start_x) // cell
            if (row + column) % 2:
                painter.fillRect(QRectF(x, y, cell, cell), dark)
    painter.restore()


def _paint_firaxis_frame(painter: QPainter, rect: QRectF) -> None:
    """Paint a restrained preview overlay; this never touches source pixels."""

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    width = max(1.0, rect.width() / 42)
    painter.setPen(QPen(QColor("#19150d"), width * 2.3))
    painter.drawEllipse(rect.adjusted(width, width, -width, -width))
    painter.setPen(QPen(QColor("#8c6b2d"), width * 1.55))
    painter.drawEllipse(rect.adjusted(width, width, -width, -width))
    painter.setPen(QPen(QColor(ACCENT), width * 0.7))
    painter.drawEllipse(rect.adjusted(width, width, -width, -width))
    painter.setPen(QPen(QColor("#f1d89a"), max(1.0, width * 0.18)))
    painter.drawEllipse(
        rect.adjusted(width * 1.4, width * 1.4, -width * 1.4, -width * 1.4)
    )
    painter.restore()


def _paint_source(
    painter: QPainter,
    image: QImage,
    canvas_rect: QRectF,
    transform: ArtTransform,
    *,
    circular_clip: bool,
) -> None:
    if image.isNull():
        return
    painter.save()
    if circular_clip:
        clip = QPainterPath()
        clip.addEllipse(_safe_zone_rect(canvas_rect))
        painter.setClipPath(clip)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(_source_target_rect(image, canvas_rect, transform), image)
    painter.restore()


def _alpha_statistics(image: QImage) -> tuple[int, int, int]:
    """Return transparent, translucent, and opaque pixel counts exactly."""

    if image.isNull():
        return (0, 0, 0)
    if not image.hasAlphaChannel():
        return (0, 0, image.width() * image.height())
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = bytes(rgba.constBits())
    stride = rgba.bytesPerLine()
    transparent = 0
    translucent = 0
    opaque = 0
    for y in range(rgba.height()):
        row = raw[y * stride : y * stride + rgba.width() * 4]
        for alpha in row[3::4]:
            if alpha == 0:
                transparent += 1
            elif alpha == 255:
                opaque += 1
            else:
                translucent += 1
    return (transparent, translucent, opaque)


class SourceArtCanvas(QWidget):
    """Interactive, read-only view of one in-memory source PNG."""

    transformChanged = Signal(dict)
    sourceChanged = Signal(str)
    diagnosticsChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_path = ""
        self._image = QImage()
        self._image_format = ""
        self._source_status = "empty"
        self._source_message = "No source PNG selected."
        self._alpha_counts = (0, 0, 0)
        self._transform = ArtTransform()
        self._drag_origin: QPointF | None = None
        self._drag_transform = ArtTransform()
        self._checkerboard_visible = True
        self._safe_zone_visible = True
        self._firaxis_frame_visible = True
        self._minimum_zoom = MIN_ZOOM
        self._maximum_zoom = MAX_ZOOM
        self._minimum_offset = MIN_OFFSET
        self._maximum_offset = MAX_OFFSET
        self.setObjectName("sourceArtCanvas")
        self.setAccessibleName("Source art positioning canvas")
        self.setAccessibleDescription(
            "Read-only PNG preview. Drag to pan, use the mouse wheel or plus and "
            "minus to zoom, and use arrow keys to nudge the source."
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setToolTip(
            "Drag to pan · wheel to zoom · arrows to nudge · Shift+arrows for 10px · "
            "Home centers · 0 resets"
        )

    @property
    def source_path(self) -> str:
        return self._source_path

    @property
    def checkerboard_visible(self) -> bool:
        return self._checkerboard_visible

    @property
    def safe_zone_visible(self) -> bool:
        return self._safe_zone_visible

    @property
    def firaxis_frame_visible(self) -> bool:
        return self._firaxis_frame_visible

    def source_image(self) -> QImage:
        """Return an implicitly shared copy; the loaded source remains untouched."""

        return QImage(self._image)

    def set_source(self, path: str, *, emit: bool = False) -> None:
        self._source_path = str(path or "")
        self._image = QImage()
        self._image_format = ""
        self._alpha_counts = (0, 0, 0)
        candidate = Path(self._source_path) if self._source_path else None
        if candidate is None:
            self._source_status = "empty"
            self._source_message = "No source PNG selected."
        elif candidate.suffix.lower() != ".png":
            self._source_status = "not_png"
            self._source_message = "The selected source is not a PNG file."
        elif not candidate.is_file():
            self._source_status = "missing"
            self._source_message = "The selected PNG does not exist."
        else:
            reader = QImageReader(str(candidate))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                self._source_status = "unreadable"
                detail = reader.errorString().strip()
                self._source_message = "PNG could not be decoded."
                if detail:
                    self._source_message += f" {detail}"
            else:
                self._image = image
                self._image_format = (
                    bytes(reader.format()).decode("ascii", "replace").upper() or "PNG"
                )
                self._alpha_counts = _alpha_statistics(image)
                self._source_status = "ready"
                self._source_message = "Source PNG loaded read-only."
        self.update()
        self.diagnosticsChanged.emit(self.diagnostics())
        if emit:
            self.sourceChanged.emit(self._source_path)

    def get_transform(self) -> dict[str, int]:
        return self._transform.as_dict()

    def set_transform(
        self,
        value: ArtTransform | Mapping[str, object] | int = 100,
        offset_x: int | None = None,
        offset_y: int | None = None,
        *,
        emit: bool = False,
    ) -> None:
        requested = ArtTransform.coerce(value, offset_x, offset_y)
        transform = ArtTransform(
            max(self._minimum_zoom, min(self._maximum_zoom, requested.zoom)),
            max(self._minimum_offset, min(self._maximum_offset, requested.offset_x)),
            max(self._minimum_offset, min(self._maximum_offset, requested.offset_y)),
        )
        if transform == self._transform:
            return
        self._transform = transform
        self.update()
        self.diagnosticsChanged.emit(self.diagnostics())
        if emit:
            self.transformChanged.emit(self.get_transform())

    def set_zoom_range(self, minimum: int, maximum: int, *, emit: bool = True) -> None:
        """Apply a caller-owned contract while preserving broad widget defaults."""

        low = max(MIN_ZOOM, int(minimum))
        high = min(MAX_ZOOM, int(maximum))
        if low > high:
            raise ValueError("minimum zoom must not exceed maximum zoom")
        self._minimum_zoom = low
        self._maximum_zoom = high
        # Match QSlider/QSpinBox range semantics: when a new range clamps the
        # current value, observers receive the accepted transform by default.
        self.set_transform(self._transform, emit=emit)

    def zoom_range(self) -> tuple[int, int]:
        return (self._minimum_zoom, self._maximum_zoom)

    def set_offset_range(self, minimum: int, maximum: int, *, emit: bool = True) -> None:
        low = max(MIN_OFFSET, int(minimum))
        high = min(MAX_OFFSET, int(maximum))
        if low > high:
            raise ValueError("minimum offset must not exceed maximum offset")
        self._minimum_offset = low
        self._maximum_offset = high
        self.set_transform(self._transform, emit=emit)

    def offset_range(self) -> tuple[int, int]:
        return (self._minimum_offset, self._maximum_offset)

    def center_source(self, *, emit: bool = True) -> None:
        self.set_transform(
            ArtTransform(self._transform.zoom, 0, 0),
            emit=emit,
        )

    def reset_transform(self, *, emit: bool = True) -> None:
        self.set_transform(ArtTransform(), emit=emit)

    def set_checkerboard_visible(self, visible: bool) -> None:
        self._checkerboard_visible = bool(visible)
        self.update()

    def set_safe_zone_visible(self, visible: bool) -> None:
        self._safe_zone_visible = bool(visible)
        self.update()

    def set_firaxis_frame_visible(self, visible: bool) -> None:
        self._firaxis_frame_visible = bool(visible)
        self.update()

    def diagnostics(self) -> dict[str, object]:
        clipping_edges = self._clipping_edges()
        transparent, translucent, opaque = self._alpha_counts
        total = transparent + translucent + opaque
        messages = [self._source_message]
        if self._source_status == "ready":
            if self._image.width() != 1024 or self._image.height() != 1024:
                messages.append(
                    "A square 1024×1024 source is recommended for icon art."
                )
            if not self._image.hasAlphaChannel():
                messages.append("The source has no alpha channel.")
            elif transparent + translucent == 0:
                messages.append("The alpha channel contains no transparent pixels.")
            if clipping_edges:
                messages.append(
                    "The current transform crosses the circular safe-zone bounds: "
                    + ", ".join(clipping_edges)
                    + "."
                )
        return {
            "status": self._source_status,
            "path": self._source_path,
            "file_name": Path(self._source_path).name if self._source_path else "",
            "format": self._image_format,
            "width": self._image.width(),
            "height": self._image.height(),
            "is_square": bool(
                not self._image.isNull() and self._image.width() == self._image.height()
            ),
            "recommended_1024_square": bool(
                self._image.width() == 1024 and self._image.height() == 1024
            ),
            "has_alpha_channel": self._image.hasAlphaChannel(),
            "has_transparency": transparent + translucent > 0,
            "transparent_pixels": transparent,
            "translucent_pixels": translucent,
            "opaque_pixels": opaque,
            "total_pixels": total,
            "transform_clipped": bool(clipping_edges),
            "clipping_edges": list(clipping_edges),
            "safe_zone_diameter_ratio": SAFE_ZONE_DIAMETER_RATIO,
            "messages": messages,
        }

    def _clipping_edges(self) -> tuple[str, ...]:
        if self._image.isNull():
            return ()
        normalized_canvas = QRectF(0, 0, 1000, 1000)
        safe = _safe_zone_rect(normalized_canvas)
        target = _source_target_rect(self._image, normalized_canvas, self._transform)
        tolerance = 0.01
        edges: list[str] = []
        if target.left() < safe.left() - tolerance:
            edges.append("left")
        if target.right() > safe.right() + tolerance:
            edges.append("right")
        if target.top() < safe.top() - tolerance:
            edges.append("top")
        if target.bottom() > safe.bottom() + tolerance:
            edges.append("bottom")
        return tuple(edges)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        canvas = _square_rect(self)
        if self._checkerboard_visible:
            _paint_checkerboard(painter, canvas)
        else:
            painter.fillRect(canvas, QColor("#10151d"))
        _paint_source(
            painter,
            self._image,
            canvas,
            self._transform,
            circular_clip=False,
        )
        if self._safe_zone_visible:
            safe = _safe_zone_rect(canvas)
            shade = QPainterPath()
            shade.addRect(canvas)
            hole = QPainterPath()
            hole.addEllipse(safe)
            shade = shade.subtracted(hole)
            painter.fillPath(shade, QColor(8, 12, 18, 112))
            painter.setPen(QPen(QColor("#e8edf5"), 1.4, Qt.PenStyle.DashLine))
            painter.drawEllipse(safe)
        if self._firaxis_frame_visible:
            _paint_firaxis_frame(painter, canvas)
        if self._image.isNull():
            painter.setPen(QColor(MUTED))
            painter.drawText(
                canvas,
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._source_message,
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._drag_origin = event.position()
            self._drag_transform = self._transform
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if (
            self._drag_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            side = max(1.0, _square_rect(self).width())
            delta = event.position() - self._drag_origin
            self.set_transform(
                ArtTransform(
                    self._drag_transform.zoom,
                    self._drag_transform.offset_x + round(delta.x() * 200 / side),
                    self._drag_transform.offset_y + round(delta.y() * 200 / side),
                ),
                emit=True,
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_origin is not None
        ):
            self._drag_origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        steps = delta / 120
        old = self._transform
        new_zoom = max(
            self._minimum_zoom,
            min(self._maximum_zoom, round(old.zoom + steps * 10)),
        )
        if new_zoom == old.zoom:
            event.accept()
            return
        canvas = _square_rect(self)
        if canvas.width() <= 0:
            self.set_transform(
                ArtTransform(new_zoom, old.offset_x, old.offset_y), emit=True
            )
            event.accept()
            return
        pointer = event.position()
        center = canvas.center()
        old_offset = QPointF(
            old.offset_x * canvas.width() / 200,
            old.offset_y * canvas.height() / 200,
        )
        ratio = new_zoom / old.zoom
        new_image_center = pointer - (pointer - (center + old_offset)) * ratio
        new_offset = new_image_center - center
        self.set_transform(
            ArtTransform(
                new_zoom,
                round(new_offset.x() * 200 / canvas.width()),
                round(new_offset.y() * 200 / canvas.height()),
            ),
            emit=True,
        )
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        x = self._transform.offset_x
        y = self._transform.offset_y
        key = event.key()
        if key == Qt.Key.Key_Left:
            x -= step
        elif key == Qt.Key.Key_Right:
            x += step
        elif key == Qt.Key.Key_Up:
            y -= step
        elif key == Qt.Key.Key_Down:
            y += step
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_transform(ArtTransform(self._transform.zoom + 10, x, y), emit=True)
            event.accept()
            return
        elif key == Qt.Key.Key_Minus:
            self.set_transform(ArtTransform(self._transform.zoom - 10, x, y), emit=True)
            event.accept()
            return
        elif key in (Qt.Key.Key_0, Qt.Key.Key_R):
            self.reset_transform(emit=True)
            event.accept()
            return
        elif key == Qt.Key.Key_Home:
            self.center_source(emit=True)
            event.accept()
            return
        else:
            super().keyPressEvent(event)
            return
        self.set_transform(ArtTransform(self._transform.zoom, x, y), emit=True)
        event.accept()


class ArtSizePreview(QWidget):
    """One presentation-only member of the synchronized BNW size ladder."""

    def __init__(self, export_size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.export_size = int(export_size)
        self._image = QImage()
        self._transform = ArtTransform()
        self._checkerboard_visible = True
        self._safe_zone_visible = True
        self._firaxis_frame_visible = True
        display = max(46, min(self.export_size, 112))
        self.setFixedSize(display + 12, display + 30)
        self.setAccessibleName(f"{self.export_size} pixel synchronized art preview")
        self.setAccessibleDescription(
            "Presentation-only circular preview. The Firaxis frame is never written to pixels."
        )
        self.setToolTip(
            f"Synchronized {self.export_size}px preview; frame is not source art"
        )

    def set_image(self, image: QImage) -> None:
        self._image = QImage(image)
        self.update()

    def set_transform(self, transform: ArtTransform) -> None:
        self._transform = transform
        self.update()

    def get_transform(self) -> dict[str, int]:
        return self._transform.as_dict()

    def set_overlays(
        self, *, checkerboard: bool, safe_zone: bool, firaxis_frame: bool
    ) -> None:
        self._checkerboard_visible = checkerboard
        self._safe_zone_visible = safe_zone
        self._firaxis_frame_visible = firaxis_frame
        self.update()

    @property
    def firaxis_frame_visible(self) -> bool:
        return self._firaxis_frame_visible

    @property
    def safe_zone_visible(self) -> bool:
        return self._safe_zone_visible

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width() - 12, self.height() - 26)
        canvas = QRectF((self.width() - side) / 2, 2, side, side)
        if self._checkerboard_visible:
            _paint_checkerboard(painter, canvas, int(max(4, side // 9)))
        else:
            painter.fillRect(canvas, QColor("#10151d"))
        _paint_source(
            painter,
            self._image,
            canvas,
            self._transform,
            circular_clip=True,
        )
        if self._safe_zone_visible:
            painter.setPen(QPen(QColor("#e8edf5"), 1, Qt.PenStyle.DashLine))
            painter.drawEllipse(_safe_zone_rect(canvas))
        if self._firaxis_frame_visible:
            _paint_firaxis_frame(painter, canvas)
        painter.setPen(QColor(MUTED))
        painter.drawText(
            QRectF(0, side + 6, self.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.export_size}px",
        )


class SynchronizedArtPreviews(QWidget):
    """The complete 256/128/80/64/45/32 preview ladder."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Synchronized Civilization V icon previews")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.previews = [ArtSizePreview(size, self) for size in ART_PREVIEW_SIZES]
        for preview in self.previews:
            layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addStretch(1)

    def set_image(self, image: QImage) -> None:
        for preview in self.previews:
            preview.set_image(image)

    def set_transform(self, transform: ArtTransform) -> None:
        for preview in self.previews:
            preview.set_transform(transform)

    def set_overlays(
        self, *, checkerboard: bool, safe_zone: bool, firaxis_frame: bool
    ) -> None:
        for preview in self.previews:
            preview.set_overlays(
                checkerboard=checkerboard,
                safe_zone=safe_zone,
                firaxis_frame=firaxis_frame,
            )


class ArtStudioWidget(QWidget):
    """Reusable source-PNG manipulator and synchronized preview surface.

    `transformChanged` is emitted only for direct/user-requested mutations.
    Programmatic `set_transform(..., emit=False)` therefore supports loading a
    project without marking it dirty.
    """

    transformChanged = Signal(dict)
    sourceChanged = Signal(str)
    diagnosticsChanged = Signal(dict)
    overlaysChanged = Signal(bool, bool, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Art source transform studio")
        self.setAccessibleDescription(
            "Read-only direct manipulation and synchronized Civilization V icon previews."
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        self.reset_button = QPushButton("Reset")
        self.center_button = QPushButton("Center")
        self.checkerboard_toggle = QCheckBox("Checkerboard alpha")
        self.safe_zone_toggle = QCheckBox("172/256 safe zone")
        self.firaxis_frame_toggle = QCheckBox("Preview-only Firaxis frame")
        self.checkerboard_toggle.setChecked(True)
        self.safe_zone_toggle.setChecked(True)
        self.firaxis_frame_toggle.setChecked(True)
        self.firaxis_frame_toggle.setToolTip(
            "Presentation overlay only; it is never written into source or generated pixels."
        )
        self.reset_button.setAccessibleDescription(
            "Restore one hundred percent zoom and center the source."
        )
        self.center_button.setAccessibleDescription(
            "Center the source while preserving the current zoom."
        )
        self.checkerboard_toggle.setAccessibleDescription(
            "Show or hide the transparency checkerboard in previews."
        )
        self.safe_zone_toggle.setAccessibleDescription(
            "Show or hide the 172 by 256 circular art safe-zone guide."
        )
        self.firaxis_frame_toggle.setAccessibleDescription(
            "Show or hide the presentation-only Firaxis-style frame."
        )
        controls.addWidget(self.reset_button)
        controls.addWidget(self.center_button)
        controls.addSpacing(8)
        controls.addWidget(self.checkerboard_toggle)
        controls.addWidget(self.safe_zone_toggle)
        controls.addWidget(self.firaxis_frame_toggle)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.canvas = SourceArtCanvas(self)
        layout.addWidget(self.canvas, 1)
        self.diagnostics_label = QLabel("No source PNG selected.")
        self.diagnostics_label.setObjectName("artDiagnostics")
        self.diagnostics_label.setAccessibleName("Source art diagnostics")
        self.diagnostics_label.setWordWrap(True)
        self.diagnostics_label.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self.diagnostics_label)
        self.previews = SynchronizedArtPreviews(self)
        layout.addWidget(self.previews)

        self.reset_button.clicked.connect(self.canvas.reset_transform)
        self.center_button.clicked.connect(self.canvas.center_source)
        self.checkerboard_toggle.toggled.connect(self._sync_overlays)
        self.safe_zone_toggle.toggled.connect(self._sync_overlays)
        self.firaxis_frame_toggle.toggled.connect(self._sync_overlays)
        self.canvas.transformChanged.connect(self._canvas_transform_changed)
        self.canvas.sourceChanged.connect(self.sourceChanged)
        self.canvas.diagnosticsChanged.connect(self._diagnostics_changed)
        self._sync_overlays(emit=False)

    @property
    def source_path(self) -> str:
        return self.canvas.source_path

    def set_source(self, path: str, *, emit: bool = False) -> None:
        self.canvas.set_source(path, emit=emit)
        self.previews.set_image(self.canvas.source_image())

    def get_transform(self) -> dict[str, int]:
        return self.canvas.get_transform()

    def set_transform(
        self,
        value: ArtTransform | Mapping[str, object] | int = 100,
        offset_x: int | None = None,
        offset_y: int | None = None,
        *,
        emit: bool = False,
    ) -> None:
        self.canvas.set_transform(value, offset_x, offset_y, emit=emit)
        # ArtPage owns the 60-160 project range. Synchronize from the accepted
        # canvas value so an out-of-range request cannot desynchronize previews.
        self.previews.set_transform(ArtTransform.coerce(self.canvas.get_transform()))

    def set_zoom_range(self, minimum: int, maximum: int, *, emit: bool = True) -> None:
        self.canvas.set_zoom_range(minimum, maximum, emit=emit)
        self.previews.set_transform(ArtTransform.coerce(self.canvas.get_transform()))

    def zoom_range(self) -> tuple[int, int]:
        return self.canvas.zoom_range()

    def set_offset_range(self, minimum: int, maximum: int, *, emit: bool = True) -> None:
        self.canvas.set_offset_range(minimum, maximum, emit=emit)
        self.previews.set_transform(ArtTransform.coerce(self.canvas.get_transform()))

    def offset_range(self) -> tuple[int, int]:
        return self.canvas.offset_range()

    def reset_transform(self, *, emit: bool = True) -> None:
        self.canvas.reset_transform(emit=emit)
        self.previews.set_transform(ArtTransform.coerce(self.canvas.get_transform()))

    def center_source(self, *, emit: bool = True) -> None:
        self.canvas.center_source(emit=emit)
        self.previews.set_transform(ArtTransform.coerce(self.canvas.get_transform()))

    def diagnostics(self) -> dict[str, object]:
        return self.canvas.diagnostics()

    def set_checkerboard_visible(self, visible: bool, *, emit: bool = False) -> None:
        with QSignalBlocker(self.checkerboard_toggle):
            self.checkerboard_toggle.setChecked(bool(visible))
        self._sync_overlays(emit=emit)

    def set_safe_zone_visible(self, visible: bool, *, emit: bool = False) -> None:
        with QSignalBlocker(self.safe_zone_toggle):
            self.safe_zone_toggle.setChecked(bool(visible))
        self._sync_overlays(emit=emit)

    def set_firaxis_frame_visible(self, visible: bool, *, emit: bool = False) -> None:
        with QSignalBlocker(self.firaxis_frame_toggle):
            self.firaxis_frame_toggle.setChecked(bool(visible))
        self._sync_overlays(emit=emit)

    def _canvas_transform_changed(self, transform: dict[str, int]) -> None:
        self.previews.set_transform(ArtTransform.coerce(transform))
        self.transformChanged.emit(dict(transform))

    def _diagnostics_changed(self, diagnostics: dict[str, object]) -> None:
        messages = diagnostics.get("messages", [])
        text = (
            " ".join(str(item) for item in messages)
            if isinstance(messages, list)
            else str(messages)
        )
        if diagnostics.get("status") == "ready":
            text = (
                f"{diagnostics['width']}×{diagnostics['height']} {diagnostics['format']} · "
                f"alpha: {'transparent pixels present' if diagnostics['has_transparency'] else 'opaque'} · "
                f"transform clipping: {'/'.join(diagnostics['clipping_edges']) if diagnostics['transform_clipped'] else 'none'}"
                + (f" · {text}" if text else "")
            )
            color = WARNING if diagnostics.get("transform_clipped") else SUCCESS
        else:
            color = WARNING if diagnostics.get("status") not in {"empty"} else MUTED
        self.diagnostics_label.setText(text)
        self.diagnostics_label.setStyleSheet(f"color: {color};")
        self.diagnosticsChanged.emit(dict(diagnostics))

    def _sync_overlays(
        self, _checked: bool | None = None, *, emit: bool = True
    ) -> None:
        checkerboard = self.checkerboard_toggle.isChecked()
        safe_zone = self.safe_zone_toggle.isChecked()
        frame = self.firaxis_frame_toggle.isChecked()
        self.canvas.set_checkerboard_visible(checkerboard)
        self.canvas.set_safe_zone_visible(safe_zone)
        self.canvas.set_firaxis_frame_visible(frame)
        self.previews.set_overlays(
            checkerboard=checkerboard,
            safe_zone=safe_zone,
            firaxis_frame=frame,
        )
        if emit:
            self.overlaysChanged.emit(checkerboard, safe_zone, frame)


__all__ = [
    "ART_PREVIEW_SIZES",
    "SAFE_ZONE_DIAMETER_RATIO",
    "ArtSizePreview",
    "ArtStudioWidget",
    "ArtTransform",
    "SourceArtCanvas",
    "SynchronizedArtPreviews",
]
