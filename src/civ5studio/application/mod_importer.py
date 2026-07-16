"""Conservative, lossless inspection of existing Civilization V mods.

The importer intentionally does not translate arbitrary SQL, XML, Lua, DLL,
or art into editable Studio fields.  It extracts trustworthy metadata and
candidate custom Type declarations, then records every source file as immutable
inspection evidence.  Creating a workspace copies those files byte-for-byte
below a marked project directory without modifying the source.  Snapshot bytes
are never compiled into generated mods.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any, Iterable, Mapping
import uuid
import xml.etree.ElementTree as ET

from civ5studio.domain import CivProject, normalize_prefix

from .workspace import DEFAULT_PROJECT_FILE, ProjectWorkspace


IMPORT_EXTENSION_KEY = "existing_mod_import"
IMPORT_FORMAT = "civ5studio.existing-mod-import"
IMPORT_FORMAT_VERSION = 2
SNAPSHOT_ROOT = "ImportedMod/Source"
MAX_XML_PARSE_BYTES = 16 * 1024 * 1024
MAX_SQL_SCAN_BYTES = 16 * 1024 * 1024
MAX_SOURCE_FILES = 100_000

_KNOWN_ACTIONS = frozenset({"UpdateDatabase", "UpdateText", "UpdateArt"})
_TABLE_CATEGORIES = {
    "civilizations": ("civilizations", "CIVILIZATION_"),
    "leaders": ("leaders", "LEADER_"),
    "traits": ("traits", "TRAIT_"),
    "units": ("units", "UNIT_"),
    "buildings": ("buildings", "BUILDING_"),
}
_TYPE_RE = re.compile(
    r"\b(?:CIVILIZATION|LEADER|TRAIT|UNIT|BUILDING)_[A-Z][A-Z0-9_]*\b"
)
_INSERT_RE = re.compile(
    r"^\s*INSERT(?:\s+OR\s+\w+)?\s+INTO\s+"
    r"(?:\[([^\]]+)\]|[`\"]([^`\"]+)[`\"]|([A-Za-z_][A-Za-z0-9_]*))",
    re.IGNORECASE | re.DOTALL,
)


class ModImportError(RuntimeError):
    """Base class for existing-mod import failures."""


class UnsafeModSourceError(ModImportError):
    """Raised when a source or manifest path is not safe to inspect or copy."""


class ModInfoParseError(ModImportError):
    """Raised when the selected ``.modinfo`` cannot be parsed safely."""


class ModSourceChangedError(ModImportError):
    """Raised when source bytes change between inspection and snapshot copy."""


class ImportedSnapshotError(ModImportError):
    """Raised when imported-snapshot metadata or workspace state is invalid."""


@dataclass(frozen=True, slots=True)
class ImportDiagnostic:
    severity: str
    code: str
    message: str
    relative_path: str = ""

    def to_dict(self) -> dict[str, str]:
        result = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.relative_path:
            result["relative_path"] = self.relative_path
        return result


@dataclass(frozen=True, slots=True)
class ModActionRecord:
    action_type: str
    relative_path: str
    supported_inventory: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "relative_path": self.relative_path,
            "supported_inventory": self.supported_inventory,
        }


@dataclass(frozen=True, slots=True)
class TypeEvidence:
    category: str
    type_name: str
    relative_path: str
    source_format: str
    confidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "type": self.type_name,
            "relative_path": self.relative_path,
            "source_format": self.source_format,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ModFileRecord:
    relative_path: str
    size: int
    sha256: str
    declared_in_modinfo: bool
    vfs: bool
    actions: tuple[str, ...]
    parse_kind: str
    parse_status: str
    parse_message: str = ""

    def to_dict(self, *, snapshot_root: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_relative_path": self.relative_path,
            "size": self.size,
            "sha256": self.sha256,
            "declared_in_modinfo": self.declared_in_modinfo,
            "vfs": self.vfs,
            "actions": list(self.actions),
            "parse_kind": self.parse_kind,
            "parse_status": self.parse_status,
            "inspection_evidence": True,
            "included_in_generated_build": False,
            "editable": False,
        }
        if self.parse_message:
            result["parse_message"] = self.parse_message
        if snapshot_root:
            result["workspace_path"] = (
                f"{snapshot_root.rstrip('/')}/{self.relative_path}"
            )
        return result


@dataclass(frozen=True, slots=True)
class ModImportReport:
    source_root: Path
    modinfo_relative_path: str
    mod_name: str
    original_mod_id: str
    mod_version: int
    properties: Mapping[str, str]
    files: tuple[ModFileRecord, ...]
    actions: tuple[ModActionRecord, ...]
    identified_types: tuple[TypeEvidence, ...]
    diagnostics: tuple[ImportDiagnostic, ...]

    @property
    def modinfo_path(self) -> Path:
        return _source_path(self.source_root, self.modinfo_relative_path)

    @property
    def vfs_files(self) -> tuple[str, ...]:
        return tuple(item.relative_path for item in self.files if item.vfs)

    def action_files(self, action_type: str) -> tuple[str, ...]:
        return tuple(
            item.relative_path
            for item in self.actions
            if item.action_type.casefold() == action_type.casefold()
        )

    def types_for(self, category: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.type_name
                    for item in self.identified_types
                    if item.category == category
                }
            )
        )

    def to_extension(self, *, snapshot_root: str | None = None) -> dict[str, Any]:
        snapshot_complete = snapshot_root is not None
        return {
            "import_format": IMPORT_FORMAT,
            "import_format_version": IMPORT_FORMAT_VERSION,
            "import_mode": "read_only_inspection_snapshot",
            "generated_build_inclusion": "excluded",
            "source": {
                "folder_name": self.source_root.name,
                "modinfo_relative_path": self.modinfo_relative_path,
                "original_mod_id": self.original_mod_id,
                "mod_version": self.mod_version,
            },
            "properties": dict(sorted(self.properties.items())),
            "editability": {
                "status": "partial_metadata_only",
                "editable_fields": [
                    "mod_name",
                    "mod_version",
                    "authors",
                    "teaser",
                    "description",
                ],
                "source_files_editable": False,
                "note": (
                    "SQL, XML, Lua, DLL, and art source files are preserved "
                    "byte-for-byte as immutable inspection evidence. They are not "
                    "included in generated builds or claimed to be round-trip editable."
                ),
            },
            "snapshot": {
                "status": "complete" if snapshot_complete else "not_created",
                "root": snapshot_root or "",
                "file_count": len(self.files),
            },
            "actions": [item.to_dict() for item in self.actions],
            "identified_types": [item.to_dict() for item in self.identified_types],
            "files": [
                item.to_dict(snapshot_root=snapshot_root) for item in self.files
            ],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "runtime_validation": "not_run",
        }


@dataclass(frozen=True, slots=True)
class ModImportPlan:
    report: ModImportReport
    project: CivProject


@dataclass(frozen=True, slots=True)
class ModImportResult:
    workspace: ProjectWorkspace
    report: ModImportReport
    copied_files: int


@dataclass(frozen=True, slots=True)
class ImportedSnapshotCopyResult:
    """Evidence that a complete imported snapshot was copied and reverified."""

    source_root: Path
    destination_root: Path
    copied_files: int
    copied_bytes: int


@dataclass(frozen=True, slots=True)
class _SnapshotRecord:
    relative_path: str
    size: int
    sha256: str


@dataclass(slots=True)
class _FileBuilder:
    relative_path: str
    size: int
    sha256: str
    declared: bool = False
    vfs: bool = False
    actions: set[str] | None = None
    parse_kind: str = "none"
    parse_status: str = "not_parsed"
    parse_message: str = ""

    def freeze(self) -> ModFileRecord:
        return ModFileRecord(
            relative_path=self.relative_path,
            size=self.size,
            sha256=self.sha256,
            declared_in_modinfo=self.declared,
            vfs=self.vfs,
            actions=tuple(sorted(self.actions or (), key=str.casefold)),
            parse_kind=self.parse_kind,
            parse_status=self.parse_status,
            parse_message=self.parse_message,
        )


class ExistingModImporter:
    """Inspect existing mods and optionally snapshot them into a new workspace."""

    def inspect(self, source: str | Path) -> ModImportPlan:
        source_root, modinfo_path = _locate_mod(source)
        physical_files = _inventory_source(source_root)
        relative_modinfo = _relative_source_path(source_root, modinfo_path)
        modinfo_bytes = modinfo_path.read_bytes()
        root = _parse_xml_bytes(modinfo_bytes, relative_modinfo, is_modinfo=True)
        if _local_name(root.tag).casefold() != "mod":
            raise ModInfoParseError("The .modinfo root element must be <Mod>.")

        diagnostics: list[ImportDiagnostic] = []
        properties = _mod_properties(root)
        actions = _mod_actions(root)
        declared = _declared_files(root)
        by_casefold = {item.casefold(): item for item in physical_files}

        referenced_paths = {item[0] for item in declared.values()}
        referenced_paths.update(item.relative_path for item in actions)
        for path in referenced_paths:
            if path.casefold() not in by_casefold:
                diagnostics.append(
                    ImportDiagnostic(
                        "error",
                        "missing_declared_file",
                        "The .modinfo references a file that is not present.",
                        path,
                    )
                )

        builders: dict[str, _FileBuilder] = {}
        action_by_path: dict[str, set[str]] = {}
        for action in actions:
            actual = by_casefold.get(action.relative_path.casefold())
            key = (actual or action.relative_path).casefold()
            action_by_path.setdefault(key, set()).add(action.action_type)
            if not action.supported_inventory:
                diagnostics.append(
                    ImportDiagnostic(
                        "warning",
                        "unsupported_mod_action",
                        f"Action {action.action_type!r} is preserved but not editable.",
                        action.relative_path,
                    )
                )

        evidence: list[TypeEvidence] = []
        for relative_path, (size, digest) in physical_files.items():
            declared_record = declared.get(relative_path.casefold())
            builder = _FileBuilder(
                relative_path=relative_path,
                size=size,
                sha256=digest,
                declared=declared_record is not None,
                vfs=bool(declared_record and declared_record[1]),
                actions=action_by_path.get(relative_path.casefold(), set()),
            )
            if relative_path == relative_modinfo:
                builder.parse_kind = "modinfo"
                builder.parse_status = "parsed"
            elif Path(relative_path).suffix.casefold() == ".xml":
                parsed, found, message = _inspect_xml_file(
                    _source_path(source_root, relative_path), relative_path
                )
                builder.parse_kind = "xml"
                builder.parse_status = "parsed" if parsed else "error"
                builder.parse_message = message
                evidence.extend(found)
                if not parsed:
                    diagnostics.append(
                        ImportDiagnostic(
                            "warning", "xml_parse_failed", message, relative_path
                        )
                    )
            elif Path(relative_path).suffix.casefold() == ".sql":
                parsed, found, message = _inspect_sql_file(
                    _source_path(source_root, relative_path), relative_path
                )
                builder.parse_kind = "sql"
                builder.parse_status = "scanned" if parsed else "error"
                builder.parse_message = message
                evidence.extend(found)
                if not parsed:
                    diagnostics.append(
                        ImportDiagnostic(
                            "warning", "sql_scan_failed", message, relative_path
                        )
                    )
            else:
                builder.parse_kind = _file_kind(relative_path)
                builder.parse_status = "not_parsed"
            if not builder.declared and relative_path != relative_modinfo:
                diagnostics.append(
                    ImportDiagnostic(
                        "info",
                        "unlisted_source_file",
                        "File is not listed in <Files>; it is still preserved.",
                        relative_path,
                    )
                )
            builders[relative_path.casefold()] = builder

        for section in ("Dependencies", "References", "Blocks", "EntryPoints"):
            element = _first_child(root, section)
            if element is not None and list(element):
                diagnostics.append(
                    ImportDiagnostic(
                        "warning",
                        f"unsupported_{section.casefold()}",
                        f"{section} are preserved in the source snapshot but not editable.",
                        relative_modinfo,
                    )
                )

        original_mod_id = str(root.attrib.get("id", "")).strip()
        try:
            uuid.UUID(original_mod_id)
        except (ValueError, TypeError, AttributeError):
            diagnostics.append(
                ImportDiagnostic(
                    "warning",
                    "invalid_original_mod_id",
                    "The original mod ID is not a UUID; a new Studio mod ID will be used.",
                    relative_modinfo,
                )
            )
        version = _positive_int(root.attrib.get("version"), fallback=1)
        report = ModImportReport(
            source_root=source_root,
            modinfo_relative_path=relative_modinfo,
            mod_name=properties.get("Name", source_root.name),
            original_mod_id=original_mod_id,
            mod_version=version,
            properties=properties,
            files=tuple(
                builders[key].freeze()
                for key in sorted(builders, key=lambda item: builders[item].relative_path.casefold())
            ),
            actions=tuple(
                sorted(actions, key=lambda item: (item.action_type.casefold(), item.relative_path.casefold()))
            ),
            identified_types=tuple(
                sorted(
                    _deduplicate_evidence(evidence),
                    key=lambda item: (
                        item.category,
                        item.type_name,
                        item.relative_path.casefold(),
                    ),
                )
            ),
            diagnostics=tuple(
                sorted(
                    diagnostics,
                    key=lambda item: (
                        item.severity,
                        item.relative_path.casefold(),
                        item.code,
                    ),
                )
            ),
        )
        project = _project_from_report(report)
        return ModImportPlan(report=report, project=project)

    def create_workspace(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        project_file: str = DEFAULT_PROJECT_FILE,
    ) -> ModImportResult:
        """Create a marked workspace with an immutable byte snapshot of the mod."""

        plan = self.inspect(source)
        raw_destination = Path(destination).expanduser()
        if _is_link_or_reparse(raw_destination):
            raise UnsafeModSourceError("Import destination cannot be a link or junction.")
        resolved_destination = raw_destination.resolve(strict=False)
        try:
            resolved_destination.relative_to(plan.report.source_root)
        except ValueError:
            pass
        else:
            raise UnsafeModSourceError(
                "Import destination cannot be inside the source mod directory."
            )

        workspace = ProjectWorkspace.create(
            resolved_destination,
            plan.project,
            project_file=project_file,
        )
        snapshot_root = _workspace_snapshot_root(workspace)
        copied = 0
        for record in plan.report.files:
            source_file = _source_path(plan.report.source_root, record.relative_path)
            target = _snapshot_path(snapshot_root, record.relative_path)
            _copy_verified(source_file, target, record)
            copied += 1

        updated = workspace.load()
        updated.extensions[IMPORT_EXTENSION_KEY] = plan.report.to_extension(
            snapshot_root=SNAPSHOT_ROOT
        )
        workspace.save(updated, require_assets=False)
        return ModImportResult(
            workspace=workspace,
            report=plan.report,
            copied_files=copied,
        )


def copy_imported_snapshot(
    project: CivProject,
    source_workspace: ProjectWorkspace | str | Path,
    destination_workspace: ProjectWorkspace | str | Path,
) -> ImportedSnapshotCopyResult | None:
    """Copy a complete imported-mod snapshot between marked workspaces.

    ``None`` is returned when the project has no existing-mod import extension.
    Otherwise both workspaces, the immutable manifest, every source byte, and
    the staged destination inventory are verified before the complete
    ``ImportedMod`` tree is moved into place.  Existing destination content is
    never replaced.

    The destination workspace must already contain ``project`` (as it does
    immediately after :meth:`ProjectWorkspace.create` during Save As).
    """

    records = _snapshot_records(project)
    if records is None:
        return None

    source = _open_workspace(source_workspace, role="source")
    destination = _open_workspace(destination_workspace, role="destination")
    _validate_snapshot_workspace_pair(project, source, destination)

    source_snapshot = source.root.joinpath(*PurePosixPath(SNAPSHOT_ROOT).parts)
    source_snapshot_resolved = _verified_snapshot_root(source, source_snapshot)
    actual = _inventory_source(source_snapshot)
    _verify_snapshot_inventory(records, actual, context="source snapshot")

    destination_imported = destination.root / "ImportedMod"
    if destination_imported.exists() or _is_link_or_reparse(destination_imported):
        raise ImportedSnapshotError(
            f"Refusing to overwrite existing imported snapshot content: {destination_imported}"
        )

    control = destination.root / ".civ5studio"
    if not control.is_dir() or _is_link_or_reparse(control):
        raise ImportedSnapshotError(
            f"Destination workspace controls are missing or unsafe: {control}"
        )

    with tempfile.TemporaryDirectory(
        prefix="imported-snapshot-", dir=control
    ) as temporary_name:
        temporary_root = Path(temporary_name)
        staged_imported = temporary_root / "ImportedMod"
        staged_snapshot = staged_imported / "Source"
        staged_snapshot.mkdir(parents=True, exist_ok=False)

        for record in records:
            source_file = _verified_snapshot_file(
                source,
                source_snapshot,
                source_snapshot_resolved,
                record.relative_path,
            )
            target = _snapshot_path(staged_snapshot, record.relative_path)
            _copy_expected_bytes(
                source_file,
                target,
                relative_path=record.relative_path,
                expected_size=record.size,
                expected_sha256=record.sha256,
            )

        staged_inventory = _inventory_source(staged_snapshot)
        _verify_snapshot_inventory(records, staged_inventory, context="staged snapshot")
        if destination_imported.exists() or _is_link_or_reparse(destination_imported):
            raise ImportedSnapshotError(
                f"Imported snapshot destination became occupied: {destination_imported}"
            )
        try:
            os.rename(staged_imported, destination_imported)
        except OSError as exc:
            raise ImportedSnapshotError(
                f"Could not publish the verified imported snapshot: {destination_imported}"
            ) from exc

    return ImportedSnapshotCopyResult(
        source_root=source_snapshot,
        destination_root=destination_imported / "Source",
        copied_files=len(records),
        copied_bytes=sum(record.size for record in records),
    )


def _project_from_report(report: ModImportReport) -> CivProject:
    try:
        parsed_mod_id = str(uuid.UUID(report.original_mod_id))
    except (ValueError, TypeError, AttributeError):
        parsed_mod_id = str(uuid.uuid4())

    civilization_types = report.types_for("civilizations")
    if len(civilization_types) == 1:
        prefix_seed = civilization_types[0].removeprefix("CIVILIZATION_")
    else:
        prefix_seed = report.mod_name
    prefix = normalize_prefix(prefix_seed)[:48] or "IMPORTED_MOD"
    properties = report.properties
    return CivProject(
        mod_id=parsed_mod_id,
        mod_name=report.mod_name,
        mod_version=report.mod_version,
        authors=properties.get("Authors", ""),
        teaser=properties.get("Teaser", ""),
        description=properties.get("Description", ""),
        internal_prefix=prefix,
        extensions={
            IMPORT_EXTENSION_KEY: report.to_extension(snapshot_root=None),
        },
    )


def _locate_mod(source: str | Path) -> tuple[Path, Path]:
    raw = Path(source).expanduser()
    if _is_link_or_reparse(raw):
        raise UnsafeModSourceError("Mod source cannot be a link or junction.")
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise UnsafeModSourceError(f"Mod source does not exist: {raw}") from exc
    if resolved.is_file():
        if resolved.suffix.casefold() != ".modinfo":
            raise UnsafeModSourceError("Select a mod directory or a .modinfo file.")
        source_root = resolved.parent
        modinfo = resolved
    elif resolved.is_dir():
        source_root = resolved
        candidates = sorted(
            (
                path
                for path in source_root.iterdir()
                if path.is_file() and path.suffix.casefold() == ".modinfo"
            ),
            key=lambda path: path.name.casefold(),
        )
        if not candidates:
            raise ModInfoParseError("No top-level .modinfo file was found.")
        if len(candidates) != 1:
            raise ModInfoParseError(
                "More than one top-level .modinfo exists; select one explicitly."
            )
        modinfo = candidates[0]
    else:
        raise UnsafeModSourceError("Mod source is neither a file nor a directory.")
    if _is_link_or_reparse(source_root) or _is_link_or_reparse(modinfo):
        raise UnsafeModSourceError("Mod source cannot contain a linked root or .modinfo.")
    return source_root, modinfo


def _inventory_source(source_root: Path) -> dict[str, tuple[int, str]]:
    inventory: dict[str, tuple[int, str]] = {}
    casefolded: set[str] = set()
    stack = [source_root]
    while stack:
        directory = stack.pop()
        if _is_link_or_reparse(directory):
            raise UnsafeModSourceError(f"Linked directory is not allowed: {directory}")
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise UnsafeModSourceError(f"Could not inspect mod directory: {directory}") from exc
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink() or _is_link_or_reparse(path):
                raise UnsafeModSourceError(f"Links and junctions are not allowed: {path}")
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise UnsafeModSourceError(f"Unsupported source filesystem entry: {path}")
            relative = _relative_source_path(source_root, path)
            folded = relative.casefold()
            if folded in casefolded:
                raise UnsafeModSourceError(
                    f"Source has a case-insensitive path collision: {relative}"
                )
            casefolded.add(folded)
            inventory[relative] = (entry.stat(follow_symlinks=False).st_size, _sha256(path))
            if len(inventory) > MAX_SOURCE_FILES:
                raise UnsafeModSourceError(
                    f"Mod contains more than {MAX_SOURCE_FILES:,} files."
                )
    return inventory


def _declared_files(root: ET.Element) -> dict[str, tuple[str, bool]]:
    result: dict[str, tuple[str, bool]] = {}
    files = _first_child(root, "Files")
    if files is None:
        return result
    for element in files.iter():
        if _local_name(element.tag).casefold() != "file":
            continue
        path = _normalize_relative_path(element.text or "", context="<File>")
        vfs = str(element.attrib.get("import", "0")).strip().casefold() in {
            "1",
            "true",
            "yes",
        }
        key = path.casefold()
        if key in result:
            result[key] = (result[key][0], result[key][1] or vfs)
        else:
            result[key] = (path, vfs)
    return result


def _mod_actions(root: ET.Element) -> list[ModActionRecord]:
    result: list[ModActionRecord] = []
    actions = _first_child(root, "Actions")
    if actions is None:
        return result
    for element in actions.iter():
        if element is actions or list(element):
            continue
        action_type = _local_name(element.tag)
        text = (element.text or "").strip()
        if not text:
            continue
        path = _normalize_relative_path(text, context=f"<{action_type}>")
        result.append(
            ModActionRecord(
                action_type=action_type,
                relative_path=path,
                supported_inventory=action_type in _KNOWN_ACTIONS,
            )
        )
    return result


def _mod_properties(root: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    properties = _first_child(root, "Properties")
    if properties is None:
        return result
    for child in properties:
        if list(child):
            continue
        result[_local_name(child.tag)] = (child.text or "").strip()
    return result


def _inspect_xml_file(
    path: Path, relative_path: str
) -> tuple[bool, list[TypeEvidence], str]:
    if path.stat().st_size > MAX_XML_PARSE_BYTES:
        return False, [], f"XML exceeds the {MAX_XML_PARSE_BYTES // (1024 * 1024)} MiB scan limit."
    try:
        root = _parse_xml_bytes(path.read_bytes(), relative_path, is_modinfo=False)
    except ModInfoParseError as exc:
        return False, [], str(exc)
    result: list[TypeEvidence] = []
    for table in root.iter():
        key = _local_name(table.tag).casefold()
        definition = _TABLE_CATEGORIES.get(key)
        if definition is None:
            continue
        category, prefix = definition
        for row in table:
            if _local_name(row.tag).casefold() != "row":
                continue
            type_name = _xml_row_type(row)
            if type_name and type_name.startswith(prefix) and _valid_type(type_name):
                result.append(
                    TypeEvidence(
                        category,
                        type_name,
                        relative_path,
                        "xml",
                        "declared_row",
                    )
                )
    return True, result, ""


def _inspect_sql_file(
    path: Path, relative_path: str
) -> tuple[bool, list[TypeEvidence], str]:
    if path.stat().st_size > MAX_SQL_SCAN_BYTES:
        return False, [], f"SQL exceeds the {MAX_SQL_SCAN_BYTES // (1024 * 1024)} MiB scan limit."
    try:
        text = _decode_text(path.read_bytes())
    except UnicodeError as exc:
        return False, [], f"SQL text encoding is unsupported: {exc}"
    result: list[TypeEvidence] = []
    for statement in _sql_statements(text):
        match = _INSERT_RE.match(statement)
        if match is None:
            continue
        table_name = next(value for value in match.groups() if value is not None)
        definition = _TABLE_CATEGORIES.get(table_name.casefold())
        if definition is None:
            continue
        category, prefix = definition
        for type_name in _TYPE_RE.findall(statement):
            if type_name.startswith(prefix) and _valid_type(type_name):
                result.append(
                    TypeEvidence(
                        category,
                        type_name,
                        relative_path,
                        "sql",
                        "candidate_insert",
                    )
                )
    return True, result, ""


def _parse_xml_bytes(data: bytes, relative_path: str, *, is_modinfo: bool) -> ET.Element:
    label = ".modinfo" if is_modinfo else "XML"
    if len(data) > MAX_XML_PARSE_BYTES:
        raise ModInfoParseError(
            f"{label} exceeds the {MAX_XML_PARSE_BYTES // (1024 * 1024)} MiB parse limit: "
            f"{relative_path}"
        )
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ModInfoParseError(
            f"DTD and entity declarations are not allowed in {label}: {relative_path}"
        )
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ModInfoParseError(f"Could not parse {label} {relative_path}: {exc}") from exc


def _sql_statements(text: str) -> Iterable[str]:
    buffer: list[str] = []
    index = 0
    quote = ""
    line_comment = False
    block_comment = False
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if character in "\r\n":
                line_comment = False
                buffer.append(character)
            index += 1
            continue
        if block_comment:
            if character == "*" and following == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if not quote and character == "-" and following == "-":
            line_comment = True
            index += 2
            continue
        if not quote and character == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        if quote:
            buffer.append(character)
            if character == quote:
                if following == quote:
                    buffer.append(following)
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            buffer.append(character)
            index += 1
            continue
        if character == ";":
            statement = "".join(buffer).strip()
            if statement:
                yield statement
            buffer = []
        else:
            buffer.append(character)
        index += 1
    statement = "".join(buffer).strip()
    if statement:
        yield statement


def _xml_row_type(row: ET.Element) -> str:
    for key, value in row.attrib.items():
        if _local_name(key).casefold() == "type":
            return value.strip()
    for child in row:
        if _local_name(child.tag).casefold() == "type":
            return (child.text or "").strip()
    return ""


def _deduplicate_evidence(values: Iterable[TypeEvidence]) -> tuple[TypeEvidence, ...]:
    result: list[TypeEvidence] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in values:
        key = (item.category, item.type_name, item.relative_path.casefold(), item.source_format)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _first_child(root: ET.Element, name: str) -> ET.Element | None:
    expected = name.casefold()
    return next(
        (child for child in root if _local_name(child.tag).casefold() == expected),
        None,
    )


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].split(":", 1)[-1]


def _valid_type(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", value))


def _normalize_relative_path(value: str, *, context: str) -> str:
    raw = value.strip().replace("\\", "/")
    drive, _ = ntpath.splitdrive(raw)
    if not raw or drive or raw.startswith("/") or "\x00" in raw:
        raise UnsafeModSourceError(f"Unsafe path in {context}: {value!r}")
    original_parts = raw.split("/")
    if ".." in original_parts:
        raise UnsafeModSourceError(f"Traversal path in {context}: {value!r}")
    parts = [part for part in original_parts if part not in {"", "."}]
    if not parts:
        raise UnsafeModSourceError(f"Empty path in {context}: {value!r}")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{index}" for index in range(1, 10))
    reserved.update(f"LPT{index}" for index in range(1, 10))
    for part in parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or any(character in '<>:"|?*' for character in part)
            or part.split(".", 1)[0].upper() in reserved
        ):
            raise UnsafeModSourceError(f"Windows-unsafe path in {context}: {value!r}")
    return PurePosixPath(*parts).as_posix()


def _relative_source_path(root: Path, path: Path) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UnsafeModSourceError(f"File escapes the selected mod root: {path}") from exc
    return _normalize_relative_path(relative.as_posix(), context="source filesystem")


def _source_path(root: Path, relative_path: str) -> Path:
    normalized = _normalize_relative_path(relative_path, context="source lookup")
    candidate = root.joinpath(*PurePosixPath(normalized).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UnsafeModSourceError(f"Source path escapes the mod root: {relative_path}") from exc
    if not resolved.is_file() or _is_link_or_reparse(candidate):
        raise UnsafeModSourceError(f"Source path is not a regular file: {relative_path}")
    return resolved


def _workspace_snapshot_root(workspace: ProjectWorkspace) -> Path:
    root = workspace.root / "ImportedMod" / "Source"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _snapshot_path(snapshot_root: Path, relative_path: str) -> Path:
    normalized = _normalize_relative_path(relative_path, context="snapshot target")
    target = snapshot_root.joinpath(*PurePosixPath(normalized).parts)
    try:
        target.resolve(strict=False).relative_to(snapshot_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UnsafeModSourceError(f"Snapshot target escapes its root: {relative_path}") from exc
    return target


def _snapshot_records(project: CivProject) -> tuple[_SnapshotRecord, ...] | None:
    if IMPORT_EXTENSION_KEY not in project.extensions:
        return None
    raw = project.extensions.get(IMPORT_EXTENSION_KEY)
    if not isinstance(raw, Mapping):
        raise ImportedSnapshotError("Existing-mod import metadata must be an object.")
    if raw.get("import_format") != IMPORT_FORMAT:
        raise ImportedSnapshotError("Existing-mod import metadata has an unknown format.")
    version = raw.get("import_format_version")
    if type(version) is not int or version not in {1, IMPORT_FORMAT_VERSION}:
        raise ImportedSnapshotError(
            f"Unsupported existing-mod import metadata version: {version!r}"
        )

    snapshot = raw.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise ImportedSnapshotError("Existing-mod snapshot metadata must be an object.")
    if snapshot.get("status") != "complete":
        raise ImportedSnapshotError(
            "The existing-mod snapshot is not recorded as complete."
        )
    snapshot_root = str(snapshot.get("root", "")).replace("\\", "/")
    if snapshot_root != SNAPSHOT_ROOT:
        raise ImportedSnapshotError(
            f"Imported snapshot root must be exactly {SNAPSHOT_ROOT!r}."
        )

    files = raw.get("files")
    if not isinstance(files, list) or not files:
        raise ImportedSnapshotError(
            "A complete existing-mod snapshot must contain a non-empty file manifest."
        )
    file_count = snapshot.get("file_count")
    if type(file_count) is not int or file_count != len(files):
        raise ImportedSnapshotError(
            "Existing-mod snapshot file_count does not match its manifest."
        )

    records: list[_SnapshotRecord] = []
    casefolded: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, Mapping):
            raise ImportedSnapshotError(
                f"Existing-mod snapshot file record {index} must be an object."
            )
        raw_relative = str(item.get("source_relative_path", ""))
        relative = _normalize_relative_path(
            raw_relative, context=f"snapshot manifest file {index}"
        )
        if raw_relative.replace("\\", "/") != relative:
            raise ImportedSnapshotError(
                f"Snapshot manifest path is not canonical: {raw_relative!r}"
            )
        folded = relative.casefold()
        if folded in casefolded:
            raise ImportedSnapshotError(
                f"Snapshot manifest has a case-insensitive path collision: {relative}"
            )
        casefolded.add(folded)

        size = item.get("size")
        if type(size) is not int or size < 0:
            raise ImportedSnapshotError(
                f"Snapshot manifest size is invalid for {relative!r}."
            )
        digest = str(item.get("sha256", "")).lower()
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ImportedSnapshotError(
                f"Snapshot manifest SHA-256 is invalid for {relative!r}."
            )
        expected_workspace_path = f"{SNAPSHOT_ROOT}/{relative}"
        workspace_path = str(item.get("workspace_path", "")).replace("\\", "/")
        if workspace_path != expected_workspace_path:
            raise ImportedSnapshotError(
                f"Snapshot workspace path does not match its source path: {relative!r}."
            )
        records.append(_SnapshotRecord(relative, size, digest))

    source = raw.get("source")
    if not isinstance(source, Mapping):
        raise ImportedSnapshotError("Existing-mod source metadata must be an object.")
    modinfo_relative = _normalize_relative_path(
        str(source.get("modinfo_relative_path", "")), context="snapshot .modinfo"
    )
    if modinfo_relative.casefold() not in casefolded:
        raise ImportedSnapshotError(
            "The recorded .modinfo is missing from the snapshot manifest."
        )
    return tuple(sorted(records, key=lambda item: item.relative_path.casefold()))


def _open_workspace(
    value: ProjectWorkspace | str | Path, *, role: str
) -> ProjectWorkspace:
    root = value.root if isinstance(value, ProjectWorkspace) else value
    try:
        return ProjectWorkspace.open(root)
    except Exception as exc:
        raise ImportedSnapshotError(
            f"Could not open the marked {role} workspace: {root}"
        ) from exc


def _validate_snapshot_workspace_pair(
    project: CivProject,
    source: ProjectWorkspace,
    destination: ProjectWorkspace,
) -> None:
    source_root = source.root.resolve(strict=True)
    destination_root = destination.root.resolve(strict=True)
    if source_root == destination_root:
        raise ImportedSnapshotError(
            "Imported snapshots can only be copied between different workspaces."
        )
    if _contains_path(source_root, destination_root) or _contains_path(
        destination_root, source_root
    ):
        raise ImportedSnapshotError(
            "Source and destination workspaces cannot contain one another."
        )
    try:
        source_project = source.load()
        destination_project = destination.load()
    except Exception as exc:
        raise ImportedSnapshotError(
            "Could not verify the source and destination workspace projects."
        ) from exc
    if source_project.project_id != project.project_id:
        raise ImportedSnapshotError(
            "The source workspace belongs to a different Studio project."
        )
    if destination_project.project_id != project.project_id:
        raise ImportedSnapshotError(
            "The destination workspace belongs to a different Studio project."
        )
    expected = project.extensions.get(IMPORT_EXTENSION_KEY)
    if source_project.extensions.get(IMPORT_EXTENSION_KEY) != expected:
        raise ModSourceChangedError(
            "Existing-mod import metadata changed in the source workspace."
        )
    if destination_project.extensions.get(IMPORT_EXTENSION_KEY) != expected:
        raise ImportedSnapshotError(
            "Destination workspace import metadata does not match the project."
        )


def _contains_path(parent: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _verified_snapshot_root(
    workspace: ProjectWorkspace, snapshot_root: Path
) -> Path:
    try:
        relative = snapshot_root.relative_to(workspace.root)
    except ValueError as exc:
        raise ImportedSnapshotError(
            "Imported snapshot root escapes its workspace."
        ) from exc
    cursor = workspace.root
    if _is_link_or_reparse(cursor):
        raise ImportedSnapshotError(f"Workspace root is a link or junction: {cursor}")
    for part in relative.parts:
        cursor = cursor / part
        if _is_link_or_reparse(cursor):
            raise ImportedSnapshotError(
                f"Imported snapshot contains a linked directory: {cursor}"
            )
    try:
        resolved = snapshot_root.resolve(strict=True)
        resolved.relative_to(workspace.root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ImportedSnapshotError(
            f"Imported snapshot root is missing or unsafe: {snapshot_root}"
        ) from exc
    if not snapshot_root.is_dir():
        raise ImportedSnapshotError(
            f"Imported snapshot root is not a directory: {snapshot_root}"
        )
    return resolved


def _verified_snapshot_file(
    workspace: ProjectWorkspace,
    snapshot_root: Path,
    expected_snapshot_root: Path,
    relative_path: str,
) -> Path:
    current_root = _verified_snapshot_root(workspace, snapshot_root)
    if current_root != expected_snapshot_root:
        raise ModSourceChangedError(
            "Imported snapshot root changed while it was being copied."
        )
    normalized = _normalize_relative_path(relative_path, context="snapshot source")
    candidate = snapshot_root.joinpath(*PurePosixPath(normalized).parts)
    cursor = snapshot_root
    for part in PurePosixPath(normalized).parts:
        cursor = cursor / part
        if _is_link_or_reparse(cursor):
            raise ImportedSnapshotError(
                f"Imported snapshot contains a linked path: {cursor}"
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(expected_snapshot_root)
    except (OSError, ValueError) as exc:
        raise ImportedSnapshotError(
            f"Imported snapshot file escapes its root: {relative_path}"
        ) from exc
    if not resolved.is_file():
        raise ImportedSnapshotError(
            f"Imported snapshot entry is not a regular file: {relative_path}"
        )
    return resolved


def _verify_snapshot_inventory(
    records: tuple[_SnapshotRecord, ...],
    inventory: Mapping[str, tuple[int, str]],
    *,
    context: str,
) -> None:
    expected = {record.relative_path: (record.size, record.sha256) for record in records}
    if set(inventory) != set(expected):
        missing = sorted(set(expected) - set(inventory), key=str.casefold)
        extra = sorted(set(inventory) - set(expected), key=str.casefold)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing[:3]))
        if extra:
            detail.append("unexpected " + ", ".join(extra[:3]))
        raise ModSourceChangedError(
            f"{context.capitalize()} does not match its complete manifest"
            + (": " + "; ".join(detail) if detail else ".")
        )
    for relative, expected_value in expected.items():
        if inventory[relative] != expected_value:
            raise ModSourceChangedError(
                f"{context.capitalize()} bytes do not match the manifest: {relative}"
            )


def _copy_verified(source: Path, target: Path, record: ModFileRecord) -> None:
    _copy_expected_bytes(
        source,
        target,
        relative_path=record.relative_path,
        expected_size=record.size,
        expected_sha256=record.sha256,
    )


def _copy_expected_bytes(
    source: Path,
    target: Path,
    *,
    relative_path: str,
    expected_size: int,
    expected_sha256: str,
) -> None:
    if _is_link_or_reparse(source):
        raise UnsafeModSourceError(f"Source became a link during import: {source}")
    before = source.stat()
    if before.st_size != expected_size or _sha256(source) != expected_sha256:
        raise ModSourceChangedError(
            f"Source changed after inspection: {relative_path}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if _is_link_or_reparse(target.parent) or target.exists():
        raise UnsafeModSourceError(f"Unsafe or occupied snapshot target: {target}")
    handle = tempfile.NamedTemporaryFile(
        mode="w+b",
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    digest = hashlib.sha256()
    copied = 0
    try:
        with handle, source.open("rb") as source_handle:
            while chunk := source_handle.read(1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if copied != expected_size or digest.hexdigest() != expected_sha256:
            raise ModSourceChangedError(
                f"Source changed while it was copied: {relative_path}"
            )
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _file_kind(relative_path: str) -> str:
    suffix = Path(relative_path).suffix.casefold()
    return {
        ".lua": "lua",
        ".dll": "dll",
        ".dds": "dds",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".fxsxml": "unit_art",
        ".gr2": "unit_art",
        ".wav": "audio",
        ".mp3": "audio",
    }.get(suffix, "unknown")


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _positive_int(value: object, *, fallback: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)
