"""Application entry point.

The full PySide6 window is imported lazily so domain and generator tests can run
without initializing a GUI platform plugin.
"""

from __future__ import annotations

from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    if any(value in {"--version", "-V"} for value in arguments[1:]):
        from . import __version__

        # PyInstaller's Windows GUI mode intentionally sets stdout to None.
        # The frozen smoke probe still needs a clean zero exit in that mode.
        if sys.stdout is not None:
            print(__version__)
        return 0

    smoke_test = "--smoke-test" in arguments[1:]
    if smoke_test:
        arguments = [
            arguments[0],
            *[value for value in arguments[1:] if value != "--smoke-test"],
        ]

    from PySide6.QtWidgets import QApplication

    from .application.controller import ApplicationController
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app = QApplication(arguments)
    app.setApplicationName("Civ V Civilization Studio")
    app.setOrganizationName("Civ V Modding Tools")
    apply_theme(app)
    window = MainWindow()
    controller = ApplicationController(window)
    window._application_controller = controller  # type: ignore[attr-defined]
    if smoke_test:
        # Construct the complete application/controller graph so frozen
        # releases prove that Qt plugins, package data, and every page import.
        # Do not show a window or enter the event loop during the release probe.
        window.close()
        return 0
    window.show()
    if len(arguments) > 1:
        candidate = Path(arguments[1])
        if candidate.is_file():
            controller.open_path(candidate)
    return app.exec()
