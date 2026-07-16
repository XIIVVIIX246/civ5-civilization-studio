"""Portable source validation for custom Civilization V music and speech."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath
import stat
import wave

from civ5studio.domain.validation import is_portable_relative_path


class AudioRole(StrEnum):
    PEACE_MUSIC = "peace_music"
    WAR_MUSIC = "war_music"
    DAWN_SPEECH = "dawn_speech"


@dataclass(frozen=True, slots=True)
class AudioAssetSpec:
    role: AudioRole
    source: str


@dataclass(frozen=True, slots=True)
class AudioIssue:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class AudioInspection:
    role: AudioRole
    source: str
    format: str
    sha256: str
    size: int
    duration_seconds: float | None
    issues: tuple[AudioIssue, ...]

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "ERROR" for issue in self.issues)


def inspect_audio_source(
    project_root: str | Path, spec: AudioAssetSpec
) -> AudioInspection:
    issues: list[AudioIssue] = []
    unresolved_root = Path(project_root).expanduser()
    if _path_contains_link_or_reparse(unresolved_root):
        return _invalid(
            spec,
            "audio.path",
            "Audio project root cannot contain a link or junction.",
        )
    root = unresolved_root.resolve()
    if not is_portable_relative_path(spec.source):
        return _invalid(spec, "audio.path", "Audio must use a portable project-relative path.")
    unresolved_source = root.joinpath(
        *PurePosixPath(spec.source.replace("\\", "/")).parts
    )
    if _path_contains_link_or_reparse(unresolved_source):
        return _invalid(
            spec, "audio.path", "Audio source cannot be a link or junction."
        )
    source = unresolved_source.resolve(strict=False)
    try:
        source.relative_to(root)
    except ValueError:
        return _invalid(spec, "audio.path", "Audio path escapes the project workspace.")
    if _path_contains_link_or_reparse(source):
        return _invalid(
            spec, "audio.path", "Audio source cannot be a link or junction."
        )
    if not source.is_file():
        return _invalid(spec, "audio.missing", "Audio source is missing.")
    if source.stat().st_size > 100 * 1024 * 1024:
        issues.append(
            AudioIssue(
                "ERROR",
                "audio.size",
                spec.source,
                "Audio source exceeds the conservative 100 MiB per-file limit.",
            )
        )

    suffix = source.suffix.lower()
    duration: float | None = None
    if suffix == ".wav":
        format_name = "wave"
        try:
            with wave.open(str(source), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate()
                duration = frames / rate if rate else None
                if handle.getnchannels() not in {1, 2}:
                    issues.append(
                        AudioIssue(
                            "ERROR",
                            "audio.channels",
                            spec.source,
                            "WAV audio must be mono or stereo.",
                        )
                    )
                if rate not in {22050, 44100, 48000}:
                    issues.append(
                        AudioIssue(
                            "WARNING",
                            "audio.sample-rate",
                            spec.source,
                            f"WAV sample rate {rate} Hz is unusual for Civ V; test in game.",
                        )
                    )
        except (wave.Error, EOFError, OSError) as exc:
            issues.append(
                AudioIssue(
                    "ERROR",
                    "audio.wave-header",
                    spec.source,
                    f"WAV header could not be read: {exc}",
                )
            )
    elif suffix == ".mp3":
        format_name = "mp3"
        header = source.read_bytes()[:4096]
        has_id3 = header.startswith(b"ID3")
        has_frame = any(
            header[index] == 0xFF and header[index + 1] & 0xE0 == 0xE0
            for index in range(max(0, len(header) - 1))
        )
        if not has_id3 and not has_frame:
            issues.append(
                AudioIssue(
                    "ERROR",
                    "audio.mp3-header",
                    spec.source,
                    "MP3 source has neither an ID3 header nor an MPEG audio frame.",
                )
            )
    else:
        format_name = suffix.removeprefix(".") or "unknown"
        issues.append(
            AudioIssue(
                "ERROR",
                "audio.format",
                spec.source,
                "Only verified WAV and MP3 source containers are supported.",
            )
        )

    issues.append(
        AudioIssue(
            "WARNING",
            "audio.runtime-required",
            spec.source,
            "Static container checks cannot prove Civ V audio decoding or volume balance.",
        )
    )
    return AudioInspection(
        spec.role,
        spec.source,
        format_name,
        _digest(source),
        source.stat().st_size,
        duration,
        tuple(issues),
    )


def _invalid(spec: AudioAssetSpec, code: str, message: str) -> AudioInspection:
    return AudioInspection(
        spec.role,
        spec.source,
        "unknown",
        "",
        0,
        None,
        (AudioIssue("ERROR", code, spec.source, message),),
    )


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _is_link_or_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
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
