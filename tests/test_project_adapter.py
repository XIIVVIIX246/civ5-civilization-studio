from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image
import pytest

from civ5studio.application import project_from_ui, project_to_ui, save_ui_project
from civ5studio.domain import load_project, validate_project


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ui_data(source: Path, output_root: Path) -> dict:
    transform = {"zoom": 125, "offset_x": 10, "offset_y": -15}
    return {
        "schema_version": 1,
        "project": {
            "mod_name": "Test Nation",
            "prefix": "TEST_NATION",
            "version": 2,
            "author": "Tester",
            "description": "A generated test civilization.",
            "affects_saved_games": True,
            "project_root": str(output_root),
        },
        "civilization": {
            "name": "Test Nation",
            "short_name": "Test",
            "adjective": "Testian",
            "base_civilization": "CIVILIZATION_POLAND",
            "dawn_of_man_quote": "Lead your people.",
            "civilopedia": "Test history.",
            "colors": {"primary": "#112233", "secondary": "#eedd44"},
            "city_names": ["First City", "Second City"],
            "spy_names": ["One Spy"],
        },
        "leader": {
            "name": "Ada",
            "title": "The Builder",
            "civilopedia": "Ada leads the test nation.",
            "flavors": {key: 5 for key in ("offense", "defense", "expansion", "growth", "science", "culture", "diplomacy", "wonder")},
            "art": {"leader_scene": str(source), "leader_fallback": str(source)},
        },
        "mechanics": {
            "trait": {
                "name": "Measured Progress",
                "short_description": "Build faster.",
                "implementation_class": "Database-native recipe",
                "recipe": "Worker speed modifier",
                "modifier_value": 15,
                "effect_description": "Workers improve tiles 15 percent faster.",
            },
            "uniques": [
                {
                    "kind": "unit",
                    "name": "Test Guard",
                    "replaces_class": "UNITCLASS_SWORDSMAN",
                    "base_template": "UNIT_SWORDSMAN",
                    "override": "Combat",
                    "value": "18",
                    "help_text": "A stronger Swordsman.",
                },
                {
                    "kind": "building",
                    "name": "Test Hall",
                    "replaces_class": "BUILDINGCLASS_MONUMENT",
                    "base_template": "BUILDING_MONUMENT",
                    "override": "Yield:YIELD_CULTURE",
                    "value": "2",
                    "help_text": "A cultural Monument.",
                },
            ],
        },
        "art": {
            role: {"source": str(source), "transform": dict(transform)}
            for role in (
                "civilization_icon",
                "civilization_alpha",
                "leader_portrait",
                "unique_unit_icon",
                "unique_building_icon",
                "unit_flag",
                "dawn_of_man",
                "map_image",
            )
        },
    }


def test_save_adapter_copies_sources_and_writes_canonical_project(tmp_path: Path) -> None:
    source = tmp_path / "external" / "source.png"
    source.parent.mkdir()
    Image.new("RGB", (64, 64), (20, 40, 60)).save(source)
    before = _hash(source)
    project_path = tmp_path / "project" / "Test.civ5project.json"
    project, portable = save_ui_project(
        project_path,
        _ui_data(source, tmp_path / "output"),
    )
    assert _hash(source) == before
    assert project_path.is_file()
    assert portable["art"]["civilization_icon"]["source"].startswith("Assets/Source/")
    loaded = load_project(project_path)
    assert loaded.project_id == project.project_id
    assert loaded.options.affects_saved_games is True
    assert loaded.trait.database_modifiers == {"WorkerSpeedModifier": 15}
    assert loaded.units[0].combat == 18
    assert loaded.buildings[0].yield_changes[0].amount == 2
    assert len(loaded.art.assets) == 9
    report = validate_project(loaded, strict_release=True, project_root=project_path.parent)
    assert report.errors == ()


def test_project_to_ui_restores_absolute_sources_and_transforms(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "white").save(source)
    path = tmp_path / "saved" / "Roundtrip.civ5project.json"
    project, _ = save_ui_project(path, _ui_data(source, tmp_path / "output"))
    restored = project_to_ui(project, path.parent)
    icon = restored["art"]["civilization_icon"]
    assert Path(icon["source"]).is_absolute()
    assert Path(icon["source"]).is_file()
    assert icon["transform"] == {"zoom": 125, "offset_x": 10, "offset_y": -15}
    assert restored["mechanics"]["trait"]["recipe"] == "Worker speed modifier"


def test_existing_stable_keys_survive_display_name_edits(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "white").save(source)
    data = _ui_data(source, tmp_path / "output")
    original = project_from_ui(data)
    leader_key = original.leader.key
    unit_key = original.units[0].key
    data["leader"]["name"] = "Renamed Leader"
    data["mechanics"]["uniques"][0]["name"] = "Renamed Guard"
    updated = project_from_ui(data, existing=original)
    assert updated.leader.key == leader_key
    assert updated.units[0].key == unit_key


def test_advanced_unique_fields_and_subject_art_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (32, 32), "white").save(source)
    Image.new("RGB", (32, 32), "black").save(second)
    data = _ui_data(source, tmp_path / "output")
    unit = data["mechanics"]["uniques"][0]
    unit.update(
        strategy_text="Use every compiled field.",
        combat=22,
        ranged_combat=6,
        moves=4,
        cost=90,
        prereq_tech="TECH_STEEL",
        free_promotions=["PROMOTION_MARCH", "PROMOTION_SHOCK_1"],
        art={
            "icon_source": str(second),
            "unit_flag_source": str(source),
            "strategic_view_source": str(second),
        },
    )
    building = data["mechanics"]["uniques"][1]
    building.update(
        strategy_text="A complete building editor row.",
        cost=55,
        gold_maintenance=2,
        defense=300,
        extra_city_hit_points=20,
        prereq_tech="TECH_WRITING",
        yield_changes=[
            {"yield_type": "YIELD_CULTURE", "amount": 3},
            {"yield_type": "YIELD_FAITH", "amount": 1},
        ],
        domain_free_experience=[{"domain_type": "DOMAIN_LAND", "amount": 10}],
        art={"icon_source": str(second)},
    )

    path = tmp_path / "advanced" / "Advanced.civ5project.json"
    project, _ = save_ui_project(path, data)
    assert (project.units[0].combat, project.units[0].ranged_combat) == (22, 6)
    assert project.units[0].free_promotions == [
        "PROMOTION_MARCH",
        "PROMOTION_SHOCK_1",
    ]
    assert len(project.buildings[0].yield_changes) == 2
    assert project.buildings[0].domain_free_experience[0].amount == 10
    restored = project_to_ui(project, path.parent)
    assert restored["mechanics"]["uniques"][0]["art"]["icon_source"].endswith(
        ".png"
    )
    assert restored["mechanics"]["uniques"][1]["yield_changes"][1] == {
        "yield_type": "YIELD_FAITH",
        "amount": 1,
    }


def test_invalid_structured_unique_reference_is_preserved_for_validation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "white").save(source)
    data = _ui_data(source, tmp_path / "output")
    data["mechanics"]["uniques"][1]["yield_changes"] = [
        {"yield_type": "", "amount": 2}
    ]
    project = project_from_ui(data)
    assert len(project.buildings[0].yield_changes) == 1
    assert project.buildings[0].yield_changes[0].yield_type == ""
    assert validate_project(project).has_code("reference.yields")


def test_failed_advanced_materialization_does_not_overwrite_loose_project(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "white").save(source)
    path = tmp_path / "loose" / "Transactional.civ5project.json"
    data = _ui_data(source, tmp_path / "output")
    project, _ = save_ui_project(path, data)
    before = path.read_bytes()
    data["project"]["author"] = "Must not be partially saved"
    data["advanced"] = {
        "diplomacy_text": {},
        "localization": {"entries": {}},
        "unit_art": {"assignments": []},
        "audio": {
            "peace_music": str(tmp_path / "missing-peace.mp3"),
            "war_music": str(tmp_path / "missing-war.mp3"),
            "dawn_of_man_speech": "",
        },
    }

    with pytest.raises(ValueError, match="does not exist"):
        save_ui_project(path, data, existing=project, source_base=path.parent)

    assert path.read_bytes() == before
