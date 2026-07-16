from __future__ import annotations

import os
from copy import deepcopy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListView

from civ5studio.ui.lua_effects import LuaEffectsPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _catalog() -> list[dict]:
    return [
        {
            "effect_id": "LUA_COASTAL_FOUNDING_GOLD",
            "version": 1,
            "label": "Harbor Founder's Purse",
            "category": "Cities & Expansion",
            "description": "Founding a coastal city grants Gold.",
            "primitive_id": "city_founded_reward",
            "trigger": "PlayerCityFounded",
            "default_parameters": {"amount": 75},
            "origin": "archive_inspired",
            "inspiration": "Coastal settlement reward patterns",
            "tags": ["coastal", "gold", "founding"],
            "runtime_notes": "Major civilizations only.",
            "incompatible_effect_ids": ["LUA_INLAND_FOUNDING_CULTURE"],
        },
        {
            "effect_id": "LUA_INLAND_FOUNDING_CULTURE",
            "version": 2,
            "label": "Heartland Chronicle",
            "category": "Culture & Tourism",
            "description": "Founding an inland city grants Culture.",
            "primitive_id": "city_founded_reward",
            "trigger": "PlayerCityFounded",
            "default_parameters": {"amount": 30},
            "origin": "studio_original",
            "inspiration": "",
            "tags": ["inland", "culture", "founding"],
            "runtime_notes": "Major civilizations only.",
            "incompatible_effect_ids": ["LUA_COASTAL_FOUNDING_GOLD"],
        },
        {
            "effect_id": "LUA_POLICY_FAITH",
            "version": 1,
            "label": "Creed of Reform",
            "category": "Faith & Religion",
            "description": "Adopting a policy grants Faith.",
            "primitive_id": "policy_adopted_reward",
            "trigger": "PlayerAdoptPolicy",
            "default_parameters": {"amount": 40},
            "origin": "studio_original",
            "inspiration": "",
            "tags": ["policy", "faith"],
            "runtime_notes": "Once per policy adoption.",
            "incompatible_effect_ids": [],
        },
        {
            "effect_id": "LUA_WARTIME_TREASURY",
            "version": 1,
            "label": "Wartime Treasury",
            "category": "Economy & State",
            "description": "While at war, gain Gold each turn.",
            "primitive_id": "player_turn_reward",
            "trigger": "PlayerDoTurn",
            "default_parameters": {"amount": 8},
            "origin": "archive_inspired",
            "inspiration": "Recurring wartime reward patterns",
            "tags": ["war", "gold", "recurring"],
            "runtime_notes": "Evaluated once per major-player turn.",
            "incompatible_effect_ids": [],
        },
    ]


def _select_browser_effect(page: LuaEffectsPage, effect_id: str) -> None:
    for index in range(page.effect_browser.count()):
        item = page.effect_browser.item(index)
        if item.data(Qt.UserRole) == effect_id:
            page.effect_browser.setCurrentItem(item)
            return
    raise AssertionError(f"Effect {effect_id!r} was not visible in the explorer")


def test_searchable_two_slot_selector_blocks_duplicates_and_conflicts() -> None:
    _app()
    page = LuaEffectsPage()
    page.set_catalog(_catalog())

    assert page.slot_combos[0].completer().caseSensitivity() == Qt.CaseInsensitive
    assert page.slot_combos[0].completer().filterMode() == Qt.MatchContains
    first = page.slot_combos[0]
    first.setCurrentIndex(first.findData("LUA_COASTAL_FOUNDING_GOLD"))

    second = page.slot_combos[1]
    assert second.findData("LUA_COASTAL_FOUNDING_GOLD") == -1
    assert second.findData("LUA_INLAND_FOUNDING_CULTURE") == -1
    assert second.findData("LUA_POLICY_FAITH") >= 0
    second.setCurrentIndex(second.findData("LUA_POLICY_FAITH"))

    selected = page.values()["selections"]
    assert [item["effect_id"] for item in selected] == [
        "LUA_COASTAL_FOUNDING_GOLD",
        "LUA_POLICY_FAITH",
    ]
    assert selected[0]["parameters"] == {"amount": 75}
    assert "compatibility check passed" in page.pair_status.text()
    page.deleteLater()


def test_filters_and_typed_label_commit_reliably() -> None:
    _app()
    page = LuaEffectsPage()
    page.set_catalog(_catalog())
    page.catalog_search.setText("faith")
    assert page.slot_combos[0].count() == 1
    assert page.slot_combos[0].itemData(0) == "LUA_POLICY_FAITH"
    page.catalog_search.setText("policy faith")
    assert page.slot_combos[0].count() == 1
    assert page.slot_combos[0].itemData(0) == "LUA_POLICY_FAITH"

    page.slot_combos[0].setEditText("creed")
    page.slot_combos[0].completer().activated[str].emit(
        page.slot_combos[0].itemText(0)
    )
    assert page.values()["selections"][0]["effect_id"] == "LUA_POLICY_FAITH"

    page.category_filter.setCurrentText("Culture & Tourism")
    page.catalog_search.clear()
    assert page.slot_combos[1].findData("LUA_INLAND_FOUNDING_CULTURE") >= 0
    page.deleteLater()


def test_load_round_trip_preserves_unknown_selection_and_overflow() -> None:
    _app()
    page = LuaEffectsPage()
    page.set_catalog(_catalog())
    raw = {
        "selections": [
            {
                "instance_id": "one",
                "effect_id": "LUA_UNKNOWN_FUTURE_EFFECT",
                "effect_version": 9,
                "parameters": {"future": True},
            },
            {
                "instance_id": "two",
                "effect_id": "LUA_POLICY_FAITH",
                "effect_version": 1,
                "parameters": {"amount": 99},
            },
            {
                "instance_id": "three",
                "effect_id": "LUA_INLAND_FOUNDING_CULTURE",
                "effect_version": 2,
                "parameters": {"amount": 42},
            },
        ]
    }
    page.load_values(raw)
    assert page.values() == raw
    assert page.remove_overflow_button.isVisibleTo(page)
    assert "strict validation will reject" in page.pair_status.text()

    page._remove_overflow()
    assert len(page.values()["selections"]) == 2
    page.deleteLater()


def test_explorer_scales_to_200_and_filters_trigger_origin_and_timing() -> None:
    _app()
    templates = _catalog()
    catalog: list[dict] = []
    for index in range(200):
        item = deepcopy(templates[index % len(templates)])
        item["effect_id"] = f"LUA_EXPLORER_{index:03d}"
        item["label"] = f"Explorer Effect {index:03d}"
        item["incompatible_effect_ids"] = []
        catalog.append(item)

    page = LuaEffectsPage()
    page.set_catalog(catalog)
    assert page.effect_browser.count() == 200
    assert "Showing 200 of 200" in page.catalog_count.text()
    assert page.effect_browser.viewMode() == QListView.IconMode

    trigger_index = page.trigger_filter.findData("PlayerDoTurn")
    page.trigger_filter.setCurrentIndex(trigger_index)
    assert page.effect_browser.count() == 50

    origin_index = page.origin_filter.findData("archive_inspired")
    page.origin_filter.setCurrentIndex(origin_index)
    assert page.effect_browser.count() == 50

    timing_index = page.timing_filter.findData("every_turn")
    page.timing_filter.setCurrentIndex(timing_index)
    assert page.effect_browser.count() == 50

    page.view_mode.setCurrentIndex(page.view_mode.findData("list"))
    assert page.effect_browser.viewMode() == QListView.ListMode
    assert "Explorer Effect" in page.effect_browser.item(0).text()
    page.deleteLater()


def test_favorites_and_recents_are_session_filters_not_project_values() -> None:
    _app()
    page = LuaEffectsPage()
    page.set_catalog(_catalog())
    effect_id = "LUA_POLICY_FAITH"
    _select_browser_effect(page, effect_id)

    page.favorite_button.click()
    assert effect_id in page._favorite_ids
    assert page.values() == {"selections": []}
    page.favorites_only.setChecked(True)
    assert page.effect_browser.count() == 1
    assert page.effect_browser.item(0).data(Qt.UserRole) == effect_id

    page.use_slot_buttons[0].click()
    assert page.values()["selections"][0]["effect_id"] == effect_id
    assert page._recent_ids[0] == effect_id
    assert set(page.values()) == {"selections"}

    page.favorites_only.setChecked(False)
    page.recent_only.setChecked(True)
    assert page.effect_browser.count() == 1
    assert page.effect_browser.item(0).data(Qt.UserRole) == effect_id
    page.deleteLater()


def test_explorer_explains_blocked_pairs_and_advisory_synergy() -> None:
    _app()
    page = LuaEffectsPage()
    page.set_catalog(_catalog())
    first = page.slot_combos[0]
    first.setCurrentIndex(first.findData("LUA_COASTAL_FOUNDING_GOLD"))

    _select_browser_effect(page, "LUA_INLAND_FOUNDING_CULTURE")
    assert not page.use_slot_buttons[1].isEnabled()
    assert "blocked by Harbor Founder's Purse" in page.explorer_compatibility.text()

    _select_browser_effect(page, "LUA_POLICY_FAITH")
    page.use_slot_buttons[1].click()
    assert "Compatibility: deterministic catalog check passed" in page.pair_guidance.text()
    assert "Synergy (advisory)" in page.pair_guidance.text()
    assert "compatibility check passed" in page.pair_status.text()
    page.deleteLater()
