"""Comparison against the results published from main.

A pull request is easier to read with "+2 new / 1 fixed" than with absolute
counts, so issues are fingerprinted without line and column numbers: reformatting
a file must not look like a new finding.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .results import Issue, RunResult, run_from_dict

FETCH_TIMEOUT_SECONDS = 20


def fetch(url: str) -> RunResult | None:
    """Load the baseline; a missing or unreachable one is not an error."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"note: no baseline available from {url} ({exc})")
        return None
    try:
        return run_from_dict(data)
    except (TypeError, KeyError) as exc:  # pragma: no cover - schema drift
        print(f"note: baseline at {url} could not be read ({exc})")
        return None


def load_file(path: Path) -> RunResult | None:
    if not path.is_file():
        print(f"note: no baseline file at {path}")
        return None
    return run_from_dict(json.loads(path.read_text(encoding="utf-8")))


def fingerprint(file_path: str, issue: Issue) -> tuple[str, str, str, str, str]:
    """Line and column are deliberately excluded."""
    return (
        file_path,
        issue.severity,
        issue.messageId or issue.code,
        ", ".join(issue.expression),
        issue.details,
    )


def _fingerprints(run: RunResult) -> dict[str, set[tuple[str, str, str, str, str]]]:
    out: dict[str, set[tuple[str, str, str, str, str]]] = {}
    for submission in run.submissions:
        marks: set[tuple[str, str, str, str, str]] = set()
        for file_result in submission.files:
            for issue in file_result.issues:
                if issue.suppressed or issue.severity == "information":
                    continue
                marks.add(fingerprint(file_result.path, issue))
        out[submission.id] = marks
    return out


def diff(current: RunResult, baseline: RunResult | None) -> dict[str, dict[str, Any]]:
    """Per submission: how many findings are new, fixed or unchanged."""
    if baseline is None:
        return {}
    old = _fingerprints(baseline)
    new = _fingerprints(current)
    result: dict[str, dict[str, Any]] = {}
    old_status = {s.id: s.status for s in baseline.submissions}
    for submission_id, marks in new.items():
        if submission_id not in old:
            result[submission_id] = {
                "known": False,
                "new": len(marks),
                "fixed": 0,
                "unchanged": 0,
                "previousStatus": None,
            }
            continue
        previous = old[submission_id]
        result[submission_id] = {
            "known": True,
            "new": len(marks - previous),
            "fixed": len(previous - marks),
            "unchanged": len(marks & previous),
            "previousStatus": old_status.get(submission_id),
        }
    return result


def describe(entry: dict[str, Any] | None) -> str:
    if not entry:
        return "–"
    if not entry.get("known"):
        return "new submission"
    added = entry.get("new", 0)
    fixed = entry.get("fixed", 0)
    if not added and not fixed:
        return "unchanged"
    parts = []
    if added:
        parts.append(f"+{added} new")
    if fixed:
        parts.append(f"{fixed} fixed")
    return " / ".join(parts)
