from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from itertools import combinations

from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain import (
    CURRENT_SCHEMA_VERSION,
    LUA_EFFECT_CATALOG,
    LUA_EFFECT_LIMIT,
    LuaEffectOrigin,
    LuaEffectSelection,
    catalog_primitive_ids,
    catalog_promotions,
    iter_lua_effects,
    lua_effect_by_id,
    lua_effect_categories,
    lua_effects_compatible,
    migrate_document,
    project_from_dict,
    project_to_dict,
    search_lua_effects,
    validate_project,
)


def _selection(effect_id: str, *, amount: object | None = None) -> LuaEffectSelection:
    definition = lua_effect_by_id(effect_id)
    assert definition is not None
    parameters = {} if amount is None else {"amount": amount}
    return LuaEffectSelection(
        effect_id=effect_id,
        effect_version=definition.version,
        parameters=parameters,
    )


def test_catalog_contains_exactly_two_hundred_curated_versioned_effects():
    assert len(LUA_EFFECT_CATALOG) == 200
    assert len({item.effect_id for item in LUA_EFFECT_CATALOG}) == 200
    assert len({item.label.casefold() for item in LUA_EFFECT_CATALOG}) == 200
    assert all(item.effect_id.startswith("civ5studio.lua.v1.") for item in LUA_EFFECT_CATALOG)
    assert all(item.version == 1 and item.pure_bnw for item in LUA_EFFECT_CATALOG)
    assert all(item.description and item.trigger and item.runtime_config for item in LUA_EFFECT_CATALOG)
    assert len(tuple(iter_lua_effects(origin=LuaEffectOrigin.ARCHIVE_INSPIRED))) == 100
    assert len(tuple(iter_lua_effects(origin=LuaEffectOrigin.STUDIO_ORIGINAL))) == 100
    assert Counter(item.category for item in LUA_EFFECT_CATALOG) == {
        category: 10 for category in lua_effect_categories()
    }
    assert len(lua_effect_categories()) == 20


def test_catalog_uses_only_declared_primitives_and_verified_bnw_promotions():
    assert catalog_primitive_ids() == (
        "player_turn_reward",
        "city_founded_reward",
        "city_captured_reward",
        "unit_trained_reward",
        "building_completed_reward",
        "improvement_completed_reward",
        "policy_adopted_reward",
        "tech_researched_reward",
        "great_person_expended_reward",
        "unit_kill_reward",
        "unit_promotion_on_train",
        "golden_age_started_reward",
        "city_growth_reward",
        "city_connection_reward",
        "war_state_reward",
        "unit_heal_turn",
    )
    catalog = ReferenceCatalog.bundled()
    assert set(catalog_promotions()) == {
        "PROMOTION_ACCURACY_1",
        "PROMOTION_AIR_SIEGE_1",
        "PROMOTION_AMPHIBIOUS",
        "PROMOTION_BARRAGE_1",
        "PROMOTION_CHARGE",
        "PROMOTION_COVER_1",
        "PROMOTION_DOGFIGHTING_1",
        "PROMOTION_MARCH",
        "PROMOTION_SCOUTING_1",
        "PROMOTION_TARGETING_1",
    }
    assert all(catalog.contains("promotions", item) for item in catalog_promotions())
    # The bundled catalog once carried PROMOTION_COMMANDO even though the live
    # Expansion2 XML/debug DB did not. Keep the catalog on the verified stock
    # March row instead of regressing to that false positive.
    assert "PROMOTION_COMMANDO" not in catalog_promotions()
    assert "PROMOTION_MARCH" in catalog_promotions()


def test_catalog_search_categories_and_compatibility_are_stable():
    categories = lua_effect_categories()
    assert categories[0] == "Economy & State"
    assert "Training Doctrines" in categories
    assert {item.label for item in search_lua_effects("river charter")} >= {
        "River Market Charter"
    }
    assert all(
        item.category == "Population"
        for item in search_lua_effects("growth", category="Population")
    )

    river = lua_effect_by_id("civ5studio.lua.v1.river_granary_grant")
    coast = lua_effect_by_id("civ5studio.lua.v1.coastal_trade_chest")
    assert river is not None and coast is not None
    assert lua_effects_compatible(river, coast)
    assert not lua_effects_compatible(river, river)
    assert not lua_effects_compatible("not.real", coast)

    recurring_a = lua_effect_by_id("civ5studio.lua.v1.war_bond_levy")
    recurring_b = lua_effect_by_id("civ5studio.lua.v1.lean_empire_ledger")
    assert recurring_a is not None and recurring_b is not None
    assert lua_effects_compatible(recurring_a, recurring_b)

    tagged = replace(recurring_a, tags=frozenset({"future-conflict"}))
    blocked = replace(
        recurring_b, incompatible_tags=frozenset({"future-conflict"})
    )
    assert not lua_effects_compatible(tagged, blocked)


def test_every_distinct_v1_catalog_pair_is_selectable():
    assert all(
        lua_effects_compatible(first, second)
        for first, second in combinations(LUA_EFFECT_CATALOG, 2)
    )


def test_lua_effect_selections_round_trip_and_schema_four_migrates(sample_project):
    project = deepcopy(sample_project)
    project.lua_effects = [
        _selection("civ5studio.lua.v1.river_granary_grant", amount=35),
        _selection("civ5studio.lua.v1.victory_coffers"),
    ]
    document = project_to_dict(project)
    assert project_from_dict(document) == project

    legacy = project_to_dict(sample_project)
    legacy["schema_version"] = 4
    legacy.pop("lua_effects")
    migrated = migrate_document(legacy)
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION == 5
    assert migrated["lua_effects"] == []


def test_valid_lua_effects_warn_about_derived_modinfo_capabilities(sample_project):
    project = deepcopy(sample_project)
    project.lua_effects = [_selection("civ5studio.lua.v1.river_granary_grant")]
    report = validate_project(project)
    assert report.is_valid
    assert report.has_code("lua-effects.saved-games-derived")
    assert report.has_code("lua-effects.multiplayer-derived")
    assert report.has_code("lua-effects.hotseat-derived")


def test_v1_curated_amount_is_typed_but_fixed(sample_project):
    project = deepcopy(sample_project)
    effect_id = "civ5studio.lua.v1.river_granary_grant"
    project.lua_effects = [_selection(effect_id, amount=35)]
    assert validate_project(project).is_valid

    project.lua_effects[0].parameters["amount"] = 36
    report = validate_project(project)
    assert any(item.code == "lua-effect.parameter" for item in report.errors)


def test_lua_effect_validation_rejects_limit_unknown_version_and_parameters(sample_project):
    project = deepcopy(sample_project)
    first = _selection("civ5studio.lua.v1.river_granary_grant", amount="many")
    first.effect_version = 99
    unknown = LuaEffectSelection(effect_id="civ5studio.lua.v1.not_real")
    third = _selection("civ5studio.lua.v1.victory_coffers")
    project.lua_effects = [first, unknown, third]
    report = validate_project(project)
    codes = {item.code for item in report.errors}
    assert len(project.lua_effects) == LUA_EFFECT_LIMIT + 1
    assert "lua-effect.limit" in codes
    assert "lua-effect.unknown" in codes
    assert "lua-effect.version" in codes
    assert "lua-effect.parameter" in codes


def test_lua_effect_validation_rejects_duplicate_and_incompatible_slots(
    sample_project, monkeypatch
):
    project = deepcopy(sample_project)
    duplicate = _selection("civ5studio.lua.v1.war_bond_levy")
    project.lua_effects = [duplicate, deepcopy(duplicate)]
    duplicate_report = validate_project(project)
    assert duplicate_report.has_code("lua-effect.duplicate")
    assert duplicate_report.has_code("lua-effect.instance-duplicate")

    import civ5studio.domain.validation as validation_module

    first = lua_effect_by_id("civ5studio.lua.v1.war_bond_levy")
    second = lua_effect_by_id("civ5studio.lua.v1.lean_empire_ledger")
    assert first is not None and second is not None
    first = replace(first, tags=frozenset({"test-conflict"}))
    second = replace(second, incompatible_tags=frozenset({"test-conflict"}))
    definitions = {first.effect_id: first, second.effect_id: second}
    monkeypatch.setattr(
        validation_module,
        "lua_effect_by_id",
        lambda effect_id: definitions.get(effect_id),
    )
    project.lua_effects = [
        _selection(first.effect_id),
        _selection(second.effect_id),
    ]
    incompatible_report = validate_project(project)
    assert any(
        item.code == "lua-effect.incompatible" for item in incompatible_report.errors
    )
