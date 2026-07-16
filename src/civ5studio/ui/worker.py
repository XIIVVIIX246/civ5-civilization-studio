"""Generic background-task adapter used by the application controller."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    started = Signal()
    progress = Signal(int, str)
    log = Signal(str)
    result = Signal(object)
    failed = Signal(str, str)
    finished = Signal()


class BackgroundTask(QRunnable):
    """Runs a service callable without coupling it to Qt widgets.

    The callable receives keyword-only ``progress`` and ``log`` callbacks. It
    may return any serializable or domain result object.
    """

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self.function(
                *self.args,
                progress=lambda percent, message="": self.signals.progress.emit(int(percent), str(message)),
                log=lambda message: self.signals.log.emit(str(message)),
                **self.kwargs,
            )
            self.signals.result.emit(result)
        except Exception as exc:  # pragma: no cover - exercised through controller integration tests
            self.signals.failed.emit(str(exc), traceback.format_exc())
        finally:
            self.signals.finished.emit()

