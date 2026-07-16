"""Deterministic Windows release packaging and evidence manifests."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import uuid
import zipfile


RELEASE_MANIFEST_NAME = "RELEASE_MANIFEST.json"


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _inventory(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Release tree contains a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix.lower() in {".pyc", ".tmp"}:
            raise ValueError(f"Release tree contains a forbidden file: {relative}")
        result.append(relative)
    return tuple(sorted(result, key=lambda value: value.as_posix()))


def package_windows_release(
    artifact_root: Path,
    zip_path: Path,
    *,
    version: str,
    git_commit: str,
) -> dict[str, object]:
    root = artifact_root.resolve()
    destination = zip_path.resolve()
    if not root.is_dir():
        raise ValueError(f"Frozen application folder does not exist: {root}")
    if destination.exists():
        raise ValueError(f"Refusing to overwrite release ZIP: {destination}")
    hash_path = destination.with_suffix(destination.suffix + ".sha256.txt")
    if hash_path.exists():
        raise ValueError(f"Refusing to overwrite release hash: {hash_path}")
    manifest_path = root / RELEASE_MANIFEST_NAME
    if manifest_path.exists():
        raise ValueError(f"Refusing to overwrite release manifest: {manifest_path}")

    payload = {
        "manifest_format": "civ5studio.windows-release",
        "manifest_version": 1,
        "application_version": version,
        "git_commit": git_commit,
        "target": "Windows x64",
        "python": platform.python_version(),
        "files": {
            relative.as_posix(): _digest(root / relative)
            for relative in _inventory(root)
        },
        "validation_boundary": (
            "Packaged/import/static checks are not a Civilization V in-game test."
        ),
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4()}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative in _inventory(root):
                info = zipfile.ZipInfo(
                    f"{root.name}/{relative.as_posix()}",
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, (root / relative).read_bytes())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        manifest_path.unlink(missing_ok=True)
        raise

    zip_sha256 = _digest(destination)
    hash_path.write_text(
        f"{zip_sha256}  {destination.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "version": version,
        "artifact_root": str(root),
        "manifest": str(manifest_path),
        "zip": str(destination),
        "sha256": zip_sha256,
        "sha256_file": str(hash_path),
        "file_count": len(payload["files"]) + 1,
    }
