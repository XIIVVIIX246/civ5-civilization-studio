"""Mode-driven, project-neutral Civ V art build service."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from PIL import Image

from .atlas import (
    AtlasSpec,
    build_atlas,
    expected_page_matrix,
    page_filename,
    placement_for,
)
from .dds import write_dds
from .profiles import (
    STRATEGIC_VIEW,
    ArtProcessingRole,
    DdsProfile,
    RenderProfile,
    art_role_profile,
)
from .rendering import render_image
from .reports import (
    OutputManifestEntry,
    RunReport,
    SourceManifestEntry,
    write_report_bundle,
)
from .validation import (
    IssueSeverity,
    SourceValidation,
    ValidationIssue,
    validate_art_role_source,
    validate_rendered_tile,
)


_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class PipelineMode(StrEnum):
    DRAFT = "draft"
    VALIDATE = "validate"
    BUILD_AVAILABLE = "build_available"
    STRICT_RELEASE = "strict_release"


class PipelineStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class IndividualArtSpec:
    key: str
    category: str
    source_path: Path
    output_path: Path
    output_size: tuple[int, int]
    dds_profile: DdsProfile
    required: bool = True
    release_blocking: bool = True
    requires_square_source: bool = False
    preferred_source_size: tuple[int, int] | None = None
    render_profile: RenderProfile = RenderProfile.PASSTHROUGH_ALPHA
    stretch_to_output: bool = True
    type_name: str = ""
    processing_role: ArtProcessingRole = ArtProcessingRole.GENERIC

    def __post_init__(self) -> None:
        _validate_relative_path(self.source_path, "source path")
        _validate_relative_path(self.output_path, "output path")
        if self.output_path.suffix.lower() != ".dds":
            raise ValueError("individual art output path must end in .dds")
        if min(self.output_size) <= 0:
            raise ValueError("individual art output dimensions must be positive")
        if self.dds_profile.default_size and self.output_size != self.dds_profile.default_size:
            raise ValueError(
                f"{self.dds_profile.name} output must be {self.dds_profile.default_size}"
            )
        if self.dds_profile == STRATEGIC_VIEW:
            if self.output_size != (64, 64) or not self.requires_square_source:
                raise ValueError("Strategic View art must be square source rendered to 64x64")
        role = ArtProcessingRole(self.processing_role)
        if role is not ArtProcessingRole.GENERIC:
            profile = art_role_profile(role)
            if profile.atlas_role:
                raise ValueError(f"{role.value} is not an individual art role")
            if profile.dds_profile != self.dds_profile:
                raise ValueError(
                    f"{role.value} requires the {profile.dds_profile.name} DDS profile"
                )
            if profile.render_profile is not self.render_profile:
                raise ValueError(
                    f"{role.value} requires {profile.render_profile.value} rendering"
                )
            if profile.output_size and self.output_size != profile.output_size:
                raise ValueError(
                    f"{role.value} output must be {profile.output_size[0]}x"
                    f"{profile.output_size[1]}"
                )
            if self.requires_square_source != profile.requires_square_source:
                shape = "square" if profile.requires_square_source else "non-square"
                raise ValueError(f"{role.value} requires a {shape} working source contract")


@dataclass(frozen=True, slots=True)
class ArtProjectSpec:
    project_id: str
    atlases: tuple[AtlasSpec, ...] = field(default_factory=tuple)
    individuals: tuple[IndividualArtSpec, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not _SAFE_PROJECT_ID.fullmatch(self.project_id):
            raise ValueError(
                "project_id must contain only letters, numbers, dot, dash, or underscore"
            )
        if self.schema_version != 1:
            raise ValueError(f"unsupported art project schema version: {self.schema_version}")
        categories = [atlas.category for atlas in self.atlases]
        if len(categories) != len(set(categories)):
            raise ValueError("atlas categories must be unique")
        keys = [item.key for atlas in self.atlases for item in atlas.items]
        keys.extend(item.key for item in self.individuals)
        if len(keys) != len(set(keys)):
            raise ValueError("art item keys must be unique across the project")


@dataclass(frozen=True, slots=True)
class PipelineResult:
    mode: PipelineMode
    status: PipelineStatus
    source_manifest: tuple[SourceManifestEntry, ...]
    output_manifest: tuple[OutputManifestEntry, ...]
    issues: tuple[ValidationIssue, ...]
    report_paths: dict[str, Path]
    build_performed: bool

    @property
    def succeeded(self) -> bool:
        return self.status is not PipelineStatus.FAIL

    @property
    def blockers(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is IssueSeverity.BLOCKER)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is IssueSeverity.WARNING)


def _validate_relative_path(path: Path, label: str) -> None:
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"{label} must be a project-relative path: {path}")


def _resolve_under(root: Path, relative: Path) -> Path:
    _validate_relative_path(relative, "asset path")
    root = root.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"asset path escapes project root: {relative}")
    return resolved


def _relative_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _issue_from_build(
    *,
    code: str,
    message: str,
    item_key: str,
    category: str,
    source_path: str = "",
    blocking: bool = True,
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        message=message,
        severity=IssueSeverity.BLOCKER if blocking else IssueSeverity.WARNING,
        item_key=item_key,
        category=category,
        source_path=source_path,
    )


def _source_entry_for_atlas_item(
    validation: SourceValidation,
    atlas: AtlasSpec,
    item_index: int,
    required: bool,
    source_path: Path,
) -> SourceManifestEntry:
    placement = placement_for(item_index, atlas.atlas_name)
    return SourceManifestEntry(
        item_key=validation.item_key,
        category=validation.category,
        output_kind="atlas",
        required=required,
        source_path=source_path.as_posix(),
        source_sha256=validation.source_sha256,
        exists=validation.exists,
        valid=validation.valid,
        validation_status=validation.status,
        validation_codes=tuple(issue.code for issue in validation.issues),
        width=validation.width,
        height=validation.height,
        atlas_name=placement.atlas_name,
        atlas_page=placement.page,
        global_index=placement.global_index,
        local_index=placement.local_index,
        row=placement.row,
        column=placement.column,
    )


def _source_entry_for_individual(
    validation: SourceValidation, item: IndividualArtSpec
) -> SourceManifestEntry:
    return SourceManifestEntry(
        item_key=validation.item_key,
        category=validation.category,
        output_kind="individual",
        required=item.required,
        source_path=item.source_path.as_posix(),
        source_sha256=validation.source_sha256,
        exists=validation.exists,
        valid=validation.valid,
        validation_status=validation.status,
        validation_codes=tuple(issue.code for issue in validation.issues),
        width=validation.width,
        height=validation.height,
        expected_output_path=item.output_path.as_posix(),
    )


def _scan_sources(
    spec: ArtProjectSpec, input_root: Path
) -> tuple[
    list[SourceManifestEntry],
    list[ValidationIssue],
    dict[str, dict[str, Path]],
    dict[str, Path],
]:
    entries: list[SourceManifestEntry] = []
    issues: list[ValidationIssue] = []
    atlas_sources: dict[str, dict[str, Path]] = {}
    individual_sources: dict[str, Path] = {}
    for atlas in spec.atlases:
        available: dict[str, Path] = {}
        for item in atlas.items:
            source = _resolve_under(input_root, item.source_path)
            validation = validate_art_role_source(
                source,
                role=item.processing_role,
                item_key=item.key,
                category=atlas.category,
                required=item.required,
                release_blocking=atlas.release_blocking,
                requires_square=atlas.requires_square_source,
                preferred_size=atlas.preferred_source_size,
            )
            entries.append(
                _source_entry_for_atlas_item(
                    validation, atlas, item.index, item.required, item.source_path
                )
            )
            issues.extend(
                ValidationIssue(
                    code=issue.code,
                    message=issue.message,
                    severity=issue.severity,
                    item_key=issue.item_key,
                    category=issue.category,
                    source_path=item.source_path.as_posix(),
                    details=issue.details,
                )
                for issue in validation.issues
            )
            if validation.exists and validation.valid:
                available[item.key] = source
        atlas_sources[atlas.category] = available

    for item in spec.individuals:
        source = _resolve_under(input_root, item.source_path)
        validation = validate_art_role_source(
            source,
            role=item.processing_role,
            item_key=item.key,
            category=item.category,
            required=item.required,
            release_blocking=item.release_blocking,
            requires_square=item.requires_square_source,
            preferred_size=item.preferred_source_size,
        )
        entries.append(_source_entry_for_individual(validation, item))
        issues.extend(
            ValidationIssue(
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
                item_key=issue.item_key,
                category=issue.category,
                source_path=item.source_path.as_posix(),
                details=issue.details,
            )
            for issue in validation.issues
        )
        if validation.exists and validation.valid:
            individual_sources[item.key] = source
    return entries, issues, atlas_sources, individual_sources


def _build_outputs(
    spec: ArtProjectSpec,
    staging_root: Path,
    atlas_sources: dict[str, dict[str, Path]],
    individual_sources: dict[str, Path],
    *,
    texconv_path: Path | None,
) -> tuple[list[OutputManifestEntry], list[ValidationIssue], set[str]]:
    outputs: list[OutputManifestEntry] = []
    issues: list[ValidationIssue] = []
    built_tokens: set[str] = set()
    atlas_root = staging_root / "Art" / "Atlases"
    preview_root = staging_root / "Art" / "Previews"

    for atlas in spec.atlases:
        available = atlas_sources[atlas.category]
        if not available:
            continue
        atlas_blocks_release = atlas.release_blocking and any(
            item.required for item in atlas.items
        )
        try:
            pages, shapes = build_atlas(
                atlas,
                available,
                atlas_root,
                preview_directory=preview_root,
                texconv_path=texconv_path,
            )
        except Exception as exc:
            issues.append(
                _issue_from_build(
                    code="ATLAS_BUILD_FAILED",
                    message=str(exc),
                    item_key="<atlas>",
                    category=atlas.category,
                    blocking=atlas_blocks_release,
                )
            )
            continue
        for shape in shapes:
            source = available[shape.item_key]
            source_item = next(item for item in atlas.items if item.key == shape.item_key)
            with Image.open(source) as opened:
                tile = render_image(opened, shape.icon_size, atlas.render_profile)
            for issue in validate_rendered_tile(tile, atlas.render_profile):
                issues.append(
                    ValidationIssue(
                        code=issue.code,
                        message=issue.message,
                        severity=(
                            IssueSeverity.BLOCKER
                            if atlas.release_blocking and source_item.required
                            else IssueSeverity.WARNING
                        ),
                        item_key=shape.item_key,
                        category=atlas.category,
                        source_path=source.as_posix(),
                        details=issue.details,
                    )
                )
        for page in pages:
            relative_output = _relative_to(page.output_path, staging_root)
            outputs.append(
                OutputManifestEntry(
                    output_kind="atlas_page",
                    category=page.category,
                    item_key="",
                    output_path=relative_output,
                    dds_profile=page.dds_profile,
                    dds_format=page.dds_format,
                    width=page.width,
                    height=page.height,
                    mipmap_count=page.mipmap_count,
                    output_sha256=page.output_sha256,
                    encoder=page.encoder,
                    atlas_name=page.atlas_name,
                    atlas_page=page.atlas_page,
                    icon_size=page.icon_size,
                    built_item_keys=page.built_item_keys,
                )
            )
            built_tokens.add(f"atlas:{atlas.category}:{page.atlas_page}:{page.icon_size}")

    by_key = {item.key: item for item in spec.individuals}
    for key, source in individual_sources.items():
        item = by_key[key]
        destination = _resolve_under(staging_root, item.output_path)
        try:
            with Image.open(source) as opened:
                if item.stretch_to_output:
                    rendered = opened.convert("RGBA").resize(
                        item.output_size, Image.Resampling.LANCZOS
                    )
                elif item.output_size[0] == item.output_size[1]:
                    rendered = render_image(
                        opened, item.output_size[0], item.render_profile
                    )
                else:
                    raise ValueError(
                        "non-square contained output requires stretch_to_output=True"
                    )
            result = write_dds(
                rendered, destination, item.dds_profile, texconv_path=texconv_path
            )
        except Exception as exc:
            issues.append(
                _issue_from_build(
                    code="INDIVIDUAL_BUILD_FAILED",
                    message=str(exc),
                    item_key=key,
                    category=item.category,
                    source_path=source.as_posix(),
                    blocking=item.required and item.release_blocking,
                )
            )
            continue
        outputs.append(
            OutputManifestEntry(
                output_kind="individual",
                category=item.category,
                item_key=key,
                output_path=_relative_to(destination, staging_root),
                dds_profile=item.dds_profile.name,
                dds_format=result.header.fourcc or "A8R8G8B8",
                width=result.header.width,
                height=result.header.height,
                mipmap_count=result.header.mipmap_count,
                output_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                encoder=result.encoder,
            )
        )
        built_tokens.add(f"individual:{key}")
    return outputs, issues, built_tokens


def _expected_tokens(
    spec: ArtProjectSpec,
    atlas_sources: dict[str, dict[str, Path]],
    individual_sources: dict[str, Path],
) -> set[str]:
    expected: set[str] = set()
    for atlas in spec.atlases:
        if not atlas_sources[atlas.category]:
            continue
        expected.update(
            f"atlas:{atlas.category}:{page}:{size}"
            for page, size in expected_page_matrix(atlas)
        )
    expected.update(f"individual:{key}" for key in individual_sources)
    return expected


def _expected_token_blocks_release(spec: ArtProjectSpec, token: str) -> bool:
    kind, identifier, *_ = token.split(":")
    if kind == "atlas":
        atlas = next(atlas for atlas in spec.atlases if atlas.category == identifier)
        return atlas.release_blocking and any(item.required for item in atlas.items)
    item = next(item for item in spec.individuals if item.key == identifier)
    return item.required and item.release_blocking


def run_art_pipeline(
    spec: ArtProjectSpec,
    *,
    input_root: Path,
    staging_root: Path,
    mode: PipelineMode = PipelineMode.DRAFT,
    texconv_path: Path | None = None,
) -> PipelineResult:
    """Audit, validate, or build a project's configured art.

    This function never deletes or recursively replaces a directory.  The
    application-level build controller owns creation and atomic publication of
    the project staging root.
    """

    mode = PipelineMode(mode)
    input_root = input_root.resolve()
    staging_root = staging_root.resolve()
    if not input_root.is_dir():
        raise FileNotFoundError(f"art input root does not exist: {input_root}")
    staging_root.mkdir(parents=True, exist_ok=True)
    source_entries, issues, atlas_sources, individual_sources = _scan_sources(
        spec, input_root
    )
    output_entries: list[OutputManifestEntry] = []
    build_performed = mode in (PipelineMode.BUILD_AVAILABLE, PipelineMode.STRICT_RELEASE)
    expected = _expected_tokens(spec, atlas_sources, individual_sources)
    if build_performed:
        output_entries, build_issues, built = _build_outputs(
            spec,
            staging_root,
            atlas_sources,
            individual_sources,
            texconv_path=texconv_path,
        )
        issues.extend(build_issues)
        for token in sorted(expected - built):
            issues.append(
                _issue_from_build(
                    code="EXPECTED_OUTPUT_MISSING",
                    message=f"configured output was not built: {token}",
                    item_key=token,
                    category="generated-output",
                    blocking=_expected_token_blocks_release(spec, token),
                )
            )

    blockers = [issue for issue in issues if issue.severity is IssueSeverity.BLOCKER]
    warnings = [issue for issue in issues if issue.severity is IssueSeverity.WARNING]
    if mode in (PipelineMode.VALIDATE, PipelineMode.STRICT_RELEASE) and blockers:
        status = PipelineStatus.FAIL
    elif blockers or warnings:
        status = PipelineStatus.WARN
    else:
        status = PipelineStatus.PASS
    run_report = RunReport(
        project_id=spec.project_id,
        mode=mode.value,
        status=status.value,
        configured_items=len(source_entries),
        existing_sources=sum(1 for entry in source_entries if entry.exists),
        valid_sources=sum(1 for entry in source_entries if entry.exists and entry.valid),
        blocker_count=len(blockers),
        warning_count=len(warnings),
        expected_outputs=len(expected),
        built_outputs=len(output_entries),
        build_performed=build_performed,
        issues=tuple(issues),
    )
    report_paths = write_report_bundle(
        staging_root / "Reports" / "Art",
        source_entries=source_entries,
        output_entries=output_entries,
        run_report=run_report,
        write_output_manifest=build_performed,
    )
    return PipelineResult(
        mode=mode,
        status=status,
        source_manifest=tuple(source_entries),
        output_manifest=tuple(output_entries),
        issues=tuple(issues),
        report_paths=report_paths,
        build_performed=build_performed,
    )


def draft(spec: ArtProjectSpec, *, input_root: Path, staging_root: Path) -> PipelineResult:
    return run_art_pipeline(
        spec, input_root=input_root, staging_root=staging_root, mode=PipelineMode.DRAFT
    )


def validate(spec: ArtProjectSpec, *, input_root: Path, staging_root: Path) -> PipelineResult:
    return run_art_pipeline(
        spec, input_root=input_root, staging_root=staging_root, mode=PipelineMode.VALIDATE
    )


def build_available(
    spec: ArtProjectSpec, *, input_root: Path, staging_root: Path
) -> PipelineResult:
    return run_art_pipeline(
        spec,
        input_root=input_root,
        staging_root=staging_root,
        mode=PipelineMode.BUILD_AVAILABLE,
    )


def strict_release(
    spec: ArtProjectSpec, *, input_root: Path, staging_root: Path
) -> PipelineResult:
    return run_art_pipeline(
        spec,
        input_root=input_root,
        staging_root=staging_root,
        mode=PipelineMode.STRICT_RELEASE,
    )
