"""Stable Civilization V identifier helpers.

The project document stores human readable names separately from stable keys.
Generated database identifiers are derived only from the project prefix and
those keys, so changing display text does not silently break saved games.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


TYPE_COMPONENT_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,47}$")
RESERVED_PREFIXES = (
    "CIVILIZATION_",
    "UNITCLASS_",
    "BUILDINGCLASS_",
    "PLAYERCOLOR_",
    "PROMOTION_",
    "BUILDING_",
    "LEADER_",
    "TRAIT_",
    "POLICY_",
    "TECH_",
    "YIELD_",
    "COLOR_",
    "UNIT_",
    "TXT_KEY_",
)


def type_component(value: str) -> str:
    """Return a normalized ASCII component suitable for a Civ V Type value."""

    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").upper()
    ascii_value = re.sub(r"[^A-Z0-9]+", "_", ascii_value)
    return re.sub(r"_+", "_", ascii_value).strip("_")


def normalize_prefix(value: str) -> str:
    """Normalize a user prefix and remove accidentally pasted Civ V prefixes."""

    result = type_component(value)
    changed = True
    while changed:
        changed = False
        for reserved in RESERVED_PREFIXES:
            if result.startswith(reserved):
                result = result[len(reserved) :]
                changed = True
                break
    return result


def is_valid_component(value: str) -> bool:
    return bool(TYPE_COMPONENT_RE.fullmatch(value or ""))


def safe_folder_name(value: str) -> str:
    """Create a conservative Windows-safe generated folder name."""

    result = type_component(value).title().replace("_", "_")
    return result or "Civ5StudioProject"


@dataclass(frozen=True, slots=True)
class GeneratedIds:
    civilization: str
    leader: str
    trait: str
    player_color: str
    primary_color: str
    secondary_color: str
    main_atlas: str
    alpha_atlas: str
    units: dict[str, str]
    buildings: dict[str, str]
    improvements: dict[str, str]
    unit_flag_atlases: dict[str, str]


def generated_ids(project: object) -> GeneratedIds:
    """Compute identifiers for a :class:`CivProject` without mutating it."""

    prefix = normalize_prefix(getattr(project, "internal_prefix"))
    leader_key = type_component(getattr(getattr(project, "leader"), "key"))
    trait_key = type_component(getattr(getattr(project, "trait"), "key"))
    units = {
        type_component(item.key): f"UNIT_{type_component(item.key)}_{prefix}"
        for item in getattr(project, "units")
    }
    buildings = {
        type_component(item.key): f"BUILDING_{type_component(item.key)}_{prefix}"
        for item in getattr(project, "buildings")
    }
    improvements = {
        type_component(item.key): f"IMPROVEMENT_{type_component(item.key)}_{prefix}"
        for item in getattr(project, "improvements", ())
    }
    flags = {
        key: f"{prefix}_UNIT_{key}_FLAG_ATLAS"
        for key in units
    }
    return GeneratedIds(
        civilization=f"CIVILIZATION_{prefix}",
        leader=f"LEADER_{leader_key}_{prefix}",
        trait=f"TRAIT_{trait_key}_{prefix}",
        player_color=f"PLAYERCOLOR_{prefix}",
        primary_color=f"COLOR_PLAYER_{prefix}_ICON",
        secondary_color=f"COLOR_PLAYER_{prefix}_BACKGROUND",
        main_atlas=f"{prefix}_ATLAS",
        alpha_atlas=f"{prefix}_ALPHA_ATLAS",
        units=units,
        buildings=buildings,
        improvements=improvements,
        unit_flag_atlases=flags,
    )
