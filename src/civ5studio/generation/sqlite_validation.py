"""Isolated SQLite and generated-tree validation for compiler output."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain.models import ArtRole, CivProject
from civ5studio.domain.validation import ValidationReport, is_portable_relative_path

from .compiler import Compilation, generated_build_type, modinfo_filename


def validate_compiled_sql(
    compilation: Compilation,
    project: CivProject,
    catalog: ReferenceCatalog | None = None,
) -> ValidationReport:
    """Execute generated SQL against a compact schema and seeded BNW donor rows."""

    catalog = catalog or ReferenceCatalog.bundled()
    report = ValidationReport()
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection, catalog)
        _seed_reference_rows(connection, catalog)
        for relative in compilation.database_files:
            sql = compilation.files.get(relative)
            if sql is None:
                report.error(
                    "generated.sql-missing", relative, "Database file is absent from compilation."
                )
                continue
            if not relative.lower().endswith(".sql"):
                continue
            try:
                connection.executescript(sql)
            except sqlite3.Error as exc:
                report.error(
                    "generated.sql-execution",
                    relative,
                    f"Isolated SQLite validation failed: {exc}",
                )
                break
        if report.errors:
            return report.sorted()
        ids = project.ids()
        _expect_one(connection, report, "Civilizations", "Type", ids.civilization)
        _expect_one(connection, report, "Leaders", "Type", ids.leader)
        _expect_one(connection, report, "Traits", "Type", ids.trait)
        for value in ids.units.values():
            _expect_one(connection, report, "Units", "Type", value)
        for value in ids.buildings.values():
            _expect_one(connection, report, "Buildings", "Type", value)
        for value in ids.improvements.values():
            _expect_one(connection, report, "Improvements", "Type", value)
        for improvement in project.improvements:
            for donor_build in catalog.builds_for_improvement(
                improvement.base_improvement
            ):
                _expect_one(
                    connection,
                    report,
                    "Builds",
                    "Type",
                    generated_build_type(project, improvement.key, donor_build),
                )
        _validate_donor_parity(connection, report, project, catalog)
    finally:
        connection.close()
    return report.sorted()


def validate_compiled_sql_against_database(
    compilation: Compilation,
    project: CivProject,
    database_path: str | Path,
    catalog: ReferenceCatalog | None = None,
) -> ValidationReport:
    """Execute generated SQL in a memory clone of a real BNW debug database.

    The source database is opened read-only and is never modified. This is a
    stronger local compatibility check than the deterministic synthetic schema,
    while still remaining static validation rather than an in-game test.
    """

    catalog = catalog or ReferenceCatalog.bundled()
    path = Path(database_path).resolve()
    report = ValidationReport()
    if not path.is_file():
        report.error(
            "bnw.database-missing",
            str(path),
            "The selected BNW debug database does not exist.",
        )
        return report.sorted()
    source: sqlite3.Connection | None = None
    clone = sqlite3.connect(":memory:")
    try:
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        quick_check = source.execute("PRAGMA quick_check").fetchone()
        if not quick_check or quick_check[0] != "ok":
            report.error(
                "bnw.database-integrity",
                str(path),
                f"SQLite quick_check returned {quick_check!r}.",
            )
            return report.sorted()
        source.backup(clone)
        if not _table_exists(clone, "Language_en_US"):
            _create_catalog_table(clone, catalog, "Language_en_US")
            report.info(
                "bnw.auxiliary-schema",
                "Language_en_US",
                "The gameplay cache has no localization table; validated text "
                "against the bundled localization schema in the memory clone.",
            )
        for relative in compilation.database_files:
            sql = compilation.files.get(relative)
            if sql is None:
                report.error(
                    "generated.sql-missing",
                    relative,
                    "Database file is absent from compilation.",
                )
                continue
            if not relative.lower().endswith(".sql"):
                continue
            try:
                clone.executescript(sql)
            except sqlite3.Error as exc:
                report.error(
                    "bnw.sql-execution",
                    relative,
                    f"Real BNW database-clone validation failed: {exc}",
                )
                break
        if not report.errors:
            ids = project.ids()
            _expect_one(clone, report, "Civilizations", "Type", ids.civilization)
            _expect_one(clone, report, "Leaders", "Type", ids.leader)
            _expect_one(clone, report, "Traits", "Type", ids.trait)
            for value in ids.units.values():
                _expect_one(clone, report, "Units", "Type", value)
            for value in ids.buildings.values():
                _expect_one(clone, report, "Buildings", "Type", value)
            for value in ids.improvements.values():
                _expect_one(clone, report, "Improvements", "Type", value)
            for improvement in project.improvements:
                for donor_build in catalog.builds_for_improvement(
                    improvement.base_improvement
                ):
                    _expect_one(
                        clone,
                        report,
                        "Builds",
                        "Type",
                        generated_build_type(
                            project, improvement.key, donor_build
                        ),
                    )
            _validate_donor_parity(clone, report, project, catalog)
        report.info(
            "bnw.database-evidence",
            str(path),
            f"Read-only source SHA-256: {_file_sha256(path)}",
        )
    except sqlite3.Error as exc:
        report.error(
            "bnw.database-open",
            str(path),
            f"Could not clone the selected SQLite database: {exc}",
        )
    finally:
        if source is not None:
            source.close()
        clone.close()
    return report.sorted()


def validate_compilation_tree(
    root: str | Path,
    compilation: Compilation,
    project: CivProject,
    catalog: ReferenceCatalog | None = None,
) -> ValidationReport:
    """Validate written files, XML, modinfo references, and isolated SQL."""

    root = Path(root)
    report = validate_compiled_sql(compilation, project, catalog)
    for relative, expected in compilation.files.items():
        if not is_portable_relative_path(relative):
            report.error("generated.path", relative, "Compiler emitted an unsafe path.")
            continue
        path = root / relative
        if not path.is_file():
            report.error("generated.file-missing", relative, "Generated file was not written.")
            continue
        if path.read_text(encoding="utf-8") != expected:
            report.error("generated.file-drift", relative, "Written file differs from compilation.")
    for relative in compilation.available_art_files:
        if not (root / relative).is_file():
            report.error("generated.art-missing", relative, "Declared rendered art file is absent.")
    for relative in compilation.source_files:
        if not (root / relative).is_file():
            report.error(
                "generated.source-missing",
                relative,
                "Declared project-owned source file is absent from the build.",
            )

    xml_paths = [
        relative
        for relative in compilation.files
        if relative.lower().endswith((".xml", ".modinfo"))
    ]
    for relative in xml_paths:
        try:
            ET.parse(root / relative)
        except (ET.ParseError, OSError) as exc:
            report.error("generated.xml-parse", relative, f"XML parse failed: {exc}")

    modinfo_path = root / modinfo_filename(project)
    if modinfo_path.is_file():
        try:
            modinfo = ET.parse(modinfo_path).getroot()
        except ET.ParseError:
            modinfo = None
        if modinfo is not None:
            listed = []
            for node in modinfo.findall("./Files/File"):
                relative = node.text or ""
                listed.append(relative)
                if not is_portable_relative_path(relative):
                    report.error("modinfo.path", relative, "Unsafe .modinfo file path.")
                elif not (root / relative).is_file():
                    report.error(
                        "modinfo.file-missing", relative, ".modinfo references a missing file."
                    )
                expected_import = "1" if relative in compilation.vfs_files else "0"
                if node.get("import") != expected_import:
                    report.error(
                        "modinfo.import",
                        relative,
                        f"Expected import={expected_import}, found {node.get('import')!r}.",
                    )
            expected_listed = [
                *compilation.vfs_files,
                *compilation.database_files,
                *compilation.lua_files,
            ]
            if listed != expected_listed:
                report.error(
                    "modinfo.inventory",
                    modinfo_filename(project),
                    "File inventory/order does not match the compilation contract.",
                )
            actions = [
                node.text or ""
                for node in modinfo.findall("./Actions/OnModActivated/UpdateDatabase")
            ]
            if actions != list(compilation.database_files):
                report.error(
                    "modinfo.database-order",
                    modinfo_filename(project),
                    "UpdateDatabase actions are not in dependency-safe order.",
                )
    return report.sorted()


def _create_schema(connection: sqlite3.Connection, catalog: ReferenceCatalog) -> None:
    for table, columns in catalog.data.get("tables", {}).items():
        _create_catalog_table(connection, catalog, str(table), tuple(columns))


def _create_catalog_table(
    connection: sqlite3.Connection,
    catalog: ReferenceCatalog,
    table: str,
    columns: tuple[str, ...] | None = None,
) -> None:
    columns = columns or catalog.ordered_columns(table)
    if not columns:
        raise ValueError(f"Bundled catalog has no schema for {table}.")
    definitions = catalog.column_definitions(table)
    if definitions:
        rendered = ", ".join(_render_column(item) for item in definitions)
    else:
        rendered = ", ".join(f'"{column}"' for column in columns)
    connection.execute(f'CREATE TABLE "{table}" ({rendered})')


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _seed_reference_rows(
    connection: sqlite3.Connection, catalog: ReferenceCatalog
) -> None:
    for civilization in sorted(catalog.values("civilizations")):
        _insert(
            connection,
            "Civilizations",
            {
                "Type": civilization,
                "Description": civilization,
                "ShortDescription": civilization,
                "Adjective": civilization,
                "Civilopedia": civilization,
                "CivilopediaTag": civilization,
                "DefaultPlayerColor": "PLAYERCOLOR_POLAND",
                "ArtDefineTag": "ART_DEF_CIVILIZATION_EUROPE",
                "ArtStyleType": "ARTSTYLE_EUROPEAN",
                "ArtStyleSuffix": "_EURO",
                "ArtStylePrefix": "EUROPEAN ",
                "PortraitIndex": 0,
                "IconAtlas": "CIV_COLOR_ATLAS",
                "AlphaIconAtlas": "CIV_ALPHA_ATLAS",
                "SoundtrackTag": "Poland",
                "MapImage": "PolandMap.dds",
                "DawnOfManQuote": "TXT_KEY_DOM",
                "DawnOfManImage": "PolandDOM.dds",
            },
        )
        _insert(
            connection,
            "Civilization_FreeBuildingClasses",
            {"CivilizationType": civilization, "BuildingClassType": "BUILDINGCLASS_PALACE"},
        )
        _insert(
            connection,
            "Civilization_FreeTechs",
            {"CivilizationType": civilization, "TechType": "TECH_AGRICULTURE"},
        )
        _insert(
            connection,
            "Civilization_FreeUnits",
            {
                "CivilizationType": civilization,
                "UnitClassType": "UNITCLASS_SETTLER",
                "Count": 1,
                "UnitAIType": "UNITAI_SETTLE",
            },
        )
    for unit_class, unit in sorted(catalog.unit_class_to_base_unit.items()):
        art_type = f"ART_DEF_{unit}"
        _insert(
            connection,
            "Units",
            _synthetic_row(
                catalog,
                "Units",
                {
                    "Type": unit,
                    "Class": unit_class,
                    "Description": unit,
                    "Help": unit,
                    "Strategy": unit,
                    "Civilopedia": unit,
                    "Combat": 10,
                    "RangedCombat": 0,
                    "Moves": 2,
                    "Cost": 40,
                    "PrereqTech": "TECH_AGRICULTURE",
                    "UnitArtInfo": art_type,
                    "UnitFlagAtlas": "UNIT_FLAG_ATLAS",
                    "UnitFlagIconOffset": 0,
                    "IconAtlas": "UNIT_ATLAS",
                    "PortraitIndex": 0,
                },
            ),
        )
        unit_tables = dict(catalog.clone_contract("Units").get("child_tables", {}))
        unit_tables["UnitGameplay2DScripts"] = catalog.ordered_columns(
            "UnitGameplay2DScripts"
        )
        unit_tables["UnitPromotions_CivilianUnitType"] = catalog.ordered_columns(
            "UnitPromotions_CivilianUnitType"
        )
        for table in sorted(unit_tables):
            _insert(
                connection,
                table,
                _synthetic_row(catalog, table, {"UnitType": unit}),
            )
        _insert(
            connection,
            "ArtDefine_UnitInfos",
            _synthetic_row(catalog, "ArtDefine_UnitInfos", {"Type": art_type}),
        )
        _insert(
            connection,
            "ArtDefine_UnitInfoMemberInfos",
            _synthetic_row(
                catalog,
                "ArtDefine_UnitInfoMemberInfos",
                {
                    "UnitInfoType": art_type,
                    "UnitMemberInfoType": f"{art_type}_MEMBER",
                    "NumMembers": 1,
                },
            ),
        )
        _insert(
            connection,
            "ArtDefine_UnitMemberInfos",
            _synthetic_row(
                catalog,
                "ArtDefine_UnitMemberInfos",
                {
                    "Type": f"{art_type}_MEMBER",
                    "Scale": 0.14,
                    "ZOffset": 0.0,
                    "Domain": "",
                    "Model": "Assets/Units/Warrior/Warrior.fxsxml",
                },
            ),
        )
        for member_table in (
            "ArtDefine_UnitMemberCombats",
            "ArtDefine_UnitMemberCombatWeapons",
        ):
            _insert(
                connection,
                member_table,
                _synthetic_row(
                    catalog,
                    member_table,
                    {"UnitMemberType": f"{art_type}_MEMBER"},
                ),
            )
        _insert(
            connection,
            "ArtDefine_StrategicView",
            _synthetic_row(
                catalog,
                "ArtDefine_StrategicView",
                {
                    "StrategicViewType": art_type,
                    "TileType": "Unit",
                    "Asset": f"SV_{unit}.dds",
                },
            ),
        )
    for building_class, building in sorted(
        catalog.building_class_to_base_building.items()
    ):
        _insert(
            connection,
            "Buildings",
            _synthetic_row(
                catalog,
                "Buildings",
                {
                    "Type": building,
                    "BuildingClass": building_class,
                    "Description": building,
                    "Help": building,
                    "Strategy": building,
                    "Civilopedia": building,
                    "Cost": 100,
                    "GoldMaintenance": 1,
                    "Defense": 0,
                    "ExtraCityHitPoints": 0,
                    "PrereqTech": "TECH_AGRICULTURE",
                    "PortraitIndex": 0,
                    "IconAtlas": "BUILDING_ATLAS",
                    "ArtDefineTag": "ART_DEF_BUILDING_GENERIC",
                },
            ),
        )
        building_tables = catalog.clone_contract("Buildings").get("child_tables", {})
        for table in sorted(building_tables):
            _insert(
                connection,
                str(table),
                _synthetic_row(
                    catalog, str(table), {"BuildingType": building}
                ),
            )
    improvement_identities = catalog.donor_identities("Improvements")
    for improvement in sorted(catalog.improvements):
        identity = improvement_identities.get(improvement, {})
        _insert(
            connection,
            "Improvements",
            _synthetic_row(
                catalog,
                "Improvements",
                {
                    "Type": improvement,
                    "Description": identity.get("Description") or improvement,
                    "Civilopedia": improvement,
                    "Help": improvement,
                    "ArtDefineTag": "ART_DEF_IMPROVEMENT_FARM",
                    "SpecificCivRequired": 0,
                    "CivilizationType": identity.get("CivilizationType"),
                    "PortraitIndex": 0,
                    "IconAtlas": "TERRAIN_ATLAS",
                },
            ),
        )
        for table in sorted(
            catalog.clone_contract("Improvements").get("child_tables", {})
        ):
            _insert(
                connection,
                str(table),
                _synthetic_row(
                    catalog, str(table), {"ImprovementType": improvement}
                ),
            )
    build_identities = catalog.donor_identities("Builds")
    first_unit = next(iter(sorted(catalog.units)), None)
    for build in sorted(catalog.builds):
        identity = build_identities.get(build, {})
        _insert(
            connection,
            "Builds",
            _synthetic_row(
                catalog,
                "Builds",
                {
                    "Type": build,
                    "Description": identity.get("Description") or build,
                    "Help": build,
                    "Recommendation": build,
                    "PrereqTech": "TECH_AGRICULTURE",
                    "ImprovementType": identity.get("ImprovementType"),
                    "IconIndex": 0,
                    "IconAtlas": "BUILD_ATLAS",
                },
            ),
        )
        for table in sorted(
            catalog.clone_contract("Builds").get("child_tables", {})
        ):
            _insert(
                connection,
                str(table),
                _synthetic_row(catalog, str(table), {"BuildType": build}),
            )
        if first_unit is not None:
            _insert(
                connection,
                "Unit_Builds",
                {"UnitType": first_unit, "BuildType": build},
            )
    connection.commit()


def _render_column(definition: dict[str, object] | object) -> str:
    if not isinstance(definition, dict):
        definition = dict(definition)  # type: ignore[arg-type]
    name = str(definition["name"])
    kind = str(definition.get("type", "text")).lower()
    sqlite_kind = "INTEGER" if kind == "boolean" else kind.upper()
    parts = [f'"{name}"', sqlite_kind]
    if definition.get("primarykey"):
        parts.append("PRIMARY KEY")
    if definition.get("autoincrement"):
        parts.append("AUTOINCREMENT")
    if definition.get("notnull"):
        parts.append("NOT NULL")
    if definition.get("unique"):
        parts.append("UNIQUE")
    if "default" in definition:
        parts.extend(("DEFAULT", _render_default(definition["default"], kind)))
    return " ".join(parts)


def _render_default(value: object, kind: str) -> str:
    rendered = str(value).strip()
    if rendered.upper() == "NULL":
        return "NULL"
    if kind == "boolean":
        return "1" if rendered.lower() in {"1", "true"} else "0"
    if kind in {"integer", "real", "float", "numeric"}:
        return rendered
    return "'" + rendered.replace("'", "''") + "'"


def _synthetic_row(
    catalog: ReferenceCatalog,
    table: str,
    overrides: dict[str, object],
) -> dict[str, object]:
    definitions = catalog.column_definitions(table)
    if not definitions:
        return {
            column: overrides.get(column, f"SYNTH_{table}_{column}")
            for column in catalog.ordered_columns(table)
        }
    result: dict[str, object] = {}
    for definition in definitions:
        name = str(definition["name"])
        if name == "ID" and definition.get("autoincrement"):
            continue
        if name in overrides:
            result[name] = overrides[name]
            continue
        kind = str(definition.get("type", "text")).lower()
        if kind == "boolean":
            result[name] = 1
        elif kind in {"integer", "real", "float", "numeric"}:
            result[name] = 7
        else:
            result[name] = f"SYNTH_{table}_{name}"
    return result


def _validate_donor_parity(
    connection: sqlite3.Connection,
    report: ValidationReport,
    project: CivProject,
    catalog: ReferenceCatalog,
) -> None:
    unit_overrides = {
        "Type",
        "Class",
        "Description",
        "Help",
        "Strategy",
        "Civilopedia",
        "Combat",
        "RangedCombat",
        "Moves",
        "Cost",
        "PrereqTech",
        "UnitFlagAtlas",
        "UnitFlagIconOffset",
        "IconAtlas",
        "PortraitIndex",
        "UnitArtInfo",
        "UnitArtInfoCulturalVariation",
        "UnitArtInfoEraVariation",
    }
    building_overrides = {
        "Type",
        "BuildingClass",
        "Description",
        "Help",
        "Strategy",
        "Civilopedia",
        "Cost",
        "GoldMaintenance",
        "Defense",
        "ExtraCityHitPoints",
        "PrereqTech",
        "PortraitIndex",
        "IconAtlas",
    }
    improvement_overrides = {
        "Type",
        "Description",
        "Civilopedia",
        "Help",
        "SpecificCivRequired",
        "CivilizationType",
        "PortraitIndex",
        "IconAtlas",
    }
    build_overrides = {
        "Type",
        "Description",
        "Help",
        "Recommendation",
        "PrereqTech",
        "ImprovementType",
        "IconIndex",
        "IconAtlas",
    }
    ids = project.ids()
    for unit in project.units:
        donor = unit.base_unit or catalog.unit_class_to_base_unit[
            unit.replaces_unit_class
        ]
        _expect_inherited_columns(
            connection,
            report,
            "Units",
            donor,
            ids.units[unit.key],
            tuple(
                column
                for column in catalog.ordered_columns("Units")
                if column not in unit_overrides and column != "ID"
            ),
        )
        child_tables = dict(
            catalog.clone_contract("Units").get("child_tables", {})
        )
        child_tables["UnitGameplay2DScripts"] = catalog.ordered_columns(
            "UnitGameplay2DScripts"
        )
        child_tables["UnitPromotions_CivilianUnitType"] = catalog.ordered_columns(
            "UnitPromotions_CivilianUnitType"
        )
        for table, columns in child_tables.items():
            if table == "Unit_FreePromotions":
                continue
            _expect_child_parity(
                connection,
                report,
                str(table),
                "UnitType",
                donor,
                ids.units[unit.key],
                tuple(str(value) for value in columns),
            )
        if any(
            asset.role is ArtRole.STRATEGIC_VIEW
            and asset.subject_key == f"unit:{unit.key}"
            and bool(asset.source_png.strip())
            for asset in project.art.assets
        ):
            _expect_strategic_view_art(
                connection,
                report,
                donor,
                ids.units[unit.key],
                project.internal_prefix,
                unit.key,
            )
    for building in project.buildings:
        donor = building.base_building or catalog.building_class_to_base_building[
            building.replaces_building_class
        ]
        _expect_inherited_columns(
            connection,
            report,
            "Buildings",
            donor,
            ids.buildings[building.key],
            tuple(
                column
                for column in catalog.ordered_columns("Buildings")
                if column not in building_overrides and column != "ID"
            ),
        )
        child_tables = catalog.clone_contract("Buildings").get("child_tables", {})
        for table, columns in child_tables.items():
            if table in {
                "Building_YieldChanges",
                "Building_DomainFreeExperiences",
            }:
                continue
            _expect_child_parity(
                connection,
                report,
                str(table),
                "BuildingType",
                donor,
                ids.buildings[building.key],
                tuple(str(value) for value in columns),
            )
    for improvement in project.improvements:
        donor = improvement.base_improvement
        custom = ids.improvements[improvement.key]
        _expect_inherited_columns(
            connection,
            report,
            "Improvements",
            donor,
            custom,
            tuple(
                column
                for column in catalog.ordered_columns("Improvements")
                if column not in improvement_overrides and column != "ID"
            ),
        )
        child_tables = catalog.clone_contract("Improvements").get(
            "child_tables", {}
        )
        for table, columns in child_tables.items():
            if table == "Improvement_Yields":
                continue
            _expect_child_parity(
                connection,
                report,
                str(table),
                "ImprovementType",
                donor,
                custom,
                tuple(str(value) for value in columns),
            )
        for donor_build in catalog.builds_for_improvement(donor):
            custom_build = generated_build_type(
                project, improvement.key, donor_build
            )
            _expect_inherited_columns(
                connection,
                report,
                "Builds",
                donor_build,
                custom_build,
                tuple(
                    column
                    for column in catalog.ordered_columns("Builds")
                    if column not in build_overrides and column != "ID"
                ),
            )
            for table, columns in catalog.clone_contract("Builds").get(
                "child_tables", {}
            ).items():
                _expect_child_parity(
                    connection,
                    report,
                    str(table),
                    "BuildType",
                    donor_build,
                    custom_build,
                    tuple(str(value) for value in columns),
                )
            _expect_child_parity(
                connection,
                report,
                "Unit_Builds",
                "BuildType",
                donor_build,
                custom_build,
                catalog.ordered_columns("Unit_Builds"),
            )


def _expect_inherited_columns(
    connection: sqlite3.Connection,
    report: ValidationReport,
    table: str,
    donor: str,
    custom: str,
    columns: tuple[str, ...],
) -> None:
    rendered = ", ".join(f'"{column}"' for column in columns)
    donor_row = connection.execute(
        f'SELECT {rendered} FROM "{table}" WHERE "Type" = ?', (donor,)
    ).fetchone()
    custom_row = connection.execute(
        f'SELECT {rendered} FROM "{table}" WHERE "Type" = ?', (custom,)
    ).fetchone()
    if donor_row != custom_row:
        report.error(
            "generated.donor-parity",
            f"{table}.{custom}",
            "One or more non-overridden donor columns were not preserved.",
        )


def _expect_strategic_view_art(
    connection: sqlite3.Connection,
    report: ValidationReport,
    donor_unit: str,
    custom_unit: str,
    prefix: str,
    unit_key: str,
) -> None:
    donor_art_row = connection.execute(
        'SELECT "UnitArtInfo" FROM "Units" WHERE "Type" = ?', (donor_unit,)
    ).fetchone()
    custom_row = connection.execute(
        'SELECT "UnitArtInfo", "UnitArtInfoCulturalVariation", '
        '"UnitArtInfoEraVariation" FROM "Units" WHERE "Type" = ?',
        (custom_unit,),
    ).fetchone()
    custom_art = f"ART_DEF_{custom_unit}"
    if custom_row != (custom_art, 0, 0):
        report.error(
            "generated.strategic-view-unit-art",
            f"Units.{custom_unit}",
            "Custom Strategic View art lacks an isolated unit art identity.",
        )
        return
    _expect_one(connection, report, "ArtDefine_UnitInfos", "Type", custom_art)
    if donor_art_row:
        _expect_child_parity(
            connection,
            report,
            "ArtDefine_UnitInfoMemberInfos",
            "UnitInfoType",
            str(donor_art_row[0]),
            custom_art,
            ("UnitInfoType", "UnitMemberInfoType", "NumMembers"),
        )
    strategic = connection.execute(
        "SELECT TileType, Asset FROM ArtDefine_StrategicView "
        "WHERE StrategicViewType = ?",
        (custom_art,),
    ).fetchall()
    expected = [("Unit", f"SV_{prefix}_{unit_key}.dds")]
    if strategic != expected:
        report.error(
            "generated.strategic-view-binding",
            f"ArtDefine_StrategicView.{custom_art}",
            "Strategic View database binding does not match the generated DDS.",
        )


def _expect_child_parity(
    connection: sqlite3.Connection,
    report: ValidationReport,
    table: str,
    key_column: str,
    donor: str,
    custom: str,
    columns: tuple[str, ...],
) -> None:
    compared = tuple(column for column in columns if column != key_column)
    rendered = ", ".join(f'"{column}"' for column in compared)
    donor_rows = connection.execute(
        f'SELECT {rendered} FROM "{table}" WHERE "{key_column}" = ?', (donor,)
    ).fetchall()
    custom_rows = connection.execute(
        f'SELECT {rendered} FROM "{table}" WHERE "{key_column}" = ?', (custom,)
    ).fetchall()
    if sorted(donor_rows, key=repr) != sorted(custom_rows, key=repr):
        report.error(
            "generated.child-donor-parity",
            f"{table}.{custom}",
            "Generated child rows do not match the donor relationship rows.",
        )


def _insert(
    connection: sqlite3.Connection, table: str, values: dict[str, object]
) -> None:
    columns = ", ".join(f'"{column}"' for column in values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})', tuple(values.values())
    )


def _expect_one(
    connection: sqlite3.Connection,
    report: ValidationReport,
    table: str,
    column: str,
    value: str,
) -> None:
    count = connection.execute(
        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" = ?', (value,)
    ).fetchone()[0]
    if count != 1:
        report.error(
            "generated.row-count",
            f"{table}.{value}",
            f"Expected one generated row, found {count}.",
        )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()
