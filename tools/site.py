"""The static site published to GitHub Pages."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import markdown as markdown_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import JsonLexer, XmlLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

from . import igmodel
from . import sections as sections_mod
from .config import Config
from .results import (
    STATUS_ERRORS,
    STATUS_ICON,
    STATUS_LABEL,
    STATUS_NOT_VALIDATED,
    STATUS_ORDER,
    STATUS_VALID,
    STATUS_WARNINGS,
    RunResult,
    SubmissionResult,
    profile_label,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

REPO_URL = "https://github.com/Gefyra/fhir-eps-examples"
SITE_TITLE = "FHIR EPS Examples"
EPS_HOME = "https://hl7.eu/fhir/eps/"

# Tags a contributor README may produce. Everything else is dropped, so a
# merged pull request cannot inject script into the published site.
ALLOWED_TAGS = {
    "p", "br", "hr", "em", "strong", "code", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "img", "sup", "sub", "del",
}
ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "th": {"align"},
    "td": {"align"},
}
VOID_TAGS = {"br", "hr", "img"}
SAFE_URL_PREFIXES = ("http://", "https://", "mailto:", "#", "./", "../")


class _Sanitizer(HTMLParser):
    """Allowlist filter: unknown tags are dropped, their text is kept."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open: list[str] = []

    def _safe_url(self, value: str) -> bool:
        lowered = value.strip().lower()
        return lowered.startswith(SAFE_URL_PREFIXES) or not (":" in lowered.split("/")[0])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRS.get(tag, set())
        rendered = []
        for name, value in attrs:
            if name not in allowed or value is None:
                continue
            if name in ("href", "src") and not self._safe_url(value):
                continue
            rendered.append(f' {name}="{html.escape(value, quote=True)}"')
        self.parts.append(f"<{tag}{''.join(rendered)}>")
        if tag not in VOID_TAGS:
            self._open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ALLOWED_TAGS:
            self.handle_starttag(tag, attrs)
            if tag in self._open and self._open[-1] == tag:
                self._open.pop()
                self.parts.append(f"</{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS and tag in self._open:
            while self._open:
                current = self._open.pop()
                self.parts.append(f"</{current}>")
                if current == tag:
                    break

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data))

    def result(self) -> str:
        while self._open:
            self.parts.append(f"</{self._open.pop()}>")
        return "".join(self.parts)


def render_markdown(text: str) -> str:
    raw = markdown_lib.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists"], output_format="html"
    )
    parser = _Sanitizer()
    parser.feed(raw)
    parser.close()
    return parser.result()


def highlight_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        lexer = get_lexer_for_filename(path.name, text)
    except ClassNotFound:  # pragma: no cover - only json and xml are allowed
        lexer = JsonLexer() if path.suffix == ".json" else XmlLexer()
    formatter = HtmlFormatter(
        linenos="table", lineanchors="L", anchorlinenos=True, cssclass="highlight"
    )
    return highlight(text, lexer, formatter)


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml", "j2"], default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["status_icon"] = lambda s: STATUS_ICON.get(s, "")
    env.filters["status_label"] = lambda s: STATUS_LABEL.get(s, s)
    env.filters["stars"] = lambda n: "★" * int(n) + "☆" * (4 - int(n))
    env.filters["ig_label"] = _ig_label
    env.filters["profile_label"] = profile_label
    env.filters["system_label"] = sections_mod.system_label
    return env


def _ig_label(ig: str) -> str:
    package, _, version = ig.partition("#")
    return f"{package} {version}" if version else package


def badge(run: RunResult) -> dict[str, Any]:
    totals = run.totals()
    parts = []
    for status in (STATUS_VALID, STATUS_WARNINGS, STATUS_ERRORS, STATUS_NOT_VALIDATED):
        if totals.get(status):
            parts.append(f"{totals[status]} {STATUS_LABEL[status]}")
    return {
        "schemaVersion": 1,
        "label": "examples",
        # Informational blue on purpose: errors in the collection are expected.
        "message": " · ".join(parts) or "none yet",
        "color": "blue",
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _readme_html(cfg: Config, submission: SubmissionResult) -> str:
    path = cfg.examples_dir / submission.contributor / submission.slug / "README.md"
    if not path.is_file():
        return ""
    return render_markdown(path.read_text(encoding="utf-8"))


def eps_url(model: dict[str, Any]) -> str:
    """The published EPS version the model was built from."""
    version = model.get("version")
    return f"{EPS_HOME}{version}/" if version else EPS_HOME


def eps_profile_url(model: dict[str, Any], canonical: str) -> str | None:
    """IG page of an EPS profile, None for anything outside the EPS package."""
    url = canonical.partition("|")[0]
    prefix = "http://hl7.eu/fhir/eps/StructureDefinition/"
    if not url.startswith(prefix) or not model.get("version"):
        return None
    return f"{eps_url(model)}StructureDefinition-{url[len(prefix):]}.html"


def _coverage(run: RunResult) -> dict[str, int]:
    eps_sections = [s for s in run.sections if s.get("eps")]
    eps_profiles = (run.profiles or {}).get("eps") or []
    return {
        "sections": len(eps_sections),
        "sectionsCovered": sum(1 for s in eps_sections if s.get("occurrenceCount")),
        "profiles": len(eps_profiles),
        "profilesCovered": sum(1 for p in eps_profiles if p.get("resourceCount")),
    }


def build_site(cfg: Config, run: RunResult, target: Path, delta: dict[str, Any] | None = None) -> None:
    env = _env()
    target.mkdir(parents=True, exist_ok=True)
    model = igmodel.load_model()
    common = {
        "run": run,
        "repo_url": REPO_URL,
        "statuses": STATUS_ORDER,
        "delta": delta or {},
        "site_title": SITE_TITLE,
        "model": model,
        "eps_url": eps_url(model),
        "eps_profile_url": lambda canonical: eps_profile_url(model, canonical),
        "profile_slugs": {
            entry["url"]: entry["slug"]
            for group in ("eps", "other")
            for entry in (run.profiles or {}).get(group) or []
        },
        "section_slugs": {entry["key"]: entry["slug"] for entry in run.sections},
        "coverage": _coverage(run),
    }

    # Assets
    assets = target / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for item in STATIC_DIR.iterdir():
        if item.is_file():
            shutil.copy(item, assets / item.name)
    (assets / "pygments.css").write_text(
        HtmlFormatter(cssclass="highlight").get_style_defs(".highlight"), encoding="utf-8"
    )
    (target / ".nojekyll").write_text("", encoding="utf-8")

    # Machine readable outputs
    _write(target / "results.json", json.dumps(asdict(run), indent=2, ensure_ascii=False) + "\n")
    _write(
        target / "sections.json",
        json.dumps(run.sections, indent=2, ensure_ascii=False) + "\n",
    )
    _write(
        target / "profiles.json",
        json.dumps(run.profiles, indent=2, ensure_ascii=False) + "\n",
    )
    _write(target / "badge.json", json.dumps(badge(run), indent=2) + "\n")

    # Dashboard
    _write(
        target / "index.html",
        env.get_template("index.html.j2").render(base="", totals=run.totals(), **common),
    )

    # Submissions
    submission_template = env.get_template("submission.html.j2")
    file_template = env.get_template("file.html.j2")
    for submission in run.submissions:
        folder = target / "submissions" / submission.contributor / submission.slug
        _write(
            folder / "index.html",
            submission_template.render(
                base="../../../",
                submission=submission,
                readme=_readme_html(cfg, submission),
                checklists=[
                    (file_result, sections_mod.checklist(file_result, model))
                    for file_result in submission.files
                    if file_result.compositions
                ],
                **common,
            ),
        )
        for file_result in submission.files:
            source = cfg.root / file_result.path
            _write(
                folder / f"{file_result.name}.html",
                file_template.render(
                    base="../../../",
                    submission=submission,
                    file=file_result,
                    source=highlight_source(source) if source.is_file() else "",
                    **common,
                ),
            )

    # Sections
    _write(
        target / "sections" / "index.html",
        env.get_template("sections.html.j2").render(base="../", **common),
    )
    section_template = env.get_template("section.html.j2")
    for entry in run.sections:
        _write(
            target / "sections" / f"{entry['slug']}.html",
            section_template.render(base="../", section=entry, **common),
        )

    # Profiles
    _write(
        target / "profiles" / "index.html",
        env.get_template("profiles.html.j2").render(base="../", **common),
    )
    profile_template = env.get_template("profile.html.j2")
    for group in ("eps", "other"):
        for entry in (run.profiles or {}).get(group) or []:
            _write(
                target / "profiles" / f"{entry['slug']}.html",
                profile_template.render(base="../", profile=entry, **common),
            )

    # Contributors
    contributors = _contributors(cfg, run)
    _write(
        target / "contributors" / "index.html",
        env.get_template("contributors.html.j2").render(
            base="../", contributors=contributors, **common
        ),
    )


def _contributors(cfg: Config, run: RunResult) -> list[dict[str, Any]]:
    from .metadata import MetadataError, load_yaml

    grouped: dict[str, dict[str, Any]] = {}
    for submission in run.submissions:
        entry = grouped.setdefault(
            submission.contributor,
            {
                "slug": submission.contributor,
                "name": submission.contributor,
                "github": "",
                "organization": "",
                "url": "",
                "submissions": [],
                "counts": {status: 0 for status in STATUS_ORDER},
            },
        )
        entry["submissions"].append(submission)
        entry["counts"][submission.status] += 1
    for slug, entry in grouped.items():
        path = cfg.examples_dir / slug / "contributor.yaml"
        if not path.is_file():
            continue
        try:
            data = load_yaml(path)
        except MetadataError:
            continue
        entry["name"] = data.get("name", slug)
        entry["github"] = data.get("github", "")
        entry["organization"] = data.get("organization", "")
        entry["url"] = data.get("url", "")
    return [grouped[key] for key in sorted(grouped)]
