"""Index of Composition sections across all submissions, measured against EPS.

This is what makes the collection comparable: one page per section code, one
row per occurrence, so that the way different implementations fill the same
section sits side by side. EPS sections come first, in the order of the EPS
Composition profile, including those nobody has sent yet; sections EPS does
not define follow.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Iterable

from .fhir import split_canonical

if TYPE_CHECKING:  # pragma: no cover
    from .results import FileResult, RunResult

SYSTEM_LABELS = {
    "http://loinc.org": "LOINC",
    "http://snomed.info/sct": "SNOMED CT",
}

CORE_PREFIX = "http://hl7.org/fhir/StructureDefinition/"
ANY_RESOURCE = CORE_PREFIX + "Resource"

REQUIRED = "required"
OPTIONAL = "optional"
NOT_IN_EPS = "not in EPS"

# How a section is filled; the columns of the comparison.
KIND_ENTRIES = "entries"
KIND_EMPTY_REASON = "emptyReason"
KIND_NARRATIVE_ONLY = "narrative only"
KIND_SUBSECTIONS = "subsections only"
KIND_EMPTY = "empty"

# Checklist states on the submission page.
PRESENT = "present"
ABSENT = "absent"
MISSING = "required but missing"


def system_label(system: str) -> str:
    if system in SYSTEM_LABELS:
        return SYSTEM_LABELS[system]
    if not system:
        return "(no system)"
    return system.rstrip("/").rsplit("/", 1)[-1]


def slugify(value: str) -> str:
    """Turn a system URI or code into a safe single path segment."""
    cleaned = re.sub(r"^https?://", "", value or "none")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", cleaned).strip("-")
    return (cleaned or "none").lower()[:80]


def key_of(system: str, code: str) -> str:
    return f"{system}|{code}"


def section_slug(system: str, code: str) -> str:
    if not code:
        return "no-code"
    return f"{slugify(system_label(system))}-{slugify(code)}"


def cardinality(section: dict[str, Any]) -> str:
    return f"{section.get('min', 0)}..{section.get('max', '*')}"


def requirement(section: dict[str, Any] | None) -> str:
    if section is None:
        return NOT_IN_EPS
    return REQUIRED if int(section.get("min", 0)) >= 1 else OPTIONAL


def _versionless(canonical: str) -> str:
    return split_canonical(canonical)[0]


def expected_types(eps_section: dict[str, Any]) -> list[str]:
    """Resource types EPS allows as entries: the core targets such as .../Condition."""
    out = []
    for profile in eps_section.get("entryProfiles") or []:
        url = _versionless(profile)
        if url.startswith(CORE_PREFIX):
            tail = url[len(CORE_PREFIX) :]
            if tail[:1].isupper() and tail not in out:
                out.append(tail)
    return out


def _allows_anything(eps_section: dict[str, Any]) -> bool:
    return any(_versionless(p) == ANY_RESOURCE for p in eps_section.get("entryProfiles") or [])


def eps_section_for(model: dict[str, Any], codes: Iterable[dict[str, str]]) -> dict[str, Any] | None:
    """The EPS section slice whose pattern code matches one of the codings."""
    wanted = {(c.get("system", ""), c.get("code", "")) for c in codes}
    for section in model.get("sections") or []:
        for coding in section.get("codes") or []:
            if (coding.get("system", ""), coding.get("code", "")) in wanted:
                return section
    return None


def annotate(model: dict[str, Any], compositions: list[dict[str, Any]]) -> None:
    """Fill sliceName on every section summary that matches an EPS section."""
    for composition in compositions:
        for section in composition.get("sections") or []:
            match = eps_section_for(model, section.get("codes") or [])
            section["sliceName"] = match["sliceName"] if match else None


def _first_coding(codes: list[dict[str, str]] | None) -> dict[str, str]:
    first = (codes or [{}])[0]
    return {"system": first.get("system", ""), "code": first.get("code", "")}


def _primary_coding(model: dict[str, Any], codes: list[dict[str, str]]) -> dict[str, str]:
    """The coding a section is indexed under: the EPS one if present, else the first."""
    match = eps_section_for(model, codes)
    if match:
        eps_codes = {(c["system"], c["code"]) for c in match.get("codes") or []}
        for coding in codes:
            if (coding.get("system", ""), coding.get("code", "")) in eps_codes:
                return coding
    return codes[0] if codes else {"system": "", "code": "", "display": ""}


def kind(section: dict[str, Any]) -> str:
    if section.get("entryCount"):
        return KIND_ENTRIES
    if section.get("emptyReason"):
        return KIND_EMPTY_REASON
    if section.get("subsectionCount"):
        return KIND_SUBSECTIONS
    if section.get("hasNarrative"):
        return KIND_NARRATIVE_ONLY
    return KIND_EMPTY


def describe(section: dict[str, Any]) -> str:
    """One short phrase for the checklist: '3 entries', 'emptyReason nilknown', ..."""
    filled = kind(section)
    if filled == KIND_ENTRIES:
        count = section.get("entryCount", 0)
        return f"{count} entr{'y' if count == 1 else 'ies'}"
    if filled == KIND_EMPTY_REASON:
        reason = section.get("emptyReason") or {}
        return f"emptyReason {reason.get('code') or reason.get('text') or ''}".strip()
    return filled


def _profile_rows(
    section: dict[str, Any], eps_section: dict[str, Any] | None
) -> list[dict[str, Any]]:
    expected = {_versionless(p) for p in (eps_section or {}).get("entryProfiles") or []}
    anything = bool(eps_section) and _allows_anything(eps_section)
    rows = []
    for profile, count in (section.get("entryProfiles") or {}).items():
        rows.append(
            {
                "profile": profile,
                "count": count,
                # Outside EPS there is no expectation to compare against.
                "expected": eps_section is None or anything or _versionless(profile) in expected,
            }
        )
    return rows


def _type_rows(section: dict[str, Any], eps_section: dict[str, Any] | None) -> list[dict[str, Any]]:
    allowed = expected_types(eps_section) if eps_section else []
    anything = bool(eps_section) and _allows_anything(eps_section)
    return [
        {
            "type": rtype,
            "count": count,
            "expected": eps_section is None or anything or rtype in allowed,
        }
        for rtype, count in (section.get("entryTypes") or {}).items()
    ]


def _eps_info(eps_section: dict[str, Any]) -> dict[str, Any]:
    return {
        "sliceName": eps_section["sliceName"],
        "title": eps_section.get("title") or eps_section["sliceName"],
        "min": eps_section.get("min", 0),
        "max": eps_section.get("max", "*"),
        "cardinality": cardinality(eps_section),
        "entryProfiles": list(eps_section.get("entryProfiles") or []),
        "entrySlices": list(eps_section.get("entrySlices") or []),
        "expectedTypes": expected_types(eps_section),
        "anyResource": _allows_anything(eps_section),
    }


def _new_entry(model: dict[str, Any], system: str, code: str, name: str) -> dict[str, Any]:
    eps_section = eps_section_for(model, [{"system": system, "code": code}]) if code else None
    return {
        "key": key_of(system, code),
        "system": system,
        "systemLabel": system_label(system),
        "code": code,
        "name": (eps_section.get("title") if eps_section else None) or name or code or "(no code)",
        "slug": section_slug(system, code),
        "requirement": requirement(eps_section),
        "eps": _eps_info(eps_section) if eps_section else None,
        "occurrences": [],
    }


def build_index(run: "RunResult", model: dict[str, Any]) -> list[dict[str, Any]]:
    """Group every section occurrence by its code; EPS sections first, in model order."""
    index: dict[str, dict[str, Any]] = {}
    eps_keys: list[str] = []
    for eps_section in model.get("sections") or []:
        codes = eps_section.get("codes") or []
        if not codes:
            continue
        system, code = codes[0].get("system", ""), codes[0].get("code", "")
        key = key_of(system, code)
        if key not in index:
            index[key] = _new_entry(model, system, code, eps_section.get("title", ""))
            eps_keys.append(key)

    for submission in run.submissions:
        for file_result in submission.files:
            for composition in file_result.compositions:
                for section in composition.get("sections") or []:
                    codes = section.get("codes") or []
                    coding = _primary_coding(model, codes)
                    system, code = coding.get("system", ""), coding.get("code", "")
                    eps_section = eps_section_for(model, codes)
                    if eps_section:
                        first = (eps_section.get("codes") or [{}])[0]
                        key = key_of(first.get("system", ""), first.get("code", ""))
                    else:
                        key = key_of(system, code)
                    entry = index.get(key)
                    if entry is None:
                        name = coding.get("display") or section.get("title") or code
                        entry = index[key] = _new_entry(model, system, code, name)
                    entry["occurrences"].append(
                        {
                            "submission": submission.id,
                            "title": submission.title,
                            "contributor": submission.contributor,
                            "status": submission.status,
                            "country": submission.country,
                            "file": file_result.name,
                            "filePath": file_result.path,
                            "compositionId": composition.get("resourceId"),
                            "sectionTitle": section.get("title"),
                            "path": section.get("path"),
                            "depth": section.get("depth", 0),
                            "codes": codes,
                            "entryCount": section.get("entryCount", 0),
                            "entryTypes": _type_rows(section, eps_section),
                            "entryProfiles": _profile_rows(section, eps_section),
                            "entriesWithoutProfile": section.get("entriesWithoutProfile", 0),
                            "unresolved": list(section.get("unresolved") or []),
                            "typeIdMatches": section.get("typeIdMatches", 0),
                            "emptyReason": section.get("emptyReason"),
                            "hasNarrative": section.get("hasNarrative", False),
                            "textStatus": section.get("textStatus"),
                            "subsectionCount": section.get("subsectionCount", 0),
                            "kind": kind(section),
                        }
                    )

    for entry in index.values():
        occurrences = entry["occurrences"]
        entry["submissionCount"] = len({o["submission"] for o in occurrences})
        entry["occurrenceCount"] = len(occurrences)
        entry["withEntries"] = sum(1 for o in occurrences if o["kind"] == KIND_ENTRIES)
        entry["withEmptyReason"] = sum(1 for o in occurrences if o["kind"] == KIND_EMPTY_REASON)
        entry["narrativeOnly"] = sum(1 for o in occurrences if o["kind"] == KIND_NARRATIVE_ONLY)
    others = sorted(
        (key for key in index if key not in eps_keys),
        key=lambda k: (index[k]["systemLabel"], index[k]["code"]),
    )
    ordered = [index[key] for key in eps_keys + others]
    # Two systems with the same short label must not share a page.
    taken: set[str] = set()
    for entry in ordered:
        slug, counter = entry["slug"], 2
        while slug in taken:
            slug = f"{entry['slug']}-{counter}"
            counter += 1
        entry["slug"] = slug
        taken.add(slug)
    return ordered


def checklist(file_result: "FileResult", model: dict[str, Any]) -> list[dict[str, Any]]:
    """Per Composition of a file: every EPS section and whether it is there.

    Only top level sections count; EPS does not nest sections.
    """
    out = []
    for composition in file_result.compositions:
        top = [s for s in composition.get("sections") or [] if not s.get("depth")]
        rows = []
        for eps_section in model.get("sections") or []:
            found = [s for s in top if s.get("sliceName") == eps_section["sliceName"]]
            if found:
                state, detail = PRESENT, ", ".join(describe(s) for s in found)
            elif requirement(eps_section) == REQUIRED:
                state, detail = MISSING, ""
            else:
                state, detail = ABSENT, ""
            first = _first_coding(eps_section.get("codes"))
            rows.append(
                {
                    "sliceName": eps_section["sliceName"],
                    "title": eps_section.get("title") or eps_section["sliceName"],
                    "system": first["system"],
                    "code": first["code"],
                    "key": key_of(first["system"], first["code"]),
                    "cardinality": cardinality(eps_section),
                    "requirement": requirement(eps_section),
                    "state": state,
                    "detail": detail,
                }
            )
        others = [s for s in top if not s.get("sliceName")]
        out.append(
            {
                "compositionId": composition.get("resourceId"),
                "title": composition.get("title"),
                "rows": rows,
                "others": [
                    {
                        "title": s.get("title"),
                        "codes": s.get("codes") or [],
                        "key": key_of(
                            _first_coding(s.get("codes"))["system"], _first_coding(s.get("codes"))["code"]
                        ),
                        "detail": describe(s),
                    }
                    for s in others
                ],
            }
        )
    return out
