from __future__ import annotations

from copy import deepcopy

from civ5studio.domain import (
    ImplementationKind,
    MechanicEffect,
    validate_project,
)


def test_complete_sample_has_no_source_errors(sample_project):
    report = validate_project(sample_project)
    assert report.is_valid
    assert report.issues == []


def test_unknown_bnw_references_are_errors(sample_project):
    project = deepcopy(sample_project)
    project.units[0].replaces_unit_class = "UNITCLASS_NOT_REAL"
    project.units[0].base_unit = "UNIT_NOT_REAL"
    project.units[0].prereq_tech = "TECH_NOT_REAL"
    project.units[0].free_promotions = ["PROMOTION_NOT_REAL"]
    report = validate_project(project)
    codes = {issue.code for issue in report.errors}
    assert "reference.unit_classes" in codes
    assert "reference.base-unit" in codes
    assert "reference.technologies" in codes
    assert "reference.promotions" in codes


def test_unsafe_portable_source_path_is_blocking(sample_project):
    project = deepcopy(sample_project)
    project.art.assets[0].source_png = "../outside.png"
    report = validate_project(project)
    assert report.has_code("path.unsafe")
    assert not report.is_valid


def test_missing_required_art_reports_the_editing_control_location(sample_project):
    project = deepcopy(sample_project)
    removed_roles = {
        ("leader_scene", "leader"),
        ("unique_unit_icon", f"unit:{project.units[0].key}"),
        ("unit_flag", f"unit:{project.units[0].key}"),
        ("unique_building_icon", f"building:{project.buildings[0].key}"),
    }
    project.art.assets = [
        asset
        for asset in project.art.assets
        if (asset.role.value, asset.subject_key) not in removed_roles
    ]

    report = validate_project(project)
    locations = {
        issue.path
        for issue in report.issues
        if issue.code == "art.required-role"
    }

    assert "leader.art.leader_scene" in locations
    assert "units[0].art.icon_source" in locations
    assert "units[0].art.unit_flag_source" in locations
    assert "buildings[0].art.icon_source" in locations


def test_unsupported_mechanics_warn_available_and_block_release(sample_project, tmp_path):
    project = deepcopy(sample_project)
    project.trait.effects.append(
        MechanicEffect(
            description="Gain a free wonder every turn.",
            implementation=ImplementationKind.UNSUPPORTED,
        )
    )
    available = validate_project(project)
    assert available.has_code("mechanic.unimplemented")
    assert not available.errors

    for asset in project.art.assets:
        source = tmp_path / asset.source_png
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
    strict = validate_project(project, strict_release=True, project_root=tmp_path)
    assert any(
        issue.code == "mechanic.unimplemented" for issue in strict.errors
    )


def test_duplicate_keys_and_replacement_classes_are_rejected(sample_project):
    project = deepcopy(sample_project)
    project.units.append(deepcopy(project.units[0]))
    report = validate_project(project)
    assert sum(issue.code == "id.duplicate" for issue in report.errors) >= 2


def test_existing_mod_snapshot_warns_in_draft_and_blocks_strict_release(
    sample_project,
) -> None:
    project = deepcopy(sample_project)
    project.extensions["existing_mod_import"] = {
        "import_format": "civ5studio.existing-mod-import"
    }

    draft = validate_project(project)
    issue = next(
        item for item in draft.issues if item.code == "existing-mod-import.release-blocked"
    )
    assert issue.severity.value == "warning"
    assert draft.is_valid

    strict = validate_project(project, strict_release=True)
    assert any(
        item.code == "existing-mod-import.release-blocked" for item in strict.errors
    )
