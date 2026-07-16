"""Create a deterministic Windows release ZIP and evidence manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from civ5studio.release import package_windows_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-commit", default="unknown")
    args = parser.parse_args()
    result = package_windows_release(
        args.artifact_root,
        args.zip_path,
        version=args.version,
        git_commit=args.git_commit,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
