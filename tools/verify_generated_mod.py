"""Independent static verification for a generated Civilization Studio mod."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image

from civ5studio.art import (
    ALPHA_ICON_ATLAS,
    PORTRAIT_ATLAS,
    STATIC_SCREEN_OPAQUE,
    STRATEGIC_VIEW,
    UNIT_FLAG_ATLAS,
    validate_dds,
)


def verify(root: Path) -> dict[str, object]:
    root = root.resolve()
    errors: list[str] = []
    modinfo_files = list(root.glob("*.modinfo"))
    if len(modinfo_files) != 1:
        errors.append(f"expected one .modinfo, found {len(modinfo_files)}")
        modinfo = None
    else:
        modinfo = modinfo_files[0]

    parsed_xml = 0
    for path in [*root.rglob("*.xml"), *modinfo_files]:
        try:
            ET.parse(path)
            parsed_xml += 1
        except ET.ParseError as exc:
            errors.append(f"XML parse failed for {path.relative_to(root)}: {exc}")

    referenced: set[str] = set()
    if modinfo:
        tree = ET.parse(modinfo)
        for node in tree.findall("./Files/File"):
            if node.text:
                referenced.add(node.text.replace("\\", "/"))
        for node in tree.findall("./Actions/OnModActivated/UpdateDatabase"):
            if node.text:
                referenced.add(node.text.replace("\\", "/"))
        for node in tree.findall("./EntryPoints/EntryPoint"):
            value = node.get("file")
            if value:
                referenced.add(value.replace("\\", "/"))
        missing = sorted(path for path in referenced if not (root / path).is_file())
        errors.extend(f"modinfo reference is missing: {path}" for path in missing)

    manifest_path = root / "Documentation" / "ART_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dds_count = 0
    formats: dict[str, int] = {}
    for item in manifest["outputs"]:
        path = root / item["path"]
        if not path.is_file():
            errors.append(f"art output is missing: {item['path']}")
            continue
        profile_name = item["profile"]
        if profile_name == "legacy_dx9_dxt1":
            profile = STATIC_SCREEN_OPAQUE
        elif item["purpose"] == "strategic_view":
            profile = STRATEGIC_VIEW
        elif item["purpose"] == "civilization_alpha_atlas":
            profile = ALPHA_ICON_ATLAS
        elif item["purpose"] == "unit_flag":
            profile = UNIT_FLAG_ATLAS
        else:
            profile = PORTRAIT_ATLAS
        try:
            header = validate_dds(
                path,
                profile,
                (int(item["width"]), int(item["height"])),
            )
        except Exception as exc:
            errors.append(f"DDS validation failed for {item['path']}: {exc}")
            continue
        dds_count += 1
        format_name = header.fourcc or "A8R8G8B8"
        formats[format_name] = formats.get(format_name, 0) + 1

    annulus_alpha_max = _outer_annulus_alpha(root, manifest)
    if annulus_alpha_max > 8:
        errors.append(
            "main civilization portrait has visible alpha outside the 172/256 "
            f"safe footprint (max={annulus_alpha_max})"
        )

    forbidden = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and (path.suffix.lower() in {".pyc", ".tmp"} or "__pycache__" in path.parts)
    ]
    errors.extend(f"forbidden generated file: {path}" for path in forbidden)
    return {
        "status": "PASS" if not errors else "FAIL",
        "root": str(root),
        "file_count": sum(path.is_file() for path in root.rglob("*")),
        "modinfo_references": len(referenced),
        "parsed_xml_files": parsed_xml,
        "dds_files_validated": dds_count,
        "dds_formats": formats,
        "portrait_outer_annulus_alpha_max": annulus_alpha_max,
        "errors": errors,
    }


def _outer_annulus_alpha(root: Path, manifest: dict) -> int:
    entry = next(
        item
        for item in manifest["outputs"]
        if item["purpose"] == "main_portrait_atlas" and item["icon_size"] == 256
    )
    with Image.open(root / entry["path"]) as atlas:
        tile = atlas.convert("RGBA").crop((0, 0, 256, 256))
    alpha = tile.getchannel("A")
    center = 127.5
    values = [
        alpha.getpixel((x, y))
        for y in range(256)
        for x in range(256)
        if math.hypot(x - center, y - center) >= 90
    ]
    return max(values, default=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mod_root", type=Path)
    args = parser.parse_args()
    result = verify(args.mod_root)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
