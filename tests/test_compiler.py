from __future__ import annotations

from copy import deepcopy
import sqlite3
import xml.etree.ElementTree as ET

import pytest

from civ5studio.domain import ArtAssetSpec, ArtRole, load_project
from civ5studio.bnw import ReferenceCatalog
from civ5studio.generation import (
    CompilationError,
    DATABASE_FILE_ORDER,
    RenderedArtifact,
    compile_project,
    generate_art_manifest,
    validate_compiled_sql,
    validate_compiled_sql_against_database,
)
from civ5studio.generation.sqlite_validation import _create_schema, _seed_reference_rows


def test_generated_inventory_and_database_order_are_stable(sample_project):
    compilation = compile_project(sample_project)
    assert compilation.database_files == DATABASE_FILE_ORDER
    assert compilation.inventory == (
        "Core/Text.sql",
        "Core/Colors.sql",
        "Core/IconAtlases.sql",
        "Core/Trait.sql",
        "Core/Leader.sql",
        "Core/Units.sql",
        "Core/Buildings.sql",
        "Core/Improvements.sql",
        "Core/Civilization.sql",
        "Lua/CivilizationRuntime.lua",
        "Art/Leaders/Leaderhead_VYTAUTAS_LITHUANIA_CUSTOM.xml",
        "Documentation/ART_MANIFEST.json",
        "Documentation/BNW_REFERENCE_PROVENANCE.json",
        "Documentation/ADVANCED_CONTENT_RUNTIME_GATES.json",
        "Documentation/ADVANCED_CONTENT_RUNTIME_GATES.md",
        "Documentation/LUA_EFFECT_MANIFEST.json",
        "Documentation/LUA_EFFECT_MANIFEST.md",
        "Documentation/CAPABILITY_REPORT.json",
        "Documentation/CAPABILITY_REPORT.md",
        "Documentation/BUILD_CHECKLIST.md",
        "Documentation/GENERATED_SUMMARY.md",
        "Documentation/UNIMPLEMENTED_EFFECTS.md",
        "Documentation/VALIDATION_REPORT.md",
        "Documentation/PROJECT_SNAPSHOT.civ5project.json",
        "Kingdom_Of_Lithuania.modinfo",
    )


def test_generated_xml_and_modinfo_parse_and_reference_safe_order(sample_project):
    compilation = compile_project(sample_project)
    leader = ET.fromstring(
        compilation.files["Art/Leaders/Leaderhead_VYTAUTAS_LITHUANIA_CUSTOM.xml"]
    )
    assert leader.tag == "LeaderScene"
    modinfo = ET.fromstring(compilation.files["Kingdom_Of_Lithuania.modinfo"])
    actions = [node.text for node in modinfo.findall("./Actions/OnModActivated/UpdateDatabase")]
    assert actions == list(DATABASE_FILE_ORDER)
    assert modinfo.findtext("./Properties/AffectsSavedGames") == "0"
    listed = [node.text for node in modinfo.findall("./Files/File")]
    assert listed == [
        *compilation.vfs_files,
        *compilation.database_files,
        *compilation.lua_files,
    ]


def test_generated_build_checklist_keeps_technical_work_inside_studio(sample_project):
    checklist = compile_project(sample_project).files[
        "Documentation/BUILD_CHECKLIST.md"
    ]

    assert "What Civilization Studio already checked" in checklist
    assert "You do not need to run SQL, parse XML, or convert DDS files yourself" in checklist
    assert "Install into Civilization V" in checklist
    assert "SMP art service" not in checklist
    assert "Execute all `Core/*.sql`" not in checklist


def test_modinfo_uses_typed_affects_saved_games_option(sample_project):
    project = deepcopy(sample_project)
    project.options.affects_saved_games = True
    modinfo = ET.fromstring(compile_project(project).files["Kingdom_Of_Lithuania.modinfo"])
    assert modinfo.findtext("./Properties/AffectsSavedGames") == "1"


def test_sql_escaping_and_isolated_execution(sample_project):
    project = deepcopy(sample_project)
    project.civilization.city_names[0] = "O'Brien's Ford"
    compilation = compile_project(project)
    assert "O''Brien''s Ford" in compilation.files["Core/Text.sql"]
    report = validate_compiled_sql(compilation, project)
    assert report.is_valid, report.errors


def test_generated_sql_header_cannot_be_escaped_by_mod_name(sample_project):
    project = deepcopy(sample_project)
    project.mod_name = "Visible Mod\nDROP TABLE Units; --"

    compilation = compile_project(project)
    sql = compilation.files["Core/Trait.sql"]

    assert "-- Mod: Visible Mod DROP TABLE Units; --\n" in sql
    assert "\nDROP TABLE Units" not in sql
    report = validate_compiled_sql(compilation, project)
    assert report.is_valid, report.errors


def test_unique_donors_use_complete_verified_bnw_clone_contracts(sample_project):
    catalog = ReferenceCatalog.bundled()
    compilation = compile_project(sample_project, catalog)
    assert len(catalog.ordered_columns("Units")) == 99
    assert len(catalog.clone_contract("Units")["child_tables"]) == 15
    assert len(catalog.ordered_columns("Buildings")) == 152
    assert len(catalog.clone_contract("Buildings")["child_tables"]) == 38
    assert catalog.ordered_columns("UnitPromotions_CivilianUnitType") == (
        "PromotionType",
        "UnitType",
    )
    units_sql = compilation.files["Core/Units.sql"]
    buildings_sql = compilation.files["Core/Buildings.sql"]
    for column in catalog.ordered_columns("Units"):
        if column != "ID":
            assert column in units_sql
    for table in catalog.clone_contract("Units")["child_tables"]:
        assert f"INSERT INTO {table}" in units_sql
    assert "INSERT INTO UnitGameplay2DScripts" in units_sql
    assert "INSERT INTO UnitPromotions_CivilianUnitType" in units_sql
    for column in catalog.ordered_columns("Buildings"):
        if column != "ID":
            assert column in buildings_sql
    for table in catalog.clone_contract("Buildings")["child_tables"]:
        assert f"INSERT INTO {table}" in buildings_sql


def test_capability_report_keeps_runtime_gate_explicit(sample_project):
    compilation = compile_project(sample_project)
    import json

    capability = json.loads(
        compilation.files["Documentation/CAPABILITY_REPORT.json"]
    )
    assert capability["verified_clone_contract"] == {
        "unit_columns": 99,
        "unit_child_tables": 15,
        "building_columns": 152,
        "building_child_tables": 38,
        "improvement_columns": 57,
        "improvement_child_tables": 19,
        "build_columns": 33,
        "build_child_tables": 2,
    }
    assert capability["release_gates"]["bnw_schema_contract"] == "PASS"
    assert capability["release_gates"]["strict_static_release"] == "NOT_RUN"
    assert capability["release_gates"]["bnw_in_game"] == "REQUIRED_NOT_RUN"
    assert capability["release_gates"]["ige_compatibility"] == "REQUIRED_NOT_RUN"

def test_sql_executes_in_read_only_clone_of_reference_database(sample_project, tmp_path):
    database = tmp_path / "Civ5DebugDatabase.db"
    connection = sqlite3.connect(database)
    try:
        catalog = ReferenceCatalog.bundled()
        _create_schema(connection, catalog)
        _seed_reference_rows(connection, catalog)
    finally:
        connection.close()

    compilation = compile_project(sample_project, catalog)
    report = validate_compiled_sql_against_database(
        compilation, sample_project, database, catalog
    )
    assert report.is_valid, report.errors
    assert report.has_code("bnw.database-evidence")


def test_optional_strategic_view_art_gets_isolated_runtime_binding(sample_project):
    project = deepcopy(sample_project)
    project.art.assets.append(
        ArtAssetSpec(
            asset_id="winged_hussar_strategic",
            role=ArtRole.STRATEGIC_VIEW,
            source_png="Assets/Source/winged-hussar-sv.png",
            subject_key="unit:WINGED_HUSSAR",
            required=True,
            crop_mode="contain",
        )
    )
    compilation = compile_project(project)
    path = "Art/StrategicView/SV_LITHUANIA_CUSTOM_WINGED_HUSSAR.dds"
    outputs = {item["path"]: item for item in compilation.art_manifest["outputs"]}
    assert outputs[path] == {
        "path": path,
        "purpose": "strategic_view",
        "source_roles": ["strategic_view"],
        "subject_key": "unit:WINGED_HUSSAR",
        "width": 64,
        "height": 64,
        "profile": "legacy_dx9_a8r8g8b8",
        "surface_count": 1,
        "mip_count": 1,
        "required": True,
    }
    sql = compilation.files["Core/Units.sql"]
    assert "ART_DEF_UNIT_WINGED_HUSSAR_LITHUANIA_CUSTOM" in sql
    assert "INSERT INTO ArtDefine_UnitInfos" in sql
    assert "INSERT INTO ArtDefine_UnitInfoMemberInfos" in sql
    assert "INSERT INTO ArtDefine_StrategicView" in sql
    assert "SV_LITHUANIA_CUSTOM_WINGED_HUSSAR.dds" in sql
    assert "retain the donor map icon binding" not in sql
    report = validate_compiled_sql(compilation, project)
    assert report.is_valid, report.errors


def test_smp_atlas_contract_matches_fixed_art_backend(sample_project):
    compilation = compile_project(sample_project)
    sql = compilation.files["Core/IconAtlases.sql"]
    assert "LITHUANIA_CUSTOM_Atlas_256.dds" in sql
    assert "LITHUANIA_CUSTOM_Alpha_128.dds" in sql
    assert "LITHUANIA_CUSTOM_Flag_WINGED_HUSSAR_32.dds" in sql
    assert sql.count(", 8, 8)") == 14

    outputs = {item["path"]: item for item in compilation.art_manifest["outputs"]}
    alpha = outputs["Art/Atlases/LITHUANIA_CUSTOM_Alpha_128.dds"]
    flag = outputs["Art/Atlases/LITHUANIA_CUSTOM_Flag_WINGED_HUSSAR_32.dds"]
    dom = outputs["Art/DOM/LITHUANIA_CUSTOM_DOM.dds"]
    fallback = outputs["Art/Leaders/LITHUANIA_CUSTOM_fallback.dds"]
    assert (alpha["width"], alpha["height"]) == (1024, 1024)
    assert (flag["width"], flag["height"]) == (256, 256)
    assert alpha["icons_per_row"] == alpha["icons_per_column"] == 8
    assert flag["profile"] == "legacy_dx9_dxt5"
    assert dom["profile"] == "legacy_dx9_dxt1"
    assert fallback["source_roles"] == ["leader_portrait"]


def test_strict_release_checks_every_art_file_and_exact_geometry(sample_project, tmp_path):
    for asset in sample_project.art.assets:
        source = tmp_path / asset.source_png
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
    manifest = generate_art_manifest(sample_project)
    artifacts = [
        RenderedArtifact(
            path=item["path"],
            width=item["width"],
            height=item["height"],
            profile=item["profile"],
            surface_count=item["surface_count"],
            mip_count=item["mip_count"],
        )
        for item in manifest["outputs"]
    ]
    compilation = compile_project(
        sample_project,
        strict_release=True,
        project_root=str(tmp_path),
        rendered_artifacts=artifacts,
    )
    assert set(compilation.available_art_files) == {item.path for item in artifacts}

    bad = list(artifacts)
    bad[0] = RenderedArtifact(
        path=bad[0].path,
        width=bad[0].width - 1,
        height=bad[0].height,
        profile=bad[0].profile,
    )
    with pytest.raises(CompilationError) as error:
        compile_project(
            sample_project,
            strict_release=True,
            project_root=str(tmp_path),
            rendered_artifacts=bad,
        )
    assert error.value.report.has_code("art.contract-mismatch")


def test_project_snapshot_is_portable_json(sample_project):
    compilation = compile_project(sample_project)
    snapshot = compilation.files["Documentation/PROJECT_SNAPSHOT.civ5project.json"]
    loaded = load_project_from_text(snapshot, tmp_name="snapshot")
    assert loaded == sample_project


def load_project_from_text(value: str, tmp_name: str):
    import json
    from civ5studio.domain import project_from_dict

    return project_from_dict(json.loads(value))
