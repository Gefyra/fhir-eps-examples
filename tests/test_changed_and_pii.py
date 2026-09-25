"""Mapping a diff to submissions, and the warn-only identifiable-data heuristics."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.changed import changed_submissions, needs_full_run
from tools.pii import scan_resource


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.fixture
def git_repo(repo: Path, make_submission) -> Path:
    make_submission(contributor="alice", slug="one")
    make_submission(contributor="bob", slug="two")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.org")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_full_run_paths():
    assert needs_full_run(["validation.config.yaml"])
    assert needs_full_run(["tools/check.py"])
    assert needs_full_run(["schema/metadata.schema.json"])
    assert needs_full_run([".github/workflows/validate-pr.yml"])
    assert needs_full_run([".github/actions/setup-validator/action.yml"])
    assert not needs_full_run(["README.md", "examples/alice/one/metadata.yaml"])
    assert not needs_full_run([".github/workflows/pr-comment.yml"])


def test_only_the_touched_submission_is_selected(cfg, git_repo: Path):
    base = git(git_repo, "rev-parse", "HEAD")
    (git_repo / "examples" / "alice" / "one" / "metadata.yaml").write_text(
        "title: Changed title\norigin: synthetic\n", encoding="utf-8"
    )
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "change")
    head = git(git_repo, "rev-parse", "HEAD")

    payload = changed_submissions(cfg, base, head)
    assert payload["full"] is False
    assert payload["submissions"] == ["alice/one"]


def test_contributor_file_selects_all_of_that_contributor(cfg, git_repo: Path, make_submission):
    make_submission(contributor="alice", slug="three")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "third")
    base = git(git_repo, "rev-parse", "HEAD")
    (git_repo / "examples" / "alice" / "contributor.yaml").write_text(
        "name: Alice Example\n", encoding="utf-8"
    )
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "contributor")
    head = git(git_repo, "rev-parse", "HEAD")

    payload = changed_submissions(cfg, base, head)
    assert payload["submissions"] == ["alice/one", "alice/three"]


def test_tooling_change_triggers_a_full_run(cfg, git_repo: Path):
    base = git(git_repo, "rev-parse", "HEAD")
    (git_repo / "validation.config.yaml").write_text(
        (git_repo / "validation.config.yaml").read_text(encoding="utf-8") + "\n# touched\n",
        encoding="utf-8",
    )
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "config")
    head = git(git_repo, "rev-parse", "HEAD")

    payload = changed_submissions(cfg, base, head)
    assert payload["full"] is True
    assert payload["submissions"] == ["alice/one", "bob/two"]


def test_unrelated_change_selects_nothing(cfg, git_repo: Path):
    base = git(git_repo, "rev-parse", "HEAD")
    (git_repo / "NOTES.md").write_text("hello\n", encoding="utf-8")
    git(git_repo, "add", "-A")
    git(git_repo, "commit", "-q", "-m", "notes")
    head = git(git_repo, "rev-parse", "HEAD")

    payload = changed_submissions(cfg, base, head)
    assert payload["full"] is False
    assert payload["submissions"] == []


PATIENT = {
    "resourceType": "Patient",
    "name": [{"family": "Musterfrau", "given": ["Erika"]}],
    "birthDate": "1975-04-03",
    "identifier": [{"system": "http://hospital.invalid/mrn", "value": "4711"}],
    "telecom": [{"system": "phone", "value": "+49 30 123456"}],
    "address": [{"line": ["Hauptstrasse 1"], "postalCode": "10115"}],
}


def test_patient_details_are_flagged():
    notes = [finding["note"] for finding in scan_resource(PATIENT, "Patient.json")]
    assert any("name" in note for note in notes)
    assert any("date of birth" in note for note in notes)
    assert any("identifier" in note for note in notes)
    assert any("contact details" in note for note in notes)
    assert any("address" in note for note in notes)


def test_test_data_tag_silences_the_name_check():
    resource = dict(PATIENT)
    resource["meta"] = {
        "security": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "HTEST"}]
    }
    notes = [finding["note"] for finding in scan_resource(resource, "Patient.json")]
    assert not any("name is present" in note for note in notes)


def test_dates_and_versions_are_not_phone_numbers():
    resource = {
        "resourceType": "Observation",
        "effectiveDateTime": "2025-05-06",
        "issued": "2025-03-12T14:02:00+01:00",
        "meta": {"versionId": "3.0.0"},
    }
    assert scan_resource(resource, "Observation.json") == []


def test_email_in_free_text_is_flagged():
    resource = {"resourceType": "Observation", "note": [{"text": "ask erika@example.org"}]}
    findings = scan_resource(resource, "Observation.json")
    assert findings and "e-mail" in findings[0]["note"]


def test_technical_urls_are_ignored():
    resource = {
        "resourceType": "Observation",
        "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
        "subject": {"reference": "Patient/example-patient-1"},
    }
    assert scan_resource(resource, "Observation.json") == []
