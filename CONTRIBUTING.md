# Contributing to Civ V Civilization Studio

Thanks for helping make Civilization V civilization modding accessible.

## Before opening a change

1. Search existing issues and pull requests.
2. Open an issue first for major workflow, file-format, or generated-mod changes.
3. Keep changes under `src/civ5studio` unless the task specifically concerns
   preserved root conversion scripts.
4. Do not submit Firaxis/2K game assets, third-party mod files, credentials,
   personal paths, generated releases, or content without redistribution
   permission.

## Development setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

Before submitting a pull request, also run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tools
.\.venv\Scripts\python.exe tools\build_bnw_reference_catalog.py --check
git diff --check
```

Static checks are not an in-game test. Report BNW and IGE runtime testing
separately and state clearly when it was not performed.

## Pull requests

- Explain the player or mod-author impact.
- List every changed file and any provenance or license considerations.
- Add or update tests for behavior changes.
- Preserve unrelated work and portable project compatibility.
- Never include signing secrets. Public releases are built by GitHub Actions
  from reviewed source and signed only by an approved signing service.

By contributing, you agree that your contribution is licensed under the MIT
License in this repository. Third-party material retains its own license.
