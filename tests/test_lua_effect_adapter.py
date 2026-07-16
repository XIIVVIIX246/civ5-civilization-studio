from __future__ import annotations

from pathlib import Path

from civ5studio.application import project_from_ui, project_to_ui
from civ5studio.domain import CivProject, LuaEffectSelection


def test_lua_effect_selections_round_trip_through_plain_ui_data(
    tmp_path: Path,
) -> None:
    project = CivProject(
        lua_effects=[
            LuaEffectSelection(
                instance_id="selection-one",
                effect_id="civ5studio.lua.v1.coastal_trade_chest",
                effect_version=1,
                parameters={"amount": 75},
            ),
            LuaEffectSelection(
                instance_id="selection-two",
                effect_id="civ5studio.lua.v1.tradition_legacy",
                effect_version=2,
                parameters={"amount": 40},
            ),
        ]
    )

    ui_data = project_to_ui(project, tmp_path)
    assert ui_data["lua_effects"]["selections"] == [
        {
            "instance_id": "selection-one",
            "effect_id": "civ5studio.lua.v1.coastal_trade_chest",
            "effect_version": 1,
            "parameters": {"amount": 75},
        },
        {
            "instance_id": "selection-two",
            "effect_id": "civ5studio.lua.v1.tradition_legacy",
            "effect_version": 2,
            "parameters": {"amount": 40},
        },
    ]

    restored = project_from_ui(ui_data, existing=project)
    assert restored.lua_effects == project.lua_effects


def test_missing_lua_effect_ui_section_preserves_existing_domain_state(
    tmp_path: Path,
) -> None:
    project = CivProject(
        lua_effects=[
            LuaEffectSelection(
                instance_id="hidden-selection",
                effect_id="civ5studio.lua.v1.coastal_trade_chest",
                parameters={"amount": 75},
            )
        ]
    )
    ui_data = project_to_ui(project, tmp_path)
    ui_data.pop("lua_effects")

    restored = project_from_ui(ui_data, existing=project)
    assert restored.lua_effects == project.lua_effects
