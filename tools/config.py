"""Loading and validation of validation.config.yaml."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

CONFIG_FILENAME = "validation.config.yaml"
EXAMPLES_DIRNAME = "examples"
FLOATING_VERSIONS = {"current", "dev", "latest"}


class ConfigError(Exception):
    """Raised when validation.config.yaml is missing, unreadable or wrong."""


def repo_root(start: Path | None = None) -> Path:
    """Return the repository root, i.e. the closest folder holding the config."""
    env = os.environ.get("FHIR_EPS_REPO_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate
    # Fall back to the package parent so that an installed copy still works.
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ValidatorConfig:
    version: str
    downloadUrl: str
    sha256: str | None
    javaArgs: tuple[str, ...]
    timeoutMinutes: int


@dataclass(frozen=True)
class TerminologyConfig:
    server: str
    cacheDir: str
    # Extra attempts when the validator cannot reach the server.
    retries: int = 2
    # After the retries, run once more with -tx n/a and mark the run.
    fallbackToOffline: bool = True


@dataclass(frozen=True)
class StructureConfig:
    allowedExtensions: tuple[str, ...]
    maxFileSizeBytes: int
    maxFilesPerSubmission: int
    slugPattern: str


@dataclass(frozen=True)
class ReportConfig:
    prCommentBudgetChars: int
    maxIssuesPerSubmissionInComment: int
    baselineUrl: str | None
    siteBaseUrl: str | None


@dataclass(frozen=True)
class EnforcedProfilesConfig:
    # Canonical URL every Bundle with type "document" is validated against, in
    # addition to the profiles it declares. None enforces nothing.
    documentBundle: str | None = None


@dataclass(frozen=True)
class Config:
    root: Path
    path: Path
    raw_text: str
    schemaVersion: int
    validator: ValidatorConfig
    terminology: TerminologyConfig
    defaultFhirVersion: str
    defaultIgs: dict[str, tuple[str, ...]]
    validatorFlags: tuple[str, ...]
    structure: StructureConfig
    report: ReportConfig
    piiEnabled: bool
    enforcedProfiles: EnforcedProfilesConfig = field(default_factory=EnforcedProfilesConfig)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def examples_dir(self) -> Path:
        return self.root / EXAMPLES_DIRNAME

    @property
    def schema_dir(self) -> Path:
        return self.root / "schema"

    def jar_path(self) -> Path:
        return self.root / ".cache" / "validator" / f"validator_cli-{self.validator.version}.jar"

    def tx_cache_dir(self) -> Path:
        return self.root / self.terminology.cacheDir

    def default_igs_for(self, fhir_version: str) -> tuple[str, ...]:
        return self.defaultIgs.get(fhir_version, ())


def _expect(mapping: Any, where: str) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(mapping).__name__}")
    return mapping


def _unknown_keys(mapping: dict[str, Any], allowed: Iterable[str], where: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def load_config(root: Path | None = None) -> Config:
    """Read and validate validation.config.yaml. Unknown keys are errors."""
    base = (root or repo_root()).resolve()
    path = base / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(f"{CONFIG_FILENAME} not found in {base}")
    raw_text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:  # pragma: no cover - message passthrough
        raise ConfigError(f"{path}: not valid YAML: {exc}") from exc
    data = _expect(data, str(path))
    _unknown_keys(
        data,
        [
            "schemaVersion",
            "validator",
            "terminology",
            "defaultFhirVersion",
            "defaultIgs",
            "validatorFlags",
            "structure",
            "report",
            "pii",
            "enforcedProfiles",
        ],
        CONFIG_FILENAME,
    )

    schema_version = data.get("schemaVersion")
    if schema_version != 1:
        raise ConfigError(f"{CONFIG_FILENAME}: schemaVersion must be 1, got {schema_version!r}")

    v = _expect(data.get("validator"), "validator")
    _unknown_keys(v, ["version", "downloadUrl", "sha256", "javaArgs", "timeoutMinutes"], "validator")
    validator = ValidatorConfig(
        version=str(v["version"]),
        downloadUrl=str(v["downloadUrl"]),
        sha256=(str(v["sha256"]) if v.get("sha256") else None),
        javaArgs=tuple(str(a) for a in v.get("javaArgs", [])),
        timeoutMinutes=int(v.get("timeoutMinutes", 25)),
    )

    t = _expect(data.get("terminology"), "terminology")
    _unknown_keys(t, ["server", "cacheDir", "retries", "fallbackToOffline"], "terminology")
    terminology = TerminologyConfig(
        server=str(t.get("server", "https://tx.fhir.org")),
        cacheDir=str(t.get("cacheDir", ".cache/txcache")),
        retries=int(t.get("retries", 2)),
        fallbackToOffline=bool(t.get("fallbackToOffline", True)),
    )

    default_fhir_version = str(data.get("defaultFhirVersion", "4.0.1"))

    default_igs_raw = _expect(data.get("defaultIgs", {}), "defaultIgs")
    default_igs: dict[str, tuple[str, ...]] = {}
    for version, igs in default_igs_raw.items():
        if igs is None:
            igs = []
        if not isinstance(igs, list):
            raise ConfigError(f"defaultIgs.{version}: expected a list")
        for ig in igs:
            check_ig_pinned(str(ig), f"defaultIgs.{version}")
        default_igs[str(version)] = tuple(str(ig) for ig in igs)
    if default_fhir_version not in default_igs:
        raise ConfigError(
            f"defaultIgs: no entry for defaultFhirVersion {default_fhir_version!r}"
        )

    flags = data.get("validatorFlags", [])
    if not isinstance(flags, list):
        raise ConfigError("validatorFlags: expected a list")

    s = _expect(data.get("structure", {}), "structure")
    _unknown_keys(
        s,
        ["allowedExtensions", "maxFileSizeBytes", "maxFilesPerSubmission", "slugPattern"],
        "structure",
    )
    structure = StructureConfig(
        allowedExtensions=tuple(str(e).lower() for e in s.get("allowedExtensions", [".json", ".xml"])),
        maxFileSizeBytes=int(s.get("maxFileSizeBytes", 5 * 1024 * 1024)),
        maxFilesPerSubmission=int(s.get("maxFilesPerSubmission", 50)),
        slugPattern=str(s.get("slugPattern", "^[a-z0-9][a-z0-9-]{1,62}$")),
    )

    r = _expect(data.get("report", {}), "report")
    _unknown_keys(
        r,
        [
            "prCommentBudgetChars",
            "maxIssuesPerSubmissionInComment",
            "baselineUrl",
            "siteBaseUrl",
        ],
        "report",
    )
    report = ReportConfig(
        prCommentBudgetChars=int(r.get("prCommentBudgetChars", 60000)),
        maxIssuesPerSubmissionInComment=int(r.get("maxIssuesPerSubmissionInComment", 10)),
        baselineUrl=(str(r["baselineUrl"]) if r.get("baselineUrl") else None),
        siteBaseUrl=(str(r["siteBaseUrl"]) if r.get("siteBaseUrl") else None),
    )

    p = _expect(data.get("pii", {}), "pii")
    _unknown_keys(p, ["enabled"], "pii")

    e = _expect(data.get("enforcedProfiles") or {}, "enforcedProfiles")
    _unknown_keys(e, ["documentBundle"], "enforcedProfiles")
    document_bundle = e.get("documentBundle")
    if document_bundle is not None and (
        not isinstance(document_bundle, str) or not document_bundle.startswith(("http://", "https://"))
    ):
        raise ConfigError(
            f"enforcedProfiles.documentBundle: expected a canonical URL, got {document_bundle!r}"
        )
    enforced = EnforcedProfilesConfig(documentBundle=document_bundle or None)

    return Config(
        root=base,
        path=path,
        raw_text=raw_text,
        schemaVersion=1,
        validator=validator,
        terminology=terminology,
        defaultFhirVersion=default_fhir_version,
        defaultIgs=default_igs,
        validatorFlags=tuple(str(f) for f in flags),
        structure=structure,
        report=report,
        piiEnabled=bool(p.get("enabled", True)),
        enforcedProfiles=enforced,
    )


def check_ig_pinned(ig: str, where: str) -> None:
    """Reject floating IG versions; they make runs irreproducible."""
    if "#" not in ig:
        raise ConfigError(f"{where}: IG {ig!r} must be pinned as 'package#version'")
    _, _, version = ig.partition("#")
    if version.lower() in FLOATING_VERSIONS or not version:
        raise ConfigError(
            f"{where}: IG {ig!r} uses a floating version; pin an explicit release instead"
        )


def config_hash(cfg: Config, igs: Iterable[str] = ()) -> str:
    """Stable cache key for ~/.fhir/packages: config file plus all IGs in use."""
    digest = hashlib.sha256()
    digest.update(cfg.raw_text.encode("utf-8"))
    for ig in sorted(set(igs)):
        digest.update(b"\n")
        digest.update(ig.encode("utf-8"))
    return digest.hexdigest()[:16]


def dotted_get(cfg_data: dict[str, Any], key: str) -> Any:
    node: Any = cfg_data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"unknown config key: {key}")
        node = node[part]
    return node
