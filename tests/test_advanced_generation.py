from __future__ import annotations

from civ5studio.application.advanced_content import update_advanced_extension
from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain import CivProject, UniqueUnitSpec
from civ5studio.generation.advanced import (
    advanced_capability_payload,
    generate_custom_unit_member_sql,
)


def test_custom_unit_member_sql_clones_complete_donor_behavior() -> None:
    project = CivProject(mod_name="Advanced", internal_prefix="ADV")
    unit = UniqueUnitSpec(
        key="GUARD",
        name="Guard",
        replaces_unit_class="UNITCLASS_WARRIOR",
        base_unit="UNIT_WARRIOR",
    )
    project.units = [unit]
    project = update_advanced_extension(
        project,
        {
            "localization": {"entries": {}},
            "unit_art": {
                "assignments": [
                    {
                        "unit_key": "GUARD",
                        "source_folder": "Assets/UnitArt/guard",
                        "fxsxml": "Guard.fxsxml",
                        "scale": 0.14,
                        "z_offset": 0.2,
                    }
                ]
            },
            "audio": {},
        },
    )
    sql = generate_custom_unit_member_sql(
        project,
        ReferenceCatalog.bundled(),
        unit,
        donor_unit="UNIT_WARRIOR",
        custom_art_type="ART_DEF_UNIT_ADV_GUARD",
    )
    assert "ArtDefine_UnitMemberInfos" in sql
    assert "ArtDefine_UnitMemberCombats" in sql
    assert "ArtDefine_UnitMemberCombatWeapons" in sql
    assert "Art/Units/GUARD/Guard.fxsxml" in sql
    assert "ORDER BY rowid LIMIT 1" in sql
    assert "DELETE FROM ArtDefine_UnitInfoMemberInfos" in sql


def test_advanced_capability_never_claims_runtime_success() -> None:
    project = CivProject(mod_name="Advanced", internal_prefix="ADV")
    project = update_advanced_extension(
        project,
        {
            "localization": {"entries": {}},
            "unit_art": {"assignments": []},
            "audio": {"peace_music": "Assets/Audio/Source/peace.mp3"},
        },
    )
    payload = advanced_capability_payload(project)
    assert payload["audio"]["runtime_status"] == "not_run"
