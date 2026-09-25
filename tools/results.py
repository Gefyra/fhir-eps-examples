"""The result model written to results/results.json and read by the reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

RESULTS_SCHEMA_VERSION = 1

STATUS_VALID = "valid"
STATUS_WARNINGS = "warnings"
STATUS_ERRORS = "errors"
STATUS_NOT_VALIDATED = "not-validated"

# Worst first; used when a submission aggregates its files.
STATUS_ORDER = [STATUS_NOT_VALIDATED, STATUS_ERRORS, STATUS_WARNINGS, STATUS_VALID]

STATUS_ICON = {
    STATUS_VALID: "✅",
    STATUS_WARNINGS: "⚠️",
    STATUS_ERRORS: "❌",
    STATUS_NOT_VALIDATED: "🚫",
}

STATUS_LABEL = {
    STATUS_VALID: "valid",
    STATUS_WARNINGS: "warnings",
    STATUS_ERRORS: "errors",
    STATUS_NOT_VALIDATED: "not validated",
}

STAR_LABELS = {
    1: "Real-world example",
    2: "Reviewed by a subject matter expert",
    3: "Validated against a profile",
    4: "Consensus example",
}


@dataclass
class Issue:
    severity: str  # fatal | error | warning | information
    code: str = ""
    messageId: str = ""
    details: str = ""
    expression: list[str] = field(default_factory=list)
    line: int | None = None
    col: int | None = None
    source: str = ""
    suppressed: bool = False
    justification: str = ""

    @property
    def location(self) -> str:
        if self.expression:
            return ", ".join(self.expression)
        if self.line:
            return f"Line {self.line}, Column {self.col or 0}"
        return ""

    def counts_as_error(self) -> bool:
        return self.severity in ("fatal", "error") and not self.suppressed


@dataclass
class Counts:
    errors: int = 0
    warnings: int = 0
    information: int = 0
    suppressed: int = 0

    def add(self, other: "Counts") -> None:
        self.errors += other.errors
        self.warnings += other.warnings
        self.information += other.information
        self.suppressed += other.suppressed

    @property
    def total(self) -> int:
        return self.errors + self.warnings + self.information + self.suppressed


def count_issues(issues: Iterable[Issue]) -> Counts:
    counts = Counts()
    for issue in issues:
        if issue.suppressed:
            counts.suppressed += 1
        elif issue.severity in ("fatal", "error"):
            counts.errors += 1
        elif issue.severity == "warning":
            counts.warnings += 1
        else:
            counts.information += 1
    return counts


@dataclass
class FileResult:
    name: str
    path: str  # repository relative
    resourceType: str | None = None
    # Bundle.type when the root resource is a Bundle.
    bundleType: str | None = None
    # Every profile declared anywhere in the file.
    profiles: list[str] = field(default_factory=list)
    # meta.profile of the root resource only; what rating level 3 looks at.
    rootProfiles: list[str] = field(default_factory=list)
    # The profile passed with -profile for this file (document Bundles only).
    enforcedProfile: str | None = None
    # Index of the validator group this file was validated in.
    group: int | None = None
    status: str = STATUS_NOT_VALIDATED
    reason: str = ""
    issues: list[Issue] = field(default_factory=list)
    counts: Counts = field(default_factory=Counts)
    # Root resource and Bundle entries: resourceType, id, fullUrl, profiles.
    resources: list[dict[str, Any]] = field(default_factory=list)
    # Every Composition with its sections, see fhir.summarize_compositions.
    compositions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def validated_profiles(self) -> list[str]:
        """Declared root profiles plus the enforced one, without duplicates."""
        out = list(dict.fromkeys(self.rootProfiles))
        if self.enforcedProfile and self.enforcedProfile not in out:
            out.append(self.enforcedProfile)
        return out

    def recompute(self) -> None:
        self.counts = count_issues(self.issues)
        if self.status == STATUS_NOT_VALIDATED:
            return
        self.status = status_from_counts(self.counts)


def status_from_counts(counts: Counts) -> str:
    if counts.errors:
        return STATUS_ERRORS
    if counts.warnings:
        return STATUS_WARNINGS
    return STATUS_VALID


def worst_status(statuses: Iterable[str]) -> str:
    seen = set(statuses)
    for status in STATUS_ORDER:
        if status in seen:
            return status
    return STATUS_VALID


@dataclass
class StaleSuppression:
    index: int
    matcher: dict[str, str]
    justification: str


@dataclass
class SubmissionResult:
    id: str
    contributor: str
    slug: str
    title: str
    origin: str
    description: str | None = None
    fhirVersion: str = "4.0.1"
    igs: list[str] = field(default_factory=list)
    country: str | None = None
    enforceProfile: bool = True
    custodian: dict[str, str] = field(default_factory=dict)
    source: dict[str, str] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    submittedOn: str | None = None
    # A submission spans two groups when only some of its files are document
    # Bundles: the enforced profile applies to every file of an invocation.
    groups: list[int] = field(default_factory=list)
    status: str = STATUS_NOT_VALIDATED
    counts: Counts = field(default_factory=Counts)
    stars: int = 0
    starReasons: list[str] = field(default_factory=list)
    files: list[FileResult] = field(default_factory=list)
    staleSuppressions: list[StaleSuppression] = field(default_factory=list)
    pii: list[dict[str, str]] = field(default_factory=list)

    def recompute(self) -> None:
        counts = Counts()
        for file_result in self.files:
            file_result.recompute()
            counts.add(file_result.counts)
        self.counts = counts
        self.status = worst_status(f.status for f in self.files) if self.files else STATUS_NOT_VALIDATED

    @property
    def all_issues(self) -> list[Issue]:
        return [issue for file_result in self.files for issue in file_result.issues]


@dataclass
class GroupResult:
    index: int
    fhirVersion: str
    igs: list[str]
    files: list[str]
    # Passed as -profile; None when the group holds no document Bundle.
    profile: str | None = None
    exitCode: int | None = None
    durationSeconds: float = 0.0
    crashed: bool = False
    reason: str = ""
    logTail: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    # How many validator invocations this group needed (1 = no retry).
    attempts: int = 1
    # True when the terminology server was unreachable and the group was
    # validated with -tx n/a instead.
    terminologyFallback: bool = False


@dataclass
class RunResult:
    schemaVersion: int = RESULTS_SCHEMA_VERSION
    generatedAt: str = ""
    git: dict[str, str] = field(default_factory=dict)
    validator: dict[str, str] = field(default_factory=dict)
    terminology: str = ""
    defaultIgs: dict[str, list[str]] = field(default_factory=dict)
    scope: str = "all"
    crashed: bool = False
    # True when at least one group ran without terminology services.
    terminologyFallback: bool = False
    groups: list[GroupResult] = field(default_factory=list)
    submissions: list[SubmissionResult] = field(default_factory=list)
    # Package and version of tools/data/eps-model.json used for the indexes.
    model: dict[str, Any] = field(default_factory=dict)
    # Built by tools.sections and tools.profiles, see there.
    sections: list[dict[str, Any]] = field(default_factory=list)
    profiles: dict[str, Any] = field(default_factory=dict)

    def by_status(self, status: str) -> list[SubmissionResult]:
        return [s for s in self.submissions if s.status == status]

    def totals(self) -> dict[str, int]:
        return {status: len(self.by_status(status)) for status in STATUS_ORDER}


def compute_stars(sub: SubmissionResult) -> tuple[int, list[str]]:
    """Highest achieved level; every level carries the reason it was granted."""
    reasons: list[str] = []
    level = 0
    if sub.origin in ("real-world", "derived-from-real"):
        level = max(level, 1)
        reasons.append(f"1 — {STAR_LABELS[1]} (origin: {sub.origin})")
    if sub.review.get("smeReviewed"):
        level = max(level, 2)
        reviewer = sub.review.get("reviewer")
        suffix = f" by {reviewer}" if reviewer else ""
        reasons.append(f"2 — {STAR_LABELS[2]}{suffix}")
    if (
        sub.files
        and all(f.validated_profiles for f in sub.files)
        and sub.counts.errors == 0
        and sub.status != STATUS_NOT_VALIDATED
    ):
        level = max(level, 3)
        reasons.append(f"3 — {STAR_LABELS[3]} ({_profile_summary(sub.files)}; no unsuppressed errors)")
    if sub.review.get("consensus"):
        level = max(level, 4)
        reasons.append(f"4 — {STAR_LABELS[4]}")
    return level, reasons


def profile_label(canonical: str) -> str:
    """Last path segment, version kept: '.../bundle-eu-eps' -> 'bundle-eu-eps'."""
    url, _, version = canonical.partition("|")
    name = url.rstrip("/").rsplit("/", 1)[-1] or url
    return f"{name}|{version}" if version else name


def _profile_summary(files: list[FileResult]) -> str:
    """'bundle-eu-eps, enforced; Bundle-uv-ips, declared' for the rating reason."""
    enforced = list(dict.fromkeys(f.enforcedProfile for f in files if f.enforcedProfile))
    declared = list(dict.fromkeys(p for f in files for p in f.rootProfiles))
    parts = []
    if enforced:
        parts.append(", ".join(profile_label(p) for p in enforced) + ", enforced")
    if declared:
        parts.append(", ".join(profile_label(p) for p in declared) + ", declared")
    return "; ".join(parts)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    return value


def dump_run(run: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(run), indent=2, ensure_ascii=False, default=_to_jsonable) + "\n",
        encoding="utf-8",
    )


def _issue(data: dict[str, Any]) -> Issue:
    return Issue(**{k: v for k, v in data.items() if k in Issue.__dataclass_fields__})


def _file(data: dict[str, Any]) -> FileResult:
    payload = {k: v for k, v in data.items() if k in FileResult.__dataclass_fields__}
    payload["issues"] = [_issue(i) for i in data.get("issues", [])]
    payload["counts"] = Counts(**data.get("counts", {}))
    return FileResult(**payload)


def _submission(data: dict[str, Any]) -> SubmissionResult:
    payload = {k: v for k, v in data.items() if k in SubmissionResult.__dataclass_fields__}
    payload["files"] = [_file(f) for f in data.get("files", [])]
    payload["counts"] = Counts(**data.get("counts", {}))
    payload["staleSuppressions"] = [
        StaleSuppression(**s) for s in data.get("staleSuppressions", [])
    ]
    return SubmissionResult(**payload)


def load_run(path: Path) -> RunResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return run_from_dict(data)


def run_from_dict(data: dict[str, Any]) -> RunResult:
    payload = {k: v for k, v in data.items() if k in RunResult.__dataclass_fields__}
    payload["groups"] = [
        GroupResult(**{k: v for k, v in g.items() if k in GroupResult.__dataclass_fields__})
        for g in data.get("groups", [])
    ]
    payload["submissions"] = [_submission(s) for s in data.get("submissions", [])]
    return RunResult(**payload)
