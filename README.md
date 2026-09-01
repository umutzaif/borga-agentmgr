# agentmgr

Bir projeyi **farklı sağlayıcıların agent'ları** arasında; proje misyonunu,
tekdüzeliği ve akademik tekrar-edilebilirliği bozmadan **devreden** ve
**dağıtan** koordinasyon katmanı.

- **Devir (handoff):** token'ı biten bir agent'ın işi akış bozulmadan başka bir
  agent'a bırakması.
- **Bölüştürme (fan-out, v2):** iş parçacıklarının birden fazla agent'a
  yeteneklerine göre dağıtılması.

Tasarım belgesi: <https://claude.ai/code/artifact/3b2fac6a-94c9-48d0-94a3-1a63ab326686>

## Nasıl çalışır

Proje, koordinasyon durumunu tek bir `.agentmgr/` dizininde tutar. Her aktör
(agent, manager, insan) **olay başına bir dosya** yazarak haberleşir:

```
.agentmgr/
  CHARTER.md      proje anayasası - tek doğruluk kaynağı
  STYLE.md        yazım + kod stili çapası
  AGENTS.md       agent kimlikleri + yetenek profilleri
  BOOTSTRAP.md    her agent'a oturum başında yapıştırılacak talimat
  config.json     heartbeat eşiği, ayarlar
  events/         olay başına bir JSON dosyası - kanonik durum
  archive/        sıkıştırılmış eski olaylar
  ledger.jsonl    events/ dizininin hash-zincirli aynası (türetilir)
  HANDOFF/        devir paketleri
```

`events/` içindeki dosya adları `<ulid>-<aktör>.json` biçimindedir. ULID
benzersiz olduğu için iki aktör asla aynı dosyaya yazmaz — kilit yok, yarış yok,
sunucu yok. `ledger.jsonl` bir önbellektir; silinip `events/` dizininden yeniden
kurulabilir.

## Kurulum

Python 3.9+ gerekir, başka bağımlılık yok. Kalıcı bir CLI aracı olarak
[pipx](https://pipx.pypa.io) ile kurmak en temizi — kendi izole ortamına kurar,
`agentmgr` komutunu PATH'e ekler:

```bash
pipx install git+https://github.com/umutzaif/borga-agentmgr.git
```

Yerel bir klondan:

```bash
pipx install .
```

Yükseltme / kaldırma:

```bash
pipx upgrade agentmgr
pipx uninstall agentmgr
```

Geliştirme için düzenlenebilir kurulum:

```bash
pip install -e .
python -m unittest discover -s tests -v
```

## Kullanım

```bash
agentmgr init --name deneme               # .agentmgr/ iskeletini kur

agentmgr join gpt-desktop-01 --provider OpenAI --strengths "test, hiz"
agentmgr charter-ack claude-desktop-01    # sürüm + sha CHARTER.md'den okunur
agentmgr claim-solo claude-desktop-01     # manager aktifse güvenli no-op
agentmgr heartbeat claude-desktop-01

agentmgr status                           # uzlaştırılmış durum (+ --json)
agentmgr reconcile                        # sahipsiz claim / bayat thread / bayat manager / charter kayması
agentmgr verify                           # ledger hash zincirini denetle
agentmgr check --command "pytest" --as claude-desktop-01 --phase pre
#   projenin doğrulama komutunu çalıştırır, sonucu check-run olayı olarak kaydeder

agentmgr log <event> --actor <id> --data '{...}'   # ham olay ekleme
```

### Devir (handoff)

```bash
agentmgr thread add T1 --title "Parser" --actor claude-desktop-01 --next "lexer"
agentmgr thread update T1 --actor claude-desktop-01 --status blocked
agentmgr thread close T1 --actor claude-desktop-01

agentmgr handoff new --from claude-desktop-01 --to gpt-desktop-01
#   -> HANDOFF/<ts>-...-to-...md; git log, dosya ağacı, açık thread'ler,
#      Charter sürüm/hash önden dolu. 1-7. bölümleri elle doldur.
agentmgr handoff list
agentmgr handoff show <id>
agentmgr handoff accept <id> --as gpt-desktop-01
#   -> handoff-accepted olayı + sahiplik SOLO(claude) -> SOLO(gpt)
```

### Fan-out (v2 — iş bölüştürme)

```bash
agentmgr thread add T1 --title "Parser" --actor mgr --tags "parser,mimari"
agentmgr thread add T2 --title "Testler" --actor mgr --tags "test yazimi"

agentmgr assign T1 --to claude-desktop-01          # açıkça ata
agentmgr assign --auto [--dry-run]                 # etiket ↔ yetenek eşleştirmesi + yük dengesi

agentmgr decision propose --as claude-desktop-01 --title "olay günlüğü JSONL"
agentmgr decision ratify <D-id> --as gpt-desktop-01
agentmgr decision list

agentmgr integrate [--strict]                      # fan-out'u birleştirmeye hazır mı?
#   tüm thread'ler done + son check geçti + bekleyen karar yok  ->  READY
```

### Manager ve izleme

```bash
agentmgr manager start --as manager-01     # manager-active damgası -> MANAGED mod
agentmgr manager run --as manager-01 --interval 30
#   arka plan döngüsü: her 30s reconcile + bulgu raporu + THREADS.md yenile
#   + periyodik manager heartbeat; Ctrl+C'de manager-idle yazıp çıkar
agentmgr manager stop --as manager-01      # manager-idle damgası

agentmgr watch --interval 5                 # salt-okunur canlı pano (hiçbir şey yazmaz)
agentmgr dashboard --port 7777              # tarayıcıda salt-okunur pano (127.0.0.1)
```

`agentmgr log` olay tipleri: `agent-join`, `claim-solo`, `charter-ack`,
`manager-active`, `manager-idle`, `thread-open`, `thread-claim`, `thread-update`,
`thread-close`, `handoff-created`, `handoff-accepted`, `decision-proposed`,
`decision-ratified`, `heartbeat`.

## Yol haritası

| Adım | İçerik |
| ---- | ------ |
| **M1** ✅ | `init`, olay günlüğü + hash zinciri, `log`, `status`, `verify` |
| **M2** ✅ | `join` / `claim-solo` / `charter-ack` / `heartbeat` kolaylıkları, `reconcile` (orphan / bayat / eksik ack) |
| **M3** ✅ | `handoff new` (git/ağaç/günlük/Charter ön-doldurma) + `handoff accept/list/show` + sahiplik transferi, `thread add/update/close` |
| **M4** ✅ | `manager start/stop/run` (reconcile döngüsü + heartbeat), `watch` (salt-okunur terminal panosu) |
| **M4.5** ✅ | bayat manager tespiti + otomatik devralma, `check` (doğrulama komutu → `check-run`), handoff placeholder kapısı (`--force`), charter kayması uyarısı, ayrı bayatlık eşikleri |
| **M5** ✅ | `dashboard` — yerel `http.server` + tek dosya HTML, `/api/state` yoklaması, salt-okunur |
| **v2** ✅ | `assign` (açık + `--auto` etiket/yetenek eşleştirme), thread `--tags`, `decision propose/ratify/list`, `integrate` hazırlık raporu; unassigned-thread ve pending-decision bulguları |

## Test

```bash
python -m unittest discover -s tests -v
```
