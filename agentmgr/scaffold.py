"""``agentmgr init`` - lay down ``.agentmgr/`` with its templates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agentmgr.paths import DIRNAME, Layout
from agentmgr.state import DEFAULT_STALE_MINUTES

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATES = ("CHARTER.md", "STYLE.md", "AGENTS.md", "BOOTSTRAP.md")

_THREADS_STUB = """# Thread Durumu

> Bu dosya `agentmgr status` tarafindan otomatik uretilir. Elle duzenleme.

_Henuz thread yok._
"""


def _template(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding="utf-8")


def init_project(
    root: Path,
    project_name: str | None = None,
    force: bool = False,
) -> Layout:
    layout = Layout(root)
    if layout.base.exists() and not force:
        raise FileExistsError(
            f"{DIRNAME}/ already exists at {layout.root} - pass --force to refresh templates"
        )

    for directory in (layout.base, layout.events, layout.archive, layout.handoff):
        directory.mkdir(parents=True, exist_ok=True)

    for name in _TEMPLATES:
        dest = layout.base / name
        if force or not dest.exists():
            dest.write_text(_template(name), encoding="utf-8")

    if force or not layout.threads.exists():
        layout.threads.write_text(_THREADS_STUB, encoding="utf-8")

    if force or not layout.config.exists():
        config = {
            "project": project_name or layout.root.name,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "heartbeat_stale_minutes": DEFAULT_STALE_MINUTES,
            "actors": [],
        }
        layout.config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    if not layout.ledger.exists():
        layout.ledger.write_text("", encoding="utf-8")

    return layout
