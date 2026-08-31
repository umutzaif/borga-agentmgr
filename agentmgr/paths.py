"""Locating and describing the ``.agentmgr/`` directory inside a project."""

from __future__ import annotations

from pathlib import Path

DIRNAME = ".agentmgr"


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
