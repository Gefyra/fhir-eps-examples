"""Heuristics that look for identifiable data. Warn-only, never blocking.

This is a second net behind the pull request checklist, not a guarantee. It is
deliberately noisy in the direction of false positives.
"""

from __future__ import annotations

import re
from typing import Any

from . import fhir
from .discover import Submission

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[ /-]?)?(?:\(?\d{2,5}\)?[ /-]?){2,}\d{2,}")
FULL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Dates, timestamps and version numbers look like phone numbers to a regex.
NOT_A_PHONE_RE = re.compile(
    r"^\d{4}(-\d{2}(-\d{2})?)?([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:\d{2})?$|^\d+(\.\d+)+$"
)
MIN_PHONE_DIGITS = 9

# Keys whose values are technical identifiers, never personal data.
SKIP_KEYS = {"system", "url", "reference", "profile", "fullUrl", "valueUri", "valueUrl", "id"}
TEST_SECURITY_CODES = {"HTEST"}


def _is_test_resource(resource: dict[str, Any]) -> bool:
    meta = resource.get("meta")
    if not isinstance(meta, dict):
        return False
    for tag in fhir.as_list(meta.get("security")):
        if not isinstance(tag, dict):
            continue
        if str(tag.get("code", "")).upper() in TEST_SECURITY_CODES:
            return True
    return False


def _finding(file_name: str, path: str, note: str) -> dict[str, str]:
    return {"file": file_name, "location": path, "note": note}


def _scan_patient(resource: dict[str, Any], file_name: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    test_data = _is_test_resource(resource)
    for index, name in enumerate(fhir.as_list(resource.get("name"))):
        if not isinstance(name, dict):
            continue
        if (name.get("family") or name.get("given")) and not test_data:
            findings.append(
                _finding(
                    file_name,
                    f"Patient.name[{index}]",
                    "a name is present and the resource is not tagged HTEST",
                )
            )
    birth_date = resource.get("birthDate")
    if isinstance(birth_date, str) and FULL_DATE_RE.match(birth_date):
        findings.append(
            _finding(
                file_name,
                "Patient.birthDate",
                "a full date of birth; consider shifting it or keeping only the year",
            )
        )
    for index, identifier in enumerate(fhir.as_list(resource.get("identifier"))):
        if not isinstance(identifier, dict):
            continue
        system = str(identifier.get("system", ""))
        if identifier.get("value") and "example" not in system.lower():
            findings.append(
                _finding(
                    file_name,
                    f"Patient.identifier[{index}].value",
                    f"an identifier in system {system or '(none)'}; make sure it is not a real one",
                )
            )
    for index, telecom in enumerate(fhir.as_list(resource.get("telecom"))):
        if isinstance(telecom, dict) and telecom.get("value"):
            findings.append(
                _finding(file_name, f"Patient.telecom[{index}]", "contact details on a patient")
            )
    for index, address in enumerate(fhir.as_list(resource.get("address"))):
        if not isinstance(address, dict):
            continue
        if address.get("line") or address.get("postalCode"):
            findings.append(
                _finding(
                    file_name,
                    f"Patient.address[{index}]",
                    "a street address or postal code on a patient",
                )
            )
    return findings


def _walk_strings(node: Any, path: str, file_name: str, findings: list[dict[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SKIP_KEYS:
                continue
            _walk_strings(value, f"{path}.{key}" if path else key, file_name, findings)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_strings(value, f"{path}[{index}]", file_name, findings)
    elif isinstance(node, str):
        value = node.strip()
        if EMAIL_RE.search(value):
            findings.append(_finding(file_name, path, "looks like an e-mail address"))
        elif (
            len(value) >= 7
            and not NOT_A_PHONE_RE.match(value)
            and sum(character.isdigit() for character in value) >= MIN_PHONE_DIGITS
            and PHONE_RE.fullmatch(value)
        ):
            findings.append(_finding(file_name, path, "looks like a phone number"))


def scan_resource(resource: dict[str, Any], file_name: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for node in fhir.iter_resources(resource):
        if fhir.resource_type(node) == "Patient":
            findings.extend(_scan_patient(node, file_name))
    _walk_strings(resource, "", file_name, findings)
    return findings


def scan_submission(sub: Submission) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in sub.fhir_files:
        try:
            resource = fhir.load_resource(path)
        except fhir.ResourceError:
            continue
        findings.extend(scan_resource(resource, path.name))
    return findings
