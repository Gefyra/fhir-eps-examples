# Patient summary exported from Epic

## Context

A patient summary as Epic produces it for a test patient: an IPS-style
document Bundle with 14 sections, three of them with entries and eleven sent
with an `emptyReason`. It shows what an EHR that implements IPS delivers today
and how far that is from EPS 1.0.0-ballot.

## Origin

Migrated from [`hl7-eu/ehds-examples`](https://github.com/hl7-eu/ehds-examples),
path `eps/epic/bundle.json`, byte-identical to commit `0cf71aa`. The entries'
`fullUrl`s point at `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/`,
and the author and custodian is "EHS Hospital" in Verona, WI.

The history in that repository, all by Patrick Werner:

- `470bd41` added a first export (timestamp `2026-05-17T14:03:43Z`, four
  sections).
- `63d3a3c` added `Bundle.meta.profile` to it.
- `9a14de3` replaced it with a second export of the same patient
  (timestamp `14:53:41Z`, a new Bundle identifier, 14 sections) and added
  `bundle-eu-eps` to `Bundle.meta.profile` by hand, with a misplaced brace.
- `8a97364` fixed that brace ("fixing json syntax").
- `de3c013` put `Bundle-uv-ips` back in front of `bundle-eu-eps`.
- `0cf71aa` reformatted the file without changing its content.

So after the export only `Bundle.meta.profile` was edited and the JSON syntax
repaired. The profiles on the Composition (`Composition-uv-ips`) and the
Patient (`Patient-uv-ips`) came out of Epic. The first export also carried empty
`"meta": {"profile": []}` objects on five entries; the second one does not.

## Representation notes

- **Absolute `fullUrl`s, relative references.** Every entry has the Epic server
  URL as its `fullUrl`, and the Composition refers to them as `Condition/<id>`,
  `MedicationRequest/<id>` and so on. That is the FHIR way to resolve
  references in a Bundle, and every section entry resolves.
- **Ten sections say "no data".** History of Procedures, Results, Medical
  Devices, Vital Signs, Functional Status, Plan of Care, Social History, History
  of Pregnancy, Advance Directives and History of Past Illness have no entries,
  `emptyReason` `unavailable`, `text.status` `empty` and the narrative "No
  information available for …". Allergies has `emptyReason` `notasked` and the
  narrative "Not on file".
- **Only three sections carry data**, one entry each: a `Condition` (ICD-10-CM,
  SNOMED CT and ICD-9-CM codings), a `MedicationRequest` in the Medication
  section, and an `Immunization`. EPS allows a `MedicationRequest` there, but its
  entry slice names `MedicationStatement-eu-eps`.
- **One section is not an EPS section.** "History of Past illness Narrative",
  LOINC `11348-0`, is the IPS past illness section; EPS 1.0.0-ballot has no
  slice for it.
- **Display names end in "Narrative"** ("History of Immunization Narrative",
  "Social history Narrative", …), where LOINC's current displays end in "note",
  so the validator reports wrong display names — as warnings, because of
  `-display-issues-are-warnings`.
- **Profiles.** The Bundle declares `Bundle-uv-ips` and `bundle-eu-eps`, the
  Composition `Composition-uv-ips`, the Patient `Patient-uv-ips`; the other five
  entries declare none.

## Validation status

In the first run of this collection (validator 6.10.4, tx.fhir.org, September
2026) the document had three errors:

- `Slice 'Bundle.entry:composition': a matching slice is required, but not
  found` (from `bundle-eu-eps`): the Composition does not conform to
  `composition-eu-eps`. The validator does not say which constraint failed; one
  that is visible in the data is `Composition.identifier`, which EPS requires
  and the Epic Composition does not have.
- Two `UNKNOWN_CODESYSTEM_VERSION` errors: the `Condition`'s clinical and
  verification status codings carry `"version": "4.0.0"`; the validator knows
  `condition-clinical` only in versions 2.0.0 and 3.0.0 and
  `condition-ver-status` in 0.5.0 to 2.0.1.

Among the 73 warnings: Epic-internal code systems (`urn:oid:1.2.840.114350…`,
`http://epic.com/CodeSystem/dose-rate-type`) the server does not know,
inactive concepts, UCUM annotations such as `{tbl}` in dose
quantities, missing narratives on entries (`dom-6`), and eHDSI value sets EPS
binds to that the server cannot resolve.

The identifiable-data heuristics flag names, date of birth, identifiers,
address and contact details of the test patient and the organisation.

## Files

| File | Content |
|---|---|
| `bundle.json` | Document Bundle: Composition, Patient, Organization, Condition, MedicationRequest, Medication, Immunization. |
