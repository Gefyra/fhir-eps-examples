"""Parsing the validator output, attributing it and building the command line."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import EPS_BUNDLE, MINIMAL_OBSERVATION, bundle
from tools.discover import discover
from tools.metadata import load_all
from tools.validator import attribute, build_command, build_groups, parse_output, tail

EXT = "http://hl7.org/fhir/StructureDefinition"


def outcome(file_path: str, issues: list[dict]) -> dict:
    return {
        "resourceType": "OperationOutcome",
        "extension": [{"url": f"{EXT}/operationoutcome-file", "valueString": file_path}],
        "issue": issues,
    }


def issue(severity: str, message_id: str, expression: str, text: str, line: int = 7) -> dict:
    return {
        "severity": severity,
        "code": "processing",
        "details": {"text": text},
        "expression": [expression],
        "extension": [
            {"url": f"{EXT}/operationoutcome-message-id", "valueString": message_id},
            {"url": f"{EXT}/operationoutcome-issue-line", "valueInteger": line},
            {"url": f"{EXT}/operationoutcome-issue-col", "valueInteger": 3},
            {"url": f"{EXT}/operationoutcome-issue-source", "valueString": "InstanceValidator"},
        ],
    }


def test_parse_bundle_of_outcomes(tmp_path: Path):
    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {"resource": outcome("/abs/a.json", [issue("error", "ID_ONE", "Observation.status", "boom")])},
            {"resource": outcome("/abs/b.json", [])},
        ],
    }
    path = tmp_path / "group-1.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    parsed = parse_output(path)
    assert [source for source, _ in parsed] == ["/abs/a.json", "/abs/b.json"]
    first = parsed[0][1][0]
    assert first.severity == "error"
    assert first.messageId == "ID_ONE"
    assert first.line == 7 and first.col == 3
    assert first.location == "Observation.status"
    assert first.source == "InstanceValidator"


def test_parse_single_outcome(tmp_path: Path):
    path = tmp_path / "single.json"
    path.write_text(
        json.dumps(outcome("/abs/a.json", [issue("warning", "W", "Observation", "hm")])),
        encoding="utf-8",
    )
    parsed = parse_output(path)
    assert len(parsed) == 1
    assert parsed[0][1][0].severity == "warning"


def test_parse_rejects_other_resources(tmp_path: Path):
    path = tmp_path / "nope.json"
    path.write_text(json.dumps({"resourceType": "Patient"}), encoding="utf-8")
    with pytest.raises(ValueError):
        parse_output(path)


def test_attribution_by_absolute_path(tmp_path: Path):
    first = tmp_path / "Observation-a.json"
    second = tmp_path / "Observation-b.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    parsed = [
        (str(second.resolve()), [issue("error", "E", "Observation", "second")]),
        (str(first.resolve()), [issue("warning", "W", "Observation", "first")]),
    ]
    parsed = [(source, parse_issue_list(issues)) for source, issues in parsed]
    attributed, leftovers = attribute(parsed, [first, second])
    assert not leftovers
    assert attributed[first][0].severity == "warning"
    assert attributed[second][0].severity == "error"


def parse_issue_list(issues: list[dict]):
    from tools.validator import _issue_from

    return [_issue_from(i) for i in issues]


def test_attribution_falls_back_to_a_suffix_match(tmp_path: Path):
    target = tmp_path / "Observation-a.json"
    target.write_text("{}", encoding="utf-8")
    parsed = [("Observation-a.json", parse_issue_list([issue("error", "E", "Observation", "x")]))]
    attributed, leftovers = attribute(parsed, [target])
    assert not leftovers
    assert target in attributed


def test_unattributable_outcomes_are_kept(tmp_path: Path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    for path in (first, second):
        path.write_text("{}", encoding="utf-8")
    parsed = [
        ("/somewhere/else.json", parse_issue_list([issue("error", "E", "Observation", "x")])),
        (str(first.resolve()), []),
    ]
    attributed, leftovers = attribute(parsed, [first, second])
    assert len(leftovers) == 1
    assert second not in attributed


def _groups(cfg):
    submissions = discover(cfg)
    load_all(cfg, submissions)
    return build_groups(cfg, submissions)


def test_grouping_and_command(cfg, make_submission):
    make_submission(slug="one")
    make_submission(slug="two", metadata="title: Two\norigin: synthetic\nigs:\n  - hl7.fhir.fi.base#2.0.0\n")
    groups = _groups(cfg)
    assert len(groups) == 2

    plain = [g for g in groups if "hl7.fhir.fi.base#2.0.0" not in g.igs][0]
    command = build_command(cfg, plain, Path("/out.json"), Path("/out.html"))
    assert command[0] == "java"
    assert "-Xmx4g" in command
    assert command[command.index("-version") + 1] == "4.0.1"
    assert command[command.index("-ig") + 1] == "hl7.fhir.eu.eps#1.0.0-ballot"
    assert command[command.index("-tx") + 1] == "https://tx.fhir.org"
    assert "-show-message-ids" in command
    assert command[-1].startswith("/")  # absolute source paths


def test_document_bundles_get_the_enforced_profile(cfg, make_submission):
    make_submission()
    (group,) = _groups(cfg)
    assert group.profile == EPS_BUNDLE
    command = build_command(cfg, group, Path("/out.json"), Path("/out.html"))
    position = command.index("-profile")
    assert command[position + 1] == EPS_BUNDLE
    # After the IGs, before the terminology server.
    assert command.index("-ig") < position < command.index("-tx")


def test_other_files_get_no_profile(cfg, make_submission):
    make_submission(slug="single", resource=MINIMAL_OBSERVATION, resource_name="Observation-a.json")
    make_submission(slug="collection", resource=bundle(type="collection"))
    (group,) = _groups(cfg)
    assert group.profile is None
    assert "-profile" not in build_command(cfg, group, Path("/out.json"), Path("/out.html"))


def test_opting_out_drops_the_enforced_profile(cfg, make_submission):
    make_submission(slug="enforced")
    make_submission(slug="opted-out", metadata="title: T\norigin: synthetic\nenforceProfile: false\n")
    groups = _groups(cfg)
    assert {g.profile: [s.id for s in g.submissions] for g in groups} == {
        None: ["someone/opted-out"],
        EPS_BUNDLE: ["someone/enforced"],
    }


def test_one_submission_can_span_two_groups(cfg, make_submission):
    directory = make_submission()
    (directory / "Observation-extra.json").write_text(json.dumps(MINIMAL_OBSERVATION), encoding="utf-8")
    groups = _groups(cfg)
    assert len(groups) == 2
    by_profile = {g.profile: [p.name for p in g.files] for g in groups}
    assert by_profile == {None: ["Observation-extra.json"], EPS_BUNDLE: ["Bundle-example.json"]}
    assert all([s.id for s in g.submissions] == ["someone/example-submission"] for g in groups)


def test_a_split_submission_is_aggregated_once(cfg, make_submission, monkeypatch, tmp_path: Path):
    """Both groups run; the submission gets both group numbers and the worst status."""
    from tools import validator
    from tools.results import GroupResult, load_run

    directory = make_submission()
    (directory / "Observation-extra.json").write_text(json.dumps(MINIMAL_OBSERVATION), encoding="utf-8")

    def fake_run(cfg_, group_, out_dir_, offline=False):
        raw = out_dir_ / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        severity = "error" if group_.profile else "warning"
        bundle_of_outcomes = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {"resource": outcome(str(path.resolve()), [issue(severity, f"ID_{group_.index}", "X", "x")])}
                for path in group_.files
            ],
        }
        (raw / f"group-{group_.index}.json").write_text(json.dumps(bundle_of_outcomes), encoding="utf-8")
        return GroupResult(
            index=group_.index,
            fhirVersion=group_.fhirVersion,
            igs=list(group_.igs),
            files=[str(p) for p in group_.files],
            profile=group_.profile,
            exitCode=0,
        )

    monkeypatch.setattr(validator, "ensure_jar", lambda cfg_: None)
    monkeypatch.setattr(validator, "sha256_file", lambda path: "0" * 64)
    monkeypatch.setattr(validator, "java_version", lambda: "test")
    monkeypatch.setattr(validator, "run_group_with_retries", fake_run)

    out = tmp_path / "results"
    assert validator.run_validation(cfg, out) == 0
    run = load_run(out / "results.json")
    (submission,) = run.submissions
    assert submission.groups == [1, 2]
    files = {f.name: f for f in submission.files}
    assert files["Bundle-example.json"].enforcedProfile == EPS_BUNDLE
    assert files["Bundle-example.json"].status == "errors"
    assert files["Observation-extra.json"].enforcedProfile is None
    assert files["Observation-extra.json"].status == "warnings"
    assert {f.group for f in submission.files} == {1, 2}
    assert submission.status == "errors"
    assert submission.counts.errors == 1 and submission.counts.warnings == 1
    assert [g.profile for g in run.groups] == [None, EPS_BUNDLE]
    # The indexes are built in the same run.
    assert run.model["package"] == "hl7.fhir.eu.eps"
    assert any(s["occurrenceCount"] for s in run.sections)
    assert run.profiles["eps"]


def test_offline_command_has_no_terminology_server(cfg, make_submission):
    make_submission()
    group = _groups(cfg)[0]
    command = build_command(cfg, group, Path("/out.json"), Path("/out.html"), offline=True)
    assert command[command.index("-tx") + 1] == "n/a"
    assert "-txCache" not in command


def test_tail_returns_the_last_lines(tmp_path: Path):
    log = tmp_path / "log.txt"
    log.write_text("\n".join(str(n) for n in range(100)), encoding="utf-8")
    assert tail(log, 5) == ["95", "96", "97", "98", "99"]
    assert tail(tmp_path / "missing.txt", 5) == []


# ------------------------------------------------------------ terminology retries


def test_terminology_failure_detection(tmp_path: Path):
    from tools.validator import terminology_failure

    log = tmp_path / "group-1.log"
    assert terminology_failure(log) is False  # no log at all
    log.write_text("Loading\n  Loading FHIR v4.0.1\n", encoding="utf-8")
    assert terminology_failure(log) is False
    log.write_text(
        "org.hl7.fhir.exceptions.FHIRException: Unable to connect to terminology server "
        "at https://tx.fhir.org. Use parameter '-tx n/a' ...\n",
        encoding="utf-8",
    )
    assert terminology_failure(log) is True


def _fake_run_group(calls: list[bool], log_text_when_online: str, crash_online: bool):
    from tools.results import GroupResult

    def fake(cfg_, group_, out_dir_, offline=False):
        calls.append(offline)
        raw = out_dir_ / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        log = raw / f"group-{group_.index}.log"
        result = GroupResult(
            index=group_.index,
            fhirVersion=group_.fhirVersion,
            igs=list(group_.igs),
            files=[str(p) for p in group_.files],
        )
        if offline or not crash_online:
            log.write_text("done\n", encoding="utf-8")
            result.exitCode = 0
        else:
            log.write_text(log_text_when_online, encoding="utf-8")
            result.crashed = True
            result.exitCode = 1
            result.reason = "the validator exited with code 1 and produced no output file"
        return result

    return fake


def test_terminology_crash_is_retried_then_validated_offline(
    cfg, make_submission, monkeypatch, tmp_path: Path
):
    from tools import validator

    make_submission()
    submissions = discover(cfg)
    load_all(cfg, submissions)
    group = build_groups(cfg, submissions)[0]
    calls: list[bool] = []
    monkeypatch.setattr(
        validator,
        "run_group",
        _fake_run_group(calls, "Unable to connect to terminology server at x\n", True),
    )
    monkeypatch.setattr(validator, "_sleep", lambda seconds: None)

    result = validator.run_group_with_retries(cfg, group, tmp_path / "results")

    # first attempt + retries from the config + one offline run
    assert calls == [False] * (1 + cfg.terminology.retries) + [True]
    assert result.crashed is False
    assert result.terminologyFallback is True
    assert result.attempts == len(calls)
    kept = sorted(p.name for p in (tmp_path / "results" / "raw").glob("group-1.attempt-*.log"))
    assert kept == [f"group-1.attempt-{n}.log" for n in range(1, len(calls))]


def test_other_crashes_are_not_retried(cfg, make_submission, monkeypatch, tmp_path: Path):
    from tools import validator

    make_submission()
    submissions = discover(cfg)
    load_all(cfg, submissions)
    group = build_groups(cfg, submissions)[0]
    calls: list[bool] = []
    monkeypatch.setattr(
        validator, "run_group", _fake_run_group(calls, "java.lang.OutOfMemoryError\n", True)
    )
    monkeypatch.setattr(validator, "_sleep", lambda seconds: None)

    result = validator.run_group_with_retries(cfg, group, tmp_path / "results")

    assert calls == [False]
    assert result.crashed is True
    assert result.terminologyFallback is False
    assert result.attempts == 1


def test_no_offline_fallback_when_disabled(cfg, make_submission, monkeypatch, tmp_path: Path):
    import dataclasses

    from tools import validator

    cfg = dataclasses.replace(
        cfg, terminology=dataclasses.replace(cfg.terminology, fallbackToOffline=False)
    )
    make_submission()
    submissions = discover(cfg)
    load_all(cfg, submissions)
    group = build_groups(cfg, submissions)[0]
    calls: list[bool] = []
    monkeypatch.setattr(
        validator,
        "run_group",
        _fake_run_group(calls, "Error fetching the server's capability statement: timeout\n", True),
    )
    monkeypatch.setattr(validator, "_sleep", lambda seconds: None)

    result = validator.run_group_with_retries(cfg, group, tmp_path / "results")

    assert calls == [False] * (1 + cfg.terminology.retries)
    assert result.crashed is True
    assert result.terminologyFallback is False
