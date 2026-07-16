"""Build the bundled BNW donor/schema catalog from a local Expansion2 install.

The generated catalog contains the complete ``Units``, ``Buildings``,
``Improvements``, and ``Builds`` table surfaces, every related child table
keyed by the corresponding Type foreign key, and the verified donor identities
used by Civilization Studio.  Raw Firaxis rows and XML are not copied into the
application; hashes and relative source paths provide provenance for the
derived catalog.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


CATALOG_FORMAT = "civ5studio.bnw-reference"
CATALOG_VERSION = 3
DEFAULT_GAME_ROOT = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Sid Meier's Civilization V"
)
SOURCE_FILES = {
    "Units": (
        Path("Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5Units.xml"),
        Path("Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5Units_Expansion2.xml"),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Units/"
            "CIV5Units_Inherited_Expansion2.xml"
        ),
    ),
    "Buildings": (
        Path("Assets/DLC/Expansion2/Gameplay/XML/Buildings/CIV5Buildings.xml"),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Buildings/"
            "CIV5Buildings_Expansion2.xml"
        ),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Buildings/"
            "CIV5Buildings_Inherited_Expansion2.xml"
        ),
    ),
    "Improvements": (
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Terrain/CIV5Improvements.xml"
        ),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Terrain/"
            "CIV5Improvements_Expansion2.xml"
        ),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Terrain/"
            "CIV5Improvements_Inherited_Expansion2.xml"
        ),
    ),
    "Builds": (
        Path("Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5Builds.xml"),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5Builds_Expansion2.xml"
        ),
        Path(
            "Assets/DLC/Expansion2/Gameplay/XML/Units/"
            "CIV5Builds_Inherited_Expansion2.xml"
        ),
    ),
}
CHILD_KEYS = {
    "Units": "UnitType",
    "Buildings": "BuildingType",
    "Improvements": "ImprovementType",
    "Builds": "BuildType",
}
UNIT_PROMOTIONS_SOURCE = Path(
    "Assets/DLC/Expansion2/Gameplay/XML/Units/CIV5UnitPromotions.xml"
)
ENGINE_SCHEMA_SOURCE = Path("Assets/SQL/Civ5EngineDatabaseSchema.sql")
ENGINE_ART_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "ArtDefine_UnitInfos": [
        {"name": "Type", "type": "text", "notnull": True, "primarykey": True},
        {"name": "DamageStates", "type": "integer"},
        {"name": "Formation", "type": "text"},
        {"name": "UnitFlagAtlas", "type": "text"},
        {"name": "UnitFlagIconOffset", "type": "integer"},
        {"name": "IconAtlas", "type": "text"},
        {"name": "PortraitIndex", "type": "integer"},
    ],
    "ArtDefine_UnitInfoMemberInfos": [
        {"name": "UnitInfoType", "type": "text"},
        {"name": "UnitMemberInfoType", "type": "text"},
        {"name": "NumMembers", "type": "integer"},
    ],
    "ArtDefine_UnitMemberInfos": [
        {"name": "Type", "type": "text", "notnull": True, "primarykey": True},
        {"name": "Scale", "type": "real"},
        {"name": "ZOffset", "type": "real"},
        {"name": "Domain", "type": "text"},
        {"name": "Model", "type": "text", "notnull": True},
        {"name": "MaterialTypeTag", "type": "text"},
        {"name": "MaterialTypeSoundOverrideTag", "type": "text"},
    ],
    "ArtDefine_UnitMemberCombats": [
        {"name": name, "type": "text" if name in {"UnitMemberType", "EnableActions", "DisableActions", "RushAttackFormation"} else "real"}
        for name in (
            "UnitMemberType", "EnableActions", "DisableActions", "MoveRadius",
            "ShortMoveRadius", "ChargeRadius", "AttackRadius", "RangedAttackRadius",
            "MoveRate", "ShortMoveRate", "TurnRateMin", "TurnRateMax",
            "TurnFacingRateMin", "TurnFacingRateMax", "RollRateMin", "RollRateMax",
            "PitchRateMin", "PitchRateMax", "LOSRadiusScale", "TargetRadius",
            "TargetHeight", "HasShortRangedAttack", "HasLongRangedAttack",
            "HasLeftRightAttack", "HasStationaryMelee", "HasStationaryRangedAttack",
            "HasRefaceAfterCombat", "ReformBeforeCombat", "HasIndependentWeaponFacing",
            "HasOpponentTracking", "HasCollisionAttack", "AttackAltitude",
            "AltitudeDecelerationDistance", "OnlyTurnInMovementActions",
            "RushAttackFormation", "LastToDie",
        )
    ],
    "ArtDefine_UnitMemberCombatWeapons": [
        {"name": name, "type": "text" if name in {"UnitMemberType", "HitEffect", "WeaponTypeTag", "WeaponTypeSoundOverrideTag"} else "real"}
        for name in (
            "UnitMemberType", "Index", "SubIndex", "ID", "VisKillStrengthMin",
            "VisKillStrengthMax", "ProjectileSpeed", "ProjectileTurnRateMin",
            "ProjectileTurnRateMax", "HitEffect", "HitEffectScale", "HitRadius",
            "ProjectileChildEffectScale", "AreaDamageDelay", "ContinuousFire",
            "WaitForEffectCompletion", "TargetGround", "IsDropped", "WeaponTypeTag",
            "WeaponTypeSoundOverrideTag", "MissTargetSlopRadius",
        )
    ],
    "ArtDefine_StrategicView": [
        {"name": "StrategicViewType", "type": "text"},
        {"name": "TileType", "type": "text", "notnull": True},
        {"name": "Asset", "type": "text", "notnull": True},
    ],
    "Audio_Sounds": [
        {"name": "SoundID", "type": "text", "primarykey": True},
        {"name": "FileName", "type": "text", "notnull": True},
        {"name": "LoadType", "type": "text"},
        {"name": "OnlyLoadOneVariationEachTime", "type": "integer"},
        {"name": "DontCache", "type": "integer"},
    ],
    "Audio_2DSounds": [
        {"name": name, "type": "text" if name in {"ScriptID", "SoundID", "SoundType"} else "real"}
        for name in (
            "ScriptID", "SoundID", "SoundType", "MaxVolume", "MinVolume", "Looping",
            "DryLevel", "WetLevel", "StartFromRandomPosition", "DontPlayMoreThan",
            "OnlyTriggerOnUnitRuns", "PercentChanceOfPlaying", "DontPlay",
            "DontTriggerDuplicates", "DontTriggerDuplicatesOnUnits",
            "MinTimeMustNotPlayAgain", "MaxTimeMustNotPlayAgain", "IsMusic",
            "MinTimeDelay", "MaxTimeDelay", "TaperSoundtrackVolume", "PitchChangeDown",
            "PitchChangeUp", "Priority", "MinRightPan", "MaxRightPan", "MinLeftPan",
            "MaxLeftPan",
        )
    ],
}


def _text(element: ET.Element) -> str:
    return (element.text or "").strip()


def _row(element: ET.Element) -> dict[str, str]:
    return {child.tag: _text(child) for child in element}


def _schema(root: ET.Element) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for table in root.findall("Table"):
        name = table.get("name", "").strip()
        if not name:
            continue
        columns: list[dict[str, Any]] = []
        for column in table.findall("Column"):
            values: dict[str, Any] = {
                "name": column.get("name", "").strip(),
                "type": column.get("type", "text").strip().lower(),
            }
            for attribute in (
                "default",
                "reference",
                "primarykey",
                "autoincrement",
                "notnull",
                "unique",
            ):
                if attribute in column.attrib:
                    raw = column.attrib[attribute].strip()
                    values[attribute] = (
                        raw.lower() == "true"
                        if attribute
                        in {"primarykey", "autoincrement", "notnull", "unique"}
                        else raw
                    )
            if values["name"]:
                columns.append(values)
        result[name] = columns
    return result


def _criteria(element: ET.Element | None) -> dict[str, str | None]:
    if element is None:
        return {}
    values: dict[str, str | None] = {
        key: value.strip() for key, value in element.attrib.items()
    }
    values.update(
        {child.tag: _text(child) if child.text is not None else None for child in element}
    )
    return values


def _matches(row: dict[str, str | None], criteria: dict[str, str | None]) -> bool:
    return all(row.get(key) == value for key, value in criteria.items())


def _apply_data(
    result: dict[str, list[dict[str, str | None]]], root: ET.Element
) -> None:
    """Apply Firaxis Row/Replace/Update/Delete operations in XML load order."""

    for section in root:
        rows = result.setdefault(section.tag, [])
        for operation in section:
            if operation.tag == "Row":
                rows.append(_criteria(operation))
            elif operation.tag == "Replace":
                replacement = _criteria(operation)
                identity = replacement.get("Type")
                if identity:
                    rows[:] = [item for item in rows if item.get("Type") != identity]
                elif replacement:
                    rows[:] = [item for item in rows if item != replacement]
                rows.append(replacement)
            elif operation.tag == "Delete":
                criteria = _criteria(operation)
                if criteria:
                    rows[:] = [item for item in rows if not _matches(item, criteria)]
            elif operation.tag == "Update":
                where = _criteria(operation.find("Where"))
                values = _criteria(operation.find("Set"))
                for item in rows:
                    if _matches(item, where):
                        item.update(values)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verified_gameplay_schemas(
    game_root: Path, target_tables: set[str]
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Resolve table definitions in vanilla -> G&K -> BNW load order."""

    roots = (
        Path("Assets/Gameplay/XML"),
        Path("Assets/DLC/Expansion/Gameplay/XML"),
        Path("Assets/DLC/Expansion2/Gameplay/XML"),
    )
    resolved: dict[str, list[dict[str, Any]]] = {}
    sources: dict[str, Path] = {}
    for relative_root in roots:
        root = (game_root / relative_root).resolve()
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.xml")):
            try:
                parsed = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            for table, definitions in _schema(parsed).items():
                if table in target_tables:
                    resolved[table] = definitions
                    sources[table] = path
    grouped: dict[Path, list[str]] = {}
    for table, path in sources.items():
        grouped.setdefault(path, []).append(table)
    evidence = [
        {
            "relative_path": path.relative_to(game_root).as_posix(),
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "tables": sorted(tables),
        }
        for path, tables in sorted(grouped.items(), key=lambda item: str(item[0]))
    ]
    return resolved, evidence


def build_catalog(
    game_root: Path,
    base_catalog: Path,
) -> dict[str, Any]:
    game_root = game_root.resolve()
    data = json.loads(base_catalog.read_text(encoding="utf-8"))
    if data.get("catalog_format") != CATALOG_FORMAT:
        raise ValueError(f"Unexpected base catalog format: {base_catalog}")

    complete_schema: dict[str, list[dict[str, Any]]] = {}
    donor_rows: dict[str, dict[str, dict[str, str | None]]] = {}
    donor_child_rows: dict[str, list[dict[str, str | None]]] = {}
    clone_contracts: dict[str, dict[str, Any]] = {}
    source_evidence: list[dict[str, Any]] = []

    for entity_table, relatives in SOURCE_FILES.items():
        schemas: dict[str, list[dict[str, Any]]] = {}
        sections: dict[str, list[dict[str, str | None]]] = {}
        paths: list[Path] = []
        for relative in relatives:
            path = (game_root / relative).resolve()
            if not path.is_file():
                raise FileNotFoundError(
                    f"Required Expansion2 reference is missing: {path}"
                )
            root = ET.parse(path).getroot()
            schemas.update(_schema(root))
            _apply_data(sections, root)
            paths.append(path)
            source_evidence.append(
                {
                    "entity": entity_table,
                    "relative_path": relative.as_posix(),
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
        if entity_table not in schemas or entity_table not in sections:
            raise ValueError(
                f"Expansion2 sources do not define and populate {entity_table}"
            )

        key_column = CHILD_KEYS[entity_table]
        child_tables = {
            table: [column["name"] for column in columns]
            for table, columns in schemas.items()
            if table != entity_table
            and key_column in {column["name"] for column in columns}
        }
        complete_schema.update(
            {
                table: columns
                for table, columns in schemas.items()
                if table == entity_table or table in child_tables
            }
        )
        donor_rows[entity_table] = {
            row["Type"]: row for row in sections[entity_table] if row.get("Type")
        }
        for table in child_tables:
            donor_child_rows[table] = list(sections.get(table, []))
        clone_contracts[entity_table] = {
            "identity_column": "Type",
            "child_key_column": key_column,
            "columns": [column["name"] for column in schemas[entity_table]],
            "child_tables": child_tables,
        }
        source_evidence[-1].update(
            {
                "merged_entity_columns": len(schemas[entity_table]),
                "merged_entity_rows": len(donor_rows[entity_table]),
                "merged_child_tables": len(child_tables),
            }
        )

    # This reverse relationship is defined in the promotions schema rather
    # than CIV5Units.xml, but it still points directly at Units.Type and must
    # follow a custom civilian unit donor.
    promotions_path = (game_root / UNIT_PROMOTIONS_SOURCE).resolve()
    if not promotions_path.is_file():
        raise FileNotFoundError(
            f"Required Expansion2 reference is missing: {promotions_path}"
        )
    promotions_root = ET.parse(promotions_path).getroot()
    promotions_schema = _schema(promotions_root)
    civilian_table = "UnitPromotions_CivilianUnitType"
    if civilian_table not in promotions_schema:
        raise ValueError(f"Expansion2 promotion schema lacks {civilian_table}")
    complete_schema[civilian_table] = promotions_schema[civilian_table]
    source_evidence.append(
        {
            "entity": "Units.external-child",
            "relative_path": UNIT_PROMOTIONS_SOURCE.as_posix(),
            "sha256": _sha256(promotions_path),
            "bytes": promotions_path.stat().st_size,
            "verified_table": civilian_table,
        }
    )

    engine_schema_path = (game_root / ENGINE_SCHEMA_SOURCE).resolve()
    if not engine_schema_path.is_file():
        raise FileNotFoundError(
            f"Required engine schema reference is missing: {engine_schema_path}"
        )
    engine_schema_text = engine_schema_path.read_text(encoding="utf-8-sig")
    for table in ENGINE_ART_SCHEMAS:
        if f"CREATE TABLE {table}" not in engine_schema_text:
            raise ValueError(f"Engine schema no longer defines {table}")
    complete_schema.update(ENGINE_ART_SCHEMAS)
    source_evidence.append(
        {
            "entity": "Engine art tables",
            "relative_path": ENGINE_SCHEMA_SOURCE.as_posix(),
            "sha256": _sha256(engine_schema_path),
            "bytes": engine_schema_path.stat().st_size,
            "verified_tables": sorted(ENGINE_ART_SCHEMAS),
        }
    )

    target_tables = set(data.get("tables", {})) | set(complete_schema) | {
        "ArtDefine_UnitInfos",
        "ArtDefine_UnitInfoMemberInfos",
        "ArtDefine_StrategicView",
    }
    gameplay_schemas, schema_evidence = _verified_gameplay_schemas(
        game_root, target_tables
    )
    complete_schema.update(gameplay_schemas)

    def active_mapping(
        rows: dict[str, dict[str, str | None]],
        class_column: str,
        class_prefix: str,
        type_prefix: str,
        previous: dict[str, str],
    ) -> dict[str, str]:
        candidates: dict[str, list[str]] = {}
        for identity, row in rows.items():
            class_name = row.get(class_column)
            if class_name:
                candidates.setdefault(str(class_name), []).append(identity)
        result: dict[str, str] = {}
        for class_name, identities in candidates.items():
            expected = class_name.replace(class_prefix, type_prefix, 1)
            preferred = previous.get(class_name, "")
            if expected in identities:
                result[class_name] = expected
            elif preferred in identities:
                result[class_name] = preferred
            else:
                result[class_name] = sorted(identities)[0]
        return result

    unit_mapping = active_mapping(
        donor_rows["Units"],
        "Class",
        "UNITCLASS_",
        "UNIT_",
        dict(data.get("unit_base_overrides", {})),
    )
    building_mapping = active_mapping(
        donor_rows["Buildings"],
        "BuildingClass",
        "BUILDINGCLASS_",
        "BUILDING_",
        dict(data.get("building_base_overrides", {})),
    )
    data["unit_classes"] = sorted(unit_mapping)
    data["building_classes"] = sorted(building_mapping)
    data["unit_base_overrides"] = {
        key: value
        for key, value in unit_mapping.items()
        if value != key.replace("UNITCLASS_", "UNIT_", 1)
    }
    data["building_base_overrides"] = {
        key: value
        for key, value in building_mapping.items()
        if value != key.replace("BUILDINGCLASS_", "BUILDING_", 1)
    }

    unit_overrides = dict(data.get("unit_base_overrides", {}))
    unit_bases = {
        str(unit_overrides.get(value, str(value).replace("UNITCLASS_", "UNIT_", 1)))
        for value in data.get("unit_classes", [])
    }
    building_overrides = dict(data.get("building_base_overrides", {}))
    building_bases = {
        str(
            building_overrides.get(
                value, str(value).replace("BUILDINGCLASS_", "BUILDING_", 1)
            )
        )
        for value in data.get("building_classes", [])
    }
    missing_units = sorted(unit_bases - donor_rows["Units"].keys())
    missing_buildings = sorted(building_bases - donor_rows["Buildings"].keys())
    if missing_units or missing_buildings:
        details = []
        if missing_units:
            details.append(f"unit donors: {', '.join(missing_units)}")
        if missing_buildings:
            details.append(f"building donors: {', '.join(missing_buildings)}")
        raise ValueError("Catalog mappings lack Expansion2 donor rows for " + "; ".join(details))

    improvements = sorted(donor_rows["Improvements"])
    builds = sorted(donor_rows["Builds"])
    improvement_builds: dict[str, list[str]] = {
        improvement: [] for improvement in improvements
    }
    for build_type, row in donor_rows["Builds"].items():
        improvement_type = row.get("ImprovementType")
        if not improvement_type:
            continue
        if improvement_type not in improvement_builds:
            raise ValueError(
                f"Build {build_type} references unknown improvement {improvement_type}"
            )
        improvement_builds[improvement_type].append(build_type)
    improvement_builds = {
        improvement: sorted(build_types)
        for improvement, build_types in sorted(improvement_builds.items())
    }

    tables = dict(data.get("tables", {}))
    for table, columns in complete_schema.items():
        tables[table] = [column["name"] for column in columns]
    donor_identities = {
        "Units": {
            identity: {
                "Class": row.get("Class"),
                "Description": row.get("Description"),
            }
            for identity, row in donor_rows["Units"].items()
        },
        "Buildings": {
            identity: {
                "BuildingClass": row.get("BuildingClass"),
                "Description": row.get("Description"),
            }
            for identity, row in donor_rows["Buildings"].items()
        },
        "Improvements": {
            identity: {
                "Description": row.get("Description"),
                "CivilizationType": row.get("CivilizationType"),
            }
            for identity, row in donor_rows["Improvements"].items()
        },
        "Builds": {
            identity: {
                "ImprovementType": row.get("ImprovementType"),
                "Description": row.get("Description"),
            }
            for identity, row in donor_rows["Builds"].items()
        },
    }
    data.update(
        {
            "catalog_version": CATALOG_VERSION,
            "tables": tables,
            "schema_definitions": complete_schema,
            "clone_contracts": clone_contracts,
            "donor_identities": donor_identities,
            "improvements": improvements,
            "builds": builds,
            "improvement_builds": improvement_builds,
        }
    )
    trait_definitions = complete_schema.get("Traits", [])
    data["trait_columns"] = sorted(
        str(item["name"])
        for item in trait_definitions
        if item.get("type") in {"integer", "boolean"}
        and item.get("name") not in {"ID"}
    )
    data.pop("donor_rows", None)
    data.pop("donor_child_rows", None)
    provenance = dict(data.get("provenance", {}))
    provenance.update(
        {
            "authority": "Local Sid Meier's Civilization V Expansion2 XML",
            "generator": "tools/build_bnw_reference_catalog.py",
            "source_evidence": source_evidence,
            "schema_evidence": schema_evidence,
            "schema_fallbacks": {
                "Language_en_US": (
                    "Localization database surface; not part of the gameplay cache."
                ),
                "UnitGameplay2DScripts": (
                    "Engine-created gameplay table; verified separately against a "
                    "read-only BNW debug database clone."
                ),
            },
            "curation": (
                "Complete generated-table schemas and clone contracts for Units, "
                "Buildings, Improvements, and Builds, plus donor identity and "
                "improvement-to-build mappings derived from the local "
                "vanilla/G&K/BNW XML load order. Raw Firaxis rows are not bundled."
            ),
        }
    )
    data["provenance"] = provenance
    return data


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument(
        "--base-catalog",
        type=Path,
        default=repo_root / "src/civ5studio/data/bnw/reference_catalog.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "src/civ5studio/data/bnw/reference_catalog.json",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    catalog = build_catalog(args.game_root, args.base_catalog)
    rendered = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != rendered:
            print(f"BNW catalog is stale: {args.output}")
            return 1
        print(f"BNW catalog is current: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
