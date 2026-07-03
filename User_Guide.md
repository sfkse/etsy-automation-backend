# Etsy Takı Otomasyon — Kullanıcı Rehberi

**Hedef kitle:** Sen. Bu doc'u backend hazır olduğunda günlük operasyonda referans alacaksın.

**Toplam okuma süresi:** ~15 dakika. Sonra bookmark'la.

---

## 📋 0. Hızlı Referans (One-pager)

### Günlük rutin (~45 dk)
```
1. Sabah:   sistemi başlat (docker + uvicorn)        2 dk
2. Sabah:   yeni ürün üret (10 ürün hedef)          25 dk
            → Rexven ürün seç
            → [YENİ] Phase 4 Sourcing analizi         3 dk
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
  • [YENİ] Phase 4 — haftalık yüksek potansiyelli 5 Rexven ürününü analiz et
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
6. Etsy Research extension v2.6'ı bu profile'a yükle (`chrome://extensions` → Load unpacked)
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

## 🔍 2A. Phase 4 — Sourcing Intelligence (Ürün Seçim Rehberi)

> **Ne işe yarar:** Elinde bir Rexven ürünü var ama hangi Etsy keyword'ünde çalışır bilmiyorsun. Phase 4 bunu sistematik hale getiriyor: ürün fotoğrafını AI ile analiz et, Etsy'de rakip verisi topla, fırsat skoru al.
>
> **Çıktı:** 5 adet sıralı Etsy keyword önerisi + her birinin fırsat skoru + rakip pazar verisi

---

### 2A.1 — Nasıl Çalışır (3 Katman)

```
LAYER A — Vision LLM (3-5 saniye)
  Rexven ürün fotoğrafı → Claude Sonnet vision
  → ~15 keyword adayı (niche / medium / broad)
  → Ürünün görsel özelliklerini otomatik algılar
    (form, material, style, theme, recipient, occasion)

LAYER B — Fırsat Puanlama
  Extension tarayıcıda Etsy'yi scrape eder (403 yok, gerçek browser)
  Her aday için top-20 rakip verisini puanlar:
  → new_shop_share   (yeni mağaza sıraya girebilir mi?)
  → price_alignment  (senin fiyat bandın uyuyor mu?)
  → market_activity  (keyword hâlâ canlı mı? — en güvenilir sinyal)
  → competition      (kaç rakip var?)
  → diversity        (tek shop dominasyonu var mı?)
  → Sonuç: opportunity_score (0-100 arası)

LAYER C — Görsel Benzerlik (opsiyonel, varsa daha zengin)
  CLIP embedding ile veritabanındaki benzer listing'leri bulur
  → Gerçek sıralama tahmini: "~rank 23, page 1"
  → Layer A'nın kaçırdığı keyword'leri keşfeder
```

---

### 2A.2 — Tam Kullanım Akışı (Adım Adım)

> **Önemli:** Extension popup penceresi Phase 1 tab'ları açıldığında kapanır. Bu normal — akış Review sayfasından devam eder.

```
ADIM 1 — Analizi başlat
  members.rexven.com/product-details/XXXX → sağ altta turuncu buton
  VEYA popup → Sourcing tab → "Analyze Product"
  → Layer A çalışır (~5 sn)
  → Popup kapanabilir — sorun değil, analysis_id storage'a kaydedildi

ADIM 2 — Phase 1 browser tab'ları izle
  Extension ~15 Etsy search tab'ı açar ve kapar
  Review sayfası (popup → Research → "Review candidates →") açık kalır
  Progress: Etsy Research popup'ta görünür

ADIM 3 — Review sayfasında "Send to Sourcing Analysis" tıkla
  Phase 1 tamamlandığında review sayfasında:
  [🔍 Send to Sourcing Analysis] butonu → tıkla
  → Backend'e listing verisi gönderilir
  → Layer B scoring otomatik başlar (~30 sn)
  → Keyword kartları review sayfasında görünür

ADIM 4 — Keyword seç
  Review sayfasında sonuçlar:
  #1 birthstone necklace   [48/100]   14/20 active
  #2 dainty necklace       [48/100]   13/20 active
  ...
  → [💾 Use for Generate Content] butonu → seçtiğin keyword'ü storage'a yazar

ADIM 5 — Ürün oluştur ve generate et
  Backend /products/new → ürünü oluştur
  Generate Content → selected_keyword_score_id otomatik uygulanır
```

---

### 2A.3 — Popup Yeniden Açıldığında

Popup kapandıktan sonra yeniden açarsan:
- **Analiz tamamsa:** Sourcing tab otomatik açılır, sonuçlar yüklenir
- **Phase 1 hâlâ çalışıyorsa:** Sourcing tab açılır, durum mesajı gösterilir
- **Hiçbir şey yoksa:** Normal Research tab'da açılır

---

### 2A.4 — Review Sayfasındaki Sourcing Sonuçları

```
┌─────────────────────────────────────────────────────────┐
│ 🔍 Sourcing Analysis Results                            │
│ form: pendant  style: dainty  theme: birthstone  ...    │
│                                                         │
│  #1  birthstone necklace              [48/100]          │
│      avg $0.00 · 15 shops · 14/20 active                │
│      [💾 Use for Generate Content]                       │
│                                                         │
│  #2  dainty necklace                  [48/100]          │
│      avg $0.00 · 13 shops · 13/20 active                │
│      [💾 Use for Generate Content]                       │
└─────────────────────────────────────────────────────────┘
```

| Alan | Ne Anlama Gelir |
|------|----------------|
| **#1** | Fırsat sıralaması (1 = en iyi) |
| **48/100** | opportunity_score — 60+ iyi, 75+ çok iyi |
| **avg $X.XX** | Top-20 rakibin ortalama fiyatı (Phase 2 data olmadan $0.00 gösterir) |
| **15 shops** | Top-20'de kaç farklı shop var — düşükse 1 shop domine ediyor |
| **14/20 active** | EHunt'tan: hâlâ satış yapan listing oranı — **en güvenilir sinyal** |

> **Neden avg $0.00?** Phase 1 search kartları her zaman `price_cents` içermiyor. Phase 2 scrape'i çalıştırdıkça bu dolar. Şimdilik `X/20 active` oranına odaklan.

---

### 2A.5 — Sub-Skorları Anlamak

Her keyword için 5 sub-skor döner (API cevabında `sub_scores`):

| Sub-Skor | İyi (>0.6) | Kötü (<0.3) | Ağırlık |
|----------|------------|-------------|---------|
| **new_shop_opportunity** | Top-20'de yeni shoplar sıraya girmiş | Sadece eski shoplar | %30 |
| **price_alignment** | Senin fiyatın rakiplerle uyuşuyor | Çok ucuz veya pahalısın | %25 |
| **market_activity** | Top-20'nin çoğu hâlâ satıyor | Ölü keyword | %25 |
| **competition_inverted** | Arama sonucu az | Milyonlarca rakip | %10 |
| **diversity** | Farklı shoplar sıralanmış | 1 shop top-20'yi domine ediyor | %10 |

> **Pratik kural şu an:** `market_activity` (X/20 active) en güvenilir sinyal — diğerleri Phase 2 data biriktikçe anlam kazanır.

---

### 2A.6 — Keyword Seçtikten Sonra Ne Yapacaksın

1. Review sayfasında **[💾 Use for Generate Content]** tıkla → `keyword_score_id` storage'a kaydedildi
2. Backend'de `/products/new` → ürünü oluştur
3. **Generate Content** sayfasında `selected_keyword_score_id` form alanına ID'yi gir
   → LLM prompt'u bu keyword'ü birincil hedef olarak kullanır, title'ın ilk 60 karakterine koyar
4. Approve → Publish

---

### 2A.7 — Sourcing Analizini Ne Zaman Yapmalısın

| Durum | Sourcing Analizi Yap mı? |
|-------|--------------------------|
| Yeni Rexven ürün, keyword bilmiyorsun | **Mutlaka** — zaten bunun için var |
| Bildik niş'te rutin ürün (cross necklace #47) | Opsiyonel — zaten hangi keyword işe yaradığını biliyorsun |
| Yeni bir kategori deniyorsun (ilk kez kedi küpesi) | **Mutlaka** — yabancı toprak |
| Mevsimsel ürün (noel kolyesi, Anneler günü) | **Evet** — seasonal keyword fırsatı araştır |
| Rakibinin iyi sattığı ürünü kopyalıyorsun | Opsiyonel — rakipten zaten keyword öğrenebilirsin |

---

### 2A.8 — Layer C (CLIP) Aktifleştirme

Layer C yalnızca `competitor_listings` tablosundaki listing'lerin CLIP embedding'leri varsa çalışır. İlk kez aktifleştirmek için:

```bash
# Tüm mevcut listing'lerin embedding'lerini hesapla (~2 saat, CPU)
cd backend
python -m src.sourcing.backfill_embeddings

# Sadece ilk 1000 ile test et
python -m src.sourcing.backfill_embeddings --max-listings 1000
```

> **Ne zaman çalıştırmalısın:** İlk `backfill`'i çalıştırmak için en az **5.000 listing** toplanmış olmalı. Daha azında görsel benzerlik anlamlı çıkmaz. Henüz yoksa Layer A + B yeterli.

---

### 2A.9 — Doğrudan API ile Kullanım

```bash
# Sadece Layer A (keyword önerileri, hızlı)
curl -X POST http://localhost:8000/sourcing/suggest-keywords \
  -F "image=@/path/to/product.jpg"

# Layer B+C'yi tetikle (extension Phase 1 verisi ingested olduktan sonra)
curl -X POST http://localhost:8000/sourcing/{analysis_id}/ingest-and-score \
  -H "Content-Type: application/json" \
  -d '{"cards": []}'

# Sonuç sorgu (polling)
curl http://localhost:8000/sourcing/{analysis_id}

# Son 20 analiz listesi
curl http://localhost:8000/sourcing
```

---

### 2A.10 — Maliyet

| İşlem | Maliyet |
|-------|---------|
| Layer A (1 ürün analizi) | ~$0.02-0.03 (Claude Sonnet vision) |
| Layer B (extension browser scraping) | $0 |
| Layer C (CLIP embedding) | $0 (local model) |
| **100 ürün/ay** | **~$2-3** |

Vision çağrısı cache'lenir — aynı ürünü tekrar analiz edersen Layer A maliyeti tekrarlanmaz.

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

### 5.6 — Phase 4 Sourcing — Hangi keyword'ü seçmeliyim?

```
Sourcing analizi döndü, 5 keyword var. Hangisini seçeyim?

ÖNCE BU 3 KURALYA BAK:
  ✓ new_shop_opportunity > 0.50?  → yeni mağaza sıraya girebiliyor
  ✓ market_activity > 0.60?       → keyword canlı, satış var
  ✓ estimated_rank ≤ 48?          → page 1'e girebilirsin

3/3 → #1 sıradaki keyword'ü al
2/3 → #1 var mı, ona bak; yoksa #2'ye geç
1/3 → tüm adaylar riskli; farklı ürün dene veya keyword üret

BONUS: price_alignment > 0.70 ise fiyatlamada rahat olacaksın.
       diversity < 0.40 ise 1 shop domine ediyor — dikkat.
```

### 5.7 — Hangi Variant'ı Pick Etmeli

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

### 5.8 — Phase 2 ne kadar listing scrape etmeli

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
| Sourcing analizini Etsy mağaza hesabı profiliyle yapmak | Bot algı riski (mini-Phase1 Etsy scraper kullanıyor) | Research profile kullan |
| Layer B sonucu beklenmeden keyword'ü seçmek | Sadece LLM tahmini var, pazar verisi yok | Status COMPLETED olana kadar bekle |
| selected_keyword_score_id olmadan generate etmek | LLM keyword'ü bilmeden üretir, title'a yerleştirmez | ID'yi mutlaka form'a ekle |
| backfill'i 5000'den az listing varken çalıştırmak | Görsel benzerlik anlamsız sonuç verir | Önce Phase 1+2'yi doldur |

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
Sourcing analiz: Rexven sayfasında turuncu buton → OR → popup → "Sourcing" tab → Analyze Product
```

### URL'ler
```
Backend admin:       localhost:8000/admin
Research dashboard:  localhost:8000/admin/research
Approval queue:      localhost:8000/products/awaiting_approval
Published:           localhost:8000/products/published
Analytics:           localhost:8000/admin/analytics
Logs:                localhost:8000/admin/jobs

--- Phase 4 Sourcing ---
Sourcing listesi:    localhost:8000/sourcing
Analiz başlat:       POST localhost:8000/sourcing/analyze
Sadece keywords:     POST localhost:8000/sourcing/suggest-keywords
Analiz sonucu:       GET  localhost:8000/sourcing/{analysis_id}
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
