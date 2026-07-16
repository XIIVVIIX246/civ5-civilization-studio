"""Safe persistence for the project-owned history service.

History has one fixed location below ``.civ5studio``.  The API intentionally
accepts a validated :class:`ProjectWorkspace` rather than an arbitrary path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

from civ5studio.application.workspace import ProjectWorkspace
from civ5studio.domain.history import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_SNAPSHOTS,
    InvalidHistoryState,
    ProjectHistory,
)


HISTORY_DIRECTORY = "history"
HISTORY_FILENAME = "project-history.json"
MAX_HISTORY_FILE_BYTES = 32 * 1024 * 1024


class ProjectHistoryPersistenceError(RuntimeError):
    """Raised when the project history cannot be safely read or published."""


class UnsafeHistoryPath(ProjectHistoryPersistenceError):
    """Raised when the fixed history location is not demonstrably project-owned."""


@dataclass(frozen=True, slots=True)
class HistorySaveResult:
    path: Path
    sha256: str
    size: int


class ProjectHistoryStore:
    """Read and atomically replace one workspace's bounded history document."""

    def __init__(
        self,
        workspace: ProjectWorkspace,
        *,
        default_max_entries: int = DEFAULT_MAX_ENTRIES,
        default_max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    ) -> None:
        if not isinstance(workspace, ProjectWorkspace):
            raise TypeError("ProjectHistoryStore requires a ProjectWorkspace.")
        # Let the domain service enforce the same public limits used on load.
        ProjectHistory(
            max_entries=default_max_entries,
            max_snapshots=default_max_snapshots,
        )
        self.workspace = workspace
        self.default_max_entries = default_max_entries
        self.default_max_snapshots = default_max_snapshots

    @property
    def path(self) -> Path:
        return self.workspace.control_root / HISTORY_DIRECTORY / HISTORY_FILENAME

    def exists(self) -> bool:
        try:
            self._preflight_workspace()
            with self.workspace.lock():
                self.workspace.load()
                path = self._validated_path(create_parent=False)
                return path.is_file()
        except ProjectHistoryPersistenceError:
            raise
        except Exception as exc:
            raise ProjectHistoryPersistenceError(
                f"Could not inspect project history {self.path}: {exc}"
            ) from exc

    def load(self) -> ProjectHistory:
        """Load persisted history, or return a new empty bounded service."""

        try:
            self._preflight_workspace()
            with self.workspace.lock():
                self.workspace.load()
                path = self._validated_path(create_parent=False)
                if not path.exists():
                    return ProjectHistory(
                        max_entries=self.default_max_entries,
                        max_snapshots=self.default_max_snapshots,
                    )
                size = path.stat().st_size
                if size > MAX_HISTORY_FILE_BYTES:
                    raise ProjectHistoryPersistenceError(
                        f"Project history exceeds {MAX_HISTORY_FILE_BYTES} bytes."
                    )
                raw = path.read_bytes()
                payload: Any = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise InvalidHistoryState("History document root must be an object.")
                return ProjectHistory.from_payload(
                    payload,
                    expected_project_id=self.workspace.project_id,
                    expected_workspace_id=self.workspace.workspace_id,
                )
        except ProjectHistoryPersistenceError:
            raise
        except Exception as exc:
            raise ProjectHistoryPersistenceError(
                f"Could not load project history {self.path}: {exc}"
            ) from exc

    def save(self, history: ProjectHistory) -> HistorySaveResult:
        """Publish history with a same-directory atomic replacement."""

        if not isinstance(history, ProjectHistory):
            raise TypeError("history must be a ProjectHistory instance.")
        payload = history.to_payload(
            project_id=self.workspace.project_id,
            workspace_id=self.workspace.workspace_id,
        )
        data = (
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        if len(data) > MAX_HISTORY_FILE_BYTES:
            raise ProjectHistoryPersistenceError(
                f"Project history exceeds {MAX_HISTORY_FILE_BYTES} bytes."
            )

        try:
            self._preflight_workspace()
            with self.workspace.lock():
                self.workspace.load()
                path = self._validated_path(create_parent=True)
                _atomic_replace(path, data)
        except ProjectHistoryPersistenceError:
            raise
        except Exception as exc:
            raise ProjectHistoryPersistenceError(
                f"Could not save project history {self.path}: {exc}"
            ) from exc
        return HistorySaveResult(
            path=path,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
        )

    def _preflight_workspace(self) -> None:
        """Reject forged/unmarked roots before the workspace lock can write."""

        control = self.workspace.control_root
        marker = self.workspace.marker_path
        if control.is_symlink() or not control.is_dir():
            raise UnsafeHistoryPath(
                "Project history requires an existing marked workspace."
            )
        if marker.is_symlink() or not marker.is_file():
            raise UnsafeHistoryPath(
                "Project history requires an existing marked workspace."
            )

    def _validated_path(self, *, create_parent: bool) -> Path:
        control = self.workspace.control_root
        if control.is_symlink() or not control.is_dir():
            raise UnsafeHistoryPath(
                "Workspace control directory is missing, unsafe, or not a directory."
            )
        root = control.resolve(strict=True)
        history_root = control / HISTORY_DIRECTORY
        if history_root.is_symlink() or (
            history_root.exists() and not history_root.is_dir()
        ):
            raise UnsafeHistoryPath(
                "Project history directory is unsafe or is not a directory."
            )
        if create_parent and not history_root.exists():
            try:
                history_root.mkdir(exist_ok=False)
            except OSError as exc:
                raise ProjectHistoryPersistenceError(
                    f"Could not create project history directory: {exc}"
                ) from exc
        resolved_parent = history_root.resolve(strict=False)
        if not resolved_parent.is_relative_to(root):
            raise UnsafeHistoryPath("Project history directory escapes the workspace.")
        path = resolved_parent / HISTORY_FILENAME
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise UnsafeHistoryPath("Project history document is not a safe regular file.")
        if not path.resolve(strict=False).is_relative_to(root):
            raise UnsafeHistoryPath("Project history document escapes the workspace.")
        return path


def _atomic_replace(path: Path, data: bytes) -> None:
    """Replace ``path`` atomically; on failure remove only our private temp."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, ProjectHistoryPersistenceError):
            raise
        raise ProjectHistoryPersistenceError(
            f"Could not atomically save project history {path}: {exc}"
        ) from exc


__all__ = [
    "HISTORY_DIRECTORY",
    "HISTORY_FILENAME",
    "HistorySaveResult",
    "MAX_HISTORY_FILE_BYTES",
    "ProjectHistoryPersistenceError",
    "ProjectHistoryStore",
    "UnsafeHistoryPath",
]
