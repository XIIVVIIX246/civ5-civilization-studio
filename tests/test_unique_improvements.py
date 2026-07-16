from __future__ import annotations

from copy import deepcopy
import os
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from civ5studio.application.project_adapter import project_from_ui, project_to_ui
from civ5studio.application.art_project import prepare_art_project
from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain import (
    ArtAssetSpec,
    ArtRole,
    UniqueImprovementSpec,
    YieldChange,
    project_from_dict,
    project_to_dict,
    validate_project,
)
from civ5studio.generation import (
    DATABASE_FILE_ORDER,
    compile_project,
    generated_build_type,
    validate_compiled_sql,
)
from civ5studio.ui.pages import UniqueTable


def _with_improvement(sample_project):
    project = deepcopy(sample_project)
    project.improvements = [
        UniqueImprovementSpec(
            key="HILL_FARM",
            name="Hill Farm",
            help_text="A hardy farm for the highlands.",
            strategy_text="Build on productive hills.",
            civilopedia_text="Hill farms have supported upland settlements for centuries.",
            base_improvement="IMPROVEMENT_FARM",
            build_prereq_tech="TECH_MINING",
            yield_changes=[YieldChange("YIELD_PRODUCTION", 1)],
        )
    ]
    project.art.assets.append(
        ArtAssetSpec(
            asset_id="hill-farm-icon",
            role=ArtRole.UNIQUE_IMPROVEMENT_ICON,
            source_png="Assets/Source/hill-farm.png",
            subject_key="improvement:HILL_FARM",
        )
    )
    return project


def test_schema_v5_round_trip_and_v3_migration_are_lossless(sample_project) -> None:
    project = _with_improvement(sample_project)
    canonical = project_to_dict(project)
    assert canonical["schema_version"] == 5
    assert project_from_dict(canonical) == project

    v3 = project_to_dict(sample_project)
    v3["schema_version"] = 3
    v3.pop("improvements")
    v3["extensions"]["migration_marker"] = {"kept": True}
    migrated = project_from_dict(v3)
    assert migrated.schema_version == 5
    assert migrated.improvements == []
    assert migrated.lua_effects == []
    assert migrated.extensions["migration_marker"] == {"kept": True}


def test_generated_improvement_and_build_ids_are_stable(sample_project) -> None:
    project = _with_improvement(sample_project)
    assert project.ids().improvements["HILL_FARM"] == (
        "IMPROVEMENT_HILL_FARM_LITHUANIA_CUSTOM"
    )
    assert generated_build_type(project, "HILL_FARM", "BUILD_FARM") == (
        "BUILD_HILL_FARM_LITHUANIA_CUSTOM_FARM"
    )


def test_compiler_clones_full_improvement_build_and_worker_contracts(
    sample_project,
) -> None:
    project = _with_improvement(sample_project)
    catalog = ReferenceCatalog.bundled()
    compilation = compile_project(project, catalog)
    sql = compilation.files["Core/Improvements.sql"]
    custom = project.ids().improvements["HILL_FARM"]
    donor_builds = catalog.builds_for_improvement("IMPROVEMENT_FARM")

    assert "Core/Improvements.sql" in DATABASE_FILE_ORDER
    assert "FROM Improvements WHERE Type = 'IMPROVEMENT_FARM'" in sql
    assert "'CIVILIZATION_LITHUANIA_CUSTOM'" in sql
    assert "ArtDefineTag" in sql  # inherited directly; no landmark art is invented.
    for table in catalog.clone_contract("Improvements")["child_tables"]:
        assert f"INSERT INTO {table}" in sql
    for donor_build in donor_builds:
        custom_build = generated_build_type(project, "HILL_FARM", donor_build)
        assert f"FROM Builds WHERE Type = '{donor_build}'" in sql
        assert custom_build in sql
        for table in catalog.clone_contract("Builds")["child_tables"]:
            assert f"INSERT INTO {table}" in sql
    assert "INSERT INTO Unit_Builds" in sql
    assert "UPDATE Improvement_Yields SET Yield = Yield + 1" in sql
    assert "TXT_KEY_IMPROVEMENT_HILL_FARM_LITHUANIA_CUSTOM" in (
        compilation.files["Core/Text.sql"]
    )

    modinfo = ET.fromstring(
        compilation.files["Kingdom_Of_Lithuania.modinfo"]
    )
    actions = [
        node.text
        for node in modinfo.findall("./Actions/OnModActivated/UpdateDatabase")
    ]
    assert actions == list(DATABASE_FILE_ORDER)
    assert actions.index("Core/Improvements.sql") < actions.index(
        "Core/Civilization.sql"
    )
    report = validate_compiled_sql(compilation, project, catalog)
    assert report.is_valid, report.errors


def test_donor_without_build_action_is_explicit_and_blocks_strict_release(
    sample_project,
) -> None:
    project = _with_improvement(sample_project)
    project.improvements[0].base_improvement = "IMPROVEMENT_CITY_RUINS"
    audit = validate_project(project)
    strict = validate_project(project, strict_release=True)
    assert audit.has_code("improvement.no-build-action")
    assert not any(
        issue.code == "improvement.no-build-action" for issue in audit.errors
    )
    assert any(
        issue.code == "improvement.no-build-action" for issue in strict.errors
    )
    sql = compile_project(project).files["Core/Improvements.sql"]
    assert "UNSUPPORTED FOR RELEASE" in sql


def test_project_adapter_preserves_all_improvement_fields_and_icon(
    sample_project, tmp_path
) -> None:
    project = _with_improvement(sample_project)
    ui = project_to_ui(project, tmp_path)
    row = ui["mechanics"]["uniques"][-1]
    assert row["kind"] == "improvement"
    assert row["base_template"] == "IMPROVEMENT_FARM"
    assert row["prereq_tech"] == "TECH_MINING"
    assert row["yield_changes"] == [
        {"yield_type": "YIELD_PRODUCTION", "amount": 1}
    ]
    restored = project_from_ui(ui, existing=project)
    assert restored.improvements == project.improvements
    icon = next(
        asset
        for asset in restored.art.assets
        if asset.role is ArtRole.UNIQUE_IMPROVEMENT_ICON
    )
    assert icon.subject_key == "improvement:HILL_FARM"
    assert icon.source_png == "Assets/Source/hill-farm.png"

    prepared = prepare_art_project(
        restored,
        project_root=tmp_path,
        working_root=tmp_path / "work",
    )
    main = prepared.spec.atlases[0]
    improvement_item = next(
        item for item in main.items if item.key == "improvement_HILL_FARM"
    )
    assert improvement_item.index == 2 + len(restored.units) + len(restored.buildings)
    assert improvement_item.processing_role.value == "unique_improvement_icon"


def test_mechanics_editor_exposes_improvement_donor_text_yield_tech_and_icon() -> None:
    _app = QApplication.instance() or QApplication([])
    editor = UniqueTable()
    editor.set_reference_catalog(
        [("UNITCLASS_WARRIOR", "UNIT_WARRIOR")],
        [("BUILDINGCLASS_MONUMENT", "BUILDING_MONUMENT")],
        ["YIELD_FOOD", "YIELD_PRODUCTION"],
        improvement_templates=["IMPROVEMENT_FARM", "IMPROVEMENT_MINE"],
        technologies=["TECH_AGRICULTURE", "TECH_MINING"],
    )
    editor.add_row(
        "improvement",
        {
            "name": "Terrace",
            "base_template": "IMPROVEMENT_FARM",
            "help_text": "Help",
            "strategy_text": "Strategy",
        },
    )
    row_index = editor.table.rowCount() - 1
    editor.table.setCurrentCell(row_index, 1)
    editor.improvement_civilopedia.setPlainText("Civilopedia")
    editor.prereq_tech.setCurrentText("TECH_MINING")
    editor.improvement_yield_changes.add_row(
        {"yield_type": "YIELD_PRODUCTION", "amount": 2}
    )
    editor.improvement_icon.set_path("C:/art/terrace.png")
    row = editor.values()[-1]
    assert row["kind"] == "improvement"
    assert row["base_template"] == "IMPROVEMENT_FARM"
    assert row["civilopedia_text"] == "Civilopedia"
    assert row["prereq_tech"] == "TECH_MINING"
    assert row["yield_changes"] == [
        {"yield_type": "YIELD_PRODUCTION", "amount": 2}
    ]
    assert row["art"]["icon_source"] == "C:/art/terrace.png"
    editor.deleteLater()
