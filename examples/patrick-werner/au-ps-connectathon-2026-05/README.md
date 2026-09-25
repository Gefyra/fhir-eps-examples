# AU Patient Summary from a May 2026 connectathon

## Context

A patient summary generated at a connectathon in May 2026 by a tool that
identifies itself as "AU Patient Summary generator" (the `Device` that authors
the Composition). It assembles AU Core resources of a test patient from the
server at `smile.sparked-fhir.com/aucore` into a document with four sections.
It shows what happens when a national summary is measured against EPS, and
what the validator makes of references that FHIR does not resolve inside a
Bundle.

## Origin

Migrated from [`hl7-eu/ehds-examples`](https://github.com/hl7-eu/ehds-examples),
path `eps/au-examples-connectathon-2026-05/bundle-baratz-toni.json`,
byte-identical to commit `0cf71aa`. The original file name is kept. Patrick
Werner added it in commit `87007f1`; the only change afterwards, in `8c31b7e`,
added `http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps` to
`Bundle.meta.profile` (and reformatted the file). Everything else is the output
of the generator.

The entries come from `https://smile.sparked-fhir.com/aucore/fhir/DEFAULT/`:
they keep that server's `meta.versionId`, `meta.lastUpdated` and
`meta.source`, and their `fullUrl`s are the server URLs. Only the Composition
and the authoring Device have `urn:uuid:` `fullUrl`s.

## Representation notes

- **An HTML page as a profile.** The Bundle declares
  `https://build.fhir.org/ig/hl7au/au-fhir-ps/StructureDefinition-au-ps-bundle.html`
  — the address of the AU PS Bundle page in the CI build, not its canonical
  URL. The validator cannot resolve it and reports that the profile was not
  checked.
- **Relative references from a `urn:uuid:` Composition.** The Composition's
  `subject` and all section entries are relative (`Patient/baratz-toni`,
  `AllergyIntolerance/nkda2`, …), while the Composition itself has a
  `urn:uuid:` `fullUrl` and the entries have absolute ones. Under FHIR's
  resolution rules these references do not resolve inside the Bundle: the
  validator reports each as "Can't find … in the bundle", notes that an entry
  with the same type and id exists, and then warns that those entries are not
  reachable from the Composition. The section pages of this site match them by
  type and id anyway and mark them "only by type and id".
- **Narrative links into a placeholder.** Every section entry carries a
  `narrativeLink` extension to a fragment of the Composition narrative
  (`urn:uuid:2c916181-…#AllergyIntolerance-https://…/_history/1`), but each
  section narrative is just "TBD", so none of the fragments exists.
- **The Composition is minimal.** No `id`, no `identifier`, no `meta.profile`;
  the four sections — Allergies, Medication, Problems, Immunizations — all have
  entries. The medication entries are `MedicationRequest`s. Two of the five
  sections EPS requires, History of Procedures and Medical Devices, are not
  there at all.
- **AU Core profiles and extensions are not loaded.** Every entry from the
  server declares an AU Core profile (`http://hl7.org.au/fhir/core/StructureDefinition/au-core-*`),
  the PractitionerRole also an AU eRequesting profile; AU extensions such as
  `indigenous-status` and `ihi-status` are used on the Patient. No AU package is
  added under `igs`, so the validator reports each profile as not checked and
  each extension as unknown.
- **SNOMED CT AU codes against the International Edition.** Several codings use
  concepts from the Australian extension of SNOMED CT (identifiers with the
  namespace `1000168` or `1000036`). The codings carry no version, so the
  validator checks them against the International Edition and reports them as
  unknown codes.

## Validation status

In the first run of this collection (validator 6.10.4, tx.fhir.org, September
2026) the document had 43 errors:

- 16 unresolved references and 15 missing narrative fragments, as described
  above,
- 3 required slices not matched: `Bundle.entry:composition` and
  `Bundle.entry:patient` from `bundle-eu-eps`, and `Bundle.entry:patient` from
  IPS `Bundle-uv-ips`, which `bundle-eu-eps` brings along as a dependency,
- 8 findings for 7 SNOMED CT codes from the Australian extension, unknown in
  the International Edition,
- `Device.deviceName.type` missing on the generator Device (required by base
  FHIR R4).

The 15 "isn't reachable by traversing forwards from the Composition" warnings
all report the location `Bundle.entry[20]`, although the Bundle has 19 entries;
their line numbers point at the right entries.

The identifiable-data heuristics flag the test patient's name, date of birth,
IHI and Medicare identifiers, address and contact details.

## Files

| File | Content |
|---|---|
| `bundle-baratz-toni.json` | Document Bundle: Composition, Patient, 2 AllergyIntolerance, 2 MedicationRequest, PractitionerRole, 3 Condition, 8 Immunization, Device. |
