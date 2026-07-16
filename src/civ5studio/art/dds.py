"""Legacy DX9 DDS writing and validation for Civilization V.

Pillow 10+ contains a BCn encoder.  Its DXT1/DXT5 payloads are usable, but the
default DDS metadata differs from the DirectXTex files used by the SMP
pipeline.  This module normalizes the 128-byte header to a conventional DX9,
one-surface, one-mip layout and validates every file after writing it.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from .profiles import AlphaMode, DdsFormat, DdsProfile
from .rendering import scrub_transparent_rgb


DDS_MAGIC = b"DDS "
DDS_HEADER_SIZE = 128
DDSD_ONE_MIP_LINEAR = 0x000A1007
DDSD_ONE_MIP_PITCH = 0x0002100F
DDPF_ALPHAPIXELS_AND_RGB = 0x41
DDSCAPS_TEXTURE = 0x1000


@dataclass(frozen=True, slots=True)
class DdsHeader:
    width: int
    height: int
    flags: int
    pitch_or_linear_size: int
    depth: int
    mipmap_count: int
    pixel_flags: int
    fourcc: str
    bits_per_pixel: int
    red_mask: int
    green_mask: int
    blue_mask: int
    alpha_mask: int
    caps: int
    caps2: int

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DdsWriteResult:
    path: Path
    profile: str
    header: DdsHeader
    encoder: str


def _prepare_image(image: Image.Image, profile: DdsProfile) -> Image.Image:
    source = image.convert("RGBA")
    has_transparency = source.getchannel("A").getextrema()[0] < 255
    if profile.alpha is AlphaMode.REQUIRED and not has_transparency:
        raise ValueError(f"DDS profile {profile.name!r} requires meaningful transparency")
    if profile.alpha is AlphaMode.OPAQUE:
        source = Image.alpha_composite(
            Image.new("RGBA", source.size, (0, 0, 0, 255)), source
        )
    return scrub_transparent_rgb(source)


def write_bgra_dds(image: Image.Image, path: Path) -> None:
    """Write uncompressed A8R8G8B8/BGRA with one surface and no mip chain."""

    rgba = scrub_transparent_rgb(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = rgba.size
    red, green, blue, alpha = rgba.split()
    pixels = Image.merge("RGBA", (blue, green, red, alpha)).tobytes()
    header = struct.pack(
        "<IIIIIII44xIIIIIIIIIIIII",
        124,
        DDSD_ONE_MIP_PITCH,
        height,
        width,
        width * 4,
        0,
        1,
        32,
        DDPF_ALPHAPIXELS_AND_RGB,
        0,
        32,
        0x00FF0000,
        0x0000FF00,
        0x000000FF,
        0xFF000000,
        DDSCAPS_TEXTURE,
        0,
        0,
        0,
        0,
    )
    path.write_bytes(DDS_MAGIC + header + pixels)


def _normalize_pillow_compressed_header(path: Path) -> None:
    data = bytearray(path.read_bytes())
    if len(data) < DDS_HEADER_SIZE or data[:4] != DDS_MAGIC:
        raise ValueError(f"Pillow did not produce a legacy DDS file: {path}")
    fourcc = bytes(data[84:88])
    if fourcc not in (b"DXT1", b"DXT5"):
        raise ValueError(f"Pillow produced unsupported DDS FourCC {fourcc!r}: {path}")
    struct.pack_into("<I", data, 8, DDSD_ONE_MIP_LINEAR)
    struct.pack_into("<I", data, 20, len(data) - DDS_HEADER_SIZE)
    struct.pack_into("<I", data, 24, 1)
    struct.pack_into("<I", data, 28, 1)
    struct.pack_into("<I", data, 88, 0)
    path.write_bytes(data)


def _write_compressed_with_pillow(
    image: Image.Image, path: Path, format_name: DdsFormat
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_image = image.convert("RGB") if format_name is DdsFormat.DXT1 else image
    save_image.save(path, format="DDS", pixel_format=format_name.value)
    _normalize_pillow_compressed_header(path)


def _write_compressed_with_texconv(
    image: Image.Image, path: Path, format_name: DdsFormat, texconv_path: Path
) -> None:
    executable = texconv_path.resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"texconv executable not found: {executable}")
    path.parent.mkdir(parents=True, exist_ok=True)
    texconv_format = "BC1_UNORM" if format_name is DdsFormat.DXT1 else "BC3_UNORM"
    with tempfile.TemporaryDirectory(prefix="civ5studio_dds_") as temp_name:
        temp = Path(temp_name)
        source = temp / f"{path.stem}.png"
        image.save(source)
        command = [
            str(executable),
            "-nologo",
            "-y",
            "-f",
            texconv_format,
            "-m",
            "1",
            "-dx9",
            "-o",
            str(temp),
            str(source),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            detail = f"{completed.stdout} {completed.stderr}".strip()
            raise RuntimeError(f"texconv failed ({completed.returncode}): {detail}")
        generated = temp / f"{source.stem}.DDS"
        if not generated.exists():
            generated = temp / f"{source.stem}.dds"
        if not generated.exists():
            raise RuntimeError("texconv completed without producing the expected DDS")
        shutil.copy2(generated, path)


def read_dds_header(path: Path) -> DdsHeader:
    data = path.read_bytes()[:DDS_HEADER_SIZE]
    if len(data) < DDS_HEADER_SIZE or data[:4] != DDS_MAGIC:
        raise ValueError(f"not a legacy DDS file: {path}")
    size, flags, height, width, pitch, depth, mipmaps = struct.unpack(
        "<7I", data[4:32]
    )
    if size != 124:
        raise ValueError(f"invalid DDS header size {size}: {path}")
    pixel_size, pixel_flags, fourcc_int, bits, red, green, blue, alpha = struct.unpack(
        "<8I", data[76:108]
    )
    if pixel_size != 32:
        raise ValueError(f"invalid DDS pixel-format size {pixel_size}: {path}")
    caps, caps2 = struct.unpack("<2I", data[108:116])
    fourcc = fourcc_int.to_bytes(4, "little").decode("ascii", errors="replace").rstrip("\0")
    if fourcc == "DX10":
        raise ValueError(f"DX10 DDS headers are not supported by Civ V: {path}")
    return DdsHeader(
        width=width,
        height=height,
        flags=flags,
        pitch_or_linear_size=pitch,
        depth=depth,
        mipmap_count=mipmaps or 1,
        pixel_flags=pixel_flags,
        fourcc=fourcc,
        bits_per_pixel=bits,
        red_mask=red,
        green_mask=green,
        blue_mask=blue,
        alpha_mask=alpha,
        caps=caps,
        caps2=caps2,
    )


def validate_dds(
    path: Path, profile: DdsProfile, expected_size: tuple[int, int]
) -> DdsHeader:
    header = read_dds_header(path)
    if (header.width, header.height) != expected_size:
        raise ValueError(
            f"DDS dimensions {header.width}x{header.height} do not match "
            f"{expected_size[0]}x{expected_size[1]}"
        )
    if header.mipmap_count != 1:
        raise ValueError(f"Civ V UI/static DDS must contain one mip surface: {path}")
    if header.caps2 != 0:
        raise ValueError(f"DDS must be a single non-cubemap surface: {path}")
    if profile.format is DdsFormat.A8R8G8B8:
        if header.fourcc:
            raise ValueError(f"A8R8G8B8 DDS must not carry FourCC {header.fourcc!r}")
        if (
            header.bits_per_pixel != 32
            or header.red_mask != 0x00FF0000
            or header.green_mask != 0x0000FF00
            or header.blue_mask != 0x000000FF
            or header.alpha_mask != 0xFF000000
        ):
            raise ValueError(f"invalid A8R8G8B8 channel masks: {header}")
        expected_bytes = header.width * header.height * 4
        if path.stat().st_size != DDS_HEADER_SIZE + expected_bytes:
            raise ValueError(f"invalid A8R8G8B8 payload size: {path}")
    else:
        if header.fourcc != profile.format.value:
            raise ValueError(
                f"DDS FourCC {header.fourcc!r} does not match {profile.format.value}"
            )
        block_bytes = 8 if profile.format is DdsFormat.DXT1 else 16
        expected_bytes = (
            ((header.width + 3) // 4) * ((header.height + 3) // 4) * block_bytes
        )
        if path.stat().st_size != DDS_HEADER_SIZE + expected_bytes:
            raise ValueError(f"invalid {profile.format.value} payload size: {path}")
        if header.pitch_or_linear_size != expected_bytes:
            raise ValueError(f"invalid DDS top-level linear size: {path}")
    return header


def write_dds(
    image: Image.Image,
    path: Path,
    profile: DdsProfile,
    *,
    texconv_path: Path | None = None,
) -> DdsWriteResult:
    """Write and immediately validate one Civ V-compatible DDS.

    Compressed profiles use Pillow's built-in legacy BCn encoder.  An explicit
    texconv path is only used as a fallback when that encoder is unavailable.
    """

    if profile.mipmaps:
        raise ValueError("the GUI art backend currently supports one-surface profiles only")
    prepared = _prepare_image(image, profile)
    encoder = "bgra"
    if profile.format is DdsFormat.A8R8G8B8:
        write_bgra_dds(prepared, path)
    else:
        encoder = "pillow-bcn"
        try:
            _write_compressed_with_pillow(prepared, path, profile.format)
        except (OSError, ValueError):
            if texconv_path is None:
                raise
            encoder = "texconv"
            _write_compressed_with_texconv(prepared, path, profile.format, texconv_path)
    header = validate_dds(path, profile, prepared.size)
    return DdsWriteResult(path=path, profile=profile.name, header=header, encoder=encoder)
