"""Compatibility metadata for Promotions - Expansion Pack v9.

The separate mod was created by Bloublou and is not bundled. Only identifiers
and read-only selector metadata are packaged; the source mod's gameplay XML
and art are never copied into generated projects.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
from typing import Any, Mapping


PEP_MOD_ID = "0d764575-8028-4350-a363-c1ffb88b6a9a"
PEP_MOD_VERSION = 9
PEP_MOD_NAME = "Promotions - Expansion Pack"
PEP_AUTHOR = "Bloublou"
PEP_WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=84863495"


@dataclass(frozen=True, slots=True)
class PromotionEntry:
    type: str
    description_key: str
    display_name: str
    help_key: str
    help_text: str
    sound: str
    icon_atlas: str
    portrait_index: int

    @property
    def selector_label(self) -> str:
        return f"{self.display_name} ({self.type})"


@dataclass(frozen=True, slots=True)
class PromotionsExpansionPackCatalog:
    mod_id: str
    version: int
    name: str
    authors: str
    evidence: tuple[Mapping[str, str], ...]
    promotions: tuple[PromotionEntry, ...]

    @classmethod
    def bundled(cls) -> "PromotionsExpansionPackCatalog":
        resource = files("civ5studio").joinpath(
            "data", "promotions_expansion_pack_v9.json"
        )
        data: dict[str, Any] = json.loads(resource.read_text(encoding="utf-8"))
        mod = data.get("mod", {})
        if (
            mod.get("id") != PEP_MOD_ID
            or mod.get("version") != PEP_MOD_VERSION
            or mod.get("name") != PEP_MOD_NAME
        ):
            raise ValueError("Bundled Promotions Expansion Pack identity is invalid.")
        promotions = tuple(
            PromotionEntry(
                type=str(item["type"]),
                description_key=str(item["description_key"]),
                display_name=str(item["display_name"]),
                help_key=str(item["help_key"]),
                help_text=str(item["help_text"]),
                sound=str(item.get("sound", "")),
                icon_atlas=str(item.get("icon_atlas", "")),
                portrait_index=int(item.get("portrait_index", 0)),
            )
            for item in data.get("promotions", ())
        )
        types = [item.type for item in promotions]
        if len(promotions) != 17 or len(types) != len(set(types)):
            raise ValueError("Bundled Promotions Expansion Pack catalog is incomplete.")
        return cls(
            mod_id=PEP_MOD_ID,
            version=PEP_MOD_VERSION,
            name=PEP_MOD_NAME,
            authors=str(mod.get("authors", "")),
            evidence=tuple(dict(item) for item in data.get("evidence", ())),
            promotions=promotions,
        )

    @property
    def types(self) -> frozenset[str]:
        return frozenset(item.type for item in self.promotions)

    def get(self, promotion_type: str) -> PromotionEntry | None:
        return next(
            (item for item in self.promotions if item.type == promotion_type), None
        )

    def ui_entries(self) -> list[dict[str, str | int]]:
        return [
            {
                "type": item.type,
                "display_name": item.display_name,
                "help_text": item.help_text,
                "sound": item.sound,
                "icon_atlas": item.icon_atlas,
                "portrait_index": item.portrait_index,
            }
            for item in self.promotions
        ]
