# Etsy Takı Otomasyon — Kullanıcı Rehberi

**Hedef kitle:** Sen. Bu doc'u backend hazır olduğunda günlük operasyonda referans alacaksın.

**Toplam okuma süresi:** ~15 dakika. Sonra bookmark'la.

---

## 📋 0. Hızlı Referans (One-pager)

### Günlük rutin (~45 dk)
```
1. Sabah:   sistemi başlat (docker + uvicorn)        2 dk
2. Sabah:   yeni ürün üret (10 ürün hedef)          25 dk
            → manual input → generate → approve → publish
3. Akşam:   dünkü ürün performansını incele          5 dk
4. Akşam:   kritik listing'leri renew (otomatik)     0 dk
5. Akşam:   1 hafta öncesi listing'leri değerlendir 10 dk
```

### Haftalık rutin (~30 dk)
```
Pazartesi sabah:
  • Phase 2 yeni research scrape (3-5 keyword)
  • CSV import → backend analizler güncellenir
  • Top 3 niche performansını kontrol et
```

### Aylık rutin (~1 saat)
```
Ay başı:
  • Variant A vs B vs C kazanma oranını incele
  • En iyi performans gösteren carrier pillar'a kayma
  • Keyword pool'a yeni keyword'ler ekle
```

---

## 🚀 1. İlk Kurulum (Bir Kere)

### 1.1 — Browser Profile Hazırlığı (5 dk)
1. Chrome → sağ üst → profil ikonu → **Add**
2. Adı: `Etsy Research`. İkonunu fark edilir bir renkte seç.
3. **Bu profile'a Etsy mağaza hesabınla LOGIN OLMA**
4. EHunt extension'ı **bu profile'a** yükle
5. EHunt'a abonelik hesabınla giriş yap
6. Etsy Research extension v2.4'ü bu profile'a yükle (`chrome://extensions` → Load unpacked)
7. **Kontrol:** rastgele bir Etsy listing'i aç, EHunt panel'i yüklendiğinde "Tags :" altında 13 tag görmeli sin

### 1.2 — Backend Başlatma (2 dk)
```bash
cd ~/projects/etsy-taki
docker compose up -d                  # postgres ayağa kalkar
source .venv/bin/activate
uvicorn src.main:app --reload         # backend localhost:8000'de
```

`localhost:8000/admin` → dashboard'a girebiliyorsan kurulum tamam.

### 1.3 — Keyword Pool Yükle (OPSİYONEL, ileride yapabilirsin)

> ⚠️ **Önemli not:** Bu CSV, extension'ın ürettiği `etsy-research-*.csv` ile **farklı**.
> - **Research CSV** (extension üretir, otomatik): rakip listing verisi → `CompetitorListing` tablosu
> - **Keyword pool CSV** (sen elle yazıyorsun): senin tercih ettiğin keyword'ler → `KeywordPool` tablosu
>
> İlk başta atlayabilirsin. Research data zaten yeterince zengin (EHunt'tan gerçek tag'ler + volume geliyor).

**Eğer yine de hazırlamak istersen:** `data/keyword_pool.csv`. Format:

```csv
keyword,category,carrier_pillar
dainty cross necklace,niche,cross
tiny cross pendant,niche,cross
gold cross necklace,medium,cross
cross necklace,big,cross
birthstone necklace,big,birthstone
personalized birthstone,niche,birthstone
...
```

**Ne işe yarar:** Phase 6.3 Tag Generator çalışırken iki kaynağa bakar:
1. Research'tan (rakip pattern'leri) — otomatik, hep var
2. **KeywordPool'dan (senin tercihlerin)** — bu CSV'i yüklersen var, yüklemezsen yok

Yani bu CSV "tag generator'a benim mağazamın imzasını ekle" demek. "Her cross necklace listing'imde 'minimalist' tag'i olsun" gibi tercihlerini buraya yazarsın.

**Ne zaman lazım olur:**
- Mağazana özel bir branding tag'i her zaman istiyorsan (örn. "boho jewelry")
- Bazı niche'lerin research'i henüz toplanmamışsa (cold-start)
- Şahsen sevdiğin ama rakiplerin az kullandığı keyword'leri zorlamak istiyorsan

Yüklemek için: `/admin/keywords` → "Import CSV". Sonra dilediğin zaman yenisini ekleyebilirsin.

**Sonuç: ilk gün için ATLA. İlk ay üretim yaptıktan sonra "şu tag her zaman olsun" dediğin pattern'ler oluşunca geri dön ve bu CSV'i hazırla.**

### 1.4 — İlk Research Scrape (45 dk)

İlk pazar bilgini topla:

1. Chrome Research profile'ında Etsy.com'a git
2. **Extension popup** → Phase 1 başlat
3. Keyword'ler: `cross necklace`, `birthstone necklace`, `name necklace` (3 keyword yeterli ilk için)
4. Her keyword için: 60-80 listing scrape (default)
5. ~15 dakika sonra Phase 1 biter → bildirimle haber alırsın
6. Sortable tabloda top 30-50 listing'i seç (high EHunt sales)
7. **Phase 2 başlat** → seçili listing'leri detay scrape
8. ~20-25 dakika sonra Phase 2 biter
9. CSV'i indir
10. Backend'de: `/admin/research/import` → CSV upload
11. Backend analizi otomatik çalışır → `/admin/research` dashboard'da niche bilgisini görürsün

Artık üretim modunda hazırsın.

---

## 📦 2. Günlük Ürün Üretimi

### 2.1 — Reksven'den Ürün Seç

Reksven listing'inden ürün seç. Önemli kriterler:
- **Stok durumu**: stokta olmalı
- **Fiyat**: $5-15 (sen $25-45'e satacaksın)
- **Fotoğraf kalitesi**: en az 3 net fotoğraf
- **Personalization mümkün mü** (isim, doğum taşı vs) — bonus puan

### 2.2 — Manuel Input (3-5 dk)

Backend'de **`/products/new`** sayfasına git:

| Alan | Örnek değer | Notlar |
|------|-------------|--------|
| SKU | TAKI-0142 | otomatik öneri kabul et |
| Carrier Pillar | Cross | 6 seçenekten biri |
| Material | 18K Gold Plated | Reksven'den |
| Color | Gold | |
| Has Stone | ✓ | |
| Stone Type | CZ Baguette | "Stone" demek YASAK; CZ ya da Pave demeli |
| Shape | Sideways | yatay/dikey/küçük vs |
| Style | Minimalist | |
| Occasion | Confirmation, Christmas | birden fazla seçilebilir |
| Recipient | Daughter, Mom | |
| Size Info | 18 inch chain, 5mm pendant | |
| Cost | $7.50 | senin alış maliyetin |
| Selling Price | $32.99 | önerilen, değiştirebilirsin |
| Photos | 3-5 supplier photo upload | Reksven'den indirdiğin |
| Source URL | Reksven listing linki | referans için |

**Carrier pillar seçimi** çok önemli — sonraki AI image prompts ve LLM stratejisi bunu kullanıyor. Doğru seç.

### 2.3 — Generate Tıkla (45-75 sn bekle)

Backend arka planda şunları yapar:
1. **Stage 1**: AI image generation (3 supplier + 6 AI lifestyle = 9 toplam)
2. **Stage 2 (paralel)**: 3 LLM variant üretir
3. **Stage 3**: Validation (title 137-140 char, 13 tag, originality ≥96%)

Bittiğinde mail/notif gelir veya manuel `/products/awaiting_approval` listesine düşer.

### 2.4 — Approval UI'de Karar (2-3 dk)

3 column yan yana görürsün:

```
VARIANT A           VARIANT B            VARIANT C
Conservative        Differentiated       Gift-focused
CTR signal: HIGH    CTR signal: MEDIUM   CTR signal: HIGH

[title 138 char]    [title 139 char]     [title 137 char]
[13 tags]           [13 tags]            [13 tags]
[description 187w]  [description 203w]   [description 195w]
[strategy why]      [strategy why]       [strategy why]
```

**Karar algoritmamız:**

| Durum | Hangi Variant? |
|-------|----------------|
| Yeni mağaza, hangi pattern çalışıyor bilmiyorsun | **B (Differentiated)** — niche tag'lerle deniyorsun |
| Köklü mağaza, niche'in bestseller pattern'i belli | **A (Conservative)** — proven SEO'ya bin |
| Holiday season (Ekim-Aralık) | **C** — otomatik HOLIDAY swap yapıldı |
| Anneler/Sevgililer günü yaklaşıyor | **C** — otomatik swap |
| Premium ürün (14K solid gold) | **A** — otomatik PREMIUM swap |
| Her üç variant da güzel ama birinde tek alan eksik | **Hybrid Edit** — variant A'nın title'ı + B'nin description'ı |
| Hiçbiri tatmin etmiyor | **Reject & Regenerate** — yeni 3 variant gelir |

**Hybrid Edit** çok güçlü: "A'nın title'ını seviyorum ama B'nin tags'i daha niche" → her field için "← Use this from variant X" düğmesi var. Sen istediğin gibi karıştır.

### 2.5 — Approve → Etsy Upload (otomatik, 1-2 dk)

Approve dediğin an:
- Variant DB'ye final olarak yazılır
- Etsy API'ye listing oluşturuldu
- "Human pacing" timer: ardışık upload'lar arasında 1-2 dk gecikme (bot davranışı önlemek için)
- Stats tracking otomatik başlar

`/products/published` listesinde görürsün.

### 2.6 — Günlük Hedef

**10 yeni listing/gün** sürdürülebilir tempo. Yeni başlıyorsan **5 listing/gün** ile başla, ısındıkça artır.

Etsy yeni mağazalar için "warm up" periyodu uyguluyor — ilk 30 günde 100+ listing atmak şüphe çekebilir.

---

## 📊 3. Hangi Metrikleri Takip Etmeli

### 3.1 — Listing-Level Metrikler

**Günlük dashboard'da göreceklerin:**

| Metrik | İyi değer | Kötü değer | Aksiyon |
|--------|-----------|-------------|---------|
| **Views/day** | 10-50 (yeni listing) | <5 | Title problemi — Etsy gösteriyor ama tıklatamıyor |
| **Favorites/views ratio** | %3-8 | <%1 | Photo problemi — fotoğraf çekmiyor |
| **Cart adds/views** | %1-3 | <%0.5 | Description/price problemi |
| **Conversion rate (sales/views)** | %0.5-2 | <%0.2 | Birden fazla şey yanlış olabilir, derin analiz lazım |
| **First sale time** | İlk 7 gün | İlk 14 gün hiçbir sales | Listing'in yeniden değerlendirilmesi gerek |

### 3.2 — Niche-Level Metrikler

Her hafta `/admin/research/<niche>` dashboard'da:

| Metrik | Anlamı | Yorum |
|--------|--------|-------|
| **Bestseller density** | Top 60'tan kaçı bestseller | %15+ = sıcak niche, çok rekabet ama satış var |
| **Avg weekly sales (EHunt)** | Top 10'un ortalama haftalık satışı | 200+ = güçlü niche |
| **Listing yaşı medyan** | Ortalama listing kaç aylık | <12 ay = yeni mağazalar girebiliyor |
| **Tag volume strat. ortalaması** | Mainstream/medium/niche oranı | Birçok mainstream tag varsa → yüksek rekabet |

### 3.3 — Variant Performance (uzun vade)

**`/admin/analytics/variants`** sayfası (Phase 7 sonrası):

```
Last 30 days:
  Variant A picked: 45 times → avg first sale: 6.2 days
  Variant B picked: 30 times → avg first sale: 4.1 days  ← winner!
  Variant C picked: 15 times → avg first sale: 8.5 days
  HYBRID picked:    10 times → avg first sale: 5.0 days
```

Bu data 60-90 gün sonra anlamlı. Patron çıktığında ezbere "her zaman B" diyebilirsin.

### 3.4 — Quality Metrics (her listing'de)

Approval UI bunları gösteriyor:

| Metrik | Hedef | Note |
|--------|-------|------|
| Title length | 137-140 char | Hard rule |
| Tag count | exactly 13 | Hard rule |
| Tag dağılımı | 6/4/3 veya 2/4/7 (variant'a göre) | Variant strategy |
| Description originality | ≥%96 unique | Validator throws altında |
| Cliché count | 0 | Phase 6 cliché filter |
| Forbidden word check | 0 hit | "Stone", "Solid Gold + Plated", etc. |
| Image count | ≥8 | Hard rule |

---

## 🎯 4. Başarı Faktörleri

### 4.1 — En Önemlileri (sırayla)

1. **Carrier Pillar seçimi (40% impact)**
   Yanlış niche → ne strateji yaparsan yap satış az. Performans verisine bakıp **kazanan pillar'larına yatırım yap**.

2. **Title kalitesi (25%)**
   137-140 karakter rule'u her listing'de sıkıca uygulanmalı. İlk 60 karakter niche-spesifik olmalı (Etsy bu kısma daha çok bakıyor).

3. **Tag SEO (20%)**
   Variant B (niche-heavy) çoğu zaman variant A'yı yener çünkü düşük rekabetli niş'te ranking yakalanıyor.

4. **Image kalitesi (10%)**
   8+ fotoğraf, biri mutlaka lifestyle (insanın boynunda görseli). AI image pipeline bunları üretir ama sen approval'da kalitesini onayla.

5. **Description (5%)**
   ≥%96 originality şart. LLM bunu otomatik sağlıyor ama bazen takılıyor.

### 4.2 — Renewal Timing

Etsy'de "renewal" listing'i feed'in başına atar. Bizim sistem otomatik yapıyor:

- **17:00 TR** (15:00 EU) — Avrupa peak shopping
- **21:00 TR** (14:00 EST) — US doğu yakası akşam
- **02:00 TR** (19:00 EST) — US batı yakası akşam
- **05:00 TR** (22:00 EST late shoppers)

**Hangi listing renew edilir?** Otomatik strateji:
- Yeni listing (≤7 gün): her gün renew
- Performing listing (sales var): haftada 2 renew
- Underperforming (0 sales after 14 days): renew'dan çıkar, manuel inceleme

### 4.3 — Quantity Strategy

| Quantity | Ne zaman | Niye |
|----------|---------|------|
| **999** | Bestseller niche, güvendiğin pattern | Etsy "popular" sinyali okuyor, satış kaybı yok |
| **10-300** | Test ediyorsun, niş emin değil | Bitince yeniden ekle, manuel kontrol şansı |
| **1** | **ASLA** | Algoritma sinyali öldürür |

Yeni başlayan listing → 100. 30 gün sonra eğer 5+ satış varsa → 999'a çıkar.

### 4.4 — Renewal Cycle Strategy (Daha Detaylı)

Etsy'de bir listing 4 ay sonra "stale" işaretleniyor. Bizim strateji:

| Yaş | Aksiyon |
|-----|---------|
| 0-7 gün | Her gün renew (warm-up) |
| 7-30 gün | Haftada 3 renew |
| 30-90 gün | Performans bazlı (sales/views >0.5%) → haftada 2 |
| 90-120 gün | Underperforming ise re-list (yeni listing_id ile) |
| 120+ gün | Sales var ise sürdür, yoksa retire |

---

## 🔍 5. Karar Çerçeveleri (Decision Frameworks)

### 5.1 — Listing 7 gün sonra 0 view

```
Sebep: Etsy bu listing'i hiç göstermiyor
Aksiyon:
  1. Title forbidden words check yap
  2. Tag distribution check (8/3/2 mi tam?)
  3. Image alt text dolu mu?
  4. Section assignment doğru mu?
Çözüm: Hepsi OK ise → re-list (yeni listing_id alır, fresh start)
```

### 5.2 — Listing 50+ view ama 0 favorite

```
Sebep: Etsy gösteriyor, görenler ilgilenmiyor
Aksiyon:
  1. İlk fotoğrafa bak — eye-catching mi?
  2. Title'da hook var mı? (e.g. "Personalized", "Unique", "Custom")
  3. Fiyat çok mu yüksek?
Çözüm: Photo değiştir + title tweak (variant değiştir)
```

### 5.3 — 5+ favorite ama 0 cart

```
Sebep: İnsanlar beğeniyor ama satın alma kararı vermiyor
Aksiyon:
  1. Description'da satın alma karar yardımcıları var mı?
     ("Free gift wrap", "Ships from US/EU", "Custom orders welcome")
  2. Fiyat psikolojisi: $32.99 vs $35.00 (.99 trick)
  3. "Only X left in stock" görünüyor mu?
Çözüm: Description revize + price tweak
```

### 5.4 — Cart adds var ama checkout yok

```
Sebep: Son anda vazgeçiyorlar
Aksiyon:
  1. Shipping cost yüksek mi?
  2. Estimated delivery uzun mu?
  3. Returns policy net mi?
Çözüm: Shipping rate ayarla, "Fast shipping" badge etkinleştir
```

### 5.5 — Yeni niş değerlendirme

```
Yeni keyword'ü pillar yapmaya değer mi?

CHECK:
  ✓ Top 10 listing'in avg weekly sales ≥ 50?
  ✓ Listing yaşı medyanı ≤ 18 ay? (eski mağaza tekeli yok mu?)
  ✓ Star Seller ratio %30-70 arası? (çok düşük → niche zayıf, çok yüksek → rekabet imkansız)
  ✓ Tag volume distribution: en az 3 tag <10M (niche fırsatı var mı?)
  ✓ Reksven'de uygun ürün var mı?

5/5 → niş olarak ekle
3-4/5 → test et, 5 listing dene, 30 gün bekle
≤2/5 → vakit kaybetme
```

### 5.6 — Hangi Variant'ı Pick Etmeli

**Karar ağacı:**

```
                  Mevcut mağaza durumun?
                /                       \
           Yeni / az sales           Köklü, satış var
              |                              |
       Mevsim ne?                  Bu niş'te performans?
       /        \                      /            \
   Holiday    Normal              Güçlü            Zayıf
   season    season                |                |
      |        |                Variant A      Variant B
   Variant C  Variant B       (proven SEO)   (yeniden dene)
   (auto-     (niche test)
   swapped)
```

### 5.7 — Phase 2 ne kadar listing scrape etmeli

| Senaryo | Phase 2 listing sayısı |
|---------|-----------------------|
| İlk research, niş tanımıyor | 30-40 |
| Hafta refresh | 30-50 |
| Tam yenileme (3 ay sonra) | 50-70 |
| Niche pivot test | 50 + farklı keyword'lerin top 10'u |

100+ asla. Sebepleri: (a) güvenlik, (b) çok zaman, (c) marginal info gain düşük.

---

## ⚠️ 6. Yaygın Hatalar (KAÇIN!)

| Hata | Sonuç | Önlem |
|------|-------|-------|
| Mağaza hesabıyla aynı browser profile'da scraping | Etsy bot algı, mağaza uyarısı/suspension | Ayrı Research profile |
| Quantity = 1 | Etsy "out of stock" algılar, ranking düşer | Min 10, ideal 100-999 |
| Approval UI'i bypass etmek (otomatik publish) | Validator atlanır, low quality listing | UI MUTLAKA |
| Aynı tag'leri 13 farklı listing'de tekrar | Cannibalization, kendi listing'lerin çatışır | Variant B kullan |
| Description'da rakipten kopya cümle | Etsy duplicate content cezası | originality ≥%96 zorunlu |
| Tag'lerde aynı kelime 3+ kez (e.g. 5 tag'de "necklace") | Tag distribution validator throws | LLM bunu önler ama elle değiştirme |
| Phase 2 büyük batch (100+) | Etsy bot algı + EHunt quota tükenir | 30-50 max |
| Sales sinyali olmadan refresh refresh refresh | Token + EHunt quota israfı | Haftada 1 refresh yeter |
| Forbidden word ("Stone" alone) title'da | Etsy listing reject olabilir | Validator zaten yakalar |
| AI image'i "real product" alt text'iyle | Yanıltıcı pazarlama, müşteri şikayeti | Lifestyle/concept alt text |

---

## 🚨 7. Acil Durum Senaryoları

### 7.1 — Etsy hesabı uyarı aldı

1. **Hemen extension'ı durdur** (popup → "Stop all jobs")
2. Etsy'nin uyarı mesajını oku — hangi policy?
3. Eğer "automated activity detected" ise:
   - Research profile ile mağaza hesabını **tamamen ayrıştır**
   - 48 saat extension'ı kullanma
   - Yeniden başlarken volume %50 düşür

### 7.2 — Listing reject edildi

Etsy bir listing'i reject ederse:
- Forbidden keyword olabilir (e.g. "Diamond" derken brass kullanıyorsun)
- IP violation (telif li kelime, e.g. "Disney")
- Image policy (gore, NSFW, vs)

Approval UI'da yeniden değerlendir, problemli alanı düzelt, **yeni listing_id ile** yeniden gönder (eskiyi düzeltme — Etsy hatırlıyor).

### 7.3 — EHunt quota tükendi

EHunt aboneliği aylık limit veriyor. Bittiğinde:
- Phase 1 verisi gelmez (sales/favorites missing)
- Phase 2'de tag'ler gelmez

Fallback: Title-derived n-gram tag analyzer otomatik devreye girer (Step 3.6'da). Kalite biraz düşer ama sistem çalışmaya devam eder.

### 7.4 — Postgres container down

```bash
docker compose ps                # status check
docker compose logs postgres     # ne oldu bak
docker compose restart postgres  # restart
docker compose up -d             # yeniden ayağa kaldır
```

Veri persistent volume'da (`etsy_taki_pgdata`), kaybolmaz. Eğer **gerçekten** silmek istersen:
```bash
docker compose down -v   # volume dahil sil (NUCLEAR)
```

### 7.5 — Anthropic API key suspend / fatura sorunu

LLM çağrıları başarısız olur. Backend exception loglar, listing CONTENT_GENERATING state'inde kalır.

Çözüm:
1. anthropic console'a git, sebep ne?
2. Key yenile / fatura öde
3. Backend `/admin/jobs` → failed listing'leri "Retry"

---

## 📅 8. Aylık Review Şablonu

Ay sonu (~1 saat):

```markdown
## [Ay] [Yıl] — Review

### Top 5 best-selling listings
1. SKU-XXXX | $X revenue | Variant Y | Pillar Z
2. ...

### Bottom 5 (retire candidates)
1. SKU-XXXX | 0 sales 30 days | Variant Y

### Variant winrate
A: %XX | B: %XX | C: %XX | Hybrid: %XX

### Pillar performance
Cross:        XX listings → $X revenue → $X/listing
Birthstone:   XX listings → $X revenue → $X/listing
Name:         XX listings → $X revenue → $X/listing
...

### Decisions
[ ] Pillar X'i artır (XX → XX listing/ay)
[ ] Pillar Y'yi kıs (düşük conversion)
[ ] Keyword pool'a ekle: [...]
[ ] Variant Z stratejisini değiştir: [...]

### Aksiyon
[ ] Niş Phase 2 refresh
[ ] Bottom 5'i retire et
[ ] Top 5 pattern'ini analiz et, yeni listing template'i çıkar
```

---

## 🎓 9. Öğrenme Eğrisi

| Hafta | Beklenti |
|-------|----------|
| 1. hafta | Sistemi öğreniyorsun. 3-5 listing/gün, hepsini elle approve. Hatalar olacak. |
| 2-3. hafta | Approval refleks kazanırsın. 7-8 listing/gün. İlk sales gelir. |
| 4. hafta | Variant pattern'ini anlamaya başlarsın. Aylık review yap. |
| 2. ay | 10-12 listing/gün. Hangi pillar kazanıyor net olur. |
| 3. ay | Aylık analytics anlamlı çıkar. Strateji rafine edersin. |
| 6. ay | "Senin tarzın" oluşur. Sistem senin için optimize edilmiştir. |

---

## 🔧 10. Sık Kullanılan Komutlar

### Backend
```bash
# Başlat
docker compose up -d
source .venv/bin/activate
uvicorn src.main:app --reload

# Logları gör
tail -f logs/app.log

# Database direkt sorgula
psql postgresql://etsy:etsy_local_dev@localhost:5432/etsy_taki
\dt              # tabloları listele
SELECT count(*) FROM products WHERE status='published';

# Migration yap (model değiştirdikten sonra)
alembic revision --autogenerate -m "açıklama"
alembic upgrade head

# Test çalıştır
pytest tests/
pytest tests/test_validators.py -v   # tek dosya
```

### Extension
```
Phase 1 başlat: extension popup → "Start Phase 1"
Phase 2 başlat: review tab → seç → "Start Phase 2"
CSV indir:      review tab → "Export CSV"
Recon page:     popup → "Recon current tab"
Stop all:       popup → "Stop"
```

### URL'ler
```
Backend admin:       localhost:8000/admin
Research dashboard:  localhost:8000/admin/research
Approval queue:      localhost:8000/products/awaiting_approval
Published:           localhost:8000/products/published
Analytics:           localhost:8000/admin/analytics
Logs:                localhost:8000/admin/jobs
```

---

## 📞 11. Yardım

Bir sorun olursa veya emin değilsen:
1. `logs/app.log` — son 100 satır
2. Browser console — extension logları
3. `docker compose logs postgres` — DB sorunları
4. `/admin/jobs` — failed job listesi

---

## 🎯 Sonuç

Bu sistemin başarısı **3 şeye** bağlı:
1. **Doğru carrier pillar seçimi** — yanlış niş başarısızlık
2. **Tutarlı günlük üretim** — günde 5-10 listing, 60 gün
3. **Aylık analytics tabanlı düzeltme** — data ne diyorsa onu yap

Senin işin **yaratıcılık değil disiplin**. Sistem zaten %95 yaratıcılık yapıyor (variant generation, image generation, validation). Sen sadece:
- Reksven'den iyi ürün seç
- Manual input dikkatli doldur
- Approval'da düşünerek karar ver

Geri kalanı sistemin işi.

İyi şanslar 🚀
