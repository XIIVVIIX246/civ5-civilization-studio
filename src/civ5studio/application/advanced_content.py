"""Portable advanced-content settings and project-owned source handling.

The core project format intentionally keeps experimental or independently
versioned desktop features inside one namespaced extension.  This module gives
that extension a typed boundary, validates it without Qt, and materializes
external audio/unit-art sources into a marked Civilization Studio workspace.

Nothing here launches Civilization V or claims that a GR2/audio payload works
at runtime.  Static inspection is only a prerequisite for the manual BNW gate.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from typing import Any, Mapping
import uuid
import xml.etree.ElementTree as ET

from civ5studio.domain.models import CivProject
from civ5studio.domain.validation import is_portable_relative_path

from .audio_assets import AudioAssetSpec, AudioRole, inspect_audio_source
from .localization import SUPPORTED_LOCALES
from .unit_art_package import inspect_unit_art_package


ADVANCED_EXTENSION_KEY = "advanced_content"
ADVANCED_FORMAT = "civ5studio.advanced-content"
ADVANCED_FORMAT_VERSION = 1
_TAG = re.compile(r"TXT_KEY_[A-Z0-9_]{1,220}\Z")
_UNIT_KEY = re.compile(r"[A-Z0-9_]{1,96}\Z")


@dataclass(frozen=True, slots=True)
class UnitArtAssignment:
    unit_key: str
    unit_name: str = ""
    unit_index: int = 0
    source_folder: str = ""
    fxsxml: str = ""
    scale: float = 1.0
    z_offset: float = 0.0


@dataclass(frozen=True, slots=True)
class AudioSettings:
    peace_music: str = ""
    war_music: str = ""
    dawn_of_man_speech: str = ""

    def populated(self) -> tuple[tuple[AudioRole, str], ...]:
        return tuple(
            (role, value)
            for role, value in (
                (AudioRole.PEACE_MUSIC, self.peace_music),
                (AudioRole.WAR_MUSIC, self.war_music),
                (AudioRole.DAWN_SPEECH, self.dawn_of_man_speech),
            )
            if value.strip()
        )


@dataclass(frozen=True, slots=True)
class AdvancedContent:
    localization: Mapping[str, Mapping[str, str]]
    unit_art: tuple[UnitArtAssignment, ...]
    audio: AudioSettings

    @property
    def enabled(self) -> bool:
        return bool(self.localization or self.unit_art or self.audio.populated())


@dataclass(frozen=True, slots=True)
class AdvancedIssue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceCopy:
    source_relative: str
    output_relative: str
    vfs: bool = True


def advanced_content(project: CivProject) -> AdvancedContent:
    """Read the namespaced extension with conservative type normalization."""

    raw = project.extensions.get(ADVANCED_EXTENSION_KEY, {})
    value = raw if isinstance(raw, Mapping) else {}
    localization_raw = value.get("localization", {})
    if isinstance(localization_raw, Mapping) and isinstance(
        localization_raw.get("entries", {}), Mapping
    ):
        localization_raw = localization_raw.get("entries", {})
    localization: dict[str, dict[str, str]] = {}
    if isinstance(localization_raw, Mapping):
        for locale, entries in localization_raw.items():
            if not isinstance(entries, Mapping):
                continue
            localization[str(locale)] = {
                str(tag): str(text) for tag, text in entries.items()
            }

    unit_art_raw = value.get("unit_art", {})
    if isinstance(unit_art_raw, Mapping):
        assignments_raw = unit_art_raw.get("assignments", ())
    else:
        assignments_raw = ()
    assignments: list[UnitArtAssignment] = []
    if isinstance(assignments_raw, (list, tuple)):
        for index, item in enumerate(assignments_raw):
            if not isinstance(item, Mapping):
                continue
            assignments.append(
                UnitArtAssignment(
                    unit_key=str(item.get("unit_key", "")).strip(),
                    unit_name=str(item.get("unit_name", "")).strip(),
                    unit_index=_integer(item.get("unit_index"), index),
                    source_folder=str(item.get("source_folder", "")).strip(),
                    fxsxml=str(item.get("fxsxml", "")).strip(),
                    scale=_float(item.get("scale"), 1.0),
                    z_offset=_float(item.get("z_offset"), 0.0),
                )
            )

    audio_raw = value.get("audio", {})
    audio_value = audio_raw if isinstance(audio_raw, Mapping) else {}
    audio = AudioSettings(
        peace_music=str(audio_value.get("peace_music", "")).strip(),
        war_music=str(audio_value.get("war_music", "")).strip(),
        dawn_of_man_speech=str(
            audio_value.get("dawn_of_man_speech", "")
        ).strip(),
    )
    return AdvancedContent(localization, tuple(assignments), audio)


def update_advanced_extension(
    project: CivProject, ui_data: Mapping[str, Any] | None
) -> CivProject:
    """Return a project copy containing normalized persisted advanced values.

    The desktop UI owns only the fields it currently understands.  Merge those
    fields into the existing extension instead of replacing whole subtrees so
    a project written by a newer Studio version can survive an edit in this
    version.  Assignment metadata is carried forward only when a non-empty,
    unambiguous ``unit_key`` identifies the same assignment on both sides.
    """

    result = deepcopy(project)
    data = ui_data if isinstance(ui_data, Mapping) else {}
    localization_raw = data.get("localization", {})
    localization = (
        localization_raw.get("entries", {})
        if isinstance(localization_raw, Mapping)
        else {}
    )
    unit_art_raw = data.get("unit_art", {})
    assignments = (
        unit_art_raw.get("assignments", [])
        if isinstance(unit_art_raw, Mapping)
        else []
    )
    audio = data.get("audio", {}) if isinstance(data.get("audio", {}), Mapping) else {}
    normalized_localization = {
        str(locale): {
            str(tag): str(text) for tag, text in entries.items()
        }
        for locale, entries in localization.items()
        if isinstance(entries, Mapping)
    } if isinstance(localization, Mapping) else {}
    normalized_assignments = [
        {
            "unit_key": str(item.get("unit_key", "")).strip(),
            "unit_name": str(item.get("unit_name", "")).strip(),
            "unit_index": _integer(item.get("unit_index"), index),
            "source_folder": str(item.get("source_folder", "")).strip(),
            "fxsxml": str(item.get("fxsxml", "")).strip(),
            "scale": _float(item.get("scale"), 1.0),
            "z_offset": _float(item.get("z_offset"), 0.0),
        }
        for index, item in enumerate(assignments)
        if isinstance(item, Mapping)
    ] if isinstance(assignments, (list, tuple)) else []
    normalized_audio = {
        "peace_music": str(audio.get("peace_music", "")).strip(),
        "war_music": str(audio.get("war_music", "")).strip(),
        "dawn_of_man_speech": str(audio.get("dawn_of_man_speech", "")).strip(),
    }
    current = advanced_content(result)
    current_assignments = [
        {
            "unit_key": item.unit_key,
            "unit_name": item.unit_name,
            "unit_index": item.unit_index,
            "source_folder": item.source_folder,
            "fxsxml": item.fxsxml,
            "scale": item.scale,
            "z_offset": item.z_offset,
        }
        for item in current.unit_art
    ]
    if (
        normalized_localization
        == {locale: dict(entries) for locale, entries in current.localization.items()}
        and normalized_assignments == current_assignments
        and normalized_audio
        == {
            "peace_music": current.audio.peace_music,
            "war_music": current.audio.war_music,
            "dawn_of_man_speech": current.audio.dawn_of_man_speech,
        }
    ):
        return result
    existing = result.extensions.get(ADVANCED_EXTENSION_KEY, {})
    extension = _mapping_copy(existing)

    localization_extension = _mapping_copy(extension.get("localization"))
    localization_extension["entries"] = normalized_localization

    unit_art_extension = _mapping_copy(extension.get("unit_art"))
    normalized_assignments = _merge_assignment_extensions(
        unit_art_extension.get("assignments"), normalized_assignments
    )
    unit_art_extension["assignments"] = normalized_assignments

    audio_extension = _mapping_copy(extension.get("audio"))
    audio_extension.update(normalized_audio)

    extension.update(
        {
            "format": ADVANCED_FORMAT,
            "format_version": _preserved_format_version(extension),
            "localization": localization_extension,
            "unit_art": unit_art_extension,
            "audio": audio_extension,
        }
    )
    result.extensions[ADVANCED_EXTENSION_KEY] = extension
    return result


def _mapping_copy(value: object) -> dict[str, Any]:
    """Deep-copy a JSON-style mapping while tolerating malformed old values."""

    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _merge_assignment_extensions(
    existing: object, normalized: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Carry unknown assignment fields across an unambiguous stable-key match."""

    existing_items = (
        [item for item in existing if isinstance(item, Mapping)]
        if isinstance(existing, (list, tuple))
        else []
    )
    existing_by_key: dict[str, Mapping[str, Any]] = {}
    ambiguous_existing: set[str] = set()
    for item in existing_items:
        key = str(item.get("unit_key", "")).strip()
        if not key:
            continue
        if key in existing_by_key:
            ambiguous_existing.add(key)
        else:
            existing_by_key[key] = item

    incoming_counts: dict[str, int] = {}
    for item in normalized:
        key = str(item.get("unit_key", "")).strip()
        if key:
            incoming_counts[key] = incoming_counts.get(key, 0) + 1

    merged: list[dict[str, Any]] = []
    for item in normalized:
        key = str(item.get("unit_key", "")).strip()
        prior = (
            existing_by_key.get(key)
            if key
            and key not in ambiguous_existing
            and incoming_counts.get(key) == 1
            else None
        )
        value = _mapping_copy(prior)
        value.update(item)
        merged.append(value)
    return merged


def _preserved_format_version(extension: Mapping[str, Any]) -> int:
    """Return the supported version without downgrading a future integer one."""

    existing = extension.get("format_version")
    if (
        isinstance(existing, int)
        and not isinstance(existing, bool)
        and existing > ADVANCED_FORMAT_VERSION
    ):
        return existing
    return ADVANCED_FORMAT_VERSION


def advanced_to_ui(project: CivProject, project_root: str | Path) -> dict[str, Any]:
    """Project the extension into the desktop editor's portable dictionary."""

    root = Path(project_root).resolve()
    content = advanced_content(project)

    def display_path(value: str) -> str:
        if not value:
            return ""
        if is_portable_relative_path(value):
            return str((root / value).resolve(strict=False))
        return value

    return {
        "localization": {
            "entries": {
                locale: dict(entries)
                for locale, entries in content.localization.items()
            }
        },
        "unit_art": {
            "assignments": [
                {
                    "unit_key": item.unit_key,
                    "unit_name": item.unit_name,
                    "unit_index": item.unit_index,
                    "source_folder": display_path(item.source_folder),
                    "fxsxml": item.fxsxml,
                    "scale": item.scale,
                    "z_offset": item.z_offset,
                }
                for item in content.unit_art
            ]
        },
        "audio": {
            "peace_music": display_path(content.audio.peace_music),
            "war_music": display_path(content.audio.war_music),
            "dawn_of_man_speech": display_path(
                content.audio.dawn_of_man_speech
            ),
        },
    }


def materialize_advanced_sources(
    project: CivProject,
    workspace_root: str | Path,
    *,
    source_root: str | Path | None = None,
) -> CivProject:
    """Copy advanced sources below a project-owned workspace.

    Existing project-relative content is retained only when it resolves to a
    real, non-linked file/directory below ``workspace_root``.  External inputs
    are validated before content-addressed copies are published.
    """

    result = deepcopy(project)
    unresolved_root = Path(workspace_root).expanduser()
    if _path_contains_link_or_reparse(unresolved_root):
        raise ValueError(
            f"Advanced workspace cannot contain a link or junction: {unresolved_root}"
        )
    root = unresolved_root.resolve()
    base = Path(source_root).expanduser() if source_root is not None else None
    content = advanced_content(result)
    if not content.enabled and ADVANCED_EXTENSION_KEY not in result.extensions:
        return result
    normalized_assignments: list[dict[str, Any]] = []
    for assignment in content.unit_art:
        if not assignment.source_folder:
            normalized_assignments.append(
                {
                    "unit_key": assignment.unit_key,
                    "unit_name": assignment.unit_name,
                    "unit_index": assignment.unit_index,
                    "source_folder": "",
                    "fxsxml": assignment.fxsxml,
                    "scale": assignment.scale,
                    "z_offset": assignment.z_offset,
                }
            )
            continue
        source = _resolve_source(
            assignment.source_folder, root, base, expect_directory=True
        )
        entry = PurePosixPath(assignment.fxsxml.replace("\\", "/")).as_posix()
        report = inspect_unit_art_package(source.parent, source.name, entry)
        if not report.is_valid:
            detail = "; ".join(
                issue.message for issue in report.issues if issue.severity == "ERROR"
            )
            raise ValueError(
                f"Unit-art package for {assignment.unit_key or assignment.unit_name} "
                f"is invalid: {detail}"
            )
        digest = _package_digest(report.sha256)
        safe_key = _safe_component(assignment.unit_key or assignment.unit_name or "unit")
        relative = PurePosixPath(
            "Assets", "UnitArt", f"{safe_key}_{digest[:12]}"
        ).as_posix()
        destination = _owned_path(root, relative)
        _copy_package(source, destination, report.files, report.sha256)
        normalized_assignments.append(
            {
                "unit_key": assignment.unit_key,
                "unit_name": assignment.unit_name,
                "unit_index": assignment.unit_index,
                "source_folder": relative,
                "fxsxml": entry,
                "scale": assignment.scale,
                "z_offset": assignment.z_offset,
            }
        )

    audio_values: dict[str, str] = {}
    for role, incoming in content.audio.populated():
        source = _resolve_source(incoming, root, base, expect_directory=False)
        # Inspect with a temporary project-relative view; the validator is
        # read-only and does not care that the parent is outside the workspace.
        inspection = inspect_audio_source(
            source.parent, AudioAssetSpec(role, source.name)
        )
        if not inspection.is_valid:
            detail = "; ".join(
                issue.message
                for issue in inspection.issues
                if issue.severity == "ERROR"
            )
            raise ValueError(f"Audio source {incoming!r} is invalid: {detail}")
        relative = PurePosixPath(
            "Assets",
            "Audio",
            "Source",
            f"{role.value}_{inspection.sha256[:12]}{source.suffix.lower()}",
        ).as_posix()
        destination = _owned_path(root, relative)
        _copy_verified_file(source, destination, inspection.sha256)
        field = {
            AudioRole.PEACE_MUSIC: "peace_music",
            AudioRole.WAR_MUSIC: "war_music",
            AudioRole.DAWN_SPEECH: "dawn_of_man_speech",
        }[role]
        audio_values[field] = relative

    extension = result.extensions.get(ADVANCED_EXTENSION_KEY, {})
    value = _mapping_copy(extension)

    localization_extension = _mapping_copy(value.get("localization"))
    localization_extension["entries"] = {
        locale: dict(entries) for locale, entries in content.localization.items()
    }

    unit_art_extension = _mapping_copy(value.get("unit_art"))
    unit_art_extension["assignments"] = _merge_assignment_extensions(
        unit_art_extension.get("assignments"), normalized_assignments
    )

    audio_extension = _mapping_copy(value.get("audio"))
    audio_extension.update(
        {
            "peace_music": audio_values.get("peace_music", ""),
            "war_music": audio_values.get("war_music", ""),
            "dawn_of_man_speech": audio_values.get("dawn_of_man_speech", ""),
        }
    )
    value.update(
        {
            "format": ADVANCED_FORMAT,
            "format_version": _preserved_format_version(value),
            "localization": localization_extension,
            "unit_art": unit_art_extension,
            "audio": audio_extension,
        }
    )
    result.extensions[ADVANCED_EXTENSION_KEY] = value
    return result


def validate_advanced_content(
    project: CivProject, project_root: str | Path | None
) -> tuple[AdvancedIssue, ...]:
    """Validate extension values and any available project-owned payloads."""

    content = advanced_content(project)
    issues: list[AdvancedIssue] = []
    for locale, entries in content.localization.items():
        if locale not in SUPPORTED_LOCALES:
            issues.append(
                AdvancedIssue(
                    "ERROR",
                    "localization.locale",
                    f"advanced.localization.{locale}",
                    f"Unsupported BNW locale: {locale!r}.",
                )
            )
        for tag, text in entries.items():
            if not _TAG.fullmatch(tag):
                issues.append(
                    AdvancedIssue(
                        "ERROR",
                        "localization.tag",
                        f"advanced.localization.{locale}.{tag}",
                        "Localization tags must use the TXT_KEY_* convention.",
                    )
                )
            if "\x00" in text:
                issues.append(
                    AdvancedIssue(
                        "ERROR",
                        "localization.nul",
                        f"advanced.localization.{locale}.{tag}",
                        "Localized text cannot contain a NUL character.",
                    )
                )

    known_units = {item.key for item in project.units}
    seen_units: set[str] = set()
    root = Path(project_root).resolve() if project_root is not None else None
    for index, assignment in enumerate(content.unit_art):
        location = f"advanced.unit_art.assignments[{index}]"
        if not assignment.unit_key or not _UNIT_KEY.fullmatch(assignment.unit_key):
            issues.append(
                AdvancedIssue(
                    "ERROR",
                    "unit-art.unit-key",
                    location,
                    "A custom unit-art assignment needs a stable unique-unit key.",
                )
            )
        elif assignment.unit_key not in known_units:
            issues.append(
                AdvancedIssue(
                    "ERROR",
                    "unit-art.unknown-unit",
                    location,
                    f"No current unique unit has key {assignment.unit_key!r}.",
                )
            )
        elif assignment.unit_key in seen_units:
            issues.append(
                AdvancedIssue(
                    "ERROR",
                    "unit-art.duplicate-unit",
                    location,
                    "Only one custom 3D package may be assigned to each unique unit.",
                )
            )
        seen_units.add(assignment.unit_key)
        if not (0.01 <= assignment.scale <= 100.0):
            issues.append(
                AdvancedIssue(
                    "ERROR",
                    "unit-art.scale",
                    location,
                    "Unit-art scale must be between 0.01 and 100.",
                )
            )
        if not (-100.0 <= assignment.z_offset <= 100.0):
            issues.append(
                AdvancedIssue(
                    "ERROR",
                    "unit-art.z-offset",
                    location,
                    "Unit-art Z offset must be between -100 and 100.",
                )
            )
        if root is None:
            issues.append(
                AdvancedIssue(
                    "WARNING",
                    "unit-art.workspace-required",
                    location,
                    "Save the project to inspect and package its 3D unit art.",
                )
            )
        else:
            report = inspect_unit_art_package(
                root, assignment.source_folder, assignment.fxsxml
            )
            issues.extend(
                AdvancedIssue(
                    item.severity, item.code, f"{location}.{item.path}", item.message
                )
                for item in report.issues
            )

    for role, source in content.audio.populated():
        location = f"advanced.audio.{role.value}"
        if root is None:
            issues.append(
                AdvancedIssue(
                    "WARNING",
                    "audio.workspace-required",
                    location,
                    "Save the project to inspect and package its audio source.",
                )
            )
            continue
        inspection = inspect_audio_source(root, AudioAssetSpec(role, source))
        issues.extend(
            AdvancedIssue(item.severity, item.code, location, item.message)
            for item in inspection.issues
        )

    if bool(content.audio.peace_music) != bool(content.audio.war_music):
        issues.append(
            AdvancedIssue(
                "ERROR",
                "audio.music-pair",
                "advanced.audio",
                "Custom leader music requires both a peace track and a war track.",
            )
        )

    return tuple(issues)


def source_copies(project: CivProject) -> tuple[SourceCopy, ...]:
    """Return deterministic generated paths for already-materialized sources."""

    content = advanced_content(project)
    prefix = _safe_component(project.internal_prefix)
    copies: list[SourceCopy] = []
    for assignment in content.unit_art:
        base = PurePosixPath(assignment.source_folder.replace("\\", "/"))
        # Files are enumerated during the build after strict inspection.  This
        # sentinel records the package root and is expanded by ``build_copies``.
        copies.append(
            SourceCopy(
                base.as_posix(),
                PurePosixPath("Art", "Units", assignment.unit_key).as_posix(),
            )
        )
    for role, source in content.audio.populated():
        extension = PurePosixPath(source).suffix.lower()
        stem = {
            AudioRole.PEACE_MUSIC: f"{prefix}_Peace",
            AudioRole.WAR_MUSIC: f"{prefix}_War",
            AudioRole.DAWN_SPEECH: f"{prefix}_DOM_Speech",
        }[role]
        copies.append(SourceCopy(source, f"Audio/{stem}{extension}"))
    return tuple(copies)


def build_copies(
    project: CivProject, project_root: str | Path
) -> tuple[SourceCopy, ...]:
    """Expand validated source packages into exact output file mappings."""

    root = Path(project_root).resolve()
    content = advanced_content(project)
    result: list[SourceCopy] = []
    for assignment in content.unit_art:
        report = inspect_unit_art_package(
            root, assignment.source_folder, assignment.fxsxml
        )
        if not report.is_valid:
            raise ValueError(
                f"Unit-art package for {assignment.unit_key!r} failed validation."
            )
        for relative in report.files:
            result.append(
                SourceCopy(
                    PurePosixPath(assignment.source_folder, relative).as_posix(),
                    PurePosixPath(
                        "Art", "Units", assignment.unit_key, relative
                    ).as_posix(),
                )
            )
    result.extend(
        item for item in source_copies(project) if not item.output_relative.startswith("Art/Units/")
    )
    outputs = [item.output_relative.casefold() for item in result]
    if len(outputs) != len(set(outputs)):
        raise ValueError("Advanced source outputs collide on Windows.")
    return tuple(sorted(result, key=lambda item: item.output_relative.casefold()))


def localization_xml_files(project: CivProject) -> dict[str, str]:
    """Generate one deterministic replacement XML per populated locale."""

    content = advanced_content(project)
    files: dict[str, str] = {}
    for locale in SUPPORTED_LOCALES:
        entries = content.localization.get(locale, {})
        if not entries:
            continue
        root = ET.Element("GameData")
        language = ET.SubElement(root, f"Language_{locale}")
        for tag, text in sorted(entries.items()):
            if not _TAG.fullmatch(tag):
                raise ValueError(f"Invalid localization tag: {tag!r}")
            replace = ET.SubElement(language, "Replace", {"Tag": tag})
            ET.SubElement(replace, "Text").text = str(text)
        ET.indent(root, space="  ")
        files[f"Localization/{locale}.xml"] = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            + ET.tostring(root, encoding="unicode", short_empty_elements=True)
            + "\n"
        )
    return files


def custom_unit_art_assignment(
    project: CivProject, unit_key: str
) -> UnitArtAssignment | None:
    return next(
        (item for item in advanced_content(project).unit_art if item.unit_key == unit_key),
        None,
    )


def unit_art_entry_output(assignment: UnitArtAssignment) -> str:
    return PurePosixPath(
        "Art", "Units", assignment.unit_key, assignment.fxsxml.replace("\\", "/")
    ).as_posix()


def audio_sql(project: CivProject) -> str:
    """Generate the engine audio rows required by configured custom tracks."""

    content = advanced_content(project)
    prefix = _safe_component(project.internal_prefix)
    rows_sounds: list[tuple[str, str, str, int]] = []
    rows_scripts: list[tuple[str, str, str, int, int, int]] = []
    for role, source in content.audio.populated():
        filename = {
            AudioRole.PEACE_MUSIC: f"{prefix}_Peace",
            AudioRole.WAR_MUSIC: f"{prefix}_War",
            AudioRole.DAWN_SPEECH: f"{prefix}_DOM_Speech",
        }[role]
        sound_id = {
            AudioRole.PEACE_MUSIC: f"SND_LEADER_MUSIC_{prefix}_PEACE",
            AudioRole.WAR_MUSIC: f"SND_LEADER_MUSIC_{prefix}_WAR",
            AudioRole.DAWN_SPEECH: f"SND_DOM_SPEECH_{prefix}",
        }[role]
        script_id = {
            AudioRole.PEACE_MUSIC: f"AS2D_LEADER_MUSIC_{prefix}_PEACE",
            AudioRole.WAR_MUSIC: f"AS2D_LEADER_MUSIC_{prefix}_WAR",
            AudioRole.DAWN_SPEECH: f"AS2D_DOM_SPEECH_{prefix}",
        }[role]
        music = role in {AudioRole.PEACE_MUSIC, AudioRole.WAR_MUSIC}
        rows_sounds.append(
            (
                sound_id,
                filename,
                "Streamed" if music else "DynamicResident",
                1,
            )
        )
        volume = 65 if music else 100
        rows_scripts.append(
            (
                script_id,
                sound_id,
                "GAME_MUSIC" if music else "GAME_SPEECH",
                volume,
                volume,
                1 if music else 0,
            )
        )
    if not rows_sounds:
        return ""

    def quoted(value: object) -> str:
        if isinstance(value, int):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    sound_values = ",\n".join(
        "  (" + ", ".join(quoted(value) for value in row) + ")"
        for row in rows_sounds
    )
    script_values = ",\n".join(
        "  (" + ", ".join(quoted(value) for value in row) + ")"
        for row in rows_scripts
    )
    return (
        "-- Audio.sql\n"
        "-- Custom audio still requires an in-game BNW playback test.\n\n"
        "INSERT INTO Audio_Sounds (SoundID, FileName, LoadType, DontCache) VALUES\n"
        f"{sound_values};\n\n"
        "INSERT INTO Audio_2DSounds\n"
        "  (ScriptID, SoundID, SoundType, MaxVolume, MinVolume, IsMusic) VALUES\n"
        f"{script_values};\n"
    )


def soundtrack_tag(project: CivProject) -> str | None:
    audio = advanced_content(project).audio
    if audio.peace_music and audio.war_music:
        return _safe_component(project.internal_prefix)
    return None


def dawn_audio_script(project: CivProject) -> str | None:
    if advanced_content(project).audio.dawn_of_man_speech:
        return f"AS2D_DOM_SPEECH_{_safe_component(project.internal_prefix)}"
    return None


def _resolve_source(
    value: str,
    workspace_root: Path,
    source_root: Path | None,
    *,
    expect_directory: bool,
) -> Path:
    workspace = Path(workspace_root).expanduser()
    if _path_contains_link_or_reparse(workspace):
        raise ValueError(
            f"Advanced workspace cannot contain a link or junction: {workspace}"
        )
    workspace = workspace.resolve()
    raw = Path(value).expanduser()
    if raw.is_absolute():
        if _path_contains_link_or_reparse(raw):
            raise ValueError(
                f"Advanced source cannot contain a link or junction: {raw}"
            )
        candidate = raw.resolve()
    elif is_portable_relative_path(value):
        relative = Path(*PurePosixPath(value.replace("\\", "/")).parts)
        unresolved_inside = workspace / relative
        if _path_contains_link_or_reparse(unresolved_inside):
            raise ValueError(
                "Advanced source cannot contain a link or junction: "
                f"{unresolved_inside}"
            )
        inside = _owned_path(workspace, value)
        if inside.exists():
            candidate = inside
        elif source_root is not None:
            unresolved_source_root = Path(source_root).expanduser()
            if _path_contains_link_or_reparse(unresolved_source_root):
                raise ValueError(
                    "Advanced source root cannot contain a link or junction: "
                    f"{unresolved_source_root}"
                )
            resolved_source_root = unresolved_source_root.resolve()
            unresolved_source = resolved_source_root / relative
            if _path_contains_link_or_reparse(unresolved_source):
                raise ValueError(
                    "Advanced source cannot contain a link or junction: "
                    f"{unresolved_source}"
                )
            candidate = _owned_path(resolved_source_root, value)
        else:
            candidate = inside
    else:
        raise ValueError(f"Advanced source path is not portable: {value!r}")
    if _path_contains_link_or_reparse(candidate):
        raise ValueError(
            f"Advanced source cannot contain a link or junction: {candidate}"
        )
    if expect_directory and not candidate.is_dir():
        raise ValueError(f"Unit-art source folder does not exist: {candidate}")
    if not expect_directory and not candidate.is_file():
        raise ValueError(f"Audio source file does not exist: {candidate}")
    return candidate


def _copy_package(
    source: Path,
    destination: Path,
    files: tuple[str, ...],
    hashes: Mapping[str, str],
) -> None:
    if destination.exists():
        if not destination.is_dir() or destination.is_symlink():
            raise ValueError(f"Unit-art destination is unsafe: {destination}")
        for relative in files:
            target = _owned_path(destination, relative)
            if not target.is_file() or target.is_symlink() or _digest(target) != hashes[relative]:
                raise ValueError(
                    f"Existing unit-art destination differs from source: {relative}"
                )
        return
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        for relative in files:
            incoming = _owned_path(source, relative)
            target = _owned_path(temporary, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(incoming, target)
            if _digest(target) != hashes[relative]:
                raise ValueError(f"Unit-art copy hash mismatch: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _copy_verified_file(source: Path, destination: Path, expected_hash: str) -> None:
    if destination.exists():
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(f"Advanced source destination is unsafe: {destination}")
        if _digest(destination) != expected_hash:
            raise ValueError(f"Advanced source destination hash differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        if _digest(temporary) != expected_hash:
            raise ValueError(f"Advanced source copy hash mismatch: {source}")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _owned_path(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    if not is_portable_relative_path(normalized):
        raise ValueError(f"Path is not a portable relative path: {relative!r}")
    candidate = (root / Path(*PurePosixPath(normalized).parts)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes the project root: {relative!r}") from exc
    return candidate


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


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.upper()).strip("_")
    return cleaned[:96] or "CUSTOM"


def _package_digest(hashes: Mapping[str, str]) -> str:
    value = sha256()
    for relative, digest in sorted(hashes.items(), key=lambda item: item[0].casefold()):
        value.update(relative.encode("utf-8"))
        value.update(b"\0")
        value.update(digest.encode("ascii"))
        value.update(b"\0")
    return value.hexdigest()


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _integer(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
