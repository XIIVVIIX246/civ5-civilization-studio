"""Visible audit-to-runtime pipeline used by the Review & Build page."""

from __future__ import annotations

from datetime import datetime
from time import monotonic

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import ACCENT, ERROR, MUTED, SUCCESS, WARNING


STAGES = (
    ("audit", "1", "Audit Draft"),
    ("validate", "2", "Validate Release"),
    ("build", "3", "Build Package"),
    ("install", "4", "Install to MODS"),
    ("launch", "5", "Launch BNW"),
    ("analyze", "6", "Analyze Logs"),
)

# Once an edit invalidates an in-flight operation, its eventual callback must
# not make the old result look current again. A genuinely new operation first
# moves the stage through RUNNING (or REQUESTED for the Steam hand-off).
_TERMINAL_RESULTS = {
    "PASS",
    "READY",
    "COMPLETE",
    "WARNING",
    "BLOCKED",
    "FAIL",
    "ERROR",
}


class PipelineStage(QFrame):
    artifactRequested = Signal(str)

    def __init__(self, number: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pipelineStage")
        self._status = "NOT RUN"
        self._started_at: float | None = None
        self._artifact_path = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 10)
        heading = QLabel(f"{number}  {title}")
        heading.setStyleSheet("font-weight: 700;")
        self.status_label = QLabel("NOT RUN")
        self.status_label.setStyleSheet(f"color: {MUTED}; font-weight: 750;")
        self.detail = QLabel("Waiting for this project revision.")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.meta_label = QLabel("Not run this session")
        self.meta_label.setStyleSheet(f"color: {MUTED}; font-size: 8pt;")
        self.artifact_button = QPushButton("Open artifact")
        self.artifact_button.setObjectName("pipelineArtifactButton")
        self.artifact_button.setAccessibleName(f"Open {title} artifact")
        self.artifact_button.setToolTip(
            "Open the output recorded for this stage in its Windows default application."
        )
        self.artifact_button.setVisible(False)
        self.artifact_button.clicked.connect(
            lambda _checked=False: self.artifactRequested.emit(self._artifact_path)
        )
        footer.addWidget(self.meta_label)
        footer.addStretch(1)
        footer.addWidget(self.artifact_button)
        layout.addWidget(heading)
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail)
        layout.addLayout(footer)

    @property
    def status(self) -> str:
        return self._status

    @property
    def artifact_path(self) -> str:
        return self._artifact_path

    def set_status(
        self,
        status: str,
        detail: str = "",
        artifact_path: str | None = None,
    ) -> bool:
        status = str(status or "NOT RUN").upper()
        if self._status == "STALE" and status in _TERMINAL_RESULTS:
            return False
        now = datetime.now().astimezone().strftime("%H:%M:%S")
        if status in {"RUNNING", "REQUESTED"}:
            self._started_at = monotonic()
            self.meta_label.setText(
                f"{'Started' if status == 'RUNNING' else 'Requested'} {now}"
            )
            artifact_path = ""
        elif status == "NOT RUN":
            self._started_at = None
            self.meta_label.setText("Not run this session")
            artifact_path = ""
        else:
            elapsed = (
                max(0.0, monotonic() - self._started_at)
                if self._started_at is not None
                else None
            )
            timing = f" · {elapsed:.1f}s" if elapsed is not None else ""
            self.meta_label.setText(f"Updated {now}{timing}")
        self._status = status
        colors = {
            "PASS": SUCCESS,
            "READY": SUCCESS,
            "COMPLETE": SUCCESS,
            "RUNNING": ACCENT,
            "REQUESTED": ACCENT,
            "WARNING": WARNING,
            "STALE": WARNING,
            "FAIL": ERROR,
            "ERROR": ERROR,
            "NOT RUN": MUTED,
            "BLOCKED": ERROR,
        }
        self.status_label.setText(status)
        self.status_label.setStyleSheet(
            f"color: {colors.get(status, MUTED)}; font-weight: 750;"
        )
        if detail:
            self.detail.setText(detail)
        if artifact_path is not None:
            self._artifact_path = str(artifact_path).strip()
            self.artifact_button.setVisible(bool(self._artifact_path))
            self.artifact_button.setToolTip(
                self._artifact_path
                if self._artifact_path
                else "No persistent artifact was recorded for this stage."
            )
        return True


class BuildPipelineWidget(QWidget):
    """Six-stage status surface; it never starts operations by itself."""

    artifactRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.stages: dict[str, PipelineStage] = {}
        for index, (stage_id, number, title) in enumerate(STAGES):
            stage = PipelineStage(number, title)
            stage.artifactRequested.connect(self.artifactRequested.emit)
            self.stages[stage_id] = stage
            layout.addWidget(stage, index // 3, index % 3)

    def set_stage(
        self,
        stage_id: str,
        status: str,
        detail: str = "",
        artifact_path: str | None = None,
    ) -> bool:
        stage = self.stages.get(stage_id)
        return (
            stage.set_status(status, detail, artifact_path)
            if stage is not None
            else False
        )

    def status(self, stage_id: str) -> str:
        stage = self.stages.get(stage_id)
        return stage.status if stage is not None else "NOT RUN"

    def invalidate_after_edit(self) -> None:
        for stage_id in ("audit", "validate", "build", "install"):
            if self.status(stage_id) != "NOT RUN":
                self.set_stage(
                    stage_id,
                    "STALE",
                    "The project changed; rerun this stage for the current revision.",
                )
        if self.status("launch") not in {"NOT RUN", "STALE"}:
            self.set_stage(
                "launch",
                "STALE",
                "The recorded launch belongs to an older project revision.",
            )
        if self.status("analyze") not in {"NOT RUN", "STALE"}:
            self.set_stage(
                "analyze",
                "STALE",
                "The analyzed logs belong to an older project revision.",
            )

    def reset(self) -> None:
        for stage_id, _number, _title in STAGES:
            self.set_stage(
                stage_id,
                "NOT RUN",
                "Waiting for this project revision.",
                artifact_path="",
            )


__all__ = ["BuildPipelineWidget", "PipelineStage", "STAGES"]
