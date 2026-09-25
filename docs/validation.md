# How validation works

Everything CI does is a `python -m tools …` call, so every step can be
reproduced locally with the same command. The workflows contain no logic beyond
calling the tooling.

## The two layers

| Layer | Command | Blocks a merge? | What it answers |
|---|---|---|---|
| Structural checks | `python -m tools check` | **yes** | Is this a well-formed submission? |
| FHIR validation | `python -m tools validate` | no | What does the HL7 validator say about it? |

The separation is the whole point of the setup. A collection of real-world
examples contains invalid examples by definition — that is what makes it
interesting. `main` therefore stays green while the collection is full of
errors; it only turns red when the infrastructure itself breaks.

## Structural checks

`tools/check.py` walks `examples/`, enforces the layout, validates
`metadata.yaml` and `contributor.yaml` against the JSON schemas in `schema/`,
and parses every FHIR file. Folders starting with `_` (such as `_template`) are
ignored.

A few findings are warnings rather than errors:

- a missing `README.md`,
- a submission without any document Bundle — EPS examples are expected as
  document Bundles, and standalone resources are validated only against the
  profiles they declare,
- a `Bundle` whose `type` is not `document`; it is not validated against the
  EPS Bundle profile,
- a file whose root resource declares no `meta.profile` and gets no enforced
  profile either, which puts rating level 3 out of reach.

## The validator

The validator is the official
[HL7 Java validator](https://github.com/hapifhir/org.hl7.fhir.core), pinned in
`validation.config.yaml`:

```yaml
validator:
  version: "6.10.4"
```

The jar is downloaded once into `.cache/validator/` and checked for size and zip
magic; set `validator.sha256` to verify the download as well. Bumps arrive as a
pull request from the `validator-update` workflow, together with the validation
results the new version produces — never as a silent `latest`.

The implementation guide is EPS itself, `hl7.fhir.eu.eps#1.0.0-ballot`. The
validator loads its dependencies — IPS 2.0.0, EU Base 2.0.0, the EU extensions,
IHE MPD and what those depend on — by itself. Keep it that way: adding a second
IPS version next to EPS puts two versions of the same canonicals into one run.

## The enforced profile

Every `Bundle` with `type` `document` is also validated against the EPS Bundle
profile, whether it declares it or not:

```yaml
enforcedProfiles:
  documentBundle: http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps
```

The key is optional; without it nothing is enforced. A submission opts out with
`enforceProfile: false` in its `metadata.yaml`.

Without `-profile` the validator checks a resource against base FHIR and against
the profiles it declares in `meta.profile`, and nothing else. With `-profile`
it checks against the given profile instead of base FHIR, and still against
every declared profile. What that means in practice was verified with
validator 6.10.4 and the Epic example of this collection, once as it is and
once with `bundle-eu-eps` removed from its `meta.profile`:

- A Bundle that does not declare `bundle-eu-eps` gets its findings — for the
  Epic document the error that the required `Bundle.entry:composition` slice is
  not matched — and an informational "Validate resource against profile
  …bundle-eu-eps|1.0.0-ballot".
- Declared profiles are still checked: the signpost "Validate resource against
  profile …Bundle-uv-ips|2.0.0 (per meta)" and its findings appear as before.
- A Bundle that declares `bundle-eu-eps` *and* gets it enforced reports each of
  its findings once, not twice.
- `bundle-eu-eps` declares IPS `Bundle-uv-ips` as a dependency
  (`structuredefinition-dependencies`), and the validator follows it, so a
  document is checked against the IPS Bundle profile as well.
- Through the entry slices of `bundle-eu-eps` the entries are checked against
  the EPS entry profiles (`immunization-obl-eu-eps`,
  `medicationrequest-obl-eu-eps`, …) even when they declare none of them. That
  is where most of the additional findings come from.

## Grouping

Starting a JVM and loading implementation guides takes far longer than
validating a file, so files are validated together. `-profile` applies to every
source of one invocation, which is why the grouping works **per file**: the key
is `(fhirVersion, effective IGs, enforced profile or none)`. A document Bundle
gets the enforced profile, every other file gets none, so a submission with a
document and a standalone resource spans two groups; its results are still
aggregated per submission.

```
java -Xmx4g -Dfile.encoding=UTF-8 -jar .cache/validator/validator_cli-6.10.4.jar \
  -version 4.0.1 \
  -ig hl7.fhir.eu.eps#1.0.0-ballot \
  -profile http://hl7.eu/fhir/eps/StructureDefinition/bundle-eu-eps \
  -tx https://tx.fhir.org -txCache .cache/txcache \
  -output results/raw/group-1.json -html-output results/raw/group-1.html \
  -show-message-ids -allow-example-urls true -extension any \
  -display-issues-are-warnings -best-practice warning \
  /abs/path/bundle-a.json /abs/path/bundle-b.json
```

The exact command of every run is written to `results/raw/group-<n>.cmd.txt`, so
a result can always be reproduced by hand. `results.json` records the enforced
profile per group (`groups[].profile`) and per file (`enforcedProfile`, next to
`group`); the site shows it on the file and submission pages.

Effective IGs are the defaults for the FHIR version (`defaultIgs` in the config)
plus whatever the submission declares in `metadata.igs`. Adding an IG to one
submission creates another group; it does not slow the others down.

Two flags deserve a note. `-extension any` and `-display-issues-are-warnings`
are both about tolerance for real-world data: unknown extensions and mismatched
display strings are reported, but they do not make an example "wrong". Both are
configurable in `validation.config.yaml`.

## Attribution

The validator writes one `OperationOutcome` per input file into a single Bundle.
Each outcome carries an `operationoutcome-file` extension with the absolute path
of the source, which is matched back to the input by real path (with a suffix
match as a fallback). Outcomes that cannot be attributed become an
infrastructure warning rather than being dropped silently, and input files
without an outcome are reported as `not-validated` with a reason.

Matching by file base name would quietly attribute findings to the wrong
example as soon as two submissions use the same file name — `bundle.json` is a
popular one.

## Status and counts

Per file, then aggregated per submission, worst wins:

| Status | Meaning |
|---|---|
| `not-validated` | No result — the validator crashed, timed out or skipped the file. |
| `errors` | At least one unsuppressed `error` or `fatal`. |
| `warnings` | At least one unsuppressed `warning`. |
| `valid` | Nothing but informational messages. |

Informational messages never affect the status. Suppressed findings are excluded
from the status but are counted and displayed.

## Known-issue suppression

`metadata.knownIssues` accepts rules with four optional matchers — `messageId`
(case-insensitive), `file` (exact file name), `location` and `details` (both
support `*` wildcards) — and a mandatory `justification`. All matchers given in
a rule must match. `location` is matched against the FHIRPath expression, or
against `Line n, Column m` when the validator reports no expression.

A rule that matches nothing is reported as **stale**, both in the pull request
comment and on the site. This is deliberate: suppressions that nobody prunes are
how a validation setup rots.

## Crashes

A crash is anything other than "the validator ran and produced parseable
output": a missing or broken output file, a timeout, a JVM failure. Then

- every file of that group becomes `not-validated` with the reason and the last
  40 log lines attached,
- the remaining groups still run,
- `validate` exits with code 2,
- the CI job fails — and on `main` the site is not deployed, so the last good
  version stays up.

Validation *errors*, by contrast, exit 0 and never fail a job.

## Terminology

`https://tx.fhir.org` is used by default, with a cache in `.cache/txcache` that
CI keeps across runs. `--offline` passes `-tx n/a`; the run then completes but
codes cannot be checked and the results are not comparable with an online run.

The server times out now and then. When a validator run fails only because the
server did not answer (the log says *Unable to connect to terminology server*),
the group is retried `terminology.retries` times and, if that does not help and
`terminology.fallbackToOffline` is set, validated once more with `-tx n/a`. Such
a run is marked everywhere: `terminologyFallback` in `results.json`, a warning in
the pull request comment and the job summary, and a banner on the site. It
reports fewer findings than usual because no LOINC, SNOMED CT or UCUM code was
checked. The logs of the failed attempts stay next to the final one as
`results/raw/group-<n>.attempt-<k>.log`. Every other kind of crash is reported
as a crash and is not retried.

Because terminology servers change independently of this repository, `main` is
revalidated weekly. A finding that appears without a commit is terminology
drift, and `results.json` records the validator version, jar SHA, IG versions,
terminology server and timestamp of every run so that such a change can be
pinned down.

## The EPS model

The comparison pages need to know what EPS defines: its section slices with
their codes, cardinalities and allowed entries, and its profiles. That is read
once from the EPS package and committed as `tools/data/eps-model.json`, so the
site and the indexes need neither the package cache nor the network:

```bash
python -m tools ig-model hl7.fhir.eu.eps#1.0.0-ballot
```

The command reads the package from `~/.fhir/packages/<id>#<version>/package`,
or downloads it from `https://packages2.fhir.org/web/<id>-<version>.tgz` when it
is not there, and writes

- `profiles`: every StructureDefinition of the package with derivation
  `constraint` and kind `resource`,
- `sections`: the `Composition.section` slices of the EPS Composition profile
  in snapshot order, with their pattern codes, cardinality and the target
  profiles of their entries (entry sub-slices included).

**When EPS changes version**, change `defaultIgs` and regenerate the model in
the same pull request. `make test` fails as long as the model's
`package#version` differs from the EPS entry in `defaultIgs`.

## Sections and profiles

`validate` also summarises every file — independently of the validator — and
builds two indexes that end up in `results.json` and on the site:

- **Sections** (`sections.json`): every `Composition.section`, nested ones
  included, keyed by its code. Per occurrence: the title as sent, the number of
  entries, their resource types and declared profiles, unresolved references,
  `emptyReason`, and whether there is a narrative. EPS sections come first in
  model order, with those nobody sends marked "no example yet"; sections EPS
  does not define follow. Entry types and profiles EPS does not name for a
  section are highlighted.
- **Profiles** (`profiles.json`): every EPS profile with the resources that
  declare it, and every other declared profile. Canonicals are compared
  without `|version`; the version is kept for display.

Section entries are resolved inside the Bundle: by `fullUrl` (`urn:uuid:…` or
absolute), a relative `Type/id` against the base of the Composition's
`fullUrl`, and — more leniently than FHIR — by resource type and id. Entries
found only by type and id are counted separately ("only by type and id") because
the validator does not resolve them and reports them as errors; the comparison
shows what was meant, the findings show what FHIR says.

## Limits worth knowing

**References are not resolved across files.** Each file is a separate source.
`subject: Patient/123` will not be found in a neighbouring file — send the
document as one `Bundle`.

**Profiles of packages that are not loaded are not checked.** A national
profile such as AU Core is reported as "has not been checked because it could
not be found" unless its package is added under `igs`.

**Unbound codes are not checked.** If a profile does not bind an element to a
value set, the validator has nothing to check against. A `valid` status means
"nothing contradicted the profiles", not "the data is correct".

## Output

```
results/
├── results.json                     the full run: submissions, files, issues, groups, indexes
├── <contributor>/<slug>/<file>.oo.json   one OperationOutcome per input file
└── raw/
    ├── group-1.json                 the validator output as it came
    ├── group-1.html                 the validator's own HTML report
    ├── group-1.log                  stdout and stderr
    └── group-1.cmd.txt              the exact command line
```

`python -m tools report` turns this into the pull request comment, the job
summary and the static site, including `sections.json` and `profiles.json`.
`site/results.json` is also the baseline the next pull request compares
against, which is where "+2 new / 1 fixed" comes from.
