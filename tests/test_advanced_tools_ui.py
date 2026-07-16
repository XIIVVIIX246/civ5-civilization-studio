from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from civ5studio.ui.advanced_tools import AdvancedToolsPage, SUPPORTED_LOCALES


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_advanced_tools_has_six_explicit_tabs_without_promotions() -> None:
    _app()
    page = AdvancedToolsPage()
    labels = [page.tabs.tabText(index) for index in range(page.tabs.count())]
    assert labels == [
        "Import Existing Mod",
        "Diplomacy & Localization",
        "Custom 3D Unit Art",
        "Audio & Music",
        "Game Test & Logs",
        "Compatibility",
    ]
    assert all("promotion" not in label.lower() for label in labels)
    assert page.import_button.text() == "Create inspection snapshot"
    assert any(
        "not included in generated builds" in label.text()
        for label in page.findChildren(QLabel)
    )
    assert SUPPORTED_LOCALES == (
        "en_US",
        "DE_DE",
        "ES_ES",
        "FR_FR",
        "IT_IT",
        "JA_JP",
        "KO_KR",
        "PL_PL",
        "RU_RU",
        "ZH_Hant_HK",
    )
    page.deleteLater()


def test_duplicate_diplomacy_and_localization_rows_are_reverted() -> None:
    _app()
    page = AdvancedToolsPage()
    page.set_diplomacy_responses(["RESPONSE_FIRST", "RESPONSE_SECOND"])
    page.add_diplomacy_response("RESPONSE_FIRST", "First line")
    page.add_diplomacy_response("RESPONSE_SECOND", "Second line")
    second_response = page.diplomacy_table.cellWidget(1, 0)
    assert isinstance(second_response, QComboBox)
    second_response.setCurrentIndex(second_response.findData("RESPONSE_FIRST"))
    assert second_response.currentData() == "RESPONSE_SECOND"

    page.add_localization_entry("en_US", "TXT_KEY_FIRST", "First text")
    page.add_localization_entry("en_US", "TXT_KEY_SECOND", "Second text")
    second_tag = page.localization_table.item(1, 1)
    assert second_tag is not None
    second_tag.setText("TXT_KEY_FIRST")
    assert second_tag.text() == "TXT_KEY_SECOND"
    values = page.values()
    assert values["diplomacy_text"] == {
        "RESPONSE_FIRST": "First line",
        "RESPONSE_SECOND": "Second line",
    }
    assert values["localization"]["entries"]["en_US"] == {
        "TXT_KEY_FIRST": "First text",
        "TXT_KEY_SECOND": "Second text",
    }
    page.deleteLater()


def test_persisted_values_round_trip_and_preserve_unresolved_units() -> None:
    _app()
    page = AdvancedToolsPage()
    page.set_diplomacy_responses(["RESPONSE_FIRST_GREETING", "RESPONSE_DEFEATED"])
    expected = {
        "diplomacy_text": {
            "RESPONSE_FIRST_GREETING": "Welcome, traveler.",
            "RESPONSE_FROM_REMOVED_CATALOG": "This unknown key is retained.",
        },
        "localization": {
            "entries": {
                "en_US": {"TXT_KEY_TEST_NAME": "Test Nation"},
                "FR_FR": {"TXT_KEY_TEST_NAME": "Nation test"},
                "ZH_Hant_HK": {"TXT_KEY_TEST_HELP": "Help text"},
            }
        },
        "unit_art": {
            "assignments": [
                {
                    "unit_key": "guard",
                    "unit_name": "Royal Guard",
                    "unit_index": 0,
                    "source_folder": "Assets/Guard",
                    "fxsxml": "Guard.fxsxml",
                    "scale": 0.85,
                    "z_offset": 0.125,
                },
                {
                    "unit_key": "removed_unit",
                    "unit_name": "Removed Unit",
                    "unit_index": 8,
                    "source_folder": "Assets/Removed",
                    "fxsxml": "Removed.fxsxml",
                    "scale": 1.0,
                    "z_offset": -0.25,
                },
            ]
        },
        "audio": {
            "peace_music": "Audio/Peace.mp3",
            "war_music": "Audio/War.mp3",
            "dawn_of_man_speech": "Audio/DOM.wav",
        },
    }
    page.load_values(expected)
    page.set_units(
        [
            {"kind": "unit", "key": "guard", "name": "Royal Guard"},
            {"kind": "building", "key": "hall", "name": "Royal Hall"},
        ]
    )

    assert page.values() == expected
    assert page.unit_art_table.rowCount() == 2
    unresolved = page.unit_art_table.cellWidget(1, 0)
    assert isinstance(unresolved, QComboBox)
    assert unresolved.currentText().startswith("Unresolved:")
    page.deleteLater()


def test_units_can_resolve_a_previously_unknown_assignment() -> None:
    _app()
    page = AdvancedToolsPage()
    page.load_values(
        {
            "unit_art": {
                "assignments": [
                    {
                        "unit_key": "ranger",
                        "unit_name": "Old Ranger Name",
                        "unit_index": 9,
                        "source_folder": "Assets/Ranger",
                        "fxsxml": "Ranger.fxsxml",
                        "scale": 1.1,
                        "z_offset": 0,
                    }
                ]
            }
        }
    )
    page.set_units(
        [
            {
                "kind": "unit",
                "key": "ranger",
                "name": "Updated Ranger Name",
                "unit_index": 2,
            }
        ]
    )
    assignment = page.values()["unit_art"]["assignments"][0]
    assert assignment["unit_key"] == "ranger"
    assert assignment["unit_name"] == "Updated Ranger Name"
    assert assignment["unit_index"] == 2
    page.deleteLater()


def test_diplomacy_catalog_refresh_preserves_unknown_existing_keys() -> None:
    _app()
    page = AdvancedToolsPage()
    page.load_values(
        {
            "diplomacy_text": {
                "RESPONSE_KNOWN": "Known line",
                "RESPONSE_LEGACY": "Legacy line",
            }
        }
    )
    page.set_diplomacy_responses(["RESPONSE_KNOWN", "RESPONSE_NEW"])
    assert page.values()["diplomacy_text"] == {
        "RESPONSE_KNOWN": "Known line",
        "RESPONSE_LEGACY": "Legacy line",
    }
    legacy_combo = page.diplomacy_table.cellWidget(1, 0)
    assert isinstance(legacy_combo, QComboBox)
    assert legacy_combo.currentText() == "Unknown preserved: RESPONSE_LEGACY"
    page.deleteLater()


def test_operational_buttons_emit_exact_path_payloads_and_show_results() -> None:
    _app()
    page = AdvancedToolsPage()
    imports: list[tuple[str, str]] = []
    analyses: list[tuple[str, str]] = []
    exports: list[tuple[str, str, str]] = []
    scans: list[str] = []
    page.importModRequested.connect(lambda source, dest: imports.append((source, dest)))
    page.analyzeLogsRequested.connect(lambda root, mod: analyses.append((root, mod)))
    page.exportDiagnosticsRequested.connect(
        lambda root, mod, dest: exports.append((root, mod, dest))
    )
    page.scanCompatibilityRequested.connect(lambda root: scans.append(root))

    page.import_source.setText("C:/Mods/Source")
    page.import_destination_parent.setText("C:/Projects")
    page.test_civ5_root.setText("C:/Civ5")
    page.test_generated_mod_root.setText("C:/Generated/Test")
    page.diagnostics_destination.setText("C:/Reports/test.zip")
    page.compatibility_mods_root.setText("C:/Civ5/MODS")
    page.import_button.click()
    page.analyze_logs_button.click()
    page.export_diagnostics_button.click()
    page.scan_compatibility_button.click()

    assert imports == [("C:/Mods/Source", "C:/Projects")]
    assert analyses == [("C:/Civ5", "C:/Generated/Test")]
    assert exports == [("C:/Civ5", "C:/Generated/Test", "C:/Reports/test.zip")]
    assert scans == ["C:/Civ5/MODS"]

    page.set_import_result("Import complete")
    page.set_diagnostics_result("Database.log contains an error", is_error=True)
    page.set_compatibility_result("No static overlaps found")
    assert page.import_result.toPlainText() == "Import complete"
    assert page.diagnostics_result.toPlainText() == "Database.log contains an error"
    assert page.compatibility_result.toPlainText() == "No static overlaps found"
    page.deleteLater()
