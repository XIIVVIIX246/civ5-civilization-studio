"""Typed capability registry for mechanics the current compiler really emits.

The GUI consumes this registry instead of advertising free-form "recipes".
Every compiled recipe names the structured project field that owns its value;
``MechanicEffect`` remains the explicit escape hatch for documented-only or
unsupported ideas and is never mistaken for generated gameplay code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from .models import ImplementationKind


class RecipeScope(str, Enum):
    TRAIT = "trait"
    UNIT = "unit"
    BUILDING = "building"


class RecipeSupport(str, Enum):
    COMPILED = "compiled"
    DOCUMENTED_ONLY = "documented_only"
    UNSUPPORTED = "unsupported"


class ParameterKind(str, Enum):
    INTEGER = "integer"
    BOOLEAN = "boolean"
    REFERENCE = "reference"
    REFERENCE_LIST = "reference_list"


@dataclass(frozen=True, slots=True)
class RecipeParameter:
    name: str
    label: str
    kind: ParameterKind
    minimum: int | None = None
    maximum: int | None = None
    reference_category: str = ""
    optional: bool = False


@dataclass(frozen=True, slots=True)
class MechanicRecipe:
    recipe_id: str
    scope: RecipeScope
    label: str
    summary: str
    implementation: ImplementationKind
    support: RecipeSupport
    storage_path: str
    parameters: tuple[RecipeParameter, ...]

    @property
    def is_compiled(self) -> bool:
        return self.support is RecipeSupport.COMPILED


_PERCENT = RecipeParameter("value", "Value", ParameterKind.INTEGER, -1000, 1000)
_NONNEGATIVE = RecipeParameter("value", "Value", ParameterKind.INTEGER, 0, 100000)
_MOVES = RecipeParameter("value", "Moves", ParameterKind.INTEGER, 1, 60)
_TECH = RecipeParameter(
    "technology", "Prerequisite technology", ParameterKind.REFERENCE,
    reference_category="technologies", optional=True,
)


_RECIPES = (
    MechanicRecipe(
        "trait.great_people_rate_modifier", RecipeScope.TRAIT,
        "Great Person rate modifier", "Adjust the empire-wide Great Person rate.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "trait.database_modifiers.GreatPeopleRateModifier", (_PERCENT,),
    ),
    MechanicRecipe(
        "trait.worker_speed_modifier", RecipeScope.TRAIT,
        "Worker speed modifier", "Adjust Worker improvement construction speed.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "trait.database_modifiers.WorkerSpeedModifier", (_PERCENT,),
    ),
    MechanicRecipe(
        "trait.plot_purchase_cost_modifier", RecipeScope.TRAIT,
        "Plot purchase cost modifier", "Adjust the gold cost of purchasing plots.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "trait.database_modifiers.PlotBuyCostModifier", (_PERCENT,),
    ),
    MechanicRecipe(
        "trait.wonder_production_modifier", RecipeScope.TRAIT,
        "Wonder production modifier", "Adjust production toward Wonders.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "trait.database_modifiers.WonderProductionModifier", (_PERCENT,),
    ),
    MechanicRecipe(
        "trait.land_trade_route_range_bonus", RecipeScope.TRAIT,
        "Land trade route range bonus", "Add range to land trade routes.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "trait.database_modifiers.LandTradeRouteRangeBonus", (_PERCENT,),
    ),
    MechanicRecipe(
        "trait.trade_route_resource_modifier", RecipeScope.TRAIT,
        "Trade route resource modifier", "Adjust the verified trade-route resource modifier.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "trait.database_modifiers.TradeRouteResourceModifier", (_PERCENT,),
    ),
    MechanicRecipe(
        "unit.combat", RecipeScope.UNIT, "Combat strength",
        "Override the cloned unit's Combat value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "units[].combat", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "unit.ranged_combat", RecipeScope.UNIT, "Ranged combat strength",
        "Override the cloned unit's RangedCombat value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "units[].ranged_combat", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "unit.moves", RecipeScope.UNIT, "Movement",
        "Override the cloned unit's Moves value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "units[].moves", (_MOVES,),
    ),
    MechanicRecipe(
        "unit.cost", RecipeScope.UNIT, "Production cost",
        "Override the cloned unit's Cost value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "units[].cost", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "unit.prereq_tech", RecipeScope.UNIT, "Prerequisite technology",
        "Override the cloned unit's PrereqTech reference.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "units[].prereq_tech", (_TECH,),
    ),
    MechanicRecipe(
        "unit.free_promotions", RecipeScope.UNIT, "Free promotions",
        "Add verified Unit_FreePromotions rows.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "units[].free_promotions",
        (RecipeParameter("promotions", "Promotions", ParameterKind.REFERENCE_LIST,
                         reference_category="promotions"),),
    ),
    MechanicRecipe(
        "building.cost", RecipeScope.BUILDING, "Production cost",
        "Override the cloned building's Cost value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "buildings[].cost", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "building.gold_maintenance", RecipeScope.BUILDING, "Gold maintenance",
        "Override the cloned building's GoldMaintenance value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "buildings[].gold_maintenance", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "building.defense", RecipeScope.BUILDING, "Defense",
        "Override the cloned building's Defense value.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "buildings[].defense", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "building.extra_city_hit_points", RecipeScope.BUILDING,
        "Extra city hit points", "Override the cloned building's ExtraCityHitPoints value.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "buildings[].extra_city_hit_points", (_NONNEGATIVE,),
    ),
    MechanicRecipe(
        "building.prereq_tech", RecipeScope.BUILDING, "Prerequisite technology",
        "Override the cloned building's PrereqTech reference.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "buildings[].prereq_tech", (_TECH,),
    ),
    MechanicRecipe(
        "building.yield_changes", RecipeScope.BUILDING, "Yield changes",
        "Add or update Building_YieldChanges rows.", ImplementationKind.DATABASE,
        RecipeSupport.COMPILED, "buildings[].yield_changes",
        (
            RecipeParameter("yield_type", "Yield", ParameterKind.REFERENCE,
                            reference_category="yields"),
            RecipeParameter("amount", "Amount", ParameterKind.INTEGER, -10000, 100000),
        ),
    ),
    MechanicRecipe(
        "building.domain_free_experience", RecipeScope.BUILDING,
        "Domain free experience", "Add or update Building_DomainFreeExperiences rows.",
        ImplementationKind.DATABASE, RecipeSupport.COMPILED,
        "buildings[].domain_free_experience",
        (
            RecipeParameter("domain_type", "Domain", ParameterKind.REFERENCE,
                            reference_category="domains"),
            RecipeParameter("amount", "Experience", ParameterKind.INTEGER, 0, 1000),
        ),
    ),
)


RECIPE_REGISTRY: Mapping[str, MechanicRecipe] = MappingProxyType(
    {recipe.recipe_id: recipe for recipe in _RECIPES}
)


def recipe_by_id(recipe_id: str) -> MechanicRecipe | None:
    return RECIPE_REGISTRY.get(recipe_id)


def recipes_for_scope(
    scope: RecipeScope, *, support: RecipeSupport | None = None
) -> tuple[MechanicRecipe, ...]:
    return tuple(
        recipe
        for recipe in _RECIPES
        if recipe.scope is scope and (support is None or recipe.support is support)
    )


def recipe_by_label(scope: RecipeScope, label: str) -> MechanicRecipe | None:
    return next(
        (recipe for recipe in _RECIPES if recipe.scope is scope and recipe.label == label),
        None,
    )


def compiled_storage_paths(scope: RecipeScope) -> frozenset[str]:
    return frozenset(
        recipe.storage_path
        for recipe in recipes_for_scope(scope, support=RecipeSupport.COMPILED)
    )


def iter_recipes() -> Iterable[MechanicRecipe]:
    return iter(_RECIPES)
