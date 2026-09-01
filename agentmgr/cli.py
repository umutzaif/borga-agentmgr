"""Command-line entry point: ``agentmgr <command>``."""
# PYTHON_ARGCOMPLETE_OK

from __future__ import annotations

import argparse
import json
import subprocess
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
from agentmgr.fanout import plan_auto_assign
from agentmgr.handoff import create_handoff, find_handoff, unfilled_sections
from agentmgr.ledger import rebuild, verify
from agentmgr.paths import Layout, ProjectNotInitialised
from agentmgr.report import findings
from agentmgr.scaffold import init_project
from agentmgr.state import (
    DEFAULT_MANAGER_STALE_MINUTES,
    DEFAULT_STALE_MINUTES,
    DEFAULT_THREAD_STALE_MINUTES,
    ProjectState,
    load_config,
    reconcile,
)


def _thresholds(cfg: dict) -> tuple[int, int, int]:
    return (
        int(cfg.get("heartbeat_stale_minutes", DEFAULT_STALE_MINUTES)),
        int(cfg.get("thread_stale_minutes", DEFAULT_THREAD_STALE_MINUTES)),
        int(cfg.get("manager_stale_minutes", DEFAULT_MANAGER_STALE_MINUTES)),
    )




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
def _last_check(layout: Layout) -> dict | None:
    latest = None
    for ev in read_events(layout):
        if ev.event == "check-run":
            latest = {**ev.data, "ts": ev.ts, "actor": ev.actor}
    return latest


def _render_status(state: ProjectState, cfg: dict, layout: Layout) -> None:
    project = cfg.get("project", layout.root.name)
    solo_minutes, _, mgr_minutes = _thresholds(cfg)
    stale = state.stale_agents(solo_minutes)
    _, charter_sha = charter_fingerprint(layout)

    manager_line = state.manager or "-"
    if state.manager and state.manager_is_stale(mgr_minutes):
        manager_line = f"{state.manager}  (STALE - last {state.agents[state.manager].last_seen})"

    bar = "-" * 60
    print(f"Agent Manager  .  {project}")
    print(bar)
    print(f"{'mode':<12}{state.mode}")
    print(f"{'manager':<12}{manager_line}")
    print(f"{'events':<12}{state.event_count}   last {state.last_event_ts or '-'}")

    last_check = _last_check(layout)
    if last_check:
        verdict = "PASS" if last_check.get("ok") else "FAIL"
        print(f"{'last check':<12}{verdict} (exit {last_check.get('exit_code')})  {last_check.get('ts')}")
    print()

    print("agents")
    if not state.agents:
        print("  (none have joined yet)")
    for ag in sorted(state.agents.values(), key=lambda a: a.actor):
        flags = []
        if ag.solo:
            flags.append("solo")
        if ag.actor in stale:
            flags.append(f"STALE >{solo_minutes}m")
        if ag.charter_ack:
            drift = charter_sha and ag.charter_sha and ag.charter_sha != charter_sha
            ack = f"charter v{ag.charter_ack}" + (" DRIFT" if drift else "")
        else:
            ack = "charter -"
        tail = ("  " + ", ".join(flags)) if flags else ""
        print(f"  {ag.actor:<20} {ack:<16} last {ag.last_seen}{tail}")
    print()

    opened = state.open_threads()
    counts: dict[str, int] = {}
    for t in state.threads.values():
        counts[t.status] = counts.get(t.status, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "none"
    print(f"threads ({summary})")
    for t in sorted(state.threads.values(), key=lambda x: (x.status, x.id)):
        owner = f"  [{t.owner}]" if t.owner else ("  [unassigned]" if t.status != "done" else "")
        step = f"  -> {t.next_step}" if t.next_step else ""
        tags = f"  #{','.join(t.tags)}" if t.tags else ""
        print(f"  {t.status:<8} {t.id:<14} {t.title}{step}{owner}{tags}")
    print()

    if state.decisions:
        print("decisions")
        for d in sorted(state.decisions.values(), key=lambda x: x.id):
            mark = "ratified" if d.status == "ratified" else "PROPOSED"
            print(f"  {d.id:<18} {mark:<9} {d.title}")
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
        lines += ["| id | durum | sahip | etiketler | baslik | siradaki adim |",
                  "| -- | ----- | ----- | --------- | ------ | ------------- |"]
        for t in sorted(state.threads.values(), key=lambda x: (x.status, x.id)):
            tags = ",".join(t.tags) or "-"
            lines.append(
                f"| {t.id} | {t.status} | {t.owner or '-'} | {tags} | {t.title} | {t.next_step or '-'} |"
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
                "charter_sha": a.charter_sha,
                "provider": a.provider,
                "strengths": a.strengths,
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
                "tags": t.tags,
            }
            for t in state.threads.values()
        },
        "decisions": {
            d.id: {"title": d.title, "status": d.status, "proposer": d.proposer, "ratifier": d.ratifier}
            for d in state.decisions.values()
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


# -------------------------------------------------------------------- M4.5 check
def cmd_check(args: argparse.Namespace) -> int:
    layout = _load()
    cfg = load_config(layout)
    command = args.command or cfg.get("verify_command")
    if not command and (layout.root / "tests").is_dir():
        command = "python -m unittest discover -s tests"
    if not command:
        _eprint(
            "error: no check command - pass --command, or set \"verify_command\" in "
            ".agentmgr/config.json"
        )
        return 1

    try:
        proc = subprocess.run(
            command,
            cwd=layout.root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        ok, code, tail = False, None, f"timed out after {args.timeout}s"
    else:
        ok = proc.returncode == 0
        code = proc.returncode
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])

    actor = sanitise_actor(args.as_) if args.as_ else "check"
    append_event(
        layout,
        "check-run",
        actor,
        {"ok": ok, "exit_code": code, "command": command, "phase": args.phase, "tail": tail[:2000]},
    )
    rebuild(layout)
    print(f"check {'PASS' if ok else 'FAIL'} (exit {code})  [{args.phase}]  {command}")
    if not ok and tail:
        for line in tail.splitlines():
            print(f"  | {line}")
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
        _, _, mgr_stale = _thresholds(load_config(layout))
        if state.manager_is_stale(mgr_stale):
            seen = state.agents[state.manager].last_seen
            _eprint(
                f"warning: manager {state.manager} looks stale (last {seen}); "
                "recording claim-solo anyway"
            )
        else:
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
    solo_t, thread_t, mgr_t = _thresholds(load_config(layout))
    _, charter_sha = charter_fingerprint(layout)

    issues = findings(state, solo_t, thread_t, mgr_t, charter_sha)
    _write_threads_md(state, layout)
    rebuild(layout)

    if not issues:
        print(f"reconcile: no issues (solo {solo_t}m / thread {thread_t}m / manager {mgr_t}m)")
        return 0
    print(f"reconcile: {len(issues)} finding(s)")
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

    unfilled = unfilled_sections(path.read_text(encoding="utf-8"))
    if unfilled and not args.force:
        _eprint(
            "error: handoff packet still has unfilled placeholders in section(s): "
            + "; ".join(unfilled)
        )
        _eprint("  the outgoing agent should fill these in, or pass --force to accept anyway")
        return 1

    taker = reconcile(events).agents.get(target)
    if taker is None or taker.charter_ack is None:
        _eprint(
            f"warning: {target} has no charter-ack on record - it should run "
            f"'agentmgr charter-ack {target}' before working"
        )

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


def _parse_tags(raw: str | None) -> list[str]:
    return [t.strip().lower() for t in (raw or "").split(",") if t.strip()]


def cmd_thread_add(args: argparse.Namespace) -> int:
    layout = _load()
    data: dict = {"id": args.id, "title": args.title}
    if args.owner:
        data["owner"] = sanitise_actor(args.owner)
    if args.next_step:
        data["next_step"] = args.next_step
    if args.tags:
        data["tags"] = _parse_tags(args.tags)
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
    if args.tags is not None:
        data["tags"] = _parse_tags(args.tags)
    if len(data) == 1:
        _eprint("error: nothing to update - pass --status, --next, --owner, or --tags")
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


# --------------------------------------------------------------------- v2 fanout
def _actor_or_manager(args: argparse.Namespace, state: ProjectState) -> str | None:
    if args.as_:
        return sanitise_actor(args.as_)
    return state.manager


def cmd_assign(args: argparse.Namespace) -> int:
    layout = _load()
    state = reconcile(read_events(layout))
    actor = _actor_or_manager(args, state)
    if not actor:
        _eprint("error: no active manager - pass --as <id> to attribute the assignment")
        return 1

    if args.auto:
        plan = plan_auto_assign(state)
        if not plan:
            print("nothing to assign (no unowned open threads, or no agents have joined)")
            return 0
        for tid, agent, reason in plan:
            print(f"  {tid} -> {agent}  ({reason})")
        if args.dry_run:
            print("dry run - no events written")
            return 0
        for tid, agent, _ in plan:
            append_event(layout, "thread-claim", actor, {"id": tid, "owner": agent})
        rebuild(layout)
        _refresh_threads(layout)
        print(f"assigned {len(plan)} thread(s)")
        return 0

    if not args.thread or not args.to:
        _eprint("error: give a thread id and --to <agent>, or use --auto")
        return 1
    if args.thread not in state.threads:
        _eprint(f"error: no thread {args.thread!r}")
        return 1
    owner = sanitise_actor(args.to)
    append_event(layout, "thread-claim", actor, {"id": args.thread, "owner": owner})
    rebuild(layout)
    _refresh_threads(layout)
    print(f"thread {args.thread} -> {owner}")
    return 0


def _decision_id(now: datetime | None = None) -> str:
    # timestamp for readability + 4 random base32 chars so two proposals in the
    # same second do not collide
    from agentmgr.ulid import new_ulid

    return "D" + (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S") + new_ulid()[-4:]


def cmd_decision_propose(args: argparse.Namespace) -> int:
    layout = _load()
    did = args.id or _decision_id()
    data = {"id": did, "title": args.title}
    if args.body:
        data["body"] = args.body
    try:
        append_event(layout, "decision-proposed", args.as_, data)
    except ValueError as exc:
        _eprint(f"error: {exc}")
        return 1
    rebuild(layout)
    print(f"decision {did} proposed - ratify with: agentmgr decision ratify {did} --as <id>")
    return 0


def cmd_decision_ratify(args: argparse.Namespace) -> int:
    layout = _load()
    state = reconcile(read_events(layout))
    dec = state.decisions.get(args.id)
    if dec is None:
        matches = [d for d in state.decisions if d.startswith(args.id)]
        if len(matches) == 1:
            dec = state.decisions[matches[0]]
        elif len(matches) > 1:
            _eprint("error: ambiguous decision id; matches: " + ", ".join(matches))
            return 1
    if dec is None:
        _eprint(f"error: no decision matching {args.id!r}")
        return 1
    if dec.status == "ratified":
        print(f"decision {dec.id} was already ratified by {dec.ratifier}")
        return 0
    append_event(layout, "decision-ratified", args.as_, {"id": dec.id})
    rebuild(layout)
    print(f"decision {dec.id} ratified - record it in CHARTER.md section 9 (ADR)")
    return 0


def cmd_decision_list(args: argparse.Namespace) -> int:
    layout = _load()
    state = reconcile(read_events(layout))
    if not state.decisions:
        print("no decisions on record")
        return 0
    for dec in sorted(state.decisions.values(), key=lambda d: d.id):
        who = f"ratified by {dec.ratifier}" if dec.status == "ratified" else f"proposed by {dec.proposer}"
        print(f"  {dec.id}  {dec.status:<9} {dec.title}  ({who})")
    return 0


def cmd_integrate(args: argparse.Namespace) -> int:
    layout = _load()
    events = read_events(layout)
    state = reconcile(events)
    blockers: list[str] = []

    still_open = state.open_threads()
    if still_open:
        blockers.append(
            f"{len(still_open)} thread(s) still open: "
            + ", ".join(sorted(t.id for t in still_open))
        )

    last_close_ts = max(
        (e.ts for e in events if e.event == "thread-close"), default=None
    )
    last_check = None
    for e in events:
        if e.event == "check-run":
            last_check = e
    if last_check is None:
        blockers.append("no check has been run - 'agentmgr check' to verify the merged result")
    elif not last_check.data.get("ok"):
        blockers.append(f"last check FAILED (exit {last_check.data.get('exit_code')})")
    elif last_close_ts and last_check.ts < last_close_ts:
        blockers.append("last passing check predates the most recent thread-close - re-run 'agentmgr check'")

    for dec in sorted(state.open_decisions(), key=lambda d: d.id):
        blockers.append(f"decision {dec.id} still pending: {dec.title}")

    if state.manager_is_stale(int(load_config(layout).get("manager_stale_minutes", 15))):
        blockers.append(f"manager {state.manager} looks stale")

    if not blockers:
        print("READY to integrate: all threads done, last check passed, no pending decisions")
        return 0
    print(f"NOT ready to integrate - {len(blockers)} blocker(s):")
    for b in blockers:
        print(f"  - {b}")
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
        _, _, mgr_stale = _thresholds(load_config(layout))
        if state.manager_is_stale(mgr_stale):
            seen = state.agents[state.manager].last_seen
            print(f"previous manager {state.manager} looks stale (last {seen}); taking over as {actor}")
        else:
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
            solo_t, thread_t, mgr_t = _thresholds(load_config(layout))
            _, charter_sha = charter_fingerprint(layout)
            issues = findings(state, solo_t, thread_t, mgr_t, charter_sha)
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


def cmd_dashboard(args: argparse.Namespace) -> int:
    layout = _load()
    from agentmgr.dashboard import serve

    try:
        serve(
            layout,
            host=args.host,
            port=args.port,
            interval=max(1, args.interval),
            open_browser=not args.no_open,
        )
    except OSError as exc:
        _eprint(f"error: could not start dashboard on {args.host}:{args.port}: {exc}")
        return 1
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

    p_check = sub.add_parser("check", help="run the project's verify command and record the result")
    p_check.add_argument("--command", help="shell command (default: config verify_command, or unittest)")
    p_check.add_argument("--as", dest="as_", help="actor id to attribute the check to")
    p_check.add_argument("--phase", choices=["pre", "post", "ad-hoc"], default="ad-hoc")
    p_check.add_argument("--timeout", type=int, default=300, help="seconds before the command is killed")
    p_check.set_defaults(func=cmd_check)

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
    ha.add_argument("--force", action="store_true", help="accept even if the packet has unfilled placeholders")
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
    ta.add_argument("--tags", help="comma-separated capability tags for auto-assign")
    ta.set_defaults(func=cmd_thread_add)

    tu = th.add_parser("update", help="update a thread's status / next step / owner / tags")
    tu.add_argument("id")
    tu.add_argument("--actor", required=True)
    tu.add_argument("--status", choices=["open", "blocked", "done"])
    tu.add_argument("--owner")
    tu.add_argument("--next", dest="next_step")
    tu.add_argument("--tags", help="comma-separated; replaces the thread's tags")
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

    p_dash = sub.add_parser("dashboard", help="serve a local read-only web dashboard")
    p_dash.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=7777)
    p_dash.add_argument("--interval", type=int, default=2, help="browser poll seconds")
    p_dash.add_argument("--no-open", action="store_true", help="do not open a browser")
    p_dash.set_defaults(func=cmd_dashboard)

    p_assign = sub.add_parser("assign", help="assign threads to agents (fan-out)")
    p_assign.add_argument("thread", nargs="?", help="thread id (omit with --auto)")
    p_assign.add_argument("--to", help="agent id to own the thread")
    p_assign.add_argument("--auto", action="store_true", help="match all unowned open threads by tag/strength")
    p_assign.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    p_assign.add_argument("--as", dest="as_", help="actor to attribute the assignment to (default: active manager)")
    p_assign.set_defaults(func=cmd_assign)

    p_dec = sub.add_parser("decision", help="propose / ratify project decisions")
    dc = p_dec.add_subparsers(dest="decision_cmd", required=True)

    d_prop = dc.add_parser("propose", help="record a proposed decision")
    d_prop.add_argument("--as", dest="as_", required=True, help="proposing actor id")
    d_prop.add_argument("--title", required=True)
    d_prop.add_argument("--body")
    d_prop.add_argument("--id", help="decision id (default: D<timestamp>)")
    d_prop.set_defaults(func=cmd_decision_propose)

    d_rat = dc.add_parser("ratify", help="mark a proposed decision as ratified")
    d_rat.add_argument("id", help="decision id or unique prefix")
    d_rat.add_argument("--as", dest="as_", required=True, help="ratifying actor id")
    d_rat.set_defaults(func=cmd_decision_ratify)

    d_list = dc.add_parser("list", help="list decisions and their status")
    d_list.set_defaults(func=cmd_decision_list)

    p_int = sub.add_parser("integrate", help="readiness report for merging a fan-out back together")
    p_int.add_argument("--strict", action="store_true", help="exit 1 if not ready")
    p_int.set_defaults(func=cmd_integrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    parser = build_parser()
    try:  # optional: `pipx inject agentmgr argcomplete` or `pip install agentmgr[completion]`
        import argcomplete

        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
