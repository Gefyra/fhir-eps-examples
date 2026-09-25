# Patient-authored summary of a person with type 1 diabetes

## Context

A patient summary written from the patient's side: "Mikko Virtanen" lives with
type 1 diabetes and wears an automated insulin delivery system, and the summary
says so in its own words. It is the richest document in the collection — 113
entries, 15 sections — and claims IPS, EPS, EU Base, IPA and the Finnish base
profile at the same time, which makes it a good test of how the layers of
profiles fit together.

## Origin

Migrated from [`hl7-eu/ehds-examples`](https://github.com/hl7-eu/ehds-examples),
path `eps/Sensotrend/Sensotrend-MIkko_Virtanen.json`, where Mikael Rinnetmäki
added it in commit `8c5a285` ("Add an EPS sample"). The file here is
byte-identical to that commit and to the state at `0cf71aa`; nobody changed it
in that repository after it was added. The original file name is kept.

The document describes its own origin. Its two `Provenance` resources say "I
have crafted this summary myself by hand, utilizing data from various sources"
and "I used Microsoft Copilot to add LOINC codes to lab results, based on the
Finnish domestic Kuntaliitto codes that were present in my records. I verified
the accuracy of the added codes and fixed any errors I was able to spot." The
Composition's author and attester is the patient, and the Bundle is labelled
`PATRPT`, `PATAST`, `SYSDEV`, `HTEST` and `TRAIN` in `meta.security`. It is
therefore recorded as `derived-from-real` rather than as the output of a system.

## Representation notes

- **Every entry is a `urn:uuid:` reference.** All section entries resolve by
  `fullUrl`; nothing in the document relies on relative references.
- **All five sections EPS requires are present**, each with entries: Problems,
  Allergies and Intolerances, Medication Summary, History of Procedures and
  Medical Devices.
- **`emptyReason` next to real text.** Alerts and Functional Status carry
  `emptyReason` `nilknown`. Patient Story and Plan of Care carry `notstarted`,
  yet their narratives hold several sentences of the patient's own text — in
  FHIR a section is "empty" when it has no entries, whatever its narrative
  says.
- **One section is not an EPS section.** "History of Past Problems" uses LOINC
  `11348-0`, the IPS past illness section. EPS 1.0.0-ballot has no slice for
  that code; its history section is Patient History, `11329-0`. The site lists
  it under "Other sections".
- **Every section narrative has `text.status` `additional`**, and the
  Composition narrative is the patient's own summary.
- **Profiles are stacked.** A `Condition` declares IPA, IPS, EU Base and the EPS
  obligation profile; the lab `Observation`s declare IPA, IPS
  `Observation-results-laboratory-pathology-uv-ips` and EU Base
  `medicalTestResult-eu-core`. Some canonicals carry a version and others do
  not: `ipa-*|1.1.0`, `Observation-tobaccouse-uv-ips|2.0.0`,
  `patient-eu-core|2.0.0-recon`, `fi-base-patient|2.0.0`.
- **`patient-eu-core|2.0.0-recon` is checked against another version.** The
  validator reports "Validate resource against profile
  …patient-eu-core|2.0.0 (per meta)": it uses the EU Base 2.0.0 profile that EPS
  brings along, without a remark that the declared version `2.0.0-recon` is a
  different one.
- **The Finnish base profile is not loaded.** `fi-base-patient|2.0.0` belongs to
  `hl7.fhir.fi.base`, which is not among the default IGs and not added under
  `igs` here, so the validator reports that the profile "has not been checked
  because it could not be found".
- **Local codes sit next to international ones.** Many codings use Finnish
  national code systems (`urn:oid:1.2.246.537.6.*`) or laboratory systems such
  as `https://fimlab.fi/`, alongside LOINC or SNOMED CT.

## Validation status

In the first run of this collection (validator 6.10.4, tx.fhir.org, September
2026) the document had no errors — against its declared profiles and against
the enforced `bundle-eu-eps` — and reached rating level 3. Its 242 warnings are
almost all terminology:

- about 160 codings in code systems the terminology server does not know, the
  Finnish OIDs above among them ("this coding was not checked"),
- 71 references to eHDSI value sets (`http://terminology.ehdsi.eu/ValueSet/…`)
  that EPS profiles bind to and that the server cannot resolve,
- one inactive SNOMED CT concept, `281657000`, used as the `reasonCode` of seven
  immunizations.

The identifiable-data heuristics flag the Patient's name, date of birth,
personal identity code, address and contact details; the Patient resource
itself carries only `PATRPT` in `meta.security`, the test labels sit on the
Bundle.

## Files

| File | Content |
|---|---|
| `Sensotrend-MIkko_Virtanen.json` | Document Bundle: Composition, Patient and 111 further entries. |
