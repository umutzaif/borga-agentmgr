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

## Kullanım (M1)

```bash
agentmgr init                     # .agentmgr/ iskeletini kur
agentmgr log claim-solo --actor claude-desktop-01
agentmgr log charter-ack --actor claude-desktop-01 --data "{\"version\":1}"
agentmgr status                   # uzlaştırılmış durum
agentmgr verify                   # ledger hash zincirini denetle
```

`agentmgr log` olay tipleri: `agent-join`, `claim-solo`, `charter-ack`,
`manager-active`, `manager-idle`, `thread-open`, `thread-claim`, `thread-update`,
`thread-close`, `handoff-created`, `handoff-accepted`, `decision-proposed`,
`decision-ratified`, `heartbeat`.

## Yol haritası

| Adım | İçerik |
| ---- | ------ |
| **M1** ✅ | `init`, olay günlüğü + hash zinciri, `log`, `status`, `verify` |
| M2 | `claim-solo` / `charter-ack` kolaylıkları, `heartbeat`, `reconcile` / orphan tespiti |
| M3 | `handoff new` (git/ağaç/günlükten ön-doldurma) + `handoff accept` + sahiplik transferi |
| M4 | `manager start/stop/run`, `watch` (terminal panosu) |
| M5 | opsiyonel `dashboard` (tek dosya HTML) |
| v2 | fan-out / yeteneğe göre ekip dağıtımı, karar onay akışı |

## Test

```bash
python -m unittest discover -s tests -v
```
