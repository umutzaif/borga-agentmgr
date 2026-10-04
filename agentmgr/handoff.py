"""Handoff packets: everything a receiving agent needs to resume as if it were
the same agent. ``handoff new`` scaffolds the document and pre-fills the
mechanical parts (git log, file tree, open threads, Charter fingerprint); the
outgoing agent fills the judgement parts by hand.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from agentmgr.charter import charter_fingerprint
from agentmgr.events import Event, sanitise_actor
from agentmgr.state import ProjectState

_TEMPLATE = """# Devir Paketi: {frm} -> {to}

- **Devir id:** `{hid}`
- **Olusturuldu:** {ts}
- **Charter:** v{cver} (sha {csha})

> Devralan agent: bu paketi bastan sona oku, sonra
> `agentmgr handoff accept {hid} --as <kimligin>` calistir.
> Charter'daki kararlar baglayicidir; sessizce sapma.

---

## 1. Misyon (kuzey yildizi)

_<CHARTER.md section 1'den 2-3 cumleyle buraya kopyala.>_

## 2. Alinan kararlar ve nedenleri

_<Bu oturumda alinan, koddan anlasilmayan kararlar; "neden X degil Y" dahil.
Devralan bunlari yeniden tartismasin.>_

{decisions}

## 3. Dunyanin durumu

### Biten
_<...>_

### Suren
_<...>_

### Hic dokunulmamis
_<...>_

## 4. Acik thread'ler

{threads}

## 5. Yururlukteki gelenekler

_<Isimlendirme, dosya yapisi, terminoloji - Charter'i genisleten, bu oturumda
yerlesmis kurallar.>_

## 6. Mayinlar

_<Yanlis gorunup kasitli olan seyler. Denenip elenmis yaklasimlar ve neden.>_

## 7. Dogrulama

_<Devir oncesi/sonrasi "hala calisiyor" kontrolu.>_

```
{verify_hint}
```

## 8. Ilk 10 dakika (devralan icin)

1. `agentmgr status` ve `agentmgr verify` calistir.
2. CHARTER.md v{cver} oku, sonra `agentmgr charter-ack <kimligin>`.
3. Bu paketin 1-7. bolumlerini oku.
4. `agentmgr handoff accept {hid} --as <kimligin>`.
5. Bolum 4'teki ilk thread'in "siradaki adim"indan basla.

---

## Ek: repo durumu (otomatik uretildi)

### Son commit'ler
```
{gitlog}
```

### Dosya agaci
```
{tree}
```
"""


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _in_own_repo(root: Path) -> bool:
    """True only when ``root`` itself is the git toplevel.

    A project nested inside some other repository must not leak that repo's
    history or file list into its handoff packet.
    """
    top = _git(root, "rev-parse", "--show-toplevel")
    if not top:
        return False
    try:
        return os.path.samefile(top, root)
    except OSError:
        return False


_ALWAYS_IGNORED = ("__pycache__/", "*.pyc", ".git/", "node_modules/", ".venv/", "venv/")


def _ignore_patterns(root: Path) -> list[str]:
    patterns = list(_ALWAYS_IGNORED)
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        for line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "!")):
                patterns.append(line)
    return patterns


def _is_ignored(rel: str, patterns: list[str]) -> bool:
    """Small gitignore subset: ``*`` globs, trailing ``/`` = directory, ``/`` inside = anchored."""
    parts = rel.split("/")
    for raw in patterns:
        dir_only = raw.endswith("/")
        pat = raw.strip("/")
        if not pat:
            continue
        if raw.startswith("/") or "/" in pat:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/*"):
                return True
        else:
            names = parts[:-1] if dir_only else parts
            if any(fnmatch.fnmatch(name, pat) for name in names):
                return True
    return False


def _file_tree(root: Path, limit: int = 200) -> str:
    tracked = _git(root, "ls-files") if _in_own_repo(root) else ""
    if tracked:
        files = [f for f in tracked.splitlines() if not f.startswith(".agentmgr/")]
    else:
        patterns = _ignore_patterns(root)
        files = [
            rel
            for rel in (
                str(p.relative_to(root)).replace("\\", "/")
                for p in sorted(root.rglob("*"))
                if p.is_file()
            )
            if not rel.startswith(".agentmgr/") and not _is_ignored(rel, patterns)
        ]
    if len(files) > limit:
        files = files[:limit] + [f"... (+{len(files) - limit} more)"]
    return "\n".join(files) or "_(bos)_"


def _decisions_block(events: list[Event]) -> str:
    titles = {
        (ev.data.get("id") or ev.id): ev.data.get("title")
        for ev in events
        if ev.event == "decision-proposed"
    }
    lines = []
    for ev in events:
        if ev.event == "decision-proposed":
            did = ev.data.get("id") or ev.id
            lines.append(f"- **{ev.ts}** onerildi `{did}` ({ev.actor}): {titles.get(did) or did}")
        elif ev.event == "decision-ratified":
            did = str(ev.data.get("id", ""))
            lines.append(f"- **{ev.ts}** onaylandi `{did}` ({ev.actor}): {titles.get(did) or did}")
    if not lines:
        return "_Kayitli karar olayi yok - CHARTER.md ADR bolumune bak._"
    return "\n".join(lines)


def _threads_block(state: ProjectState) -> str:
    opened = state.open_threads()
    if not opened:
        return "_Acik thread yok._"
    chunks = []
    for t in sorted(opened, key=lambda x: x.id):
        chunks.append(
            f"### {t.id} - {t.title}\n"
            f"- durum: {t.status}\n"
            f"- sahip: {t.owner or '-'}\n"
            f"- siradaki adim: {t.next_step or '_<doldur>_'}\n"
            f"- blocker: _<varsa>_\n"
            f"- kabul kriteri: _<doldur>_"
        )
    return "\n\n".join(chunks)


def handoff_id(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")


def build_document(
    root: Path,
    frm: str,
    to: str,
    hid: str,
    charter_version: int | None,
    charter_sha: str | None,
    events: list[Event],
    state: ProjectState,
) -> str:
    verify_hint = (
        "python -m unittest discover -s tests -v"
        if (root / "tests").is_dir()
        else "_<projeyi dogrulayan komut>_"
    )
    gitlog = (_git(root, "log", "--oneline", "-15") if _in_own_repo(root) else "") or (
        "_(git gecmisi yok)_"
    )
    return _TEMPLATE.format(
        frm=frm,
        to=to,
        hid=hid,
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        cver=charter_version if charter_version is not None else "?",
        csha=(charter_sha[:12] if charter_sha else "?"),
        decisions=_decisions_block(events),
        threads=_threads_block(state),
        verify_hint=verify_hint,
        gitlog=gitlog,
        tree=_file_tree(root),
    )


def create_handoff(
    layout,
    frm: str,
    to: str,
    events: list[Event],
    state: ProjectState,
    now: datetime | None = None,
) -> tuple[str, Path]:
    frm = sanitise_actor(frm)
    to = sanitise_actor(to)
    if frm == to:
        raise ValueError("--from and --to must differ")
    hid = handoff_id(now)
    layout.handoff.mkdir(parents=True, exist_ok=True)
    path = layout.handoff / f"{hid}-{frm}-to-{to}.md"
    version, sha = charter_fingerprint(layout)
    body = build_document(layout.root, frm, to, hid, version, sha, events, state)
    with open(path, "x", encoding="utf-8") as fh:
        fh.write(body)
    return hid, path


# placeholders may wrap across lines; angle brackets inside are never part of one
_PLACEHOLDER_RE = re.compile(r"_<[^<>]*>_")
_SECTION_RE = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)


def unfilled_sections(text: str, through: int = 7) -> list[str]:
    """Numbered sections 1..``through`` that still contain a ``_<...>_`` placeholder."""
    marks = [(int(m.group(1)), m.group(2).strip(), m.start()) for m in _SECTION_RE.finditer(text)]
    marks.append((10**6, "", len(text)))
    bad: list[str] = []
    for (num, title, start), (_, _, nxt) in zip(marks, marks[1:]):
        if num <= through and _PLACEHOLDER_RE.search(text[start:nxt]):
            bad.append(f"{num}. {title}")
    return bad


def find_handoff(layout, token: str) -> Path | None:
    if not layout.handoff.is_dir():
        return None
    docs = sorted(layout.handoff.glob("*.md"))
    exact = [p for p in docs if p.stem == token]
    if exact:
        return exact[0]
    prefix = [p for p in docs if p.stem.startswith(token)]
    if len(prefix) == 1:
        return prefix[0]
    if len(prefix) > 1:
        raise ValueError(
            "ambiguous handoff id; matches: " + ", ".join(p.stem for p in prefix)
        )
    loose = [p for p in docs if token in p.stem]
    if len(loose) == 1:
        return loose[0]
    if len(loose) > 1:
        raise ValueError(
            "ambiguous handoff id; matches: " + ", ".join(p.stem for p in loose)
        )
    return None
