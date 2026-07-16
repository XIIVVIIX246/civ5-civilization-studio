from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from civ5studio.application import project_from_ui, project_to_ui
from civ5studio.domain import (
    ArtAssetSpec,
    ArtManifestSpec,
    ArtRole,
    CivilizationSpec,
    CivProject,
    DomainExperience,
    ImplementationKind,
    LeaderSpec,
    MechanicEffect,
    PlayerColors,
    ProjectOptions,
    TraitSpec,
    UniqueBuildingSpec,
    UniqueImprovementSpec,
    UniqueUnitSpec,
    YieldChange,
)


VISIBLE_FLAVORS = {
    "FLAVOR_OFFENSE": 8,
    "FLAVOR_DEFENSE": 7,
    "FLAVOR_EXPANSION": 6,
    "FLAVOR_GROWTH": 5,
    "FLAVOR_SCIENCE": 9,
    "FLAVOR_CULTURE": 4,
    "FLAVOR_DIPLOMACY": 3,
    "FLAVOR_WONDER": 2,
}


def _asset(
    role: ArtRole,
    subject: str,
    source: str,
    *,
    focal_x: float = 0.41,
    focal_y: float = 0.62,
) -> ArtAssetSpec:
    return ArtAssetSpec(
        asset_id=f"asset-{role.value}-{subject}",
        role=role,
        source_png=source,
        subject_key=subject,
        required=False,
        crop_mode="contain",
        focal_x=focal_x,
        focal_y=focal_y,
    )


def _rich_project(tmp_path: Path) -> CivProject:
    effect_one = MechanicEffect(
        description="Hidden scripted effect",
        implementation=ImplementationKind.LUA_RECIPE,
        recipe_id="SCRIPTED_EFFECT",
        parameters={"amount": 2},
        notes="Keep the parameters and notes.",
    )
    effect_two = MechanicEffect(
        description="DLL-only effect",
        implementation=ImplementationKind.UNSUPPORTED,
        recipe_id="DLL_EFFECT",
        parameters={"scope": "empire"},
        notes="Design note.",
    )
    unit_one = UniqueUnitSpec(
        key="GUARD",
        name="River Guard",
        help_text="Visible unit help.",
        strategy_text="A separate hidden strategy.",
        replaces_unit_class="UNITCLASS_SWORDSMAN",
        base_unit="UNIT_SWORDSMAN",
        combat=21,
        ranged_combat=4,
        moves=3,
        cost=75,
        prereq_tech="TECH_STEEL",
        free_promotions=["PROMOTION_SHOCK_1", "PROMOTION_MARCH"],
        effects=[effect_one],
    )
    unit_two = UniqueUnitSpec(
        key="SCOUT",
        name="Marsh Scout",
        help_text="Second unit help.",
        strategy_text="Second hidden strategy.",
        replaces_unit_class="UNITCLASS_SCOUT",
        base_unit="UNIT_SCOUT",
        cost=30,
        prereq_tech="TECH_AGRICULTURE",
        free_promotions=["PROMOTION_IGNORE_TERRAIN_COST"],
        effects=[effect_two],
    )
    building_one = UniqueBuildingSpec(
        key="HALL",
        name="River Hall",
        help_text="Visible building help.",
        strategy_text="A separate building strategy.",
        replaces_building_class="BUILDINGCLASS_MONUMENT",
        base_building="BUILDING_MONUMENT",
        cost=45,
        gold_maintenance=2,
        defense=150,
        extra_city_hit_points=20,
        prereq_tech="TECH_WRITING",
        yield_changes=[
            YieldChange("YIELD_CULTURE", 3),
            YieldChange("YIELD_FAITH", 1),
        ],
        domain_free_experience=[DomainExperience("DOMAIN_LAND", 10)],
        effects=[effect_one],
    )
    building_two = UniqueBuildingSpec(
        key="DOCK",
        name="River Dock",
        help_text="Second building help.",
        strategy_text="Second building strategy.",
        replaces_building_class="BUILDINGCLASS_HARBOR",
        base_building="BUILDING_HARBOR",
        yield_changes=[YieldChange("YIELD_PRODUCTION", 2)],
        domain_free_experience=[DomainExperience("DOMAIN_SEA", 15)],
        effects=[effect_two],
    )
    art_assets = [
        _asset(ArtRole.CIVILIZATION_ICON, "civilization", "Assets/civ.png"),
        _asset(ArtRole.CIVILIZATION_ALPHA, "civilization", "Assets/alpha.png"),
        _asset(ArtRole.LEADER_PORTRAIT, "leader", "Assets/leader.png"),
        _asset(ArtRole.LEADER_SCENE, "leader", "Assets/scene.png"),
        _asset(ArtRole.DAWN_OF_MAN, "civilization", "Assets/dom.png"),
        _asset(ArtRole.MAP_IMAGE, "civilization", "Assets/map.png"),
        _asset(ArtRole.UNIQUE_UNIT_ICON, "unit:GUARD", "Assets/guard.png"),
        _asset(ArtRole.UNIT_FLAG, "unit:GUARD", "Assets/guard-flag.png"),
        _asset(ArtRole.STRATEGIC_VIEW, "unit:GUARD", "Assets/guard-sv.png"),
        _asset(
            ArtRole.UNIQUE_UNIT_ICON,
            "unit:SCOUT",
            "Assets/scout.png",
            focal_x=0.25,
            focal_y=0.75,
        ),
        _asset(ArtRole.UNIT_FLAG, "unit:SCOUT", "Assets/scout-flag.png"),
        _asset(ArtRole.STRATEGIC_VIEW, "unit:SCOUT", "Assets/scout-sv.png"),
        _asset(ArtRole.UNIQUE_BUILDING_ICON, "building:HALL", "Assets/hall.png"),
        _asset(
            ArtRole.UNIQUE_BUILDING_ICON,
            "building:DOCK",
            "Assets/dock.png",
            focal_x=0.7,
            focal_y=0.3,
        ),
    ]
    roles = (
        "civilization_icon",
        "civilization_alpha",
        "leader_portrait",
        "unique_unit_icon",
        "unique_building_icon",
        "unit_flag",
        "dawn_of_man",
        "map_image",
    )
    transforms = {
        role: {
            "zoom": 115,
            "offset_x": 7,
            "offset_y": -9,
            "adapter_private": f"keep-{role}",
        }
        for role in roles
    }
    return CivProject(
        project_id="project-stable",
        mod_id="mod-stable",
        mod_name="Rich Civilization",
        mod_version=7,
        authors="Adapter Tester",
        teaser="A deliberately custom teaser.",
        description="Visible description.",
        internal_prefix="RICH",
        civilization=CivilizationSpec(
            name="River Nation",
            short_name="River",
            adjective="Riverine",
            civilopedia="Civilization history.",
            dawn_of_man_quote="Lead from the river.",
            base_civilization="CIVILIZATION_POLAND",
            copy_free_buildings_from="CIVILIZATION_ROME",
            copy_free_techs_and_units_from="CIVILIZATION_ZULU",
            start_region_avoid="REGION_DESERT",
            city_names=["One", "Two"],
            spy_names=["Hidden Hand"],
        ),
        leader=LeaderSpec(
            key="RIVER_LEADER",
            name="River Leader",
            civilopedia="Leader history.",
            victory_competitiveness=1,
            wonder_competitiveness=2,
            minor_civ_competitiveness=3,
            boldness=4,
            diplo_balance=6,
            warmonger_hate=7,
            denounce_willingness=8,
            dof_willingness=9,
            loyalty=10,
            neediness=1,
            forgiveness=2,
            chattiness=3,
            meanness=4,
            flavors={**VISIBLE_FLAVORS, "FLAVOR_RELIGION": 10},
            major_civ_approach_biases={"MAJOR_CIV_APPROACH_WAR": 8},
            minor_civ_approach_biases={"MINOR_CIV_APPROACH_FRIENDLY": 9},
            diplomacy_text={"FIRST_GREETING": "A private greeting."},
        ),
        trait=TraitSpec(
            key="RIVER_TRAIT",
            name="River Knowledge",
            short_description="Short trait text.",
            long_description="Visible trait description.",
            database_modifiers={
                "WorkerSpeedModifier": 20,
                "MilitaryProductionModifier": 15,
            },
            effects=[effect_one, effect_two],
        ),
        units=[unit_one, unit_two],
        buildings=[building_one, building_two],
        colors=PlayerColors(
            primary_red=round(17 / 255, 6),
            primary_green=round(34 / 255, 6),
            primary_blue=round(51 / 255, 6),
            primary_alpha=0.4,
            secondary_red=round(221 / 255, 6),
            secondary_green=round(204 / 255, 6),
            secondary_blue=round(68 / 255, 6),
            secondary_alpha=0.6,
        ),
        art=ArtManifestSpec(
            contract_version="custom-art-contract-v9",
            allow_placeholders=True,
            assets=art_assets,
        ),
        options=ProjectOptions(
            affects_saved_games=False,
            supports_multiplayer=False,
            supports_hotseat=False,
            supports_mac=False,
        ),
        extensions={
            "third_party": {"retain": [1, 2, 3]},
            "ui": {
                "project_root": str(tmp_path / "Build Output"),
                "leader_title": "Keeper of the River",
                "art_transforms": transforms,
                "unsupported_unique_rows": [
                    {"kind": "improvement", "name": "Hidden Marsh"}
                ],
                "private_ui_state": {"retain": True},
            },
        },
    )


def test_ui_round_trip_is_lossless_for_unexposed_domain_fields(tmp_path: Path) -> None:
    original = _rich_project(tmp_path)

    ui_data = project_to_ui(original, tmp_path)
    restored = project_from_ui(ui_data, existing=original)

    assert restored == original


def test_unique_key_rename_migrates_hidden_fields_pep_and_art_identity(
    tmp_path: Path,
) -> None:
    original = _rich_project(tmp_path)
    original.dependencies.promotions_expansion_pack = True
    original.units[0].promotions_expansion_pack = ["PROMOTION_REPUTATION"]
    ui_data = project_to_ui(original, tmp_path)
    unit_row = next(
        row
        for row in ui_data["mechanics"]["uniques"]
        if row["kind"] == "unit" and row["key"] == "GUARD"
    )
    building_row = next(
        row
        for row in ui_data["mechanics"]["uniques"]
        if row["kind"] == "building" and row["key"] == "HALL"
    )
    assert unit_row["original_key"] == "GUARD"
    assert building_row["original_key"] == "HALL"
    unit_row["key"] = "RIVER_GUARD"
    building_row["key"] = "RIVER_HALL"

    updated = project_from_ui(ui_data, existing=original)

    renamed_unit = next(item for item in updated.units if item.key == "RIVER_GUARD")
    renamed_building = next(
        item for item in updated.buildings if item.key == "RIVER_HALL"
    )
    assert renamed_unit.effects == original.units[0].effects
    assert renamed_unit.promotions_expansion_pack == ["PROMOTION_REPUTATION"]
    assert renamed_building.effects == original.buildings[0].effects
    old_asset = next(
        asset
        for asset in original.art.assets
        if asset.role is ArtRole.UNIQUE_UNIT_ICON
        and asset.subject_key == "unit:GUARD"
    )
    migrated = next(
        asset
        for asset in updated.art.assets
        if asset.role is ArtRole.UNIQUE_UNIT_ICON
        and asset.subject_key == "unit:RIVER_GUARD"
    )
    assert migrated.asset_id == old_asset.asset_id
    assert migrated.source_png == old_asset.source_png
    assert migrated.crop_mode == old_asset.crop_mode
    assert migrated.focal_x == old_asset.focal_x
    assert migrated.focal_y == old_asset.focal_y


def test_documented_lua_effect_round_trip_remains_lossless_and_uncompiled(
    tmp_path: Path,
) -> None:
    original = _rich_project(tmp_path)
    original.trait.database_modifiers = {}
    original.trait.effects = [original.trait.effects[0]]

    ui_data = project_to_ui(original, tmp_path)
    assert ui_data["mechanics"]["trait"]["implementation_class"] == (
        "Lua idea (not compiled)"
    )
    restored = project_from_ui(ui_data, existing=original)
    assert restored == original


def test_visible_edits_update_only_the_exposed_slice(tmp_path: Path) -> None:
    original = _rich_project(tmp_path)
    ui_data = project_to_ui(original, tmp_path)
    replacement_icon = tmp_path / "replacement-guard.png"

    ui_data["project"]["affects_saved_games"] = True
    ui_data["project"]["description"] = "An edited visible description."
    ui_data["civilization"]["base_civilization"] = "CIVILIZATION_AMERICA"
    ui_data["leader"]["flavors"]["offense"] = 10
    ui_data["leader"]["title"] = "Edited title"
    ui_data["mechanics"]["trait"].update(
        {
            "recipe": "Great Person rate modifier",
            "modifier_value": 33,
            "effect_description": "Edited visible trait description.",
        }
    )
    ui_data["mechanics"]["uniques"][0].update(
        {"override": "Moves", "value": "5", "help_text": "Edited unit help."}
    )
    ui_data["mechanics"]["uniques"][2].update(
        {"override": "Defense", "value": "900", "help_text": "Edited hall help."}
    )
    ui_data["art"]["unique_unit_icon"] = {
        "source": str(replacement_icon),
        "transform": {"zoom": 120, "offset_x": 20, "offset_y": -10},
    }

    updated = project_from_ui(ui_data, existing=original)

    assert updated.description == "An edited visible description."
    assert updated.teaser == original.teaser
    assert updated.options.affects_saved_games is True
    assert updated.options.supports_multiplayer is False
    assert updated.options.supports_hotseat is False
    assert updated.options.supports_mac is False
    assert updated.civilization.base_civilization == "CIVILIZATION_AMERICA"
    assert updated.civilization.copy_free_buildings_from == "CIVILIZATION_ROME"
    assert updated.civilization.copy_free_techs_and_units_from == "CIVILIZATION_ZULU"
    assert updated.civilization.start_region_avoid == "REGION_DESERT"
    assert updated.leader.flavors["FLAVOR_OFFENSE"] == 10
    assert updated.leader.flavors["FLAVOR_RELIGION"] == 10
    assert updated.leader.boldness == original.leader.boldness
    assert updated.leader.major_civ_approach_biases == (
        original.leader.major_civ_approach_biases
    )
    assert updated.leader.minor_civ_approach_biases == (
        original.leader.minor_civ_approach_biases
    )
    assert updated.leader.diplomacy_text == original.leader.diplomacy_text
    assert updated.trait.database_modifiers == {
        "GreatPeopleRateModifier": 33,
        "MilitaryProductionModifier": 15,
    }
    assert updated.trait.effects == original.trait.effects
    assert updated.units[0].combat is None
    assert updated.units[0].moves == 5
    assert updated.units[0].ranged_combat == 4
    assert updated.units[0].prereq_tech == "TECH_STEEL"
    assert updated.units[0].free_promotions == original.units[0].free_promotions
    assert updated.units[0].effects == original.units[0].effects
    assert updated.units[0].strategy_text == original.units[0].strategy_text
    assert updated.buildings[0].cost is None
    assert updated.buildings[0].defense == 900
    assert updated.buildings[0].yield_changes == original.buildings[0].yield_changes
    assert updated.buildings[0].domain_free_experience == (
        original.buildings[0].domain_free_experience
    )
    assert updated.colors.primary_alpha == 0.4
    assert updated.colors.secondary_alpha == 0.6
    assets = {(asset.role, asset.subject_key): asset for asset in updated.art.assets}
    assert assets[(ArtRole.UNIQUE_UNIT_ICON, "unit:GUARD")].source_png == (
        replacement_icon.as_posix()
    )
    assert assets[(ArtRole.UNIQUE_UNIT_ICON, "unit:GUARD")].focal_x == 0.6
    assert assets[(ArtRole.UNIQUE_UNIT_ICON, "unit:SCOUT")] == next(
        asset
        for asset in original.art.assets
        if asset.role is ArtRole.UNIQUE_UNIT_ICON
        and asset.subject_key == "unit:SCOUT"
    )
    assert assets[(ArtRole.STRATEGIC_VIEW, "unit:SCOUT")].source_png == (
        "Assets/scout-sv.png"
    )
    assert updated.art.contract_version == "custom-art-contract-v9"
    assert updated.art.allow_placeholders is True
    assert updated.extensions["third_party"] == original.extensions["third_party"]
    assert updated.extensions["ui"]["private_ui_state"] == {"retain": True}
    assert updated.extensions["ui"]["unsupported_unique_rows"] == [
        {"kind": "improvement", "name": "Hidden Marsh"}
    ]


def test_deleting_first_unique_rows_preserves_survivors_by_stable_key(
    tmp_path: Path,
) -> None:
    original = _rich_project(tmp_path)
    original.dependencies.promotions_expansion_pack = True
    original.units[0].promotions_expansion_pack = ["PROMOTION_REPUTATION"]
    original.units[1].promotions_expansion_pack = ["PROMOTION_MOUNTAIN"]
    original.improvements = [
        UniqueImprovementSpec(
            key="FARMSTEAD",
            name="River Farmstead",
            help_text="First improvement help.",
            strategy_text="First improvement strategy.",
            civilopedia_text="First improvement history.",
            base_improvement="IMPROVEMENT_FARM",
            build_prereq_tech="TECH_CALENDAR",
            yield_changes=[YieldChange("YIELD_FOOD", 1)],
        ),
        UniqueImprovementSpec(
            key="MARSH_POST",
            name="Marsh Trading Post",
            help_text="Second improvement help.",
            strategy_text="Second improvement strategy.",
            civilopedia_text="Second improvement history.",
            base_improvement="IMPROVEMENT_TRADING_POST",
            build_prereq_tech="TECH_GUILDS",
            yield_changes=[YieldChange("YIELD_GOLD", 2)],
        ),
    ]
    original.art.assets.extend(
        [
            _asset(
                ArtRole.UNIQUE_IMPROVEMENT_ICON,
                "improvement:FARMSTEAD",
                "Assets/farmstead.png",
            ),
            _asset(
                ArtRole.UNIQUE_IMPROVEMENT_ICON,
                "improvement:MARSH_POST",
                "Assets/marsh-post.png",
                focal_x=0.33,
                focal_y=0.66,
            ),
        ]
    )
    ui_data = project_to_ui(original, tmp_path)
    deleted_keys = {"GUARD", "HALL", "FARMSTEAD"}
    ui_data["mechanics"]["uniques"] = [
        row
        for row in ui_data["mechanics"]["uniques"]
        if row["key"] not in deleted_keys
    ]

    updated = project_from_ui(ui_data, existing=original)

    assert [item.key for item in updated.units] == ["SCOUT"]
    assert [item.key for item in updated.buildings] == ["DOCK"]
    assert [item.key for item in updated.improvements] == ["MARSH_POST"]
    assert updated.units[0].effects == original.units[1].effects
    assert updated.buildings[0].effects == original.buildings[1].effects
    assert updated.units[0].promotions_expansion_pack == ["PROMOTION_MOUNTAIN"]
    assert updated.improvements[0] == original.improvements[1]

    updated_assets = {
        (asset.role, asset.subject_key): asset for asset in updated.art.assets
    }
    original_assets = {
        (asset.role, asset.subject_key): asset for asset in original.art.assets
    }
    survivor_assets = (
        (ArtRole.UNIQUE_UNIT_ICON, "unit:SCOUT"),
        (ArtRole.UNIT_FLAG, "unit:SCOUT"),
        (ArtRole.STRATEGIC_VIEW, "unit:SCOUT"),
        (ArtRole.UNIQUE_BUILDING_ICON, "building:DOCK"),
        (ArtRole.UNIQUE_IMPROVEMENT_ICON, "improvement:MARSH_POST"),
    )
    for identity in survivor_assets:
        assert updated_assets[identity] == original_assets[identity]
    assert not any(
        asset.subject_key
        in {"unit:GUARD", "building:HALL", "improvement:FARMSTEAD"}
        for asset in updated.art.assets
    )


def test_keyless_legacy_rows_use_position_without_reusing_a_keyed_match(
    tmp_path: Path,
) -> None:
    original = _rich_project(tmp_path)
    legacy_ui = project_to_ui(original, tmp_path)
    for row in legacy_ui["mechanics"]["uniques"]:
        row.pop("key")
        row.pop("original_key")
    legacy_round_trip = project_from_ui(legacy_ui, existing=original)
    assert [item.key for item in legacy_round_trip.units] == ["GUARD", "SCOUT"]
    assert legacy_round_trip.units[0].effects == original.units[0].effects
    assert legacy_round_trip.units[1].effects == original.units[1].effects
    assert [item.key for item in legacy_round_trip.buildings] == ["HALL", "DOCK"]

    mixed_ui = project_to_ui(original, tmp_path)
    unit_rows = [
        deepcopy(row)
        for row in mixed_ui["mechanics"]["uniques"]
        if row["kind"] == "unit"
    ]
    legacy_replacement = unit_rows[0]
    legacy_replacement.pop("key")
    legacy_replacement.pop("original_key")
    legacy_replacement["name"] = "Legacy Replacement"
    mixed_ui["mechanics"]["uniques"] = [unit_rows[1], legacy_replacement]

    mixed = project_from_ui(mixed_ui, existing=original)
    assert [item.key for item in mixed.units] == ["SCOUT", "LEGACY_REPLACEMENT"]
    assert mixed.units[0].effects == original.units[1].effects
    assert mixed.units[1].effects == []


def test_reordering_keyed_rows_keeps_hidden_state_with_each_key(
    tmp_path: Path,
) -> None:
    original = _rich_project(tmp_path)
    ui_data = project_to_ui(original, tmp_path)
    rows = ui_data["mechanics"]["uniques"]
    ui_data["mechanics"]["uniques"] = [rows[1], rows[0], rows[3], rows[2]]

    reordered = project_from_ui(ui_data, existing=original)

    assert [item.key for item in reordered.units] == ["SCOUT", "GUARD"]
    assert reordered.units[0].effects == original.units[1].effects
    assert reordered.units[1].effects == original.units[0].effects
    assert [item.key for item in reordered.buildings] == ["DOCK", "HALL"]
    assert reordered.buildings[0].effects == original.buildings[1].effects
    assert reordered.buildings[1].effects == original.buildings[0].effects
