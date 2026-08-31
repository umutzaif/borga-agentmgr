# Agent Bootstrap Talimatı

> Bu metni, bu projede çalışacak **her** agent'a oturumun en başında yapıştır.
> Sağlayıcıdan bağımsızdır. Amacı: agent'ın diğer agent'lardan haberdar olması
> ve Charter'a bağlı kalması.

---

Bu projede birden fazla agent koordineli çalışıyor olabilir. Koda dokunmadan
önce şu adımları uygula:

1. **Günlüğü oku.** `.agentmgr/ledger.jsonl` dosyasının son 20 satırına bak.
   (Yoksa `.agentmgr/events/` dizinini listele.)

2. **Manager var mı?** Son olaylarda `manager-active` varsa ve ona karşılık gelen
   `manager-idle` yoksa: **MANAGED moddasın.** Kendi başına iş başlatma; manager'dan
   görev ataması ya da bir devir paketi bekle.

3. **Manager yoksa (SOLO mod):**
   1. `.agentmgr/CHARTER.md` dosyasını baştan sona oku.
   2. En yeni `.agentmgr/HANDOFF/*.md` dosyası varsa onu oku.
   3. Şu komutları çalıştır (kimliğini sabit tut, ör. `claude-desktop-01`):

          agentmgr charter-ack <kimlik>
          agentmgr claim-solo <kimlik>

   4. Artık çalışabilirsin.

4. **İlerledikçe olay yaz.** Bir thread'in durumu değişince:

       agentmgr log thread-update --actor <kimlik> --data "{\"id\":\"<id>\",\"status\":\"blocked\",\"next_step\":\"...\"}"

   Bir thread bitince:

       agentmgr thread close --data "{\"id\":\"<id>\"}"

5. **Token'ın bitmek üzereyse DURMA — önce devret.** Bir devir paketi üret ve doldur:

       agentmgr handoff new --from <kimlik> --to <sıradaki-agent>

Charter'daki kararlar bağlayıcıdır. Bir kararı değiştirmen gerekiyorsa sessizce
sapma; `agentmgr log decision-proposed --actor <kimlik> --data "{...}"` ile öneri aç.
