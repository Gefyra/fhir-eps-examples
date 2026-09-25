# FHIR EPS Examples Repository

[![Validation status](https://img.shields.io/endpoint?url=https%3A%2F%2Fgefyra.github.io%2Ffhir-eps-examples%2Fbadge.json)](https://gefyra.github.io/fhir-eps-examples/)

**Browse the collection: <https://gefyra.github.io/fhir-eps-examples/>**

> This is an independent community collection. It is **not an official HL7
> Europe publication**, and nothing here is normative. The specification is the
> [HL7 Europe Patient Summary 1.0.0-ballot](https://hl7.eu/fhir/eps/1.0.0-ballot/).

## Overview

This repository collects real-world examples of **patient summaries measured
against the HL7 Europe Patient Summary (EPS)**, package
`hl7.fhir.eu.eps#1.0.0-ballot`.

EPS 1.0.0 is in ballot. A specification under ballot is best judged against
what systems actually produce, and that is what this collection is for:

- **How do real implementations fare against EPS?** Every example is validated
  against the ballot version, and the findings are published.
- **How do they fill each section?** One comparison page per
  `Composition.section` puts the Problems, Allergies, Medication … sections of
  every example side by side: entries or `emptyReason`, which resource types,
  which profiles, narrative only or not.
- **Which EPS profiles have no example yet?** A profile index lists every EPS
  profile and the resources that declare it.

When a finding shows that the problem is in the specification rather than in
the example, please give ballot feedback there: the ballot IG's own "Propose a
change" link points to [HL7 Jira](http://jira.hl7.org).

This is a **community-driven effort** with a **low barrier to contribution**.

---

## Scope

We accept:
- EPS documents: a `Bundle` with `type` `document` and a `Composition` first —
  the preferred form
- IPS documents and national patient summaries, measured against EPS as they are
- Single resources that claim an EPS profile (a `Patient`, an
  `AllergyIntolerance`, …); they are validated only against the profiles they
  declare

Examples do **not need to be perfect or fully valid**.
Capturing real-world data is more important than correctness.

---

## Repository Structure

Examples never move. Every submission stays where its contributor put it, and
its status is computed by CI and published on the site.

```
examples/
  <contributor-slug>/
    contributor.yaml              name: …          (the only required field)
    <submission-slug>/
      metadata.yaml               title: …  origin: …   (the only required fields)
      README.md                   context, origin, modelling notes
      *.json|xml                  a document Bundle, or single resources
```

Supporting parts of the repository:

| Path | What it is |
|---|---|
| `validation.config.yaml` | The single source of truth: validator version, implementation guides, the enforced profile, limits. |
| `schema/` | JSON Schemas for `metadata.yaml` and `contributor.yaml`. |
| `tools/` | The Python tooling behind every CI step; runs locally the same way. |
| `tools/data/eps-model.json` | EPS sections and profiles, generated from the EPS package; what the comparison pages are built from. |
| `docs/` | [How validation works](docs/validation.md), [metadata reference](docs/metadata-reference.md). |
| `examples/_template/` | Copy this to start a submission. |

---

## Validation

Every pull request gets an automated report, and the whole collection is
revalidated on `main` and once a week.

- **Structural checks block a merge**: files must be parseable and sit in the
  layout above, and `metadata.yaml` needs `title` and `origin`.
- **FHIR validation never blocks a merge.** The HL7 Java validator runs against
  a pinned version with EPS 1.0.0-ballot loaded, and its findings are published
  as information about the example.
- **Every document Bundle is also validated against the EPS Bundle profile**
  (`bundle-eu-eps`), whether it declares it or not. A submission can opt out
  with `enforceProfile: false`.

That distinction is deliberate: a collection of real-world data contains invalid
data, so `main` is never red because an example has errors — only when the
infrastructure breaks.

Details: [`docs/validation.md`](docs/validation.md).

---

## Comparison Pages

- [**Sections**](https://gefyra.github.io/fhir-eps-examples/sections/index.html):
  every EPS section in the order of the EPS Composition profile, with its
  cardinality, and one row per example that sends it. Sections EPS does not
  define are listed as well; EPS sections nobody sends yet are marked "no
  example yet".
- [**Profiles**](https://gefyra.github.io/fhir-eps-examples/profiles/index.html):
  every EPS profile with the resources that declare it in `meta.profile`, and
  every other declared profile (IPS, national, …).
- Every submission page carries an EPS section checklist: present, absent, or
  required but missing.

Both indexes are also published as JSON:
[`sections.json`](https://gefyra.github.io/fhir-eps-examples/sections.json),
[`profiles.json`](https://gefyra.github.io/fhir-eps-examples/profiles.json) and
the full [`results.json`](https://gefyra.github.io/fhir-eps-examples/results.json).

---

## Submission Guidelines

We intentionally keep submission simple. Step by step:
[**CONTRIBUTING.md**](CONTRIBUTING.md).

You can contribute by:
- Opening a Pull Request
- Opening an [issue with the submission form](https://github.com/Gefyra/fhir-eps-examples/issues/new?template=submit-example.yml)
- Sharing examples via Zulip or email (maintainers will add them)
- Contributing during HL7 Connectathons

### Minimal Requirements

Each submission needs:
- Example file(s) (JSON or XML), ideally one document Bundle
- `metadata.yaml` with exactly two fields: `title` and `origin`

Strongly encouraged, but not enforced — a short `README.md` describing:
- Context / use case
- Origin (vendor, project, synthetic, etc.)
- The modelling decisions worth discussing

The custodian defaults to your `contributor.yaml`, sections and profiles are
read out of the resources, and the submission date comes from the git history.

### Important Notes

- Examples do **not need to validate**
- Errors are acceptable
- Do not include sensitive or identifiable patient data

---

## Evaluation & Quality Indicators

A **lightweight rating system** helps users understand example quality:

- ⭐ Real-world example — `origin` is `real-world` or `derived-from-real`
- ⭐⭐ Reviewed by SME — set by a maintainer after review
- ⭐⭐⭐ Validated against profile — computed by CI: every file was validated
  against at least one profile (declared in `meta.profile` of its root
  resource, or the enforced EPS Bundle profile) and validation produced no
  unsuppressed errors
- ⭐⭐⭐⭐ Consensus example — the community agreed this is how it should be done

A submission shows the **highest level it has reached**; the levels are not
cumulative requirements. Level 3 is the only one awarded automatically.

This system is **informational only** and does not block submissions.

---

## Guiding Principles

- **Open collection** – no gatekeeping of submissions
- **Reality over perfection**
- **No blame** – examples are not used to criticize implementations
- **Community consensus over time**

---

## Nature of the Content

This repository contains example data only.

Examples:
- may be incomplete
- may not validate
- may not follow best practices

They are intended to reflect real-world implementations, not ideal models.

---

## Data Disclaimer

All examples must be fully de-identified.

No real patient-identifiable information (PII) must be included.
Contributors are responsible for ensuring that shared examples comply with applicable data protection regulations.

---

## Related Work & References

- HL7 Europe Patient Summary, ballot version: https://hl7.eu/fhir/eps/1.0.0-ballot/
- International Patient Summary 2.0.0, which EPS builds on: https://hl7.org/fhir/uv/ips/STU2/
- `hl7-eu/ehds-examples`, where the first examples of this collection were
  contributed: https://github.com/hl7-eu/ehds-examples

The tooling is shared with the sibling project
[fhir-biomarker-examples](https://github.com/patrick-werner/fhir-biomarker-examples).

---

## Future Directions

- Follow EPS beyond the ballot: a new version is a config change plus a
  regenerated `tools/data/eps-model.json`
- Provide rendered views of the documents
- Highlight consensus examples per section

---

## How to Engage

- Share examples during HL7 Connectathons
- Discuss on the FHIR Zulip chat (<https://chat.fhir.org>)
- Send ballot feedback on the specification through HL7 Jira
- Contribute via GitHub

---

## Maintainers

- Patrick Werner
- (add others)

---

## License

This repository is licensed under the Apache License 2.0.

The license applies to all example content (e.g. FHIR JSON/XML files), documentation, and supporting materials.
