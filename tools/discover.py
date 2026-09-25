"""Discovery of contributor folders and submissions under examples/."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .config import Config

IGNORED_PREFIX = "_"
METADATA_FILENAME = "metadata.yaml"
CONTRIBUTOR_FILENAME = "contributor.yaml"
README_FILENAME = "README.md"


@dataclass
class Submission:
    contributor_slug: str
    slug: str
    dir: Path
    fhir_files: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    contributor: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.contributor_slug}/{self.slug}"

    @property
    def metadata_path(self) -> Path:
        return self.dir / METADATA_FILENAME

    @property
    def readme_path(self) -> Path:
        return self.dir / README_FILENAME

    @property
    def contributor_path(self) -> Path:
        return self.dir.parent / CONTRIBUTOR_FILENAME

    def rel(self, path: Path, root: Path) -> str:
        return path.resolve().relative_to(root.resolve()).as_posix()


def is_ignored(name: str) -> bool:
    return name.startswith(IGNORED_PREFIX) or name.startswith(".")


def iter_contributor_dirs(examples_dir: Path) -> Iterator[Path]:
    if not examples_dir.is_dir():
        return
    for entry in sorted(examples_dir.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and not is_ignored(entry.name):
            yield entry


def iter_submission_dirs(contributor_dir: Path) -> Iterator[Path]:
    for entry in sorted(contributor_dir.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and not is_ignored(entry.name):
            yield entry


def fhir_files_in(submission_dir: Path, cfg: Config) -> list[Path]:
    allowed = set(cfg.structure.allowedExtensions)
    return sorted(
        (p for p in submission_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed),
        key=lambda p: p.name,
    )


def discover(cfg: Config) -> list[Submission]:
    """Walk exactly two levels under examples/, ignoring _* and dot folders."""
    submissions: list[Submission] = []
    for contributor_dir in iter_contributor_dirs(cfg.examples_dir):
        for submission_dir in iter_submission_dirs(contributor_dir):
            submissions.append(
                Submission(
                    contributor_slug=contributor_dir.name,
                    slug=submission_dir.name,
                    dir=submission_dir,
                    fhir_files=fhir_files_in(submission_dir, cfg),
                )
            )
    return submissions


def find_submission(cfg: Config, path_or_id: str) -> Submission | None:
    """Resolve 'contributor/slug' or a path (inside a submission) to a Submission."""
    candidate = Path(path_or_id)
    if candidate.exists():
        resolved = candidate.resolve()
        if resolved.is_file():
            resolved = resolved.parent
        target = resolved
    else:
        target = (cfg.examples_dir / path_or_id).resolve()
    for sub in discover(cfg):
        if sub.dir.resolve() == target:
            return sub
    return None


def submitted_on(sub: Submission, root: Path) -> str | None:
    """Date of the first commit that added something inside the submission."""
    try:
        out = subprocess.run(
            [
                "git",
                "log",
                "--diff-filter=A",
                "--format=%cs",
                "--",
                sub.dir.resolve().relative_to(root.resolve()).as_posix(),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - git missing
        return None
    lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    return lines[-1] if lines else None
