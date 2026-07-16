"""Project-owned workspaces with portable art and crash recovery.

The service in this module deliberately owns a narrow filesystem surface.  It
will only write below a marked workspace, never recursively deletes a path,
and publishes JSON and imported source files with same-directory atomic
replacements.  It is independent of Qt so recovery can run before the desktop
window is created.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Any, BinaryIO, Mapping
import uuid

from civ5studio.domain import CivProject, dumps_project, is_portable_relative_path, load_project


WORKSPACE_MARKER = "workspace.json"
WORKSPACE_MARKER_FORMAT = "civ5studio.workspace"
WORKSPACE_MARKER_VERSION = 2
RECOVERY_MARKER_FORMAT = "civ5studio.recovery"
RECOVERY_MARKER_VERSION = 1
DEFAULT_PROJECT_FILE = "project.civ5project.json"


class WorkspaceError(RuntimeError):
    """Base class for project workspace failures."""


class UnsafeWorkspaceError(WorkspaceError):
    """Raised when a path is not demonstrably owned by this project."""


class WorkspaceBusyError(WorkspaceError):
    """Raised when another save/import operation owns the workspace lock."""


class WorkspaceAssetError(WorkspaceError):
    """Raised when source art cannot be copied into the workspace."""


class RecoveryError(WorkspaceError):
    """Raised when recovery data is corrupt, unsafe, or incompatible."""


@dataclass(frozen=True, slots=True)
class ImportedSource:
    relative_path: str
    sha256: str
    size: int
    reused: bool


@dataclass(frozen=True, slots=True)
class ProjectSaveResult:
    project_path: Path
    backup_path: Path | None
    sha256: str


@dataclass(frozen=True, slots=True)
class RecoveryStatus:
    available: bool
    reason: str
    autosave_path: Path | None = None
    updated_utc: str = ""
    autosave_sha256: str = ""
    current_project_sha256: str = ""
    base_project_sha256: str = ""
    base_matches_current: bool | None = None
    orphaned_metadata: bool = False


_ACTIVE_LOCKS: set[str] = set()
_ACTIVE_LOCKS_GUARD = threading.Lock()


class _WorkspaceLock(AbstractContextManager["_WorkspaceLock"]):
    """Non-blocking process/thread lock whose OS lock is released on a crash."""

    def __init__(self, path: Path):
        self.path = path
        self._handle: BinaryIO | None = None
        self._key = os.path.normcase(str(path.resolve(strict=False)))

    def __enter__(self) -> "_WorkspaceLock":
        with _ACTIVE_LOCKS_GUARD:
            if self._key in _ACTIVE_LOCKS:
                raise WorkspaceBusyError(f"Workspace is already being changed: {self.path}")
            _ACTIVE_LOCKS.add(self._key)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - exercised by non-Windows CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                raise WorkspaceBusyError(
                    f"Workspace is open in another process: {self.path.parent.parent}"
                ) from exc
            self._handle = handle
            return self
        except Exception:
            with _ACTIVE_LOCKS_GUARD:
                _ACTIVE_LOCKS.discard(self._key)
            raise

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        handle = self._handle
        try:
            if handle is not None:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:  # pragma: no cover - exercised by non-Windows CI
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
        finally:
            self._handle = None
            with _ACTIVE_LOCKS_GUARD:
                _ACTIVE_LOCKS.discard(self._key)


class ProjectWorkspace:
    """A validated, self-contained Civilization Studio project directory."""

    def __init__(
        self,
        root: Path,
        *,
        project_id: str,
        workspace_id: str,
        project_file: str,
    ) -> None:
        self.root = root.resolve()
        unresolved_control = self.root / ".civ5studio"
        if unresolved_control.is_symlink():
            raise UnsafeWorkspaceError("Workspace control directory cannot be a symlink.")
        self.control_root = _owned_path(self.root, ".civ5studio")
        self.marker_path = self.control_root / WORKSPACE_MARKER
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.project_file = project_file
        self.project_path = _owned_path(self.root, project_file)
        self._lock_path = self.control_root / "workspace.lock"

    @classmethod
    def create(
        cls,
        root: str | Path,
        project: CivProject,
        *,
        project_file: str = DEFAULT_PROJECT_FILE,
        source_root: str | Path | None = None,
    ) -> "ProjectWorkspace":
        """Claim an empty directory and create a portable project in it.

        Every non-empty art source must either already be a safe file inside
        the new workspace, be absolute, or be resolvable below ``source_root``.
        External sources are copied; the caller's files are never modified.
        """

        destination = Path(root).expanduser().resolve()
        _validate_workspace_root(destination)
        project_file = _validate_project_file(project_file)
        _validate_uuid(project.project_id, "project_id")
        _preflight_project_sources(project, destination, source_root)
        if destination.exists():
            if not destination.is_dir():
                raise UnsafeWorkspaceError(f"Workspace root is not a directory: {destination}")
            if any(destination.iterdir()):
                raise UnsafeWorkspaceError(
                    f"Refusing to claim non-empty unmarked directory: {destination}"
                )
        else:
            destination.mkdir(parents=True, exist_ok=False)

        control = destination / ".civ5studio"
        try:
            control.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise UnsafeWorkspaceError(
                f"Refusing to claim existing workspace controls: {control}"
            ) from exc

        workspace_id = str(uuid.uuid4())
        workspace = cls(
            destination,
            project_id=project.project_id,
            workspace_id=workspace_id,
            project_file=project_file,
        )
        created = _utc_now()
        with workspace.lock():
            _atomic_json(
                workspace.marker_path,
                {
                    "marker_format": WORKSPACE_MARKER_FORMAT,
                    "marker_version": WORKSPACE_MARKER_VERSION,
                    "workspace_id": workspace_id,
                    "project_id": project.project_id,
                    "project_file": project_file,
                    "created_utc": created,
                },
            )
            portable = workspace._materialize_sources_unlocked(project, source_root)
            workspace._validate_portable_project(portable, require_assets=True)
            _atomic_bytes(workspace.project_path, dumps_project(portable).encode("utf-8"))
        return workspace

    @classmethod
    def open(cls, root: str | Path) -> "ProjectWorkspace":
        destination = Path(root).expanduser().resolve()
        control = destination / ".civ5studio"
        if control.is_symlink():
            raise UnsafeWorkspaceError("Workspace control directory cannot be a symlink.")
        marker_path = _owned_path(destination, f".civ5studio/{WORKSPACE_MARKER}")
        if marker_path.is_symlink():
            raise UnsafeWorkspaceError("Workspace marker cannot be a symlink.")
        marker = _read_json(marker_path, "workspace marker", UnsafeWorkspaceError)
        _validate_workspace_marker(marker, marker_path)
        workspace = cls(
            destination,
            project_id=str(marker["project_id"]),
            workspace_id=str(marker["workspace_id"]),
            project_file=str(marker["project_file"]),
        )
        workspace._assert_marker()
        project = workspace.load()
        if project.project_id != workspace.project_id:
            raise UnsafeWorkspaceError(
                "Workspace marker and project document have different project IDs."
            )
        return workspace

    @classmethod
    def open_project_file(cls, path: str | Path) -> "ProjectWorkspace":
        project_path = Path(path).expanduser().resolve()
        workspace = cls.open(project_path.parent)
        if project_path != workspace.project_path:
            raise UnsafeWorkspaceError(
                f"Project is not the workspace's registered document: {project_path}"
            )
        return workspace

    def lock(self) -> AbstractContextManager[object]:
        """Acquire the non-blocking workspace mutation lock."""

        return _WorkspaceLock(self._lock_path)

    def load(self) -> CivProject:
        self._assert_marker()
        if self.project_path.is_symlink():
            raise UnsafeWorkspaceError("Workspace project document cannot be a symlink.")
        project = load_project(self.project_path)
        if project.project_id != self.project_id:
            raise UnsafeWorkspaceError(
                "Workspace marker and project document have different project IDs."
            )
        self._validate_portable_project(project, require_assets=False)
        return project

    def import_source(self, source: str | Path) -> ImportedSource:
        """Copy one PNG into ``Assets/Source`` using a content-addressed name."""

        with self.lock():
            self._assert_marker()
            return self._import_source_unlocked(Path(source).expanduser())

    def materialize_sources(
        self, project: CivProject, source_root: str | Path | None = None
    ) -> CivProject:
        """Return a copy whose art paths all point to workspace-owned files."""

        with self.lock():
            self._assert_marker()
            return self._materialize_sources_unlocked(project, source_root)

    def save(
        self,
        project: CivProject,
        *,
        source_root: str | Path | None = None,
        import_sources: bool = False,
        require_assets: bool = False,
        clear_recovery: bool = True,
    ) -> ProjectSaveResult:
        """Atomically save, retaining the previous revision as an immutable backup.

        Set ``import_sources`` to copy external/relocated art before the save.
        Missing relative art is allowed for drafts unless ``require_assets`` is
        true, but absolute and escaping paths are always rejected.
        """

        with self.lock():
            self._assert_marker()
            value = (
                self._materialize_sources_unlocked(project, source_root)
                if import_sources
                else deepcopy(project)
            )
            return self._save_unlocked(
                value,
                require_assets=require_assets,
                clear_recovery=clear_recovery,
            )

    def list_backups(self) -> tuple[Path, ...]:
        backup_root = _owned_path(self.control_root, "backups/projects")
        if not backup_root.is_dir():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in backup_root.glob("*.civ5project.json")
                    if path.is_file() and not path.is_symlink()
                ),
                key=lambda path: path.name,
                reverse=True,
            )
        )

    def restore_backup(self, backup: str | Path) -> ProjectSaveResult:
        """Restore one project-owned backup while backing up the current revision."""

        with self.lock():
            self._assert_marker()
            backup_root = _owned_path(self.control_root, "backups/projects")
            source = _owned_path(backup_root, Path(backup).name)
            requested = Path(backup).expanduser().resolve()
            if requested != source or not source.is_file() or source.is_symlink():
                raise UnsafeWorkspaceError(f"Not a project-owned backup: {backup}")
            project = load_project(source)
            return self._save_unlocked(
                project, require_assets=False, clear_recovery=True
            )

    def autosave(self, project: CivProject) -> RecoveryStatus:
        """Publish a versioned recovery snapshot without changing the project file."""

        with self.lock():
            self._assert_marker()
            self._validate_portable_project(project, require_assets=False)
            current_hash = _sha256_file(self.project_path)
            recovery_root = _owned_path(self.control_root, "recovery")
            autosaves_root = _owned_path(self.control_root, "recovery/autosaves")
            autosaves_root.mkdir(parents=True, exist_ok=True)
            created = _utc_now()
            filename = (
                created.replace("-", "").replace(":", "").replace(".", "")
                .replace("+00:00", "Z")
                + f"_{uuid.uuid4().hex}.civ5project.json"
            )
            autosave_path = _owned_path(autosaves_root, filename)
            payload = dumps_project(project).encode("utf-8")
            autosave_hash = hashlib.sha256(payload).hexdigest()
            previous = self._read_recovery_metadata(optional=True)
            first_created = (
                str(previous.get("created_utc"))
                if previous and previous.get("state") == "active"
                else created
            )
            relative = autosave_path.relative_to(self.control_root).as_posix()
            # A short-lived writing marker makes every interruption legible:
            # before the snapshot exists the previous orphan remains usable;
            # after it exists orphan discovery can recover the new snapshot.
            _atomic_json(
                self._recovery_metadata_path,
                {
                    "marker_format": RECOVERY_MARKER_FORMAT,
                    "marker_version": RECOVERY_MARKER_VERSION,
                    "state": "writing",
                    "workspace_id": self.workspace_id,
                    "project_id": self.project_id,
                    "autosave_file": relative,
                    "created_utc": first_created,
                    "updated_utc": created,
                },
            )
            _atomic_bytes(autosave_path, payload)
            _atomic_json(
                self._recovery_metadata_path,
                {
                    "marker_format": RECOVERY_MARKER_FORMAT,
                    "marker_version": RECOVERY_MARKER_VERSION,
                    "state": "active",
                    "workspace_id": self.workspace_id,
                    "project_id": self.project_id,
                    "autosave_file": relative,
                    "autosave_sha256": autosave_hash,
                    "base_project_sha256": current_hash,
                    "created_utc": first_created,
                    "updated_utc": created,
                },
            )
            self._remove_previous_autosave(previous, autosave_path)
            self._prune_autosaves(keep=autosave_path)
            return self._recovery_status_unlocked()

    def recovery_status(self) -> RecoveryStatus:
        with self.lock():
            self._assert_marker()
            return self._recovery_status_unlocked()

    def load_recovery(self) -> CivProject:
        with self.lock():
            self._assert_marker()
            status = self._recovery_status_unlocked()
            if not status.available or status.autosave_path is None:
                raise RecoveryError("No distinct autosave is available for recovery.")
            return load_project(status.autosave_path)

    def recover(self) -> ProjectSaveResult:
        """Replace the primary document with its autosave, retaining a backup."""

        with self.lock():
            self._assert_marker()
            status = self._recovery_status_unlocked()
            if not status.available or status.autosave_path is None:
                raise RecoveryError("No distinct autosave is available for recovery.")
            project = load_project(status.autosave_path)
            return self._save_unlocked(
                project, require_assets=False, clear_recovery=True
            )

    def discard_recovery(self) -> None:
        """Suppress and remove only the active project-owned recovery snapshot."""

        with self.lock():
            self._assert_marker()
            self._discard_recovery_unlocked()

    @property
    def _recovery_metadata_path(self) -> Path:
        return _owned_path(self.control_root, "recovery/recovery.json")

    def _assert_marker(self) -> None:
        if self.marker_path.is_symlink():
            raise UnsafeWorkspaceError("Workspace marker cannot be a symlink.")
        marker = _read_json(self.marker_path, "workspace marker", UnsafeWorkspaceError)
        _validate_workspace_marker(marker, self.marker_path)
        if (
            marker.get("workspace_id") != self.workspace_id
            or marker.get("project_id") != self.project_id
            or marker.get("project_file") != self.project_file
        ):
            raise UnsafeWorkspaceError("Workspace ownership marker changed unexpectedly.")

    def _materialize_sources_unlocked(
        self, project: CivProject, source_root: str | Path | None
    ) -> CivProject:
        if project.project_id != self.project_id:
            raise UnsafeWorkspaceError("Cannot save a different project in this workspace.")
        result = deepcopy(project)
        base = Path(source_root).expanduser().resolve() if source_root is not None else None
        for asset in result.art.assets:
            raw = asset.source_png.strip()
            if not raw:
                continue
            if is_portable_relative_path(raw):
                workspace_source = _owned_path(self.root, raw)
                if workspace_source.is_file() and not workspace_source.is_symlink():
                    asset.source_png = Path(raw.replace("\\", "/")).as_posix()
                    continue
                if base is None:
                    raise WorkspaceAssetError(
                        f"Art source is missing from the workspace: {raw}"
                    )
                source = _owned_path(base, raw)
            else:
                source = Path(raw).expanduser().resolve()
            imported = self._import_source_unlocked(source)
            asset.source_png = imported.relative_path
        self._validate_portable_project(result, require_assets=True)
        return result

    def _import_source_unlocked(self, source: Path) -> ImportedSource:
        source = source.resolve()
        if not source.is_file():
            raise WorkspaceAssetError(f"Art source is not a file: {source}")
        _validate_png_source(source)
        digest = _sha256_file(source)
        size = source.stat().st_size
        safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", source.stem).strip("_.-")
        safe_stem = (safe_stem or "source")[:72]
        destination_root = _owned_path(self.root, "Assets/Source")
        destination_root.mkdir(parents=True, exist_ok=True)
        for length in (12, 20, 64):
            target = destination_root / f"{safe_stem}_{digest[:length]}.png"
            _owned_path(self.root, target.relative_to(self.root).as_posix())
            if target.exists():
                if target.is_symlink():
                    raise WorkspaceAssetError(f"Refusing workspace symlink: {target}")
                if target.is_file() and _sha256_file(target) == digest:
                    return ImportedSource(
                        target.relative_to(self.root).as_posix(), digest, size, True
                    )
                continue
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                with source.open("rb") as incoming, temporary.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                if _sha256_file(temporary) != digest:
                    raise WorkspaceAssetError(
                        f"Copied art failed SHA-256 verification: {source}"
                    )
                try:
                    os.link(temporary, target)
                    temporary.unlink()
                except FileExistsError:
                    temporary.unlink(missing_ok=True)
                    continue
                except OSError:
                    # On Windows os.rename never replaces an existing target.
                    # On other systems this branch is only used when no target
                    # exists under our held workspace lock.
                    if target.exists():
                        temporary.unlink(missing_ok=True)
                        continue
                    os.rename(temporary, target)
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
            return ImportedSource(target.relative_to(self.root).as_posix(), digest, size, False)
        raise WorkspaceAssetError(
            f"Could not allocate a collision-free content path for {source}"
        )

    def _validate_portable_project(
        self, project: CivProject, *, require_assets: bool
    ) -> None:
        if project.project_id != self.project_id:
            raise UnsafeWorkspaceError("Cannot save a different project in this workspace.")
        for asset in project.art.assets:
            value = asset.source_png.strip()
            if not value:
                continue
            if not is_portable_relative_path(value):
                raise UnsafeWorkspaceError(
                    f"Project art path is not portable: {asset.source_png!r}"
                )
            target = _owned_path(self.root, value)
            if target.is_symlink():
                raise UnsafeWorkspaceError(f"Project art cannot be a symlink: {value}")
            if require_assets and not target.is_file():
                raise WorkspaceAssetError(f"Project art is missing: {value}")

    def _save_unlocked(
        self,
        project: CivProject,
        *,
        require_assets: bool,
        clear_recovery: bool,
    ) -> ProjectSaveResult:
        self._validate_portable_project(project, require_assets=require_assets)
        payload = dumps_project(project).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        backup = None
        if self.project_path.is_file():
            if self.project_path.is_symlink():
                raise UnsafeWorkspaceError("Workspace project document cannot be a symlink.")
            previous = self.project_path.read_bytes()
            previous_hash = hashlib.sha256(previous).hexdigest()
            if previous != payload:
                backup_root = _owned_path(self.control_root, "backups/projects")
                backup_root.mkdir(parents=True, exist_ok=True)
                stamp = _utc_now().replace("-", "").replace(":", "").replace(".", "")
                stamp = stamp.replace("+00:00", "Z")
                backup = backup_root / (
                    f"{stamp}_{previous_hash[:12]}_{uuid.uuid4().hex[:8]}"
                    ".civ5project.json"
                )
                _atomic_bytes(backup, previous)
        _atomic_bytes(self.project_path, payload)
        if clear_recovery:
            self._discard_recovery_unlocked()
        return ProjectSaveResult(self.project_path, backup, digest)

    def _read_recovery_metadata(self, *, optional: bool) -> dict[str, Any] | None:
        path = self._recovery_metadata_path
        if optional and not path.is_file():
            return None
        metadata = _read_json(path, "recovery metadata", RecoveryError)
        if metadata.get("marker_format") != RECOVERY_MARKER_FORMAT:
            raise RecoveryError(f"Unknown recovery metadata format: {path}")
        if metadata.get("marker_version") != RECOVERY_MARKER_VERSION:
            raise RecoveryError(f"Unsupported recovery metadata version: {path}")
        if (
            metadata.get("workspace_id") != self.workspace_id
            or metadata.get("project_id") != self.project_id
        ):
            raise RecoveryError("Recovery metadata belongs to another workspace or project.")
        return metadata

    def _recovery_status_unlocked(self) -> RecoveryStatus:
        current_hash = _sha256_file(self.project_path)
        metadata = self._read_recovery_metadata(optional=True)
        if metadata is not None and metadata.get("state") == "discarded":
            return RecoveryStatus(
                False,
                "discarded",
                updated_utc=str(metadata.get("updated_utc", "")),
                current_project_sha256=current_hash,
            )
        if metadata is None or metadata.get("state") == "writing":
            orphan = self._newest_valid_orphan()
            if orphan is None:
                return RecoveryStatus(
                    False,
                    "none" if metadata is None else "interrupted_before_snapshot",
                    updated_utc=str(metadata.get("updated_utc", "")) if metadata else "",
                    current_project_sha256=current_hash,
                    orphaned_metadata=metadata is not None,
                )
            autosave_path, autosave_hash, updated = orphan
            return RecoveryStatus(
                autosave_hash != current_hash,
                (
                    "orphaned_autosave"
                    if metadata is None and autosave_hash != current_hash
                    else "interrupted_autosave"
                    if autosave_hash != current_hash
                    else "matches_project"
                ),
                autosave_path,
                updated,
                autosave_hash,
                current_hash,
                orphaned_metadata=True,
            )
        if metadata.get("state") != "active":
            raise RecoveryError("Recovery metadata has an unknown state.")
        relative = metadata.get("autosave_file")
        if not isinstance(relative, str) or not is_portable_relative_path(relative):
            raise RecoveryError("Recovery metadata contains an unsafe autosave path.")
        autosave_path = self._recovery_autosave_path(relative)
        if not autosave_path.is_file() or autosave_path.is_symlink():
            raise RecoveryError("Recovery metadata points to a missing autosave.")
        autosave_hash = _sha256_file(autosave_path)
        if autosave_hash != metadata.get("autosave_sha256"):
            raise RecoveryError("Autosave SHA-256 does not match recovery metadata.")
        try:
            recovered = load_project(autosave_path)
        except Exception as exc:
            raise RecoveryError(f"Autosave is not a valid project document: {exc}") from exc
        if recovered.project_id != self.project_id:
            raise RecoveryError("Autosave belongs to a different project.")
        base_hash = str(metadata.get("base_project_sha256", ""))
        distinct = autosave_hash != current_hash
        return RecoveryStatus(
            distinct,
            "available" if distinct else "matches_project",
            autosave_path,
            str(metadata.get("updated_utc", "")),
            autosave_hash,
            current_hash,
            base_hash,
            base_hash == current_hash if base_hash else None,
        )

    def _newest_valid_orphan(self) -> tuple[Path, str, str] | None:
        autosaves_root = _owned_path(self.control_root, "recovery/autosaves")
        if not autosaves_root.is_dir():
            return None
        candidates = sorted(
            autosaves_root.glob("*.civ5project.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                project = load_project(path)
            except Exception:
                continue
            if project.project_id != self.project_id:
                continue
            modified = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            return path, _sha256_file(path), modified
        return None

    def _remove_previous_autosave(
        self, previous: Mapping[str, Any] | None, current: Path
    ) -> None:
        if not previous or previous.get("state") != "active":
            return
        relative = previous.get("autosave_file")
        if not isinstance(relative, str) or not is_portable_relative_path(relative):
            return
        try:
            prior = self._recovery_autosave_path(relative)
        except RecoveryError:
            return
        if prior != current and prior.is_file() and not prior.is_symlink():
            prior.unlink()

    def _discard_recovery_unlocked(self) -> None:
        recovery_root = _owned_path(self.control_root, "recovery")
        if not recovery_root.exists():
            return
        if not recovery_root.is_dir():
            raise RecoveryError(f"Recovery control path is not a directory: {recovery_root}")
        recovery_root.mkdir(parents=True, exist_ok=True)
        metadata: dict[str, Any] | None
        try:
            metadata = self._read_recovery_metadata(optional=True)
        except RecoveryError:
            metadata = None
        _atomic_json(
            self._recovery_metadata_path,
            {
                "marker_format": RECOVERY_MARKER_FORMAT,
                "marker_version": RECOVERY_MARKER_VERSION,
                "state": "discarded",
                "workspace_id": self.workspace_id,
                "project_id": self.project_id,
                "updated_utc": _utc_now(),
            },
        )
        if metadata and metadata.get("state") == "active":
            relative = metadata.get("autosave_file")
            if isinstance(relative, str) and is_portable_relative_path(relative):
                try:
                    path = self._recovery_autosave_path(relative)
                except RecoveryError:
                    path = None
                if path is not None and path.is_file() and not path.is_symlink():
                    path.unlink()
        self._prune_autosaves(keep=None)

    def _prune_autosaves(self, *, keep: Path | None) -> None:
        """Remove only validated snapshots for this project from the owned slot."""

        autosaves_root = _owned_path(self.control_root, "recovery/autosaves")
        if not autosaves_root.is_dir():
            return
        for path in autosaves_root.glob("*.civ5project.json"):
            if path == keep or not path.is_file() or path.is_symlink():
                continue
            try:
                candidate = load_project(path)
            except Exception:
                continue
            if candidate.project_id == self.project_id:
                path.unlink()

    def _recovery_autosave_path(self, relative: str) -> Path:
        normalized = relative.replace("\\", "/")
        parts = tuple(part for part in normalized.split("/") if part)
        if (
            len(parts) != 3
            or parts[:2] != ("recovery", "autosaves")
            or not parts[2].lower().endswith(".civ5project.json")
        ):
            raise RecoveryError("Recovery metadata does not point to an autosave slot.")
        return _owned_path(self.control_root, normalized)


def _validate_workspace_root(root: Path) -> None:
    if root.parent == root:
        raise UnsafeWorkspaceError("A filesystem root cannot be claimed as a workspace.")


def _validate_project_file(value: str) -> str:
    normalized = value.replace("\\", "/")
    if (
        not is_portable_relative_path(normalized)
        or len(Path(normalized).parts) != 1
        or not normalized.lower().endswith(".civ5project.json")
    ):
        raise UnsafeWorkspaceError(
            "The project filename must be one portable *.civ5project.json filename."
        )
    _validate_windows_relative_path(normalized)
    return normalized


def _validate_workspace_marker(marker: Mapping[str, Any], path: Path) -> None:
    if marker.get("marker_format") != WORKSPACE_MARKER_FORMAT:
        raise UnsafeWorkspaceError(f"Unknown workspace marker format: {path}")
    if marker.get("marker_version") != WORKSPACE_MARKER_VERSION:
        raise UnsafeWorkspaceError(f"Unsupported project workspace version: {path}")
    for key in ("workspace_id", "project_id"):
        _validate_uuid(marker.get(key), key, marker_path=path)
    _validate_project_file(str(marker.get("project_file", "")))


def _validate_uuid(value: object, name: str, *, marker_path: Path | None = None) -> None:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        location = f": {marker_path}" if marker_path is not None else ""
        raise UnsafeWorkspaceError(f"Workspace has an invalid {name}{location}") from exc


def _preflight_project_sources(
    project: CivProject,
    destination: Path,
    source_root: str | Path | None,
) -> None:
    base = Path(source_root).expanduser().resolve() if source_root is not None else None
    for asset in project.art.assets:
        raw = asset.source_png.strip()
        if not raw:
            continue
        if is_portable_relative_path(raw):
            local = _owned_path(destination, raw)
            if local.is_file() and not local.is_symlink():
                source = local
            elif base is not None:
                source = _owned_path(base, raw)
            else:
                raise WorkspaceAssetError(
                    f"Art source is missing from the workspace: {raw}"
                )
        else:
            source = Path(raw).expanduser().resolve()
        if not source.is_file():
            raise WorkspaceAssetError(f"Art source is not a file: {source}")
        _validate_png_source(source)


def _validate_png_source(source: Path) -> None:
    if source.suffix.lower() != ".png":
        raise WorkspaceAssetError(f"Art source must be a PNG file: {source}")
    with source.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise WorkspaceAssetError(f"Art source has an invalid PNG signature: {source}")


def _owned_path(root: Path, relative: str) -> Path:
    if not is_portable_relative_path(relative):
        raise UnsafeWorkspaceError(f"Unsafe workspace-relative path: {relative!r}")
    _validate_windows_relative_path(relative)
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(relative.replace("/", os.sep))).resolve(strict=False)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeWorkspaceError(
            f"Path escapes project-owned workspace {resolved_root}: {candidate}"
        ) from exc
    return candidate


def _validate_windows_relative_path(value: str) -> None:
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{index}" for index in range(1, 10))
    reserved.update(f"LPT{index}" for index in range(1, 10))
    for component in value.replace("\\", "/").split("/"):
        if (
            not component
            or len(component) > 240
            or component.endswith((" ", "."))
            or any(ord(character) < 32 for character in component)
            or any(character in '<>:"|?*' for character in component)
            or component.split(".", 1)[0].upper() in reserved
        ):
            raise UnsafeWorkspaceError(
                f"Path is not safe on Windows: {value!r}"
            )


def _read_json(
    path: Path, label: str, exception_type: type[WorkspaceError]
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise exception_type(f"Could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise exception_type(f"{label.capitalize()} must be a JSON object: {path}")
    return value


def _atomic_json(path: Path, value: object) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_bytes(path, payload)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
