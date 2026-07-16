from __future__ import annotations

import struct
import sqlite3
import wave

from civ5studio.application.advanced_content import (
    materialize_advanced_sources,
    update_advanced_extension,
)
from civ5studio.application.unit_art_package import GR2_MAGIC
from civ5studio.build import BuildMode, BuildService
from civ5studio.generation import compile_project, validate_compiled_sql
from civ5studio.bnw import ReferenceCatalog
from civ5studio.generation.sqlite_validation import _create_schema, _seed_reference_rows


def _wav(path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(struct.pack("<h", 0) * 2205)


def test_advanced_sources_compile_validate_and_publish(sample_project, tmp_path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    package = external / "hussar"
    package.mkdir()
    (package / "Hussar.fxsxml").write_text(
        "<Asset><Model>Hussar.gr2</Model><Texture>Hussar.dds</Texture></Asset>",
        encoding="utf-8",
    )
    (package / "Hussar.gr2").write_bytes(GR2_MAGIC + b"Hussar.dds\0")
    (package / "Hussar.dds").write_bytes(b"DDS " + bytes(124))
    peace = external / "peace.wav"
    war = external / "war.wav"
    speech = external / "speech.wav"
    for path in (peace, war, speech):
        _wav(path)

    workspace = tmp_path / "project"
    workspace.mkdir()
    project = update_advanced_extension(
        sample_project,
        {
            "localization": {
                "entries": {
                    "FR_FR": {
                        "TXT_KEY_CIV_LITHUANIA_CUSTOM_DESC": "Lituanie",
                    }
                }
            },
            "unit_art": {
                "assignments": [
                    {
                        "unit_key": "WINGED_HUSSAR",
                        "unit_name": "Winged Hussar",
                        "unit_index": 0,
                        "source_folder": str(package),
                        "fxsxml": "Hussar.fxsxml",
                        "scale": 0.14,
                        "z_offset": 0.0,
                    }
                ]
            },
            "audio": {
                "peace_music": str(peace),
                "war_music": str(war),
                "dawn_of_man_speech": str(speech),
            },
        },
    )
    project = materialize_advanced_sources(project, workspace)
    compilation = compile_project(project, project_root=str(workspace))
    assert not validate_compiled_sql(compilation, project).errors
    assert "Localization/FR_FR.xml" in compilation.database_files
    assert "Core/Audio.sql" in compilation.database_files
    assert "Audio/LITHUANIA_CUSTOM_Peace.wav" in compilation.source_files
    assert "Art/Units/WINGED_HUSSAR/Hussar.fxsxml" in compilation.source_files
    assert "ArtDefine_UnitMemberCombatWeapons" in compilation.files["Core/Units.sql"]
    units_sql = compilation.files["Core/Units.sql"]
    assert "No custom Strategic View PNG; retain the donor map icon binding." in units_sql
    assert "SELECT 'ART_DEF_UNIT_WINGED_HUSSAR_LITHUANIA_CUSTOM', TileType, Asset" in units_sql

    catalog = ReferenceCatalog.bundled()
    connection = sqlite3.connect(":memory:")
    try:
        _create_schema(connection, catalog)
        _seed_reference_rows(connection, catalog)
        for relative in compilation.database_files:
            if relative.lower().endswith(".sql"):
                connection.executescript(compilation.files[relative])
        donor_rows = connection.execute(
            "SELECT TileType, Asset FROM ArtDefine_StrategicView "
            "WHERE StrategicViewType = "
            "(SELECT UnitArtInfo FROM Units WHERE Type = 'UNIT_LANCER')"
        ).fetchall()
        custom_rows = connection.execute(
            "SELECT TileType, Asset FROM ArtDefine_StrategicView "
            "WHERE StrategicViewType = ?",
            ("ART_DEF_UNIT_WINGED_HUSSAR_LITHUANIA_CUSTOM",),
        ).fetchall()
        assert custom_rows == donor_rows
    finally:
        connection.close()
    assert "<ReloadAudioSystem>1</ReloadAudioSystem>" in compilation.files[
        "Kingdom_Of_Lithuania.modinfo"
    ]

    result = BuildService().build(
        project,
        tmp_path / "output",
        source_root=workspace,
        mode=BuildMode.AVAILABLE,
        create_zip=False,
    )
    assert (result.published_path / "Audio/LITHUANIA_CUSTOM_Peace.wav").is_file()
    assert (result.published_path / "Art/Units/WINGED_HUSSAR/Hussar.gr2").is_file()
    assert (result.published_path / "Localization/FR_FR.xml").is_file()
