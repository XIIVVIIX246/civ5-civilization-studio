from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from civ5studio.ui.art_studio import (
    ART_PREVIEW_SIZES,
    SAFE_ZONE_DIAMETER_RATIO,
    ArtStudioWidget,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png(path: Path, width: int = 64, height: int = 32) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    image.fill(QColor(30, 80, 140, 255))
    image.setPixelColor(0, 0, QColor(0, 0, 0, 0))
    image.setPixelColor(1, 0, QColor(30, 80, 140, 128))
    assert image.save(str(path), "PNG")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_diagnostics_are_exact_and_source_stays_read_only(tmp_path) -> None:
    _app()
    source = _png(tmp_path / "source.png")
    before_hash = _sha256(source)
    before_mtime = source.stat().st_mtime_ns
    widget = ArtStudioWidget()
    source_events: list[str] = []
    diagnostic_events: list[dict[str, object]] = []
    widget.sourceChanged.connect(source_events.append)
    widget.diagnosticsChanged.connect(
        lambda value: diagnostic_events.append(dict(value))
    )

    widget.set_source(str(source), emit=True)
    diagnostics = widget.diagnostics()

    assert source_events == [str(source)]
    assert diagnostic_events[-1]["status"] == "ready"
    assert diagnostics["status"] == "ready"
    assert (diagnostics["width"], diagnostics["height"]) == (64, 32)
    assert diagnostics["format"] == "PNG"
    assert diagnostics["is_square"] is False
    assert diagnostics["recommended_1024_square"] is False
    assert diagnostics["has_alpha_channel"] is True
    assert diagnostics["has_transparency"] is True
    assert diagnostics["transparent_pixels"] == 1
    assert diagnostics["translucent_pixels"] == 1
    assert diagnostics["opaque_pixels"] == 64 * 32 - 2
    assert diagnostics["safe_zone_diameter_ratio"] == SAFE_ZONE_DIAMETER_RATIO

    widget.set_transform({"zoom": 180, "offset_x": 12, "offset_y": -8})
    widget.resize(780, 620)
    assert not widget.grab().isNull()
    QApplication.processEvents()
    assert _sha256(source) == before_hash
    assert source.stat().st_mtime_ns == before_mtime
    widget.deleteLater()


def test_transform_signal_contract_and_all_previews_stay_synchronized() -> None:
    _app()
    widget = ArtStudioWidget()
    emissions: list[dict[str, int]] = []
    widget.transformChanged.connect(lambda value: emissions.append(dict(value)))

    widget.set_transform({"zoom": 145, "offset_x": 17, "offset_y": -23})
    assert widget.get_transform() == {
        "zoom": 145,
        "offset_x": 17,
        "offset_y": -23,
    }
    assert emissions == []
    assert (
        tuple(preview.export_size for preview in widget.previews.previews)
        == ART_PREVIEW_SIZES
    )
    assert all(
        preview.get_transform() == widget.get_transform()
        for preview in widget.previews.previews
    )

    widget.set_transform(155, 20, -25, emit=True)
    assert emissions == [{"zoom": 155, "offset_x": 20, "offset_y": -25}]
    assert all(
        preview.get_transform() == emissions[-1] for preview in widget.previews.previews
    )

    widget.set_safe_zone_visible(False)
    widget.set_firaxis_frame_visible(False)
    assert all(not preview.safe_zone_visible for preview in widget.previews.previews)
    assert all(
        not preview.firaxis_frame_visible for preview in widget.previews.previews
    )
    assert widget.get_transform() == emissions[-1]
    widget.deleteLater()


def test_wheel_drag_keyboard_center_and_reset_are_direct_manipulation() -> None:
    app = _app()
    widget = ArtStudioWidget()
    widget.resize(760, 680)
    widget.show()
    app.processEvents()
    canvas = widget.canvas

    center = canvas.rect().center()
    global_center = canvas.mapToGlobal(center)
    wheel = QWheelEvent(
        QPointF(center),
        QPointF(global_center),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(canvas, wheel)
    assert widget.get_transform()["zoom"] == 110

    canvas.setFocus()
    QTest.keyClick(canvas, Qt.Key.Key_Right)
    QTest.keyClick(canvas, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    after_keys = widget.get_transform()
    assert after_keys["offset_x"] == 1
    assert after_keys["offset_y"] == 10

    start = QPointF(center)
    end = QPointF(center + QPoint(45, -30))
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        start,
        QPointF(canvas.mapToGlobal(center)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        end,
        QPointF(canvas.mapToGlobal(center + QPoint(45, -30))),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        end,
        QPointF(canvas.mapToGlobal(center + QPoint(45, -30))),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(canvas, press)
    QApplication.sendEvent(canvas, move)
    QApplication.sendEvent(canvas, release)
    after_drag = widget.get_transform()
    assert after_drag["offset_x"] > after_keys["offset_x"]
    assert after_drag["offset_y"] < after_keys["offset_y"]

    zoom = after_drag["zoom"]
    QTest.mouseClick(widget.center_button, Qt.MouseButton.LeftButton)
    assert widget.get_transform() == {"zoom": zoom, "offset_x": 0, "offset_y": 0}
    QTest.mouseClick(widget.reset_button, Qt.MouseButton.LeftButton)
    assert widget.get_transform() == {"zoom": 100, "offset_x": 0, "offset_y": 0}
    widget.close()
    widget.deleteLater()


def test_missing_non_png_and_transform_clipping_diagnostics(tmp_path) -> None:
    _app()
    widget = ArtStudioWidget()

    widget.set_source(str(tmp_path / "missing.png"))
    assert widget.diagnostics()["status"] == "missing"
    text = tmp_path / "not-art.txt"
    text.write_text("not an image", encoding="utf-8")
    widget.set_source(str(text))
    assert widget.diagnostics()["status"] == "not_png"

    source = _png(tmp_path / "art.png", 64, 64)
    widget.set_source(str(source))
    assert widget.diagnostics()["transform_clipped"] is False
    widget.set_transform({"zoom": 200, "offset_x": 0, "offset_y": 0})
    diagnostics = widget.diagnostics()
    assert diagnostics["transform_clipped"] is True
    assert diagnostics["clipping_edges"] == ["left", "right", "top", "bottom"]
    assert "transform clipping" in widget.diagnostics_label.text().lower()
    widget.deleteLater()


def test_overlay_toggles_are_presentation_state_not_transform_state(tmp_path) -> None:
    _app()
    source = _png(tmp_path / "overlay.png", 48, 48)
    widget = ArtStudioWidget()
    widget.set_source(str(source))
    transform_before = widget.get_transform()
    diagnostics_before = widget.diagnostics()
    overlay_emissions: list[tuple[bool, bool, bool]] = []
    widget.overlaysChanged.connect(lambda a, b, c: overlay_emissions.append((a, b, c)))

    widget.firaxis_frame_toggle.setChecked(False)
    widget.safe_zone_toggle.setChecked(False)
    widget.checkerboard_toggle.setChecked(False)

    assert overlay_emissions[-1] == (False, False, False)
    assert widget.get_transform() == transform_before
    assert widget.diagnostics() == diagnostics_before
    assert not hasattr(widget, "export")
    assert not hasattr(widget, "save")
    widget.deleteLater()
