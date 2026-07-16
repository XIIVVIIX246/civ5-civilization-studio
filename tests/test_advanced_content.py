from __future__ import annotations

import struct
import wave

from civ5studio.application.advanced_content import (
    advanced_content,
    advanced_to_ui,
    audio_sql,
    build_copies,
    localization_xml_files,
    materialize_advanced_sources,
    update_advanced_extension,
    validate_advanced_content,
)
from civ5studio.application.unit_art_package import GR2_MAGIC
from civ5studio.domain import CivProject, UniqueUnitSpec


def _project() -> CivProject:
    project = CivProject(mod_name="Advanced", internal_prefix="ADV")
    project.units = [
        UniqueUnitSpec(
            key="GUARD",
            name="Guard",
            replaces_unit_class="UNITCLASS_WARRIOR",
            base_unit="UNIT_WARRIOR",
        )
    ]
    return project


def _wav(path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(struct.pack("<h", 0) * 2205)


def _unit_package(root) -> None:
    root.mkdir()
    (root / "Guard.fxsxml").write_text(
        "<Asset><Model file='Guard.gr2'/><Texture>Guard.dds</Texture></Asset>",
        encoding="utf-8",
    )
    (root / "Guard.gr2").write_bytes(GR2_MAGIC + b"Guard.dds\0")
    (root / "Guard.dds").write_bytes(b"DDS " + bytes(124))


def test_advanced_extension_round_trips_and_generates_text(tmp_path) -> None:
    project = update_advanced_extension(
        _project(),
        {
            "localization": {
                "entries": {
                    "FR_FR": {"TXT_KEY_ADV_NAME": "Avance"},
                }
            },
            "unit_art": {"assignments": []},
            "audio": {},
        },
    )
    assert advanced_content(project).localization["FR_FR"]["TXT_KEY_ADV_NAME"] == "Avance"
    xml = localization_xml_files(project)["Localization/FR_FR.xml"]
    assert '<Replace Tag="TXT_KEY_ADV_NAME">' in xml
    assert advanced_to_ui(project, tmp_path)["localization"]["entries"] == {
        "FR_FR": {"TXT_KEY_ADV_NAME": "Avance"}
    }


def test_advanced_ui_edit_preserves_future_extension_fields_by_stable_unit_key() -> None:
    project = _project()
    project.units.append(
        UniqueUnitSpec(
            key="SCOUT",
            name="Scout",
            replaces_unit_class="UNITCLASS_SCOUT",
            base_unit="UNIT_SCOUT",
        )
    )
    project.extensions["advanced_content"] = {
        "format": "civ5studio.advanced-content",
        "format_version": 7,
        "future_root": {"enabled": True},
        "localization": {
            "entries": {"FR_FR": {"TXT_KEY_OLD": "Ancien"}},
            "future_fallback": {"locale": "EN_US"},
        },
        "unit_art": {
            "assignments": [
                {
                    "unit_key": "GUARD",
                    "unit_name": "Old Guard",
                    "unit_index": 0,
                    "source_folder": "old/guard",
                    "fxsxml": "old.fxsxml",
                    "scale": 1.0,
                    "z_offset": 0.0,
                    "future_lods": {"high": 3},
                },
                {
                    "unit_key": "SCOUT",
                    "unit_name": "Old Scout",
                    "unit_index": 1,
                    "source_folder": "old/scout",
                    "fxsxml": "old.fxsxml",
                    "scale": 1.0,
                    "z_offset": 0.0,
                    "future_lods": {"high": 1},
                },
            ],
            "future_policy": {"preload": True},
        },
        "audio": {
            "peace_music": "old-peace.wav",
            "war_music": "old-war.wav",
            "dawn_of_man_speech": "",
            "future_streaming": {"buffer_kib": 512},
        },
    }

    updated = update_advanced_extension(
        project,
        {
            "localization": {
                "entries": {"FR_FR": {"TXT_KEY_NEW": "Nouveau"}}
            },
            "unit_art": {
                # Reordering must not transfer unknown metadata by position.
                "assignments": [
                    {
                        "unit_key": "SCOUT",
                        "unit_name": "New Scout",
                        "unit_index": 0,
                        "source_folder": "new/scout",
                        "fxsxml": "Scout.fxsxml",
                        "scale": 0.5,
                        "z_offset": 0.1,
                    },
                    {
                        "unit_key": "GUARD",
                        "unit_name": "New Guard",
                        "unit_index": 1,
                        "source_folder": "new/guard",
                        "fxsxml": "Guard.fxsxml",
                        "scale": 0.75,
                        "z_offset": 0.2,
                    },
                ]
            },
            "audio": {
                "peace_music": "new-peace.wav",
                "war_music": "new-war.wav",
                "dawn_of_man_speech": "new-speech.wav",
            },
        },
    )

    extension = updated.extensions["advanced_content"]
    assert extension["format_version"] == 7
    assert extension["future_root"] == {"enabled": True}
    assert extension["localization"] == {
        "entries": {"FR_FR": {"TXT_KEY_NEW": "Nouveau"}},
        "future_fallback": {"locale": "EN_US"},
    }
    assert extension["unit_art"]["future_policy"] == {"preload": True}
    assert extension["unit_art"]["assignments"][0]["future_lods"] == {"high": 1}
    assert extension["unit_art"]["assignments"][1]["future_lods"] == {"high": 3}
    assert extension["unit_art"]["assignments"][0]["unit_name"] == "New Scout"
    assert extension["audio"]["future_streaming"] == {"buffer_kib": 512}
    assert extension["audio"]["peace_music"] == "new-peace.wav"

    # The update is copy-on-write, including preserved nested values.
    assert project.extensions["advanced_content"]["localization"]["entries"] == {
        "FR_FR": {"TXT_KEY_OLD": "Ancien"}
    }


def test_materializes_audio_and_unit_package_then_builds_copy_map(tmp_path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    package = external / "unit"
    _unit_package(package)
    peace = external / "peace.wav"
    war = external / "war.wav"
    _wav(peace)
    _wav(war)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = update_advanced_extension(
        _project(),
        {
            "localization": {"entries": {}},
            "unit_art": {
                "assignments": [
                    {
                        "unit_key": "GUARD",
                        "unit_name": "Guard",
                        "unit_index": 0,
                        "source_folder": str(package),
                        "fxsxml": "Guard.fxsxml",
                        "scale": 0.14,
                        "z_offset": 0.0,
                    }
                ]
            },
            "audio": {
                "peace_music": str(peace),
                "war_music": str(war),
                "dawn_of_man_speech": "",
            },
        },
    )
    portable = materialize_advanced_sources(project, workspace)
    content = advanced_content(portable)
    assert content.unit_art[0].source_folder.startswith("Assets/UnitArt/")
    assert content.audio.peace_music.startswith("Assets/Audio/Source/")
    assert not [
        issue for issue in validate_advanced_content(portable, workspace)
        if issue.severity == "ERROR"
    ]
    copies = build_copies(portable, workspace)
    outputs = {item.output_relative for item in copies}
    assert "Art/Units/GUARD/Guard.fxsxml" in outputs
    assert "Audio/ADV_Peace.wav" in outputs
    assert "Audio/ADV_War.wav" in outputs
    sql = audio_sql(portable)
    assert "AS2D_LEADER_MUSIC_ADV_PEACE" in sql
    assert "SND_LEADER_MUSIC_ADV_WAR" in sql


def test_materialization_preserves_future_extension_fields(tmp_path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    package = external / "unit"
    _unit_package(package)
    peace = external / "peace.wav"
    war = external / "war.wav"
    _wav(peace)
    _wav(war)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = update_advanced_extension(
        _project(),
        {
            "localization": {
                "entries": {"FR_FR": {"TXT_KEY_ADV_NAME": "Avance"}}
            },
            "unit_art": {
                "assignments": [
                    {
                        "unit_key": "GUARD",
                        "unit_name": "Guard",
                        "unit_index": 0,
                        "source_folder": str(package),
                        "fxsxml": "Guard.fxsxml",
                        "scale": 0.14,
                        "z_offset": 0.0,
                    }
                ]
            },
            "audio": {
                "peace_music": str(peace),
                "war_music": str(war),
                "dawn_of_man_speech": "",
            },
        },
    )
    extension = project.extensions["advanced_content"]
    extension["format_version"] = 8
    extension["future_root"] = {"mode": "future"}
    extension["localization"]["future_fallback"] = "EN_US"
    extension["unit_art"]["future_policy"] = {"preload": True}
    extension["unit_art"]["assignments"][0]["future_lods"] = {"high": 4}
    extension["audio"]["future_streaming"] = {"buffer_kib": 256}

    portable = materialize_advanced_sources(project, workspace)
    persisted = portable.extensions["advanced_content"]

    assert persisted["format_version"] == 8
    assert persisted["future_root"] == {"mode": "future"}
    assert persisted["localization"]["future_fallback"] == "EN_US"
    assert persisted["unit_art"]["future_policy"] == {"preload": True}
    assert persisted["unit_art"]["assignments"][0]["future_lods"] == {"high": 4}
    assert persisted["audio"]["future_streaming"] == {"buffer_kib": 256}
    assert persisted["unit_art"]["assignments"][0]["source_folder"].startswith(
        "Assets/UnitArt/"
    )
    assert persisted["audio"]["peace_music"].startswith("Assets/Audio/Source/")


def test_invalid_advanced_values_report_errors(tmp_path) -> None:
    project = update_advanced_extension(
        _project(),
        {
            "localization": {"entries": {"xx_XX": {"BAD": "x"}}},
            "unit_art": {
                "assignments": [
                    {
                        "unit_key": "MISSING",
                        "source_folder": "Assets/UnitArt/missing",
                        "fxsxml": "x.fxsxml",
                    }
                ]
            },
            "audio": {"peace_music": "missing.mp3"},
        },
    )
    codes = {item.code for item in validate_advanced_content(project, tmp_path)}
    assert {"localization.locale", "localization.tag", "unit-art.unknown-unit", "audio.missing"} <= codes
