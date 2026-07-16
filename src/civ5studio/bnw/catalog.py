"""Bundled, evidence-backed Brave New World reference catalog."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import json
from typing import Any, Iterable, Mapping


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReferenceCatalog:
    """Evidence-backed IDs, schemas, and donor rows for BNW compilation."""

    data: Mapping[str, Any]

    @classmethod
    def bundled(cls) -> "ReferenceCatalog":
        package = resources.files("civ5studio")
        path = package.joinpath("data", "bnw", "reference_catalog.json")
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if value.get("catalog_format") != "civ5studio.bnw-reference":
            raise CatalogError("Bundled BNW reference catalog has an unknown format.")
        return cls(value)

    @property
    def provenance(self) -> Mapping[str, Any]:
        return self.data.get("provenance", {})

    def values(self, category: str) -> frozenset[str]:
        value = self.data.get(category, [])
        if isinstance(value, Mapping):
            return frozenset(str(key) for key in value)
        return frozenset(str(item) for item in value)

    def contains(self, category: str, value: str | None) -> bool:
        return bool(value) and value in self.values(category)

    @property
    def unit_class_to_base_unit(self) -> dict[str, str]:
        overrides = dict(self.data.get("unit_base_overrides", {}))
        return {
            item: overrides.get(item, item.replace("UNITCLASS_", "UNIT_", 1))
            for item in self.values("unit_classes")
        }

    @property
    def building_class_to_base_building(self) -> dict[str, str]:
        overrides = dict(self.data.get("building_base_overrides", {}))
        return {
            item: overrides.get(
                item, item.replace("BUILDINGCLASS_", "BUILDING_", 1)
            )
            for item in self.values("building_classes")
        }

    @property
    def units(self) -> frozenset[str]:
        return frozenset(self.unit_class_to_base_unit.values())

    @property
    def buildings(self) -> frozenset[str]:
        return frozenset(self.building_class_to_base_building.values())

    @property
    def improvements(self) -> frozenset[str]:
        """Verified Expansion2 improvement donor Type values."""

        return self.values("improvements")

    @property
    def builds(self) -> frozenset[str]:
        """Verified Expansion2 worker build-action Type values."""

        return self.values("builds")

    @property
    def improvement_builds(self) -> dict[str, tuple[str, ...]]:
        """Map every improvement donor to its zero or more worker build rows."""

        raw = self.data.get("improvement_builds", {})
        if not isinstance(raw, Mapping):
            return {}
        return {
            str(improvement): tuple(
                str(build_type) for build_type in build_types
            )
            for improvement, build_types in raw.items()
            if isinstance(build_types, list)
        }

    def builds_for_improvement(self, improvement_type: str) -> tuple[str, ...]:
        return self.improvement_builds.get(improvement_type, ())

    def columns(self, table: str) -> frozenset[str]:
        tables = self.data.get("tables", {})
        if not isinstance(tables, Mapping):
            return frozenset()
        return frozenset(str(item) for item in tables.get(table, []))

    def ordered_columns(self, table: str) -> tuple[str, ...]:
        tables = self.data.get("tables", {})
        if not isinstance(tables, Mapping):
            return ()
        value = tables.get(table, [])
        return tuple(str(item) for item in value) if isinstance(value, list) else ()

    def column_definitions(self, table: str) -> tuple[Mapping[str, Any], ...]:
        definitions = self.data.get("schema_definitions", {})
        if not isinstance(definitions, Mapping):
            return ()
        value = definitions.get(table, [])
        if not isinstance(value, list):
            return ()
        return tuple(item for item in value if isinstance(item, Mapping))

    def clone_contract(self, table: str) -> Mapping[str, Any]:
        contracts = self.data.get("clone_contracts", {})
        if not isinstance(contracts, Mapping):
            return {}
        value = contracts.get(table, {})
        return value if isinstance(value, Mapping) else {}

    def donor_rows(self, table: str) -> Mapping[str, Mapping[str, Any]]:
        donors = self.data.get("donor_rows", {})
        if not isinstance(donors, Mapping):
            return {}
        value = donors.get(table, {})
        if not isinstance(value, Mapping):
            return {}
        return {
            str(key): row
            for key, row in value.items()
            if isinstance(row, Mapping)
        }

    def donor_identities(self, table: str) -> Mapping[str, Mapping[str, Any]]:
        identities = self.data.get("donor_identities", {})
        if not isinstance(identities, Mapping):
            return {}
        value = identities.get(table, {})
        if not isinstance(value, Mapping):
            return {}
        return {
            str(key): row
            for key, row in value.items()
            if isinstance(row, Mapping)
        }

    def donor_child_rows(self, table: str) -> tuple[Mapping[str, Any], ...]:
        donors = self.data.get("donor_child_rows", {})
        if not isinstance(donors, Mapping):
            return ()
        value = donors.get(table, [])
        if not isinstance(value, list):
            return ()
        return tuple(row for row in value if isinstance(row, Mapping))

    def display_name(self, value: str) -> str:
        """Return a readable fallback label while retaining the verified ID."""

        prefixes = (
            "CIVILIZATION_",
            "UNITCLASS_",
            "UNIT_",
            "BUILDINGCLASS_",
            "BUILDING_",
            "IMPROVEMENT_",
            "BUILD_",
            "TECH_",
            "PROMOTION_",
            "YIELD_",
            "REGION_",
            "FLAVOR_",
        )
        label = value
        for prefix in prefixes:
            if label.startswith(prefix):
                label = label[len(prefix) :]
                break
        words = label.replace("_", " ").lower().split()
        abbreviations = {"ai": "AI", "aa": "AA", "sam": "SAM", "xp": "XP"}
        return " ".join(abbreviations.get(word, word.capitalize()) for word in words)

    def missing_schema_references(
        self, required: Mapping[str, Iterable[str]]
    ) -> tuple[str, ...]:
        missing: list[str] = []
        for table, columns in required.items():
            known = self.columns(table)
            if not known:
                missing.append(f"table {table}")
                continue
            for column in columns:
                if column not in known:
                    missing.append(f"column {table}.{column}")
        return tuple(sorted(missing))
