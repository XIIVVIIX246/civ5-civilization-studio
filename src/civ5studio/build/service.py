"""Safe project-owned staging, validation, publication, and ZIP packaging."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
from typing import Mapping
import uuid
import zipfile

from civ5studio.bnw import ReferenceCatalog
from civ5studio.locking import FileMutationLock, MutationBusyError
from civ5studio.domain.models import CivProject
from civ5studio.domain.validation import ValidationReport, is_portable_relative_path, validate_project
from civ5studio.generation.compiler import (
    Compilation,
    CompilationError,
    RenderedArtifact,
    compile_project,
    generate_art_manifest,
    generate_validation_report,
    project_folder_name,
)
from civ5studio.generation.sqlite_validation import validate_compilation_tree


WORKSPACE_MARKER = "workspace.json"
OUTPUT_MARKER = ".civ5studio-generated.json"


class BuildMode(str, Enum):
    AVAILABLE = "available"
    STRICT_RELEASE = "strict_release"


class UnsafeBuildPath(RuntimeError):
    pass


class BuildInProgress(UnsafeBuildPath):
    pass


class GeneratedOutputIntegrityError(ValueError):
    """A generated folder no longer matches its validation marker."""


class BuildBlocked(RuntimeError):
    def __init__(self, report: ValidationReport, staging_path: Path | None = None):
        self.report = report
        self.staging_path = staging_path
        detail = "; ".join(f"{item.path}: {item.message}" for item in report.errors[:4])
        super().__init__(f"Build blocked: {detail}")


@dataclass(frozen=True, slots=True)
class BuildResult:
    mode: BuildMode
    build_id: str
    published_path: Path
    package_path: Path | None
    backup_path: Path | None
    inventory: tuple[str, ...]
    report: ValidationReport
    compilation: Compilation


class BuildService:
    def __init__(self, catalog: ReferenceCatalog | None = None):
        self.catalog = catalog or ReferenceCatalog.bundled()

    def audit(
        self, project: CivProject, project_root: str | Path | None = None
    ) -> ValidationReport:
        return validate_project(
            project, self.catalog, strict_release=False, project_root=project_root
        )

    def validate(
        self,
        project: CivProject,
        project_root: str | Path | None = None,
        *,
        strict_release: bool = True,
    ) -> ValidationReport:
        return validate_project(
            project,
            self.catalog,
            strict_release=strict_release,
            project_root=project_root,
        )

    def build(
        self,
        project: CivProject,
        project_root: str | Path,
        *,
        source_root: str | Path | None = None,
        mode: BuildMode = BuildMode.AVAILABLE,
        rendered_art_root: str | Path | None = None,
        create_zip: bool = True,
    ) -> BuildResult:
        root = Path(project_root).resolve()
        folder = project_folder_name(project)
        _validate_windows_paths(root / "generated" / folder, ())
        root.mkdir(parents=True, exist_ok=True)
        try:
            # Lock outside the control directory so two first-time builders
            # cannot race while claiming/marking the workspace itself.
            with FileMutationLock(
                root / ".civ5studio-build.lock", label="project build"
            ):
                self._ensure_workspace(root, project)
                return self._build_unlocked(
                    project,
                    root,
                    source_root=source_root,
                    mode=mode,
                    rendered_art_root=rendered_art_root,
                    create_zip=create_zip,
                )
        except MutationBusyError as exc:
            raise BuildInProgress(str(exc)) from exc

    def _build_unlocked(
        self,
        project: CivProject,
        project_root: str | Path,
        *,
        source_root: str | Path | None = None,
        mode: BuildMode = BuildMode.AVAILABLE,
        rendered_art_root: str | Path | None = None,
        create_zip: bool = True,
    ) -> BuildResult:
        """Build and publish inside a project-owned workspace.

        Rebuilds never recursively delete a destination. An existing generated
        folder is accepted only when its marker matches this project, then it is
        atomically renamed into the retained backup area before publication.
        """

        root = Path(project_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        project_source_root = (
            Path(source_root).resolve() if source_root is not None else root
        )
        if not project_source_root.is_dir():
            raise UnsafeBuildPath(
                f"Project source root is not a directory: {project_source_root}"
            )
        control = self._ensure_workspace(root, project)
        build_id = str(uuid.uuid4())
        disk_token = build_id.replace("-", "")[:12]
        folder = project_folder_name(project)
        # Keep internal mutation paths short enough for legacy Windows/Civ V
        # tooling while retaining the full UUID in the integrity marker.
        staging_parent = control / "s" / disk_token
        stage = staging_parent / folder
        _ensure_within(root, stage)

        rendered_root = Path(rendered_art_root).resolve() if rendered_art_root else None
        rendered_artifacts = self._available_art(project, rendered_root)
        available_art = tuple(item.path for item in rendered_artifacts)
        strict = mode is BuildMode.STRICT_RELEASE
        try:
            compilation = compile_project(
                project,
                self.catalog,
                strict_release=strict,
                project_root=str(project_source_root),
                available_art_files=available_art,
                rendered_artifacts=rendered_artifacts,
            )
        except CompilationError as exc:
            raise BuildBlocked(exc.report, stage) from exc

        expected_inventory = tuple(
            sorted(
                [
                    *compilation.files.keys(),
                    *compilation.source_files.keys(),
                    *compilation.available_art_files,
                ]
            )
        )
        path_inventory = (*expected_inventory, OUTPUT_MARKER)
        target = root / "generated" / folder
        backup_target = control / "b" / disk_token / folder
        _validate_windows_paths(stage, path_inventory)
        _validate_windows_paths(target, path_inventory)
        _validate_windows_paths(backup_target, path_inventory)
        package = (
            control
            / "packages"
            / f"{folder}-v{project.mod_version}-{disk_token}.zip"
        )
        if create_zip:
            _validate_windows_paths(package, ())

        # No generated payload is written until every predictable Windows
        # staging, publication, backup, and package path passes preflight.
        stage.mkdir(parents=True, exist_ok=False)
        _write_compilation(stage, compilation)
        self._copy_source_files(project_source_root, stage, compilation.source_files)
        if rendered_root is not None:
            self._copy_rendered_art(rendered_root, stage, compilation.available_art_files)

        post = validate_compilation_tree(stage, compilation, project, self.catalog)
        combined = ValidationReport(list(compilation.report.issues))
        combined.extend(post.issues)
        combined = combined.sorted()
        report_path = stage / "Documentation" / "VALIDATION_REPORT.md"
        report_text = generate_validation_report(project, combined)
        report_path.write_text(report_text, encoding="utf-8", newline="\n")
        if post.errors:
            raise BuildBlocked(combined, stage)
        updated_files = dict(compilation.files)
        updated_files["Documentation/VALIDATION_REPORT.md"] = report_text
        compilation = replace(compilation, files=updated_files, report=combined)

        player_inventory = _player_inventory(stage)
        if player_inventory != expected_inventory:
            raise UnsafeBuildPath(
                "Generated file inventory does not match the compiler output contract."
            )
        inventory_sha256 = {
            relative: _sha256_file(stage / relative) for relative in player_inventory
        }
        marker = {
            "marker_format": "civ5studio.generated-output",
            "marker_version": 2,
            "project_id": project.project_id,
            "mod_id": project.mod_id,
            "build_id": build_id,
            "mode": mode.value,
            "inventory": list(player_inventory),
            "sha256": inventory_sha256,
        }
        _atomic_json(stage / OUTPUT_MARKER, marker)

        publish_parent = root / "generated"
        _ensure_within(root, target)
        publish_parent.mkdir(parents=True, exist_ok=True)
        backup = self._publish(stage, target, control, project, disk_token)
        _remove_empty(staging_parent)

        published_package = None
        if create_zip:
            package_dir = control / "packages"
            package_dir.mkdir(parents=True, exist_ok=True)
            package_clean(target, package)
            published_package = package
        return BuildResult(
            mode=mode,
            build_id=build_id,
            published_path=target,
            package_path=published_package,
            backup_path=backup,
            inventory=player_inventory,
            report=combined,
            compilation=compilation,
        )

    def _ensure_workspace(self, root: Path, project: CivProject) -> Path:
        control = root / ".civ5studio"
        marker_path = control / WORKSPACE_MARKER
        if control.exists() and not control.is_dir():
            raise UnsafeBuildPath(f"Workspace control path is not a directory: {control}")
        if control.exists() and not marker_path.is_file():
            raise UnsafeBuildPath(
                f"Refusing to claim existing unmarked control directory: {control}"
            )
        if marker_path.is_file():
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise UnsafeBuildPath(f"Invalid workspace marker: {marker_path}") from exc
            if marker.get("project_id") != project.project_id:
                raise UnsafeBuildPath(
                    "Workspace belongs to a different Civilization Studio project."
                )
        else:
            control.mkdir(parents=True, exist_ok=False)
            _atomic_json(
                marker_path,
                {
                    "marker_format": "civ5studio.workspace",
                    "marker_version": 1,
                    "project_id": project.project_id,
                },
            )
        return control

    def _available_art(
        self, project: CivProject, rendered_root: Path | None
    ) -> tuple[RenderedArtifact, ...]:
        if rendered_root is None:
            return ()
        if not rendered_root.is_dir():
            raise UnsafeBuildPath(f"Rendered art root is not a directory: {rendered_root}")
        manifest = generate_art_manifest(project)
        expected = [str(item["path"]) for item in manifest["outputs"]]
        result: list[RenderedArtifact] = []
        for relative in expected:
            source = (rendered_root / relative).resolve()
            _ensure_within(rendered_root, source)
            if source.is_file():
                result.append(inspect_dds_artifact(source, relative))
        return tuple(result)

    def _copy_rendered_art(
        self, source_root: Path, stage: Path, paths: tuple[str, ...]
    ) -> None:
        for relative in paths:
            source = (source_root / relative).resolve()
            target = stage / relative
            _ensure_within(source_root, source)
            _ensure_within(stage, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _copy_source_files(
        self, source_root: Path, stage: Path, files: Mapping[str, str]
    ) -> None:
        """Copy only compiler-declared project-owned binary/VFS sources."""

        for output_relative, source_relative in sorted(files.items()):
            source = (source_root / source_relative).resolve(strict=False)
            target = (stage / output_relative).resolve(strict=False)
            _ensure_within(source_root, source)
            _ensure_within(stage, target)
            if not source.is_file() or source.is_symlink():
                raise UnsafeBuildPath(
                    f"Declared project source is missing or linked: {source_relative}"
                )
            if target.exists() or target.is_symlink():
                raise UnsafeBuildPath(
                    f"Declared source output collides with generated content: {output_relative}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if _sha256_file(source) != _sha256_file(target):
                raise UnsafeBuildPath(
                    f"Copied source hash mismatch: {output_relative}"
                )

    def _publish(
        self,
        stage: Path,
        target: Path,
        control: Path,
        project: CivProject,
        disk_token: str,
    ) -> Path | None:
        backup = None
        if target.exists():
            marker_path = target / OUTPUT_MARKER
            if not marker_path.is_file():
                raise UnsafeBuildPath(
                    f"Refusing to replace unmarked destination directory: {target}"
                )
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise UnsafeBuildPath(f"Invalid generated-output marker: {marker_path}") from exc
            if marker.get("project_id") != project.project_id:
                raise UnsafeBuildPath(
                    f"Refusing to replace output owned by another project: {target}"
                )
            backup = control / "b" / disk_token / target.name
            _ensure_within(control, backup)
            backup.parent.mkdir(parents=True, exist_ok=False)
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        return backup


def package_clean(mod_root: str | Path, zip_path: str | Path) -> Path:
    """Write a deterministic player ZIP and refuse to overwrite any file."""

    unresolved_root = Path(mod_root).expanduser()
    unresolved_destination = Path(zip_path).expanduser()
    if _path_contains_link_or_reparse(unresolved_root):
        raise UnsafeBuildPath(
            f"Generated mod root cannot be a link or junction: {unresolved_root}"
        )
    if _path_contains_link_or_reparse(unresolved_destination):
        raise UnsafeBuildPath(
            f"Package destination cannot be a link or junction: {unresolved_destination}"
        )
    root = unresolved_root.resolve()
    destination = unresolved_destination.resolve()
    if not root.is_dir():
        raise UnsafeBuildPath(f"Generated mod root does not exist: {root}")
    if destination.exists():
        raise UnsafeBuildPath(f"Refusing to overwrite package: {destination}")
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise UnsafeBuildPath("Package destination must be outside the generated mod root.")

    package_files = _package_files(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4()}.tmp")
    try:
        with zipfile.ZipFile(
            temporary, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path in package_files:
                relative = path.relative_to(root).as_posix()
                if relative == OUTPUT_MARKER or "__pycache__" in path.parts:
                    continue
                if path.suffix.lower() in {".pyc", ".tmp"}:
                    continue
                if _is_link_or_reparse(path):
                    raise UnsafeBuildPath(
                        f"Generated mod contains a link or junction: {path}"
                    )
                _ensure_within(root, path)
                if not path.is_file():
                    raise UnsafeBuildPath(
                        f"Generated mod entry changed before packaging: {path}"
                    )
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def _package_files(root: Path) -> tuple[Path, ...]:
    """Inventory regular package files without traversing links or junctions."""

    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        if _is_link_or_reparse(directory):
            raise UnsafeBuildPath(
                f"Generated mod contains a link or junction: {directory}"
            )
        _ensure_within(root, directory)
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise UnsafeBuildPath(
                f"Generated mod directory cannot be inspected: {directory}"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            if _is_link_or_reparse(path):
                raise UnsafeBuildPath(
                    f"Generated mod contains a link or junction: {path}"
                )
            _ensure_within(root, path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(path)
            except OSError as exc:
                raise UnsafeBuildPath(
                    f"Generated mod entry cannot be inspected: {path}"
                ) from exc
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def zip_inventory(path: str | Path) -> tuple[str, ...]:
    with zipfile.ZipFile(path, "r") as archive:
        return tuple(sorted(item.filename for item in archive.infolist() if not item.is_dir()))


def verify_generated_output(
    path: str | Path, *, require_strict_release: bool = False
) -> dict[str, object]:
    """Verify a generated folder's exact file inventory and SHA-256 hashes.

    The marker itself is control metadata and is intentionally excluded from
    the player inventory. Every other file must be listed exactly once and
    match the digest recorded when the build passed validation.
    """

    root = Path(path).resolve()
    marker_path = root / OUTPUT_MARKER
    if not root.is_dir() or not marker_path.is_file():
        raise GeneratedOutputIntegrityError(
            "Install source is not a validated Civilization Studio build."
        )
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeneratedOutputIntegrityError(
            "Install source has an invalid generated-output marker."
        ) from exc
    if not isinstance(marker, dict):
        raise GeneratedOutputIntegrityError(
            "Install source has an invalid generated-output marker."
        )
    if marker.get("marker_format") != "civ5studio.generated-output":
        raise GeneratedOutputIntegrityError(
            "Install source marker has an unknown format."
        )
    if marker.get("marker_version") != 2:
        raise GeneratedOutputIntegrityError(
            "Install source lacks the current SHA-256 integrity manifest; rebuild it."
        )
    if require_strict_release and marker.get("mode") != BuildMode.STRICT_RELEASE.value:
        raise GeneratedOutputIntegrityError(
            "Only a strict_release build can be installed."
        )

    raw_inventory = marker.get("inventory")
    if not isinstance(raw_inventory, list) or not all(
        isinstance(relative, str) for relative in raw_inventory
    ):
        raise GeneratedOutputIntegrityError(
            "Install source marker has an invalid player inventory."
        )
    if len(raw_inventory) != len(set(raw_inventory)):
        raise GeneratedOutputIntegrityError(
            "Install source marker contains duplicate inventory paths."
        )
    for relative in raw_inventory:
        if relative == OUTPUT_MARKER or not is_portable_relative_path(relative):
            raise GeneratedOutputIntegrityError(
                f"Install source marker contains an unsafe inventory path: {relative!r}."
            )
    expected_inventory = tuple(sorted(raw_inventory))

    raw_hashes = marker.get("sha256")
    if not isinstance(raw_hashes, dict) or set(raw_hashes) != set(expected_inventory):
        raise GeneratedOutputIntegrityError(
            "Install source SHA-256 manifest does not cover the exact player inventory."
        )
    for relative, digest in raw_hashes.items():
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise GeneratedOutputIntegrityError(
                f"Install source has an invalid SHA-256 digest for {relative}."
            )

    actual_inventory = _player_inventory(root)
    if actual_inventory != expected_inventory:
        missing = sorted(set(expected_inventory) - set(actual_inventory))
        unexpected = sorted(set(actual_inventory) - set(expected_inventory))
        detail: list[str] = []
        if missing:
            detail.append(f"missing: {', '.join(missing[:3])}")
        if unexpected:
            detail.append(f"unexpected: {', '.join(unexpected[:3])}")
        raise GeneratedOutputIntegrityError(
            "Install source file inventory changed after validation"
            + (f" ({'; '.join(detail)})" if detail else "")
            + "."
        )

    for relative in expected_inventory:
        target = root / relative
        _ensure_within(root, target)
        if _sha256_file(target) != raw_hashes[relative]:
            raise GeneratedOutputIntegrityError(
                f"Install source SHA-256 mismatch for {relative}."
            )
    return marker


def inspect_dds_artifact(path: str | Path, relative_path: str) -> RenderedArtifact:
    """Read the legacy DDS header fields required by the compiler contract."""

    source = Path(path)
    header = source.read_bytes()[:128]
    if len(header) < 128 or header[:4] != b"DDS " or _u32(header, 4) != 124:
        return RenderedArtifact(relative_path, 0, 0, "invalid_dds", 0, 0)
    height = _u32(header, 12)
    width = _u32(header, 16)
    depth = _u32(header, 24)
    mip_count = max(1, _u32(header, 28))
    four_cc = header[84:88]
    if four_cc == b"DXT1":
        profile = "legacy_dx9_dxt1"
    elif four_cc == b"DXT5":
        profile = "legacy_dx9_dxt5"
    elif four_cc == b"\x00\x00\x00\x00" and _u32(header, 88) == 32:
        profile = "legacy_dx9_a8r8g8b8"
    else:
        profile = "unknown_dds_profile"
    caps2 = _u32(header, 112)
    has_extra_surfaces = bool(caps2 & (0x0000FE00 | 0x00200000)) or depth > 1
    surface_count = 0 if has_extra_surfaces else 1
    return RenderedArtifact(
        relative_path,
        width,
        height,
        profile,
        surface_count=surface_count,
        mip_count=mip_count,
    )


def _u32(value: bytes, offset: int) -> int:
    return struct.unpack_from("<I", value, offset)[0]


def _write_compilation(root: Path, compilation: Compilation) -> None:
    for relative, content in compilation.files.items():
        if not is_portable_relative_path(relative):
            raise UnsafeBuildPath(f"Compiler emitted unsafe path: {relative}")
        target = root / relative
        _ensure_within(root, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _player_inventory(root: Path) -> tuple[str, ...]:
    inventory: list[str] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise GeneratedOutputIntegrityError(
                f"Generated output contains an unsupported symbolic link: {path}."
            )
        if path.is_file() and path.name != OUTPUT_MARKER:
            _ensure_within(root, path)
            inventory.append(path.relative_to(root).as_posix())
    return tuple(sorted(inventory))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_within(root: Path, candidate: Path) -> None:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeBuildPath(
            f"Path escapes project-owned root {root_resolved}: {candidate_resolved}"
        ) from exc


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise UnsafeBuildPath(f"Path metadata cannot be inspected: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _path_contains_link_or_reparse(path: Path) -> bool:
    absolute = path.absolute()
    return any(
        _is_link_or_reparse(component)
        for component in reversed((absolute, *absolute.parents))
    )


def _validate_windows_paths(root: Path, inventory: tuple[str, ...]) -> None:
    limit = 240
    candidates = [root, *(root / relative for relative in inventory)]
    longest = max(candidates, key=lambda value: len(str(value)))
    if len(str(longest)) > limit:
        raise UnsafeBuildPath(
            "Generated Windows path exceeds the conservative Civ V/MAX_PATH "
            f"limit ({len(str(longest))} > {limit}): {longest}. "
            "Choose a shorter project/output folder or mod name."
        )


def _remove_empty(path: Path) -> None:
    current = path
    for _ in range(2):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
