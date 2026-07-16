from __future__ import annotations

from pathlib import Path

import pytest

from civ5studio.domain import CivProject, load_project


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = REPO_ROOT / "samples" / "kingdom_of_lithuania.civ5project.json"


@pytest.fixture
def sample_project() -> CivProject:
    return load_project(SAMPLE_PATH)
