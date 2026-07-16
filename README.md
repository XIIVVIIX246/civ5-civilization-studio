# Civ V Civilization Studio

[![CI](https://github.com/XIIVVIIX246/civ5-civilization-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/XIIVVIIX246/civ5-civilization-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Public repository: <https://github.com/XIIVVIIX246/civ5-civilization-studio>

Civ V Civilization Studio is a guided Windows desktop application for creating
custom civilizations for *Sid Meier's Civilization V: Brave New World*. It
keeps the editable project, imported source art, generated SQL/XML/Lua, Civ V
DDS art, validation evidence, and clean player ZIP in one reproducible workflow.
Users do not need to edit JSON, SQL, XML, Lua, or DDS files by hand.

The original PNG-to-DDS converter scripts remain at the repository root for
provenance. The current application lives under `src/civ5studio`.

This is an unofficial fan-made tool and is not affiliated with, endorsed by,
or supported by Firaxis Games, 2K, Take-Two Interactive, Aspyr, or Valve.
Sid Meier's Civilization and related marks belong to their respective owners.

## Launch the app

For an installed Windows release, run
`Civ5-Civilization-Studio-<version>-Setup.exe`. The per-user installer does not
require administrator privileges, adds a Start menu shortcut and uninstaller,
and offers an optional desktop shortcut. It registers the app as an **Open
with** choice for JSON without taking over the system JSON default.

For a portable Windows release, extract the entire ZIP and double-click the
`Civ5-Civilization-Studio-<version>-windows-x64.exe` inside the extracted
folder. Keep the executable and its adjacent `_internal` folder together.

To run from this repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m civ5studio
```

An existing project can also be opened at launch:

```powershell
.\.venv\Scripts\python.exe -m civ5studio "C:\Path\My Civilization.civ5project.json"
```

See [USER_GUIDE.md](docs/USER_GUIDE.md) for the complete walkthrough.

The desktop shell opens in **Guided (recommended)** mode. A welcoming Start
Here page, worked example, plain-language explanations, six-step Continue
sequence, click-to-fix validation, and one **Check and create my mod** action
keep a first project understandable. Live BNW-style previews and detailed
problem panels remain available without taking over the form. Expert controls,
`Ctrl+K` command search, undo/redo, named snapshots, and the detailed validation
pipeline remain available without changing the portable project model.

## Six-page guided workflow

1. **Start Here** - name the mod, enter the creator, or load the worked example.
2. **Your Civilization** - enter player-facing names, colors, cities, spies,
   introduction text, and history.
3. **Your Leader** - enter the leader's name and choose a readable AI play-style
   preset; detailed BNW priorities remain available in Expert controls.
4. **Abilities & Uniques** - choose one compiler-supported civilization bonus,
   then rename and describe the normal BNW units, buildings, or improvements
   that become the civilization's unique items.
5. **Artwork** - add PNG sources, adjust non-destructive crops, and inspect the
   safe-zone diagnostics and preview-only Firaxis frames.
6. **Check, Build & Play** - fix clearly described problems, create a validated
   mod, install the current build, and follow the real in-game test checklist.

Promotions Expansion Pack v9, up to two of the 200 curated Extra Gameplay
Effects, and Advanced Tools are available under **Optional extras**. They do not
interrupt the beginner Continue sequence. Expert controls expose the raw BNW
identifiers and separate audit, validation, build, install, launch-request, and
log-analysis evidence needed by experienced authors.

**Promotions - Expansion Pack was separately created by Bloublou and is not
bundled with Civilization Studio.** Users who enable the integration must
obtain the mod separately from its
[Steam Workshop page](https://steamcommunity.com/sharedfiles/filedetails/?id=84863495).

Original Civilization Studio code is licensed under the [MIT License](LICENSE).
Bundled runtime components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

First save creates a self-contained workspace. Imported PNGs are copied into
it, manual saves are atomic and retain backups, edits trigger continuous draft
validation, and saved workspaces receive crash-recovery autosaves.

An existing-mod snapshot is evidence, not a conversion or build input. Its
arbitrary SQL, XML, Lua, DLL, and art are preserved byte-for-byte but excluded
from generated mods, and any project containing that snapshot is blocked from
strict release.

See [LUA_EFFECT_LIBRARY.md](docs/LUA_EFFECT_LIBRARY.md) for the catalog,
generation, compatibility, and required runtime-test contracts.

## Developer verification and Windows release

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\build_bnw_reference_catalog.py --check
powershell -ExecutionPolicy Bypass -File .\tools\build_windows.ps1
```

The release script runs tests by default, freezes the Windows app, probes its
version and complete Qt UI construction, then writes a versioned folder,
deterministic ZIP, release manifest, and SHA-256 sidecar under `release`.
Maintainers should follow
[RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

Without a certificate, the portable builder labels its output
`public-candidate-unsigned` and records that state inside `SIGNING_STATUS.txt`.
A trusted public build requires a code-signing certificate thumbprint:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_windows.ps1 `
  -SigningCertificateSha1 "<certificate-thumbprint>"
```

An installer release additionally requires Inno Setup 6 and a clean worktree:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_installer.ps1
```

Without `-SigningCertificateSha1`, the installer is deliberately reported as
`UNSIGNED_NO_CERTIFICATE`. Supplying a real certificate thumbprint makes the
script timestamp, Authenticode-sign, and verify the installer before reporting
`SIGNED_AND_VERIFIED`. In both cases it writes a SHA-256 sidecar; users should
expect Windows reputation warnings for an unsigned build.

## Validation boundary

Passing project, BNW-schema, SQL, XML, DDS, package-inventory, and hash checks is
static evidence only. It does **not** prove that Civilization V loaded the mod,
that gameplay behaved as intended, or that IGE remained compatible. Runtime
release evidence requires launching BNW with the exact generated build,
starting a game, checking the affected screens and mechanics, reviewing Civ V
logs, and repeating the smoke test with IGE enabled.
