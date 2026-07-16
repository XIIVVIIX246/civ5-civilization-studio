from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

import civ5studio.application.localization as localization_module

from civ5studio.application.localization import (
    export_localization_csv,
    generate_localization_xml,
    import_localization_csv,
    load_localization_csv,
    save_localization_csv,
)


def test_localization_csv_round_trip_and_xml_are_deterministic() -> None:
    source = (
        'locale,tag,text\n'
        'en_US,TXT_KEY_TEST_GREETING,"Hello, world"\n'
        'FR_FR,TXT_KEY_TEST_GREETING,Bonjour\n'
    )
    imported = import_localization_csv(source)
    assert imported.is_valid, imported.issues
    exported = export_localization_csv(imported.entries)
    assert import_localization_csv(exported).entries == imported.entries
    xml = generate_localization_xml(imported.entries)
    root = ET.fromstring(xml)
    assert root.find("Language_en_US/Row/Text").text == "Hello, world"
    assert root.find("Language_FR_FR/Row/Text").text == "Bonjour"


def test_localization_rejects_unknown_locales_tags_and_duplicates() -> None:
    imported = import_localization_csv(
        "locale,tag,text\n"
        "xx_XX,TXT_KEY_VALID,Nope\n"
        "en_US,NOT_A_TEXT_KEY,Nope\n"
        "en_US,TXT_KEY_VALID,First\n"
        "en_US,TXT_KEY_VALID,Second\n"
    )
    assert not imported.is_valid
    assert {issue.code for issue in imported.issues} == {
        "localization.locale",
        "localization.tag",
        "localization.duplicate",
    }


def test_export_neutralizes_spreadsheet_formula_text() -> None:
    exported = export_localization_csv(
        {"en_US": {"TXT_KEY_FORMULA": "=HYPERLINK(\"bad\")"}}
    )
    assert "'=HYPERLINK" in exported
    imported = import_localization_csv(exported)
    assert imported.entries["en_US"]["TXT_KEY_FORMULA"] == '=HYPERLINK("bad")'


def test_localization_file_io_refuses_overwrite(tmp_path) -> None:
    path = tmp_path / "translations.csv"
    saved = save_localization_csv(
        path, {"FR_FR": {"TXT_KEY_TEST": "Bonjour"}}
    )
    assert load_localization_csv(saved).entries == {
        "FR_FR": {"TXT_KEY_TEST": "Bonjour"}
    }
    try:
        save_localization_csv(path, {})
    except FileExistsError:
        pass
    else:  # pragma: no cover - safety regression guard
        raise AssertionError("Localization export overwrote an existing file")


def test_localization_file_io_rejects_reparse_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "translations.csv"
    source.write_text("locale,tag,text\n", encoding="utf-8")
    original = localization_module._is_link_or_reparse
    monkeypatch.setattr(
        localization_module,
        "_is_link_or_reparse",
        lambda path: path == source or original(path),
    )

    with pytest.raises(ValueError, match="link or junction"):
        load_localization_csv(source)
    with pytest.raises(ValueError, match="link or junction"):
        save_localization_csv(source, {})
