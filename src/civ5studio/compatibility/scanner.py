"""Conservative, read-only inspection of an installed Civ V MODS folder.

The scanner reports evidence.  It never enables, disables, edits, moves, or
deletes mods and it does not infer compatibility from a folder name.  Mentions
of IGE, EUI, or YnAEMP are surfaced only when those names occur in parsed
``.modinfo`` metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import re
import stat
from typing import Iterable
import xml.etree.ElementTree as ET

from civ5studio.domain.validation import is_portable_relative_path


MAX_MODINFO_BYTES = 2 * 1024 * 1024
MAX_DATABASE_SOURCE_BYTES = 32 * 1024 * 1024
_DATABASE_SUFFIXES = {".xml", ".sql"}
_PATH_ACTION_TAGS = {
    "addindll",
    "custom",
    "file",
    "ingameuiaddin",
    "postprocess",
    "updateaudio",
    "updatedatabase",
    "updatetext",
}
_TYPE_VALUE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,255}$")
_QUOTED_TYPE_RE = re.compile(
    r"(?P<quote>['\"])(?P<value>[A-Za-z][A-Za-z0-9_]{2,255})(?P=quote)"
)
_INSERT_RE = re.compile(
    r"\bINSERT\s+(?:OR\s+(?:ABORT|FAIL|IGNORE|REPLACE|ROLLBACK)\s+)?"
    r"INTO\s+(?P<table>(?:\[[^\]]+\]|`[^`]+`|\"[^\"]+\"|[A-Za-z_]\w*))\s*"
    r"\((?P<columns>.*?)\)\s*VALUES\s*(?P<values>.*?);",
    re.IGNORECASE | re.DOTALL,
)


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class ScanIssue:
    severity: str
    code: str
    message: str
    source: str = ""
    mod_name: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "mod_name": self.mod_name,
        }


@dataclass(frozen=True, slots=True)
class ModRelation:
    kind: str
    mod_id: str
    minimum_version: int | None
    maximum_version: int | None
    title: str = ""


@dataclass(frozen=True, slots=True)
class TypeDeclaration:
    identifier: str
    table: str
    confidence: Confidence
    mod_id: str
    mod_name: str
    modinfo_path: Path
    source_file: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class InstalledMod:
    folder: Path
    modinfo_path: Path
    mod_id: str
    name: str
    version: int | None
    declared_files: tuple[str, ...] = ()
    action_files: tuple[str, ...] = ()
    relations: tuple[ModRelation, ...] = ()
    type_declarations: tuple[TypeDeclaration, ...] = ()


@dataclass(frozen=True, slots=True)
class TypeConflict:
    identifier: str
    confidence: Confidence
    declarations: tuple[TypeDeclaration, ...]


@dataclass(frozen=True, slots=True)
class EcosystemPresence:
    product: str
    mod_id: str
    mod_name: str
    evidence_field: str
    evidence_value: str


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    mods_root: Path
    mods: tuple[InstalledMod, ...]
    issues: tuple[ScanIssue, ...]
    duplicate_mod_ids: dict[str, tuple[InstalledMod, ...]] = field(default_factory=dict)
    type_conflicts: tuple[TypeConflict, ...] = ()
    ecosystem_presence: tuple[EcosystemPresence, ...] = ()

    @property
    def errors(self) -> tuple[ScanIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "ERROR")

    @property
    def warnings(self) -> tuple[ScanIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "WARNING")


def scan_installed_mods(mods_root: str | Path) -> CompatibilityReport:
    """Inspect immediate Civ V mod folders without changing the MODS tree."""

    unresolved_root = Path(mods_root).expanduser()
    issues: list[ScanIssue] = []
    mods: list[InstalledMod] = []
    if _path_contains_link_or_reparse(unresolved_root):
        root = unresolved_root.absolute()
        issues.append(
            ScanIssue(
                "ERROR",
                "UNSAFE_MODS_ROOT_LINK",
                "The configured Civ V MODS directory cannot be a link or junction.",
                str(root),
            )
        )
        return CompatibilityReport(root, (), tuple(issues))
    root = unresolved_root.resolve()
    if not root.is_dir():
        issues.append(
            ScanIssue(
                "ERROR",
                "MODS_ROOT_MISSING",
                "The configured Civ V MODS directory does not exist or is not a directory.",
                str(root),
            )
        )
        return CompatibilityReport(root, (), tuple(issues))

    for folder in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
        if folder.name.startswith("."):
            continue
        if _is_link_or_reparse(folder):
            issues.append(
                ScanIssue(
                    "ERROR",
                    "UNSAFE_MOD_FOLDER_LINK",
                    "Link or junction mod folders are not inspected.",
                    str(folder),
                )
            )
            continue
        if not folder.is_dir():
            continue
        modinfos = sorted(folder.glob("*.modinfo"), key=lambda value: value.name.casefold())
        if not modinfos:
            issues.append(
                ScanIssue(
                    "WARNING",
                    "MODINFO_MISSING",
                    "Installed-mod folder has no top-level .modinfo file.",
                    str(folder),
                    folder.name,
                )
            )
            continue
        if len(modinfos) > 1:
            issues.append(
                ScanIssue(
                    "ERROR",
                    "MULTIPLE_MODINFO_FILES",
                    "Installed-mod folder has multiple top-level .modinfo files; each is scanned independently.",
                    str(folder),
                    folder.name,
                )
            )
        for modinfo in modinfos:
            parsed = _parse_mod(folder, modinfo, issues)
            if parsed is not None:
                mods.append(parsed)

    duplicate_ids = _duplicate_mod_ids(mods)
    for mod_id, matches in duplicate_ids.items():
        issues.append(
            ScanIssue(
                "ERROR",
                "DUPLICATE_MOD_ID",
                f"Mod ID {mod_id!r} is declared by {len(matches)} installed mods: "
                + ", ".join(item.name for item in matches),
                mod_id,
            )
        )
    _validate_relations(mods, issues)
    conflicts = _find_type_conflicts(mods)
    for conflict in conflicts:
        issues.append(
            ScanIssue(
                "WARNING",
                "CUSTOM_TYPE_CONFLICT",
                f"{conflict.identifier} is declared by multiple installed mods "
                f"({conflict.confidence.value} confidence): "
                + ", ".join(sorted({item.mod_name for item in conflict.declarations})),
                conflict.identifier,
            )
        )
    ecosystems = _discover_ecosystems(mods)
    issues.sort(key=lambda item: (item.severity != "ERROR", item.code, item.source))
    return CompatibilityReport(
        root,
        tuple(mods),
        tuple(issues),
        duplicate_ids,
        conflicts,
        ecosystems,
    )


def _parse_mod(
    folder: Path, modinfo: Path, issues: list[ScanIssue]
) -> InstalledMod | None:
    if _is_link_or_reparse(modinfo) or not _is_within(folder, modinfo):
        issues.append(
            ScanIssue(
                "ERROR",
                "UNSAFE_MODINFO_PATH",
                "The .modinfo file is a link or resolves outside its mod folder.",
                str(modinfo),
                folder.name,
            )
        )
        return None
    try:
        size = modinfo.stat().st_size
    except OSError as exc:
        issues.append(ScanIssue("ERROR", "MODINFO_UNREADABLE", str(exc), str(modinfo), folder.name))
        return None
    if size > MAX_MODINFO_BYTES:
        issues.append(
            ScanIssue(
                "ERROR",
                "MODINFO_TOO_LARGE",
                f"The .modinfo file exceeds the {MAX_MODINFO_BYTES}-byte safety limit.",
                str(modinfo),
                folder.name,
            )
        )
        return None
    try:
        document = ET.fromstring(modinfo.read_bytes())
    except (OSError, ET.ParseError) as exc:
        issues.append(ScanIssue("ERROR", "MODINFO_INVALID_XML", str(exc), str(modinfo), folder.name))
        return None
    if _local_name(document.tag).casefold() != "mod":
        issues.append(
            ScanIssue("ERROR", "MODINFO_INVALID_ROOT", "The .modinfo root element is not Mod.", str(modinfo), folder.name)
        )
        return None

    mod_id = document.attrib.get("id", "").strip()
    raw_version = document.attrib.get("version", "").strip()
    properties = _first_child(document, "Properties")
    name = _child_text(properties, "Name") if properties is not None else ""
    name = name.strip() or folder.name
    if not mod_id:
        issues.append(ScanIssue("ERROR", "MOD_ID_MISSING", "The .modinfo Mod element has no id.", str(modinfo), name))
    version = _parse_nonnegative_int(raw_version)
    if version is None:
        issues.append(
            ScanIssue(
                "ERROR",
                "MOD_VERSION_INVALID",
                f"The .modinfo version is not a non-negative integer: {raw_version!r}.",
                str(modinfo),
                name,
            )
        )

    declared = _file_entries(document)
    actions = _action_file_entries(document)
    relations = _relations(document, name, modinfo, issues)
    declared_set = {item.replace("\\", "/").casefold() for item in declared}
    for action in actions:
        if action.replace("\\", "/").casefold() not in declared_set:
            issues.append(
                ScanIssue(
                    "WARNING",
                    "ACTION_FILE_UNDECLARED",
                    f"Action references a file not listed under Files: {action}",
                    str(modinfo),
                    name,
                )
            )

    valid_database_files: list[tuple[str, Path]] = []
    for relative in _ordered_unique((*declared, *actions)):
        candidate = _validate_declared_file(folder, relative, name, issues)
        if candidate is not None and candidate.suffix.casefold() in _DATABASE_SUFFIXES:
            valid_database_files.append((relative, candidate))

    declarations: list[TypeDeclaration] = []
    for relative, source in valid_database_files:
        try:
            source_size = source.stat().st_size
        except OSError as exc:
            issues.append(ScanIssue("ERROR", "MOD_FILE_UNREADABLE", str(exc), str(source), name))
            continue
        if source_size > MAX_DATABASE_SOURCE_BYTES:
            issues.append(
                ScanIssue(
                    "WARNING",
                    "DATABASE_SOURCE_TOO_LARGE",
                    f"Database source was not type-scanned because it exceeds {MAX_DATABASE_SOURCE_BYTES} bytes.",
                    str(source),
                    name,
                )
            )
            continue
        try:
            content = source.read_text(encoding="utf-8-sig", errors="replace")
            if source.suffix.casefold() == ".xml":
                raw = _extract_xml_types(content)
            else:
                raw = _extract_sql_types(content)
        except (OSError, ET.ParseError) as exc:
            issues.append(
                ScanIssue(
                    "WARNING",
                    "DATABASE_SOURCE_UNREADABLE",
                    f"Could not inspect database type declarations: {exc}",
                    str(source),
                    name,
                )
            )
            continue
        declarations.extend(
            TypeDeclaration(
                identifier,
                table,
                confidence,
                mod_id,
                name,
                modinfo,
                relative,
                line,
            )
            for identifier, table, confidence, line in raw
        )

    return InstalledMod(
        folder,
        modinfo,
        mod_id,
        name,
        version,
        tuple(declared),
        tuple(actions),
        tuple(relations),
        tuple(_deduplicate_declarations(declarations)),
    )


def _validate_declared_file(
    folder: Path, relative: str, mod_name: str, issues: list[ScanIssue]
) -> Path | None:
    normalized = relative.strip().replace("\\", "/")
    if not is_portable_relative_path(normalized):
        issues.append(
            ScanIssue(
                "ERROR",
                "UNSAFE_MOD_FILE_PATH",
                f"Declared file path is absolute or escapes the mod folder: {relative!r}.",
                str(folder),
                mod_name,
            )
        )
        return None
    candidate = folder.joinpath(*normalized.split("/"))
    if _is_link_or_reparse(candidate) or not _is_within(folder, candidate):
        issues.append(
            ScanIssue(
                "ERROR",
                "UNSAFE_MOD_FILE_LINK",
                f"Declared file is a link or resolves outside the mod folder: {relative!r}.",
                str(candidate),
                mod_name,
            )
        )
        return None
    if not candidate.exists():
        issues.append(
            ScanIssue(
                "ERROR",
                "DECLARED_MOD_FILE_MISSING",
                f"Declared mod file is missing: {relative}",
                str(candidate),
                mod_name,
            )
        )
        return None
    if not candidate.is_file():
        issues.append(
            ScanIssue(
                "ERROR",
                "DECLARED_MOD_FILE_NOT_FILE",
                f"Declared mod path is not a regular file: {relative}",
                str(candidate),
                mod_name,
            )
        )
        return None
    return candidate.resolve()


def _file_entries(document: ET.Element) -> list[str]:
    files = _first_child(document, "Files")
    if files is None:
        return []
    return _ordered_unique(
        item.text.strip()
        for item in files
        if _local_name(item.tag).casefold() == "file" and item.text and item.text.strip()
    )


def _action_file_entries(document: ET.Element) -> list[str]:
    actions = _first_child(document, "Actions")
    entry_points = _first_child(document, "EntryPoints")
    values: list[str] = []
    for root in (actions, entry_points):
        if root is None:
            continue
        for item in root.iter():
            if (
                _local_name(item.tag).casefold() in _PATH_ACTION_TAGS
                and len(item) == 0
                and item.text
                and item.text.strip()
            ):
                values.append(item.text.strip())
    return _ordered_unique(values)


def _relations(
    document: ET.Element,
    mod_name: str,
    modinfo: Path,
    issues: list[ScanIssue],
) -> list[ModRelation]:
    result: list[ModRelation] = []
    for container_name in ("Dependencies", "References"):
        container = _first_child(document, container_name)
        if container is None:
            continue
        kind = container_name[:-3].casefold() if container_name.endswith("ies") else container_name[:-1].casefold()
        # Keep user-facing terms conventional rather than relying on the
        # English plural transform above.
        kind = "dependency" if container_name == "Dependencies" else "reference"
        for item in container:
            if _local_name(item.tag).casefold() != "mod":
                continue
            relation_id = item.attrib.get("id", "").strip()
            minimum = _optional_version(item.attrib.get("minversion"), kind, mod_name, modinfo, issues)
            maximum = _optional_version(item.attrib.get("maxversion"), kind, mod_name, modinfo, issues)
            if not relation_id:
                issues.append(
                    ScanIssue(
                        "ERROR",
                        "DECLARED_RELATION_ID_MISSING",
                        f"Declared {kind} has no mod id.",
                        str(modinfo),
                        mod_name,
                    )
                )
            result.append(
                ModRelation(kind, relation_id, minimum, maximum, item.attrib.get("title", "").strip())
            )
    return result


def _optional_version(
    raw: str | None,
    kind: str,
    mod_name: str,
    modinfo: Path,
    issues: list[ScanIssue],
) -> int | None:
    if raw is None or not raw.strip():
        return None
    value = _parse_nonnegative_int(raw.strip())
    if value is None:
        issues.append(
            ScanIssue(
                "ERROR",
                "DECLARED_RELATION_VERSION_INVALID",
                f"Declared {kind} contains an invalid version bound: {raw!r}.",
                str(modinfo),
                mod_name,
            )
        )
    return value


def _validate_relations(mods: list[InstalledMod], issues: list[ScanIssue]) -> None:
    by_id: dict[str, list[InstalledMod]] = {}
    for mod in mods:
        if mod.mod_id:
            by_id.setdefault(mod.mod_id.casefold(), []).append(mod)
    for owner in mods:
        for relation in owner.relations:
            if not relation.mod_id:
                continue
            candidates = by_id.get(relation.mod_id.casefold(), [])
            if not candidates:
                issues.append(
                    ScanIssue(
                        "WARNING",
                        f"DECLARED_{relation.kind.upper()}_MISSING",
                        f"{owner.name} declares {relation.kind} {relation.title or relation.mod_id!r}, but no installed .modinfo has that id.",
                        str(owner.modinfo_path),
                        owner.name,
                    )
                )
                continue
            versions = [item.version for item in candidates if item.version is not None]
            if not versions:
                issues.append(
                    ScanIssue(
                        "WARNING",
                        "DECLARED_RELATION_VERSION_UNVERIFIABLE",
                        f"Installed candidates for {relation.title or relation.mod_id!r} have no valid version.",
                        str(owner.modinfo_path),
                        owner.name,
                    )
                )
                continue
            if not any(_version_matches(value, relation) for value in versions):
                bounds = _format_bounds(relation)
                issues.append(
                    ScanIssue(
                        "WARNING",
                        "DECLARED_RELATION_VERSION_MISMATCH",
                        f"{owner.name} requires {relation.title or relation.mod_id!r} {bounds}; installed version(s): "
                        + ", ".join(str(value) for value in sorted(set(versions))),
                        str(owner.modinfo_path),
                        owner.name,
                    )
                )


def _version_matches(value: int, relation: ModRelation) -> bool:
    return not (
        relation.minimum_version is not None and value < relation.minimum_version
    ) and not (
        relation.maximum_version is not None and value > relation.maximum_version
    )


def _format_bounds(relation: ModRelation) -> str:
    if relation.minimum_version is not None and relation.maximum_version is not None:
        return f"versions {relation.minimum_version} through {relation.maximum_version}"
    if relation.minimum_version is not None:
        return f"version {relation.minimum_version} or later"
    if relation.maximum_version is not None:
        return f"version {relation.maximum_version} or earlier"
    return "at any version"


def _extract_xml_types(content: str) -> list[tuple[str, str, Confidence, int | None]]:
    document = ET.fromstring(content)
    values: list[tuple[str, str, Confidence, int | None]] = []
    for table in document:
        table_name = _local_name(table.tag)
        for row in table:
            if _local_name(row.tag).casefold() != "row":
                continue
            identifier = ""
            for key, value in row.attrib.items():
                if _local_name(key).casefold() == "type":
                    identifier = value.strip()
                    break
            if not identifier:
                type_element = _first_child(row, "Type")
                if type_element is not None and type_element.text:
                    identifier = type_element.text.strip()
            if _is_type_value(identifier):
                values.append((identifier, table_name, Confidence.HIGH, None))
    return values


def _extract_sql_types(content: str) -> list[tuple[str, str, Confidence, int | None]]:
    without_comments = _strip_sql_comments(content)
    values: list[tuple[str, str, Confidence, int | None]] = []
    high_values: set[str] = set()
    for match in _INSERT_RE.finditer(without_comments):
        table = _unquote_identifier(match.group("table"))
        columns = [_unquote_identifier(value.strip()) for value in _split_csv(match.group("columns"))]
        try:
            type_index = next(index for index, value in enumerate(columns) if value.casefold() == "type")
        except StopIteration:
            continue
        for group in _value_groups(match.group("values")):
            row_values = _split_csv(group)
            if type_index >= len(row_values):
                continue
            identifier = _sql_literal(row_values[type_index])
            if _is_type_value(identifier):
                line = without_comments.count("\n", 0, match.start()) + 1
                values.append((identifier, table, Confidence.HIGH, line))
                high_values.add(identifier.casefold())
    # Less structured SQL (for example INSERT ... SELECT) is still useful as
    # collision evidence, but it must remain visibly low confidence.
    for match in _QUOTED_TYPE_RE.finditer(without_comments):
        identifier = match.group("value")
        if _looks_custom_type(identifier) and identifier.casefold() not in high_values:
            line = without_comments.count("\n", 0, match.start()) + 1
            values.append((identifier, "UNKNOWN", Confidence.LOW, line))
    return values


def _strip_sql_comments(content: str) -> str:
    # Preserve line counts for evidence.  This intentionally handles ordinary
    # Civ V SQL, not every possible SQLite string/comment edge case.
    content = re.sub(r"/\*.*?\*/", lambda match: "\n" * match.group(0).count("\n"), content, flags=re.DOTALL)
    return re.sub(r"--[^\r\n]*", "", content)


def _value_groups(content: str) -> list[str]:
    groups: list[str] = []
    depth = 0
    start: int | None = None
    quote = ""
    index = 0
    while index < len(content):
        character = content[index]
        if quote:
            if character == quote:
                if index + 1 < len(content) and content[index + 1] == quote:
                    index += 1
                else:
                    quote = ""
        elif character in {"'", '"'}:
            quote = character
        elif character == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif character == ")" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(content[start:index])
                start = None
        index += 1
    return groups


def _split_csv(content: str) -> list[str]:
    values: list[str] = []
    start = 0
    depth = 0
    quote = ""
    index = 0
    while index < len(content):
        character = content[index]
        if quote:
            if character == quote:
                if index + 1 < len(content) and content[index + 1] == quote:
                    index += 1
                else:
                    quote = ""
        elif character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            values.append(content[start:index].strip())
            start = index + 1
        index += 1
    values.append(content[start:].strip())
    return values


def _sql_literal(value: str) -> str:
    candidate = value.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        return candidate[1:-1].replace(candidate[0] * 2, candidate[0]).strip()
    return ""


def _find_type_conflicts(mods: list[InstalledMod]) -> tuple[TypeConflict, ...]:
    by_identifier: dict[str, list[TypeDeclaration]] = {}
    for mod in mods:
        for declaration in mod.type_declarations:
            by_identifier.setdefault(declaration.identifier.casefold(), []).append(declaration)
    conflicts: list[TypeConflict] = []
    for declarations in by_identifier.values():
        owners = {str(item.modinfo_path).casefold() for item in declarations}
        if len(owners) < 2:
            continue
        tables = {item.table.casefold() for item in declarations if item.table != "UNKNOWN"}
        confidences = {item.confidence for item in declarations}
        if confidences == {Confidence.HIGH} and len(tables) == 1:
            confidence = Confidence.HIGH
        elif Confidence.LOW not in confidences and tables:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW
        conflicts.append(
            TypeConflict(
                declarations[0].identifier,
                confidence,
                tuple(sorted(declarations, key=lambda item: (item.mod_name.casefold(), item.source_file.casefold()))),
            )
        )
    return tuple(sorted(conflicts, key=lambda item: item.identifier.casefold()))


def _duplicate_mod_ids(mods: list[InstalledMod]) -> dict[str, tuple[InstalledMod, ...]]:
    grouped: dict[str, list[InstalledMod]] = {}
    display: dict[str, str] = {}
    for mod in mods:
        if mod.mod_id:
            key = mod.mod_id.casefold()
            grouped.setdefault(key, []).append(mod)
            display.setdefault(key, mod.mod_id)
    return {
        display[key]: tuple(values)
        for key, values in grouped.items()
        if len(values) > 1
    }


def _discover_ecosystems(mods: list[InstalledMod]) -> tuple[EcosystemPresence, ...]:
    patterns = (
        ("IGE", re.compile(r"(?:\bIGE\b|\bIngame\s+Editor\b)", re.IGNORECASE)),
        ("EUI", re.compile(r"(?:\bEUI\b|\bEnhanced\s+User\s+Interface\b)", re.IGNORECASE)),
        ("YnAEMP", re.compile(r"(?:\bYnAEMP\b|Yet\s*\(not\)\s*Another\s+Earth\s+Maps\s+Pack)", re.IGNORECASE)),
    )
    values: list[EcosystemPresence] = []
    for mod in mods:
        for product, pattern in patterns:
            if pattern.search(mod.name):
                values.append(EcosystemPresence(product, mod.mod_id, mod.name, "Properties/Name", mod.name))
    return tuple(values)


def _deduplicate_declarations(values: Iterable[TypeDeclaration]) -> list[TypeDeclaration]:
    result: list[TypeDeclaration] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in values:
        key = (
            item.identifier.casefold(),
            item.table.casefold(),
            item.source_file.casefold(),
            item.confidence.value,
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = raw.strip()
        key = value.replace("\\", "/").casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _first_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    expected = name.casefold()
    return next(
        (child for child in element if _local_name(child.tag).casefold() == expected),
        None,
    )


def _child_text(element: ET.Element, name: str) -> str:
    child = _first_child(element, name)
    return child.text if child is not None and child.text else ""


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _parse_nonnegative_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _is_type_value(value: str) -> bool:
    return bool(_TYPE_VALUE_RE.fullmatch(value))


def _looks_custom_type(value: str) -> bool:
    return _is_type_value(value) and "_" in value and value.upper() == value


def _unquote_identifier(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and (
        (value[0], value[-1]) in {("[", "]"), ('"', '"'), ("`", "`")}
    ):
        return value[1:-1]
    return value


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _path_contains_link_or_reparse(path: Path) -> bool:
    absolute = path.absolute()
    return any(
        _is_link_or_reparse(component)
        for component in reversed((absolute, *absolute.parents))
    )
