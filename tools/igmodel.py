"""The EPS model: profiles and Composition sections of the pinned EPS package.

The site and the section and profile indexes read tools/data/eps-model.json and
nothing else, so building them needs neither the package cache nor the network.
The file is committed and regenerated with

    python -m tools ig-model hl7.fhir.eu.eps#<version>

whenever the EPS version in validation.config.yaml changes. A unit test fails
when the two disagree.
"""

from __future__ import annotations

import io
import json
import tarfile
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from .config import ConfigError, check_ig_pinned

MODEL_PATH = Path(__file__).parent / "data" / "eps-model.json"
PACKAGE_CACHE = Path.home() / ".fhir" / "packages"
PACKAGE_URL = "https://packages2.fhir.org/web/{id}-{version}.tgz"
DOWNLOAD_TIMEOUT_SECONDS = 120
MODEL_SCHEMA_VERSION = 1


class ModelError(Exception):
    """Raised when a package cannot be read or does not look like EPS."""


# ------------------------------------------------------------------- package


def split_ig(ig: str) -> tuple[str, str]:
    try:
        check_ig_pinned(ig, "ig-model")
    except ConfigError as exc:
        raise ModelError(str(exc)) from exc
    package_id, _, version = ig.partition("#")
    return package_id, version


def _read_local(folder: Path) -> list[dict[str, Any]]:
    resources = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("resourceType") == "StructureDefinition":
            resources.append(data)
    return resources


def _read_tarball(payload: bytes) -> list[dict[str, Any]]:
    """StructureDefinitions directly under package/; nothing is written to disk."""
    resources = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            parts = member.name.split("/")
            if not member.isfile() or len(parts) != 2 or parts[0] != "package":
                continue
            if not parts[1].endswith(".json"):
                continue
            handle = archive.extractfile(member)
            if handle is None:  # pragma: no cover - regular files always have one
                continue
            try:
                data = json.loads(handle.read().decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(data, dict) and data.get("resourceType") == "StructureDefinition":
                resources.append(data)
    return resources


def load_structure_definitions(ig: str, cache: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    """StructureDefinitions of one package, from the local cache or the package server."""
    package_id, version = split_ig(ig)
    folder = (cache or PACKAGE_CACHE) / f"{package_id}#{version}" / "package"
    if folder.is_dir():
        return _read_local(folder), str(folder)
    url = PACKAGE_URL.format(id=package_id, version=version)
    print(f"{folder} not found; downloading {url}", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise ModelError(f"cannot download {url}: {exc}") from exc
    try:
        return _read_tarball(payload), url
    except (tarfile.TarError, OSError) as exc:
        raise ModelError(f"{url} is not a readable package: {exc}") from exc


# --------------------------------------------------------------------- model


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def _target_profiles(element: dict[str, Any]) -> list[str]:
    out = []
    for type_ in element.get("type") or []:
        if isinstance(type_, dict):
            out.extend(str(p) for p in type_.get("targetProfile") or [])
    return out


def _pattern_codings(element: dict[str, Any]) -> list[dict[str, str]]:
    concept = element.get("patternCodeableConcept") or element.get("fixedCodeableConcept") or {}
    out = []
    for coding in concept.get("coding") or []:
        if isinstance(coding, dict) and coding.get("code"):
            out.append(
                {
                    "system": str(coding.get("system") or ""),
                    "code": str(coding["code"]),
                    "display": str(coding.get("display") or ""),
                }
            )
    return out


def composition_sections(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """The Composition.section slices of a profile, in snapshot order."""
    elements = (profile.get("snapshot") or {}).get("element") or []
    by_id = {str(e.get("id")): e for e in elements if isinstance(e, dict)}
    sections = []
    for element in elements:
        element_id = str(element.get("id", ""))
        head, _, slice_name = element_id.partition(":")
        if head != "Composition.section" or not slice_name or "." in slice_name:
            continue
        prefix = f"Composition.section:{slice_name}"
        code = by_id.get(f"{prefix}.code", {})
        entry = by_id.get(f"{prefix}.entry", {})
        entry_slices = []
        for candidate in elements:
            candidate_id = str(candidate.get("id", ""))
            if candidate_id.startswith(f"{prefix}.entry:") and "." not in candidate_id[len(prefix) + 7 :]:
                entry_slices.append(
                    {
                        "sliceName": candidate.get("sliceName") or candidate_id.rsplit(":", 1)[-1],
                        "min": int(candidate.get("min", 0)),
                        "max": str(candidate.get("max", "*")),
                        "profiles": _target_profiles(candidate),
                    }
                )
        entry_profiles = _target_profiles(entry)
        for entry_slice in entry_slices:
            entry_profiles.extend(entry_slice["profiles"])
        sections.append(
            {
                "sliceName": slice_name,
                "title": str(element.get("label") or element.get("short") or slice_name),
                "min": int(element.get("min", 0)),
                "max": str(element.get("max", "*")),
                "codes": _pattern_codings(code),
                "entryProfiles": _dedupe(entry_profiles),
                "entrySlices": entry_slices,
            }
        )
    return sections


def build_model(
    package_id: str,
    version: str,
    structure_definitions: list[dict[str, Any]],
    composition_url: str | None = None,
) -> dict[str, Any]:
    profiles = [
        sd
        for sd in structure_definitions
        if sd.get("derivation") == "constraint" and sd.get("kind") == "resource" and sd.get("url")
    ]
    compositions = [sd for sd in profiles if sd.get("type") == "Composition"]
    if composition_url:
        compositions = [sd for sd in compositions if sd.get("url") == composition_url]
    if len(compositions) != 1:
        found = ", ".join(str(sd.get("url")) for sd in compositions) or "none"
        raise ModelError(
            f"{package_id}#{version}: expected exactly one Composition profile, found {found}; "
            "pick one with --composition"
        )
    composition = compositions[0]
    return {
        "schemaVersion": MODEL_SCHEMA_VERSION,
        "package": package_id,
        "version": version,
        "composition": str(composition["url"]),
        "profiles": [
            {
                "url": str(sd["url"]),
                "name": str(sd.get("name") or ""),
                "title": str(sd.get("title") or sd.get("name") or ""),
                "type": str(sd.get("type") or ""),
            }
            for sd in sorted(profiles, key=lambda s: (str(s.get("type")), str(s.get("url"))))
        ],
        "sections": composition_sections(composition),
    }


def generate(ig: str, target: Path = MODEL_PATH, composition_url: str | None = None) -> dict[str, Any]:
    package_id, version = split_ig(ig)
    structure_definitions, origin = load_structure_definitions(ig)
    model = build_model(package_id, version, structure_definitions, composition_url)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{len(model['profiles'])} profile(s) and {len(model['sections'])} section(s) "
        f"from {origin} written to {target}"
    )
    return model


EMPTY_MODEL: dict[str, Any] = {
    "schemaVersion": MODEL_SCHEMA_VERSION,
    "package": None,
    "version": None,
    "composition": None,
    "profiles": [],
    "sections": [],
}


@lru_cache(maxsize=4)
def load_model(path: Path = MODEL_PATH) -> dict[str, Any]:
    """The committed model. Missing file: an empty model, so a site still builds."""
    if not path.is_file():
        return dict(EMPTY_MODEL)
    return json.loads(path.read_text(encoding="utf-8"))
