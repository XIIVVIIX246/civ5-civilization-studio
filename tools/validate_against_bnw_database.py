"""Validate generated gameplay SQL in a read-only clone of a BNW cache DB."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from civ5studio.domain import load_project
from civ5studio.generation import (
    CompilationError,
    compile_project,
    validate_compiled_sql_against_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="Portable .civ5project.json file")
    parser.add_argument("database", type=Path, help="Civ5DebugDatabase.db snapshot")
    args = parser.parse_args()

    project = load_project(args.project)
    try:
        compilation = compile_project(project)
    except CompilationError as exc:
        report = exc.report
    else:
        report = validate_compiled_sql_against_database(
            compilation, project, args.database
        )
    payload = {
        "status": "PASS" if report.is_valid else "FAIL",
        "project": str(args.project.resolve()),
        "database": str(args.database.resolve()),
        "issues": [
            {
                "severity": item.severity.value,
                "code": item.code,
                "path": item.path,
                "message": item.message,
                "hint": item.hint,
            }
            for item in report.issues
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
