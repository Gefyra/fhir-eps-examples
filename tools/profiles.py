"""Index of declared profiles: which EPS profiles the collection covers.

Every profile of the EPS package is listed, with the resources that declare it
in meta.profile; the ones nobody declares yet stand out as "no example yet".
Everything else that is declared (IPS, national profiles, typos) is listed as
"other declared profiles". Canonicals are keyed without their |version, which
is kept for display.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .fhir import split_canonical
from .results import profile_label
from .sections import slugify

if TYPE_CHECKING:  # pragma: no cover
    from .results import RunResult


def _unique_slug(url: str, taken: set[str]) -> str:
    """'http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps' -> 'hl7.eu-fhir-eps-bundle-eu-eps'."""
    base = slugify(re.sub(r"\.html?$", "", url.replace("/StructureDefinition/", "/")))
    slug, counter = base, 2
    while slug in taken:
        slug = f"{base}-{counter}"
        counter += 1
    taken.add(slug)
    return slug


def _rows(run: "RunResult") -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Declaring resources per versionless canonical, and every resource at all."""
    declared: dict[str, list[dict[str, Any]]] = {}
    everything: list[dict[str, Any]] = []
    for submission in run.submissions:
        for file_result in submission.files:
            for resource in file_result.resources:
                row = {
                    "submission": submission.id,
                    "title": submission.title,
                    "contributor": submission.contributor,
                    "status": submission.status,
                    "file": file_result.name,
                    "filePath": file_result.path,
                    "resourceType": resource.get("resourceType"),
                    "id": resource.get("id"),
                    "fullUrl": resource.get("fullUrl"),
                    "profiles": list(resource.get("profiles") or []),
                }
                everything.append(row)
                seen: set[str] = set()
                for canonical in row["profiles"]:
                    url = split_canonical(canonical)[0]
                    if url in seen:
                        continue
                    seen.add(url)
                    declared.setdefault(url, []).append(dict(row, declaredAs=canonical))
    return declared, everything


def _versions(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({v for row in rows if (v := split_canonical(row["declaredAs"])[1])})


def _enforced_files(run: "RunResult", url: str) -> int:
    return sum(
        1
        for submission in run.submissions
        for file_result in submission.files
        if file_result.enforcedProfile and split_canonical(file_result.enforcedProfile)[0] == url
    )


def build_index(run: "RunResult", model: dict[str, Any]) -> dict[str, Any]:
    declared, everything = _rows(run)
    taken: set[str] = set()
    eps: list[dict[str, Any]] = []
    eps_urls: set[str] = set()
    for profile in model.get("profiles") or []:
        url = profile["url"]
        eps_urls.add(url)
        rows = declared.get(url, [])
        same_type = [r for r in everything if r["resourceType"] == profile.get("type")]
        undeclared = [
            r for r in same_type if url not in {split_canonical(p)[0] for p in r["profiles"]}
        ]
        eps.append(
            {
                "url": url,
                "label": profile_label(url),
                "name": profile.get("name", ""),
                "title": profile.get("title", ""),
                "types": [profile.get("type", "")],
                "slug": _unique_slug(url, taken),
                "eps": True,
                "versions": _versions(rows),
                "resources": rows,
                "resourceCount": len(rows),
                "submissionCount": len({r["submission"] for r in rows}),
                "undeclaredCount": len(undeclared),
                "enforcedFileCount": _enforced_files(run, url),
            }
        )
    other: list[dict[str, Any]] = []
    for url in sorted(u for u in declared if u not in eps_urls):
        rows = declared[url]
        other.append(
            {
                "url": url,
                "label": profile_label(url),
                "name": "",
                "title": "",
                "types": sorted({str(r["resourceType"]) for r in rows}),
                "slug": _unique_slug(url, taken),
                "eps": False,
                "versions": _versions(rows),
                "resources": rows,
                "resourceCount": len(rows),
                "submissionCount": len({r["submission"] for r in rows}),
                "undeclaredCount": None,
                "enforcedFileCount": _enforced_files(run, url),
            }
        )
    return {
        "package": model.get("package"),
        "version": model.get("version"),
        "eps": eps,
        "other": other,
    }
