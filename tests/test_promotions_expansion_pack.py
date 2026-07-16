from __future__ import annotations

from copy import deepcopy
from hashlib import md5, sha256
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from civ5studio.application import project_from_ui, project_to_ui
from civ5studio.domain import dumps_project, project_from_dict, validate_project
from civ5studio.generation import compile_project, validate_compiled_sql
from civ5studio.integrations import (
    PEP_MOD_ID,
    PEP_MOD_NAME,
    PEP_MOD_VERSION,
    PromotionsExpansionPackCatalog,
)
from civ5studio.ui.main_window import MainWindow


REFERENCE_ROOT = Path(
    r"C:\Users\ExampleUser\Documents\My Games\Sid Meier's Civilization 5\Mods"
    r"\Promotions - Expansion Pack (v 9)"
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bundled_pep_v9_catalog_has_exact_identity_and_source_evidence() -> None:
    catalog = PromotionsExpansionPackCatalog.bundled()
    assert (catalog.mod_id, catalog.version, catalog.name) == (
        PEP_MOD_ID,
        PEP_MOD_VERSION,
        PEP_MOD_NAME,
    )
    assert len(catalog.promotions) == 17
    assert len(catalog.types) == 17
    assert catalog.get("PROMOTION_REPUTATION").display_name == "Reputation"  # type: ignore[union-attr]
    evidence = {item["relative_path"]: item for item in catalog.evidence}
    assert evidence["Promotions - Expansion Pack (v 9).modinfo"]["sha256"] == (
        "BB24A81BB1A1438B6786502E18CF962C4A618AC3863107F4A1D9E4AAB2672989"
    )
    assert evidence["PEP - INIT.xml"]["sha256"] == (
        "35F4669FDA56D57955B9A666CCC5EBD39F01920880BB59C45D3CDD0E3F1B879C"
    )
    assert evidence["PEP - INIT.xml"]["md5"] == (
        "C63EE07171BCD321E3DC65901CFA514B"
    )
    assert evidence["PEP - INIT.xml"]["modinfo_declared_md5"] == (
        "4B019768A27CF59ADC20060ECAB9E0A9"
    )
    # The developer workstation's installed source is optional at test time,
    # but when present it must still match the bundled evidence exactly.
    for relative, item in evidence.items():
        source = REFERENCE_ROOT / relative
        if source.is_file():
            assert sha256(source.read_bytes()).hexdigest().upper() == item["sha256"]
            if "md5" in item:
                assert md5(source.read_bytes()).hexdigest().upper() == item["md5"]


def test_disabled_pep_assignments_are_preserved_but_not_generated(sample_project) -> None:
    project = deepcopy(sample_project)
    project.dependencies.promotions_expansion_pack = False
    project.units[0].promotions_expansion_pack = ["PROMOTION_REPUTATION"]

    report = validate_project(project)
    assert report.is_valid
    assert report.has_code("dependency.pep-disabled")
    compilation = compile_project(project)
    assert "PROMOTION_REPUTATION" not in compilation.files["Core/Units.sql"]
    assert "Documentation/PROMOTIONS_EXPANSION_PACK_REFERENCE.json" not in compilation.files
    modinfo = ET.fromstring(compilation.files["Kingdom_Of_Lithuania.modinfo"])
    assert modinfo.find("./References/Mod") is None


def test_enabled_pep_assignment_generates_sql_reference_and_provenance(sample_project) -> None:
    project = deepcopy(sample_project)
    project.dependencies.promotions_expansion_pack = True
    project.units[0].promotions_expansion_pack = ["PROMOTION_REPUTATION"]

    compilation = compile_project(project)
    units_sql = compilation.files["Core/Units.sql"]
    assert "-- Promotions - Expansion Pack v9 assignment" in units_sql
    assert "'PROMOTION_REPUTATION'" in units_sql
    modinfo = ET.fromstring(compilation.files["Kingdom_Of_Lithuania.modinfo"])
    reference = modinfo.find("./References/Mod")
    assert reference is not None
    assert reference.attrib == {
        "id": PEP_MOD_ID,
        "minversion": "9",
        "maxversion": "9",
        "title": PEP_MOD_NAME,
    }
    provenance = json.loads(
        compilation.files["Documentation/PROMOTIONS_EXPANSION_PACK_REFERENCE.json"]
    )
    assert provenance["assigned_types"] == ["PROMOTION_REPUTATION"]
    assert provenance["mod"]["id"] == PEP_MOD_ID
    assert validate_compiled_sql(compilation, project).is_valid


def test_pep_dependency_and_assignments_round_trip_losslessly(sample_project) -> None:
    project = deepcopy(sample_project)
    project.dependencies.promotions_expansion_pack = True
    project.units[0].promotions_expansion_pack = [
        "PROMOTION_REPUTATION",
        "PROMOTION_MOUNTAIN",
    ]
    project.extensions["future_feature"] = {"unknown": [1, 2, 3]}

    restored = project_from_dict(json.loads(dumps_project(project)))
    assert restored.dependencies.promotions_expansion_pack is True
    assert restored.units[0].promotions_expansion_pack == [
        "PROMOTION_REPUTATION",
        "PROMOTION_MOUNTAIN",
    ]
    assert restored.extensions == project.extensions


def test_dedicated_gui_page_round_trips_without_polluting_vanilla_choices(
    sample_project, tmp_path
) -> None:
    _app()
    project = deepcopy(sample_project)
    project.dependencies.promotions_expansion_pack = True
    project.units[0].promotions_expansion_pack = ["PROMOTION_REPUTATION"]
    catalog = PromotionsExpansionPackCatalog.bundled()

    window = MainWindow()
    window.set_reference_catalog(
        civilizations=[project.civilization.base_civilization],
        unit_templates=[
            (project.units[0].replaces_unit_class, project.units[0].base_unit)
        ],
        building_templates=[
            (
                project.buildings[0].replaces_building_class,
                project.buildings[0].base_building,
            )
        ],
        yields=["YIELD_CULTURE"],
        promotions=["PROMOTION_MARCH"],
        promotions_expansion_pack=catalog.ui_entries(),
    )
    window.load_values(project_to_ui(project, tmp_path), tmp_path / "project.json")

    vanilla_editor = window.pages[3].uniques.promotions  # type: ignore[attr-defined]
    assert "PROMOTION_REPUTATION" not in vanilla_editor.references
    pep_page = window.pages[4]
    assert pep_page.enabled.isChecked() is True  # type: ignore[attr-defined]
    assert pep_page.values()["assignments"][0]["promotion_type"] == "PROMOTION_REPUTATION"  # type: ignore[attr-defined]

    round_tripped = project_from_ui(window.collect_values(), existing=project)
    assert round_tripped.dependencies.promotions_expansion_pack is True
    assert round_tripped.units[0].promotions_expansion_pack == [
        "PROMOTION_REPUTATION"
    ]
    window.mark_clean()
    window.deleteLater()


def test_pep_assignment_never_moves_to_a_replacement_unit_at_the_same_index(
    sample_project, tmp_path
) -> None:
    _app()
    project = deepcopy(sample_project)
    project.dependencies.promotions_expansion_pack = True
    project.units[0].promotions_expansion_pack = ["PROMOTION_REPUTATION"]
    window = MainWindow()
    window.set_reference_catalog(
        civilizations=[project.civilization.base_civilization],
        unit_templates=[
            (project.units[0].replaces_unit_class, project.units[0].base_unit)
        ],
        building_templates=[],
        yields=["YIELD_CULTURE"],
        promotions_expansion_pack=PromotionsExpansionPackCatalog.bundled().ui_entries(),
    )
    window.load_values(project_to_ui(project, tmp_path), tmp_path / "project.json")

    replacement = deepcopy(window.pages[3].values()["uniques"][0])
    # Removing and adding a different unit has no immutable rename token.
    # Editing the Expert key in place deliberately retains this token.
    replacement.pop("original_key", None)
    replacement["key"] = "REPLACEMENT_UNIT"
    replacement["name"] = "Replacement Unit"
    window.pages[3].load_values(  # type: ignore[attr-defined]
        {"trait": window.pages[3].values()["trait"], "uniques": [replacement]}
    )
    window.pages[4].set_units([replacement])  # type: ignore[attr-defined]

    preserved = window.pages[4].values()["assignments"][0]  # type: ignore[attr-defined]
    assert preserved["unit_key"] == project.units[0].key
    rebuilt = project_from_ui(window.collect_values())
    assert rebuilt.units[0].key == "REPLACEMENT_UNIT"
    assert rebuilt.units[0].promotions_expansion_pack == []
    window.mark_clean()
    window.deleteLater()
