from __future__ import annotations

import json

import pytest

from civ5studio.domain import (
    CURRENT_SCHEMA_VERSION,
    ArtRole,
    ProjectFormatError,
    dumps_project,
    load_project,
    migrate_document,
    project_from_dict,
    project_to_dict,
    save_project,
)


def test_sample_round_trip_is_lossless(sample_project, tmp_path):
    canonical = project_to_dict(sample_project)
    assert project_from_dict(canonical) == sample_project
    assert json.loads(dumps_project(sample_project)) == canonical

    destination = tmp_path / "portable.civ5project.json"
    save_project(destination, sample_project)
    assert load_project(destination) == sample_project
    assert destination.read_bytes().endswith(b"\n")


def test_generated_ids_are_stable_and_verified(sample_project):
    ids = sample_project.ids()
    assert ids.civilization == "CIVILIZATION_LITHUANIA_CUSTOM"
    assert ids.leader == "LEADER_VYTAUTAS_LITHUANIA_CUSTOM"
    assert ids.trait == "TRAIT_GRAND_DUCHY_LITHUANIA_CUSTOM"
    assert ids.units["WINGED_HUSSAR"] == "UNIT_WINGED_HUSSAR_LITHUANIA_CUSTOM"
    assert ids.buildings["HILL_FORT"] == "BUILDING_HILL_FORT_LITHUANIA_CUSTOM"
    assert ids.unit_flag_atlases["WINGED_HUSSAR"] == (
        "LITHUANIA_CUSTOM_UNIT_WINGED_HUSSAR_FLAG_ATLAS"
    )


def test_legacy_v10_document_migrates_to_current_schema():
    legacy = {
        "mod_name": "O'Brien Realm",
        "mod_guid": "34a4b891-d6c5-4fb3-9732-df0a89001ae2",
        "version": "3",
        "authors": "Builder",
        "internal_prefix": "OBRIEN",
        "civilization": {
            "display_name": "O'Brien Realm",
            "short_description": "O'Brien",
            "adjective": "O'Brien",
            "dawn_of_man_quote": "Welcome.",
            "base_civ_to_clone": "CIVILIZATION_POLAND",
        },
        "leader": {"display_name": "Niall"},
        "trait": {
            "display_name": "Legacy",
            "short_description": "Legacy",
            "long_description": "Faster soldiers.",
            "military_production_modifier": 10,
            "lua_effects": "Grant an unsupported bonus.",
        },
        "units": [
            {
                "display_name": "Guard",
                "replaces_unit_class": "UNITCLASS_WARRIOR",
                "combat": 0,
                "ranged_combat": -1,
            }
        ],
        "buildings": [
            {
                "display_name": "Hall",
                "replaces_building_class": "BUILDINGCLASS_MONUMENT",
                "yield_changes": [["YIELD_CULTURE", 1]],
            }
        ],
        "city_names": ["Dublin"],
        "spy_names": ["Finn"],
        "player_colors": {"primary_r": 0.1, "secondary_b": 0.9},
        "art": {"civ_icon_path": "art/civ.png"},
        "options": {"affects_saved_games": True},
    }
    migrated = migrate_document(legacy)
    project = project_from_dict(migrated)
    assert project.schema_version == CURRENT_SCHEMA_VERSION
    assert project.mod_version == 3
    assert project.leader.key == "NIALL"
    assert project.trait.database_modifiers["MilitaryProductionModifier"] == 10
    assert project.trait.effects[0].description == "Grant an unsupported bonus."
    assert project.units[0].combat is None
    assert project.buildings[0].yield_changes[0].yield_type == "YIELD_CULTURE"
    assert project.colors.primary_red == 0.1
    assert project.art.assets[0].role is ArtRole.CIVILIZATION_ICON
    assert project.options.affects_saved_games is True


def test_newer_schema_is_rejected(sample_project):
    document = project_to_dict(sample_project)
    document["schema_version"] = CURRENT_SCHEMA_VERSION + 1
    with pytest.raises(ProjectFormatError, match="newer"):
        project_from_dict(document)


@pytest.mark.parametrize(
    ("mutate", "model_name", "json_path"),
    [
        (
            lambda document: document.__setitem__("future_project_field", True),
            "CivProject",
            "$.future_project_field",
        ),
        (
            lambda document: document["options"].__setitem__(
                "future_option", True
            ),
            "ProjectOptions",
            "$.options.future_option",
        ),
        (
            lambda document: document["units"][0].__setitem__(
                "future_unit_rule", 12
            ),
            "UniqueUnitSpec",
            "$.units[0].future_unit_rule",
        ),
        (
            lambda document: document["buildings"][0]["yield_changes"][
                0
            ].__setitem__("future_yield_rule", 12),
            "YieldChange",
            "$.buildings[0].yield_changes[0].future_yield_rule",
        ),
        (
            lambda document: document["art"]["assets"][0].__setitem__(
                "future_crop_rule", "smart"
            ),
            "ArtAssetSpec",
            "$.art.assets[0].future_crop_rule",
        ),
    ],
)
def test_current_schema_unknown_fields_are_rejected_with_exact_path(
    sample_project, mutate, model_name, json_path
):
    document = project_to_dict(sample_project)
    mutate(document)

    with pytest.raises(ProjectFormatError) as captured:
        project_from_dict(document)

    message = str(captured.value)
    assert model_name in message
    assert json_path in message


def test_extension_payload_remains_opaque_and_round_trips(sample_project):
    document = project_to_dict(sample_project)
    payload = {
        "format_version": 91,
        "future_nested_object": {
            "unrecognized_field": [1, {"another_future_field": True}]
        },
    }
    document["extensions"]["third_party_future_extension"] = payload

    restored = project_from_dict(document)

    assert restored.extensions["third_party_future_extension"] == payload
    assert (
        project_to_dict(restored)["extensions"]["third_party_future_extension"]
        == payload
    )
