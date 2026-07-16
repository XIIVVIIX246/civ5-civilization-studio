"""Application palette and restrained Windows-native styling."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


ACCENT = "#c8a45d"
ACCENT_HOVER = "#dab972"
PANEL = "#202632"
PANEL_ALT = "#272f3d"
BACKGROUND = "#171c25"
TEXT = "#edf0f5"
MUTED = "#aeb6c4"
ERROR = "#e06c75"
WARNING = "#e5b567"
SUCCESS = "#7ec699"


STYLE_SHEET = f"""
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 10pt;
}}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QFrame#card, QGroupBox {{
    background: {PANEL};
    border: 1px solid #364052;
    border-radius: 7px;
}}
QFrame#pipelineStage, QFrame#previewSurface {{
    background: #171d27;
    border: 1px solid #364052;
    border-radius: 6px;
}}
QDockWidget {{
    color: {TEXT};
    font-weight: 650;
}}
QDockWidget::title {{
    background: #1d2430;
    border: 1px solid #30394a;
    padding: 6px 9px;
}}
QSplitter::handle {{ background: #30394a; width: 2px; height: 2px; }}
QGroupBox {{
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
}}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QTableWidget, QTreeWidget, QListWidget {{
    background: #141922;
    border: 1px solid #3a4558;
    border-radius: 5px;
    padding: 5px;
    selection-background-color: #4b607d;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QTableWidget:focus, QTreeWidget:focus,
QListWidget:focus {{
    border: 2px solid {ACCENT};
}}
QPushButton:focus, QToolButton:focus {{
    border: 2px solid {ACCENT};
}}
QCheckBox:focus, QRadioButton:focus, QSlider:focus {{
    border: 1px solid {ACCENT};
    border-radius: 3px;
}}
QWidget[validationFocus="true"] {{
    border: 2px solid {ERROR};
}}
QPushButton {{
    background: #344155;
    border: 1px solid #4c5d75;
    border-radius: 5px;
    padding: 7px 12px;
}}
QPushButton:hover {{ background: #40506a; }}
QPushButton:pressed {{ background: #2b3546; }}
QPushButton:disabled {{ color: #747d8c; background: #252b35; border-color: #303744; }}
QPushButton#primaryButton {{
    color: #16191f;
    background: {ACCENT};
    border-color: {ACCENT};
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background: {ACCENT_HOVER}; }}
QListWidget#stepList {{
    background: #131821;
    border: none;
    border-right: 1px solid #30394a;
    border-radius: 0;
    padding: 12px 8px;
}}
QListWidget#stepList::item {{
    padding: 12px 10px;
    margin: 2px 0;
    border-radius: 5px;
}}
QListWidget#stepList::item:selected {{
    color: #16191f;
    background: {ACCENT};
}}
QHeaderView::section {{
    background: #2a3342;
    border: none;
    border-right: 1px solid #3b4658;
    padding: 6px;
    font-weight: 600;
}}
QToolTip {{
    color: {TEXT};
    background: #10141b;
    border: 1px solid {ACCENT};
    padding: 5px;
}}
QProgressBar {{
    background: #141922;
    border: 1px solid #3a4558;
    border-radius: 4px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor("#141922"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor("#344155"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#16191f"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE_SHEET)
