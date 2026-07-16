"""Conservative installation into a Civilization V MODS directory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import shutil
import uuid
from typing import Callable

from civ5studio.build.service import OUTPUT_MARKER, verify_generated_output
from civ5studio.locking import FileMutationLock, MutationBusyError


WINDOWS_INSTALL_PATH_LIMIT = 240


class InstallInProgress(RuntimeError):
    """Raised when another process or thread owns the MODS mutation lock."""


@dataclass(frozen=True, slots=True)
class InstallResult:
    destination: Path
    backup_path: Path | None


def default_civ5_mods_path() -> Path:
    return (
        Path.home()
        / "Documents"
        / "My Games"
        / "Sid Meier's Civilization 5"
        / "MODS"
    )


class InstallService:
    def install(
        self,
        build_root: str | Path,
        mods_root: str | Path,
        *,
        progress: Callable[[int, str], None] = lambda _percent, _message="": None,
        log: Callable[[str], None] = lambda _message: None,
    ) -> InstallResult:
        source = Path(build_root).resolve()
        mods = Path(mods_root).resolve()
        marker = verify_generated_output(source, require_strict_release=True)
        if len(list(source.glob("*.modinfo"))) != 1:
            raise ValueError("Install source must contain exactly one .modinfo file.")

        destination = mods / source.name
        _ensure_within(mods, destination)
        temporary = mods / f".civ5studio-install-{uuid.uuid4()}"
        _ensure_within(mods, temporary)
        lock_path = mods / ".civ5studio-install.lock"
        inventory = tuple(str(relative) for relative in marker["inventory"])
        _validate_windows_install_paths(
            (destination, temporary),
            inventory,
            extra_paths=(lock_path,),
        )

        # The MODS root and lock are created only after all predictable copy
        # destinations have passed the conservative Windows path preflight.
        mods.mkdir(parents=True, exist_ok=True)
        try:
            with FileMutationLock(lock_path, label="Civilization Studio install"):
                return self._install_locked(
                    source,
                    mods,
                    destination,
                    temporary,
                    inventory,
                    progress=progress,
                    log=log,
                )
        except MutationBusyError as exc:
            raise InstallInProgress(str(exc)) from exc

    def _install_locked(
        self,
        source: Path,
        mods: Path,
        destination: Path,
        temporary: Path,
        inventory: tuple[str, ...],
        *,
        progress: Callable[[int, str], None],
        log: Callable[[str], None],
    ) -> InstallResult:
        backup: Path | None = None
        if destination.exists():
            backup_root = (
                mods.parent
                / "Civ5Studio Mod Backups"
                / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            )
            backup = backup_root / destination.name
            _validate_windows_install_paths((backup,), inventory)

        temporary_created = False
        try:
            temporary.mkdir(exist_ok=False)
            temporary_created = True
            progress(10, "Copying validated mod")
            shutil.copytree(source, temporary, dirs_exist_ok=True)
            progress(60, "Reverifying copied mod")
            verify_generated_output(temporary, require_strict_release=True)
            if backup is not None:
                backup_root = backup.parent
                backup_root.mkdir(parents=True, exist_ok=False)
                os.replace(destination, backup)
                log(f"Retained previous install at {backup}")
            progress(80, "Publishing mod to MODS")
            os.replace(temporary, destination)
            temporary_created = False
        except Exception:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            if temporary_created and temporary.exists():
                shutil.rmtree(temporary)
            raise
        progress(100, "Install complete")
        log(f"Installed mod at {destination}")
        return InstallResult(destination, backup)


def _ensure_within(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Install path escapes MODS root: {candidate}") from exc


def _validate_windows_install_paths(
    roots: tuple[Path, ...],
    inventory: tuple[str, ...],
    *,
    extra_paths: tuple[Path, ...] = (),
) -> None:
    candidates = [
        *roots,
        *(root / relative for root in roots for relative in inventory),
        *(root / OUTPUT_MARKER for root in roots),
        *extra_paths,
    ]
    longest = max(candidates, key=lambda value: len(str(value)))
    length = len(str(longest))
    if length > WINDOWS_INSTALL_PATH_LIMIT:
        raise ValueError(
            "Install Windows path exceeds the conservative Civ V/MAX_PATH "
            f"limit ({length} > {WINDOWS_INSTALL_PATH_LIMIT}): {longest}. "
            "Choose a shorter MODS folder or mod name."
        )
