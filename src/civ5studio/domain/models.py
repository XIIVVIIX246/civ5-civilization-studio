"""Portable domain model for a complete Civ V BNW civilization project."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import uuid

from .ids import GeneratedIds, generated_ids


PROJECT_FORMAT = "civ5studio.project"
CURRENT_SCHEMA_VERSION = 5


class ImplementationKind(str, Enum):
    DATABASE = "database"
    LUA_RECIPE = "lua_recipe"
    UNSUPPORTED = "unsupported"


class ArtRole(str, Enum):
    CIVILIZATION_ICON = "civilization_icon"
    CIVILIZATION_ALPHA = "civilization_alpha"
    LEADER_PORTRAIT = "leader_portrait"
    LEADER_SCENE = "leader_scene"
    DAWN_OF_MAN = "dawn_of_man"
    MAP_IMAGE = "map_image"
    UNIQUE_UNIT_ICON = "unique_unit_icon"
    UNIQUE_BUILDING_ICON = "unique_building_icon"
    UNIQUE_IMPROVEMENT_ICON = "unique_improvement_icon"
    UNIT_FLAG = "unit_flag"
    STRATEGIC_VIEW = "strategic_view"


@dataclass(slots=True)
class MechanicEffect:
    description: str = ""
    implementation: ImplementationKind = ImplementationKind.UNSUPPORTED
    recipe_id: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(slots=True)
class CivilizationSpec:
    name: str = ""
    short_name: str = ""
    adjective: str = ""
    civilopedia: str = ""
    dawn_of_man_quote: str = ""
    base_civilization: str = "CIVILIZATION_POLAND"
    copy_free_buildings_from: str = "CIVILIZATION_POLAND"
    copy_free_techs_and_units_from: str = "CIVILIZATION_ZULU"
    start_region_avoid: str = ""
    city_names: list[str] = field(default_factory=list)
    spy_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LeaderSpec:
    key: str = "LEADER"
    name: str = ""
    civilopedia: str = ""
    victory_competitiveness: int = 5
    wonder_competitiveness: int = 5
    minor_civ_competitiveness: int = 5
    boldness: int = 5
    diplo_balance: int = 5
    warmonger_hate: int = 5
    denounce_willingness: int = 5
    dof_willingness: int = 5
    loyalty: int = 5
    neediness: int = 5
    forgiveness: int = 5
    chattiness: int = 5
    meanness: int = 5
    flavors: dict[str, int] = field(default_factory=dict)
    major_civ_approach_biases: dict[str, int] = field(default_factory=dict)
    minor_civ_approach_biases: dict[str, int] = field(default_factory=dict)
    diplomacy_text: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TraitSpec:
    key: str = "TRAIT"
    name: str = ""
    short_description: str = ""
    long_description: str = ""
    database_modifiers: dict[str, int | bool] = field(default_factory=dict)
    effects: list[MechanicEffect] = field(default_factory=list)


@dataclass(slots=True)
class UniqueUnitSpec:
    key: str = "UNIT"
    name: str = ""
    help_text: str = ""
    strategy_text: str = ""
    replaces_unit_class: str = "UNITCLASS_WARRIOR"
    base_unit: str = ""
    combat: int | None = None
    ranged_combat: int | None = None
    moves: int | None = None
    cost: int | None = None
    prereq_tech: str | None = None
    free_promotions: list[str] = field(default_factory=list)
    promotions_expansion_pack: list[str] = field(default_factory=list)
    effects: list[MechanicEffect] = field(default_factory=list)


@dataclass(slots=True)
class YieldChange:
    yield_type: str = "YIELD_PRODUCTION"
    amount: int = 0


@dataclass(slots=True)
class DomainExperience:
    domain_type: str = "DOMAIN_LAND"
    amount: int = 0


@dataclass(slots=True)
class UniqueBuildingSpec:
    key: str = "BUILDING"
    name: str = ""
    help_text: str = ""
    strategy_text: str = ""
    replaces_building_class: str = "BUILDINGCLASS_MONUMENT"
    base_building: str = ""
    cost: int | None = None
    gold_maintenance: int | None = None
    defense: int | None = None
    extra_city_hit_points: int | None = None
    prereq_tech: str | None = None
    yield_changes: list[YieldChange] = field(default_factory=list)
    domain_free_experience: list[DomainExperience] = field(default_factory=list)
    effects: list[MechanicEffect] = field(default_factory=list)


@dataclass(slots=True)
class UniqueImprovementSpec:
    """Civilization-specific improvement cloned from a verified BNW donor."""

    key: str = "IMPROVEMENT"
    name: str = ""
    help_text: str = ""
    strategy_text: str = ""
    civilopedia_text: str = ""
    base_improvement: str = "IMPROVEMENT_FARM"
    build_prereq_tech: str | None = None
    yield_changes: list[YieldChange] = field(default_factory=list)


@dataclass(slots=True)
class PlayerColors:
    primary_red: float = 0.70
    primary_green: float = 0.13
    primary_blue: float = 0.13
    primary_alpha: float = 1.0
    secondary_red: float = 1.0
    secondary_green: float = 0.84
    secondary_blue: float = 0.0
    secondary_alpha: float = 1.0


@dataclass(slots=True)
class ArtAssetSpec:
    asset_id: str = ""
    role: ArtRole = ArtRole.CIVILIZATION_ICON
    source_png: str = ""
    subject_key: str = "civilization"
    required: bool = True
    crop_mode: str = "cover"
    focal_x: float = 0.5
    focal_y: float = 0.5


@dataclass(slots=True)
class ArtManifestSpec:
    contract_version: str = "smp-civ5-v1"
    allow_placeholders: bool = False
    assets: list[ArtAssetSpec] = field(default_factory=list)


@dataclass(slots=True)
class ProjectOptions:
    affects_saved_games: bool = False
    supports_multiplayer: bool = True
    supports_hotseat: bool = True
    supports_mac: bool = True


@dataclass(slots=True)
class ProjectDependencies:
    """Optional external mods required by generated project content."""

    promotions_expansion_pack: bool = False


@dataclass(slots=True)
class LuaEffectSelection:
    """A version-pinned selection from the compiler-owned Lua effect catalog."""

    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    effect_id: str = ""
    effect_version: int = 1
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CivProject:
    project_format: str = PROJECT_FORMAT
    schema_version: int = CURRENT_SCHEMA_VERSION
    project_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mod_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mod_name: str = ""
    mod_version: int = 1
    authors: str = ""
    teaser: str = ""
    description: str = ""
    internal_prefix: str = ""
    civilization: CivilizationSpec = field(default_factory=CivilizationSpec)
    leader: LeaderSpec = field(default_factory=LeaderSpec)
    trait: TraitSpec = field(default_factory=TraitSpec)
    units: list[UniqueUnitSpec] = field(default_factory=list)
    buildings: list[UniqueBuildingSpec] = field(default_factory=list)
    improvements: list[UniqueImprovementSpec] = field(default_factory=list)
    colors: PlayerColors = field(default_factory=PlayerColors)
    art: ArtManifestSpec = field(default_factory=ArtManifestSpec)
    options: ProjectOptions = field(default_factory=ProjectOptions)
    dependencies: ProjectDependencies = field(default_factory=ProjectDependencies)
    lua_effects: list[LuaEffectSelection] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)

    def ids(self) -> GeneratedIds:
        return generated_ids(self)
