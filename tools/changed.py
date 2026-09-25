"""Map a git diff range to the submissions that have to be revalidated."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .config import Config
from .discover import CONTRIBUTOR_FILENAME, discover

# A change to any of these invalidates every earlier result, so everything runs.
FULL_RUN_PATHS = (
    "validation.config.yaml",
    "pyproject.toml",
    "schema/",
    "tools/",
    ".github/actions/",
)
FULL_RUN_WORKFLOW_PREFIX = ".github/workflows/validate-"


def changed_files(root: Path, base: str, head: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if out.returncode != 0:
        # Shallow clones or a missing merge base: fall back to a plain two-dot diff.
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base, head],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def needs_full_run(paths: list[str]) -> bool:
    for path in paths:
        if path in FULL_RUN_PATHS:
            return True
        if any(path.startswith(prefix) for prefix in FULL_RUN_PATHS if prefix.endswith("/")):
            return True
        if path.startswith(FULL_RUN_WORKFLOW_PREFIX):
            return True
    return False


def changed_submissions(cfg: Config, base: str, head: str) -> dict[str, Any]:
    paths = changed_files(cfg.root, base, head)
    submissions = discover(cfg)
    known = {sub.id: sub for sub in submissions}
    full = needs_full_run(paths)

    touched: set[str] = set()
    for path in paths:
        parts = Path(path).parts
        if len(parts) < 3 or parts[0] != "examples":
            continue
        contributor = parts[1]
        if contributor.startswith("_") or contributor.startswith("."):
            continue
        if parts[2] == CONTRIBUTOR_FILENAME:
            touched.update(sub.id for sub in submissions if sub.contributor_slug == contributor)
            continue
        candidate = f"{contributor}/{parts[2]}"
        if candidate in known:  # deleted submissions simply disappear
            touched.add(candidate)

    selected = sorted(known) if full else sorted(touched)
    return {
        "base": base,
        "head": head,
        "full": full,
        "submissions": selected,
        "files": paths,
    }
