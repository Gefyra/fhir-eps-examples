"""Structural checks. This is the only gate: findings here block a pull request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import fhir, metadata as md
from .config import Config, ConfigError, check_ig_pinned
from .discover import (
    CONTRIBUTOR_FILENAME,
    METADATA_FILENAME,
    README_FILENAME,
    Submission,
    discover,
    is_ignored,
)

FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@dataclass
class Finding:
    level: str  # "error" or "warning"
    path: str
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.message}"


@dataclass
class CheckResult:
    findings: list[Finding]
    submissions: list[Submission]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _rel(cfg: Config, path: Path) -> str:
    try:
        return path.resolve().relative_to(cfg.root.resolve()).as_posix()
    except ValueError:  # pragma: no cover - paths are always inside the repo
        return path.as_posix()


def find_key_line(path: Path, key: str) -> int | None:
    """Line of a top level YAML key, used for GitHub annotations."""
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.startswith(f"{key}:") or line.startswith(f"{key} :"):
                return number
    except OSError:
        return None
    return None


def _check_layout(cfg: Config, findings: list[Finding]) -> None:
    """Every file under examples/ must sit in one of the four allowed places."""
    examples = cfg.examples_dir
    if not examples.is_dir():
        findings.append(Finding("error", "examples", "the examples/ folder is missing"))
        return
    slug_re = re.compile(cfg.structure.slugPattern)
    allowed_ext = set(cfg.structure.allowedExtensions)

    seen_contributors: dict[str, str] = {}
    for entry in sorted(examples.iterdir(), key=lambda p: p.name):
        rel = _rel(cfg, entry)
        if entry.is_file():
            findings.append(
                Finding("error", rel, "loose file in examples/; files belong inside a submission folder")
            )
            continue
        if is_ignored(entry.name):
            continue
        if not slug_re.match(entry.name):
            findings.append(
                Finding(
                    "error",
                    rel,
                    f"contributor folder name does not match {cfg.structure.slugPattern}",
                )
            )
        lowered = entry.name.lower()
        if lowered in seen_contributors:
            findings.append(
                Finding("error", rel, f"folder name collides with {seen_contributors[lowered]} (case-insensitive)")
            )
        seen_contributors[lowered] = rel
        _check_contributor_dir(cfg, entry, slug_re, allowed_ext, findings)


def _check_contributor_dir(
    cfg: Config,
    contributor_dir: Path,
    slug_re: re.Pattern[str],
    allowed_ext: set[str],
    findings: list[Finding],
) -> None:
    contributor_file = contributor_dir / CONTRIBUTOR_FILENAME
    if not contributor_file.is_file():
        findings.append(
            Finding("error", _rel(cfg, contributor_dir), f"{CONTRIBUTOR_FILENAME} is missing")
        )
    seen_submissions: dict[str, str] = {}
    submission_count = 0
    for entry in sorted(contributor_dir.iterdir(), key=lambda p: p.name):
        rel = _rel(cfg, entry)
        if entry.is_file():
            if entry.name != CONTRIBUTOR_FILENAME and not is_ignored(entry.name):
                findings.append(
                    Finding(
                        "error",
                        rel,
                        f"only {CONTRIBUTOR_FILENAME} is allowed directly in a contributor folder",
                    )
                )
            continue
        if is_ignored(entry.name):
            continue
        submission_count += 1
        if not slug_re.match(entry.name):
            findings.append(
                Finding("error", rel, f"submission folder name does not match {cfg.structure.slugPattern}")
            )
        lowered = entry.name.lower()
        if lowered in seen_submissions:
            findings.append(
                Finding("error", rel, f"folder name collides with {seen_submissions[lowered]} (case-insensitive)")
            )
        seen_submissions[lowered] = rel
        _check_submission_layout(cfg, entry, allowed_ext, findings)
    if submission_count == 0:
        findings.append(
            Finding("warning", _rel(cfg, contributor_dir), "contributor folder contains no submission")
        )


def _check_submission_layout(
    cfg: Config, submission_dir: Path, allowed_ext: set[str], findings: list[Finding]
) -> None:
    fhir_files = 0
    seen_files: dict[str, str] = {}
    for entry in sorted(submission_dir.iterdir(), key=lambda p: p.name):
        rel = _rel(cfg, entry)
        if entry.is_dir():
            if is_ignored(entry.name):
                continue
            findings.append(
                Finding("error", rel, "subfolders inside a submission are not allowed; keep the folder flat")
            )
            continue
        name = entry.name
        if is_ignored(name):
            continue
        if name in (METADATA_FILENAME, README_FILENAME):
            continue
        suffix = entry.suffix.lower()
        if suffix not in allowed_ext:
            findings.append(
                Finding(
                    "error",
                    rel,
                    "file type not allowed; a submission holds "
                    f"{METADATA_FILENAME}, {README_FILENAME} and "
                    f"{', '.join(sorted(allowed_ext))} files only",
                )
            )
            continue
        if not FILENAME_PATTERN.match(name):
            findings.append(Finding("error", rel, "file name contains characters that are not allowed"))
        lowered = name.lower()
        if lowered in seen_files:
            findings.append(
                Finding("error", rel, f"file name collides with {seen_files[lowered]} (case-insensitive)")
            )
        seen_files[lowered] = rel
        fhir_files += 1
        size = entry.stat().st_size
        if size > cfg.structure.maxFileSizeBytes:
            findings.append(
                Finding(
                    "error",
                    rel,
                    f"file is {size} bytes, the limit is {cfg.structure.maxFileSizeBytes}",
                )
            )
    if fhir_files == 0:
        findings.append(
            Finding(
                "error",
                _rel(cfg, submission_dir),
                "submission contains no FHIR file (" + ", ".join(sorted(allowed_ext)) + ")",
            )
        )
    if fhir_files > cfg.structure.maxFilesPerSubmission:
        findings.append(
            Finding(
                "error",
                _rel(cfg, submission_dir),
                f"submission holds {fhir_files} files, the limit is {cfg.structure.maxFilesPerSubmission}",
            )
        )
    if not (submission_dir / METADATA_FILENAME).is_file():
        findings.append(
            Finding("error", _rel(cfg, submission_dir), f"{METADATA_FILENAME} is missing")
        )
    if not (submission_dir / README_FILENAME).is_file():
        findings.append(
            Finding(
                "warning",
                _rel(cfg, submission_dir),
                f"{README_FILENAME} is missing; a short description helps readers a lot",
            )
        )


def _check_contributor_file(cfg: Config, sub: Submission, findings: list[Finding], done: set[str]) -> None:
    if sub.contributor_slug in done:
        return
    done.add(sub.contributor_slug)
    path = sub.contributor_path
    if not path.is_file():
        return  # already reported by the layout check
    rel = _rel(cfg, path)
    try:
        data = md.load_yaml(path)
    except md.MetadataError as exc:
        findings.append(Finding("error", rel, str(exc)))
        return
    sub.contributor = data
    for message in md.schema_errors(cfg, data, "contributor.schema.json"):
        key = message.split(":", 1)[0] if ":" in message else ""
        findings.append(Finding("error", rel, message, find_key_line(path, key)))


def _check_metadata_file(cfg: Config, sub: Submission, findings: list[Finding]) -> None:
    path = sub.metadata_path
    if not path.is_file():
        return  # already reported by the layout check
    rel = _rel(cfg, path)
    try:
        data = md.load_yaml(path)
    except md.MetadataError as exc:
        findings.append(Finding("error", rel, str(exc)))
        return
    sub.metadata = data
    errors = md.schema_errors(cfg, data, "metadata.schema.json")
    for message in errors:
        key = message.split(":", 1)[0] if ":" in message else ""
        findings.append(Finding("error", rel, message, find_key_line(path, key)))
    if errors:
        return
    try:
        for ig in data.get("igs") or []:
            check_ig_pinned(str(ig), "igs")
    except ConfigError as exc:
        findings.append(Finding("error", rel, str(exc), find_key_line(path, "igs")))
    known_files = {p.name for p in sub.fhir_files}
    for index, rule in enumerate(data.get("knownIssues") or []):
        target = rule.get("file")
        if target and target not in known_files:
            findings.append(
                Finding(
                    "error",
                    rel,
                    f"knownIssues[{index}].file refers to {target!r}, which is not a file of this submission",
                    find_key_line(path, "knownIssues"),
                )
            )


def _check_resources(cfg: Config, sub: Submission, findings: list[Finding]) -> None:
    any_document = False
    parsed = 0
    for path in sub.fhir_files:
        rel = _rel(cfg, path)
        try:
            resource = fhir.load_resource(path)
        except fhir.ResourceError as exc:
            findings.append(Finding("error", rel, str(exc)))
            continue
        if not fhir.resource_type(resource):
            findings.append(Finding("error", rel, "resource has no resourceType"))
            continue
        parsed += 1
        if fhir.is_document_bundle(resource):
            any_document = True
        elif fhir.resource_type(resource) == "Bundle":
            bundle_type = fhir.bundle_type(resource) or "(none)"
            findings.append(
                Finding(
                    "warning",
                    rel,
                    f"Bundle.type is '{bundle_type}', not 'document'; only document Bundles are "
                    "validated against the EPS Bundle profile",
                )
            )
        enforced = md.enforced_profile(cfg, sub.metadata or {}, resource)
        if not fhir.profiles(resource) and not enforced:
            findings.append(
                Finding(
                    "warning",
                    rel,
                    "the root resource declares no meta.profile and no profile is enforced for it; "
                    "rating level 3 (validated against profile) cannot be reached",
                )
            )
    if parsed and not any_document:
        findings.append(
            Finding(
                "warning",
                _rel(cfg, sub.dir),
                "no file is a document Bundle; EPS examples are expected as document Bundles, and "
                "standalone resources are validated only against the profiles they declare",
            )
        )


def run_check(cfg: Config, only_ids: Iterable[str] | None = None) -> CheckResult:
    """Layout checks run over the whole tree; per-submission checks can be narrowed."""
    findings: list[Finding] = []
    _check_layout(cfg, findings)
    submissions = discover(cfg)
    selected = set(only_ids) if only_ids is not None else None
    contributor_done: set[str] = set()
    for sub in submissions:
        if selected is not None and sub.id not in selected:
            continue
        _check_contributor_file(cfg, sub, findings, contributor_done)
        _check_metadata_file(cfg, sub, findings)
        _check_resources(cfg, sub, findings)
    return CheckResult(findings=findings, submissions=submissions)


def github_annotations(result: CheckResult) -> list[str]:
    lines = []
    for finding in result.findings:
        line = f",line={finding.line}" if finding.line else ""
        message = finding.message.replace("\n", " ")
        lines.append(f"::{finding.level} file={finding.path}{line}::{message}")
    return lines


def summary_markdown(result: CheckResult, submission_count: int) -> str:
    marker = "passed" if result.ok else "failed"
    out: list[str] = [f"<!-- check-status: {marker} -->"]
    if result.ok:
        out.append("### Structural checks: ✅ passed")
        out.append("")
        out.append(f"{submission_count} submission(s) in the collection.")
    else:
        out.append("### Structural checks: ❌ failed")
        out.append("")
        out.append(f"{len(result.errors)} finding(s) must be fixed before this pull request can be merged.")
        out.append("")
        out.append("| File | Problem |")
        out.append("|---|---|")
        for finding in result.errors:
            where = f"`{finding.path}`" + (f" (line {finding.line})" if finding.line else "")
            out.append(f"| {where} | {_md_escape(finding.message)} |")
    if result.warnings:
        out.append("")
        out.append(f"<details><summary>{len(result.warnings)} warning(s) — informational only</summary>")
        out.append("")
        out.append("| File | Note |")
        out.append("|---|---|")
        for finding in result.warnings:
            out.append(f"| `{finding.path}` | {_md_escape(finding.message)} |")
        out.append("")
        out.append("</details>")
    out.append("")
    return "\n".join(out)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
