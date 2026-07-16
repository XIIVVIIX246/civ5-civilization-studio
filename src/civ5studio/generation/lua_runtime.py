"""Deterministic, data-driven BNW Lua runtime generation.

The catalog owns effect descriptions and typed configuration.  This module is
the only place where those definitions become executable Lua.  It deliberately
emits a fixed dispatcher implementation plus scalar data; project text is never
treated as source code.
"""

from __future__ import annotations

import json
from typing import Mapping

from civ5studio.domain.lua_effects import (
    catalog_conditions,
    catalog_primitive_ids,
    lua_effect_by_id,
    lua_effects_compatible,
    validate_lua_parameters,
)
from civ5studio.domain.models import CivProject


LUA_EFFECT_LIMIT = 2
RUNTIME_GATE = "REQUIRED_NOT_RUN"
SUPPORTED_PRIMITIVES = frozenset(
    {
        "player_turn_reward",
        "city_founded_reward",
        "city_captured_reward",
        "unit_trained_reward",
        "building_completed_reward",
        "improvement_completed_reward",
        "policy_adopted_reward",
        "tech_researched_reward",
        "great_person_expended_reward",
        "golden_age_started_reward",
        "city_growth_reward",
        "city_connection_reward",
        "war_state_reward",
        "unit_kill_reward",
        "unit_heal_turn",
        "unit_promotion_on_train",
    }
)
if set(catalog_primitive_ids()) != SUPPORTED_PRIMITIVES:
    missing = sorted(set(catalog_primitive_ids()) - SUPPORTED_PRIMITIVES)
    extra = sorted(SUPPORTED_PRIMITIVES - set(catalog_primitive_ids()))
    raise RuntimeError(
        "Lua compiler/catalog primitive mismatch; "
        f"missing={missing!r}, compiler_only={extra!r}."
    )
SUPPORTED_REWARDS = frozenset(
    {"gold", "faith", "culture", "golden_age", "food", "production", "experience", "heal"}
)
SUPPORTED_CONFIG_KEYS = frozenset(
    {"reward", "amount", "condition", "condition_value", "threshold", "scope", "promotion"}
)
SUPPORTED_SCOPES = frozenset({"player", "capital", "city", "unit"})
SUPPORTED_CONDITIONS = frozenset(
    {
        "admiral", "adjacent_forest", "adjacent_jungle", "adjacent_marsh",
        "air", "always", "artist", "at_peace", "at_war",
        "barbarian", "bomber", "camp", "capital", "city_count_at_least",
        "city_count_at_most", "city_count_equals", "civilian", "coastal",
        "culture_building", "defense_building", "desert", "distance_at_least",
        "economic_building", "engineer", "era", "faith_building", "farm",
        "fighter", "first_building", "fishing_boats", "general",
        "golden_age", "gunpowder", "happiness_below", "happy_capital", "hill",
        "holy_city", "ideology", "land_desert",
        "land_forest", "land_friendly", "land_hill", "land_jungle",
        "land_marsh", "land_military", "land_snow", "land_tundra",
        "lumbermill", "melee", "merchant", "military",
        "military_building", "mine", "mounted", "multiple_wars", "musician",
        "naval", "naval_friendly", "naval_ranged", "noncapital",
        "oil_well", "original_capital", "pasture", "peace_and_happy",
        "peace_started", "peace_streak", "plantation", "policy_branch",
        "population_at_least", "population_at_most", "positive_happiness",
        "prophet", "quarry", "ranged", "recon",
        "resource", "restoration_candidate", "river", "science_building",
        "scientist", "siege", "snow", "trading_post", "treasury_above",
        "treasury_band", "treasury_below", "tundra", "unhappy",
        "war_and_golden_age", "war_started", "war_streak", "wonder", "writer",
    }
)
if set(catalog_conditions()) != SUPPORTED_CONDITIONS:
    missing = sorted(set(catalog_conditions()) - SUPPORTED_CONDITIONS)
    extra = sorted(SUPPORTED_CONDITIONS - set(catalog_conditions()))
    raise RuntimeError(
        "Lua compiler/catalog condition mismatch; "
        f"missing={missing!r}, compiler_only={extra!r}."
    )
PRIMITIVE_HOOKS: Mapping[str, str] = {
    "player_turn_reward": "PlayerDoTurn",
    "city_connection_reward": "PlayerDoTurn",
    "war_state_reward": "PlayerDoTurn",
    "unit_heal_turn": "PlayerDoTurn",
    "city_founded_reward": "PlayerCityFounded",
    "city_captured_reward": "CityCaptureComplete",
    "unit_trained_reward": "CityTrained",
    "unit_promotion_on_train": "CityTrained",
    "building_completed_reward": "CityConstructed",
    "improvement_completed_reward": "BuildFinished",
    "policy_adopted_reward": "PlayerAdoptPolicy",
    "tech_researched_reward": "TeamTechResearched",
    "great_person_expended_reward": "GreatPersonExpended",
    "golden_age_started_reward": "PlayerDoTurn",
    "city_growth_reward": "SetPopulation",
    "unit_kill_reward": "UnitPrekill",
}
PRIMITIVE_TARGET_SCOPES: Mapping[str, frozenset[str]] = {
    "player_turn_reward": frozenset({"player", "capital"}),
    "city_founded_reward": frozenset({"player", "city", "capital"}),
    "city_captured_reward": frozenset({"player", "city", "capital"}),
    "unit_trained_reward": frozenset({"player", "city", "capital", "unit"}),
    "building_completed_reward": frozenset({"player", "city", "capital"}),
    "improvement_completed_reward": frozenset({"player", "city", "capital"}),
    "policy_adopted_reward": frozenset({"player", "capital"}),
    "tech_researched_reward": frozenset({"player", "capital"}),
    "great_person_expended_reward": frozenset({"player", "capital"}),
    "golden_age_started_reward": frozenset({"player", "capital"}),
    "city_growth_reward": frozenset({"player", "city", "capital"}),
    "city_connection_reward": frozenset({"player", "city", "capital"}),
    "war_state_reward": frozenset({"player", "capital"}),
    "unit_kill_reward": frozenset({"player", "capital"}),
    "unit_heal_turn": frozenset({"unit"}),
    "unit_promotion_on_train": frozenset({"unit"}),
}
HOOK_HANDLERS: Mapping[str, str] = {
    "PlayerDoTurn": "OnPlayerDoTurn",
    "PlayerCityFounded": "OnPlayerCityFounded",
    "CityCaptureComplete": "OnCityCaptureComplete",
    "CityTrained": "OnCityTrained",
    "CityConstructed": "OnCityConstructed",
    "BuildFinished": "OnBuildFinished",
    "PlayerAdoptPolicy": "OnPlayerAdoptPolicy",
    "TeamTechResearched": "OnTeamTechResearched",
    "GreatPersonExpended": "OnGreatPersonExpended",
    "SetPopulation": "OnSetPopulation",
    "UnitPrekill": "OnUnitPrekill",
}


def _enum_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    return str(candidate)


def _scalar(value: object) -> str | int | bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    raise TypeError(
        "Lua effect runtime configuration must contain only strings, integers, "
        f"or booleans; found {type(value).__name__}."
    )


def _merged_runtime_config(selection: object, definition: object) -> dict[str, str | int | bool]:
    configured = {
        str(key): _scalar(value)
        for key, value in dict(getattr(definition, "runtime_config", {})).items()
    }
    configured.update(
        {
            str(key): _scalar(value)
            for key, value in dict(getattr(selection, "parameters", {})).items()
        }
    )
    unknown_keys = sorted(set(configured) - SUPPORTED_CONFIG_KEYS)
    if unknown_keys:
        raise ValueError(
            f"Lua effect {getattr(definition, 'effect_id', '<unknown>')} uses "
            f"unsupported runtime keys: {', '.join(unknown_keys)}"
        )
    condition = str(configured.get("condition", "always"))
    if condition not in SUPPORTED_CONDITIONS:
        raise ValueError(
            f"Lua effect {getattr(definition, 'effect_id', '<unknown>')} uses "
            f"unsupported condition: {condition}"
        )
    scope = str(configured.get("scope", "player"))
    if scope not in SUPPORTED_SCOPES:
        raise ValueError(
            f"Lua effect {getattr(definition, 'effect_id', '<unknown>')} uses "
            f"unsupported scope: {scope}"
        )
    return configured


def selected_lua_effects(project: CivProject) -> list[dict[str, object]]:
    """Resolve selected catalog entries into stable compiler records."""

    if len(project.lua_effects) > LUA_EFFECT_LIMIT:
        raise ValueError(
            f"A civilization may select at most {LUA_EFFECT_LIMIT} Lua effects."
        )
    resolved: list[dict[str, object]] = []
    seen_effect_ids: set[str] = set()
    seen_instance_ids: set[str] = set()
    for slot, selection in enumerate(project.lua_effects, start=1):
        definition = lua_effect_by_id(selection.effect_id)
        if definition is None:
            # Domain validation rejects this before compilation.  Keeping the
            # failure explicit here prevents a future caller from silently
            # dropping an unknown effect.
            raise ValueError(f"Unknown Lua effect id: {selection.effect_id}")
        if selection.effect_id in seen_effect_ids:
            raise ValueError(f"Duplicate Lua effect id: {selection.effect_id}")
        if selection.instance_id in seen_instance_ids:
            raise ValueError(
                f"Duplicate Lua effect instance id: {selection.instance_id}"
            )
        seen_effect_ids.add(selection.effect_id)
        seen_instance_ids.add(selection.instance_id)
        if selection.effect_version != definition.version:
            raise ValueError(
                f"Lua effect {selection.effect_id} selects version "
                f"{selection.effect_version}, but catalog version {definition.version} "
                "is installed."
            )
        if not isinstance(selection.parameters, Mapping):
            raise ValueError(
                f"Lua effect {selection.effect_id} parameters must be a mapping."
            )
        parameter_errors = validate_lua_parameters(
            definition, selection.parameters
        )
        if parameter_errors:
            raise ValueError(
                f"Lua effect {selection.effect_id} has invalid parameters: "
                + "; ".join(parameter_errors)
            )
        if definition.primitive_id not in SUPPORTED_PRIMITIVES:
            raise ValueError(
                f"Lua effect {selection.effect_id} uses unsupported primitive: "
                f"{definition.primitive_id}"
            )
        config = _merged_runtime_config(selection, definition)
        scope = str(config.get("scope", "player"))
        if scope not in PRIMITIVE_TARGET_SCOPES[definition.primitive_id]:
            raise ValueError(
                f"Lua effect {selection.effect_id} targets {scope}, but primitive "
                f"{definition.primitive_id} cannot supply that friendly target."
            )
        if definition.primitive_id == "unit_promotion_on_train":
            promotion = config.get("promotion")
            if not isinstance(promotion, str) or not promotion.startswith("PROMOTION_"):
                raise ValueError(
                    f"Lua effect {selection.effect_id} requires a fixed PROMOTION_* id."
                )
            if config.get("scope") != "unit":
                raise ValueError(
                    f"Lua effect {selection.effect_id} must target unit scope."
                )
        else:
            reward = config.get("reward")
            if reward not in SUPPORTED_REWARDS:
                raise ValueError(
                    f"Lua effect {selection.effect_id} uses unsupported reward: {reward}"
                )
            amount = config.get("amount")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                raise ValueError(
                    f"Lua effect {selection.effect_id} requires a positive integer amount."
                )
            valid_scopes = {
                "gold": {"player"},
                "faith": {"player"},
                "culture": {"player"},
                "golden_age": {"player"},
                "food": {"city", "capital"},
                "production": {"city", "capital"},
                "experience": {"unit"},
                "heal": {"unit"},
            }
            if scope not in valid_scopes[str(reward)]:
                raise ValueError(
                    f"Lua effect {selection.effect_id} cannot grant {reward} to {scope}."
                )
        resolved.append(
            {
                "slot": slot,
                "instance_id": selection.instance_id,
                "effect_id": definition.effect_id,
                "effect_version": selection.effect_version,
                "catalog_version": definition.version,
                "label": definition.label,
                "category": definition.category,
                "description": definition.description,
                "primitive_id": definition.primitive_id,
                "trigger": definition.trigger,
                "runtime_config": config,
                "parameters": dict(selection.parameters),
                "origin": _enum_value(definition.origin),
                "inspiration": definition.inspiration,
                "tags": sorted(definition.tags),
                "pure_bnw": bool(definition.pure_bnw),
                "supports_multiplayer": bool(definition.supports_multiplayer),
                "supports_hotseat": bool(definition.supports_hotseat),
                "runtime_notes": definition.runtime_notes,
                "status": "COMPILED",
                "runtime_gate": RUNTIME_GATE,
            }
        )
    if len(project.lua_effects) == 2 and not lua_effects_compatible(
        project.lua_effects[0].effect_id, project.lua_effects[1].effect_id
    ):
        raise ValueError("The selected Lua effect pair is catalog-incompatible.")
    return resolved


def registered_lua_hooks(project: CivProject) -> tuple[str, ...]:
    effects = selected_lua_effects(project)
    primitives = {str(effect["primitive_id"]) for effect in effects}
    required = {PRIMITIVE_HOOKS[primitive] for primitive in primitives}
    return tuple(hook for hook in HOOK_HANDLERS if hook in required)


def uses_persistent_lua_state(project: CivProject) -> bool:
    for effect in selected_lua_effects(project):
        config = effect["runtime_config"]
        assert isinstance(config, Mapping)
        if effect["primitive_id"] in {
            "golden_age_started_reward",
            "city_connection_reward",
            "war_state_reward",
        }:
            return True
        if config.get("condition") == "first_building":
            return True
    return False


def lua_effect_manifest(project: CivProject) -> dict[str, object]:
    effects = selected_lua_effects(project)
    persistent_state = uses_persistent_lua_state(project)
    pair_status = "PASS" if len(effects) == 2 else "NOT_APPLICABLE"
    return {
        "manifest_format": "civ5studio.lua-effect-selection",
        "manifest_version": 1,
        "project_id": project.project_id,
        "civilization_type": project.ids().civilization,
        "selection_limit": LUA_EFFECT_LIMIT,
        "selected_count": len(effects),
        "compatibility": {
            "status": pair_status,
            "selected_effect_ids": [effect["effect_id"] for effect in effects],
            "reason": (
                "The two distinct selections passed the catalog tag-conflict rules."
                if len(effects) == 2
                else "Pair compatibility applies only when two effects are selected."
            ),
        },
        "runtime": {
            "entry_point": "Lua/CivilizationRuntime.lua",
            "implementation": "fixed namespaced dispatchers with scalar catalog data",
            "authority": "gameplay GameEvents; never the active UI player",
            "persistent_state": persistent_state,
            "state_backend": (
                "Modding.OpenSaveData with namespaced keys"
                if persistent_state
                else "not used"
            ),
            "state_namespaces": (
                [
                    f"civ5studio:{project.mod_id}:{effect['instance_id']}"
                    for effect in effects
                    if effect["primitive_id"]
                    in {
                        "golden_age_started_reward",
                        "city_connection_reward",
                        "war_state_reward",
                    }
                    or (
                        isinstance(effect["runtime_config"], Mapping)
                        and effect["runtime_config"].get("condition")
                        == "first_building"
                    )
                ]
                if persistent_state
                else []
            ),
            "randomness": False,
            "reward_semantics": {
                "production": (
                    "Applied to a concrete unit, building, project, or specialist "
                    "order; completion-callback rewards and rewards with no concrete "
                    "order are preserved as city overflow production."
                )
            },
            "registered_game_events": list(registered_lua_hooks(project)),
        },
        "modinfo_overrides": {
            "AffectsSavedGames": 1 if effects else None,
            "SupportsMultiplayer": 0 if effects else None,
            "SupportsHotSeat": 0 if effects else None,
            "reason": (
                "Selected gameplay Lua is save-affecting and has not received "
                "multiplayer or hot-seat runtime certification."
                if effects
                else "No selected gameplay Lua effects."
            ),
        },
        "effects": effects,
        "runtime_gate": RUNTIME_GATE if effects else "NOT_APPLICABLE",
        "validation_boundary": (
            "COMPILED means the effect was generated from a typed, fixed primitive. "
            "It does not prove Civilization V or IGE runtime behavior."
        ),
    }


def lua_effect_manifest_json(project: CivProject) -> str:
    return json.dumps(lua_effect_manifest(project), indent=2, ensure_ascii=False) + "\n"


def lua_effect_manifest_markdown(project: CivProject) -> str:
    payload = lua_effect_manifest(project)
    effects = payload["effects"]
    assert isinstance(effects, list)
    lines = [
        f"# Selected Lua Effects: {project.mod_name}\n\n",
        f"- Selected: {len(effects)} of {LUA_EFFECT_LIMIT}.\n",
        f"- Pair compatibility: **{payload['compatibility']['status']}**.\n",
        "- Runtime: one namespaced `Lua/CivilizationRuntime.lua` entry point.\n",
        "- Gameplay authority: `GameEvents` player/team arguments; never the active UI player.\n",
        "- Randomness: none.\n",
        "- Production rewards: current concrete order, or preserved as city "
        "overflow during completion callbacks and when no concrete order is active.\n",
        f"- Persistent state: {payload['runtime']['persistent_state']} "
        f"({payload['runtime']['state_backend']}).\n",
        "- Registered gameplay events: "
        + (", ".join(f"`{item}`" for item in registered_lua_hooks(project)) or "none")
        + ".\n",
        f"- BNW/IGE runtime gate: **{payload['runtime_gate']}**.\n",
    ]
    if effects:
        lines.extend(
            (
                "- `.modinfo` overrides: `AffectsSavedGames=1`, "
                "`SupportsMultiplayer=0`, `SupportsHotSeat=0`.\n\n",
                "Static compilation does not prove in-game behavior. Test every selected "
                "effect in Brave New World and with IGE enabled.\n\n",
            )
        )
    else:
        lines.append("\nNo gameplay Lua effect is selected.\n")
        return "".join(lines)
    for effect in effects:
        assert isinstance(effect, Mapping)
        lines.extend(
            (
                f"## Slot {effect['slot']}: {effect['label']}\n\n",
                f"- ID/version: `{effect['effect_id']}` v{effect['effect_version']}\n",
                f"- Instance: `{effect['instance_id']}`\n",
                f"- Category: {effect['category']}\n",
                f"- Trigger/primitive: `{effect['trigger']}` / `{effect['primitive_id']}`\n",
                f"- Origin: `{effect['origin']}`\n",
                f"- Description: {effect['description']}\n",
                f"- Runtime configuration: `{json.dumps(effect['runtime_config'], sort_keys=True)}`\n",
                f"- Status: **COMPILED**; runtime gate **{RUNTIME_GATE}**.\n",
            )
        )
        if effect.get("inspiration"):
            lines.append(f"- Inspiration: {effect['inspiration']}\n")
        if effect.get("runtime_notes"):
            lines.append(f"- Runtime notes: {effect['runtime_notes']}\n")
        lines.append("\n")
    return "".join(lines)


def _lua_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _lua_literal(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return _lua_string(value)


def _lua_effect_table(project: CivProject) -> str:
    rows: list[str] = []
    for effect in selected_lua_effects(project):
        values: dict[str, str | int | bool] = {
            "instance_id": str(effect["instance_id"]),
            "effect_id": str(effect["effect_id"]),
            "effect_version": int(effect["effect_version"]),
            "primitive_id": str(effect["primitive_id"]),
        }
        config = effect["runtime_config"]
        assert isinstance(config, Mapping)
        values.update({str(key): _scalar(value) for key, value in config.items()})
        rendered = ", ".join(
            f"[{_lua_string(key)}] = {_lua_literal(value)}"
            for key, value in sorted(values.items())
        )
        rows.append(f"  {{ {rendered} }},")
    return "\n".join(rows)


def _lua_event_registrations(project: CivProject, prefix: str) -> str:
    rows: list[str] = []
    for hook in registered_lua_hooks(project):
        handler = HOOK_HANDLERS[hook]
        rows.extend(
            (
                f"if GameEvents and GameEvents.{hook} then",
                f"  GameEvents.{hook}.Add({prefix}_{handler})",
                "end",
            )
        )
    return "\n".join(rows)


def generate_lua_runtime(project: CivProject) -> str:
    """Emit one guarded BNW runtime for zero to two selected effects."""

    prefix = project.internal_prefix
    civilization_type = project.ids().civilization
    effects = selected_lua_effects(project)
    if not effects:
        return f'''-- CivilizationRuntime.lua
-- Generated civilization runtime shell.
-- Safe runtime shell. No tested Lua effect is selected.

local iCivilization = GameInfoTypes["{civilization_type}"]
if not iCivilization then
  return
end

local function {prefix}_IsValidMajorPlayer(pPlayer)
  return pPlayer
    and pPlayer:IsAlive()
    and not pPlayer:IsBarbarian()
    and not pPlayer:IsMinorCiv()
end

-- Select up to two tested catalog effects in Civilization Studio to register
-- the fixed, data-driven GameEvents runtime.
'''

    effect_rows = _lua_effect_table(project)
    event_registrations = _lua_event_registrations(project, prefix)
    state_namespace = _lua_string(f"civ5studio:{project.mod_id}:")
    return f'''-- CivilizationRuntime.lua
-- Generated civilization runtime.
-- Generated from typed Civ V Civilization Studio Lua effects.
-- Runtime proof still requires a BNW and IGE in-game test.

local iCivilization = GameInfoTypes["{civilization_type}"]
if not iCivilization then
  return
end

local {prefix}_Effects = {{
{effect_rows}
}}
local {prefix}_StateNamespace = {state_namespace}
local {prefix}_SaveData = nil
if Modding and Modding.OpenSaveData then
  local opened, saveData = pcall(Modding.OpenSaveData)
  if opened then {prefix}_SaveData = saveData end
end

local function {prefix}_StateKey(effect, suffix)
  return {prefix}_StateNamespace .. effect.instance_id .. ":" .. suffix
end

local function {prefix}_GetState(effect, suffix)
  local key = {prefix}_StateKey(effect, suffix)
  if {prefix}_SaveData then return {prefix}_SaveData.GetValue(key) end
  return nil
end

local function {prefix}_SetState(effect, suffix, value)
  local key = {prefix}_StateKey(effect, suffix)
  if {prefix}_SaveData then
    {prefix}_SaveData.SetValue(key, value)
    return true
  end
  return false
end

local function {prefix}_IsValidMajorPlayer(pPlayer)
  return pPlayer
    and pPlayer:IsAlive()
    and not pPlayer:IsBarbarian()
    and not pPlayer:IsMinorCiv()
end

local function {prefix}_IsOurPlayer(pPlayer)
  return {prefix}_IsValidMajorPlayer(pPlayer)
    and pPlayer:GetCivilizationType() == iCivilization
end

local function {prefix}_ForPrimitive(primitiveID, callback)
  for _, effect in ipairs({prefix}_Effects) do
    if effect.primitive_id == primitiveID then
      callback(effect)
    end
  end
end

local function {prefix}_BuildingHasYield(iBuilding, yieldType)
  local building = GameInfo.Buildings[iBuilding]
  if not building then return false end
  local yieldTables = {{
    GameInfo.Building_YieldChanges,
    GameInfo.Building_YieldChangesPerPop,
    GameInfo.Building_YieldModifiers,
    GameInfo.Building_TechEnhancedYieldChanges
  }}
  for _, infoTable in ipairs(yieldTables) do
    if infoTable then
      for row in infoTable() do
        local amount = tonumber(row.Yield or row.YieldMod or row.YieldChange) or 0
        if row.BuildingType == building.Type and row.YieldType == yieldType
          and amount > 0 then
          return true
        end
      end
    end
  end
  return false
end

local function {prefix}_AdjacentHasFeature(pPlot, featureType)
  if not pPlot or not featureType then return false end
  for direction = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1 do
    local adjacent = Map.PlotDirection(pPlot:GetX(), pPlot:GetY(), direction)
    if adjacent and adjacent:GetFeatureType() == featureType then return true end
  end
  return false
end

local function {prefix}_PlotOrAdjacentHasResource(pPlot, teamID)
  if not pPlot then return false end
  if pPlot:GetResourceType(teamID) ~= -1 then return true end
  for direction = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1 do
    local adjacent = Map.PlotDirection(pPlot:GetX(), pPlot:GetY(), direction)
    if adjacent and adjacent:GetResourceType(teamID) ~= -1 then return true end
  end
  return false
end

local function {prefix}_WarCount(pPlayer)
  if not pPlayer then return 0 end
  local team = Teams[pPlayer:GetTeam()]
  return team and team:GetAtWarCount(false) or 0
end

local function {prefix}_PassesCondition(effect, context)
  local condition = effect.condition or "always"
  if condition == "always" then return true end
  local pPlayer = context.player
  local pCity = context.city
  local pUnit = context.unit
  local pPlot = context.plot or (pCity and pCity:Plot())
  local conditionValue = effect.condition_value or effect.threshold
  local threshold = tonumber(conditionValue) or 0
  local warCount = context.war_count or {prefix}_WarCount(pPlayer)

  if condition == "at_war" then return warCount > 0 end
  if condition == "at_peace" then return warCount == 0 end
  if condition == "golden_age" then return pPlayer and pPlayer:IsGoldenAge() end
  if condition == "positive_happiness" then
    return pPlayer and pPlayer:GetExcessHappiness() > 0
  end
  if condition == "unhappy" then return pPlayer and pPlayer:IsEmpireUnhappy() end
  if condition == "happiness_below" then
    return pPlayer and pPlayer:GetExcessHappiness() < threshold
  end
  if condition == "happy_capital" then
    return pPlayer and pPlayer:GetExcessHappiness() > 0
      and pPlayer:GetCapitalCity() ~= nil
  end
  if condition == "peace_and_happy" then
    return pPlayer and warCount == 0 and pPlayer:GetExcessHappiness() > 0
  end
  if condition == "war_and_golden_age" then
    return pPlayer and warCount > 0 and pPlayer:IsGoldenAge()
  end
  if condition == "treasury_below" then return pPlayer and pPlayer:GetGold() < threshold end
  if condition == "treasury_above" then return pPlayer and pPlayer:GetGold() >= threshold end
  if condition == "treasury_band" then
    local low, high = string.match(tostring(conditionValue or ""), "^(-?%d+):(-?%d+)$")
    local gold = pPlayer and pPlayer:GetGold()
    return gold and low and high and gold >= tonumber(low) and gold <= tonumber(high)
  end
  if condition == "city_count_at_most" then
    return pPlayer and pPlayer:GetNumCities() <= threshold
  end
  if condition == "city_count_at_least" then
    return pPlayer and pPlayer:GetNumCities() >= threshold
  end
  if condition == "city_count_equals" then
    return pPlayer and pPlayer:GetNumCities() == threshold
  end
  if condition == "multiple_wars" then return warCount >= threshold end

  if condition == "coastal" then
    return pCity and pCity:IsCoastal(GameDefines.MIN_WATER_SIZE_FOR_OCEAN or -1)
  end
  if condition == "river" then return pPlot and pPlot:IsRiver() end
  if condition == "hill" then return pPlot and pPlot:IsHills() end
  if condition == "adjacent_forest" then
    return {prefix}_AdjacentHasFeature(pPlot, GameInfoTypes["FEATURE_FOREST"])
  end
  if condition == "adjacent_jungle" then
    return {prefix}_AdjacentHasFeature(pPlot, GameInfoTypes["FEATURE_JUNGLE"])
  end
  if condition == "adjacent_marsh" then
    return {prefix}_AdjacentHasFeature(pPlot, GameInfoTypes["FEATURE_MARSH"])
  end
  if condition == "desert" then
    return pPlot and pPlot:GetTerrainType() == GameInfoTypes["TERRAIN_DESERT"]
  end
  if condition == "tundra" then
    return pPlot and pPlot:GetTerrainType() == GameInfoTypes["TERRAIN_TUNDRA"]
  end
  if condition == "snow" then
    return pPlot and pPlot:GetTerrainType() == GameInfoTypes["TERRAIN_SNOW"]
  end
  if condition == "resource" then
    return pPlot and pPlayer
      and {prefix}_PlotOrAdjacentHasResource(pPlot, pPlayer:GetTeam())
  end
  if condition == "distance_at_least" then
    local capital = pPlayer and pPlayer:GetCapitalCity()
    return pCity and capital and Map.PlotDistance(
      pCity:GetX(), pCity:GetY(), capital:GetX(), capital:GetY()
    ) >= threshold
  end
  if condition == "capital" then
    local expectedOwner = pPlayer and pPlayer:GetID()
      or (pUnit and pUnit:GetOwner())
    if pCity then
      return pCity:IsCapital()
        and expectedOwner ~= nil and pCity:GetOwner() == expectedOwner
    end
    local plotCity = pPlot and pPlot:GetPlotCity()
    return plotCity and plotCity:IsCapital()
      and expectedOwner ~= nil and plotCity:GetOwner() == expectedOwner
  end
  if condition == "noncapital" then return pCity and not pCity:IsCapital() end
  if condition == "holy_city" then
    if not pCity or not GameInfo.Religions then return false end
    for religion in GameInfo.Religions() do
      if pCity:IsHolyCityForReligion(religion.ID) then return true end
    end
    return false
  end
  if condition == "original_capital" then
    return pCity and pCity:IsOriginalCapital()
  end
  if condition == "restoration_candidate" then
    local originalOwner = pCity and pCity:GetOriginalOwner()
    return originalOwner and originalOwner ~= -1
      and originalOwner ~= context.old_owner and originalOwner ~= context.new_owner
  end
  if condition == "population_at_most" then
    local population = tonumber(context.population)
      or (pCity and pCity:GetPopulation())
    return population and population <= threshold
  end
  if condition == "population_at_least" then
    local population = tonumber(context.population)
      or (pCity and pCity:GetPopulation())
    return population and population >= threshold
  end

  if condition == "military" then return pUnit and pUnit:IsCombatUnit() end
  if condition == "civilian" then return pUnit and not pUnit:IsCombatUnit() end
  if condition == "land_military" then
    return pUnit and pUnit:IsCombatUnit()
      and pUnit:GetDomainType() == DomainTypes.DOMAIN_LAND
  end
  if condition == "naval" then
    return pUnit and pUnit:IsCombatUnit()
      and pUnit:GetDomainType() == DomainTypes.DOMAIN_SEA
  end
  if condition == "air" then
    return pUnit and pUnit:IsCombatUnit()
      and pUnit:GetDomainType() == DomainTypes.DOMAIN_AIR
  end
  if condition == "land_friendly" then
    return pUnit and pPlot and pUnit:GetDomainType() == DomainTypes.DOMAIN_LAND
      and pPlot:IsFriendlyTerritory(pUnit:GetOwner())
  end
  if condition == "naval_friendly" then
    return pUnit and pPlot and pUnit:GetDomainType() == DomainTypes.DOMAIN_SEA
      and pPlot:IsFriendlyTerritory(pUnit:GetOwner())
  end
  local landTerrainConditions = {{
    land_forest = {{ "feature", "FEATURE_FOREST" }},
    land_jungle = {{ "feature", "FEATURE_JUNGLE" }},
    land_marsh = {{ "feature", "FEATURE_MARSH" }},
    land_hill = {{ "hill", "" }},
    land_desert = {{ "terrain", "TERRAIN_DESERT" }},
    land_tundra = {{ "terrain", "TERRAIN_TUNDRA" }},
    land_snow = {{ "terrain", "TERRAIN_SNOW" }}
  }}
  local landCondition = landTerrainConditions[condition]
  if landCondition then
    if not pUnit or not pPlot or pUnit:GetDomainType() ~= DomainTypes.DOMAIN_LAND then
      return false
    end
    if landCondition[1] == "feature" then
      return pPlot:GetFeatureType() == GameInfoTypes[landCondition[2]]
    elseif landCondition[1] == "terrain" then
      return pPlot:GetTerrainType() == GameInfoTypes[landCondition[2]]
    end
    return pPlot:IsHills()
  end

  local unit = pUnit and GameInfo.Units[pUnit:GetUnitType()]
  if condition == "melee" then return unit and unit.CombatClass == "UNITCOMBAT_MELEE" end
  if condition == "ranged" then return unit and unit.CombatClass == "UNITCOMBAT_ARCHER" end
  if condition == "mounted" then
    return unit and (unit.CombatClass == "UNITCOMBAT_MOUNTED"
      or unit.CombatClass == "UNITCOMBAT_ARMOR")
  end
  if condition == "siege" then return unit and unit.CombatClass == "UNITCOMBAT_SIEGE" end
  if condition == "recon" then return unit and unit.CombatClass == "UNITCOMBAT_RECON" end
  if condition == "naval_ranged" then
    return unit and unit.CombatClass == "UNITCOMBAT_NAVALRANGED"
  end
  if condition == "fighter" then return unit and unit.CombatClass == "UNITCOMBAT_FIGHTER" end
  if condition == "bomber" then return unit and unit.CombatClass == "UNITCOMBAT_BOMBER" end
  if condition == "gunpowder" then return unit and unit.CombatClass == "UNITCOMBAT_GUN" end

  local iBuilding = context.building_type
  local building = iBuilding and GameInfo.Buildings[iBuilding]
  if condition == "wonder" then
    return building and (tonumber(building.MaxGlobalInstances) or -1) == 1
  end
  if condition == "defense_building" then
    return building and ((tonumber(building.Defense) or 0) > 0
      or (tonumber(building.ExtraCityHitPoints) or 0) > 0)
  end
  if condition == "culture_building" then
    return building and ((tonumber(building.Culture) or 0) > 0
      or (tonumber(building.SpecialistExtraCulture) or 0) > 0
      or {prefix}_BuildingHasYield(iBuilding, "YIELD_CULTURE"))
  end
  if condition == "science_building" then
    return building and (building.SpecialistType == "SPECIALIST_SCIENTIST"
      or {prefix}_BuildingHasYield(iBuilding, "YIELD_SCIENCE"))
  end
  if condition == "faith_building" then
    return building and {prefix}_BuildingHasYield(iBuilding, "YIELD_FAITH")
  end
  if condition == "military_building" then
    return building and ((tonumber(building.Experience) or 0) > 0
      or (tonumber(building.MilitaryProductionModifier) or 0) > 0)
  end
  if condition == "economic_building" then
    return building and ((tonumber(building.Gold) or 0) > 0
      or (tonumber(building.TradeRouteSeaGoldBonus) or 0) > 0
      or (tonumber(building.TradeRouteLandGoldBonus) or 0) > 0
      or building.SpecialistType == "SPECIALIST_MERCHANT"
      or {prefix}_BuildingHasYield(iBuilding, "YIELD_GOLD"))
  end
  if condition == "first_building" then return context.is_first_building == true end

  local improvementConditions = {{
    farm = "IMPROVEMENT_FARM", mine = "IMPROVEMENT_MINE",
    trading_post = "IMPROVEMENT_TRADING_POST",
    lumbermill = "IMPROVEMENT_LUMBERMILL", camp = "IMPROVEMENT_CAMP",
    pasture = "IMPROVEMENT_PASTURE", plantation = "IMPROVEMENT_PLANTATION",
    quarry = "IMPROVEMENT_QUARRY", fishing_boats = "IMPROVEMENT_FISHING_BOATS",
    oil_well = "IMPROVEMENT_WELL"
  }}
  if improvementConditions[condition] then
    if context.improvement_type ~= GameInfoTypes[improvementConditions[condition]] then
      return false
    end
    if condition == "fishing_boats" then
      return pCity
        and pCity:IsCoastal(GameDefines.MIN_WATER_SIZE_FOR_OCEAN or -1)
    end
    return true
  end

  if condition == "policy_branch" then
    local policy = context.policy_type and GameInfo.Policies[context.policy_type]
    return policy and policy.PolicyBranchType == conditionValue
  end
  if condition == "ideology" then
    local policy = context.policy_type and GameInfo.Policies[context.policy_type]
    return policy and (tonumber(policy.Level) or 0) > 0
  end
  if condition == "era" then
    local technology = context.tech_type and GameInfo.Technologies[context.tech_type]
    return technology and technology.Era == conditionValue
  end

  local greatPeople = {{
    scientist = "UNITCLASS_SCIENTIST", engineer = "UNITCLASS_ENGINEER",
    merchant = "UNITCLASS_MERCHANT", artist = "UNITCLASS_ARTIST",
    writer = "UNITCLASS_WRITER", musician = "UNITCLASS_MUSICIAN",
    general = "UNITCLASS_GREAT_GENERAL", admiral = "UNITCLASS_GREAT_ADMIRAL",
    prophet = "UNITCLASS_PROPHET"
  }}
  if greatPeople[condition] then
    local expendedUnit = context.unit_type and GameInfo.Units[context.unit_type]
    return expendedUnit and expendedUnit.Class == greatPeople[condition]
  end
  if condition == "barbarian" then return context.is_barbarian == true end
  if condition == "war_started" then
    return context.previous_war_count ~= nil
      and context.previous_war_count == 0 and warCount > 0
  end
  if condition == "peace_started" then
    return context.previous_war_count ~= nil
      and context.previous_war_count > 0 and warCount == 0
  end
  if condition == "peace_streak" then return context.peace_streak == threshold end
  if condition == "war_streak" then return context.war_streak == threshold end
  return false
end

local function {prefix}_GrantProduction(pCity, amount, preserveAsOverflow)
  local hasConcreteOrder = pCity:GetProductionUnit() ~= -1
    or pCity:GetProductionBuilding() ~= -1
    or pCity:GetProductionProject() ~= -1
    or pCity:GetProductionSpecialist() ~= -1
  if hasConcreteOrder and not preserveAsOverflow then
    pCity:ChangeProduction(amount)
  else
    pCity:SetOverflowProduction(pCity:GetOverflowProduction() + amount)
  end
end

local function {prefix}_GrantReward(effect, context)
  local amount = tonumber(effect.amount) or 0
  if amount <= 0 then return end
  local pPlayer = context.player
  local pCity = context.city
  local pUnit = context.unit
  if effect.scope == "capital" then
    pCity = pPlayer and pPlayer:GetCapitalCity()
  elseif effect.scope == "city" then
    pCity = context.city
  elseif effect.scope == "unit" then
    pUnit = context.unit
  end
  if effect.reward == "gold" and pPlayer then
    pPlayer:ChangeGold(amount)
  elseif effect.reward == "faith" and pPlayer then
    pPlayer:ChangeFaith(amount)
  elseif effect.reward == "culture" and pPlayer then
    pPlayer:ChangeJONSCulture(amount)
  elseif effect.reward == "golden_age" and pPlayer then
    pPlayer:ChangeGoldenAgeProgressMeter(amount)
  elseif effect.reward == "food" and pCity then
    pCity:ChangeFood(amount)
  elseif effect.reward == "production" and pCity then
    {prefix}_GrantProduction(
      pCity, amount, context.preserve_production_as_overflow == true
    )
  elseif effect.reward == "experience" and pUnit then
    pUnit:ChangeExperience(amount)
  elseif effect.reward == "heal" and pUnit then
    pUnit:ChangeDamage(-math.min(amount, pUnit:GetDamage()))
  end
end

local function {prefix}_RunRewardPrimitive(primitiveID, context)
  {prefix}_ForPrimitive(primitiveID, function(effect)
    if {prefix}_PassesCondition(effect, context) then
      {prefix}_GrantReward(effect, context)
    end
  end)
end

local function {prefix}_ProcessGoldenAgeEffects(pPlayer, playerID)
  {prefix}_ForPrimitive("golden_age_started_reward", function(effect)
    if not {prefix}_SaveData then return end
    local suffix = "golden_age:" .. playerID
    local previous = tonumber({prefix}_GetState(effect, suffix))
    local current = pPlayer:IsGoldenAge() and 1 or 0
    if previous ~= nil and previous == 0 and current == 1 then
      local context = {{ player = pPlayer, city = pPlayer:GetCapitalCity() }}
      if {prefix}_PassesCondition(effect, context) then
        {prefix}_GrantReward(effect, context)
      end
    end
    {prefix}_SetState(effect, suffix, current)
  end)
end

local function {prefix}_ProcessWarStateEffects(pPlayer, playerID)
  {prefix}_ForPrimitive("war_state_reward", function(effect)
    if not {prefix}_SaveData then return end
    local warCount = {prefix}_WarCount(pPlayer)
    local base = "war:" .. playerID .. ":"
    local previous = tonumber({prefix}_GetState(effect, base .. "count"))
    local peaceStreak = tonumber({prefix}_GetState(effect, base .. "peace_streak")) or 0
    local warStreak = tonumber({prefix}_GetState(effect, base .. "war_streak")) or 0
    if warCount == 0 then
      peaceStreak = peaceStreak + 1
      warStreak = 0
    else
      warStreak = warStreak + 1
      peaceStreak = 0
    end
    local context = {{
      player = pPlayer,
      city = pPlayer:GetCapitalCity(),
      war_count = warCount,
      previous_war_count = previous,
      peace_streak = peaceStreak,
      war_streak = warStreak
    }}
    local needsPrevious = effect.condition == "war_started"
      or effect.condition == "peace_started"
    if (not needsPrevious or previous ~= nil)
      and {prefix}_PassesCondition(effect, context) then
      {prefix}_GrantReward(effect, context)
    end
    {prefix}_SetState(effect, base .. "count", warCount)
    {prefix}_SetState(effect, base .. "peace_streak", peaceStreak)
    {prefix}_SetState(effect, base .. "war_streak", warStreak)
  end)
end

local function {prefix}_ProcessConnectionEffects(pPlayer, playerID)
  {prefix}_ForPrimitive("city_connection_reward", function(effect)
    if not {prefix}_SaveData then return end
    local initializedKey = "connection:" .. playerID .. ":initialized"
    local initialized = {prefix}_GetState(effect, initializedKey) ~= nil
    for pCity in pPlayer:Cities() do
      if not pCity:IsCapital() and pPlayer:IsCapitalConnectedToCity(pCity) then
        local cityKey = "connection:" .. playerID .. ":"
          .. pCity:GetX() .. ":" .. pCity:GetY() .. ":"
          .. pCity:GetGameTurnFounded()
        local alreadyRewarded = {prefix}_GetState(effect, cityKey) ~= nil
        if initialized and not alreadyRewarded then
          local cityContext = {{
            player = pPlayer, city = pCity, plot = pCity:Plot()
          }}
          if {prefix}_PassesCondition(effect, cityContext) then
            {prefix}_GrantReward(effect, cityContext)
          end
        end
        {prefix}_SetState(effect, cityKey, 1)
      end
    end
    if not initialized then {prefix}_SetState(effect, initializedKey, 1) end
  end)
end

local function {prefix}_OnPlayerDoTurn(playerID)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  {prefix}_ProcessGoldenAgeEffects(pPlayer, playerID)
  {prefix}_ProcessWarStateEffects(pPlayer, playerID)
  {prefix}_ProcessConnectionEffects(pPlayer, playerID)
  local context = {{ player = pPlayer, city = pPlayer:GetCapitalCity() }}
  {prefix}_RunRewardPrimitive("player_turn_reward", context)
  {prefix}_ForPrimitive("unit_heal_turn", function(effect)
    for pUnit in pPlayer:Units() do
      if pUnit:GetDamage() > 0 then
        local unitContext = {{ player = pPlayer, unit = pUnit, plot = pUnit:GetPlot() }}
        if {prefix}_PassesCondition(effect, unitContext) then
          {prefix}_GrantReward(effect, unitContext)
        end
      end
    end
  end)
end

local function {prefix}_OnPlayerCityFounded(playerID, plotX, plotY)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local pPlot = Map.GetPlot(plotX, plotY)
  local pCity = pPlot and pPlot:GetPlotCity()
  if not pCity or pCity:GetOwner() ~= playerID then return end
  {prefix}_RunRewardPrimitive(
    "city_founded_reward", {{ player = pPlayer, city = pCity, plot = pPlot }}
  )
end

local function {prefix}_OnCityCaptureComplete(
  oldOwnerID, isCapital, plotX, plotY, newOwnerID,
  oldPopulation, isConquest, greatWorkCount, capturedGreatWorks
)
  if isConquest ~= true or oldOwnerID == newOwnerID then return end
  local pPlayer = Players[newOwnerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local pPlot = Map.GetPlot(plotX, plotY)
  local pCity = pPlot and pPlot:GetPlotCity()
  if not pCity or pCity:GetOwner() ~= newOwnerID then return end
  {prefix}_ForPrimitive("city_captured_reward", function(effect)
    local context = {{
      player = pPlayer,
      city = pCity,
      plot = pPlot,
      old_owner = oldOwnerID,
      new_owner = newOwnerID,
      old_population = oldPopulation,
      population = oldPopulation,
      is_conquest = isConquest
    }}
    if {prefix}_PassesCondition(effect, context) then
      {prefix}_GrantReward(effect, context)
    end
  end)
end

local function {prefix}_OnCityTrained(playerID, cityID, unitID, isGold, isFaith)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local pCity = pPlayer:GetCityByID(cityID)
  local pUnit = pPlayer:GetUnitByID(unitID)
  if not pCity or not pUnit then return end
  local context = {{
    player = pPlayer,
    city = pCity,
    unit = pUnit,
    plot = pCity:Plot(),
    preserve_production_as_overflow = true
  }}
  {prefix}_RunRewardPrimitive("unit_trained_reward", context)
  {prefix}_ForPrimitive("unit_promotion_on_train", function(effect)
    if {prefix}_PassesCondition(effect, context) then
      local iPromotion = effect.promotion and GameInfoTypes[effect.promotion]
      if iPromotion then pUnit:SetHasPromotion(iPromotion, true) end
    end
  end)
end

local function {prefix}_OnCityConstructed(playerID, cityID, buildingType, isGold, isFaith)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local pCity = pPlayer:GetCityByID(cityID)
  if not pCity then return end
  {prefix}_ForPrimitive("building_completed_reward", function(effect)
    local isFirstBuilding = false
    if effect.condition == "first_building" then
      if not {prefix}_SaveData then return end
      local suffix = "first_building:" .. playerID .. ":"
        .. pCity:GetX() .. ":" .. pCity:GetY() .. ":"
        .. pCity:GetGameTurnFounded()
      isFirstBuilding = {prefix}_GetState(effect, suffix) == nil
      {prefix}_SetState(effect, suffix, 1)
    end
    local context = {{
      player = pPlayer,
      city = pCity,
      plot = pCity:Plot(),
      building_type = buildingType,
      is_first_building = isFirstBuilding,
      preserve_production_as_overflow = true
    }}
    if {prefix}_PassesCondition(effect, context) then
      {prefix}_GrantReward(effect, context)
    end
  end)
end

local function {prefix}_OnBuildFinished(playerID, plotX, plotY, improvementType)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local pPlot = Map.GetPlot(plotX, plotY)
  if not pPlot then return end
  local pCity = pPlot:GetWorkingCity()
  if pCity and pCity:GetOwner() ~= playerID then pCity = nil end
  {prefix}_RunRewardPrimitive("improvement_completed_reward", {{
    player = pPlayer, city = pCity, plot = pPlot, improvement_type = improvementType
  }})
end

local function {prefix}_OnPlayerAdoptPolicy(playerID, policyID)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  {prefix}_RunRewardPrimitive("policy_adopted_reward", {{
    player = pPlayer, city = pPlayer:GetCapitalCity(), policy_type = policyID
  }})
end

local function {prefix}_OnTeamTechResearched(teamID, techID, change)
  if not change or change <= 0 then return end
  local maxMajor = GameDefines.MAX_MAJOR_CIVS or 22
  for playerID = 0, maxMajor - 1 do
    local pPlayer = Players[playerID]
    if {prefix}_IsOurPlayer(pPlayer) and pPlayer:GetTeam() == teamID then
      {prefix}_RunRewardPrimitive("tech_researched_reward", {{
        player = pPlayer, city = pPlayer:GetCapitalCity(), tech_type = techID
      }})
    end
  end
end

local function {prefix}_OnGreatPersonExpended(playerID, unitID, unitType, plotX, plotY)
  local pPlayer = Players[playerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local resolvedUnitType = unitType or unitID
  local pPlot = plotX and plotY and Map.GetPlot(plotX, plotY)
  local pCity = pPlot and pPlot:GetWorkingCity() or pPlayer:GetCapitalCity()
  {prefix}_RunRewardPrimitive("great_person_expended_reward", {{
    player = pPlayer, city = pCity, plot = pPlot, unit_type = resolvedUnitType
  }})
end

local function {prefix}_OnSetPopulation(plotX, plotY, oldPopulation, newPopulation)
  if oldPopulation <= 0 or newPopulation <= oldPopulation then return end
  local pPlot = Map.GetPlot(plotX, plotY)
  local pCity = pPlot and pPlot:GetPlotCity()
  if not pCity then return end
  local pPlayer = Players[pCity:GetOwner()]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  {prefix}_RunRewardPrimitive("city_growth_reward", {{
    player = pPlayer, city = pCity, plot = pPlot
  }})
end

local function {prefix}_OnUnitPrekill(
  killedPlayerID, killedUnitID, killedUnitType, plotX, plotY, isDelay, killerPlayerID
)
  if not killerPlayerID or killerPlayerID == -1
    or killedPlayerID == killerPlayerID then return end
  local pPlayer = Players[killerPlayerID]
  if not {prefix}_IsOurPlayer(pPlayer) then return end
  local killedPlayer = Players[killedPlayerID]
  local killedUnit = killedPlayer and killedPlayer:GetUnitByID(killedUnitID)
  local pPlot = Map.GetPlot(plotX, plotY)
  {prefix}_RunRewardPrimitive("unit_kill_reward", {{
    player = pPlayer, city = pPlayer:GetCapitalCity(), unit = killedUnit,
    plot = pPlot, unit_type = killedUnitType,
    is_barbarian = killedPlayer and killedPlayer:IsBarbarian() or false
  }})
end

{event_registrations}
'''
