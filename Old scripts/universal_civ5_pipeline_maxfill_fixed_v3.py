#!/usr/bin/env python3
"""
universal_civ5_pipeline.py
==========================
Civilization V: Brave New World PNG -> DDS art pipeline with atlas/QA output.

Design goals
------------
* Default to the Civ V custom-civ pattern that is least likely to drift from an
  existing mod: one combined 4x4 normal icon atlas at 256/128/80/64/45/32.
* Preserve alpha and write uncompressed 32-bit A8R8G8B8/BGRA DDS with no mipmaps.
* Export alpha/team icons as standalone 1x1 DDS files at 128/80/64/48/45/32/24.
* Export unit flags as a single 8x8 256x256 atlas with 32px cells.
* Produce a manifest, XML template, QA report, and preview PNGs for review.

This script intentionally does not edit a live mod by default. Point it at an
existing mod data folder with --mod-data-dir and it will read IconTextureAtlases
and reuse matching combined-atlas filenames/tags when it can; otherwise it emits
clear warnings instead of silently inventing incompatible atlas names.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from dataclasses import dataclass, field
from hashlib import md5
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

# Civ V BNW constants requested by the QA brief.
NORMAL_ATLAS_SIZES = [256, 128, 80, 64, 45, 32]
ALPHA_ICON_SIZES = [128, 80, 64, 48, 45, 32, 24]
NORMAL_GRID = 4
UNIT_FLAG_GRID = 8
UNIT_FLAG_CELL = 32
SAFE_OCCUPANCY = 0.94  # TEST BUILD: larger normal-icon fill for Civ V circular UI crops; legacy fallback was 0.82.
SAFE_MARGIN_MIN = 0.08
PREFIX_RE = re.compile(r"^[A-Za-z0-9_]+$")

NORMAL_ROLES = {"civ", "leader", "unit", "building", "support", "promotion", "dummy", "trait"}

# --- vNext: high-resolution master + profile support -----------------------
# New profile flow normalizes to a high-resolution master and downscales to the
# legacy size ladders. The legacy 256 master path is preserved for old configs.
DEFAULT_MASTER_SIZE = 1024

# Role-specific circular-safe subject scale. SAFE_OCCUPANCY remains the fallback.
ROLE_SAFE_SUBJECT_SCALE = {
    # TEST BUILD: normal Civ V icon roles are intentionally less conservative.
    # This reduces the persistent "tiny empty ring" when the source is displayed
    # through Civ V's circular UI crop. Alpha/team icons and unit flags stay
    # conservative because their glyph readability is more fragile.
    "civ": 0.94,
    "leader": 0.92,
    "unit": 0.94,
    "building": 0.94,
    "promotion": 0.95,
    "support": 0.95,
    "dummy": 0.95,
    "trait": 0.95,
    "alpha": 0.78,
    "alpha_icon": 0.78,
    "unit_flag": 0.90,
}

# asset_type values understood by the new JSON flow. These describe what an asset
# IS (icon vs flag vs scene); they are NOT Civ V database TypeNames. The Civ V
# TypeName still lives in "type"/"type_name" and is never repurposed here.
KNOWN_ASSET_TYPES = {
    "civ_icon", "leader_icon", "unit_icon", "building_icon", "support_icon",
    "promotion_icon", "dummy_icon", "trait_icon", "alpha_icon", "unit_flag",
    "dawn_image", "map_image", "leader_scene",
}

# Canonical profile names plus human-friendly aliases.
PROFILE_ALIASES = {
    "white_glyph_black_background": "civ5_alpha_glyph_black_to_transparent",
    "unit_flag_black_background": "civ5_unit_flag_black_to_transparent",
    "dawn_of_man": "civ5_dom",
    "leader_scene": "civ5_leader_scene_4x3",
}

KNOWN_PROFILES = {
    "civ5_circular_icon",
    "civ5_alpha_glyph_black_to_transparent",
    "civ5_unit_flag_black_to_transparent",
    "civ5_dom",
    "civ5_map",
    "civ5_leader_scene_4x3",
    "civ5_leader_scene_16x9",
}

# Default profile per asset role. alpha_icon and unit_flag intentionally map to
# legacy behavior unless a black-background profile is explicitly selected or the
# source is detected to be white-on-black (handled at processing time).
ROLE_DEFAULT_PROFILE = {
    "civ": "civ5_circular_icon",
    "leader": "civ5_circular_icon",
    "unit": "civ5_circular_icon",
    "building": "civ5_circular_icon",
    "support": "civ5_circular_icon",
    "promotion": "civ5_circular_icon",
    "dummy": "civ5_circular_icon",
    "trait": "civ5_circular_icon",
    "alpha_icon": None,   # legacy alpha behavior unless explicitly profiled
    "unit_flag": None,    # legacy strict flag behavior unless explicitly profiled
    "dawn_image": "civ5_dom",
    "map_image": "civ5_map",
    "leader_scene": "civ5_leader_scene_4x3",
}

# Profile definitions. These are data-only defaults consumed by the processing
# functions; nothing here writes files. "compatible_roles" drives validation.
PROFILES: dict[str, dict] = {
    "civ5_circular_icon": {
        "kind": "circular_icon",
        "target_master_size": DEFAULT_MASTER_SIZE,
        "atlas_sizes": NORMAL_ATLAS_SIZES,
        "center_crop_square": True,
        "force_opaque": False,
        "black_bg_cleanup": False,
        "force_white": False,
        "circular_preview": True,
        "compatible_roles": {"civ", "leader", "unit", "building", "support",
                             "promotion", "dummy", "trait"},
    },
    "civ5_alpha_glyph_black_to_transparent": {
        "kind": "alpha_glyph",
        "target_master_size": DEFAULT_MASTER_SIZE,
        "atlas_sizes": ALPHA_ICON_SIZES,
        "black_bg_cleanup": True,
        "force_white": True,
        "force_opaque": False,
        "safe_subject_scale": 0.78,
        "compatible_roles": {"alpha_icon", "support", "dummy"},
    },
    "civ5_unit_flag_black_to_transparent": {
        "kind": "unit_flag_glyph",
        "target_master_size": DEFAULT_MASTER_SIZE,
        "intermediate_size": 256,
        "black_bg_cleanup": True,
        "force_white": True,
        "force_opaque": False,
        "safe_subject_scale": 0.90,
        "final_cell": UNIT_FLAG_CELL,
        "compatible_roles": {"unit_flag"},
    },
    "civ5_dom": {
        "kind": "scene",
        "final_size": (1024, 768),
        "preview_size": (256, 192),
        "force_opaque": True,
        "compatible_roles": {"dawn_image"},
    },
    "civ5_map": {
        "kind": "scene",
        "final_size": (512, 512),
        "preview_size": (256, 256),
        "force_opaque": True,
        "compatible_roles": {"map_image"},
    },
    "civ5_leader_scene_4x3": {
        "kind": "scene",
        "final_size": (1024, 768),
        "preview_size": (256, 192),
        "force_opaque": True,
        "compatible_roles": {"leader_scene"},
    },
    "civ5_leader_scene_16x9": {
        "kind": "scene",
        "final_size": (1280, 720),
        "preview_size": (256, 144),
        "force_opaque": True,
        "compatible_roles": {"leader_scene"},
    },
}

# Trailing numeric-suffix detector for filename validation (e.g. _1, _256, _1024).
NUMERIC_SUFFIX_RE = re.compile(r"_(\d+)$")


def resolve_asset_profile(asset_role: str, explicit_profile: Optional[str],
                          asset_options: Optional[dict] = None) -> Optional[str]:
    """Resolve the effective profile name for an asset.

    Precedence: explicit profile (after alias expansion) > role default. Returns
    None when the role has no default profile (legacy behavior preserved). Unknown
    explicit profiles are returned as-is so validation can report them clearly.
    """
    asset_options = asset_options or {}
    explicit = explicit_profile or asset_options.get("profile")
    if explicit:
        name = str(explicit).strip()
        return PROFILE_ALIASES.get(name, name)
    return ROLE_DEFAULT_PROFILE.get(asset_role)


def safe_subject_scale_for_role(role: str, profile: Optional[str] = None,
                                override: Optional[float] = None) -> float:
    """Return the circular-safe subject scale for a role/profile.

    Precedence: explicit override > profile safe_subject_scale > role default >
    global SAFE_OCCUPANCY fallback.
    """
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    if profile and profile in PROFILES:
        pscale = PROFILES[profile].get("safe_subject_scale")
        if pscale is not None:
            return float(pscale)
    return float(ROLE_SAFE_SUBJECT_SCALE.get(role, SAFE_OCCUPANCY))


def cfg_profile_for(cfg: "PipelineConfig", role: str) -> str:
    """Return an explicit profile string for civ/leader from config, else ''."""
    # civ/leader icons are created inline (no AssetSpec from JSON); honor a
    # config-level default_profile, then the role default, only when profile-driven.
    if cfg.uses_profiles:
        if cfg.default_profile:
            resolved = PROFILE_ALIASES.get(cfg.default_profile.strip(), cfg.default_profile.strip())
            if role in PROFILES.get(resolved, {}).get("compatible_roles", set()):
                return resolved
        return ROLE_DEFAULT_PROFILE.get(role) or ""
    return ""


def cfg_alpha_profile(cfg: "PipelineConfig") -> Optional[str]:
    """Return the alpha-icon profile if the config opted into one, else None."""
    explicit = getattr(cfg, "_alpha_profile", None)
    return explicit or None


def resolve_leader_scene_profile(cfg: "PipelineConfig") -> str:
    """Default leader scene stays 4:3 1024x768 unless 16:9 was explicitly chosen."""
    name = (cfg.leader_scene_profile or "").strip()
    name = PROFILE_ALIASES.get(name, name)
    if name == "civ5_leader_scene_16x9":
        return name
    return "civ5_leader_scene_4x3"


def resolve_write_per_asset_previews(cfg: "PipelineConfig") -> bool:
    """Default true for profile-driven configs, false for legacy, unless set."""
    if cfg.write_per_asset_previews is not None:
        return bool(cfg.write_per_asset_previews)
    return bool(cfg.uses_profiles)


def _default_asset_type(role: str) -> str:
    return {
        "civ": "civ_icon", "leader": "leader_icon", "unit": "unit_icon",
        "building": "building_icon", "support": "support_icon",
        "promotion": "promotion_icon", "dummy": "dummy_icon", "trait": "trait_icon",
    }.get(role, role)


@dataclass
class AssetSpec:
    role: str
    label: str
    source: Path
    suffix: str = ""
    atlas: str = ""
    portrait_index: Optional[int] = None
    type_name: str = ""
    # --- vNext optional fields (backward compatible; default to inert) -------
    asset_type: str = ""           # what the asset IS, e.g. unit_icon (NOT a Civ V TypeName)
    profile: str = ""              # explicit profile name/alias from JSON
    safe_subject_scale: Optional[float] = None  # per-asset circular-safe override
    options: dict = field(default_factory=dict)  # free-form per-asset process options
    # Runtime/QA bookkeeping populated during generation (not from JSON):
    resolved_profile: str = ""
    black_bg_cleanup_applied: bool = False
    normalized_source_size: Optional[tuple[int, int]] = None
    final_target_size: Optional[tuple[int, int]] = None


@dataclass
class AtlasDefinition:
    atlas: str
    size: int
    filename: str
    icons_per_row: int
    icons_per_column: int
    source_file: str = ""


@dataclass
class AtlasSelection:
    atlas: str
    files_by_size: dict[int, str]
    icons_per_row: int
    icons_per_column: int

    def filename_for(self, size: int) -> str:
        if size in self.files_by_size:
            return self.files_by_size[size]
        stem = infer_atlas_stem(next(iter(self.files_by_size.values()), self.atlas), size)
        return f"{stem}_{size}.dds"

    @property
    def stem(self) -> str:
        return infer_atlas_stem(next(iter(self.files_by_size.values()), self.atlas), None)


@dataclass
class IconUsage:
    table: str
    type_name: str
    icon_atlas: str = ""
    portrait_index: Optional[int] = None
    alpha_icon_atlas: str = ""
    unit_flag_atlas: str = ""
    unit_flag_icon_offset: Optional[int] = None
    source_file: str = ""


@dataclass
class MedallionOptions:
    bake: bool = False
    # TEST BUILD: bigger baked medallions. The old defaults were
    # fill_percent=0.84, radius_percent=0.46, rim_width_percent=0.035.
    # radius 0.495 is nearly full-cell while still staying within the legal
    # validation limit of <= 0.5 and leaving subpixel antialias room.
    fill_percent: float = 0.94
    radius_percent: float = 0.495
    rim: bool = False
    rim_width_percent: float = 0.020
    rim_style: str = "gold"
    background: str = "transparent"
    preview_only: bool = False


@dataclass
class PipelineConfig:
    prefix: str
    output_dir: Optional[Path]
    civ_icon: Path
    leader_icon: Path
    alpha_icon: Path
    units: list[AssetSpec] = field(default_factory=list)
    buildings: list[AssetSpec] = field(default_factory=list)
    supports: list[AssetSpec] = field(default_factory=list)
    flags: list[AssetSpec] = field(default_factory=list)
    map_image: Optional[Path] = None
    dawn_image: Optional[Path] = None
    leader_scene: Optional[Path] = None
    mod_data_dir: Optional[Path] = None
    icon_atlas_name: str = ""
    icon_atlas_stem: str = ""
    flag_atlas_name: str = ""
    flag_atlas_stem: str = ""
    alpha_atlas_name: str = ""
    dry_run: bool = False
    write_mod: bool = False
    bake_circular_mask: bool = False
    medallion: MedallionOptions = field(default_factory=MedallionOptions)
    allow_painted_flags: bool = False
    preset: str = "existing-combined-atlas"
    explicit_indexes: dict[str, int] = field(default_factory=dict)
    dawn_output_name: str = ""
    map_output_name: str = ""
    leader_scene_output_name: str = ""
    # --- vNext options (all default to backward-compatible behavior) --------
    leader_scene_profile: str = ""          # set to civ5_leader_scene_16x9 to opt in
    write_per_asset_previews: Optional[bool] = None  # None -> auto (true for profiled configs)
    allow_numeric_suffixes: bool = False
    copy_new_assets: bool = False
    update_modinfo_imports: bool = False
    mod_art_subdir: str = "Art"
    uses_profiles: bool = False             # True when any asset/config sets profiles
    default_profile: str = ""               # config-level fallback for circular-icon roles
    normal_icon_profile: str = ""           # optional top-level profile for civ/leader/unit/building circular icons
    support_icon_profile: str = ""          # optional top-level profile for support/promotion/dummy/trait circular icons
    unit_flag_profile: str = ""             # optional top-level profile for unit flags


@dataclass
class QAResult:
    name: str
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# DDS writer / reader
# ---------------------------------------------------------------------------

def save_as_dds(img: Image.Image, path: Path) -> None:
    """Save an uncompressed 32-bit BGRA DDS with alpha and one mip level."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = scrub_transparent_rgb(img.convert("RGBA"))
    w, h = img.size
    r, g, b, a = img.split()
    pixel_data = Image.merge("RGBA", (b, g, r, a)).tobytes()
    header = struct.pack(
        "<IIIIIII44xIIIIIIIIIIIII",
        124,                # DDS_HEADER.dwSize
        0x0002100F,          # caps | height | width | pitch | pixelformat
        h, w, w * 4,         # dimensions + pitch
        0, 1,                # depth, mipMapCount (no mipmaps)
        32, 0x41, 0, 32,     # pixel format: RGB | ALPHAPIXELS, no fourCC, 32 bpp
        0x00FF0000,          # R mask as interpreted over BGRA byte order
        0x0000FF00,          # G mask
        0x000000FF,          # B mask
        0xFF000000,          # A mask
        0x1000, 0, 0, 0, 0,  # texture caps only
    )
    with path.open("wb") as f:
        f.write(b"DDS ")
        f.write(header)
        f.write(pixel_data)


def self_test_dds(output_dir: Optional[Path] = None) -> bool:
    """Round-trip a 2x2 known-pixel DDS to confirm channel order and masks.

    Writes red, green, blue, transparent pixels, reads them back through the
    raw BGRA bytes, and confirms the header advertises uncompressed 32-bit BGRA
    with the correct masks. Optionally emits a diagnostic PNG. Returns True on
    success and prints a clear report.
    """
    import tempfile
    pixels = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (0, 0, 0, 0)]
    src = Image.new("RGBA", (2, 2))
    src.putdata(pixels)
    tmpdir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="dds_selftest_"))
    tmpdir.mkdir(parents=True, exist_ok=True)
    dds_path = tmpdir / "selftest.dds"
    save_as_dds(src, dds_path)

    ok = True
    msgs = []
    header = read_dds_header(dds_path)
    if header["width"] != 2 or header["height"] != 2:
        ok = False; msgs.append(f"FAIL dimensions: {header['width']}x{header['height']}")
    else:
        msgs.append("PASS dimensions 2x2")
    if header["bpp"] != 32:
        ok = False; msgs.append(f"FAIL bpp: {header['bpp']}")
    else:
        msgs.append("PASS 32 bpp")
    if header["fourcc"] != 0:
        ok = False; msgs.append(f"FAIL fourcc not zero (compressed?): {header['fourcc']}")
    else:
        msgs.append("PASS uncompressed (fourcc=0)")
    if header["alpha_mask"] != 0xFF000000:
        ok = False; msgs.append(f"FAIL alpha mask: {header['alpha_mask']:#010x}")
    else:
        msgs.append("PASS alpha mask 0xFF000000")
    if header["mipmaps"] != 1:
        ok = False; msgs.append(f"FAIL mipmaps: {header['mipmaps']}")
    else:
        msgs.append("PASS single mip level")

    # Verify pixel byte order: file stores BGRA after the 128-byte header.
    raw = dds_path.read_bytes()[128:]
    expected_bgra = b"".join(bytes((b, g, r, a)) for (r, g, b, a) in pixels)
    if raw == expected_bgra:
        msgs.append("PASS pixel bytes are BGRA in the expected order")
    else:
        ok = False
        msgs.append("FAIL pixel byte order does not match expected BGRA")
        msgs.append(f"  expected: {expected_bgra.hex()}")
        msgs.append(f"  actual:   {raw.hex()}")

    if output_dir:
        diag = src.resize((128, 128), Image.Resampling.NEAREST)
        diag.save(tmpdir / "selftest_diagnostic.png")
        msgs.append(f"Diagnostic PNG: {tmpdir / 'selftest_diagnostic.png'}")

    print("DDS self-test:", "SUCCESS" if ok else "FAILURE")
    for m in msgs:
        print("  " + m)
    return ok


def read_dds_header(path: Path) -> dict:
    with path.open("rb") as f:
        data = f.read(128)
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ValueError(f"Not a DDS file: {path}")
    size, flags, height, width, pitch, depth, mipmaps = struct.unpack("<IIIIIII", data[4:32])
    pf = struct.unpack("<IIIIIIII", data[76:108])
    return {
        "width": width,
        "height": height,
        "pitch": pitch,
        "mipmaps": mipmaps,
        "pf_flags": pf[1],
        "fourcc": pf[2],
        "bpp": pf[3],
        "alpha_mask": pf[7],
    }


# ---------------------------------------------------------------------------
# Image processing / QA helpers
# ---------------------------------------------------------------------------

def open_rgba(path: Path) -> Image.Image:
    try:
        return Image.open(path).convert("RGBA")
    except Exception as exc:
        raise ValueError(f"Could not open PNG {path}: {exc}") from exc


def alpha_bbox(img: Image.Image, threshold: int = 8) -> Optional[tuple[int, int, int, int]]:
    alpha = img.convert("RGBA").getchannel("A")
    mask = alpha.point(lambda p: 255 if p > threshold else 0)
    return mask.getbbox()


def center_crop_to_square(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    side = min(img.width, img.height)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


def normalize_icon_master(src_path: Path, role: str, warnings: list[str],
                          master_size: int = 256,
                          safe_subject_scale: Optional[float] = None) -> Image.Image:
    """Return an icon master with safe transparent padding.

    Transparent art is cropped to its meaningful alpha bbox before being fitted
    into the central safe area. Opaque/non-alpha art is center-cropped square and
    then shrunk, preventing full-bleed generated paintings from touching the
    circular Civ V mask or cell edge.

    Legacy callers get a 256x256 master at SAFE_OCCUPANCY (unchanged). The new
    profile flow passes master_size=1024 and a role-aware safe_subject_scale so a
    high-resolution master can be downscaled to the size ladder without an early
    quality loss at 256.
    """
    occupancy = SAFE_OCCUPANCY if safe_subject_scale is None else float(safe_subject_scale)
    img = open_rgba(src_path)
    if img.width != img.height:
        warnings.append(f"{role}:{src_path.name}: non-square source was center-cropped/padded to a square master.")

    a = img.getchannel("A")
    amin, amax = a.getextrema()
    if amin >= 250:
        # Fixed: strip edge-connected white/black mats from AI-generated circular
        # icons, then prune small detached watermark/sparkle islands before bbox.
        cleaned = remove_edge_connected_flat_background(img, f"{role}:{src_path.name}", warnings)
        if cleaned.getchannel("A").getextrema()[0] < 250:
            cleaned = prune_alpha_components(cleaned, f"{role}:{src_path.name}", warnings)
            img = cleaned
            a = img.getchannel("A")
            amin, amax = a.getextrema()

    bbox = alpha_bbox(img) if amin < 250 else None
    if bbox:
        subject = img.crop(bbox)
    else:
        subject = center_crop_to_square(img)
        if amin >= 250:
            warnings.append(f"{role}:{src_path.name}: source is fully opaque; transparent safe padding was added but background may remain visible inside the circle.")

    max_subject = int(round(master_size * occupancy))
    scale = min(max_subject / subject.width, max_subject / subject.height)
    new_size = (max(1, int(round(subject.width * scale))), max(1, int(round(subject.height * scale))))
    subject = subject.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (master_size, master_size), (0, 0, 0, 0))
    canvas.paste(subject, ((master_size - new_size[0]) // 2, (master_size - new_size[1]) // 2), subject)
    return canvas


def apply_circular_mask(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.width - 1, img.height - 1), fill=255)
    img.putalpha(ImageChops.darker(img.getchannel("A"), mask))
    return img


def icon_cell(master_256: Image.Image, size: int, circular: bool = True) -> Image.Image:
    cell = master_256.resize((size, size), Image.Resampling.LANCZOS)
    return apply_circular_mask(cell) if circular else cell


def make_circle_mask(size: int, radius: float, antialias_scale: int = 4) -> Image.Image:
    """Return a smooth alpha mask for a centered circle.

    The ellipse is drawn at a higher resolution and downsampled with LANCZOS so
    the baked medallion has Civ V-friendly antialiased edges instead of a harsh
    binary cutout.
    """
    scale = max(1, int(antialias_scale))
    hi_size = size * scale
    hi_radius = radius * scale
    center = hi_size / 2
    mask = Image.new("L", (hi_size, hi_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        (center - hi_radius, center - hi_radius, center + hi_radius, center + hi_radius),
        fill=255,
    )
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def _fit_subject_to_canvas(subject: Image.Image, canvas_size: int, max_extent: int) -> Image.Image:
    scale = min(max_extent / subject.width, max_extent / subject.height)
    new_size = (max(1, int(round(subject.width * scale))), max(1, int(round(subject.height * scale))))
    subject = subject.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    canvas.paste(subject, ((canvas_size - new_size[0]) // 2, (canvas_size - new_size[1]) // 2), subject)
    return canvas


def normalize_subject_for_medallion(img: Image.Image, target_diameter: int, fill_percent: float) -> Image.Image:
    """Fit source art inside the medallion circle with safe padding."""
    src = img.convert("RGBA")
    alpha = src.getchannel("A")
    amin, _ = alpha.getextrema()
    bbox = alpha_bbox(src) if amin < 250 else None
    subject = src.crop(bbox) if bbox else center_crop_to_square(src)
    max_extent = max(1, int(round(target_diameter * fill_percent)))
    return _fit_subject_to_canvas(subject, src.width, max_extent)


def _tinted_layer(size: int, color: tuple[int, int, int, int], mask: Optional[Image.Image] = None) -> Image.Image:
    layer = Image.new("RGBA", (size, size), color)
    if mask is not None:
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    return layer


def draw_medallion_rim(canvas: Image.Image, center: tuple[float, float], radius: float, options: MedallionOptions) -> None:
    """Draw a subtle Civ V-style rim/frame ring above medallion art."""
    if not options.rim or options.rim_style == "none":
        return
    size = canvas.width
    scale = 4
    hi = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(hi)
    cx, cy = center[0] * scale, center[1] * scale
    r = radius * scale
    width = max(1, int(round(size * options.rim_width_percent * scale)))
    if options.rim_style == "silver":
        outer = (176, 181, 176, 245)
        mid = (105, 111, 114, 230)
        light = (236, 240, 230, 170)
    else:
        outer = (173, 132, 55, 245)
        mid = (92, 61, 27, 235)
        light = (246, 220, 132, 170)
    bbox = (cx - r, cy - r, cx + r, cy + r)
    draw.ellipse(bbox, outline=mid, width=max(1, width + scale))
    inset = width / 2
    draw.ellipse((bbox[0] + inset, bbox[1] + inset, bbox[2] - inset, bbox[3] - inset), outline=outer, width=width)
    sep_width = max(1, width // 3)
    inner_inset = width + sep_width
    draw.ellipse((bbox[0] + inner_inset, bbox[1] + inner_inset, bbox[2] - inner_inset, bbox[3] - inner_inset), outline=(24, 20, 16, 150), width=sep_width)
    # Restrained top-left highlight arc.
    try:
        draw.arc((bbox[0] + inset, bbox[1] + inset, bbox[2] - inset, bbox[3] - inset), 205, 315, fill=light, width=max(1, width // 3))
    except TypeError:  # Older Pillow without width= on arc.
        draw.arc((bbox[0] + inset, bbox[1] + inset, bbox[2] - inset, bbox[3] - inset), 205, 315, fill=light)
    canvas.alpha_composite(hi.resize((size, size), Image.Resampling.LANCZOS))


def compose_medallion_icon(img: Image.Image, cell_size: int, options: MedallionOptions) -> Image.Image:
    """Bake a normal icon source into a circular medallion inside a square cell."""
    size = int(cell_size)
    radius = max(1.0, min(size / 2 - 0.5, size * options.radius_percent))
    diameter = max(1, int(round(radius * 2)))
    circle_mask = make_circle_mask(size, radius)
    src = img.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS) if img.size != (size, size) else img.convert("RGBA")
    fitted = normalize_subject_for_medallion(src, diameter, options.fill_percent)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if options.background == "dark":
        canvas.alpha_composite(Image.new("RGBA", (size, size), (16, 14, 12, 230)))
        canvas.alpha_composite(_tinted_layer(size, (38, 31, 24, 255), circle_mask))
    elif options.background == "parchment":
        canvas.alpha_composite(Image.new("RGBA", (size, size), (50, 37, 20, 210)))
        canvas.alpha_composite(_tinted_layer(size, (166, 136, 78, 255), circle_mask))
    elif options.background == "source-blur":
        blurred = src.filter(ImageFilter.GaussianBlur(max(1, size // 18))).resize((size, size), Image.Resampling.LANCZOS)
        shade = Image.new("RGBA", (size, size), (18, 15, 12, 150))
        blurred.alpha_composite(shade)
        canvas.alpha_composite(blurred)

    clipped = fitted.copy()
    clipped.putalpha(ImageChops.multiply(clipped.getchannel("A"), circle_mask))
    canvas.alpha_composite(clipped)

    # Very subtle inner shade and top-left glint, masked to the circle.
    inner = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(inner)
    cx = cy = size / 2
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(0, 0, 0, 70), width=max(1, int(round(size * 0.012))))
    d.arc((cx - radius * 0.86, cy - radius * 0.86, cx + radius * 0.86, cy + radius * 0.86), 210, 300, fill=(255, 245, 210, 45), width=max(1, int(round(size * 0.01))))
    inner.putalpha(ImageChops.multiply(inner.getchannel("A"), circle_mask))
    canvas.alpha_composite(inner)

    draw_medallion_rim(canvas, (size / 2, size / 2), radius, options)
    return scrub_transparent_rgb(canvas)


def medallion_subject_metrics(square_master: Image.Image, medallion_master: Image.Image, options: MedallionOptions) -> dict:
    """Return QA metrics for medallion fit/readability heuristics."""
    size = medallion_master.width
    radius = size * options.radius_percent
    diameter = max(1, int(round(radius * 2)))
    fitted_subject = normalize_subject_for_medallion(square_master.resize((size, size), Image.Resampling.LANCZOS), diameter, options.fill_percent)
    bbox = alpha_bbox(fitted_subject)
    clipped = False
    fill_ratio = None
    warning_fill = False
    unreadable_32 = False
    if bbox:
        l, t, r, b = bbox
        cx = cy = size / 2
        corners = ((l, t), (r, t), (l, b), (r, b))
        clipped = any(math.hypot(x - cx, y - cy) > radius + 1 for x, y in corners)
        fill_ratio = max(r - l, b - t) / max(1, radius * 2)
        warning_fill = fill_ratio > 0.92
    small = medallion_master.resize((32, 32), Image.Resampling.LANCZOS)
    a = small.getchannel("A")
    coverage = sum(a.histogram()[32:]) / (32 * 32)
    # Heuristic: almost empty or almost solid at 32px tends to be unreadable.
    unreadable_32 = coverage < 0.06 or coverage > 0.90
    return {
        "subject_clipped_by_circle": clipped,
        "subject_fill_ratio": None if fill_ratio is None else round(fill_ratio, 3),
        "fills_too_much_circle": warning_fill,
        "potentially_unreadable_at_32px": unreadable_32,
        "visible_coverage_32_pct": round(coverage * 100, 2),
    }


def scrub_transparent_rgb(img: Image.Image) -> Image.Image:
    """Set fully transparent pixels to black to avoid RGB fringe garbage."""
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    transparent = a.point(lambda p: 255 if p == 0 else 0)
    black = Image.new("RGBA", img.size, (0, 0, 0, 0))
    img.paste(black, (0, 0), transparent)
    return img


def prepare_alpha_icon(src_path: Path, warnings: list[str],
                       profile: Optional[str] = None,
                       safe_subject_scale: Optional[float] = None,
                       master_size: int = 256) -> tuple[Image.Image, bool]:
    """Make a white-on-transparent alpha/team icon master.

    Returns (image, black_bg_cleanup_applied). When the profile is
    civ5_alpha_glyph_black_to_transparent (or the source clearly looks like a
    white-on-black glyph) the robust black-background cleanup runs first;
    otherwise the legacy flat-background path is preserved exactly.
    """
    original = open_rgba(src_path)
    alpha0 = original.getchannel("A")
    use_black_bg = profile == "civ5_alpha_glyph_black_to_transparent"
    if not use_black_bg and profile is None and looks_like_white_on_black(src_path):
        use_black_bg = True
        warnings.append(f"alpha:{src_path.name}: detected white-on-black source; applied black-background glyph cleanup.")

    if use_black_bg:
        scale = safe_subject_scale_for_role("alpha", profile, safe_subject_scale)
        white = black_background_to_white_transparent_glyph(
            original, force_white=True, safe_subject_scale=scale,
            master_size=master_size, warnings=warnings,
        )
        qa_alpha_symbol_complexity(white, "alpha", warnings)
        return white, True

    cleaned = remove_checker_or_flat_background(original, warnings) if alpha0.getextrema()[0] >= 250 else original
    img = normalize_icon_master_from_image(
        cleaned, "alpha", warnings,
        master_size=master_size,
        safe_subject_scale=safe_subject_scale,
    )
    alpha = img.getchannel("A")
    # Convert visible pixels to white while preserving antialiasing alpha.
    white = Image.new("RGBA", img.size, (255, 255, 255, 0))
    white.putalpha(alpha)
    qa_alpha_symbol_complexity(white, "alpha", warnings)
    return white, False


def normalize_icon_master_from_image(img: Image.Image, role: str, warnings: list[str],
                                     master_size: int = 256,
                                     safe_subject_scale: Optional[float] = None) -> Image.Image:
    occupancy = SAFE_OCCUPANCY if safe_subject_scale is None else float(safe_subject_scale)
    tmp = img.convert("RGBA")
    bbox = alpha_bbox(tmp)
    subject = tmp.crop(bbox) if bbox else center_crop_to_square(tmp)
    max_subject = int(round(master_size * occupancy))
    scale = min(max_subject / subject.width, max_subject / subject.height)
    new_size = (max(1, int(round(subject.width * scale))), max(1, int(round(subject.height * scale))))
    subject = subject.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (master_size, master_size), (0, 0, 0, 0))
    canvas.paste(subject, ((master_size - new_size[0]) // 2, (master_size - new_size[1]) // 2), subject)
    return canvas


def remove_checker_or_flat_background(img: Image.Image, warnings: list[str]) -> Image.Image:
    """Best-effort removal for flattened checkerboard/flat black/gray/white backgrounds."""
    img = img.convert("RGBA")
    pixels = img.load()
    corners = [pixels[0, 0], pixels[img.width - 1, 0], pixels[0, img.height - 1], pixels[img.width - 1, img.height - 1]]
    avg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    # Detect common flat backgrounds from corners.
    if max(abs(c[i] - avg[i]) for c in corners for i in range(3)) < 10:
        out = img.copy()
        data = []
        for r, g, b, a in out.getdata():
            dist = math.sqrt((r - avg[0]) ** 2 + (g - avg[1]) ** 2 + (b - avg[2]) ** 2)
            if dist < 30:
                data.append((r, g, b, 0))
            else:
                data.append((r, g, b, a))
        out.putdata(data)
        warnings.append("alpha: removed a likely flat opaque background from the alpha/team icon; inspect preview for accidental holes.")
        return out
    warnings.append("alpha: alpha/team icon appears opaque and not a simple flat background; possible flattened checkerboard/black square needs manual cleanup.")
    return img




def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    return math.sqrt((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2)


def _luma(rgb: tuple[int, int, int]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _saturation_proxy(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)


def remove_edge_connected_flat_background(img: Image.Image, role: str, warnings: list[str],
                                          tolerance: int = 52) -> Image.Image:
    """Remove only the edge-connected flat white/black mat from opaque icon art.

    AI generators often return a circular icon painted on an opaque white or
    black square, sometimes with a small watermark/sparkle in the corner. Using
    the whole opaque square as the subject causes the real icon/flag to be
    scaled down. This function flood-fills only from the image edges when all
    corners look like the same low-saturation white/black mat, leaving the
    interior painting intact.
    """
    src = img.convert("RGBA")
    alpha = src.getchannel("A")
    if alpha.getextrema()[0] < 250:
        return src
    w, h = src.size
    pix = src.load()
    corners = [pix[0, 0][:3], pix[w - 1, 0][:3], pix[0, h - 1][:3], pix[w - 1, h - 1][:3]]
    avg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    spread = max(_color_distance(c, avg) for c in corners)
    avg_luma = _luma(avg)
    avg_sat = _saturation_proxy(avg)
    # Restrict this to true white/black/gray mats. Do not strip normal painted skies/terrain.
    is_bright_mat = avg_luma >= 235 and avg_sat <= 35 and spread <= 35
    is_dark_mat = avg_luma <= 35 and spread <= 35
    # Flattened transparency checkerboards have alternating white/gray corners:
    # high luma and low saturation, but high corner spread. Treat them as a
    # separate edge-connected mask so support icons do not show checker tiles.
    corner_sats = [_saturation_proxy(c) for c in corners]
    corner_lumas = [_luma(c) for c in corners]
    is_checker_mat = (not is_bright_mat and not is_dark_mat
                      and min(corner_lumas) >= 205 and max(corner_sats) <= 45)
    if not (is_bright_mat or is_dark_mat or is_checker_mat):
        return src

    if is_checker_mat:
        hsv = src.convert("RGB").convert("HSV")
        hh, ss, vv = hsv.split()
        low_sat = ss.point(lambda p: 255 if p <= 45 else 0)
        high_val = vv.point(lambda p: 255 if p >= 205 else 0)
        work_mask = ImageChops.multiply(low_sat, high_val)
        marker_value = 128
        for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            if work_mask.getpixel(xy) != 255:
                continue
            ImageDraw.floodfill(work_mask, xy, marker_value, thresh=0)
        mask = work_mask.point(lambda p: 255 if p == marker_value else 0)
    else:
        marker = (255, 0, 255) if avg != (255, 0, 255) else (0, 255, 0)
        work = src.convert("RGB")
        # Pillow's floodfill is much faster and safer than a pure-Python BFS over
        # multi-megapixel AI source art. It only marks regions connected to corners.
        for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            try:
                ImageDraw.floodfill(work, xy, marker, thresh=tolerance)
            except TypeError:
                ImageDraw.floodfill(work, xy, marker)
        r, g, b = work.split()
        if marker == (255, 0, 255):
            mask = r.point(lambda p: 255 if p == 255 else 0)
            mask = ImageChops.multiply(mask, g.point(lambda p: 255 if p == 0 else 0))
            mask = ImageChops.multiply(mask, b.point(lambda p: 255 if p == 255 else 0))
        else:
            mask = r.point(lambda p: 255 if p == 0 else 0)
            mask = ImageChops.multiply(mask, g.point(lambda p: 255 if p == 255 else 0))
            mask = ImageChops.multiply(mask, b.point(lambda p: 255 if p == 0 else 0))
    count = ImageStat.Stat(mask).sum[0] / 255
    if count == 0:
        return src
    out = src.copy()
    a = out.getchannel("A")
    a = ImageChops.subtract(a, mask)

    # AI image tools frequently add a small gray sparkle/watermark in a corner.
    # Once the edge mat is gone, any remaining alpha in the extreme corners is
    # almost always that artifact, and it will poison the crop bbox.
    corner = Image.new("L", (w, h), 0)
    cd = ImageDraw.Draw(corner)
    cw, ch = max(1, int(w * 0.18)), max(1, int(h * 0.18))
    cd.rectangle((0, 0, cw, ch), fill=255)
    cd.rectangle((w - cw, 0, w, ch), fill=255)
    cd.rectangle((0, h - ch, cw, h), fill=255)
    cd.rectangle((w - cw, h - ch, w, h), fill=255)
    corner_leftovers = ImageChops.multiply(a, corner)
    removed_corner = ImageStat.Stat(corner_leftovers).sum[0] / 255
    if removed_corner:
        a = ImageChops.subtract(a, corner)
        warnings.append(f"{role}: removed corner watermark/sparkle residue after mat cleanup ({int(removed_corner)} alpha-px).")

    out.putalpha(a)
    warnings.append(f"{role}: removed edge-connected {'checkerboard' if is_checker_mat else ('white/gray' if is_bright_mat else 'black')} source mat before icon fitting ({count / max(1, w*h):.1%} of pixels).")
    return out

def prune_alpha_components(img: Image.Image, role: str, warnings: list[str],
                           min_area_pct: float = 0.001) -> Image.Image:
    """Remove tiny detached alpha islands such as AI watermark sparkles.

    The threshold is relative to source size so high-resolution source files do
    not preserve a 3,000-pixel watermark while a 512px glyph still keeps real
    symbol pieces.
    """
    src = img.convert("RGBA")
    a = src.getchannel("A")
    if a.getextrema()[1] == 0:
        return src
    if src.width * src.height > 1_000_000:
        # Large AI source art is handled by edge-mat and corner-artifact cleanup.
        # Avoid a very slow pure-Python connected-component pass here.
        return src
    min_area = max(12, int(round(src.width * src.height * float(min_area_pct))))
    binary = a.point(lambda p: 255 if p > 24 else 0)
    kept = _largest_components_mask(binary, min_area)
    removed_mask = ImageChops.subtract(binary, kept)
    removed = ImageStat.Stat(removed_mask).sum[0] / 255
    if removed > 0:
        new_alpha = ImageChops.multiply(a, kept.point(lambda p: 255 if p else 0))
        src.putalpha(new_alpha)
        warnings.append(f"{role}: removed small detached alpha island(s) below {min_area} px before fitting ({int(removed)} px).")
    return src

def _largest_components_mask(mask: Image.Image, min_component_area: int) -> Image.Image:
    """Drop connected components smaller than min_component_area from a binary mask.

    Uses a simple iterative flood fill (no scipy dependency). Mask is mode "L"
    with 0/255 values; returns a cleaned "L" mask.
    """
    w, h = mask.size
    px = mask.load()
    visited = bytearray(w * h)
    keep = Image.new("L", (w, h), 0)
    kp = keep.load()
    for sy in range(h):
        for sx in range(w):
            idx = sy * w + sx
            if visited[idx] or px[sx, sy] == 0:
                continue
            # BFS over this component.
            stack = [(sx, sy)]
            visited[idx] = 1
            component = []
            while stack:
                cx, cy = stack.pop()
                component.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < w and 0 <= ny < h:
                        nidx = ny * w + nx
                        if not visited[nidx] and px[nx, ny] != 0:
                            visited[nidx] = 1
                            stack.append((nx, ny))
            if len(component) >= min_component_area:
                for cx, cy in component:
                    kp[cx, cy] = 255
    return keep


def black_background_to_white_transparent_glyph(
    img: Image.Image,
    black_threshold: int = 100,
    white_threshold: int = 200,
    force_white: bool = True,
    remove_small_islands: bool = True,
    min_component_area: int = 12,
    safe_subject_scale: float = 0.76,
    master_size: int = 1024,
    warnings: Optional[list[str]] = None,
) -> Image.Image:
    """Convert an opaque black-background white-glyph PNG to white-on-transparent.

    Near-black pixels become fully transparent; bright glyph pixels become opaque
    (white when force_white). Mid-tones get a proportional alpha so antialiased
    edges survive. Small color-noise islands are optionally pruned, then the glyph
    is centered on a transparent canvas and scaled to the safe occupancy.

    Operates at the source resolution then normalizes to master_size, so detail is
    preserved before downscaling to the final ladder.
    """
    src = img.convert("RGBA")
    r, g, b, a = src.split()
    # Luma approximates perceived brightness of the (assumed) grayscale glyph.
    gray = Image.merge("RGB", (r, g, b)).convert("L")
    gpx = gray.load()
    apx = a.load()
    w, h = src.size

    # Build a new alpha channel from brightness with a soft ramp between
    # black_threshold and white_threshold to retain antialiasing. The original
    # implementation looped over every source pixel in Python; this vectorized
    # Pillow point operation is much faster on 2K/3K AI art.
    span = max(1, white_threshold - black_threshold)
    # Fast path for true glyph sources: fully opaque black background with only
    # black/white values should convert to a binary alpha mask (0 or 255). This
    # prevents washed-out team icons / unit flags if a source has no real
    # antialiasing to preserve.
    gmin, gmax = gray.getextrema()
    gray_hist = gray.histogram()
    non_binary_bins = sum(gray_hist[i] for i in range(1, 255))
    binary_source = (a.getextrema()[0] >= 250 and gmin == 0 and gmax == 255 and non_binary_bins == 0)
    if binary_source:
        new_alpha = gray.point(lambda lum: 255 if lum > black_threshold else 0)
    else:
        def ramp(lum: int) -> int:
            if lum <= black_threshold:
                return 0
            if lum >= white_threshold:
                return 255
            return int(round((lum - black_threshold) / span * 255))
        new_alpha = gray.point(ramp)
    # Respect pre-existing transparency in the source.
    if a.getextrema()[0] < 250:
        new_alpha = ImageChops.multiply(new_alpha, a)

    if remove_small_islands:
        # Most generator watermark/sparkle artifacts are below the elevated
        # black_threshold=100 and disappear here. Full connected-component
        # cleanup is kept only for smaller sources; pure-Python component scans
        # over multi-megapixel PNGs make batch runs unacceptably slow.
        if w * h <= 1_000_000:
            binary = new_alpha.point(lambda p: 255 if p > 24 else 0)
            dynamic_min_area = max(1, int(min_component_area), int(round(w * h * 0.001)))
            kept = _largest_components_mask(binary, dynamic_min_area)
            removed_mask = ImageChops.subtract(binary, kept)
            removed = ImageStat.Stat(removed_mask).sum[0] / 255
            if removed and warnings is not None:
                warnings.append(f"black-bg glyph cleanup: removed detached component(s) below {dynamic_min_area} px ({int(removed)} px).")
            new_alpha = ImageChops.multiply(new_alpha, kept.point(lambda p: 255 if p else 0))

    if force_white:
        glyph = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    else:
        glyph = Image.merge("RGBA", (r, g, b, Image.new("L", (w, h), 0)))
    glyph.putalpha(new_alpha)

    if warnings is not None:
        cov = sum(new_alpha.histogram()[24:]) / max(1, w * h)
        if cov < 0.01:
            warnings.append("black-bg glyph cleanup: almost nothing survived; source may not be a white-on-black glyph.")
        elif cov > 0.85:
            warnings.append("black-bg glyph cleanup: nearly everything survived; source may not have a true black background.")

    # Crop to the surviving glyph and re-fit into a transparent square master.
    bbox = alpha_bbox(glyph, threshold=8)
    subject = glyph.crop(bbox) if bbox else glyph
    return _fit_subject_to_canvas(subject, master_size, int(round(master_size * safe_subject_scale)))


def looks_like_white_on_black(src_path: Path) -> bool:
    """Heuristic: fully (or near) opaque source whose corners are near-black and
    whose bright pixels form a sparse glyph. Used to auto-route legacy alpha
    sources into black-bg cleanup only when it is clearly appropriate.
    """
    try:
        img = open_rgba(src_path)
    except Exception:
        return False
    a = img.getchannel("A")
    if a.getextrema()[0] < 250:
        return False  # already has transparency; not a flat black background.
    small = img.convert("RGB").resize((48, 48))
    corners = [small.getpixel((0, 0)), small.getpixel((47, 0)),
               small.getpixel((0, 47)), small.getpixel((47, 47))]
    corners_dark = all(max(c) <= 45 for c in corners)
    gray = small.convert("L")
    # Pillow 13 deprecated Image.getdata(); use get_flattened_data when present.
    gray_pixels = gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata()
    bright = sum(1 for p in gray_pixels if p >= 160) / (48 * 48)
    return corners_dark and 0.01 <= bright <= 0.6


PAINTED_FLAG_MESSAGE = (
    "Unit flag source appears to be a painted scene, not a 32px glyph. "
    "Redraw manually as white silhouette on transparent background."
)


def assess_unit_flag_source(src_path: Path) -> dict:
    """Heuristically decide whether a source looks like a painted scene.

    A Civ V unit flag should be a sparse white glyph on transparency. We flag
    sources that are opaque, high-coverage, edge-touching, and high-detail.
    Returns metrics plus a 'painted' boolean and human-readable 'reasons'.
    """
    img = open_rgba(src_path)
    a = img.getchannel("A")
    amin, amax = a.getextrema()
    total = img.width * img.height
    hist = a.histogram()
    opaque_pct = sum(hist[250:]) / total
    coverage = sum(hist[64:]) / total  # anything meaningfully visible
    fully_opaque = amin >= 250
    # Edge density proxy for detail.
    from PIL import ImageFilter
    edges = a.filter(ImageFilter.FIND_EDGES()).point(lambda p: 255 if p > 25 else 0)
    edge_ratio = ImageStat.Stat(edges).sum[0] / 255 / total
    # Edge-touching test: does the visible alpha reach the source border?
    bbox = alpha_bbox(img)
    edge_touch = False
    if bbox:
        l, t, r, b = bbox
        edge_touch = (l <= 1 or t <= 1 or r >= img.width - 1 or b >= img.height - 1)
    # Color richness: a glyph is near-monochrome; a painting has many colors.
    small = img.convert("RGB").resize((32, 32))
    colors = small.getcolors(maxcolors=32 * 32)
    distinct = len(colors) if colors is not None else 32 * 32
    reasons = []
    if fully_opaque:
        reasons.append("source is fully opaque (no transparent background)")
    if coverage > 0.55:
        reasons.append(f"visible coverage {coverage:.0%} is too high for a glyph")
    if edge_touch and coverage > 0.4:
        reasons.append("subject touches the image border (full-bleed)")
    if edge_ratio > 0.12:
        reasons.append(f"high edge/detail density ({edge_ratio:.0%})")
    if distinct > 200:
        reasons.append(f"{distinct} distinct colors suggests a full-color painting")
    # Painted if it is opaque AND shows at least one detail/coverage symptom.
    painted = fully_opaque and len(reasons) >= 2
    return {
        "alpha_min": amin, "alpha_max": amax,
        "opaque_pct": round(opaque_pct * 100, 2),
        "coverage_pct": round(coverage * 100, 2),
        "edge_ratio_pct": round(edge_ratio * 100, 2),
        "distinct_colors_32": distinct,
        "edge_touching": edge_touch,
        "painted": painted,
        "reasons": reasons,
    }


def prepare_unit_flag(src_path: Path, label: str, warnings: list[str],
                      allow_painted: bool = False,
                      profile: Optional[str] = None,
                      safe_subject_scale: Optional[float] = None) -> tuple[Optional[Image.Image], bool]:
    """Return (32x32 white-on-transparent flag, black_bg_cleanup_applied).

    When the profile is civ5_unit_flag_black_to_transparent, the source is run
    through black-background glyph cleanup BEFORE the painted-scene assessment so
    a correct white-on-black glyph (which is fully opaque) is not rejected.
    Legacy strict behavior is preserved when no flag profile is selected.
    """
    use_black_bg_profile = profile == "civ5_unit_flag_black_to_transparent"
    auto_white_on_black = False
    if not use_black_bg_profile and profile is None and looks_like_white_on_black(src_path):
        auto_white_on_black = True
        warnings.append(
            f"unit_flag:{label}: detected white-on-black glyph source; "
            "applied black-background cleanup instead of rejecting it as painted art."
        )

    if use_black_bg_profile or auto_white_on_black:
        original = open_rgba(src_path)
        effective_profile = "civ5_unit_flag_black_to_transparent"
        scale = safe_subject_scale_for_role("unit_flag", effective_profile, safe_subject_scale)
        cleaned = black_background_to_white_transparent_glyph(
            original, force_white=True, safe_subject_scale=scale,
            master_size=PROFILES[effective_profile].get("intermediate_size", 256),
            warnings=warnings,
        )
        # Assess the CLEANED glyph (now white-on-transparent) for readability.
        small = cleaned.resize((UNIT_FLAG_CELL, UNIT_FLAG_CELL), Image.Resampling.LANCZOS)
        qa_alpha_symbol_complexity(small, f"unit_flag:{label}", warnings)
        return small, True

    assessment = assess_unit_flag_source(src_path)
    if assessment["painted"]:
        detail = "; ".join(assessment["reasons"])
        if allow_painted:
            warnings.append(f"STRONG: unit_flag:{label}: {PAINTED_FLAG_MESSAGE} (allowed via --allow-painted-flags) [{detail}]")
        else:
            warnings.append(f"FATAL: unit_flag:{label}: {PAINTED_FLAG_MESSAGE} Skipped; pass --allow-painted-flags to force, or set profile civ5_unit_flag_black_to_transparent for white-on-black glyphs. [{detail}]")
            return None, False
    img = normalize_icon_master(src_path, f"unit_flag:{label}", warnings)
    alpha = img.getchannel("A")
    white = Image.new("RGBA", img.size, (255, 255, 255, 0))
    white.putalpha(alpha)
    small = white.resize((UNIT_FLAG_CELL, UNIT_FLAG_CELL), Image.Resampling.LANCZOS)
    qa_alpha_symbol_complexity(small, f"unit_flag:{label}", warnings)
    return small, False


def qa_alpha_symbol_complexity(img: Image.Image, name: str, warnings: list[str]) -> None:
    alpha = img.convert("RGBA").getchannel("A")
    hist = alpha.histogram()
    opaqueish = sum(hist[180:])
    total = img.width * img.height
    coverage = opaqueish / total
    if coverage < 0.03:
        warnings.append(f"{name}: symbol coverage is only {coverage:.1%}; it may be invisible in Civ V.")
    if coverage > 0.50:
        warnings.append(f"{name}: symbol coverage is {coverage:.1%}; likely a solid/painted background rather than a simple glyph.")
    # Edge count proxy for detailed paintings used as flags.
    edges = alpha.filter(ImageFilterSafe.FIND_EDGES()).point(lambda p: 255 if p > 25 else 0)
    edge_ratio = ImageStat.Stat(edges).sum[0] / 255 / total
    if img.width <= 32 and edge_ratio > 0.12:
        warnings.append(f"{name}: high edge/detail density at 32px; painted source suspected; use a hand-drawn simple white silhouette/glyph.")
    bbox = alpha_bbox(img)
    if img.width <= 32 and bbox:
        l, t, r, b = bbox
        fill_box = (r - l) * (b - t) / total
        if fill_box > 0 and coverage / fill_box > 0.82:
            warnings.append(f"{name}: alpha shape fills most of its bounding box; this looks more like a block/painting than an icon glyph.")


class ImageFilterSafe:
    @staticmethod
    def FIND_EDGES():
        from PIL import ImageFilter
        return ImageFilter.FIND_EDGES


def fit_center_crop(img: Image.Image, target_w: int, target_h: int, opaque: bool = True) -> Image.Image:
    img = img.convert("RGBA")
    scale = max(target_w / img.width, target_h / img.height)
    new_w, new_h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left, top = (new_w - target_w) // 2, (new_h - target_h) // 2
    cropped = resized.crop((left, top, left + target_w, top + target_h))
    if opaque:
        bg = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
        bg.paste(cropped, (0, 0), cropped)
        return bg
    return cropped


# ---------------------------------------------------------------------------
# Existing mod atlas/usage parsing / selection
# ---------------------------------------------------------------------------



def path_is_inside(child: Path, parent: Path) -> bool:
    """Return True when child resolves inside parent (or equals parent)."""
    child_resolved = child.resolve()
    parent_resolved = parent.resolve()
    return child_resolved == parent_resolved or parent_resolved in child_resolved.parents


def assert_inside_mod_data_dir(target: Path, mod_data_dir: Path) -> Path:
    """Resolve and validate a write target before touching selected mod data."""
    target_resolved = target.resolve()
    mod_resolved = mod_data_dir.resolve()
    if not path_is_inside(target_resolved, mod_resolved):
        raise SystemExit(f"Refusing to write outside mod_data_dir: {target_resolved} (mod_data_dir: {mod_resolved})")
    return target_resolved

SIZE_SUFFIX_RE = re.compile(r"(?i)(?:[_-]?)(256|128|80|64|48|45|32|24)(?=\.dds$)")


def infer_atlas_stem(filename: str, size: Optional[int]) -> str:
    """Return the filename stem before a Civ V size suffix.

    Supports Atlas256.dds, Atlas_256.dds, and Atlas-256.dds without returning
    stems such as filename.dds, which previously caused filename.dds_256.dds.
    """
    name = Path(filename).name
    if name.lower().endswith(".dds"):
        name = name[:-4]
    sizes = [str(size)] if size else ["256", "128", "80", "64", "48", "45", "32", "24"]
    for token in sizes:
        m = re.search(rf"(?i)(?:[_-]?){token}$", name)
        if m:
            return name[:m.start()]
    return name


def parse_existing_atlas_definitions(mod_data_dir: Optional[Path], warnings: Optional[list[str]] = None) -> list[AtlasDefinition]:
    if not mod_data_dir or not mod_data_dir.exists():
        return []
    defs: list[AtlasDefinition] = []
    for path in list(mod_data_dir.rglob("*.xml")) + list(mod_data_dir.rglob("*.sql")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        defs.extend(parse_xml_atlas_rows(text, str(path)))
        defs.extend(parse_sql_atlas_rows(text, str(path), warnings))
    return defs


def _xml_attrs(fragment: str) -> dict[str, str]:
    """Parse name="value" attributes from an XML start tag fragment."""
    return {m.group(1): m.group(2) for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', fragment)}


def parse_xml_atlas_rows(text: str, source: str) -> list[AtlasDefinition]:
    rows: list[AtlasDefinition] = []

    def emit(atlas, size, filename, per_row, per_col):
        if atlas and size and filename and per_row and per_col:
            try:
                rows.append(AtlasDefinition(atlas, int(size), Path(filename).name,
                                            int(per_row), int(per_col), source))
            except ValueError:
                pass

    # 1) Nested element rows: <Row><Atlas>..</Atlas>...</Row>
    for row in re.findall(r"<Row(?:\s+[^>]*)?>(.*?)</Row>", text, flags=re.I | re.S):
        def tag(name: str) -> Optional[str]:
            m = re.search(rf"<{name}>(.*?)</{name}>", row, flags=re.I | re.S)
            return m.group(1).strip() if m else None
        emit(tag("Atlas"), tag("IconSize"), tag("Filename"),
             tag("IconsPerRow"), tag("IconsPerColumn"))

    # 2) Self-closing attribute rows: <Row Atlas=".." IconSize=".." ... />
    for frag in re.findall(r"<Row\b([^>]*?)/>", text, flags=re.I | re.S):
        a = _xml_attrs(frag)
        if "Atlas" in a or "Filename" in a:
            emit(a.get("Atlas"), a.get("IconSize"), a.get("Filename"),
                 a.get("IconsPerRow"), a.get("IconsPerColumn"))

    # 3) Update/Set rows merging <Where .../> and <Set .../> attributes.
    for block in re.findall(r"<Update\b[^>]*>(.*?)</Update>", text, flags=re.I | re.S):
        merged: dict[str, str] = {}
        for frag in re.findall(r"<(?:Where|Set)\b([^>]*?)/?>", block, flags=re.I | re.S):
            merged.update(_xml_attrs(frag))
        # Update/Set also allows nested <Filename>.. element children under <Set>.
        for name in ("Atlas", "IconSize", "Filename", "IconsPerRow", "IconsPerColumn"):
            m = re.search(rf"<{name}>(.*?)</{name}>", block, flags=re.I | re.S)
            if m and name not in merged:
                merged[name] = m.group(1).strip()
        if "Atlas" in merged and "Filename" in merged:
            emit(merged.get("Atlas"), merged.get("IconSize"), merged.get("Filename"),
                 merged.get("IconsPerRow"), merged.get("IconsPerColumn"))
    return rows


ATLAS_DEFAULT_COLUMNS = ["Atlas", "IconSize", "Filename", "IconsPerRow", "IconsPerColumn"]


def parse_sql_atlas_rows(text: str, source: str, warnings: Optional[list[str]] = None) -> list[AtlasDefinition]:
    """Parse only statements that actually target IconTextureAtlases.

    Supports INSERT INTO / INSERT OR REPLACE INTO / REPLACE INTO, optional
    column lists (with arbitrary column order), and multiple value tuples in a
    single statement. Statements targeting any other table are ignored, so
    decoy value sequences inside Language_en_US, Units, etc. no longer produce
    false-positive atlas rows.
    """
    rows: list[AtlasDefinition] = []
    stmt_re = re.compile(
        r"(?:INSERT\s+OR\s+REPLACE\s+INTO|INSERT\s+INTO|REPLACE\s+INTO)\s+"
        r"[`\"\[]?IconTextureAtlases[`\"\]]?\s*"
        r"(?:\((?P<cols>[^)]*)\))?\s*VALUES\s*(?P<vals>.*?);",
        flags=re.I | re.S,
    )
    for m in stmt_re.finditer(text):
        cols = None
        if m.group("cols"):
            cols = [c.strip().strip('`[]"') for c in m.group("cols").split(",")]
        for tup in re.findall(r"\((.*?)\)", m.group("vals"), flags=re.S):
            vals = [strip_sql_string(v) for v in split_sql_values(tup)]
            order = cols if cols else ATLAS_DEFAULT_COLUMNS
            if len(vals) != len(order):
                if warnings is not None:
                    warnings.append(
                        f"{Path(source).name}: skipped an IconTextureAtlases tuple with "
                        f"{len(vals)} value(s) for {len(order)} column(s)."
                    )
                continue
            data = dict(zip(order, vals))
            try:
                rows.append(AtlasDefinition(
                    atlas=data["Atlas"],
                    size=int(data["IconSize"]),
                    filename=Path(data["Filename"]).name,
                    icons_per_row=int(data["IconsPerRow"]),
                    icons_per_column=int(data["IconsPerColumn"]),
                    source_file=source,
                ))
            except (KeyError, ValueError):
                if warnings is not None:
                    warnings.append(f"{Path(source).name}: could not parse an IconTextureAtlases row; check column names.")
    return rows


def detect_large_image_names(mod_data_dir: Optional[Path]) -> dict[str, str]:
    """Find existing DawnOfManImage/MapImage/leader-scene DDS names in a mod.

    Returns a dict with any of the keys 'dawn', 'map', 'leader_scene'. These
    let the pipeline regenerate art under the mod's exact existing filenames
    instead of inventing new ones that would not be referenced anywhere.
    """
    found: dict[str, str] = {}
    if not mod_data_dir or not mod_data_dir.exists():
        return found
    for path in list(mod_data_dir.rglob("*.sql")) + list(mod_data_dir.rglob("*.xml")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Civilizations.DawnOfManImage / MapImage (SQL value, SQL assignment, or XML element).
        for key, col in (("dawn", "DawnOfManImage"), ("map", "MapImage")):
            if key in found:
                continue
            m = re.search(rf"{col}\s*=\s*['\"]([^'\"]+\.dds)['\"]", text, flags=re.I)
            if not m:
                m = re.search(rf"<{col}>\s*([^<]+\.dds)\s*</{col}>", text, flags=re.I)
            if not m:
                # Positional INSERT into Civilizations: grab any *.dds whose name hints at the role.
                for cand in re.findall(r"['\"]([^'\"]+\.dds)['\"]", text):
                    low = cand.lower()
                    if key == "dawn" and "dawn" in low:
                        m = re.match(r"(.*)", cand); found[key] = Path(cand).name; break
                    if key == "map" and low.startswith("map"):
                        found[key] = Path(cand).name; break
            if m and key not in found:
                found[key] = Path(m.group(1)).name
        # Leader scene fallback DDS referenced inside a *Scene*.xml.
        if "leader_scene" not in found and "scene" in path.name.lower():
            m = re.search(r"<FallbackImage>\s*([^<]+\.dds)\s*</FallbackImage>", text, flags=re.I)
            if not m:
                m = re.search(r"['\"]([^'\"]*[Ss]cene[^'\"]*\.dds)['\"]", text)
            if m:
                found["leader_scene"] = Path(m.group(1)).name
    return found


def resolve_large_image_names(cfg: PipelineConfig, warnings: list[str]) -> dict[str, str]:
    """Decide final DDS names: explicit override > auto-detected > default."""
    detected = detect_large_image_names(cfg.mod_data_dir)
    names: dict[str, str] = {}

    def pick(key: str, override: str, default: str) -> str:
        if override:
            return Path(override).name
        if key in detected:
            warnings.append(f"Auto-detected existing {key} image name '{detected[key]}' from mod data; generating under that name.")
            return detected[key]
        return default

    names["dawn"] = pick("dawn", cfg.dawn_output_name, f"{cfg.prefix}_DAWN_OF_MAN.dds")
    names["map"] = pick("map", cfg.map_output_name, f"Map_{cfg.prefix}.dds")
    names["leader_scene"] = pick("leader_scene", cfg.leader_scene_output_name, f"{cfg.prefix}_LEADER_SCENE.dds")
    return names


def parse_existing_icon_usage(mod_data_dir: Optional[Path]) -> list[IconUsage]:
    if not mod_data_dir or not mod_data_dir.exists():
        return []
    uses: list[IconUsage] = []
    for path in list(mod_data_dir.rglob("*.xml")) + list(mod_data_dir.rglob("*.sql")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix.lower() == ".xml":
            uses.extend(parse_xml_icon_usage(text, str(path)))
        else:
            uses.extend(parse_sql_icon_usage(text, str(path)))
    return uses


USAGE_TABLES = (
    "Civilizations|Leaders|Units|UnitPromotions|Promotions|Buildings|"
    "Improvements|Resources|Policies|Technologies|Specialists|Traits"
)


def parse_xml_icon_usage(text: str, source: str) -> list[IconUsage]:
    uses: list[IconUsage] = []
    table_stack = re.findall(
        rf"<(?P<table>{USAGE_TABLES})>(.*?)</(?P=table)>",
        text, flags=re.I | re.S,
    )
    for table, body in table_stack:
        # Nested element rows.
        for row in re.findall(r"<Row(?:\s+[^>]*)?>(.*?)</Row>", body, flags=re.I | re.S):
            def tag(name: str) -> str:
                m = re.search(rf"<{name}>(.*?)</{name}>", row, flags=re.I | re.S)
                return m.group(1).strip() if m else ""
            _maybe_add_usage(uses, table, source,
                             type_name=tag("Type"),
                             icon_atlas=tag("IconAtlas"),
                             portrait=tag("PortraitIndex"),
                             alpha_atlas=tag("AlphaIconAtlas"),
                             flag_atlas=tag("UnitFlagAtlas"),
                             flag_offset=tag("UnitFlagIconOffset"))
        # Self-closing attribute rows.
        for frag in re.findall(r"<Row\b([^>]*?)/>", body, flags=re.I | re.S):
            a = _xml_attrs(frag)
            _maybe_add_usage(uses, table, source,
                             type_name=a.get("Type", ""),
                             icon_atlas=a.get("IconAtlas", ""),
                             portrait=a.get("PortraitIndex", ""),
                             alpha_atlas=a.get("AlphaIconAtlas", ""),
                             flag_atlas=a.get("UnitFlagAtlas", ""),
                             flag_offset=a.get("UnitFlagIconOffset", ""))
    return uses


def _maybe_add_usage(uses, table, source, type_name, icon_atlas, portrait,
                     alpha_atlas, flag_atlas, flag_offset) -> None:
    if not type_name:
        return
    use = IconUsage(
        table=table,
        type_name=type_name,
        icon_atlas=icon_atlas,
        portrait_index=int(portrait) if str(portrait).lstrip("-").isdigit() else None,
        alpha_icon_atlas=alpha_atlas,
        unit_flag_atlas=flag_atlas,
        unit_flag_icon_offset=int(flag_offset) if str(flag_offset).lstrip("-").isdigit() else None,
        source_file=source,
    )
    if use.icon_atlas or use.alpha_icon_atlas or use.unit_flag_atlas or use.portrait_index is not None:
        uses.append(use)


def parse_sql_icon_usage(text: str, source: str) -> list[IconUsage]:
    uses: list[IconUsage] = []
    insert_re = re.compile(r"INSERT\s+INTO\s+(?P<table>\w+)\s*\((?P<cols>[^)]*)\)\s*VALUES\s*(?P<vals>.*?);", re.I | re.S)
    for ins in insert_re.finditer(text):
        cols = [c.strip().strip('`[]"') for c in ins.group('cols').split(',')]
        interested = {"Type", "IconAtlas", "PortraitIndex", "AlphaIconAtlas", "UnitFlagAtlas", "UnitFlagIconOffset"}
        if not interested.intersection(cols):
            continue
        for tup in re.findall(r"\((.*?)\)", ins.group('vals'), flags=re.S):
            vals = split_sql_values(tup)
            if len(vals) != len(cols):
                continue
            data = dict(zip(cols, vals))
            if "Type" not in data:
                continue
            uses.append(IconUsage(
                table=ins.group('table'), type_name=strip_sql_string(data.get('Type', '')),
                icon_atlas=strip_sql_string(data.get('IconAtlas', '')),
                portrait_index=to_int(data.get('PortraitIndex')),
                alpha_icon_atlas=strip_sql_string(data.get('AlphaIconAtlas', '')),
                unit_flag_atlas=strip_sql_string(data.get('UnitFlagAtlas', '')),
                unit_flag_icon_offset=to_int(data.get('UnitFlagIconOffset')),
                source_file=source,
            ))
    update_re = re.compile(r"UPDATE\s+(?P<table>\w+)\s+SET\s+(?P<sets>.*?)\s+WHERE\s+Type\s*=\s*['\"](?P<type>[^'\"]+)['\"]", re.I | re.S)
    for up in update_re.finditer(text):
        data = parse_sql_assignments(up.group('sets'))
        if data:
            uses.append(IconUsage(
                table=up.group('table'), type_name=up.group('type'),
                icon_atlas=strip_sql_string(data.get('IconAtlas', '')),
                portrait_index=to_int(data.get('PortraitIndex')),
                alpha_icon_atlas=strip_sql_string(data.get('AlphaIconAtlas', '')),
                unit_flag_atlas=strip_sql_string(data.get('UnitFlagAtlas', '')),
                unit_flag_icon_offset=to_int(data.get('UnitFlagIconOffset')),
                source_file=source,
            ))
    return uses


def split_sql_values(text: str) -> list[str]:
    vals, cur, quote = [], [], None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    cur.append(text[i + 1]); i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch; cur.append(ch)
        elif ch == ',':
            vals.append(''.join(cur).strip()); cur = []
        else:
            cur.append(ch)
        i += 1
    vals.append(''.join(cur).strip())
    return vals


def strip_sql_string(value: str) -> str:
    value = (value or '').strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        return value[1:-1].replace(value[0] * 2, value[0])
    return "" if value.upper() == "NULL" else value


def to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    value = str(value).strip().strip('"\'')
    return int(value) if re.fullmatch(r"-?\d+", value) else None


def parse_sql_assignments(text: str) -> dict[str, str]:
    out = {}
    for part in split_sql_values(text):
        if '=' in part:
            k, v = part.split('=', 1)
            out[k.strip().strip('`[]"')] = v.strip()
    return out


def choose_atlas_selection(cfg: PipelineConfig, warnings: list[str], alpha: bool = False) -> AtlasSelection:
    existing = parse_existing_atlas_definitions(cfg.mod_data_dir, warnings)
    up = cfg.prefix.upper()
    if alpha:
        explicit_name = cfg.alpha_atlas_name or f"{up}_ALPHA_ATLAS"
        candidates = [d for d in existing if "ALPHA" in d.atlas.upper() and d.icons_per_row == 1 and d.icons_per_column == 1]
        complete = {d.atlas: [] for d in candidates}
        for d in candidates:
            complete[d.atlas].append(d)
        for name, defs in complete.items():
            if {d.size for d in defs} >= set(ALPHA_ICON_SIZES):
                if not cfg.alpha_atlas_name or name == cfg.alpha_atlas_name:
                    warnings.append(f"Reusing existing alpha atlas definition: {name}.")
                    return AtlasSelection(name, {d.size: Path(d.filename).name for d in defs}, 1, 1)
        return AtlasSelection(explicit_name, {size: f"{cfg.prefix}_Alpha_{size}.dds" for size in ALPHA_ICON_SIZES}, 1, 1)

    if cfg.icon_atlas_name and cfg.icon_atlas_stem:
        explicit_stem = infer_atlas_stem(cfg.icon_atlas_stem, None)
        return AtlasSelection(cfg.icon_atlas_name, {size: f"{explicit_stem}_{size}.dds" for size in NORMAL_ATLAS_SIZES}, NORMAL_GRID, NORMAL_GRID)
    candidates: dict[str, list[AtlasDefinition]] = {}
    for d in existing:
        if d.icons_per_row == NORMAL_GRID and d.icons_per_column == NORMAL_GRID and d.size in NORMAL_ATLAS_SIZES:
            if "ALPHA" not in d.atlas.upper() and "FLAG" not in d.atlas.upper():
                candidates.setdefault(d.atlas, []).append(d)
    complete = {k: v for k, v in candidates.items() if {d.size for d in v} >= set(NORMAL_ATLAS_SIZES)}
    if complete and cfg.preset != "generated-separate-atlases":
        preferred = None
        for name in complete:
            if name.upper() in {f"{up}_ICON_ATLAS", f"{up}_CIV_ICON_ATLAS", "FLORENCE_ICON_ATLAS"}:
                preferred = name; break
        name = preferred or sorted(complete)[0]
        files = {d.size: Path(d.filename).name for d in complete[name]}
        warnings.append(f"Reusing existing combined IconTextureAtlases definition: {name} -> existing DDS filenames.")
        return AtlasSelection(name, files, NORMAL_GRID, NORMAL_GRID)
    if existing and cfg.preset == "existing-combined-atlas":
        warnings.append("Existing mod data was found, but no complete 4x4 normal atlas size ladder was detected. Generating a new XML template only; manually reconcile atlas names before importing.")
    stem = infer_atlas_stem(cfg.icon_atlas_stem, None) if cfg.icon_atlas_stem else f"{cfg.prefix}_IconAtlas"
    return AtlasSelection(cfg.icon_atlas_name or f"{up}_ICON_ATLAS", {size: f"{stem}_{size}.dds" for size in NORMAL_ATLAS_SIZES}, NORMAL_GRID, NORMAL_GRID)



def choose_unit_flag_filename(cfg: PipelineConfig, flag_atlas: str, flag_stem: str, warnings: list[str]) -> str:
    """Return the 32px unit-flag DDS filename, preferring an existing mod atlas row.

    This preserves legacy mods that use filenames like NabataeaUnitFlags32.dds
    instead of the generator's fallback NabataeaUnitFlags_32.dds.
    """
    for d in parse_existing_atlas_definitions(cfg.mod_data_dir, warnings):
        if (d.atlas == flag_atlas and d.size == 32
                and d.icons_per_row == UNIT_FLAG_GRID and d.icons_per_column == UNIT_FLAG_GRID):
            warnings.append(f"Reusing existing unit flag atlas definition: {flag_atlas} -> {Path(d.filename).name}.")
            return Path(d.filename).name
    return f"{flag_stem}_32.dds"

def choose_icon_atlas(cfg: PipelineConfig, warnings: list[str]) -> tuple[str, str]:
    sel = choose_atlas_selection(cfg, warnings, alpha=False)
    return sel.atlas, sel.stem


def apply_existing_or_explicit_indexes(cfg: PipelineConfig, normal_items: list[AssetSpec], warnings: list[str]) -> None:
    usage = parse_existing_icon_usage(cfg.mod_data_dir)
    # Civ V BNW promotion icons live in UnitPromotions (some older mods use a
    # bare Promotions table); accept both. Support icons may reuse promotion,
    # building, or other rows when an explicit #TYPE_NAME is supplied.
    promo_tables = {"unitpromotions", "promotions"}
    by_role = {
        'civ': [u for u in usage if u.table.lower() == 'civilizations'],
        'leader': [u for u in usage if u.table.lower() == 'leaders'],
        'unit': [u for u in usage if u.table.lower() == 'units'],
        'building': [u for u in usage if u.table.lower() == 'buildings'],
        'promotion': [u for u in usage if u.table.lower() in promo_tables],
        'support': [u for u in usage if u.table.lower() in promo_tables or u.table.lower() == 'buildings'],
        'dummy': [u for u in usage if u.table.lower() == 'buildings'],
        'trait': [u for u in usage if u.table.lower() == 'traits'],
    }
    used: set[int] = set()
    for item in normal_items:
        key = item.label.lower()
        if key in cfg.explicit_indexes:
            item.portrait_index = cfg.explicit_indexes[key]
            warnings.append(f"Explicit PortraitIndex {item.portrait_index} applied to {item.role}:{item.label}.")
        else:
            match = None
            if item.type_name:
                # Exact #TYPE_NAME match wins; prefer rows that actually carry an index.
                match = next((u for u in usage if u.type_name.upper() == item.type_name.upper() and u.portrait_index is not None), None)
                if match is None:
                    warnings.append(f"{item.role}:{item.label}: #TYPE_NAME {item.type_name} not found in existing usage; will assign a free index.")
            elif item.role in by_role and len(by_role[item.role]) == 1 and by_role[item.role][0].portrait_index is not None:
                match = by_role[item.role][0]
            if match:
                item.atlas = match.icon_atlas or item.atlas
                item.portrait_index = match.portrait_index
                item.type_name = match.type_name
                warnings.append(f"Reused existing {match.type_name} ({match.table}) IconAtlas/PortraitIndex {item.atlas}/{item.portrait_index} from {Path(match.source_file).name}.")
        if item.portrait_index is not None:
            used.add(item.portrait_index)
    next_index = 0
    for item in normal_items:
        if item.portrait_index is None:
            while next_index in used:
                next_index += 1
            item.portrait_index = next_index
            used.add(next_index)
            next_index += 1
    for item in normal_items:
        if item.portrait_index < 0 or item.portrait_index >= NORMAL_GRID * NORMAL_GRID:
            raise SystemExit(f"PortraitIndex for {item.role}:{item.label} must fit the 4x4 atlas; got {item.portrait_index}")


def find_mod_replacement_targets(cfg: PipelineConfig, generated_files: list[Path]) -> list[dict]:
    """Find same-name DDS replacements strictly inside cfg.mod_data_dir.

    This intentionally indexes only files below the final merged mod_data_dir. It
    never scans a parent MODS directory or sibling mods.
    """
    if not cfg.mod_data_dir or not cfg.mod_data_dir.exists():
        return []
    mod_root = cfg.mod_data_dir.resolve()
    mod_files: dict[str, Path] = {}
    duplicates: dict[str, list[Path]] = {}
    for p in cfg.mod_data_dir.rglob("*"):
        if not p.is_file():
            continue
        resolved = assert_inside_mod_data_dir(p, mod_root)
        key = p.name.lower()
        if key in mod_files:
            duplicates.setdefault(key, [mod_files[key]]).append(resolved)
            continue
        mod_files[key] = resolved
    replacements = []
    for src in generated_files:
        dst = mod_files.get(src.name.lower())
        duplicate_paths = duplicates.get(src.name.lower(), [])
        replacements.append({
            "generated": str(src),
            "mod_target": str(dst) if dst else "",
            "will_replace": bool(dst),
            "duplicates": [str(p) for p in duplicate_paths],
        })
    return replacements


def select_modinfo_file(mod_data_dir: Optional[Path]) -> Optional[Path]:
    """Select the single .modinfo file directly under the selected mod root."""
    if not mod_data_dir:
        return None
    if not mod_data_dir.exists():
        raise SystemExit(f"mod_data_dir does not exist: {mod_data_dir}")
    mod_root = mod_data_dir.resolve()
    root_modinfos = sorted(p for p in mod_data_dir.glob("*.modinfo") if p.is_file())
    if len(root_modinfos) > 1:
        names = ", ".join(str(p.resolve()) for p in root_modinfos)
        raise SystemExit(f"Expected one .modinfo directly under mod_data_dir, found {len(root_modinfos)}: {names}")
    if root_modinfos:
        return assert_inside_mod_data_dir(root_modinfos[0], mod_root)
    nested = sorted(p for p in mod_data_dir.rglob("*.modinfo") if p.is_file())
    if nested:
        names = ", ".join(str(p.resolve()) for p in nested)
        raise SystemExit(f"No .modinfo directly under mod_data_dir; refusing to modify nested .modinfo file(s): {names}")
    return None


def group_warnings_by_severity(warnings: list[str]) -> dict[str, list[str]]:
    """Bucket warnings into fatal / strong / normal / info by their prefix."""
    groups = {"fatal": [], "strong": [], "normal": [], "info": []}
    for w in warnings:
        head = w.split(":", 1)[0].strip().upper()
        if head.startswith("FATAL"):
            groups["fatal"].append(w)
        elif head.startswith("STRONG"):
            groups["strong"].append(w)
        elif head.startswith("INFO") or w.lower().startswith("reusing") or w.lower().startswith("reused") or "auto-detected" in w.lower():
            groups["info"].append(w)
        else:
            groups["normal"].append(w)
    return groups


def write_dry_run_report(path: Path, replacements: list[dict], warnings: list[str], large_names: Optional[dict] = None, medallion_sources: Optional[list[str]] = None, medallion_changes_atlas: bool = False, source_files: Optional[list[Path]] = None, mod_data_dir: Optional[Path] = None, modinfo_file: Optional[Path] = None) -> None:
    lines = [
        "# Dry-run Mod Integration Report",
        "",
        "Mode: --dry-run. No DDS, XML, previews, or mod files are written by this run.",
        "This report describes exactly what a normal run and a --write-mod run would do.",
        "",
        "## Source PNG files",
    ]
    for src in source_files or []:
        lines.append(f"- {src}")
    if not source_files:
        lines.append("- None configured.")
    lines += [
        "",
        "## Target mod directory",
        f"- {mod_data_dir if mod_data_dir else 'None configured; --write-mod would require mod_data_dir.'}",
        "",
        "## Planned generated files and mod targets",
    ]
    if not replacements:
        lines.append("- No generated files were planned (check configuration).")
    for r in replacements:
        gen = Path(r["generated"]).name
        lines.append(f"- Generated file: {gen}")
        if r.get("duplicates"):
            lines.append("  - ERROR: multiple same-name targets inside mod_data_dir; --write-mod will abort.")
            lines += [f"    - {name}" for name in r["duplicates"]]
        if r["will_replace"]:
            lines.append(f"  - Existing mod target: {r['mod_target']}")
            lines.append("  - Action under --write-mod: replace this file only if it remains inside mod_data_dir.")
        else:
            lines.append("  - No same-name mod target found inside mod_data_dir; file will be reported and not integrated automatically.")
    lines += [
        "",
        "## Planned .modinfo refresh",
        f"- {modinfo_file if modinfo_file else 'No root .modinfo file found; none will be refreshed.'}",
        "",
        "## Write safety",
        "- All --write-mod replacement and .modinfo targets are resolved with Path.resolve().",
        "- The run aborts before any mod write whose resolved path is outside mod_data_dir.",
        "- No sibling mod directories or parent MODS directory files are selected by this plan.",
    ]
    if large_names:
        lines += ["", "## Large image filename plan"]
        for key, name in large_names.items():
            lines.append(f"- {key}: {name}")
    lines += ["", "## Medallion baking plan"]
    if medallion_sources:
        lines.append(f"- Normal icon atlas changes: {'yes' if medallion_changes_atlas else 'preview-only'}")
        lines.append("- Normal icon files that would be medallion-baked:")
        lines += [f"  - {name}" for name in medallion_sources]
    else:
        lines.append("- Medallion baking disabled; normal icon atlas cells would use the existing square-icon normalization.")
    groups = group_warnings_by_severity(warnings)
    lines += ["", "## Warnings by severity"]
    for sev in ("fatal", "strong", "normal", "info"):
        lines.append(f"### {sev.upper()}")
        if groups[sev]:
            lines += [f"- {w}" for w in groups[sev]]
        else:
            lines.append("- None")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')

# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def validate_config(cfg: PipelineConfig) -> list[str]:
    errors = []
    if not cfg.prefix or not PREFIX_RE.match(cfg.prefix):
        errors.append("prefix is required and may contain only letters, numbers, and underscores")
    if not cfg.output_dir:
        errors.append("output_dir is required after merging JSON config and CLI options")
    required = [("civ_icon", cfg.civ_icon), ("leader_icon", cfg.leader_icon), ("alpha_icon", cfg.alpha_icon)]
    for name, path in required:
        if not path or str(path) == '' or path == Path('.') or not path.exists() or not path.is_file():
            errors.append(f"{name} is required and does not exist: {path}")
    for group_name, group, lo, hi in [
        ("units", cfg.units, 1, 4), ("buildings", cfg.buildings, 1, 3),
        ("supports", cfg.supports, 0, 8), ("flags", cfg.flags, 0, 4),
    ]:
        if not (lo <= len(group) <= hi):
            errors.append(f"{group_name} count must be {lo}-{hi}; got {len(group)}")
        labels = [a.label.lower() for a in group]
        if len(labels) != len(set(labels)):
            errors.append(f"{group_name} labels must be unique")
        for a in group:
            if not a.label:
                errors.append(f"{group_name} has an empty label")
            if not a.source.exists():
                errors.append(f"{group_name} source does not exist: {a.source}")
    for p in [cfg.map_image, cfg.dawn_image, cfg.leader_scene]:
        if p and not p.exists():
            errors.append(f"optional image does not exist: {p}")
    if not 0.1 <= cfg.medallion.fill_percent <= 1.0:
        errors.append("medallion_fill_percent must be between 0.1 and 1.0")
    if not 0.1 <= cfg.medallion.radius_percent <= 0.5:
        errors.append("medallion_radius_percent must be between 0.1 and 0.5")
    if not 0.0 <= cfg.medallion.rim_width_percent <= 0.12:
        errors.append("medallion_rim_width_percent must be between 0.0 and 0.12")
    if cfg.medallion.rim_style not in {"gold", "silver", "none"}:
        errors.append("medallion_rim_style must be gold, silver, or none")
    if cfg.medallion.background not in {"transparent", "dark", "parchment", "source-blur"}:
        errors.append("medallion_background must be transparent, dark, parchment, or source-blur")
    if cfg.write_mod and not cfg.mod_data_dir:
        errors.append("--write-mod requires mod_data_dir after merging JSON config and CLI options")
    return errors


# ---------------------------------------------------------------------------
# vNext: strict validation, check-only, template, modinfo imports
# ---------------------------------------------------------------------------

def _iter_named_assets(cfg: PipelineConfig):
    """Yield (group, AssetSpec-like dict) for every named/source asset."""
    yield ("civ_icon", "Civilization", cfg.civ_icon, "civ", "")
    yield ("leader_icon", "Leader", cfg.leader_icon, "leader", "")
    yield ("alpha_icon", "AlphaIcon", cfg.alpha_icon, "alpha_icon", cfg_alpha_profile(cfg) or "")
    for a in cfg.units:
        yield ("unit", a.label, a.source, "unit", a.profile)
    for a in cfg.buildings:
        yield ("building", a.label, a.source, "building", a.profile)
    for a in cfg.supports:
        yield ("support", a.label, a.source, "support", a.profile)
    for a in cfg.flags:
        yield ("unit_flag", a.label, a.source, "unit_flag", a.profile)
    if cfg.dawn_image:
        yield ("dawn_image", "DawnOfMan", cfg.dawn_image, "dawn_image", "")
    if cfg.map_image:
        yield ("map_image", "Map", cfg.map_image, "map_image", "")
    if cfg.leader_scene:
        yield ("leader_scene", "LeaderScene", cfg.leader_scene, "leader_scene", cfg.leader_scene_profile)


def validate_filename(path: Path, allow_numeric_suffixes: bool) -> list[str]:
    """Return clear errors for a source filename. Empty list means valid."""
    errs = []
    name = path.name
    if not name.lower().endswith(".png"):
        errs.append(f"ERROR: {name} is invalid.\n  Reason: source files must end in .png.\n  Expected style: {path.stem}.png")
        return errs
    stem = path.stem
    if not allow_numeric_suffixes:
        m = NUMERIC_SUFFIX_RE.search(stem)
        if m:
            clean = NUMERIC_SUFFIX_RE.sub("", stem)
            errs.append(
                f"ERROR: {name} is invalid.\n"
                f"  Reason: trailing numeric suffix '_{m.group(1)}' is not allowed.\n"
                f"  Expected style: {clean}.png\n"
                f"  (set allow_numeric_suffixes=true to override)"
            )
    return errs


def validate_processing_plan(cfg: PipelineConfig, mod_atlas_defs=None,
                             check_mod: bool = False) -> tuple[list[str], list[str]]:
    """Strict validation of sources, filenames, profiles, and atlas capacity.

    Returns (errors, warnings). Errors block --check-only; warnings are advisory.
    This complements validate_config (which covers counts/medallion ranges).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1) Source existence + filename hygiene.
    for group, label, src, role, profile in _iter_named_assets(cfg):
        if not src or str(src) in ("", "."):
            errors.append(f"{group}:{label}: no source path configured.")
            continue
        if not src.exists():
            errors.append(f"{group}:{label}: source file does not exist: {src}")
            continue
        errors.extend(validate_filename(src, cfg.allow_numeric_suffixes))

    # 2) Prefix pattern.
    if not cfg.prefix or not PREFIX_RE.match(cfg.prefix):
        errors.append("prefix is required and may contain only letters, numbers, and underscores.")

    # 3) Role / asset_type / profile validity and compatibility.
    role_of_asset_type = {
        "civ_icon": "civ", "leader_icon": "leader", "unit_icon": "unit",
        "building_icon": "building", "support_icon": "support",
        "promotion_icon": "promotion", "dummy_icon": "dummy", "trait_icon": "trait",
        "alpha_icon": "alpha_icon", "unit_flag": "unit_flag",
        "dawn_image": "dawn_image", "map_image": "map_image", "leader_scene": "leader_scene",
    }
    for spec_group, specs in (("units", cfg.units), ("buildings", cfg.buildings),
                              ("supports", cfg.supports), ("flags", cfg.flags)):
        for a in specs:
            role = "unit_flag" if spec_group == "flags" else a.role
            if a.asset_type:
                if a.asset_type not in KNOWN_ASSET_TYPES:
                    errors.append(f"{spec_group}:{a.label}: unknown asset_type '{a.asset_type}'. Known: {sorted(KNOWN_ASSET_TYPES)}")
                else:
                    expected_role = role_of_asset_type.get(a.asset_type)
                    if expected_role is not None and expected_role != role:
                        errors.append(
                            f"{spec_group}:{a.label}: asset_type '{a.asset_type}' maps to role "
                            f"'{expected_role}' but this asset is in '{spec_group}' (role '{role}'). "
                            f"Use the matching asset_type or move the asset."
                        )
            prof = resolve_asset_profile(role, a.profile or None, a.options)
            if a.profile:
                resolved = PROFILE_ALIASES.get(a.profile.strip(), a.profile.strip())
                if resolved not in KNOWN_PROFILES:
                    errors.append(f"{spec_group}:{a.label}: unknown profile '{a.profile}'. Known: {sorted(KNOWN_PROFILES)}")
                elif role not in PROFILES[resolved].get("compatible_roles", set()):
                    errors.append(f"{spec_group}:{a.label}: profile '{resolved}' is not compatible with role '{role}'.")

    # Explicit alpha / leader-scene profile compatibility.
    ap = cfg_alpha_profile(cfg)
    if ap:
        resolved = PROFILE_ALIASES.get(ap.strip(), ap.strip())
        if resolved not in KNOWN_PROFILES:
            errors.append(f"alpha_icon: unknown alpha_profile '{ap}'.")
        elif "alpha_icon" not in PROFILES[resolved].get("compatible_roles", set()):
            errors.append(f"alpha_icon: profile '{resolved}' is not valid for an alpha icon (e.g. civ5_map is not allowed).")
    if cfg.leader_scene_profile:
        resolved = PROFILE_ALIASES.get(cfg.leader_scene_profile.strip(), cfg.leader_scene_profile.strip())
        if resolved not in {"civ5_leader_scene_4x3", "civ5_leader_scene_16x9"}:
            errors.append(f"leader_scene: profile '{cfg.leader_scene_profile}' must be civ5_leader_scene_4x3 or civ5_leader_scene_16x9.")

    # 4) Scene target invariants.
    if cfg.dawn_image and PROFILES["civ5_dom"]["final_size"] != (1024, 768):
        errors.append("Dawn of Man final target must be 1024x768.")
    if cfg.map_image and PROFILES["civ5_map"]["final_size"] != (512, 512):
        errors.append("Map final target must be 512x512.")
    if cfg.leader_scene:
        lsp = resolve_leader_scene_profile(cfg)
        expected = (1280, 720) if lsp == "civ5_leader_scene_16x9" else (1024, 768)
        if PROFILES[lsp]["final_size"] != expected:
            errors.append(f"Leader scene profile {lsp} has an unexpected final size.")

    # 5) Index bounds.
    for a in cfg.flags:
        if a.portrait_index is not None and not (0 <= a.portrait_index <= 63):
            errors.append(f"flags:{a.label}: unit flag portrait_index {a.portrait_index} must be within 0-63.")
    for label, idx in cfg.explicit_indexes.items():
        # Normal icon indexes (non-flag) must fit 0-15. Flags handled above.
        flag_labels = {f.label.lower() for f in cfg.flags}
        if label not in flag_labels and not (0 <= idx <= 15):
            errors.append(f"asset_index '{label}={idx}': normal icon portrait_index must be within 0-15.")

    # 6) Atlas capacity + advisory warnings.
    normal_count = 2 + len(cfg.units) + len(cfg.buildings) + len(cfg.supports)
    if normal_count > NORMAL_GRID * NORMAL_GRID:
        errors.append(f"Normal icon count {normal_count} exceeds the 4x4 atlas capacity of 16.")
    elif normal_count > 16:
        warnings.append(f"Normal icon count {normal_count} exceeds 16.")
    if not cfg.flags:
        warnings.append("No unit flags configured.")

    # 7) Mod-target advisories (only when a mod dir is in play).
    if check_mod and cfg.mod_data_dir and cfg.mod_data_dir.exists():
        modinfo = None
        try:
            modinfo = select_modinfo_file(cfg.mod_data_dir)
        except SystemExit as exc:
            warnings.append(f"mod_data_dir: {exc}")
        if cfg.write_mod:
            existing_dds = {p.name.lower() for p in cfg.mod_data_dir.rglob("*.dds")}
            planned = _planned_dds_names(cfg)
            unmatched = [n for n in planned if n.lower() not in existing_dds]
            if unmatched and not cfg.copy_new_assets:
                warnings.append(
                    "Some generated DDS names do not match any existing mod target and "
                    "will not be integrated automatically: " + ", ".join(sorted(unmatched))
                )
        if modinfo:
            text = modinfo.read_text(encoding="utf-8", errors="ignore")
            if ".dds" not in text.lower():
                warnings.append(f".modinfo {modinfo.name} exists but references no DDS art files.")
    return errors, warnings


def _planned_dds_names(cfg: PipelineConfig) -> list[str]:
    """Best-effort list of DDS filenames a normal run would produce (names only)."""
    names: list[str] = []
    warnings: list[str] = []
    icon_sel = choose_atlas_selection(cfg, warnings, alpha=False)
    alpha_sel = choose_atlas_selection(cfg, warnings, alpha=True)
    names += [icon_sel.filename_for(s) for s in NORMAL_ATLAS_SIZES]
    names += [alpha_sel.filename_for(s) for s in ALPHA_ICON_SIZES]
    flag_atlas = cfg.flag_atlas_name or f"{cfg.prefix.upper()}_UNIT_FLAG_ATLAS"
    flag_stem = infer_atlas_stem(cfg.flag_atlas_stem, None) if cfg.flag_atlas_stem else f"{cfg.prefix}_UnitFlagAtlas"
    flag_filename = choose_unit_flag_filename(cfg, flag_atlas, flag_stem, warnings) if cfg.flags else ""
    if cfg.flags:
        names.append(choose_unit_flag_filename(cfg, flag_atlas, flag_stem, warnings))
    large = resolve_large_image_names(cfg, warnings)
    if cfg.dawn_image:
        names.append(large["dawn"])
    if cfg.map_image:
        names.append(large["map"])
    if cfg.leader_scene:
        names.append(large["leader_scene"])
    return names


def run_check_only(cfg: PipelineConfig, log: Callable[[str], None] = print) -> int:
    """Lightweight validation with a console summary and no file writes."""
    base_errors = validate_config(cfg)
    plan_errors, plan_warnings = validate_processing_plan(cfg, check_mod=True)
    errors = base_errors + plan_errors

    ls_profile = resolve_leader_scene_profile(cfg) if cfg.leader_scene else None
    dom_ok = cfg.dawn_image is not None
    map_ok = cfg.map_image is not None
    normal_count = 2 + len(cfg.units) + len(cfg.buildings) + len(cfg.supports)
    all_exist = all(s.exists() for _, _, s, _, _ in _iter_named_assets(cfg) if s and str(s) not in ("", "."))

    log("Civ V Art Pipeline Check")
    log(f"Prefix: {cfg.prefix}")
    log(f"Output dir: {cfg.output_dir}")
    log(f"Normal circular icons: {normal_count}")
    log(f"Alpha/team glyphs: 1")
    log(f"Unit flags: {len(cfg.flags)}")
    if dom_ok:
        w, h = PROFILES['civ5_dom']['final_size']; log(f"Dawn of Man: yes, {w}x{h}")
    else:
        log("Dawn of Man: no")
    if map_ok:
        w, h = PROFILES['civ5_map']['final_size']; log(f"Map: yes, {w}x{h}")
    else:
        log("Map: no")
    if ls_profile:
        w, h = PROFILES[ls_profile]['final_size']; log(f"Leader scene: yes, {w}x{h}")
    else:
        log("Leader scene: no")
    log(f"Existing mod dir: {cfg.mod_data_dir if cfg.mod_data_dir else 'none'}")
    log(f"All source files exist: {'yes' if all_exist else 'no'}")
    filename_ok = not any('numeric suffix' in e or 'must end in .png' in e for e in plan_errors)
    log(f"Filename validation: {'passed' if filename_ok else 'FAILED'}")
    profile_ok = not any('profile' in e.lower() for e in plan_errors)
    log(f"Profile validation: {'passed' if profile_ok else 'FAILED'}")
    capacity_ok = not any('atlas capacity' in e.lower() or 'exceeds the 4x4' in e.lower() for e in plan_errors)
    log(f"Atlas capacity: {'passed' if capacity_ok else 'FAILED'}")

    for w in plan_warnings:
        log(f"WARNING: {w}")
    if errors:
        log("Ready to convert: no")
        log("")
        log("Errors:")
        for e in errors:
            for line in e.splitlines():
                log(f"  {line}")
        return 1
    log("Ready to convert: yes")
    return 0


def make_template(prefix: str, output: Optional[Path], units: int, buildings: int,
                  supports: int, include_leader_scene: bool,
                  include_flux_names: bool, profile: str = "custom_civ") -> Path:
    """Generate a starter profiled JSON config. Sources need not exist."""
    if not PREFIX_RE.match(prefix):
        raise SystemExit(f"--make-template prefix may contain only letters, numbers, and underscores: {prefix}")
    base = f"Input/{prefix}"

    def src(name: str) -> str:
        return f"{base}/{prefix}_{name}.png"

    unit_names = ["ChunkeyWarrior", "Scout", "Archer", "Spearman"][:max(0, units)]
    while len(unit_names) < units:
        unit_names.append(f"Unit{len(unit_names) + 1}")
    building_names = ["Mound", "Plaza", "Granary", "Temple", "Market"][:max(0, buildings)]
    while len(building_names) < buildings:
        building_names.append(f"Building{len(building_names) + 1}")
    support_names = [f"Support{i + 1}" for i in range(max(0, supports))]

    def unit_block(label):
        return {
            "label": label,
            "source": src(f"{label}Icon"),
            "asset_type": "unit_icon",
            "type_name": f"UNIT_{prefix.upper()}_{re.sub(r'(?<!^)(?=[A-Z])', '_', label).upper()}",
            "profile": "civ5_circular_icon",
        }

    def flag_block(label):
        return {
            "label": f"{label}Flag",
            "source": src(f"{label}Flag"),
            "asset_type": "unit_flag",
            "type_name": f"UNIT_{prefix.upper()}_{re.sub(r'(?<!^)(?=[A-Z])', '_', label).upper()}",
            "profile": "civ5_unit_flag_black_to_transparent",
        }

    def building_block(label):
        return {
            "label": label,
            "source": src(f"{label}Icon"),
            "asset_type": "building_icon",
            "type_name": f"BUILDING_{prefix.upper()}_{re.sub(r'(?<!^)(?=[A-Z])', '_', label).upper()}",
            "profile": "civ5_circular_icon",
        }

    config: dict = {
        "_notes": [
            "Generated starter config. Replace example paths/types with your real assets.",
            "JSON has no comments; use _notes fields for explanatory text.",
            "mod_data_dir is intentionally omitted; add it (e.g. C:/Users/you/Documents/My Games/Sid Meier's Civilization 5/MODS/" + prefix + "_BNW_Custom_Civ) only when you are ready to integrate.",
            "Run with --check-only first to validate before converting.",
        ],
        "prefix": prefix,
        "output_dir": f"Output/{prefix}",
        "civ_icon": src("CivilizationIcon"),
        "leader_icon": src("LeaderIcon"),
        "alpha_icon": src("AlphaIcon"),
        "alpha_profile": "civ5_alpha_glyph_black_to_transparent",
        "units": [unit_block(n) for n in unit_names],
        "buildings": [building_block(n) for n in building_names],
        "supports": [
            {"label": n, "source": src(f"{n}Icon"), "asset_type": "support_icon",
             "profile": "civ5_circular_icon"} for n in support_names
        ],
        "flags": [flag_block(n) for n in unit_names],
        "map_image": src("Map"),
        "dawn_image": src("DOM"),
        "write_per_asset_previews": True,
        "preset": "existing-combined-atlas",
    }
    # --template-profile: if it names a known circular-icon profile/alias, set it as
    # the config-level default_profile; otherwise treat it as a descriptive label.
    prof_name = (profile or "").strip()
    resolved_prof = PROFILE_ALIASES.get(prof_name, prof_name)
    if resolved_prof in PROFILES and "civ" in PROFILES[resolved_prof].get("compatible_roles", set()):
        config["default_profile"] = resolved_prof
        config["_notes"].append(
            f"default_profile '{resolved_prof}' applies to civ/leader/unit/building/support "
            f"icons that do not set their own profile."
        )
    elif prof_name and prof_name != "custom_civ":
        config["_notes"].append(f"Template profile label: {prof_name} (descriptive only).")
    if include_leader_scene:
        config["leader_scene"] = src("LeaderScene")
        config["leader_scene_profile"] = "civ5_leader_scene_4x3"
    if include_flux_names:
        config["_notes"].append(
            "FLUX Schnell source PNGs should be named <Prefix>_<Asset>.png with no "
            "trailing numeric suffix (e.g. " + prefix + "_LeaderIcon.png, not " +
            prefix + "_LeaderIcon_1.png)."
        )

    out_path = output if output else Path(f"{prefix}.dds.json")
    out_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return out_path


def update_modinfo_imports(modinfo: Path, mod_root: Path, dds_files: list[Path],
                           log: Callable[[str], None]) -> None:
    """Ensure each DDS has an import="1" <File> entry in the .modinfo Files block.

    Conservative text-level edit: preserves existing entries, adds only missing
    DDS files relative to the .modinfo directory, backs up before writing, and
    refuses to edit when no <Files> section can be located safely.
    """
    modinfo = assert_inside_mod_data_dir(modinfo, mod_root)
    text = modinfo.read_text(encoding="utf-8", errors="ignore")
    files_match = re.search(r"(<Files\b[^>]*>)(.*?)(</Files>)", text, flags=re.I | re.S)
    if not files_match:
        log(f"WARNING: no <Files> section found in {modinfo.name}; not adding import entries.")
        return
    base = modinfo.parent.resolve()
    existing_rel = {re.sub(r"[\\/]+", "/", m.strip()).lower()
                    for m in re.findall(r"<File[^>]*>([^<]+)</File>", files_match.group(2), flags=re.I)}
    additions = []
    for dds in dds_files:
        target = assert_inside_mod_data_dir(dds, mod_root)
        rel_posix = target.relative_to(base).as_posix()
        rel = rel_posix.replace("/", "\\")
        if rel_posix.lower() in existing_rel:
            log(f"WARNING: duplicate .modinfo entry skipped for {rel}.")
            continue
        digest = md5(target.read_bytes()).hexdigest()
        additions.append(f'    <File md5="{digest}" import="1">{rel}</File>')
    if not additions:
        log(".modinfo import entries already present; nothing added.")
        return
    backup = assert_inside_mod_data_dir(modinfo.with_name(modinfo.name + ".bak"), mod_root)
    backup.write_text(text, encoding="utf-8")
    new_inner = files_match.group(2).rstrip("\n") + "\n" + "\n".join(additions) + "\n"
    new_text = text[:files_match.start(2)] + new_inner + text[files_match.end(2):]
    modinfo.write_text(new_text, encoding="utf-8")
    log(f"Backed up .modinfo: {backup}")
    log(f"Added {len(additions)} import entry(ies) to {modinfo.name}")


def generate_assets(cfg: PipelineConfig, log: Callable[[str], None] = print) -> dict:
    errors = validate_config(cfg)
    if errors:
        raise SystemExit("\n".join(errors))

    warnings: list[str] = []
    qa: list[QAResult] = []
    out = cfg.output_dir
    dds_dir, xml_dir, preview_dir = out / "Art", out / "XML", out / "Previews"

    icon_selection = choose_atlas_selection(cfg, warnings, alpha=False)
    alpha_selection = choose_atlas_selection(cfg, warnings, alpha=True)
    icon_atlas, icon_stem = icon_selection.atlas, icon_selection.stem
    flag_atlas = cfg.flag_atlas_name or f"{cfg.prefix.upper()}_UNIT_FLAG_ATLAS"
    flag_stem = infer_atlas_stem(cfg.flag_atlas_stem, None) if cfg.flag_atlas_stem else f"{cfg.prefix}_UnitFlagAtlas"
    flag_filename = choose_unit_flag_filename(cfg, flag_atlas, flag_stem, warnings) if cfg.flags else ""

    normal_items: list[AssetSpec] = [
        AssetSpec("civ", "Civilization", cfg.civ_icon, atlas=icon_atlas,
                  asset_type="civ_icon", profile=cfg_profile_for(cfg, "civ")),
        AssetSpec("leader", "Leader", cfg.leader_icon, atlas=icon_atlas,
                  asset_type="leader_icon", profile=cfg_profile_for(cfg, "leader")),
    ]
    for item in cfg.units + cfg.buildings + cfg.supports:
        item.atlas = icon_atlas
        normal_items.append(item)
    for item in normal_items:
        explicit = item.profile or None
        if not explicit:
            top_level = ""
            if item.role in {"civ", "leader", "unit", "building"}:
                top_level = cfg.normal_icon_profile or cfg.default_profile
            elif item.role in {"support", "promotion", "dummy", "trait"}:
                top_level = cfg.support_icon_profile or cfg.default_profile
            elif cfg.default_profile:
                top_level = cfg.default_profile
            if top_level:
                cand = PROFILE_ALIASES.get(top_level.strip(), top_level.strip())
                if item.role in PROFILES.get(cand, {}).get("compatible_roles", set()):
                    explicit = cand
        item.resolved_profile = resolve_asset_profile(item.role, explicit, item.options) or "civ5_circular_icon"
    apply_existing_or_explicit_indexes(cfg, normal_items, warnings)
    if len(normal_items) > NORMAL_GRID * NORMAL_GRID:
        raise SystemExit("Too many normal icons for a 4x4 atlas")

    large_names = resolve_large_image_names(cfg, warnings)
    generated_paths: list[Path] = []
    generated_paths.extend(dds_dir / icon_selection.filename_for(size) for size in NORMAL_ATLAS_SIZES)
    generated_paths.extend(dds_dir / alpha_selection.filename_for(size) for size in ALPHA_ICON_SIZES)
    if cfg.flags:
        generated_paths.append(dds_dir / flag_filename)
    if cfg.dawn_image:
        generated_paths.append(dds_dir / large_names["dawn"])
    if cfg.map_image:
        generated_paths.append(dds_dir / large_names["map"])
    if cfg.leader_scene:
        generated_paths.append(dds_dir / large_names["leader_scene"])
    replacements = find_mod_replacement_targets(cfg, generated_paths)

    medallion_sources = [str(item.source) for item in normal_items] if cfg.medallion.bake or cfg.medallion.preview_only else []
    if cfg.medallion.bake:
        warnings.append(f"INFO: Medallion baking enabled for {len(normal_items)} normal icon atlas cell(s); alpha icons, unit flags, and large images are unchanged.")
    elif cfg.medallion.preview_only:
        warnings.append("INFO: Medallion preview-only mode enabled; DDS normal icon atlases keep existing square-icon output.")

    # Produce the dry-run report before any generated art/XML is written.
    (out).mkdir(parents=True, exist_ok=True)
    write_dry_run_report(
        out / f"{cfg.prefix}_DryRun_Report.md",
        replacements,
        warnings,
        large_names,
        medallion_sources=medallion_sources,
        medallion_changes_atlas=cfg.medallion.bake and not cfg.medallion.preview_only,
        source_files=[p for p in [cfg.civ_icon, cfg.leader_icon, cfg.alpha_icon, cfg.map_image, cfg.dawn_image, cfg.leader_scene] if p] + [a.source for a in cfg.units + cfg.buildings + cfg.supports + cfg.flags],
        mod_data_dir=cfg.mod_data_dir,
        modinfo_file=select_modinfo_file(cfg.mod_data_dir),
    )
    if cfg.dry_run:
        log(f"Dry run complete. Review {out / f'{cfg.prefix}_DryRun_Report.md'} before writing assets.")
        return {"prefix": cfg.prefix, "dry_run": True, "planned_replacements": replacements, "warnings": warnings}

    for d in (dds_dir, xml_dir, preview_dir):
        d.mkdir(parents=True, exist_ok=True)

    log(f"Building combined normal icon atlas {icon_atlas} ({len(normal_items)}/16 cells)...")
    want_per_asset = resolve_write_per_asset_previews(cfg)
    masters: list[tuple[AssetSpec, Image.Image]] = []
    medallion_masters: list[tuple[AssetSpec, Image.Image]] = []
    normal_metrics = []
    for item in normal_items:
        prof = item.resolved_profile or "civ5_circular_icon"
        master_size = PROFILES.get(prof, {}).get("target_master_size", 256) if cfg.uses_profiles else 256
        scale = safe_subject_scale_for_role(item.role, prof, item.safe_subject_scale) if cfg.uses_profiles else None
        master = normalize_icon_master(item.source, item.role, warnings,
                                       master_size=master_size, safe_subject_scale=scale)
        item.normalized_source_size = master.size
        item.final_target_size = (NORMAL_ATLAS_SIZES[0], NORMAL_ATLAS_SIZES[0])
        medallion_master = compose_medallion_icon(master, 256, cfg.medallion) if (cfg.medallion.bake or cfg.medallion.preview_only) else master
        masters.append((item, master))
        if cfg.medallion.bake or cfg.medallion.preview_only:
            medallion_masters.append((item, medallion_master))
        metrics = alpha_metrics(master)
        if cfg.medallion.bake or cfg.medallion.preview_only:
            med_metrics = medallion_subject_metrics(master, medallion_master, cfg.medallion)
            metrics["medallion"] = med_metrics
            if med_metrics["subject_clipped_by_circle"]:
                warnings.append(f"{item.role}:{item.label}: medallion QA detected possible subject clipping by the circular mask.")
            if med_metrics["fills_too_much_circle"]:
                warnings.append(f"{item.role}:{item.label}: subject fills too much of the medallion circle; consider lowering medallion_fill_percent or adding source padding.")
            if med_metrics["potentially_unreadable_at_32px"]:
                warnings.append(f"{item.role}:{item.label}: medallion may be unreadable at 32px; inspect normal_icon_before_after_preview.png.")
        normal_metrics.append({"role": item.role, "label": item.label, "profile": prof,
                               "safe_subject_scale": scale, "metrics": metrics})
        if want_per_asset:
            write_per_asset_circular_previews(item, master, preview_dir, cfg.medallion)
    atlas_masters = medallion_masters if (cfg.medallion.bake and not cfg.medallion.preview_only) else masters
    for size in NORMAL_ATLAS_SIZES:
        atlas = Image.new("RGBA", (size * NORMAL_GRID, size * NORMAL_GRID), (0, 0, 0, 0))
        for item, master in atlas_masters:
            cell = icon_cell(master, size, circular=cfg.bake_circular_mask and not (cfg.medallion.bake and not cfg.medallion.preview_only))
            x = (item.portrait_index % NORMAL_GRID) * size
            y = (item.portrait_index // NORMAL_GRID) * size
            atlas.paste(cell, (x, y), cell)
        filename = icon_selection.filename_for(size)
        save_as_dds(atlas, dds_dir / filename)
        validate_dds_file(dds_dir / filename, size * NORMAL_GRID, size * NORMAL_GRID, True, qa)
    make_icon_preview(masters, preview_dir / "normal_icon_cells_preview.png")
    make_circle_preview(masters, preview_dir / "normal_icon_circle_mask_preview.png")
    if cfg.medallion.bake or cfg.medallion.preview_only:
        write_medallion_previews(masters, medallion_masters, preview_dir, cfg.medallion)

    log(f"Exporting alpha/team icons into atlas {alpha_selection.atlas}...")
    alpha_profile = resolve_asset_profile("alpha_icon", cfg_alpha_profile(cfg), None)
    alpha_master, alpha_bb_applied = prepare_alpha_icon(
        cfg.alpha_icon, warnings, profile=alpha_profile,
        master_size=(PROFILES.get(alpha_profile, {}).get("target_master_size", 256) if alpha_profile else 256),
    )
    alpha_files = []
    for size in ALPHA_ICON_SIZES:
        img = alpha_master.resize((size, size), Image.Resampling.LANCZOS)
        name = alpha_selection.filename_for(size)
        save_as_dds(img, dds_dir / name)
        alpha_files.append(name)
        validate_dds_file(dds_dir / name, size, size, True, qa)
    alpha_icon_metrics = alpha_metrics(alpha_master)
    make_checker_preview(alpha_master, preview_dir / "alpha_checkerboard_preview.png")
    if want_per_asset:
        per_asset_dir = preview_dir / "_per_asset"
        per_asset_dir.mkdir(parents=True, exist_ok=True)
        make_checker_preview(alpha_master, per_asset_dir / "AlphaIcon_transparent_checker_preview.png")

    flag_files = []
    flag_metrics = []
    if cfg.flags:
        log(f"Packing {len(cfg.flags)} unit flag(s) into 8x8 256x256 atlas...")
        flag_atlas_img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        packed = 0
        for i, fl in enumerate(cfg.flags):
            fl.atlas = flag_atlas
            fl.portrait_index = cfg.explicit_indexes.get(fl.label.lower(), i)
            fl_explicit = fl.profile or cfg.unit_flag_profile or None
            fl.resolved_profile = resolve_asset_profile("unit_flag", fl_explicit, fl.options) or ""
            assessment = assess_unit_flag_source(fl.source)
            small, fl_bb = prepare_unit_flag(fl.source, fl.label, warnings,
                                             allow_painted=cfg.allow_painted_flags,
                                             profile=fl.resolved_profile or None,
                                             safe_subject_scale=fl.safe_subject_scale)
            fl.black_bg_cleanup_applied = fl_bb
            fl.final_target_size = (UNIT_FLAG_CELL, UNIT_FLAG_CELL)
            metrics = alpha_metrics(small) if small is not None else {}
            metrics["source_assessment"] = assessment
            # When black-bg cleanup ran and the flag packed, the raw-source
            # "painted" verdict is pre-cleanup context only, not a failure.
            metrics["painted_resolved_by_cleanup"] = bool(fl_bb and small is not None and assessment.get("painted"))
            flag_metrics.append({"label": fl.label, "skipped": small is None,
                                 "profile": fl.resolved_profile or "legacy",
                                 "black_bg_cleanup": fl_bb, "metrics": metrics})
            if small is None:
                continue
            flag_atlas_img.paste(small, ((fl.portrait_index % UNIT_FLAG_GRID) * UNIT_FLAG_CELL, (fl.portrait_index // UNIT_FLAG_GRID) * UNIT_FLAG_CELL), small)
            packed += 1
            if want_per_asset:
                per_asset_dir = preview_dir / "_per_asset"
                per_asset_dir.mkdir(parents=True, exist_ok=True)
                make_checker_preview(small.resize((64, 64), Image.Resampling.NEAREST),
                                     per_asset_dir / f"{fl.label}_flag_32px_preview.png", cell=8)
        if packed:
            name = flag_filename
            save_as_dds(flag_atlas_img, dds_dir / name)
            flag_files.append(name)
            validate_dds_file(dds_dir / name, 256, 256, True, qa)
            make_checker_preview(flag_atlas_img, preview_dir / "unit_flag_preview.png", cell=32)
        else:
            log("All unit flags were rejected as painted scenes; no flag atlas written (use --allow-painted-flags to force).")
    else:
        log("Unit flags not selected; skipping flag atlas.")

    scene_files = {}
    if cfg.dawn_image:
        w, h = PROFILES["civ5_dom"]["final_size"]
        pw, ph = PROFILES["civ5_dom"]["preview_size"]
        img = fit_center_crop(open_rgba(cfg.dawn_image), w, h, opaque=True)
        save_as_dds(img, dds_dir / large_names["dawn"])
        scene_files["dawn_of_man"] = large_names["dawn"]
        validate_dds_file(dds_dir / scene_files["dawn_of_man"], w, h, True, qa)
        img.resize((pw, ph)).save(preview_dir / "dawn_of_man_preview.png")
    if cfg.map_image:
        w, h = PROFILES["civ5_map"]["final_size"]
        pw, ph = PROFILES["civ5_map"]["preview_size"]
        img = fit_center_crop(open_rgba(cfg.map_image), w, h, opaque=True)
        save_as_dds(img, dds_dir / large_names["map"])
        scene_files["map"] = large_names["map"]
        validate_dds_file(dds_dir / scene_files["map"], w, h, True, qa)
        img.resize((pw, ph)).save(preview_dir / "map_preview.png")
    if cfg.leader_scene:
        ls_profile = resolve_leader_scene_profile(cfg)
        w, h = PROFILES[ls_profile]["final_size"]
        pw, ph = PROFILES[ls_profile]["preview_size"]
        img = fit_center_crop(open_rgba(cfg.leader_scene), w, h, opaque=True)
        save_as_dds(img, dds_dir / large_names["leader_scene"])
        scene_files["leader_scene"] = large_names["leader_scene"]
        validate_dds_file(dds_dir / scene_files["leader_scene"], w, h, True, qa)
        img.resize((pw, ph)).save(preview_dir / "leader_scene_preview.png")

    write_atlas_xml(xml_dir / f"{cfg.prefix}_AtlasDefinitions.xml", icon_selection, alpha_selection, flag_atlas if cfg.flags else "", flag_filename if cfg.flags else "")
    write_usage_xml(xml_dir / f"{cfg.prefix}_IconUsage_Template.xml", cfg, normal_items, alpha_selection.atlas, scene_files)

    manifest = build_manifest(cfg, normal_items, icon_atlas, icon_stem, alpha_files, flag_files, flag_atlas, scene_files, warnings, qa)
    manifest["alpha_icons"]["atlas"] = alpha_selection.atlas
    manifest["alpha_icons"]["metrics"] = alpha_icon_metrics
    manifest["alpha_icons"]["profile"] = alpha_profile or "legacy"
    manifest["alpha_icons"]["black_background_cleanup"] = alpha_bb_applied
    manifest["normal_alpha_metrics"] = normal_metrics
    manifest["unit_flag_alpha_metrics"] = flag_metrics
    manifest["planned_replacements"] = replacements
    manifest["medallions"] = {
        "enabled": cfg.medallion.bake,
        "preview_only": cfg.medallion.preview_only,
        "radius_percent": cfg.medallion.radius_percent,
        "fill_percent": cfg.medallion.fill_percent,
        "rim_enabled": cfg.medallion.rim,
        "rim_style": cfg.medallion.rim_style,
        "rim_width_percent": cfg.medallion.rim_width_percent,
        "background": cfg.medallion.background,
        "applies_to": "normal icon atlas cells only",
    }
    (out / f"{cfg.prefix}_AssetManifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_qa_report(out / f"{cfg.prefix}_QA_Report.md", manifest)
    if cfg.write_mod:
        write_mod_replacements(cfg, generated_paths, log)
    log(f"Done. Review warnings: {len(warnings)}. Clear Civ V cache after importing art changes.")
    return manifest


def validate_dds_file(path: Path, width: int, height: int, require_alpha: bool, qa: list[QAResult]) -> None:
    result = QAResult(path.name)
    try:
        h = read_dds_header(path)
        result.metrics.update(h)
        if h["width"] != width or h["height"] != height:
            result.warnings.append(f"DDS dimensions {h['width']}x{h['height']} do not match expected {width}x{height}")
        if h["mipmaps"] != 1:
            result.warnings.append(f"DDS mipmap count is {h['mipmaps']}; expected 1/no generated mipmaps")
        if h["fourcc"] != 0 or h["bpp"] != 32:
            result.warnings.append("DDS is not uncompressed 32-bit RGB/A")
        if require_alpha and not h["alpha_mask"]:
            result.warnings.append("DDS header does not advertise an alpha mask")
        result.metrics["exists"] = True
    except Exception as exc:
        result.warnings.append(str(exc))
        result.metrics["exists"] = False
    qa.append(result)


def alpha_metrics(img: Image.Image) -> dict:
    a = img.convert("RGBA").getchannel("A")
    hist = a.histogram()
    total = img.width * img.height
    opaque = sum(hist[250:]) / total
    transparent = sum(hist[:5]) / total
    amin, amax = a.getextrema()
    bbox = alpha_bbox(img)
    margin = None
    full_bleed = False
    if bbox:
        l, t, r, b = bbox
        margin = min(l / img.width, t / img.height, (img.width - r) / img.width, (img.height - b) / img.height)
        full_bleed = margin < SAFE_MARGIN_MIN
    return {"alpha_min": amin, "alpha_max": amax, "opaque_pct": round(opaque * 100, 2), "transparent_pct": round(transparent * 100, 2), "safe_margin_pct": None if margin is None else round(margin * 100, 2), "likely_full_bleed": full_bleed}


def build_manifest(cfg: PipelineConfig, normal_items: list[AssetSpec], icon_atlas: str, icon_stem: str, alpha_files: list[str], flag_files: list[str], flag_atlas: str, scene_files: dict, warnings: list[str], qa: list[QAResult]) -> dict:
    return {
        "prefix": cfg.prefix,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "standards": {
            "normal_icon_atlas": "4x4 grid, sizes 256/128/80/64/45/32, uncompressed A8R8G8B8, no mipmaps; optional baked medallions apply only to normal icon cells",
            "alpha_team_icons": "FLORENCE_ALPHA_ATLAS-style 1x1 atlas rows, white-on-transparent DDS at 128/80/64/48/45/32/24",
            "unit_flags": "8x8 256x256 atlas with 32px cells",
            "large_images": "Dawn/leader 1024x768 opaque; map 512x512 opaque",
        },
        "atlases": {
            "normal": {"atlas": icon_atlas, "stem": icon_stem, "icons_per_row": 4, "icons_per_column": 4},
            "unit_flags": {"atlas": flag_atlas, "files": flag_files, "icons_per_row": 8, "icons_per_column": 8} if flag_files else None,
        },
        "normal_icons": [
            {"role": i.role, "label": i.label, "source": str(i.source), "atlas": i.atlas,
             "portrait_index": i.portrait_index,
             "asset_type": i.asset_type or _default_asset_type(i.role),
             "profile": i.resolved_profile or resolve_asset_profile(i.role, i.profile or None, i.options),
             "safe_subject_scale": (i.safe_subject_scale
                                    if i.safe_subject_scale is not None
                                    else (safe_subject_scale_for_role(i.role, i.resolved_profile, None) if cfg.uses_profiles else None)),
             "normalized_source_size": list(i.normalized_source_size) if i.normalized_source_size else None,
             "final_target_size": list(i.final_target_size) if i.final_target_size else None,
             "black_background_cleanup": i.black_bg_cleanup_applied,
             "circular_mask_baked": bool(cfg.bake_circular_mask and not (cfg.medallion.bake and not cfg.medallion.preview_only)),
             "per_asset_previews": resolve_write_per_asset_previews(cfg)}
            for i in normal_items
        ],
        "alpha_icons": {"source": str(cfg.alpha_icon), "files": alpha_files},
        "unit_flags": [
            {"label": f.label, "source": str(f.source), "atlas": f.atlas,
             "unit_flag_icon_offset": f.portrait_index,
             "asset_type": f.asset_type or "unit_flag",
             "profile": f.resolved_profile or resolve_asset_profile("unit_flag", f.profile or None, f.options),
             "safe_subject_scale": (f.safe_subject_scale
                                    if f.safe_subject_scale is not None
                                    else safe_subject_scale_for_role("unit_flag", f.resolved_profile or None, None)),
             "final_target_size": list(f.final_target_size) if f.final_target_size else None,
             "black_background_cleanup": f.black_bg_cleanup_applied}
            for f in cfg.flags
        ],
        "scenes": scene_files,
        "warnings": warnings,
        "warnings_by_severity": group_warnings_by_severity(warnings),
        "dds_validation": [{"name": q.name, "metrics": q.metrics, "warnings": q.warnings} for q in qa],
        "post_import_reminder": "Clear the Civ V cache after art or SQL/XML changes.",
    }


# ---------------------------------------------------------------------------
# Previews and XML output
# ---------------------------------------------------------------------------

def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    img = Image.new("RGBA", size, (220, 220, 220, 255))
    draw = ImageDraw.Draw(img)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(150, 150, 150, 255))
    return img


def make_icon_preview(items: list[tuple[AssetSpec, Image.Image]], path: Path) -> None:
    cell = 128
    sheet = checkerboard((cell * 4, cell * 4), 16)
    draw = ImageDraw.Draw(sheet)
    for spec, master in items:
        img = icon_cell(master, cell, circular=False)
        x, y = (spec.portrait_index % 4) * cell, (spec.portrait_index // 4) * cell
        sheet.paste(img, (x, y), img)
        draw.rectangle((x, y, x + cell - 1, y + cell - 1), outline=(255, 0, 0, 255))
        draw.text((x + 3, y + 3), f"{spec.portrait_index}:{spec.role}", fill=(255, 255, 0, 255))
    sheet.save(path)


def make_circle_preview(items: list[tuple[AssetSpec, Image.Image]], path: Path) -> None:
    cell = 128
    sheet = checkerboard((cell * 4, cell * 4), 16)
    draw = ImageDraw.Draw(sheet)
    for spec, master in items:
        img = icon_cell(master, cell, circular=True)
        x, y = (spec.portrait_index % 4) * cell, (spec.portrait_index // 4) * cell
        sheet.paste(img, (x, y), img)
        draw.ellipse((x, y, x + cell - 1, y + cell - 1), outline=(0, 255, 255, 255), width=2)
        draw.text((x + 3, y + 3), str(spec.portrait_index), fill=(255, 255, 0, 255))
    sheet.save(path)


def write_per_asset_circular_previews(spec: AssetSpec, master: Image.Image,
                                      preview_dir: Path,
                                      options: "MedallionOptions") -> None:
    """Write per-asset normalized square, circle, and small-size previews.

    Files land under Previews/_per_asset/ and are review-only; they never affect
    DDS output. The circle preview shows a checkerboard background, the circular
    Civ V mask outline, and an optional medallion rim when medallion mode is on.
    """
    out_dir = preview_dir / "_per_asset"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = re.sub(r"[^A-Za-z0-9_.-]", "_", spec.label) or "asset"

    # Normalized square (transparent) on checkerboard.
    sq = master.resize((256, 256), Image.Resampling.LANCZOS)
    sq_bg = checkerboard((256, 256), 16)
    sq_bg.paste(sq, (0, 0), sq)
    sq_bg.save(out_dir / f"{label}_normalized_square.png")

    # Circle preview: checkerboard, art, circular mask outline, optional rim.
    size = 256
    circ = checkerboard((size, size), 16)
    art = master.resize((size, size), Image.Resampling.LANCZOS)
    if options and (options.bake or options.preview_only):
        art = compose_medallion_icon(master, size, options)
    circ.paste(art, (0, 0), art)
    draw = ImageDraw.Draw(circ)
    radius = (size / 2) * (options.radius_percent * 2 if (options and (options.bake or options.preview_only)) else 1.0)
    radius = min(radius, size / 2 - 1)
    cx = cy = size / 2
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                 outline=(0, 200, 255, 255), width=2)
    circ.save(out_dir / f"{label}_circle_preview.png")

    # Small-size previews to spot-check clipping at game sizes.
    for px in (64, 45, 32):
        small_bg = checkerboard((px * 3, px * 3), max(4, px // 4))
        cell = icon_cell(master, px, circular=True)
        small_bg.paste(cell, (px, px), cell)
        small_bg.save(out_dir / f"{label}_{px}px_preview.png")


def write_medallion_previews(items: list[tuple[AssetSpec, Image.Image]], medallions: list[tuple[AssetSpec, Image.Image]], preview_dir: Path, options: MedallionOptions) -> None:
    """Write medallion-specific atlas and before/after QA previews."""
    cell = 128
    sheet = checkerboard((cell * 4, cell * 4), 16)
    draw = ImageDraw.Draw(sheet)
    for spec, master in medallions:
        img = master.resize((cell, cell), Image.Resampling.LANCZOS)
        x, y = (spec.portrait_index % 4) * cell, (spec.portrait_index // 4) * cell
        sheet.paste(img, (x, y), img)
        draw.rectangle((x, y, x + cell - 1, y + cell - 1), outline=(255, 0, 0, 180))
        draw.text((x + 3, y + 3), f"{spec.portrait_index}:{spec.role}", fill=(255, 255, 0, 255))
    sheet.save(preview_dir / "normal_icon_medallion_cells_preview.png")

    circle_sheet = checkerboard((cell * 4, cell * 4), 16)
    circle_draw = ImageDraw.Draw(circle_sheet)
    radius = cell * options.radius_percent
    for spec, master in medallions:
        img = master.resize((cell, cell), Image.Resampling.LANCZOS)
        x, y = (spec.portrait_index % 4) * cell, (spec.portrait_index // 4) * cell
        circle_sheet.paste(img, (x, y), img)
        cx, cy = x + cell / 2, y + cell / 2
        circle_draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(0, 255, 255, 255), width=2)
        circle_draw.text((x + 3, y + 3), str(spec.portrait_index), fill=(255, 255, 0, 255))
    circle_sheet.save(preview_dir / "normal_icon_medallion_circle_preview.png")

    # Before/after strip: normalized square, baked 128, then baked 64/45/32.
    row_h = 154
    label_h = 18
    rows = max(1, len(items))
    width = 128 + 128 + 64 + 45 + 32 + 7 * 8
    before_after = checkerboard((width, rows * row_h), 8)
    draw = ImageDraw.Draw(before_after)
    med_by_label = {spec.label: img for spec, img in medallions}
    for row, (spec, master) in enumerate(items):
        y = row * row_h
        x = 8
        original = master.resize((128, 128), Image.Resampling.LANCZOS)
        baked = med_by_label[spec.label].resize((128, 128), Image.Resampling.LANCZOS)
        before_after.paste(original, (x, y + label_h), original)
        draw.text((x, y + 2), f"{spec.portrait_index}:{spec.label} before", fill=(255, 255, 0, 255))
        x += 136
        before_after.paste(baked, (x, y + label_h), baked)
        draw.text((x, y + 2), "medallion", fill=(255, 255, 0, 255))
        x += 136
        for small in (64, 45, 32):
            sm = med_by_label[spec.label].resize((small, small), Image.Resampling.LANCZOS)
            before_after.paste(sm, (x, y + label_h), sm)
            draw.text((x, y + label_h + small + 2), f"{small}px", fill=(255, 255, 0, 255))
            x += small + 8
    before_after.save(preview_dir / "normal_icon_before_after_preview.png")


def make_checker_preview(img: Image.Image, path: Path, cell: int = 16) -> None:
    bg = checkerboard(img.size, max(4, cell // 2))
    bg.paste(img, (0, 0), img)
    if cell:
        draw = ImageDraw.Draw(bg)
        for x in range(0, img.width, cell):
            draw.line((x, 0, x, img.height), fill=(255, 0, 0, 160))
        for y in range(0, img.height, cell):
            draw.line((0, y, img.width, y), fill=(255, 0, 0, 160))
    bg.save(path)


def write_atlas_xml(path: Path, icon_selection: AtlasSelection, alpha_selection: AtlasSelection, flag_atlas: str, flag_filename: str) -> None:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<GameData>', '  <IconTextureAtlases>']
    for size in NORMAL_ATLAS_SIZES:
        lines += ['    <Row>', f'      <Atlas>{icon_selection.atlas}</Atlas>', f'      <IconSize>{size}</IconSize>', f'      <Filename>{icon_selection.filename_for(size)}</Filename>', '      <IconsPerRow>4</IconsPerRow>', '      <IconsPerColumn>4</IconsPerColumn>', '    </Row>']
    for size in ALPHA_ICON_SIZES:
        lines += ['    <Row>', f'      <Atlas>{alpha_selection.atlas}</Atlas>', f'      <IconSize>{size}</IconSize>', f'      <Filename>{alpha_selection.filename_for(size)}</Filename>', '      <IconsPerRow>1</IconsPerRow>', '      <IconsPerColumn>1</IconsPerColumn>', '    </Row>']
    if flag_atlas:
        lines += ['    <Row>', f'      <Atlas>{flag_atlas}</Atlas>', '      <IconSize>32</IconSize>', f'      <Filename>{flag_filename}</Filename>', '      <IconsPerRow>8</IconsPerRow>', '      <IconsPerColumn>8</IconsPerColumn>', '    </Row>']
    lines += ['  </IconTextureAtlases>', '</GameData>']
    path.write_text('\n'.join(lines), encoding='utf-8')


def write_usage_xml(path: Path, cfg: PipelineConfig, normal_items: list[AssetSpec], alpha_atlas: str, scene_files: dict) -> None:
    up = cfg.prefix.upper()
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<GameData>', '  <!-- Template only: reconcile Types with your real mod SQL/XML. -->']
    lines += ['  <Civilizations>', '    <Row>', f'      <Type>CIVILIZATION_{up}</Type>', f'      <IconAtlas>{normal_items[0].atlas}</IconAtlas>', f'      <PortraitIndex>{normal_items[0].portrait_index}</PortraitIndex>', f'      <AlphaIconAtlas>{alpha_atlas}</AlphaIconAtlas>']
    if 'dawn_of_man' in scene_files:
        lines.append(f'      <DawnOfManImage>{scene_files["dawn_of_man"]}</DawnOfManImage>')
    if 'map' in scene_files:
        lines.append(f'      <MapImage>{scene_files["map"]}</MapImage>')
    lines += ['    </Row>', '  </Civilizations>']
    lines += ['  <Leaders>', '    <Row>', f'      <Type>LEADER_{up}</Type>', f'      <IconAtlas>{normal_items[1].atlas}</IconAtlas>', f'      <PortraitIndex>{normal_items[1].portrait_index}</PortraitIndex>', '    </Row>', '  </Leaders>']
    lines += ['  <!-- UnitFlagIconOffset values are zero-based positions in the 8x8 unit flag atlas. -->', '</GameData>']
    path.write_text('\n'.join(lines), encoding='utf-8')


def write_mod_replacements(cfg: PipelineConfig, generated_files: list[Path], log: Callable[[str], None]) -> None:
    if not cfg.mod_data_dir:
        raise SystemExit("--write-mod requires mod_data_dir after merging JSON config and CLI options")
    mod_root = cfg.mod_data_dir.resolve()
    replacements = find_mod_replacement_targets(cfg, generated_files)
    integrated: list[Path] = []
    for r in replacements:
        if r.get('duplicates'):
            duplicate_list = ", ".join(r['duplicates'])
            raise SystemExit(f"Multiple same-name DDS targets found inside mod_data_dir for {Path(r['generated']).name}: {duplicate_list}")
        if not r['will_replace']:
            if cfg.copy_new_assets:
                src = Path(r['generated']).resolve()
                art_dir = assert_inside_mod_data_dir(cfg.mod_data_dir / cfg.mod_art_subdir, mod_root)
                art_dir.mkdir(parents=True, exist_ok=True)
                dst = assert_inside_mod_data_dir(art_dir / src.name, mod_root)
                dst.write_bytes(src.read_bytes())
                integrated.append(dst)
                log(f"Copied new asset into mod: {dst}")
            else:
                log(f"No same-name DDS target found inside mod_data_dir; not integrated: {Path(r['generated']).name}")
            continue
        src = Path(r['generated']).resolve()
        dst = assert_inside_mod_data_dir(Path(r['mod_target']), mod_root)
        backup = assert_inside_mod_data_dir(dst.with_name(dst.name + ".bak"), mod_root)
        if not backup.exists():
            backup.write_bytes(dst.read_bytes())
            log(f"Backed up mod file: {backup}")
        dst.write_bytes(src.read_bytes())
        integrated.append(dst)
        log(f"Replaced mod file inside mod_data_dir: {dst}")
    if cfg.update_modinfo_imports and integrated:
        modinfo = select_modinfo_file(cfg.mod_data_dir)
        if modinfo:
            update_modinfo_imports(modinfo, mod_root, integrated, log)
        else:
            log("WARNING: --update-modinfo-imports set but no root .modinfo found; skipped.")
    refresh_modinfo_md5(cfg.mod_data_dir, log)


def refresh_modinfo_md5(mod_data_dir: Optional[Path], log: Callable[[str], None]) -> None:
    modinfo = select_modinfo_file(mod_data_dir)
    if not modinfo or not mod_data_dir:
        log("No root .modinfo file found under mod_data_dir; skipped .modinfo MD5 refresh.")
        return
    mod_root = mod_data_dir.resolve()
    modinfo = assert_inside_mod_data_dir(modinfo, mod_root)
    text = modinfo.read_text(encoding='utf-8', errors='ignore')
    base = modinfo.parent.resolve()

    def repl(m: re.Match) -> str:
        open_tag, value, close_tag = m.group(1), m.group(2).strip(), m.group(3)
        # .modinfo entries may use Windows backslashes or forward slashes; normalize
        # to the local OS separator so the path resolves on any platform.
        rel_parts = re.split(r"[\\/]+", value)
        target = assert_inside_mod_data_dir(base.joinpath(*rel_parts), mod_root)
        if not target.exists():
            return m.group(0)
        digest = md5(target.read_bytes()).hexdigest()
        if re.search(r'md5="[^"]*"', open_tag, flags=re.I):
            open_tag = re.sub(r'md5="[^"]*"', f'md5="{digest}"', open_tag, flags=re.I)
        else:
            open_tag = open_tag[:-1] + f' md5="{digest}">'
        return f'{open_tag}{value}{close_tag}'

    new = re.sub(r'(<File[^>]*>)([^<]+)(</File>)', repl, text, flags=re.I)
    if new != text:
        backup = assert_inside_mod_data_dir(modinfo.with_name(modinfo.name + ".bak"), mod_root)
        backup.write_text(text, encoding='utf-8')
        modinfo.write_text(new, encoding='utf-8')
        log(f"Backed up .modinfo: {backup}")
        log(f"Refreshed .modinfo MD5s: {modinfo}")
    else:
        log(f".modinfo MD5s already current or no existing files referenced: {modinfo}")


def write_qa_report(path: Path, manifest: dict) -> None:
    lines = [f"# {manifest['prefix']} Civ V Asset QA Report", "", f"Generated: {manifest['generated_utc']}", ""]
    # vNext: profile summary.
    lines += ["## Profile Summary"]
    alpha = manifest.get("alpha_icons", {})
    lines.append(f"- Alpha icon profile: {alpha.get('profile', 'legacy')}; "
                 f"black-background cleanup: {'yes' if alpha.get('black_background_cleanup') else 'no'}")
    for i in manifest.get("normal_icons", []):
        lines.append(f"- {i['role']} `{i['label']}`: profile {i.get('profile')}, "
                     f"safe_subject_scale {i.get('safe_subject_scale')}, "
                     f"master {i.get('normalized_source_size')}, "
                     f"circular mask baked: {'yes' if i.get('circular_mask_baked') else 'preview-only'}")
    for f in manifest.get("unit_flags", []):
        lines.append(f"- unit_flag `{f['label']}`: profile {f.get('profile')}, "
                     f"black-background cleanup: {'yes' if f.get('black_background_cleanup') else 'no'}, "
                     f"final {f.get('final_target_size')}")
    lines.append(f"- Per-asset previews written: "
                 f"{'yes' if (manifest.get('normal_icons') or [{}])[0].get('per_asset_previews') else 'no'}")
    lines.append("")
    groups = group_warnings_by_severity(manifest["warnings"])
    lines.append("## Warnings by severity")
    for sev in ("fatal", "strong", "normal", "info"):
        lines.append(f"### {sev.upper()}")
        if groups[sev]:
            lines += [f"- {w}" for w in groups[sev]]
        else:
            lines.append("- None")
    lines += ["", "## DDS Validation"]
    for item in manifest["dds_validation"]:
        lines.append(f"- `{item['name']}`: {item['metrics']}")
        for w in item["warnings"]:
            lines.append(f"  - WARNING: {w}")
    if manifest.get("alpha_icons", {}).get("metrics"):
        m = manifest['alpha_icons']['metrics']
        meaningful = m.get("alpha_min", 255) < 250 and m.get("alpha_max", 0) > 5
        lines += ["", "## Alpha / Team Icon Metrics",
                  f"- Alpha/team icon: `{m}`",
                  f"- Meaningful white-on-transparent: {'yes' if meaningful else 'NO - inspect, may be solid/opaque'}"]
    med = manifest.get("medallions", {})
    lines += ["", "## Medallion Baking"]
    if med:
        lines += [
            f"- Enabled for DDS output: {'yes' if med.get('enabled') and not med.get('preview_only') else 'no'}",
            f"- Preview-only: {'yes' if med.get('preview_only') else 'no'}",
            f"- Radius percent: {med.get('radius_percent')}",
            f"- Fill percent: {med.get('fill_percent')}",
            f"- Rim enabled: {'yes' if med.get('rim_enabled') else 'no'}",
            f"- Rim style: {med.get('rim_style')}",
            f"- Background: {med.get('background')}",
            "- Scope: normal icon atlas cells only; alpha/team icons, unit flags, maps, Dawn of Man, and leader scenes are not medallion-baked.",
        ]
    else:
        lines.append("- Disabled.")
    lines += ["", "## Normal Icon Metrics"]
    for item in manifest.get("normal_alpha_metrics", []):
        m = item['metrics']
        fb = m.get("likely_full_bleed")
        lines.append(f"- {item['role']} `{item['label']}`: opaque {m.get('opaque_pct')}%, "
                     f"transparent {m.get('transparent_pct')}%, safe margin {m.get('safe_margin_pct')}%, "
                     f"likely full-bleed: {fb}")
        if m.get("medallion"):
            med = m["medallion"]
            lines.append(f"  - Medallion: clipped={med.get('subject_clipped_by_circle')}; "
                         f"fill-ratio={med.get('subject_fill_ratio')}; "
                         f"fills-too-much={med.get('fills_too_much_circle')}; "
                         f"32px-unreadable-warning={med.get('potentially_unreadable_at_32px')}; "
                         f"32px-visible-coverage={med.get('visible_coverage_32_pct')}%")
    if manifest.get("unit_flag_alpha_metrics"):
        lines += ["", "## Unit Flag Metrics"]
        for item in manifest["unit_flag_alpha_metrics"]:
            m = item.get("metrics", {})
            assess = m.get("source_assessment", {})
            cleaned = item.get("black_bg_cleanup")
            resolved = m.get("painted_resolved_by_cleanup")
            if item.get("skipped"):
                status = "SKIPPED (painted)"
            elif cleaned:
                status = "packed (black-bg cleanup applied)"
            else:
                status = "packed"
            if resolved:
                # Cleanup handled a fully-opaque white-on-black source successfully.
                lines.append(f"- `{item['label']}` [{status}]: profile {item.get('profile')}; "
                             f"raw source was opaque white-on-black and was converted to "
                             f"white-on-transparent (pre-cleanup painted-heuristic no longer applies).")
            else:
                painted = assess.get("painted")
                lines.append(f"- `{item['label']}` [{status}]: profile {item.get('profile')}; "
                             f"painted-source={painted}; "
                             f"coverage {assess.get('coverage_pct')}%, edge {assess.get('edge_ratio_pct')}%, "
                             f"colors {assess.get('distinct_colors_32')}")
                if not cleaned:
                    for reason in assess.get("reasons", []):
                        lines.append(f"  - {reason}")
    lines += ["", "## Mod Integration Plan"]
    if manifest.get("planned_replacements"):
        for repl in manifest["planned_replacements"]:
            gen = Path(repl["generated"]).name
            if repl["mod_target"]:
                lines.append(f"- Generated file: {gen}")
                lines.append(f"  - Existing mod target: {repl['mod_target']}")
                lines.append("  - Action under --write-mod: replace and refresh .modinfo MD5")
            else:
                lines.append(f"- Generated file: {gen}")
                lines.append("  - No same-name mod target found; file will not be integrated automatically.")
    else:
        lines.append("- No --mod-data-dir supplied; nothing to integrate.")
    lines += ["", "## Validation Checklist",
              "- Confirm the mod SQL/XML points at the atlas name and PortraitIndex values in the manifest.",
              "- Confirm alpha/team icons preview as a white glyph on transparency, not a square/checkerboard.",
              "- Confirm unit flags are readable white silhouettes at 32px.",
              "- Clear the Civ V cache before retesting in-game."]
    path.write_text('\n'.join(lines), encoding='utf-8')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_asset(value: str, role: str) -> AssetSpec:
    # Accept label=path, label=path@index, label=path#TYPE_NAME, or path.
    portrait_index = None
    type_name = ''
    if '#' in value:
        value, type_name = value.rsplit('#', 1)
    if '@' in value:
        value, index_text = value.rsplit('@', 1)
        portrait_index = int(index_text)
    if '=' in value:
        label, path = value.split('=', 1)
    else:
        path = value
        label = Path(path).stem
    return AssetSpec(role=role, label=label.strip(), source=Path(path).expanduser(), portrait_index=portrait_index, type_name=type_name.strip())


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build Civ V BNW DDS art assets from PNGs.")
    absent = argparse.SUPPRESS
    p.add_argument('--config', type=Path, default=absent, help='JSON asset plan; CLI options override matching values')
    p.add_argument('--prefix', default=absent)
    p.add_argument('--output-dir', type=Path, default=absent)
    p.add_argument('--civ-icon', type=Path, default=absent)
    p.add_argument('--leader-icon', type=Path, default=absent)
    p.add_argument('--alpha-icon', type=Path, default=absent)
    p.add_argument('--unit', action='append', default=absent, help='label=path.png; repeat 1-4 times')
    p.add_argument('--building', action='append', default=absent, help='label=path.png; repeat 1-3 times')
    p.add_argument('--support', action='append', default=absent, help='label=path.png; optional repeat 0-8 times')
    p.add_argument('--flag', action='append', default=absent, help='label=path.png; optional repeat 0-4 times')
    p.add_argument('--map-image', type=Path, default=absent)
    p.add_argument('--dawn-image', type=Path, default=absent)
    p.add_argument('--leader-scene', type=Path, default=absent)
    p.add_argument('--mod-data-dir', type=Path, default=absent, help='Existing mod folder containing SQL/XML IconTextureAtlases to match')
    p.add_argument('--icon-atlas-name', default=absent)
    p.add_argument('--icon-atlas-stem', default=absent)
    p.add_argument('--flag-atlas-name', default=absent)
    p.add_argument('--flag-atlas-stem', default=absent)
    p.add_argument('--alpha-atlas-name', default=absent)
    p.add_argument('--asset-index', action='append', default=absent, help='Explicit per-asset index mapping as label=index; also supports label=path@index on asset args')
    p.add_argument('--dry-run', action='store_true', default=absent, help='Parse config + existing mod data and write only the dry-run plan; generate no art/XML/DDS and modify nothing')
    p.add_argument('--write-mod', action='store_true', default=absent, help='After generating output, replace same-name files in --mod-data-dir and refresh .modinfo MD5s')
    p.add_argument('--bake-circular-mask', action='store_true', default=absent, help='Actually bake circular masks into normal icon DDS atlases; by default masks are preview-only')
    p.add_argument('--bake-medallions', action='store_true', default=absent, help='Bake normal icon atlas cells into circular Civ V-style medallions')
    p.add_argument('--medallion-fill-percent', type=float, default=absent, help='How much of the medallion circle source art occupies (default: 0.94 in max-fill test build; old default was 0.84)')
    p.add_argument('--medallion-radius-percent', type=float, default=absent, help='Medallion radius relative to square cell size (default: 0.495 in max-fill test build; old default was 0.46)')
    p.add_argument('--medallion-rim', action='store_true', default=absent, help='Draw a simple rim around baked medallions')
    p.add_argument('--medallion-rim-width-percent', type=float, default=absent, help='Rim width relative to square cell size (default: 0.020 in max-fill test build; old default was 0.035)')
    p.add_argument('--medallion-rim-style', choices=['gold', 'silver', 'none'], default=absent, help='Medallion rim palette (default: gold)')
    p.add_argument('--medallion-background', choices=['transparent', 'dark', 'parchment', 'source-blur'], default=absent, help='Background outside/behind medallion circle (default: transparent)')
    p.add_argument('--medallion-preview-only', action='store_true', default=absent, help='Generate medallion previews but keep DDS atlases unchanged')
    p.add_argument('--allow-painted-flags', action='store_true', default=absent, help='Permit painted/opaque unit-flag sources (still warns); default is strict and skips them')
    p.add_argument('--dawn-output-name', default=absent, help='Force the Dawn of Man DDS filename (e.g. DawnOfMan_Florence.dds)')
    p.add_argument('--map-output-name', default=absent, help='Force the map DDS filename (e.g. Map_Florence512.dds)')
    p.add_argument('--leader-scene-output-name', default=absent, help='Force the leader scene DDS filename (e.g. Lorenzo_Scene.dds)')
    p.add_argument('--self-test-dds', action='store_true', default=absent, help='Run the DDS writer self-test and exit')
    p.add_argument('--preset', choices=['existing-combined-atlas', 'generated-separate-atlases', 'no-mod-integration'], default=absent)
    # --- vNext options -----------------------------------------------------
    p.add_argument('--check-only', action='store_true', default=absent, help='Validate config + sources and print a summary; write no DDS/previews/mod files')
    p.add_argument('--write-per-asset-previews', action='store_true', default=absent, help='Force per-asset previews under Previews/_per_asset/ (default: on for profiled configs)')
    p.add_argument('--allow-numeric-suffixes', action='store_true', default=absent, help='Permit source filenames with trailing numeric suffixes like _1.png/_256.png')
    p.add_argument('--leader-scene-profile', choices=['civ5_leader_scene_4x3', 'civ5_leader_scene_16x9'], default=absent, help='Leader scene aspect profile (default: civ5_leader_scene_4x3 / 1024x768)')
    p.add_argument('--alpha-profile', default=absent, help='Alpha/team icon profile, e.g. civ5_alpha_glyph_black_to_transparent (or alias white_glyph_black_background)')
    p.add_argument('--normal-icon-profile', default=absent, help='Top-level profile for civ/leader/unit/building icons, e.g. civ5_circular_icon')
    p.add_argument('--support-icon-profile', default=absent, help='Top-level profile for support/promotion icons, e.g. civ5_circular_icon')
    p.add_argument('--unit-flag-profile', default=absent, help='Top-level profile for unit flags, e.g. civ5_unit_flag_black_to_transparent')
    p.add_argument('--default-profile', default=absent, help='Config-level fallback profile for circular-icon roles that do not set their own profile')
    p.add_argument('--copy-new-assets', action='store_true', default=absent, help='With --write-mod, copy generated DDS that have no same-name target into mod_art_subdir')
    p.add_argument('--update-modinfo-imports', action='store_true', default=absent, help='With --write-mod, add import="1" <File> entries for integrated DDS to the root .modinfo')
    p.add_argument('--mod-art-subdir', default=absent, help='Subdirectory inside mod_data_dir for copied new assets (default: Art)')
    p.add_argument('--make-template', default=absent, metavar='PREFIX', help='Generate a starter profiled JSON config for PREFIX and exit')
    p.add_argument('--template-output', type=Path, default=absent, help='Output path for --make-template (default: <PREFIX>.dds.json)')
    p.add_argument('--template-profile', default=absent, help='Template profile name label (default: custom_civ)')
    p.add_argument('--template-units', type=int, default=absent, help='Number of unit icon/flag pairs in the template (default: 1)')
    p.add_argument('--template-buildings', type=int, default=absent, help='Number of building icons in the template (default: 1)')
    p.add_argument('--template-supports', type=int, default=absent, help='Number of support icons in the template (default: 0)')
    p.add_argument('--include-leader-scene', action='store_true', default=absent, help='Include a leader_scene entry in the generated template')
    p.add_argument('--include-flux-generated-names', action='store_true', default=absent, help='Add FLUX Schnell naming guidance notes to the template')
    return p


def parse_config_path(argv: Optional[list[str]]) -> Optional[Path]:
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument('--config', type=Path)
    known, _unknown = config_parser.parse_known_args(argv)
    return known.config


def read_config(path: Optional[Path]) -> dict:
    if not path:
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def cfg_value(args: argparse.Namespace, data: dict, name: str, default=None):
    if hasattr(args, name):
        cli = getattr(args, name)
        if cli not in (None, ''):
            return cli
    return data.get(name.replace('_', '-'), data.get(name, default))


def parse_asset_list(values, role: str) -> list[AssetSpec]:
    if not values:
        return []
    out = []
    for value in values:
        if isinstance(value, dict):
            spec = AssetSpec(role=role, label=value.get('label') or Path(value['source']).stem, source=Path(value['source']).expanduser())
            spec.portrait_index = value.get('portrait_index')
            # type_name wins over type; type is still treated as a Civ V TypeName.
            spec.type_name = value.get('type_name') or value.get('type', '')
            spec.asset_type = value.get('asset_type', '')
            spec.profile = value.get('profile', '')
            sss = value.get('safe_subject_scale')
            spec.safe_subject_scale = float(sss) if sss is not None else None
            opts = value.get('options')
            if isinstance(opts, dict):
                spec.options = opts
            out.append(spec)
        else:
            out.append(parse_asset(str(value), role))
    return out


def config_uses_profiles(data: dict, specs: Iterable[AssetSpec]) -> bool:
    """Detect whether a config opts into the profile-driven flow.

    True when any asset carries a profile/asset_type/safe_subject_scale, or when
    config-level profile fields are present. Old configs return False and keep the
    exact legacy 256-master behavior.
    """
    for s in specs:
        if s.profile or s.asset_type or s.safe_subject_scale is not None:
            return True
    config_keys = ("default_profile", "leader_scene_profile", "alpha_profile",
                   "normal_icon_profile", "support_icon_profile", "unit_flag_profile",
                   "write_per_asset_previews")
    return any(k in data for k in config_keys)




def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)

def parse_explicit_indexes(values) -> dict[str, int]:
    mapping = {}
    for value in values or []:
        label, index = str(value).split('=', 1)
        mapping[label.strip().lower()] = int(index)
    return mapping


def config_from_args(args: argparse.Namespace, data: Optional[dict] = None) -> PipelineConfig:
    data = read_config(getattr(args, 'config', None)) if data is None else data
    preset = cfg_value(args, data, 'preset', 'existing-combined-atlas')
    no_mod = preset == 'no-mod-integration'
    if no_mod:
        args.mod_data_dir = None
    explicit = parse_explicit_indexes(cfg_value(args, data, 'asset_index', []))
    units = parse_asset_list(cfg_value(args, data, 'unit', data.get('units', [])), 'unit')
    buildings = parse_asset_list(cfg_value(args, data, 'building', data.get('buildings', [])), 'building')
    supports = parse_asset_list(cfg_value(args, data, 'support', data.get('supports', [])), 'support')
    flags = parse_asset_list(cfg_value(args, data, 'flag', data.get('flags', [])), 'unit_flag')
    # Only normal-atlas assets should feed the normal explicit PortraitIndex map.
    # Unit flags have their own UnitFlagIconOffset/portrait index space and may
    # intentionally reuse the same labels as unit icons (e.g. DesertProwler).
    # Including flags here overwrites unit icon indexes with flag offsets.
    for spec in units + buildings + supports:
        if spec.portrait_index is not None:
            explicit[spec.label.lower()] = spec.portrait_index
    uses_profiles = config_uses_profiles(data, units + buildings + supports + flags)
    # CLI-only profile signals also opt into the profile-driven flow.
    if (cfg_value(args, data, 'alpha_profile', '') or cfg_value(args, data, 'default_profile', '')
            or cfg_value(args, data, 'leader_scene_profile', '')
            or cfg_value(args, data, 'normal_icon_profile', '') or cfg_value(args, data, 'support_icon_profile', '')
            or cfg_value(args, data, 'unit_flag_profile', '')):
        uses_profiles = True
    wpap_raw = cfg_value(args, data, 'write_per_asset_previews', None)
    write_per_asset = None if wpap_raw is None else as_bool(wpap_raw)
    cfg = PipelineConfig(
        prefix=cfg_value(args, data, 'prefix', ''),
        output_dir=Path(cfg_value(args, data, 'output_dir')) if cfg_value(args, data, 'output_dir') else None,
        civ_icon=Path(cfg_value(args, data, 'civ_icon', '')),
        leader_icon=Path(cfg_value(args, data, 'leader_icon', '')),
        alpha_icon=Path(cfg_value(args, data, 'alpha_icon', '')),
        units=units,
        buildings=buildings,
        supports=supports,
        flags=flags,
        map_image=Path(cfg_value(args, data, 'map_image')) if cfg_value(args, data, 'map_image') else None,
        dawn_image=Path(cfg_value(args, data, 'dawn_image')) if cfg_value(args, data, 'dawn_image') else None,
        leader_scene=Path(cfg_value(args, data, 'leader_scene')) if cfg_value(args, data, 'leader_scene') else None,
        mod_data_dir=None if no_mod else (Path(cfg_value(args, data, 'mod_data_dir')) if cfg_value(args, data, 'mod_data_dir') else None),
        icon_atlas_name=cfg_value(args, data, 'icon_atlas_name', ''),
        icon_atlas_stem=cfg_value(args, data, 'icon_atlas_stem', ''),
        flag_atlas_name=cfg_value(args, data, 'flag_atlas_name', ''),
        flag_atlas_stem=cfg_value(args, data, 'flag_atlas_stem', ''),
        alpha_atlas_name=cfg_value(args, data, 'alpha_atlas_name', ''),
        dry_run=as_bool(cfg_value(args, data, 'dry_run', False)),
        write_mod=as_bool(cfg_value(args, data, 'write_mod', False)),
        bake_circular_mask=as_bool(cfg_value(args, data, 'bake_circular_mask', False)),
        medallion=MedallionOptions(
            bake=as_bool(cfg_value(args, data, 'bake_medallions', False)),
            fill_percent=float(cfg_value(args, data, 'medallion_fill_percent', 0.94)),
            radius_percent=float(cfg_value(args, data, 'medallion_radius_percent', 0.495)),
            rim=as_bool(cfg_value(args, data, 'medallion_rim', False)),
            rim_width_percent=float(cfg_value(args, data, 'medallion_rim_width_percent', 0.020)),
            rim_style=cfg_value(args, data, 'medallion_rim_style', 'gold'),
            background=cfg_value(args, data, 'medallion_background', 'transparent'),
            preview_only=as_bool(cfg_value(args, data, 'medallion_preview_only', False)),
        ),
        allow_painted_flags=as_bool(cfg_value(args, data, 'allow_painted_flags', False)),
        preset=preset,
        explicit_indexes=explicit,
        dawn_output_name=cfg_value(args, data, 'dawn_output_name', ''),
        map_output_name=cfg_value(args, data, 'map_output_name', ''),
        leader_scene_output_name=cfg_value(args, data, 'leader_scene_output_name', ''),
        leader_scene_profile=cfg_value(args, data, 'leader_scene_profile', ''),
        write_per_asset_previews=write_per_asset,
        allow_numeric_suffixes=as_bool(cfg_value(args, data, 'allow_numeric_suffixes', False)),
        copy_new_assets=as_bool(cfg_value(args, data, 'copy_new_assets', False)),
        update_modinfo_imports=as_bool(cfg_value(args, data, 'update_modinfo_imports', False)),
        mod_art_subdir=cfg_value(args, data, 'mod_art_subdir', 'Art') or 'Art',
        uses_profiles=uses_profiles,
        default_profile=cfg_value(args, data, 'default_profile', '') or '',
        normal_icon_profile=cfg_value(args, data, 'normal_icon_profile', '') or '',
        support_icon_profile=cfg_value(args, data, 'support_icon_profile', '') or '',
        unit_flag_profile=cfg_value(args, data, 'unit_flag_profile', '') or '',
    )
    # Stash optional alpha profile for the alpha-icon flow (not a core field).
    # cfg_value already prefers a CLI --alpha-profile over the JSON alpha_profile.
    cfg._alpha_profile = (cfg_value(args, data, 'alpha_profile', '') or None)
    return cfg


def main(argv: Optional[list[str]] = None) -> int:
    try:
        config_path = parse_config_path(argv)
        data = read_config(config_path)
        parser = build_arg_parser()
        args = parser.parse_args(argv)
        if config_path and not hasattr(args, 'config'):
            args.config = config_path
        if getattr(args, 'self_test_dds', False):
            ok = self_test_dds(getattr(args, 'output_dir', None))
            return 0 if ok else 1
        # --make-template short-circuits before any config requirement.
        template_prefix = getattr(args, 'make_template', None)
        if template_prefix:
            out = make_template(
                prefix=template_prefix,
                output=getattr(args, 'template_output', None) or None,
                units=getattr(args, 'template_units', None) if getattr(args, 'template_units', None) is not None else 1,
                buildings=getattr(args, 'template_buildings', None) if getattr(args, 'template_buildings', None) is not None else 1,
                supports=getattr(args, 'template_supports', None) if getattr(args, 'template_supports', None) is not None else 0,
                include_leader_scene=bool(getattr(args, 'include_leader_scene', False)),
                include_flux_names=bool(getattr(args, 'include_flux_generated_names', False)),
                profile=getattr(args, 'template_profile', None) or "custom_civ",
            )
            print(f"Wrote template: {out}")
            return 0
        cfg = config_from_args(args, data)
        if getattr(args, 'check_only', False):
            return run_check_only(cfg)
        generate_assets(cfg)
        return 0
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        print(exc, file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
