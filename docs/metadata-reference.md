# Metadata reference

Two files describe a submission. The authoritative definitions are
[`schema/contributor.schema.json`](../schema/contributor.schema.json) and
[`schema/metadata.schema.json`](../schema/metadata.schema.json); both use
`additionalProperties: false`, so a misspelled key fails the structural check
instead of being ignored.

## `examples/<contributor>/contributor.yaml`

| Field | Required | Rule |
|---|---|---|
| `name` | **yes** | 2–100 characters. A person or an organisation. |
| `organization` | no | 2–200 characters. |
| `github` | no | GitHub login without `@`, `^[A-Za-z0-9-]{1,39}$`. |
| `contact` | no | E-mail address, Zulip handle, whatever you prefer. |
| `url` | no | `http://` or `https://`. |

Minimal:

```yaml
name: Patrick Werner
```

One file per contributor folder. Who contributed what is answered by the folder
path plus the git history, not by a field repeated in every submission.

## `examples/<contributor>/<submission>/metadata.yaml`

Required: `title` and `origin`. Nothing else.

```yaml
title: Patient summary exported from our EHR
origin: real-world
```

| Field | Required | Default / rule |
|---|---|---|
| `title` | **yes** | 3–120 characters. |
| `origin` | **yes** | `real-world`, `derived-from-real` or `synthetic`. |
| `description` | no | One or two sentences. Longer prose belongs in `README.md`. |
| `fhirVersion` | no | `4.0.1`, `4.3.0` or `5.0.0`. Default: `defaultFhirVersion` from the config (`4.0.1`). |
| `igs` | no | Extra implementation guides as `package#version`. Floating versions are rejected. |
| `country` | no | Upper case ISO 3166-1 alpha-2 code, `^[A-Z]{2}$`. Not derived. |
| `enforceProfile` | no | `true` or `false`. Default: `true`. |
| `custodian` | no | `{name, github, contact}`. Defaults to `contributor.yaml`. |
| `source` | no | `{vendor, system, project, url}` — where the example was produced. |
| `knownIssues` | no | Accepted findings, see below. |
| `review` | no | Maintainers only, see below. |

Deliberately absent: a schema version (the schema is versioned with the
repository), a submission date (derived from the first commit that touched the
folder), the sections and profiles (read out of the resources), and the
de-identification and licence declarations (they live in the pull request
template, where a human ticks them).

### `origin`

Be honest here; it is the basis of rating level 1.

- `real-world` — came out of a running system, possibly de-identified.
- `derived-from-real` — built from a real example, substantially rewritten.
- `synthetic` — invented.

### `igs`

```yaml
igs:
  - hl7.fhir.fi.base#2.0.0
```

Always pinned: `#current`, `#dev` and `#latest` are rejected, because a result
that changes without a commit cannot be reasoned about. The defaults for the
FHIR version (EPS 1.0.0-ballot for R4) are always added on top. Add the package
of every profile your resources declare that the defaults do not bring along —
national base profiles, typically — or the validator reports that it could not
check them.

### `country`

The country whose rules or systems the example comes from, shown on the site:

```yaml
country: FI
```

It is never derived; an address in the data says where the patient lives, not
which national profiles the system follows.

### `enforceProfile`

Every document Bundle is validated against the profile configured in
`validation.config.yaml` under `enforcedProfiles.documentBundle` — the EPS
Bundle profile — whether it declares it or not. Set this to `false` when your
document is not meant to be a patient summary, and it is validated only against
the profiles it declares:

```yaml
enforceProfile: false
```

### `knownIssues`

```yaml
knownIssues:
  - messageId: Validation_VAL_Profile_Minimum_SLICE
    location: "Bundle"
    justification: The source system cannot produce an EPS Composition yet; accepted until it can.
```

| Matcher | Matching |
|---|---|
| `messageId` | Exact, case-insensitive. The id shown in the report. |
| `file` | Exact file name inside this submission. |
| `location` | FHIRPath expression, or `Line n, Column m`. `*` wildcards allowed. |
| `details` | The message text. `*` wildcards allowed. |
| `justification` | **Required**, at least 10 characters. |

At least one matcher must be present, and all matchers given must match. A
suppressed finding no longer counts towards the status, but it is still counted
and shown with its justification. A rule that matches nothing is reported as
stale.

### `review`

Set by maintainers, not by contributors.

| Field | Effect |
|---|---|
| `smeReviewed` | Rating level 2. |
| `consensus` | Rating level 4. |
| `reviewer`, `date`, `notes` | Documentation of the review. |
| `normalizedVersion` | Path of an improved variant of this submission. |

## Rating

The level shown is the **highest one reached**, not a sum:

| Level | Granted by |
|---|---|
| ★ | `origin` is `real-world` or `derived-from-real`. |
| ★★ | `review.smeReviewed`. |
| ★★★ | CI: every file was validated against at least one profile — declared in `meta.profile` of its root resource, or the enforced one — the status is not `not-validated`, and there are no unsuppressed errors. The reason names the profiles. |
| ★★★★ | `review.consensus`. |

Suppressed errors do not prevent level 3, but they are visible on the submission
page, with the justification — so the level is never a way of hiding something.
