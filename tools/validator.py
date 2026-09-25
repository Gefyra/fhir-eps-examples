"""Running the HL7 Java validator: jar handling, grouping, attribution, crashes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import fhir, igmodel, metadata as md, pii as pii_mod, suppress
from . import profiles as profiles_mod
from . import sections as sections_mod
from .config import Config
from .discover import Submission, discover, find_submission, submitted_on
from .results import (
    Counts,
    FileResult,
    GroupResult,
    Issue,
    RunResult,
    STATUS_NOT_VALIDATED,
    SubmissionResult,
    compute_stars,
    dump_run,
)

ZIP_MAGIC = b"PK\x03\x04"
MIN_JAR_BYTES = 50 * 1024 * 1024
LOG_TAIL_LINES = 40

EXT_FILE = "operationoutcome-file"
EXT_MESSAGE_ID = "operationoutcome-message-id"
EXT_LINE = "operationoutcome-issue-line"
EXT_COL = "operationoutcome-issue-col"
EXT_SOURCE = "operationoutcome-issue-source"


class ValidatorError(Exception):
    """Raised when the validator jar cannot be provided."""


# --------------------------------------------------------------------------- jar


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_jar(cfg: Config) -> Path:
    """Download the pinned validator once and sanity-check the artefact."""
    target = cfg.jar_path()
    if target.is_file() and target.stat().st_size > MIN_JAR_BYTES:
        return target
    url = cfg.validator.downloadUrl.format(version=cfg.validator.version)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".part")
    print(f"downloading validator {cfg.validator.version} from {url}", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=600) as response, temp.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
    except (urllib.error.URLError, OSError) as exc:
        temp.unlink(missing_ok=True)
        raise ValidatorError(f"cannot download {url}: {exc}") from exc
    size = temp.stat().st_size
    if size < MIN_JAR_BYTES or temp.read_bytes()[:4] != ZIP_MAGIC:
        temp.unlink(missing_ok=True)
        raise ValidatorError(f"downloaded file from {url} is not a jar ({size} bytes)")
    if cfg.validator.sha256:
        actual = sha256_file(temp)
        if actual.lower() != cfg.validator.sha256.lower():
            temp.unlink(missing_ok=True)
            raise ValidatorError(
                f"sha256 mismatch for {url}: expected {cfg.validator.sha256}, got {actual}"
            )
    temp.replace(target)
    print(f"validator stored at {target} ({size} bytes)", flush=True)
    return target


def java_version() -> str:
    try:
        out = subprocess.run(
            ["java", "-version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - java missing
        return "unknown"
    first = (out.stderr or out.stdout).splitlines()
    return first[0].strip() if first else "unknown"


# ------------------------------------------------------------------------ groups


@dataclass
class Group:
    index: int
    fhirVersion: str
    igs: tuple[str, ...]
    # Passed as -profile. The validator applies it to every file of the
    # invocation, which is why the grouping works per file.
    profile: str | None
    members: list[tuple[Submission, Path]]

    @property
    def files(self) -> list[Path]:
        return [path for _, path in self.members]

    @property
    def submissions(self) -> list[Submission]:
        seen: dict[str, Submission] = {}
        for sub, _ in self.members:
            seen.setdefault(sub.id, sub)
        return list(seen.values())


def build_groups(cfg: Config, submissions: Iterable[Submission]) -> list[Group]:
    """One validator invocation per (FHIR version, effective IG set, enforced profile).

    Document Bundles get the enforced profile, every other file gets none, so
    a submission that mixes both ends up in two groups.
    """
    buckets: dict[tuple[str, tuple[str, ...], str], list[tuple[Submission, Path]]] = {}
    for sub in submissions:
        version = str(sub.metadata.get("fhirVersion") or cfg.defaultFhirVersion)
        igs = md.effective_igs(sub, cfg)
        for path in sub.fhir_files:
            profile = md.enforced_profile_for_file(cfg, sub, path) or ""
            buckets.setdefault((version, igs, profile), []).append((sub, path))
    groups = []
    for index, key in enumerate(sorted(buckets), start=1):
        version, igs, profile = key
        groups.append(
            Group(
                index=index,
                fhirVersion=version,
                igs=igs,
                profile=profile or None,
                members=buckets[key],
            )
        )
    return groups


def build_command(
    cfg: Config, group: Group, out_json: Path, out_html: Path, offline: bool = False
) -> list[str]:
    jar = cfg.jar_path()
    command = ["java", *cfg.validator.javaArgs, "-jar", str(jar), "-version", group.fhirVersion]
    for ig in group.igs:
        command += ["-ig", ig]
    if group.profile:
        command += ["-profile", group.profile]
    command += ["-tx", "n/a" if offline else cfg.terminology.server]
    if not offline:
        command += ["-txCache", str(cfg.tx_cache_dir())]
    command += ["-output", str(out_json), "-html-output", str(out_html)]
    command += list(cfg.validatorFlags)
    command += [str(path.resolve()) for path in group.files]
    return command


def run_group(cfg: Config, group: Group, out_dir: Path, offline: bool = False) -> GroupResult:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_json = raw_dir / f"group-{group.index}.json"
    out_html = raw_dir / f"group-{group.index}.html"
    log_path = raw_dir / f"group-{group.index}.log"
    cmd_path = raw_dir / f"group-{group.index}.cmd.txt"
    if not offline:
        cfg.tx_cache_dir().mkdir(parents=True, exist_ok=True)

    command = build_command(cfg, group, out_json, out_html, offline=offline)
    cmd_path.write_text(" \\\n  ".join(command) + "\n", encoding="utf-8")

    result = GroupResult(
        index=group.index,
        fhirVersion=group.fhirVersion,
        igs=list(group.igs),
        files=[str(p) for p in group.files],
        profile=group.profile,
        command=command,
    )
    started = time.monotonic()
    timeout = cfg.validator.timeoutMinutes * 60
    enforced = f", enforced profile {group.profile}" if group.profile else ""
    print(
        f"validating group {group.index}: {len(group.files)} file(s), "
        f"IGs {', '.join(group.igs) or 'none'}{enforced}",
        flush=True,
    )
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
                cwd=cfg.root,
            )
        result.exitCode = process.returncode
    except subprocess.TimeoutExpired:
        result.crashed = True
        result.reason = f"the validator did not finish within {cfg.validator.timeoutMinutes} minutes"
    except OSError as exc:
        result.crashed = True
        result.reason = f"the validator could not be started: {exc}"
    result.durationSeconds = round(time.monotonic() - started, 1)
    result.logTail = tail(log_path, LOG_TAIL_LINES)

    if not result.crashed and not out_json.is_file():
        result.crashed = True
        result.reason = (
            f"the validator exited with code {result.exitCode} and produced no output file"
        )
    return result


# Log fragments that identify "the terminology server did not answer" crashes.
TERMINOLOGY_FAILURE_MARKERS = (
    "Unable to connect to terminology server",
    "Error fetching the server's capability statement",
    "TerminologyServiceException",
)
RETRY_DELAY_SECONDS = 15
_sleep = time.sleep  # replaced in tests


def terminology_failure(log_path: Path) -> bool:
    """True when the validator log says the terminology server was unreachable."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in text for marker in TERMINOLOGY_FAILURE_MARKERS)


def _keep_attempt_log(log_path: Path, attempt: int) -> None:
    """Preserve the log of a failed attempt next to the final one."""
    if log_path.is_file():
        log_path.replace(log_path.with_name(f"{log_path.stem}.attempt-{attempt}.log"))


def run_group_with_retries(
    cfg: Config, group: Group, out_dir: Path, offline: bool = False
) -> GroupResult:
    """run_group, repeated when the terminology server is why it crashed.

    tx.fhir.org times out now and then. Such a crash is retried
    cfg.terminology.retries times; if the server still does not answer and
    cfg.terminology.fallbackToOffline is set, the group is validated once more
    with -tx n/a and marked, so that every report can say that terminology
    checks were skipped. Any other crash is returned as is.
    """
    log_path = out_dir / "raw" / f"group-{group.index}.log"
    result = run_group(cfg, group, out_dir, offline=offline)
    attempts = 1
    while (
        result.crashed
        and not offline
        and attempts <= cfg.terminology.retries
        and terminology_failure(log_path)
    ):
        _keep_attempt_log(log_path, attempts)
        delay = RETRY_DELAY_SECONDS * attempts
        print(
            f"group {group.index}: terminology server unreachable, retrying in {delay}s "
            f"(retry {attempts} of {cfg.terminology.retries})",
            file=sys.stderr,
            flush=True,
        )
        _sleep(delay)
        result = run_group(cfg, group, out_dir, offline=offline)
        attempts += 1
    if (
        result.crashed
        and not offline
        and cfg.terminology.fallbackToOffline
        and terminology_failure(log_path)
    ):
        _keep_attempt_log(log_path, attempts)
        print(
            f"group {group.index}: terminology server unreachable after {attempts} attempt(s); "
            "validating without terminology services (-tx n/a)",
            file=sys.stderr,
            flush=True,
        )
        result = run_group(cfg, group, out_dir, offline=True)
        attempts += 1
        result.terminologyFallback = True
    result.attempts = attempts
    return result


def tail(path: Path, lines: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:  # pragma: no cover
        return []
    return content[-lines:]


# ------------------------------------------------------------------------ parsing


def _extension_value(node: dict[str, Any], suffix: str) -> Any:
    for extension in node.get("extension") or []:
        if not isinstance(extension, dict):
            continue
        url = str(extension.get("url", ""))
        if url.rsplit("/", 1)[-1] != suffix:
            continue
        for key, value in extension.items():
            if key.startswith("value"):
                return value
    return None


def _issue_from(node: dict[str, Any]) -> Issue:
    details = node.get("details") or {}
    text = details.get("text") if isinstance(details, dict) else None
    expression = [str(e) for e in node.get("expression") or []]
    if not expression:
        expression = [str(e) for e in node.get("location") or []]
    line = _extension_value(node, EXT_LINE)
    col = _extension_value(node, EXT_COL)
    return Issue(
        severity=str(node.get("severity", "information")),
        code=str(node.get("code", "")),
        messageId=str(_extension_value(node, EXT_MESSAGE_ID) or ""),
        details=str(text or node.get("diagnostics") or ""),
        expression=expression,
        line=int(line) if isinstance(line, (int, float, str)) and str(line).isdigit() else None,
        col=int(col) if isinstance(col, (int, float, str)) and str(col).isdigit() else None,
        source=str(_extension_value(node, EXT_SOURCE) or ""),
    )


def parse_output(path: Path) -> list[tuple[str | None, list[Issue]]]:
    """Split the validator output into (source file, issues) pairs.

    Accepts either a Bundle of OperationOutcomes or a single OperationOutcome.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    outcomes: list[dict[str, Any]] = []
    if data.get("resourceType") == "Bundle":
        for entry in data.get("entry") or []:
            resource = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(resource, dict) and resource.get("resourceType") == "OperationOutcome":
                outcomes.append(resource)
    elif data.get("resourceType") == "OperationOutcome":
        outcomes.append(data)
    else:
        raise ValueError(f"{path}: unexpected resourceType {data.get('resourceType')!r}")

    parsed: list[tuple[str | None, list[Issue]]] = []
    for outcome in outcomes:
        source = _extension_value(outcome, EXT_FILE)
        issues = [_issue_from(i) for i in outcome.get("issue") or [] if isinstance(i, dict)]
        parsed.append((str(source) if source else None, issues))
    return parsed


def attribute(
    parsed: list[tuple[str | None, list[Issue]]], files: list[Path]
) -> tuple[dict[Path, list[Issue]], list[Issue]]:
    """Map each OperationOutcome to the file it belongs to.

    Exact realpath match first, then a suffix match on the reported path. Whatever
    is left over becomes an infrastructure warning rather than being dropped.
    """
    by_real = {str(Path(p).resolve()): p for p in files}
    attributed: dict[Path, list[Issue]] = {}
    unattributed: list[Issue] = []
    for source, issues in parsed:
        target: Path | None = None
        if source:
            candidate = str(Path(source).resolve()) if os.path.isabs(source) else None
            if candidate and candidate in by_real:
                target = by_real[candidate]
            else:
                normalised = source.replace("\\", "/")
                for real, path in by_real.items():
                    if real.replace("\\", "/").endswith(normalised.lstrip("./")):
                        target = path
                        break
        if target is None:
            if len(parsed) == 1 and len(files) == 1:
                target = files[0]
            else:
                unattributed.extend(issues)
                continue
        attributed.setdefault(target, []).extend(issues)
    return attributed, unattributed


# --------------------------------------------------------------------- run entry


def _select(cfg: Config, targets: list[str] | None) -> list[Submission]:
    everything = discover(cfg)
    md.load_all(cfg, everything)
    if targets is None:
        return everything
    wanted: list[Submission] = []
    for target in targets:
        found = find_submission(cfg, target)
        if found is None:
            print(f"warning: no submission found for {target!r}", file=sys.stderr)
            continue
        md.load_all(cfg, [found])
        if all(found.id != s.id for s in wanted):
            wanted.append(found)
    return wanted


def _file_result(cfg: Config, sub: Submission, path: Path, model: dict[str, Any]) -> FileResult:
    rel = path.resolve().relative_to(cfg.root.resolve()).as_posix()
    result = FileResult(name=path.name, path=rel)
    try:
        resource = fhir.load_resource(path)
    except fhir.ResourceError as exc:
        result.reason = str(exc)
        return result
    result.resourceType = fhir.resource_type(resource)
    result.bundleType = fhir.bundle_type(resource)
    profiles: list[str] = []
    for node in fhir.iter_resources(resource):
        profiles.extend(fhir.profiles(node))
    result.profiles = sorted(set(profiles))
    result.rootProfiles = fhir.profiles(resource)
    result.enforcedProfile = md.enforced_profile(cfg, sub.metadata, resource)
    result.resources = fhir.resource_summaries(resource)
    result.compositions = fhir.summarize_compositions(resource)
    sections_mod.annotate(model, result.compositions)
    return result


def _git_info(root: Path) -> dict[str, str]:
    def run(*args: str) -> str:
        try:
            out = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):  # pragma: no cover
            return ""
        return out.stdout.strip()

    return {"sha": run("rev-parse", "HEAD"), "ref": run("rev-parse", "--abbrev-ref", "HEAD")}


def run_validation(
    cfg: Config, out_dir: Path, targets: list[str] | None = None, offline: bool = False
) -> int:
    """Validate everything selected. Returns 0, or 2 when the validator crashed."""
    submissions = _select(cfg, targets)
    if not submissions:
        print("nothing to validate")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_jar(cfg)
    jar = cfg.jar_path()

    groups = build_groups(cfg, submissions)
    run = RunResult(
        generatedAt=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        git=_git_info(cfg.root),
        validator={
            "version": cfg.validator.version,
            "jarSha256": sha256_file(jar),
            "javaVersion": java_version(),
        },
        terminology="n/a (offline)" if offline else cfg.terminology.server,
        defaultIgs={k: list(v) for k, v in cfg.defaultIgs.items()},
        scope="all" if targets is None else "selected",
    )

    issues_by_file: dict[Path, list[Issue]] = {}
    not_validated: dict[Path, str] = {}
    infrastructure: list[Issue] = []

    for group in groups:
        group_result = run_group_with_retries(cfg, group, out_dir, offline=offline)
        run.groups.append(group_result)
        if group_result.crashed:
            run.crashed = True
            for path in group.files:
                not_validated[path] = group_result.reason
            print(f"group {group.index} crashed: {group_result.reason}", file=sys.stderr)
            continue
        out_json = out_dir / "raw" / f"group-{group.index}.json"
        try:
            parsed = parse_output(out_json)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            group_result.crashed = True
            group_result.reason = f"the validator output could not be parsed: {exc}"
            run.crashed = True
            for path in group.files:
                not_validated[path] = group_result.reason
            print(f"group {group.index} crashed: {group_result.reason}", file=sys.stderr)
            continue
        attributed, leftovers = attribute(parsed, group.files)
        issues_by_file.update(attributed)
        for path in group.files:
            if path not in attributed:
                not_validated[path] = (
                    "the validator produced no OperationOutcome for this file"
                )
        for issue in leftovers:
            issue.severity = "warning"
            infrastructure.append(issue)

    group_of = {path: group.index for group in groups for path in group.files}
    model = igmodel.load_model()
    run.model = {"package": model.get("package"), "version": model.get("version")}
    for sub in submissions:
        resolved = md.resolve(sub, cfg)
        entry = SubmissionResult(
            id=sub.id,
            contributor=sub.contributor_slug,
            slug=sub.slug,
            title=resolved.title,
            origin=resolved.origin,
            description=resolved.description,
            fhirVersion=resolved.fhirVersion,
            igs=list(resolved.igs),
            country=resolved.country,
            enforceProfile=resolved.enforceProfile,
            custodian=resolved.custodian,
            source=resolved.source,
            review=resolved.review,
            submittedOn=submitted_on(sub, cfg.root),
            groups=sorted({group_of[path] for path in sub.fhir_files if path in group_of}),
        )
        for path in sub.fhir_files:
            file_result = _file_result(cfg, sub, path, model)
            file_result.group = group_of.get(path)
            if path in not_validated:
                file_result.status = STATUS_NOT_VALIDATED
                file_result.reason = not_validated[path]
            else:
                file_result.status = "valid"
                file_result.issues = issues_by_file.get(path, [])
            entry.files.append(file_result)
            _write_outcome(out_dir, file_result)
        stale = suppress.apply(suppress.parse_rules(resolved.knownIssues), entry.files)
        entry.staleSuppressions = stale
        if cfg.piiEnabled:
            entry.pii = pii_mod.scan_submission(sub)
        entry.recompute()
        entry.stars, entry.starReasons = compute_stars(entry)
        run.submissions.append(entry)

    run.submissions.sort(key=lambda s: s.id)
    run.sections = sections_mod.build_index(run, model)
    run.profiles = profiles_mod.build_index(run, model)
    fallback_groups = [g.index for g in run.groups if g.terminologyFallback]
    if fallback_groups:
        run.terminologyFallback = True
        run.terminology = (
            f"{cfg.terminology.server} unreachable; {len(fallback_groups)} of {len(run.groups)} "
            "group(s) validated without terminology services"
        )
        print(
            "warning: terminology server unreachable; validated without terminology services "
            f"(group(s) {', '.join(map(str, fallback_groups))})",
            file=sys.stderr,
        )
    if infrastructure:
        print(
            f"warning: {len(infrastructure)} validator issue(s) could not be attributed to a file",
            file=sys.stderr,
        )
    dump_run(run, out_dir / "results.json")

    totals = run.totals()
    print(
        "\n"
        + ", ".join(f"{count} {status}" for status, count in totals.items() if count)
        + f" · {len(run.groups)} group(s) · results in {out_dir}/results.json"
    )
    return 2 if run.crashed else 0


def _write_outcome(out_dir: Path, file_result: FileResult) -> None:
    """One OperationOutcome per input file, mirroring the examples/ layout."""
    target = out_dir / Path(file_result.path).relative_to("examples")
    target = target.with_name(target.name + ".oo.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    outcome = {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": issue.severity,
                "code": issue.code or "processing",
                "details": {"text": issue.details},
                "expression": issue.expression,
                "extension": [
                    {
                        "url": "http://hl7.org/fhir/StructureDefinition/operationoutcome-message-id",
                        "valueString": issue.messageId,
                    }
                ]
                if issue.messageId
                else [],
            }
            for issue in file_result.issues
        ]
        or [
            {
                "severity": "information",
                "code": "informational",
                "details": {"text": "No issues reported."},
            }
        ],
    }
    target.write_text(json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
