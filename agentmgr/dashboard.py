"""Optional read-only web dashboard: ``agentmgr dashboard``.

A local ``http.server`` serves one self-contained HTML page that polls
``/api/state``. It is a pure consumer of the event log - it never writes an
event and never rebuilds the ledger. Bind is 127.0.0.1 by default.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agentmgr.charter import charter_fingerprint
from agentmgr.events import now_iso, read_events
from agentmgr.ledger import head
from agentmgr.paths import Layout
from agentmgr.report import findings
from agentmgr.state import (
    DEFAULT_MANAGER_STALE_MINUTES,
    DEFAULT_STALE_MINUTES,
    DEFAULT_THREAD_STALE_MINUTES,
    load_config,
    reconcile,
)


def build_state(layout: Layout) -> dict:
    events = read_events(layout)
    state = reconcile(events)
    cfg = load_config(layout)
    solo_t = int(cfg.get("heartbeat_stale_minutes", DEFAULT_STALE_MINUTES))
    thread_t = int(cfg.get("thread_stale_minutes", DEFAULT_THREAD_STALE_MINUTES))
    mgr_t = int(cfg.get("manager_stale_minutes", DEFAULT_MANAGER_STALE_MINUTES))
    _, charter_sha = charter_fingerprint(layout)
    stale = state.stale_agents(solo_t)

    last_check = None
    for ev in events:
        if ev.event == "check-run":
            last_check = {**ev.data, "ts": ev.ts, "actor": ev.actor}

    return {
        "project": cfg.get("project", layout.root.name),
        "generated": now_iso(),
        "mode": state.mode,
        "manager": state.manager,
        "manager_stale": state.manager_is_stale(mgr_t),
        "event_count": state.event_count,
        "last_event_ts": state.last_event_ts,
        "ledger_head": head(layout),
        "charter_sha": charter_sha,
        "agents": [
            {
                "actor": a.actor,
                "solo": a.solo,
                "charter_ack": a.charter_ack,
                "charter_drift": bool(charter_sha and a.charter_sha and a.charter_sha != charter_sha),
                "stale": a.actor in stale,
                "last_seen": a.last_seen,
            }
            for a in sorted(state.agents.values(), key=lambda x: x.actor)
        ],
        "threads": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "owner": t.owner,
                "next_step": t.next_step,
                "updated": t.updated,
            }
            for t in sorted(state.threads.values(), key=lambda x: (x.status, x.id))
        ],
        "pending_handoffs": state.pending_handoffs,
        "findings": findings(state, solo_t, thread_t, mgr_t, charter_sha),
        "last_check": last_check,
        "recent_events": [
            {"ts": e.ts, "actor": e.actor, "event": e.event} for e in events[-40:]
        ],
    }


def _make_handler(layout: Layout, interval: int):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = _PAGE.replace("__INTERVAL__", str(interval))
                self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
            elif path == "/api/state":
                try:
                    payload = json.dumps(build_state(layout), ensure_ascii=False)
                    self._send(200, "application/json; charset=utf-8", payload.encode("utf-8"))
                except Exception as exc:  # never take the server down over one bad read
                    self._send(500, "application/json", json.dumps({"error": str(exc)}).encode())
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

        def log_message(self, *args) -> None:  # keep the console quiet
            pass

    return Handler


def make_server(layout: Layout, host: str, port: int, interval: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _make_handler(layout, interval))


def serve(
    layout: Layout,
    host: str = "127.0.0.1",
    port: int = 7777,
    interval: int = 2,
    open_browser: bool = True,
) -> None:
    httpd = make_server(layout, host, port, interval)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"agentmgr dashboard on {url}  (read-only; Ctrl+C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()


_PAGE = r"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>agentmgr dashboard</title>
<style>
  :root {
    --bg:#f6f7f9; --surface:#fff; --sunk:#eef0f3; --ink:#1b1e25; --soft:#454b57;
    --faint:#6b7280; --rule:#dfe2e7; --accent:#b56a1b;
    --good:#3f7d5c; --warn:#b0791f; --crit:#b0433a; --info:#3057a8;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#121419; --surface:#1a1d23; --sunk:#22262e; --ink:#e7e9ec; --soft:#b3b9c4;
      --faint:#838b98; --rule:#333944; --accent:#e0913f;
      --good:#63a883; --warn:#d69f4c; --crit:#d9645a; --info:#7aa2e3;
    }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  .mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
  header { padding:1rem 1.25rem; border-bottom:1px solid var(--rule);
    display:flex; flex-wrap:wrap; gap:.5rem 1.25rem; align-items:baseline; }
  header h1 { font-size:1rem; margin:0; font-weight:600; }
  header .meta { color:var(--faint); font-size:.8rem; }
  main { padding:1.25rem; display:grid; gap:1.25rem;
    grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); max-width:1400px; }
  section { background:var(--surface); border:1px solid var(--rule); border-radius:8px; padding:1rem; }
  section h2 { font-size:.72rem; letter-spacing:.12em; text-transform:uppercase;
    color:var(--faint); margin:0 0 .75rem; }
  .badge { display:inline-block; padding:.15em .6em; border-radius:999px; font-size:.75rem;
    font-weight:600; border:1px solid currentColor; }
  .b-idle{color:var(--faint)} .b-solo{color:var(--info)} .b-managed{color:var(--good)}
  .b-team{color:var(--good)} .b-contested{color:var(--crit)}
  table { width:100%; border-collapse:collapse; }
  th,td { text-align:left; padding:.4rem .5rem; border-bottom:1px solid var(--rule); vertical-align:top; }
  th { font-size:.68rem; letter-spacing:.08em; text-transform:uppercase; color:var(--faint); }
  tr:last-child td { border-bottom:none; }
  .pill { font-size:.68rem; padding:.1em .5em; border-radius:4px; background:var(--sunk); }
  .pill.open{color:var(--info)} .pill.blocked{color:var(--warn)} .pill.done{color:var(--faint)}
  .flag { color:var(--crit); font-weight:600; font-size:.72rem; }
  .ok { color:var(--good); font-weight:600; }
  .fail { color:var(--crit); font-weight:600; }
  ul.findings { margin:0; padding-left:1.1rem; }
  ul.findings li { color:var(--crit); margin:.2rem 0; }
  ul.findings li.none { color:var(--good); list-style:none; margin-left:-1.1rem; }
  .feed { max-height:320px; overflow-y:auto; }
  .feed div { padding:.25rem 0; border-bottom:1px solid var(--rule); font-size:.8rem; }
  .feed .t { color:var(--faint); }
  .empty { color:var(--faint); font-style:italic; }
  footer { padding:.75rem 1.25rem; color:var(--faint); font-size:.75rem; border-top:1px solid var(--rule); }
  .stale { color:var(--warn); font-weight:600; }
</style>
</head>
<body>
<header>
  <h1 id="project">agentmgr</h1>
  <span id="mode"></span>
  <span class="meta" id="manager"></span>
  <span class="meta mono" id="head"></span>
  <span class="meta" id="gen"></span>
</header>
<main>
  <section><h2>Bulgular</h2><ul class="findings" id="findings"></ul></section>
  <section><h2>Son kontrol</h2><div id="check" class="empty">-</div></section>
  <section style="grid-column:1/-1"><h2>Agent'lar</h2><table id="agents"><tbody></tbody></table></section>
  <section style="grid-column:1/-1"><h2>Thread'ler</h2><table id="threads"><tbody></tbody></table></section>
  <section><h2>Bekleyen devirler</h2><table id="handoffs"><tbody></tbody></table></section>
  <section><h2>Son olaylar</h2><div class="feed" id="feed"></div></section>
</main>
<footer>agentmgr dashboard - salt-okunur - <span id="poll"></span>s'de bir yenilenir</footer>
<script>
const INTERVAL = parseInt("__INTERVAL__", 10) || 2;
document.getElementById("poll").textContent = INTERVAL;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function render(d) {
  $("project").textContent = d.project;
  const m = (d.mode || "").toLowerCase().replace(/\(.*/, "");
  const cls = m.startsWith("solo") ? "b-solo" : m === "managed" ? "b-managed"
            : m === "team" ? "b-team" : m === "contested" ? "b-contested" : "b-idle";
  $("mode").innerHTML = `<span class="badge ${cls}">${esc(d.mode)}</span>`;
  $("manager").innerHTML = d.manager
    ? `manager: ${esc(d.manager)}${d.manager_stale ? ' <span class="stale">STALE</span>' : ""}`
    : "manager: -";
  $("head").textContent = "head " + (d.ledger_head || "").slice(0, 12) + "  ·  " + d.event_count + " olay";
  $("gen").textContent = "guncelleme " + (d.generated || "").replace("T", " ").replace(/\.\d+Z$/, "Z");

  const f = $("findings");
  f.innerHTML = d.findings.length
    ? d.findings.map(x => `<li>${esc(x)}</li>`).join("")
    : `<li class="none">temiz</li>`;

  const c = d.last_check;
  $("check").className = c ? "" : "empty";
  $("check").innerHTML = c
    ? `<span class="${c.ok ? "ok" : "fail"}">${c.ok ? "PASS" : "FAIL"}</span> (exit ${c.exit_code}) `
      + `[${esc(c.phase || "-")}] <span class="t">${esc(c.ts)}</span><br><span class="mono">${esc(c.command || "")}</span>`
    : "hic kontrol calistirilmadi";

  $("agents").querySelector("tbody").innerHTML = d.agents.length ? d.agents.map(a => `<tr>
    <td>${esc(a.actor)}</td>
    <td>${a.solo ? "solo" : ""}</td>
    <td>${a.charter_ack ? "charter v" + a.charter_ack : '<span class="flag">ack yok</span>'}
        ${a.charter_drift ? '<span class="flag">DRIFT</span>' : ""}</td>
    <td>${a.stale ? '<span class="stale">STALE</span>' : ""}</td>
    <td class="mono t">${esc(a.last_seen)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">henuz agent yok</td></tr>`;

  $("threads").querySelector("tbody").innerHTML = d.threads.length ? d.threads.map(t => `<tr>
    <td class="mono">${esc(t.id)}</td>
    <td><span class="pill ${esc(t.status)}">${esc(t.status)}</span></td>
    <td>${esc(t.title)}</td>
    <td>${esc(t.owner || "-")}</td>
    <td>${esc(t.next_step || "-")}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">thread yok</td></tr>`;

  $("handoffs").querySelector("tbody").innerHTML = d.pending_handoffs.length
    ? d.pending_handoffs.map(h => `<tr><td class="mono">${esc(h.id)}</td>
        <td>${esc(h.from)} &rarr; ${esc(h.to)}</td><td class="t mono">${esc(h.ts)}</td></tr>`).join("")
    : `<tr><td class="empty">yok</td></tr>`;

  $("feed").innerHTML = d.recent_events.slice().reverse().map(e =>
    `<div><span class="t mono">${esc(e.ts)}</span> &nbsp; <b>${esc(e.event)}</b> &nbsp; ${esc(e.actor)}</div>`
  ).join("") || `<div class="empty">olay yok</div>`;
}

async function tick() {
  try {
    const r = await fetch("/api/state", {cache: "no-store"});
    render(await r.json());
  } catch (e) { /* keep last render */ }
}
tick();
setInterval(tick, INTERVAL * 1000);
</script>
</body>
</html>
"""
