"""Tooling for the fhir-eps-examples collection.

The package is deliberately small and dependency-light so that a single
maintainer can run every CI step locally:

    python -m tools check
    python -m tools validate --all --out results/
    python -m tools report --results results/ --site site/
    python -m tools ig-model hl7.fhir.eu.eps#1.0.0-ballot
"""

__version__ = "1.0.0"
