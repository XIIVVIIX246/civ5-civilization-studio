#!/usr/bin/env python3
r"""
udmb_atlas_builder.py
=====================
Small UDMB-specific PNG -> DDS atlas builder for Civilization V: Brave New World.

Purpose
-------
Builds the Universal Defensive Military Buildings (UDMB) 8x8 normal icon atlas:
  UDMB_IconAtlas_256.dds
  UDMB_IconAtlas_128.dds
  UDMB_IconAtlas_80.dds
  UDMB_IconAtlas_64.dds
  UDMB_IconAtlas_45.dds
  UDMB_IconAtlas_32.dds

This is intentionally smaller than the universal custom-civ converter. It does
not require civ/leader/alpha/map/DOM assets. It only builds one normal icon atlas
from an "icons" list in JSON.

Key defaults
------------
* 8x8 atlas grid, matching UDMB_08_Art.sql.
* safe_subject_scale defaults to 0.72 for buildings and 0.78 for promotions.
* Optional baked Firaxis-style circular medallion/rim output. When enabled,
  square corners stay transparent while the circular icon area is filled.
* Optional one-off recovery mode for already-circular source PNGs: strip the
  old baked ring/background, keep the inner art disk, then rebake one clean
  medallion at the new size.
* Writes uncompressed 32-bit BGRA/A8R8G8B8 DDS with no mipmaps.

Example
-------
python .\udmb_atlas_builder.py --config .\UDMB.json --check-only
python .\udmb_atlas_builder.py --config .\UDMB.json
python .\udmb_atlas_builder.py --config .\UDMB.json --write-mod
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import struct
import sys
from dataclasses import dataclass, field
from hashlib import md5
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageStat

ATLAS_SIZES = [256, 128, 80, 64, 45, 32]
GRID_DEFAULT = 8
SAFE_MARGIN_WARN = 0.04


@dataclass
class IconSpec:
    label: str
    source: Path
    portrait_index: int
    table: str = ""
    type_name: str = ""
    safe_subject_scale: Optional[float] = None


@dataclass
class Config:
    prefix: str = "UDMB"
    input_dir: Optional[Path] = None
    output_dir: Path = Path("Output/UDMB")
    mod_data_dir: Optional[Path] = None
    icon_atlas_name: str = "UDMB_ICON_ATLAS"
    icon_atlas_stem: str = "UDMB_IconAtlas"
    icons_per_row: int = GRID_DEFAULT
    icons_per_column: int = GRID_DEFAULT
    atlas_sizes: list[int] = field(default_factory=lambda: ATLAS_SIZES.copy())
    bake_circular_mask: bool = False
    bake_medallions: bool = False
    medallion_radius_percent: float = 0.485
    medallion_rim_width_percent: float = 0.035
    medallion_rim_style: str = "firaxis_gold"
    medallion_background_mode: str = "firaxis_dark"
    source_has_prebaked_medallion: bool = False
    strip_prebaked_medallion: bool = False
    prebaked_inner_art_radius_percent: float = 0.90
    default_safe_subject_scale: float = 0.76
    building_safe_subject_scale: float = 0.72
    promotion_safe_subject_scale: float = 0.78
    copy_new_assets: bool = False
    update_modinfo_imports: bool = False
    icons: list[IconSpec] = field(default_factory=list)


def save_as_dds(img: Image.Image, path: Path) -> None:
    """Save uncompressed 32-bit BGRA DDS with alpha and one mip level."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = scrub_transparent_rgb(img.convert("RGBA"))
    w, h = img.size
    r, g, b, a = img.split()
    pixel_data = Image.merge("RGBA", (b, g, r, a)).tobytes()
    header = struct.pack(
        "<IIIIIII44xIIIIIIIIIIIII",
        124,
        0x0002100F,
        h, w, w * 4,
        0, 1,
        32, 0x41, 0, 32,
        0x00FF0000,
        0x0000FF00,
        0x000000FF,
        0xFF000000,
        0x1000, 0, 0, 0, 0,
    )
    with path.open("wb") as f:
        f.write(b"DDS ")
        f.write(header)
        f.write(pixel_data)


def read_dds_header(path: Path) -> dict:
    data = path.read_bytes()[:128]
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


def scrub_transparent_rgb(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    transparent = a.point(lambda p: 255 if p == 0 else 0)
    img.paste(Image.new("RGBA", img.size, (0, 0, 0, 0)), (0, 0), transparent)
    return img


def open_rgba(path: Path) -> Image.Image:
    try:
        return Image.open(path).convert("RGBA")
    except Exception as exc:
        raise SystemExit(f"Could not open PNG {path}: {exc}") from exc


def alpha_bbox(img: Image.Image, threshold: int = 8):
    alpha = img.convert("RGBA").getchannel("A")
    mask = alpha.point(lambda p: 255 if p > threshold else 0)
    return mask.getbbox()


def center_crop_to_square(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    side = min(img.width, img.height)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


def _luma(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _saturation_proxy(rgb):
    return max(rgb) - min(rgb)


def _color_distance(c1, c2):
    return math.sqrt((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2)


def remove_edge_connected_flat_background(img: Image.Image, label: str, warnings: list[str], tolerance: int = 52) -> Image.Image:
    """Remove opaque white/black/checkerboard mats touching the image edge.

    This is a safe subset copied from the universal pipeline behavior. It helps
    when AI-generated art has a black/white square around a circular medallion.
    It only removes edge-connected flat areas and leaves the interior art alone.
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
    is_bright_mat = avg_luma >= 235 and avg_sat <= 35 and spread <= 35
    is_dark_mat = avg_luma <= 35 and spread <= 35
    corner_lumas = [_luma(c) for c in corners]
    corner_sats = [_saturation_proxy(c) for c in corners]
    is_checker_mat = (not is_bright_mat and not is_dark_mat and min(corner_lumas) >= 205 and max(corner_sats) <= 45)
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
            if work_mask.getpixel(xy) == 255:
                ImageDraw.floodfill(work_mask, xy, marker_value, thresh=0)
        mask = work_mask.point(lambda p: 255 if p == marker_value else 0)
    else:
        marker = (255, 0, 255) if avg != (255, 0, 255) else (0, 255, 0)
        work = src.convert("RGB")
        for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            ImageDraw.floodfill(work, xy, marker, thresh=tolerance)
        r, g, b = work.split()
        if marker == (255, 0, 255):
            mask = r.point(lambda p: 255 if p == 255 else 0)
            mask = ImageChops.multiply(mask, g.point(lambda p: 255 if p == 0 else 0))
            mask = ImageChops.multiply(mask, b.point(lambda p: 255 if p == 255 else 0))
        else:
            mask = r.point(lambda p: 255 if p == 0 else 0)
            mask = ImageChops.multiply(mask, g.point(lambda p: 255 if p == 255 else 0))
            mask = ImageChops.multiply(mask, b.point(lambda p: 255 if p == 0 else 0))
    removed = int(ImageStat.Stat(mask).sum[0] / 255)
    if not removed:
        return src
    out = src.copy()
    a = ImageChops.subtract(out.getchannel("A"), mask)
    out.putalpha(a)
    warnings.append(f"{label}: removed edge-connected source mat before fitting ({removed} px).")
    return out


def extract_prebaked_medallion_art(img: Image.Image, label: str, inner_art_radius_percent: float, warnings: list[str]) -> Image.Image:
    """Strip an existing baked ring/background and keep only the inner art disk.

    This is a one-off recovery mode for source PNGs that already contain a
    circular Civ V-style medallion. It preserves only the painted interior so
    the builder can rebake a single clean rim at the desired size.
    """
    img = img.convert("RGBA")
    if img.width != img.height:
        img = center_crop_to_square(img)
    size = min(img.width, img.height)
    alpha = img.getchannel("A")
    bbox = alpha_bbox(img)
    if bbox:
        l, t, r, b = bbox
        diameter = min(r - l, b - t)
        cx = (l + r) / 2.0
        cy = (t + b) / 2.0
        radius = diameter / 2.0
    else:
        cx = cy = (size - 1) / 2.0
        radius = size * 0.485
        warnings.append(f"{label}: pre-baked medallion strip mode used geometric fallback circle.")

    inner_scale = max(0.5, min(float(inner_art_radius_percent), 0.98))
    inner_radius = max(1.0, radius * inner_scale)
    inner_bbox = (cx - inner_radius, cy - inner_radius, cx + inner_radius, cy + inner_radius)
    mask = _aa_ellipse_mask(size, inner_bbox)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    subject = img.copy()
    subject.putalpha(ImageChops.darker(subject.getchannel("A"), mask))
    out.alpha_composite(subject)
    warnings.append(f"{label}: stripped pre-baked medallion rim/background and kept inner art disk (radius scale {inner_scale:.2f}).")
    return scrub_transparent_rgb(out)


def normalize_icon_master(src_path: Path, label: str, scale: float, master_size: int = 1024, warnings: Optional[list[str]] = None, cfg: Optional[Config] = None) -> Image.Image:
    warnings = warnings if warnings is not None else []
    img = open_rgba(src_path)
    if img.width != img.height:
        warnings.append(f"{label}: non-square source was center-cropped/padded to square.")
    alpha = img.getchannel("A")
    amin, _ = alpha.getextrema()
    if amin >= 250:
        img = remove_edge_connected_flat_background(img, label, warnings)
        alpha = img.getchannel("A")
        amin, _ = alpha.getextrema()

    if cfg and cfg.source_has_prebaked_medallion and cfg.strip_prebaked_medallion:
        img = extract_prebaked_medallion_art(img, label, cfg.prebaked_inner_art_radius_percent, warnings)
        alpha = img.getchannel("A")
        amin, _ = alpha.getextrema()

    bbox = alpha_bbox(img) if amin < 250 else None
    if bbox:
        subject = img.crop(bbox)
    else:
        subject = center_crop_to_square(img)
        warnings.append(f"{label}: source is fully opaque; fitted as square art with transparent padding added around it.")

    max_subject = int(round(master_size * float(scale)))
    resize_scale = min(max_subject / subject.width, max_subject / subject.height)
    new_size = (max(1, int(round(subject.width * resize_scale))), max(1, int(round(subject.height * resize_scale))))
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


def _aa_ellipse_mask(size: int, bbox: tuple[float, float, float, float], scale: int = 4) -> Image.Image:
    """Return an anti-aliased L-mode ellipse mask for a square cell."""
    big = Image.new("L", (size * scale, size * scale), 0)
    bb = tuple(int(round(v * scale)) for v in bbox)
    ImageDraw.Draw(big).ellipse(bb, fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def _radial_fill(size: int, inner_mask: Image.Image, mode: str = "firaxis_dark") -> Image.Image:
    """Create a subtle Civ V-like inner medallion background.

    This prevents a visibly empty transparent center when the source icon is a
    cut-out subject. The result is still fully transparent outside inner_mask.
    """
    mode = (mode or "firaxis_dark").lower()
    if mode in {"none", "transparent", "off"}:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    if mode in {"stone", "firaxis_stone"}:
        center = (94, 88, 75)
        edge = (35, 32, 28)
    elif mode in {"gold", "firaxis_gold"}:
        center = (118, 87, 42)
        edge = (42, 29, 15)
    else:
        center = (82, 64, 43)
        edge = (25, 21, 17)

    cx = cy = (size - 1) / 2.0
    max_r = max(1.0, size * 0.5)
    px = bytearray()
    mask_data = inner_mask.tobytes()
    for y in range(size):
        for x in range(size):
            m = mask_data[y * size + x]
            if m == 0:
                px.extend((0, 0, 0, 0))
                continue
            d = min(1.0, math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_r)
            # Slight center lift, darker edge. This reads well down to 32px.
            t = d ** 0.85
            r = int(center[0] * (1 - t) + edge[0] * t)
            g = int(center[1] * (1 - t) + edge[1] * t)
            b = int(center[2] * (1 - t) + edge[2] * t)
            px.extend((r, g, b, m))
    return Image.frombytes("RGBA", (size, size), bytes(px))


def _rim_colors(style: str) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int]]:
    style = (style or "firaxis_gold").lower()
    if style in {"stone", "firaxis_stone"}:
        return (150, 139, 116, 255), (74, 66, 52, 255), (224, 204, 156, 220)
    if style in {"bronze", "firaxis_bronze"}:
        return (159, 103, 45, 255), (70, 42, 19, 255), (229, 170, 83, 230)
    return (184, 139, 58, 255), (76, 49, 19, 255), (242, 203, 109, 235)


def bake_medallion_cell(
    img: Image.Image,
    radius_percent: float = 0.485,
    rim_width_percent: float = 0.035,
    rim_style: str = "firaxis_gold",
    background_mode: str = "firaxis_dark",
) -> Image.Image:
    """Bake a Firaxis-style circular medallion into one atlas cell.

    The final cell keeps transparent square corners, fills the circular icon
    body, clips the subject to the inner circle, and draws a small rim on top.
    """
    img = img.convert("RGBA")
    if img.width != img.height:
        img = center_crop_to_square(img)
    size = img.width
    radius = max(1.0, min(float(radius_percent), 0.5) * size)
    cx = cy = (size - 1) / 2.0
    outer_bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    rim_px = max(1.0, float(rim_width_percent) * size)
    inner_radius = max(1.0, radius - rim_px)
    inner_bbox = (cx - inner_radius, cy - inner_radius, cx + inner_radius, cy + inner_radius)

    outer_mask = _aa_ellipse_mask(size, outer_bbox)
    inner_mask = _aa_ellipse_mask(size, inner_bbox)
    ring_mask = ImageChops.subtract(outer_mask, inner_mask)

    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base.alpha_composite(_radial_fill(size, inner_mask, background_mode))

    # Clip subject/art to the inside of the medallion so it never bleeds into
    # transparent corners or over the baked rim.
    subject = img.copy()
    subject_alpha = ImageChops.darker(subject.getchannel("A"), inner_mask)
    subject.putalpha(subject_alpha)
    base.alpha_composite(subject)

    rim_main, rim_shadow, rim_highlight = _rim_colors(rim_style)
    rim_layer = Image.new("RGBA", (size, size), rim_main)
    base.paste(rim_layer, (0, 0), ring_mask)

    # Small shadows/highlights help the rim survive the 45px and 32px versions.
    draw = ImageDraw.Draw(base, "RGBA")
    outline_w = max(1, int(round(size * 0.006)))
    highlight_w = max(1, int(round(size * 0.004)))
    draw.ellipse(outer_bbox, outline=rim_shadow, width=outline_w)
    draw.ellipse(inner_bbox, outline=rim_shadow, width=outline_w)
    inset = max(1.0, size * 0.011)
    hi_bbox = (outer_bbox[0] + inset, outer_bbox[1] + inset, outer_bbox[2] - inset, outer_bbox[3] - inset)
    draw.arc(hi_bbox, start=205, end=335, fill=rim_highlight, width=highlight_w)
    return scrub_transparent_rgb(base)


def render_icon_cell(master: Image.Image, cfg: Config, size: int) -> Image.Image:
    """Render one atlas cell using the configured circular/mask policy."""
    cell = master.resize((size, size), Image.Resampling.LANCZOS)
    if cfg.bake_medallions:
        return bake_medallion_cell(
            cell,
            radius_percent=cfg.medallion_radius_percent,
            rim_width_percent=cfg.medallion_rim_width_percent,
            rim_style=cfg.medallion_rim_style,
            background_mode=cfg.medallion_background_mode,
        )
    if cfg.bake_circular_mask:
        return apply_circular_mask(cell)
    return cell


def alpha_metrics(img: Image.Image) -> dict:
    a = img.convert("RGBA").getchannel("A")
    hist = a.histogram()
    total = img.width * img.height
    amin, amax = a.getextrema()
    bbox = alpha_bbox(img)
    margin = None
    if bbox:
        l, t, r, b = bbox
        margin = min(l / img.width, t / img.height, (img.width - r) / img.width, (img.height - b) / img.height)
    return {
        "alpha_min": amin,
        "alpha_max": amax,
        "opaque_pct": round(sum(hist[250:]) / total * 100, 2),
        "transparent_pct": round(sum(hist[:5]) / total * 100, 2),
        "safe_margin_pct": None if margin is None else round(margin * 100, 2),
        "likely_full_bleed": bool(margin is not None and margin < SAFE_MARGIN_WARN),
    }


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    img = Image.new("RGBA", size, (220, 220, 220, 255))
    d = ImageDraw.Draw(img)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(150, 150, 150, 255))
    return img


def make_atlas_preview(masters: dict[int, tuple[IconSpec, Image.Image]], cfg: Config, path: Path, circular: bool = False) -> None:
    cell = 96
    sheet = checkerboard((cfg.icons_per_row * cell, cfg.icons_per_column * cell), 12)
    draw = ImageDraw.Draw(sheet)
    for idx, (spec, master) in masters.items():
        img = render_icon_cell(master, cfg, cell) if cfg.bake_medallions else master.resize((cell, cell), Image.Resampling.LANCZOS)
        if circular and not cfg.bake_medallions:
            img = apply_circular_mask(img)
        x = (idx % cfg.icons_per_row) * cell
        y = (idx // cfg.icons_per_row) * cell
        sheet.paste(img, (x, y), img)
        draw.rectangle((x, y, x + cell - 1, y + cell - 1), outline=(255, 0, 0, 180))
        if circular:
            draw.ellipse((x, y, x + cell - 1, y + cell - 1), outline=(0, 255, 255, 220), width=1)
        draw.text((x + 2, y + 2), str(idx), fill=(255, 255, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def make_tech_size_preview(masters: dict[int, tuple[IconSpec, Image.Image]], cfg: Config, path: Path) -> None:
    # Row strip showing 45px and 32px outputs on checkerboard for visual scale checks.
    cell = 64
    cols = min(cfg.icons_per_row, 8)
    rows = math.ceil(len(masters) / cols)
    sheet = checkerboard((cols * cell, rows * cell), 8)
    draw = ImageDraw.Draw(sheet)
    for pos, idx in enumerate(sorted(masters)):
        spec, master = masters[idx]
        x = (pos % cols) * cell
        y = (pos // cols) * cell
        icon45 = render_icon_cell(master, cfg, 45)
        sheet.paste(icon45, (x + 2, y + 16), icon45)
        icon32 = render_icon_cell(master, cfg, 32)
        sheet.paste(icon32, (x + 48 - 16, y + 28), icon32)
        draw.text((x + 2, y + 2), str(idx), fill=(255, 255, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def parse_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    cfg = Config()
    cfg.prefix = data.get("prefix", "UDMB")
    cfg.input_dir = Path(data["input_dir"]) if data.get("input_dir") else None
    cfg.output_dir = Path(data.get("output_dir", "Output/UDMB"))
    cfg.mod_data_dir = Path(data["mod_data_dir"]) if data.get("mod_data_dir") else None
    cfg.icon_atlas_name = data.get("icon_atlas_name", "UDMB_ICON_ATLAS")
    cfg.icon_atlas_stem = data.get("icon_atlas_stem", "UDMB_IconAtlas")
    cfg.icons_per_row = int(data.get("icons_per_row", GRID_DEFAULT))
    cfg.icons_per_column = int(data.get("icons_per_column", GRID_DEFAULT))
    cfg.atlas_sizes = [int(x) for x in data.get("atlas_sizes", ATLAS_SIZES)]
    cfg.bake_circular_mask = bool(data.get("bake_circular_mask", False))
    cfg.bake_medallions = bool(data.get("bake_medallions", False))
    cfg.medallion_radius_percent = float(data.get("medallion_radius_percent", 0.485))
    cfg.medallion_rim_width_percent = float(data.get("medallion_rim_width_percent", 0.035))
    cfg.medallion_rim_style = data.get("medallion_rim_style", "firaxis_gold")
    cfg.medallion_background_mode = data.get("medallion_background_mode", "firaxis_dark")
    cfg.source_has_prebaked_medallion = bool(data.get("source_has_prebaked_medallion", False))
    cfg.strip_prebaked_medallion = bool(data.get("strip_prebaked_medallion", False))
    cfg.prebaked_inner_art_radius_percent = float(data.get("prebaked_inner_art_radius_percent", 0.90))
    cfg.default_safe_subject_scale = float(data.get("default_safe_subject_scale", 0.76))
    cfg.building_safe_subject_scale = float(data.get("building_safe_subject_scale", 0.72))
    cfg.promotion_safe_subject_scale = float(data.get("promotion_safe_subject_scale", 0.78))
    cfg.copy_new_assets = bool(data.get("copy_new_assets", False))
    cfg.update_modinfo_imports = bool(data.get("update_modinfo_imports", False))
    icons = []
    for item in data.get("icons", []):
        source = Path(item["source"])
        icons.append(IconSpec(
            label=item.get("label") or source.stem,
            source=source,
            portrait_index=int(item["portrait_index"]),
            table=item.get("table", ""),
            type_name=item.get("type_name", ""),
            safe_subject_scale=float(item["safe_subject_scale"]) if item.get("safe_subject_scale") is not None else None,
        ))
    cfg.icons = icons
    return cfg


def validate_config(cfg: Config) -> list[str]:
    errors = []
    if cfg.icons_per_row != 8 or cfg.icons_per_column != 8:
        errors.append("UDMB builder expects icons_per_row=8 and icons_per_column=8.")
    if not 0.0 < cfg.medallion_radius_percent <= 0.5:
        errors.append("medallion_radius_percent must be greater than 0 and less than or equal to 0.5.")
    if not 0.0 < cfg.medallion_rim_width_percent < cfg.medallion_radius_percent:
        errors.append("medallion_rim_width_percent must be greater than 0 and smaller than medallion_radius_percent.")
    if not cfg.icons:
        errors.append("No icons configured.")
    seen = set()
    for icon in cfg.icons:
        if icon.portrait_index in seen:
            errors.append(f"Duplicate portrait_index {icon.portrait_index}.")
        seen.add(icon.portrait_index)
        if icon.portrait_index < 0 or icon.portrait_index >= cfg.icons_per_row * cfg.icons_per_column:
            errors.append(f"{icon.label}: portrait_index {icon.portrait_index} is outside 0-63.")
        if not icon.source.exists() or not icon.source.is_file():
            errors.append(f"{icon.label}: missing source PNG: {icon.source}")
        if icon.source.suffix.lower() != ".png":
            errors.append(f"{icon.label}: source must be a .png: {icon.source}")
    if cfg.mod_data_dir and not cfg.mod_data_dir.exists():
        errors.append(f"mod_data_dir does not exist: {cfg.mod_data_dir}")
    return errors


def scale_for_icon(cfg: Config, icon: IconSpec) -> float:
    if icon.safe_subject_scale is not None:
        return icon.safe_subject_scale
    role = (icon.table or "").lower()
    type_name = (icon.type_name or "").upper()
    source_name = icon.source.name.lower()
    if role == "unitpromotions" or type_name.startswith("PROMOTION_") or "promotionicon" in source_name or "promotion_icon" in source_name:
        return cfg.promotion_safe_subject_scale
    if role == "buildings" or type_name.startswith("BUILDING_"):
        return cfg.building_safe_subject_scale
    return cfg.default_safe_subject_scale


def build_atlas(cfg: Config, check_only: bool = False) -> dict:
    warnings: list[str] = []
    errors = validate_config(cfg)
    if errors:
        raise SystemExit("\n".join(errors))

    planned = [f"{cfg.icon_atlas_stem}_{s}.dds" for s in cfg.atlas_sizes]
    summary = {
        "prefix": cfg.prefix,
        "atlas": cfg.icon_atlas_name,
        "grid": [cfg.icons_per_row, cfg.icons_per_column],
        "sizes": cfg.atlas_sizes,
        "planned_dds": planned,
        "icons": [],
        "warnings": warnings,
        "bake_medallions": cfg.bake_medallions,
        "medallion_radius_percent": cfg.medallion_radius_percent,
        "medallion_rim_width_percent": cfg.medallion_rim_width_percent,
        "medallion_rim_style": cfg.medallion_rim_style,
        "medallion_background_mode": cfg.medallion_background_mode,
    }
    if check_only:
        return summary

    art_dir = cfg.output_dir / "Art"
    preview_dir = cfg.output_dir / "Previews"
    xml_dir = cfg.output_dir / "XML"
    art_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    xml_dir.mkdir(parents=True, exist_ok=True)

    masters: dict[int, tuple[IconSpec, Image.Image]] = {}
    for icon in cfg.icons:
        scale = scale_for_icon(cfg, icon)
        master = normalize_icon_master(icon.source, f"{icon.portrait_index}:{icon.label}", scale, 1024, warnings, cfg)
        masters[icon.portrait_index] = (icon, master)
        metrics = alpha_metrics(master)
        summary["icons"].append({
            "label": icon.label,
            "type_name": icon.type_name,
            "table": icon.table,
            "portrait_index": icon.portrait_index,
            "source": str(icon.source),
            "safe_subject_scale": scale,
            "metrics": metrics,
        })
        if metrics.get("likely_full_bleed"):
            warnings.append(f"{icon.portrait_index}:{icon.label}: icon may still be too full-bleed; inspect previews.")

    for size in cfg.atlas_sizes:
        atlas = Image.new("RGBA", (size * cfg.icons_per_row, size * cfg.icons_per_column), (0, 0, 0, 0))
        for idx, (icon, master) in masters.items():
            cell = render_icon_cell(master, cfg, size)
            x = (idx % cfg.icons_per_row) * size
            y = (idx // cfg.icons_per_row) * size
            atlas.paste(cell, (x, y), cell)
        out = art_dir / f"{cfg.icon_atlas_stem}_{size}.dds"
        save_as_dds(atlas, out)
        h = read_dds_header(out)
        if h["width"] != size * cfg.icons_per_row or h["height"] != size * cfg.icons_per_column or h["fourcc"] != 0 or h["bpp"] != 32:
            warnings.append(f"{out.name}: DDS validation issue: {h}")

    make_atlas_preview(masters, cfg, preview_dir / "UDMB_atlas_square_preview.png", circular=False)
    make_atlas_preview(masters, cfg, preview_dir / "UDMB_atlas_circle_preview_review_only.png", circular=True)
    make_tech_size_preview(masters, cfg, preview_dir / "UDMB_tech_size_45_32_preview.png")
    write_art_sql_template(cfg, xml_dir / "UDMB_08_Art_Template.sql")
    write_report(cfg, summary, cfg.output_dir / "UDMB_AtlasBuilder_Report.md")
    (cfg.output_dir / "UDMB_AtlasBuilder_Manifest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def write_art_sql_template(cfg: Config, path: Path) -> None:
    lines = [
        "-- UDMB_08_Art.sql template generated by udmb_atlas_builder.py",
        "INSERT OR IGNORE INTO IconTextureAtlases",
        "\t(Atlas, IconSize, Filename, IconsPerRow, IconsPerColumn)",
        "VALUES",
    ]
    vals = []
    for size in cfg.atlas_sizes:
        vals.append(f"\t('{cfg.icon_atlas_name}', {size}, '{cfg.icon_atlas_stem}_{size}.dds', {cfg.icons_per_row}, {cfg.icons_per_column})")
    lines.append(",\n".join(vals) + ";")
    lines.append("")
    for icon in sorted(cfg.icons, key=lambda x: x.portrait_index):
        if not icon.type_name or icon.table.lower() == "reserved":
            lines.append(f"-- Reserved slot {icon.portrait_index}: {icon.label}")
            continue
        table = icon.table or ("UnitPromotions" if icon.type_name.upper().startswith("PROMOTION_") else "Buildings")
        lines.append(f"UPDATE {table} SET IconAtlas = '{cfg.icon_atlas_name}', PortraitIndex = {icon.portrait_index} WHERE Type = '{icon.type_name}';")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_report(cfg: Config, manifest: dict, path: Path) -> None:
    lines = [
        "# UDMB Atlas Builder Report",
        "",
        f"Atlas: `{cfg.icon_atlas_name}`",
        f"Grid: {cfg.icons_per_row}x{cfg.icons_per_column}",
        f"Output: `{cfg.output_dir}`",
        f"Baked medallions: `{cfg.bake_medallions}`",
        f"Medallion radius: `{cfg.medallion_radius_percent}`",
        f"Medallion rim width: `{cfg.medallion_rim_width_percent}`",
        f"Source has pre-baked medallion: `{cfg.source_has_prebaked_medallion}`",
        f"Strip pre-baked medallion: `{cfg.strip_prebaked_medallion}`",
        f"Pre-baked inner art radius percent: `{cfg.prebaked_inner_art_radius_percent}`",
        "",
        "## DDS Files",
    ]
    for name in manifest["planned_dds"]:
        lines.append(f"- `Art/{name}`")
    lines += ["", "## Icon Slots"]
    for icon in manifest["icons"]:
        lines.append(f"- {icon['portrait_index']:02d}: `{icon['label']}` scale={icon['safe_subject_scale']} safe_margin={icon['metrics'].get('safe_margin_pct')}%")
    lines += ["", "## Warnings"]
    if manifest["warnings"]:
        lines += [f"- {w}" for w in manifest["warnings"]]
    else:
        lines.append("- None")
    lines += [
        "",
        "## Preview Files",
        "- `Previews/UDMB_atlas_square_preview.png`",
        "- `Previews/UDMB_atlas_circle_preview_review_only.png`",
        "- `Previews/UDMB_tech_size_45_32_preview.png`",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def select_modinfo_file(mod_data_dir: Path) -> Optional[Path]:
    infos = sorted(p for p in mod_data_dir.glob("*.modinfo") if p.is_file())
    if len(infos) > 1:
        raise SystemExit("Multiple .modinfo files in mod_data_dir; refusing to update.")
    return infos[0] if infos else None


def write_mod(cfg: Config) -> None:
    if not cfg.mod_data_dir:
        raise SystemExit("--write-mod requires mod_data_dir in JSON or CLI.")
    art_src = cfg.output_dir / "Art"
    art_dst = cfg.mod_data_dir / "Art"
    art_dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for size in cfg.atlas_sizes:
        src = art_src / f"{cfg.icon_atlas_stem}_{size}.dds"
        dst = art_dst / src.name
        if dst.exists() and not (dst.with_name(dst.name + ".bak")).exists():
            shutil.copy2(dst, dst.with_name(dst.name + ".bak"))
        shutil.copy2(src, dst)
        copied.append(dst)
        print(f"Wrote mod DDS: {dst}")
    refresh_modinfo_md5(cfg, copied)


def refresh_modinfo_md5(cfg: Config, copied: list[Path]) -> None:
    if not cfg.mod_data_dir:
        return
    modinfo = select_modinfo_file(cfg.mod_data_dir)
    if not modinfo:
        print("No .modinfo found; skipped MD5 refresh.")
        return
    text = modinfo.read_text(encoding="utf-8", errors="ignore")
    base = modinfo.parent
    rel_to_digest = {}
    for p in copied:
        rel = p.relative_to(base).as_posix().lower()
        rel_back = str(p.relative_to(base)).replace("/", "\\").lower()
        digest = md5(p.read_bytes()).hexdigest()
        rel_to_digest[rel] = digest
        rel_to_digest[rel_back] = digest

    def repl(m: re.Match) -> str:
        open_tag, value, close_tag = m.group(1), m.group(2).strip(), m.group(3)
        norm = value.replace("\\", "/").lower()
        digest = rel_to_digest.get(norm) or rel_to_digest.get(value.lower())
        if not digest:
            return m.group(0)
        if re.search(r'md5="[^"]*"', open_tag, flags=re.I):
            open_tag = re.sub(r'md5="[^"]*"', f'md5="{digest}"', open_tag, flags=re.I)
        else:
            open_tag = open_tag[:-1] + f' md5="{digest}">'
        if 'import=' not in open_tag.lower():
            open_tag = open_tag[:-1] + ' import="1">'
        return f"{open_tag}{value}{close_tag}"

    new = re.sub(r'(<File[^>]*>)([^<]+)(</File>)', repl, text, flags=re.I)
    if new != text:
        backup = modinfo.with_name(modinfo.name + ".bak")
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")
        modinfo.write_text(new, encoding="utf-8")
        print(f"Refreshed .modinfo MD5s: {modinfo}")
    else:
        print("No matching DDS entries found in .modinfo; MD5 refresh skipped.")


def build_arg_parser():
    p = argparse.ArgumentParser(description="UDMB-specific 8x8 Civ V PNG -> DDS atlas builder.")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--write-mod", action="store_true")
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--mod-data-dir", type=Path)
    p.add_argument("--bake-circular-mask", action="store_true")
    p.add_argument("--bake-medallions", action="store_true")
    p.add_argument("--strip-prebaked-medallion", action="store_true")
    return p


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = parse_config(args.config)
    if args.output_dir:
        cfg.output_dir = args.output_dir
    if args.mod_data_dir:
        cfg.mod_data_dir = args.mod_data_dir
    if args.bake_circular_mask:
        cfg.bake_circular_mask = True
    if args.bake_medallions:
        cfg.bake_medallions = True
    if args.strip_prebaked_medallion:
        cfg.source_has_prebaked_medallion = True
        cfg.strip_prebaked_medallion = True
    if args.check_only:
        errors = validate_config(cfg)
        if errors:
            print("UDMB check: FAILED")
            for e in errors:
                print("ERROR:", e)
            return 1
        print("UDMB check: OK")
        print(f"Icons: {len(cfg.icons)}")
        print(f"Atlas: {cfg.icon_atlas_name}, {cfg.icons_per_row}x{cfg.icons_per_column}")
        print(f"Output: {cfg.output_dir}")
        if cfg.strip_prebaked_medallion:
            print(f"Pre-baked medallion strip mode: ON (inner art radius scale {cfg.prebaked_inner_art_radius_percent})")
        print("Planned DDS:")
        for s in cfg.atlas_sizes:
            print(f"  {cfg.icon_atlas_stem}_{s}.dds")
        return 0
    manifest = build_atlas(cfg, check_only=False)
    print(f"Built UDMB atlas in: {cfg.output_dir}")
    print(f"Warnings: {len(manifest['warnings'])}")
    for w in manifest['warnings'][:12]:
        print("WARNING:", w)
    if args.write_mod:
        write_mod(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
