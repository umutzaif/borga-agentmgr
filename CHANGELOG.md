# Changelog

Notable changes to agentmgr. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); the project uses
[Semantic Versioning](https://semver.org/).

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

[0.2.0]: https://github.com/umutzaif/borga-agentmgr/releases/tag/v0.2.0
