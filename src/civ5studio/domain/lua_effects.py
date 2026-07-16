"""Versioned, pure-BNW Lua effect catalog for civilization-level recipes.

The catalog is deliberately data-like Python rather than executable user code.
Every entry resolves to one of a small set of compiler-owned primitives, so a
project can remain portable without embedding arbitrary Lua in its JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Mapping


LUA_EFFECT_CATALOG_VERSION = 1
LUA_EFFECT_LIMIT = 2


class LuaEffectOrigin(str, Enum):
    """Where the design idea came from; no third-party code is copied."""

    ARCHIVE_INSPIRED = "archive_inspired"
    STUDIO_ORIGINAL = "studio_original"


class LuaParameterKind(str, Enum):
    INTEGER = "integer"
    BOOLEAN = "boolean"
    CHOICE = "choice"


LuaScalar = str | int | bool


@dataclass(frozen=True, slots=True)
class LuaEffectParameter:
    key: str
    label: str
    kind: LuaParameterKind
    default: LuaScalar
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True, slots=True)
class LuaEffectDefinition:
    effect_id: str
    version: int
    label: str
    category: str
    description: str
    primitive_id: str
    trigger: str
    runtime_config: Mapping[str, LuaScalar]
    parameters: tuple[LuaEffectParameter, ...]
    origin: LuaEffectOrigin
    inspiration: str
    tags: frozenset[str] = frozenset()
    incompatible_tags: frozenset[str] = frozenset()
    pure_bnw: bool = True
    supports_multiplayer: bool = False
    supports_hotseat: bool = False
    runtime_notes: str = ""

    def parameter_defaults(self) -> dict[str, LuaScalar]:
        return {parameter.key: parameter.default for parameter in self.parameters}

    def resolved_parameters(
        self, overrides: Mapping[str, object] | None = None
    ) -> dict[str, LuaScalar]:
        """Merge declared defaults with overrides without accepting new keys."""

        result = self.parameter_defaults()
        if overrides:
            for key, value in overrides.items():
                if key in result:
                    result[key] = value  # validation owns type/range reporting
        return result


@dataclass(frozen=True, slots=True)
class _Seed:
    slug: str
    label: str
    description: str
    reward: str = ""
    amount: int = 0
    condition: str = "always"
    condition_value: LuaScalar | None = None
    scope: str = "player"
    extra: tuple[tuple[str, LuaScalar], ...] = ()


@dataclass(frozen=True, slots=True)
class _Family:
    category: str
    primitive_id: str
    trigger: str
    origin: LuaEffectOrigin
    inspiration: str
    seeds: tuple[_Seed, ...]
    tags: frozenset[str] = frozenset()
    incompatible_tags: frozenset[str] = frozenset()
    runtime_notes: str = "Uses a guarded pure-BNW gameplay event handler."


def _s(
    slug: str,
    label: str,
    description: str,
    reward: str = "",
    amount: int = 0,
    condition: str = "always",
    condition_value: LuaScalar | None = None,
    scope: str = "player",
    **extra: LuaScalar,
) -> _Seed:
    return _Seed(
        slug,
        label,
        description,
        reward,
        amount,
        condition,
        condition_value,
        scope,
        tuple(sorted(extra.items())),
    )


_ARCHIVE = LuaEffectOrigin.ARCHIVE_INSPIRED
_ORIGINAL = LuaEffectOrigin.STUDIO_ORIGINAL


_FAMILIES: tuple[_Family, ...] = (
    _Family(
        "Economy & State",
        "player_turn_reward",
        "GameEvents.PlayerDoTurn",
        _ARCHIVE,
        "Normalized from recurring treasury, happiness, war, and faith patterns found in the read-only mod archives.",
        (
            _s("empty_coffers_relief", "Empty Coffers Relief", "While the treasury is below 100 Gold, gain 12 Gold each turn.", "gold", 12, "treasury_below", 100),
            _s("war_bond_levy", "War Bond Levy", "While at war, gain 8 Gold each turn.", "gold", 8, "at_war"),
            _s("peace_dividend", "Peace Dividend", "While at peace, gain 5 Culture each turn.", "culture", 5, "at_peace"),
            _s("golden_age_tithe", "Golden Age Tithe", "During a Golden Age, gain 6 Faith each turn.", "faith", 6, "golden_age"),
            _s("contented_momentum", "Contented Momentum", "With positive Happiness, add 5 Golden Age points each turn.", "golden_age", 5, "positive_happiness"),
            _s("hardship_devotion", "Hardship Devotion", "While Unhappy, gain 5 Faith each turn.", "faith", 5, "unhappy"),
            _s("merchant_surplus", "Merchant Surplus", "At 500 or more Gold, convert prosperity into 4 Culture each turn.", "culture", 4, "treasury_above", 500),
            _s("wartime_devotion", "Wartime Devotion", "While at war, gain 4 Faith each turn.", "faith", 4, "at_war"),
            _s("peaceful_reserves", "Peaceful Reserves", "While at peace, add 4 Golden Age points each turn.", "golden_age", 4, "at_peace"),
            _s("steady_heritage", "Steady Heritage", "Gain 2 Culture every turn without an additional condition.", "culture", 2),
        ),
    ),
    _Family(
        "Settlement",
        "city_founded_reward",
        "GameEvents.PlayerCityFounded",
        _ARCHIVE,
        "Rebuilt from archived city-founding, terrain-count, and expansion reward concepts.",
        (
            _s("river_granary_grant", "River Granary Grant", "Founding beside a river grants 35 Food to the new city.", "food", 35, "river", scope="city"),
            _s("coastal_trade_chest", "Coastal Trade Chest", "Founding on the coast grants 120 Gold.", "gold", 120, "coastal"),
            _s("hill_foundry_stores", "Hill Foundry Stores", "Founding on a hill grants 45 Production to the new city.", "production", 45, "hill", scope="city"),
            _s("forest_memory", "Forest Memory", "Founding beside a Forest grants 60 Culture.", "culture", 60, "adjacent_forest"),
            _s("jungle_shrine", "Jungle Shrine", "Founding beside a Jungle grants 70 Faith.", "faith", 70, "adjacent_jungle"),
            _s("desert_pilgrimage", "Desert Pilgrimage", "A desert settlement grants 85 Faith.", "faith", 85, "desert"),
            _s("tundra_work_camp", "Tundra Work Camp", "A tundra settlement gains 55 Production.", "production", 55, "tundra", scope="city"),
            _s("snowbound_resolve", "Snowbound Resolve", "A snow settlement adds 100 Golden Age points.", "golden_age", 100, "snow"),
            _s("marshland_provisions", "Marshland Provisions", "Founding beside a Marsh grants 50 Food to the new city.", "food", 50, "adjacent_marsh", scope="city"),
            _s("resource_frontier_claim", "Resource Frontier Claim", "Founding on or beside a revealed resource grants 140 Gold.", "gold", 140, "resource"),
        ),
    ),
    _Family(
        "Conquest",
        "city_captured_reward",
        "GameEvents.CityCaptureComplete",
        _ARCHIVE,
        "Normalized from archived conquest plunder and production-momentum ideas; post-capture puppet and raze choices are intentionally excluded.",
        (
            _s("victory_coffers", "Victory Coffers", "Capturing an enemy city grants 180 Gold.", "gold", 180),
            _s("annals_of_conquest", "Annals of Conquest", "Capturing an enemy city grants 90 Culture.", "culture", 90),
            _s("consecrated_victory", "Consecrated Victory", "Capturing an enemy city grants 100 Faith.", "faith", 100),
            _s("triumphal_procession", "Triumphal Procession", "Capturing an enemy city adds 125 Golden Age points.", "golden_age", 125),
            _s("coastal_prize_office", "Coastal Prize Office", "Capturing a coastal city grants 150 Gold.", "gold", 150, "coastal"),
            _s("hill_fortress_work_crews", "Hill Fortress Work Crews", "A captured hill city receives 70 Production.", "production", 70, "hill", scope="city"),
            _s("river_salvage_levy", "River Salvage Levy", "Capturing a river city grants 200 Gold.", "gold", 200, "river"),
            _s("captured_grain_stores", "Captured Grain Stores", "A captured city immediately receives 60 Food.", "food", 60, scope="city"),
            _s("capital_victory_forge", "Capital Victory Forge", "Each city capture grants 55 Production in the capital.", "production", 55, scope="capital"),
            _s("restoration_renown", "Restoration Renown", "Capturing a city whose original owner differs from both the conqueror and prior owner grants 140 Culture.", "culture", 140, "restoration_candidate"),
        ),
    ),
    _Family(
        "Military Training",
        "unit_trained_reward",
        "GameEvents.CityTrained",
        _ARCHIVE,
        "Reimplemented from archived new-unit reward, temporary morale, and experience mechanics.",
        (
            _s("veteran_muster", "Veteran Muster", "New military units begin with 12 Experience.", "experience", 12, "military", scope="unit"),
            _s("civil_service_apprenticeship", "Civil Service Apprenticeship", "New civilian units grant 25 Culture.", "culture", 25, "civilian"),
            _s("land_army_bounty", "Land Army Bounty", "Training or purchasing a land military unit grants 35 Gold.", "gold", 35, "land_military"),
            _s("fleet_sponsorship", "Fleet Sponsorship", "Training or purchasing a naval military unit grants 50 Gold.", "gold", 50, "naval"),
            _s("air_corps_fund", "Air Corps Fund", "Training or purchasing an air unit grants 60 Production to its city.", "production", 60, "air", scope="city"),
            _s("melee_oath", "Melee Oath", "Training or purchasing a melee unit grants 30 Faith.", "faith", 30, "melee"),
            _s("ranged_drill", "Ranged Drill", "New ranged units begin with 10 Experience.", "experience", 10, "ranged", scope="unit"),
            _s("cavalry_pageant", "Cavalry Pageant", "Training or purchasing a mounted or armored unit adds 45 Golden Age points.", "golden_age", 45, "mounted"),
            _s("siege_workshops", "Siege Workshops", "Training or purchasing a siege unit refunds 45 Production to its city.", "production", 45, "siege", scope="city"),
            _s("scout_storytellers", "Scout Storytellers", "Training or purchasing a recon unit grants 35 Culture.", "culture", 35, "recon"),
        ),
        runtime_notes=(
            "CityTrained includes production completions and Gold or Faith purchases; "
            "free, spawned, and upgraded units do not trigger it."
        ),
    ),
    _Family(
        "Infrastructure",
        "building_completed_reward",
        "GameEvents.CityConstructed",
        _ARCHIVE,
        "Rebuilt from archived construction rewards, defensive auras, and policy-production feedback loops.",
        (
            _s("builders_rebate", "Builder's Rebate", "Completing or purchasing any building grants 20 Gold.", "gold", 20),
            _s("monumental_memory", "Monumental Memory", "Completing or purchasing a Culture building grants 35 Culture.", "culture", 35, "culture_building"),
            _s("temple_alms", "Temple Alms", "Completing or purchasing a Faith building grants 40 Faith.", "faith", 40, "faith_building"),
            _s("academy_endowment", "Academy Endowment", "Completing or purchasing a Science building grants 45 Culture.", "culture", 45, "science_building"),
            _s("garrison_foundation", "Garrison Foundation", "Completing or purchasing a defensive building grants 50 Production to its city.", "production", 50, "defense_building", scope="city"),
            _s("arsenal_subscription", "Arsenal Subscription", "Completing or purchasing a military building grants 55 Gold.", "gold", 55, "military_building"),
            _s("market_festival", "Market Festival", "Completing or purchasing an economic building adds 40 Golden Age points.", "golden_age", 40, "economic_building"),
            _s("wonder_celebration", "Wonder Celebration", "Completing or purchasing a World Wonder grants 120 Culture.", "culture", 120, "wonder"),
            _s("capital_masons", "Capital Masons", "Completing or purchasing a building in the capital refunds 30 Production there.", "production", 30, "capital", scope="capital"),
            _s("provincial_feast", "Provincial Feast", "Completing or purchasing a building outside the capital adds 25 Food to that city.", "food", 25, "noncapital", scope="city"),
        ),
        runtime_notes=(
            "CityConstructed includes production completions and Gold or Faith "
            "building purchases."
        ),
    ),
    _Family(
        "Improvements & Resources",
        "improvement_completed_reward",
        "GameEvents.BuildFinished",
        _ARCHIVE,
        "Normalized from archived improvement-completion rewards and resource-development traits.",
        (
            _s("harvest_festival", "Harvest Festival", "Completing a Farm assigned to a city grants 20 Food to that working city.", "food", 20, "farm", scope="city"),
            _s("miners_dividend", "Miner's Dividend", "Completing a Mine grants 35 Gold.", "gold", 35, "mine"),
            _s("merchant_post_charter", "Merchant Post Charter", "Completing a Trading Post grants 30 Gold.", "gold", 30, "trading_post"),
            _s("lumber_canticle", "Lumber Canticle", "Completing a Lumber Mill grants 25 Culture.", "culture", 25, "lumbermill"),
            _s("hunters_offering", "Hunter's Offering", "Completing a Camp grants 30 Faith.", "faith", 30, "camp"),
            _s("pastoral_fair", "Pastoral Fair", "Completing a Pasture adds 30 Golden Age points.", "golden_age", 30, "pasture"),
            _s("plantation_advance", "Plantation Advance", "Completing a Plantation grants 30 Culture.", "culture", 30, "plantation"),
            _s("quarry_masons", "Quarry Masons", "Completing a Quarry assigned to a city grants 35 Production to that working city.", "production", 35, "quarry", scope="city"),
            _s("fishing_fleet_blessing", "Fishing Fleet Blessing", "Completing Fishing Boats assigned to a coastal city grants 35 Food to that working city.", "food", 35, "fishing_boats", scope="city"),
            _s("oilfield_concession", "Oilfield Concession", "Completing an Oil Well grants 100 Gold.", "gold", 100, "oil_well"),
        ),
        runtime_notes="City-scoped rewards require a working city and fail closed on unassigned plots.",
    ),
    _Family(
        "Policies",
        "policy_adopted_reward",
        "GameEvents.PlayerAdoptPolicy",
        _ARCHIVE,
        "Reworked from archived policy-adoption production, culture, and territorial-momentum effects.",
        (
            _s("tradition_legacy", "Tradition Legacy", "Adopting a Tradition policy grants 70 Culture.", "culture", 70, "policy_branch", "POLICY_BRANCH_TRADITION"),
            _s("liberty_homestead", "Liberty Homestead", "Adopting a Liberty policy grants 60 Production in the capital.", "production", 60, "policy_branch", "POLICY_BRANCH_LIBERTY", "capital"),
            _s("honor_warchest", "Honor Warchest", "Adopting an Honor policy grants 100 Gold.", "gold", 100, "policy_branch", "POLICY_BRANCH_HONOR"),
            _s("piety_devotion", "Piety Devotion", "Adopting a Piety policy grants 90 Faith.", "faith", 90, "policy_branch", "POLICY_BRANCH_PIETY"),
            _s("patronage_ceremony", "Patronage Ceremony", "Adopting a Patronage policy adds 80 Golden Age points.", "golden_age", 80, "policy_branch", "POLICY_BRANCH_PATRONAGE"),
            _s("aesthetics_salon", "Aesthetics Salon", "Adopting an Aesthetics policy grants 100 Culture.", "culture", 100, "policy_branch", "POLICY_BRANCH_AESTHETICS"),
            _s("commerce_reserve", "Commerce Reserve", "Adopting a Commerce policy grants 150 Gold.", "gold", 150, "policy_branch", "POLICY_BRANCH_COMMERCE"),
            _s("exploration_stores", "Exploration Stores", "Adopting an Exploration policy grants 70 Production in the capital.", "production", 70, "policy_branch", "POLICY_BRANCH_EXPLORATION", "capital"),
            _s("rationalism_archive", "Rationalism Archive", "Adopting a Rationalism policy grants 110 Culture.", "culture", 110, "policy_branch", "POLICY_BRANCH_RATIONALISM"),
            _s("ideological_rally", "Ideological Rally", "Adopting a Freedom, Order, or Autocracy tenet adds 160 Golden Age points.", "golden_age", 160, "ideology"),
        ),
    ),
    _Family(
        "Technology",
        "tech_researched_reward",
        "GameEvents.TeamTechResearched",
        _ARCHIVE,
        "Normalized from archived technology rewards and era-transition dividends.",
        (
            _s("ancient_lore", "Ancient Lore", "Researching an Ancient technology grants 25 Culture.", "culture", 25, "era", "ERA_ANCIENT"),
            _s("classical_patronage", "Classical Patronage", "Researching a Classical technology grants 45 Gold.", "gold", 45, "era", "ERA_CLASSICAL"),
            _s("medieval_scriptoria", "Medieval Scriptoria", "Researching a Medieval technology grants 50 Faith.", "faith", 50, "era", "ERA_MEDIEVAL"),
            _s("renaissance_workshops", "Renaissance Workshops", "Researching a Renaissance technology grants 45 Production in the capital.", "production", 45, "era", "ERA_RENAISSANCE", "capital"),
            _s("industrial_investment", "Industrial Investment", "Researching an Industrial technology grants 90 Gold.", "gold", 90, "era", "ERA_INDUSTRIAL"),
            _s("modern_optimism", "Modern Optimism", "Researching a Modern technology adds 75 Golden Age points.", "golden_age", 75, "era", "ERA_MODERN"),
            _s("atomic_reflection", "Atomic Reflection", "Researching an Atomic technology grants 80 Culture.", "culture", 80, "era", "ERA_POSTMODERN"),
            _s("information_endowment", "Information Endowment", "Researching an Information technology grants 120 Gold.", "gold", 120, "era", "ERA_FUTURE"),
            _s("inventors_tithe", "Inventor's Tithe", "Researching any technology grants 20 Faith.", "faith", 20),
            _s("public_discovery", "Public Discovery", "Researching any technology grants 20 Culture.", "culture", 20),
        ),
    ),
    _Family(
        "Great People",
        "great_person_expended_reward",
        "GameEvents.GreatPersonExpended",
        _ARCHIVE,
        "Rebuilt from archived Great Person expenditure, Great Work, and city-boom mechanics.",
        (
            _s("scientists_legacy", "Scientist's Legacy", "Expending a Great Scientist grants 140 Culture.", "culture", 140, "scientist"),
            _s("engineers_reserve", "Engineer's Reserve", "Expending a Great Engineer grants 100 Production in the capital.", "production", 100, "engineer", scope="capital"),
            _s("merchants_bequest", "Merchant's Bequest", "Expending a Great Merchant grants 220 Gold.", "gold", 220, "merchant"),
            _s("artists_jubilee", "Artist's Jubilee", "Expending a Great Artist adds 180 Golden Age points.", "golden_age", 180, "artist"),
            _s("writers_testament", "Writer's Testament", "Expending a Great Writer grants 150 Culture.", "culture", 150, "writer"),
            _s("musicians_offering", "Musician's Offering", "Expending a Great Musician grants 130 Faith.", "faith", 130, "musician"),
            _s("generals_spoils", "General's Spoils", "Expending a Great General grants 180 Gold.", "gold", 180, "general"),
            _s("admirals_harbor_fund", "Admiral's Harbor Fund", "Expending a Great Admiral grants 90 Production in the capital.", "production", 90, "admiral", scope="capital"),
            _s("prophets_revelation", "Prophet's Revelation", "Expending a Great Prophet grants 180 Faith.", "faith", 180, "prophet"),
            _s("great_legacy", "Great Legacy", "Expending any Great Person grants 80 Culture.", "culture", 80),
        ),
    ),
    _Family(
        "Combat Victories",
        "unit_kill_reward",
        "GameEvents.UnitPrekill",
        _ARCHIVE,
        "Normalized from archived post-kill economy, faith, culture, and barbarian reward systems.",
        (
            _s("spoils_of_battle", "Spoils of Battle", "Defeating an enemy military unit grants 25 Gold.", "gold", 25, "military"),
            _s("songs_of_victory", "Songs of Victory", "Defeating an enemy military unit grants 15 Culture.", "culture", 15, "military"),
            _s("martyrs_vow", "Martyr's Vow", "Defeating an enemy military unit grants 15 Faith.", "faith", 15, "military"),
            _s("barbarian_bounty", "Barbarian Bounty", "Defeating a Barbarian unit grants 40 Gold.", "gold", 40, "barbarian"),
            _s("naval_prize_money", "Naval Prize Money", "Sinking a naval unit grants 50 Gold.", "gold", 50, "naval"),
            _s("air_ace_renown", "Air Ace Renown", "Destroying an air unit grants 35 Culture.", "culture", 35, "air"),
            _s("cavalry_trophies", "Cavalry Trophies", "Defeating a mounted or armored unit adds 30 Golden Age points.", "golden_age", 30, "mounted"),
            _s("siege_breakers", "Siege Breakers", "Defeating a siege unit grants 30 Production in the capital.", "production", 30, "siege", scope="capital"),
            _s("ranged_hunters", "Ranged Hunters", "Defeating a ranged unit grants 20 Culture.", "culture", 20, "ranged"),
            _s("gunpowder_trophies", "Gunpowder Trophies", "Defeating a gunpowder unit grants 45 Culture.", "culture", 45, "gunpowder"),
        ),
    ),
    _Family(
        "Strategic Statecraft",
        "player_turn_reward",
        "GameEvents.PlayerDoTurn",
        _ORIGINAL,
        "Civilization Studio original: bounded strategic-state dividends designed for the shared turn dispatcher.",
        (
            _s("lean_empire_ledger", "Lean Empire Ledger", "With three or fewer cities, gain 6 Gold each turn.", "gold", 6, "city_count_at_most", 3),
            _s("wide_empire_chorus", "Wide Empire Chorus", "With eight or more cities, gain 5 Culture each turn.", "culture", 5, "city_count_at_least", 8),
            _s("capital_in_harmony", "Capital in Harmony", "With positive Happiness and an owned capital, add 4 Golden Age points each turn.", "golden_age", 4, "happy_capital"),
            _s("frontier_war_fund", "Frontier War Fund", "At war with at least two rivals, gain 12 Gold each turn.", "gold", 12, "multiple_wars", 2),
            _s("single_city_devotion", "Single-City Devotion", "While controlling exactly one city, gain 7 Faith each turn.", "faith", 7, "city_count_equals", 1),
            _s("recovery_budget", "Recovery Budget", "Below -5 Happiness, gain 8 Gold each turn.", "gold", 8, "happiness_below", -5),
            _s("prosperity_archive", "Prosperity Archive", "At 1,000 or more Gold, gain 6 Culture each turn.", "culture", 6, "treasury_above", 1000),
            _s("peacetime_pilgrims", "Peacetime Pilgrims", "At peace with positive Happiness, gain 5 Faith each turn.", "faith", 5, "peace_and_happy"),
            _s("wartime_remembrance", "Wartime Remembrance", "At war during a Golden Age, gain 7 Culture each turn.", "culture", 7, "war_and_golden_age"),
            _s("balanced_exchequer", "Balanced Exchequer", "Between 100 and 499 Gold, add 3 Golden Age points each turn.", "golden_age", 3, "treasury_band", "100:499"),
        ),
    ),
    _Family(
        "Founding Charters",
        "city_founded_reward",
        "GameEvents.PlayerCityFounded",
        _ORIGINAL,
        "Civilization Studio original: charter choices combine site context with player-, city-, and capital-level rewards.",
        (
            _s("river_market_charter", "River Market Charter", "A river settlement grants 100 Gold.", "gold", 100, "river"),
            _s("coastal_shipyard_charter", "Coastal Shipyard Charter", "A coastal settlement gains 50 Production.", "production", 50, "coastal", scope="city"),
            _s("hill_citadel_charter", "Hill Citadel Charter", "A hill settlement grants 70 Culture.", "culture", 70, "hill"),
            _s("forest_commons_charter", "Forest Commons Charter", "Founding beside a Forest grants 45 Food to the new city.", "food", 45, "adjacent_forest", scope="city"),
            _s("jungle_apothecary_charter", "Jungle Apothecary Charter", "Founding beside a Jungle adds 80 Golden Age points.", "golden_age", 80, "adjacent_jungle"),
            _s("desert_caravan_charter", "Desert Caravan Charter", "A desert settlement grants 130 Gold.", "gold", 130, "desert"),
            _s("tundra_chapel_charter", "Tundra Chapel Charter", "A tundra settlement grants 75 Faith.", "faith", 75, "tundra"),
            _s("snow_research_charter", "Snow Resolve Charter", "A snow settlement grants 90 Culture for overcoming the frontier.", "culture", 90, "snow"),
            _s("marsh_reclamation_charter", "Marsh Reclamation Charter", "Founding beside a Marsh grants 65 Production to the new city.", "production", 65, "adjacent_marsh", scope="city"),
            _s("resource_crown_charter", "Resource Crown Charter", "A resource-rich settlement grants 60 Production in the capital.", "production", 60, "resource", scope="capital"),
        ),
    ),
    _Family(
        "Conquest Aftermath",
        "city_captured_reward",
        "GameEvents.CityCaptureComplete",
        _ORIGINAL,
        "Civilization Studio original: distinct capture aftermath packages without free-form Lua or hidden dependencies.",
        (
            _s("restoration_decree", "Restoration Decree", "Capturing a city whose original owner differs from both the conqueror and prior owner grants 160 Faith.", "faith", 160, "restoration_candidate"),
            _s("hill_city_scribes", "Hill City Scribes", "Capturing a hill city grants 110 Culture.", "culture", 110, "hill"),
            _s("desert_city_rations", "Desert City Rations", "A captured desert city gains 80 Food.", "food", 80, "desert", scope="city"),
            _s("tundra_reconstruction", "Tundra Reconstruction", "Capturing a tundra city grants 75 Production in the capital.", "production", 75, "tundra", scope="capital"),
            _s("harbor_seizure", "Harbor Seizure", "Capturing a coastal city grants 220 Gold.", "gold", 220, "coastal"),
            _s("river_capitulation", "River Capitulation", "Capturing a river city grants 130 Culture.", "culture", 130, "river"),
            _s("holy_city_guardianship", "Holy City Guardianship", "Capturing a Holy City grants 200 Faith.", "faith", 200, "holy_city"),
            _s("capital_standard", "Capital Standard", "Capturing an original capital adds 220 Golden Age points.", "golden_age", 220, "original_capital"),
            _s("small_city_resettlement", "Small-City Resettlement", "Capturing a city of population 4 or less grants it 90 Food.", "food", 90, "population_at_most", 4, "city"),
            _s("great_city_tribute", "Great-City Tribute", "Capturing a city of population 12 or more grants 300 Gold.", "gold", 300, "population_at_least", 12),
        ),
    ),
    _Family(
        "Training Doctrines",
        "unit_promotion_on_train",
        "GameEvents.CityTrained",
        _ORIGINAL,
        "Civilization Studio original: guarded grants of verified vanilla BNW promotions by unit role.",
        (
            _s("amphibious_marine_doctrine", "Amphibious Marine Doctrine", "New melee units receive Amphibious.", condition="melee", scope="unit", promotion="PROMOTION_AMPHIBIOUS"),
            _s("ranged_accuracy_doctrine", "Ranged Accuracy Doctrine", "New ranged units receive Accuracy I.", condition="ranged", scope="unit", promotion="PROMOTION_ACCURACY_1"),
            _s("siege_barrage_doctrine", "Siege Barrage Doctrine", "New siege units receive Barrage I.", condition="siege", scope="unit", promotion="PROMOTION_BARRAGE_1"),
            _s("cavalry_charge_doctrine", "Cavalry Charge Doctrine", "New mounted or armored units receive Charge.", condition="mounted", scope="unit", promotion="PROMOTION_CHARGE"),
            _s("recon_scouting_doctrine", "Recon Scouting Doctrine", "New recon units receive Scouting I.", condition="recon", scope="unit", promotion="PROMOTION_SCOUTING_1"),
            _s("infantry_cover_doctrine", "Infantry Cover Doctrine", "New melee units receive Cover I.", condition="melee", scope="unit", promotion="PROMOTION_COVER_1"),
            _s("naval_targeting_doctrine", "Naval Targeting Doctrine", "New naval ranged units receive Targeting I.", condition="naval_ranged", scope="unit", promotion="PROMOTION_TARGETING_1"),
            _s("fighter_dogfighting_doctrine", "Fighter Dogfighting Doctrine", "New fighter units receive Dogfighting I.", condition="fighter", scope="unit", promotion="PROMOTION_DOGFIGHTING_1"),
            _s("bomber_siege_doctrine", "Bomber Siege Doctrine", "New bomber units receive Air Siege I.", condition="bomber", scope="unit", promotion="PROMOTION_AIR_SIEGE_1"),
            _s("gunpowder_march_doctrine", "Gunpowder March Doctrine", "New gunpowder units receive March.", condition="gunpowder", scope="unit", promotion="PROMOTION_MARCH"),
        ),
        runtime_notes=(
            "CityTrained includes production completions and Gold or Faith purchases; "
            "free, spawned, and upgraded units do not trigger it."
        ),
    ),
    _Family(
        "Civic Construction",
        "building_completed_reward",
        "GameEvents.CityConstructed",
        _ORIGINAL,
        "Civilization Studio original: category-specific civic dividends with explicit reward targets.",
        (
            _s("cultural_cornerstone", "Cultural Cornerstone", "A Culture building adds 35 Food to its city.", "food", 35, "culture_building", scope="city"),
            _s("scientific_open_house", "Scientific Open House", "A Science building grants 55 Culture.", "culture", 55, "science_building"),
            _s("faithful_work_crews", "Faithful Work Crews", "A Faith building adds 40 Production to its city.", "production", 40, "faith_building", scope="city"),
            _s("walls_subscription", "Walls Subscription", "A defensive building grants 65 Gold.", "gold", 65, "defense_building"),
            _s("barracks_homecoming", "Barracks Homecoming", "A military building adds 35 Food to its city.", "food", 35, "military_building", scope="city"),
            _s("market_public_works", "Market Public Works", "An economic building adds 45 Production to its city.", "production", 45, "economic_building", scope="city"),
            _s("wonder_pilgrimage", "Wonder Pilgrimage", "Completing or purchasing a World Wonder grants 140 Faith.", "faith", 140, "wonder"),
            _s("capital_blueprint_exchange", "Capital Blueprint Exchange", "A capital building grants 50 Production in the capital.", "production", 50, "capital", scope="capital"),
            _s("provincial_endowment", "Provincial Endowment", "A non-capital building grants 45 Gold.", "gold", 45, "noncapital"),
            _s("first_in_city_festival", "First-in-City Festival", "The first building completed or purchased after this effect begins tracking in a city adds 70 Golden Age points.", "golden_age", 70, "first_building"),
        ),
        runtime_notes=(
            "CityConstructed includes production completions and Gold or Faith "
            "building purchases."
        ),
    ),
    _Family(
        "Golden Ages",
        "golden_age_started_reward",
        "GameEvents.PlayerDoTurn (state transition)",
        _ORIGINAL,
        "Civilization Studio original: one-shot opening packages for a newly started Golden Age.",
        (
            _s("jubilee_treasury", "Jubilee Treasury", "First detecting a newly active Golden Age grants 250 Gold.", "gold", 250),
            _s("jubilee_annals", "Jubilee Annals", "First detecting a newly active Golden Age grants 140 Culture.", "culture", 140),
            _s("jubilee_devotion", "Jubilee Devotion", "First detecting a newly active Golden Age grants 140 Faith.", "faith", 140),
            _s("capital_illumination", "Capital Illumination", "First detecting a newly active Golden Age grants 100 Production in the capital.", "production", 100, scope="capital"),
            _s("capital_banquet", "Capital Banquet", "First detecting a newly active Golden Age grants 120 Food in the capital.", "food", 120, scope="capital"),
            _s("wartime_jubilee", "Wartime Jubilee", "First detecting a newly active Golden Age while at war grants 350 Gold.", "gold", 350, "at_war"),
            _s("peace_jubilee", "Peace Jubilee", "First detecting a newly active Golden Age while at peace grants 180 Culture.", "culture", 180, "at_peace"),
            _s("happy_jubilee", "Happy Jubilee", "First detecting a newly active Golden Age with positive Happiness grants 170 Faith.", "faith", 170, "positive_happiness"),
            _s("lean_empire_jubilee", "Lean-Empire Jubilee", "First detecting a newly active Golden Age with three or fewer cities grants 150 Production in the capital.", "production", 150, "city_count_at_most", 3, "capital"),
            _s("wide_empire_jubilee", "Wide-Empire Jubilee", "First detecting a newly active Golden Age with eight or more cities grants 220 Gold.", "gold", 220, "city_count_at_least", 8),
        ),
        runtime_notes=(
            "PlayerDoTurn detects the inactive-to-active transition once. Golden Ages "
            "started mid-turn are rewarded at the next player-turn check, and an "
            "already-active Golden Age establishes a no-reward baseline."
        ),
    ),
    _Family(
        "Population",
        "city_growth_reward",
        "GameEvents.SetPopulation",
        _ORIGINAL,
        "Civilization Studio original: deterministic rewards when an owned city gains population.",
        (
            _s("urban_tax_roll", "Urban Tax Roll", "Each population gain grants 20 Gold.", "gold", 20),
            _s("oral_history_circle", "Oral History Circle", "Each population gain grants 12 Culture.", "culture", 12),
            _s("parish_welcome", "Parish Welcome", "Each population gain grants 12 Faith.", "faith", 12),
            _s("growth_work_shift", "Growth Work Shift", "Each population gain adds 15 Production to that city.", "production", 15, scope="city"),
            _s("capital_migration_bureau", "Capital Migration Bureau", "Population growth outside the capital grants 12 Production in the capital.", "production", 12, "noncapital", scope="capital"),
            _s("river_population_fair", "River Population Fair", "Population growth in a river city adds 15 Golden Age points.", "golden_age", 15, "river"),
            _s("coastal_population_market", "Coastal Population Market", "Population growth in a coastal city grants 25 Gold.", "gold", 25, "coastal"),
            _s("small_city_nursery", "Small-City Nursery", "Growth to population 5 or less returns 18 Food to that city.", "food", 18, "population_at_most", 5, "city"),
            _s("metropolitan_arts_fund", "Metropolitan Arts Fund", "Growth to population 12 or more grants 25 Culture.", "culture", 25, "population_at_least", 12),
            _s("capital_growth_ceremony", "Capital Growth Ceremony", "Population growth in the capital grants 20 Faith.", "faith", 20, "capital"),
        ),
        runtime_notes=(
            "SetPopulation rewards positive changes from an established population. "
            "City founding and capture initialization from population zero are excluded."
        ),
    ),
    _Family(
        "City Connections",
        "city_connection_reward",
        "GameEvents.PlayerDoTurn",
        _ORIGINAL,
        "Civilization Studio original: state-tracked rewards for newly connected non-capital cities.",
        (
            _s("road_opening_toll", "Road-Opening Toll", "Connecting a city to the capital for the first time grants 90 Gold.", "gold", 90),
            _s("connected_traditions", "Connected Traditions", "A newly connected city grants 55 Culture.", "culture", 55),
            _s("pilgrimage_road", "Pilgrimage Road", "A newly connected city grants 60 Faith.", "faith", 60),
            _s("supply_line_opening", "Supply-Line Opening", "A newly connected city gains 45 Production.", "production", 45, scope="city"),
            _s("grain_convoy", "Grain Convoy", "A newly connected city gains 50 Food.", "food", 50, scope="city"),
            _s("river_road_festival", "River-Road Festival", "Connecting a river city adds 70 Golden Age points.", "golden_age", 70, "river"),
            _s("coastal_link_exchange", "Coastal Link Exchange", "Connecting a coastal city grants 110 Gold.", "gold", 110, "coastal"),
            _s("small_city_link_aid", "Small-City Link Aid", "Connecting a city of population 5 or less grants it 70 Food.", "food", 70, "population_at_most", 5, "city"),
            _s("metropolitan_link_arts", "Metropolitan Link Arts", "Connecting a city of population 12 or more grants 90 Culture.", "culture", 90, "population_at_least", 12),
            _s("frontier_link_fund", "Frontier Link Fund", "Connecting a city eight or more plots from the capital grants 140 Gold.", "gold", 140, "distance_at_least", 8),
        ),
        runtime_notes=(
            "Uses namespaced save data to reward each qualifying connection once. "
            "Connections already present on the first tracked turn establish the "
            "baseline without a reward."
        ),
    ),
    _Family(
        "War & Peace",
        "war_state_reward",
        "GameEvents.PlayerDoTurn",
        _ORIGINAL,
        "Civilization Studio original: state-transition rewards for declarations, peace, and multi-front pressure.",
        (
            _s("mobilization_chest", "Mobilization Chest", "Beginning the first tracked turn after moving from peace into war grants 180 Gold.", "gold", 180, "war_started"),
            _s("mobilization_hymn", "Mobilization Hymn", "Beginning the first tracked turn after moving from peace into war grants 100 Culture.", "culture", 100, "war_started"),
            _s("mobilization_prayer", "Mobilization Prayer", "Beginning the first tracked turn after moving from peace into war grants 110 Faith.", "faith", 110, "war_started"),
            _s("peace_conference", "Peace Conference", "Beginning the first tracked turn after ending all wars grants 130 Culture.", "culture", 130, "peace_started"),
            _s("demobilization_dividend", "Demobilization Dividend", "Beginning the first tracked turn after ending all wars grants 220 Gold.", "gold", 220, "peace_started"),
            _s("reconstruction_shift", "Reconstruction Shift", "Beginning the first tracked turn after ending all wars grants 100 Production in the capital.", "production", 100, "peace_started", scope="capital"),
            _s("two_front_reserve", "Two-Front Reserve", "Beginning a turn at war with two or more rivals grants 15 Gold.", "gold", 15, "multiple_wars", 2),
            _s("encircled_resolve", "Encircled Resolve", "Beginning a turn at war with three or more rivals adds 12 Golden Age points.", "golden_age", 12, "multiple_wars", 3),
            _s("long_peace_archive", "Long-Peace Archive", "Beginning a tenth consecutive tracked peaceful turn grants 100 Culture.", "culture", 100, "peace_streak", 10),
            _s("long_war_devotion", "Long-War Devotion", "Beginning a tenth consecutive tracked wartime turn grants 100 Faith.", "faith", 100, "war_streak", 10),
        ),
        runtime_notes=(
            "PlayerDoTurn polls war state. The first observation establishes the "
            "transition baseline and begins streak counting; rewards are not replayed "
            "after reload."
        ),
    ),
    _Family(
        "Unit Recovery",
        "unit_heal_turn",
        "GameEvents.PlayerDoTurn",
        _ORIGINAL,
        "Civilization Studio original: bounded turn-based healing by owned-unit context.",
        (
            _s("forest_field_medicine", "Forest Field Medicine", "Damaged land units in Forest heal 8 extra HP each turn.", "heal", 8, "land_forest", scope="unit"),
            _s("jungle_field_medicine", "Jungle Field Medicine", "Damaged land units in Jungle heal 8 extra HP each turn.", "heal", 8, "land_jungle", scope="unit"),
            _s("hill_sanatorium", "Hill Sanatorium", "Damaged land units on Hills heal 6 extra HP each turn.", "heal", 6, "land_hill", scope="unit"),
            _s("desert_survival_camps", "Desert Survival Camps", "Damaged land units in Desert heal 7 extra HP each turn.", "heal", 7, "land_desert", scope="unit"),
            _s("tundra_warming_tents", "Tundra Warming Tents", "Damaged land units in Tundra heal 7 extra HP each turn.", "heal", 7, "land_tundra", scope="unit"),
            _s("snow_rescue_patrols", "Snow Rescue Patrols", "Damaged land units on Snow heal 9 extra HP each turn.", "heal", 9, "land_snow", scope="unit"),
            _s("marsh_apothecaries", "Marsh Apothecaries", "Damaged land units in Marsh heal 8 extra HP each turn.", "heal", 8, "land_marsh", scope="unit"),
            _s("home_waters_repair", "Home Waters Repair", "Damaged naval units in friendly territory heal 7 extra HP each turn.", "heal", 7, "naval_friendly", scope="unit"),
            _s("friendly_soil_triage", "Friendly Soil Triage", "Damaged land units in friendly territory heal 5 extra HP each turn.", "heal", 5, "land_friendly", scope="unit"),
            _s("capital_guard_hospital", "Capital Guard Hospital", "Damaged units stationed in the capital heal 10 extra HP each turn.", "heal", 10, "capital", scope="unit"),
        ),
    ),
)


def _build_catalog() -> tuple[LuaEffectDefinition, ...]:
    definitions: list[LuaEffectDefinition] = []
    for family in _FAMILIES:
        if len(family.seeds) != 10:
            raise RuntimeError(
                f"Lua effect family {family.category!r} must contain exactly ten entries."
            )
        for seed in family.seeds:
            config: dict[str, LuaScalar] = {
                "condition": seed.condition,
                "scope": seed.scope,
            }
            if seed.reward:
                config["reward"] = seed.reward
            if seed.amount:
                config["amount"] = seed.amount
            if seed.condition_value is not None:
                config["condition_value"] = seed.condition_value
            config.update(seed.extra)

            parameters: list[LuaEffectParameter] = []
            if seed.amount:
                parameters.append(
                    LuaEffectParameter(
                        "amount",
                        "Reward amount",
                        LuaParameterKind.INTEGER,
                        seed.amount,
                        seed.amount,
                        seed.amount,
                        description=(
                            "Fixed at the curated v1 amount; the typed field is "
                            "reserved for a future tuning UI."
                        ),
                    )
                )
            definitions.append(
                LuaEffectDefinition(
                    effect_id=f"civ5studio.lua.v1.{seed.slug}",
                    version=LUA_EFFECT_CATALOG_VERSION,
                    label=seed.label,
                    category=family.category,
                    description=seed.description,
                    primitive_id=family.primitive_id,
                    trigger=family.trigger,
                    runtime_config=config,
                    parameters=tuple(parameters),
                    origin=family.origin,
                    inspiration=family.inspiration,
                    tags=family.tags,
                    incompatible_tags=family.incompatible_tags,
                    runtime_notes=family.runtime_notes,
                )
            )

    if len(definitions) != 200:
        raise RuntimeError(f"Expected 200 Lua effects, found {len(definitions)}.")
    ids = [definition.effect_id for definition in definitions]
    labels = [definition.label.casefold() for definition in definitions]
    if len(set(ids)) != len(ids):
        raise RuntimeError("Lua effect IDs must be unique.")
    if len(set(labels)) != len(labels):
        raise RuntimeError("Lua effect labels must be unique.")
    return tuple(definitions)


LUA_EFFECT_CATALOG: tuple[LuaEffectDefinition, ...] = _build_catalog()
LUA_EFFECTS_BY_ID: Mapping[str, LuaEffectDefinition] = {
    definition.effect_id: definition for definition in LUA_EFFECT_CATALOG
}


def iter_lua_effects(
    *,
    category: str | None = None,
    origin: LuaEffectOrigin | str | None = None,
) -> Iterator[LuaEffectDefinition]:
    """Iterate catalog entries in stable presentation order."""

    normalized_origin = LuaEffectOrigin(origin) if origin is not None else None
    for definition in LUA_EFFECT_CATALOG:
        if category is not None and definition.category != category:
            continue
        if normalized_origin is not None and definition.origin is not normalized_origin:
            continue
        yield definition


def lua_effect_by_id(effect_id: str) -> LuaEffectDefinition | None:
    return LUA_EFFECTS_BY_ID.get(effect_id)


def lua_effect_categories() -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.category for item in LUA_EFFECT_CATALOG))


def search_lua_effects(
    query: str = "", *, category: str | None = None
) -> tuple[LuaEffectDefinition, ...]:
    """Case-insensitive search over IDs, labels, descriptions, and categories."""

    words = tuple(word for word in query.casefold().split() if word)
    matches = []
    for definition in iter_lua_effects(category=category):
        haystack = " ".join(
            (
                definition.effect_id,
                definition.label,
                definition.category,
                definition.description,
                definition.trigger,
                definition.inspiration,
            )
        ).casefold()
        if all(word in haystack for word in words):
            matches.append(definition)
    return tuple(matches)


def _definition(
    value: LuaEffectDefinition | str,
) -> LuaEffectDefinition | None:
    if isinstance(value, LuaEffectDefinition):
        return value
    return lua_effect_by_id(value)


def lua_effects_compatible(
    first: LuaEffectDefinition | str,
    second: LuaEffectDefinition | str,
) -> bool:
    """Return whether two known, distinct effects may share a civilization."""

    left = _definition(first)
    right = _definition(second)
    if left is None or right is None or left.effect_id == right.effect_id:
        return False
    return not (
        left.incompatible_tags.intersection(right.tags)
        or right.incompatible_tags.intersection(left.tags)
    )


def validate_lua_parameters(
    definition: LuaEffectDefinition,
    parameters: Mapping[str, object],
) -> tuple[str, ...]:
    """Return stable human-readable errors for a selection's override values."""

    declared = {parameter.key: parameter for parameter in definition.parameters}
    errors: list[str] = []
    for key in sorted(parameters):
        if key not in declared:
            errors.append(f"Unknown parameter {key!r}.")
            continue
        parameter = declared[key]
        value = parameters[key]
        if parameter.kind is LuaParameterKind.INTEGER:
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append(f"Parameter {key!r} must be an integer.")
            elif parameter.minimum is not None and value < parameter.minimum:
                errors.append(f"Parameter {key!r} must be at least {parameter.minimum}.")
            elif parameter.maximum is not None and value > parameter.maximum:
                errors.append(f"Parameter {key!r} must be at most {parameter.maximum}.")
        elif parameter.kind is LuaParameterKind.BOOLEAN:
            if not isinstance(value, bool):
                errors.append(f"Parameter {key!r} must be true or false.")
        elif parameter.kind is LuaParameterKind.CHOICE:
            if not isinstance(value, str) or value not in parameter.choices:
                choices = ", ".join(parameter.choices)
                errors.append(f"Parameter {key!r} must be one of: {choices}.")
    return tuple(errors)


def catalog_primitive_ids() -> tuple[str, ...]:
    """Return the exact primitive surface consumed by the Lua compiler."""

    return tuple(dict.fromkeys(item.primitive_id for item in LUA_EFFECT_CATALOG))


def catalog_conditions() -> tuple[str, ...]:
    return tuple(
        sorted({str(item.runtime_config["condition"]) for item in LUA_EFFECT_CATALOG})
    )


def catalog_promotions() -> tuple[str, ...]:
    return tuple(
        sorted(
            str(value)
            for item in LUA_EFFECT_CATALOG
            if (value := item.runtime_config.get("promotion")) is not None
        )
    )
