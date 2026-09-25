# Contributing an example

The bar is deliberately low. A submission needs **one FHIR file** and **two
lines of metadata**. Your example does not have to validate, and validation
errors never block a pull request.

## The quick version

```
examples/<your-slug>/
├── contributor.yaml            name: Your Name
└── <example-slug>/
    ├── metadata.yaml           title: …   origin: …
    ├── README.md               optional, but please write one
    └── Bundle-*.json           your patient summary as a document Bundle
```

1. Fork the repository and create a branch.
2. Copy `examples/_template/` to `examples/<your-slug>/`. Slugs are lower case,
   digits and hyphens (`^[a-z0-9][a-z0-9-]{1,62}$`).
3. Put your patient summary into the submission folder. JSON and XML both work.
4. Fill in `metadata.yaml`:

   ```yaml
   title: Patient summary from our EHR
   origin: real-world
   ```

   That is genuinely all that is required. `origin` is one of `real-world`,
   `derived-from-real` or `synthetic`.
5. Open a pull request and tick the boxes in the template.

## What happens then

| | |
|---|---|
| **Structural checks** run first | Parseable files, the layout above, the two metadata fields. **These block the merge.** |
| **FHIR validation** runs second | The HL7 Java validator, pinned to one version, with EPS 1.0.0-ballot loaded. **This never blocks the merge.** |
| **A bot comment** appears | A table with the status of each submission, the findings, and what changed compared with `main`. It is updated in place on every push. |
| **After the merge** | The collection is re-validated and the [site](https://gefyra.github.io/fhir-eps-examples/) is rebuilt, including the section and profile comparison pages. |

## Rules that actually block

The gate is `python -m tools check`. It fails when:

- a file sits somewhere other than the layout above (no subfolders inside a
  submission, no loose files, only `.json` and `.xml` besides `metadata.yaml`
  and `README.md`),
- `metadata.yaml` is missing, unparseable, lacks `title` or `origin`, or
  contains a key that does not exist (typos fail loudly on purpose),
- `contributor.yaml` is missing or has no `name`,
- a FHIR file is not parseable or has no `resourceType`,
- an `igs` entry uses a floating version such as `#current`,
- a submission has no FHIR file at all.

Everything else — including a resource that fails validation completely — is
information, not a blocker. The check also prints warnings that never block: a
missing `README.md`, a submission without a document Bundle, a Bundle whose
`type` is not `document`, and a file that is validated against no profile at
all.

## Running the checks locally (optional)

```bash
make install                                       # creates .venv
make check                                         # the blocking gate, seconds
make validate SUBMISSION=examples/you/your-example # needs Java 21, downloads ~190 MB once
make site && make serve                            # look at the result
```

The first validator run also downloads EPS and the packages it depends on into
`~/.fhir/packages`; expect a few minutes. Later runs are faster, but a large
document still takes a while.

## Choosing what to submit

Good submissions:

- come from a real system, even when they are messy,
- are a complete patient summary as the system sends it: a `Bundle` with
  `type` `document`, the `Composition` first, and every resource the sections
  refer to as an entry,
- include a `README.md` that explains the context and what is unusual: which
  system produced it, which sections it fills and how, what it deliberately
  leaves out.

An IPS document or a national patient summary is just as welcome as a document
built for EPS; it shows how far the existing implementations are from EPS.
Single resources that claim an EPS profile are accepted as well, but they say
nothing about sections and are validated only against the profiles they
declare.

**Every document Bundle is validated against the EPS Bundle profile**
(`http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps`), whether it
declares it in `meta.profile` or not. That is the point of the collection: the
report shows how the document fares against EPS. If your document is not meant
to be a patient summary at all — a discharge letter, say — opt out in
`metadata.yaml`:

```yaml
enforceProfile: false
```

It is then validated only against the profiles it declares.

**Declare the profiles your system claims.** Put them into `meta.profile` of the
resources that are meant to conform to something: the EPS, IPS or national
profile your system implements. The validator checks each resource against the
profiles it declares, and the profile index on the site shows who declares
what. If a profile's package is not loaded by default, add it under `igs` in
`metadata.yaml` (see below); otherwise the validator reports that it could not
check it.

## Practical notes

**References resolve inside a Bundle.** Entries are found by `fullUrl`
(`urn:uuid:…` or an absolute URL) and relative references by the FHIR rules
around `fullUrl`. Each file is validated on its own, so `Patient/123` in one
file will not find the `Patient` in the file next to it — put everything into
the document.

**XML works exactly like JSON.** Same layout, same checks.

**`country`** says which country's rules or systems the example comes from, as
an upper case ISO 3166-1 alpha-2 code. It is optional and shown on the site:

```yaml
country: FI
```

**Extra implementation guides** go into `metadata.yaml`, always pinned — the
national base profiles your resources declare, for example:

```yaml
igs:
  - hl7.fhir.fi.base#2.0.0
```

The default (EPS 1.0.0-ballot, which brings IPS 2.0.0 and EU Base 2.0.0 with
it) is always loaded on top of this. Submissions with the same FHIR version and
the same IG set are validated in one validator run.

**Findings you know about and accept** go into `knownIssues`. A justification is
mandatory, and a rule that stops matching is reported as stale so it does not
rot:

```yaml
knownIssues:
  - messageId: Terminology_TX_System_Relative
    file: Bundle-example.json
    justification: The source system emits the code system name, and we want that visible.
```

A suppressed finding no longer counts towards the status, but it is still shown —
greyed out, with your justification next to it. See
[`docs/metadata-reference.md`](docs/metadata-reference.md) for every field and
[`docs/validation.md`](docs/validation.md) for how validation works.

## De-identification

This is the one thing we are strict about. Examples must contain no
patient-identifiable data. Replace names, identifiers, contact details and
addresses, and shift or truncate dates of birth. Tagging the resources with
`meta.security` `HTEST` is good practice:

```json
"meta": {
  "security": [
    {"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "HTEST"}
  ]
}
```

CI runs simple heuristics and points out anything that looks like a name, an
address, an e-mail address or a phone number. They are hints, not a guarantee —
you remain responsible for what you publish.

## No pull request? No problem

Open an [issue using the submission form](https://github.com/Gefyra/fhir-eps-examples/issues/new?template=submit-example.yml),
send the example by e-mail, post it on Zulip, or bring it to a connectathon. A
maintainer will add it and credit you in `contributor.yaml`.

## Licence

Contributions are published under the Apache License 2.0, like the rest of the
repository.
