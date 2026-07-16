from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from civ5studio.main import main


def test_package_imports() -> None:
    import civ5studio

    assert civ5studio.__version__ == "0.4.1"


def test_version_probe_does_not_initialize_qt(capsys) -> None:
    assert main(["civ5-civilization-studio", "--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.4.1"


def test_frozen_windowed_version_probe_tolerates_missing_stdout(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    assert main(["civ5-civilization-studio", "--version"]) == 0


def test_application_smoke_probe_constructs_complete_ui() -> None:
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-m", "civ5studio", "--smoke-test"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
