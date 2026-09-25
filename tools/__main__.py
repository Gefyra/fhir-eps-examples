"""Command line entry point: python -m tools <command>.

Every CI step is one of these commands, so everything the workflows do can be
reproduced locally with the same call.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ConfigError, load_config, repo_root


def _print_err(message: str) -> None:
    print(message, file=sys.stderr)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _github_output(pairs: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        for key, value in pairs.items():
            print(f"{key}={value}")
        return
    with open(target, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def _job_summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        print(text)
        return
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


# --------------------------------------------------------------------------- check


def cmd_check(args: argparse.Namespace) -> int:
    from .check import github_annotations, run_check, summary_markdown

    cfg = load_config()
    only_ids = None
    if args.changed:
        changed_path = Path(args.changed)
        if changed_path.is_file():
            data = json.loads(changed_path.read_text(encoding="utf-8"))
            if not data.get("full", True):
                only_ids = data.get("submissions", [])
    result = run_check(cfg, only_ids)

    for finding in result.findings:
        print(f"{finding.level}: {finding}")
    print(
        f"\n{len(result.submissions)} submission(s) discovered, "
        f"{len(result.errors)} error(s), {len(result.warnings)} warning(s)."
    )

    if args.github:
        for line in github_annotations(result):
            print(line)
    if args.summary:
        _write(Path(args.summary), summary_markdown(result, len(result.submissions)))
    return 0 if result.ok else 1


# ------------------------------------------------------------------------- changed


def cmd_changed(args: argparse.Namespace) -> int:
    from .changed import changed_submissions

    cfg = load_config()
    payload = changed_submissions(cfg, args.base, args.head)
    _write(Path(args.output), json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    if args.github_output:
        _github_output(
            {
                "has_targets": "true" if payload["submissions"] or payload["full"] else "false",
                "full": "true" if payload["full"] else "false",
            }
        )
    return 0


# ----------------------------------------------------------------- ensure-validator


def cmd_ensure_validator(args: argparse.Namespace) -> int:
    from .validator import ensure_jar

    cfg = load_config()
    path = ensure_jar(cfg)
    print(f"validator jar: {path}")
    return 0


# ------------------------------------------------------------------------ validate


def cmd_validate(args: argparse.Namespace) -> int:
    from .validator import run_validation

    cfg = load_config()
    out_dir = Path(args.out)
    targets: list[str] | None = None
    if args.changed:
        data = json.loads(Path(args.changed).read_text(encoding="utf-8"))
        targets = None if data.get("full") else list(data.get("submissions", []))
    elif args.paths:
        targets = list(args.paths)
    elif not args.all:
        _print_err("validate: pass --all, --changed FILE or one or more paths")
        return 1
    return run_validation(cfg, out_dir, targets=targets, offline=args.offline)


# -------------------------------------------------------------------------- report


def cmd_report(args: argparse.Namespace) -> int:
    from .report_md import render_job_summary, render_pr_comment
    from .results import RunResult, load_run
    from . import baseline as baseline_mod

    cfg = load_config()
    results_file = Path(args.results) / "results.json"
    if results_file.is_file():
        run = load_run(results_file)
    else:
        # The structural checks run before validation, so the comment is built
        # from the check summary alone on that first pass.
        print(f"note: {results_file} does not exist; reporting structural checks only")
        run = RunResult(validator={"version": cfg.validator.version})

    base = None
    if args.baseline:
        base = baseline_mod.load_file(Path(args.baseline))
    elif not args.no_baseline:
        url = args.baseline_url or cfg.report.baselineUrl
        if url:
            base = baseline_mod.fetch(url)
    delta = baseline_mod.diff(run, base) if base else {}

    check_summary = None
    if args.check_summary and Path(args.check_summary).is_file():
        check_summary = Path(args.check_summary).read_text(encoding="utf-8")

    if args.pr_comment:
        body = render_pr_comment(
            cfg, run, delta, check_summary=check_summary, run_url=args.run_url, baseline=base
        )
        _write(Path(args.pr_comment), body)
        print(f"pull request comment written to {args.pr_comment} ({len(body)} chars)")
    if args.job_summary:
        _job_summary(render_job_summary(cfg, run, delta))
    if args.site:
        from .site import build_site

        target = Path(args.site)
        build_site(cfg, run, target, delta=delta)
        print(f"site written to {target}")
    return 0


# ------------------------------------------------------------------------ ig-model


def cmd_ig_model(args: argparse.Namespace) -> int:
    from .igmodel import MODEL_PATH, ModelError, generate

    target = Path(args.out) if args.out else MODEL_PATH
    try:
        generate(args.package, target, composition_url=args.composition)
    except ModelError as exc:
        _print_err(f"ig-model: {exc}")
        return 1
    return 0


# -------------------------------------------------------------------- print-config


def cmd_print_config(args: argparse.Namespace) -> int:
    import yaml

    from .config import config_hash, dotted_get
    from .discover import discover
    from .metadata import all_effective_igs, load_all

    cfg = load_config()
    data = yaml.safe_load(cfg.raw_text)
    if args.key:
        value = dotted_get(data, args.key)
        print(value if not isinstance(value, (dict, list)) else json.dumps(value))
        return 0
    submissions = discover(cfg)
    load_all(cfg, submissions)
    igs = all_effective_igs(cfg, submissions)
    pairs = {
        "validator_version": cfg.validator.version,
        "config_hash": config_hash(cfg, igs),
        "java_args": " ".join(cfg.validator.javaArgs),
    }
    if args.github_output:
        _github_output(pairs)
    else:
        for key, value in pairs.items():
            print(f"{key}={value}")
    return 0


def cmd_set_config(args: argparse.Namespace) -> int:
    """Rewrite one scalar value in place, keeping comments and formatting."""
    import re

    cfg_path = repo_root() / "validation.config.yaml"
    parts = args.key.split(".")
    text = cfg_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    depth = 0
    index = 0
    replaced = False
    for part in parts:
        pattern = re.compile(r"^(\s{" + str(depth * 2) + r"})(" + re.escape(part) + r"):(.*)$")
        while index < len(lines):
            match = pattern.match(lines[index])
            if match:
                if part is parts[-1] or depth == len(parts) - 1:
                    quoted = args.value
                    if not re.fullmatch(r"(true|false|null|-?\d+(\.\d+)?)", quoted):
                        quoted = f'"{quoted}"'
                    comment = ""
                    tail = match.group(3)
                    if "#" in tail:
                        comment = "  #" + tail.split("#", 1)[1]
                    lines[index] = f"{match.group(1)}{part}: {quoted}{comment}"
                    replaced = True
                break
            index += 1
        index += 1
        depth += 1
    if not replaced:
        _print_err(f"set-config: key {args.key} not found in {cfg_path}")
        return 1
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{args.key} = {args.value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tools", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="structural checks (the only gate)")
    p_check.add_argument("--changed", help="restrict per-submission checks to .ci/changed.json")
    p_check.add_argument("--github", action="store_true", help="emit GitHub annotations")
    p_check.add_argument("--summary", help="write a markdown summary to this file")
    p_check.set_defaults(func=cmd_check)

    p_changed = sub.add_parser("changed", help="map a diff range to submissions")
    p_changed.add_argument("--base", required=True)
    p_changed.add_argument("--head", required=True)
    p_changed.add_argument("--output", required=True)
    p_changed.add_argument("--github-output", action="store_true")
    p_changed.set_defaults(func=cmd_changed)

    p_ensure = sub.add_parser("ensure-validator", help="download and verify the pinned validator jar")
    p_ensure.set_defaults(func=cmd_ensure_validator)

    p_validate = sub.add_parser("validate", help="run the FHIR validator")
    p_validate.add_argument("paths", nargs="*", help="submission folders or ids")
    p_validate.add_argument("--all", action="store_true")
    p_validate.add_argument("--changed", help="read targets from .ci/changed.json")
    p_validate.add_argument("--out", default="results", help="output folder (default: results)")
    p_validate.add_argument("--offline", action="store_true", help="run without a terminology server")
    p_validate.set_defaults(func=cmd_validate)

    p_report = sub.add_parser("report", help="render comment, job summary and site")
    p_report.add_argument("--results", default="results")
    p_report.add_argument("--baseline", help="local results.json to compare against")
    p_report.add_argument(
        "--baseline-url", help="URL of the results.json published from main (default: report.baselineUrl)"
    )
    p_report.add_argument("--no-baseline", action="store_true", help="do not compare against main")
    p_report.add_argument("--pr-comment", help="write the pull request comment here")
    p_report.add_argument("--check-summary", help="markdown produced by 'check --summary'")
    p_report.add_argument("--run-url", help="URL of the workflow run, linked in the comment")
    p_report.add_argument("--job-summary", action="store_true")
    p_report.add_argument("--site", help="build the static site into this folder")
    p_report.set_defaults(func=cmd_report)

    p_model = sub.add_parser(
        "ig-model", help="regenerate tools/data/eps-model.json from an EPS package"
    )
    p_model.add_argument("package", help="package#version, e.g. hl7.fhir.eu.eps#1.0.0-ballot")
    p_model.add_argument("--out", help="write here instead of tools/data/eps-model.json")
    p_model.add_argument(
        "--composition", help="canonical of the Composition profile, if the package has several"
    )
    p_model.set_defaults(func=cmd_ig_model)

    p_print = sub.add_parser("print-config", help="print config values for the workflows")
    p_print.add_argument("--key", help="dotted key, e.g. validator.version")
    p_print.add_argument("--github-output", action="store_true")
    p_print.set_defaults(func=cmd_print_config)

    p_set = sub.add_parser("set-config", help="set one scalar config value in place")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.set_defaults(func=cmd_set_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        _print_err(f"configuration error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
