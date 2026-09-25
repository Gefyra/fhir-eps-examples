"""Shared fixtures: a throwaway repository with the real config and schemas."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

HTEST = {"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "HTEST"}
LOINC = "http://loinc.org"
EPS_BUNDLE = "http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps"
EU_CONDITION = "http://hl7.eu/fhir/base/StructureDefinition/condition-eu-core"

# A small EPS-shaped document: one section with an entry, one with an
# emptyReason, one with narrative only.
MINIMAL_BUNDLE = {
    "resourceType": "Bundle",
    "id": "example-1",
    "meta": {"security": [HTEST]},
    "identifier": {"system": "urn:ietf:rfc:3986", "value": "urn:uuid:0c3e7c4a-5bd1-4d3e-8d0a-1f7c2c1b9a01"},
    "type": "document",
    "timestamp": "2026-01-15T09:00:00+01:00",
    "entry": [
        {
            "fullUrl": "urn:uuid:composition-1",
            "resource": {
                "resourceType": "Composition",
                "id": "composition-1",
                "status": "final",
                "type": {"coding": [{"system": LOINC, "code": "60591-5"}]},
                "subject": {"reference": "urn:uuid:patient-1"},
                "date": "2026-01-15T09:00:00+01:00",
                "author": [{"reference": "urn:uuid:patient-1"}],
                "title": "Patient summary",
                "section": [
                    {
                        "title": "Problems",
                        "code": {"coding": [{"system": LOINC, "code": "11450-4"}]},
                        "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">Asthma</div>"},
                        "entry": [{"reference": "urn:uuid:condition-1"}],
                    },
                    {
                        "title": "Allergies",
                        "code": {"coding": [{"system": LOINC, "code": "48765-2"}]},
                        "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">None known</div>"},
                        "emptyReason": {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/list-empty-reason",
                                    "code": "nilknown",
                                }
                            ]
                        },
                    },
                    {
                        "title": "Medication",
                        "code": {"coding": [{"system": LOINC, "code": "10160-0"}]},
                        "text": {"status": "generated", "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">No medication</div>"},
                    },
                ],
            },
        },
        {
            "fullUrl": "urn:uuid:patient-1",
            "resource": {"resourceType": "Patient", "id": "patient-1", "gender": "female"},
        },
        {
            "fullUrl": "urn:uuid:condition-1",
            "resource": {
                "resourceType": "Condition",
                "id": "condition-1",
                "meta": {"profile": [EU_CONDITION]},
                "code": {"text": "Asthma"},
                "subject": {"reference": "urn:uuid:patient-1"},
            },
        },
    ],
}

MINIMAL_OBSERVATION = {
    "resourceType": "Observation",
    "id": "example-1",
    "meta": {
        "profile": ["http://hl7.org/fhir/uv/ips/StructureDefinition/Observation-results-uv-ips"],
        "security": [HTEST],
    },
    "status": "final",
    "code": {"coding": [{"system": LOINC, "code": "4548-4"}]},
    "subject": {"reference": "Patient/example-patient"},
    "effectiveDateTime": "2026-01-15T09:00:00+01:00",
}


def bundle(**changes) -> dict:
    """A deep copy of MINIMAL_BUNDLE with top level fields replaced."""
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    resource.update(changes)
    return resource


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An empty collection with the production config and schemas."""
    shutil.copy(REPO_ROOT / "validation.config.yaml", tmp_path / "validation.config.yaml")
    shutil.copytree(REPO_ROOT / "schema", tmp_path / "schema")
    (tmp_path / "examples").mkdir()
    return tmp_path


@pytest.fixture
def make_submission(repo: Path):
    """Create examples/<contributor>/<slug> with metadata, README and a resource."""

    def _make(
        contributor: str = "someone",
        slug: str = "example-submission",
        metadata: str = "title: An example submission\norigin: synthetic\n",
        contributor_yaml: str = "name: Some One\n",
        resource: dict | str | None = None,
        resource_name: str = "Bundle-example.json",
        readme: str | None = "# An example submission\n",
    ) -> Path:
        contributor_dir = repo / "examples" / contributor
        contributor_dir.mkdir(parents=True, exist_ok=True)
        (contributor_dir / "contributor.yaml").write_text(contributor_yaml, encoding="utf-8")
        submission_dir = contributor_dir / slug
        submission_dir.mkdir(parents=True, exist_ok=True)
        (submission_dir / "metadata.yaml").write_text(metadata, encoding="utf-8")
        if readme is not None:
            (submission_dir / "README.md").write_text(readme, encoding="utf-8")
        if resource is None:
            resource = MINIMAL_BUNDLE
        body = resource if isinstance(resource, str) else json.dumps(resource, indent=2)
        (submission_dir / resource_name).write_text(body, encoding="utf-8")
        return submission_dir

    return _make


@pytest.fixture
def cfg(repo: Path):
    from tools.config import load_config

    return load_config(repo)
