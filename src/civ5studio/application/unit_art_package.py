"""Read-only validation for attachable Civ V FXSXML/GR2 unit-art packages."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
import stat
import xml.etree.ElementTree as ET

from civ5studio.domain.validation import is_portable_relative_path


GR2_MAGIC = bytes.fromhex("29 DE 6C C0 BA A4 53 2B 25 F5 B7 A5 F6 66 E2 EE")
ALLOWED_SUFFIXES = frozenset({".fxsxml", ".gr2", ".dds"})
_REFERENCE = re.compile(
    rb"([A-Za-z0-9_ ./\\()'\-]{1,240}\.(?:dds|gr2|fxsxml))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class UnitArtIssue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class UnitArtPackageReport:
    package_root: Path
    entry_fxsxml: str
    files: tuple[str, ...]
    sha256: dict[str, str]
    local_references: tuple[str, ...]
    engine_references: tuple[str, ...]
    issues: tuple[UnitArtIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)


def inspect_unit_art_package(
    project_root: str | Path,
    package_relative: str,
    entry_fxsxml: str,
) -> UnitArtPackageReport:
    """Inspect a project-owned package without modifying or executing it.

    Local FXSXML/GR2/DDS references must resolve case-insensitively inside the
    package. References beginning with ``Assets/`` are recorded as external
    Firaxis engine dependencies because the base-game package archives are not
    copied into a generated mod.
    """

    issues: list[UnitArtIssue] = []
    unresolved_root = Path(project_root).expanduser()
    if _path_contains_link_or_reparse(unresolved_root):
        return _invalid(
            unresolved_root.absolute(),
            entry_fxsxml,
            "unit-art.project-root-link",
            "Unit-art project root cannot contain a link or junction.",
        )
    root = unresolved_root.resolve()
    if not is_portable_relative_path(package_relative):
        return _invalid(root, entry_fxsxml, "unit-art.package-path", package_relative)
    unresolved_package = root.joinpath(
        *PurePosixPath(package_relative.replace("\\", "/")).parts
    )
    if _path_contains_link_or_reparse(unresolved_package):
        return _invalid(
            unresolved_package,
            entry_fxsxml,
            "unit-art.package-link",
            "Unit-art package cannot contain a link or junction.",
        )
    package = unresolved_package.resolve(strict=False)
    if (
        not _is_within(root, package)
        or not package.is_dir()
        or _path_contains_link_or_reparse(package)
    ):
        return _invalid(
            package,
            entry_fxsxml,
            "unit-art.package-missing",
            "Unit-art package must be a real project-owned directory.",
        )
    if not is_portable_relative_path(entry_fxsxml) or not entry_fxsxml.lower().endswith(
        ".fxsxml"
    ):
        return _invalid(
            package,
            entry_fxsxml,
            "unit-art.entry-path",
            "Entry point must be one portable .fxsxml path.",
        )

    files: list[Path] = []
    index: dict[str, Path] = {}
    for candidate in _package_entries(package, issues):
        if _is_link_or_reparse(candidate) or not _is_within(package, candidate):
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.symlink",
                    str(candidate),
                    "Links and junctions are not supported in unit-art packages.",
                )
            )
            continue
        relative = candidate.relative_to(package).as_posix()
        if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.file-type",
                    relative,
                    "Only FXSXML, GR2, and DDS files may be imported as unit art.",
                )
            )
            continue
        folded = relative.casefold()
        if folded in index:
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.case-collision",
                    relative,
                    "Package paths collide when read by a case-insensitive Windows filesystem.",
                )
            )
        index[folded] = candidate
        files.append(candidate)

    entry = index.get(PurePosixPath(entry_fxsxml).as_posix().casefold())
    if entry is None:
        issues.append(
            UnitArtIssue(
                "ERROR",
                "unit-art.entry-missing",
                entry_fxsxml,
                "The selected FXSXML entry is not present in the package.",
            )
        )

    local_refs: set[str] = set()
    engine_refs: set[str] = set()
    if entry is not None:
        try:
            tree = ET.parse(entry)
        except (ET.ParseError, OSError) as exc:
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.fxsxml-parse",
                    entry_fxsxml,
                    f"FXSXML parse failed: {exc}",
                )
            )
        else:
            for element in tree.iter():
                values = [*element.attrib.values()]
                if element.text and element.text.strip():
                    values.append(element.text.strip())
                for value in values:
                    if Path(value).suffix.lower() in ALLOWED_SUFFIXES:
                        _classify_reference(value, local_refs, engine_refs)

    for candidate in files:
        relative = candidate.relative_to(package).as_posix()
        suffix = candidate.suffix.lower()
        if suffix == ".gr2":
            data = candidate.read_bytes()
            if len(data) < len(GR2_MAGIC) or data[: len(GR2_MAGIC)] != GR2_MAGIC:
                issues.append(
                    UnitArtIssue(
                        "ERROR",
                        "unit-art.gr2-header",
                        relative,
                        "GR2 file lacks the verified Civ V Granny2 header.",
                    )
                )
            for match in _REFERENCE.findall(data):
                value = match.decode("ascii", errors="ignore").strip("\x00 ")
                if value.lower().endswith(".dds"):
                    _classify_reference(value, local_refs, engine_refs)
        elif suffix == ".dds":
            data = candidate.read_bytes()[:128]
            if len(data) < 128 or data[:4] != b"DDS ":
                issues.append(
                    UnitArtIssue(
                        "ERROR",
                        "unit-art.dds-header",
                        relative,
                        "Unit texture is not a valid legacy DDS file.",
                    )
                )

    for reference in sorted(local_refs):
        normalized = PurePosixPath(reference.replace("\\", "/")).as_posix()
        if not is_portable_relative_path(normalized):
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.reference-path",
                    reference,
                    "Unit-art reference is not a portable relative path.",
                )
            )
            continue
        direct = normalized.casefold()
        basename_matches = [
            path
            for folded, path in index.items()
            if PurePosixPath(folded).name == PurePosixPath(direct).name
        ]
        if direct not in index and len(basename_matches) != 1:
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.reference-missing",
                    reference,
                    "Referenced unit-art file is missing or ambiguous in the package.",
                )
            )

    if not any(path.suffix.lower() == ".gr2" for path in files):
        issues.append(
            UnitArtIssue(
                "ERROR",
                "unit-art.model-missing",
                entry_fxsxml,
                "A custom unit-art package must contain at least one GR2 model.",
            )
        )
    if not any(path.suffix.lower() == ".dds" for path in files):
        issues.append(
            UnitArtIssue(
                "WARNING",
                "unit-art.texture-missing",
                entry_fxsxml,
                "No custom DDS texture is packaged; verify that engine textures are intentional.",
            )
        )
    issues.append(
        UnitArtIssue(
            "WARNING",
            "unit-art.runtime-required",
            entry_fxsxml,
            "Static checks cannot prove GR2 skeleton, animation, material, or Nexus compatibility.",
        )
    )
    relative_files = tuple(path.relative_to(package).as_posix() for path in files)
    hashes = {relative: _digest(package / relative) for relative in relative_files}
    return UnitArtPackageReport(
        package,
        PurePosixPath(entry_fxsxml).as_posix(),
        relative_files,
        hashes,
        tuple(sorted(local_refs)),
        tuple(sorted(engine_refs)),
        tuple(issues),
    )


def _classify_reference(
    value: str, local: set[str], engine: set[str]
) -> None:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.casefold().startswith("assets/"):
        engine.add(normalized)
    else:
        local.add(normalized)


def _invalid(
    root: Path, entry: str, code: str, message: str
) -> UnitArtPackageReport:
    return UnitArtPackageReport(
        root,
        entry,
        (),
        {},
        (),
        (),
        (UnitArtIssue("ERROR", code, str(root), message),),
    )


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def _package_entries(
    package: Path, issues: list[UnitArtIssue]
) -> tuple[Path, ...]:
    files: list[Path] = []
    pending = [package]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            issues.append(
                UnitArtIssue(
                    "ERROR",
                    "unit-art.package-read",
                    str(directory),
                    f"Unit-art package directory cannot be inspected: {exc}",
                )
            )
            continue
        for entry in entries:
            candidate = Path(entry.path)
            if _is_link_or_reparse(candidate):
                issues.append(
                    UnitArtIssue(
                        "ERROR",
                        "unit-art.symlink",
                        str(candidate),
                        "Links and junctions are not supported in unit-art packages.",
                    )
                )
                continue
            if not _is_within(package, candidate):
                issues.append(
                    UnitArtIssue(
                        "ERROR",
                        "unit-art.path-escape",
                        str(candidate),
                        "Unit-art package entry resolves outside its package root.",
                    )
                )
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False):
                    files.append(candidate)
            except OSError as exc:
                issues.append(
                    UnitArtIssue(
                        "ERROR",
                        "unit-art.package-read",
                        str(candidate),
                        f"Unit-art package entry cannot be inspected: {exc}",
                    )
                )
    return tuple(sorted(files, key=lambda path: path.relative_to(package).as_posix()))


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


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()
