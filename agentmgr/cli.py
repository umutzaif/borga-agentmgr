"""Command-line entry point: ``agentmgr <command>``.

M1 surface: ``init``, ``log``, ``status``, ``verify``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agentmgr import __version__
from agentmgr.charter import charter_fingerprint
from agentmgr.events import (
    KNOWN_EVENTS,
    append_event,
    read_events,
    sanitise_actor,
)
from agentmgr.handoff import create_handoff, find_handoff
from agentmgr.ledger import rebuild, verify
from agentmgr.paths import Layout, ProjectNotInitialised
from agentmgr.report import findings
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

    issues = findings(state, threshold)
    _write_threads_md(state, layout)
    rebuild(layout)

    if not issues:
        print(f"reconcile: no issues (threshold {threshold}m)")
        return 0
    print(f"reconcile: {len(issues)} finding(s) (threshold {threshold}m)")
    for item in issues:
        print(f"  - {item}")
    return 1 if args.strict else 0


# ------------------------------------------------------------------- M3 handoff
def cmd_handoff_new(args: argparse.Namespace) -> int:
    layout = _load()
    events = read_events(layout)
    state = reconcile(events)
    try:
        hid, path = create_handoff(layout, args.frm, args.to, events, state)
    except (ValueError, FileExistsError) as exc:
        _eprint(f"error: {exc}")
        return 1
    frm, to = sanitise_actor(args.frm), sanitise_actor(args.to)
    rel = path.relative_to(layout.root).as_posix()
    append_event(
        layout,
        "handoff-created",
        frm,
        {"id": hid, "from": frm, "to": to, "path": rel},
    )
    rebuild(layout)
    print(f"created {rel}")
    print("  fill in sections 1-7 by hand, then the receiver runs:")
    print(f"  agentmgr handoff accept {hid} --as {to}")
    return 0


def cmd_handoff_accept(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        path = find_handoff(layout, args.id)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    if path is None:
        _eprint(f"error: no handoff matching {args.id!r}")
        return 1

    hid = path.stem.split("-", 1)[0]
    events = read_events(layout)
    created = [e for e in events if e.event == "handoff-created" and e.data.get("id") == hid]
    accepted = [e for e in events if e.event == "handoff-accepted" and e.data.get("id") == hid]

    declared_to = created[0].data.get("to") if created else None
    if not declared_to and "-to-" in path.stem:
        declared_to = path.stem.split("-to-", 1)[1]

    target = args.as_ or declared_to
    if not target:
        _eprint("error: could not infer the accepting actor; pass --as <id>")
        return 1
    target = sanitise_actor(target)

    if accepted:
        print(f"handoff {hid} was already accepted by {accepted[-1].data.get('to')}")
        return 0
    if declared_to and target != declared_to:
        _eprint(f"warning: handoff {hid} targets {declared_to}, accepting as {target}")

    append_event(layout, "handoff-accepted", target, {"id": hid, "to": target})
    rebuild(layout)
    version, _ = charter_fingerprint(layout)
    ver_hint = f"   (CHARTER.md is at v{version})" if version else ""
    print(f"handoff {hid} accepted - ownership is now SOLO({target})")
    print("next:")
    print(f"  1. read {path.relative_to(layout.root).as_posix()} sections 1-7")
    print(f"  2. agentmgr charter-ack {target}{ver_hint}")
    print("  3. start from the 'siradaki adim' of the first open thread")
    return 0


def cmd_handoff_list(args: argparse.Namespace) -> int:
    layout = _load()
    docs = sorted(layout.handoff.glob("*.md")) if layout.handoff.is_dir() else []
    if not docs:
        print("no handoffs yet")
        return 0
    events = read_events(layout)
    accepted_ids = {e.data.get("id") for e in events if e.event == "handoff-accepted"}
    for path in docs:
        hid = path.stem.split("-", 1)[0]
        status = "accepted" if hid in accepted_ids else "PENDING"
        print(f"  {hid}  {status:<9} {path.stem}")
    return 0


def cmd_handoff_show(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        path = find_handoff(layout, args.id)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    if path is None:
        _eprint(f"error: no handoff matching {args.id!r}")
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


# ------------------------------------------------------------------- M3 threads
def _refresh_threads(layout: Layout) -> None:
    _write_threads_md(reconcile(read_events(layout)), layout)


def cmd_thread_add(args: argparse.Namespace) -> int:
    layout = _load()
    data: dict = {"id": args.id, "title": args.title}
    if args.owner:
        data["owner"] = sanitise_actor(args.owner)
    if args.next_step:
        data["next_step"] = args.next_step
    try:
        append_event(layout, "thread-open", args.actor, data)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    _refresh_threads(layout)
    print(f"thread {args.id} opened")
    return 0


def cmd_thread_update(args: argparse.Namespace) -> int:
    layout = _load()
    data: dict = {"id": args.id}
    if args.status:
        data["status"] = args.status
    if args.next_step is not None:
        data["next_step"] = args.next_step
    if args.owner:
        data["owner"] = sanitise_actor(args.owner)
    if len(data) == 1:
        _eprint("error: nothing to update - pass --status, --next, or --owner")
        return 1
    try:
        append_event(layout, "thread-update", args.actor, data)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    _refresh_threads(layout)
    print(f"thread {args.id} updated")
    return 0


def cmd_thread_close(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        append_event(layout, "thread-close", args.actor, {"id": args.id})
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    _refresh_threads(layout)
    print(f"thread {args.id} closed")
    return 0


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


# ------------------------------------------------------------------- M4 manager
def cmd_manager_start(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        actor = sanitise_actor(args.as_)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    state = reconcile(read_events(layout))
    if state.manager == actor:
        print(f"{actor} is already the active manager")
        return 0
    if state.manager:
        _eprint(f"warning: {state.manager} is already the active manager; taking over as {actor}")
    append_event(layout, "manager-active", actor, {})
    rebuild(layout)
    print(f"manager-active recorded for {actor}")
    return 0


def cmd_manager_stop(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        actor = sanitise_actor(args.as_)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    state = reconcile(read_events(layout))
    if state.manager != actor:
        _eprint(f"warning: active manager is {state.manager or 'none'}, not {actor}")
    append_event(layout, "manager-idle", actor, {})
    rebuild(layout)
    print(f"manager-idle recorded for {actor}")
    return 0


def cmd_manager_run(args: argparse.Namespace) -> int:
    layout = _load()
    try:
        actor = sanitise_actor(args.as_)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    interval = max(1, args.interval)

    append_event(layout, "manager-active", actor, {})
    rebuild(layout)
    print(f"manager {actor} active - reconciling every {interval}s (Ctrl+C to stop)")

    previous: list[str] | None = None
    tick = 0
    try:
        while True:
            events = read_events(layout)
            state = reconcile(events)
            cfg = load_config(layout)
            threshold = int(cfg.get("heartbeat_stale_minutes", 90))
            issues = findings(state, threshold)
            _write_threads_md(state, layout)
            if not args.once and tick % 5 == 0:
                append_event(layout, "heartbeat", actor, {"role": "manager"})
            rebuild(layout)

            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            if issues != previous:
                print(f"[{stamp}] mode={state.mode} events={state.event_count} findings={len(issues)}")
                for item in issues:
                    print(f"    - {item}")
                previous = issues
            else:
                print(f"[{stamp}] mode={state.mode} events={state.event_count} (no change)")

            if args.once:
                break
            tick += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
    finally:
        append_event(layout, "manager-idle", actor, {})
        rebuild(layout)
        print(f"manager {actor} idle")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    layout = _load()
    interval = max(1, args.interval)
    try:
        while True:
            state = reconcile(read_events(layout))
            cfg = load_config(layout)
            if not args.no_clear:
                print("\033[2J\033[H", end="")
            _render_status(state, cfg, layout)
            print(f"\n(watching - refresh {interval}s - Ctrl+C to stop)")
            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print()
    return 0


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

    p_ho = sub.add_parser("handoff", help="create / accept project handoffs")
    ho = p_ho.add_subparsers(dest="handoff_cmd", required=True)

    hn = ho.add_parser("new", help="scaffold a handoff packet with mechanical parts pre-filled")
    hn.add_argument("--from", dest="frm", required=True, help="outgoing actor id")
    hn.add_argument("--to", required=True, help="incoming actor id")
    hn.set_defaults(func=cmd_handoff_new)

    ha = ho.add_parser("accept", help="accept a handoff and take ownership")
    ha.add_argument("id", help="handoff id or unique prefix")
    ha.add_argument("--as", dest="as_", help="accepting actor id (default: the handoff target)")
    ha.set_defaults(func=cmd_handoff_accept)

    hl = ho.add_parser("list", help="list handoff packets and their status")
    hl.set_defaults(func=cmd_handoff_list)

    hs = ho.add_parser("show", help="print a handoff packet")
    hs.add_argument("id", help="handoff id or unique prefix")
    hs.set_defaults(func=cmd_handoff_show)

    p_th = sub.add_parser("thread", help="thread registry operations")
    th = p_th.add_subparsers(dest="thread_cmd", required=True)

    ta = th.add_parser("add", help="open a thread")
    ta.add_argument("id", help="short thread id, e.g. T1")
    ta.add_argument("--title", required=True)
    ta.add_argument("--actor", required=True)
    ta.add_argument("--owner")
    ta.add_argument("--next", dest="next_step", help="next concrete step")
    ta.set_defaults(func=cmd_thread_add)

    tu = th.add_parser("update", help="update a thread's status / next step / owner")
    tu.add_argument("id")
    tu.add_argument("--actor", required=True)
    tu.add_argument("--status", choices=["open", "blocked", "done"])
    tu.add_argument("--owner")
    tu.add_argument("--next", dest="next_step")
    tu.set_defaults(func=cmd_thread_update)

    tc = th.add_parser("close", help="close a thread")
    tc.add_argument("id")
    tc.add_argument("--actor", required=True)
    tc.set_defaults(func=cmd_thread_close)

    p_mgr = sub.add_parser("manager", help="manager lifecycle (coordination only)")
    mg = p_mgr.add_subparsers(dest="manager_cmd", required=True)

    m_start = mg.add_parser("start", help="stamp manager-active")
    m_start.add_argument("--as", dest="as_", required=True, help="manager actor id")
    m_start.set_defaults(func=cmd_manager_start)

    m_stop = mg.add_parser("stop", help="stamp manager-idle")
    m_stop.add_argument("--as", dest="as_", required=True, help="manager actor id")
    m_stop.set_defaults(func=cmd_manager_stop)

    m_run = mg.add_parser("run", help="active loop: reconcile + report + heartbeat until Ctrl+C")
    m_run.add_argument("--as", dest="as_", required=True, help="manager actor id")
    m_run.add_argument("--interval", type=int, default=30, help="seconds between cycles")
    m_run.add_argument("--once", action="store_true", help="run one cycle and exit")
    m_run.set_defaults(func=cmd_manager_run)

    p_watch = sub.add_parser("watch", help="live read-only status panel")
    p_watch.add_argument("--interval", type=int, default=5, help="seconds between refreshes")
    p_watch.add_argument("--once", action="store_true", help="render once and exit")
    p_watch.add_argument("--no-clear", action="store_true", help="do not clear the screen each refresh")
    p_watch.set_defaults(func=cmd_watch)

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
