# Short title of this example

## Context

Which system produced this patient summary, in which country and for which
purpose (cross-border care, a national summary, a connectathon, …), and why the
example is interesting for the collection.

## Origin

Which system produced the data, and how it was de-identified or synthesised.
Say what, if anything, was changed after the export.

## Representation notes

Anything a reader should know about the modelling decisions: which sections the
document fills and which it leaves out or sends with an `emptyReason`, how the
entries are referenced, which code systems are used, known deviations from EPS,
and so on.

Say which profiles the resources claim in `meta.profile` and why, or that they
claim none. The template declares the EPS Bundle, Composition and Patient
profiles and EU Base `condition-eu-core`; replace them with what your system
implements. The Bundle is validated against the EPS Bundle profile either way.

## Files

| File | Content |
|---|---|
| `Bundle-example.json` | The patient summary as a document Bundle. |
