"""Minimal reading and summarising of FHIR resources (JSON and XML)."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator

FHIR_NS = "http://hl7.org/fhir"
_PRIMITIVE_HOLDER = "value"


class ResourceError(Exception):
    """Raised when a file cannot be read as a FHIR resource."""


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _is_resource_container(element: ET.Element) -> bool:
    """Bundle.entry.resource, contained and friends wrap exactly one resource.

    FHIR element names are lowerCamelCase and resource names UpperCamelCase, so
    a single child starting with a capital letter is a nested resource.
    """
    return len(element) == 1 and _localname(element[0].tag)[:1].isupper()


def xml_to_dict(element: ET.Element) -> Any:
    """Convert FHIR XML to the JSON object model (good enough for summaries)."""
    node: dict[str, Any] = {}
    value = element.get(_PRIMITIVE_HOLDER)
    if value is not None:
        # A primitive element; may still carry id/extension children.
        if len(element) == 0:
            return value
        node[_PRIMITIVE_HOLDER] = value
    for child in element:
        name = _localname(child.tag)
        if name == "div":
            # The narrative is XHTML, not FHIR; keep it as the string JSON has.
            converted: Any = ET.tostring(child, encoding="unicode")
        elif _is_resource_container(child):
            converted = xml_to_dict(child[0])
            if isinstance(converted, dict):
                converted["resourceType"] = _localname(child[0].tag)
        else:
            converted = xml_to_dict(child)
        if name in node:
            existing = node[name]
            if isinstance(existing, list):
                existing.append(converted)
            else:
                node[name] = [existing, converted]
        else:
            node[name] = converted
    if _PRIMITIVE_HOLDER in node and len(node) == 1:
        return node[_PRIMITIVE_HOLDER]
    return node


def as_list(value: Any) -> list[Any]:
    """XML has no arrays; single occurrences stay scalars. Callers use as_list()."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_resource(path: Path) -> dict[str, Any]:
    """Read one FHIR resource file. Raises ResourceError on any problem."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResourceError(f"cannot read file: {exc}") from exc
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ResourceError(f"invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ResourceError("top level JSON value is not an object")
        return data
    if suffix == ".xml":
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ResourceError(f"invalid XML: {exc}") from exc
        data = xml_to_dict(root)
        if not isinstance(data, dict):
            raise ResourceError("top level XML element has no content")
        data["resourceType"] = _localname(root.tag)
        return data
    raise ResourceError(f"unsupported file extension {suffix!r}")


def resource_type(resource: dict[str, Any]) -> str | None:
    value = resource.get("resourceType")
    return value if isinstance(value, str) else None


def resource_id(resource: dict[str, Any]) -> str | None:
    value = resource.get("id")
    return value if isinstance(value, str) else None


def iter_resources(resource: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield the root resource, Bundle entries and contained resources."""
    if not isinstance(resource, dict):
        return
    yield resource
    for contained in as_list(resource.get("contained")):
        if isinstance(contained, dict):
            yield from iter_resources(contained)
    for entry in as_list(resource.get("entry")):
        if isinstance(entry, dict) and isinstance(entry.get("resource"), dict):
            yield from iter_resources(entry["resource"])


def iter_entries(bundle: dict[str, Any]) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """(fullUrl, resource) for every Bundle entry that carries a resource."""
    for entry in as_list(bundle.get("entry")):
        if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
            continue
        full_url = entry.get("fullUrl")
        yield (full_url if isinstance(full_url, str) else None), entry["resource"]


def profiles(resource: dict[str, Any]) -> list[str]:
    meta = resource.get("meta")
    if not isinstance(meta, dict):
        return []
    return [p for p in as_list(meta.get("profile")) if isinstance(p, str)]


def split_canonical(canonical: str) -> tuple[str, str | None]:
    """'http://x/StructureDefinition/y|2.0.0' -> ('http://x/StructureDefinition/y', '2.0.0')."""
    url, _, version = canonical.partition("|")
    return url, (version or None)


def codings(concept: Any) -> list[dict[str, str]]:
    if not isinstance(concept, dict):
        return []
    out: list[dict[str, str]] = []
    for coding in as_list(concept.get("coding")):
        if not isinstance(coding, dict):
            continue
        entry = {
            "system": str(coding.get("system")) if coding.get("system") is not None else "",
            "code": str(coding.get("code")) if coding.get("code") is not None else "",
            "display": str(coding.get("display")) if coding.get("display") is not None else "",
        }
        if entry["code"] or entry["system"]:
            out.append(entry)
    return out


def bundle_type(resource: dict[str, Any]) -> str | None:
    if resource_type(resource) != "Bundle":
        return None
    value = resource.get("type")
    return value if isinstance(value, str) else None


def is_document_bundle(resource: dict[str, Any]) -> bool:
    return bundle_type(resource) == "document"


def resource_summaries(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """The root resource and every Bundle entry: type, id, fullUrl, declared profiles.

    This is what the profile index is built from. Contained resources are left
    out; nothing outside their container can refer to them.
    """
    out = [
        {
            "resourceType": resource_type(resource) or "Unknown",
            "id": resource_id(resource),
            "fullUrl": None,
            "profiles": profiles(resource),
        }
    ]
    if resource_type(resource) == "Bundle":
        for full_url, entry in iter_entries(resource):
            out.append(
                {
                    "resourceType": resource_type(entry) or "Unknown",
                    "id": resource_id(entry),
                    "fullUrl": full_url,
                    "profiles": profiles(entry),
                }
            )
    return out


# ---------------------------------------------------------------- references

_RELATIVE_REF = re.compile(
    r"^(?P<type>[A-Z][A-Za-z]+)/(?P<id>[A-Za-z0-9\-.]{1,64})(?:/_history/[A-Za-z0-9\-.]{1,64})?$"
)
_ABSOLUTE_REF = re.compile(
    r"^(?P<base>https?://.+?)/(?P<type>[A-Z][A-Za-z]+)/(?P<id>[A-Za-z0-9\-.]{1,64})"
    r"(?:/_history/[A-Za-z0-9\-.]{1,64})?$"
)


class BundleIndex:
    """Resolves references between the entries of one Bundle.

    A reference that equals a fullUrl (urn:uuid: or absolute) resolves to that
    entry, and a relative Type/id is resolved against the base of the
    referencing entry's fullUrl, as FHIR prescribes. Beyond that, a relative
    Type/id also matches an entry by resource type and id; FHIR does not allow
    that, the validator reports it, and the summaries count it separately so
    the comparison shows it instead of hiding it.
    """

    # How a reference was resolved.
    CONTAINED = "contained"
    FULL_URL = "fullUrl"
    BASE = "base"
    TYPE_ID = "typeId"

    def __init__(self, bundle: dict[str, Any] | None = None) -> None:
        self.by_full_url: dict[str, dict[str, Any]] = {}
        self.by_type_id: dict[str, dict[str, Any]] = {}
        if bundle is None or resource_type(bundle) != "Bundle":
            return
        for full_url, entry in iter_entries(bundle):
            if full_url:
                self.by_full_url.setdefault(full_url, entry)
            rtype, rid = resource_type(entry), resource_id(entry)
            if rtype and rid:
                self.by_type_id.setdefault(f"{rtype}/{rid}", entry)

    def resolve(
        self,
        reference: str,
        context_full_url: str | None = None,
        container: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self.resolve_with_rule(reference, context_full_url, container)[0]

    def resolve_with_rule(
        self,
        reference: str,
        context_full_url: str | None = None,
        container: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        ref = reference.strip()
        if not ref:
            return None, None
        if ref.startswith("#"):
            for contained in as_list((container or {}).get("contained")):
                if isinstance(contained, dict) and resource_id(contained) == ref[1:]:
                    return contained, self.CONTAINED
            return None, None
        if ref in self.by_full_url:
            return self.by_full_url[ref], self.FULL_URL
        relative = _RELATIVE_REF.match(ref)
        if relative:
            key = f"{relative.group('type')}/{relative.group('id')}"
            base = _ABSOLUTE_REF.match(context_full_url or "")
            if base:
                candidate = f"{base.group('base')}/{key}"
                if candidate in self.by_full_url:
                    return self.by_full_url[candidate], self.BASE
            found = self.by_type_id.get(key)
            return found, (self.TYPE_ID if found is not None else None)
        absolute = _ABSOLUTE_REF.match(ref)
        if absolute:
            # A versioned absolute reference still points at the entry.
            versionless = f"{absolute.group('base')}/{absolute.group('type')}/{absolute.group('id')}"
            found = self.by_full_url.get(versionless)
            return found, (self.FULL_URL if found is not None else None)
        return None, None


# ------------------------------------------------------------------ sections


def iter_compositions(resource: dict[str, Any]) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """(fullUrl, Composition) for a root Composition or the entries of a Bundle."""
    if resource_type(resource) == "Composition":
        yield None, resource
        return
    if resource_type(resource) == "Bundle":
        for full_url, entry in iter_entries(resource):
            if resource_type(entry) == "Composition":
                yield full_url, entry


def _empty_reason(section: dict[str, Any]) -> dict[str, str] | None:
    concept = section.get("emptyReason")
    if not isinstance(concept, dict):
        return None
    found = codings(concept)
    code = found[0]["code"] if found else ""
    text = str(concept.get("text") or (found[0]["display"] if found else "") or "")
    if not code and not text:
        return None
    return {"code": code, "text": text}


def _narrative(section: dict[str, Any]) -> tuple[bool, str | None]:
    text = section.get("text")
    if not isinstance(text, dict):
        return False, None
    div = text.get("div")
    status = text.get("status")
    return (isinstance(div, str) and bool(div.strip())), (status if isinstance(status, str) else None)


def summarize_section(
    section: dict[str, Any],
    index: BundleIndex,
    composition: dict[str, Any],
    composition_full_url: str | None,
    path: str = "section[0]",
    depth: int = 0,
) -> dict[str, Any]:
    """What a section carries: codes, resolved entries, emptyReason, narrative."""
    entry_types: dict[str, int] = {}
    entry_profiles: dict[str, int] = {}
    unresolved: list[str] = []
    without_profile = 0
    type_id_matches = 0
    entries = [e for e in as_list(section.get("entry")) if isinstance(e, dict)]
    for entry in entries:
        reference = entry.get("reference")
        target, rule = (
            index.resolve_with_rule(reference, composition_full_url, composition)
            if isinstance(reference, str)
            else (None, None)
        )
        if rule == BundleIndex.TYPE_ID:
            type_id_matches += 1
        if target is None:
            label = reference if isinstance(reference, str) else (entry.get("display") or "(no reference)")
            unresolved.append(str(label))
            continue
        rtype = resource_type(target) or "Unknown"
        entry_types[rtype] = entry_types.get(rtype, 0) + 1
        declared = profiles(target)
        if not declared:
            without_profile += 1
        for profile in declared:
            entry_profiles[profile] = entry_profiles.get(profile, 0) + 1
    has_div, text_status = _narrative(section)
    subsections = [s for s in as_list(section.get("section")) if isinstance(s, dict)]
    title = section.get("title")
    return {
        "path": path,
        "depth": depth,
        "title": title if isinstance(title, str) else None,
        "codes": codings(section.get("code")),
        "entryCount": len(entries),
        "entryTypes": dict(sorted(entry_types.items())),
        "entryProfiles": dict(sorted(entry_profiles.items())),
        "entriesWithoutProfile": without_profile,
        "unresolved": unresolved,
        # Resolved only by type and id, against the FHIR rules; see BundleIndex.
        "typeIdMatches": type_id_matches,
        "emptyReason": _empty_reason(section),
        "hasNarrative": has_div,
        "textStatus": text_status,
        "subsectionCount": len(subsections),
        # Filled in by tools.sections, which knows the EPS model.
        "sliceName": None,
    }


def _walk_sections(
    sections: list[Any],
    index: BundleIndex,
    composition: dict[str, Any],
    composition_full_url: str | None,
    prefix: str,
    depth: int,
    out: list[dict[str, Any]],
) -> None:
    for position, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        path = f"{prefix}section[{position}]"
        out.append(summarize_section(section, index, composition, composition_full_url, path, depth))
        _walk_sections(
            as_list(section.get("section")),
            index,
            composition,
            composition_full_url,
            f"{path}.",
            depth + 1,
            out,
        )


def summarize_compositions(resource: dict[str, Any]) -> list[dict[str, Any]]:
    """Every Composition of a file with its sections; nested ones follow their parent."""
    index = BundleIndex(resource)
    out: list[dict[str, Any]] = []
    for full_url, composition in iter_compositions(resource):
        sections: list[dict[str, Any]] = []
        _walk_sections(as_list(composition.get("section")), index, composition, full_url, "", 0, sections)
        title = composition.get("title")
        out.append(
            {
                "resourceId": resource_id(composition),
                "fullUrl": full_url,
                "title": title if isinstance(title, str) else None,
                "profiles": profiles(composition),
                "sections": sections,
            }
        )
    return out
