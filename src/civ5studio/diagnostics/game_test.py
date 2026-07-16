"""A non-destructive assistant for manual Civilization V runtime testing.

This module deliberately does not launch Civilization V, edit ``config.ini``,
clear cache files, or install a mod.  It discovers paths, explains the manual
steps, reads the four useful Civ V logs, and can package redacted evidence into
a user-selected ZIP.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile


EXPECTED_LOG_NAMES = ("Database.log", "Lua.log", "xml.log", "Modding.log")
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_MODINFO_BYTES = 2 * 1024 * 1024
MAX_IDENTITY_SOURCE_BYTES = 16 * 1024 * 1024
MAX_LOG_CAPTURE_BYTES = 16 * 1024 * 1024
_ERROR_RE = re.compile(
    r"(?:\berror\b|\bexception\b|\bfail(?:ed|ure)?\b|constraint\s+failed|"
    r"\bno\s+such\s+(?:table|column)\b|\bsyntax\s+error\b|\bmalformed\b|"
    r"\binvalid\s+(?:column|database|xml)\b|\battempt\s+to\b.*\bnil\b|"
    r"\bstack\s+traceback\b|\bunable\s+to\b|\bcould\s+not\b)",
    re.IGNORECASE,
)
_WARNING_RE = re.compile(r"\bwarn(?:ing)?\b", re.IGNORECASE)
_BENIGN_ERROR_COUNT_RE = re.compile(
    r"(?:\bno\s+errors?\b|\b0\s+errors?\b|\berrors?\s*[:=]\s*0\b|"
    r"\bfailed\s*[:=]\s*0\b)",
    re.IGNORECASE,
)
_TYPE_TOKEN_RE = re.compile(
    r"\b(?:BUILDING|CIVILIZATION|IMPROVEMENT|LEADER|POLICY|PROMOTION|RESOURCE|"
    r"SPECIALIST|TECH|TRAIT|UNIT)_[A-Z0-9_]+\b"
)


class EnvironmentStatus(StrEnum):
    READY = "READY"
    INCOMPLETE = "INCOMPLETE"
    NOT_FOUND = "NOT_FOUND"


class AttributionConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    UNATTRIBUTED = "UNATTRIBUTED"


@dataclass(frozen=True, slots=True)
class EnvironmentIssue:
    severity: str
    code: str
    message: str
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class Civ5UserEnvironment:
    root: Path
    mods_path: Path
    logs_path: Path
    cache_path: Path
    config_path: Path
    status: EnvironmentStatus
    logging_enabled: bool | None
    issues: tuple[EnvironmentIssue, ...]


@dataclass(frozen=True, slots=True)
class GeneratedModIdentity:
    root: Path
    modinfo_path: Path
    mod_id: str
    name: str
    version: str
    tokens: tuple[str, ...]
    modinfo_sha256: str
    generated_marker_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class LogFinding:
    log_name: str
    line_number: int
    severity: str
    attribution: AttributionConfidence
    message: str
    matched_token: str = ""

    @property
    def tied_to_generated_mod(self) -> bool:
        return self.attribution is not AttributionConfidence.UNATTRIBUTED


@dataclass(frozen=True, slots=True)
class FileEvidence:
    label: str
    exists: bool
    size: int | None
    sha256: str | None
    captured: bool
    truncated: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class ChecklistStep:
    number: int
    title: str
    instructions: str


@dataclass(frozen=True, slots=True)
class DiagnosticsReport:
    environment: Civ5UserEnvironment
    generated_mod: GeneratedModIdentity
    evidence: tuple[FileEvidence, ...]
    findings: tuple[LogFinding, ...]
    checklist: tuple[ChecklistStep, ...]
    safety_boundary: str = (
        "No game launch, mod install, config edit, or cache deletion was performed. "
        "BNW and IGE behavior still require the listed manual in-game tests."
    )

    @property
    def generated_mod_findings(self) -> tuple[LogFinding, ...]:
        return tuple(item for item in self.findings if item.tied_to_generated_mod)


@dataclass(frozen=True, slots=True)
class BundleResult:
    path: Path
    sha256: str
    report: DiagnosticsReport


@dataclass(frozen=True, slots=True)
class _CapturedLog:
    name: str
    text: str
    evidence: FileEvidence


def discover_civ5_user_environment(
    configured_root: str | Path | None = None,
    *,
    home: str | Path | None = None,
) -> Civ5UserEnvironment:
    """Discover and validate the Civ V user-data folder without creating it."""

    user_home = Path(home).resolve() if home is not None else Path.home().resolve()
    root = (
        Path(configured_root).resolve()
        if configured_root is not None
        else user_home
        / "Documents"
        / "My Games"
        / "Sid Meier's Civilization 5"
    )
    mods = root / "MODS"
    logs = root / "Logs"
    cache = root / "cache"
    config = root / "config.ini"
    issues: list[EnvironmentIssue] = []
    if not root.is_dir():
        issues.append(
            EnvironmentIssue(
                "ERROR",
                "CIV5_USER_ROOT_MISSING",
                "The configured Civilization V user-data folder does not exist or is not a directory.",
                root,
            )
        )
        return Civ5UserEnvironment(
            root,
            mods,
            logs,
            cache,
            config,
            EnvironmentStatus.NOT_FOUND,
            None,
            tuple(issues),
        )

    for label, path, required in (
        ("MODS", mods, True),
        ("Logs", logs, True),
        ("cache", cache, False),
    ):
        if not path.is_dir():
            issues.append(
                EnvironmentIssue(
                    "ERROR" if required else "WARNING",
                    f"CIV5_{label.upper()}_MISSING",
                    f"Expected Civilization V {label} directory was not found.",
                    path,
                )
            )

    logging_enabled: bool | None = None
    if not config.is_file():
        issues.append(
            EnvironmentIssue(
                "WARNING",
                "CIV5_CONFIG_MISSING",
                "config.ini was not found; log settings could not be verified.",
                config,
            )
        )
    elif config.is_symlink():
        issues.append(
            EnvironmentIssue(
                "WARNING",
                "CIV5_CONFIG_LINK_UNREAD",
                "Linked config.ini was not read.",
                config,
            )
        )
    else:
        try:
            if config.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError(f"config.ini exceeds {MAX_CONFIG_BYTES} bytes")
            text = config.read_text(encoding="utf-8-sig", errors="replace")
            setting = re.search(
                r"(?im)^\s*LoggingEnabled\s*=\s*([01])\s*(?:;.*)?$", text
            )
            if setting:
                logging_enabled = setting.group(1) == "1"
                if not logging_enabled:
                    issues.append(
                        EnvironmentIssue(
                            "WARNING",
                            "CIV5_LOGGING_DISABLED",
                            "config.ini reports LoggingEnabled = 0; fresh diagnostic logs may be incomplete.",
                            config,
                        )
                    )
            else:
                issues.append(
                    EnvironmentIssue(
                        "WARNING",
                        "CIV5_LOGGING_SETTING_UNKNOWN",
                        "LoggingEnabled was not found in config.ini.",
                        config,
                    )
                )
        except (OSError, ValueError) as exc:
            issues.append(
                EnvironmentIssue(
                    "WARNING",
                    "CIV5_CONFIG_UNREADABLE",
                    f"config.ini could not be inspected: {exc}",
                    config,
                )
            )

    required_missing = any(
        item.code in {"CIV5_MODS_MISSING", "CIV5_LOGS_MISSING"} for item in issues
    )
    status = EnvironmentStatus.INCOMPLETE if required_missing else EnvironmentStatus.READY
    return Civ5UserEnvironment(
        root,
        mods,
        logs,
        cache,
        config,
        status,
        logging_enabled,
        tuple(issues),
    )


def inspect_generated_mod(generated_mod_root: str | Path) -> GeneratedModIdentity:
    """Read identity tokens from one generated/installed mod folder."""

    root = Path(generated_mod_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Generated mod folder does not exist: {root}")
    modinfos = sorted(root.glob("*.modinfo"))
    if len(modinfos) != 1:
        raise ValueError("Generated mod folder must contain exactly one top-level .modinfo file.")
    modinfo = modinfos[0]
    if modinfo.is_symlink() or not _is_within(root, modinfo):
        raise ValueError("Generated mod .modinfo must be a regular file inside the mod folder.")
    if modinfo.stat().st_size > MAX_MODINFO_BYTES:
        raise ValueError(f"Generated mod .modinfo exceeds {MAX_MODINFO_BYTES} bytes.")
    try:
        document = ET.fromstring(modinfo.read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"Generated mod .modinfo is invalid: {exc}") from exc
    if _local_name(document.tag).casefold() != "mod":
        raise ValueError("Generated mod .modinfo root element must be Mod.")
    properties = _first_child(document, "Properties")
    name = _child_text(properties, "Name").strip() if properties is not None else ""
    name = name or root.name
    mod_id = document.attrib.get("id", "").strip()
    version = document.attrib.get("version", "").strip()
    tokens: set[str] = {name, root.name}
    if mod_id:
        tokens.add(mod_id)
    files = _modinfo_files(document)
    for relative in files:
        normalized = relative.replace("\\", "/")
        tokens.add(Path(normalized).name)
        if len(Path(normalized).stem) >= 6:
            tokens.add(Path(normalized).stem)
        source = root.joinpath(*normalized.split("/"))
        if (
            source.suffix.casefold() in {".xml", ".sql", ".lua"}
            and source.is_file()
            and not source.is_symlink()
            and _is_within(root, source)
            and source.stat().st_size <= MAX_IDENTITY_SOURCE_BYTES
        ):
            content = source.read_text(encoding="utf-8-sig", errors="replace")
            tokens.update(_TYPE_TOKEN_RE.findall(content))
    tokens = {value.strip() for value in tokens if _useful_identity_token(value)}
    marker = root / ".civ5studio-generated.json"
    marker_hash = (
        _sha256_file(marker)
        if marker.is_file() and not marker.is_symlink() and _is_within(root, marker)
        else None
    )
    return GeneratedModIdentity(
        root,
        modinfo,
        mod_id,
        name,
        version,
        tuple(sorted(tokens, key=lambda value: (-len(value), value.casefold()))),
        _sha256_file(modinfo),
        marker_hash,
    )


def analyze_game_logs(
    environment: Civ5UserEnvironment,
    generated_mod: GeneratedModIdentity,
) -> tuple[tuple[FileEvidence, ...], tuple[LogFinding, ...]]:
    """Hash and analyze expected logs; never reads cache or arbitrary files."""

    captures = _capture_logs(environment)
    return _analyze_captures(captures, generated_mod)


def _analyze_captures(
    captures: tuple[_CapturedLog, ...],
    generated_mod: GeneratedModIdentity,
) -> tuple[tuple[FileEvidence, ...], tuple[LogFinding, ...]]:
    findings: list[LogFinding] = []
    token_pairs = tuple((token, token.casefold()) for token in generated_mod.tokens)
    for capture in captures:
        if not capture.evidence.captured:
            continue
        lines = capture.text.splitlines()
        token_hits: dict[int, str] = {}
        for index, line in enumerate(lines):
            lowered = line.casefold()
            match = next((token for token, folded in token_pairs if folded in lowered), "")
            if match:
                token_hits[index] = match
        for index, line in enumerate(lines):
            severity = _line_severity(line)
            if severity is None:
                continue
            matched = token_hits.get(index, "")
            attribution = AttributionConfidence.HIGH if matched else AttributionConfidence.UNATTRIBUTED
            if not matched:
                nearby = [
                    (distance, token_hits[nearby_index])
                    for nearby_index in range(max(0, index - 3), min(len(lines), index + 4))
                    if nearby_index in token_hits
                    for distance in (abs(index - nearby_index),)
                ]
                if nearby:
                    _, matched = min(nearby, key=lambda item: item[0])
                    attribution = AttributionConfidence.MEDIUM
            findings.append(
                LogFinding(
                    capture.name,
                    index + 1,
                    severity,
                    attribution,
                    line.strip()[:2000],
                    matched,
                )
            )
    findings.sort(
        key=lambda item: (
            item.attribution is AttributionConfidence.UNATTRIBUTED,
            item.log_name.casefold(),
            item.line_number,
        )
    )
    return tuple(item.evidence for item in captures), tuple(findings)


def build_manual_test_checklist(
    environment: Civ5UserEnvironment,
    generated_mod: GeneratedModIdentity,
    *,
    include_ige_pass: bool = True,
) -> tuple[ChecklistStep, ...]:
    """Return explicit user actions; none of these actions are executed here."""

    logging_note = {
        True: "LoggingEnabled = 1 was detected; keep it enabled for the test.",
        False: "LoggingEnabled = 0 was detected. Manually set it to 1 while Civ V is closed, then restore it later if desired.",
        None: "LoggingEnabled could not be verified. Manually confirm it is set to 1 while Civ V is closed.",
    }[environment.logging_enabled]
    steps = [
        ChecklistStep(
            1,
            "Confirm the test artifact",
            f"Use the exact strict build for {generated_mod.name!r} (mod id {generated_mod.mod_id or 'not declared'}). Record its build/package hash before installing.",
        ),
        ChecklistStep(
            2,
            "Install through Civilization Studio",
            f"Use the app's verified Install action and confirm the destination under {environment.mods_path}. This diagnostic assistant does not install or move files.",
        ),
        ChecklistStep(
            3,
            "Close Civilization V",
            "Exit the game completely before changing logging, installed mods, or cache contents.",
        ),
        ChecklistStep(
            4,
            "Prepare logging",
            logging_note,
        ),
        ChecklistStep(
            5,
            "Optionally refresh cache manually",
            f"If a clean-cache test is required, first back up {environment.cache_path}, then manually clear only that cache folder's contents. This assistant does not delete cache files.",
        ),
        ChecklistStep(
            6,
            "Launch BNW manually",
            "Start Civilization V through your normal Steam/desktop route, choose DirectX 10/11 as usual, and enter the MODS menu. This assistant does not launch the game.",
        ),
        ChecklistStep(
            7,
            "Run the isolated baseline",
            f"Enable {generated_mod.name!r} and only its declared dependencies. Start a new Brave New World game with the custom civilization and exercise its trait, uniques, art, Civilopedia, setup screen, and save/load behavior.",
        ),
        ChecklistStep(
            8,
            "Exit and preserve fresh logs",
            f"After reproducing the result, exit Civ V before collecting {', '.join(EXPECTED_LOG_NAMES)} from {environment.logs_path}. Avoid launching another session first because logs may be replaced.",
        ),
    ]
    if include_ige_pass:
        steps.append(
            ChecklistStep(
                9,
                "Run a separate IGE pass",
                "Only after the isolated baseline passes, repeat in a fresh session with the installed Ingame Editor mod enabled. Exercise IGE opening/closing and unit, city, plot, and player edits. Presence of IGE is not itself proof of compatibility.",
            )
        )
    steps.append(
        ChecklistStep(
            len(steps) + 1,
            "Classify the result",
            "Treat static validation, baseline BNW runtime, and the separate IGE runtime pass as distinct gates. Report each as PASS, FAIL, or NOT RUN with the diagnostic ZIP hash.",
        )
    )
    return tuple(steps)


def collect_diagnostics_bundle(
    environment: Civ5UserEnvironment,
    generated_mod_root: str | Path,
    destination: str | Path,
    *,
    include_ige_pass: bool = True,
) -> BundleResult:
    """Create a redacted deterministic ZIP at a user-selected destination."""

    generated_mod = inspect_generated_mod(generated_mod_root)
    # Capture once so the hashes, parsed findings, and bundled bytes describe
    # exactly the same log snapshot even if Civ V writes a new line later.
    captures = _capture_logs(environment)
    evidence, findings = _analyze_captures(captures, generated_mod)
    checklist = build_manual_test_checklist(
        environment, generated_mod, include_ige_pass=include_ige_pass
    )
    report = DiagnosticsReport(environment, generated_mod, evidence, findings, checklist)
    output = Path(destination).resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite diagnostics bundle: {output}")
    if output.suffix.casefold() != ".zip":
        raise ValueError("Diagnostics bundle destination must end in .zip.")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    replacements = _redaction_replacements(environment, generated_mod)
    payload = _report_payload(report, replacements)
    markdown = _report_markdown(report, replacements)
    try:
        with zipfile.ZipFile(
            temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            _zip_text(
                archive,
                "diagnostics.json",
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            )
            _zip_text(archive, "diagnostics.md", markdown)
            for capture in captures:
                if capture.evidence.captured:
                    _zip_text(
                        archive,
                        f"logs/{capture.name}",
                        _redact(capture.text, replacements),
                    )
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return BundleResult(output, _sha256_file(output), report)


def _capture_logs(environment: Civ5UserEnvironment) -> tuple[_CapturedLog, ...]:
    available: dict[str, Path] = {}
    if environment.logs_path.is_dir():
        try:
            available = {
                item.name.casefold(): item
                for item in environment.logs_path.iterdir()
                if item.is_file() and not item.is_symlink()
            }
        except OSError:
            available = {}
    captures: list[_CapturedLog] = []
    for expected in EXPECTED_LOG_NAMES:
        path = available.get(expected.casefold(), environment.logs_path / expected)
        label = f"%CIV5_LOGS%/{expected}"
        if not path.is_file() or path.is_symlink() or not _is_within(environment.logs_path, path):
            captures.append(
                _CapturedLog(
                    expected,
                    "",
                    FileEvidence(
                        label,
                        False,
                        None,
                        None,
                        False,
                        note="Expected log was not found as a regular file.",
                    ),
                )
            )
            continue
        try:
            size = path.stat().st_size
            digest = _sha256_file(path)
            with path.open("rb") as source:
                truncated = size > MAX_LOG_CAPTURE_BYTES
                if truncated:
                    source.seek(size - MAX_LOG_CAPTURE_BYTES)
                raw = source.read(MAX_LOG_CAPTURE_BYTES)
            text = raw.decode("utf-8-sig", errors="replace")
            if truncated and "\n" in text:
                text = text.split("\n", 1)[1]
            captures.append(
                _CapturedLog(
                    expected,
                    text,
                    FileEvidence(
                        label,
                        True,
                        size,
                        digest,
                        True,
                        truncated,
                        "Captured the most recent tail only." if truncated else "",
                    ),
                )
            )
        except OSError as exc:
            captures.append(
                _CapturedLog(
                    expected,
                    "",
                    FileEvidence(label, True, None, None, False, note=f"Could not read log: {exc}"),
                )
            )
    return tuple(captures)


def _line_severity(line: str) -> str | None:
    if _BENIGN_ERROR_COUNT_RE.search(line):
        return None
    if _ERROR_RE.search(line):
        return "ERROR"
    if _WARNING_RE.search(line):
        return "WARNING"
    return None


def _report_payload(
    report: DiagnosticsReport, replacements: tuple[tuple[str, str], ...]
) -> dict[str, object]:
    environment = report.environment
    generated = report.generated_mod
    return {
        "format": "civ5studio.runtime-diagnostics",
        "version": 1,
        "safety_boundary": report.safety_boundary,
        "environment": {
            "status": environment.status.value,
            "root": _redact(str(environment.root), replacements),
            "mods": _redact(str(environment.mods_path), replacements),
            "logs": _redact(str(environment.logs_path), replacements),
            "cache": _redact(str(environment.cache_path), replacements),
            "config": _redact(str(environment.config_path), replacements),
            "logging_enabled": environment.logging_enabled,
            "issues": [
                {
                    "severity": item.severity,
                    "code": item.code,
                    "message": _redact(item.message, replacements),
                    "path": _redact(str(item.path), replacements) if item.path else None,
                }
                for item in environment.issues
            ],
        },
        "generated_mod": {
            "name": generated.name,
            "mod_id": generated.mod_id,
            "version": generated.version,
            "root": "%GENERATED_MOD_ROOT%",
            "modinfo_sha256": generated.modinfo_sha256,
            "generated_marker_sha256": generated.generated_marker_sha256,
        },
        "evidence": [
            {
                "label": item.label,
                "exists": item.exists,
                "size": item.size,
                "sha256": item.sha256,
                "captured": item.captured,
                "truncated": item.truncated,
                "note": _redact(item.note, replacements),
            }
            for item in report.evidence
        ],
        "findings": [
            {
                "log": item.log_name,
                "line": item.line_number,
                "severity": item.severity,
                "attribution": item.attribution.value,
                "tied_to_generated_mod": item.tied_to_generated_mod,
                "matched_token": item.matched_token,
                "message": _redact(item.message, replacements),
            }
            for item in report.findings
        ],
        "checklist": [
            {
                "number": item.number,
                "title": item.title,
                "instructions": _redact(item.instructions, replacements),
            }
            for item in report.checklist
        ],
        "runtime_gates": {
            "bnw_in_game": "NOT_RUN_BY_ASSISTANT",
            "ige_compatibility": "NOT_RUN_BY_ASSISTANT",
        },
    }


def _report_markdown(
    report: DiagnosticsReport, replacements: tuple[tuple[str, str], ...]
) -> str:
    tied = report.generated_mod_findings
    lines = [
        "# Civilization V Runtime Diagnostics",
        "",
        _redact(report.safety_boundary, replacements),
        "",
        f"- Environment: {report.environment.status.value}",
        f"- Generated mod: {report.generated_mod.name}",
        f"- Mod ID: {report.generated_mod.mod_id or 'not declared'}",
        f"- Modinfo SHA-256: `{report.generated_mod.modinfo_sha256}`",
        f"- Findings tied to this mod: {len(tied)}",
        "",
        "## Evidence",
        "",
    ]
    for item in report.evidence:
        digest = f" SHA-256 `{item.sha256}`" if item.sha256 else ""
        lines.append(
            f"- {item.label}: {'captured' if item.captured else 'not captured'}; "
            f"{item.size if item.size is not None else 'unknown'} bytes;{digest}"
        )
    lines.extend(["", "## Findings tied to the generated mod", ""])
    if tied:
        for item in tied:
            lines.append(
                f"- {item.severity} {item.log_name}:{item.line_number} "
                f"[{item.attribution.value}] {_redact(item.message, replacements)}"
            )
    else:
        lines.append("- No captured error/warning line could be attributed to this mod. This is not runtime proof.")
    lines.extend(["", "## Manual checklist", ""])
    for item in report.checklist:
        lines.append(f"{item.number}. **{item.title}:** {_redact(item.instructions, replacements)}")
    return "\n".join(lines) + "\n"


def _redaction_replacements(
    environment: Civ5UserEnvironment, generated: GeneratedModIdentity
) -> tuple[tuple[str, str], ...]:
    values = {
        str(generated.root): "%GENERATED_MOD_ROOT%",
        generated.root.as_posix(): "%GENERATED_MOD_ROOT%",
        str(environment.mods_path): "%CIV5_MODS%",
        environment.mods_path.as_posix(): "%CIV5_MODS%",
        str(environment.logs_path): "%CIV5_LOGS%",
        environment.logs_path.as_posix(): "%CIV5_LOGS%",
        str(environment.cache_path): "%CIV5_CACHE%",
        environment.cache_path.as_posix(): "%CIV5_CACHE%",
        str(environment.root): "%CIV5_USER_ROOT%",
        environment.root.as_posix(): "%CIV5_USER_ROOT%",
        str(Path.home().resolve()): "%USERPROFILE%",
        Path.home().resolve().as_posix(): "%USERPROFILE%",
    }
    return tuple(
        sorted(
            ((source, target) for source, target in values.items() if source),
            key=lambda item: len(item[0]),
            reverse=True,
        )
    )


def _redact(value: str, replacements: tuple[tuple[str, str], ...]) -> str:
    result = value
    for source, target in replacements:
        result = re.sub(re.escape(source), lambda _match: target, result, flags=re.IGNORECASE)
    return result


def _zip_text(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content.encode("utf-8"))


def _modinfo_files(document: ET.Element) -> tuple[str, ...]:
    files = _first_child(document, "Files")
    if files is None:
        return ()
    values: list[str] = []
    for item in files:
        if _local_name(item.tag).casefold() == "file" and item.text and item.text.strip():
            relative = item.text.strip()
            normalized = relative.replace("\\", "/")
            if (
                normalized
                and not normalized.startswith("/")
                and ".." not in Path(normalized).parts
                and not re.match(r"^[A-Za-z]:", normalized)
            ):
                values.append(relative)
    return tuple(values)


def _useful_identity_token(value: str) -> bool:
    stripped = value.strip()
    return len(stripped) >= 6 and stripped.casefold() not in {
        "civilization",
        "database",
        "generated",
        "modding",
    }


def _first_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    expected = name.casefold()
    return next(
        (child for child in element if _local_name(child.tag).casefold() == expected),
        None,
    )


def _child_text(element: ET.Element, name: str) -> str:
    child = _first_child(element, name)
    return child.text if child is not None and child.text else ""


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True
