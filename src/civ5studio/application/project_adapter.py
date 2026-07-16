"""Translate presentation dictionaries into the portable project model."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re
import shutil
from typing import Any

from civ5studio.domain import (
    ArtAssetSpec,
    ArtManifestSpec,
    ArtRole,
    CivilizationSpec,
    CivProject,
    DomainExperience,
    ImplementationKind,
    LeaderSpec,
    LuaEffectSelection,
    MechanicEffect,
    PlayerColors,
    ProjectDependencies,
    ProjectOptions,
    TraitSpec,
    UniqueBuildingSpec,
    UniqueImprovementSpec,
    UniqueUnitSpec,
    YieldChange,
    normalize_prefix,
    RecipeScope,
    recipes_for_scope,
    save_project,
    type_component,
)

from .advanced_content import (
    advanced_to_ui,
    materialize_advanced_sources,
    update_advanced_extension,
)


TRAIT_RECIPES: dict[str, tuple[str, bool]] = {
    recipe.label: (
        recipe.storage_path.rsplit(".", 1)[-1],
        recipe.parameters[0].kind.value == "boolean",
    )
    for recipe in recipes_for_scope(RecipeScope.TRAIT)
    if recipe.is_compiled
}

FLAVOR_IDS = {
    "offense": "FLAVOR_OFFENSE",
    "defense": "FLAVOR_DEFENSE",
    "expansion": "FLAVOR_EXPANSION",
    "growth": "FLAVOR_GROWTH",
    "science": "FLAVOR_SCIENCE",
    "culture": "FLAVOR_CULTURE",
    "diplomacy": "FLAVOR_DIPLOMACY",
    "wonder": "FLAVOR_WONDER",
}

_SOURCE_ROLE_PATHS = (
    ("leader_scene", ("leader", "art", "leader_scene")),
    ("leader_fallback", ("leader", "art", "leader_fallback")),
    ("civilization_icon", ("art", "civilization_icon", "source")),
    ("civilization_alpha", ("art", "civilization_alpha", "source")),
    ("leader_portrait", ("art", "leader_portrait", "source")),
    ("unique_unit_icon", ("art", "unique_unit_icon", "source")),
    ("unique_building_icon", ("art", "unique_building_icon", "source")),
    ("unit_flag", ("art", "unit_flag", "source")),
    ("dawn_of_man", ("art", "dawn_of_man", "source")),
    ("map_image", ("art", "map_image", "source")),
)


def save_ui_project(
    path: str | Path,
    ui_data: dict[str, Any],
    *,
    existing: CivProject | None = None,
    source_base: str | Path | None = None,
) -> tuple[CivProject, dict[str, Any]]:
    """Copy selected sources into the project and atomically save canonical JSON."""

    destination = Path(path).resolve()
    portable = materialize_ui_sources(
        ui_data,
        destination.parent,
        source_base=Path(source_base).resolve() if source_base else None,
    )
    project = project_from_ui(portable, existing=existing)
    project = materialize_advanced_sources(
        project,
        destination.parent,
        source_root=Path(source_base).resolve() if source_base else None,
    )
    save_project(destination, project)
    return project, portable


def materialize_ui_sources(
    ui_data: dict[str, Any],
    project_root: str | Path,
    *,
    source_base: Path | None = None,
) -> dict[str, Any]:
    """Return a copy with source art stored as project-relative read-only copies."""

    root = Path(project_root).resolve()
    result = deepcopy(ui_data)
    for role, key_path in _SOURCE_ROLE_PATHS:
        raw = _nested_get(result, key_path)
        portable = _materialize_source(raw, role, root, source_base)
        if portable is not None:
            _nested_set(result, key_path, portable)

    mechanics = _dict(result.get("mechanics"))
    unique_rows = mechanics.get("uniques", [])
    if isinstance(unique_rows, list):
        for index, raw_row in enumerate(unique_rows, start=1):
            if not isinstance(raw_row, dict):
                continue
            art = _dict(raw_row.get("art"))
            kind = _text(raw_row.get("kind")) or "unique"
            for field_name in ("icon_source", "unit_flag_source", "strategic_view_source"):
                portable = _materialize_source(
                    art.get(field_name),
                    f"{kind}_{index}_{field_name}",
                    root,
                    source_base,
                )
                if portable is not None:
                    art[field_name] = portable
            raw_row["art"] = art
    return result


def _materialize_source(
    raw: Any,
    role: str,
    root: Path,
    source_base: Path | None,
) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    source = Path(raw).expanduser()
    if not source.is_absolute() and source_base is not None:
        source = source_base / source
    source = source.resolve()
    if not source.is_file():
        return f"Assets/Source/MISSING_{role}.png"
    digest = _sha256(source)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", source.stem).strip("_") or role
    relative = Path("Assets") / "Source" / f"{stem}_{digest[:12]}{source.suffix.lower()}"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source, target)
    elif _sha256(target) != digest:
        relative = relative.with_name(f"{stem}_{digest[:20]}{source.suffix.lower()}")
        target = root / relative
        if not target.exists():
            shutil.copy2(source, target)
    return relative.as_posix()


def project_from_ui(
    ui_data: dict[str, Any], *, existing: CivProject | None = None
) -> CivProject:
    project_data = _dict(ui_data.get("project"))
    civ_data = _dict(ui_data.get("civilization"))
    leader_data = _dict(ui_data.get("leader"))
    mechanics = _dict(ui_data.get("mechanics"))
    trait_data = _dict(mechanics.get("trait"))
    art_data = _dict(ui_data.get("art"))
    advanced_present = "advanced" in ui_data
    advanced_data = _dict(ui_data.get("advanced"))
    pep_present = "promotions_expansion_pack" in ui_data
    pep_data = _dict(ui_data.get("promotions_expansion_pack"))
    lua_effects_present = "lua_effects" in ui_data
    lua_effects_data = _dict(ui_data.get("lua_effects"))
    pep_assignments = (
        pep_data.get("assignments", [])
        if isinstance(pep_data.get("assignments", []), list)
        else []
    )

    project = deepcopy(existing) if existing is not None else CivProject()
    previous_description = project.description
    previous_art = deepcopy(project.art)
    previous_units = deepcopy(project.units)
    previous_buildings = deepcopy(project.buildings)
    previous_improvements = deepcopy(project.improvements)
    previous_ui_extension = _dict(deepcopy(project.extensions.get("ui")))
    previous_transforms = _dict(previous_ui_extension.get("art_transforms"))
    project.mod_name = _text(project_data.get("mod_name"))
    project.mod_version = _integer(project_data.get("version"), 1)
    project.authors = _text(project_data.get("author"))
    project.description = _text(project_data.get("description"))
    if existing is None or project.teaser == _derived_teaser(previous_description):
        project.teaser = _derived_teaser(project.description)
    project.internal_prefix = normalize_prefix(_text(project_data.get("prefix")))
    options = deepcopy(project.options) if existing is not None else ProjectOptions()
    options.affects_saved_games = bool(project_data.get("affects_saved_games", True))
    project.options = options
    dependencies = (
        deepcopy(project.dependencies)
        if existing is not None
        else ProjectDependencies()
    )
    if pep_present:
        dependencies.promotions_expansion_pack = bool(pep_data.get("enabled", False))
    project.dependencies = dependencies
    if lua_effects_present:
        raw_lua_selections = lua_effects_data.get("selections", [])
        project.lua_effects = _lua_effect_selections(raw_lua_selections)

    base_civ = _text(civ_data.get("base_civilization")) or "CIVILIZATION_POLAND"
    civilization = (
        deepcopy(project.civilization)
        if existing is not None
        else CivilizationSpec(
            base_civilization=base_civ,
            copy_free_buildings_from=base_civ,
            copy_free_techs_and_units_from=base_civ,
        )
    )
    civilization.name = _text(civ_data.get("name"))
    civilization.short_name = _text(civ_data.get("short_name"))
    civilization.adjective = _text(civ_data.get("adjective"))
    civilization.civilopedia = _text(civ_data.get("civilopedia"))
    civilization.dawn_of_man_quote = _text(civ_data.get("dawn_of_man_quote"))
    civilization.base_civilization = base_civ
    civilization.city_names = _string_list(civ_data.get("city_names"))
    civilization.spy_names = _string_list(civ_data.get("spy_names"))
    project.civilization = civilization

    leader_name = _text(leader_data.get("name"))
    leader = deepcopy(project.leader) if existing is not None else LeaderSpec()
    if existing is None:
        leader.key = type_component(leader_name) or "LEADER"
    leader.name = leader_name
    leader.civilopedia = _text(leader_data.get("civilopedia"))
    incoming_flavors = _dict(leader_data.get("flavors"))
    for key, flavor_id in FLAVOR_IDS.items():
        if key in incoming_flavors:
            leader.flavors[flavor_id] = _integer(incoming_flavors[key], 5)
    if advanced_present:
        diplomacy = _dict(advanced_data.get("diplomacy_text"))
        leader.diplomacy_text = {
            _text(response): _text(line)
            for response, line in diplomacy.items()
            if _text(response)
        }
    project.leader = leader

    trait_name = _text(trait_data.get("name"))
    recipe = _text(trait_data.get("recipe"))
    implementation_label = _text(trait_data.get("implementation_class"))
    effect_description = _text(trait_data.get("effect_description"))
    project.trait = _update_trait(
        project.trait if existing is not None else None,
        trait_name=trait_name,
        short_description=_text(trait_data.get("short_description")),
        effect_description=effect_description,
        implementation_label=implementation_label,
        recipe=recipe,
        modifier_value=_integer(trait_data.get("modifier_value"), 0),
    )

    units: list[UniqueUnitSpec] = []
    buildings: list[UniqueBuildingSpec] = []
    improvements: list[UniqueImprovementSpec] = []
    unsupported_rows: list[dict[str, Any]] = []
    unit_index = 0
    building_index = 0
    improvement_index = 0
    used_previous_units: set[int] = set()
    used_previous_buildings: set[int] = set()
    used_previous_improvements: set[int] = set()
    unique_row_values = (
        mechanics.get("uniques", [])
        if isinstance(mechanics.get("uniques", []), list)
        else []
    )
    for index, row_value in enumerate(unique_row_values, start=1):
        row = _dict(row_value)
        kind = _text(row.get("kind")).lower()
        name = _text(row.get("name"))
        override = _text(row.get("override"))
        value = _optional_int(row.get("value"))
        if kind == "unit":
            row_key = _text(row.get("key"))
            original_key = _text(row.get("original_key"))
            old_match = _match_previous_unique(
                previous_units,
                used_previous_units,
                row_key=original_key or row_key,
                legacy_position=unit_index,
            )
            unit_index += 1
            key = (
                row_key
                or (old_match.key if old_match else "")
                or type_component(name)
                or f"UNIT_{index}"
            )
            prior = deepcopy(old_match) if old_match else UniqueUnitSpec(key=key)
            prior.key = key
            old_help = prior.help_text
            old_strategy = prior.strategy_text
            prior.name = name
            prior.help_text = _text(row.get("help_text"))
            if "strategy_text" in row:
                prior.strategy_text = _text(row.get("strategy_text"))
            elif old_match is None or old_strategy == old_help:
                prior.strategy_text = prior.help_text
            prior.replaces_unit_class = _text(row.get("replaces_class"))
            prior.base_unit = _text(row.get("base_template"))
            old_override, old_value = _unit_override(prior)
            incoming_stats = {
                field: _optional_int(row.get(field))
                for field in ("combat", "ranged_combat", "moves", "cost")
                if field in row
            }
            advanced_changed = old_match is None and any(
                item is not None for item in incoming_stats.values()
            )
            if old_match is not None:
                advanced_changed = any(
                    getattr(prior, field) != incoming
                    for field, incoming in incoming_stats.items()
                )
            legacy_changed = override != old_override or (
                override and _text(row.get("value")) != old_value
            )
            if legacy_changed and not advanced_changed:
                if old_override and old_override != override:
                    setattr(prior, _unit_override_field(old_override), None)
                if override in {"Combat", "RangedCombat", "Moves", "Cost"}:
                    setattr(prior, _snake_case(override), value)
                elif old_override:
                    setattr(prior, _unit_override_field(old_override), None)
            else:
                for field, incoming in incoming_stats.items():
                    setattr(prior, field, incoming)
            if "prereq_tech" in row:
                prior.prereq_tech = _text(row.get("prereq_tech")) or None
            if "free_promotions" in row:
                prior.free_promotions = _string_list(row.get("free_promotions"))
            if pep_present:
                assigned = []
                for raw_assignment in pep_assignments:
                    assignment = _dict(raw_assignment)
                    assignment_key = _text(assignment.get("unit_key"))
                    assignment_name = _text(assignment.get("unit_name"))
                    assignment_index = _optional_int(assignment.get("unit_index"))
                    if assignment_key:
                        targets_unit = assignment_key in {prior.key, original_key}
                    elif assignment_name:
                        targets_unit = assignment_name == prior.name
                    else:
                        targets_unit = assignment_index == unit_index - 1
                    if not targets_unit:
                        continue
                    promotion = _text(assignment.get("promotion_type"))
                    if promotion and promotion not in assigned:
                        assigned.append(promotion)
                prior.promotions_expansion_pack = assigned
            units.append(prior)
        elif kind == "building":
            row_key = _text(row.get("key"))
            original_key = _text(row.get("original_key"))
            old_match = _match_previous_unique(
                previous_buildings,
                used_previous_buildings,
                row_key=original_key or row_key,
                legacy_position=building_index,
            )
            building_index += 1
            key = (
                row_key
                or (old_match.key if old_match else "")
                or type_component(name)
                or f"BUILDING_{index}"
            )
            prior = (
                deepcopy(old_match)
                if old_match
                else UniqueBuildingSpec(key=key)
            )
            prior.key = key
            old_help = prior.help_text
            old_strategy = prior.strategy_text
            prior.name = name
            prior.help_text = _text(row.get("help_text"))
            if "strategy_text" in row:
                prior.strategy_text = _text(row.get("strategy_text"))
            elif old_match is None or old_strategy == old_help:
                prior.strategy_text = prior.help_text
            prior.replaces_building_class = _text(row.get("replaces_class"))
            prior.base_building = _text(row.get("base_template"))
            old_override, old_value = _building_override(prior)
            incoming_stats = {
                field: _optional_int(row.get(field))
                for field in (
                    "cost", "gold_maintenance", "defense", "extra_city_hit_points"
                )
                if field in row
            }
            incoming_yields = (
                _yield_changes(row.get("yield_changes"))
                if "yield_changes" in row
                else prior.yield_changes
            )
            incoming_xp = (
                _domain_experience(row.get("domain_free_experience"))
                if "domain_free_experience" in row
                else prior.domain_free_experience
            )
            advanced_changed = old_match is None and (
                any(item is not None for item in incoming_stats.values())
                or bool(incoming_yields)
                or bool(incoming_xp)
            )
            if old_match is not None:
                advanced_changed = (
                    any(
                        getattr(prior, field) != incoming
                        for field, incoming in incoming_stats.items()
                    )
                    or incoming_yields != prior.yield_changes
                    or incoming_xp != prior.domain_free_experience
                )
            legacy_changed = override != old_override or (
                override and _text(row.get("value")) != old_value
            )
            if legacy_changed and not advanced_changed:
                if old_override and old_override != override:
                    _clear_building_override(prior, old_override)
                if override.startswith("Yield:") and value is not None:
                    yield_type = override.partition(":")[2]
                    prior.yield_changes = [
                        item for item in prior.yield_changes if item.yield_type != yield_type
                    ]
                    prior.yield_changes.append(YieldChange(yield_type, value))
                elif override in {
                    "Cost", "GoldMaintenance", "Defense", "ExtraCityHitPoints"
                }:
                    setattr(prior, _snake_case(override), value)
                elif old_override:
                    _clear_building_override(prior, old_override)
            else:
                for field, incoming in incoming_stats.items():
                    setattr(prior, field, incoming)
                if "yield_changes" in row:
                    prior.yield_changes = incoming_yields
                if "domain_free_experience" in row:
                    prior.domain_free_experience = incoming_xp
            if "prereq_tech" in row:
                prior.prereq_tech = _text(row.get("prereq_tech")) or None
            buildings.append(prior)
        elif kind == "improvement":
            row_key = _text(row.get("key"))
            original_key = _text(row.get("original_key"))
            old_match = _match_previous_unique(
                previous_improvements,
                used_previous_improvements,
                row_key=original_key or row_key,
                legacy_position=improvement_index,
            )
            improvement_index += 1
            key = (
                row_key
                or (old_match.key if old_match else "")
                or type_component(name)
                or f"IMPROVEMENT_{index}"
            )
            prior = (
                deepcopy(old_match)
                if old_match
                else UniqueImprovementSpec(key=key)
            )
            prior.key = key
            old_help = prior.help_text
            old_strategy = prior.strategy_text
            prior.name = name
            prior.help_text = _text(row.get("help_text"))
            if "strategy_text" in row:
                prior.strategy_text = _text(row.get("strategy_text"))
            elif old_match is None or old_strategy == old_help:
                prior.strategy_text = prior.help_text
            if "civilopedia_text" in row:
                prior.civilopedia_text = _text(row.get("civilopedia_text"))
            prior.base_improvement = _text(row.get("base_template"))
            if "prereq_tech" in row:
                prior.build_prereq_tech = _text(row.get("prereq_tech")) or None
            if "yield_changes" in row:
                prior.yield_changes = _yield_changes(row.get("yield_changes"))
            improvements.append(prior)
        else:
            unsupported_rows.append(deepcopy(row))
    project.units = units
    project.buildings = buildings
    project.improvements = improvements

    color_data = _dict(civ_data.get("colors"))
    primary = _hex_to_rgb(_text(color_data.get("primary")) or "#b32222")
    secondary = _hex_to_rgb(_text(color_data.get("secondary")) or "#ffd700")
    colors = deepcopy(project.colors) if existing is not None else PlayerColors()
    colors.primary_red, colors.primary_green, colors.primary_blue = primary
    colors.secondary_red, colors.secondary_green, colors.secondary_blue = secondary
    project.colors = colors

    assets = _art_assets(
        art_data,
        leader_data,
        units,
        buildings,
        improvements,
        unique_rows=[_dict(value) for value in unique_row_values],
        existing=previous_art if existing is not None else None,
        previous_first_unit=(previous_units[0].key if previous_units else ""),
        previous_first_building=(previous_buildings[0].key if previous_buildings else ""),
        previous_transforms=previous_transforms,
    )
    if existing is not None:
        previous_art.assets = assets
        project.art = previous_art
    else:
        project.art = ArtManifestSpec(
            contract_version="smp-civ5-v1",
            allow_placeholders=False,
            assets=assets,
        )
    project.extensions = dict(project.extensions)
    ui_extension = deepcopy(previous_ui_extension)
    ui_extension["project_root"] = _text(project_data.get("project_root"))
    ui_extension["leader_title"] = _text(leader_data.get("title"))
    merged_transforms = deepcopy(previous_transforms)
    for role, entry in art_data.items():
        if not isinstance(entry, dict):
            continue
        transform = _dict(entry.get("transform"))
        preserved = _dict(merged_transforms.get(role))
        preserved.update(deepcopy(transform))
        merged_transforms[role] = preserved
    ui_extension["art_transforms"] = merged_transforms
    preserved_unsupported = list(
        previous_ui_extension.get("unsupported_unique_rows", [])
        if isinstance(previous_ui_extension.get("unsupported_unique_rows"), list)
        else []
    )
    for row in unsupported_rows:
        if row not in preserved_unsupported:
            preserved_unsupported.append(row)
    ui_extension["unsupported_unique_rows"] = preserved_unsupported
    project.extensions["ui"] = ui_extension
    if advanced_present:
        project = update_advanced_extension(project, advanced_data)
    return project


def project_to_ui(project: CivProject, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    ui_extension = _dict(project.extensions.get("ui"))
    transforms = _dict(ui_extension.get("art_transforms"))
    implementation_label, recipe, modifier_value = _trait_projection(project.trait)

    assets = {(asset.role, asset.subject_key): asset for asset in project.art.assets}

    def source(role: ArtRole, subject: str) -> str:
        asset = assets.get((role, subject))
        return str((root / asset.source_png).resolve()) if asset else ""

    units = [
        _unit_row(
            item,
            icon_source=source(ArtRole.UNIQUE_UNIT_ICON, f"unit:{item.key}"),
            unit_flag_source=source(ArtRole.UNIT_FLAG, f"unit:{item.key}"),
            strategic_view_source=source(
                ArtRole.STRATEGIC_VIEW, f"unit:{item.key}"
            ),
        )
        for item in project.units
    ]
    buildings = [
        _building_row(
            item,
            icon_source=source(
                ArtRole.UNIQUE_BUILDING_ICON, f"building:{item.key}"
            ),
        )
        for item in project.buildings
    ]
    improvements = [
        _improvement_row(
            item,
            icon_source=source(
                ArtRole.UNIQUE_IMPROVEMENT_ICON, f"improvement:{item.key}"
            ),
        )
        for item in project.improvements
    ]
    first_unit = project.units[0].key if project.units else ""
    first_building = project.buildings[0].key if project.buildings else ""

    art_roles = (
        "civilization_icon",
        "civilization_alpha",
        "leader_portrait",
        "unique_unit_icon",
        "unique_building_icon",
        "unit_flag",
        "dawn_of_man",
        "map_image",
    )
    sources = {
        "civilization_icon": source(ArtRole.CIVILIZATION_ICON, "civilization"),
        "civilization_alpha": source(ArtRole.CIVILIZATION_ALPHA, "civilization"),
        "leader_portrait": source(ArtRole.LEADER_PORTRAIT, "leader"),
        "unique_unit_icon": source(
            ArtRole.UNIQUE_UNIT_ICON, f"unit:{first_unit}"
        ) if first_unit else "",
        "unique_building_icon": source(
            ArtRole.UNIQUE_BUILDING_ICON, f"building:{first_building}"
        ) if first_building else "",
        "unit_flag": source(ArtRole.UNIT_FLAG, f"unit:{first_unit}") if first_unit else "",
        "dawn_of_man": source(ArtRole.DAWN_OF_MAN, "civilization"),
        "map_image": source(ArtRole.MAP_IMAGE, "civilization"),
    }
    art = {
        role: {
            "source": sources[role],
            "transform": _transform_dict(transforms.get(role)),
        }
        for role in art_roles
    }
    result = {
        "schema_version": 1,
        "project": {
            "mod_name": project.mod_name,
            "prefix": project.internal_prefix,
            "version": project.mod_version,
            "author": project.authors,
            "description": project.description,
            "affects_saved_games": project.options.affects_saved_games,
            "project_root": _text(ui_extension.get("project_root"))
            or str(root / "Build Output"),
        },
        "civilization": {
            "name": project.civilization.name,
            "short_name": project.civilization.short_name,
            "adjective": project.civilization.adjective,
            "base_civilization": project.civilization.base_civilization,
            "dawn_of_man_quote": project.civilization.dawn_of_man_quote,
            "civilopedia": project.civilization.civilopedia,
            "colors": {
                "primary": _rgb_to_hex(
                    project.colors.primary_red,
                    project.colors.primary_green,
                    project.colors.primary_blue,
                ),
                "secondary": _rgb_to_hex(
                    project.colors.secondary_red,
                    project.colors.secondary_green,
                    project.colors.secondary_blue,
                ),
            },
            "city_names": list(project.civilization.city_names),
            "spy_names": list(project.civilization.spy_names),
        },
        "leader": {
            "name": project.leader.name,
            "title": _text(ui_extension.get("leader_title")),
            "civilopedia": project.leader.civilopedia,
            "flavors": {
                key: project.leader.flavors.get(flavor_id, 5)
                for key, flavor_id in FLAVOR_IDS.items()
            },
            "art": {
                "leader_scene": source(ArtRole.LEADER_SCENE, "leader"),
                "leader_fallback": source(ArtRole.LEADER_PORTRAIT, "leader"),
            },
        },
        "mechanics": {
            "trait": {
                "name": project.trait.name,
                "short_description": project.trait.short_description,
                "implementation_class": implementation_label,
                "recipe": recipe,
                "modifier_value": modifier_value,
                "effect_description": project.trait.long_description,
            },
            "uniques": [*units, *buildings, *improvements],
        },
        "promotions_expansion_pack": {
            "enabled": project.dependencies.promotions_expansion_pack,
            "assignments": [
                {
                    "unit_key": unit.key,
                    "unit_name": unit.name,
                    "unit_index": index,
                    "promotion_type": promotion,
                }
                for index, unit in enumerate(project.units)
                for promotion in unit.promotions_expansion_pack
            ],
        },
        "lua_effects": {
            "selections": [
                {
                    "instance_id": selection.instance_id,
                    "effect_id": selection.effect_id,
                    "effect_version": selection.effect_version,
                    "parameters": deepcopy(selection.parameters),
                }
                for selection in project.lua_effects
            ]
        },
        "art": art,
    }
    advanced = advanced_to_ui(project, root)
    advanced["diplomacy_text"] = dict(project.leader.diplomacy_text)
    result["advanced"] = advanced
    return result


def _trait_projection(trait: TraitSpec) -> tuple[str, str, int]:
    reverse_recipes = {
        column: recipe for recipe, (column, _boolean) in TRAIT_RECIPES.items()
    }
    if trait.database_modifiers:
        column, value = next(iter(trait.database_modifiers.items()))
        return "Database-native recipe", reverse_recipes.get(column, column), int(value)
    if trait.effects:
        effect = trait.effects[0]
        implementation = (
            "Lua idea (not compiled)"
            if effect.implementation is ImplementationKind.LUA_RECIPE
            else "Custom code / DLL required"
        )
        return (
            implementation,
            effect.recipe_id or "Unimplemented custom mechanic",
            10,
        )
    return "Database-native recipe", "No database modifier", 10


def _update_trait(
    existing: TraitSpec | None,
    *,
    trait_name: str,
    short_description: str,
    effect_description: str,
    implementation_label: str,
    recipe: str,
    modifier_value: int,
) -> TraitSpec:
    """Update the single exposed trait slot while retaining hidden mechanics."""

    trait = deepcopy(existing) if existing is not None else TraitSpec()
    old_long_description = trait.long_description
    if existing is None:
        trait.key = type_component(trait_name) or "TRAIT"
    trait.name = trait_name
    trait.short_description = short_description
    trait.long_description = effect_description

    visible_modifier = (
        next(iter(trait.database_modifiers)) if trait.database_modifiers else ""
    )
    visible_effect = 0 if not visible_modifier and trait.effects else None
    is_database = implementation_label.startswith("Database")
    is_empty = not recipe or recipe == "No database modifier"

    database_column = ""
    boolean_value = False
    if is_database and not is_empty:
        if recipe in TRAIT_RECIPES:
            database_column, boolean_value = TRAIT_RECIPES[recipe]
        elif visible_modifier and recipe == visible_modifier:
            database_column = visible_modifier
            boolean_value = isinstance(
                trait.database_modifiers.get(visible_modifier), bool
            )

    if database_column:
        database_value: int | bool = (
            bool(modifier_value) if boolean_value else modifier_value
        )
        if visible_modifier:
            trait.database_modifiers = _replace_first_mapping_entry(
                trait.database_modifiers,
                visible_modifier,
                database_column,
                database_value,
            )
        else:
            trait.database_modifiers[database_column] = database_value
            if visible_effect is not None:
                trait.effects.pop(visible_effect)
        return trait

    if is_database and is_empty:
        if visible_modifier:
            trait.database_modifiers.pop(visible_modifier, None)
        elif visible_effect is not None:
            trait.effects.pop(visible_effect)
        return trait

    kind = (
        ImplementationKind.LUA_RECIPE
        if implementation_label.startswith(("Lua idea", "Tested Lua"))
        else ImplementationKind.UNSUPPORTED
    )
    if visible_modifier:
        trait.database_modifiers.pop(visible_modifier, None)
    if visible_effect is not None:
        effect = trait.effects[visible_effect]
        created_effect = False
    else:
        effect = MechanicEffect(
            notes="Selected in the GUI but no verified compiler recipe is registered."
        )
        trait.effects.insert(0, effect)
        created_effect = True
    if created_effect or effect.description == old_long_description:
        effect.description = effect_description or recipe
    effect.implementation = kind
    projected_recipe = effect.recipe_id or "Unimplemented custom mechanic"
    if created_effect or recipe != projected_recipe:
        effect.recipe_id = type_component(recipe)
    return trait


def _replace_first_mapping_entry(
    values: dict[str, int | bool],
    old_key: str,
    new_key: str,
    new_value: int | bool,
) -> dict[str, int | bool]:
    result: dict[str, int | bool] = {}
    for key, value in values.items():
        if key == old_key:
            result[new_key] = new_value
        elif key != new_key:
            result[key] = value
    return result


def _match_previous_unique(
    previous: list[Any],
    used_indices: set[int],
    *,
    row_key: str,
    legacy_position: int,
) -> Any | None:
    """Return one prior component without transferring state across stable keys.

    Current UI rows always carry their domain key, so a keyed row may inherit
    hidden fields only from the previous object with that exact key. Older UI
    payloads did not carry keys; those rows retain the historical positional
    fallback when that previous position has not already been consumed.
    """

    if row_key:
        for index, candidate in enumerate(previous):
            candidate_key = _text(getattr(candidate, "key", ""))
            if index in used_indices or candidate_key != row_key:
                continue
            used_indices.add(index)
            return candidate
        return None
    if 0 <= legacy_position < len(previous) and legacy_position not in used_indices:
        used_indices.add(legacy_position)
        return previous[legacy_position]
    return None


def _art_assets(
    art: dict[str, Any],
    leader: dict[str, Any],
    units: list[UniqueUnitSpec],
    buildings: list[UniqueBuildingSpec],
    improvements: list[UniqueImprovementSpec],
    *,
    unique_rows: list[dict[str, Any]],
    existing: ArtManifestSpec | None = None,
    previous_first_unit: str = "",
    previous_first_building: str = "",
    previous_transforms: dict[str, Any] | None = None,
) -> list[ArtAssetSpec]:
    """Merge exposed art slots without flattening per-subject manifest entries."""

    leader_art = _dict(leader.get("art"))
    paths = {
        ArtRole.CIVILIZATION_ICON: _art_path(art, "civilization_icon"),
        ArtRole.CIVILIZATION_ALPHA: _art_path(art, "civilization_alpha"),
        ArtRole.LEADER_PORTRAIT: _art_path(art, "leader_portrait")
        or _text(leader_art.get("leader_fallback")),
        ArtRole.LEADER_SCENE: _text(leader_art.get("leader_scene")),
        ArtRole.DAWN_OF_MAN: _art_path(art, "dawn_of_man"),
        ArtRole.MAP_IMAGE: _art_path(art, "map_image"),
    }
    old_transforms = previous_transforms or {}
    unit_rows = [row for row in unique_rows if _text(row.get("kind")).lower() == "unit"]
    building_rows = [
        row for row in unique_rows if _text(row.get("kind")).lower() == "building"
    ]
    improvement_rows = [
        row for row in unique_rows if _text(row.get("kind")).lower() == "improvement"
    ]
    subject_renames: dict[str, str] = {}
    for prefix, rows, specs in (
        ("unit", unit_rows, units),
        ("building", building_rows, buildings),
        ("improvement", improvement_rows, improvements),
    ):
        for row, spec in zip(rows, specs, strict=False):
            original_key = _text(row.get("original_key"))
            if original_key and original_key != spec.key:
                subject_renames[f"{prefix}:{original_key}"] = (
                    f"{prefix}:{spec.key}"
                )

    active_units = {f"unit:{item.key}" for item in units}
    active_buildings = {f"building:{item.key}" for item in buildings}
    active_improvements = {
        f"improvement:{item.key}" for item in improvements
    }
    result = []
    for asset in deepcopy(existing.assets if existing is not None else []):
        if asset.subject_key in subject_renames:
            asset.subject_key = subject_renames[asset.subject_key]
        if asset.subject_key.startswith("unit:") and asset.subject_key not in active_units:
            continue
        if (
            asset.subject_key.startswith("building:")
            and asset.subject_key not in active_buildings
        ):
            continue
        if (
            asset.subject_key.startswith("improvement:")
            and asset.subject_key not in active_improvements
        ):
            continue
        result.append(asset)

    def matching(role: ArtRole, subject: str) -> list[int]:
        return [
            index
            for index, asset in enumerate(result)
            if asset.role is role and asset.subject_key == subject
        ]

    def upsert(
        role: ArtRole,
        subject: str,
        path: str,
        suffix: str = "",
        *,
        exposed: bool = True,
        transform_role: str | None = None,
        apply_transform: bool = True,
    ) -> None:
        matches = matching(role, subject)
        if existing is not None and not exposed and matches:
            return
        if not path:
            if exposed and matches:
                remove = set(matches)
                result[:] = [
                    asset for index, asset in enumerate(result) if index not in remove
                ]
            return

        normalized_path = path.replace("\\", "/")
        role_name = transform_role or role.value
        incoming_transform = _transform_dict(
            _dict(_dict(art.get(role_name)).get("transform"))
        )
        old_transform = _transform_dict(old_transforms.get(role_name))
        transform_changed = apply_transform and (
            existing is None or incoming_transform != old_transform
        )
        if matches:
            asset = result[matches[-1]]
            asset.source_png = _preserve_relative_source(
                normalized_path, asset.source_png
            )
            if transform_changed:
                asset.focal_x = 0.5 + incoming_transform["offset_x"] / 200
                asset.focal_y = 0.5 + incoming_transform["offset_y"] / 200
            return

        asset_id = f"{role.value}{suffix}".replace(":", "-")[:80]
        result.append(
            ArtAssetSpec(
                asset_id=asset_id,
                role=role,
                source_png=normalized_path,
                subject_key=subject,
                required=True,
                crop_mode="manual",
                focal_x=0.5 + incoming_transform["offset_x"] / 200,
                focal_y=0.5 + incoming_transform["offset_y"] / 200,
            )
        )

    def unique_path(
        role: ArtRole,
        subject: str,
        row_art: dict[str, Any],
        field_name: str,
        shared_path: str = "",
    ) -> tuple[str, bool]:
        """Resolve new per-unique art against the former shared first-row slot.

        A loaded absolute row path that resolves to the existing portable path is
        unchanged. This lets legacy Art Studio edits still update the first unique,
        while an actual per-unique edit remains authoritative.
        """

        row_exposed = field_name in row_art
        row_path = _text(row_art.get(field_name))
        matches = matching(role, subject)
        if not matches:
            return (row_path if row_exposed else shared_path), row_exposed or bool(shared_path)
        stored = result[matches[-1]].source_png
        row_changed = row_exposed and (
            not row_path or _preserve_relative_source(row_path, stored) != stored
        )
        shared_changed = bool(shared_path) and (
            _preserve_relative_source(shared_path, stored) != stored
        )
        if row_changed:
            return row_path, True
        if shared_changed:
            return shared_path, True
        return (row_path if row_exposed else shared_path), row_exposed

    for role, path in paths.items():
        subject = (
            "leader"
            if role in {ArtRole.LEADER_PORTRAIT, ArtRole.LEADER_SCENE}
            else "civilization"
        )
        upsert(role, subject, path)
    shared_unit_icon = _art_path(art, "unique_unit_icon")
    shared_flag = _art_path(art, "unit_flag")
    for index, unit in enumerate(units):
        subject = f"unit:{unit.key}"
        row_art = _dict(unit_rows[index].get("art")) if index < len(unit_rows) else {}
        original_key = (
            _text(unit_rows[index].get("original_key"))
            if index < len(unit_rows)
            else ""
        )
        was_exposed = (
            existing is None
            or (original_key or unit.key) == previous_first_unit
        )
        icon_path, icon_exposed = unique_path(
            ArtRole.UNIQUE_UNIT_ICON,
            subject,
            row_art,
            "icon_source",
            shared_unit_icon if was_exposed else "",
        )
        flag_path, flag_exposed = unique_path(
            ArtRole.UNIT_FLAG,
            subject,
            row_art,
            "unit_flag_source",
            shared_flag if was_exposed else "",
        )
        strategic_path, strategic_exposed = unique_path(
            ArtRole.STRATEGIC_VIEW,
            subject,
            row_art,
            "strategic_view_source",
        )
        upsert(
            ArtRole.UNIQUE_UNIT_ICON,
            subject,
            icon_path,
            f"-{unit.key}",
            exposed=icon_exposed or was_exposed,
            transform_role="unique_unit_icon",
            apply_transform=was_exposed,
        )
        upsert(
            ArtRole.UNIT_FLAG,
            subject,
            flag_path,
            f"-{unit.key}",
            exposed=flag_exposed or was_exposed,
            transform_role="unit_flag",
            apply_transform=was_exposed,
        )
        upsert(
            ArtRole.STRATEGIC_VIEW,
            subject,
            strategic_path,
            f"-{unit.key}",
            exposed=strategic_exposed,
            transform_role="strategic_view",
            apply_transform=False,
        )
    shared_building_icon = _art_path(art, "unique_building_icon")
    for index, building in enumerate(buildings):
        row_art = (
            _dict(building_rows[index].get("art"))
            if index < len(building_rows)
            else {}
        )
        original_key = (
            _text(building_rows[index].get("original_key"))
            if index < len(building_rows)
            else ""
        )
        was_exposed = (
            existing is None
            or (original_key or building.key) == previous_first_building
        )
        icon_path, icon_exposed = unique_path(
            ArtRole.UNIQUE_BUILDING_ICON,
            f"building:{building.key}",
            row_art,
            "icon_source",
            shared_building_icon if was_exposed else "",
        )
        upsert(
            ArtRole.UNIQUE_BUILDING_ICON,
            f"building:{building.key}",
            icon_path,
            f"-{building.key}",
            exposed=(
                icon_exposed
                or was_exposed
            ),
            transform_role="unique_building_icon",
            apply_transform=was_exposed,
        )
    for index, improvement in enumerate(improvements):
        row_art = (
            _dict(improvement_rows[index].get("art"))
            if index < len(improvement_rows)
            else {}
        )
        subject = f"improvement:{improvement.key}"
        icon_path, icon_exposed = unique_path(
            ArtRole.UNIQUE_IMPROVEMENT_ICON,
            subject,
            row_art,
            "icon_source",
        )
        upsert(
            ArtRole.UNIQUE_IMPROVEMENT_ICON,
            subject,
            icon_path,
            f"-{improvement.key}",
            exposed=icon_exposed or existing is None,
            transform_role="unique_improvement_icon",
            apply_transform=False,
        )
    return result


def _unit_row(
    item: UniqueUnitSpec,
    *,
    icon_source: str,
    unit_flag_source: str,
    strategic_view_source: str,
) -> dict[str, Any]:
    override, value = _unit_override(item)
    return {
        "kind": "unit",
        "key": item.key,
        "original_key": item.key,
        "name": item.name,
        "replaces_class": item.replaces_unit_class,
        "base_template": item.base_unit,
        "override": override,
        "value": value,
        "help_text": item.help_text,
        "strategy_text": item.strategy_text,
        "combat": item.combat,
        "ranged_combat": item.ranged_combat,
        "moves": item.moves,
        "cost": item.cost,
        "prereq_tech": item.prereq_tech or "",
        "free_promotions": list(item.free_promotions),
        "art": {
            "icon_source": icon_source,
            "unit_flag_source": unit_flag_source,
            "strategic_view_source": strategic_view_source,
        },
    }


def _building_row(
    item: UniqueBuildingSpec, *, icon_source: str
) -> dict[str, Any]:
    override, value = _building_override(item)
    return {
        "kind": "building",
        "key": item.key,
        "original_key": item.key,
        "name": item.name,
        "replaces_class": item.replaces_building_class,
        "base_template": item.base_building,
        "override": override,
        "value": value,
        "help_text": item.help_text,
        "strategy_text": item.strategy_text,
        "cost": item.cost,
        "gold_maintenance": item.gold_maintenance,
        "defense": item.defense,
        "extra_city_hit_points": item.extra_city_hit_points,
        "prereq_tech": item.prereq_tech or "",
        "yield_changes": [
            {"yield_type": change.yield_type, "amount": change.amount}
            for change in item.yield_changes
        ],
        "domain_free_experience": [
            {"domain_type": change.domain_type, "amount": change.amount}
            for change in item.domain_free_experience
        ],
        "art": {"icon_source": icon_source},
    }


def _improvement_row(
    item: UniqueImprovementSpec, *, icon_source: str
) -> dict[str, Any]:
    return {
        "kind": "improvement",
        "key": item.key,
        "original_key": item.key,
        "name": item.name,
        "replaces_class": "",
        "base_template": item.base_improvement,
        "override": "Yield:YIELD_PRODUCTION",
        "value": "",
        "help_text": item.help_text,
        "strategy_text": item.strategy_text,
        "civilopedia_text": item.civilopedia_text,
        "prereq_tech": item.build_prereq_tech or "",
        "yield_changes": [
            {"yield_type": change.yield_type, "amount": change.amount}
            for change in item.yield_changes
        ],
        "art": {"icon_source": icon_source},
    }


def _unit_override(item: UniqueUnitSpec) -> tuple[str, str]:
    for label, field in (
        ("Combat", "combat"),
        ("RangedCombat", "ranged_combat"),
        ("Moves", "moves"),
        ("Cost", "cost"),
    ):
        current = getattr(item, field)
        if current is not None:
            return label, str(current)
    return "", ""


def _unit_override_field(label: str) -> str:
    return {
        "Combat": "combat",
        "RangedCombat": "ranged_combat",
        "Moves": "moves",
        "Cost": "cost",
    }[label]


def _building_override(item: UniqueBuildingSpec) -> tuple[str, str]:
    for label, field in (
        ("Cost", "cost"),
        ("GoldMaintenance", "gold_maintenance"),
        ("Defense", "defense"),
        ("ExtraCityHitPoints", "extra_city_hit_points"),
    ):
        current = getattr(item, field)
        if current is not None:
            return label, str(current)
    if item.yield_changes:
        return (
            f"Yield:{item.yield_changes[0].yield_type}",
            str(item.yield_changes[0].amount),
        )
    return "", ""


def _clear_building_override(item: UniqueBuildingSpec, label: str) -> None:
    if label.startswith("Yield:"):
        yield_type = label.partition(":")[2]
        item.yield_changes = [
            value for value in item.yield_changes if value.yield_type != yield_type
        ]
    else:
        setattr(item, _snake_case(label), None)


def _art_path(art: dict[str, Any], role: str) -> str:
    return _text(_dict(art.get(role)).get("source"))


def _preserve_relative_source(incoming: str, stored: str) -> str:
    """Keep a portable path when the UI returned its resolved absolute form."""

    normalized_incoming = incoming.replace("\\", "/")
    normalized_stored = stored.replace("\\", "/")
    if normalized_incoming.casefold() == normalized_stored.casefold():
        return stored
    suffix = "/" + normalized_stored.lstrip("/")
    if normalized_incoming.casefold().endswith(suffix.casefold()):
        return stored
    return normalized_incoming


def _transform_dict(value: Any) -> dict[str, int]:
    raw = _dict(value)
    return {
        "zoom": _integer(raw.get("zoom"), 100),
        "offset_x": _integer(raw.get("offset_x"), 0),
        "offset_y": _integer(raw.get("offset_y"), 0),
    }


def _nested_get(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _nested_set(value: dict[str, Any], path: tuple[str, ...], item: Any) -> None:
    current = value
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = item


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _derived_teaser(description: str) -> str:
    return description.splitlines()[0][:255] if description else ""


def _integer(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    text = _text(value)
    return _integer(text, 0) if text else None


def _string_list(value: Any) -> list[str]:
    return [text for item in value if (text := _text(item))] if isinstance(value, list) else []


def _lua_effect_selections(value: Any) -> list[LuaEffectSelection]:
    if not isinstance(value, list):
        return []
    selections: list[LuaEffectSelection] = []
    for raw in value:
        item = _dict(raw)
        effect_id = _text(item.get("effect_id"))
        if not effect_id:
            continue
        arguments: dict[str, Any] = {
            "effect_id": effect_id,
            "effect_version": _integer(item.get("effect_version"), 1),
            "parameters": deepcopy(_dict(item.get("parameters"))),
        }
        instance_id = _text(item.get("instance_id"))
        if instance_id:
            arguments["instance_id"] = instance_id
        selections.append(LuaEffectSelection(**arguments))
    return selections


def _yield_changes(value: Any) -> list[YieldChange]:
    if not isinstance(value, list):
        return []
    result: list[YieldChange] = []
    for raw in value:
        item = _dict(raw)
        yield_type = _text(item.get("yield_type"))
        amount = _optional_int(item.get("amount"))
        if amount is not None:
            result.append(YieldChange(yield_type, amount))
    return result


def _domain_experience(value: Any) -> list[DomainExperience]:
    if not isinstance(value, list):
        return []
    result: list[DomainExperience] = []
    for raw in value:
        item = _dict(raw)
        domain_type = _text(item.get("domain_type"))
        amount = _optional_int(item.get("amount"))
        if amount is not None:
            result.append(DomainExperience(domain_type, amount))
    return result


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", value)
    if not match:
        return 0.0, 0.0, 0.0
    text = match.group(1)
    return tuple(round(int(text[index : index + 2], 16) / 255, 6) for index in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(red: float, green: float, blue: float) -> str:
    channels = [max(0, min(255, round(value * 255))) for value in (red, green, blue)]
    return "#" + "".join(f"{value:02x}" for value in channels)


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
