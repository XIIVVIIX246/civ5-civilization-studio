# Windows release checklist

Use this checklist when publishing the Civilization Studio desktop app. It is
separate from the per-project BNW checklist generated inside each Civ V mod.

## 1. Confirm source and version

- Work from the intended commit and inspect all modified and untracked files.
- Confirm `pyproject.toml` and `src/civ5studio/__init__.py` expose the same app
  version.
- Confirm the bundled BNW catalog provenance and hashes reflect the intended
  local Expansion2 source set.
- Do not include local projects, game caches, logs, generated mods, or previous
  release artifacts in the source commit.
- Confirm `LICENSE`, `THIRD_PARTY_NOTICES.md`, `docs/PUBLIC_RELEASE.md`,
  `docs/SOURCE_PROVENANCE.md`, and the complete `licenses` directory are
  present and current.
- Confirm Promotions - Expansion Pack is described as Bloublou's separate
  Steam Workshop mod and that none of its mod files or art are packaged.

```powershell
git status --short --untracked-files=all
git rev-parse HEAD
```

## 2. Create the test environment

Python 3.12 is the CI and recommended release version. Python 3.11 or newer is
supported by the package metadata.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 3. Run static and integration checks

```powershell
.\.venv\Scripts\python.exe -m compileall -q src tools
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\build_bnw_reference_catalog.py --check
git diff --check
```

`build_bnw_reference_catalog.py --check` uses the configured local Civ V game
root. A machine without the authoritative Expansion2 XML cannot satisfy that
provenance check and must not regenerate the catalog from guessed data.

When a portable complete project and a read-only `Civ5DebugDatabase.db` snapshot
are available, run the optional live-schema comparison against an in-memory
clone:

```powershell
.\.venv\Scripts\python.exe tools\validate_against_bnw_database.py `
  "C:\Path\Project.civ5project.json" `
  "C:\Path\Civ5DebugDatabase.db"
```

The validator opens the supplied database as read-only evidence and executes
generated gameplay SQL only in memory. Record the database SHA-256 with the
result:

```powershell
Get-FileHash "C:\Path\Civ5DebugDatabase.db" -Algorithm SHA256
```

## 4. Build the Windows artifact

The build script runs the test suite unless `-SkipTests` is supplied. For a
normal release, commit the intended source so the worktree is clean, then let
it run the tests again. The script refuses to label a dirty tree with an
incomplete Git identity:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_windows.ps1 `
  -PythonPath .\.venv\Scripts\python.exe
```

The script:

1. freezes a windowed x64 application with bundled package data;
2. launches hidden version and complete-UI construction smoke probes;
3. writes `RELEASE_MANIFEST.json` into the frozen folder;
4. creates a deterministic ZIP without overwriting an older artifact;
5. writes a `.zip.sha256.txt` sidecar for the ZIP; and
6. embeds the application license, third-party licenses, public-release notes,
   and source provenance;
7. rejects local-identity leaks and bundled Promotions Expansion Pack files;
   and
8. publishes a separately named `public` folder and ZIP beneath `release`.

Retain the PowerShell result object; it reports the exact executable, manifest,
ZIP, digest, and sidecar paths.

## 5. Build and identify the Windows installer

Install Inno Setup 6 on the release machine. The installer builder accepts only
a project-owned frozen folder whose `RELEASE_MANIFEST.json` commit matches the
current clean worktree, and it refuses to overwrite an existing installer or
hash sidecar:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_installer.ps1 `
  -FrozenFolder "release\<frozen-folder>"
```

That command creates a per-user Setup executable and reports
`UNSIGNED_NO_CERTIFICATE`. An unsigned installer is testable but is not a
trusted-publisher release and can trigger a Windows reputation warning.

For an Authenticode release, make the signing certificate available in the
current user's certificate store and supply its SHA-1 thumbprint. The SHA-1
value identifies the certificate; the file digest and timestamp algorithms
remain SHA-256:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_installer.ps1 `
  -FrozenFolder "release\<frozen-folder>" `
  -SigningCertificateSha1 "<certificate-thumbprint>"
```

The script locates `signtool.exe` or accepts `-SignToolPath`, applies a
timestamp through `-TimestampUrl`, verifies the resulting signature, and must
report `SIGNED_AND_VERIFIED`. It writes an installer `.sha256.txt` sidecar in
either signing mode. The CI packaging job follows the same path; its optional
`WINDOWS_SIGNING_PFX_BASE64` and `WINDOWS_SIGNING_PFX_PASSWORD` secrets enable
signing without making the certificate part of the repository.

## 6. Verify the published packages

```powershell
Get-FileHash "release\<artifact>.zip" -Algorithm SHA256
Get-Content "release\<artifact>.zip.sha256.txt"
Get-FileHash "release\Civ5-Civilization-Studio-<version>-Setup.exe" -Algorithm SHA256
Get-Content "release\Civ5-Civilization-Studio-<version>-Setup.exe.sha256.txt"
Get-AuthenticodeSignature "release\Civ5-Civilization-Studio-<version>-Setup.exe"
```

- Confirm both computed digests match their sidecars.
- Run `tools/verify_public_release.py` against the final ZIP and require PASS.
- Scan the final ZIP with current local antimalware tooling and retain the
  result. Do not upload private test projects or logs to public scanners.
- For a signed release, require an Authenticode `Status` of `Valid` and retain
  the signer and timestamp evidence. For an intentionally unsigned test build,
  record that fact explicitly.
- Inspect `RELEASE_MANIFEST.json` for the expected version and commit.
- Extract the ZIP to a new path; do not test in the PyInstaller staging tree.
- Launch the extracted executable and confirm the six guided pages and three
  optional pages render without missing styles, text corruption, or a visible
  console window.
- Confirm Guided is the default, the Preview and Problems docks start closed,
  and Continue advances through Start Here, Your Civilization, Your Leader,
  Abilities & Uniques, Artwork, and Check, Build & Play without detouring into
  optional pages.
- Verify the worked example fills understandable names, a compiled ability,
  cities, spies, leader personality, and two named uniques. Verify each of the
  four Choose playstyle entries creates a pre-change snapshot.
- Confirm Expert controls reveal donor IDs and the three optional pages,
  `Ctrl+K` finds pages/fields/actions, `Alt+1` through `Alt+6` navigate Guided,
  `Alt+1` through `Alt+9` navigate Expert, and text scaling does not clip the
  header, forms, or build card.
- Trigger known validation errors and confirm step badges and the Problems dock
  agree; activate each finding and confirm the owning page/field receives
  focus. Confirm the live civilization preview follows names, colors, uniques,
  and source-art changes without modifying any PNG.
- Exercise Abilities & Uniques donor search/cards/inspector, Extra Gameplay
  Effects card/list filters and two-effect comparison, and Artwork
  mouse/keyboard transforms. Confirm the serialized project round-trips
  unchanged through Guided and Expert controls.
- Exercise undo, redo, manual snapshots, full restore, and one-section restore.
  Reopen the marked workspace and verify named snapshots load from the fixed
  digest-verified history document. Corrupt a disposable copy and confirm the
  app leaves it untouched, reports session-only history, and never claims that
  an in-memory snapshot was persisted.
- In Expert mode rename a unique's stable key twice. Confirm its hidden
  mechanics, PEP assignments, existing art asset IDs, crop mode, and focal
  coordinates survive both edits and a save/reopen cycle.
- In Guided, run **Check and create my mod** and confirm a successful current
  build enables installation. In Expert controls, also run Check my progress
  and Run final safety check and confirm the detailed pipeline retains the
  distinct stage results. Confirm an explicit Save clears obsolete
  build/install readiness.
- Run the Setup executable and verify the per-user Start menu entry, optional
  desktop shortcut, JSON **Open with** registration, and uninstaller. Confirm
  that the system JSON default was not replaced.
- Create, save, close, reopen, and recover a disposable workspace.
- Exercise the existing-mod snapshot importer against a disposable source and
  confirm the source remains byte-for-byte unchanged.
- Use **Save As** on that imported workspace and confirm every
  `ImportedMod/Source` file and SHA-256 is retained, then tamper with one source
  snapshot file and confirm another Save As is refused.
- Confirm an imported workspace receives a draft warning and that strict
  validation/build is blocked because snapshot source is inspection evidence,
  not generated-mod input.
- Exercise a unique improvement, localization, custom unit-art package, and
  audio pair in a disposable project; confirm their static validators and
  generated inventories run in the frozen app.
- Run the game-log assistant and compatibility scanner against disposable or
  read-only test trees and confirm neither mutates its selected source.
- Run a strict build of a complete known project and verify the generated ZIP.
- Confirm a project edit disables installation until another strict build.
- Confirm the Expert pipeline labels Check my progress, Run final safety check,
  Check and create my mod, Install into Civilization V, Open Civilization V,
  and Check Civ V logs for problems independently. Cancel the launch
  confirmation once; in a safe environment accept it once and confirm a Steam
  handoff is `REQUESTED`, never `PASS`. Only an explicit user-entered manual
  result may show runtime PASS.
- Exercise install and replacement-backup behavior against a disposable fake
  `MODS` directory before using a real game directory.

## 7. Manual BNW/IGE release gate

Use the exact generated mod from the packaged app, not a development build.
Install it into Civ V, start a BNW game, inspect its UI and mechanics, review
the Civ V logs, and repeat with IGE enabled. Record the app ZIP SHA-256, project
file hash, generated-output build ID, mod ZIP hash, game version, and test
result together.

Include custom improvements, 3D unit animations, diplomacy/localization, and
audio playback in the run when configured. Automated tests, log analysis,
compatibility scanning, the live database validator, and a successful
frozen-app probe remain static evidence. They do not replace this BNW and IGE
runtime gate.

## 8. Final handoff

- Report the exact commit, app version, portable ZIP and Setup paths, and both
  SHA-256 values.
- Report installer signing status, signer/timestamp evidence when signed, or
  explicitly state that the installer is unsigned.
- Report the full test count and any skipped or unavailable checks.
- State explicitly whether the BNW and IGE in-game test passed or was not run.
- Re-run `git status --short --untracked-files=all` and explain every remaining
  modified or untracked path.
