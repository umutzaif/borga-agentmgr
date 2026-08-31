# Proje Anayasası (Charter)

> Bu belge projenin **tek doğruluk kaynağıdır**. Bu projede çalışacak her agent,
> koda dokunmadan önce bunu baştan sona okur ve `agentmgr charter-ack <kimlik>`
> çalıştırır. Buradaki kararlar append-only'dir: değiştirmek için sessizce sapma;
> `agentmgr log decision-proposed` ile öneri aç, kabul edilirse sürüm numarasını artır.

**Sürüm:** 1
**Son güncelleme:** _<TARİH>_

---

## 1. Misyon

_<Projenin ne ürettiğini ve neden var olduğunu 3-5 cümlede yaz. Bu metin her
devir paketinin başında "kuzey yıldızı" olarak birebir tekrarlanır.>_

## 2. Kapsam dışı (non-goals)

- _<Bu projenin bilinçli olarak YAPMAYACAĞI şeyler. Kapsam kaymasını burada durdur.>_

## 3. Kısıtlar

- **Dil / sürüm:** _<...>_
- **Hedef platform:** _<...>_
- **Bağımlılık politikası:** _<ör. yalnızca standart kütüphane; yeni bağımlılık ADR gerektirir>_
- **Performans / kaynak sınırları:** _<...>_

## 4. Dizin ve isimlendirme şeması

- **Klasör düzeni:** _<...>_
- **Dosya / sembol isimlendirme:** _<kurallar + örnek>_

## 5. Tekrar-edilebilirlik (akademik)

- **Araç sürümleri:** _<sabitlenmiş sürümler / lockfile konumu>_
- **Rastgele tohumlar:** _<sabit seed değerleri ve nerede ayarlandığı>_
- **Veri kaynağı / provenance:** _<veri nereden, hangi sürüm, nasıl doğrulanır>_
- **Baştan üretme komutu:** _<projeyi sıfırdan üreten tek komut>_
- **Atıf / kaynak stili:** _<ör. IEEE>_
- **Commit mesaj formatı:** _<ör. Conventional Commits>_

## 6. "Definition of Done" (çıktı tipine göre)

| Çıktı tipi   | Bitti sayılması için                                        |
| ------------ | ---------------------------------------------------------- |
| Kod modülü   | testler geçer, tip denetimi temiz, genel API'de docstring |
| Doküman      | _<...>_                                                    |
| Deney / sonuç| _<...>_                                                    |

## 7. Yasak desenler

- _<Projede kesinlikle istenmeyen yaklaşımlar, kütüphaneler, stiller.>_

## 8. Terminoloji sözlüğü

| Terim    | Anlamı   |
| -------- | -------- |
| _<terim>_ | _<tanım>_ |

## 9. Kararlar (ADR — append-only)

### ADR-001: _<başlık>_

- **Tarih:** _<TARİH>_
- **Durum:** kabul edildi
- **Bağlam:** _<neden bir karara ihtiyaç vardı>_
- **Karar:** _<ne kararlaştırıldı>_
- **Sonuç:** _<etkileri ve ödünleşimleri>_
