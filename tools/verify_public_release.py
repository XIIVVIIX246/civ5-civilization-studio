"""Fail closed when a Windows public ZIP lacks notices or leaks local identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import zipfile


REQUIRED_SUFFIXES = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "PUBLIC_RELEASE.md",
    "SOURCE_PROVENANCE.md",
    "SIGNING_STATUS.txt",
    "licenses/LGPL-3.0.txt",
    "licenses/GPL-3.0.txt",
    "licenses/Python-3.12.txt",
    "licenses/Apache-2.0.txt",
    "licenses/Pillow.txt",
    "licenses/PyInstaller.txt",
}
FORBIDDEN_NAMES = ("Promotions - Expansion Pack (v 9).modinfo", "PEP - INIT.xml")
SENSITIVE = (
    re.compile(r"C:[\\/]Users[\\/]nated", re.IGNORECASE),
    re.compile(r"johnisahoe246@gmail\.com", re.IGNORECASE),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY", re.IGNORECASE),
)
TEXT_SUFFIXES = {".json", ".txt", ".md", ".xml", ".sql", ".lua", ".ini", ".toml"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.zip_path) as archive:
        names = archive.namelist()
        normalized = {name.replace("\\", "/") for name in names}
        missing = sorted(
            suffix for suffix in REQUIRED_SUFFIXES
            if not any(name.endswith(suffix) for name in normalized)
        )
        if missing:
            raise SystemExit(f"Missing public-release files: {missing}")
        bundled_mod = sorted(
            name for name in normalized
            if any(name.endswith(forbidden) for forbidden in FORBIDDEN_NAMES)
        )
        if bundled_mod:
            raise SystemExit(f"Separate Promotions Expansion Pack files were bundled: {bundled_mod}")
        leaks: list[str] = []
        for name in names:
            if Path(name).suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = archive.read(name).decode("utf-8", errors="ignore")
            if any(pattern.search(text) for pattern in SENSITIVE):
                leaks.append(name)
        if leaks:
            raise SystemExit(f"Sensitive local identity found in: {sorted(leaks)}")
    print(json.dumps({"status": "PASS", "zip": str(args.zip_path), "entries": len(names)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
