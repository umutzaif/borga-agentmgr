# Changelog

Notable changes to agentmgr. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-10-04

Field fixes from the first end-to-end pilot (a small e-commerce app built by
Claude, Antigravity and Cursor through `agentmgr`).

### Fixed
- `handoff accept` now moves the outgoing agent's open threads to the
  receiver (it only logged `handoff-accepted` before, so the receiver had to
  re-own them by hand). Done threads and other agents' threads are untouched.
- `handoff accept` no longer marks the receiver `solo` while a manager is
  active; `status` stays honest in MANAGED/TEAM projects.
- The handoff completeness gate also catches `_<...>_` placeholders that wrap
  across lines (sections 2 and 5 of the template slipped through).
- Handoff packets only include git history when the project root *is* the git
  toplevel — a project nested in an unrelated repo no longer inherits that
  repo's commits. The fallback file tree honours `.gitignore` and skips
  `__pycache__`/`*.pyc`.
- Ratified decisions are rendered with their title in the packet instead of a
  raw dict.
- `log`/`thread` events reject thread statuses other than
  `open` / `blocked` / `done`.
- `manager run` heartbeats on a clock (about a third of
  `manager_stale_minutes`, never rarer than one cycle) instead of every fifth
  cycle, and warns when `--interval` is not shorter than the stale window.
  Previously `--interval 300` let the manager go stale between heartbeats.

### Changed
- `manager start` / `manager run` refuse to replace a fresh manager unless
  `--force`; replacing a stale one is still allowed but is recorded
  (`takeover_from` on the event) and `reconcile` reports it.
- `assign --auto` still skips the manager by default, but the manager (if it
  joined) is now eligible for a thread it matches by tag, instead of such a
  thread falling through to a poorly-matched agent.

## [0.2.0] - 2026-09-01

First feature-complete release: both halves of the brief — hand a project off
between agents, and split its threads across several agents.

### Added
- **Event log substrate** — one immutable file per event in
  `.agentmgr/events/`, race-free writes; `ledger.jsonl` is a derived,
  sha256 hash-chained mirror with `agentmgr verify`.
- **Solo protocol** — `init`, `join`, `claim-solo`, `charter-ack`,
  `heartbeat`, `reconcile`, `status`, `log`.
- **Handoff** — `handoff new/accept/list/show`: a packet with
  git log / file tree / open threads / Charter fingerprint pre-filled; solo
  ownership transfer; a completeness gate that refuses a packet with unfilled
  placeholders (`--force` overrides).
- **Manager** — `manager start/stop/run` coordination loop (reconcile +
  findings + heartbeat); stale-manager detection and auto-takeover;
  `watch` read-only terminal panel.
- **Fan-out** — `thread add/update/close` with capability `--tags`;
  `assign <thread> --to` and `assign --auto` (tag ↔ strength matching with
  load balancing); `decision propose/ratify/list`; `integrate` readiness
  report for merging a fan-out back together.
- **`check`** — run the project's verify command, record a `check-run` event;
  surfaced in `status`, `dashboard`, and `integrate`.
- **`dashboard`** — local `http.server` serving one self-contained HTML page
  that polls `/api/state`; read-only, binds `127.0.0.1`.
- Split staleness thresholds (`heartbeat_stale_minutes` /
  `thread_stale_minutes` / `manager_stale_minutes`); charter-drift detection.
- Optional shell completion via `argcomplete` (`agentmgr[completion]`).
- pipx-installable; MIT licensed; CI on Python 3.9 and 3.12 plus a packaging
  job; tag-triggered release workflow.

## [0.1.0] - 2026-08-31

### Added
- Initial skeleton: `init`, event log, `log`, `status`.

[0.2.1]: https://github.com/umutzaif/borga-agentmgr/releases/tag/v0.2.1
[0.2.0]: https://github.com/umutzaif/borga-agentmgr/releases/tag/v0.2.0
