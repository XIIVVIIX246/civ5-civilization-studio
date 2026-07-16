#!/usr/bin/env python3
"""
Simple Civ V DDS Builder

A small deterministic builder for Civilization V custom-civ art.
It is intentionally simpler than the large universal pipeline.

Profiles supported:
- prebuilt_circle      : finished circular Civ V-style icon already includes border/ring
- raw_square_medallion : raw square art that should be turned into a Civ V medallion icon
- alpha_glyph          : centered glyph on transparent background
- unit_flag            : centered glyph/icon for 32x32 unit-flag atlas slots
- map                  : opaque 512x512 image
- dawn                 : opaque 1024x768 image
- leader_scene         : opaque 1024x768 image

Outputs:
- normal icon atlases: 256, 128, 80, 64, 45, 32 (4x4 atlas)
- alpha standalone DDS files: 128, 80, 64, 48, 45, 32, 24
- unit flag atlas: 256x256 (8x8 grid of 32x32 slots)
- map / Dawn of Man / leader scene DDS files
- PNG previews for validation

DDS format:
- uncompressed 32-bit A8R8G8B8 compatible byte layout (BGRA bytes)
- no mipmaps
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from PIL import Image, ImageDraw, ImageChops
except ImportError:
    print("This script requires Pillow. Install it with: pip install pillow", file=sys.stderr)
    raise

# -----------------------------
# Constants / defaults
# -----------------------------
NORMAL_ATLAS_SIZES = [256, 128, 80, 64, 45, 32]
ALPHA_SIZES = [128, 80, 64, 48, 45, 32, 24]
UNIT_FLAG_ATLAS_SIZE = 256
UNIT_FLAG_SLOT_SIZE = 32
UNIT_FLAG_GRID = 8
NORMAL_ATLAS_GRID = 4

# Dai Viet-inspired visible-fit defaults
DEFAULT_VISIBLE_RATIO = 172.0 / 256.0   # 0.671875
BUILDING_VISIBLE_RATIO = 178.0 / 256.0  # 0.6953125
LEADER_VISIBLE_RATIO = 176.0 / 256.0    # 0.6875
UNIT_FLAG_VISIBLE_RATIO = 22.0 / 32.0   # 0.6875
ALPHA_VISIBLE_RATIO = 0.70

# Raw square medallion defaults
MEDALLION_RADIUS_RATIO = 0.46
MEDALLION_RIM_WIDTH_RATIO = 0.035
RAW_SQUARE_SUBJECT_RATIO = 0.78
MEDALLION_BG = (30, 24, 16, 255)
MEDALLION_GOLD_LIGHT = (245, 211, 110, 255)
MEDALLION_GOLD_MID = (202, 151, 54, 255)
MEDALLION_GOLD_DARK = (109, 72, 24, 255)

# -----------------------------
# Config dataclasses
# -----------------------------
@dataclass
class IconItem:
    label: str
    file: str
    role: str = "support"          # civ, leader, unit, building, support
    profile: str = "prebuilt_circle"  # prebuilt_circle or raw_square_medallion
    portrait_index: Optional[int] = None
    visible_ratio: Optional[float] = None
    subject_ratio: Optional[float] = None  # for raw_square_medallion


@dataclass
class OutputConfig:
    output_dir: str
    normal_atlas_base: str = "CivIconAtlas"
    alpha_base: str = "CivAlpha"
    normal_atlas_pattern: Optional[str] = None
    alpha_pattern: Optional[str] = None
    unit_flag_atlas_name: str = "CivUnitFlags32.dds"
    map_output_name: Optional[str] = None
    dawn_output_name: Optional[str] = None
    leader_scene_output_name: Optional[str] = None
    preview_dir_name: str = "Previews"


@dataclass
class AssetConfig:
    civ_icon: Optional[IconItem] = None
    leader_icon: Optional[IconItem] = None
    normal_icons: list[IconItem] = field(default_factory=list)
    alpha_icon: Optional[dict[str, Any]] = None
    unit_flags: list[dict[str, Any]] = field(default_factory=list)
    map_image: Optional[str] = None
    dawn_image: Optional[str] = None
    leader_scene: Optional[str] = None


@dataclass
class BuilderConfig:
    output: OutputConfig
    assets: AssetConfig
    mod_art_dir: Optional[str] = None
    copy_to_mod: bool = False


# -----------------------------
# Utilities
# -----------------------------
def load_rgba(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def center_crop_to_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    if w == h:
        return img
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def alpha_bbox(img: Image.Image) -> Optional[tuple[int, int, int, int]]:
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    return bbox


def scrub_transparent_rgb(img: Image.Image) -> Image.Image:
    """Clear RGB values where alpha is zero to avoid colored halos."""
    img = img.convert("RGBA")
    data = bytearray(img.tobytes())
    for i in range(0, len(data), 4):
        if data[i + 3] == 0:
            data[i + 0] = 0
            data[i + 1] = 0
            data[i + 2] = 0
    return Image.frombytes("RGBA", img.size, bytes(data))

def white_on_black_to_transparent(img: Image.Image) -> Image.Image:
    """Convert a white glyph on black background into white RGBA with transparent background."""
    img = img.convert("RGBA")
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    src = img.load()
    dst = out.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = src[x, y]
            luma = int(0.2126 * r + 0.7152 * g + 0.0722 * b)
            alpha = int(max(0, min(255, luma)) * (a / 255.0))
            dst[x, y] = (255, 255, 255, alpha)
    return scrub_transparent_rgb(out)


def maybe_prepare_glyph(img: Image.Image, source_mode: str = "auto") -> Image.Image:
    """Prepare alpha/unit flag source art.

    source_mode:
    - white_on_black: convert black background to transparency
    - transparent: use existing alpha as-is
    - auto: if fully opaque with dark corners, treat as white_on_black
    """
    source_mode = (source_mode or "auto").lower()
    img = img.convert("RGBA")
    if source_mode in {"white_on_black", "black", "black_background"}:
        return white_on_black_to_transparent(img)
    if source_mode in {"transparent", "alpha", "rgba"}:
        return img

    a = img.getchannel("A")
    if a.getextrema()[0] >= 250:
        px = img.load()
        corners = [
            px[0, 0],
            px[img.width - 1, 0],
            px[0, img.height - 1],
            px[img.width - 1, img.height - 1],
        ]
        avg_luma = sum((0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) for c in corners) / 4.0
        if avg_luma < 40:
            return white_on_black_to_transparent(img)
    return img



def fit_full_square(img: Image.Image, canvas_size: int, visible_ratio: float) -> Image.Image:
    """Resize the whole square image into a centered square area of the canvas."""
    sq = center_crop_to_square(img)
    target = max(1, int(round(canvas_size * visible_ratio)))
    sq = sq.resize((target, target), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    xy = ((canvas_size - target) // 2, (canvas_size - target) // 2)
    canvas.alpha_composite(sq, xy)
    return scrub_transparent_rgb(canvas)


def fit_subject_square(img: Image.Image, canvas_size: int, subject_ratio: float) -> Image.Image:
    """Crop to alpha bbox if present; else center-crop to square; then fit to target size."""
    sq = center_crop_to_square(img)
    bbox = alpha_bbox(sq)
    if bbox:
        subject = sq.crop(bbox)
    else:
        subject = sq
    target = max(1, int(round(canvas_size * subject_ratio)))
    scale = min(target / max(1, subject.size[0]), target / max(1, subject.size[1]))
    new_w = max(1, int(round(subject.size[0] * scale)))
    new_h = max(1, int(round(subject.size[1] * scale)))
    subject = subject.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    xy = ((canvas_size - new_w) // 2, (canvas_size - new_h) // 2)
    canvas.alpha_composite(subject, xy)
    return scrub_transparent_rgb(canvas)


def _ellipse_mask(size: int, bbox: tuple[float, float, float, float], scale: int = 4) -> Image.Image:
    big = Image.new("L", (size * scale, size * scale), 0)
    draw = ImageDraw.Draw(big)
    draw.ellipse([v * scale for v in bbox], fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def build_raw_square_medallion(img: Image.Image, canvas_size: int, subject_ratio: float = RAW_SQUARE_SUBJECT_RATIO) -> Image.Image:
    """Build one Civ V-style medallion from raw square art."""
    subject = fit_subject_square(img, canvas_size, subject_ratio)
    out = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    center = canvas_size / 2.0
    radius = canvas_size * MEDALLION_RADIUS_RATIO
    rim_w = canvas_size * MEDALLION_RIM_WIDTH_RATIO

    # Outer decorative rings
    outer_bbox = (center - radius, center - radius, center + radius, center + radius)
    ring2_bbox = (center - (radius - rim_w * 1.4), center - (radius - rim_w * 1.4),
                  center + (radius - rim_w * 1.4), center + (radius - rim_w * 1.4))
    inner_art_bbox = (center - (radius - rim_w * 2.5), center - (radius - rim_w * 2.5),
                      center + (radius - rim_w * 2.5), center + (radius - rim_w * 2.5))

    draw = ImageDraw.Draw(out)
    draw.ellipse(outer_bbox, fill=MEDALLION_GOLD_DARK)
    draw.ellipse((outer_bbox[0] + rim_w * 0.35, outer_bbox[1] + rim_w * 0.35,
                  outer_bbox[2] - rim_w * 0.35, outer_bbox[3] - rim_w * 0.35), fill=MEDALLION_GOLD_LIGHT)
    draw.ellipse(ring2_bbox, fill=MEDALLION_GOLD_DARK)
    draw.ellipse((ring2_bbox[0] + rim_w * 0.45, ring2_bbox[1] + rim_w * 0.45,
                  ring2_bbox[2] - rim_w * 0.45, ring2_bbox[3] - rim_w * 0.45), fill=MEDALLION_BG)

    # Clip art into the inner circular area.
    mask = _ellipse_mask(canvas_size, inner_art_bbox)
    clipped = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    tmp = subject.copy()
    # combine source alpha with the circle mask
    tmp.putalpha(ImageChops.multiply(tmp.getchannel("A"), mask))
    clipped.alpha_composite(tmp)
    out.alpha_composite(clipped)
    return scrub_transparent_rgb(out)


def role_default_ratio(role: str) -> float:
    role = (role or "").lower()
    if role == "building":
        return BUILDING_VISIBLE_RATIO
    if role == "leader":
        return LEADER_VISIBLE_RATIO
    return DEFAULT_VISIBLE_RATIO


def build_normal_icon_cell(icon: IconItem, path: Path, size: int) -> Image.Image:
    img = load_rgba(path)
    profile = (icon.profile or "prebuilt_circle").lower()
    if profile == "prebuilt_circle":
        ratio = float(icon.visible_ratio) if icon.visible_ratio is not None else role_default_ratio(icon.role)
        return fit_full_square(img, size, ratio)
    if profile == "raw_square_medallion":
        subject_ratio = float(icon.subject_ratio) if icon.subject_ratio is not None else RAW_SQUARE_SUBJECT_RATIO
        medallion = build_raw_square_medallion(img, size, subject_ratio)
        # Raw square art needs a ring, but the finished ring should still obey
        # the same Dai Viet-style safe padding as prebuilt circular icons.
        ratio = float(icon.visible_ratio) if icon.visible_ratio is not None else role_default_ratio(icon.role)
        return fit_full_square(medallion, size, ratio)
    raise ValueError(f"Unknown normal icon profile: {icon.profile}")


def build_alpha_cell(path: Path, size: int, visible_ratio: float = ALPHA_VISIBLE_RATIO, source_mode: str = "auto") -> Image.Image:
    img = maybe_prepare_glyph(load_rgba(path), source_mode)
    return fit_subject_square(img, size, visible_ratio)


def build_unit_flag_cell(path: Path, size: int = UNIT_FLAG_SLOT_SIZE, visible_ratio: float = UNIT_FLAG_VISIBLE_RATIO, source_mode: str = "auto") -> Image.Image:
    img = maybe_prepare_glyph(load_rgba(path), source_mode)
    return fit_subject_square(img, size, visible_ratio)


def build_opaque_image(path: Path, size: tuple[int, int]) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    img = ImageOpsContain(img, size)
    canvas = Image.new("RGBA", size, (0, 0, 0, 255))
    x = (size[0] - img.width) // 2
    y = (size[1] - img.height) // 2
    canvas.alpha_composite(img, (x, y))
    # flatten to opaque
    flat = Image.new("RGBA", size, (0, 0, 0, 255))
    flat.alpha_composite(canvas)
    return flat


def ImageOpsContain(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    # lightweight replacement avoiding direct dependency on ImageOps.contain variations
    w, h = img.size
    sw, sh = size
    scale = min(sw / max(1, w), sh / max(1, h))
    new_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def make_normal_atlas(cells: list[Image.Image], size: int) -> Image.Image:
    atlas = Image.new("RGBA", (size * NORMAL_ATLAS_GRID, size * NORMAL_ATLAS_GRID), (0, 0, 0, 0))
    for idx, cell in enumerate(cells):
        x = (idx % NORMAL_ATLAS_GRID) * size
        y = (idx // NORMAL_ATLAS_GRID) * size
        atlas.alpha_composite(cell, (x, y))
    return scrub_transparent_rgb(atlas)


def make_unit_flag_atlas(cells: list[Image.Image]) -> Image.Image:
    atlas = Image.new("RGBA", (UNIT_FLAG_ATLAS_SIZE, UNIT_FLAG_ATLAS_SIZE), (0, 0, 0, 0))
    for idx, cell in enumerate(cells):
        x = (idx % UNIT_FLAG_GRID) * UNIT_FLAG_SLOT_SIZE
        y = (idx // UNIT_FLAG_GRID) * UNIT_FLAG_SLOT_SIZE
        atlas.alpha_composite(cell, (x, y))
    return scrub_transparent_rgb(atlas)


# -----------------------------
# DDS writer (uncompressed 32-bit BGRA / A8R8G8B8)
# -----------------------------
def write_dds_rgba(img: Image.Image, out_path: Path) -> None:
    img = img.convert("RGBA")
    width, height = img.size

    # DDS_PIXELFORMAT structure
    DDPF_ALPHAPIXELS = 0x1
    DDPF_RGB = 0x40
    pf_size = 32
    pf_flags = DDPF_RGB | DDPF_ALPHAPIXELS
    pf_fourcc = 0
    pf_rgb_bit_count = 32
    pf_r_mask = 0x00FF0000
    pf_g_mask = 0x0000FF00
    pf_b_mask = 0x000000FF
    pf_a_mask = 0xFF000000

    DDSD_CAPS = 0x1
    DDSD_HEIGHT = 0x2
    DDSD_WIDTH = 0x4
    DDSD_PITCH = 0x8
    DDSD_PIXELFORMAT = 0x1000
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT
    pitch = width * 4

    DDSCAPS_TEXTURE = 0x1000

    header_values = [
        124,        # dwSize
        flags,
        height,
        width,
        pitch,
        0,          # depth
        0,          # mip map count
        *([0] * 11),
        pf_size,
        pf_flags,
        pf_fourcc,
        pf_rgb_bit_count,
        pf_r_mask,
        pf_g_mask,
        pf_b_mask,
        pf_a_mask,
        DDSCAPS_TEXTURE,
        0, 0, 0, 0  # caps2,caps3,caps4,reserved2
    ]
    if len(header_values) != 31:
        raise AssertionError(f"DDS header expected 31 ints, got {len(header_values)}")
    header = struct.pack('<4s31I', b'DDS ', *header_values)

    raw = bytearray(img.tobytes())
    # RGBA -> BGRA in-place
    for i in range(0, len(raw), 4):
        raw[i], raw[i + 2] = raw[i + 2], raw[i]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('wb') as f:
        f.write(header)
        f.write(raw)


# -----------------------------
# Config parsing
# -----------------------------
def parse_icon_item(data: dict[str, Any]) -> IconItem:
    return IconItem(
        label=data["label"],
        file=data["file"],
        role=data.get("role", "support"),
        profile=data.get("profile", "prebuilt_circle"),
        portrait_index=data.get("portrait_index"),
        visible_ratio=data.get("visible_ratio"),
        subject_ratio=data.get("subject_ratio"),
    )


def parse_config(path: Path) -> BuilderConfig:
    data = json.loads(path.read_text(encoding='utf-8'))
    out = OutputConfig(**data["output"])
    a = data["assets"]
    assets = AssetConfig(
        civ_icon=parse_icon_item(a["civ_icon"]) if a.get("civ_icon") else None,
        leader_icon=parse_icon_item(a["leader_icon"]) if a.get("leader_icon") else None,
        normal_icons=[parse_icon_item(x) for x in a.get("normal_icons", [])],
        alpha_icon=a.get("alpha_icon"),
        unit_flags=a.get("unit_flags", []),
        map_image=a.get("map_image"),
        dawn_image=a.get("dawn_image"),
        leader_scene=a.get("leader_scene"),
    )
    return BuilderConfig(
        output=out,
        assets=assets,
        mod_art_dir=data.get("mod_art_dir"),
        copy_to_mod=bool(data.get("copy_to_mod", False)),
    )


def validate_config(cfg: BuilderConfig, config_path: Path) -> list[str]:
    errors: list[str] = []
    root = config_path.parent
    if not cfg.output.output_dir:
        errors.append("output.output_dir is required")

    def check_path(p: Optional[str], label: str):
        if p and not (root / p).exists() and not Path(p).exists():
            errors.append(f"Missing file for {label}: {p}")

    for label, item in [("civ_icon", cfg.assets.civ_icon), ("leader_icon", cfg.assets.leader_icon)]:
        if item:
            check_path(item.file, label)
    for idx, item in enumerate(cfg.assets.normal_icons):
        check_path(item.file, f"normal_icons[{idx}]")
    if cfg.assets.alpha_icon:
        check_path(cfg.assets.alpha_icon.get("file"), "alpha_icon")
    for idx, item in enumerate(cfg.assets.unit_flags):
        check_path(item.get("file"), f"unit_flags[{idx}]")
    check_path(cfg.assets.map_image, "map_image")
    check_path(cfg.assets.dawn_image, "dawn_image")
    check_path(cfg.assets.leader_scene, "leader_scene")

    # normal icon capacity: 16 max in 4x4 atlas
    total_normal = len([x for x in [cfg.assets.civ_icon, cfg.assets.leader_icon] if x]) + len(cfg.assets.normal_icons)
    if total_normal > NORMAL_ATLAS_GRID * NORMAL_ATLAS_GRID:
        errors.append(f"Too many normal icons ({total_normal}). Max supported is 16 for one 4x4 atlas.")
    return errors


def resolve_path(base_dir: Path, p: str) -> Path:
    pth = Path(p)
    return pth if pth.is_absolute() else (base_dir / pth)


# -----------------------------
# Build process
# -----------------------------
def build(cfg: BuilderConfig, config_path: Path) -> dict[str, list[Path]]:
    base_dir = config_path.parent
    out_dir = resolve_path(base_dir, cfg.output.output_dir)
    preview_dir = out_dir / cfg.output.preview_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    outputs: dict[str, list[Path]] = {"dds": [], "previews": []}

    # Assemble normal icon order.
    normal_items: list[IconItem] = []
    if cfg.assets.civ_icon:
        normal_items.append(cfg.assets.civ_icon)
    if cfg.assets.leader_icon:
        normal_items.append(cfg.assets.leader_icon)
    normal_items.extend(cfg.assets.normal_icons)

    # Normal icon atlases + preview PNGs
    if normal_items:
        for size in NORMAL_ATLAS_SIZES:
            cells = [build_normal_icon_cell(item, resolve_path(base_dir, item.file), size) for item in normal_items]
            atlas = make_normal_atlas(cells, size)
            normal_name = (cfg.output.normal_atlas_pattern or f"{cfg.output.normal_atlas_base}_{{size}}.dds").format(size=size)
            dds_path = out_dir / normal_name
            write_dds_rgba(atlas, dds_path)
            outputs["dds"].append(dds_path)

            preview_path = preview_dir / f"{Path(normal_name).stem}_preview.png"
            atlas.save(preview_path)
            outputs["previews"].append(preview_path)

    # Alpha standalone DDSs
    if cfg.assets.alpha_icon:
        alpha_file = resolve_path(base_dir, cfg.assets.alpha_icon["file"])
        alpha_ratio = float(cfg.assets.alpha_icon.get("visible_ratio", ALPHA_VISIBLE_RATIO))
        alpha_source_mode = cfg.assets.alpha_icon.get("source_mode", "auto")
        for size in ALPHA_SIZES:
            img = build_alpha_cell(alpha_file, size, alpha_ratio, alpha_source_mode)
            alpha_name = (cfg.output.alpha_pattern or f"{cfg.output.alpha_base}_{{size}}.dds").format(size=size)
            dds_path = out_dir / alpha_name
            write_dds_rgba(img, dds_path)
            outputs["dds"].append(dds_path)

            preview_path = preview_dir / f"{Path(alpha_name).stem}_preview.png"
            img.save(preview_path)
            outputs["previews"].append(preview_path)

    # Unit flag atlas
    if cfg.assets.unit_flags:
        flag_cells = []
        for item in cfg.assets.unit_flags:
            ratio = float(item.get("visible_ratio", UNIT_FLAG_VISIBLE_RATIO))
            source_mode = item.get("source_mode", "auto")
            flag_cells.append(build_unit_flag_cell(resolve_path(base_dir, item["file"]), UNIT_FLAG_SLOT_SIZE, ratio, source_mode))
        atlas = make_unit_flag_atlas(flag_cells)
        dds_path = out_dir / cfg.output.unit_flag_atlas_name
        write_dds_rgba(atlas, dds_path)
        outputs["dds"].append(dds_path)
        preview_path = preview_dir / (Path(cfg.output.unit_flag_atlas_name).stem + "_preview.png")
        atlas.save(preview_path)
        outputs["previews"].append(preview_path)

    # Map / Dawn / Leader Scene
    if cfg.assets.map_image and cfg.output.map_output_name:
        img = build_opaque_image(resolve_path(base_dir, cfg.assets.map_image), (512, 512))
        path = out_dir / cfg.output.map_output_name
        write_dds_rgba(img, path)
        outputs["dds"].append(path)
        p = preview_dir / (Path(cfg.output.map_output_name).stem + "_preview.png")
        img.save(p)
        outputs["previews"].append(p)

    if cfg.assets.dawn_image and cfg.output.dawn_output_name:
        img = build_opaque_image(resolve_path(base_dir, cfg.assets.dawn_image), (1024, 768))
        path = out_dir / cfg.output.dawn_output_name
        write_dds_rgba(img, path)
        outputs["dds"].append(path)
        p = preview_dir / (Path(cfg.output.dawn_output_name).stem + "_preview.png")
        img.save(p)
        outputs["previews"].append(p)

    if cfg.assets.leader_scene and cfg.output.leader_scene_output_name:
        img = build_opaque_image(resolve_path(base_dir, cfg.assets.leader_scene), (1024, 768))
        path = out_dir / cfg.output.leader_scene_output_name
        write_dds_rgba(img, path)
        outputs["dds"].append(path)
        p = preview_dir / (Path(cfg.output.leader_scene_output_name).stem + "_preview.png")
        img.save(p)
        outputs["previews"].append(p)

    # Optional copy to mod art folder
    if cfg.copy_to_mod and cfg.mod_art_dir:
        mod_dir = resolve_path(base_dir, cfg.mod_art_dir)
        mod_dir.mkdir(parents=True, exist_ok=True)
        for f in outputs["dds"]:
            shutil.copy2(f, mod_dir / f.name)

    return outputs


def write_report(cfg: BuilderConfig, config_path: Path, outputs: dict[str, list[Path]]) -> Path:
    base_dir = config_path.parent
    out_dir = resolve_path(base_dir, cfg.output.output_dir)
    report = out_dir / "BUILD_REPORT.md"
    lines = [
        "# Simple Civ V DDS Builder Report",
        "",
        f"Config: `{config_path}`",
        f"Output dir: `{out_dir}`",
        "",
        "## Standards",
        f"- Default prebuilt-circle visible ratio: `{DEFAULT_VISIBLE_RATIO:.6f}` (172/256)",
        f"- Building prebuilt-circle visible ratio: `{BUILDING_VISIBLE_RATIO:.6f}` (178/256)",
        f"- Leader prebuilt-circle visible ratio: `{LEADER_VISIBLE_RATIO:.6f}` (176/256)",
        f"- Unit flag visible ratio: `{UNIT_FLAG_VISIBLE_RATIO:.6f}` (22/32)",
        f"- Alpha visible ratio default: `{ALPHA_VISIBLE_RATIO:.2f}`",
        f"- Raw-square subject ratio default: `{RAW_SQUARE_SUBJECT_RATIO:.2f}`",
        "",
        f"DDS files written: **{len(outputs['dds'])}**",
        f"Preview PNGs written: **{len(outputs['previews'])}**",
        "",
        "## DDS Files",
    ]
    for p in outputs["dds"]:
        lines.append(f"- `{p.name}`")
    lines += ["", "## Preview Files"]
    for p in outputs["previews"]:
        lines.append(f"- `{p.name}`")
    report.write_text("\n".join(lines), encoding='utf-8')
    return report


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build Civ V DDS assets from a simple JSON manifest.")
    p.add_argument("--config", required=True, help="Path to JSON config manifest")
    p.add_argument("--copy-to-mod", action="store_true", help="Override config and copy DDS outputs into mod_art_dir")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = make_parser().parse_args(argv)
    config_path = Path(args.config).resolve()
    cfg = parse_config(config_path)
    if args.copy_to_mod:
        cfg.copy_to_mod = True
    errors = validate_config(cfg, config_path)
    if errors:
        print("Configuration errors:", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        return 2
    outputs = build(cfg, config_path)
    report_path = write_report(cfg, config_path, outputs)
    print("Build complete.")
    print(f"DDS files: {len(outputs['dds'])}")
    print(f"Preview PNGs: {len(outputs['previews'])}")
    print(f"Report: {report_path}")
    if cfg.copy_to_mod and cfg.mod_art_dir:
        print(f"Copied DDS files to mod art dir: {cfg.mod_art_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
