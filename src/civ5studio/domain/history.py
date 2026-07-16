"""Bounded, UI-independent project history and named snapshots.

The desktop editor works with dictionaries before they are converted into the
canonical :class:`CivProject` model.  This module deliberately treats those
dictionaries as opaque JSON documents: every stored revision is detached from
the caller, content-addressed, bounded, and safe to serialize.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping, Sequence
import uuid


HISTORY_FORMAT = "civ5studio.project-history"
HISTORY_FORMAT_VERSION = 1
DEFAULT_MAX_ENTRIES = 100
DEFAULT_MAX_SNAPSHOTS = 100
MAX_ALLOWED_ENTRIES = 500
MAX_ALLOWED_SNAPSHOTS = 500
MAX_LABEL_LENGTH = 160

ProjectState = dict[str, Any]
SectionPath = str | Sequence[str | int]


class ProjectHistoryError(ValueError):
    """Base class for invalid history operations or documents."""


class InvalidHistoryState(ProjectHistoryError):
    """Raised when a state or persisted history document is invalid."""


class HistoryBoundaryError(ProjectHistoryError):
    """Raised when undo or redo has reached the end of the timeline."""


class UnknownSnapshotError(ProjectHistoryError):
    """Raised when a named snapshot ID is not present."""


class UnknownSectionError(ProjectHistoryError):
    """Raised when a requested snapshot section cannot be restored."""


class SnapshotReason(str, Enum):
    """Why a durable named snapshot was captured."""

    MANUAL = "manual"
    BEFORE_IMPORT = "before_import"
    BEFORE_BUILD = "before_build"


@dataclass(frozen=True, slots=True)
class HistoryEntryInfo:
    entry_id: str
    label: str
    created_utc: str
    digest: str


@dataclass(frozen=True, slots=True)
class SnapshotInfo:
    snapshot_id: str
    label: str
    created_utc: str
    reason: SnapshotReason
    digest: str


@dataclass(frozen=True, slots=True)
class HistoryRecordResult:
    entry: HistoryEntryInfo
    added: bool
    redo_discarded: int = 0


@dataclass(frozen=True, slots=True)
class CompareSummary:
    identical: bool
    total_changes: int
    added_sections: tuple[str, ...]
    removed_sections: tuple[str, ...]
    modified_sections: tuple[str, ...]
    changed_paths: tuple[str, ...]
    truncated: bool


@dataclass(slots=True)
class _HistoryRecord:
    info: HistoryEntryInfo
    state: ProjectState


@dataclass(slots=True)
class _SnapshotRecord:
    info: SnapshotInfo
    state: ProjectState


class ProjectHistory:
    """A bounded undo timeline plus independently named project snapshots.

    ``record`` is intended to be called with the complete dictionary collected
    from the editor.  Consecutive identical documents are coalesced.  Returned
    states are always detached copies, so widgets/controllers cannot mutate a
    revision accidentally.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    ) -> None:
        self.max_entries = _bounded_limit(
            max_entries, "max_entries", MAX_ALLOWED_ENTRIES
        )
        self.max_snapshots = _bounded_limit(
            max_snapshots, "max_snapshots", MAX_ALLOWED_SNAPSHOTS
        )
        self._entries: list[_HistoryRecord] = []
        self._snapshots: list[_SnapshotRecord] = []
        self._cursor = -1

    @property
    def empty(self) -> bool:
        return not self._entries

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def can_undo(self) -> bool:
        return self._cursor > 0

    @property
    def can_redo(self) -> bool:
        return 0 <= self._cursor < len(self._entries) - 1

    @property
    def entries(self) -> tuple[HistoryEntryInfo, ...]:
        return tuple(record.info for record in self._entries)

    @property
    def snapshots(self) -> tuple[SnapshotInfo, ...]:
        return tuple(record.info for record in self._snapshots)

    @property
    def current_entry(self) -> HistoryEntryInfo:
        if self.empty:
            raise HistoryBoundaryError("Project history is empty.")
        return self._entries[self._cursor].info

    @property
    def current_state(self) -> ProjectState:
        if self.empty:
            raise HistoryBoundaryError("Project history is empty.")
        return _clone_state(self._entries[self._cursor].state)

    def reset(
        self,
        state: Mapping[str, Any],
        *,
        label: str = "Initial state",
        clear_snapshots: bool = True,
    ) -> HistoryEntryInfo:
        """Start a new timeline, optionally retaining named snapshots."""

        normalized = _normalize_state(state)
        self._entries.clear()
        self._cursor = -1
        if clear_snapshots:
            self._snapshots.clear()
        return self._append_entry(normalized, label).entry

    def record(
        self, state: Mapping[str, Any], *, label: str = "Edit"
    ) -> HistoryRecordResult:
        """Append a complete state, coalescing it when nothing changed."""

        normalized = _normalize_state(state)
        digest = state_digest(normalized)
        if not self.empty and self._entries[self._cursor].info.digest == digest:
            return HistoryRecordResult(
                entry=self._entries[self._cursor].info,
                added=False,
                redo_discarded=0,
            )
        return self._append_entry(normalized, label, digest=digest)

    def undo(self) -> ProjectState:
        if not self.can_undo:
            raise HistoryBoundaryError("No earlier project state is available.")
        self._cursor -= 1
        return self.current_state

    def redo(self) -> ProjectState:
        if not self.can_redo:
            raise HistoryBoundaryError("No later project state is available.")
        self._cursor += 1
        return self.current_state

    def create_snapshot(
        self,
        label: str,
        *,
        state: Mapping[str, Any] | None = None,
        reason: SnapshotReason = SnapshotReason.MANUAL,
    ) -> SnapshotInfo:
        """Capture a named state independently of the undo cursor."""

        if not isinstance(reason, SnapshotReason):
            try:
                reason = SnapshotReason(reason)
            except (TypeError, ValueError) as exc:
                raise ProjectHistoryError(f"Unknown snapshot reason: {reason!r}") from exc
        normalized = self.current_state if state is None else _normalize_state(state)
        info = SnapshotInfo(
            snapshot_id=str(uuid.uuid4()),
            label=_normalize_label(label, "Snapshot"),
            created_utc=_utc_now(),
            reason=reason,
            digest=state_digest(normalized),
        )
        self._snapshots.append(_SnapshotRecord(info=info, state=normalized))
        overflow = len(self._snapshots) - self.max_snapshots
        if overflow > 0:
            del self._snapshots[:overflow]
        return info

    def snapshot_before_import(
        self,
        *,
        state: Mapping[str, Any] | None = None,
        detail: str = "",
    ) -> SnapshotInfo:
        return self.create_snapshot(
            _automatic_label("Before import", detail),
            state=state,
            reason=SnapshotReason.BEFORE_IMPORT,
        )

    def snapshot_before_build(
        self,
        *,
        state: Mapping[str, Any] | None = None,
        detail: str = "",
    ) -> SnapshotInfo:
        return self.create_snapshot(
            _automatic_label("Before build", detail),
            state=state,
            reason=SnapshotReason.BEFORE_BUILD,
        )

    def snapshot_state(self, snapshot_id: str) -> ProjectState:
        return _clone_state(self._snapshot(snapshot_id).state)

    def restore_snapshot(
        self, snapshot_id: str, *, label: str | None = None
    ) -> ProjectState:
        snapshot = self._snapshot(snapshot_id)
        self.record(
            snapshot.state,
            label=label or f"Restore snapshot: {snapshot.info.label}",
        )
        return self.current_state

    def restore_section(
        self,
        snapshot_id: str,
        section: SectionPath,
        *,
        base_state: Mapping[str, Any] | None = None,
        label: str | None = None,
    ) -> ProjectState:
        """Restore one top-level or nested section and record the full result."""

        snapshot = self._snapshot(snapshot_id)
        path = _normalize_section_path(section)
        value = _get_section(snapshot.state, path, "snapshot")
        base = self.current_state if base_state is None else _normalize_state(base_state)
        _set_section(base, path, value)
        display_path = _pointer(path)
        self.record(
            base,
            label=label or f"Restore section {display_path}: {snapshot.info.label}",
        )
        return self.current_state

    def compare_snapshot(
        self,
        snapshot_id: str,
        *,
        state: Mapping[str, Any] | None = None,
        max_paths: int = 100,
    ) -> CompareSummary:
        current = self.current_state if state is None else _normalize_state(state)
        return compare_states(
            self._snapshot(snapshot_id).state,
            current,
            max_paths=max_paths,
        )

    def to_payload(self, *, project_id: str, workspace_id: str) -> dict[str, Any]:
        """Return the versioned document persisted by the application store."""

        _validate_uuid(project_id, "project_id")
        _validate_uuid(workspace_id, "workspace_id")
        return {
            "history_format": HISTORY_FORMAT,
            "history_version": HISTORY_FORMAT_VERSION,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "max_entries": self.max_entries,
            "max_snapshots": self.max_snapshots,
            "cursor": self._cursor,
            "entries": [
                {
                    "entry_id": record.info.entry_id,
                    "label": record.info.label,
                    "created_utc": record.info.created_utc,
                    "digest": record.info.digest,
                    "state": _clone_state(record.state),
                }
                for record in self._entries
            ],
            "snapshots": [
                {
                    "snapshot_id": record.info.snapshot_id,
                    "label": record.info.label,
                    "created_utc": record.info.created_utc,
                    "reason": record.info.reason.value,
                    "digest": record.info.digest,
                    "state": _clone_state(record.state),
                }
                for record in self._snapshots
            ],
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_project_id: str,
        expected_workspace_id: str,
    ) -> "ProjectHistory":
        """Validate and load a persisted history bound to one workspace."""

        if not isinstance(payload, Mapping):
            raise InvalidHistoryState("History document root must be an object.")
        if payload.get("history_format") != HISTORY_FORMAT:
            raise InvalidHistoryState("Unsupported project history format.")
        if payload.get("history_version") != HISTORY_FORMAT_VERSION:
            raise InvalidHistoryState("Unsupported project history version.")
        if payload.get("project_id") != expected_project_id:
            raise InvalidHistoryState("History belongs to a different project.")
        if payload.get("workspace_id") != expected_workspace_id:
            raise InvalidHistoryState("History belongs to a different workspace.")

        history = cls(
            max_entries=_required_int(payload, "max_entries"),
            max_snapshots=_required_int(payload, "max_snapshots"),
        )
        raw_entries = _required_list(payload, "entries")
        raw_snapshots = _required_list(payload, "snapshots")
        if len(raw_entries) > history.max_entries:
            raise InvalidHistoryState("History contains more entries than its limit.")
        if len(raw_snapshots) > history.max_snapshots:
            raise InvalidHistoryState("History contains more snapshots than its limit.")

        entry_ids: set[str] = set()
        previous_digest = ""
        for index, raw in enumerate(raw_entries):
            record = _load_entry(raw, index)
            if record.info.entry_id in entry_ids:
                raise InvalidHistoryState("History entry IDs must be unique.")
            if previous_digest == record.info.digest:
                raise InvalidHistoryState(
                    "Persisted history contains consecutive duplicate states."
                )
            entry_ids.add(record.info.entry_id)
            previous_digest = record.info.digest
            history._entries.append(record)

        snapshot_ids: set[str] = set()
        for index, raw in enumerate(raw_snapshots):
            record = _load_snapshot(raw, index)
            if record.info.snapshot_id in snapshot_ids:
                raise InvalidHistoryState("Snapshot IDs must be unique.")
            snapshot_ids.add(record.info.snapshot_id)
            history._snapshots.append(record)

        cursor = payload.get("cursor")
        if not isinstance(cursor, int) or isinstance(cursor, bool):
            raise InvalidHistoryState("History cursor must be an integer.")
        if history._entries:
            if not 0 <= cursor < len(history._entries):
                raise InvalidHistoryState("History cursor is outside the timeline.")
        elif cursor != -1:
            raise InvalidHistoryState("An empty history must have cursor -1.")
        history._cursor = cursor
        return history

    def _append_entry(
        self,
        state: ProjectState,
        label: str,
        *,
        digest: str | None = None,
    ) -> HistoryRecordResult:
        redo_discarded = len(self._entries) - self._cursor - 1
        if redo_discarded:
            del self._entries[self._cursor + 1 :]
        info = HistoryEntryInfo(
            entry_id=str(uuid.uuid4()),
            label=_normalize_label(label, "Edit"),
            created_utc=_utc_now(),
            digest=digest or state_digest(state),
        )
        self._entries.append(_HistoryRecord(info=info, state=_clone_state(state)))
        self._cursor = len(self._entries) - 1
        overflow = len(self._entries) - self.max_entries
        if overflow > 0:
            del self._entries[:overflow]
            self._cursor -= overflow
        return HistoryRecordResult(
            entry=info,
            added=True,
            redo_discarded=redo_discarded,
        )

    def _snapshot(self, snapshot_id: str) -> _SnapshotRecord:
        for record in self._snapshots:
            if record.info.snapshot_id == snapshot_id:
                return record
        raise UnknownSnapshotError(f"Unknown snapshot ID: {snapshot_id}")


def state_digest(state: Mapping[str, Any]) -> str:
    """Return a deterministic digest for a complete JSON project dictionary."""

    normalized = _normalize_state(state)
    return hashlib.sha256(_canonical_bytes(normalized)).hexdigest()


def compare_states(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    max_paths: int = 100,
) -> CompareSummary:
    """Summarize structural JSON differences without exposing stored objects."""

    old = _normalize_state(before)
    new = _normalize_state(after)
    if not isinstance(max_paths, int) or isinstance(max_paths, bool) or max_paths < 1:
        raise ProjectHistoryError("max_paths must be a positive integer.")
    changed: list[str] = []
    total = _collect_changes(old, new, (), changed, max_paths)
    old_keys = set(old)
    new_keys = set(new)
    added = tuple(sorted(new_keys - old_keys))
    removed = tuple(sorted(old_keys - new_keys))
    modified = tuple(
        sorted(key for key in old_keys & new_keys if not _same_json(old[key], new[key]))
    )
    return CompareSummary(
        identical=total == 0,
        total_changes=total,
        added_sections=added,
        removed_sections=removed,
        modified_sections=modified,
        changed_paths=tuple(changed),
        truncated=total > len(changed),
    )


def _normalize_state(state: Mapping[str, Any]) -> ProjectState:
    if not isinstance(state, Mapping):
        raise InvalidHistoryState("Project state root must be a JSON object.")
    try:
        normalized = _normalize_json(state, "$", set())
    except RecursionError as exc:
        raise InvalidHistoryState("Project state is nested too deeply.") from exc
    if not isinstance(normalized, dict):  # defensive; root check above guarantees it
        raise InvalidHistoryState("Project state root must be a JSON object.")
    return normalized


def _normalize_json(value: Any, path: str, active: set[int]) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidHistoryState(f"Non-finite number at {path} is not valid JSON.")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise InvalidHistoryState(f"Circular object at {path} is not valid JSON.")
        active.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise InvalidHistoryState(f"Object key at {path} must be a string.")
                result[key] = _normalize_json(item, f"{path}.{key}", active)
            return result
        finally:
            active.remove(identity)
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise InvalidHistoryState(f"Circular array at {path} is not valid JSON.")
        active.add(identity)
        try:
            return [
                _normalize_json(item, f"{path}[{index}]", active)
                for index, item in enumerate(value)
            ]
        finally:
            active.remove(identity)
    raise InvalidHistoryState(
        f"Unsupported value {type(value).__name__} at {path}; project history is JSON-only."
    )


def _clone_state(state: Mapping[str, Any]) -> ProjectState:
    return json.loads(_canonical_bytes(state))


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _bounded_limit(value: int, name: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise InvalidHistoryState(f"{name} must be between 1 and {maximum}.")
    return value


def _normalize_label(label: str, default: str) -> str:
    if not isinstance(label, str):
        raise ProjectHistoryError("History labels must be text.")
    if any(ord(character) < 32 or ord(character) == 127 for character in label):
        raise ProjectHistoryError("History labels cannot contain control characters.")
    normalized = " ".join(label.split()) or default
    if len(normalized) > MAX_LABEL_LENGTH:
        normalized = normalized[: MAX_LABEL_LENGTH - 1].rstrip() + "…"
    return normalized


def _automatic_label(prefix: str, detail: str) -> str:
    normalized_detail = _normalize_label(detail, "")
    return prefix if not normalized_detail else f"{prefix} — {normalized_detail}"


def _normalize_section_path(section: SectionPath) -> tuple[str | int, ...]:
    if isinstance(section, str):
        path: tuple[str | int, ...] = (section,)
    elif isinstance(section, Sequence) and not isinstance(section, (bytes, bytearray)):
        path = tuple(section)
    else:
        raise UnknownSectionError("Section must be a key or a key/index path.")
    if not path or not isinstance(path[0], str) or not path[0]:
        raise UnknownSectionError("A section path must start with a non-empty key.")
    for part in path:
        if isinstance(part, str):
            if not part:
                raise UnknownSectionError("Section keys cannot be empty.")
        elif isinstance(part, int) and not isinstance(part, bool) and part >= 0:
            continue
        else:
            raise UnknownSectionError(
                "Section path components must be non-empty keys or non-negative indexes."
            )
    return path


def _get_section(root: Any, path: tuple[str | int, ...], source: str) -> Any:
    current = root
    for part in path:
        if isinstance(part, str) and isinstance(current, Mapping) and part in current:
            current = current[part]
        elif (
            isinstance(part, int)
            and isinstance(current, list)
            and part < len(current)
        ):
            current = current[part]
        else:
            raise UnknownSectionError(
                f"Section {_pointer(path)} is not present in the {source} state."
            )
    return current


def _set_section(root: ProjectState, path: tuple[str | int, ...], value: Any) -> None:
    if len(path) == 1:
        root[path[0]] = _normalize_json(value, "$", set())
        return
    parent = _get_section(root, path[:-1], "base")
    final = path[-1]
    normalized = _normalize_json(value, "$", set())
    if isinstance(final, str) and isinstance(parent, dict):
        parent[final] = normalized
        return
    if isinstance(final, int) and isinstance(parent, list) and final < len(parent):
        parent[final] = normalized
        return
    raise UnknownSectionError(
        f"Section {_pointer(path)} cannot be placed in the base state."
    )


def _collect_changes(
    before: Any,
    after: Any,
    path: tuple[str | int, ...],
    output: list[str],
    limit: int,
) -> int:
    if type(before) is type(after) and isinstance(before, dict):
        total = 0
        for key in sorted(set(before) | set(after)):
            child = (*path, key)
            if key not in before or key not in after:
                total += 1
                if len(output) < limit:
                    output.append(_pointer(child))
            else:
                total += _collect_changes(before[key], after[key], child, output, limit)
        return total
    if type(before) is type(after) and isinstance(before, list):
        total = 0
        for index in range(max(len(before), len(after))):
            child = (*path, index)
            if index >= len(before) or index >= len(after):
                total += 1
                if len(output) < limit:
                    output.append(_pointer(child))
            else:
                total += _collect_changes(before[index], after[index], child, output, limit)
        return total
    if before == after and type(before) is type(after):
        return 0
    if len(output) < limit:
        output.append(_pointer(path))
    return 1


def _same_json(before: Any, after: Any) -> bool:
    """Use the same type-sensitive equality contract as ``_collect_changes``."""

    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(
            _same_json(before[key], after[key]) for key in before
        )
    if isinstance(before, list):
        return len(before) == len(after) and all(
            _same_json(old, new) for old, new in zip(before, after, strict=True)
        )
    return before == after


def _pointer(path: Sequence[str | int]) -> str:
    if not path:
        return "/"
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1") for part in path
    )


def _load_entry(raw: Any, index: int) -> _HistoryRecord:
    item = _required_mapping(raw, f"entries[{index}]")
    entry_id = _required_uuid(item, "entry_id", f"entries[{index}]")
    label = _required_label(item, "label", f"entries[{index}]")
    created = _required_timestamp(item, "created_utc", f"entries[{index}]")
    state = _normalize_state(_required_mapping(item.get("state"), f"entries[{index}].state"))
    digest = _required_digest(item, state, f"entries[{index}]")
    return _HistoryRecord(
        info=HistoryEntryInfo(entry_id, label, created, digest), state=state
    )


def _load_snapshot(raw: Any, index: int) -> _SnapshotRecord:
    item = _required_mapping(raw, f"snapshots[{index}]")
    snapshot_id = _required_uuid(item, "snapshot_id", f"snapshots[{index}]")
    label = _required_label(item, "label", f"snapshots[{index}]")
    created = _required_timestamp(item, "created_utc", f"snapshots[{index}]")
    try:
        reason = SnapshotReason(item.get("reason"))
    except (TypeError, ValueError) as exc:
        raise InvalidHistoryState(
            f"snapshots[{index}].reason is not recognized."
        ) from exc
    state = _normalize_state(
        _required_mapping(item.get("state"), f"snapshots[{index}].state")
    )
    digest = _required_digest(item, state, f"snapshots[{index}]")
    return _SnapshotRecord(
        info=SnapshotInfo(snapshot_id, label, created, reason, digest), state=state
    )


def _required_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidHistoryState(f"{path} must be an object.")
    return value


def _required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise InvalidHistoryState(f"{key} must be an array.")
    return value


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidHistoryState(f"{key} must be an integer.")
    return value


def _required_uuid(payload: Mapping[str, Any], key: str, path: str) -> str:
    value = payload.get(key)
    try:
        _validate_uuid(value, f"{path}.{key}")
    except ProjectHistoryError as exc:
        raise InvalidHistoryState(str(exc)) from exc
    return value


def _validate_uuid(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise ProjectHistoryError(f"{name} must be a UUID string.")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ProjectHistoryError(f"{name} must be a UUID string.") from exc


def _required_label(payload: Mapping[str, Any], key: str, path: str) -> str:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise InvalidHistoryState(f"{path}.{key} must be text.")
    try:
        normalized = _normalize_label(raw, "")
    except ProjectHistoryError as exc:
        raise InvalidHistoryState(str(exc)) from exc
    if raw != normalized or not raw:
        raise InvalidHistoryState(f"{path}.{key} is not a normalized label.")
    return raw


def _required_timestamp(payload: Mapping[str, Any], key: str, path: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise InvalidHistoryState(f"{path}.{key} must be an ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidHistoryState(
            f"{path}.{key} must be an ISO-8601 timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise InvalidHistoryState(f"{path}.{key} must include a timezone.")
    return value


def _required_digest(
    payload: Mapping[str, Any], state: ProjectState, path: str
) -> str:
    digest = payload.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise InvalidHistoryState(f"{path}.digest must be a SHA-256 digest.")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise InvalidHistoryState(f"{path}.digest must be a SHA-256 digest.") from exc
    expected = state_digest(state)
    if digest.lower() != expected:
        raise InvalidHistoryState(f"{path} state digest does not match its content.")
    return expected


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


__all__ = [
    "CompareSummary",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_SNAPSHOTS",
    "HISTORY_FORMAT",
    "HISTORY_FORMAT_VERSION",
    "HistoryBoundaryError",
    "HistoryEntryInfo",
    "HistoryRecordResult",
    "InvalidHistoryState",
    "ProjectHistory",
    "ProjectHistoryError",
    "ProjectState",
    "SectionPath",
    "SnapshotInfo",
    "SnapshotReason",
    "UnknownSectionError",
    "UnknownSnapshotError",
    "compare_states",
    "state_digest",
]
