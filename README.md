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

```bash
pip install -e .
```

Python 3.9+ gerekir, başka bağımlılık yok.

## Kullanım

```bash
agentmgr init --name deneme               # .agentmgr/ iskeletini kur

agentmgr join gpt-desktop-01 --provider OpenAI --strengths "test, hiz"
agentmgr charter-ack claude-desktop-01    # sürüm + sha CHARTER.md'den okunur
agentmgr claim-solo claude-desktop-01     # manager aktifse güvenli no-op
agentmgr heartbeat claude-desktop-01

agentmgr status                           # uzlaştırılmış durum (+ --json)
agentmgr reconcile                        # sahipsiz claim / bayat thread / eksik ack
agentmgr verify                           # ledger hash zincirini denetle

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

### Manager ve izleme

```bash
agentmgr manager start --as manager-01     # manager-active damgası -> MANAGED mod
agentmgr manager run --as manager-01 --interval 30
#   arka plan döngüsü: her 30s reconcile + bulgu raporu + THREADS.md yenile
#   + periyodik manager heartbeat; Ctrl+C'de manager-idle yazıp çıkar
agentmgr manager stop --as manager-01      # manager-idle damgası

agentmgr watch --interval 5                 # salt-okunur canlı pano (hiçbir şey yazmaz)
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
| M5 | opsiyonel `dashboard` (tek dosya HTML) |
| v2 | fan-out / yeteneğe göre ekip dağıtımı, karar onay akışı |

## Test

```bash
python -m unittest discover -s tests -v
```
