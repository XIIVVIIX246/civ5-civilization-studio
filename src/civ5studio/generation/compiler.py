"""Deterministic SQL/XML/Lua/text/documentation compiler for Civ V BNW."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from typing import Iterable, Mapping
import xml.etree.ElementTree as ET

from civ5studio.application.advanced_content import (
    advanced_content,
    audio_sql,
    build_copies,
    custom_unit_art_assignment,
    dawn_audio_script,
    localization_xml_files,
    soundtrack_tag,
)
from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain.ids import safe_folder_name, type_component
from civ5studio.domain.models import ArtRole, CivProject, MechanicEffect
from civ5studio.domain.recipes import iter_recipes
from civ5studio.domain.serialization import dumps_project
from civ5studio.domain.validation import (
    Severity,
    ValidationReport,
    is_portable_relative_path,
    validate_project,
)
from civ5studio.integrations import (
    PEP_MOD_ID,
    PEP_MOD_NAME,
    PEP_MOD_VERSION,
    PromotionsExpansionPackCatalog,
)

from .contracts import (
    ALPHA_ATLAS_SIZES,
    ATLAS_GRID,
    DATABASE_FILE_ORDER,
    DEFAULT_LEADER_FLAVORS,
    DEFAULT_MAJOR_CIV_BIASES,
    DEFAULT_MINOR_CIV_BIASES,
    MAIN_ATLAS_SIZES,
    PORTRAIT_FIT_DIAMETER,
    PORTRAIT_REFERENCE_SIZE,
    REQUIRED_SCHEMA,
)
from .advanced import (
    advanced_capability_markdown,
    advanced_capability_payload,
    generate_custom_unit_member_sql,
)
from .lua_runtime import (
    generate_lua_runtime,
    lua_effect_manifest_json,
    lua_effect_manifest_markdown,
    selected_lua_effects,
)


@dataclass(frozen=True, slots=True)
class Compilation:
    files: Mapping[str, str]
    source_files: Mapping[str, str]
    database_files: tuple[str, ...]
    lua_files: tuple[str, ...]
    vfs_files: tuple[str, ...]
    expected_art_files: tuple[str, ...]
    available_art_files: tuple[str, ...]
    art_manifest: Mapping[str, object]
    report: ValidationReport

    @property
    def inventory(self) -> tuple[str, ...]:
        return tuple([*self.files, *self.source_files])


class CompilationError(RuntimeError):
    def __init__(self, report: ValidationReport):
        self.report = report
        summary = "; ".join(f"{item.path}: {item.message}" for item in report.errors[:4])
        super().__init__(f"Project compilation blocked by validation errors: {summary}")


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    path: str
    width: int
    height: int
    profile: str
    surface_count: int = 1
    mip_count: int = 1


def project_folder_name(project: CivProject) -> str:
    return safe_folder_name(project.mod_name)


def modinfo_filename(project: CivProject) -> str:
    return f"{project_folder_name(project)}.modinfo"


def generated_build_type(
    project: CivProject, improvement_key: str, donor_build_type: str
) -> str:
    """Return a stable custom build identity for one donor worker action."""

    donor = type_component(donor_build_type.removeprefix("BUILD_")) or "ACTION"
    return (
        f"BUILD_{type_component(improvement_key)}_"
        f"{project.internal_prefix}_{donor}"
    )


def compile_project(
    project: CivProject,
    catalog: ReferenceCatalog | None = None,
    *,
    strict_release: bool = False,
    project_root: str | None = None,
    available_art_files: Iterable[str] = (),
    rendered_artifacts: Iterable[RenderedArtifact] = (),
) -> Compilation:
    """Compile a validated project into deterministic generated text files.

    ``available_art_files`` contains already-rendered, project-relative Art/
    paths supplied by the separate art service. This compiler never renders or
    invents DDS files.
    """

    catalog = catalog or ReferenceCatalog.bundled()
    report = validate_project(
        project, catalog, strict_release=strict_release, project_root=project_root
    )
    missing_schema = catalog.missing_schema_references(REQUIRED_SCHEMA)
    for reference in missing_schema:
        report.error(
            "generation.schema-reference",
            "bnw.reference_catalog",
            f"Generator requires unverified {reference}.",
        )
    _validate_clone_contracts(catalog, report)

    artifact_metadata: dict[str, RenderedArtifact] = {}
    supplied_paths = list(available_art_files)
    for artifact in rendered_artifacts:
        supplied_paths.append(artifact.path)
        artifact_metadata[artifact.path.replace("\\", "/")] = artifact
    normalized_art: set[str] = set()
    for value in supplied_paths:
        normalized = str(value).replace("\\", "/")
        if not is_portable_relative_path(normalized) or not normalized.startswith("Art/"):
            report.error(
                "path.unsafe-artifact",
                "available_art_files",
                f"Rendered artifact path is unsafe or outside Art/: {value!r}.",
            )
        else:
            normalized_art.add(str(PurePosixPath(normalized)))

    art_manifest = generate_art_manifest(project)
    expected_art = {
        str(item["path"]) for item in art_manifest["outputs"] if item.get("required", True)
    }
    expected_by_path = {str(item["path"]): item for item in art_manifest["outputs"]}
    for unexpected in sorted(normalized_art - expected_art):
        report.error(
            "art.unexpected-output",
            "available_art_files",
            f"Rendered file is not declared by ART_MANIFEST.json: {unexpected}",
        )
    if strict_release:
        for missing in sorted(expected_art - normalized_art):
            report.error(
                "art.output-missing",
                "available_art_files",
                f"Strict release requires rendered art output: {missing}",
            )
        for path in sorted(expected_art & normalized_art):
            if path not in artifact_metadata:
                report.error(
                    "art.geometry-unverified",
                    "rendered_artifacts",
                    f"Strict release requires verified geometry/profile metadata for {path}.",
                )
    for path, artifact in sorted(artifact_metadata.items()):
        if path not in expected_by_path:
            continue
        expected = expected_by_path[path]
        comparisons = {
            "width": artifact.width,
            "height": artifact.height,
            "profile": artifact.profile,
            "surface_count": artifact.surface_count,
            "mip_count": artifact.mip_count,
        }
        for field, actual in comparisons.items():
            required = expected.get(field)
            if actual != required:
                report.error(
                    "art.contract-mismatch",
                    f"rendered_artifacts.{path}.{field}",
                    f"Expected {required!r}, found {actual!r}.",
                )
    advanced = advanced_content(project)
    if (advanced.unit_art or advanced.audio.populated()) and not project_root:
        report.error(
            "generation.advanced-project-root",
            "advanced",
            "Custom unit art and audio require a saved project workspace during compilation.",
        )
    if report.errors:
        raise CompilationError(report.sorted())

    localization_files = localization_xml_files(project)
    generated_audio_sql = audio_sql(project)
    database_file_list = list(DATABASE_FILE_ORDER)
    if localization_files:
        text_index = database_file_list.index("Core/Text.sql") + 1
        database_file_list[text_index:text_index] = sorted(localization_files)
    if generated_audio_sql:
        civilization_index = database_file_list.index("Core/Civilization.sql")
        database_file_list.insert(civilization_index, "Core/Audio.sql")
    database_files = tuple(database_file_list)
    lua_files = ("Lua/CivilizationRuntime.lua",)
    leader_xml = leaderhead_xml_path(project)
    copy_rows = build_copies(project, project_root) if project_root else ()
    source_files = {
        item.output_relative: item.source_relative for item in copy_rows
    }
    vfs_files = (leader_xml, *sorted(source_files), *sorted(normalized_art))

    files: dict[str, str] = {}
    files["Core/Text.sql"] = generate_text_sql(project, catalog)
    files["Core/Colors.sql"] = generate_colors_sql(project)
    files["Core/IconAtlases.sql"] = generate_icon_atlases_sql(project)
    files["Core/Trait.sql"] = generate_trait_sql(project)
    files["Core/Leader.sql"] = generate_leader_sql(project, catalog)
    files["Core/Units.sql"] = generate_units_sql(project, catalog)
    files["Core/Buildings.sql"] = generate_buildings_sql(project, catalog)
    files["Core/Improvements.sql"] = generate_improvements_sql(project, catalog)
    if generated_audio_sql:
        files["Core/Audio.sql"] = generated_audio_sql
    files["Core/Civilization.sql"] = generate_civilization_sql(project)
    files.update(localization_files)
    files["Lua/CivilizationRuntime.lua"] = generate_runtime_lua(project)
    files[leader_xml] = generate_leaderhead_xml(project)
    files["Documentation/ART_MANIFEST.json"] = (
        json.dumps(art_manifest, indent=2, ensure_ascii=False) + "\n"
    )
    files["Documentation/BNW_REFERENCE_PROVENANCE.json"] = (
        json.dumps(dict(catalog.provenance), indent=2, ensure_ascii=False) + "\n"
    )
    files["Documentation/ADVANCED_CONTENT_RUNTIME_GATES.json"] = (
        json.dumps(
            advanced_capability_payload(project), indent=2, ensure_ascii=False
        )
        + "\n"
    )
    files["Documentation/ADVANCED_CONTENT_RUNTIME_GATES.md"] = (
        advanced_capability_markdown(project)
    )
    files["Documentation/LUA_EFFECT_MANIFEST.json"] = (
        lua_effect_manifest_json(project)
    )
    files["Documentation/LUA_EFFECT_MANIFEST.md"] = (
        lua_effect_manifest_markdown(project)
    )
    if project.dependencies.promotions_expansion_pack:
        pep_catalog = PromotionsExpansionPackCatalog.bundled()
        files["Documentation/PROMOTIONS_EXPANSION_PACK_REFERENCE.json"] = (
            json.dumps(
                {
                    "mod": {
                        "id": pep_catalog.mod_id,
                        "version": pep_catalog.version,
                        "name": pep_catalog.name,
                        "authors": pep_catalog.authors,
                    },
                    "evidence": list(pep_catalog.evidence),
                    "assigned_types": sorted(
                        {
                            promotion
                            for unit in project.units
                            for promotion in unit.promotions_expansion_pack
                        }
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    capability_report = generate_capability_report(
        project, catalog, report, strict_release=strict_release
    )
    files["Documentation/CAPABILITY_REPORT.json"] = (
        json.dumps(capability_report, indent=2, ensure_ascii=False) + "\n"
    )
    files["Documentation/CAPABILITY_REPORT.md"] = generate_capability_markdown(
        project, capability_report
    )
    files["Documentation/BUILD_CHECKLIST.md"] = generate_build_checklist(project)
    files["Documentation/GENERATED_SUMMARY.md"] = generate_summary(project)
    files["Documentation/UNIMPLEMENTED_EFFECTS.md"] = generate_unimplemented(project)
    files["Documentation/VALIDATION_REPORT.md"] = generate_validation_report(project, report)
    files["Documentation/PROJECT_SNAPSHOT.civ5project.json"] = dumps_project(project)
    files[modinfo_filename(project)] = generate_modinfo(
        project, database_files, lua_files, vfs_files
    )
    return Compilation(
        files=files,
        source_files=source_files,
        database_files=database_files,
        lua_files=lua_files,
        vfs_files=vfs_files,
        expected_art_files=tuple(sorted(expected_art)),
        available_art_files=tuple(sorted(normalized_art)),
        art_manifest=art_manifest,
        report=report.sorted(),
    )


def _header(filename: str, project: CivProject) -> str:
    safe_mod_name = "".join(
        " " if ord(character) < 32 or character in "\u0085\u2028\u2029" else character
        for character in project.mod_name
    )
    return (
        f"-- {filename}\n"
        f"-- Mod: {safe_mod_name}\n"
        "-- Generated deterministically by Civ V Civilization Studio.\n"
        "-- Target: Civilization V Brave New World / Expansion2.\n\n"
    )


def sql_string(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _text_keys(project: CivProject, catalog: ReferenceCatalog) -> dict[str, str]:
    prefix = project.internal_prefix
    civ = project.civilization
    leader = project.leader
    trait = project.trait
    values = {
        f"TXT_KEY_CIV_{prefix}_DESC": civ.name,
        f"TXT_KEY_CIV_{prefix}_SHORT_DESC": civ.short_name,
        f"TXT_KEY_CIV_{prefix}_ADJECTIVE": civ.adjective,
        f"TXT_KEY_PEDIA_{prefix}_TEXT": civ.civilopedia or civ.name,
        f"TXT_KEY_CIV5_DOM_{prefix}_TEXT": civ.dawn_of_man_quote,
        f"TXT_KEY_LEADER_{leader.key}_{prefix}": leader.name,
        f"TXT_KEY_LEADER_{leader.key}_{prefix}_PEDIA": leader.civilopedia or leader.name,
        f"TXT_KEY_TRAIT_{trait.key}_{prefix}": trait.long_description,
        f"TXT_KEY_TRAIT_{trait.key}_{prefix}_SHORT": trait.short_description,
    }
    for index, name in enumerate(civ.city_names, start=1):
        values[f"TXT_KEY_CITY_NAME_{prefix}_{index:02d}"] = name
    for index, name in enumerate(civ.spy_names, start=1):
        values[f"TXT_KEY_SPY_NAME_{prefix}_{index:02d}"] = name
    for unit in project.units:
        base = f"TXT_KEY_UNIT_{unit.key}_{prefix}"
        values[base] = unit.name
        values[f"{base}_HELP"] = unit.help_text or unit.name
        values[f"{base}_STRATEGY"] = unit.strategy_text or unit.help_text or unit.name
        values[f"{base}_PEDIA"] = unit.help_text or unit.name
    for building in project.buildings:
        base = f"TXT_KEY_BUILDING_{building.key}_{prefix}"
        values[base] = building.name
        values[f"{base}_HELP"] = building.help_text or building.name
        values[f"{base}_STRATEGY"] = (
            building.strategy_text or building.help_text or building.name
        )
        values[f"{base}_PEDIA"] = building.help_text or building.name
    for improvement in project.improvements:
        base = f"TXT_KEY_IMPROVEMENT_{improvement.key}_{prefix}"
        values[base] = improvement.name
        values[f"{base}_HELP"] = improvement.help_text or improvement.name
        values[f"{base}_STRATEGY"] = (
            improvement.strategy_text or improvement.help_text or improvement.name
        )
        values[f"{base}_PEDIA"] = (
            improvement.civilopedia_text
            or improvement.help_text
            or improvement.name
        )
        for donor_build in catalog.builds_for_improvement(
            improvement.base_improvement
        ):
            suffix = type_component(donor_build.removeprefix("BUILD_")) or "ACTION"
            build_key = f"TXT_KEY_BUILD_{improvement.key}_{prefix}_{suffix}"
            values[build_key] = f"Build {improvement.name}"
            values[f"{build_key}_HELP"] = (
                improvement.help_text or f"Construct {improvement.name}."
            )
            values[f"{build_key}_RECOMMENDATION"] = (
                improvement.strategy_text
                or improvement.help_text
                or f"Construct {improvement.name}."
            )

    defaults = {
        "RESPONSE_FIRST_GREETING": (
            f"Greetings. I am {leader.name}, and I speak for {civ.short_name}."
        ),
        "RESPONSE_DEFEATED": "Our realm has fallen, but our people will remember.",
        "RESPONSE_DOW_GENERIC": "You leave us no choice. Prepare yourself.",
        "RESPONSE_WORK_AGAINST_SOMEONE": "We will consider acting together.",
        "RESPONSE_WORK_WITH_US": "Cooperation may benefit both our peoples.",
    }
    for response in sorted(catalog.values("diplomacy_responses")):
        key = f"TXT_KEY_LEADER_{leader.key}_{prefix}_{response.removeprefix('RESPONSE_')}"
        values[key] = leader.diplomacy_text.get(response, defaults.get(response, leader.name))
    return values


def generate_text_sql(project: CivProject, catalog: ReferenceCatalog) -> str:
    rows = [
        f"  ({sql_string(key)}, {sql_string(text)})"
        for key, text in sorted(_text_keys(project, catalog).items())
    ]
    return (
        _header("Text.sql", project)
        + "INSERT INTO Language_en_US (Tag, Text) VALUES\n"
        + ",\n".join(rows)
        + ";\n"
    )


def generate_colors_sql(project: CivProject) -> str:
    ids = project.ids()
    color = project.colors
    return _header("Colors.sql", project) + f"""INSERT INTO Colors
  (Type, Red, Green, Blue, Alpha)
VALUES
  ({sql_string(ids.primary_color)}, {color.primary_red}, {color.primary_green}, {color.primary_blue}, {color.primary_alpha}),
  ({sql_string(ids.secondary_color)}, {color.secondary_red}, {color.secondary_green}, {color.secondary_blue}, {color.secondary_alpha});

INSERT INTO PlayerColors
  (Type, PrimaryColor, SecondaryColor, TextColor)
VALUES
  ({sql_string(ids.player_color)}, {sql_string(ids.primary_color)}, {sql_string(ids.secondary_color)}, 'COLOR_PLAYER_WHITE_TEXT');
"""


def generate_icon_atlases_sql(project: CivProject) -> str:
    ids = project.ids()
    prefix = project.internal_prefix
    rows: list[str] = []
    for size in MAIN_ATLAS_SIZES:
        rows.append(
            f"  ({sql_string(ids.main_atlas)}, {size}, "
            f"{sql_string(f'{prefix}_Atlas_{size}.dds')}, 8, 8)"
        )
    for size in ALPHA_ATLAS_SIZES:
        rows.append(
            f"  ({sql_string(ids.alpha_atlas)}, {size}, "
            f"{sql_string(f'{prefix}_Alpha_{size}.dds')}, 8, 8)"
        )
    for unit in project.units:
        rows.append(
            f"  ({sql_string(ids.unit_flag_atlases[unit.key])}, 32, "
            f"{sql_string(f'{prefix}_Flag_{unit.key}_32.dds')}, 8, 8)"
        )
    return (
        _header("IconAtlases.sql", project)
        + "INSERT INTO IconTextureAtlases\n"
        + "  (Atlas, IconSize, Filename, IconsPerRow, IconsPerColumn)\nVALUES\n"
        + ",\n".join(rows)
        + ";\n"
    )


def generate_trait_sql(project: CivProject) -> str:
    ids = project.ids()
    trait = project.trait
    columns = ["Type", "Description", "ShortDescription"]
    values = [
        sql_string(ids.trait),
        sql_string(f"TXT_KEY_TRAIT_{trait.key}_{project.internal_prefix}"),
        sql_string(f"TXT_KEY_TRAIT_{trait.key}_{project.internal_prefix}_SHORT"),
    ]
    for column, value in sorted(trait.database_modifiers.items()):
        columns.append(column)
        values.append("1" if value is True else "0" if value is False else str(value))
    return (
        _header("Trait.sql", project)
        + "INSERT INTO Traits\n"
        + f"  ({', '.join(columns)})\nVALUES\n"
        + f"  ({', '.join(values)});\n"
    )


def generate_leader_sql(project: CivProject, catalog: ReferenceCatalog) -> str:
    ids = project.ids()
    leader = project.leader
    prefix = project.internal_prefix
    art_tag = PurePosixPath(leaderhead_xml_path(project)).name
    columns = (
        "Type, Description, Civilopedia, CivilopediaTag, ArtDefineTag, "
        "VictoryCompetitiveness, WonderCompetitiveness, MinorCivCompetitiveness, "
        "Boldness, DiploBalance, WarmongerHate, DenounceWillingness, DoFWillingness, "
        "Loyalty, Neediness, Forgiveness, Chattiness, Meanness, IconAtlas, PortraitIndex"
    )
    values = [
        sql_string(ids.leader),
        sql_string(f"TXT_KEY_LEADER_{leader.key}_{prefix}"),
        sql_string(f"TXT_KEY_LEADER_{leader.key}_{prefix}_PEDIA"),
        sql_string(f"TXT_KEY_LEADER_{leader.key}_{prefix}"),
        sql_string(art_tag),
        str(leader.victory_competitiveness), str(leader.wonder_competitiveness),
        str(leader.minor_civ_competitiveness), str(leader.boldness),
        str(leader.diplo_balance), str(leader.warmonger_hate),
        str(leader.denounce_willingness), str(leader.dof_willingness),
        str(leader.loyalty), str(leader.neediness), str(leader.forgiveness),
        str(leader.chattiness), str(leader.meanness), sql_string(ids.main_atlas), "1",
    ]
    lines = [
        _header("Leader.sql", project),
        f"INSERT INTO Leaders ({columns}) VALUES\n  ({', '.join(values)});\n\n",
    ]
    major = {**DEFAULT_MAJOR_CIV_BIASES, **leader.major_civ_approach_biases}
    minor = {**DEFAULT_MINOR_CIV_BIASES, **leader.minor_civ_approach_biases}
    flavors = {**DEFAULT_LEADER_FLAVORS, **leader.flavors}
    lines.append(_multi_insert(
        "Leader_MajorCivApproachBiases",
        ("LeaderType", "MajorCivApproachType", "Bias"),
        [(ids.leader, key, value) for key, value in sorted(major.items())],
    ))
    lines.append(_multi_insert(
        "Leader_MinorCivApproachBiases",
        ("LeaderType", "MinorCivApproachType", "Bias"),
        [(ids.leader, key, value) for key, value in sorted(minor.items())],
    ))
    lines.append(_multi_insert(
        "Leader_Flavors",
        ("LeaderType", "FlavorType", "Flavor"),
        [(ids.leader, key, value) for key, value in sorted(flavors.items())],
    ))
    lines.append(_multi_insert(
        "Leader_Traits", ("LeaderType", "TraitType"), [(ids.leader, ids.trait)]
    ))
    response_rows = []
    for response in sorted(catalog.values("diplomacy_responses")):
        text_key = (
            f"TXT_KEY_LEADER_{leader.key}_{prefix}_{response.removeprefix('RESPONSE_')}"
        )
        response_rows.append((ids.leader, response, text_key, 500))
    lines.append(_multi_insert(
        "Diplomacy_Responses",
        ("LeaderType", "ResponseType", "Response", "Bias"),
        response_rows,
    ))
    return "".join(lines)


def generate_units_sql(project: CivProject, catalog: ReferenceCatalog) -> str:
    ids = project.ids()
    prefix = project.internal_prefix
    lines = [_header("Units.sql", project)]
    contract = catalog.clone_contract("Units")
    columns = tuple(str(value) for value in contract.get("columns", ()))
    child_tables = contract.get("child_tables", {})
    for index, unit in enumerate(project.units):
        custom = ids.units[unit.key]
        base = unit.base_unit or catalog.unit_class_to_base_unit[unit.replaces_unit_class]
        strategic_view_path = _strategic_view_output_path(project, unit.key)
        custom_unit_art = custom_unit_art_assignment(project, unit.key)
        dedicated_art = bool(strategic_view_path or custom_unit_art)
        desc = f"TXT_KEY_UNIT_{unit.key}_{prefix}"
        overrides = {
            "Type": sql_string(custom),
            "Class": sql_string(unit.replaces_unit_class),
            "Description": sql_string(desc),
            "Help": sql_string(f"{desc}_HELP"),
            "Strategy": sql_string(f"{desc}_STRATEGY"),
            "Civilopedia": sql_string(f"{desc}_PEDIA"),
            "Combat": _override(unit.combat, "Combat"),
            "RangedCombat": _override(unit.ranged_combat, "RangedCombat"),
            "Moves": _override(unit.moves, "Moves"),
            "Cost": _override(unit.cost, "Cost"),
            "PrereqTech": (
                sql_string(unit.prereq_tech)
                if unit.prereq_tech is not None
                else "PrereqTech"
            ),
            "UnitFlagAtlas": sql_string(ids.unit_flag_atlases[unit.key]),
            "UnitFlagIconOffset": "0",
            "IconAtlas": sql_string(ids.main_atlas),
            "PortraitIndex": str(2 + index),
        }
        if dedicated_art:
            overrides.update(
                {
                    "UnitArtInfo": sql_string(f"ART_DEF_{custom}"),
                    "UnitArtInfoCulturalVariation": "0",
                    "UnitArtInfoEraVariation": "0",
                }
            )
        lines.append(f"-- Unique unit: {unit.name}\n")
        lines.append(
            _clone_row_sql(
                "Units",
                columns,
                identity_column="Type",
                donor_identity=base,
                overrides=overrides,
                omitted_columns=("ID",),
            )
        )
        for table, table_columns in sorted(child_tables.items()):
            lines.append(
                _clone_child_rows_sql(
                    str(table),
                    tuple(str(value) for value in table_columns),
                    key_column="UnitType",
                    donor_identity=base,
                    custom_identity=custom,
                )
            )
        gameplay_columns = catalog.ordered_columns("UnitGameplay2DScripts")
        if gameplay_columns:
            lines.append(
                _clone_child_rows_sql(
                    "UnitGameplay2DScripts",
                    gameplay_columns,
                    key_column="UnitType",
                    donor_identity=base,
                    custom_identity=custom,
                )
            )
        civilian_promotion_columns = catalog.ordered_columns(
            "UnitPromotions_CivilianUnitType"
        )
        if civilian_promotion_columns:
            lines.append(
                _clone_child_rows_sql(
                    "UnitPromotions_CivilianUnitType",
                    civilian_promotion_columns,
                    key_column="UnitType",
                    donor_identity=base,
                    custom_identity=custom,
                )
            )
        if dedicated_art:
            lines.append(
                _clone_unit_art_definitions_sql(
                    catalog,
                    donor_unit=base,
                    custom_art_type=f"ART_DEF_{custom}",
                    strategic_view_asset=(
                        PurePosixPath(strategic_view_path).name
                        if strategic_view_path
                        else ""
                    ),
                )
            )
        if custom_unit_art is not None:
            lines.append(
                generate_custom_unit_member_sql(
                    project,
                    catalog,
                    unit,
                    donor_unit=base,
                    custom_art_type=f"ART_DEF_{custom}",
                )
            )
        for promotion in unit.free_promotions:
            lines.append(
                "INSERT INTO Unit_FreePromotions (UnitType, PromotionType)\n"
                f"SELECT {sql_string(custom)}, {sql_string(promotion)}\n"
                "WHERE NOT EXISTS (SELECT 1 FROM Unit_FreePromotions "
                f"WHERE UnitType = {sql_string(custom)} AND PromotionType = "
                f"{sql_string(promotion)});\n\n"
            )
        if project.dependencies.promotions_expansion_pack:
            for promotion in unit.promotions_expansion_pack:
                lines.append(
                    "-- Promotions - Expansion Pack v9 assignment\n"
                    "INSERT INTO Unit_FreePromotions (UnitType, PromotionType)\n"
                    f"SELECT {sql_string(custom)}, {sql_string(promotion)}\n"
                    "WHERE NOT EXISTS (SELECT 1 FROM Unit_FreePromotions "
                    f"WHERE UnitType = {sql_string(custom)} AND PromotionType = "
                    f"{sql_string(promotion)});\n\n"
                )
    if not project.units:
        lines.append("-- No unique units configured.\n")
    return "".join(lines)


def generate_buildings_sql(project: CivProject, catalog: ReferenceCatalog) -> str:
    ids = project.ids()
    prefix = project.internal_prefix
    lines = [_header("Buildings.sql", project)]
    contract = catalog.clone_contract("Buildings")
    columns = tuple(str(value) for value in contract.get("columns", ()))
    child_tables = contract.get("child_tables", {})
    for index, building in enumerate(project.buildings):
        custom = ids.buildings[building.key]
        base = building.base_building or catalog.building_class_to_base_building[
            building.replaces_building_class
        ]
        desc = f"TXT_KEY_BUILDING_{building.key}_{prefix}"
        overrides = {
            "Type": sql_string(custom),
            "BuildingClass": sql_string(building.replaces_building_class),
            "Description": sql_string(desc),
            "Help": sql_string(f"{desc}_HELP"),
            "Strategy": sql_string(f"{desc}_STRATEGY"),
            "Civilopedia": sql_string(f"{desc}_PEDIA"),
            "Cost": _override(building.cost, "Cost"),
            "GoldMaintenance": _override(
                building.gold_maintenance, "GoldMaintenance"
            ),
            "Defense": _override(building.defense, "Defense"),
            "ExtraCityHitPoints": _override(
                building.extra_city_hit_points, "ExtraCityHitPoints"
            ),
            "PrereqTech": (
                sql_string(building.prereq_tech)
                if building.prereq_tech is not None
                else "PrereqTech"
            ),
            "PortraitIndex": str(2 + len(project.units) + index),
            "IconAtlas": sql_string(ids.main_atlas),
        }
        lines.append(f"-- Unique building: {building.name}\n")
        lines.append(
            _clone_row_sql(
                "Buildings",
                columns,
                identity_column="Type",
                donor_identity=base,
                overrides=overrides,
                omitted_columns=("ID",),
            )
        )
        for table, table_columns in sorted(child_tables.items()):
            lines.append(
                _clone_child_rows_sql(
                    str(table),
                    tuple(str(value) for value in table_columns),
                    key_column="BuildingType",
                    donor_identity=base,
                    custom_identity=custom,
                )
            )
        for change in building.yield_changes:
            lines.append(
                "UPDATE Building_YieldChanges SET Yield = Yield + "
                f"{change.amount} WHERE BuildingType = {sql_string(custom)} "
                f"AND YieldType = {sql_string(change.yield_type)};\n"
                "INSERT INTO Building_YieldChanges (BuildingType, YieldType, Yield)\n"
                f"SELECT {sql_string(custom)}, {sql_string(change.yield_type)}, {change.amount}\n"
                "WHERE NOT EXISTS (SELECT 1 FROM Building_YieldChanges "
                f"WHERE BuildingType = {sql_string(custom)} AND YieldType = "
                f"{sql_string(change.yield_type)});\n\n"
            )
        for change in building.domain_free_experience:
            lines.append(
                "UPDATE Building_DomainFreeExperiences SET Experience = Experience + "
                f"{change.amount} WHERE BuildingType = {sql_string(custom)} "
                f"AND DomainType = {sql_string(change.domain_type)};\n"
                "INSERT INTO Building_DomainFreeExperiences "
                "(BuildingType, DomainType, Experience)\n"
                f"SELECT {sql_string(custom)}, {sql_string(change.domain_type)}, {change.amount}\n"
                "WHERE NOT EXISTS (SELECT 1 FROM Building_DomainFreeExperiences "
                f"WHERE BuildingType = {sql_string(custom)} AND DomainType = "
                f"{sql_string(change.domain_type)});\n\n"
            )
    if not project.buildings:
        lines.append("-- No unique buildings configured.\n")
    return "".join(lines)


def generate_civilization_sql(project: CivProject) -> str:
    ids = project.ids()
    civ = project.civilization
    prefix = project.internal_prefix
    custom_soundtrack = soundtrack_tag(project)
    custom_dawn_audio = dawn_audio_script(project)
    soundtrack_expression = (
        sql_string(custom_soundtrack) if custom_soundtrack else "SoundtrackTag"
    )
    dawn_audio_expression = (
        sql_string(custom_dawn_audio) if custom_dawn_audio else "DawnOfManAudio"
    )
    lines = [_header("Civilization.sql", project)]
    lines.append(f"""INSERT INTO Civilizations
  (Type, Description, ShortDescription, Adjective, Civilopedia, CivilopediaTag,
   DefaultPlayerColor, ArtDefineTag, ArtStyleType, ArtStyleSuffix, ArtStylePrefix,
   PortraitIndex, IconAtlas, AlphaIconAtlas, SoundtrackTag, MapImage,
   DawnOfManQuote, DawnOfManImage, DawnOfManAudio)
SELECT
  {sql_string(ids.civilization)},
  {sql_string(f'TXT_KEY_CIV_{prefix}_DESC')},
  {sql_string(f'TXT_KEY_CIV_{prefix}_SHORT_DESC')},
  {sql_string(f'TXT_KEY_CIV_{prefix}_ADJECTIVE')},
  {sql_string(f'TXT_KEY_PEDIA_{prefix}_TEXT')},
  {sql_string(f'TXT_KEY_PEDIA_{prefix}')},
  {sql_string(ids.player_color)}, ArtDefineTag, ArtStyleType, ArtStyleSuffix, ArtStylePrefix,
  0, {sql_string(ids.main_atlas)}, {sql_string(ids.alpha_atlas)}, {soundtrack_expression},
  {sql_string(f'{prefix}_map.dds')}, {sql_string(f'TXT_KEY_CIV5_DOM_{prefix}_TEXT')},
  {sql_string(f'{prefix}_DOM.dds')}, {dawn_audio_expression}
FROM Civilizations WHERE Type = {sql_string(civ.base_civilization)};

""")
    city_rows = [
        (ids.civilization, f"TXT_KEY_CITY_NAME_{prefix}_{index:02d}")
        for index, _ in enumerate(civ.city_names, start=1)
    ]
    lines.append(_multi_insert(
        "Civilization_CityNames", ("CivilizationType", "CityName"), city_rows
    ))
    spy_rows = [
        (ids.civilization, f"TXT_KEY_SPY_NAME_{prefix}_{index:02d}")
        for index, _ in enumerate(civ.spy_names, start=1)
    ]
    if spy_rows:
        lines.append(_multi_insert(
            "Civilization_SpyNames", ("CivilizationType", "SpyName"), spy_rows
        ))
    lines.append(f"""INSERT INTO Civilization_FreeBuildingClasses
  (CivilizationType, BuildingClassType)
SELECT {sql_string(ids.civilization)}, BuildingClassType
FROM Civilization_FreeBuildingClasses
WHERE CivilizationType = {sql_string(civ.copy_free_buildings_from)};

INSERT INTO Civilization_FreeTechs (CivilizationType, TechType)
SELECT {sql_string(ids.civilization)}, TechType FROM Civilization_FreeTechs
WHERE CivilizationType = {sql_string(civ.copy_free_techs_and_units_from)};

INSERT INTO Civilization_FreeUnits
  (CivilizationType, UnitClassType, Count, UnitAIType)
SELECT {sql_string(ids.civilization)}, UnitClassType, Count, UnitAIType
FROM Civilization_FreeUnits
WHERE CivilizationType = {sql_string(civ.copy_free_techs_and_units_from)};

""")
    lines.append(_multi_insert(
        "Civilization_Leaders",
        ("CivilizationType", "LeaderheadType"),
        [(ids.civilization, ids.leader)],
    ))
    if project.units:
        lines.append(_multi_insert(
            "Civilization_UnitClassOverrides",
            ("CivilizationType", "UnitClassType", "UnitType"),
            [
                (ids.civilization, unit.replaces_unit_class, ids.units[unit.key])
                for unit in project.units
            ],
        ))
    if project.buildings:
        lines.append(_multi_insert(
            "Civilization_BuildingClassOverrides",
            ("CivilizationType", "BuildingClassType", "BuildingType"),
            [
                (
                    ids.civilization,
                    building.replaces_building_class,
                    ids.buildings[building.key],
                )
                for building in project.buildings
            ],
        ))
    if civ.start_region_avoid:
        lines.append(_multi_insert(
            "Civilization_Start_Region_Avoid",
            ("CivilizationType", "RegionType"),
            [(ids.civilization, civ.start_region_avoid)],
        ))
    return "".join(lines)


def generate_runtime_lua(project: CivProject) -> str:
    return generate_lua_runtime(project)


def leaderhead_xml_path(project: CivProject) -> str:
    return (
        f"Art/Leaders/Leaderhead_{project.leader.key}_{project.internal_prefix}.xml"
    )


def generate_leaderhead_xml(project: CivProject) -> str:
    prefix = project.internal_prefix
    root = ET.Element("LeaderScene", {"FallbackImage": f"{prefix}_fallback.dds"})
    ET.SubElement(root, "Image").text = f"{prefix}_scene.dds"
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="unicode", short_empty_elements=True
    ) + "\n"


def generate_modinfo(
    project: CivProject,
    database_files: Iterable[str],
    lua_files: Iterable[str],
    vfs_files: Iterable[str],
) -> str:
    root = ET.Element("Mod", {"id": project.mod_id, "version": str(project.mod_version)})
    properties = ET.SubElement(root, "Properties")
    has_gameplay_lua = bool(project.lua_effects)
    property_values = {
        "Name": project.mod_name,
        "Teaser": project.teaser,
        "Description": project.description or project.teaser,
        "Authors": project.authors,
        "HideSetupGame": "0",
        "AffectsSavedGames": (
            "1" if has_gameplay_lua or project.options.affects_saved_games else "0"
        ),
        "MinCompatibleSaveVersion": "0",
        "SupportsSinglePlayer": "1",
        "SupportsMultiplayer": (
            "0"
            if has_gameplay_lua
            else "1" if project.options.supports_multiplayer else "0"
        ),
        "SupportsHotSeat": (
            "0"
            if has_gameplay_lua
            else "1" if project.options.supports_hotseat else "0"
        ),
        "SupportsMac": "1" if project.options.supports_mac else "0",
        "ReloadAudioSystem": (
            "1" if advanced_content(project).audio.populated() else "0"
        ),
        "ReloadLandmarkSystem": "0",
        "ReloadStrategicViewSystem": "1",
        "ReloadUnitSystem": "1",
    }
    for tag, value in property_values.items():
        ET.SubElement(properties, tag).text = str(value)
    ET.SubElement(root, "Dependencies")
    references = ET.SubElement(root, "References")
    if project.dependencies.promotions_expansion_pack:
        ET.SubElement(
            references,
            "Mod",
            {
                "id": PEP_MOD_ID,
                "minversion": str(PEP_MOD_VERSION),
                "maxversion": str(PEP_MOD_VERSION),
                "title": PEP_MOD_NAME,
            },
        )
    ET.SubElement(root, "Blocks")

    db_files = tuple(database_files)
    lua_files = tuple(lua_files)
    vfs_files = tuple(vfs_files)
    files = ET.SubElement(root, "Files")
    for path in vfs_files:
        ET.SubElement(files, "File", {"import": "1"}).text = path
    for path in (*db_files, *lua_files):
        ET.SubElement(files, "File", {"import": "0"}).text = path
    actions = ET.SubElement(root, "Actions")
    activated = ET.SubElement(actions, "OnModActivated")
    for path in db_files:
        ET.SubElement(activated, "UpdateDatabase").text = path
    entry_points = ET.SubElement(root, "EntryPoints")
    for path in lua_files:
        entry = ET.SubElement(
            entry_points, "EntryPoint", {"type": "InGameUIAddin", "file": path}
        )
        ET.SubElement(entry, "Name").text = (
            f"{project.internal_prefix}_{PurePosixPath(path).stem}"
        )
        ET.SubElement(entry, "Description").text = "Generated civilization runtime"
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="unicode", short_empty_elements=True
    ) + "\n"


def generate_art_manifest(project: CivProject) -> dict[str, object]:
    ids = project.ids()
    prefix = project.internal_prefix
    slots = [
        {"slot": 0, "subject_key": "civilization", "role": "civilization_icon"},
        {"slot": 1, "subject_key": "leader", "role": "leader_portrait"},
    ]
    for index, unit in enumerate(project.units, start=2):
        slots.append(
            {"slot": index, "subject_key": f"unit:{unit.key}", "role": "unique_unit_icon"}
        )
    building_start = 2 + len(project.units)
    for index, building in enumerate(project.buildings, start=building_start):
        slots.append(
            {
                "slot": index,
                "subject_key": f"building:{building.key}",
                "role": "unique_building_icon",
            }
        )
    improvement_start = building_start + len(project.buildings)
    for index, improvement in enumerate(
        project.improvements, start=improvement_start
    ):
        slots.append(
            {
                "slot": index,
                "subject_key": f"improvement:{improvement.key}",
                "role": "unique_improvement_icon",
            }
        )
    outputs: list[dict[str, object]] = []
    for size in MAIN_ATLAS_SIZES:
        outputs.append(
            {
                "path": f"Art/Atlases/{prefix}_Atlas_{size}.dds",
                "purpose": "main_portrait_atlas",
                "atlas": ids.main_atlas,
                "atlas_stem": f"{prefix}_Atlas",
                "icon_size": size,
                "width": size * ATLAS_GRID[0],
                "height": size * ATLAS_GRID[1],
                "icons_per_row": ATLAS_GRID[0],
                "icons_per_column": ATLAS_GRID[1],
                "profile": "legacy_dx9_dxt5",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            }
        )
    for size in ALPHA_ATLAS_SIZES:
        outputs.append(
            {
                "path": f"Art/Atlases/{prefix}_Alpha_{size}.dds",
                "purpose": "civilization_alpha_atlas",
                "atlas": ids.alpha_atlas,
                "atlas_stem": f"{prefix}_Alpha",
                "icon_size": size,
                "width": size * ATLAS_GRID[0],
                "height": size * ATLAS_GRID[1],
                "icons_per_row": ATLAS_GRID[0],
                "icons_per_column": ATLAS_GRID[1],
                "profile": "legacy_dx9_dxt5",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            }
        )
    for unit in project.units:
        outputs.append(
            {
                "path": f"Art/Atlases/{prefix}_Flag_{unit.key}_32.dds",
                "purpose": "unit_flag",
                "atlas": ids.unit_flag_atlases[unit.key],
                "atlas_stem": f"{prefix}_Flag_{unit.key}",
                "icon_size": 32,
                "width": 32 * ATLAS_GRID[0],
                "height": 32 * ATLAS_GRID[1],
                "icons_per_row": ATLAS_GRID[0],
                "icons_per_column": ATLAS_GRID[1],
                "profile": "legacy_dx9_dxt5",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            }
        )
        strategic_view_path = _strategic_view_output_path(project, unit.key)
        if strategic_view_path:
            outputs.append(
                {
                    "path": strategic_view_path,
                    "purpose": "strategic_view",
                    "source_roles": ["strategic_view"],
                    "subject_key": f"unit:{unit.key}",
                    "width": 64,
                    "height": 64,
                    "profile": "legacy_dx9_a8r8g8b8",
                    "surface_count": 1,
                    "mip_count": 1,
                    "required": True,
                }
            )
    outputs.extend(
        [
            {
                "path": f"Art/Leaders/{prefix}_scene.dds",
                "purpose": "leader_scene",
                "source_roles": ["leader_scene"],
                "width": 1600,
                "height": 900,
                "profile": "legacy_dx9_dxt1",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            },
            {
                "path": f"Art/Leaders/{prefix}_fallback.dds",
                "purpose": "leader_fallback",
                "source_roles": ["leader_portrait"],
                "width": 825,
                "height": 1024,
                "profile": "legacy_dx9_dxt1",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            },
            {
                "path": f"Art/DOM/{prefix}_DOM.dds",
                "purpose": "dawn_of_man",
                "source_roles": ["dawn_of_man"],
                "width": 1024,
                "height": 768,
                "profile": "legacy_dx9_dxt1",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            },
            {
                "path": f"Art/Maps/{prefix}_map.dds",
                "purpose": "civilization_map",
                "source_roles": ["map_image"],
                "width": 360,
                "height": 412,
                "profile": "legacy_dx9_dxt1",
                "surface_count": 1,
                "mip_count": 1,
                "required": True,
            },
        ]
    )
    sources = [
        {
            "asset_id": asset.asset_id,
            "role": asset.role.value,
            "subject_key": asset.subject_key,
            "source_png": asset.source_png.replace("\\", "/"),
            "required": asset.required,
            "crop_mode": asset.crop_mode,
            "focal_x": asset.focal_x,
            "focal_y": asset.focal_y,
        }
        for asset in project.art.assets
    ]
    return {
        "manifest_format": "civ5studio.art-manifest",
        "manifest_version": 1,
        "contract_version": project.art.contract_version,
        "project_id": project.project_id,
        "internal_prefix": prefix,
        "authority": "Strategic Missile Project current implementation",
        "contract": {
            "preferred_source_size": [1024, 1024],
            "atlas_grid": list(ATLAS_GRID),
            "main_atlas_sizes": list(MAIN_ATLAS_SIZES),
            "alpha_atlas_sizes": list(ALPHA_ATLAS_SIZES),
            "portrait_fit_diameter": PORTRAIT_FIT_DIAMETER,
            "portrait_reference_size": PORTRAIT_REFERENCE_SIZE,
            "unit_flag_fit_fraction": 0.78,
            "no_baked_ring_or_frame": True,
            "transparent_rgb_must_be_scrubbed": True,
        },
        "atlas_slots": slots,
        "sources": sources,
        "outputs": outputs,
    }


def generate_capability_report(
    project: CivProject,
    catalog: ReferenceCatalog,
    report: ValidationReport,
    *,
    strict_release: bool,
) -> dict[str, object]:
    effects: list[dict[str, str]] = []
    groups: list[tuple[str, list[MechanicEffect]]] = [
        ("trait", project.trait.effects)
    ]
    groups.extend((f"unit:{item.key}", item.effects) for item in project.units)
    groups.extend(
        (f"building:{item.key}", item.effects) for item in project.buildings
    )
    for subject, declared in groups:
        for effect in declared:
            effects.append(
                {
                    "subject": subject,
                    "description": effect.description,
                    "implementation": effect.implementation.value,
                    "recipe_id": effect.recipe_id,
                    "status": "UNIMPLEMENTED",
                }
            )
    compiled_lua_effects = [
        {
            "slot": effect["slot"],
            "instance_id": effect["instance_id"],
            "effect_id": effect["effect_id"],
            "effect_version": effect["effect_version"],
            "label": effect["label"],
            "category": effect["category"],
            "primitive_id": effect["primitive_id"],
            "trigger": effect["trigger"],
            "runtime_config": effect["runtime_config"],
            "status": "COMPILED",
            "runtime_gate": "REQUIRED_NOT_RUN",
        }
        for effect in selected_lua_effects(project)
    ]
    recipes = [
        {
            "recipe_id": recipe.recipe_id,
            "scope": recipe.scope.value,
            "label": recipe.label,
            "support": recipe.support.value,
            "implementation": recipe.implementation.value,
            "storage_path": recipe.storage_path,
        }
        for recipe in iter_recipes()
    ]
    strict_status = "PASS" if strict_release and not report.errors else "NOT_RUN"
    return {
        "capability_format": "civ5studio.capability-report",
        "capability_version": 2,
        "project_id": project.project_id,
        "target": "Sid Meier's Civilization V: Brave New World / Expansion2",
        "reference_catalog_version": catalog.data.get("catalog_version"),
        "verified_clone_contract": {
            "unit_columns": len(catalog.ordered_columns("Units")),
            "unit_child_tables": len(
                catalog.clone_contract("Units").get("child_tables", {})
            ),
            "building_columns": len(catalog.ordered_columns("Buildings")),
            "building_child_tables": len(
                catalog.clone_contract("Buildings").get("child_tables", {})
            ),
            "improvement_columns": len(catalog.ordered_columns("Improvements")),
            "improvement_child_tables": len(
                catalog.clone_contract("Improvements").get("child_tables", {})
            ),
            "build_columns": len(catalog.ordered_columns("Builds")),
            "build_child_tables": len(
                catalog.clone_contract("Builds").get("child_tables", {})
            ),
        },
        "registered_recipes": recipes,
        "project_usage": {
            "trait_database_modifiers": sorted(project.trait.database_modifiers),
            "unique_units": len(project.units),
            "unique_buildings": len(project.buildings),
            "unique_improvements": len(project.improvements),
            "selected_lua_effects": len(compiled_lua_effects),
            "improvements_without_build_actions": sorted(
                item.key
                for item in project.improvements
                if not catalog.builds_for_improvement(item.base_improvement)
            ),
            "custom_strategic_view_units": sorted(
                asset.subject_key.removeprefix("unit:")
                for asset in project.art.assets
                if asset.role is ArtRole.STRATEGIC_VIEW and asset.source_png.strip()
            ),
            "external_mod_references": (
                [
                    {
                        "id": PEP_MOD_ID,
                        "version": PEP_MOD_VERSION,
                        "name": PEP_MOD_NAME,
                    }
                ]
                if project.dependencies.promotions_expansion_pack
                else []
            ),
            "promotions_expansion_pack_assignments": sum(
                len(unit.promotions_expansion_pack) for unit in project.units
            ),
        },
        "compiled_lua_effects": compiled_lua_effects,
        "unimplemented_effects": effects,
        "validation_counts": {
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "information": len(report.issues) - len(report.errors) - len(report.warnings),
        },
        "release_gates": {
            "bnw_schema_contract": "PASS",
            "mechanic_completeness": "PASS" if not effects else "FAIL",
            "lua_effect_runtime": (
                "REQUIRED_NOT_RUN" if compiled_lua_effects else "NOT_APPLICABLE"
            ),
            "strict_static_release": strict_status,
            "install_eligibility": "PASS" if strict_status == "PASS" else "BLOCKED",
            "bnw_in_game": "REQUIRED_NOT_RUN",
            "ige_compatibility": "REQUIRED_NOT_RUN",
        },
        "validation_boundary": (
            "Static schema, SQL, XML, DDS, inventory, and hash checks do not prove "
            "Civilization V or IGE runtime behavior."
        ),
    }


def generate_capability_markdown(
    project: CivProject, capability: Mapping[str, object]
) -> str:
    gates = capability.get("release_gates", {})
    gate_values = gates if isinstance(gates, Mapping) else {}
    clone = capability.get("verified_clone_contract", {})
    clone_values = clone if isinstance(clone, Mapping) else {}
    recipes = capability.get("registered_recipes", [])
    compiled_lua = capability.get("compiled_lua_effects", [])
    effects = capability.get("unimplemented_effects", [])
    lines = [
        f"# Capability and Release Gate: {project.mod_name}\n\n",
        "## Verified compiler surface\n\n",
        f"- Units: {clone_values.get('unit_columns', 0)} columns and "
        f"{clone_values.get('unit_child_tables', 0)} child tables.\n",
        f"- Buildings: {clone_values.get('building_columns', 0)} columns and "
        f"{clone_values.get('building_child_tables', 0)} child tables.\n",
        f"- Improvements: {clone_values.get('improvement_columns', 0)} columns and "
        f"{clone_values.get('improvement_child_tables', 0)} child tables.\n",
        f"- Worker builds: {clone_values.get('build_columns', 0)} columns and "
        f"{clone_values.get('build_child_tables', 0)} owned child tables, plus "
        "verified `Unit_Builds` propagation.\n",
        f"- Registered compiled recipes: {len(recipes) if isinstance(recipes, list) else 0}.\n\n",
        "## Release gates\n\n",
    ]
    for name, value in gate_values.items():
        lines.append(f"- `{name}`: **{value}**\n")
    lines.append("\n## Compiled Lua effects\n\n")
    if isinstance(compiled_lua, list) and compiled_lua:
        for item in compiled_lua:
            if isinstance(item, Mapping):
                lines.append(
                    f"- Slot {item.get('slot', '')}: `{item.get('effect_id', '')}` "
                    f"({item.get('label', '')}) - **COMPILED**, runtime gate "
                    f"**{item.get('runtime_gate', 'REQUIRED_NOT_RUN')}**.\n"
                )
    else:
        lines.append("None selected.\n")
    lines.append("\n## Declared but unimplemented mechanics\n\n")
    if isinstance(effects, list) and effects:
        for item in effects:
            if isinstance(item, Mapping):
                lines.append(
                    f"- `{item.get('subject', '')}`: {item.get('description', '')}\n"
                )
    else:
        lines.append("None.\n")
    lines.append(
        "\nStatic schema, SQL, XML, DDS, inventory, and hash checks do not prove "
        "Civilization V or IGE runtime behavior.\n"
    )
    return "".join(lines)


def generate_improvements_sql(
    project: CivProject, catalog: ReferenceCatalog
) -> str:
    """Clone complete donor improvement/build contracts with stable identities."""

    ids = project.ids()
    prefix = project.internal_prefix
    lines = [_header("Improvements.sql", project)]
    improvement_contract = catalog.clone_contract("Improvements")
    improvement_columns = tuple(
        str(value) for value in improvement_contract.get("columns", ())
    )
    improvement_children = improvement_contract.get("child_tables", {})
    build_contract = catalog.clone_contract("Builds")
    build_columns = tuple(str(value) for value in build_contract.get("columns", ()))
    build_children = build_contract.get("child_tables", {})
    unit_build_columns = catalog.ordered_columns("Unit_Builds")

    for index, improvement in enumerate(project.improvements):
        custom = ids.improvements[improvement.key]
        donor = improvement.base_improvement
        desc = f"TXT_KEY_IMPROVEMENT_{improvement.key}_{prefix}"
        portrait = 2 + len(project.units) + len(project.buildings) + index
        improvement_overrides = {
            "Type": sql_string(custom),
            "Description": sql_string(desc),
            "Civilopedia": sql_string(f"{desc}_PEDIA"),
            "Help": sql_string(f"{desc}_HELP"),
            "SpecificCivRequired": "1",
            "CivilizationType": sql_string(ids.civilization),
            "PortraitIndex": str(portrait),
            "IconAtlas": sql_string(ids.main_atlas),
        }
        lines.append(f"-- Unique improvement: {improvement.name}\n")
        lines.append(
            _clone_row_sql(
                "Improvements",
                improvement_columns,
                identity_column="Type",
                donor_identity=donor,
                overrides={
                    key: value
                    for key, value in improvement_overrides.items()
                    if key in improvement_columns
                },
                omitted_columns=("ID",),
            )
        )
        for table, table_columns in sorted(improvement_children.items()):
            lines.append(
                _clone_child_rows_sql(
                    str(table),
                    tuple(str(value) for value in table_columns),
                    key_column="ImprovementType",
                    donor_identity=donor,
                    custom_identity=custom,
                )
            )
        for change in improvement.yield_changes:
            lines.append(
                "UPDATE Improvement_Yields SET Yield = Yield + "
                f"{change.amount} WHERE ImprovementType = {sql_string(custom)} "
                f"AND YieldType = {sql_string(change.yield_type)};\n"
                "INSERT INTO Improvement_Yields (ImprovementType, YieldType, Yield)\n"
                f"SELECT {sql_string(custom)}, {sql_string(change.yield_type)}, "
                f"{change.amount}\n"
                "WHERE NOT EXISTS (SELECT 1 FROM Improvement_Yields "
                f"WHERE ImprovementType = {sql_string(custom)} AND YieldType = "
                f"{sql_string(change.yield_type)});\n\n"
            )

        donor_builds = catalog.builds_for_improvement(donor)
        if not donor_builds:
            lines.append(
                "-- UNSUPPORTED FOR RELEASE: this verified donor has no worker "
                "Builds row; strict validation blocks the project.\n\n"
            )
        for donor_build in donor_builds:
            custom_build = generated_build_type(
                project, improvement.key, donor_build
            )
            suffix = type_component(donor_build.removeprefix("BUILD_")) or "ACTION"
            build_desc = f"TXT_KEY_BUILD_{improvement.key}_{prefix}_{suffix}"
            build_overrides = {
                "Type": sql_string(custom_build),
                "Description": sql_string(build_desc),
                "Help": sql_string(f"{build_desc}_HELP"),
                "Recommendation": sql_string(f"{build_desc}_RECOMMENDATION"),
                "PrereqTech": (
                    sql_string(improvement.build_prereq_tech)
                    if improvement.build_prereq_tech is not None
                    else "PrereqTech"
                ),
                "ImprovementType": sql_string(custom),
                "IconIndex": str(portrait),
                "IconAtlas": sql_string(ids.main_atlas),
            }
            lines.append(
                _clone_row_sql(
                    "Builds",
                    build_columns,
                    identity_column="Type",
                    donor_identity=donor_build,
                    overrides={
                        key: value
                        for key, value in build_overrides.items()
                        if key in build_columns
                    },
                    omitted_columns=("ID",),
                )
            )
            for table, table_columns in sorted(build_children.items()):
                lines.append(
                    _clone_child_rows_sql(
                        str(table),
                        tuple(str(value) for value in table_columns),
                        key_column="BuildType",
                        donor_identity=donor_build,
                        custom_identity=custom_build,
                    )
                )
            lines.append(
                _clone_child_rows_sql(
                    "Unit_Builds",
                    unit_build_columns,
                    key_column="BuildType",
                    donor_identity=donor_build,
                    custom_identity=custom_build,
                )
            )
    if not project.improvements:
        lines.append("-- No unique improvements configured.\n")
    return "".join(lines)


def generate_unimplemented(project: CivProject) -> str:
    groups: list[tuple[str, list[MechanicEffect]]] = [("Trait", project.trait.effects)]
    groups.extend((f"Unit: {item.name}", item.effects) for item in project.units)
    groups.extend((f"Building: {item.name}", item.effects) for item in project.buildings)
    lines = [f"# Unimplemented Effects: {project.mod_name}\n\n"]
    any_effects = False
    for heading, effects in groups:
        if not effects:
            continue
        any_effects = True
        lines.append(f"## {heading}\n\n")
        for effect in effects:
            lines.append(f"- **{effect.implementation.value}**: {effect.description}\n")
            if effect.recipe_id:
                lines.append(f"  - Requested recipe: `{effect.recipe_id}`\n")
            if effect.notes:
                lines.append(f"  - Notes: {effect.notes}\n")
        lines.append("\n")
    if not any_effects:
        lines.append("No unimplemented mechanics are declared.\n")
    else:
        lines.append(
            "These descriptions were not converted into executable Lua or SQL. "
            "Strict release validation remains blocked until each effect uses a tested recipe.\n"
        )
    return "".join(lines)


def generate_validation_report(project: CivProject, report: ValidationReport) -> str:
    lines = [f"# Validation Report: {project.mod_name}\n\n"]
    if not report.issues:
        return "".join(lines) + "No source validation issues. Static validation is not an in-game test.\n"
    for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO):
        items = [item for item in report.issues if item.severity is severity]
        if not items:
            continue
        lines.append(f"## {severity.value.title()} ({len(items)})\n\n")
        for item in items:
            lines.append(f"- `{item.code}` at `{item.path}`: {item.message}\n")
            if item.hint:
                lines.append(f"  - {item.hint}\n")
        lines.append("\n")
    lines.append("Static validation is not an in-game test.\n")
    return "".join(lines)


def generate_summary(project: CivProject) -> str:
    ids = project.ids()
    lines = [
        f"# Generated Summary: {project.mod_name}\n\n",
        f"- Project ID: `{project.project_id}`\n",
        f"- Mod ID: `{project.mod_id}`\n",
        f"- Mod version: `{project.mod_version}`\n",
        f"- Civilization: `{ids.civilization}`\n",
        f"- Leader: `{ids.leader}`\n",
        f"- Trait: `{ids.trait}`\n",
        f"- Main atlas: `{ids.main_atlas}` (8x8)\n",
        f"- Alpha atlas: `{ids.alpha_atlas}`\n\n",
        "## Unique Content\n\n",
    ]
    for unit in project.units:
        lines.append(
            f"- Unit `{ids.units[unit.key]}` replaces `{unit.replaces_unit_class}`.\n"
        )
    for building in project.buildings:
        lines.append(
            f"- Building `{ids.buildings[building.key]}` replaces "
            f"`{building.replaces_building_class}`.\n"
        )
    for improvement in project.improvements:
        lines.append(
            f"- Improvement `{ids.improvements[improvement.key]}` clones "
            f"`{improvement.base_improvement}`; its worker build actions are cloned "
            "from the verified donor mapping.\n"
        )
    if not project.units and not project.buildings and not project.improvements:
        lines.append("- No unique units, buildings, or improvements.\n")
    compiled_lua = selected_lua_effects(project)
    if compiled_lua:
        lines.append("\n## Selected Lua Effects\n\n")
        for effect in compiled_lua:
            lines.append(
                f"- Slot {effect['slot']}: `{effect['effect_id']}` "
                f"({effect['label']}) - statically compiled; BNW/IGE runtime not run.\n"
            )
        lines.append(
            "- Generated `.modinfo` safety properties: `AffectsSavedGames=1`, "
            "`SupportsMultiplayer=0`, `SupportsHotSeat=0`.\n"
        )
    if project.dependencies.promotions_expansion_pack:
        lines.extend(
            (
                "\n## External Mod Reference\n\n",
                f"- `{PEP_MOD_NAME}` v{PEP_MOD_VERSION}: `{PEP_MOD_ID}`.\n",
            )
        )
    return "".join(lines)


def generate_build_checklist(project: CivProject) -> str:
    enabled_mods = (
        "this mod and Promotions - Expansion Pack (v 9)"
        if project.dependencies.promotions_expansion_pack
        else "only this mod"
    )
    lua_effect_steps = ""
    if project.lua_effects:
        labels = ", ".join(
            str(effect["label"]) for effect in selected_lua_effects(project)
        )
        lua_effect_steps = f"""
7. Exercise each selected Lua effect independently, then together: {labels}.
8. Save, reload, advance at least two turns, and repeat each trigger. Confirm no
   duplicate rewards and review `Lua.log` for errors.
9. Keep multiplayer and hot-seat off for this build. Studio marks packages with
   extra effects as save-affecting and single-player only until certified.
"""
    return f"""# Build and BNW Test Checklist: {project.mod_name}

## What Civilization Studio already checked

- Created every required Civ V image and icon size from the selected PNG files.
- Checked DDS format, size, alpha, atlas placement, and mip settings.
- Parsed the generated leader XML and `{modinfo_filename(project)}`.
- Tested the generated game data against the bundled BNW reference database.
- Confirmed the player ZIP matches the validated generated mod folder.

You do not need to run SQL, parse XML, or convert DDS files yourself. If Studio
reported a successful build, those static checks passed for this exact package.

## What to test in Civilization V

1. Use Studio's **Install into Civilization V** button, or copy the complete
   generated folder into the Civ V `MODS` directory.
2. Open Civilization V, choose **MODS**, enable {enabled_mods}, and start Brave New World.
3. Confirm the civilization and leader appear in game setup.
4. Start a new game and inspect the opening screen, icons, map image, colors,
   special ability, unique replacements, city names, and spy names.
5. Exercise every unique unit, building, and improvement. Save the game, reload
   it, and play at least two more turns.
6. If anything fails, exit the game and use Studio's **Check Civ V logs for
   problems** tool before rebuilding.
{lua_effect_steps}

Passing Studio's static checks does not prove in-game behavior. Only testing
the exact installed build in Brave New World provides runtime evidence.
"""


def _multi_insert(
    table: str, columns: tuple[str, ...], rows: Iterable[tuple[object, ...]]
) -> str:
    values = list(rows)
    if not values:
        return ""
    rendered = [
        "  (" + ", ".join(_sql_value(value) for value in row) + ")" for row in values
    ]
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n"
        + ",\n".join(rendered)
        + ";\n\n"
    )


def _sql_value(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return sql_string(value)


def _override(value: int | None, base_column: str) -> str:
    return base_column if value is None else str(value)


def _clone_row_sql(
    table: str,
    columns: Iterable[str],
    *,
    identity_column: str,
    donor_identity: str,
    overrides: Mapping[str, str],
    omitted_columns: Iterable[str] = (),
) -> str:
    """Clone one donor row with an explicit, schema-verified column contract."""

    omitted = set(omitted_columns)
    selected = tuple(column for column in columns if column not in omitted)
    if not selected or identity_column not in selected:
        raise ValueError(f"Incomplete clone contract for {table}.")
    unknown = set(overrides) - set(selected)
    if unknown:
        raise ValueError(
            f"Clone overrides reference unknown {table} columns: "
            + ", ".join(sorted(unknown))
        )
    rendered_columns = ", ".join(selected)
    expressions = [overrides.get(column, column) for column in selected]
    return (
        f"INSERT INTO {table}\n"
        f"  ({rendered_columns})\n"
        "SELECT\n  "
        + ",\n  ".join(expressions)
        + f"\nFROM {table} WHERE {identity_column} = "
        + sql_string(donor_identity)
        + ";\n\n"
    )


def _validate_clone_contracts(
    catalog: ReferenceCatalog, report: ValidationReport
) -> None:
    expected = {"Units": (99, 15), "Buildings": (152, 38)}
    for table, (column_count, child_count) in expected.items():
        contract = catalog.clone_contract(table)
        columns = tuple(str(value) for value in contract.get("columns", ()))
        child_tables = contract.get("child_tables", {})
        if columns != catalog.ordered_columns(table) or len(columns) != column_count:
            report.error(
                "generation.clone-contract",
                f"bnw.reference_catalog.{table}",
                f"Expected the complete ordered {table} contract "
                f"({column_count} columns).",
            )
        if not isinstance(child_tables, Mapping) or len(child_tables) != child_count:
            report.error(
                "generation.clone-contract",
                f"bnw.reference_catalog.{table}.child_tables",
                f"Expected {child_count} verified child-table contracts.",
            )
            continue
        for child_table, child_columns in child_tables.items():
            expected_columns = catalog.ordered_columns(str(child_table))
            actual_columns = tuple(str(value) for value in child_columns)
            if not expected_columns or actual_columns != expected_columns:
                report.error(
                    "generation.clone-contract",
                    f"bnw.reference_catalog.{child_table}",
                    "Child-table columns do not match the verified schema.",
                )
    for table, identity_column, child_key_column in (
        ("Improvements", "Type", "ImprovementType"),
        ("Builds", "Type", "BuildType"),
    ):
        contract = catalog.clone_contract(table)
        columns = tuple(str(value) for value in contract.get("columns", ()))
        child_tables = contract.get("child_tables", {})
        if (
            not columns
            or columns != catalog.ordered_columns(table)
            or identity_column not in columns
            or contract.get("identity_column") != identity_column
            or contract.get("child_key_column") != child_key_column
        ):
            report.error(
                "generation.clone-contract",
                f"bnw.reference_catalog.{table}",
                f"The complete ordered {table} contract or its identity metadata "
                "does not match the verified catalog schema.",
            )
        if not isinstance(child_tables, Mapping) or not child_tables:
            report.error(
                "generation.clone-contract",
                f"bnw.reference_catalog.{table}.child_tables",
                f"No verified {table} child-table contracts are available.",
            )
            continue
        for child_table, child_columns in child_tables.items():
            actual = tuple(str(value) for value in child_columns)
            if (
                actual != catalog.ordered_columns(str(child_table))
                or child_key_column not in actual
            ):
                report.error(
                    "generation.clone-contract",
                    f"bnw.reference_catalog.{child_table}",
                    f"Child-table contract must match the catalog and contain "
                    f"{child_key_column}.",
                )
    for table, columns in {
        "UnitGameplay2DScripts": (
            "UnitType",
            "SelectionSound",
            "FirstSelectionSound",
        ),
        "UnitPromotions_CivilianUnitType": ("PromotionType", "UnitType"),
        "ArtDefine_UnitInfos": (
            "Type",
            "DamageStates",
            "Formation",
            "UnitFlagAtlas",
            "UnitFlagIconOffset",
            "IconAtlas",
            "PortraitIndex",
        ),
        "ArtDefine_UnitInfoMemberInfos": (
            "UnitInfoType",
            "UnitMemberInfoType",
            "NumMembers",
        ),
        "ArtDefine_StrategicView": (
            "StrategicViewType",
            "TileType",
            "Asset",
        ),
        "Unit_Builds": ("UnitType", "BuildType"),
    }.items():
        if catalog.ordered_columns(table) != columns:
            report.error(
                "generation.clone-contract",
                f"bnw.reference_catalog.{table}",
                "Required external unit relationship lacks a verified schema.",
            )


def _clone_child_rows_sql(
    table: str,
    columns: Iterable[str],
    *,
    key_column: str,
    donor_identity: str,
    custom_identity: str,
) -> str:
    """Clone every donor child row while replacing only its owner identity."""

    selected = tuple(columns)
    if key_column not in selected:
        raise ValueError(f"Clone contract for {table} lacks {key_column}.")
    expressions = [
        sql_string(custom_identity) if column == key_column else column
        for column in selected
    ]
    return (
        f"INSERT INTO {table} ({', '.join(selected)})\n"
        f"SELECT {', '.join(expressions)} FROM {table} "
        f"WHERE {key_column} = {sql_string(donor_identity)};\n\n"
    )


def _strategic_view_output_path(project: CivProject, unit_key: str) -> str:
    subject = f"unit:{unit_key}"
    if any(
        asset.role is ArtRole.STRATEGIC_VIEW
        and asset.subject_key == subject
        and bool(asset.source_png.strip())
        for asset in project.art.assets
    ):
        return f"Art/StrategicView/SV_{project.internal_prefix}_{unit_key}.dds"
    return ""


def _clone_unit_art_definitions_sql(
    catalog: ReferenceCatalog,
    *,
    donor_unit: str,
    custom_art_type: str,
    strategic_view_asset: str,
) -> str:
    info_columns = catalog.ordered_columns("ArtDefine_UnitInfos")
    member_columns = catalog.ordered_columns("ArtDefine_UnitInfoMemberInfos")
    strategic_columns = catalog.ordered_columns("ArtDefine_StrategicView")
    if (
        "Type" not in info_columns
        or "UnitInfoType" not in member_columns
        or "StrategicViewType" not in strategic_columns
    ):
        raise ValueError("Incomplete BNW unit art-definition schema.")
    donor_art = (
        "(SELECT UnitArtInfo FROM Units WHERE Type = "
        + sql_string(donor_unit)
        + ")"
    )
    info_expressions = [
        sql_string(custom_art_type) if column == "Type" else column
        for column in info_columns
    ]
    member_expressions = [
        sql_string(custom_art_type) if column == "UnitInfoType" else column
        for column in member_columns
    ]
    result = (
        "-- Dedicated art identity required for custom unit presentation.\n"
        f"INSERT INTO ArtDefine_UnitInfos ({', '.join(info_columns)})\n"
        f"SELECT {', '.join(info_expressions)} FROM ArtDefine_UnitInfos "
        f"WHERE Type = {donor_art};\n\n"
        f"INSERT INTO ArtDefine_UnitInfoMemberInfos ({', '.join(member_columns)})\n"
        f"SELECT {', '.join(member_expressions)} "
        "FROM ArtDefine_UnitInfoMemberInfos "
        f"WHERE UnitInfoType = {donor_art};\n\n"
    )
    if strategic_view_asset:
        result += (
            "INSERT INTO ArtDefine_StrategicView "
            "(StrategicViewType, TileType, Asset) VALUES\n"
            f"  ({sql_string(custom_art_type)}, 'Unit', "
            f"{sql_string(strategic_view_asset)});\n\n"
        )
    else:
        strategic_expressions = [
            sql_string(custom_art_type)
            if column == "StrategicViewType"
            else column
            for column in strategic_columns
        ]
        result += (
            "-- No custom Strategic View PNG; retain the donor map icon binding.\n"
            f"INSERT INTO ArtDefine_StrategicView ({', '.join(strategic_columns)})\n"
            f"SELECT {', '.join(strategic_expressions)} "
            "FROM ArtDefine_StrategicView\n"
            f"WHERE StrategicViewType = {donor_art};\n\n"
        )
    return result
