from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from civ5studio.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_main_window_has_six_guided_steps_and_three_optional_editors() -> None:
    _app()
    window = MainWindow()
    assert window.steps.count() == 9
    assert window.stack.count() == 9
    assert window.STEP_NAMES[4] == "5  Promotions Mod (Optional)"
    assert window.STEP_NAMES[6] == "7  Advanced Tools (Optional)"
    assert window.STEP_NAMES[7] == "8  Extra Gameplay Effects (Optional)"
    assert window.GUIDED_PAGE_INDICES == (0, 1, 2, 3, 5, 8)
    assert [
        index for index in range(window.steps.count()) if not window.steps.item(index).isHidden()
    ] == [0, 1, 2, 3, 5, 8]
    assert window.review_page.install_button.isEnabled() is False
    window.deleteLater()


def test_window_collects_portable_plain_data() -> None:
    _app()
    window = MainWindow()
    project = window.pages[0]
    project.mod_name.setText("Test Civilization")  # type: ignore[attr-defined]
    project.prefix.setText("TEST_CIV")  # type: ignore[attr-defined]
    data = window.collect_values()
    assert data["schema_version"] == 1
    assert data["project"]["mod_name"] == "Test Civilization"
    assert data["project"]["prefix"] == "TEST_CIV"
    assert set(data) == {
        "schema_version",
        "project",
        "civilization",
        "leader",
        "mechanics",
        "promotions_expansion_pack",
        "art",
        "advanced",
        "lua_effects",
    }
    window.mark_clean()
    window.deleteLater()


def test_preview_overlay_is_presentation_only() -> None:
    _app()
    window = MainWindow()
    art = window.pages[5]
    values = art.values()
    assert "ring" not in repr(values).lower()
    assert values["civilization_icon"]["transform"] == {"zoom": 100, "offset_x": 0, "offset_y": 0}
    window.mark_clean()
    window.deleteLater()


def test_verified_catalog_choices_feed_structured_unique_rows() -> None:
    _app()
    window = MainWindow()
    window.set_reference_catalog(
        civilizations=["CIVILIZATION_POLAND", "CIVILIZATION_ZULU"],
        unit_templates=[("UNITCLASS_WARRIOR", "UNIT_WARRIOR")],
        building_templates=[("BUILDINGCLASS_MONUMENT", "BUILDING_MONUMENT")],
        yields=["YIELD_CULTURE"],
    )
    mechanics = window.pages[3]
    rows = mechanics.uniques.values()  # type: ignore[attr-defined]
    assert rows[0]["replaces_class"] == "UNITCLASS_SWORDSMAN"
    assert rows[0]["override"] == "Combat"
    assert rows[1]["replaces_class"] == "BUILDINGCLASS_MONUMENT"
    assert rows[1]["override"] == "Yield:YIELD_CULTURE"
    assert mechanics.values()["trait"]["modifier_value"] == 10
    window.mark_clean()
    window.deleteLater()


def test_unique_detail_editor_exposes_all_compiled_fields_and_per_unique_art() -> None:
    _app()
    window = MainWindow()
    mechanics = window.pages[3]
    unique_editor = mechanics.uniques  # type: ignore[attr-defined]
    unique_editor.table.setCurrentCell(0, 1)
    unique_editor.unit_numbers["combat"].setText("24")
    unique_editor.unit_numbers["ranged_combat"].setText("7")
    unique_editor.unit_numbers["moves"].setText("3")
    unique_editor.unit_numbers["cost"].setText("85")
    unique_editor.prereq_tech.setCurrentText("TECH_STEEL")
    unique_editor.promotions.add_row("PROMOTION_MARCH")
    unique_editor.promotions.add_row("PROMOTION_SHOCK_1")
    unique_editor.unit_icon.set_path("C:/art/guard.png")
    unique_editor.unit_flag.set_path("C:/art/guard-flag.png")
    unique_editor.strategic_view.set_path("C:/art/guard-sv.png")

    row = unique_editor.values()[0]
    assert (row["combat"], row["ranged_combat"], row["moves"], row["cost"]) == (
        24,
        7,
        3,
        85,
    )
    assert row["prereq_tech"] == "TECH_STEEL"
    assert row["free_promotions"] == ["PROMOTION_MARCH", "PROMOTION_SHOCK_1"]
    assert row["art"] == {
        "icon_source": "C:/art/guard.png",
        "unit_flag_source": "C:/art/guard-flag.png",
        "strategic_view_source": "C:/art/guard-sv.png",
    }

    unique_editor.table.setCurrentCell(1, 1)
    unique_editor.building_numbers["cost"].setText("60")
    unique_editor.building_numbers["gold_maintenance"].setText("2")
    unique_editor.building_numbers["defense"].setText("250")
    unique_editor.building_numbers["extra_city_hit_points"].setText("15")
    unique_editor.yield_changes.add_row(
        {"yield_type": "YIELD_CULTURE", "amount": 3}
    )
    unique_editor.domain_experience.add_row(
        {"domain_type": "DOMAIN_LAND", "amount": 10}
    )
    unique_editor.building_icon.set_path("C:/art/hall.png")
    building = unique_editor.values()[1]
    assert building["yield_changes"] == [
        {"yield_type": "YIELD_CULTURE", "amount": 3}
    ]
    assert building["domain_free_experience"] == [
        {"domain_type": "DOMAIN_LAND", "amount": 10}
    ]
    assert building["art"]["icon_source"] == "C:/art/hall.png"
    window.mark_clean()
    window.deleteLater()
