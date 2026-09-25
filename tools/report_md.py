"""Markdown rendering: the sticky pull request comment and the job summary."""

from __future__ import annotations

from typing import Any, Iterable

from .baseline import describe
from .config import Config
from .results import (
    Issue,
    profile_label,
    RunResult,
    STATUS_ERRORS,
    STATUS_ICON,
    STATUS_LABEL,
    STATUS_NOT_VALIDATED,
    STATUS_ORDER,
    STATUS_VALID,
    STATUS_WARNINGS,
    SubmissionResult,
)

MARKER_START = "<!-- fhir-eps-validation -->"
MARKER_END = "<!-- /fhir-eps-validation -->"
SEVERITY_ICON = {"fatal": "❌", "error": "❌", "warning": "⚠️", "information": "ℹ️"}


def ig_label(ig: str) -> str:
    package, _, version = ig.partition("#")
    return f"{package.rsplit('.', 1)[-1]} {version}" if version else package


def escape(text: str, limit: int = 300) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned.replace("|", "\\|")


def status_cell(status: str) -> str:
    return f"{STATUS_ICON.get(status, '')} {STATUS_LABEL.get(status, status)}"


def _all_igs(run: RunResult) -> list[str]:
    igs: set[str] = set()
    for submission in run.submissions:
        igs.update(submission.igs)
    return sorted(igs)


def _header(cfg: Config, run: RunResult, run_url: str | None) -> list[str]:
    igs = ", ".join(ig_label(ig) for ig in _all_igs(run)) or "none"
    terminology = run.terminology or cfg.terminology.server
    scope = (
        f"{len(run.submissions)} submission(s) validated"
        if run.scope == "all"
        else f"{len(run.submissions)} submission(s) validated (changed only)"
    )
    parts = [
        f"Validator {run.validator.get('version', cfg.validator.version)}",
        terminology.replace("https://", ""),
        f"IGs: {igs}",
    ]
    enforced = sorted({g.profile for g in run.groups if g.profile})
    if enforced:
        parts.append(
            "document Bundles also against " + ", ".join(f"`{profile_label(p)}`" for p in enforced)
        )
    if run_url:
        parts.append(f"[workflow run]({run_url})")
    parts.append(scope)
    return [MARKER_START, "## FHIR validation results", "", " · ".join(parts), ""]


def _summary_table(run: RunResult, delta: dict[str, dict[str, Any]]) -> list[str]:
    lines = [
        "| Submission | FHIR | Status | Errors | Warnings | Info | Suppressed | vs. main |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for submission in sorted(run.submissions, key=_severity_key):
        counts = submission.counts
        lines.append(
            f"| `{submission.id}` | {submission.fhirVersion} | {status_cell(submission.status)} "
            f"| {counts.errors} | {counts.warnings} | {counts.information} | {counts.suppressed} "
            f"| {describe(delta.get(submission.id))} |"
        )
    lines.append("")
    return lines


def _severity_key(submission: SubmissionResult) -> tuple[int, str]:
    return (STATUS_ORDER.index(submission.status), submission.id)


def _issue_rows(issues: Iterable[Issue], file_name: str, limit: int) -> list[str]:
    rows = []
    for issue in list(issues)[:limit]:
        rows.append(
            f"| {SEVERITY_ICON.get(issue.severity, '')} {issue.severity} | `{file_name}` "
            f"| {escape(issue.location, 120)} | `{issue.messageId or '-'}` | {escape(issue.details)} |"
        )
    return rows


def _details_block(submission: SubmissionResult, max_issues: int) -> str:
    interesting = [
        (file_result, issue)
        for file_result in submission.files
        for issue in file_result.issues
        if issue.severity in ("fatal", "error", "warning") and not issue.suppressed
    ]
    interesting.sort(key=lambda pair: 0 if pair[1].severity in ("fatal", "error") else 1)
    if not interesting and submission.status != STATUS_NOT_VALIDATED:
        return ""
    counts = submission.counts
    headline = f"{counts.errors} error(s), {counts.warnings} warning(s)"
    shown = interesting[:max_issues]
    more = len(interesting) - len(shown)
    lines = [
        f"<details><summary>{STATUS_ICON.get(submission.status, '')} {submission.id} — {headline}"
        + (f" (top {len(shown)} shown)" if more > 0 else "")
        + "</summary>",
        "",
    ]
    if submission.status == STATUS_NOT_VALIDATED:
        reasons = sorted({f.reason for f in submission.files if f.reason})
        lines.append("This submission was not validated:")
        lines.append("")
        for reason in reasons:
            lines.append(f"- {escape(reason, 400)}")
        lines.append("")
    if shown:
        lines.append("| Sev | File | Location | Message id | Details |")
        lines.append("|---|---|---|---|---|")
        for file_result, issue in shown:
            lines.extend(_issue_rows([issue], file_result.name, 1))
        if more > 0:
            lines.append("")
            lines.append(f"{more} further finding(s) — see the `validation-results` artifact.")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return "\n".join(lines)


def _suppressions_section(run: RunResult) -> list[str]:
    rows = []
    for submission in run.submissions:
        matched = submission.counts.suppressed
        stale = len(submission.staleSuppressions)
        if not matched and not stale:
            continue
        note = "—" if not stale else f"{stale} rule(s) match nothing any more"
        rows.append(f"| `{submission.id}` | {matched} | {note} |")
    if not rows:
        return []
    return [
        "### Known-issue suppressions",
        "",
        "| Submission | Suppressed findings | Stale rules |",
        "|---|---|---|",
        *rows,
        "",
    ]


def _pii_section(run: RunResult) -> list[str]:
    rows = []
    for submission in run.submissions:
        for finding in submission.pii[:5]:
            rows.append(
                f"| `{submission.id}` | `{finding['file']}` | `{escape(finding['location'], 80)}` "
                f"| {escape(finding['note'], 160)} |"
            )
    if not rows:
        return []
    return [
        "### Possible identifiable data (heuristic, warn-only)",
        "",
        "| Submission | File | Location | Note |",
        "|---|---|---|---|",
        *rows,
        "",
        "These are guesses, not findings. Please double-check that the example is de-identified.",
        "",
    ]


def _footer(run: RunResult, baseline: RunResult | None) -> list[str]:
    lines = [
        "> Validation errors do not block merging; only the structural checks do. "
        "Full details are in the `validation-results` artifact of this run.",
    ]
    if baseline is not None:
        generated = (baseline.generatedAt or "").split("T")[0] or "an earlier run"
        lines.append(f"> Baseline: results from main, {generated}.")
    if run.terminologyFallback:
        lines.append(
            "> ⚠️ The terminology server was unreachable, so this run validated **without "
            "terminology services** (no LOINC, SNOMED CT or UCUM checks). Expect fewer findings "
            "than usual; a later run with a reachable server may report more."
        )
    if run.crashed:
        lines.append(
            "> ⚠️ The validator crashed for at least one group; the affected files are reported "
            "as not validated. This is an infrastructure problem, not a problem with the example."
        )
    lines.append("")
    lines.append(MARKER_END)
    return lines


def render_pr_comment(
    cfg: Config,
    run: RunResult,
    delta: dict[str, dict[str, Any]],
    check_summary: str | None = None,
    run_url: str | None = None,
    baseline: RunResult | None = None,
) -> str:
    """Header, checks and the table are always included; details fill the budget."""
    checks_failed = bool(check_summary and "<!-- check-status: failed -->" in check_summary)

    head = _header(cfg, run, run_url)
    if check_summary:
        body = check_summary.replace("<!-- check-status: failed -->", "").replace(
            "<!-- check-status: passed -->", ""
        )
        head.append(body.strip())
        head.append("")
    else:
        head.append("### Structural checks: ✅ passed")
        head.append("")

    if checks_failed:
        head.append(
            "The structural checks must pass before the FHIR validation results are meaningful, "
            "so the rest of this report is omitted."
        )
        head.append("")
        return "\n".join(head + _footer(run, baseline)) + "\n"

    if not run.submissions:
        head.append(
            "No FHIR validation results in this comment: either this pull request touches no "
            "submission, or the validation job has not finished yet. In the second case this "
            "comment is updated as soon as it has."
        )
        head.append("")
        return "\n".join(head + _footer(run, baseline)) + "\n"

    head.extend(_summary_table(run, delta))
    tail = _suppressions_section(run) + _pii_section(run) + _footer(run, baseline)

    budget = cfg.report.prCommentBudgetChars
    fixed = len("\n".join(head)) + len("\n".join(tail)) + 2
    blocks: list[str] = []
    omitted = 0
    ordered = sorted(run.submissions, key=_severity_key)
    used = fixed
    for submission in ordered:
        if submission.status == STATUS_VALID:
            continue
        block = _details_block(submission, cfg.report.maxIssuesPerSubmissionInComment)
        if not block:
            continue
        if used + len(block) + 80 > budget:
            omitted += 1
            continue
        blocks.append(block)
        used += len(block)
    if omitted:
        blocks.append(
            f"{omitted} further submission(s) with findings are not shown here — "
            "see the `validation-results` artifact.\n"
        )
    return "\n".join(head + blocks + tail) + "\n"


def render_job_summary(cfg: Config, run: RunResult, delta: dict[str, dict[str, Any]]) -> str:
    totals = run.totals()
    lines = [
        "## FHIR validation results",
        "",
        f"Validator {run.validator.get('version', cfg.validator.version)} · "
        f"terminology {run.terminology} · generated {run.generatedAt}",
        "",
        "| Status | Submissions |",
        "|---|---|",
    ]
    for status in STATUS_ORDER:
        lines.append(f"| {status_cell(status)} | {totals.get(status, 0)} |")
    lines.append("")
    if run.terminologyFallback:
        lines.append(
            "> ⚠️ Terminology server unreachable: validated without terminology services "
            "(no LOINC, SNOMED CT or UCUM checks), so fewer findings than usual."
        )
        lines.append("")
    lines.extend(_summary_table(run, delta))
    for group in run.groups:
        if group.crashed:
            lines.append(f"### ❌ Group {group.index} crashed")
            lines.append("")
            lines.append(group.reason)
            lines.append("")
            lines.append("```")
            lines.extend(group.logTail)
            lines.append("```")
            lines.append("")
    return "\n".join(lines)
