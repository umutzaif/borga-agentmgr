# Agent Kayıt Defteri

> Bir agent projeye ilk katıldığında buraya bir satır ekler ve şunu çalıştırır:
>
>     agentmgr log agent-join --actor <kimlik> --data "{\"provider\":\"...\",\"strengths\":[\"...\"]}"
>
> Manager, thread dağıtımında (v2) bu yetenek profillerini kullanır.
> Kimlikler oturum boyunca **sabit** kalmalı: `claude-desktop-01`, `gpt-desktop-01` gibi.

| Kimlik            | Sağlayıcı  | Güçlü olduğu alanlar                        | Notlar |
| ----------------- | ---------- | ------------------------------------------ | ------ |
| claude-desktop-01 | Anthropic  | _<ör. mimari, refactor, uzun bağlam>_      |        |
| gpt-desktop-01    | OpenAI     | _<ör. hızlı iterasyon, test yazımı>_       |        |
| _<kimlik>_        | _<...>_    | _<...>_                                    |        |
