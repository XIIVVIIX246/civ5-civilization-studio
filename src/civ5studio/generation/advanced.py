"""SQL/document helpers for optional advanced project content."""

from __future__ import annotations

import json
from typing import Iterable

from civ5studio.application.advanced_content import (
    advanced_content,
    custom_unit_art_assignment,
    unit_art_entry_output,
)
from civ5studio.bnw import ReferenceCatalog
from civ5studio.domain.models import CivProject, UniqueUnitSpec


def generate_custom_unit_member_sql(
    project: CivProject,
    catalog: ReferenceCatalog,
    unit: UniqueUnitSpec,
    *,
    donor_unit: str,
    custom_art_type: str,
) -> str:
    """Bind one verified FXSXML package to a cloned unit-art definition.

    The first donor member supplies domain/material/combat/weapon behavior.
    That is the safest deterministic mapping available without authoring new
    Granny animation graphs.  Runtime skeleton/animation testing remains
    mandatory and is recorded in the generated documentation.
    """

    assignment = custom_unit_art_assignment(project, unit.key)
    if assignment is None:
        return ""
    member_columns = catalog.ordered_columns("ArtDefine_UnitMemberInfos")
    mapping_columns = catalog.ordered_columns("ArtDefine_UnitInfoMemberInfos")
    combat_columns = catalog.ordered_columns("ArtDefine_UnitMemberCombats")
    weapon_columns = catalog.ordered_columns("ArtDefine_UnitMemberCombatWeapons")
    required = {
        "ArtDefine_UnitMemberInfos": (member_columns, {"Type", "Model"}),
        "ArtDefine_UnitInfoMemberInfos": (
            mapping_columns,
            {"UnitInfoType", "UnitMemberInfoType", "NumMembers"},
        ),
        "ArtDefine_UnitMemberCombats": (combat_columns, {"UnitMemberType"}),
        "ArtDefine_UnitMemberCombatWeapons": (
            weapon_columns,
            {"UnitMemberType"},
        ),
    }
    missing = [
        table
        for table, (columns, names) in required.items()
        if not names.issubset(columns)
    ]
    if missing:
        raise ValueError(
            "BNW catalog lacks custom unit-art schema for " + ", ".join(missing)
        )

    custom_member = f"ART_DEF_UNIT_MEMBER_{project.internal_prefix}_{unit.key}"
    donor_art = (
        "(SELECT UnitArtInfo FROM Units WHERE Type = " + _quote(donor_unit) + ")"
    )
    donor_member = (
        "(SELECT UnitMemberInfoType FROM ArtDefine_UnitInfoMemberInfos "
        f"WHERE UnitInfoType = {donor_art} ORDER BY rowid LIMIT 1)"
    )
    member_expressions: list[str] = []
    for column in member_columns:
        if column == "Type":
            member_expressions.append(_quote(custom_member))
        elif column == "Scale":
            member_expressions.append(_number(assignment.scale))
        elif column == "ZOffset":
            member_expressions.append(_number(assignment.z_offset))
        elif column == "Model":
            member_expressions.append(_quote(unit_art_entry_output(assignment)))
        else:
            member_expressions.append(_identifier(column))

    lines = [
        "-- Project-owned custom FXSXML/GR2 package; runtime animation test required.\n",
        "INSERT INTO ArtDefine_UnitMemberInfos "
        f"({', '.join(_identifier(item) for item in member_columns)})\n",
        f"SELECT {', '.join(member_expressions)}\n",
        "FROM ArtDefine_UnitMemberInfos\n",
        f"WHERE Type = {donor_member};\n\n",
    ]
    for table, columns in (
        ("ArtDefine_UnitMemberCombats", combat_columns),
        ("ArtDefine_UnitMemberCombatWeapons", weapon_columns),
    ):
        expressions = [
            _quote(custom_member)
            if column == "UnitMemberType"
            else _identifier(column)
            for column in columns
        ]
        lines.extend(
            [
                f"INSERT INTO {table} "
                f"({', '.join(_identifier(item) for item in columns)})\n",
                f"SELECT {', '.join(expressions)} FROM {table}\n",
                f"WHERE UnitMemberType = {donor_member};\n\n",
            ]
        )

    mapping_expressions = []
    for column in mapping_columns:
        if column == "UnitInfoType":
            mapping_expressions.append(_quote(custom_art_type))
        elif column == "UnitMemberInfoType":
            mapping_expressions.append(_quote(custom_member))
        else:
            mapping_expressions.append(_identifier(column))
    lines.extend(
        [
            "DELETE FROM ArtDefine_UnitInfoMemberInfos\n",
            f"WHERE UnitInfoType = {_quote(custom_art_type)};\n\n",
            "INSERT INTO ArtDefine_UnitInfoMemberInfos "
            f"({', '.join(_identifier(item) for item in mapping_columns)})\n",
            f"SELECT {', '.join(mapping_expressions)}\n",
            "FROM ArtDefine_UnitInfoMemberInfos\n",
            f"WHERE UnitInfoType = {donor_art}\n",
            "ORDER BY rowid LIMIT 1;\n\n",
        ]
    )
    return "".join(lines)


def advanced_capability_payload(project: CivProject) -> dict[str, object]:
    content = advanced_content(project)
    return {
        "localization": {
            "locales": sorted(content.localization),
            "entry_count": sum(len(values) for values in content.localization.values()),
            "static_status": "generated" if content.localization else "not_configured",
        },
        "custom_unit_art": {
            "assignments": [
                {
                    "unit_key": item.unit_key,
                    "entry_fxsxml": item.fxsxml,
                    "scale": item.scale,
                    "z_offset": item.z_offset,
                }
                for item in content.unit_art
            ],
            "runtime_status": "not_run" if content.unit_art else "not_configured",
            "runtime_gate": (
                "Verify model, skeleton, animation, material, formation, combat, "
                "strategic-view, and save/load behavior in BNW."
            ),
        },
        "audio": {
            "roles": [role.value for role, _source in content.audio.populated()],
            "runtime_status": (
                "not_run" if content.audio.populated() else "not_configured"
            ),
            "runtime_gate": (
                "Verify peace/war transitions, Dawn of Man playback, decoding, "
                "looping, and volume balance in BNW."
            ),
        },
    }


def advanced_capability_markdown(project: CivProject) -> str:
    payload = advanced_capability_payload(project)
    return (
        "# Advanced Content Runtime Gates\n\n"
        "Static packaging is not an in-game test.\n\n"
        "```json\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n```\n"
    )


def _quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _number(value: float) -> str:
    rendered = format(float(value), ".12g")
    return rendered if rendered not in {"-0", "-0.0"} else "0"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def missing_required_tables(
    catalog: ReferenceCatalog, names: Iterable[str]
) -> tuple[str, ...]:
    return tuple(name for name in names if not catalog.ordered_columns(name))
