from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from luaparser import ast as lua_ast

from civ5studio.domain import LuaEffectSelection
from civ5studio.domain.lua_effects import (
    catalog_conditions,
    iter_lua_effects,
    lua_effects_compatible,
)
from civ5studio.generation import (
    compile_project,
    generate_lua_runtime,
    lua_effect_manifest,
    registered_lua_hooks,
)
import civ5studio.generation.lua_runtime as lua_runtime


def _selection(definition: object, index: int = 1) -> LuaEffectSelection:
    return LuaEffectSelection(
        instance_id=f"00000000-0000-4000-8000-{index:012d}",
        effect_id=definition.effect_id,
        effect_version=definition.version,
    )


def _definition(primitive_id: str) -> object:
    return next(
        item for item in iter_lua_effects() if item.primitive_id == primitive_id
    )


def test_empty_selection_still_emits_stable_not_applicable_manifest(
    sample_project,
) -> None:
    compilation = compile_project(sample_project)
    payload = json.loads(
        compilation.files["Documentation/LUA_EFFECT_MANIFEST.json"]
    )
    assert payload["selected_count"] == 0
    assert payload["effects"] == []
    assert payload["compatibility"]["status"] == "NOT_APPLICABLE"
    assert payload["runtime"]["registered_game_events"] == []
    assert payload["runtime_gate"] == "NOT_APPLICABLE"
    assert "**NOT_APPLICABLE**" in compilation.files[
        "Documentation/LUA_EFFECT_MANIFEST.md"
    ]


def test_every_catalog_effect_has_a_complete_runtime_and_manifest(sample_project) -> None:
    definitions = list(iter_lua_effects())
    assert len(definitions) == 200
    for definition in definitions:
        project = deepcopy(sample_project)
        project.lua_effects = [_selection(definition)]
        runtime = generate_lua_runtime(project)
        manifest = lua_effect_manifest(project)
        effect = manifest["effects"][0]
        assert effect["effect_id"] == definition.effect_id
        assert effect["primitive_id"] == definition.primitive_id
        assert effect["runtime_config"] == dict(definition.runtime_config)
        assert effect["status"] == "COMPILED"
        assert effect["runtime_gate"] == "REQUIRED_NOT_RUN"
        assert definition.primitive_id in runtime
        assert manifest["runtime"]["registered_game_events"] == list(
            registered_lua_hooks(project)
        )
        assert len(registered_lua_hooks(project)) == 1


def test_generated_runtime_shell_and_pair_parse_as_lua(sample_project) -> None:
    empty = deepcopy(sample_project)
    lua_ast.parse(generate_lua_runtime(empty))

    definitions = list(iter_lua_effects())
    pair = deepcopy(sample_project)
    pair.lua_effects = [
        _selection(definitions[0], 1),
        _selection(
            next(
                item
                for item in definitions
                if item.primitive_id == "unit_promotion_on_train"
            ),
            2,
        ),
    ]
    lua_ast.parse(generate_lua_runtime(pair))


def test_runtime_template_covers_every_catalog_condition(sample_project) -> None:
    project = deepcopy(sample_project)
    definition = next(iter_lua_effects())
    project.lua_effects = [_selection(definition)]
    runtime = generate_lua_runtime(project)
    missing = [
        condition
        for condition in catalog_conditions()
        if f'"{condition}"' not in runtime and f"{condition} =" not in runtime
    ]
    assert missing == []


def test_compatible_effects_share_one_game_event_dispatcher(sample_project) -> None:
    definitions = [
        item for item in iter_lua_effects() if item.primitive_id == "city_founded_reward"
    ]
    first, second = definitions[:2]
    assert lua_effects_compatible(first, second)
    project = deepcopy(sample_project)
    project.lua_effects = [_selection(first, 1), _selection(second, 2)]
    compilation = compile_project(project)
    runtime = compilation.files["Lua/CivilizationRuntime.lua"]
    assert runtime.count("GameEvents.PlayerCityFounded.Add(") == 1
    assert runtime.count(".Add(") == 1
    assert first.effect_id in runtime
    assert second.effect_id in runtime
    manifest = json.loads(
        compilation.files["Documentation/LUA_EFFECT_MANIFEST.json"]
    )
    assert manifest["compatibility"] == {
        "status": "PASS",
        "selected_effect_ids": [first.effect_id, second.effect_id],
        "reason": "The two distinct selections passed the catalog tag-conflict rules.",
    }


def test_two_effect_compilation_is_deterministic_guarded_and_truthful(
    sample_project,
) -> None:
    project = deepcopy(sample_project)
    founded = _definition("city_founded_reward")
    trained = _definition("unit_trained_reward")
    project.lua_effects = [_selection(founded, 1), _selection(trained, 2)]

    first = compile_project(project)
    second = compile_project(project)
    assert first.files == second.files

    runtime = first.files["Lua/CivilizationRuntime.lua"]
    assert "Game.GetActivePlayer" not in runtime
    assert "math.random" not in runtime
    assert "Events.Gameplay" not in runtime
    assert runtime.count("GameEvents.PlayerCityFounded.Add(") == 1
    assert runtime.count("GameEvents.CityTrained.Add(") == 1
    assert "GameEvents.PlayerDoTurn.Add(" not in runtime
    assert runtime.count(".Add(") == 2

    manifest = json.loads(first.files["Documentation/LUA_EFFECT_MANIFEST.json"])
    assert manifest["selected_count"] == 2
    assert manifest["runtime"]["registered_game_events"] == [
        "PlayerCityFounded",
        "CityTrained",
    ]
    assert all(item["status"] == "COMPILED" for item in manifest["effects"])
    assert manifest["runtime_gate"] == "REQUIRED_NOT_RUN"

    capability = json.loads(first.files["Documentation/CAPABILITY_REPORT.json"])
    assert len(capability["compiled_lua_effects"]) == 2
    assert not capability["unimplemented_effects"]
    assert capability["release_gates"]["mechanic_completeness"] == "PASS"
    assert capability["release_gates"]["lua_effect_runtime"] == "REQUIRED_NOT_RUN"
    assert capability["release_gates"]["bnw_in_game"] == "REQUIRED_NOT_RUN"

    modinfo = ET.fromstring(first.files["Kingdom_Of_Lithuania.modinfo"])
    assert modinfo.findtext("./Properties/AffectsSavedGames") == "1"
    assert modinfo.findtext("./Properties/SupportsMultiplayer") == "0"
    assert modinfo.findtext("./Properties/SupportsHotSeat") == "0"


@pytest.mark.parametrize(
    "primitive_id",
    ["unit_kill_reward", "great_person_expended_reward"],
)
def test_primitives_without_a_friendly_unit_reject_unit_scoped_rewards(
    sample_project, monkeypatch: pytest.MonkeyPatch, primitive_id: str
) -> None:
    definition = SimpleNamespace(
        effect_id="test.invalid-unit-context",
        version=1,
        label="Invalid context",
        category="Test",
        description="Must be rejected.",
        primitive_id=primitive_id,
        trigger="test",
        runtime_config={"reward": "heal", "amount": 5, "scope": "unit"},
        parameters=(),
        origin=SimpleNamespace(value="studio-original"),
        inspiration="",
        tags=frozenset(),
        pure_bnw=True,
        supports_multiplayer=False,
        supports_hotseat=False,
        runtime_notes="",
    )
    monkeypatch.setattr(lua_runtime, "lua_effect_by_id", lambda _effect_id: definition)
    project = deepcopy(sample_project)
    project.lua_effects = [
        LuaEffectSelection(
            instance_id="00000000-0000-4000-8000-000000000091",
            effect_id=definition.effect_id,
            effect_version=1,
        )
    ]
    with pytest.raises(ValueError, match="cannot supply that friendly target"):
        generate_lua_runtime(project)


def test_connected_city_dispatch_never_counts_the_capital(sample_project) -> None:
    project = deepcopy(sample_project)
    definition = _definition("city_connection_reward")
    project.lua_effects = [_selection(definition)]
    runtime = generate_lua_runtime(project)
    assert "not pCity:IsCapital() and pPlayer:IsCapitalConnectedToCity(pCity)" in runtime


def test_runtime_uses_truthful_stock_bnw_context_and_reward_semantics(
    sample_project,
) -> None:
    project = deepcopy(sample_project)
    project.lua_effects = [_selection(next(iter_lua_effects()))]
    runtime = generate_lua_runtime(project)
    assert "if not change or change <= 0 then return end" in runtime
    assert "if isDelay or not killerPlayerID" not in runtime
    assert "or killedPlayerID == killerPlayerID then return end" in runtime
    assert "population = oldPopulation" in runtime
    assert "local population = tonumber(context.population)" in runtime
    assert "if oldPopulation <= 0 or newPopulation <= oldPopulation then return end" in runtime
    assert "pPlot:IsFriendlyTerritory(pUnit:GetOwner())" in runtime
    assert "plotCity:GetOwner() == expectedOwner" in runtime
    assert "GameDefines.MIN_WATER_SIZE_FOR_OCEAN or -1" in runtime
    assert "local hasConcreteOrder = pCity:GetProductionUnit() ~= -1" in runtime
    assert "pCity:ChangeProduction(amount)" in runtime
    assert "pCity:SetOverflowProduction(pCity:GetOverflowProduction() + amount)" in runtime
    assert "_GrantProduction(pCity, amount, preserveAsOverflow)" in runtime
    assert "preserve_production_as_overflow = true" in runtime
    assert 'scientist = "UNITCLASS_SCIENTIST"' in runtime
    assert "expendedUnit.Class == greatPeople[condition]" in runtime
    assert "if pCity and pCity:GetOwner() ~= playerID then pCity = nil end" in runtime


def test_runtime_boundary_rejects_more_than_two_and_duplicate_effects(
    sample_project,
) -> None:
    definitions = list(iter_lua_effects())
    project = deepcopy(sample_project)
    project.lua_effects = [
        _selection(definitions[index], index + 1) for index in range(3)
    ]
    with pytest.raises(ValueError, match="at most 2"):
        generate_lua_runtime(project)

    project.lua_effects = [
        _selection(definitions[0], 1),
        _selection(definitions[0], 2),
    ]
    with pytest.raises(ValueError, match="Duplicate Lua effect id"):
        generate_lua_runtime(project)


@pytest.mark.parametrize(
    ("primitive_id", "state_snippet"),
    [
        ("city_connection_reward", '"connection:" .. playerID'),
        ("war_state_reward", '"war:" .. playerID'),
        ("golden_age_started_reward", '"golden_age:" .. playerID'),
    ],
)
def test_stateful_effects_use_namespaced_save_data(
    sample_project, primitive_id: str, state_snippet: str
) -> None:
    project = deepcopy(sample_project)
    definition = _definition(primitive_id)
    project.lua_effects = [_selection(definition)]
    runtime = generate_lua_runtime(project)
    manifest = lua_effect_manifest(project)
    assert "Modding.OpenSaveData" in runtime
    assert state_snippet in runtime
    assert manifest["runtime"]["persistent_state"] is True
    assert manifest["runtime"]["state_namespaces"] == [
        f"civ5studio:{project.mod_id}:{project.lua_effects[0].instance_id}"
    ]


def test_war_streaks_reward_the_threshold_once_and_reset(sample_project) -> None:
    project = deepcopy(sample_project)
    definition = next(
        item
        for item in iter_lua_effects()
        if item.primitive_id == "war_state_reward"
        and item.runtime_config["condition"] == "war_streak"
    )
    project.lua_effects = [_selection(definition)]
    runtime = generate_lua_runtime(project)
    assert "warStreak = warStreak + 1" in runtime
    assert "peaceStreak = 0" in runtime
    assert "context.war_streak == threshold" in runtime


def test_only_war_transition_effects_require_a_previous_state(sample_project) -> None:
    project = deepcopy(sample_project)
    definition = next(
        item
        for item in iter_lua_effects()
        if item.primitive_id == "war_state_reward"
        and item.runtime_config["condition"] == "multiple_wars"
    )
    project.lua_effects = [_selection(definition)]

    runtime = generate_lua_runtime(project)

    assert 'local needsPrevious = effect.condition == "war_started"' in runtime
    assert 'or effect.condition == "peace_started"' in runtime
    assert "(not needsPrevious or previous ~= nil)" in runtime


def test_first_building_state_is_per_effect_instance_and_city(sample_project) -> None:
    project = deepcopy(sample_project)
    definition = next(
        item
        for item in iter_lua_effects()
        if item.runtime_config["condition"] == "first_building"
    )
    project.lua_effects = [_selection(definition)]
    runtime = generate_lua_runtime(project)
    manifest = lua_effect_manifest(project)
    assert '"first_building:" .. playerID' in runtime
    assert 'pCity:GetX() .. ":" .. pCity:GetY()' in runtime
    assert "pCity:GetGameTurnFounded()" in runtime
    assert manifest["runtime"]["persistent_state"] is True


def test_runtime_scalar_data_is_lua_escaped(sample_project, monkeypatch) -> None:
    injection = '\"; Game.GetActivePlayer():ChangeGold(999); --'
    definition = SimpleNamespace(
        effect_id="test.scalar-escaping",
        version=1,
        label="Escaping",
        category="Test",
        description="Scalar data only.",
        primitive_id="player_turn_reward",
        trigger="PlayerDoTurn",
        runtime_config={
            "reward": "gold",
            "amount": 1,
            "scope": "player",
            "condition": "treasury_above",
            "condition_value": injection,
        },
        parameters=(),
        origin=SimpleNamespace(value="studio-original"),
        inspiration="",
        tags=frozenset(),
        pure_bnw=True,
        supports_multiplayer=False,
        supports_hotseat=False,
        runtime_notes="",
    )
    monkeypatch.setattr(lua_runtime, "lua_effect_by_id", lambda _effect_id: definition)
    project = deepcopy(sample_project)
    project.lua_effects = [
        LuaEffectSelection(
            instance_id="00000000-0000-4000-8000-000000000092",
            effect_id=definition.effect_id,
            effect_version=1,
        )
    ]
    runtime = generate_lua_runtime(project)
    lua_ast.parse(runtime)
    assert f'"condition_value"] = "{injection}"' not in runtime
    assert '\\"; Game.GetActivePlayer()' in runtime


def test_project_name_cannot_end_a_lua_header_comment(sample_project) -> None:
    project = deepcopy(sample_project)
    project.mod_name = "Visible name\nGame.GetActivePlayer():ChangeGold(999)"
    definition = next(iter_lua_effects())
    project.lua_effects = [_selection(definition)]
    runtime = generate_lua_runtime(project)
    assert "Visible name" not in runtime
    assert "Game.GetActivePlayer" not in runtime
