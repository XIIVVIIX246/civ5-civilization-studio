"""Source-project validation with explicit release severity."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path, PurePosixPath
import re
import uuid
from typing import Iterable

from civ5studio.bnw import ReferenceCatalog
from civ5studio.integrations import PromotionsExpansionPackCatalog

from .ids import is_valid_component, normalize_prefix, type_component
from .models import (
    CURRENT_SCHEMA_VERSION,
    PROJECT_FORMAT,
    ArtRole,
    CivProject,
    ImplementationKind,
    MechanicEffect,
)
from .lua_effects import (
    LUA_EFFECT_LIMIT,
    lua_effect_by_id,
    lua_effects_compatible,
    validate_lua_parameters,
)
from .recipes import RecipeScope, recipe_by_id


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    severity: Severity
    message: str
    hint: str = ""


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(
        self,
        severity: Severity,
        code: str,
        path: str,
        message: str,
        hint: str = "",
    ) -> None:
        self.issues.append(ValidationIssue(code, path, severity, message, hint))

    def error(self, code: str, path: str, message: str, hint: str = "") -> None:
        self.add(Severity.ERROR, code, path, message, hint)

    def warning(self, code: str, path: str, message: str, hint: str = "") -> None:
        self.add(Severity.WARNING, code, path, message, hint)

    def info(self, code: str, path: str, message: str, hint: str = "") -> None:
        self.add(Severity.INFO, code, path, message, hint)

    def extend(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues.extend(issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity is Severity.WARNING)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def has_code(self, code: str) -> bool:
        return any(item.code == code for item in self.issues)

    def sorted(self) -> "ValidationReport":
        rank = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
        return ValidationReport(
            sorted(self.issues, key=lambda item: (rank[item.severity], item.path, item.code))
        )


_ASSET_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")


def is_portable_relative_path(value: str) -> bool:
    if not value or "\x00" in value or re.match(r"^[A-Za-z]:", value):
        return False
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not path.is_absolute() and ".." not in path.parts and "." != normalized


def validate_project(
    project: CivProject,
    catalog: ReferenceCatalog | None = None,
    *,
    strict_release: bool = False,
    project_root: str | Path | None = None,
) -> ValidationReport:
    """Validate a project for an available build or a strict release.

    Available-build validation keeps missing art and unimplemented mechanics as
    visible warnings so safe SQL/docs can still be generated. Strict release
    promotes those items to errors.
    """

    catalog = catalog or ReferenceCatalog.bundled()
    report = ValidationReport()

    if project.project_format != PROJECT_FORMAT:
        report.error("project.format", "project_format", "Unknown project document format.")
    if project.schema_version != CURRENT_SCHEMA_VERSION:
        report.error(
            "project.schema",
            "schema_version",
            f"Expected schema {CURRENT_SCHEMA_VERSION}; migrate the document before building.",
        )
    if "existing_mod_import" in project.extensions:
        message = (
            "This project contains an immutable existing-mod inspection snapshot. "
            "Its SQL, XML, Lua, DLL, and art are intentionally excluded from generated builds."
        )
        hint = (
            "Keep this workspace for inspection, or create a separate Studio project with a "
            "new mod ID and explicitly recreate supported content before release."
        )
        if strict_release:
            report.error(
                "existing-mod-import.release-blocked",
                "extensions.existing_mod_import",
                message,
                hint,
            )
        else:
            report.warning(
                "existing-mod-import.release-blocked",
                "extensions.existing_mod_import",
                message,
                hint,
            )
    for field_name, value in (("project_id", project.project_id), ("mod_id", project.mod_id)):
        try:
            parsed = uuid.UUID(value)
            if str(parsed) != value.lower():
                report.warning(
                    "id.uuid-canonical",
                    field_name,
                    "UUID is valid but not in canonical lowercase form.",
                )
        except (ValueError, AttributeError, TypeError):
            report.error("id.uuid", field_name, "A valid UUID is required.")

    _required_text(report, "mod_name", project.mod_name)
    _required_text(report, "authors", project.authors)
    if project.mod_version < 1:
        report.error("mod.version", "mod_version", "Mod version must be at least 1.")

    _validate_lua_effect_selections(project, report, catalog)

    prefix = normalize_prefix(project.internal_prefix)
    if project.internal_prefix != prefix or not is_valid_component(prefix):
        report.error(
            "id.prefix",
            "internal_prefix",
            "Internal prefix must already be a 1-48 character uppercase Type component.",
            f"Suggested value: {prefix or 'CUSTOM_CIV'}",
        )

    civ = project.civilization
    for path, value in (
        ("civilization.name", civ.name),
        ("civilization.short_name", civ.short_name),
        ("civilization.adjective", civ.adjective),
        ("civilization.dawn_of_man_quote", civ.dawn_of_man_quote),
        ("leader.name", project.leader.name),
        ("trait.name", project.trait.name),
        ("trait.short_description", project.trait.short_description),
        ("trait.long_description", project.trait.long_description),
    ):
        _required_text(report, path, value)

    for path, value in (
        ("civilization.base_civilization", civ.base_civilization),
        ("civilization.copy_free_buildings_from", civ.copy_free_buildings_from),
        (
            "civilization.copy_free_techs_and_units_from",
            civ.copy_free_techs_and_units_from,
        ),
    ):
        _reference(report, catalog, "civilizations", path, value)
    if civ.start_region_avoid:
        _reference(
            report, catalog, "regions", "civilization.start_region_avoid", civ.start_region_avoid
        )

    _validate_key(report, "leader.key", project.leader.key)
    _validate_key(report, "trait.key", project.trait.key)
    _validate_names(report, "civilization.city_names", civ.city_names, required=True)
    _validate_names(report, "civilization.spy_names", civ.spy_names, required=False)
    if len(civ.city_names) < 5:
        report.warning(
            "civilization.city-count",
            "civilization.city_names",
            "At least five city names are recommended to avoid repeated names.",
        )
    if not civ.spy_names:
        report.warning(
            "civilization.spy-count",
            "civilization.spy_names",
            "No custom spy names are defined; BNW may show fallback text.",
        )

    personality_fields = (
        "victory_competitiveness", "wonder_competitiveness",
        "minor_civ_competitiveness", "boldness", "diplo_balance",
        "warmonger_hate", "denounce_willingness", "dof_willingness",
        "loyalty", "neediness", "forgiveness", "chattiness", "meanness",
    )
    for field_name in personality_fields:
        _bounded_int(
            report,
            f"leader.{field_name}",
            getattr(project.leader, field_name),
            1,
            10,
        )
    _validate_biases(
        report, catalog, project.leader.flavors, "leader.flavors", "flavors"
    )
    _validate_biases(
        report,
        catalog,
        project.leader.major_civ_approach_biases,
        "leader.major_civ_approach_biases",
        "major_civ_approaches",
    )
    _validate_biases(
        report,
        catalog,
        project.leader.minor_civ_approach_biases,
        "leader.minor_civ_approach_biases",
        "minor_civ_approaches",
    )
    for response in project.leader.diplomacy_text:
        _reference(
            report,
            catalog,
            "diplomacy_responses",
            f"leader.diplomacy_text.{response}",
            response,
        )

    trait_columns = catalog.values("trait_columns")
    for column, value in project.trait.database_modifiers.items():
        if column not in trait_columns:
            report.error(
                "reference.trait-column",
                f"trait.database_modifiers.{column}",
                f"{column!r} is not a verified BNW Traits column.",
            )
        if not isinstance(value, (int, bool)):
            report.error(
                "trait.modifier-type",
                f"trait.database_modifiers.{column}",
                "Trait database modifier must be an integer or boolean.",
            )

    seen_unit_keys: set[str] = set()
    seen_unit_classes: set[str] = set()
    pep_catalog = PromotionsExpansionPackCatalog.bundled()
    for index, unit in enumerate(project.units):
        path = f"units[{index}]"
        _validate_key(report, f"{path}.key", unit.key)
        _required_text(report, f"{path}.name", unit.name)
        _duplicate(report, seen_unit_keys, unit.key, f"{path}.key", "unit key")
        _duplicate(
            report,
            seen_unit_classes,
            unit.replaces_unit_class,
            f"{path}.replaces_unit_class",
            "unit replacement class",
        )
        _reference(
            report,
            catalog,
            "unit_classes",
            f"{path}.replaces_unit_class",
            unit.replaces_unit_class,
        )
        expected_base = catalog.unit_class_to_base_unit.get(unit.replaces_unit_class)
        base = unit.base_unit or expected_base
        if not base or base not in catalog.units:
            report.error(
                "reference.base-unit",
                f"{path}.base_unit",
                f"No verified base unit is available for {unit.replaces_unit_class!r}.",
            )
        elif unit.base_unit and expected_base and unit.base_unit != expected_base:
            report.error(
                "reference.base-unit-class",
                f"{path}.base_unit",
                f"{unit.base_unit} does not match the verified default {expected_base}.",
            )
        for stat in ("combat", "ranged_combat", "cost"):
            value = getattr(unit, stat)
            if value is not None:
                _bounded_int(report, f"{path}.{stat}", value, 0, 100000)
        if unit.moves is not None:
            _bounded_int(report, f"{path}.moves", unit.moves, 1, 60)
        if unit.prereq_tech:
            _reference(
                report, catalog, "technologies", f"{path}.prereq_tech", unit.prereq_tech
            )
        for promo_index, promotion in enumerate(unit.free_promotions):
            _reference(
                report,
                catalog,
                "promotions",
                f"{path}.free_promotions[{promo_index}]",
                promotion,
            )
        seen_pep_promotions: set[str] = set()
        for promo_index, promotion in enumerate(unit.promotions_expansion_pack):
            pep_path = f"{path}.promotions_expansion_pack[{promo_index}]"
            if promotion in seen_pep_promotions:
                report.error(
                    "dependency.pep-promotion-duplicate",
                    pep_path,
                    f"Promotions Expansion Pack type {promotion!r} is assigned twice.",
                )
            seen_pep_promotions.add(promotion)
            if promotion not in pep_catalog.types:
                severity = Severity.ERROR if project.dependencies.promotions_expansion_pack else Severity.WARNING
                report.add(
                    severity,
                    "dependency.pep-promotion",
                    pep_path,
                    f"{promotion!r} is not in the provenance-backed v9 catalog.",
                )
            if not project.dependencies.promotions_expansion_pack:
                report.warning(
                    "dependency.pep-disabled",
                    pep_path,
                    "Assignment is preserved but will not be generated until the "
                    "Promotions Expansion Pack dependency is enabled.",
                )
        _effects(
            report, unit.effects, f"{path}.effects", strict_release, RecipeScope.UNIT
        )

    seen_building_keys: set[str] = set()
    seen_building_classes: set[str] = set()
    for index, building in enumerate(project.buildings):
        path = f"buildings[{index}]"
        _validate_key(report, f"{path}.key", building.key)
        _required_text(report, f"{path}.name", building.name)
        _duplicate(report, seen_building_keys, building.key, f"{path}.key", "building key")
        _duplicate(
            report,
            seen_building_classes,
            building.replaces_building_class,
            f"{path}.replaces_building_class",
            "building replacement class",
        )
        _reference(
            report,
            catalog,
            "building_classes",
            f"{path}.replaces_building_class",
            building.replaces_building_class,
        )
        expected_base = catalog.building_class_to_base_building.get(
            building.replaces_building_class
        )
        base = building.base_building or expected_base
        if not base or base not in catalog.buildings:
            report.error(
                "reference.base-building",
                f"{path}.base_building",
                f"No verified base building is available for {building.replaces_building_class!r}.",
            )
        elif building.base_building and expected_base and building.base_building != expected_base:
            report.error(
                "reference.base-building-class",
                f"{path}.base_building",
                f"{building.base_building} does not match the verified default {expected_base}.",
            )
        for stat in ("cost", "gold_maintenance", "defense", "extra_city_hit_points"):
            value = getattr(building, stat)
            if value is not None:
                _bounded_int(report, f"{path}.{stat}", value, 0, 100000)
        if building.prereq_tech:
            _reference(
                report,
                catalog,
                "technologies",
                f"{path}.prereq_tech",
                building.prereq_tech,
            )
        for yield_index, change in enumerate(building.yield_changes):
            _reference(
                report,
                catalog,
                "yields",
                f"{path}.yield_changes[{yield_index}].yield_type",
                change.yield_type,
            )
            if not isinstance(change.amount, int):
                report.error(
                    "building.yield-type",
                    f"{path}.yield_changes[{yield_index}].amount",
                    "Yield change must be an integer.",
                )
        for xp_index, change in enumerate(building.domain_free_experience):
            _reference(
                report,
                catalog,
                "domains",
                f"{path}.domain_free_experience[{xp_index}].domain_type",
                change.domain_type,
            )
            _bounded_int(
                report,
                f"{path}.domain_free_experience[{xp_index}].amount",
                change.amount,
                0,
                1000,
            )
        _effects(
            report,
            building.effects,
            f"{path}.effects",
            strict_release,
            RecipeScope.BUILDING,
        )

    seen_improvement_keys: set[str] = set()
    for index, improvement in enumerate(project.improvements):
        path = f"improvements[{index}]"
        _validate_key(report, f"{path}.key", improvement.key)
        _required_text(report, f"{path}.name", improvement.name)
        _duplicate(
            report,
            seen_improvement_keys,
            improvement.key,
            f"{path}.key",
            "improvement key",
        )
        _reference(
            report,
            catalog,
            "improvements",
            f"{path}.base_improvement",
            improvement.base_improvement,
        )
        build_actions = catalog.builds_for_improvement(improvement.base_improvement)
        if improvement.base_improvement in catalog.improvements and not build_actions:
            report.add(
                Severity.ERROR if strict_release else Severity.WARNING,
                "improvement.no-build-action",
                f"{path}.base_improvement",
                f"{improvement.base_improvement} has no verified BNW worker build action. "
                "The donor can be cloned for audit output, but the improvement cannot "
                "be released as worker-buildable.",
                "Choose a donor with a verified build action or keep this project out of strict release.",
            )
        if improvement.build_prereq_tech:
            _reference(
                report,
                catalog,
                "technologies",
                f"{path}.build_prereq_tech",
                improvement.build_prereq_tech,
            )
        if not improvement.yield_changes:
            report.warning(
                "improvement.yields-empty",
                f"{path}.yield_changes",
                "No custom yield change is defined; the generated improvement will retain donor yields.",
            )
        seen_yields: set[str] = set()
        for yield_index, change in enumerate(improvement.yield_changes):
            yield_path = f"{path}.yield_changes[{yield_index}]"
            _reference(
                report,
                catalog,
                "yields",
                f"{yield_path}.yield_type",
                change.yield_type,
            )
            _duplicate(
                report,
                seen_yields,
                change.yield_type,
                f"{yield_path}.yield_type",
                "improvement yield type",
            )
            if isinstance(change.amount, bool) or not isinstance(change.amount, int):
                report.error(
                    "improvement.yield-type",
                    f"{yield_path}.amount",
                    "Yield change must be an integer.",
                )

    _effects(
        report,
        project.trait.effects,
        "trait.effects",
        strict_release,
        RecipeScope.TRAIT,
    )
    for color_field in fields(project.colors):
        field_name = color_field.name
        value = getattr(project.colors, field_name)
        if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            report.error(
                "colors.range",
                f"colors.{field_name}",
                "Color channels must be numeric values from 0.0 through 1.0.",
            )

    # Local import avoids a domain/application import cycle: the advanced
    # extension validator itself reuses this module's portable-path helper.
    from civ5studio.application.advanced_content import validate_advanced_content

    for issue in validate_advanced_content(project, project_root):
        severity = {
            "ERROR": Severity.ERROR,
            "WARNING": Severity.WARNING,
            "INFO": Severity.INFO,
        }.get(issue.severity.upper(), Severity.WARNING)
        report.add(severity, issue.code, issue.path, issue.message)

    _validate_art(project, report, strict_release, project_root)

    try:
        ids = project.ids()
        all_ids = [
            ids.civilization, ids.leader, ids.trait, ids.player_color,
            ids.primary_color, ids.secondary_color, ids.main_atlas, ids.alpha_atlas,
            *ids.units.values(), *ids.buildings.values(), *ids.unit_flag_atlases.values(),
            *ids.improvements.values(),
        ]
        if len(all_ids) != len(set(all_ids)):
            report.error("id.collision", "internal_prefix", "Generated Type values collide.")
    except Exception as exc:
        report.error("id.generation", "internal_prefix", f"Could not generate Type IDs: {exc}")
    return report.sorted()


def _validate_lua_effect_selections(
    project: CivProject,
    report: ValidationReport,
    catalog: ReferenceCatalog,
) -> None:
    """Validate the bounded, version-pinned civilization Lua recipe slots."""

    selections = project.lua_effects
    if len(selections) > LUA_EFFECT_LIMIT:
        report.error(
            "lua-effect.limit",
            "lua_effects",
            f"A civilization may select at most {LUA_EFFECT_LIMIT} Lua effects; "
            f"this project has {len(selections)}.",
        )

    seen_instances: set[str] = set()
    seen_effects: set[str] = set()
    known = []
    for index, selection in enumerate(selections):
        path = f"lua_effects[{index}]"
        try:
            parsed = uuid.UUID(selection.instance_id)
            if str(parsed) != selection.instance_id.lower():
                report.warning(
                    "lua-effect.instance-id-canonical",
                    f"{path}.instance_id",
                    "The effect instance UUID is valid but not canonical lowercase text.",
                )
        except (ValueError, AttributeError, TypeError):
            report.error(
                "lua-effect.instance-id",
                f"{path}.instance_id",
                "A stable UUID is required for each selected Lua effect instance.",
            )
        if selection.instance_id in seen_instances:
            report.error(
                "lua-effect.instance-duplicate",
                f"{path}.instance_id",
                "Lua effect instance IDs must be unique within a project.",
            )
        seen_instances.add(selection.instance_id)

        if selection.effect_id in seen_effects:
            report.error(
                "lua-effect.duplicate",
                f"{path}.effect_id",
                "The same Lua effect cannot occupy both civilization slots.",
            )
        seen_effects.add(selection.effect_id)

        definition = lua_effect_by_id(selection.effect_id)
        if definition is None:
            report.error(
                "lua-effect.unknown",
                f"{path}.effect_id",
                f"Lua effect {selection.effect_id!r} is not in the bundled catalog.",
            )
            continue
        known.append((index, definition))

        if isinstance(selection.effect_version, bool) or not isinstance(
            selection.effect_version, int
        ):
            report.error(
                "lua-effect.version-type",
                f"{path}.effect_version",
                "Lua effect versions must be integers.",
            )
        elif selection.effect_version != definition.version:
            report.error(
                "lua-effect.version",
                f"{path}.effect_version",
                f"Effect {selection.effect_id!r} requires catalog version "
                f"{definition.version}, not {selection.effect_version}.",
            )
        if not definition.pure_bnw:
            report.error(
                "lua-effect.dependency",
                f"{path}.effect_id",
                "This catalog release accepts only pure BNW Lua recipes.",
            )

        if not isinstance(selection.parameters, dict):
            report.error(
                "lua-effect.parameters-type",
                f"{path}.parameters",
                "Lua effect parameters must be a JSON object.",
            )
        else:
            for message in validate_lua_parameters(
                definition, selection.parameters
            ):
                report.error(
                    "lua-effect.parameter",
                    f"{path}.parameters",
                    message,
                )

        promotion = definition.runtime_config.get("promotion")
        if promotion is not None and not catalog.contains(
            "promotions", str(promotion)
        ):
            report.error(
                "lua-effect.catalog-promotion",
                f"{path}.effect_id",
                f"Catalog effect references unknown BNW promotion {promotion!r}.",
            )

    for left_offset, (left_index, left) in enumerate(known):
        for right_index, right in known[left_offset + 1 :]:
            if left.effect_id != right.effect_id and not lua_effects_compatible(
                left, right
            ):
                report.error(
                    "lua-effect.incompatible",
                    f"lua_effects[{right_index}].effect_id",
                    f"{left.label!r} and {right.label!r} cannot be combined.",
                    f"Replace one of the effects selected in slots {left_index + 1} "
                    f"and {right_index + 1}.",
                )

    if selections and not project.options.affects_saved_games:
        report.warning(
            "lua-effects.saved-games-derived",
            "options.affects_saved_games",
            "Selected gameplay Lua affects save data; generated mod metadata will "
            "set AffectsSavedGames to 1.",
        )
    if selections and project.options.supports_multiplayer:
        report.warning(
            "lua-effects.multiplayer-derived",
            "options.supports_multiplayer",
            "The Lua catalog is not multiplayer-certified; generated mod metadata "
            "will set SupportsMultiplayer to 0.",
        )
    if selections and project.options.supports_hotseat:
        report.warning(
            "lua-effects.hotseat-derived",
            "options.supports_hotseat",
            "The Lua catalog is not hotseat-certified; generated mod metadata will "
            "set SupportsHotSeat to 0.",
        )


def _required_text(report: ValidationReport, path: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        report.error("required", path, "A non-empty text value is required.")


def _reference(
    report: ValidationReport,
    catalog: ReferenceCatalog,
    category: str,
    path: str,
    value: str | None,
) -> None:
    if not catalog.contains(category, value):
        report.error(
            f"reference.{category}",
            path,
            f"{value!r} is not present in the bundled BNW reference catalog.",
        )


def _validate_key(report: ValidationReport, path: str, value: str) -> None:
    suggested = type_component(value)
    if value != suggested or not is_valid_component(suggested):
        report.error(
            "id.key",
            path,
            "Stable keys must already be uppercase Civ V Type components.",
            f"Suggested value: {suggested or 'CONTENT'}",
        )


def _bounded_int(
    report: ValidationReport, path: str, value: object, minimum: int, maximum: int
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        report.error(
            "number.range", path, f"Value must be an integer from {minimum} through {maximum}."
        )


def _validate_biases(
    report: ValidationReport,
    catalog: ReferenceCatalog,
    values: dict[str, int],
    path: str,
    category: str,
) -> None:
    for key, value in values.items():
        _reference(report, catalog, category, f"{path}.{key}", key)
        _bounded_int(report, f"{path}.{key}", value, 1, 10)


def _validate_names(
    report: ValidationReport, path: str, names: list[str], *, required: bool
) -> None:
    if required and not names:
        report.error("names.empty", path, "At least one name is required.")
        return
    seen: set[str] = set()
    for index, value in enumerate(names):
        item_path = f"{path}[{index}]"
        _required_text(report, item_path, value)
        folded = value.strip().casefold() if isinstance(value, str) else ""
        if folded in seen:
            report.error("names.duplicate", item_path, f"Duplicate name: {value!r}.")
        seen.add(folded)


def _duplicate(
    report: ValidationReport,
    seen: set[str],
    value: str,
    path: str,
    label: str,
) -> None:
    if value in seen:
        report.error("id.duplicate", path, f"Duplicate {label}: {value}.")
    seen.add(value)


def _effects(
    report: ValidationReport,
    effects: list[MechanicEffect],
    path: str,
    strict_release: bool,
    scope: RecipeScope,
) -> None:
    for index, effect in enumerate(effects):
        effect_path = f"{path}[{index}]"
        if not effect.description.strip():
            report.error("mechanic.description", f"{effect_path}.description", "Describe the effect.")
        recipe = recipe_by_id(effect.recipe_id)
        if recipe is not None and recipe.scope is not scope:
            message = (
                f"Recipe {effect.recipe_id!r} belongs to {recipe.scope.value}, not "
                f"{scope.value}."
            )
        elif recipe is not None and recipe.is_compiled:
            message = (
                f"Recipe {effect.recipe_id!r} is compiled only from its structured "
                f"field ({recipe.storage_path}); MechanicEffect entries are not emitted."
            )
        elif effect.implementation is ImplementationKind.DATABASE:
            message = (
                "No compiled database recipe matches this effect; use one of the "
                "verified structured trait, unit, or building fields."
            )
        elif effect.implementation is ImplementationKind.LUA_RECIPE:
            message = "No tested Lua recipe is registered for this effect."
        else:
            message = "This mechanic is explicitly unsupported by the current compiler."
        if strict_release:
            report.error("mechanic.unimplemented", effect_path, message)
        else:
            report.warning(
                "mechanic.unimplemented",
                effect_path,
                message + " It will be listed in UNIMPLEMENTED_EFFECTS.md.",
            )


def _validate_art(
    project: CivProject,
    report: ValidationReport,
    strict_release: bool,
    project_root: str | Path | None,
) -> None:
    expected = {
        (ArtRole.CIVILIZATION_ICON, "civilization"),
        (ArtRole.CIVILIZATION_ALPHA, "civilization"),
        (ArtRole.LEADER_PORTRAIT, "leader"),
        (ArtRole.LEADER_SCENE, "leader"),
        (ArtRole.DAWN_OF_MAN, "civilization"),
        (ArtRole.MAP_IMAGE, "civilization"),
    }
    for unit in project.units:
        expected.add((ArtRole.UNIQUE_UNIT_ICON, f"unit:{unit.key}"))
        expected.add((ArtRole.UNIT_FLAG, f"unit:{unit.key}"))
    for building in project.buildings:
        expected.add((ArtRole.UNIQUE_BUILDING_ICON, f"building:{building.key}"))
    for improvement in project.improvements:
        expected.add(
            (ArtRole.UNIQUE_IMPROVEMENT_ICON, f"improvement:{improvement.key}")
        )

    if 2 + len(project.units) + len(project.buildings) + len(project.improvements) > 64:
        report.error(
            "art.atlas-capacity",
            "art.assets",
            "The single 8x8 main atlas can hold at most 62 unique components after "
            "the civilization and leader slots.",
        )

    seen_ids: set[str] = set()
    seen_roles: set[tuple[ArtRole, str]] = set()
    root = Path(project_root).resolve() if project_root is not None else None
    for index, asset in enumerate(project.art.assets):
        path = f"art.assets[{index}]"
        if not _ASSET_ID_RE.fullmatch(asset.asset_id or ""):
            report.error("art.asset-id", f"{path}.asset_id", "Asset ID is not portable.")
        _duplicate(report, seen_ids, asset.asset_id, f"{path}.asset_id", "art asset ID")
        pair = (asset.role, asset.subject_key)
        if pair in seen_roles:
            report.error(
                "art.duplicate-role",
                path,
                f"Multiple assets claim {asset.role.value} for {asset.subject_key}.",
            )
        seen_roles.add(pair)
        if not is_portable_relative_path(asset.source_png):
            report.error(
                "path.unsafe",
                f"{path}.source_png",
                "Art source must be a portable relative path with no '..' components.",
            )
        elif root is not None and not (root / asset.source_png).is_file():
            severity = Severity.ERROR if strict_release and asset.required else Severity.WARNING
            report.add(
                severity,
                "art.source-missing",
                f"{path}.source_png",
                f"Art source does not exist: {asset.source_png}",
            )
        if asset.crop_mode not in {"cover", "contain", "manual"}:
            report.error(
                "art.crop-mode", f"{path}.crop_mode", "Crop mode must be cover, contain, or manual."
            )
        for axis, value in (("focal_x", asset.focal_x), ("focal_y", asset.focal_y)):
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                report.error(
                    "art.focal-range", f"{path}.{axis}", "Focal coordinates must be 0.0 through 1.0."
                )

    for role, subject in sorted(expected - seen_roles, key=lambda item: (item[0].value, item[1])):
        severity = Severity.ERROR if strict_release else Severity.WARNING
        location = {
            (ArtRole.CIVILIZATION_ICON, "civilization"): "art.civilization_icon.source",
            (ArtRole.CIVILIZATION_ALPHA, "civilization"): "art.civilization_alpha.source",
            (ArtRole.LEADER_PORTRAIT, "leader"): "art.leader_portrait.source",
            (ArtRole.LEADER_SCENE, "leader"): "leader.art.leader_scene",
            (ArtRole.DAWN_OF_MAN, "civilization"): "art.dawn_of_man.source",
            (ArtRole.MAP_IMAGE, "civilization"): "art.map_image.source",
        }.get((role, subject), "art.assets")
        if subject.startswith("unit:"):
            unit_key = subject.partition(":")[2]
            unit_index = next(
                (index for index, unit in enumerate(project.units) if unit.key == unit_key),
                -1,
            )
            field = (
                "unit_flag_source"
                if role is ArtRole.UNIT_FLAG
                else "icon_source"
            )
            if unit_index >= 0:
                location = f"units[{unit_index}].art.{field}"
        elif subject.startswith("building:"):
            building_key = subject.partition(":")[2]
            building_index = next(
                (
                    index
                    for index, building in enumerate(project.buildings)
                    if building.key == building_key
                ),
                -1,
            )
            if building_index >= 0:
                location = f"buildings[{building_index}].art.icon_source"
        elif subject.startswith("improvement:"):
            improvement_key = subject.partition(":")[2]
            improvement_index = next(
                (
                    index
                    for index, improvement in enumerate(project.improvements)
                    if improvement.key == improvement_key
                ),
                -1,
            )
            if improvement_index >= 0:
                location = f"improvements[{improvement_index}].art.icon_source"
        report.add(
            severity,
            "art.required-role",
            location,
            f"Missing {role.value} source for {subject}.",
        )
    if root is None and strict_release:
        report.error(
            "art.root-unverified",
            "art",
            "Strict release validation requires project_root so source files can be verified.",
        )
