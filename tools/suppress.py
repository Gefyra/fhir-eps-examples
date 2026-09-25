"""Known-issue suppression: accept a finding explicitly instead of hiding it."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Iterable

from .results import FileResult, Issue, StaleSuppression

MATCHERS = ("messageId", "file", "location", "details")


@dataclass
class Rule:
    index: int
    messageId: str | None
    file: str | None
    location: str | None
    details: str | None
    justification: str

    @property
    def matcher(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("messageId", self.messageId),
                ("file", self.file),
                ("location", self.location),
                ("details", self.details),
            )
            if value
        }


def parse_rules(raw: Iterable[dict[str, Any]]) -> list[Rule]:
    rules: list[Rule] = []
    for index, entry in enumerate(raw or []):
        rules.append(
            Rule(
                index=index,
                messageId=(str(entry["messageId"]) if entry.get("messageId") else None),
                file=(str(entry["file"]) if entry.get("file") else None),
                location=(str(entry["location"]) if entry.get("location") else None),
                details=(str(entry["details"]) if entry.get("details") else None),
                justification=str(entry.get("justification", "")),
            )
        )
    return rules


def _wildcard_match(pattern: str, value: str) -> bool:
    if "*" in pattern:
        return fnmatch.fnmatchcase(value, pattern)
    return pattern == value


def matches(rule: Rule, issue: Issue, file_name: str) -> bool:
    """All matchers given in the rule must match; an empty rule matches nothing."""
    if not rule.matcher:
        return False
    if rule.file is not None and rule.file != file_name:
        return False
    if rule.messageId is not None and rule.messageId.lower() != (issue.messageId or "").lower():
        return False
    if rule.location is not None and not _wildcard_match(rule.location, issue.location):
        return False
    if rule.details is not None and not _wildcard_match(rule.details, issue.details):
        return False
    return True


def apply(rules: list[Rule], files: list[FileResult]) -> list[StaleSuppression]:
    """Mark matching issues as suppressed; return the rules that matched nothing."""
    used: set[int] = set()
    for file_result in files:
        for issue in file_result.issues:
            if issue.severity == "information":
                continue
            for rule in rules:
                if matches(rule, issue, file_result.name):
                    issue.suppressed = True
                    issue.justification = rule.justification
                    used.add(rule.index)
                    break
    return [
        StaleSuppression(index=rule.index, matcher=rule.matcher, justification=rule.justification)
        for rule in rules
        if rule.index not in used
    ]
