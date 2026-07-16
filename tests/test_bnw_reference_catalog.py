from __future__ import annotations

from civ5studio.bnw import ReferenceCatalog


EXPECTED_SOURCE_HASHES = {
    "Assets/DLC/Expansion2/Gameplay/XML/Terrain/CIV5Improvements.xml": (
        "9a23601c5a3f24e9a6da39893347a25a994b5b204bc03eedde8f174bd52f3056"
    ),
    "Assets/DLC/Expansion2/Gameplay/XML/Terrain/"
    "CIV5Improvements_Expansion2.xml": (
        "811fa25c04b0068b35c2556de7cecc4e86c1585cdaeea69e4a0bc946b038b514"
    ),
    "Assets/DLC/Expansion2/Gameplay/XML/Terrain/"
    "CIV5Improvements_Inherited_Expansion2.xml": (
        "6895d7a5077b0e6884f99461531294abe600417761f182d68d4dceff9c75a633"
    ),
    "Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5Builds.xml": (
        "b6d0160cfa40c2fda56761f83078d8984bad88a74e57d33ef8a6bf931d7f1926"
    ),
    "Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5Builds_Expansion2.xml": (
        "19efa57c700fb7d5173c9aa56772ff60f86ac02a91a5900c23aa0b6e486ab474"
    ),
    "Assets/DLC/Expansion2/Gameplay/XML/Units/"
    "CIV5Builds_Inherited_Expansion2.xml": (
        "2f22e4902f485339b39004153ca1bf9230423a0739c17662d915e5cef7e36b17"
    ),
}


def test_improvement_and_build_clone_contracts_cover_complete_expansion2_schema() -> None:
    catalog = ReferenceCatalog.bundled()
    improvement_contract = catalog.clone_contract("Improvements")
    build_contract = catalog.clone_contract("Builds")

    assert catalog.data["catalog_version"] == 3
    assert len(catalog.ordered_columns("Improvements")) == 57
    assert improvement_contract["identity_column"] == "Type"
    assert improvement_contract["child_key_column"] == "ImprovementType"
    assert improvement_contract["columns"] == list(
        catalog.ordered_columns("Improvements")
    )
    assert len(improvement_contract["child_tables"]) == 19
    for table, columns in improvement_contract["child_tables"].items():
        assert "ImprovementType" in columns
        assert tuple(columns) == catalog.ordered_columns(table)

    assert len(catalog.ordered_columns("Builds")) == 33
    assert build_contract["identity_column"] == "Type"
    assert build_contract["child_key_column"] == "BuildType"
    assert build_contract["columns"] == list(catalog.ordered_columns("Builds"))
    assert set(build_contract["child_tables"]) == {
        "BuildFeatures",
        "Build_TechTimeChanges",
    }
    for table, columns in build_contract["child_tables"].items():
        assert "BuildType" in columns
        assert tuple(columns) == catalog.ordered_columns(table)


def test_improvement_build_mapping_is_total_verified_and_contains_no_raw_rows() -> None:
    catalog = ReferenceCatalog.bundled()
    improvement_identities = catalog.donor_identities("Improvements")
    build_identities = catalog.donor_identities("Builds")

    assert len(catalog.improvements) == len(improvement_identities) == 25
    assert len(catalog.builds) == len(build_identities) == 31
    assert set(catalog.improvement_builds) == set(catalog.improvements)
    assert sum(bool(rows) for rows in catalog.improvement_builds.values()) == 22
    assert sum(len(rows) for rows in catalog.improvement_builds.values()) == 23
    assert catalog.builds_for_improvement("IMPROVEMENT_FISHING_BOATS") == (
        "BUILD_FISHING_BOATS",
        "BUILD_FISHING_BOATS_NO_KILL",
    )
    assert catalog.builds_for_improvement("IMPROVEMENT_BARBARIAN_CAMP") == ()
    assert catalog.builds_for_improvement("IMPROVEMENT_CITY_RUINS") == ()
    assert catalog.builds_for_improvement("IMPROVEMENT_GOODY_HUT") == ()

    for improvement, build_types in catalog.improvement_builds.items():
        for build_type in build_types:
            assert build_type in catalog.builds
            assert build_identities[build_type]["ImprovementType"] == improvement
    assert "donor_rows" not in catalog.data
    assert "donor_child_rows" not in catalog.data


def test_improvement_and_build_sources_have_exact_local_expansion2_provenance() -> None:
    catalog = ReferenceCatalog.bundled()
    evidence = {
        item["relative_path"]: item
        for item in catalog.provenance["source_evidence"]
        if item.get("entity") in {"Improvements", "Builds"}
    }

    assert set(evidence) == set(EXPECTED_SOURCE_HASHES)
    for relative_path, expected_hash in EXPECTED_SOURCE_HASHES.items():
        assert evidence[relative_path]["sha256"] == expected_hash
        assert evidence[relative_path]["bytes"] > 0
