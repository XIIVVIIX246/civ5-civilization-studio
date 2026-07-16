from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

import civ5studio.compatibility.scanner as scanner_module
from civ5studio.compatibility import Confidence, scan_installed_mods


def _write_mod(
    mods_root: Path,
    folder_name: str,
    *,
    mod_id: str,
    version: str = "1",
    name: str | None = None,
    files: dict[str, str] | None = None,
    declared_paths: tuple[str, ...] | None = None,
    action_paths: tuple[str, ...] | None = None,
    dependencies: tuple[tuple[str, str, str], ...] = (),
    references: tuple[tuple[str, str, str], ...] = (),
) -> Path:
    folder = mods_root / folder_name
    folder.mkdir(parents=True)
    for relative, content in (files or {}).items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    root = ET.Element("Mod", {"id": mod_id, "version": version})
    properties = ET.SubElement(root, "Properties")
    ET.SubElement(properties, "Name").text = name or folder_name
    file_values = declared_paths if declared_paths is not None else tuple((files or {}).keys())
    file_root = ET.SubElement(root, "Files")
    for relative in file_values:
        ET.SubElement(file_root, "File", {"import": "0"}).text = relative
    if dependencies:
        values = ET.SubElement(root, "Dependencies")
        for relation_id, minimum, maximum in dependencies:
            ET.SubElement(
                values,
                "Mod",
                {
                    "id": relation_id,
                    "minversion": minimum,
                    "maxversion": maximum,
                    "title": f"Dependency {relation_id}",
                },
            )
    if references:
        values = ET.SubElement(root, "References")
        for relation_id, minimum, maximum in references:
            ET.SubElement(
                values,
                "Mod",
                {
                    "id": relation_id,
                    "minversion": minimum,
                    "maxversion": maximum,
                    "title": f"Reference {relation_id}",
                },
            )
    actions = ET.SubElement(root, "Actions")
    activated = ET.SubElement(actions, "OnModActivated")
    for relative in action_paths if action_paths is not None else file_values:
        if Path(relative).suffix.casefold() in {".xml", ".sql"}:
            ET.SubElement(activated, "UpdateDatabase").text = relative
    modinfo = folder / f"{folder_name}.modinfo"
    ET.ElementTree(root).write(modinfo, encoding="utf-8", xml_declaration=True)
    return folder


def test_scanner_detects_duplicate_ids_and_relation_failures(tmp_path: Path) -> None:
    mods = tmp_path / "MODS"
    _write_mod(mods, "Library v1", mod_id="library-id", version="1")
    _write_mod(mods, "Library duplicate", mod_id="library-id", version="1")
    _write_mod(
        mods,
        "Consumer",
        mod_id="consumer-id",
        dependencies=(("library-id", "2", "4"),),
        references=(("missing-id", "0", "99"),),
    )

    report = scan_installed_mods(mods)

    assert "library-id" in report.duplicate_mod_ids
    assert len(report.duplicate_mod_ids["library-id"]) == 2
    codes = {item.code for item in report.issues}
    assert "DUPLICATE_MOD_ID" in codes
    assert "DECLARED_RELATION_VERSION_MISMATCH" in codes
    assert "DECLARED_REFERENCE_MISSING" in codes


def test_scanner_finds_high_confidence_xml_and_sql_type_conflict(
    tmp_path: Path,
) -> None:
    mods = tmp_path / "MODS"
    xml = """<?xml version="1.0"?>
<GameData>
  <UnitPromotions>
    <Update><Where Type="PROMOTION_BLITZ"/><Set LostWithUpgrade="0"/></Update>
    <Row><Type>PROMOTION_SHARED_CUSTOM</Type><Description>TXT_KEY_ONE</Description></Row>
  </UnitPromotions>
</GameData>
"""
    sql = """
-- A reference does not count as a declaration.
UPDATE UnitPromotions SET LostWithUpgrade = 0 WHERE Type = 'PROMOTION_BLITZ';
INSERT INTO UnitPromotions
  (Description, Type, LostWithUpgrade)
VALUES
  ('TXT_KEY_TWO', 'PROMOTION_SHARED_CUSTOM', 0);
"""
    _write_mod(mods, "XML mod", mod_id="xml-id", files={"data.xml": xml})
    _write_mod(mods, "SQL mod", mod_id="sql-id", files={"data.sql": sql})

    report = scan_installed_mods(mods)

    assert len(report.type_conflicts) == 1
    conflict = report.type_conflicts[0]
    assert conflict.identifier == "PROMOTION_SHARED_CUSTOM"
    assert conflict.confidence is Confidence.HIGH
    assert {item.table for item in conflict.declarations} == {"UnitPromotions"}
    assert "PROMOTION_BLITZ" not in {
        item.identifier
        for mod in report.mods
        for item in mod.type_declarations
        if item.confidence is Confidence.HIGH
    }


def test_scanner_rejects_unsafe_and_missing_declared_files_without_reading_them(
    tmp_path: Path,
) -> None:
    mods = tmp_path / "MODS"
    outside = mods / "outside.xml"
    outside.parent.mkdir(parents=True)
    outside.write_text(
        "<GameData><Units><Row><Type>UNIT_OUTSIDE</Type></Row></Units></GameData>",
        encoding="utf-8",
    )
    _write_mod(
        mods,
        "Unsafe",
        mod_id="unsafe-id",
        declared_paths=("../outside.xml", "missing.sql"),
        action_paths=("../outside.xml", "missing.sql", "not-declared.xml"),
    )

    report = scan_installed_mods(mods)

    codes = {item.code for item in report.issues}
    assert "UNSAFE_MOD_FILE_PATH" in codes
    assert "DECLARED_MOD_FILE_MISSING" in codes
    assert "ACTION_FILE_UNDECLARED" in codes
    assert not [
        item
        for mod in report.mods
        for item in mod.type_declarations
        if item.identifier == "UNIT_OUTSIDE"
    ]


def test_ecosystem_awareness_uses_only_parsed_modinfo_name(tmp_path: Path) -> None:
    mods = tmp_path / "MODS"
    _write_mod(
        mods,
        "not-an-ige-folder",
        mod_id="ige-id",
        name="Ingame Editor",
    )
    _write_mod(
        mods,
        "Enhanced User Interface folder name only",
        mod_id="ordinary-id",
        name="Ordinary UI Mod",
    )
    _write_mod(mods, "map", mod_id="map-id", name="YnAEMP v25")

    report = scan_installed_mods(mods)

    assert {item.product for item in report.ecosystem_presence} == {"IGE", "YnAEMP"}
    assert all(item.evidence_field == "Properties/Name" for item in report.ecosystem_presence)
    assert not any("compatible" in item.message.casefold() for item in report.issues)


def test_missing_modinfo_and_root_are_reported_without_mutation(tmp_path: Path) -> None:
    missing = tmp_path / "not-created"
    report = scan_installed_mods(missing)
    assert {item.code for item in report.errors} == {"MODS_ROOT_MISSING"}
    assert not missing.exists()

    mods = tmp_path / "MODS"
    (mods / "broken-folder").mkdir(parents=True)
    report = scan_installed_mods(mods)
    assert any(item.code == "MODINFO_MISSING" for item in report.warnings)


def test_scanner_rejects_reparse_mods_root_before_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    linked_parent = tmp_path / "linked-parent"
    mods = linked_parent / "MODS"
    mods.mkdir(parents=True)
    original = scanner_module._is_link_or_reparse
    monkeypatch.setattr(
        scanner_module,
        "_is_link_or_reparse",
        lambda path: path == linked_parent or original(path),
    )

    report = scan_installed_mods(mods)

    assert {item.code for item in report.errors} == {"UNSAFE_MODS_ROOT_LINK"}
    assert report.mods == ()


def test_scanner_rejects_reparse_mod_folder_and_modinfo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mods = tmp_path / "MODS"
    linked_folder = _write_mod(mods, "Linked folder", mod_id="linked-folder")
    linked_modinfo_folder = _write_mod(
        mods, "Linked modinfo", mod_id="linked-modinfo"
    )
    linked_modinfo = next(linked_modinfo_folder.glob("*.modinfo"))
    _write_mod(mods, "Safe", mod_id="safe")
    flagged = {linked_folder, linked_modinfo}
    original = scanner_module._is_link_or_reparse
    monkeypatch.setattr(
        scanner_module,
        "_is_link_or_reparse",
        lambda path: path in flagged or original(path),
    )

    report = scan_installed_mods(mods)

    codes = {item.code for item in report.errors}
    assert "UNSAFE_MOD_FOLDER_LINK" in codes
    assert "UNSAFE_MODINFO_PATH" in codes
    assert [mod.mod_id for mod in report.mods] == ["safe"]
