"""Typed Civ V localization interchange independent of the Qt editor."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
import os
from pathlib import Path
import re
import stat
from typing import Mapping
import uuid
import xml.etree.ElementTree as ET


SUPPORTED_LOCALES: Mapping[str, str] = {
    "en_US": "English",
    "DE_DE": "German",
    "ES_ES": "Spanish",
    "FR_FR": "French",
    "IT_IT": "Italian",
    "JA_JP": "Japanese",
    "KO_KR": "Korean",
    "PL_PL": "Polish",
    "RU_RU": "Russian",
    "ZH_Hant_HK": "Traditional Chinese",
}
_TAG = re.compile(r"TXT_KEY_[A-Z0-9_]{1,220}\Z")


@dataclass(frozen=True, slots=True)
class LocalizationIssue:
    severity: str
    code: str
    row: int
    message: str


@dataclass(frozen=True, slots=True)
class LocalizationImport:
    entries: dict[str, dict[str, str]]
    issues: tuple[LocalizationIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)


def import_localization_csv(text: str) -> LocalizationImport:
    """Read locale/tag/text rows without executing formulas or guessing tags."""

    issues: list[LocalizationIssue] = []
    entries: dict[str, dict[str, str]] = {}
    try:
        reader = csv.DictReader(StringIO(text, newline=""))
    except csv.Error as exc:  # pragma: no cover - construction is normally inert
        return LocalizationImport(
            {}, (LocalizationIssue("ERROR", "localization.csv", 0, str(exc)),)
        )
    if reader.fieldnames != ["locale", "tag", "text"]:
        return LocalizationImport(
            {},
            (
                LocalizationIssue(
                    "ERROR",
                    "localization.header",
                    1,
                    "CSV header must be exactly: locale,tag,text",
                ),
            ),
        )
    try:
        rows = list(reader)
    except csv.Error as exc:
        return LocalizationImport(
            {}, (LocalizationIssue("ERROR", "localization.csv", reader.line_num, str(exc)),)
        )
    for index, row in enumerate(rows, start=2):
        locale = (row.get("locale") or "").strip()
        tag = (row.get("tag") or "").strip()
        value = row.get("text") or ""
        if len(value) >= 2 and value[0] == "'" and value[1] in "=+-@":
            value = value[1:]
        if locale not in SUPPORTED_LOCALES:
            issues.append(
                LocalizationIssue(
                    "ERROR",
                    "localization.locale",
                    index,
                    f"Unsupported BNW locale: {locale!r}.",
                )
            )
            continue
        if not _TAG.fullmatch(tag):
            issues.append(
                LocalizationIssue(
                    "ERROR",
                    "localization.tag",
                    index,
                    f"Invalid text tag: {tag!r}.",
                )
            )
            continue
        if "\x00" in value:
            issues.append(
                LocalizationIssue(
                    "ERROR",
                    "localization.nul",
                    index,
                    "Localized text cannot contain a NUL character.",
                )
            )
            continue
        language = entries.setdefault(locale, {})
        if tag in language:
            issues.append(
                LocalizationIssue(
                    "ERROR",
                    "localization.duplicate",
                    index,
                    f"Duplicate {locale}/{tag} entry.",
                )
            )
            continue
        language[tag] = value
    return LocalizationImport(entries, tuple(issues))


def export_localization_csv(entries: Mapping[str, Mapping[str, str]]) -> str:
    target = StringIO(newline="")
    writer = csv.writer(target, lineterminator="\n")
    writer.writerow(("locale", "tag", "text"))
    for locale in SUPPORTED_LOCALES:
        for tag, value in sorted(entries.get(locale, {}).items()):
            writer.writerow((locale, tag, _safe_spreadsheet_text(str(value))))
    return target.getvalue()


def generate_localization_xml(entries: Mapping[str, Mapping[str, str]]) -> str:
    """Generate deterministic GameData XML for non-English text overrides."""

    root = ET.Element("GameData")
    for locale in SUPPORTED_LOCALES:
        values = entries.get(locale, {})
        if not values:
            continue
        language = ET.SubElement(root, f"Language_{locale}")
        for tag, value in sorted(values.items()):
            if not _TAG.fullmatch(tag):
                raise ValueError(f"Invalid localization tag: {tag!r}")
            row = ET.SubElement(language, "Row", {"Tag": tag})
            ET.SubElement(row, "Text").text = str(value)
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="unicode", short_empty_elements=True
    ) + "\n"


def load_localization_csv(path: str | Path) -> LocalizationImport:
    unresolved = Path(path).expanduser()
    if _path_contains_link_or_reparse(unresolved):
        raise ValueError("Localization CSV cannot be a link or junction.")
    source = unresolved.resolve()
    if _path_contains_link_or_reparse(source):
        raise ValueError("Localization CSV cannot be a link or junction.")
    if not source.is_file():
        raise ValueError("Localization CSV must be a real file.")
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Localization CSV exceeds the 16 MiB safety limit.")
    return import_localization_csv(source.read_text(encoding="utf-8-sig"))


def save_localization_csv(
    path: str | Path, entries: Mapping[str, Mapping[str, str]]
) -> Path:
    unresolved = Path(path).expanduser()
    if _path_contains_link_or_reparse(unresolved):
        raise ValueError("Localization export path cannot contain a link or junction.")
    destination = unresolved.resolve()
    if destination.suffix.casefold() != ".csv":
        raise ValueError("Localization export must use a .csv filename.")
    if destination.exists():
        raise FileExistsError(
            f"Refusing to overwrite localization CSV: {destination}"
        )
    if not destination.parent.is_dir():
        raise ValueError("Localization export parent folder does not exist.")
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(export_localization_csv(entries))
        if _path_contains_link_or_reparse(destination):
            raise ValueError(
                "Localization export path became a link or junction."
            )
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _safe_spreadsheet_text(value: str) -> str:
    # CSV is an interchange format, but exported text should not execute if a
    # translator opens the file in Excel or another spreadsheet program.
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


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
