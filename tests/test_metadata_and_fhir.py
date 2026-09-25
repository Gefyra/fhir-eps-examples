"""Defaulting of metadata, the configuration, and reading of FHIR resources."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from conftest import EPS_BUNDLE, EU_CONDITION, MINIMAL_BUNDLE, MINIMAL_OBSERVATION, bundle
from tools import fhir
from tools.config import ConfigError, load_config
from tools.discover import discover, find_submission
from tools.metadata import (
    MetadataError,
    effective_igs,
    enforced_profile,
    load_all,
    load_yaml,
    resolve,
)

XML_BUNDLE = """<?xml version="1.0" encoding="UTF-8"?>
<Bundle xmlns="http://hl7.org/fhir">
  <id value="xml-1"/>
  <meta><profile value="http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps"/></meta>
  <type value="document"/>
  <entry>
    <fullUrl value="urn:uuid:c1"/>
    <resource>
      <Composition>
        <id value="c1"/>
        <status value="final"/>
        <section>
          <title value="Problems"/>
          <code><coding><system value="http://loinc.org"/><code value="11450-4"/></coding></code>
          <text><status value="generated"/><div xmlns="http://www.w3.org/1999/xhtml">Asthma</div></text>
          <entry><reference value="urn:uuid:p1"/></entry>
        </section>
      </Composition>
    </resource>
  </entry>
  <entry>
    <fullUrl value="urn:uuid:p1"/>
    <resource>
      <Condition>
        <id value="p1"/>
        <meta><profile value="http://hl7.eu/fhir/base/StructureDefinition/condition-eu-core"/></meta>
      </Condition>
    </resource>
  </entry>
</Bundle>
"""


def _resolved(cfg):
    submissions = discover(cfg)
    load_all(cfg, submissions)
    return resolve(submissions[0], cfg)


# ------------------------------------------------------------------ metadata


def test_defaults_are_applied(cfg, make_submission):
    make_submission()
    resolved = _resolved(cfg)
    assert resolved.fhirVersion == "4.0.1"
    assert resolved.custodian["name"] == "Some One"
    assert resolved.igs == ("hl7.fhir.eu.eps#1.0.0-ballot",)
    assert resolved.country is None
    assert resolved.enforceProfile is True


def test_country_and_opt_out_are_read(cfg, make_submission):
    make_submission(metadata="title: T\norigin: synthetic\ncountry: AU\nenforceProfile: false\n")
    resolved = _resolved(cfg)
    assert resolved.country == "AU"
    assert resolved.enforceProfile is False


def test_custodian_overrides_the_contributor(cfg, make_submission):
    make_submission(
        metadata="title: T\norigin: synthetic\ncustodian:\n  name: Someone Else\n  github: else\n"
    )
    assert _resolved(cfg).custodian["name"] == "Someone Else"


def test_effective_igs_merge_and_deduplicate(cfg, make_submission):
    make_submission(
        metadata="title: T\norigin: synthetic\nigs:\n  - hl7.fhir.eu.eps#1.0.0-ballot\n  - hl7.fhir.fi.base#2.0.0\n"
    )
    submissions = discover(cfg)
    load_all(cfg, submissions)
    assert effective_igs(submissions[0], cfg) == (
        "hl7.fhir.eu.eps#1.0.0-ballot",
        "hl7.fhir.fi.base#2.0.0",
    )


def test_floating_ig_is_rejected(cfg, make_submission):
    make_submission(metadata="title: T\norigin: synthetic\nigs:\n  - some.package#current\n")
    submissions = discover(cfg)
    load_all(cfg, submissions)
    with pytest.raises(ConfigError):
        effective_igs(submissions[0], cfg)


def test_enforced_profile_only_for_document_bundles(cfg):
    assert enforced_profile(cfg, {}, MINIMAL_BUNDLE) == EPS_BUNDLE
    assert enforced_profile(cfg, {"enforceProfile": True}, MINIMAL_BUNDLE) == EPS_BUNDLE
    assert enforced_profile(cfg, {"enforceProfile": False}, MINIMAL_BUNDLE) is None
    assert enforced_profile(cfg, {}, bundle(type="collection")) is None
    assert enforced_profile(cfg, {}, MINIMAL_OBSERVATION) is None


def test_find_submission_by_id_and_by_path(cfg, make_submission):
    directory = make_submission(contributor="alice", slug="one")
    assert find_submission(cfg, "alice/one").id == "alice/one"
    assert find_submission(cfg, str(directory)).id == "alice/one"
    assert find_submission(cfg, str(directory / "Bundle-example.json")).id == "alice/one"
    assert find_submission(cfg, "nobody/nothing") is None


def test_duplicate_keys_are_rejected(tmp_path: Path):
    path = tmp_path / "metadata.yaml"
    path.write_text("title: One\ntitle: Two\n", encoding="utf-8")
    with pytest.raises(MetadataError, match="duplicate key"):
        load_yaml(path)


def test_empty_file_is_rejected(tmp_path: Path):
    path = tmp_path / "metadata.yaml"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(MetadataError, match="empty"):
        load_yaml(path)


# -------------------------------------------------------------------- config


def test_enforced_profile_is_configured(cfg):
    assert cfg.enforcedProfiles.documentBundle == EPS_BUNDLE


def test_enforced_profiles_are_optional(repo: Path):
    config = repo / "validation.config.yaml"
    text = config.read_text(encoding="utf-8")
    start = text.index("enforcedProfiles:")
    end = text.index("\n\n", start)
    config.write_text(text[:start] + text[end + 2 :], encoding="utf-8")
    assert load_config(repo).enforcedProfiles.documentBundle is None
    assert enforced_profile(load_config(repo), {}, MINIMAL_BUNDLE) is None


def test_enforced_profile_must_be_a_url(repo: Path):
    config = repo / "validation.config.yaml"
    text = config.read_text(encoding="utf-8").replace(
        f"documentBundle: {EPS_BUNDLE}", "documentBundle: bundle-eu-eps"
    )
    config.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="canonical URL"):
        load_config(repo)


# --------------------------------------------------------------------- fhir


def test_xml_bundle_is_read_like_json(tmp_path: Path):
    path = tmp_path / "Bundle-xml.xml"
    path.write_text(XML_BUNDLE, encoding="utf-8")
    resource = fhir.load_resource(path)
    assert resource["resourceType"] == "Bundle"
    assert fhir.is_document_bundle(resource)
    assert fhir.profiles(resource) == [EPS_BUNDLE]
    summaries = fhir.resource_summaries(resource)
    assert [s["resourceType"] for s in summaries] == ["Bundle", "Composition", "Condition"]
    assert summaries[2]["profiles"] == [EU_CONDITION]
    section = fhir.summarize_compositions(resource)[0]["sections"][0]
    assert section["codes"][0]["code"] == "11450-4"
    assert section["entryTypes"] == {"Condition": 1}
    assert section["hasNarrative"] is True
    assert section["textStatus"] == "generated"


def test_resource_summaries_list_root_and_entries():
    summaries = fhir.resource_summaries(MINIMAL_BUNDLE)
    assert summaries[0] == {
        "resourceType": "Bundle",
        "id": "example-1",
        "fullUrl": None,
        "profiles": [],
    }
    assert [(s["resourceType"], s["fullUrl"]) for s in summaries[1:]] == [
        ("Composition", "urn:uuid:composition-1"),
        ("Patient", "urn:uuid:patient-1"),
        ("Condition", "urn:uuid:condition-1"),
    ]
    assert fhir.resource_summaries(MINIMAL_OBSERVATION)[0]["profiles"] == MINIMAL_OBSERVATION["meta"]["profile"]


def test_split_canonical():
    assert fhir.split_canonical("http://x/y|2.0.0") == ("http://x/y", "2.0.0")
    assert fhir.split_canonical("http://x/y") == ("http://x/y", None)


def _sections(resource: dict) -> list[dict]:
    return fhir.summarize_compositions(resource)[0]["sections"]


def test_sections_by_full_url_with_empty_reason_and_narrative_only():
    problems, allergies, medication = _sections(MINIMAL_BUNDLE)
    assert problems["entryCount"] == 1
    assert problems["entryTypes"] == {"Condition": 1}
    assert problems["entryProfiles"] == {EU_CONDITION: 1}
    assert problems["unresolved"] == []
    assert allergies["entryCount"] == 0
    assert allergies["emptyReason"] == {"code": "nilknown", "text": ""}
    assert medication["entryCount"] == 0
    assert medication["emptyReason"] is None
    assert medication["hasNarrative"] is True


def test_relative_references_resolve_against_the_full_url_base():
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    base = "https://fhir.example.org/r4"
    resource["entry"][0]["fullUrl"] = f"{base}/Composition/composition-1"
    resource["entry"][2]["fullUrl"] = f"{base}/Condition/condition-1"
    section = resource["entry"][0]["resource"]["section"][0]
    section["entry"] = [{"reference": "Condition/condition-1"}]
    summary = _sections(resource)[0]
    assert summary["entryTypes"] == {"Condition": 1}
    assert summary["typeIdMatches"] == 0


def test_relative_references_resolve_by_type_and_id():
    # The Composition has a urn:uuid fullUrl, so there is no base to resolve
    # against; Type/id still finds the entry, and that is counted because FHIR
    # itself would not resolve it.
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    resource["entry"][2]["fullUrl"] = "https://server.example.org/fhir/Condition/condition-1"
    section = resource["entry"][0]["resource"]["section"][0]
    section["entry"] = [
        {"reference": "Condition/condition-1"},
        {"reference": "Condition/condition-1/_history/2"},
    ]
    summary = _sections(resource)[0]
    assert summary["entryTypes"] == {"Condition": 2}
    assert summary["typeIdMatches"] == 2
    assert summary["unresolved"] == []


def test_unresolved_entries_are_listed():
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    section = resource["entry"][0]["resource"]["section"][0]
    section["entry"] = [
        {"reference": "urn:uuid:condition-1"},
        {"reference": "Condition/elsewhere"},
        {"reference": "urn:uuid:missing"},
        {"display": "Only a display"},
    ]
    summary = _sections(resource)[0]
    assert summary["entryCount"] == 4
    assert summary["entryTypes"] == {"Condition": 1}
    assert summary["unresolved"] == ["Condition/elsewhere", "urn:uuid:missing", "Only a display"]


def test_nested_sections_are_flattened_after_their_parent():
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    parent = resource["entry"][0]["resource"]["section"][0]
    parent["section"] = [
        {
            "title": "Nested",
            "code": {"coding": [{"system": "http://loinc.org", "code": "11348-0"}]},
            "entry": [{"reference": "urn:uuid:condition-1"}],
        }
    ]
    sections = _sections(resource)
    assert [s["path"] for s in sections] == [
        "section[0]",
        "section[0].section[0]",
        "section[1]",
        "section[2]",
    ]
    assert sections[0]["subsectionCount"] == 1
    assert sections[1]["depth"] == 1
    assert sections[1]["entryTypes"] == {"Condition": 1}


def test_contained_references_resolve_inside_the_composition():
    resource = copy.deepcopy(MINIMAL_BUNDLE)
    composition = resource["entry"][0]["resource"]
    composition["contained"] = [{"resourceType": "AllergyIntolerance", "id": "a1"}]
    composition["section"][1]["entry"] = [{"reference": "#a1"}]
    assert _sections(resource)[1]["entryTypes"] == {"AllergyIntolerance": 1}


def test_a_standalone_composition_is_summarised():
    composition = copy.deepcopy(MINIMAL_BUNDLE["entry"][0]["resource"])
    compositions = fhir.summarize_compositions(composition)
    assert len(compositions) == 1
    # Nothing to resolve against outside a Bundle.
    assert compositions[0]["sections"][0]["unresolved"] == ["urn:uuid:condition-1"]


def test_bundle_entries_and_contained_are_walked():
    resource = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "outer",
                    "contained": [{"resourceType": "Observation", "id": "inner"}],
                }
            }
        ],
    }
    ids = [node.get("id") for node in fhir.iter_resources(resource)]
    assert ids == [None, "outer", "inner"]


def test_broken_files_raise(tmp_path: Path):
    bad_json = tmp_path / "a.json"
    bad_json.write_text("{", encoding="utf-8")
    with pytest.raises(fhir.ResourceError, match="invalid JSON"):
        fhir.load_resource(bad_json)
    bad_xml = tmp_path / "a.xml"
    bad_xml.write_text("<Bundle>", encoding="utf-8")
    with pytest.raises(fhir.ResourceError, match="invalid XML"):
        fhir.load_resource(bad_xml)


def test_json_round_trip_of_the_fixture(tmp_path: Path):
    path = tmp_path / "Bundle.json"
    path.write_text(json.dumps(MINIMAL_BUNDLE), encoding="utf-8")
    assert fhir.load_resource(path) == MINIMAL_BUNDLE
