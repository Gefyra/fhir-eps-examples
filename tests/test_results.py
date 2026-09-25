"""Status aggregation, rating levels and the suppression filter."""

from __future__ import annotations

from tools.results import (
    FileResult,
    Issue,
    STATUS_ERRORS,
    STATUS_NOT_VALIDATED,
    STATUS_VALID,
    STATUS_WARNINGS,
    SubmissionResult,
    compute_stars,
)
from tools.suppress import apply, parse_rules


EPS_BUNDLE = "http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps"


def file_with(*issues: Issue, name: str = "Observation-a.json", status: str = "valid") -> FileResult:
    return FileResult(
        name=name,
        path=f"examples/c/s/{name}",
        resourceType="Observation",
        profiles=["http://example.org/StructureDefinition/x"],
        rootProfiles=["http://example.org/StructureDefinition/x"],
        status=status,
        issues=list(issues),
    )


def document(*issues: Issue, declared: list[str] | None = None, enforced: str | None = EPS_BUNDLE) -> FileResult:
    return FileResult(
        name="Bundle-a.json",
        path="examples/c/s/Bundle-a.json",
        resourceType="Bundle",
        bundleType="document",
        profiles=list(declared or []),
        rootProfiles=list(declared or []),
        enforcedProfile=enforced,
        status="valid",
        issues=list(issues),
    )


def submission(*files: FileResult, **kwargs) -> SubmissionResult:
    kwargs.setdefault("origin", "synthetic")
    entry = SubmissionResult(id="c/s", contributor="c", slug="s", title="T", **kwargs)
    entry.files = list(files)
    entry.recompute()
    return entry


def test_information_does_not_change_the_status():
    entry = submission(file_with(Issue(severity="information", details="fyi")))
    assert entry.status == STATUS_VALID
    assert entry.counts.information == 1


def test_warnings_and_errors():
    assert submission(file_with(Issue(severity="warning"))).status == STATUS_WARNINGS
    assert submission(file_with(Issue(severity="error"))).status == STATUS_ERRORS
    assert submission(file_with(Issue(severity="fatal"))).status == STATUS_ERRORS


def test_not_validated_wins_over_everything():
    entry = submission(
        file_with(Issue(severity="error"), name="a.json"),
        file_with(name="b.json", status=STATUS_NOT_VALIDATED),
    )
    assert entry.status == STATUS_NOT_VALIDATED


def test_suppressed_errors_do_not_count():
    issue = Issue(severity="error", messageId="SOME_ID", expression=["Observation.status"])
    file_result = file_with(issue)
    rules = parse_rules(
        [{"messageId": "some_id", "justification": "Known and accepted for now."}]
    )
    stale = apply(rules, [file_result])
    assert not stale
    entry = submission(file_result)
    assert entry.status == STATUS_VALID
    assert entry.counts.suppressed == 1
    assert entry.counts.errors == 0


def test_stale_rules_are_reported():
    rules = parse_rules([{"messageId": "NEVER_SEEN", "justification": "Used to happen once."}])
    stale = apply(rules, [file_with(Issue(severity="error", messageId="OTHER"))])
    assert len(stale) == 1
    assert stale[0].matcher == {"messageId": "NEVER_SEEN"}


def test_all_matchers_must_match():
    issue = Issue(severity="error", messageId="ID", expression=["Observation.status"], details="boom")
    file_result = file_with(issue, name="Observation-a.json")
    rules = parse_rules(
        [{"messageId": "ID", "file": "other.json", "justification": "Wrong file on purpose."}]
    )
    apply(rules, [file_result])
    assert not issue.suppressed


def test_wildcards_in_location_and_details():
    issue = Issue(severity="warning", expression=["Observation.component[2].value"], details="unit mg/dl is wrong")
    file_result = file_with(issue)
    rules = parse_rules(
        [{"location": "Observation.component*", "details": "*mg/dl*", "justification": "Legacy units."}]
    )
    apply(rules, [file_result])
    assert issue.suppressed


def test_line_fallback_location():
    issue = Issue(severity="error", line=12, col=4)
    assert issue.location == "Line 12, Column 4"


def test_stars_highest_level_wins():
    entry = submission(file_with(), origin="real-world")
    level, reasons = compute_stars(entry)
    assert level == 3  # profile declared, no errors
    assert any(reason.startswith("1 —") for reason in reasons)
    assert any(reason.startswith("3 —") for reason in reasons)

    entry.review = {"consensus": True}
    assert compute_stars(entry)[0] == 4


def test_level_three_needs_a_profile():
    entry = submission(FileResult(name="a.json", path="examples/c/s/a.json", resourceType="Observation", status="valid"))
    assert compute_stars(entry)[0] == 0


def test_level_three_counts_only_root_profiles():
    # A profile on a Bundle entry does not make the Bundle itself profiled.
    unprofiled = FileResult(
        name="Bundle-a.json",
        path="examples/c/s/Bundle-a.json",
        resourceType="Bundle",
        bundleType="collection",
        profiles=["http://example.org/StructureDefinition/entry"],
        status="valid",
    )
    assert compute_stars(submission(unprofiled))[0] == 0


def test_level_three_through_the_enforced_profile():
    entry = submission(document())
    level, reasons = compute_stars(entry)
    assert level == 3
    assert "bundle-eu-eps, enforced" in reasons[-1]
    assert "declared" not in reasons[-1]


def test_level_three_reason_names_declared_and_enforced_profiles():
    entry = submission(
        document(declared=["http://hl7.org/fhir/uv/ips/StructureDefinition/Bundle-uv-ips|2.0.0"]),
        file_with(name="Observation-b.json"),
    )
    level, reasons = compute_stars(entry)
    assert level == 3
    assert reasons[-1] == (
        "3 — Validated against a profile (bundle-eu-eps, enforced; "
        "Bundle-uv-ips|2.0.0, x, declared; no unsuppressed errors)"
    )


def test_level_three_needs_every_file():
    unprofiled = FileResult(name="b.json", path="examples/c/s/b.json", resourceType="Patient", status="valid")
    assert compute_stars(submission(document(), unprofiled))[0] == 0


def test_level_three_is_lost_with_errors_against_the_enforced_profile():
    entry = submission(document(Issue(severity="error", messageId="Slice")))
    assert compute_stars(entry)[0] == 0


def test_opted_out_document_without_declared_profile_misses_level_three():
    assert compute_stars(submission(document(enforced=None)))[0] == 0


def test_level_three_survives_a_suppressed_error():
    issue = Issue(severity="error", messageId="ID")
    file_result = file_with(issue)
    apply(parse_rules([{"messageId": "ID", "justification": "Accepted, documented."}]), [file_result])
    entry = submission(file_result)
    assert compute_stars(entry)[0] == 3


def test_level_three_is_lost_when_the_file_was_not_validated():
    entry = submission(file_with(status=STATUS_NOT_VALIDATED))
    assert compute_stars(entry)[0] == 0
