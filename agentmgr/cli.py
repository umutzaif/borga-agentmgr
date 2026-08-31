"""Command-line entry point: ``agentmgr <command>``.

M1 surface: ``init``, ``log``, ``status``, ``verify``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentmgr import __version__
from agentmgr.charter import charter_fingerprint
from agentmgr.events import (
    KNOWN_EVENTS,
    append_event,
    parse_iso,
    read_events,
    sanitise_actor,
)
from agentmgr.ledger import rebuild, verify
from agentmgr.paths import Layout, ProjectNotInitialised
from agentmgr.scaffold import init_project
from agentmgr.state import ProjectState, load_config, reconcile


def _load(start: Path | None = None) -> Layout:
    """Discover the project or raise SystemExit(2) with a friendly message."""
    try:
        return Layout.discover(start)
    except ProjectNotInitialised as exc:
        _eprint(f"error: {exc}")
        raise SystemExit(2)


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------- init
def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    try:
        layout = init_project(root, project_name=args.name, force=args.force)
    except FileExistsError as exc:
        _eprint(f"error: {exc}")
        return 1
    print(f"initialised {layout.base}")
    for name in ("CHARTER.md", "STYLE.md", "AGENTS.md", "BOOTSTRAP.md", "config.json"):
        print(f"  {name}")
    print("\nnext: paste .agentmgr/BOOTSTRAP.md into each agent, then fill in CHARTER.md")
    return 0


# ---------------------------------------------------------------------------- log
def cmd_log(args: argparse.Namespace) -> int:
    try:
        layout = Layout.discover()
    except ProjectNotInitialised as exc:
        _eprint(f"error: {exc}")
        return 2

    if args.data:
        try:
            data = json.loads(args.data)
        except json.JSONDecodeError as exc:
            _eprint(f"error: --data is not valid JSON: {exc}")
            return 1
        if not isinstance(data, dict):
            _eprint("error: --data must be a JSON object")
            return 1
    else:
        data = {}

    if args.event not in KNOWN_EVENTS and not args.allow_unknown:
        _eprint(
            f"error: unknown event {args.event!r}. "
            f"pass --allow-unknown to force.\nknown events: {', '.join(sorted(KNOWN_EVENTS))}"
        )
        return 1

    try:
        ev = append_event(layout, args.event, args.actor, data)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    print(f"{ev.id}  {ev.event}  actor={ev.actor}")
    return 0


# ------------------------------------------------------------------------- status
def _render_status(state: ProjectState, cfg: dict, layout: Layout) -> None:
    project = cfg.get("project", layout.root.name)
    stale_minutes = int(cfg.get("heartbeat_stale_minutes", 90))
    stale = state.stale_agents(stale_minutes)

    bar = "-" * 60
    print(f"Agent Manager  .  {project}")
    print(bar)
    print(f"{'mode':<12}{state.mode}")
    print(f"{'manager':<12}{state.manager or '-'}")
    print(f"{'events':<12}{state.event_count}   last {state.last_event_ts or '-'}")
    print()

    print("agents")
    if not state.agents:
        print("  (none have joined yet)")
    for ag in sorted(state.agents.values(), key=lambda a: a.actor):
        flags = []
        if ag.solo:
            flags.append("solo")
        if ag.actor in stale:
            flags.append(f"STALE >{stale_minutes}m")
        ack = f"charter v{ag.charter_ack}" if ag.charter_ack else "charter -"
        tail = ("  " + ", ".join(flags)) if flags else ""
        print(f"  {ag.actor:<20} {ack:<12} last {ag.last_seen}{tail}")
    print()

    opened = state.open_threads()
    counts: dict[str, int] = {}
    for t in state.threads.values():
        counts[t.status] = counts.get(t.status, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "none"
    print(f"threads ({summary})")
    for t in sorted(state.threads.values(), key=lambda x: (x.status, x.id)):
        owner = f"  [{t.owner}]" if t.owner else ""
        step = f"  -> {t.next_step}" if t.next_step else ""
        print(f"  {t.status:<8} {t.id:<14} {t.title}{step}{owner}")
    print()

    print("pending handoffs")
    if not state.pending_handoffs:
        print("  (none)")
    for h in state.pending_handoffs:
        print(f"  {h.get('id')}  {h.get('from')} -> {h.get('to')}  ({h.get('ts')})")
    print()

    print("remaining work")
    if not opened:
        print("  (nothing open)")
    for t in opened:
        note = t.next_step or ("blocked" if t.status == "blocked" else "open")
        print(f"  - {t.title} - {note}")


def _write_threads_md(state: ProjectState, layout: Layout) -> None:
    lines = [
        "# Thread Durumu",
        "",
        "> Bu dosya `agentmgr status` tarafindan otomatik uretilir. Elle duzenleme.",
        "",
    ]
    if not state.threads:
        lines.append("_Henuz thread yok._")
    else:
        lines += ["| id | durum | sahip | baslik | siradaki adim |",
                  "| -- | ----- | ----- | ------ | ------------- |"]
        for t in sorted(state.threads.values(), key=lambda x: (x.status, x.id)):
            lines.append(
                f"| {t.id} | {t.status} | {t.owner or '-'} | {t.title} | {t.next_step or '-'} |"
            )
    layout.threads.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_status(args: argparse.Namespace) -> int:
    try:
        layout = Layout.discover()
    except ProjectNotInitialised as exc:
        _eprint(f"error: {exc}")
        return 2
    try:
        events = read_events(layout)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    state = reconcile(events)
    cfg = load_config(layout)
    _write_threads_md(state, layout)

    if args.json:
        print(json.dumps(_state_to_json(state), indent=2))
    else:
        _render_status(state, cfg, layout)
    return 0


def _state_to_json(state: ProjectState) -> dict:
    return {
        "mode": state.mode,
        "manager": state.manager,
        "event_count": state.event_count,
        "last_event_ts": state.last_event_ts,
        "agents": {
            a.actor: {
                "solo": a.solo,
                "charter_ack": a.charter_ack,
                "last_seen": a.last_seen,
            }
            for a in state.agents.values()
        },
        "threads": {
            t.id: {
                "title": t.title,
                "status": t.status,
                "owner": t.owner,
                "next_step": t.next_step,
            }
            for t in state.threads.values()
        },
        "pending_handoffs": state.pending_handoffs,
    }


# ------------------------------------------------------------------------- verify
def cmd_verify(args: argparse.Namespace) -> int:
    try:
        layout = Layout.discover()
    except ProjectNotInitialised as exc:
        _eprint(f"error: {exc}")
        return 2
    ok, msg = verify(layout)
    print(("OK    " if ok else "FAIL  ") + msg)
    return 0 if ok else 1


# ---------------------------------------------------------------- M2 convenience
def cmd_join(args: argparse.Namespace) -> int:
    layout = _load()
    data: dict = {}
    if args.provider:
        data["provider"] = args.provider
    if args.strengths:
        data["strengths"] = [s.strip() for s in args.strengths.split(",") if s.strip()]
    try:
        ev = append_event(layout, "agent-join", args.actor, data)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    _remember_actor(layout, ev.actor)
    rebuild(layout)
    print(f"agent-join recorded for {ev.actor}")
    return 0


def cmd_claim_solo(args: argparse.Namespace) -> int:
    layout = _load()
    state = reconcile(read_events(layout))
    try:
        actor = sanitise_actor(args.actor)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1

    if state.manager:
        print(f"manager {state.manager} is active - not writing claim-solo (safe no-op)")
        return 0

    existing = state.agents.get(actor)
    if existing and existing.solo:
        print(f"{actor} already holds a solo claim")
        return 0

    others = sorted(a.actor for a in state.agents.values() if a.solo and a.actor != actor)
    append_event(layout, "claim-solo", actor)
    rebuild(layout)
    if others:
        verb = "also holds" if len(others) == 1 else "also hold"
        _eprint(
            f"warning: {', '.join(others)} {verb} a solo claim - project is CONTESTED; "
            "resolve with a handoff or by starting the manager"
        )
    print(f"claim-solo recorded for {actor}")
    return 0


def cmd_charter_ack(args: argparse.Namespace) -> int:
    layout = _load()
    version, digest = charter_fingerprint(layout)
    if args.version is not None:
        version = args.version
    if version is None:
        _eprint(
            "error: could not read a version from CHARTER.md - add a "
            "'**Sürüm:** N' line or pass --version"
        )
        return 1

    data: dict = {"version": version}
    if digest:
        data["sha256"] = digest
    try:
        append_event(layout, "charter-ack", args.actor, data)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    tail = f" (sha {digest[:12]})" if digest else ""
    print(f"charter-ack v{version} recorded for {sanitise_actor(args.actor)}{tail}")
    return 0


def cmd_heartbeat(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        append_event(layout, "heartbeat", args.actor)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    print(f"heartbeat recorded for {sanitise_actor(args.actor)}")
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    layout = _load()
    state = reconcile(read_events(layout))
    cfg = load_config(layout)
    threshold = int(cfg.get("heartbeat_stale_minutes", 90))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold)

    findings: list[str] = []

    for actor in sorted(state.stale_agents(threshold, now)):
        seen = state.agents[actor].last_seen
        findings.append(f"orphaned solo claim: {actor} silent > {threshold}m (last {seen})")

    for ag in sorted(state.agents.values(), key=lambda a: a.actor):
        owns = any(t.owner == ag.actor for t in state.threads.values())
        if ag.charter_ack is None and (ag.solo or owns):
            findings.append(f"no charter-ack on record for active agent {ag.actor}")

    for thread in sorted(state.open_threads(), key=lambda t: t.id):
        if thread.updated and parse_iso(thread.updated) < cutoff:
            findings.append(
                f"stale thread {thread.id} ({thread.status}) - no update since {thread.updated}"
            )

    if state.mode == "CONTESTED":
        findings.append("mode CONTESTED: multiple solo claims and no active manager")

    _write_threads_md(state, layout)
    rebuild(layout)

    if not findings:
        print(f"reconcile: no issues (threshold {threshold}m)")
        return 0
    print(f"reconcile: {len(findings)} finding(s) (threshold {threshold}m)")
    for item in findings:
        print(f"  - {item}")
    return 1 if args.strict else 0


def _remember_actor(layout: Layout, actor: str) -> None:
    if not layout.config.exists():
        return
    try:
        cfg = json.loads(layout.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    actors = cfg.setdefault("actors", [])
    if actor not in actors:
        actors.append(actor)
        layout.config.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentmgr",
        description="Coordination layer for handing off and splitting a project across AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"agentmgr {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create .agentmgr/ with templates")
    p_init.add_argument("path", nargs="?", default=".", help="project root (default: cwd)")
    p_init.add_argument("--name", help="project name (default: folder name)")
    p_init.add_argument("--force", action="store_true", help="overwrite existing templates")
    p_init.set_defaults(func=cmd_init)

    p_log = sub.add_parser("log", help="append one event to the log")
    p_log.add_argument("event", help="event type (see 'known events' on error)")
    p_log.add_argument("--actor", required=True, help="stable actor id, e.g. claude-desktop-01")
    p_log.add_argument("--data", help="JSON object payload")
    p_log.add_argument("--allow-unknown", action="store_true", help="permit a non-standard event type")
    p_log.set_defaults(func=cmd_log)

    p_status = sub.add_parser("status", help="print the reconciled project state")
    p_status.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p_status.set_defaults(func=cmd_status)

    p_verify = sub.add_parser("verify", help="check the ledger hash chain")
    p_verify.set_defaults(func=cmd_verify)

    p_join = sub.add_parser("join", help="record agent-join with a capability profile")
    p_join.add_argument("actor", help="stable actor id")
    p_join.add_argument("--provider", help="e.g. Anthropic, OpenAI")
    p_join.add_argument("--strengths", help="comma-separated capability tags")
    p_join.set_defaults(func=cmd_join)

    p_solo = sub.add_parser("claim-solo", help="declare 'working alone'; no-op if a manager is active")
    p_solo.add_argument("actor", help="stable actor id")
    p_solo.set_defaults(func=cmd_claim_solo)

    p_ack = sub.add_parser("charter-ack", help="record that this agent read the current Charter")
    p_ack.add_argument("actor", help="stable actor id")
    p_ack.add_argument("--version", type=int, help="override the version read from CHARTER.md")
    p_ack.set_defaults(func=cmd_charter_ack)

    p_hb = sub.add_parser("heartbeat", help="record a liveness ping")
    p_hb.add_argument("actor", help="stable actor id")
    p_hb.set_defaults(func=cmd_heartbeat)

    p_rec = sub.add_parser("reconcile", help="report orphaned claims, stale threads, uncommitted agents")
    p_rec.add_argument("--strict", action="store_true", help="exit 1 if any finding")
    p_rec.set_defaults(func=cmd_reconcile)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
