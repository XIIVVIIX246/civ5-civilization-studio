from __future__ import annotations

from copy import deepcopy

from civ5studio.domain import (
    ImplementationKind,
    MechanicEffect,
    RecipeScope,
    RecipeSupport,
    iter_recipes,
    recipe_by_id,
    recipes_for_scope,
    validate_project,
)


def test_trait_registry_advertises_only_verified_compiled_columns() -> None:
    recipes = recipes_for_scope(RecipeScope.TRAIT, support=RecipeSupport.COMPILED)
    columns = {recipe.storage_path.rsplit(".", 1)[-1] for recipe in recipes}
    assert columns == {
        "GreatPeopleRateModifier",
        "WorkerSpeedModifier",
        "PlotBuyCostModifier",
        "WonderProductionModifier",
        "LandTradeRouteRangeBonus",
        "TradeRouteResourceModifier",
    }
    assert "MilitaryProductionModifier" not in columns
    assert "FasterWaterMovement" not in columns
    assert "MountainNavigation" not in columns


def test_compiled_recipes_have_unique_ids_and_structured_storage() -> None:
    recipes = list(iter_recipes())
    assert len({recipe.recipe_id for recipe in recipes}) == len(recipes)
    assert all(recipe.implementation is ImplementationKind.DATABASE for recipe in recipes)
    assert all(recipe.is_compiled for recipe in recipes)
    assert all(recipe.storage_path for recipe in recipes)
    assert recipe_by_id("building.yield_changes").scope is RecipeScope.BUILDING  # type: ignore[union-attr]


def test_structured_recipe_in_free_form_effect_is_explicitly_unimplemented(
    sample_project,
) -> None:
    project = deepcopy(sample_project)
    project.trait.effects.append(
        MechanicEffect(
            description="Stored in the wrong representation.",
            implementation=ImplementationKind.DATABASE,
            recipe_id="trait.worker_speed_modifier",
            parameters={"value": 25},
        )
    )
    report = validate_project(project)
    issue = next(item for item in report.issues if item.code == "mechanic.unimplemented")
    assert "trait.database_modifiers.WorkerSpeedModifier" in issue.message
