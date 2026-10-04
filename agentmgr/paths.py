"""Locating and describing the ``.agentmgr/`` directory inside a project."""

from __future__ import annotations

import os
from pathlib import Path

DIRNAME = ".agentmgr"
# a project this many levels above the cwd (or in the home directory) is probably not the one meant
MAX_UPWARD_LEVELS = 3
QUIET_ENV = "AGENTMGR_NO_ROOT_WARNING"


class ProjectNotInitialised(Exception):
    """Raised when no ``.agentmgr/`` exists in the cwd or any parent."""


def find_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if (candidate / DIRNAME).is_dir():
            return candidate
    raise ProjectNotInitialised(
        f"no {DIRNAME}/ found in {start} or any parent - run 'agentmgr init' first"
    )


def _home() -> Path:
    return Path.home()


def distant_root_warning(start: Path, root: Path) -> str | None:
    """Explain why an adopted project root looks suspicious, or ``None`` if it looks fine.

    ``find_root`` walks up from the cwd, so a stray ``.agentmgr`` in the home
    directory or high above would otherwise be picked up silently.
    """
    if os.environ.get(QUIET_ENV):
        return None
    start, root = Path(start).resolve(), Path(root).resolve()
    if start == root:
        return None
    try:
        levels = len(start.relative_to(root).parts)
    except ValueError:
        return None
    is_home = root == _home().resolve()
    if not is_home and levels <= MAX_UPWARD_LEVELS:
        return None
    where = "your home directory" if is_home else f"{levels} levels above here"
    return (
        f"warning: using the {DIRNAME} project at {root} ({where}, cwd is {start}). "
        f"If that is not the project you meant, cd into it or run 'agentmgr init' here; "
        f"set {QUIET_ENV}=1 to silence this."
    )


class Layout:
    """Absolute paths for every file agentmgr reads or writes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.base = self.root / DIRNAME
        self.events = self.base / "events"
        self.archive = self.base / "archive"
        self.handoff = self.base / "HANDOFF"
        self.ledger = self.base / "ledger.jsonl"
        self.charter = self.base / "CHARTER.md"
        self.style = self.base / "STYLE.md"
        self.agents = self.base / "AGENTS.md"
        self.threads = self.base / "THREADS.md"
        self.bootstrap = self.base / "BOOTSTRAP.md"
        self.config = self.base / "config.json"

    @classmethod
    def discover(cls, start: Path | None = None) -> "Layout":
        return cls(find_root(start))
