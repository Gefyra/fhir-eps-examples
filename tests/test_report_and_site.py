"""The pull request comment, the baseline delta, the section and profile indexes and the site."""

from __future__ import annotations

import copy
from pathlib import Path

from conftest import EPS_BUNDLE, EU_CONDITION, MINIMAL_BUNDLE
from tools import fhir, igmodel
from tools import profiles as profiles_mod
from tools import sections as sections_mod
from tools.baseline import describe, diff, fingerprint
from tools.report_md import MARKER_END, MARKER_START, ig_label, render_job_summary, render_pr_comment
from tools.results import FileResult, GroupResult, Issue, RunResult, SubmissionResult
from tools.site import badge, build_site, render_markdown

MODEL = igmodel.load_model()


def make_run(*submissions: SubmissionResult, **kwargs) -> RunResult:
    run = RunResult(
        generatedAt="2026-02-01T10:00:00Z",
        validator={"version": "6.10.4"},
        terminology="https://tx.fhir.org",
        **kwargs,
    )
    run.submissions = list(submissions)
    return run


def document_file(contributor: str, slug: str, resource: dict | None = None, **kwargs) -> FileResult:
    """A FileResult built from a real Bundle the way the validator builds it."""
    resource = resource or MINIMAL_BUNDLE
    compositions = fhir.summarize_compositions(resource)
    sections_mod.annotate(MODEL, compositions)
    kwargs.setdefault("enforcedProfile", EPS_BUNDLE)
    return FileResult(
        name="Bundle-a.json",
        path=f"examples/{contributor}/{slug}/Bundle-a.json",
        resourceType="Bundle",
        bundleType="document",
        profiles=sorted({p for node in fhir.iter_resources(resource) for p in fhir.profiles(node)}),
        rootProfiles=fhir.profiles(resource),
        status="valid",
        resources=fhir.resource_summaries(resource),
        compositions=compositions,
        group=1,
        **kwargs,
    )


def make_submission(
    identifier: str = "c/s",
    issues: list[Issue] | None = None,
    title: str = "An example",
    resource: dict | None = None,
    **kwargs,
) -> SubmissionResult:
    contributor, slug = identifier.split("/")
    entry = SubmissionResult(
        id=identifier,
        contributor=contributor,
        slug=slug,
        title=title,
        origin="real-world",
        igs=["hl7.fhir.eu.eps#1.0.0-ballot"],
        country="FI",
        custodian={"name": "Some One", "github": "", "contact": ""},
        groups=[1],
        **kwargs,
    )
    entry.files = [document_file(contributor, slug, resource, issues=issues or [])]
    entry.recompute()
    return entry


def indexed_run(*submissions: SubmissionResult) -> RunResult:
    run = make_run(*submissions)
    run.sections = sections_mod.build_index(run, MODEL)
    run.profiles = profiles_mod.build_index(run, MODEL)
    run.model = {"package": MODEL["package"], "version": MODEL["version"]}
    return run


def with_unexpected_entries() -> dict:
    """Problems carries an Observation and a Condition with a foreign profile,
    and a section EPS does not know is added."""
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    resource["entry"][2]["resource"]["meta"]["profile"] = [
        EU_CONDITION + "|2.0.0",
        "http://example.org/StructureDefinition/national-condition",
    ]
    resource["entry"].append(
        {
            "fullUrl": "urn:uuid:observation-1",
            "resource": {"resourceType": "Observation", "id": "observation-1"},
        }
    )
    sections = resource["entry"][0]["resource"]["section"]
    sections[0]["entry"].append({"reference": "urn:uuid:observation-1"})
    sections.append(
        {
            "title": "Past illness",
            "code": {"coding": [{"system": "http://loinc.org", "code": "11348-0"}]},
            "entry": [{"reference": "urn:uuid:condition-1"}],
        }
    )
    return resource


# --------------------------------------------------------------- pr comment


def test_comment_contains_the_markers_and_the_table(cfg):
    run = make_run(make_submission(issues=[Issue(severity="error", messageId="E1", details="boom")]))
    body = render_pr_comment(cfg, run, {}, check_summary="<!-- check-status: passed -->\n### Structural checks: ✅ passed\n")
    assert body.startswith(MARKER_START)
    assert MARKER_START == "<!-- fhir-eps-validation -->"
    assert body.rstrip().endswith(MARKER_END)
    assert "| Submission | FHIR | Status |" in body
    assert "`c/s`" in body
    assert "<details>" in body
    assert "E1" in body


def test_comment_names_the_enforced_profile(cfg):
    run = make_run(make_submission())
    run.groups = [GroupResult(index=1, fhirVersion="4.0.1", igs=[], files=[], profile=EPS_BUNDLE)]
    body = render_pr_comment(cfg, run, {})
    assert "document Bundles also against `bundle-eu-eps`" in body


def test_failed_checks_omit_the_rest(cfg):
    run = make_run(make_submission())
    body = render_pr_comment(
        cfg, run, {}, check_summary="<!-- check-status: failed -->\n### Structural checks: ❌ failed\n"
    )
    assert "| Submission | FHIR | Status |" not in body
    assert "structural checks must pass" in body


def test_comment_without_results(cfg):
    body = render_pr_comment(cfg, RunResult(validator={"version": "6.10.4"}), {})
    assert "No FHIR validation results in this comment" in body


def test_comment_respects_the_budget(cfg):
    issues = [Issue(severity="error", messageId=f"E{n}", details="x" * 200) for n in range(50)]
    submissions = [make_submission(f"c/s{n}", issues=list(issues)) for n in range(40)]
    run = make_run(*submissions)
    body = render_pr_comment(cfg, run, {})
    assert len(body) <= cfg.report.prCommentBudgetChars
    assert "not shown here" in body


def test_baseline_delta(cfg):
    old_issue = Issue(severity="error", messageId="E1", details="boom", expression=["Bundle"], line=3)
    same_issue = Issue(severity="error", messageId="E1", details="boom", expression=["Bundle"], line=99)
    new_issue = Issue(severity="error", messageId="E2", details="other", expression=["Bundle"])

    baseline = make_run(make_submission(issues=[old_issue]))
    current = make_run(make_submission(issues=[same_issue, new_issue]))
    delta = diff(current, baseline)
    assert delta["c/s"]["new"] == 1
    assert delta["c/s"]["fixed"] == 0
    assert delta["c/s"]["unchanged"] == 1  # the line number moved, the finding did not
    assert describe(delta["c/s"]) == "+1 new"

    fixed = diff(make_run(make_submission(issues=[])), baseline)
    assert describe(fixed["c/s"]) == "1 fixed"
    assert describe(diff(make_run(make_submission("c/new")), baseline)["c/new"]) == "new submission"
    assert describe(None) == "–"


def test_fingerprint_ignores_line_and_column():
    a = Issue(severity="error", messageId="E", details="d", expression=["x"], line=1, col=2)
    b = Issue(severity="error", messageId="E", details="d", expression=["x"], line=9, col=9)
    assert fingerprint("f", a) == fingerprint("f", b)


# ------------------------------------------------------------ section index


def test_eps_sections_come_first_in_model_order():
    index = sections_mod.build_index(make_run(make_submission()), MODEL)
    eps = [entry for entry in index if entry["eps"]]
    assert [entry["eps"]["sliceName"] for entry in eps] == [s["sliceName"] for s in MODEL["sections"]]
    assert index[: len(eps)] == eps
    problems = eps[0]
    assert problems["code"] == "11450-4"
    assert problems["requirement"] == "required"
    assert problems["slug"] == "loinc-11450-4"


def test_sections_without_occurrence_stay_listed():
    index = sections_mod.build_index(make_run(make_submission()), MODEL)
    by_code = {entry["code"]: entry for entry in index}
    assert by_code["47519-4"]["occurrenceCount"] == 0  # History of Procedures: no example yet
    assert by_code["47519-4"]["requirement"] == "required"
    assert by_code["11369-6"]["occurrenceCount"] == 0
    assert by_code["11369-6"]["requirement"] == "optional"


def test_how_sections_are_filled_is_counted():
    index = sections_mod.build_index(make_run(make_submission("a/one"), make_submission("b/two")), MODEL)
    by_code = {entry["code"]: entry for entry in index}
    assert by_code["11450-4"]["submissionCount"] == 2
    assert by_code["11450-4"]["withEntries"] == 2
    assert by_code["48765-2"]["withEmptyReason"] == 2
    assert by_code["10160-0"]["narrativeOnly"] == 2
    occurrence = by_code["48765-2"]["occurrences"][0]
    assert occurrence["emptyReason"]["code"] == "nilknown"
    assert occurrence["country"] == "FI"


def test_unexpected_entries_and_other_sections():
    index = sections_mod.build_index(make_run(make_submission(resource=with_unexpected_entries())), MODEL)
    by_code = {entry["code"]: entry for entry in index}
    occurrence = by_code["11450-4"]["occurrences"][0]
    types = {row["type"]: row["expected"] for row in occurrence["entryTypes"]}
    assert types == {"Condition": True, "Observation": False}
    profiles = {row["profile"]: row["expected"] for row in occurrence["entryProfiles"]}
    # The version does not matter for the comparison.
    assert profiles[EU_CONDITION + "|2.0.0"] is True
    assert profiles["http://example.org/StructureDefinition/national-condition"] is False
    assert occurrence["entriesWithoutProfile"] == 1

    other = index[-1]
    assert other["code"] == "11348-0"
    assert other["eps"] is None
    assert other["requirement"] == "not in EPS"
    assert other["occurrences"][0]["entryProfiles"][0]["expected"] is True


def test_checklist_marks_missing_required_sections():
    file_result = make_submission().files[0]
    (composition,) = sections_mod.checklist(file_result, MODEL)
    states = {row["sliceName"]: (row["state"], row["detail"]) for row in composition["rows"]}
    assert states["sectionProblems"] == ("present", "1 entry")
    assert states["sectionAllergies"] == ("present", "emptyReason nilknown")
    assert states["sectionMedications"] == ("present", "narrative only")
    assert states["sectionProceduresHx"] == ("required but missing", "")
    assert states["sectionImmunizations"] == ("absent", "")
    assert composition["others"] == []


def test_section_slug_is_path_safe():
    assert sections_mod.section_slug("http://loinc.org", "11450-4") == "loinc-11450-4"
    assert sections_mod.section_slug("urn:oid:1.2.3", "A B/C") == "urn-oid-1.2.3-a-b-c"
    assert sections_mod.section_slug("", "") == "no-code"


# ------------------------------------------------------------ profile index


def test_every_eps_profile_is_listed():
    index = profiles_mod.build_index(make_run(make_submission()), MODEL)
    assert [p["url"] for p in index["eps"]] == [p["url"] for p in MODEL["profiles"]]
    by_label = {p["label"]: p for p in index["eps"]}
    assert by_label["bundle-eu-eps"]["resourceCount"] == 0  # enforced, but not declared
    assert by_label["bundle-eu-eps"]["enforcedFileCount"] == 1
    assert by_label["patient-eu-eps"]["resourceCount"] == 0
    assert by_label["patient-eu-eps"]["undeclaredCount"] == 1


def test_other_profiles_are_keyed_without_version():
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    resource["meta"]["profile"] = [EPS_BUNDLE + "|1.0.0-ballot"]
    run = make_run(make_submission("a/one"), make_submission("b/two", resource=with_unexpected_entries()))
    run.submissions.append(make_submission("c/three", resource=resource))
    index = profiles_mod.build_index(run, MODEL)
    other = {p["url"]: p for p in index["other"]}
    condition = other[EU_CONDITION]
    assert condition["resourceCount"] == 3
    assert condition["submissionCount"] == 3
    assert condition["versions"] == ["2.0.0"]
    assert condition["types"] == ["Condition"]
    assert "http://example.org/StructureDefinition/national-condition" in other
    bundle_profile = {p["label"]: p for p in index["eps"]}["bundle-eu-eps"]
    assert bundle_profile["resourceCount"] == 1
    assert bundle_profile["versions"] == ["1.0.0-ballot"]
    assert bundle_profile["resources"][0]["declaredAs"] == EPS_BUNDLE + "|1.0.0-ballot"
    slugs = [p["slug"] for p in index["eps"] + index["other"]]
    assert len(slugs) == len(set(slugs))


# -------------------------------------------------------------------- site


def test_badge_is_a_shields_endpoint():
    run = make_run(make_submission("a/one"), make_submission("b/two", issues=[Issue(severity="error")]))
    payload = badge(run)
    assert payload["schemaVersion"] == 1
    assert payload["label"] == "examples"
    assert payload["color"] == "blue"
    assert "1 valid" in payload["message"] and "1 errors" in payload["message"]


def test_markdown_is_sanitised():
    rendered = render_markdown("# Title\n\n<script>alert(1)</script>\n\n[ok](https://example.org)\n")
    assert "<h1>Title</h1>" in rendered
    assert "<script>" not in rendered
    assert "alert(1)" in rendered  # dropped tag, text kept
    assert '<a href="https://example.org">ok</a>' in rendered


def test_markdown_drops_dangerous_urls():
    rendered = render_markdown("[click](javascript:alert(1))")
    assert "javascript:" not in rendered


def test_ig_label_is_short():
    assert ig_label("hl7.fhir.eu.eps#1.0.0-ballot") == "eps 1.0.0-ballot"


def test_site_builds_every_page(cfg, tmp_path: Path):
    run = indexed_run(
        make_submission("a/one"),
        make_submission("b/two", resource=with_unexpected_entries(), issues=[Issue(severity="error", messageId="E")]),
    )
    target = tmp_path / "site"
    build_site(cfg, run, target)
    for name in ("index.html", ".nojekyll", "badge.json", "results.json", "sections.json", "profiles.json"):
        assert (target / name).is_file(), name
    assert sorted(p.name for p in target.glob("*.json")) == [
        "badge.json", "profiles.json", "results.json", "sections.json"
    ]
    assert (target / "contributors" / "index.html").is_file()
    assert (target / "sections" / "index.html").is_file()
    assert (target / "profiles" / "index.html").is_file()
    for entry in run.sections:
        assert (target / "sections" / f"{entry['slug']}.html").is_file()
    for entry in run.profiles["eps"] + run.profiles["other"]:
        assert (target / "profiles" / f"{entry['slug']}.html").is_file()
    assert (target / "submissions" / "a" / "one" / "index.html").is_file()
    assert (target / "submissions" / "a" / "one" / "Bundle-a.json.html").is_file()

    index = (target / "index.html").read_text(encoding="utf-8")
    assert "submissions/a/one/index.html" in index
    assert "assets/style.css" in index
    assert "not an official HL7 Europe" in index
    assert "https://hl7.eu/fhir/eps/1.0.0-ballot/" in index

    submission = (target / "submissions" / "a" / "one" / "index.html").read_text(encoding="utf-8")
    assert "EPS sections" in submission
    assert "required but missing" in submission
    assert "enforced" in submission
    file_page = (target / "submissions" / "a" / "one" / "Bundle-a.json.html").read_text(encoding="utf-8")
    assert "Also validated against" in file_page and EPS_BUNDLE in file_page

    problems = (target / "sections" / "loinc-11450-4.html").read_text(encoding="utf-8")
    assert "What EPS expects" in problems
    assert 'class="unexpected"' in problems
    other = (target / "sections" / "loinc-11348-0.html").read_text(encoding="utf-8")
    assert "EPS does not define a section with this code" in other
    sections_index = (target / "sections" / "index.html").read_text(encoding="utf-8")
    assert "no example yet" in sections_index
    profiles_index = (target / "profiles" / "index.html").read_text(encoding="utf-8")
    assert "no example yet" in profiles_index
    assert "Other declared profiles" in profiles_index


def test_job_summary_reports_a_crash(cfg):
    run = make_run(make_submission())
    run.groups = [
        GroupResult(
            index=1, fhirVersion="4.0.1", igs=[], files=[], crashed=True, reason="out of memory",
            logTail=["Error occurred during initialization of VM"],
        )
    ]
    summary = render_job_summary(cfg, run, {})
    assert "crashed" in summary
    assert "out of memory" in summary
    assert "initialization of VM" in summary
