"""The committed EPS model and the code that generates it."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from conftest import REPO_ROOT
from tools.config import load_config
from tools.igmodel import MODEL_PATH, ModelError, _read_tarball, build_model, load_model, split_ig


def _eps_default(cfg) -> str:
    (ig,) = [ig for ig in cfg.default_igs_for("4.0.1") if ig.startswith("hl7.fhir.eu.eps#")]
    return ig


def test_model_matches_the_configured_eps_version():
    """Bumping EPS in the config without 'python -m tools ig-model' fails here."""
    cfg = load_config(REPO_ROOT)
    model = load_model()
    assert MODEL_PATH.is_file()
    assert f"{model['package']}#{model['version']}" == _eps_default(cfg)


def test_committed_model_has_sections_and_profiles():
    model = load_model()
    assert model["composition"] == "http://hl7.eu/fhir/eps/StructureDefinition/composition-eu-eps"
    assert model["sections"][0]["sliceName"] == "sectionProblems"
    assert model["sections"][0]["codes"] == [
        {"system": "http://loinc.org", "code": "11450-4", "display": ""}
    ]
    assert all(p["url"].startswith("http://hl7.eu/fhir/eps/") for p in model["profiles"])
    assert "Bundle" in {p["type"] for p in model["profiles"]}


def _element(element_id: str, **fields) -> dict:
    path = ".".join(part.split(":")[0] for part in element_id.split("."))
    return {"id": element_id, "path": path, **fields}


def _reference(*profiles: str) -> list[dict]:
    return [{"code": "Reference", "targetProfile": list(profiles)}]


COMPOSITION = {
    "resourceType": "StructureDefinition",
    "url": "http://example.org/StructureDefinition/composition-x",
    "name": "CompositionX",
    "title": "Composition (X)",
    "type": "Composition",
    "kind": "resource",
    "derivation": "constraint",
    "snapshot": {
        "element": [
            _element("Composition"),
            _element("Composition.section", min=1, max="*"),
            _element("Composition.section:second", sliceName="second", min=0, max="1", short="Second section"),
            _element(
                "Composition.section:second.code",
                patternCodeableConcept={"coding": [{"system": "http://loinc.org", "code": "2"}]},
            ),
            _element("Composition.section:second.entry", type=_reference("http://hl7.org/fhir/StructureDefinition/Observation")),
            _element("Composition.section:first", sliceName="first", min=1, max="1", short="First section"),
            _element(
                "Composition.section:first.code",
                patternCodeableConcept={"coding": [{"system": "http://loinc.org", "code": "1", "display": "One"}]},
            ),
            _element(
                "Composition.section:first.entry",
                type=_reference(
                    "http://hl7.org/fhir/StructureDefinition/Condition",
                    "http://hl7.org/fhir/StructureDefinition/DocumentReference",
                ),
            ),
            _element(
                "Composition.section:first.entry:problem",
                sliceName="problem",
                min=0,
                max="*",
                type=_reference("http://example.org/StructureDefinition/condition-x"),
            ),
            _element(
                "Composition.section:first.entry:problem.reference",
            ),
        ]
    },
}

OTHER_PROFILES = [
    {
        "resourceType": "StructureDefinition",
        "url": "http://example.org/StructureDefinition/condition-x",
        "name": "ConditionX",
        "type": "Condition",
        "kind": "resource",
        "derivation": "constraint",
    },
    {
        "resourceType": "StructureDefinition",
        "url": "http://example.org/StructureDefinition/extension-x",
        "name": "ExtensionX",
        "type": "Extension",
        "kind": "complex-type",
        "derivation": "constraint",
    },
    {
        "resourceType": "StructureDefinition",
        "url": "http://example.org/StructureDefinition/logical-x",
        "name": "LogicalX",
        "type": "LogicalX",
        "kind": "logical",
        "derivation": "specialization",
    },
]


def test_sections_in_snapshot_order_with_entry_slices():
    model = build_model("example.ig", "1.0.0", [COMPOSITION, *OTHER_PROFILES])
    assert [s["sliceName"] for s in model["sections"]] == ["second", "first"]
    first = model["sections"][1]
    assert first["title"] == "First section"
    assert (first["min"], first["max"]) == (1, "1")
    assert first["codes"] == [{"system": "http://loinc.org", "code": "1", "display": "One"}]
    assert first["entryProfiles"] == [
        "http://hl7.org/fhir/StructureDefinition/Condition",
        "http://hl7.org/fhir/StructureDefinition/DocumentReference",
        "http://example.org/StructureDefinition/condition-x",
    ]
    assert first["entrySlices"] == [
        {
            "sliceName": "problem",
            "min": 0,
            "max": "*",
            "profiles": ["http://example.org/StructureDefinition/condition-x"],
        }
    ]


def test_only_resource_profiles_are_listed():
    model = build_model("example.ig", "1.0.0", [COMPOSITION, *OTHER_PROFILES])
    assert [(p["type"], p["name"]) for p in model["profiles"]] == [
        ("Composition", "CompositionX"),
        ("Condition", "ConditionX"),
    ]
    assert (model["package"], model["version"]) == ("example.ig", "1.0.0")


def test_ambiguous_composition_needs_a_choice():
    second = dict(COMPOSITION, url="http://example.org/StructureDefinition/composition-y")
    with pytest.raises(ModelError, match="exactly one Composition profile"):
        build_model("example.ig", "1.0.0", [COMPOSITION, second])
    model = build_model("example.ig", "1.0.0", [COMPOSITION, second], composition_url=second["url"])
    assert model["composition"] == second["url"]


def test_package_tarball_is_read_without_extracting():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in (
            ("package/StructureDefinition-composition-x.json", COMPOSITION),
            ("package/package.json", {"name": "example.ig"}),
            ("package/example/StructureDefinition-ignored.json", OTHER_PROFILES[0]),
        ):
            data = json.dumps(payload).encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    resources = _read_tarball(buffer.getvalue())
    assert [r["url"] for r in resources] == [COMPOSITION["url"]]


def test_floating_versions_are_rejected():
    assert split_ig("hl7.fhir.eu.eps#1.0.0-ballot") == ("hl7.fhir.eu.eps", "1.0.0-ballot")
    with pytest.raises(ModelError):
        split_ig("hl7.fhir.eu.eps#current")


def test_a_missing_model_is_empty(tmp_path: Path):
    model = load_model(tmp_path / "missing.json")
    assert model["sections"] == [] and model["profiles"] == []
