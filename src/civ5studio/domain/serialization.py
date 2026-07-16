"""JSON serialization and migrations for portable ``.civ5project.json`` files."""

from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from enum import Enum
import copy
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .ids import type_component
from .models import (
    CURRENT_SCHEMA_VERSION,
    PROJECT_FORMAT,
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
)


class ProjectFormatError(ValueError):
    """Raised when a project document cannot be migrated safely."""


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _primitive(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    return value


def project_to_dict(project: CivProject) -> dict[str, Any]:
    """Convert a project to its canonical, JSON-safe representation."""

    result = _primitive(project)
    result["project_format"] = PROJECT_FORMAT
    result["schema_version"] = CURRENT_SCHEMA_VERSION
    return result


def dumps_project(project: CivProject) -> str:
    return json.dumps(project_to_dict(project), indent=2, ensure_ascii=False) + "\n"


def save_project(path: str | Path, project: CivProject) -> Path:
    """Atomically save a project document without leaving a partial JSON file."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = dumps_project(project)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def load_project(path: str | Path) -> CivProject:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectFormatError(f"Could not read project JSON {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise ProjectFormatError("Project root must be a JSON object.")
    return project_from_dict(document)


def migrate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a current-schema copy of a legacy or current project document."""

    data = copy.deepcopy(dict(document))
    if "schema_version" not in data:
        data = _migrate_legacy_v0(data)
    version = data.get("schema_version")
    if not isinstance(version, int):
        raise ProjectFormatError("schema_version must be an integer.")
    if version > CURRENT_SCHEMA_VERSION:
        raise ProjectFormatError(
            f"Project schema {version} is newer than supported schema "
            f"{CURRENT_SCHEMA_VERSION}."
        )
    while version < CURRENT_SCHEMA_VERSION:
        if version == 1:
            data = _migrate_v1_to_v2(data)
        elif version == 2:
            data = _migrate_v2_to_v3(data)
        elif version == 3:
            data = _migrate_v3_to_v4(data)
        elif version == 4:
            data = _migrate_v4_to_v5(data)
        else:
            raise ProjectFormatError(f"No migration is available for schema {version}.")
        version = data["schema_version"]
    if data.get("project_format") != PROJECT_FORMAT:
        raise ProjectFormatError(
            f"Unsupported project_format {data.get('project_format')!r}; "
            f"expected {PROJECT_FORMAT!r}."
        )
    return data


def project_from_dict(document: Mapping[str, Any]) -> CivProject:
    data = migrate_document(document)

    civilization = _construct(
        CivilizationSpec, data.get("civilization", {}), path="$.civilization"
    )
    leader = _construct(LeaderSpec, data.get("leader", {}), path="$.leader")

    trait_data = dict(data.get("trait", {}))
    trait_data["effects"] = [
        _effect(item, path=f"$.trait.effects[{index}]")
        for index, item in enumerate(trait_data.get("effects", []))
    ]
    trait = _construct(TraitSpec, trait_data, path="$.trait")

    units: list[UniqueUnitSpec] = []
    for index, raw in enumerate(data.get("units", [])):
        item = dict(raw)
        item["effects"] = [
            _effect(effect, path=f"$.units[{index}].effects[{effect_index}]")
            for effect_index, effect in enumerate(item.get("effects", []))
        ]
        units.append(_construct(UniqueUnitSpec, item, path=f"$.units[{index}]"))

    buildings: list[UniqueBuildingSpec] = []
    for index, raw in enumerate(data.get("buildings", [])):
        item = dict(raw)
        item["yield_changes"] = [
            _construct(
                YieldChange,
                value,
                path=f"$.buildings[{index}].yield_changes[{value_index}]",
            )
            for value_index, value in enumerate(item.get("yield_changes", []))
        ]
        item["domain_free_experience"] = [
            _construct(
                DomainExperience,
                value,
                path=(
                    f"$.buildings[{index}].domain_free_experience["
                    f"{value_index}]"
                ),
            )
            for value_index, value in enumerate(
                item.get("domain_free_experience", [])
            )
        ]
        item["effects"] = [
            _effect(
                effect,
                path=f"$.buildings[{index}].effects[{effect_index}]",
            )
            for effect_index, effect in enumerate(item.get("effects", []))
        ]
        buildings.append(
            _construct(UniqueBuildingSpec, item, path=f"$.buildings[{index}]")
        )

    improvements: list[UniqueImprovementSpec] = []
    for index, raw in enumerate(data.get("improvements", [])):
        item = dict(raw)
        item["yield_changes"] = [
            _construct(
                YieldChange,
                value,
                path=f"$.improvements[{index}].yield_changes[{value_index}]",
            )
            for value_index, value in enumerate(item.get("yield_changes", []))
        ]
        improvements.append(
            _construct(UniqueImprovementSpec, item, path=f"$.improvements[{index}]")
        )

    art_data = dict(data.get("art", {}))
    assets = []
    for index, raw in enumerate(art_data.get("assets", [])):
        item = dict(raw)
        try:
            item["role"] = ArtRole(item.get("role", ArtRole.CIVILIZATION_ICON.value))
        except ValueError as exc:
            raise ProjectFormatError(f"Unknown art role: {item.get('role')!r}") from exc
        assets.append(
            _construct(ArtAssetSpec, item, path=f"$.art.assets[{index}]")
        )
    art_data["assets"] = assets

    top_level = dict(data)
    lua_effects = [
        _construct(
            LuaEffectSelection,
            raw,
            path=f"$.lua_effects[{index}]",
        )
        for index, raw in enumerate(data.get("lua_effects", []))
    ]
    top_level.update(
        civilization=civilization,
        leader=leader,
        trait=trait,
        units=units,
        buildings=buildings,
        improvements=improvements,
        colors=_construct(PlayerColors, data.get("colors", {}), path="$.colors"),
        art=_construct(ArtManifestSpec, art_data, path="$.art"),
        options=_construct(ProjectOptions, data.get("options", {}), path="$.options"),
        dependencies=_construct(
            ProjectDependencies,
            data.get("dependencies", {}),
            path="$.dependencies",
        ),
        lua_effects=lua_effects,
    )
    return _construct(CivProject, top_level, path="$")


def _construct(
    cls: type[Any], raw: Mapping[str, Any] | Any, *, path: str
) -> Any:
    if not isinstance(raw, Mapping):
        raise ProjectFormatError(
            f"{cls.__name__} at {path} must be a JSON object."
        )
    allowed = {item.name for item in fields(cls)}
    unknown = sorted(str(key) for key in raw if key not in allowed)
    if unknown:
        locations = ", ".join(f"{path}.{key}" for key in unknown)
        raise ProjectFormatError(
            f"Unknown field(s) for {cls.__name__} at {path}: {locations}."
        )
    return cls(**dict(raw))


def _effect(raw: Mapping[str, Any], *, path: str) -> MechanicEffect:
    item = dict(raw)
    try:
        item["implementation"] = ImplementationKind(
            item.get("implementation", ImplementationKind.UNSUPPORTED.value)
        )
    except ValueError as exc:
        raise ProjectFormatError(
            f"Unknown mechanic implementation: {item.get('implementation')!r}"
        ) from exc
    return _construct(MechanicEffect, item, path=path)


def _migrate_legacy_v0(data: dict[str, Any]) -> dict[str, Any]:
    """Migrate the v10 builder's unversioned ``ModSpec`` JSON shape."""

    civilization = dict(data.get("civilization", {}))
    civilization = {
        "name": civilization.get("name", civilization.get("display_name", "")),
        "short_name": civilization.get(
            "short_name", civilization.get("short_description", "")
        ),
        "adjective": civilization.get("adjective", ""),
        "civilopedia": civilization.get("civilopedia", ""),
        "dawn_of_man_quote": civilization.get("dawn_of_man_quote", ""),
        "base_civilization": civilization.get(
            "base_civilization",
            civilization.get("base_civ_to_clone", "CIVILIZATION_POLAND"),
        ),
        "copy_free_buildings_from": civilization.get(
            "copy_free_buildings_from",
            civilization.get("free_buildings_from_civ", "CIVILIZATION_POLAND"),
        ),
        "copy_free_techs_and_units_from": civilization.get(
            "copy_free_techs_and_units_from",
            civilization.get("free_techs_from_civ", "CIVILIZATION_ZULU"),
        ),
        "start_region_avoid": civilization.get(
            "start_region_avoid", civilization.get("region_avoid", "")
        ),
        "city_names": civilization.get("city_names", data.get("city_names", [])),
        "spy_names": civilization.get("spy_names", data.get("spy_names", [])),
    }

    leader = dict(data.get("leader", {}))
    leader["name"] = leader.get("name", leader.pop("display_name", ""))
    leader["key"] = leader.get("key") or type_component(leader["name"]) or "LEADER"
    leader.pop("art_define_tag", None)
    leader.pop("portrait_index", None)

    trait = dict(data.get("trait", {}))
    trait["name"] = trait.get("name", trait.pop("display_name", ""))
    trait["key"] = trait.get("key") or type_component(trait["name"]) or "TRAIT"
    modifiers: dict[str, int | bool] = dict(trait.get("database_modifiers", {}))
    legacy_trait_fields = {
        "level_experience_modifier": "LevelExperienceModifier",
        "great_people_rate_modifier": "GreatPeopleRateModifier",
        "worker_speed_modifier": "WorkerSpeedModifier",
        "military_production_modifier": "MilitaryProductionModifier",
        "plot_buy_cost_modifier": "PlotBuyCostModifier",
        "faster_water_movement": "FasterWaterMovement",
        "mountain_navigation": "MountainNavigation",
    }
    for old, new in legacy_trait_fields.items():
        value = trait.pop(old, None)
        if value not in (None, 0, False, ""):
            modifiers[new] = value
    trait["database_modifiers"] = modifiers
    effects = list(trait.get("effects", []))
    lua_effects = trait.pop("lua_effects", "")
    if lua_effects:
        effects.append(
            {
                "description": lua_effects,
                "implementation": ImplementationKind.UNSUPPORTED.value,
                "notes": "Migrated from the legacy free-form lua_effects field.",
            }
        )
    trait["effects"] = effects

    units = []
    for raw in data.get("units", []):
        item = dict(raw)
        item["name"] = item.get("name", item.pop("display_name", ""))
        item["key"] = item.get("key") or type_component(item["name"]) or "UNIT"
        item["base_unit"] = item.get("base_unit", item.pop("base_unit_to_clone", ""))
        for old in ("type_name", "art_def_type", "art_member_type", "unit_art_info", "unit_flag_atlas", "portrait_index"):
            item.pop(old, None)
        for key in ("combat", "moves", "cost"):
            if item.get(key) == 0:
                item[key] = None
        if item.get("ranged_combat") == -1:
            item["ranged_combat"] = None
        if item.get("prereq_tech") == "":
            item["prereq_tech"] = None
        units.append(item)

    buildings = []
    for raw in data.get("buildings", []):
        item = dict(raw)
        item["name"] = item.get("name", item.pop("display_name", ""))
        item["key"] = item.get("key") or type_component(item["name"]) or "BUILDING"
        item["base_building"] = item.get(
            "base_building", item.pop("base_building_to_clone", "")
        )
        item.pop("type_name", None)
        item.pop("portrait_index", None)
        item["yield_changes"] = [
            {"yield_type": value[0], "amount": value[1]}
            if isinstance(value, (list, tuple))
            else value
            for value in item.get("yield_changes", [])
        ]
        legacy_xp = item.pop("domain_free_experiences", [])
        item["domain_free_experience"] = [
            {"domain_type": value[0], "amount": value[1]}
            if isinstance(value, (list, tuple))
            else value
            for value in legacy_xp
        ]
        for key in ("cost", "defense", "extra_city_hp"):
            if item.get(key) == 0:
                item[key] = None
        if "extra_city_hp" in item:
            item["extra_city_hit_points"] = item.pop("extra_city_hp")
        if item.get("gold_maintenance") == -1:
            item["gold_maintenance"] = None
        if item.get("prereq_tech") == "":
            item["prereq_tech"] = None
        buildings.append(item)

    colors = dict(data.get("colors", data.get("player_colors", {})))
    color_names = {
        "primary_r": "primary_red",
        "primary_g": "primary_green",
        "primary_b": "primary_blue",
        "primary_a": "primary_alpha",
        "secondary_r": "secondary_red",
        "secondary_g": "secondary_green",
        "secondary_b": "secondary_blue",
        "secondary_a": "secondary_alpha",
    }
    colors = {color_names.get(key, key): value for key, value in colors.items()}

    art = _legacy_art_manifest(dict(data.get("art", {})), units, buildings)
    legacy_options = dict(data.get("options", {}))
    options = {
        "affects_saved_games": bool(legacy_options.get("affects_saved_games", False)),
        "supports_multiplayer": bool(legacy_options.get("supports_multiplayer", True)),
        "supports_hotseat": bool(legacy_options.get("supports_hotseat", True)),
        "supports_mac": bool(legacy_options.get("supports_mac", True)),
    }
    known_top_level = {
        "mod_name", "mod_guid", "mod_id", "version", "mod_version", "authors",
        "teaser", "mod_description", "description", "internal_prefix",
        "civilization", "leader", "trait", "units", "buildings", "city_names",
        "spy_names", "colors", "player_colors", "art", "options", "extensions",
    }
    extensions = dict(data.get("extensions", {}))
    unknown = {key: value for key, value in data.items() if key not in known_top_level}
    if unknown:
        extensions["legacy_unknown"] = unknown

    try:
        mod_version = int(data.get("mod_version", data.get("version", 1)))
    except (TypeError, ValueError):
        mod_version = 1
    return {
        "project_format": PROJECT_FORMAT,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "project_id": data.get("project_id") or str(__import__("uuid").uuid4()),
        "mod_id": data.get("mod_id") or data.get("mod_guid") or str(__import__("uuid").uuid4()),
        "mod_name": data.get("mod_name", ""),
        "mod_version": mod_version,
        "authors": data.get("authors", ""),
        "teaser": data.get("teaser", ""),
        "description": data.get("description", data.get("mod_description", "")),
        "internal_prefix": data.get("internal_prefix", ""),
        "civilization": civilization,
        "leader": leader,
        "trait": trait,
        "units": units,
        "buildings": buildings,
        "improvements": [],
        "lua_effects": [],
        "colors": colors,
        "art": art,
        "options": options,
        "extensions": extensions,
    }


def _legacy_art_manifest(
    legacy: dict[str, Any], units: list[dict[str, Any]], buildings: list[dict[str, Any]]
) -> dict[str, Any]:
    aliases = [
        (ArtRole.CIVILIZATION_ICON, "civilization", ("civilization_icon_path", "civ_icon_path")),
        (ArtRole.CIVILIZATION_ALPHA, "civilization", ("civilization_alpha_path", "civ_alpha_path")),
        (ArtRole.LEADER_PORTRAIT, "leader", ("leader_portrait_path",)),
        (ArtRole.LEADER_SCENE, "leader", ("leader_scene_path",)),
        (ArtRole.DAWN_OF_MAN, "civilization", ("dawn_of_man_path", "dom_image_path")),
        (ArtRole.MAP_IMAGE, "civilization", ("map_image_path",)),
    ]
    assets = []
    for role, subject, keys in aliases:
        source = next((legacy.get(key) for key in keys if legacy.get(key)), "")
        if source:
            assets.append(
                {
                    "asset_id": role.value,
                    "role": role.value,
                    "source_png": source,
                    "subject_key": subject,
                    "required": True,
                }
            )
    if units:
        unit_key = units[0]["key"]
        for role, aliases_for_role in (
            (ArtRole.UNIQUE_UNIT_ICON, ("unique_unit_icon_path", "unit_icon_path")),
            (ArtRole.UNIT_FLAG, ("unit_flag_path",)),
        ):
            source = next(
                (legacy.get(key) for key in aliases_for_role if legacy.get(key)), ""
            )
            if source:
                assets.append(
                    {
                        "asset_id": f"{role.value}_{unit_key.lower()}",
                        "role": role.value,
                        "source_png": source,
                        "subject_key": f"unit:{unit_key}",
                        "required": True,
                    }
                )
    if buildings:
        building_key = buildings[0]["key"]
        source = legacy.get("unique_building_icon_path") or legacy.get("building_icon_path")
        if source:
            assets.append(
                {
                    "asset_id": f"unique_building_icon_{building_key.lower()}",
                    "role": ArtRole.UNIQUE_BUILDING_ICON.value,
                    "source_png": source,
                    "subject_key": f"building:{building_key}",
                    "required": True,
                }
            )
    return {
        "contract_version": "smp-civ5-v1",
        "allow_placeholders": True,
        "assets": assets,
    }


def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)
    result["schema_version"] = 2
    if "mod_version" not in result:
        try:
            result["mod_version"] = int(result.pop("version", 1))
        except (TypeError, ValueError):
            result["mod_version"] = 1
    result.setdefault("extensions", {})
    result.setdefault("art", {"contract_version": "smp-civ5-v1", "assets": []})
    result.setdefault("options", {"affects_saved_games": False})
    return result


def _migrate_v2_to_v3(data: dict[str, Any]) -> dict[str, Any]:
    """Add explicit optional-mod dependency and per-unit PEP promotion slots."""

    result = copy.deepcopy(data)
    result["schema_version"] = 3
    result.setdefault("dependencies", {"promotions_expansion_pack": False})
    units = result.get("units", [])
    if isinstance(units, list):
        for raw in units:
            if isinstance(raw, dict):
                raw.setdefault("promotions_expansion_pack", [])
    return result


def _migrate_v3_to_v4(data: dict[str, Any]) -> dict[str, Any]:
    """Add typed civilization-specific improvements without changing old content."""

    result = copy.deepcopy(data)
    result["schema_version"] = 4
    result.setdefault("improvements", [])
    return result


def _migrate_v4_to_v5(data: dict[str, Any]) -> dict[str, Any]:
    """Add the version-pinned civilization-level Lua effect selections."""

    result = copy.deepcopy(data)
    result["schema_version"] = 5
    result.setdefault("lua_effects", [])
    return result
