# AI Sanal Dolap — Devir Dokümanı

> Bu doküman projeyi başka bir sohbette kaldığı yerden sürdürmek için yazıldı.
> **Anahtarlar burada YOK** — `.env` dosyasında duruyorlar ve git'e girmiyorlar.
> Durumu görmek için: `python cli.py doctor` (anahtarları maskeli gösterir).

**Konum:** `C:/Users/egear/OneDrive/Masaüstü/virtual-wardrobe`
**Durum:** Faz 0 ✅ · Faz 1 ✅ · Faz 2 ✅ · Faz 4 ✅ · Faz 6 ✅ · Faz 3 ertelendi
**Bu turda:** §28 çoklu manken · §30 bölge kapısı · §31 kırp→hizala · §32 kişi
maskesi · §36 şablon önseli kapatıldı · §38 tek kıyafette ham çıktı ·
§40+43 zemin seçimi · **§44 KÖR NOKTA ÇÖZÜLDÜ (yeşil çıkarım base'i)**
**Testler:** 365 geçiyor (`pytest`, ~65 sn, API çağırmaz)
**Dolap:** 12 kıyafet
**Mankenler:** `base` (#1, 12 katman, **aktif**) · `manken 2` (#139, 3 katman —
  #10 sarı, #14 lacivert, #16 chino; yeşil çıkarım base'i var).
  *(`Stüdyo` mankeni bu turda silindi — 0 katmanı vardı, kayıp yok.)*
**Sağlayıcı:** FASHN doğrudan API, `tryon-max` (varsayılan). `FASHN_API_KEY` gerekli.
**Kredi:** ~48 kaldı (100 alındı). Bu turda 22 harcandı: §31 (2) · §32.3 ölçümü (4) ·
  §34.5 (4) · §44 renk deneyi (6) · §44.9 slot deneyi (6)
**Sunucu:** `Dolabi Ac.bat` çift tıkla (ya da `python cli.py web`) → http://127.0.0.1:8000

> ### ⚠ SIRADAKİ İŞ: §45'e bak
> §44 bu turun en önemli sonucu — kör nokta kapandı. Açık sorular, ölçülmemiş
> hipotezler ve sıradaki adaylar §45'te; mimarinin özeti §2 ve §45.1'de.

---

## 1. Proje nedir

Kullanıcı kendi kıyafetlerini fotoğraflayıp dijital dolabına ekliyor; sonra bu
kıyafetleri bir manken üzerinde **manuel giydirip** kombin deneyebiliyor, ayrıca
AI'dan öneri alabiliyor.

```
[1] Fotoğraf çek ──► [2] Dolaba kaydet ──► [3] Mankene giydir ──► [4] Kombin
     (kullanıcı)      ✅ FAZ 0             ✅ FAZ 1              ✅ FAZ 2
```

---

## 2. En kritik mimari karar

**Her kombinde VTON çalıştırılamaz.** Kullanıcı manuel deneme yaparken 20-30
kombin dener; her tıklamada difüzyon çalıştırmak 15-40 sn bekleme + her tıklamada
para demek. Kullanılamaz.

Çözüm — **katmanı bir kez üret, sonsuz kez birleştir:**

```
YÜKLEME ANINDA (kıyafet başına 1 kez):
  fotoğraf → arka plan temizle → VTON(base_manken, kıyafet)
           → farkı al → şeffaf PNG katmanı kaydet

GİYDİRME ANINDA (her tıklamada):
  katmanları z-sırasına göre bindir → anında (<50ms), bedava
```

- **Maliyet:** 100 kıyafet × ~$0.075 = tek seferlik ~$7.50. Sonra sınırsız kombin.
- Tüm katmanlar aynı manken/poz/çözünürlükten üretildiği için piksel piksel hizalı.

### Katmanı segmentasyonla değil FARKLA çıkarıyoruz

Manken sabit olduğuna göre, giydirme sonrası **değişen pikseller kıyafetin ta
kendisidir.** Ayrı segmentasyon modeli gerekmiyor.

Ham fark yetmiyor, altı temizlik adımı şart (hepsi ölçümle gerekçelendirildi):

| Adım | Neden |
|---|---|
| Açma (aşındır→genişlet, **eşit çekirdek**) | Difüzyon mankenin geri kalanını da milimetrik oynatıyor → serpinti. Çekirdekler eşit olmazsa siluet sessizce şişer (§6.1 #10) |
| Kapama (genişlet→aşındır, **eşit çekirdek**) | Kıyafet rengi tene yakınsa fark zayıf → katmanda delik |
| 1 px genişletme | Fark eşiği kıyafetin yumuşak kenarında aşılamıyor; genişletmezsek kenardan base sızıyor |
| En büyük bağlı bileşen | VTON tüm görüntüyü yeniden üretiyor; bir tişört katmanının %5'i bacaktaydı |
| Delik doldurma (+ **alfayı da opak yap**) | Silüet içindeki her boşluk tanım gereği hatadır. Alfa güncellenmezse delik dolar ama saydam kalır (§6.1 #11) |
| Base sızıntısını sil | Base'in kıyafeti komşu bölgede yeniden çizilip katmana giriyor (§6.1 #15) |
| Kontur pürüzsüzleştirme | Silmenin ve ham eşiğin bıraktığı 1-2 px'lik çentikler; kapatılmazsa siluet boyunca zemin sızar |
| Kenar yumuşatma (anti-alias) | Alfa 0→255 sıçrarsa kenar merdiven basamağı gibi görünür (§6.1 #14) |
| Kenar rengi tazeleme | En dış piksel sırası kıyafetle arkasının karışımı → bindirmede renkli halka |

---

## 3. Kategori tablosu = katman sırası + çakışma kuralı

`config.CATEGORIES` sadece etiket listesi değil:

| Kategori | `z` (çizim sırası) | `slots` (kapladığı bölge) |
|---|---|---|
| Ayakkabı | 10 | `ayak` |
| Alt giyim | 20 | `alt` |
| Elbise | 25 | `ust`, `alt` |
| Üst giyim | 30 | `ust` |
| Dış giyim | 40 | `dis` |
| Aksesuar | 50 | `aksesuar` |

`z` çizim sırasını, `slots` "hangi ikisi aynı anda giyilemez"i belirliyor.
Elbise hem `ust` hem `alt` kapladığı için tişört seçilince otomatik düşer.
**Faz 2'nin giydirme mantığı tamamen bu tabloya dayanacak.**

---

## 4. Kurulum ve komutlar

```bash
pip install -r requirements.txt
pip install "rembg[cpu]"      # sade `pip install rembg` MOTORU KURMUYOR
```

`.env` (git'e girmez, `python cli.py doctor` ile doğrula):
```
FAL_KEY=...              # sanal deneme (fal.ai)
ANTHROPIC_API_KEY=...    # kıyafet öznitelik çıkarımı
```

| Komut | Ne yapar |
|---|---|
| `python cli.py doctor` | Kurulum + anahtar kontrolü (anahtarı maskeler) |
| `python cli.py add <foto> [--cutout auto\|rembg\|flood]` | Kıyafet ekler |
| `python cli.py add-folder <klasör>` | Toplu ekler |
| `python cli.py list` / `show <id>` / `rm <id>` / `stats` | Dolap yönetimi |
| `python cli.py mannequin [--from-photo X \| --style person\|mannequin \| --placeholder]` | Aktif mankenin fotoğrafını değiştirir (**o mankenin katmanlarını geçersizler**) |
| `python cli.py mannequin --list` | Mankenleri listeler (▶ = aktif, katman sayısıyla) |
| `python cli.py mannequin --from-photo X --name "Yaz"` | **YENİ** manken ekler (bedava, eskiler korunur) |
| `python cli.py mannequin --use <id>` | Aktif mankeni değiştirir (**bedava, hiçbir şey silmez**) |
| `python cli.py mannequin --rm <id>` | Mankeni + katman/renderlarını siler (**GERİ ALINAMAZ**) |
| `python cli.py build-layers [--id N] [--force]` | Katman üretir (**ÜCRETLİ**) |
| `python cli.py build-layers --reextract` | Saklanmış ham çıktıdan yeniden çıkarır (**BEDAVA**) |
| `python cli.py preview 8 6 -o kombin.png` | Katmanları birleştirir |
| `python cli.py web` | **Giydirme arayüzünü başlat** → http://127.0.0.1:8000 |
| `python cli.py layer-ab <id>` | Katman mimarisi model karşılaştırması (**ÜCRETLİ**, §24.2) |
| `python cli.py tryon-ab <id> --seed 42` | VTON ayar karşılaştırması (**ÜCRETLİ**, §20.1) |
| `python cli.py render 10 7` | Kombini zincirleme giydir (**ÜCRETLİ**, önbellekli) |
| `python cli.py web --host 0.0.0.0` | Telefondan eriş → http://192.168.1.108:8000 |
| `pytest` | 174 test |

> `--reextract` önemli: çıkarım parametrelerini ayarlarken API'ye tekrar ödeme
> yapmamak için ham VTON çıktıları saklanıyor.

---

## 5. Sağlayıcı ve API

**fal.ai → FASHN v1.6** (`fal-ai/fashn/tryon/v1.6`). Şema fal'ın OpenAPI'sinden
doğrulandı, tahmin değil:

- Zorunlu: `model_image`, `garment_image`
- `category`: `tops` | `bottoms` | `one-pieces` — **ayakkabı ve aksesuar YOK**
- `garment_photo_type`: `flat-lay` ← cutout hattımızın ürettiği tam olarak bu
- `mode`: `quality` kullanılıyor (katman tek seferlik, kalitede cimrilik yanlış)

`wardrobe/vton.py` sağlayıcı-bağımsız: `fal` ve `mock` adaptörleri tek
`try_on(model, garment, category)` arayüzü arkasında. Değiştirmek tek satır
(`--provider` veya `VTON_PROVIDER`). Model A/B karşılaştırması kod değişikliği
gerektirmiyor.

Öznitelik çıkarımı: **Claude `claude-opus-5`**, `output_config.format` ile JSON
şeması dayatılıyor (regex ayrıştırma yok), `effort: "low"` (basit çıkarım görevi).
Görsel 1024px'e küçültülüyor — token maliyetini birkaç kat düşürüyor.

---

## 6. Ölçülmüş bulgular

Bu bölüm portföy anlatısının çekirdeği: hepsi tahmin değil, ölçüm.

### 6.1 Bulunan ve düzeltilen buglar

| # | Bug | Nasıl bulundu | Etki |
|---|---|---|---|
| 1 | **`dominant_color` arka planı okuyordu** | Test: kırmızı görsel "beyaz" döndü | Her kıyafetin rengi yanlış |
| 2 | **UUID dosya adı ipucunu yutuyordu** | Test: her kıyafet "üst" oldu | Yedek yolda kategori hep yanlış |
| 3 | **`int16` taşması ×3 + `uint8` ×1** | `RuntimeWarning: invalid value in sqrt` | 255²=65025 taşıyor → NaN → maske sessizce boşalıyor, üstelik **en yüksek kontrastlı** (ayırt edilmesi en kolay) durumda |
| 4 | **`rembg` yarım kurulumu tüm CLI'yı öldürüyordu** | `cli.py doctor` çalışmadı | `SystemExit` `BaseException`'dan türüyor, `except Exception` yakalamıyor |
| 5 | **Manken oranı bozuluyordu** | Test: 3:4 fotoğraf 2:3'e sıkışıyor | Kullanıcı kendini ince/uzun görüyor, tüm katmanlar o orana göre |
| 6 | **Manken değişince katmanlar geçersiz olmuyordu** | Test | Eski katman yeni mankende kayıyor, sessizce |
| 7 | **Katmanın %5'i bacak bölgesindeydi** | Ölçüm: 4.403 opak piksel, alfa 255 | Faz 2'de tişört (z=30) şortu (z=20) delerdi |
| 8 | **Testler GERÇEK veriyi eziyordu** | Manken çubuk adama dönmüştü | `conftest`'te `MANNEQUIN_DIR`/`LAYER_DIR` izole değildi → iki tur boyunca **bozuk veriyle ölçüm yaptım ve yanlış sonuç çıkardım** |
| 9 | **Ücretlendirilen çıktı çöpe gidiyordu** | 3 çağrı para yakıp elde hiçbir şey bırakmadı | İnference `fal.run`'da çalışıp ücretlenir, sonuç AYRI bir CDN'den (`cdn.fashn.ai`) indirilir. DNS o CDN'i çözemeyince indirme patlıyor, ham çıktı kaydedilmeden `except` bloğuna düşülüyordu — **para gitti, dosya yok** |
| 10 | **Açma/kapama silueti 2 px şişiriyordu** | Kombinde etek ucunda koyu çizgi; ölçüm: palete uzaklık içeride 18.9, en dış 1 px'te 88.3 | `MinFilter(3)` 1 px aşındırır, `MaxFilter(5)` 2 px genişletir — "açma" ve "kapama" isimleri doğru, aritmetiği yanlış. Her çift net +1 px, toplam +2 px. Fazladan piksel sırası kıyafet değil, **kıyafetle arkasının karışımı** |
| 15 | **Sızıntı filtresinin SIRASI** | Silme→tırtıklı kenar; boyama→kesik kesik bant | Base sızıntısını silmek bel bandını temizliyor ama kenarda çentik açıyor; boyamak kenarı koruyor ama toleransın dışındaki pikselleri katmanda bırakıp kesik bant yapıyor. Çözüm ikisini yarıştırmak değil, **silmeyi kontur pürüzsüzleştirmesinin ÖNÜNE koymak** — pürüzsüzleştirme silmenin açtığı çentikleri kapatıyor. Ölçüldü: kombinde kalan mavi 169 → **11** piksel |
| 14 | **Kenarlarda anti-alias yoktu** | Kullanıcı büyütmede merdiven basamağı gördü | Alfa `keep` ile sert kırpılıyordu: 0'dan ~129'a bir anda sıçrıyor, ara değer yoktu. Ölçüm: yarı saydam piksel sayısı **0**. Kontur pürüzsüzleştirme + yumuşatma sonrası ~15.000 |
| 13 | **Bug #8 aynen tekrarladı** | Yeni test gerçek `base_display.png`'yi sildi | `DISPLAY_BASE = MANNEQUIN_DIR / ...` modül yüklenirken hesaplanıyor; `conftest` dizini `tmp_path`'e yönlendirince sabit hâlâ GERÇEK klasörü gösteriyordu. Yol artık `display_base_path()` ile çağrı anında çözülüyor. **Ders: türetilmiş yolları sabit yapma** |
| 12 | **Filtre sırası yanlıştı** | Sızıntı filtresi hiçbir şey değiştirmedi | Filtre bel bandını siliyor, hemen ardından `fill_holes` o bandı "kıyafetin içinde boşluk" sanıp geri dolduruyordu. Doğru yer: delik doldurmadan SONRA |
| 11 | **Doldurulan delik saydam kalıyordu** | #10 düzeltilince test kırıldı | `fill_holes` "burası kıyafetin içi" diyor ama alfa bulanık maskeden okunuyordu; maskede orada delik olduğu için değer ~0. Delik doldurma çalışıyor, sonucu alfaya yansımıyordu. **Bug #10 bunu kazara örtüyordu** (iki ardışık `MaxFilter(5)` delikleri zaten kapatıyordu) |

**#14-15 dersi:** iki ayrı çözümü yarıştırmak yerine sıralarını düzeltmek. Silme ve pürüzsüzleştirme tek başlarına birer kusur üretiyordu; doğru sırada art arda gelince ikisi de yok oldu.

**#8 ve #13 aynı ders, iki kez:** izolasyon eksikse ölçümlerine güvenemezsin — ve modül seviyesinde hesaplanan her türetilmiş yol o izolasyonu delen bir kapıdır.

**#8 en önemli ders:** test izolasyonu eksikse ölçümlerine güvenemezsin. O hata
hiçbir testi kırmadı, sessizce yanlış veri üretti. Artık `conftest.isolated_env`
DB + yükleme + manken + katman dizinlerini `tmp_path`'e yönlendiriyor ve
testlerden önce/sonra `base.png` hash'i birebir aynı kalıyor (kanıtlandı).

**#9 için kalıcı çözüm:** ücretli çağrıdan **önce** indirme yolu doğrulanıyor
(`vton.require_media_host`). Sonucu indiremeyeceksek istek hiç gönderilmiyor.
İki incelik ölçümle öğrenildi:

- Sonuç sunucusu **tahmin edilemez.** İlk yazdığım kontrol `fal.media`'ya
  bakıyordu ("fal kullanıyoruz, fal'ın CDN'idir"). Kontrol geçti, çağrı gitti,
  indirme yine patladı — çünkü FASHN sonucu `cdn.fashn.ai`'dan veriyor.
  `RESULT_HOSTS` tablosundaki her alan adı artık **gözlenmiş** bir sonuç
  URL'sinden geliyor, varsayımdan değil.
- Kontrol uç nokta başına ayrı; tek bir "hepsi çözülsün" listesi, ilgisiz bir
  CDN düştüğünde çalışan hattı gereksiz kilitlerdi.

İndirme yine de patlarsa hata mesajı **sonucun URL'sini taşıyor** ve o URL
`layers.error` sütununa yazılıyor. Çıktı fal'da duruyor; elle indirip
`data/layers/g<id>_m<mid>_raw.png` olarak kaydedip `--reextract` çalıştırmak
parayı kurtarıyor — bu oturumda bir çağrı böyle geri alındı.

**#10-11 en öğretici çift:** bir bug diğerini gizliyordu. Siluet şişmesi
(#10) delikleri de kapatıyordu, o yüzden delik-alfa hatası (#11) hiç
görünmüyordu. #10 düzeltilince #11 anında testi kırdı. Ders: "çalışıyor" ile
"doğru" aynı şey değil — iki hatanın birbirini götürdüğü bir kod, ilk
düzeltmede bozuluyormuş gibi görünür.

> *(Görsel: `docs/kenar-halkasi.png` — kişisel fotoğraf içerdiği için repoya dahil edilmedi; ölçümün sayıları yukarıda.)*

*Etek ucundaki koyu çizgi: önce · sadece çekirdekler eşitlenince (siluet fazla
inceldi, base sızdı) · +1 px genişletme ve kenar rengi tazelemesiyle.*

**Kenar için kalıcı çözüm — üç parça:**

1. Açma/kapama çekirdekleri **eşit** (`Min(3)+Max(3)`, `Max(5)+Min(5)`).
2. Ardından **bilinçli 1 px genişletme.** Fark eşiği (18) kıyafetin yumuşak
   kenarında aşılamıyor, yani eşik sınırı gerçek kenarın ~1 px içinde kalıyor;
   genişletmezsek bindirmede kenardan base sızıyor.
3. `decontaminate_edges`: kenar piksellerinin **rengini** en yakın "derin iç"
   pikselden tazeler, **şeklini** değiştirmez. Maskeyi aşındırmak yanlış çözüm
   olurdu — bir kenar hatasını başka bir kenar hatasıyla değişirdik.

Ölçülen sonuç (kıyafetin kendi paletine uzaklık, en dış 1 px):

| | önce | sonra |
|---|---|---|
| #8 bordo polo | 52.9 | 43.7 |
| #7 gri örme şort | 34.2 | 22.5 |
| #10 sarı baskılı tişört | 88.3 | 69.7 |

Sayı hâlâ iç kısımdan (10-18) yüksek — kenarda bir miktar karışım kaçınılmaz.
Ama görünür koyu çizgi kayboldu; asıl ölçüt bu.

**Bu düzeltmelerin hepsi `--reextract` ile BEDAVA denendi.** Ham VTON çıktıları
saklandığı için kenar parametreleri dört tur ayarlandı, tek kuruş ödenmedi.
Mimarinin bu kararı burada karşılığını verdi.

**#3 için kalıcı çözüm:** tüm RGB uzaklık hesapları `imageutil.rgb_distance()`
kapısından geçiyor (float32'ye yükseltme garantili). NumPy'de çarpmadan önce tip
yükseltmeyi hatırlamaya güvenmek yerine tek kapı bırakıldı.

### 6.2 Renk filtresi deneyi — BAŞARISIZ (ama öğretici)

Fikir: fark algoritması "ne değişti"yi biliyor ama "bu kıyafet neye benziyor"u
bilmiyor. Elimizde kıyafetin cutout'u var → renk paletini çıkar, uymayanı at.

Temiz veriyle ölçüm:

| Kurulum | Bel bandı artefaktı | Polo kaplama | Şort kaplama |
|---|---|---|---|
| **Filtresiz (mevcut)** | %72 | %10.9 | %7.5 |
| Tolerans 70 | %0 | %9.8 | %5.7 |
| Tolerans 100 | %0 | %9.9 | %6.6 |

Hedef metrik düzeliyor ama gölgedeki gerçek kıyafet pikselleri de gidiyor,
yerlerine delik açılıyor ve alttaki eski kıyafet sızıyor. **Bir kusuru iki
kusurla değiştiriyor.** Filtre `use_color_filter=False` ile kapalı; kod ve
ölçümler `wardrobe/layers.py`'de duruyor.

**İkinci deneme — `drop_base_leak`, o da BAŞARISIZ.** Birincinin kusuru tek
yönlü olmasıydı ("piksel kıyafetin paletine uzak mı"), o yüzden gölgedeki
gerçek kıyafeti de kesiyordu. İkincisi çift yönlü kuruldu: *piksel kıyafetin
paletine mi, yoksa aynı koordinattaki base pikseline mi daha yakın?*

Mantık sağlam ama ölçüm çürüttü. Palet parlaklık ölçekleriyle (×0.45'e kadar)
genişletildiği için **koyu bir kıyafetin paleti neredeyse siyahı da kapsıyor**;
bordo polonun paletine siyah sızıntı "yakın" çıkıyor ve test ayrım yapamıyor.
Leke kalkmadı, kenarlar tırtıklandı, #6'nın kaplaması %0.6'dan %0.4'e düştü.
Fonksiyon çağrılmıyor, ölçüm kaydı olarak duruyor.

**İki denemenin ortak dersi:** base sızıntısını piksel filtresiyle çözme
girişimlerinin ikisi de aynı yere çıktı. Sonuç net — *base sızıntısı bir piksel
problemi değil, veri problemi.* Çözümü base'in kıyafetinde (§7), çıkarım
algoritmasında değil.

### 6.3 Diğer ölçümler

- rembg vs flood: rembg kadife koltuk arka planını temiz kaldırdı, flood
  kaldıramazdı. İlk çağrı 17 sn (176MB model indirir), sonrası 1-3 sn.
- Claude öznitelik çıkarımı gerçekten işe yaradı: Fenerbahçe logosunu, polo
  yakayı, "pamuk pike" kumaşını okudu.
- **"Yeşil şort" aslında siyah çıktı** — Claude yanılmadı, fotoğraf yanıldı.
  Piksel ölçümü: R=35 G=32 B=31, ölçülebilir yeşil yok. Loş/sıcak ışıkta çekim
  rengi kaybetmiş. Ders: kötü aydınlatma öznitelik kalitesini doğrudan vuruyor.

---

## 7. ÇÖZÜLDÜ: bel çizgisi

**Semptom (eski):** polo ile şort arasında beyaz bir bant.

### 7.1 Kök sebep — önce iddia edildi, sonra ÖLÇÜLDÜ

İddia şuydu: sorun algoritmada değil veride; her kıyafet, üzerinde **başka
kıyafetler olan** bir base'e karşı bağımsız üretiliyor. Bu makul bir gerekçeydi
ama kanıt değildi — §6.2 artefaktın *büyüklüğünü* ölçmüştü, *kaynağını* değil.

Kaynak testi (API çağırmadan, diskteki katmanlar üzerinde): katmanın her opak
pikseli, kıyafetin kendi paletine mi yoksa base'in bileşenlerine mi (duvar /
lacivert tişört / gri şort / ten) daha yakın diye sınıflandırıldı.

| Ölçüm | Sonuç |
|---|---|
| Bordo polo katmanının poloya **uymayan** pikselleri | 10.005 (katmanın %8.2'si) |
| Bunların base'in **gri şortuyla** eşleşen kısmı | **%90.2** (medyan RGB uzaklığı **6.0** / 441) |
| Kirliliğin dikey tepesi | y %55 |
| Base'in gerçek bel çizgisi (lacivert→gri geçişi) | y %56.5 (732 px) |
| **Fark** | **12 piksel** — 1296 px'lik tuvalde %1'den az |

Medyan uzaklık 6.0 "benzer renk" değil, **aynı piksel** demek. Artefakt,
base'in gri şortunun yeniden çizilmiş hali; tam bel çizgisinde duruyor. İddia
kanıtlandı.

Aynı test şunu da gösterdi: sorun bel çizgisiyle sınırlı değil. Base'in kıyafeti
yeni kıyafetten **geniş** olan her yerde aynı şey oluyor — silüet kenarında
duvar pikselleri (%22.9), şortun altında ten pikselleri (%21.2) katmana
sızıyor. Genel kural: *base'in kıyafeti yeni kıyafetin siluetinin dışına
taştığı her yerde, taşan bölge katmana bulaşıyor.*

### 7.2 Düzeltme ve doğrulama

Base yenilendi: **dar ribana siyah polo + sade siyah şort**, desen yok. Aynı
bordo polo (#8) aynı boru hattından yeniden üretildi:

| | ÖNCE (bol lacivert tişört + desenli gri şort) | SONRA (dar siyah polo + sade siyah şort) |
|---|---|---|
| Kıyafete uymayan piksel | **%8.20** | **%4.28** |
| Bel bandında (y %55-56) | **3.986 px** | **272 px** |
| Kirliliğin yoğunlaşması (en yoğun 3 bant) | %46.5 | %25.5 |

Sayı yarıya indi ama asıl sonuç dağılımda: eskiden kirlilik **tek bir bantta**
toplanıyordu (görünür beyaz şerit), şimdi silüet kenarına yayılmış ince bir
kalıntı. Görsel olarak bel bandı tamamen kayboldu.

> *(Görsel: `docs/bel-cizgisi-once-sonra.png` — kişisel fotoğraf içerdiği için repoya dahil edilmedi; ölçümün sayıları yukarıda.)*

*Soldan sağa: eski base'de bel bandı · aynı kare teşhis boyamasıyla (kırmızı =
poloya ait olmayan piksel) · yeni base'de aynı polo · yeni base'de krem-sarı
polo.*

**Yüksek kontrast testi:** açık krem-sarı polo (#9) koyu base üzerinde — bir
bant olsa en çok burada görünürdü. Görsel temiz.

> ⚠ #9'un **%0 kirlilik** sayısına güvenme. Saflık metriği kıyafetin kendi
> paletini parlaklık ölçekleriyle genişletiyor; krem-sarı bir kıyafette bu
> genişletme krem duvarı da "kıyafet" saymaya başlıyor. Metrik o kıyafette
> **kör** — koyu/doygun renklerde anlamlı, açık nötrlerde değil. #9'un kanıtı
> sayı değil, göz.

### 7.3 Kalan kusur: belde SİYAH LEKE (açık.)

Model, giydirdiği kıyafetin komşusunu yeniden çiziyor: base'de şortun belini
uydurdu (düğmeli, desenli bir bant) ve fark bunu üst katmana ait sandı.

**Bu kusur ilk raporlandığında "görünmüyor" denmişti — yanlıştı.** Bordo polo o
sırada sadece siyah şortla test edilmişti; leke siyahın üstünde siyah olduğu
için fark edilmedi. Açık gri şortla (#7) kombinlendiğinde **belde büyük, düzensiz
siyah bir leke** olarak ortaya çıkıyor.

Etkilenen katmanlar: **#8 bordo polo** ve **#5 lacivert tişört** (ikisi de koyu
üstler). #9 krem polo ve #10 sarı tişörtte yok — açık renkli oldukları için
farkta base'in siyah beliyle karışmıyorlar.

Piksel filtresiyle çözülmeye iki kez çalışıldı, ikisi de başarısız (§6.2).
Çözüm base'in kıyafetinde: bkz. §7.4-A3, **antrasit** base.

### 7.4 Düzeltmenin BEDELİ: base'in rengi bir kör nokta yaratıyor

Tüm dolap yeni base'de üretilince ortaya çıktı — ve mimarinin doğrudan bir
sonucu olduğu için en önemli kısıt bu olabilir:

| Kıyafet | Katman kaplaması | Kirlilik | Durum |
|---|---|---|---|
| #5 lacivert tişört | %13.2 | %5.27 | iyi |
| #7 gri örme şort | %10.7 | %0.22 | çok iyi |
| #8 bordo polo | %13.5 | %4.28 | iyi |
| #9 krem-sarı polo | %15.5 | (metrik kör) | görsel olarak iyi |
| #10 sarı baskılı tişört | %15.5 | %3.42 | iyi, baskı korunmuş |
| **#6 siyah keten şort** | **%0.7** | — | **KULLANILAMAZ** |

#6'nın ham çıktısı doğru: model şortu giydirmiş. Sorun çıkarımda:

```
#6 siyah keten şort : fark ortalaması  3.88   alt bedende eşiği (18) aşan  %2.6
#7 gri örme şort    : fark ortalaması 22.51   alt bedende eşiği (18) aşan %31.4
```

Base **siyah şort** giyiyor. Siyah şortun üstüne siyah şort giydirilince
ortada fark yok — çıkarılacak sinyal yok. Eşiği düşürmek çözmez; 3.88 zaten
gürültü seviyesi.

**Genel kural:** fark tabanlı çıkarım, base'in kıyafetinin çıkarılan kıyafetle
**kontrast** yapmasını gerektiriyor. Ama tek bir base her kıyafetle aynı anda
kontrast yapamaz — base'in kıyafeti hangi renkse, o renkteki kıyafetler kör
noktada kalıyor.

Eski base'de kör nokta açık gri altlardaydı (fark edilmedi çünkü öyle bir
kıyafet yoktu); yeni base'de siyah altlarda ve siyah alt yaygın bir şey.

Sistem bu durumu zaten kendi yakalıyor (`MIN_LAYER_COVERAGE` uyarısı) —
sessizce bozuk katman üretmiyor.

**Hangi renk en iyisi?** Dolabın gerçek renklerine karşı ölçüldü. Sayı, aday
renge en yakın kıyafetin RGB uzaklığı (eşik 18):

| Aday base rengi | Üstlerle | Altlarla |
|---|---|---|
| Turkuaz | 165 | 186 |
| Chroma yeşili | 135 | 149 |
| Beyaz | 128 | 88 |
| Orta gri | 40 | 78 |
| Koyu gri (antrasit) | 26 | 60 |
| **Siyah (mevcut)** | **23** | **9** |

Siyahın altta 9 çıkması #6'nın kaybolmasını tam olarak açıklıyor. Üstteki 23 de
rahatsız edici: bordo polo (#8) sınıra yakın.

### 7.6 ÇÖZÜM: iki base — biri çıkarım, biri gösterim

§7.4 ve §7.5 birlikte şunu söylüyordu: base'in kıyafet renginin **birbirine zıt
iki gereksinimi** var ve tek bir renk ikisini birden karşılayamıyor. Çözüm renk
aramayı bırakıp **iki işi ayırmak** oldu.

| Dosya | Rengi | İşi |
|---|---|---|
| `base.png` | orta mavi `#456191` | Çıkarım — kontrast burada lazım |
| `base_display.png` | aynı görüntü, kıyafeti nötr koyuya boyanmış | Bindirme — sızıntı burada görünmesin |

Geometri **birebir aynı** (tek görüntünün yeniden renklendirilmiş hâli), o yüzden
katmanlar ikisine de tıpatıp oturuyor. §7.5'teki hibrit bu yüzden çökmüştü: orada
iki AYRI fotoğraf vardı ve kıyafet siluetleri farklıydı.

`mannequin.build_display_base()` üretiyor, `layers.compose()` kullanıyor, manken
değişince otomatik siliniyor.

**Base rengi neden orta mavi:** aday renkler dolabın gerçek renklerine karşı
ölçüldü. Kritik incelik — **Gemini istenen rengi koyulaştırıyor**, o yüzden
adaylar "koyulaşmış hâliyle de sağlam mı" diye değerlendirildi:

| Aday | İstenen (üst/alt) | %28 koyulaşmış | En kötü |
|---|---|---|---|
| **Orta mavi `#5F82BE`** | 87 / 105 | 74 / 119 | **74** |
| Orta yeşil | 75 / 108 | 60 / 90 | 60 |
| Petrol `#3C5F6E` | 55 / 97 | **17** / 54 | 17 |

Petrol ilk denemede gerçekten kullanıldı ve gerçekten koyulaştı (`#394651`
geldi) — üstlerle kontrastı **19**'a düştü, siyah base'in 23'ünden bile kötü.
Orta mavi seçildi, gelen `#456191`, ölçülen kontrast **84 / 112**.

**Üçüncü parça — `drop_base_clothing` filtresi.** Base'in kıyafeti yine de
katmana sızıyor; artık silinebiliyor, çünkü base rengi dolaptaki her kıyafetten
uzak. Filtrenin güvenlik kuralında güzel bir simetri var:

> Filtre yalnızca kıyafet base'in renginden yeterince uzaksa uygulanır.
> Yakınsa uygulanmaz — ama zaten o durumda sızıntı da görünmez.
> **Yani filtre tam olarak ihtiyaç duyulduğu durumlarda güvenlidir.**

Ölçüldü: #5 lacivert tişört base'e 41 birim uzakta → atlanıyor (uygulansa
katmanın %28'ini yerdi). Diğer beşi 85-165 arasında → uygulanıyor, sildikleri
%0.0-3.6.

**Sıra kritik:** filtre delik doldurmadan SONRA gelmeli. Önce öncesine
konmuştu ve etkisi yok oldu — `fill_holes` silinen bandı "kıyafetin içinde
kalmış boşluk" sanıp geri dolduruyordu.

**Kalan kusur:** #5 lacivert tişörtte belde mavi kalıntı var (filtrenin
atladığı tek kıyafet). Bir de filtre katmanda delik açtığında altından gösterim
base'i görünüyor — nötr olduğu için silik gri bir şerit olarak okunuyor.

> *(Görsel: `docs/kombinler.png` — kişisel fotoğraf içerdiği için repoya dahil edilmedi; ölçümün sayıları yukarıda.)*

### 7.5 Turkuaz base deneyi — BAŞARISIZ (ölçüldü, geri alındı)

Yukarıdaki tabloya bakıp turkuaz denendi. Base, kendi fotoğrafına sanal deneme
uygulanarak turkuaz giydirildi (mevcut cutout'lar turkuaza boyanıp `try_on`'a
verildi — turkuaz kıyafete sahip olmak gerekmedi), sonra tüm dolap yeniden
üretildi.

**Çıkarım tarafı beklendiği gibi düzeldi:**

| | siyah base | turkuaz base |
|---|---|---|
| #6 siyah keten şort kaplaması | %0.6 (kullanılamaz) | **%7.5** (sağlam) |

**Ama bindirme tarafı bozuldu.** Belde bağıran bir turkuaz bant çıktı.

> *(Görsel: `docs/turkuaz-deneyi.png` — kişisel fotoğraf içerdiği için repoya dahil edilmedi; ölçümün sayıları yukarıda.)*

**Öğrenilen kural — base'in renginin İKİ ZIT gereksinimi var:**

| Gereksinim | İstediği |
|---|---|
| Çıkarım (fark) | Kıyafet renklerinden mümkün olduğunca **uzak** |
| Bindirme (kombin) | Sızdığında **göze batmayan** |

Sızıntı kaçınılmaz (§7.1): base'in kıyafeti yeni kıyafetin siluetinin dışına
taştığı her yerde görünüyor. Siyah sızınca gölge sanılıyor, turkuaz sızınca
felaket. Turkuaz birinci gereksinimde kazanıp ikincisinde kaybetti.

**Hibrit de denendi ve o da başarısız:** katmanları turkuaz base'den çıkarıp
siyah base üzerinde göstermek. Hizalama sorun değildi (iki base arasında yüz
farkı 3.4, duvar farkı 0.0 — VTON arka planı ve kafayı piksel piksel korumuş),
ama iki base'in **kıyafet siluetleri** farklı: turkuaz kolun bittiği yerde siyah
base'in kolu devam ediyor (bölge farkı 173). Katmanlar birinin geometrisine göre
kesildiği için diğerine oturmuyor — sonuç iki kusuru birden taşıyor.

**Sonuç ve öneri:** base'in kıyafeti **koyu ama siyah olmayan** olmalı —
antrasit/koyu gri. Sızıntı gölge gibi okunur (ikinci gereksinim), siyah
kıyafetler de eşiği rahat aşar: antrasit (70,70,74) ile siyah keten şort
(38,36,36) arası uzaklık **60**, eşiğin üç katından fazla. Denenmedi.

Deney geri alındı; dolap siyah base haliyle duruyor (`ready` ×6, #6 hariç
hepsi kullanılabilir). Turkuaz katmanlar ve base `scratchpad`'de kaldı.

---

## 8. Sıradaki adım

### A. Bel çizgisi deneyi — ✅ BİTTİ
Yapıldı ve ölçüldü, bkz. §7. Base artık dar siyah polo + sade siyah şort.

### A2. Kalan katmanları üret — ✅ BİTTİ
DNS düzeltildikten sonra (§13) tüm dolap üretildi: **6 katmanın 6'sı `ready`**.
Ama #6 siyah keten şort kullanılamaz durumda — sebebi §7.4, çözümü A3.

Kombin denemek için:
```
python cli.py preview 10 7 -o kombin.png     # sarı baskılı tişört + gri şort
```

> *(Görsel: `docs/kombinler.png` — kişisel fotoğraf içerdiği için repoya dahil edilmedi; ölçümün sayıları yukarıda.)*

*Faz 1'in çıktısı: üç kombin, hepsi tek bir base'den üretilmiş katmanların
bindirilmesiyle — yeni API çağrısı yok, anlık, bedava. Soldan sağa #10+#7,
#9+#7, #5+#7. Üçüncüde belde kalan yama §7.3'teki kusur.*

### A3. Base'i ANTRASİT'e çevir (~$0.60, denenmedi)
§7.4'teki kör noktayı, §7.5'in tuzağına düşmeden kapatmanın yolu: base'in
kıyafeti **koyu ama siyah olmayan** olsun. Turkuaz denendi, çıkarımı düzeltip
bindirmeyi bozdu; antrasit iki gereksinimi birden karşılıyor — sızıntı gölge
gibi okunur, siyah kıyafet yine de eşiği rahat aşar (uzaklık 60, eşik 18).

İki yol:

1. **Fotoğraf çek** — aynı duruş/duvar, dar sade antrasit üst + antrasit alt.
   Risksiz; sadece katmanların yeniden üretimi kadar maliyet.
2. **Sanal deneme ile giydir** — §7.5'teki yöntem: mevcut bir cutout'u antrasit'e
   boyayıp kendi fotoğrafına giydir. Kıyafet almak gerekmiyor, ama base bir
   difüzyon çıktısı olur ve yüz/vücut hafifçe kayar.

```
python cli.py mannequin --from-photo <yeni foto>
python cli.py build-layers
```

**Başarı ölçütü iki şarttır, ikisi birden:** #6'nın kaplaması %0.6'dan %7
bandına çıkmalı **VE** kombinlerde belde görünür bant olmamalı. Turkuazda
birincisi sağlandı, ikincisi sağlanmadı — o yüzden başarısız sayıldı.

> **Önce `data/` klasörünü yedekle.** Manken değişince ham çıktılar siliniyor;
> turkuaz deneyi sadece bu sayede geri alınabildi.

### B. Faz 2'ye geç
FastAPI + düz HTML/JS giydirme arayüzü. **Streamlit kullanma** — her etkileşimde
tüm script'i baştan çalıştırıyor, katmanlı anlık önizleme için yanlış araç.
Katman bindirme sadece üst üste `<img>` + CSS `z-index`, build step yok.
Çakışma mantığı `config.conflicts()` ile hazır.

---

## 9. Yol haritası

| Faz | İçerik | Durum |
|---|---|---|
| 0 | Dolap altyapısı: yükleme, kırpma, öznitelik, DB, CLI | ✅ |
| 1 | Base manken + VTON + fark tabanlı katman çıkarımı | ✅ |
| 2 | Manuel giydirme arayüzü (FastAPI + CSS z-index) | ✅ |
| 3 | AI kombin önerisi: kural filtresi → renk uyumu → LLM | ⬜ Dolap büyüyünce |
| 4 | "Gerçekçi göster": tam VTON zinciri + cache | ✅ |
| 5 | Kişiselleştirilmiş manken (SMPL-X veya ölçüden figür) | ⬜ |

**Faz 3 notu:** LLM'e 100 kıyafet atıp "seç" deme. Üç katman: (1) kural filtresi
— sıcaklık → `warmth`, bağlam → `formality`; (2) Lab uzayında renk uyumu → 8-10
aday; (3) LLM seçer + Türkçe gerekçe yazar.

**Faz 5 notu:** "3B model" üç seviye — (A) ölçüden figür ~2-3 gün, (B) SMPL-X
~1 hafta, (C) tam 3B kumaş simülasyonu aylar ve VTON'dan **kötü** sonuç. C'yi
yapma. A/B'de asıl iş SMPL-X değil, gri mesh'i fotogerçek hale getirme adımı —
VTON modelleri insan fotoğrafı bekliyor.

---

## 10. Bilinen sınırlar

- **Ayakkabı ve aksesuar için VTON yok** (FASHN kategori listesinde yok).
  `status="unsupported"` ile işaretlenip atlanıyor — sessizce başarısız olmuyor.
- **Gömlek içeride mi dışarıda mı** — katman sisteminde çözülemez.
- **Flat-lay fotoğrafta kollar kıvrıksa** model onu "kolun şekli bu" sanıyor;
  kolları yanlara açık serip çekmek gerekiyor.
- **Base'in kıyafeti katmana sızıyor** — büyük ölçüde çözüldü (§7), ama
  mekanizma duruyor: model komşu bölgeyi yeniden çiziyor. Base dar ve sade
  olduğunda görünmez hale geliyor, yok olmuyor.
- **Base'in kıyafet rengiyle aynı renkteki kıyafetler çıkarılamıyor** — fark
  sıfıra yakın kalıyor. Şu an siyah altlar kör noktada (§7.4). Mimarinin
  doğrudan sonucu; tek base her renkle kontrast yapamaz.
- **Saflık metriği açık nötr renklerde kör** — palet parlaklıkla genişletildiği
  için krem/beyaz/gri kıyafetlerde duvarı ve teni de kıyafet sayıyor (§7.2).
  Doygun renklerde (bordo, sarı) güvenilir, nötrlerde göze bak.
- **Yeni base'de ayaklar kadrajın dışında** — bel deneyi için sorun değil ama
  ayakkabı ve tam boy oran için ileride yeniden çekim gerekecek.
- Kötü aydınlatma → renk kaybı → yanlış öznitelik (bkz. §6.3).

---

## 11. Proje yapısı

```
config.py              yollar, kategori/katman tablosu, VLM ayarları
db.py                  SQLite şema + CRUD + idempotent migration
cli.py                 komut dağıtıcı
wardrobe/
  imageutil.py         EXIF, küçültme, rgb_distance(), to_lab(), apply_align()
  secrets.py           anahtar okuma + maskeli raporlama
  cutout.py            arka plan temizleme (rembg | flood) + person_mask (§32)
  vision.py            Claude vision + JSON şema + translate_prompt()
  ingest.py            yükleme hattı — tek giriş: add_garment() (KIRP→HİZALA, §31)
  mannequin.py         manken(ler): aktif seçimi, ekleme/geçiş/silme + gösterim base'i
  templates.py         22 çekim şablonu + segmentasyon önseli
  vton.py              sağlayıcılar: fashn(tryon-max) | fal(v1.6) | gemini | mock
  layers.py            fark tabanlı katman çıkarımı + bölge kapısı (§30) + birleştirme
  render.py            Faz 4 zincirleme render + önbellek
  edits.py             Faz 6 düzenleme sohbeti + sürüm geçmişi
web/
  app.py               FastAPI uç noktaları
  static/              index.html · app.js · style.css (moda editoryal tema)
tests/                 347 test, API anahtarı gerektirmez
                       (§28: test_coklu_manken.py — 22 test, ağırlığı veri kaybında)
                       (§30: test_bolge_kapisi.py — 13 test, kapının zararsızlığı)
data/                  raw/ cutout/ layers/ mannequins/ renders/ + wardrobe.db
Clothes/               kullanıcının kıyafet fotoğrafları (4 adet)
yellow_polo.jpeg       + sonradan eklenen 2 kıyafet (kök dizinde)
yellow_t_shirt.jpeg
Boydan foto/           tam boy fotoğraflar (3 adet — 2026-08-06 tarihli
                       olan güncel base: dar siyah polo + sade siyah şort)
```

**DB şeması:** `garments` · `mannequins` (`is_active` ile — §28) · `layers`
(PK `(garment_id, mannequin_id)`, status:
`pending|ready|failed|unsupported|stale`) · `outfits` · `outfit_items`.
Faz 2-5'in tabloları da kurulu — ilerledikçe migration gerekmiyor.

Sonradan eklenen sütunlar `db.MIGRATIONS`'ta ve `_apply_migrations` idempotent
(§21). Kural: bu listeye yalnızca DEFAULT'u olan sütunlar girer — ve DEFAULT'u
anlamlı olmayan bir sütun eklendiyse (`is_active`, §28.6) migration'ın onu
düzelten bir adımı da olmalı.

---

## 12. Harcama

| Kalem | Tutar |
|---|---|
| Manken üretimi (3 kez) | ~$0.09 |
| Sanal deneme (6 çağrı) | ~$0.45 |
| Claude öznitelik (4 kıyafet) | ~$0.10 |
| *Ara toplam (önceki oturum)* | *~$0.64* |
| Sanal deneme — bel çizgisi deneyi (4 ücretli çağrı) | ~$0.30 |
| ↳ bunun **DNS yüzünden boşa gideni** (2 çağrı) | ~$0.15 |
| ↳ bunun elle kurtarılanı (1 çağrı) | ~$0.075 |
| Sanal deneme — kalan dolap (4 çağrı) | ~$0.30 |
| Sanal deneme — mavi base üzerinde dolap (6 çağrı) | ~$0.45 |
| Faz 4 — ilk gerçekçi render (2 çağrı) | ~$0.15 |
| 2 yeni tişört (yükleme akışı) + #12 yeniden denemesi | ~$0.28 |
| Claude öznitelik (2 yeni kıyafet) | ~$0.05 |
| Turkuaz base deneyi — base (2) + dolap (6) = 8 çağrı | ~$0.60 |
| ↳ deney başarısız, geri alındı; bilgi kaldı (§7.5) | — |
| `segmentation_free` A/B — #12, 2 çağrı (§20.1) | ~$0.15 |
| ↳ hipotez çürüdü, ayar geri alındı; **kök sebep bulundu** | — |
| §28 çoklu manken — 0 çağrı (yalnızca dosya işlemi) | **$0.00** |
| §30 bölge kapısı — 0 çağrı (`--reextract`, bedava) | **$0.00** |
| §31 #16'nın onarımı — 1 çağrı (2 kredi) | ~$0.20 |
| **Toplam** | **~$2.92** |

100 kıyafetlik tam dolap tahmini: ~$10 (fal) + ~$3 (Claude), tek seferlik.

Boşa giden $0.15 tesadüf değildi, bir tasarım açığıydı — §6.1 #9. Artık ön
kontrol var; aynı hata bir daha para yakmıyor.

---

## 13. ✅ ÇÖZÜLDÜ: bu makinede DNS bozuktu

**Belirti:** `build-layers` şu hatayla duruyor:

```
ResultUnreachable: sonuç sunucusu (cdn.fashn.ai) DNS'te çözülemiyor
```

**Teşhis (ölçüldü):**

| Alan adı | Yerel çözümleyici | 8.8.8.8 / 1.1.1.1 |
|---|---|---|
| `fal.run`, `queue.fal.run` | ✅ çözüyor | ✅ |
| `api.anthropic.com` | ✅ çözüyor | ✅ |
| `cdn.fashn.ai` | ❌ `getaddrinfo failed` | ✅ (CloudFront) |
| `v3.fal.media`, `fal.media` | ❌ (ara sıra çözüyor) | ✅ |

Yani fal'da arıza yok, Claude tarafı da sağlam. Sorun sadece bu makinenin ad
çözümlemesinde ve **inference uç noktası çözülüp sonuç CDN'i çözülmediği için**
en pahalı biçimde tezahür ediyordu: para gidiyor, dosya gelmiyor (§6.1 #9).

**Çözüm — DNS sunucusunu değiştir. (Yapıldı ve işe yaradı.)** Ayarlar → Ağ ve
internet → Wi-Fi → Donanım özellikleri → DNS sunucusu ataması → Düzenle → El ile
girilen → IPv4 açık → Tercih edilen `1.1.1.1`, Alternatif `8.8.8.8` → Kaydet.
Doğrulama:

```
python -c "import socket; print(socket.gethostbyname('cdn.fashn.ai'))"
```

Bir IP yazdırıyorsa hat açık, `build-layers` çalışır.

> Projeye bilerek DNS baypası **gömülmedi**. Uygulamanın ad çözümlemesini
> kullanıcının yapılandırdığı sunucunun dışına kaçırması sürpriz bir davranış
> olurdu; üstelik sorun uygulamada değil ortamda. Kod tarafında yapılan tek şey,
> bu arızanın **para yakmasını** engellemek.

**Ödenmiş ama inememiş çıktıyı kurtarma:** hata mesajındaki URL `layers.error`
sütununda duruyor.

```
python -c "import db; print(db.connect().execute('SELECT garment_id, error FROM layers WHERE status=\"failed\"').fetchall()[0]['error'])"
```

URL'yi indirip `data/layers/g<id>_m<mid>_raw.png` olarak kaydet, sonra:

```
python cli.py build-layers --reextract --id <id>
```

Bu bedava — #9 bu yolla kurtarıldı.

---

## 14. Faz 2 — giydirme arayüzü

```
python cli.py web            # http://127.0.0.1:8000
python cli.py web --reload   # geliştirme (kod değişince yeniden başlar)
```

**Sunucu görüntü BİRLEŞTİRMİYOR.** Katmanları olduğu gibi servis ediyor,
tarayıcı `<img>` + CSS `z-index` ile bindiriyor. Faz 1'in tüm varlık sebebi
buydu (§2): katmanlar zaten aynı mankenden, aynı çözünürlükte üretildiği için
piksel piksel hizalı. Her tıklamada sunucuya gidip PNG birleştirmek gereksiz
gecikme olurdu — seçim anında görünüyor, ağ trafiği yok.

**Çakışma kuralı tek yerden geliyor.** `/api/wardrobe` cevabı kategori
tablosunu (`z` ve `slots`) da taşıyor; istemci kuralı yeniden tanımlamıyor,
sunucudan alıyor. Yani `config.CATEGORIES` hâlâ tek kaynak. Elbise seçilince
tişört+pantolonun düşmesi bu tablodan geliyor, JS'te yazılı bir istisnadan
değil.

| Uç nokta | İşi |
|---|---|
| `GET /api/wardrobe` | Dolap + kategori kuralları + katman durumu |
| `GET /api/base.png` | Zemin — **gösterim** base'i (§7.6) |
| `GET /api/layer/{id}.png` | Tek katman (şeffaf PNG) |
| `GET /api/cutout/{id}.png` | Dolap listesindeki küçük görsel |
| `GET/POST /api/outfits`, `DELETE /api/outfits/{id}` | Kombin kaydet/oku/sil |
| `GET /api/mannequins` | Mankenler + katman sayısı + silinecek varlık sayısı (§28) |
| `POST /api/mannequins` | Yeni manken (**ücretsiz**, katman üretmez) |
| `POST /api/mannequins/{id}/aktif` | Aktif mankeni değiştir (**ücretsiz, hiçbir şey silmez**) |
| `DELETE /api/mannequins/{id}` | Manken + katman/renderlarını sil (**GERİ ALINAMAZ**) |
| `GET /api/mannequins/{id}.png?w=` | Şeritteki küçük görsel (gösterim base'i) |

**Katmanı olmayan kıyafet gizlenmiyor, işaretleniyor** ("katman yok" rozeti,
tıklanamaz). Sessizce listeden düşürmek kullanıcıya hata gibi görünürdü —
kıyafeti eklediğini biliyor.

Kombinler `outfits` / `outfit_items` tablolarına yazılıyor; bu tablolar Faz 0'da
zaten kurulmuştu, migration gerekmedi.

**Test edilenler** (`tests/test_web.py`, 9 test): kategori kurallarının cevapta
olduğu, katman durumunun doğru bildirildiği, hazır olmayan katmanın 404 verdiği,
zeminin gösterim base'i olduğu, kombin kaydet/oku/sil döngüsü. Tarayıcıdaki
bindirme test edilmiyor — asıl kural `config.py`'de ve orada test ediliyor.

**Elle doğrulandı:** iki katman doğru z-sırasıyla bindi (şort z=20 altta,
tişört z=30 üstte), başka bir üst seçilince öncekinin otomatik düştüğü,
kombinin kaydedilip listelendiği tarayıcıda çalıştırılarak görüldü.

---

## 15. Faz 4 — "Gerçekçi Göster"

```
python cli.py render 10 7            # ÜCRETLİ, önbellekli
python cli.py render 10 7 --force    # önbellektekini yok say
```
Arayüzde: kombini seç → "Gerçekçi Göster".

**Faz 1'in tersini yapıyor.** Katman mimarisinde kıyafetler ayrı ayrı üretilip
üst üste bindiriliyor ve birbirlerini bilmiyorlar — bel çizgisinin, kumaşın
diğerinin üstüne nasıl düştüğünün tam tutmamasının sebebi bu (§7). Burada
kıyafetler **zincirleme** giydiriliyor: önce alt, sonra üst; her adım bir
öncekinin çıktısını girdi alıyor. Yani model üstü giydirirken altı görüyor.
Katman çıkarımı yok, bindirme yok — dolayısıyla çıkarımın hiçbir kusuru da yok.

> *(Görsel: `docs/faz4-gercekci.png` — kişisel fotoğraf içerdiği için repoya dahil edilmedi; ölçümün sayıları yukarıda.)*

*Krem polo + siyah şort, zincirleme. Katman bindirmesindeki bel geçişi
artefaktı ve kenar halkası burada hiç yok.*

**Bedeli ve nasıl yönetildiği:** kıyafet başına bir VTON çağrısı. İki parçalı
kombin ~30-80 sn ve ~$0.15. Bu yüzden:

| Karar | Neden |
|---|---|
| Sonuç önbelleğe yazılıyor | Aynı kombin ikinci kez bedava |
| Önbellek anahtarı **sıradan bağımsız** | `[10,7]` ve `[7,10]` aynı dosya — yoksa aynı kombin iki kez ödenir |
| Anahtar manken id'sini içeriyor | Manken değişince eski renderlar geçersiz, `clear_cache()` siliyor |
| `plan()` çağrı YAPMADAN maliyeti söylüyor | Arayüz düğmenin yanında "2 çağrı · ~$0.15" yazıyor; kimse ücretli işlemi bilmeden başlatmıyor |
| Desteklenmeyen kategori atlanıyor | Ayakkabı/aksesuar (§10) sessizce değil, gerekçesiyle |
| İş arka planda + durum yoklama | 60 saniye boyunca donmuş ekran yerine "2/3 giydiriliyor" |

**Zincir sırası z'ye göre ARTAN** (önce alt, sonra üst) — Faz 1'in çözemediği
bel çizgisi sorunu tam olarak bu sıra sayesinde burada oluşmuyor.

**Test edilenler** (`tests/test_render.py`, 11 test): `plan()`in sağlayıcıya
hiç dokunmadığı (ücret riski), sıranın doğru olduğu, desteklenmeyenin gerekçeyle
atlandığı, önbellek isabetinde sağlayıcının ÇAĞRILMADIĞI, anahtarın sıradan
bağımsız olduğu, ara dosyaların temizlendiği, hata halinde yarım işin önbelleğe
yazılmadığı, manken değişince renderların silindiği.

> ⚠ `conftest`'e `RENDER_DIR` izolasyonu eklendi. Eklenmeseydi testler
> kullanıcının **ücretle üretilmiş** renderlarını silerdi — §6.1 #8 ve #13'ün
> aynısı, üçüncü kez.

**Sırada:** Faz 3 (AI kombin önerisi), dolap büyüdükten sonra.

---

## 16. Kırpma modeli değişti — ve neden

**`u2net` → `isnet-general-use`** (`wardrobe/cutout.REMBG_MODEL`). Yeni bağımlılık
gerekmedi; kurulu rembg bu modelleri zaten taşıyor.

**Sebep, ölçülmüş bir hata:** beyaz tişört beyaz çarşafın üstünde çekildi
(kıyafet-zemin kontrastı **61.8**; sarı tişörtte 150+). `u2net` solda kadrajın
kenarına kadar uzanan çarşaf dilimini kıyafete kattı. O bozuk görsel VTON'a
gidince model ortada uydurma bir **pat** çizdi ve göğüsteki logo kayboldu.

| Model | Kadraj kenarına değiyor mu | Sonuç |
|---|---|---|
| `u2net` (eski) | **EVET** — çarşafı aldı | bozuk |
| `isnet-general-use` | hayır | ✔ temiz |
| `u2net_cloth_seg` | hayır | bozuk çıktı (çoklu maske üst üste) |

**Model değiştirmek tek başına yetmedi, iki tuzak daha çıktı:**

1. **isnet yarı saydam matte veriyor** — tam opak piksel sayısı **1**, "opak"
   bölgede ortalama alfa 159 (u2net'te 252). Bu hattı SESSİZCE bozardı:
   `garment_palette()` alfası 200 üstü pikselleri örneklüyor, palet boş dönerdi
   ve ona dayanan her şey (kör nokta kontrolü, base sızıntısı filtresi) fark
   edilmeden devre dışı kalırdı. Çözüm: `_harden_alpha()`.
2. **Sadece eşiklemek delik bırakıyor.** Ölçüldü, eşik ve çözünürlüğe göre
   kutu doluluğu:

   | Ayar | Kaplama | Kutu doluluğu | Kadraj kenarı |
   |---|---|---|---|
   | tam çözünürlük, eşik 110 | %25.9 | %51.2 | hayır |
   | 1024px, eşik 110 | %26.9 | %53.1 | hayır |
   | **1024px, eşik 60 + delik doldur** | **%38.8** | **%74.0** | **hayır** ✔ |
   | 1024px, eşik 30 + delik doldur | %43.2 | %69.0 | EVET (zemini geri aldı) |

   Segmentasyon modelleri ~1024'te eğitiliyor; tam çözünürlükte kıyafetin içi
   delik deşik çıkıyor. Maske çalışma çözünürlüğünde hesaplanıp orijinale
   büyütülüyor.

**Yeni koruma — `cutout.touches_frame_edge()`.** Flat-lay çekimde kıyafet
kadrajın ortasındadır; kırpık kenara dayanıyorsa zeminin bir parçası kıyafet
sanılmış demektir. **Kaplama kontrolü bunu yakalamıyordu** — bozuk kırpık %44.5
ile MIN/MAX aralığının tam ortasındaydı. Artık `add_garment` uyarı veriyor.

### Kalan sorun: #12 beyaz tişört

Kırpma düzeltildi ve **logo artık çıkıyor** — yani düzeltme işe yaradı. Ama
VTON çıktısı hâlâ zayıf: tişört fazla kısa render ediliyor ve ortada bir pat
kalıyor. Düz beyaz kıyafet, açık tenli/açık duvarlı bir base üzerinde modelin
zorlandığı bir vaka. Seçenekler: tekrar denemek (difüzyon stokastik, ~$0.075),
koyu zeminde yeniden çekmek, ya da kabul etmek. **Denenmedi.**

---

## 17. Çekim şablonları (`wardrobe/templates.py`)

Beş silüet: tişört, uzun kollu, gömlek, şort, pantolon. Normalize (0-1)
çokgen olarak duruyorlar, çözünürlükten bağımsızlar.

**İki işi var, ikincisi ölçülebilir olan:**

1. **Çekim rehberi.** Arayüz fotoğrafı şablonla üst üste gösteriyor; kullanıcı
   oturmadıysa yeniden çekiyor. Kolların açık serilmesini sağlıyor (§10) ve
   kıyafeti kadrajın ortasında, kenarlara boşluk bırakarak tutuyor.

2. **Segmentasyon önseli — asıl kazanç.** Ölçüldü, beyaz tişört beyaz çarşafın
   üstünde, **eski ve başarısız `u2net` modeliyle**:

   | | Kaplama | Kutu doluluğu | Kadraj kenarı |
   |---|---|---|---|
   | ham | %44.6 | %80.3 | **EVET** (çarşafı aldı) |
   | "kenara değen parçayı at" | **%0.1** | — | hayır (her şeyi sildi) |
   | **şablonla sınırla** | **%38.1** | **%83.1** | **hayır** ✔ |

   **Şablon bozuk modeli bile düzeltti.**

**Ortadaki satır en önemli ders:** "kenara değen parçayı at" her şeyi sildi,
çünkü çarşaf kıyafete **yapışmıştı** — ayrı bir leke değil, tek bileşen. Yani
algoritmaya *nerede olmadığını* söylemek işe yaramıyor; **nerede olduğunu**
söylemek gerekiyor. Negatif değil pozitif önsel.

**Ne kadar hassas olmalı:** ölçümde düz bir DİKDÖRTGEN bile sorunu çözdü. Bu
yüzden önsel `PRIOR_MARGIN = 0.12` ile cömertçe genişletiliyor ve kullanıcıdan
milimetrik hizalama beklenmiyor.

**Nerede devreye giriyor:** sadece **kurtarma** olarak. Kırpık kadraj kenarına
dayanmıyorsa hiç dokunulmuyor — sağlam vakalarda gereksiz risk almamak için.
Önsel maskenin tamamını yerse de ham maskeye dönülüyor (güvenlik freni).

### Telefondan kullanım

```
python cli.py web --host 0.0.0.0
```
Telefonda: `http://192.168.1.108:8000` (aynı Wi-Fi). Güvenlik duvarı sorarsa
özel ağlarda izin ver.

> ⚠ **Kimlik doğrulama yok.** Aynı ağdaki herkes tam boy fotoğrafları görebilir.
> Ev ağında sorun değil, ortak ağda açma.

> **Canlı kamera kaplaması neden yok:** tarayıcılar HTTPS olmayan adreste
> (localhost hariç) kameraya erişimi engelliyor. Bu yüzden akış "native
> kamerayla çek → uygulama şablonla üst üste göster → onayla/yeniden çek"
> şeklinde. HTTP üzerinden çalışır.

---

## 18. AÇIK KONULAR — buradan devam

### 18.1 Mor tişörtteki mavi pikseller: sebebi ölçüldü

Base'in kıyafet rengi `#436090` (67,96,144). Her kıyafetin ona uzaklığı ve
katmanda kalan sızıntı:

| Kıyafet | Base'e mesafe | Etkin tolerans | Kalan mavi piksel |
|---|---|---|---|
| #10 sarı tişört | 165 | 55 | **2** |
| #12 kırık beyaz | 127 | 55 | 249 |
| #9 krem polo | 102 | 50 | 131 |
| **#11 mor tişört** | **46** | **22** | **95.269** |

**Mor, base'in mavisine komşu bir renk.** Güvenlik kuralı toleransı mesafenin
yarısıyla sınırlıyor (§7.6) — yoksa filtre kıyafetin KENDİ rengini yerdi. Ama
bu, sızıntının da temizlenememesi demek. Kural doğru çalışıyor; sorun rengin
kendisinde.

**Bu, §7.4'teki takasın bir katman derinindeki hali:** siyah base siyah şortu
kör ediyordu, mavi base onu kurtardı ama şimdi mavi/mor/lacivert üstleri
vuruyor. Tek base ile bu takastan kaçış yok — sadece hangi renklerin kurban
olacağı seçiliyor.

Beyaz tişörtte (#12) sızıntı az ama VTON çıktısının kendisi zayıf: model
uydurma bir pat çiziyor ve kıyafeti kısa render ediyor (§16).

### 18.2 Karar noktası: katman mimarisi mi, doğrudan render mı?

Faz 4 (§15) zincirleme VTON ile **çıkarım yapmıyor** — dolayısıyla mavi
sızıntı, kenar halkası, kör nokta gibi kusurların HİÇBİRİ oluşmuyor. Ölçülmüş
karşılaştırma: krem polo + siyah şort renderı temiz çıktı, katman bindirmesinde
aynı kombinde bel geçişi kusurluydu.

| | Katman (Faz 1-2) | Zincirleme render (Faz 4) |
|---|---|---|
| Hız | anında | 30-80 sn |
| Maliyet | kombin başına $0 | ~$0.075 × kıyafet |
| Kalite | çıkarım kusurlarına açık | temiz |
| Kör nokta | var (§7.4, §18.1) | yok |

Kullanıcının önerisi: kalite bu seviyede kalacaksa doğrudan Gemini sınıfı bir
düzenleyiciyle render almak. **Ölçüm bu fikri kısmen destekliyor** — Gemini
katman üretiminde kullanılamaz (kıyafet dışını korumuyor, §"Gemini ölçümü"),
ama Faz 4'te kullanılabilir çünkü orada çıkarım yok.

**Denenmedi, önerilen deney:** aynı kombini üç yolla üretip yan yana koymak —
(a) katman bindirme, (b) FASHN zinciri, (c) Gemini sınıfı düzenleyici. Maliyet
~$0.30. Karar bu karşılaştırmadan sonra verilmeli.

### 18.3 İstenen ama yapılmayan: hizalama arayüzü

Telefonda canlı kamera kaplaması HTTPS gerektirdiği için (§17) şu an sadece
"çek → şablonla göster → onayla/vazgeç" var. Kullanıcının istediği: fotoğrafı
**kaydırıp ölçekleyerek** şablona tam oturtmak — yön tuşları + yakınlaştırma.

Yapılacak iş: `#hizalama` panelinde fotoğrafa `transform: translate/scale`
uygulayan kontroller; onaylanan dönüşüm sunucuya gönderilip kırpma öncesi
uygulanır. Şablon önseli zaten hazır olduğu için asıl kazanç, önselin kıyafete
tam oturması olur.

> Not: ölçümde düz bir dikdörtgen önsel bile bozuk kırpmayı düzeltmişti (§17),
> yani hassas hizalama **şart değil** — iyileştirme, zorunluluk değil.

---

## 19. ÇÖZÜLDÜ: §18.1 mavi sızıntı — sorun filtrede değil, METRİKTEYDİ

§18.1'de sızıntının *büyüklüğü* ölçülmüştü ama *neden temizlenemediği* değil.
Ölçüldü ve cevap beklenenden basit çıktı: **RGB uzaklığı parlaklıkla rengi tek
sayıya karıştırıyor.**

| | base'e RGB uzaklığı | base'e (a\*,b\*) uzaklığı |
|---|---|---|
| Mor tişört (#4A2F6B) | **61.8** | **22.1** |
| Base mavisinin ×0.60 gölgesi | **74.2** | **10.3** |

RGB **sıralamayı ters çeviriyor**: base'in kendi gölgesi, mor tişörtten daha
uzak görünüyor. Yani gölgeli sızıntıyı yakalayan hiçbir tolerans (≥74 gerekir)
morun kendisini (61.8) yemeden çalışamaz. `drop_base_clothing`'in yarı-mesafe
güvenlik kuralı doğru çalışıyordu; kusurlu olan ölçtüğü uzaydı.

**Aynı kusur ikinci bir yerde daha vardı ve orada hiç fark edilmemişti.**
`build_display_base` de nötrleme maskesini `rgb_distance < 60` ile kuruyordu ve
base'in kıyafetinin gölgeli bölgelerini kaçırıyordu: gösterim base'inde
**21.014 piksel** hâlâ mavi kalmıştı. Katman filtresi düzelip siluet daha temiz
kesilince o mavi kıyafetin kenarında bir çizgi olarak ortaya çıktı — yani
düzeltmenin kendisi ikinci kusuru görünür yaptı.

### 19.1 Çözüm — üç parça

**1. `imageutil.to_lab()` + `lab_distance()`.** Ağırlıklı Lab uzaklığı; L\*'ın
payı `LAB_LIGHTNESS_WEIGHT = 0.5`. Sıfır olamaz (lacivert ile açık mavi ayırt
edilemez hale gelir), 1.0 da olamaz (standart ΔE, gölgeye yine kör). skimage
bağımlılığı eklenmedi — dönüşüm 10 satır.

**2. `layers.drop_base_leak_lab()`.** Karar **iki yönlü** ve **aynı
koordinattaki base pikseliyle** veriliyor:

> piksel, base'in orada olduğu şeye mi yoksa kıyafetin paletine mi daha yakın?

Palet ortalamasıyla değil piksel bazlı karşılaştırma yapmasının yan faydası:
base'in duvar ya da ten olduğu yerde uzaklık zaten büyük çıkıyor, yani ayrı bir
"sadece gövde bandına bak" kuralı gerekmiyor. Konum bilgisi karşılaştırmanın
içinde geliyor.

Bu, sızıntıyı piksel filtresiyle çözmenin **üçüncü** denemesi. Öncekiler neden
başarısızdı ve bu neden farklı:

| Deneme | Kusuru |
|---|---|
| `color_filter` (§6.2) | Tek yönlü; gölgedeki gerçek kıyafeti de kesiyordu |
| `drop_base_leak` | İki yönlüydü ama RGB'deydi **ve** paleti parlaklıkla genişletiyordu → koyu kıyafetin paleti siyahı kapsıyordu |
| `drop_base_clothing` | Tek yönlü + RGB; toleransı yarı mesafeyle sınırlamak zorunda, base'e yakın renklerde kapanıyor |
| **`drop_base_leak_lab`** | İki yönlü + Lab + piksel bazlı. Parlaklık genişletmesi **hiç yok** — L\* payını kısmak aynı işi doğru yapıyor |

**3. `mannequin.build_display_base()` de krom düzlemine geçti.** Eşik ölçümle
seçildi — base kıyafet paletine ortalama uzaklık:

| bölge | krom (a\*,b\*) |
|---|---|
| base'in kıyafeti | **0.9** |
| duvar | 29.9 |
| saç | 31.5 |
| ten | 47.9 |

Eşik 15: kıyafeti tam alıyor, diğer üçüne bulaşma **%0.0**. Gövde bandı artık
ayrım aracı değil güvenlik ağı — bu base'de bant içi/dışı fark **0 piksel**,
yani krom eşiği tek başına yetiyor. Bant yine de duruyor, başka bir base'de
kadraja giren mavi bir nesne nötrlenmesin diye.

### 19.2 Ölçülen sonuç

Yer gerçeği: katman pikselinin, **aynı koordinattaki base pikseliyle** RGB
uzaklığı < 25 ise o piksel sızıntıdır (model base'i yeniden çizmiş).

| kıyafet | rgb (eski) | lab | **both (seçilen)** |
|---|---|---|---|
| #5 lacivert tişört | 4.828 | 3.212 | **3.211** |
| #6 siyah keten şort | 4.335 | 141 | **141** |
| #7 gri örme şort | 4.427 | 653 | **650** |
| #8 bordo polo | 1.998 | 157 | **157** |
| #9 krem polo | 2.662 | 298 | **298** |
| #10 sarı baskılı tişört | 2.179 | 0 | **0** |
| #11 mor tişört | 2.501 | 311 | **308** |
| #12 kırık beyaz | 4.712 | 123 | **87** |

Gösterim base'inde kalan mavi: **21.014 → 1 piksel.**

**`LEAK_FILTER = "both"`** seçildi. İkisi rakip değil tamamlayıcı: RGB filtresi
base'in ana rengine yakın lekeleri palet üzerinden, Lab filtresi
gölgeli/yeniden çizilmiş olanları piksel bazlı yakalıyor. §6.1 #14-15'in dersi
burada üçüncü kez geçerli oldu — **iki çözümü yarıştırmak yerine doğru sırada
arka arkaya koymak.**

Bedeli kaplamada 0.6-1.2 puan (#11: %14.5 → %13.8). Sentetik veride ölçülen
yanlış pozitif oranı %0.6. Görsel doğrulama: silüet boyunca uzanan tırtıklı
kenar da kayboldu — o kusur ölçülmemişti, düzeltmenin yan faydası.

### 19.3 KALAN KUSUR: kol ağızlarında silik gri şerit (dürüst rapor)

Sızıntı ve tırtıklı kenar gitti, ama görsel karşılaştırmada yeni bir şey
göründü: kol ağızlarında ve etek ucunda **silik gri-mavi bir şerit.**

Bu filtrenin hatası değil, filtrenin **doğru çalışmasının sonucu.** §7.1'in
genel kuralı: *base'in kıyafeti yeni kıyafetin siluetinin dışına taştığı her
yerde o bölge katmana bulaşıyor.* Eskiden o piksel katmanda **kalıyordu** —
kirli renkli ve tırtıklı bir kenar olarak. Şimdi doğru şekilde atılıyor ve
altından nötrlenmiş gösterim base'i görünüyor.

Yani takas şu: **tırtıklı kirli kenar → düzgün nötr şerit.** İkincisi gölge
gibi okunuyor, birincisi render hatası gibi okunuyordu — ama görünmez değil.

Kök sebep hâlâ veride (§7.1): base'in tişörtünün kolu, dolaptaki tişörtlerin
çoğundan geniş. Kalıcı çözüm base'i **daha dar kollu** bir üstle yeniden
çekmek. Denenmedi.

Ölçülmemiş bir ara fikir: iç bölgede **sil**, siluet kenarında **boya**
(`repaint_base_leak` iki filtreyi de birlikte kullanır). Mantıklı görünüyor ama
bu projede mantıklı görünen üç fikir üst üste ölçümde çürüdü (§6.2) — önce
ölç.

> ⚠ **§18.1'deki "95.269 mavi piksel" sayısına artık güvenme.** O metrik
> "base paletine RGB < 55" sayıyordu; mor, base'e RGB'de 45.8 uzakta olduğu
> için **tişörtün kendisini** sayıyordu. §7.2'deki saflık metriğinin açık
> nötrlerde kör olması gibi, bu da base'e komşu renklerde kör. Yeni ölçüm
> piksel bazlı yer gerçeğine dayanıyor.

**Tümü `--reextract` ile BEDAVA yapıldı** — ham çıktılar saklandığı için tek
kuruş ödenmedi. Mimarinin bu kararı ikinci kez karşılığını verdi.

---

## 20. Sağlayıcı katmanı: FASHN parametreleri + alternatif sağlayıcı

### 20.1 §16'nın kök sebebi — hipotez ÇÜRÜDÜ, gerçek sebep FOTOĞRAFTA

fal'ın OpenAPI şeması çekildi (tahmin edilmedi). `FashnTryonV16Input` içinde
kullanmadığımız bir alan çıktı: **`segmentation_free`, varsayılanı `True`.**

Hipotez makuldü: açıkken model yeni kıyafeti mevcut olanın üzerine harmanlıyor
ve onun sınırlarını miras alıyor olabilir — §16'nın "fazla kısa render ediliyor"
belirtisi buna birebir uyuyordu.

**Ölçüldü (`tryon-ab 12 --seed 42`, ~$0.15) ve çürüdü:**

| | segfree=False | segfree=True |
|---|---|---|
| Etek ucu | y = 0.619 | y = **0.619** |
| Kaplama | %15.0 | %14.8 |
| İki çıktı arası fark | medyan **0.00** · ortalama 3.64 · eşiği aşan %3.5 |

İki çıktı istatistiksel olarak aynı ve **kusur ikisinde de aynen duruyor**.
Ayar sağlayıcının varsayılanına geri alındı: etkisi ölçülmemiş bir sapmayı
taşımak, sonraki her katmanı sağlayıcının test ettiği yapılandırmanın dışına
çıkarırdı.

**Gerçek sebep kırpığa bakınca görüldü: #12'nin fotoğrafı KATLI çekilmiş.**

| kırpıkta görünen | render'da çıkan |
|---|---|
| Yakadan eteğe inen **dikey kat izi** | ortadaki uydurma **düğme patı** |
| Göğüsteki **yatay kat izi** | **kapitone panel** görüntüsü |
| Solda çarşaftan kalan tırtıklı şerit | omuzlardaki **bej lekeler** |

Model hiçbir şey uydurmamış — **kendisine verilen kat izlerini sadakatle
giysi yapısı olarak çizmiş.** §10'daki "kıvrık kolu kolun şekli sanıyor"
kuralının aynısı, kollardan katlara genişletilmiş hâli.

Yani §16 iki kez yanlış yere baktı: önce kırpma modeline (düzeltildi, sorun
sürdü), sonra VTON modeline (parametresi ölçüldü, etkisi yok). Sebep hep
girdideydi.

**Çözüm ücretsiz:** #12'yi düz serip, kollar açık, kat izi olmadan, **koyu**
bir zeminde yeniden çek (§16'nın kendi listesindeki "koyu zeminde yeniden
çekmek" seçeneği — artık doğru olduğu biliniyor). Sonra `add` ve
`build-layers --id 12`.

**Bu kusur da otomatik tespit edilemedi.** İki metrik denendi, ikisi de ayırmadı:

| | #12 (bozuk) | #11 | #10 | #9 |
|---|---|---|---|---|
| Şablonun kol bölgesi doluluğu | **%95.9** | %87.6 | %92.0 | %93.6 |
| Gövde ortasında kat izi | **0.6** | −0.1 | −5.9 | 0.1 |

Kol doluluğu metriği kendini yiyor: kollar **altta katlı** olduğu için
sınırlayıcı kutu daralıyor ve normalize edilmiş "kol bölgesi" gövdenin üstüne
düşüyor. Ayıran tek sayı en/boy oranı (1.16 vs 1.02-1.06) ama tek örnekle eşik
konmaz. §20.2'deki sonuçla aynı yere çıkıyor: **bu kusur sınıfı ölçülebiliyor
ama önceden kestirilemiyor.** Göz görüyor, sayı görmüyor — o yüzden §21'deki
kırpma sonrası doğrulama paneli, otomatik bir dedektörden daha değerli.

`seed` de eklendi: tohumsuz çağrı tekrarlanabilir değil, o yüzden §16'daki
"tekrar dene" seçeneği denenememişti. Yukarıdaki A/B tohum 42 ile yapıldı —
tek değişken ayarın kendisi olsun diye.

```
python cli.py tryon-ab <id> --seed 42            # iki ayar yan yana, ~$0.15
python cli.py tryon-ab <id> --seed 42 --gemini   # üçüncü yol dahil, ~$0.23
python cli.py tryon-ab <id> --yes                # onay sorma (betik için)
```

Komut çıktıyı katman olarak **kaydetmiyor**, sadece karşılaştırma dosyası
yazıyor — dolabı bozmadan deneme yapılabiliyor.

### 20.2 "Zor kıyafeti otomatik tespit et" — DENENDİ, OLMUYOR

Fikir: beyaz/açık kıyafetleri önceden tanıyıp alternatif sağlayıcıya yönlendir.
Ücretsiz sinyaller ölçüldü:

| kıyafet | duvara uzaklık | zemine uzaklık (Lab) | gerçek sonuç |
|---|---|---|---|
| #7 gri şort | **5.7** | 1.9 | ✅ iyi |
| #9 krem polo | **7.1** | 1.6 | ✅ iyi |
| **#12 kırık beyaz** | **16.7** | 6.4 | ❌ **bozuk** |

Sinyal işe yaramıyor: kontrast tabanlı bir ön-tespit, çalışan iki kıyafeti
işaretler ve bozuk olanı **daha kolay** sayardı. Katman kutusu da ayırmıyor
(#12'nin yüksekliği %42.0, üstlerin bandı %40.9-46.1 — eteği 3-5 puan kısa ama
tek örnekle eşik konmaz).

**Bu yüzden otomatik yönlendirme ön-tahmine bağlanmadı.** Yönlendirme var ama
gözleme dayanıyor: uygun olmayan sağlayıcı **ücretli çağrıdan önce** reddediliyor
(`vton.supports_layers`), kategori desteği sağlayıcıya soruluyor.

### 20.3 `GeminiEditProvider` — nerede kullanılabilir, nerede kullanılamaz

`fal-ai/gemini-25-flash-image/edit` (şema doğrulandı) sağlayıcı olarak eklendi.

| | Katman üretimi (Faz 1) | Zincirleme render (Faz 4) |
|---|---|---|
| Kullanılabilir mi | **HAYIR** | evet |
| Neden | Kıyafet DIŞINDAKİ pikselleri de yeniden üretiyor; fark tabanlı çıkarım "kıyafet dışı sabit kalır" varsayımına dayanıyor | Orada çıkarım yok, sonuç doğrudan gösteriliyor |

Bu kısıt `supports_layers = False` ile **sağlayıcının kendisi tarafından**
bildiriliyor — çağıran tarafın hatırlamasına bırakılmıyor. `build_layer` ücretli
çağrıdan önce reddediyor.

**Kategori sınırı yok.** "Ayakkabı olmaz" FASHN'ın eğitim setinin sınırı (§10),
evrensel bir kural değil. Dolapta ayakkabı biriktiğinde tek yol bu olacak:

```
python cli.py render 3 --provider gemini
```

**İki incelik:**

- **Sonuç `sync_mode` ile isteniyor**, yani yanıtın içinde data URI olarak
  geliyor ve hiçbir CDN'e dokunulmuyor. Bu bilinçli: `RESULT_HOSTS`'a tahminle
  alan adı yazmak §6.1 #9'da bir kez para yaktı ve bu uç noktanın CDN'i henüz
  **gözlenmedi**. Kapı eksik değil — gerekmiyor.
- **Önbellek anahtarı sağlayıcıyı içeriyor** (`m1_6-9_gemini`), ama varsayılan
  sağlayıcı için eski biçim korunuyor. Değişseydi ücretle üretilmiş mevcut
  önbellek dosyaları bulunamaz olur ve aynı kombine ikinci kez ödenirdi.

---

## 21. §18.3 hizalama arayüzü — YAPILDI

Panel artık fotoğrafı **kaydırıp ölçekleyerek ve döndürerek** şablona
oturtmayı sağlıyor: sürükleme (fare + dokunma), yön tuşları, klavye
(oklar · `+`/`-` · `[`/`]` · `0` sıfırlar), tekerlekle ölçek. Onaylanan
dönüşüm sunucuya gidiyor ve **kırpmadan önce** uygulanıyor
(`imageutil.apply_align`).

**En kritik nokta koordinat sözleşmesi.** Önizleme ile sunucu ayrışırsa hata
sessiz olur: kullanıcı kıyafeti şablona oturtur, sunucu başka bir yere taşır,
kırpma bozulur ve sebebi görünmez. Sözleşme:

| kural | neden |
|---|---|
| Tuval boyutu değişmiyor | Şablon 0-1 normalize; tuval değişirse önsel kayar |
| Çerçeve oranı = fotoğraf oranı (JS'ten kuruluyor) | `translate(%)` eleman genişliğine göre; oran tutmazsa yüzdeler kayar |
| Sıra: ölçek → dönme → taşıma | CSS `translate(…) rotate(…) scale(…)` bu sırayı verir |
| Açılan kenar zeminin medyan rengiyle dolar | Siyah dolgu flood yedeğinin arka plan referansını bozar, rembg'e sahte kontrast kenarı verir |
| Sınırlar `/api/templates`'ten geliyor | Sınır iki yerde tanımlanırsa sessizce ayrışır (§14 ilkesi) |
| Değerler sunucuda tekrar kırpılıyor | `scale=0` afin matrisi tekilleştirir; istemciye güvenilmez |

**Sözleşme tarayıcıda doğrulandı**, iddia edilmedi: `getComputedStyle`'ın
verdiği CSS matrisi ile `apply_align`'ın ürettiği matris karşılaştırıldı.

```
CSS    : (1.2557, 0.3365, -0.3365, 1.2557, 30.6, -23.8)
Python : (1.2557, 0.3365, -0.3365, 1.2557, 30.6, -23.8)
en büyük fark: 3.6e-06 · işaretli pikselin sapması: 0.24 px
```

**Orijinal fotoğraf korunuyor.** Hizalanmış görüntü `{slug}_aligned.png` olarak
ayrı yazılıyor; üstüne yazılsaydı yanlış hizalamadan dönmenin tek yolu
fotoğrafı telefondan yeniden yüklemek olurdu.

**Hizalama DB'ye kaydediliyor** (`garments.align_json`). `CREATE TABLE IF NOT
EXISTS` mevcut tabloya sütun eklemediği için `db._apply_migrations()` yazıldı —
idempotent, yalnızca DEFAULT'u olan sütunları ekler. Bu olmasaydı şema
güncellemesi yeni kurulumları düzeltip **var olan veritabanını sessizce eski
bırakırdı.**

**Kırpma sonrası doğrulama paneli** de eklendi: sonuç, şablonla üst üste
gösteriliyor. Panelde iyi duran bir hizalama kırpma modelinin yine de zemini
almasını engellemeyebilir — bunu ancak burada görmek mümkün.

---

## 22. Bu turda değişen dosyalar

| Dosya | Ne değişti |
|---|---|
| `wardrobe/imageutil.py` | `to_lab` · `lab_distance` · `apply_align` · `clamp_align` · `edge_color` |
| `wardrobe/layers.py` | `drop_base_leak_lab` · `LEAK_FILTER` · sağlayıcı uygunluk kapısı |
| `wardrobe/mannequin.py` | Nötrleme maskesi krom düzlemine geçti, bant genişledi |
| `wardrobe/vton.py` | `segmentation_free` · `seed` · `GeminiEditProvider` · data URI · `supports_layers`/`supports_category` |
| `wardrobe/render.py` | Sağlayıcıya duyarlı `plan()` ve önbellek anahtarı |
| `wardrobe/ingest.py` | `align` parametresi — kırpmadan önce uygulanıyor |
| `db.py` | `align_json` sütunu + `_apply_migrations` |
| `cli.py` | `render --provider` · `tryon-ab` |
| `web/app.py` | Hizalama form alanları · sağlayıcı seçimi · anahtar regex'i |
| `web/static/*` | Hizalama paneli + sonuç doğrulama paneli |
| `tests/` | +47 test (174 → **221**), yeni: `test_align.py` · `test_leak_lab.py` · `test_vton_saglayicilar.py` |

---

## 23. "Gerçekçi Göster çalışmıyor" — dört ayrı kusur, sonuç aslında üretilmişti

Kullanıcı düğmeye bastı, arayüz sonsuza kadar döndü. Teşhis şaşırtıcı çıktı:
**render başarıyla tamamlanmıştı** (`m1_6-8.png`, 18:14:00) ve sonuç temizdi.
Arayüz onu kaybetmişti. Dört ayrı kusur üst üste binmişti:

### 23.1 `subscribe` zaman aşımsız çağrılıyordu

fal_client'ın kendi belgesinde yazıyor: **"If not set, waits indefinitely."**
Yani fal'ın kuyruğunda takılan bir iş bizi süresiz bekletir, `except` bloğuna
hiç düşmez ve **teşhis edilebilir bile olmaz.**

`CALL_TIMEOUT = 240` (client_timeout) ve `QUEUE_TIMEOUT = 120` (start_timeout)
eklendi. Ayrıca `on_enqueue` ile `request_id` yakalanıyor ve zaman aşımı
mesajına konuyor — zaman aşımı "iş çalışmadı" demek DEĞİL, ücretlenmiş
olabilir. §6.1 #9'un dersinin aynısı: ödenmiş bir sonucu geri almanın tek yolu
ona işaret eden bir tutamak saklamak.

### 23.2 API'ye 20 MEGAPİKSEL görsel gönderiyorduk

Asıl yavaşlığın sebebi buydu. Telefon kırpıkları 3840×5120:

| kıyafet | önce | sonra | kazanç |
|---|---|---|---|
| #7 gri şort | **9.07 MB** | 1.30 MB | 7.0× |
| #8 bordo polo | **7.35 MB** | 0.96 MB | 7.7× |
| #6 siyah şort | **3.82 MB** | 0.66 MB | 5.8× |
| **toplam dolap** | **27.8 MB** | **8.1 MB** | **3.5×** |

Korelasyon net: `tryon-ab` çağrısı #12 ile (1.43 MB) normal sürede döndü,
arayüzdeki render #6 + #8 ile (3.8 + 7.4 MB) dakikalarca sürdü. Data URI
yoluna düşülürse base64 bunu %34 daha şişiriyor.

**Bunun hiçbir karşılığı yok: modelin çıktısı zaten 864×1296.** `VTON_MAX_PX =
1536` eklendi — baskı detayı korunuyor, piksel sayısı ~8 kat düşüyor. Aynı
gerekçe VLM yolunda zaten vardı (`VLM_MAX_PX`); VTON yolunda atlanmıştı.

> Yan düzeltme: `upload_image`/`encode_image`'ın varsayılan biçimi **jpeg** ve
> jpeg alfayı düşürür. Kırpığın alfası "kıyafet nerede" bilgisinin ta kendisi —
> açıkça `format="png"` veriliyor ve testle sabitlendi.

### 23.3 Arka plan işi çökerse iş sonsuza kadar "running" kalıyordu

Daemon thread bir istisnayla ölürse `_JOBS[job_id]` hiç güncellenmiyor; arayüz
süresiz yokluyor, sunucu kaydında hiçbir hata görünmüyor. `_arka_planda()`
sarmalayıcısı eklendi — **her yol ya done ya failed ile bitiyor.**

### 23.4 İş kaydı bellekte; sunucu yeniden başlayınca sonuç "kayboluyordu"

Kullanıcının gördüğü şey buydu. `_JOBS` bellekte olduğu için sunucu yeniden
başlayınca iş kimliği yok oldu, `/api/render/job/{id}` 404 döndü ve arayüz
"Başarısız" dedi — **oysa render diskte, ücreti ödenmiş halde duruyordu.**

Arayüz artık 404'te işi değil **sonucu** soruyor: `/api/render/plan` yanıtı
`cached` ve `key` taşıyor, önbellekte varsa render gösteriliyor. Anahtar
istemcide yeniden türetilmiyor — kural tek yerde (§14 ilkesi).

Bir de "Giydiriliyor… 2/2" yanına **geçen saniye** yazılıyor: 60 saniyedir aynı
şeyi yazan bir ekran, donmuş bir ekrandan ayırt edilemiyor. Kullanıcının pes
etmesinin sebebi tam olarak buydu.

### 23.5 Ders

Dört kusurun hiçbiri tek başına görünür değildi ve **hiçbiri asıl işi
bozmamıştı** — zincirleme render doğru çalışıyor, çıktı temiz. Bozuk olan
işin kendisi değil, **işin durumunu bildirme yolu**ydu. §6.1 #8'in ("ölçümüne
güvenemezsin") kardeşi: *kullanıcıya doğru durumu gösteremiyorsan, doğru
çalışan bir sistemin bozuk olduğunu düşünürsün.*

> ⚠ Bu turda bir dosya PowerShell ile metin olarak yeniden yazılırken
> **kodlaması bozuldu** (UTF-8 → cp1252 → UTF-8, Türkçe karakterler mojibake).
> Onarıldı. Kural: kaynak dosyalarda toplu değişiklik için PowerShell metin
> işleme kullanma — `web/` git'te izlenmiyor, yani geri dönülecek bir sürüm de
> yoktu.

---

---

## 24. FASHN'ın kendi API'si — `tryon-max` ve "mavi çizgiler modelin suçu mu?"

Kullanıcı FASHN'ın kendi sitesinde aynı kıyafetleri denedi: sonuç temiz,
arka plan bile silinmemiş. Bizim katman bindirmemizde ise hâlâ mavi çizgiler
var. Haklı bir soru: **daha iyi model, katman mimarisini kurtarır mı?**

### 24.1 Neden şüpheliyim — ve neden yine de ölçülmesi gerekiyor

Fark tabanlı çıkarımın aldığı şey "yeni kıyafet" değil, **iki siluetin
simetrik farkı.** Base mankenin üstünde mavi bir tişört var; mor tişört onun
dışına taşmadığı her yerde base'in mavisi **zorunlu olarak** değişiyor
(mavi → ten/duvar) ve o değişim katmana giriyor. Bu geometri, model kalitesi
değil — mükemmel bir model bile bu bölgeyi değiştirmek zorunda.

Ama kullanıcının noktası da geçersiz değil: model kıyafet **dışını** ne kadar
az kurcalarsa sızıntı o kadar azalır. §7.1'de ölçülen kirliliğin bir kısmı tam
olarak buydu — model base'in şortunun belini yeniden çizmişti.

Yani iki ayrı sebep var ve **ölçüm ikisini ayırabiliyor.**

### 24.2 `python cli.py layer-ab <id>` — soruyu sayıya çeviren komut

Aynı kıyafet iki modelle giydiriliyor, ikisinden de aynı boru hattıyla katman
çıkarılıyor ve iki sayı ölçülüyor:

| ölçüm | ne söylüyor |
|---|---|
| **sızıntı px** | Katman pikseli, aynı koordinattaki base pikseliyle neredeyse aynı (RGB < 25) |
| **dış fark** | Kıyafet bölgesinin **dışında** modelin değiştirdiği piksel oranı |

Okuma kılavuzu — karar bu tabloya bakarak veriliyor:

| dış fark | sızıntı | sonuç |
|---|---|---|
| düşük | düşük | **Katman mimarisi yaşar** — model iyi, geç |
| düşük | yüksek | Suç mimaride; model değiştirmek çözmez |
| yüksek | — | Model kıyafet dışını kurcalıyor |

```
python cli.py layer-ab 11              # mor tişört — en kötü vaka
python cli.py layer-ab 11 --resolution 2k --mode quality
```

Çıktılar `layerab_11_*_ham.png` (giydirilmiş) ve `_katman.png` olarak yazılıyor;
dolaba **kaydedilmiyor**.

### 24.3 `FashnProvider` — fal'ın yanına, yerine değil

Dokümanlar fal'ın değil **FASHN'ın kendi API'sinin** (`api.fashn.ai/v1`), yani
ayrı bir anahtar gerekiyor: `FASHN_API_KEY`. Anahtar yoksa hat çökmüyor, fal
üzerinden v1.6'ya düşüyor.

| | fal / v1.6 | fashn / tryon-max |
|---|---|---|
| Çözünürlük | 864×1296 sabit | 1k / 2k / **4k** |
| Ayakkabı, şapka, takı, çanta | ✗ (§10) | **✓** |
| Prompt ile düzeltme | ✗ | ✓ ("tuck in shirt") |
| Kategori | elle eşleniyor | model kendisi sınıflandırıyor |
| Katman üretimine uygunluk | **kanıtlanmış** | **ölçülmedi** (§24.2) |

**Üç mimari kazanım:**

1. **Sonuç `return_base64` ile isteniyor** — yani ayrı bir CDN'den indirme adımı
   YOK. §6.1 #9'daki en pahalı başarısızlık ("inference ücretlendirildi, sonuç
   indirilemedi") bu yolda **yapısal olarak imkânsız.** `RESULT_HOSTS` kapısına
   da gerek kalmıyor.
2. **Kategori sınırı yok** — dolapta ayakkabı biriktiğinde tek yol bu.
3. Zaman aşımlı yoklama (§23.1'in dersi baştan içeride).

`supports_layers` model adına bağlı: v1.6 için `True` (mevcut sekiz katman
onunla üretildi), tryon-max için ölçülene kadar `False`. `allow_layers=True`
kapıyı bilerek açıyor — kapalı bıraksaydım tam da ölçülmesi gereken deneyi
engellerdi.

**Kredi maliyeti (dokümandan):** `fast`+`1k` = 1, `balanced`+`2k` = 3,
`quality`+`4k` = 5 kredi. Uygulama planlarında kredi ~$0.10; API fiyatı ayrı
sayfada.

### 24.4 İki HTTP tuzağı — ikisi de ölçümle çözüldü

**403, ama Cloudflare'den.** İlk çağrı `403 Forbidden` döndü ve "anahtar bozuk"
gibi göründü. Gövde okununca `error code: 1010` çıktı — bu bir **Cloudflare**
kodu. Teşhisi kesinleştiren şey: **anahtarsız istek de aynı 403'ü verdi.**
Kimlik doğrulama sorunu olsaydı ikisi farklı sonuç verirdi.

Sebep: urllib varsayılan olarak `User-Agent: Python-urllib/3.13` gönderiyor ve
Cloudflare bunu engelliyor. Herhangi bir UA yetiyor; tarayıcı taklidine gerek
yok, kendimizi dürüstçe tanıtıyoruz.

**Hata gövdesi yutuluyordu.** Teşhis için gereken bilgi (`1010`) cevabın
içindeydi ve biz onu atıyorduk. Artık tek HTTP kapısı (`_cagir_http`) gövdeyi
okuyup mesaja koyuyor.

---

## 25. KARAR: katman mimarisi KALIYOR, sağlayıcı tryon-max oldu

`layer-ab 11` çalıştırıldı (2 kredi). Sonuç, benim beklentimin aksine
**kullanıcıyı haklı çıkardı.**

### 25.1 Tek katman ölçümü

| | fal / v1.6 | fashn / tryon-max |
|---|---|---|
| Sızıntı px | 11.355 | **3.253** |
| Dış fark | %1.98 | %8.22 |
| Kaplama | %14.3 | %17.4 |
| **Render edilen renk** | (56,51,117) | (65,50,88) |
| **Gerçek renge uzaklık** | **37.5** | **22.4** |

Görsel fark çarpıcıydı: v1.6'nın **ham çıktısı** idare ederken **katmanı**
göğsünde koyu lekeler, omuzlarda gri yamalarla çıkıyordu. tryon-max'in katmanı
ham çıktısıyla neredeyse birebir aynı.

**Kök sebep:** v1.6 mor tişörtü **yanlış renkte** üretiyordu — mavi kanalı
yüksek, gerçek renkten 37.5 birim uzak. O yanlış mavimsi mor base'in mavisiyle
karışıyordu ve §18.1'de "mor, base'in mavisine komşu" diye ölçtüğümüz şey
aslında **modelin renk hatasıydı**, kıyafetin özelliği değil.

Yani mavi çizgilerin sebebi ne filtre ne mimariydi — **modelin rengi yanlış
üretmesiydi.**

### 25.2 Asıl sınav: iki katmanın bindirilmesi

Tek katmanın temiz olması yetmez; kusurlar tarihsel olarak **kombinde**
çıkıyordu (§7). Üstelik bir risk sinyali vardı:

| kıyafet dışı bölge | v1.6 | tryon-max |
|---|---|---|
| yüz / kafa | 4.5 | **22.6** |
| duvar (sol / sağ) | **0.0 / 0.0** | 7.6 / 3.0 |
| bacaklar | 2.8 | 6.9 |
| **yüzün kayması** | **0 px** | **3 px** |

v1.6 duvarı piksel piksel koruyor; tryon-max her şeyi yeniden üretiyor ve
vücudu 3 px kaydırıyor. Katmanlar farklı çağrılardan kesildiği için bu,
§7.5'teki hibridin çöktüğü mekanizmanın ta kendisiydi.

**Test edildi (#11 + #7, 2 kredi): korku gerçekleşmedi.** İki katman düzgün
oturdu, bel geçişi temiz.

> ⚠ Sayısal bel metriği neredeyse hiç oynamadı (28.120 → 25.816 px, %8) ama
> görsel fark gece gündüz. Metrik burada **kör** — §19.2'de yazıldığı gibi
> "base paletine yakın piksel" sayıyor ve mor, base'in mavisine yakın olduğu
> için **tişörtün kendisini** sayıyor. Kararı göz verdi, sayı değil. Bunu
> metriğin başarısı gibi sunmamak lazım.

### 25.3 Dolap yeniden üretildi

`build-layers --provider fashn --force --exclude 5 7 11` → 5 çağrı, 10 kredi.
#7 ve #11 ölçüm sırasında zaten ödenmişti; ham çıktıları `data/layers/`'a
taşınıp `--reextract` ile bedava çıkarıldı (eski v1.6 hamları `.v16.png`
olarak yedeklendi).

| kıyafet | v1.6 kaplama | tryon-max kaplama |
|---|---|---|
| #6 siyah keten şort | %6.6 | **%8.9** |
| #7 gri örme şort | %8.6 | %8.8 |
| #8 bordo polo | %13.0 | %16.8 |
| #9 krem polo | %16.3 | %17.4 |
| #10 sarı baskılı | %15.1 | %16.8 |
| #11 mor tişört | %13.8 | %17.4 |
| #12 kırık beyaz | %11.4 | **%16.2** |

**Beklenmedik yan kazanım: #12'nin uydurma "patı" kayboldu.** §20.1'de
fotoğrafın katlı olmasına bağlanmıştı ve doğruydu — ama tryon-max o katlı
girdiden bile temiz sonuç çıkarıyor. §16'daki sorun kapandı.

#5 lacivert tişört kullanıcı tarafından elden çıkarıldığı için üretilmedi
(`--exclude 5`).

**Harcama:** 4 kredi (ölçüm) + 10 kredi (dolap) = **14 kredi.** 86 kredi kaldı.

### 25.5 RGB filtresi ARTIK ZARARLI — sağlayıcı değişince filtre de değişti

Kullanıcı fark etti: base'in kıyafetine yakın renkli bir kıyafet (lacivert)
eklendiğinde katmanda gri yamalar çıkıyor. Doğruydu — ama sebep beklenen yer
değildi.

Filtre konfigürasyonları, **tryon-max ham çıktıları** üzerinde, 11 kıyafet:

| konfig | kaplama | sızıntı px |
|---|---|---|
| none | %176.3 | 63.633 |
| rgb | %172.8 | 58.960 |
| **lab** | **%164.7** | **16.551** |
| both | %162.3 | 16.532 |

**RGB filtresinin Lab'ın üstüne kattığı fayda: 19 piksel (%0.1).** Bedeli
kaplamada 2.4 puan — ve bedel eşit dağılmıyor. #14 lacivert tişörtte (base'e
uzaklık 69) uyarlanır tolerans 34'e çıkıyor; laciverdin **gölgeli gerçek
pikselleri** o mesafenin içinde kalıyor ve siliniyor. Sonuç: omuzda ve yanda
gri yamalar. `lab` tek başına aynı kıyafeti tertemiz çıkarıyor.

`LEAK_FILTER = "lab"`. Tüm dolap `--reextract` ile bedava yeniden çıkarıldı.

**§19.2'deki "both daha iyi" ölçümü yanlış değildi — ESKİMİŞTİ.** O ölçüm
v1.6 çıktıları üzerindeydi ve v1.6 renkleri yanlış üretiyordu (§25.1: mor
tişörtte 37.5 birim hata). RGB filtresi aslında **o renk hatasının koltuk
değneğiydi.** Model rengi doğru üretince değnek yük oldu.

> **DERS:** doğru filtre modele bağlı. Sağlayıcı değişince filtre seçimi
> yeniden ölçülmeli — "daha önce ölçmüştük" yetmiyor. Bu, §6.1 #8'in
> ("izolasyon eksikse ölçümüne güvenemezsin") zaman boyutundaki hali:
> *bir ölçümün geçerliliği, ölçüldüğü koşulların hâlâ geçerli olmasına bağlı.*

### 25.7 "Yenileyince görecek miyim?" — hayır, ve sebebi önbellekti

Katmanlar bu projede sık yeniden üretiliyor (`--reextract` bedava, sağlayıcı
değişimi, filtre ayarı). Ama URL'ler sabitti (`/api/layer/8.png`), yani tarayıcı
**eski katmanı bellekten** servis ediyordu. Kullanıcı için bu "düzeltme işe
yaramamış" gibi görünüyor — düzeltme çalışıyor, görüntü bayat.

Üç katmanlı bir sorun çıktı ve üçü de kapatıldı:

| katman | belirti | çözüm |
|---|---|---|
| Görseller | eski katman/kırpık/base gösteriliyor | `/api/wardrobe` artık `layer_rev`, `cutout_rev`, `base_rev` (dosya mtime'ı) veriyor; URL'lere `?v=` basılıyor |
| `app.js` | **düzeltmenin kendisi devreye girmiyordu** | statik dosyalara `Cache-Control: no-cache` |
| `index.html` | no-cache bile yetmedi | `/` artık varlık URL'lerine sürüm damgası basıyor |

**İkinci satır en öğretici:** görsellerin bayatlamasını düzelten kod yazıldı,
ama tarayıcı **eski app.js'i** çalıştırdığı için düzeltme hiç çalışmadı.
Ölçüldü — sunucudaki dosyada yeni satır vardı, tarayıcıdaki `guncelle`
fonksiyonunda eski satır duruyordu.

**Üçüncü satır daha da öğretici:** `no-cache` başlığı eklendikten sonra bile
tarayıcı eski kodu çalıştırmaya devam etti — çünkü dosyayı **başlık eklenmeden
önce** önbelleğe almıştı ve o politikaya uyuyordu. Zorla yenilemek de yetmedi.
Başlık, geleceği düzeltiyor ama geçmişi düzeltmiyor. URL'yi değiştirmek ise
tanım gereği çalışıyor: farklı URL = önbellekte karşılığı olmayan kaynak.

> Kural: **önbellek geçersizleştirmesi başlıkla değil, URL ile yapılır.**
> Başlık bir ricadır, URL bir olgudur.

Sürüm damgası mtime olduğu için önbellek yine çalışıyor — dosya değişmediyse
URL de değişmiyor.

### 25.8 Yaka kenarındaki iki "bug" — biri bug DEĞİLMİŞ

Kullanıcı iki kusur bildirdi. İkisi de araştırıldı; **biri hiç kusur değildi.**

**1. Sarı tişörtün yakasındaki lacivert band — GERÇEK KIYAFET.**

Kırpılmış fotoğrafa bakınca çıktı: tişörtün **lacivert iç yakası** var, üstünde
"FENERIUM" etiketi. Model onu sadakatle çizmiş. Ölçüm zinciri şöyle ilerledi ve
her adım bir hipotezi eledi:

| test | sonuç | çıkarım |
|---|---|---|
| Katmanın kendi pikselinde base tonu? | 0 px | kenar kirlenmesi değil |
| Katman alfası → yaka altında delik var | evet | zemin görünüyor olabilir |
| Gösterim base'inin yakasını tenle doldur | **hiç değişmedi** | zeminden de değil |
| Kıyafetin kırpığına bak | **lacivert iç yaka** | kusur yok |

**Az kalsın doğru çalışan bir şeyi "düzeltiyordum."** Ders: bir artefaktın
kaynağını elemeden düzeltmeye başlamak, olmayan bir hatayı kovalamak demek.

**2. Mor tişörtün yakasındaki ince koyu halka — gerçek ama sub-piksel sınıfı.**

Üç hipotez kuruldu, **üçü de ölçümle çürütüldü:**

| hipotez | test | sonuç |
|---|---|---|
| Base'in kolyesi | base fotoğrafına bak | kolye YOK |
| Kıyafetin kendi yakası | kırpığa bak | düz mor, şerit YOK |
| Model uydurdu | ham çıktıya bak | ham çıktı TEMİZ |
| Maske gerçek kenarın dışına taşıyor | +1 px genişletmeyi kapat | **hiç değişmedi** |

Genişletme takası da ölçüldü ve şaşırtıcı çıktı — üç ayar da aynı:

| ayar | boyna taşan px | kenarda sızma |
|---|---|---|
| mevcut (+1px, blur 2.0) | 1.805 | 4 |
| genişletme YOK | 1.805 | 4 |
| +1px, blur 1.2 | 1.800 | 5 |

Sebebi: kontur pürüzsüzleştirmesi (blur 2.0 + yeniden eşikleme) sonradan gelip
±1 px farkı yutuyor. Yani §6.1 #10'daki genişletme, o adım eklendikten sonra
**etkisiz kalmış** — kaldırmak da bir şeyi bozmuyor.

Kalan tek açıklama: halka katmanın **yarı saydam anti-alias rampasında**
(alfa 1-128 arası). Orada morun rengi altındaki nötr gri base'le karışıyor ve
1-2 piksellik koyu bir çizgi bırakıyor. Bu, yumuşak kenarlı bir katmanı FARKLI
bir zemine bindirmenin doğasında var; parametreyle kapatılamaz.

**Gerçek çözümler ve bedelleri:**

| yol | bedel | not |
|---|---|---|
| Base'i yakası daha düşük/dar bir üstle yeniden çek | ücretsiz + 22 kredi (dolabı yeniden üret) | kök sebebi kaldırır (§7.1) |
| Faz 4 zincirleme render kullan | kombin başı ~4 kredi | bindirme yok, artefakt yok |
| Kabul et | 0 | 1-2 px, yakın planda görünüyor |

`EXTRA_DILATE` sabiti ayarlanabilir bırakıldı (varsayılan `True`, davranış
değişmedi) — ölçüm kaydı olarak duruyor.

> Çalışmadan önce `data/layers` yedeklendi (`layers_yedek_<tarih>`), sonrasında
> 11 katmanın 11'i yedekle **birebir aynı** doğrulandı. Hiçbir şey bozulmadı.

### 25.6 Çoklu base fikri — ÖLÇÜLDÜ, şimdilik GEREKMİYOR

Kullanıcının önerisi: arka planda 2-3 farklı renkte base tutmak ve kıyafetin
rengine göre en kontrastlı olanı seçmek. Fikir §7.4'teki kör noktaya doğru
nişan alıyor.

**Önce bir uyarı:** §7.5'te buna çok benzeyen bir şey denendi ve çöktü —
turkuaz base'den çıkarılan katmanlar siyah base'e oturmadı, çünkü iki base'in
kıyafet **siluetleri** farklıydı (bölge farkı 173). Fikrin tuzaktan kaçmasının
tek yolu, alternatif base'leri **yeni fotoğraf/VTON ile değil, aynı görüntüyü
yeniden renklendirerek** üretmek — o zaman geometri birebir aynı kalır.
`build_display_base` tam olarak böyle çalışıyor ve tutuyor (§7.6).

**Ama şu an gerekmiyor.** Dolaptaki her kıyafetin base'in kıyafet paletine
uzaklığı ölçüldü:

| en yakın üç kıyafet | uzaklık | seviye |
|---|---|---|
| #5 lacivert | 40.7 | riskli |
| #11 mor | 45.8 | uygun |
| #14 lacivert | 69.3 | uygun |

Hiçbiri "engel" bandında (< 25) değil. #14'teki gri yamalar kör noktadan
değil, §25.5'teki RGB filtresinden geliyordu ve **ücretsiz** çözüldü.

**Karar: çoklu base ŞİMDİLİK yapılmıyor**, ama fikir doğru ve yordamı yazılı.
Tetikleyici net: `base_conflict()` bir kıyafette **uzaklık < 25** raporlarsa
(yükleme akışı bunu zaten ücretsiz kontrol ediyor), tek çözüm o kıyafeti farklı
renge boyanmış bir base'den üretmek olur. O gün geldiğinde:

1. `base.png`'nin kıyafet maskesi zaten hesaplanıyor (krom < 15, §19.1)
2. Maske hedef renge boyanır → `base_<renk>.png`, **geometri aynı**
3. Katman o base'e karşı çıkarılır, `base_display.png` üzerinde gösterilir
4. `layers` tablosuna hangi base'in kullanıldığı yazılmalı (şu an tek base
   varsayılıyor)



"Mavi çizgiler geometriden gelir, model değiştirmek çözmez" dedim. Geometri
argümanı doğruydu ama **eksikti**: sızıntının büyük kısmı geometriden değil,
modelin rengi yanlış üretmesinden geliyordu. Kullanıcının "daha iyi model
çözer" sezgisi doğru çıktı.

Ders §6.1'in kardeşi: *doğru bir mekanizma açıklaması, o mekanizmanın baskın
sebep olduğunu kanıtlamaz.* İkisi ayrı iddia ve ikincisi ölçüm ister.

---

---

## 26. Faz 6 — düzenleme sohbeti ("kolları kıvır", "sola dön")

Faz 4'ün render'ı bir FOTOĞRAF. Bu özellik onun üzerinde konuşma gibi
çalışıyor: kullanıcı yazıyor, model uyguluyor, sonuç bir sonraki talimatın
girdisi oluyor.

```
render (m1_6-8.png)
  └─ "kolları kıvır"          → m1_6-8_e1.png
       └─ "hafifçe sola dön"  → m1_6-8_e2.png
```

FASHN'ın `edit` uç noktası (şema dokümandan doğrulandı: `model_name: "edit"`,
zorunlu `image` + `prompt`). Katman hattıyla ilgisi yok — burada çıkarım
yapılmıyor, sonuç doğrudan gösteriliyor, dolayısıyla §7'nin hiçbir kusuru
devreye girmiyor.

**Üç tasarım kararı, üçü de bu projenin daha önce ödediği bedellerden:**

| karar | gerekçe |
|---|---|
| Zincir **diske** yazılıyor (PNG + JSON), belleğe değil | §23.4: bellekteki iş kaydı sunucu yeniden başlayınca kayboldu ve ÜCRETLE üretilmiş bir sonuç "kayıp" göründü |
| Geri alma dosyayı **SİLMİYOR**, sadece zincirden düşürüyor | Ödenmiş bir görüntüyü silmek, parayı çöpe atmanın en sessiz yolu. `redo` onu ücretsiz geri getiriyor |
| Anahtar regex ile doğrulanıyor | Zincir dosya adına gömülü ve anahtar istemciden geliyor — yol enjeksiyonu |

**Ücret koruması iki katmanlı:** boş/çok uzun talimat hem istemcide hem
sunucuda, **çağrı yapılmadan** reddediliyor. `plan()` sağlayıcıya hiç
dokunmuyor (render.plan ile aynı kural).

| uç nokta | işi |
|---|---|
| `GET /api/edit/{key}` | zincirin durumu + kredi (ücretsiz) |
| `GET /api/edit/{key}/current.png` | zincirin sonundaki görüntü |
| `POST /api/edit/{key}` | talimat uygula (ÜCRETLİ, arka planda) |
| `POST /api/edit/{key}/undo` · `/redo` · `/reset` | geçmişte gezinme |

Arayüzde: render'ın altında sohbet kutusu, hazır öneri çipleri (kolları kıvır ·
içine sok · hafif sola dön · stüdyo ışığı), geçmiş listesi (bir adıma tıklayınca
o hali gösteriyor), geri al / başa dön. `Ctrl+Enter` gönderiyor.

**Maliyet:** düzenleme başına 2 kredi (balanced+1k), ~15-25 sn.

**Test:** 23 test (`tests/test_edits.py`), ağa çıkmadan. Ağırlık para ve veri
kaybında: boş talimatta çağrı yapılmadığı, geri almanın dosya silmediği,
zincirin diskte kaldığı, ikinci talimatın birincinin SONUCUNA uygulandığı.

---

---

## 27. Bu oturumda yapılanlar (§26 sonrası)

Sıkıştırılmış kayıt. Her madde kodda gerekçesiyle yorumlanmış durumda.

### 27.1 Para kaybettiren iki hata — ikisi de düzeltildi

**A) Üretilen render bulunamıyordu.** `get_provider()` varsayılanı fashn'a
çevrildiğinde `render.DEFAULT_RENDER_PROVIDER` sabiti `"fal"` kaldı. Web
katmanı anahtarı "fal"a göre (`m1_7-10`), `render_outfit` ise sağlayıcıyı
fashn'a çözüp dosyayı `m1_7-10_fashn.png` yazıyordu. **Aynı istek iki farklı
anahtar üretti**; render üretildi, ücretlendi, arayüz "yok" sandı.

Düzeltme: `_render_provider` artık `None` dönmüyor, sağlayıcıyı **nesne**
olarak çözüyor — anahtar ve çağrı aynı nesneden türüyor. Ayrıca
`render.cached_key()` eklendi: "var mı" değil **diskteki dosyanın anahtarını**
döndürüyor, ve sağlayıcıya özel ad yoksa eski eksiz ada da bakıyor (fal
döneminden kalan ücretli renderlar kaybolmasın).

**B) Testler kullanıcının düzenleme zincirlerini siliyordu.** `edits.py`
`RENDER_DIR`'i import anında alıyordu; `conftest` yalnızca
`wardrobe.render.RENDER_DIR`'i yönlendirdiği için `clear_cache()` çağıran her
test GERÇEK `data/renders`'a uzanıyordu. **§6.1 #8 ve #13'ün ÜÇÜNCÜ tekrarı.**
Yol artık çağrı anında çözülüyor (`edits.RENDER_DIR()`), ve bunu kanıtlayan
iki test var.

> Kalıcılık ölçüldü: sunucu kapat → `pytest` → yeniden başlat sonrası
> 5 render + 25 katman + 15 kırpık + 18 fotoğraf + manken + DB, **hepsinin
> hash'i aynı, kayıp 0.**

### 27.2 Düzenleme sohbeti — sürüm geçmişi

Kullanıcı bildirdi: *"eskiye basınca yeniye dönemiyorum."* Sebep tasarım
hatasıydı — bir sürüme tıklamak zinciri KESİYOR ve sonraki adımların kaydını
siliyordu. Dosyalar duruyordu ama kayıt gidince dönüş yolu kalmıyordu.

Kayıt biçimi değişti: `{"steps": [tüm sürümler], "selected": n}`. Seçim ayrı
tutuluyor, geçmişe dokunmuyor. `parent` alanı dallanmayı taşıyor: 1'e dönüp
yeni talimat yazılırsa yol `1 → 4` olur, 2 ve 3 geçmişte durur.

Eklenenler: **film şeridi** (mankenin altında, küçük görsellerle, `?w=140` ile
1207 KB → 35 KB), **İleri →** düğmesi, eski düz-liste biçimini okuma.

### 27.3 Türkçe talimat desteği

FASHN'ın prompt örneklerinin hepsi İngilizce. Türkçe gönderip sonucun sessizce
kötüleşmesi en kötü hata türü (çağrı ücretli, hata "model beceremedi" gibi
görünür). `vision.translate_prompt()` eklendi — Claude Haiku, ~$0.0001, ~1 sn.

Üç kural: Türkçe harf yoksa çeviri denenmez · çeviri patlarsa özgün metin
gider (asla fırlatmaz) · **geçmişte kullanıcının yazdığı cümle durur**, çeviri
`sent` alanında ayrı.

### 27.4 Yaka etiketi — prompt ile çözüldü

Flat-lay'de arka yaka öne kıvrılınca ense etiketi ("FENERIUM", "ALLSAINTS")
fotoğrafın parçası oluyor ve model onu sadakatle çiziyor. Kırpıkla render yan
yana konarak kanıtlandı: **model uydurmuyor.**

`FASHN_TRYON_PROMPT` eklendi ve ölçüldü (aynı tohum, tek değişken prompt):
etiket ve lacivert iç yaka **tamamen kayboldu**. `prompt=""` ile kapatılabiliyor
(A/B için). Semptomu kapatıyor, sebebi değil — kaynak hâlâ kırpıkta.

### 27.5 Tek çağrıda iki kıyafet — DENENDİ, OLMADI

İki kırpık tek "kombin flat-lay"ine birleştirilip tek çağrı yapıldı (2 kredi).
**Model yalnızca ÜSTÜ giydirdi**, şortu yok saydı — bacaklarda base'e göre fark
7.0 (zincirlemede 47.4), yani orada hiçbir şey değişmemiş. `product_image`
tekil ve `category` parametresi yok, "bu tam kombin" denemiyor.

> Ölçümün drift kısmı GEÇERSİZ: zincirleme render eski oturumdan `fal/v1.6`
> ile üretilmişti, tek çağrı `tryon-max`. Karşılaştırma strateji değil model
> farkını ölçtü.

### 27.6 Arayüz — moda editoryal görünüm

Koyu tema → **kırık beyaz** (`#F6F5F1`), keskin hat (`border-radius: 0`), iki
tipografi ailesi (serif/italik başlık + sans veri). Sayfa **ortalandı**
(1920 px'de mankenin iki yanında 770 px boşluk vardı → 144 px).

Yol boyunca çıkanlar:
- İlk seçilen gri **3.5-3.8:1** kontrast veriyordu (WCAG AA eşiği 4.5) →
  koyulaştırıldı, hepsi ≥4.8:1
- Dolap panelindeki **yatay kaydırma çubuğu** düzeldi: grid öğelerinin
  `min-width: auto` değeri `nowrap` başlığın sütunu genişletmesine izin
  veriyordu
- Başlık aralığı kuralı `:not(:first-child)` ile yazılmıştı ve sarmalayıcı
  içindeki başlıklara uygulanmıyordu ("DÜZENLE" düğmenin üstüne biniyordu) →
  kural tersine çevrildi: boşluk varsayılan, sıfırlama istisna
- Yan paneller genişletildi (300→360, 340→400) + iki kırılma noktası: dar
  ekranda **önce paneller** geri çekiliyor, manken en son (1280 px'de manken
  375 → 473)

### 27.7 Önbellek: başlık değil URL

Katmanlar sık yeniden üretiliyor ama URL'ler sabitti → tarayıcı eski görseli
gösteriyordu. Üç katman da kapatıldı: görsellere `?v=<mtime>`, statik
dosyalara `no-cache`, `/` varlık URL'lerine sürüm damgası basıyor.

> `no-cache` başlığı TEK BAŞINA yetmedi: tarayıcı dosyayı başlık eklenmeden
> önce önbelleğe aldıysa eski politikaya uyuyor, zorla yenilemek bile
> yetmiyor. **Önbellek geçersizleştirmesi başlıkla değil URL ile yapılır.**

### 27.8 Şablonlar: 5 → 22

Aksesuar (saat · bileklik · kolye · şapka · kasket · bere · çanta · kemer ·
atkı), kadın kıyafetleri (elbise · tulum · etek · tayt · crop · askılı) ve dış
giyim (ceket · mont). Açılır menü kategoriye göre gruplandı.

**Gözden kaçmış boşluk:** `elbise` ve `dis_giyim` kategorileri baştan beri
tanımlıydı ama HİÇ şablonu yoktu — elbise yükleyen "Tişört" seçmek zorunda
kalıyor, kurtarma önseli eteği kesiyordu. Test eklendi: her kategorinin en az
bir şablonu olmalı (ayakkabı hariç).

**Kaplama eşiği kategoriye bağlandı** (`layers.coverage_range`). Bir saat
tuvalin ~%0.2'sini kaplar; tek eşikle (%0.8) katman doğru üretilse bile
"neredeyse boş" uyarısı alınıyordu — sayı doğru, yorumu yanlış.

### 27.9 Diğer

- **Katman kaynağı tembel üretiliyor.** `ensure_composite` her kombin
  seçiminde 1.5 MB yazıyordu; kullanıcı gezerken 18 dosya / 27 MB birikmişti.
  Artık ancak gerçekten düzenleme yapılınca üretiliyor.
- **Düzenleme kaynağı seçilebiliyor:** katman görüntüsü (bedava zemin, toplam
  2 kredi) veya gerçekçi render (temiz zemin, 4+2 kredi).
- `conftest` artık TÜM sağlayıcı anahtarlarını siliyor — sağlayıcı seçimi
  testleri geliştiricinin `.env`'ine bağlıydı.

---

## 28. Çoklu manken (A planı) — ✅ YAPILDI

Kullanıcının kararı: **birden çok base manken yan yana yaşasın.** Her mankenin
kendi katman seti olur, aralarında geçiş yapılır, hiçbiri silinmez.

**Sonuç: yapıldı, ölçüldü, kredi harcanmadı.** Kabul ölçütlerinin doğrulaması
§28.6'da; aşağıdaki 28.1-28.5 tasarım notları olarak duruyor (uygulama onlara
uydu, sapmalar §28.6'da açıkça yazılı).

### 28.1 İyi haber: şema ZATEN hazır

`db.py`'deki tasarım Faz 5'i öngörmüş:

| yapı | durum |
|---|---|
| `mannequins` tablosu (`id`, `name` UNIQUE, `kind`, `image_path`, `params_json`) | ✅ var |
| `layers` PK = (`garment_id`, `mannequin_id`) | ✅ **zaten manken başına** |
| `layers.raw_path(garment_id, mannequin_id)` | ✅ zaten anahtarlı |
| `render.cache_key` → `m{mid}_...` | ✅ zaten anahtarlı |

Yani **veri modeli değişmiyor.** Değişmesi gereken, "tek base var" varsayan
yerler.

### 28.2 Değişmesi gerekenler

| yer | bugün | olması gereken |
|---|---|---|
| `mannequin.get_base()` | `WHERE name='base'` | AKTİF mankeni döner |
| `mannequin._save()` | `UPDATE ... WHERE name='base'` (**üzerine yazıyor**) | yeni satır ekler |
| `MANNEQUIN_DIR / "base.png"` | sabit ad | `base_{id}.png` |
| `display_base_path()` | sabit `base_display.png` | `base_{id}_display.png` |
| `_invalidate_layers()` | manken değişince siler | yalnızca AYNI mankenin fotoğrafı değişirse |
| `render.clear_cache()` | TÜM renderları siler | yalnızca o mankeninkileri (`m{mid}_*`) |
| `edits.clear_all()` | tüm zincirleri siler | aynı şekilde manken bazlı |

"Aktif manken" için en basit yol: `mannequins` tablosuna `is_active INTEGER
DEFAULT 0` sütunu + `db.MIGRATIONS`'a ekleme (yordam §21'de kurulu, idempotent).

### 28.3 Uç noktalar ve arayüz

```
GET    /api/mannequins            → liste (id, ad, küçük görsel, katman sayısı, aktif mi)
POST   /api/mannequins            → yeni base fotoğrafı yükle (ücretsiz)
POST   /api/mannequins/{id}/aktif → aktif olanı değiştir (ücretsiz, hiçbir şey silmez)
DELETE /api/mannequins/{id}       → sil (⚠ o mankenin katmanları+renderları gider, ONAY ŞART)
GET    /api/mannequins/{id}.png   → küçük görsel
```

Giriş ekranı: mankenler ızgarada, her birinin altında "N katman hazır". Birini
seç → mevcut ekran. "+ Yeni manken" → fotoğraf yükle → hizalama yok, doğrudan
`from_photo`. Aktif manken varsa ekran atlanabilir (`?manken=` ya da localStorage).

### 28.4 TUZAKLAR — bunları atlama

1. **Türetilmiş yolu modül seviyesinde SABİTLEME.** Bu projede aynı hata üç
   kez oldu (§6.1 #8, #13, §27.1-B). `display_base_path()` zaten fonksiyon;
   yeni yollar da fonksiyon olmalı, `conftest` yönlendirmesini delmesinler.

2. **Manken DEĞİŞTİRMEK ile FOTOĞRAFINI DEĞİŞTİRMEK farklı.** Birincisi hiçbir
   şey silmemeli (asıl amaç bu), ikincisi o mankenin katmanlarını geçersiz
   kılmalı. `_save()` şu an ikisini ayırmıyor.

3. **Silme geri alınamaz ve ÜCRETLE üretilmiş veriyi yok eder.** Bir mankenin
   ~30 kredilik katmanı olabiliyor. Onay ekranında kaç katman/render
   silineceği YAZMALI.

4. **Eski veri korunmalı.** Mevcut `base` satırı, `base.png`, `base_display.png`
   ve `m1_*` renderlar çalışmaya devam etmeli. Migration'da mevcut satır
   `is_active=1` işaretlenmeli; dosya adları için ya eski adları da kabul et ya
   da tek seferlik yeniden adlandır.

5. **`conftest`'e izolasyon eklemeyi unutma.** Yeni bir dizin/dosya deseni
   eklenirse testler gerçek veriye uzanır — bu projenin en pahalı hata sınıfı.

### 28.5 Kabul ölçütü

- İki manken tanımlı, aralarında geçiş yapılıyor ve **hiçbir katman silinmiyor**
- Geçiş sonrası `pytest` + sunucu yeniden başlatma sonrası ikisinin de
  katmanları/renderları duruyor (parmak izi karşılaştırmasıyla)
- Yeni manken eklemek ücretsiz; katman üretimi ayrı ve açıkça ücretli
- Mevcut mankenin verisi bozulmuyor

### 28.6 UYGULAMA — ne yapıldı, ne ölçüldü

**Şema gerçekten değişmedi.** §28.1'in iddiası doğru çıktı: `layers`'ın birincil
anahtarı zaten `(garment_id, mannequin_id)`, `raw_path` ve `render.cache_key`
zaten manken kimliğini taşıyordu. Eklenen tek sütun `mannequins.is_active`.

Yani iş, "tek base var" varsayan **yedi yeri** düzeltmekti — hepsi §28.2'nin
tablosundaki yerler:

| yer | önce | sonra |
|---|---|---|
| `mannequin.get_base()` | `WHERE name='base'` | aktif manken (`_row`) |
| `layers._base_mannequin_id` | ayrı sorgu, `name='base'` | `mannequin.active_id()` |
| `render._base_mannequin_id` | ayrı sorgu, `name='base'` | `mannequin.active_id()` |
| `web._layers_by_garment` | JOIN + `m.name='base'` | `mannequin_id = active` |
| `mannequin._save()` | **UPDATE — üstüne yazıyordu** | `name` verilirse INSERT |
| `display_base_path()` | sabit `base_display.png` | görselin adından türüyor |
| `render.clear_cache()` | TÜM renderları silerdi | `m{mid}_*` |
| `edits.clear_all()` | TÜM zincirleri silerdi | `m{mid}_*` |

**Aktif manken kimliği TEK YERDEN geliyor** (`mannequin.active_id`). Üç ayrı
modül aynı `SELECT ... WHERE name='base'` sorgusunu kopyalamıştı; çoklu
mankende bu, üçünün ayrı zamanlarda farklı cevap vermesi riskiydi. §27.1-A'nın
dersi bire bir buraya uyuyor: *aynı anahtarı iki yerde hesaplarsan er geç
ayrışırlar ve ödenmiş bir dosya "kayıp" görünür.*

#### Ölçülen sonuç — kabul ölçütünün dördü de sağlandı

Yöntem: `data/` klasörünün SHA-256 parmak izi alındı, işlemler yapıldı, tekrar
alındı ve karşılaştırıldı.

| adım | kayıp dosya | değişen dosya |
|---|---|---|
| `pytest` (329 test) | **0** | **0** |
| Yeni manken ekleme (API'den) | **0** | 0 (+2 yeni: `base_135.png`, `base_135_display.png`) |
| **11 kez manken geçişi** (ileri-geri) | **0** | **0** |
| Sunucu yeniden başlatma | **0** | **0** |
| `pytest` (tekrar) | **0** | **0** |

Geçişten sonra `base` mankeninin **11/11 katmanı** yerinde ve arayüzde
görünüyor. Tarayıcıda da doğrulandı (iddia edilmedi): manken kartına tıklandı,
dolap 11 hazır → 11 "katman yok"a döndü, geri dönünce 11 hazıra geri geldi;
zemin görüntüsü ikisinde de doğru mankeni gösterdi.

**Harcanan kredi: 0.** Manken eklemek ve geçiş yapmak yalnızca dosya işlemi.

#### İki tuzak ölçümle çözüldü

**1. Zemin görüntüsü bayatlıyordu — damga yetmiyor.** `/api/base.png` sabit bir
adres ve aktif mankene göre farklı dosya servis ediyor. Önbellek damgası
dosyanın mtime'ı olduğu için iki mankenin gösterim base'i **aynı saniyede**
üretilmişse damgalar eşit çıkıyor, URL değişmiyor ve tarayıcı manken
değiştirmiş kullanıcıya **eski zemini** gösteriyor. URL'ye manken kimliği de
konuldu (`?m=1&v=…`). §25.7'nin kuralının doğrudan uygulaması: *önbellek
geçersizleştirmesi başlıkla değil URL ile yapılır* — ve burada mtime tek başına
bir "URL" oluşturmuyordu.

**2. Dosya adlandırma kuralını topluca değiştirmek veri kaybıdır.** İlk akla
gelen `base_{id}.png` düzenini herkese uygulamaktı. O durumda mevcut
`base.png`, `base_display.png` ve onlara bağlı 11 katman bir anda "kayıp"
olurdu. Bunun yerine: **ilk manken eski adını koruyor**, yenileri
`base_{id}.png` alıyor; gösterim base'inin adı da görselin adından türüyor
(`base.png` → `base_display.png`, `base_135.png` → `base_135_display.png`).
Sonuç: geçişte **tek bir dosya bile yeniden adlandırılmadı.**

#### §28.4'ün tuzaklarına ne oldu

| tuzak | durum |
|---|---|
| 1. Türetilmiş yolu modül seviyesinde sabitleme | `image_path_for()` ve `display_base_path()` **fonksiyon**; `MANNEQUIN_DIR`'e her çağrıda bakıyorlar. Test: `test_yeni_manken_yollari_izole_dizinde` |
| 2. Manken DEĞİŞTİRMEK ≠ FOTOĞRAFINI DEĞİŞTİRMEK | `_save(name=…)` ile ayrıldı. İki test bunu karşılıklı doğruluyor: eklemek eskiyi bozmuyor, fotoğraf değiştirmek YALNIZCA o mankeni geçersizliyor |
| 3. Silme geri alınamaz | `usage()` kaç katman/render/düzenleme gideceğini sayıyor; hem CLI onayında hem arayüz `confirm`'ünde yazıyor. Ayrıca **son manken silinemiyor** ve aktif silinirse yerine otomatik biri geçiyor |
| 4. Eski veri korunmalı | Yukarıdaki adlandırma kararı + `_ensure_active_mannequin` migration'ı. Test: sütunsuz eski bir DB kurulup `init_db` sonrası aktif mankenin doğru işaretlendiği ölçülüyor |
| 5. `conftest` izolasyonu | Yeni dosya desenleri zaten `MANNEQUIN_DIR`/`LAYER_DIR`/`RENDER_DIR` altında, üçü de yönlendirilmiş. Parmak izi karşılaştırması bunu kanıtladı (0 değişiklik) |

**Migration'ın sessiz tehlikesi:** `is_active` sonradan eklendi ve varsayılanı
`0`. O hâliyle bırakılsaydı mevcut veritabanında **hiçbir manken aktif
olmayacaktı** — dosyalar yerinde durur, ama `get_base()` `None` döner ve ücretle
üretilmiş 11 katman bir anda erişilemez görünürdü. `db._ensure_active_mannequin`
tam olarak bunun için var: aktif yoksa en eskiyi işaretliyor, birden fazla aktif
varsa tekile indiriyor. Idempotent, her açılışta çalışıyor.

#### Arayüz: giriş ekranı değil, kalıcı şerit (§28.3'ten SAPMA)

§28.3 "girişte bir seçim ekranı" öngörüyordu. Uygulamada **sahne panelinin
üstünde her zaman görünen bir şerit** yapıldı. Gerekçe: aktif manken her zaman
tanımlı olduğu için giriş ekranı §28.3'ün kendi kuralıyla ("aktif manken varsa
ekran atlanabilir") **hep atlanırdı** — yani yazılan ekran neredeyse hiç
görünmezdi. Şerit aynı işi yapıyor ve kullanıcı hangi zemin üzerinde olduğunu
her an görüyor.

Film şeridiyle (§27.2) bilerek aynı görsel dil: küçük kareler, aktif olan
mürekkep çerçeveli. İkisi de "hangi sürümdeyim" sorusunu cevaplıyor.

> Bu bir tasarım kararı, ölçüm değil — kullanıcı giriş ekranını isterse şerit
> kalabilir ve üstüne eklenebilir.

Katmanı olmayan manken **gizlenmiyor, işaretleniyor** ("katman yok", turuncu) —
§14'teki "katmanı olmayan kıyafet" kuralının aynısı: kullanıcı mankeni
eklediğini biliyor, listeden düşmesi hata gibi görünürdü.

#### Ücret sınırı nereye çizildi

| işlem | ücret |
|---|---|
| Manken eklemek, geçmek, listelemek, silmek | **0** |
| Yeni mankende katmanları üretmek | 11 kıyafet × 2 kredi ≈ **22 kredi** |

İkisi bilerek **ayrı işlem**. Tek düğmeye bağlansaydı "+ Yeni manken" sessizce
22 kredilik bir işlem olurdu. Bir test bunu kilitliyor: manken ekleme yolunda
`build_layer` çağrılırsa test kırılıyor.

---

## 29. Sırada ne var

**Önce iki karar kullanıcının:**

1. **`Stüdyo` mankeninde katman üretilsin mi?** (~22 kredi, ~78 kredi var)
   Şu an 0 katmanı var, yani seçilince dolap boş görünüyor. Üretmek:
   ```
   python cli.py mannequin --use 135
   python cli.py build-layers            # ÜCRETLİ, ~22 kredi
   ```
   İstenmezse silmek de bedava: `python cli.py mannequin --rm 135`
   (o mankende ücretle üretilmiş hiçbir şey yok, kayıp 0).

   > ⚠ Yeni base bir **Gemini üretimi** ve kıyafeti açık renkli. Katman
   > üretmeden önce `base_conflict` kontrolüne bak: base'in kıyafet rengi
   > dolaptaki kıyafetlere yakınsa o kıyafetler kör noktada kalır (§7.4).
   > Bu kontrol ücretsiz ve yükleme akışında zaten var.

2. **`git init` yapılmış ama hâlâ hiç commit yok.** §23'teki kodlama kazası
   bunu somutlaştırmıştı: geri dönülecek bir sürüm yoktu. Bu turda `data/`
   yedeklendi (`data_yedek_20260813_1550`) ama kod için hâlâ ağ yok.

**Sonra sıradakiler:**

3. **Kutu doluluğu uyarısı** (§31.1) — bu turda kullanıcı istemedi ama tek
   ayıran sinyal buydu: #16 %86.9, sağlamların en yükseği %77.7. Eşik değil
   UYARI olarak eklenmeli (tek örnekle eşik konmaz, §20.1).
4. **Otomatik hizalama** — §31'den sonra artık sadece konfor: kırpma zaten
   hizalamadan bağımsız. rembg'in maskesinden ölçek/konum hesaplanıp kıyafet
   tuvale kendiliğinden oturtulabilir.
5. Saat/aksesuarın gerçekten çalıştığını ölçmek (2 kredi) — şablonlar hazır ama
   tryon-max'in saati bileğe doğru yerleştirdiği **denenmedi**.
6. Ayakkabı için base'i tam boy yeniden çekmek (base diz altından kesik, §10).
7. §18.2'nin üç yollu karşılaştırması: `tryon-ab <id> --gemini`, ~$0.23.
8. Faz 3 (AI kombin önerisi) — dolap büyüyünce.

**Çoklu mankenin açtığı yeni imkân:** §25.6'daki "çoklu base" fikri artık
uygulanabilir. Orada tetikleyici netti — `base_conflict()` bir kıyafette
**uzaklık < 25** raporlarsa o kıyafet farklı renkte bir base'den üretilmeli.
Şema ve arayüz artık buna hazır; eksik olan tek şey, aynı görüntünün yeniden
renklendirilmiş bir kopyasını **ayrı manken kaydı** olarak açmak (§25.6'nın
4. maddesi "layers tablosuna hangi base'in kullanıldığı yazılmalı" diyordu —
o artık zaten yazılıyor).

---

## 30. Kategori bölge kapısı — pantolonun yüzüne çizdiği hayalet yüz ✅

**Belirti:** kullanıcı chino pantolon (#16) ekledi; katman `ready` çıktı, hata
yok, ama kombinde mankenin **yüzüne ikinci bir hayalet yüz** ve omzuna mavi bir
yama çiziliyordu.

### 30.1 Kök sebep — üç yanlış adres elendi

| şüpheli | ölçüm | sonuç |
|---|---|---|
| Çekim şablonu oturmamış | Şablon önseli **yalnızca kurtarma**: kırpık kadraj kenarına dayanmazsa hiç çalışmıyor. #16'da dayanmıyordu → şablon hiç kullanılmadı | ❌ suçsuz |
| Kırpma bozuk | rembg temiz kesmiş: %25.1 kaplama, kadraj kenarına değmiyor | ❌ suçsuz |
| **Model kıyafet dışını yeniden üretti** | base'e göre fark: **gövde %52.8**, **yüz %48.5** (aynı hattan geçen şortta %5.2 ve %30.1) | ✅ **sebep** |

Base **şort** giyiyor. Uzun pantolon giydirmek, model için bacakların tamamını
(kalçadan bileğe) yeniden çizmek demek — ve tryon-max bunu yaparken gövdeyi ve
yüzü de yeniden üretti. Fark tabanlı çıkarım bunu sadakatle "değişen piksel =
kıyafet" saydı.

Katmanın dikey dağılımı sebebi tek bakışta gösteriyordu:

| kıyafet | bacakta | belden yukarıda | dikey yayılım |
|---|---|---|---|
| #6, #7, #15 şortlar | **%100** | %0 | y %55-84 |
| **#16 chino** | %69.3 | **%23.9** | y **%2-100** |

y %2 = kafanın tepesi. Pantolonun orada işi yok.

### 30.2 Çözüm: konuma bak, renge değil

`config.CATEGORIES` her kıyafetin hangi vücut bölgesini kapladığını **zaten**
söylüyordu (`slots`). Kapı bunu kullanıyor: kıyafetin fiziksel olarak
olamayacağı dikey banttaki piksseller atılıyor.

**Bu filtrenin öncekilerden farkı ve neden bu sefer tuttu:** §6.2'deki
`color_filter`, `drop_base_leak` ve §7.6'daki `drop_base_clothing` — üçü de
RENGE bakıyordu ("bu piksel kıyafete mi base'e mi benziyor") ve üçü de
gölgedeki gerçek kıyafet piksellerini yiyordu. Bu filtre renge **hiç**
bakmıyor, KONUMA bakıyor — ve konum, rengin aksine, gölgeden etkilenmiyor.

§17'nin dersinin aynısı: algoritmaya *nerede olmadığını* değil **nerede
olabileceğini** söylemek.

**Bant `slots`'tan türüyor, ayrı bir tablodan değil.** Faydası elbisede
görünüyor: `slots("elbise") == ("ust", "alt")` olduğu için elbisenin bandı
ikisinin birleşimi olarak kendiliğinden çıkıyor. Ayrı bir kategori→bant tablosu
`CATEGORIES` ile sessizce ayrışabilirdi (§14 ilkesi).

> ⚠ `vton.SLOT_BANDS` ile KARIŞTIRMA. O tablo mock sağlayıcının kıyafeti
> yapıştıracağı kutu ve dar: `ust` için (0.20, 0.55). Gerçek üst katmanlar
> y %73'e kadar iniyor — o tabloyu kapı olarak kullanmak **sağlam katmanları
> keserdi.** İki tablo benzer isimli ama iki ayrı soruya cevap veriyor:
> "nereye yapıştırayım" ve "nerede OLABİLİR".

Bant sayıları dolabın gerçek katmanlarından ölçüldü (8 üst: y %22-73 · 3 şort:
y %55-84) ve cömertçe genişletildi. Güvenlik freni var: kapı maskenin
%40'ından fazlasını yerse **hiç uygulanmıyor** — §17'deki önselin freniyle aynı
mantık, sessizce boş katman üretmemek için.

### 30.3 Ölçülen sonuç

`--reextract` ile tüm dolap **bedava** yeniden çıkarıldı (0 kredi):

| | kaplama önce | kaplama sonra | dikey yayılım |
|---|---|---|---|
| 11 sağlam katman | — | **birebir aynı** | değişmedi |
| **#16 chino** | %22.06 | **%18.71** | y %2-100 → **y %46-100** |

"Birebir aynı" iddiası SHA-256 ile doğrulandı: 12 katmanın 11'i yedekle
**bit düzeyinde özdeş**, yalnızca #16 değişti. Yani filtre tam olarak ihtiyaç
duyulduğu yerde çalışıyor, başka hiçbir yere dokunmuyor — §6.2'de çöken üç
denemenin yapamadığı şey bu.

Görsel: hayalet yüz, omuzdaki mavi yama ve duvardaki gri leke tamamen kayboldu.

### 30.4 Bir iddiam ölçümle ÇÜRÜDÜ — kapının hattaki yeri

Kapıyı `largest_component`'ten **önce** koydum ve gerekçesi makuldü: çöp
pantolona bağlı olduğu için bileşen etiketleme ikisini tek parça görüyor, kapı
önce gelirse bağlantı kopar. Yorum satırına "sonraya koymak işe yaramazdı"
yazdım. **Ölçtüm ve yanlıştı:**

| yerleşim | kaplama | yayılım | bağlı parça |
|---|---|---|---|
| kapı yok | %22.06 | y %2-100 | 33 |
| kapı **sonda** | %18.72 | y %46-100 | 12 |
| kapı **önce** (mevcut) | %18.71 | y %46-100 | 12 |

İki yerleşim arasındaki fark **46 piksel** — kapının kestiği köprünün bant
içinde kalan güdüğü. "Önce" hâlâ biraz daha temiz, o yüzden öyle kaldı; ama
asıl kazanç kapının kendisi, yerleşimi değil.

**Ders (§25'in kardeşi):** *doğru bir mekanizma açıklaması, o mekanizmanın
baskın sebep olduğunu kanıtlamaz.* Testlerin docstring'i de düzeltildi — eski
hâli "kapı sonraya konursa bu test kırılır" diyordu ve bu doğru değildi, yani
test kendi kanıtladığından fazlasını iddia ediyordu.

### 30.5 Kalan iş: şablon/hizalama akışı — §31'de ÇÖZÜLDÜ

> Aşağıdaki not §31'den ÖNCE yazıldı ve kısmen yanıldı: hizalamanın "tamamen
> boş olmadığı" doğruydu ama yönü tersti — hizalama kırpmayı iyileştirmiyor,
> **bozuyordu**. Ölçüm §31'de.

Kullanıcının ikinci sorusu ("şablonlar oturmuyor, kendi analiz edip
kırpamaz mı?") **haklı ve hâlâ açık.** Ölçülmüş durum:

- Şablon önseli yalnızca kurtarma olarak çalışıyor → çoğu fotoğrafta
  kullanıcının şablona oturtmak için harcadığı emek kırpmayı hiç etkilemiyor.
- Ama hizalama tamamen boş da değil: #16'nın orijinal fotoğrafında pantolon
  kadraja sığmıyordu, kullanıcı %53'e küçültünce sığdı.

**Önerilen (denenmedi):** rembg zaten kıyafeti buluyor. Maskesinin sınırlayıcı
kutusundan ölçek ve konum **hesaplanabilir** — kıyafet tuvale kendiliğinden
ortalanıp sığdırılır, manuel panel "otomatik yanlışsa düzelt" olarak kalır.
İkinci bir segmentasyon gerekmiyor (bir kez kes, kutuyu ölç, RGBA'yı dönüştür),
yani maliyeti **0**. Şablon seçimi de Claude'un zaten döndürdüğü kategoriden
gelebilir.

> Bu iş pantolon kusurunu çözmezdi (kırpık zaten temizdi) — ayrı bir kazanç:
> kullanıcının emeği + kadraja sığmayan fotoğrafların kırpığı. §20.1'de katlı
> çekilmiş bir tişörtün modele "düğme patı" çizdirdiği vaka, bozuk girdinin
> ne kadar pahalı olabildiğini gösteriyor.

**⚠ "kırpık zaten temizdi" YANLIŞTI — bkz. §31.** Kırpığı önizlerken RGBA'yı
RGB'ye çevirmiştim, yani alfayı düşürüp maskesiz orijinale bakmıştım. Kullanıcı
dolap kartına bakıp "bir tek bu kırpık değil" dedi ve haklıydı.

---

## 31. Kırpmayı bozan şey HİZALAMANIN KENDİSİYMİŞ ✅

**Kullanıcının tespiti:** dolap kartlarında chino pantolon (#16) diğerlerinden
farklı görünüyordu — çizgili çarşaf ve çiçekli perde kırpığın içindeydi.
Doğruydu. rembg kıyafet silueti yerine kaba bir **DİKDÖRTGEN BLOK** döndürmüş.

### 31.1 İki koruma da bunu kaçırdı — ve neden

| koruma | #16'da değeri | sağlam bandı | sonuç |
|---|---|---|---|
| Kaplama kontrolü | %25.1 | %15-70 | ✓ geçti |
| `touches_frame_edge` | False | — | ✓ geçti |
| **Kutu doluluğu** (ölçülmemişti) | **%86.9** | %53.7-77.7 | ✗ **tek ayıran** |

Blok dikdörtgen olduğu için sınırlayıcı kutusunu neredeyse tamamen dolduruyor.
§16'da aynı metrik kullanılmıştı ama yalnızca model karşılaştırmasında; yükleme
akışına bir uyarı olarak **eklenmedi** (kullanıcı bu turda istemedi). Tek örnek
olduğu için eşik de konmamalı — §20.1'in dersi.

### 31.2 Kök sebep: %53'e küçültmek segmentasyonu öldürüyor

Aynı fotoğraf, aynı model, tek fark hizalama:

| kaynak | model | kaplama | kutu doluluğu | sonuç |
|---|---|---|---|---|
| hizalanmış (ölçek 0.53) | isnet | %25.1 | **%86.8** | blok, zemin içeride |
| hizalanmış | u2net | %29.2 | %99.3 | daha kötü |
| **orijinal** | **isnet** | %42.2 | **%61.4** | **düzgün siluet** |
| orijinal + şablon önseli | isnet | — | %61.3 | en temiz |

Sebep: segmentasyon maskesi 1024 px çalışma çözünürlüğünde hesaplanıyor
(§16'da ölçülmüş bir karar). Fotoğraf %53'e küçültülünce kıyafet o tuvalde
~400 px'e düşüyor ve model küçük nesnede siluet çıkaramıyor.

**Acı ironi:** hizalama paneli (§21) tam olarak kırpmayı İYİLEŞTİRMEK için
yazılmıştı — şablon önseli kıyafete otursun diye. Ölçüm tersini gösterdi.

### 31.3 Düzeltme: önce kırp, sonra hizala

`ingest.add_garment`'in sırası değişti:

```
ESKİ:  foto → hizala → KIRP → öznitelik
YENİ:  foto → KIRP → hizala(kırpığın üstüne) → öznitelik
```

Kırpma artık kullanıcının panelde ne yaptığından **bağımsız**. Hizalama yine
uygulanıyor (kadrajlama ve şablon önizlemesinin anlamı korunuyor) ama artık
kırpma kalitesini ne iyileştirebiliyor ne bozabiliyor.

`imageutil.apply_align` de alfaya duyarlı hale geldi: RGBA girdide açığa çıkan
kenar **şeffaf** dolduruluyor. Zemin rengiyle doldurmak kıyafetin etrafına opak
bir çerçeve çizer ve o çerçeve VTON'a "kıyafetin parçası" olarak giderdi.

Hizalanmış 4 kıyafette eski/yeni sıra karşılaştırıldı (kutu doluluğu):

| kıyafet | ölçek | eski | yeni |
|---|---|---|---|
| #13 keten gömlek | 0.96 | %58.6 | %71.1 |
| #14 lacivert tişört | 0.79 | %75.2 | %62.1 |
| #15 bej şort | 0.79 | %66.3 | %76.7 |
| **#16 chino** | **0.53** | **%86.9** | **%58.1** |

Dördü de sağlıklı bandda; #16 blok olmaktan çıkıyor. Ölçek ne kadar küçükse
eski sıradaki hasar o kadar büyük — beklenen ilişki.

### 31.4 #16 onarıldı (2 kredi)

Kırpık orijinalden yeniden üretildi (`shape='pantolon'`, hizalama YOK):
kutu doluluğu **%86.9 → %61.3**, kadraj kenarına değmiyor, görsel olarak
düzgün pantolon silueti. `align_json` boşaltıldı — kayıt gerçeği yansıtmalı.

Katman yeniden üretildi (**2 kredi**, kullanıcı onayladı):

| | kaplama | dikey yayılım |
|---|---|---|
| eski kırpık, kapısız | %22.06 | y %2-100 |
| eski kırpık + bölge kapısı (§30) | %18.71 | y %46-100 |
| **yeni kırpık + kapı** | **%14.10** | **y %53-100** |

%14.10, şortların %8.8-9.2'siyle tutarlı (pantolon daha çok kaplar). Görselde
hayalet yüz, omuzdaki mavi yama ve pantolondaki soluk lekeler gitti.

**İki kusur üst üste binmişti ve biri diğerini gizliyordu:** bölge kapısı
hayalet yüzü temizledi ama modele hâlâ çarşaflı bir "kıyafet" veriliyordu.
Kapı olmasaydı kırpma hatası da bu kadar net görünmezdi. §6.1 #10-11'in
kardeşi.

### 31.5 Şablonların yeni rolü

Şablonlar KALIYOR ama kullanıcıdan artık **fotoğrafı şablona oturtması
beklenmiyor** — o emek ölçüldü ve kırpmayı etkilemiyordu (üstelik bozuyordu).
İki işi sürüyor:

1. **Çekim rehberi** — kolları açık ser, kadrajın ortasına koy, kenarlara
   boşluk bırak. §10 ve §20.1'deki kusurların ikisi de çekim hatasıydı.
2. **Kurtarma önseli** — kırpık kadraj kenarına dayanırsa devreye giriyor.
   §17'de bozuk bir modeli bile düzeltmişti. Hizalanmamış fotoğrafta da
   çalıştığı ölçüldü (#16: önselle %61.3, önselsiz %61.4 — üstelik önsel
   kalan tarak artefaktını temizledi).

> Yani "şablonsuz yapalım mı" sorusunun cevabı: **hayır, ama artık ona
> uymak zorunda değilsin.** Önsel arka planda, yalnızca gerektiğinde çalışıyor.

---

## 32. Yeni manken eklenince ekranı kaplayan gri dikdörtgen ✅

**Belirti:** kullanıcı kendi odasında çekilmiş bir fotoğrafı manken olarak
ekledi; sahnede kişinin arkasındaki gri pano **dev bir gri dikdörtgen** olarak
boyanmış çıktı.

**Sebep:** `build_display_base` base'in kıyafetini nötr koyuya boyuyor ve hangi
pikselin "kıyafet" olduğunu KROM (a*,b*) yakınlığıyla seçiyordu. Bu ölçüt
§19.1'de **ölçülerek** seçilmişti — ama o base'in kıyafeti doygun orta maviydi:

| base | kıyafet | duvar sol | duvar sağ | ten |
|---|---|---|---|---|
| orta mavi kıyafetli (1) | 1.2 | 30.2 | 35.8 | 46.6 |
| **koyu/siyah kıyafetli (139)** | 0.8 | **8.7** | **14.1** | **15.2** |

Eşik 15. İlkinde ayrım tertemiz; ikincisinde duvar **da** ten **de** eşiğin
altında/sınırında. Nötrlenen tuval oranı: **%43.7**.

**Kök sebep eşikte değil, ÖLÇÜLEN UZAYDA.** Neredeyse siyah bir kıyafetin krom
düzlemindeki yeri sıfıra yakın — gri bir duvarınki de öyle. Hangi eşik
seçilirse seçilsin bu ikisi komşu kalıyor. §19'un dersinin bir katman derini:
orada RGB'den kroma geçilmişti, burada krom da yetmiyor.

### 32.1 Çözüm yapısal: base'in kıyafeti tanım gereği KİŞİNİN ÜSTÜNDE

`cutout.person_mask()` eklendi (rembg ile ön plan maskesi). Nötrleme artık
kişiyle kesişiyor: duvar, kapı, zemin bir eşiğe hiç sorulmadan eleniyor.

§30'daki bölge kapısının aynı fikri — **renge değil konuma bakmak.** Bu projede
renk tabanlı filtre denemelerinin çoğu çöktü (§6.2 ×2, §7.6, §25.5); konum
tabanlı iki deneme de tuttu.

Ölçülen etki (nötrlenen tuval oranı):

| manken | önce | sonra |
|---|---|---|
| base (1) — çalışan durum | %20.6 | **%20.6** |
| Stüdyo (135) | %38.0 | %20.7 |
| **manken 2 (139) — bozuk** | **%43.7** | **%11.9** |

Çalışan durum korundu: base(1)'in gösterim base'i oturum öncesi yedeğe göre
piksellerin **%0.13**'ünde, azami 26/765 farkla değişti — gözle görülmez (fark,
kişi maskesinin kıyafet kenarını 1-2 px kırpması).

**rembg opsiyonel kalıyor:** yoksa `person_mask` None dönüyor ve eski davranışa
düşülüyor. Hat kırılmıyor, yalnızca bu koruma devre dışı kalıyor (testi var).

> Testte kişi maskesi sentetik veriliyor (conftest rembg'i kapatıyor). Test
> "kişinin dışında hiç piksel değişmesin" demiyor — maskeye bilerek 2 px
> Gaussian yumuşatma uygulanıyor, yani kenarda birkaç piksel taşması tasarımın
> parçası. Ölçtüğü şey panonun kişiden uzak kısmının hiç boyanmaması.

### 32.2 AYRI BİR SORUN: bu fotoğraf base olarak uygun değil

Gri dikdörtgen bizim bugumuzdu ve düzeldi. Ama aynı manken §7.4'teki kör nokta
sorununu taşıyor — kıyafeti neredeyse siyah. `base_conflict()` ile ÜCRETSİZ
ölçüldü (12 kıyafet, base'in kıyafet paletine uzaklık):

| durum | kıyafetler | sonuç |
|---|---|---|
| **engel** (< 25) | #14 lacivert (**1.0**) · #6 keten şort (10.7) · #11 mor (17.5) | katman **boş çıkar** |
| riskli (25-45) | #5 lacivert (26.1) · #8 bordo polo (30.1) | zayıf |
| uygun (> 45) | kalan 7 | sorunsuz |

Yani bu mankende dolabın **3 kıyafeti hiç üretilemez, 2'si riskli**. Sistem
bunu ücretli çağrıdan önce zaten söylüyor (yükleme akışındaki kapı), ama
`build-layers` toplu çalıştırılırsa 3 çağrı boşa gider.

**Öneri:** base fotoğrafı için §7.6'da ölçülmüş kural geçerli — kıyafet
**doygun ve orta tonda** olmalı (kazanan: orta mavi), zemin sade. Mevcut
`base` (1) tam olarak bu ve 12 katmanı hazır.

### 32.3 ⚠ YUKARIDAKİ "3 KIYAFET ÜRETİLEMEZ" İDDİASI ÖLÇÜLDÜ VE ÇÜRÜDÜ

Kullanıcı haklı bir itiraz getirdi: *FASHN'ın kendi uygulaması bu mankende
giydirmeyi sorunsuz yapıyor, bizimki neden yapamasın — filtreden mi?*

4 kredi harcanıp ölçüldü (2 çağrı): en kötü tahmin edilen vaka (#14 lacivert,
uzaklık **1.0**) ve kontrol (#10 sarı, uzaklık 174.7).

| | ham çıktı gövde farkı | kaplama | görsel |
|---|---|---|---|
| #14 lacivert (tahmin: **engel**) | 21.8 | **%5.71** | **kullanılabilir** |
| #10 sarı (tahmin: uygun) | 144.9 | %8.28 | temiz |

**Üç sonuç, üçü de beklentimin dışında:**

1. **Giydirmede hiçbir sorun yok.** Ham çıktıların ikisi de kusursuz — model
   her iki tişörtü de doğru giydirdi. FASHN'ın uygulamasıyla aramızda
   *giydirme* farkı YOK; fark bizim ondan sonra yaptığımız **fark çıkarımında**.
2. **"Katman boş çıkar" YANLIŞTI.** En kötü vaka bile %5.71 verdi ve bindirmede
   göze düzgün görünüyor. Sinyal gerçekten zayıf (21.8 vs 144.9, eşik 18 —
   7 kat fark) ama ölü değil.
3. **Filtre suçsuz.** Aynı ham çıktıdan `LEAK_FILTER` açık/kapalı çıkarıldı:

   | | filtresiz | lab |
   |---|---|---|
   | #14 | %5.71 | **%5.71** (fark YOK) |
   | #10 | %10.07 | %8.28 |

   #14'te filtre **hiçbir şey yapmıyor** — güvenlik kuralı (kıyafet base'e
   yakınsa uygulama) tam olarak tasarlandığı gibi devreye girmiyor.

**Zayıf katman neden yine de iyi görünüyor:** gösterim base'inin kıyafeti nötr
koyuya boyanmış. Katmandaki boşlukların altından koyu nötr görünüyor ve kumaş
gibi okunuyor. Mavi base'de aynı boşluk MAVİ gösterirdi ve göze batardı.
Yani manken 2'nin koyu kıyafeti **çıkarımı zorlaştırıyor ama bindirmeyi
kolaylaştırıyor** — §7.5'teki iki zıt gereksinimin öbür ucu.

**Asıl kusur `base_conflict`'in eşiklerinde:** o eşikler §7.4'te **fal/v1.6**
ile ve siyah base üzerinde kalibre edilmişti (uzaklık 9 → kaplama %0.6,
kullanılamaz). tryon-max görüntünün tamamını yeniden ürettiği için aynı renk
kıyafette bile kullanılabilir bir fark bırakıyor (uzaklık 1.0 → %5.71).
§25.5'in dersi bir kez daha: *bir ölçümün geçerliliği, ölçüldüğü koşulların
hâlâ geçerli olmasına bağlı.*

> **YAPILACAK:** `base_conflict` eşikleri tryon-max ile yeniden kalibre
> edilmeli ve yükleme akışındaki "Katmanı boş çıkardı" uyarısı yumuşatılmalı —
> metin artık ölçümle çelişiyor. İki örnekle yeni eşik KONULMADI (bu projenin
> kendi kuralı: tek/iki örnekle eşik konmaz).

---

## 33. İki kalan kusur: ikisi de FOTOĞRAFTA, kodda değil

Kullanıcı iki şey bildirdi: (a) lacivert tişört manken 2'de yamalı görünüyor,
(b) chino pantolonun kırpığı hâlâ iyi değil. İkisi de ölçüldü; ikisinin de
sebebi girdide.

### 33.1 Lacivert tişört manken 2'de yamalı — kör noktanın gerçek yüzü

Aynı kıyafet, iki manken, aynı boru hattı:

| manken | base'in kıyafeti | kaplama | görsel |
|---|---|---|---|
| base (1) | orta mavi (doygun) | **%15.84** | temiz, göğüsteki kırmızı logo okunuyor |
| manken 2 (139) | neredeyse siyah | **%5.71** | yamalı, logo yok |

Gövdede ham fark **21.8**, eşik **18**. Yani sinyal eşiğin hemen üstünde
sürünüyor ve yalnızca kıvrım/gölge sınırlarında eşiği aşıyor — ekranda görünen
"yamalar" tam olarak o pikseller.

§32.3'te ölçtüğümüz "boş çıkmıyor, kullanılabilir" doğruydu ama **küçük
önizlemede**. Tam boyutta kusur görünür hale geliyor. Dürüst ifade: bu bir
kör nokta ve mimarinin doğrudan sonucu — fark tabanlı çıkarım, base'in
kıyafetiyle kontrast gerektiriyor (§7.4).

**Üç çıkış yolu, üçü de mevcut:**

| yol | bedel | sonuç |
|---|---|---|
| Bu kıyafeti `base` (1) mankeninde kullan | 0 | zaten temiz katmanı var |
| Manken 2'de **Gerçekçi Göster** (Faz 4) | 2 kredi/kombin | çıkarım YOK, kusur da yok — FASHN'ın uygulamasının yaptığı şey |
| Manken 2'yi **doygun orta tonlu** bir üstle yeniden çek | 0 + katman üretimi | kör nokta tamamen kalkar |

### 33.2 Chino kırpığı — kontrast 18.6, dolaptaki en düşük

Maskenin sınırı orijinal fotoğrafın üzerine çizilince görüldü: **paçalar
maskede yok**, maske bacakları çapraz kesip sivri bir kamayla bitiyor.

Eşik sorunu DEĞİL — ham alfa ölçüldü, y%90'da alfa>200 olan 325 px var, yani
model orada zaten karar veremiyor (alfa>60 ile alfa>200 arasında 16 px fark).
`fill_holes` de suçsuz: chino'da doldurduğu alan **%0.0**.

Sebep kontrast. Aynı fotoğrafın içinde:

| bölge | kıyafet-zemin RGB kontrastı |
|---|---|
| bel | **106.3** |
| paça | **14.4** |

Bej pantolon, beyaz-gri çizgili çarşafın üstünde ve ışık aşağı doğru düşüyor.
Dolabın tamamında ölçüldü (kırpığın alt %20'lik bandı):

| kıyafet | kontrast |
|---|---|
| **#16 chino** | **18.6** ← en düşük |
| #13 keten gömlek | 24.3 |
| #12 kırık beyaz tişört | 39.0 |
| #6 keten şort | 39.5 |
| kalan 8 kıyafet | 74.4 – 286.0 |

**Metrik geçmişi doğruluyor:** #12, §16'da "model uydurma bir pat çizdi" diye
bilinen vaka ve düşük grupta. Ayrım da net — 39.5 ile 74.4 arasında boşluk var.
Ama #13 ve #6'nın kırpıkları sağlam, yani metrik yanlış pozitif de veriyor:
**kapı değil, uyarı olarak** kullanılmalı.

**Çözüm kodda değil:** kontrast 18.6'da hiçbir segmentasyon modeli paçayı
zeminden ayıramaz. §16'nın kendi listesindeki cevap geçerli — **koyu, sade,
kontrastlı bir zeminde yeniden çek.** Açık renkli kıyafet → koyu örtü.

> **YAPILACAK (ücretsiz, 12 veri noktası var):** kontrast metriğini yükleme
> akışına uyarı olarak ekle. #16 yüklenirken "paça bölgesinde kontrast düşük,
> koyu zeminde tekrar çek" deseydi bu turun tamamı yaşanmazdı. §31.1'deki kutu
> doluluğu uyarısıyla birlikte eklenmeli.

---

## 34. Pantolonu bozan şey ŞABLON ÖNSELİYMİŞ — ve §33'ün teşhisi yanlıştı

Kullanıcı §33'teki "kontrast" açıklamasına itiraz etti: *"kontrast olamaz,
beyaz tişört bal gibi de olmuş."* Haklıydı.

### 34.1 §33.2'nin kontrast ölçümü DAİRESELDİ

"Paçada kontrast 14.4" ölçümü, zemin örneğini **maskenin dışından** alıyordu —
ama maskenin dışında kalan şey zemin değil, **kesilmiş kumaşın kendisiydi.**
Yani kumaşı kumaşla karşılaştırıp "kontrast yok" sonucuna varmıştım.

Dairesel olmayan ölçüm (kumaş: bacağın ortası · zemin: iki bacak arası):

| satır | kontrast |
|---|---|
| 1450 | **93.4** |
| 1600 | 62.6 |
| 1750 | **80.6** |

Kontrast yüksek. §33.2'nin tamamı geçersiz.

### 34.2 Gerçek sebep: önsel kıyafetin değil ŞABLONUN silüetini dayatıyor

`_apply_prior` maskeyle **kesişiyor**, yani yalnızca silebiliyor. Kıyafet
şablondan genişse fazlası kesiliyor. Ölçüldü:

| | kaplama | paça genişliği |
|---|---|---|
| önselsiz | %42.2 | **340 px** |
| önsel uygulanmış | %27.4 | **91 px** |
| **şablon maskesinin kendisi** | **%27.4** | **94 px** |

Son satır kanıt: sonuç şablonla **birebir aynı**. Kırpık pantolonun değil,
`pantolon` şablonunun silüetiydi.

### 34.3 "Sadece kurtarma" varsayımı tutmuyordu

§17 bunu "yalnızca bozuk vakalarda devreye girer, sağlam vakalara dokunulmaz"
diye tasarlamıştı. Ölçüldü — **12 kıyafetin 6'sında tetikleniyor** ve her
seferinde maskenin %18-47'sini siliyor:

| kıyafet | önselsiz | önselli | kayıp | zarar |
|---|---|---|---|---|
| #8 bordo polo | %67.4 | %41.0 | %39.2 | kollar kırpıldı |
| #10 sarı tişört | %61.2 | %37.8 | %38.3 | kollar kırpıldı |
| #13 keten gömlek | %37.7 | %30.8 | %18.3 | kol kırpıldı |
| #14 lacivert tişört | %46.7 | %33.4 | %28.4 | kollar kırpıldı |
| #15 bej şort | %34.0 | %18.1 | %46.6 | **şort ikiye bölündü** |
| #16 chino | %42.2 | %27.4 | %35.1 | **paçalar yok oldu** |

**Yüzde freni denendi ve ÇÜRÜDÜ:** §17'nin gerçek kurtarma vakası (#12, u2net)
maskenin %33.6'sını siliyor, #16'nın yıkım vakası %35.1'ini. İki durum bu
metrikle ayrılamıyor — fren yazılsaydı işe yaramayacaktı.

### 34.4 Çözüm: önsel POLİGON değil KUTU

Dayanak §17'nin kendi ölçümü: *"düz bir DİKDÖRTGEN bile sorunu çözdü."*
Önselin işi segmentasyon değil, "kıyafet kabaca burada" demek.

| kıyafet | önselsiz | poligon (eski) | **kutu (yeni)** |
|---|---|---|---|
| #8 | %67.4 | %41.0 | **%58.5** |
| #10 | %61.2 | %37.8 | **%52.7** |
| #13 | %37.7 | %30.8 | **%37.6** |
| #14 | %46.7 | %33.4 | **%44.7** |
| #15 | %34.0 | %18.1 | **%22.2** |
| #16 | %42.2 | %27.4 | **%31.5** |

Görsel doğrulama (6 kıyafet, üç kurulum yan yana): kutu kolları ve paçaları
koruyor, #15'i ikiye bölmüyor — ama kıyafetin ALTINDAKİ yabancı nesneyi
(stand/sehpa, #10 ve #14) hâlâ atıyor. Kurtarmanın asıl işi buydu.

Pay sweep'i de yapıldı (0.12 / 0.20 / 0.28): pay büyüdükçe önsel etkisizleşiyor
(#8'de 0.28 → %64.9 ≈ önselsiz %67.4). `PRIOR_MARGIN` **0.12'de bırakıldı** —
tek turda tek değişken.

**Poligon arayüzde duruyor:** çekim rehberi olarak kıyafet şeklinde olması
doğru, çünkü orada bir şey kesmiyor. Değişen yalnızca segmentasyon önseli.

### 34.5 Durum — #16 iki mankende de yenilendi (4 kredi)

Kırpık yeniden üretildi: paça genişliği **182 → 348 px**, kaplama
%27.4 → %31.5. Ardından katmanı **her iki mankende** yeniden üretildi
(kullanıcı kararı; diğer 5 kıyafet "kötü değil" diye bırakıldı):

| | kaplama | paça genişliği |
|---|---|---|
| base (1) — eski kırpıktan | %14.10 | 253 px |
| **base (1) — yeni kırpıktan** | **%17.57** | 250 px |
| **manken 2 (139)** | **%7.02** | 48 px |

> manken 2'deki %7.02 kusur DEĞİL: o fotoğrafta kişi kadrajın daha küçük bir
> kısmını kaplıyor (kişi maskesi %18.3 · base'de %32.2), yani aynı kıyafet daha
> az tuval pikseli kaplıyor. Kaplama tuvale göre normalize; mankenler arası
> karşılaştırmada yanıltıcı. Görsel doğrulandı: üç kombinde de pantolon doğru.

- Diğer 5 kıyafetin (#8 #10 #13 #14 #15) **kırpıkları düzeldi** ama katmanları
  hâlâ eski kırpıklardan. Yenilemek kıyafet başına 2 kredi — kullanıcı şimdilik
  gerek görmedi.

> **Ders (bu turda üç kez):** bir metriğin ne ölçtüğünü doğrulamadan ona
> dayanma. Kutu doluluğu u2net'i haksız yere eledi (bacakları bitişik serilmiş
> bir pantolonun DOĞRU silüeti de yüksek doluluk verir); kontrast metriği
> dairesel çıktı; yüzde freni iki vakayı ayıramadı. Üçünü de kullanıcının
> itirazı çürüttü.

---

## 35. `base_conflict` eşikleri yeniden kalibre edildi ✅

§32.3 bir borç bırakmıştı: eşikler fal/v1.6 ile ölçülmüştü, tryon-max'te
çürümüştü ve "katman boş çıkar" uyarısı ölçümle çelişiyordu. Kapatıldı.

### 35.1 Veri: 15 (kıyafet × manken) ölçümü, tryon-max

Kaplama **kişi alanına normalize** edildi (`kaplama / kişi maskesi oranı`) —
yoksa kategoriler (şort %9, üst %16) ve mankenler (base'de figür tuvalin
%32.2'si, manken 2'de %18.3'ü) karşılaştırılamıyor.

| uzaklık | 1.0 | 40.7 | 45.8 | 69.3 | 93.1 | 101.8 | 116.4 | 126.6 | 164.6 | 174.7 |
|---|---|---|---|---|---|---|---|---|---|---|
| normalize kaplama | **0.312** | 0.458 | 0.542 | 0.492 | 0.521 | 0.539 | 0.704 | 0.503 | 0.523 | 0.452 |

**İki sonuç:**

1. **40'ın üstünde uzaklığın ölçülebilir etkisi yok** (0.45-0.70, eğilim yok).
   Eski "riskli 25-45" bandının dayanağı kalmamış.
2. **En uç noktada bile çökme yok:** uzaklık 1.0'da normalize kaplama 0.312,
   yani tipik değerin ~%65'i. Zayıf ama kullanılabilir; görselle doğrulandı.

Eski eşiklerin dayanağı (v1.6, siyah base) *uzaklık 9 → kaplama %0.6* idi —
o koşulda "boş çıkar" DOĞRUYDU. Sağlayıcı değişince ölçüm de değişti.

### 35.2 Değişen

| | eski | yeni |
|---|---|---|
| `< 25` | **engel** — ücretli çağrı YAPILMAZ | — |
| `25-45` | riskli | — |
| `< 15` | — | **zayıf** — üretilir, not düşülür |
| `>= 15` | uygun | uygun |
| `ok` | duruma göre False | **her zaman True** |

`ok` artık hiçbir koşulda üretimi durdurmuyor. Gerekçe: elimizdeki tek düşük
ölçüm (1.0) ÇALIŞTI. Çalışacağı ölçülmüş bir işlemi tahminle engellemek,
ücretli çağrıyı boşa harcamaktan daha kötü — kullanıcı yapabileceği bir şeyi
yapamıyor ve sebebi de yanlış.

Arayüz akışı: katman üretiliyor, zayıf sinyal `note` alanıyla sarı uyarı
olarak geçiyor ("…tipik değerin ~%65'i kadar çıkıyor — zayıf ama kullanılabilir").

**2 ile 40 arası ÖLÇÜLMEDİ.** `LOW_CONTRAST_DISTANCE = 15` bir sınıflandırıcı
değil, ölçülen tek düşük noktanın etrafına konmuş ihtiyatlı bir uyarı sınırı.
Bu belirsizlik hem sabitin yorumunda hem docstring'de yazılı.

### 35.3 Gerçek dolapta etkisi

| manken | eski | yeni |
|---|---|---|
| base | 12 uygun (1'i "riskli": #5, uzaklık 40.7) | **12 uygun** |
| manken 2 | 3 **engel** + 2 riskli | **2 zayıf (ikisi de üretilebilir)** + 10 uygun |

manken 2'de artık hiçbir kıyafet engellenmiyor. Engellenen üçünden biri (#14,
uzaklık 1.0) zaten ölçümle üretilmiş ve çalışmıştı.

> Test tarafında iki test **tersine çevrildi** (`test_kor_noktada_ucretli_cagri_YAPILMAZ`
> → `..._URETILIYOR_ama_uyari_geciyor`). Eski testler yanlış değildi, **eskimişti** —
> docstring'lerinde hangi koşulda ölçüldükleri yazıyor.

---

## 36. Şablon önseli KAPATILDI + bir yöntem hatası

### 36.1 §34'ün "kutu önseli" düzeltmesi yetersizdi

Kullanıcı kartına bakıp söyledi: *"bu kesim hâlâ çok kötü."* Haklıydı — kutu
önseli ölçülebilir bir iyileşmeydi ama sorunu çözmüyordu:

| #16 kırpığı | kaplama | kutu doluluğu | paça |
|---|---|---|---|
| poligon önsel | %27.4 | %61.3 | 173 px |
| kutu önsel (§34) | %31.5 | %71.0 | 342 px |
| **önselsiz** | **%39.3** | %66.5 | **595 px** |

§34'te "düzgün pantolon silüeti" diye raporlamıştım; kart hâlâ skinny
gösteriyordu. Ölçüm iyileşmeyi doğru veriyordu, **yorum fazla iyimserdi.**

### 36.2 KAPATILDI — `cutout.PRIOR_RESCUE = False`

Kullanıcı kararı, ölçüme dayanıyor (isnet, 12 kıyafet):

- Kurtarma **6/12 kıyafette** tetikleniyor — "yalnızca bozuk vakalara dokunur"
  varsayımı tutmuyor.
- Tetiklendiğinde maskenin **%18-47'sini** siliyor.
- 2 yardım (#10, #14: alttaki standı atıyor) · 2 zarar (#13 kol, #16 paça).
- §17'yi motive eden vaka (#12) isnet ile kadraj kenarına **hiç değmiyor** —
  yani kurtarmaya zaten uğramıyor. Asıl düzeltme §16'daki model değişikliğiydi
  (u2net → isnet), şablon değil.

Kod ve ölçümler duruyor; `True` yapmak tek satır. Tripwire testi var
(`test_sablon_onseli_KAPALI`). **Şablonlar arayüzde çekim rehberi olarak
kalıyor** — asıl değerleri orada (kolları açık serdirmek, kıyafeti ortalamak).

### 36.3 ⚠ YÖNTEM HATASI: tohumsuz yeniden üretim, 2 kredi

§34.5'te #16'nın katmanını **tohumsuz** yeniden ürettim ve sonucu "iyileşti"
diye sundum. Kullanıcı baktı: *"eski hâli daha iyiydi."* Doğruydu — ama asıl
sorun hangisinin iyi olduğu değil, **karşılaştırmanın geçersiz olması:**
difüzyon stokastik, aynı girdiyle iki çağrı zaten farklı çıkar. Kırpık
değişikliği ile rastgelelik aynı anda oynadı, yani fark **atfedilemez.**

§20.1'de kural zaten yazılıydı ("AYNI TOHUM: yoksa iki kare hem modelden hem
difüzyonun rastgeleliğinden farklı çıkar") ama yalnızca `tryon-ab`de vardı,
asıl üretim komutunda yoktu. Eklendi:

```
python cli.py build-layers --id 16 --force --seed 42
```

### 36.4 Sonuç

| #16 katmanı | kaplama | paça | not |
|---|---|---|---|
| eski (poligon kırpıktan) | %14.10 | 253 px | kullanıcının beğendiği |
| kutu kırpıktan, tohumsuz | %17.57 | 250 px | daha dar paça, hayalet kontur |
| **önselsiz kırpık + tohum 42** | **%17.83** | **262 px** | **aktif** |

Yedekler `scratchpad`'de; eskisine dönmek tek `cp`. Kalan hayalet kontur
§19.3'ün bilinen kalıntısı (base'in kendi kıyafetinin siluet dışına taşması),
bu turun konusu değil.

**Diğer 5 kıyafetin kırpıkları artık önselsiz üretilecek** ama katmanları hâlâ
eski kırpıklardan — yeniden üretmek kıyafet başına 2 kredi, kullanıcı gerek
görmedi.

---

## 37. "Bizimki neden tişörtü bile giydiremiyor?" — giydiremiyor DEĞİL

Kullanıcı manken 2'de #14 + #16 kombinini gördü: tişörtte koyu lekeler, belde
gri şort yamaları, kolda hayalet. Haklı bir soru: *"AI modeli bunu normal
giydirebiliyor, bizimki neden yapamıyor?"*

**Cevap: bizim giydirmemiz de kusursuz.** Aynı üretimin ham çıktıları:

| | sonuç |
|---|---|
| #14 ham çıktı (lacivert tişört) | **temiz** — tişört giydirilmiş, base'in şortu duruyor |
| #16 ham çıktı (chino) | **temiz** — pantolon giydirilmiş, base'in tişörtü duruyor |
| ikisinin KATMAN bindirmesi | yamalı, lekeli |

Bozulma giydirmede değil, **fark çıkarımında ve bindirmede.** Ölçüldü — katman
piksellerinin, altındaki base pikseliyle neredeyse aynı olan oranı:

| katman | base sızıntısı |
|---|---|
| #14 lacivert tişört | **%44.8** |
| #16 chino | %11.3 |

#14'ün katmanının neredeyse yarısı aslında base'in KENDİ tişörtü: manken 2
lacivert tişört giyiyor, eklenen kıyafet de lacivert (uzaklık **1.0**), yani
fark ikisini ayıramıyor. İki böyle katman üst üste binince yamalar çıkıyor.

**Bu, mimarinin bilinen takası (§2, §7.4), kusur değil:** katman yolu kombinleri
ÜCRETSİZ ve ANINDA yapabilmek için farktan çıkarım yapıyor; fark ise base'in
kıyafetiyle kontrast gerektiriyor.

### 37.1 Katman yenilemek bu sorunu ÇÖZMEZ

Ayrı iki mesele karıştırılmamalı:

| sorun | kaynağı | yenilemek çözer mi |
|---|---|---|
| Kolları kırpılmış kıyafet (#8 #10 #13 #14 #15) | ESKİ kırpık (şablon önseli, §36) | **evet** |
| manken 2'deki yamalar | base'in kıyafeti kıyafetle aynı renk | **hayır** |

manken 2'de #14 yeniden üretilse yine ~%45 sızıntılı çıkar — kırpıkla ilgisi
yok.

### 37.2 manken 2'de temiz sonuç için iki yol

1. **"Gerçekçi Göster" (Faz 4)** — zincirleme render, çıkarım YOK, bindirme YOK.
   FASHN'ın uygulamasının yaptığı şeyin aynısı ve bizde zaten var. Kombin başına
   kıyafet × ~2 kredi.
2. **manken 2'yi doygun/orta tonda bir üstle yeniden çek** (§7.6'da ölçülen
   kazanan: orta mavi). O zaman fark güçlü olur, katman yolu çalışır ve
   kombinler sonsuza kadar bedava olur.

---

## 38. Tek kıyafette HAM VTON çıktısı gösteriliyor ✅

Kullanıcının fikri: *"tek kıyafet bildirirken direkt ham VTON çıktısını
kullansa, bindirmeyi sadece kombinde yapsa?"*

**Doğru fikir ve bedava.** Bindirmenin varlık sebebi birden çok kıyafeti
birleştirebilmek (§2). Tek parçada hiçbir şey birleştirmiyor — yalnızca
çıkarım kusurlarını taşıyor: base sızıntısı, kenar halkası, kör nokta.

Ölçülen (manken 2, lacivert tişört):

| | sonuç |
|---|---|
| ham çıktı | **temiz** |
| katman bindirmesi | katmanın **%44.8'i** base'in kendi tişörtü |

**Maliyet sıfır:** ham çıktılar `--reextract` için ZATEN saklanıyor
(15/15 mevcut, ~1.45 MB ortalama). Ücreti çoktan ödenmiş bir sonucu
göstermiyorduk sadece.

### 38.1 Nasıl çalışıyor

| seçim | gösterilen | gerekçe |
|---|---|---|
| 1 kıyafet | `GET /api/dressed/{id}.png` — ham çıktı | birleştirilecek bir şey yok |
| 2+ kıyafet | katman bindirmesi (eskisi gibi) | ham çıktılar birleştirilemez |

İkinci satır bir kısıt değil matematik: her ham çıktı AYRI bir çağrıda üretildi
ve base'in geri kalanını da içeriyor (#14'ün hamında base'in şortu var,
#16'nınkinde base'in tişörtü). Üst üste konulamazlar — biri diğerinin
kıyafetini örter. Kombinde bindirme hâlâ tek ücretsiz yol.

`/api/wardrobe` her kıyafet için `dressed_rev` taşıyor (0 = ham çıktı yok →
istemci bindirmeye düşüyor). Damga mtime, yani önbellek kırma da §25.7'nin
kuralına uygun.

Arayüzde ne görüldüğü **yazıyor**: tek kıyafette "Gerçek giydirme çıktısı —
ücreti zaten ödenmişti", kombinde "N katman bindirildi". İkisi farklı kalitede
ve sebebinin görünür olması şart, yoksa "kombin yapınca neden bozuldu"
sorusu cevapsız kalır.

### 38.2 Ne değişmedi

- Kombin görünümü aynı (ve aynı kusurlarla) — §37'deki kök sebep duruyor.
- "Gerçekçi Göster" (Faz 4) hâlâ ayrı ve ücretli: o, kombini ZİNCİRLEME
  giydiriyor, yani birden çok kıyafeti tek bir temiz görüntüde birleştiriyor.
  Bu özellik onun ücretsiz tek-kıyafet karşılığı.

---

## 39. Halenin kaynağı + "sayı iyileşti, göz kötüleşti" üç kez

Kullanıcı #16'nın yeni sürümünü beğenmedi ve eskisini istedi. Ölçüm onu
doğruladı; ama asıl değerli kısım, **denenen üç düzeltmenin de ölçüde kazanıp
gözde kaybetmesi.**

### 39.1 Hale anti-alias değil, katmanın İÇİNDEKİ opak açık piksellermiş

İlk teşhisim kenar rampasıydı (yarı saydam piksellerin duvarla karışması).
Ölçüm çürüttü — kalça hizasında, gövdenin sağında:

| | opak piksel | bunların AÇIK olanı (>190) |
|---|---|---|
| v1 | %58.0 | %8 |
| v3 | %76.9 | **%18** |

Yani hale opak, katmanın tam içinde. Sebep: model geniş pantolonu giydirirken
**kalçanın yanındaki duvar/el bölgesini yeniden boyamış**, fark da onu kıyafet
sanmış. Katmanın **%30.2'si kişinin dışında** (65.212 piksel duvar).

v1 bunu içermiyor çünkü kırpığı dardı — yani **kazara doğru.** Gerçek paça
genişliğini kaybediyor ama görünür kusuru da kaybediyor.

### 39.2 Üç aday, üçü de ölçüde kazandı gözde kaybetti

| aday | değişiklik | sayı | göz |
|---|---|---|---|
| v4 | `EDGE_SOFTEN` 0.5 + `DECONTAM_DEPTH` 12 | rampa-iç fark 27.9 → **0.9** | **kötüleşti** — basamaklı kenar (§6.1 #14 aynen geri geldi) |
| v5 | yalnız `DECONTAM_DEPTH` 12 | fark → **2.2** | **değişmedi** |
| v6 | + kişi maskesi (§32'nin fikri) | açık piksel %18 → **%1** | **kötüleşti** — pantolonun dış kenarı kesildi, altından base'in şortu çıktı |

v6 özellikle öğretici: aynı fikir (`person_mask`) gösterim base'inde
mükemmel çalışmıştı (§32), burada çöktü. Sebep, maskenin GİYDİRİLMİŞ çıktıdan
alınması: modelin çizdiği pantolon, modelin çizdiği vücut siluetinden geniş.
**Bir fikrin bir yerde işe yaraması, komşu yerde de işe yarayacağı anlamına
gelmiyor.**

### 39.3 Ders: ölçüt seçmek, ölçüm yapmaktan zor

Bu projede "önce ölç" kuralı baştan beri var ve işe yaradı. Bu tur onun
eksik yarısını gösterdi: **yanlış ölçüte bakarsan ölçüm seni yanlış yere
götürür.** Üç düzeltme de kendi hedef metriğini iyileştirdi ve üçü de
kullanıcının şikâyetini çözmedi.

Kullanıcının kuralı (*"hem sayı hem gözle ölç"*) bu yüzden kayda geçiyor:
görsel doğrulama, metrik doğrulamanın yerine geçmez ama onun **veto hakkı**
vardır.

Bu turda ayrıca metriklerin kendisi üç kez çürüdü: kutu doluluğu u2net'i haksız
eledi, kontrast ölçümü dairesel çıktı, yüzde freni iki vakayı ayıramadı (§34.5).

### 39.4 Sürümler artık kalıcı: `data/layer_surumleri/`

Kullanıcı ayrıca *"önceki halini de silme"* dedi. Sürümler `scratchpad`'de
tutuluyordu ve orası oturumluk. Artık projede:

```
data/layer_surumleri/g16_m1_v1_poligon-kirpik.png      ← CANLI
data/layer_surumleri/g16_m1_v2_kutu-kirpik-tohumsuz.png
data/layer_surumleri/g16_m1_v3_onselsiz-tohum42.png
data/layer_surumleri/g16_KIRPIK_v1_poligon.png
data/layer_surumleri/g16_KIRPIK_v3_onselsiz.png
```

**Kural: bir katmanı yeniden üretmeden önce eskisi buraya kopyalanır.**
Ücretle üretilmiş bir görüntünün üstüne yazmak, bu projede parayı çöpe atmanın
en sessiz yolu (§26'daki "geri alma dosyayı SİLMEZ" kararının aynısı).

---

## 40. "Her yeni mankeni gri yapmak zorunda mısın?" — hayır

Kullanıcı fark etti: yeni manken eklenince sahne gri görünüyor, ama sarı
tişörte basınca gerçek fotoğraf çıkıyor.

**Nötrleme (gösterim base'i) yalnızca BİNDİRME için var.** Gerekçesi ölçülmüş:
katmanın boşluk bıraktığı ya da base'in kıyafetinin yeni kıyafetin siluetinin
dışına taştığı yerde altından base'in GERÇEK kıyafeti çıkıyor — turkuaz base
deneyinde (§7.5) bu "belde bağıran bir turkuaz bant" olarak ölçülmüştü.

Bindirme olmayan durumlarda gereksiz. Zemin artık duruma göre seçiliyor:

| seçim | zemin | üstte |
|---|---|---|
| boş | **gerçek fotoğraf** | — |
| 1 kıyafet | gerçek fotoğraf | ham VTON çıktısı (§38) |
| 2+ kıyafet | **nötrlenmiş** | katmanlar |

Yani grilik yalnızca gerçekten bindirme yapılan yerde görünüyor.

`GET /api/base_raw.png` eklendi; `/api/wardrobe` `base_raw_rev` taşıyor
(önbellek kırma §25.7'nin kuralına uygun). Tarayıcıda doğrulandı.

**Gösterim base'i yine de her mankende üretiliyor** ve üretilmeli: 2+ kombinde
lazım, üretimi ücretsiz (yalnızca yeniden renklendirme, ~1 sn) ve manken
değişince otomatik siliniyor. Kullanıcının gördüğü maliyet sıfır; değişen tek
şey ne zaman GÖSTERİLDİĞİ.

---

## 41. Aynı kombin, iki mankende farklı kusur — sebep RENK değil GEOMETRİ

Kullanıcı sarı tişört + chino kombinini iki mankende karşılaştırdı: manken 2'de
temiz, **base'de yakada gri bir halka.** Renk uzaklığı bunu açıklamıyor
(sarı ↔ her iki base de çok uzak).

**Sebep base'in kıyafetinin GEOMETRİSİ.** Base'in mavi tişörtünün yakası, sarı
tişörtün render edilen yakasından yüksek; üstte kalan ince şerit base kıyafeti
olduğu için sızıntı filtresi onu doğru şekilde atıyor ve altından nötrlenmiş
gösterim base'i (gri) görünüyor. manken 2'nin tişörtünün yakası daha alçak,
taşmıyor, halka yok.

Bu §19.3'te "kalan kusur" diye yazılan şeyin ta kendisi:
*tırtıklı kirli kenar → düzgün nötr şerit.* Kalıcı çözümü de orada yazıyor:
**base'i daha alçak/dar yakalı bir üstle çekmek.**

### 41.1 İki metrik çelişti, biri çöptü

| ölçüm | base | manken 2 |
|---|---|---|
| yaka bandında nötr-koyu piksel | %4.9 | %1.6 |
| "base kıyafeti var, katman yok" (taşan) | %0.9 | **%39.2** |

İkinci satır ilkiyle çelişiyor. Sebep: taşan hesabı base kıyafetini KROM
yakınlığıyla buluyor ve manken 2'nin kıyafeti neredeyse akromatik olduğu için
**duvarı da kıyafet sayıyor** — görselleştirince kırmızı tüm duvarı kapladı.

Yani §32'de gösterim base'i için düzeltilen kusur, `base_clothing_palette`'e
dayanan DİĞER hesaplarda hâlâ duruyor. `person_mask` orada uygulanmadı.

> **Açık iş:** krom tabanlı "base kıyafeti" maskesini kullanan her yer
> (`drop_base_clothing`, teşhis betikleri) koyu kıyafetli mankenlerde duvarı
> kıyafet sayıyor. §32'nin kişi maskesi oraya da taşınmalı — ölçülmedi.

### 41.2 `base_conflict` uyarı metni düzeltildi

Eski metin kaplama metriğine dayanıyordu ("tipiğin ~%65'i, zayıf ama
kullanılabilir") ve yanlış soruyu cevaplıyordu: kaplama makul çıkıyor ama
katmanın İÇERİĞİ base oluyor (uzaklık 1.0'da **%44.8**). Yeni metin bunu
söylüyor ve iki çıkış yolunu veriyor (Gerçekçi Göster / mankeni yeniden çek).

---

## 42. Krom maskesine kişi maskesi — ÖLÇÜLDÜ, ETKİSİ YOK, kısmen geri alındı

§41.1'de açık iş olarak yazılmıştı: `base_clothing_palette` sabit örnekleme
kutuları kullanıyor ve figür kadrajı doldurmadığında duvar örneği alıyor.
Uygulandı ve ölçüldü.

### 42.1 Kirlilik gerçek

Örnekleme kutusunun (gövde y %36-52 · kalça y %64-74, x %42-62) kişi maskesinin
içinde kalan kısmı:

| manken | kişi maskesi | kutunun kişide kalanı | kutudaki duvar örneği |
|---|---|---|---|
| base | %32.2 | **%100.0** | 0 px |
| manken 2 | %18.3 | %92.8 | **4.180 px** (renk `[109,99,86]`) |

### 42.2 Ama propagasyonu YOK

Kişi maskesiyle kesiştirilip paletler karşılaştırıldı:

| manken | palet kayması | aşağı akış (`base_conflict` uzaklıkları) |
|---|---|---|
| base | **0.0** | 12 kıyafetin hiçbiri değişmedi |
| manken 2 | **0.0** | 12 kıyafetin hiçbiri değişmedi |

Sebep `_palet`in çalışma biçimi: en kalabalık 5 renk kovası seçiliyor. 54.121
pikselli kıyafetin yanında %7'lik duvar azınlığı hiçbir kovada ilk 5'e
giremiyor. **Oylama zaten azınlık kirliliğine dayanıklı.**

### 42.3 Karar: mekanizma kalıyor, bağımlılık eklenmiyor

- `base_clothing_palette(..., person=...)` parametresi **duruyor** ve
  `build_display_base` onu geçiyor — orada maske ZATEN hesaplanıyor (§32) ve
  ölçülmüş gerçek bir etkisi var, yani ek maliyet sıfır.
- `base_conflict`'e **eklenmedi.** Etkisi ölçüldü ve yok; oraya rembg
  bağımlılığı koymak yükleme akışına karşılıksız 1-3 sn ekler.
  §20.1'in dersi aynen geçerli: *etkisi ölçülmemiş/olmayan bir sapmayı
  taşımak, taşımamaktan kötü.*
- `cutout.person_mask_for(path)` eklendi — (yol, mtime) anahtarlı önbellek,
  yani maske ikinci çağrıda bedava ve dosya değişirse yenileniyor.
- Güvenlik freni: maske örnekleme kutusunun %80'inden fazlasını yerse kutuya
  dönülüyor. Boş palet, ona dayanan her şeyi (kör nokta kontrolü, sızıntı
  filtresi) SESSİZCE devre dışı bırakırdı.

İki test eklendi (357 test): maske verilince duvarın palete girmediği, ve
frenin devreye girdiği.

> **Bu bölümün asıl değeri negatif sonuç olması.** §41'de "açık iş" diye
> yazdığım şey ölçülünce boş çıktı. Kirliliği doğru teşhis etmişim ama
> **teşhis ile etki ayrı iddialar** — §25'in dersi, bu turda dördüncü kez.

---

## 43. "Grinin üstüne mi giydiriyorsun?" — teknik olarak hayır, pratikte EVET

Kullanıcı ısrar etti: *"madem grinin üstüne giydirilmiyor, benim fotoğrafım neden
griye boyandı ve o gri kalıntılar neden duruyor?"* Ölçüm onu haklı çıkardı ve
benim ifademi düzeltti.

### 43.1 Hangi kısım doğruydu

Nötrlenmiş görüntü **VTON'a da fark hesabına da girmiyor.** İki kanıt:

- Kod: `build_layer` VTON'a `base_row["image_path"]` (ham fotoğraf) gönderiyor
  ve farkı aynı ham fotoğrafla alıyor. Faz 4 zinciri de ham fotoğraftan
  başlıyor (`current = base_row["image_path"]`).
- Deney: `base_display.png` tamamen silinip 12 katman yeniden çıkarıldı →
  **11'i birebir aynı** (12'si ilgisiz bir sebeple değişti).

### 43.2 Ama pratikte gördüğü şey gerçekten o griydi

Katmanlar tek başına beyaz zeminde çizildiğinde ortaya çıktı:
**tişörtün gövdesi katmanda YOK, şeffaf.** Ekranda "lacivert tişört" diye
görünen şey zeminin katmanın deliğinden görünmesi.

Ölçüldü — gövde bölgesinde **katman doluluğu %4**, yani görüntünün **%96'sı
zemin.** Zemin nötrlenmiş olduğu için lacivert tişört GRİ görünüyordu:

| zemin | gövdede kıyafetin gerçek rengine uzaklık |
|---|---|
| nötrlenmiş (eski davranış) | 17.3 |
| **gerçek fotoğraf** | **7.7** |

Yani kör noktadaki bir kıyafette nötrleme **zararlı**: kıyafeti yanlış renkte
gösteriyor. Benim "grilik ilgisiz" ifadem teknik olarak doğru ama kullanıcının
baktığı şeyi ıskalıyordu.

**Bir istisna da atlamışım:** `edits.materialize` düzenleme kaynağı olarak
`compose()`'u kullanıyor, yani "Katman görüntüsü" modunda nötr zeminli görüntü
FASHN'ın edit uç noktasına GİDİYOR. Orada gri gerçekten modele giriyor.

### 43.3 Düzeltme: zemin kombine göre seçiliyor

| durum | zemin | gerekçe |
|---|---|---|
| seçim boş | gerçek fotoğraf | bindirme yok (§40) |
| 1 kıyafet | gerçek fotoğraf | ham VTON çıktısı üstünü kapatıyor (§38) |
| 2+ kıyafet, hepsi UZAK renkte | **nötrlenmiş** | sızan base göze batmasın (§7.5) |
| 2+ kıyafet, biri KÖR NOKTADA | **gerçek fotoğraf** | katman boş, zemin baskın; nötr yanlış renk gösterir |

`/api/wardrobe` her kıyafet için `base_near` taşıyor; eşik
`layers.LOW_CONTRAST_DISTANCE` ve istemci onu yeniden tanımlamıyor (§14).
Mesafe (kırpık+manken, mtime) anahtarlı önbellekte.

Tarayıcıda doğrulandı: manken 2'de #14+#16 → `base_raw.png`, #10+#16 →
`base.png`. Kör noktadakiler otomatik listeleniyor (#6, #14).

### 43.4 Ders

Nötrlemenin gerekçesi (§7.5 turkuaz) **tek yönlü** kurulmuştu: "sızıntı göze
batmasın". Ama sızıntının göze batıp batmaması kıyafetle base'in İLİŞKİSİNE
bağlı — aynı renkteyse sızıntı zararsız, hatta faydalı. Sabit bir zemin bu iki
durumu ayırt edemiyordu.

*Bir gerekçenin bir yönde doğru olması, sabit bir kural haline getirilebileceği
anlamına gelmiyor.*

---

## 44. ÇÖZÜLDÜ: kör nokta — base'in kıyafetini YAZILIMLA boyamak (6 kredi)

§7.4'ten beri açık olan en temel kısıt kapandı: *"tek base her renkle kontrast
yapamaz, o yüzden base'in kıyafet rengindeki kıyafetler kör noktada kalır."*

### 44.1 Fikir: iki base ZATEN ayrı, o hâlde çıkarım base'i GERÇEK olmak zorunda değil

§7.6'da iki base ayrılmıştı (çıkarım / gösterim). O ayrım şu imkânı doğuruyor:
**çıkarım base'inin gerçekçi görünmesi gerekmiyor** — kullanıcı onu hiç
görmüyor. O hâlde kıyafeti dolaptaki her şeyden maksimum uzak bir renge
boyanabilir.

Boyama ÜCRETSİZ ve geometri birebir aynı kalıyor: kıyafet maskesi zaten
hesaplanıyor (krom < 15 ∩ kişi maskesi, §32), parlaklık taşınıyor, yalnızca
renk değişiyor. §7.5'teki hibrit bu yüzden çökmüştü — orada İKİ AYRI FOTOĞRAF
vardı; burada tek görüntünün yeniden renklendirilmiş hâli.

### 44.2 Ölçüm (manken 2, #14 lacivert tişört — en kötü vaka, tohum 42)

| çıkarım base'i | kaplama | base sızıntısı | gözle |
|---|---|---|---|
| orijinal (lacivert, uzaklık **1.0**) | %5.71 | **%44.8** | enkaz: belde bej bant, uylukta şort deseni |
| **chroma yeşil** | %8.71 | **%0.1** | **tertemiz, renkli leke yok** |
| magenta | %8.69 | %0.2 | temiz ama uylukta magenta nokta |
| orta mavi | **%10.19** | %0.1 | temiz ama uylukta mavi nokta |

**Sızıntı %44.8 → %0.1.** Kör nokta kapandı.

**İki incelik:**

1. **Renk sıralaması kaplamayı öngörmedi.** Serbest sıralamada chroma yeşil
   196.0 ile birinci, orta mavi 60.1 ile beşinciydi; ama kaplamada orta mavi
   kazandı (%10.19 vs %8.71). Uzaklık sinyalin varlığını garanti ediyor,
   büyüklüğünü değil.
2. **%0.1 sızıntı bile doygun renkte GÖRÜNÜYOR.** Magenta ve mavide uylukta
   birer nokta kaldı; chroma yeşilde görünür leke yok. Sebebi muhtemelen Lab
   filtresinin en uzak renkte en emin çalışması. §7.5'in dersi minyatür halde:
   *sızıntı kaçınılmaz, o yüzden sızan renk göze batmayan ya da tamamen
   temizlenebilen olmalı.*

### 44.3 §7.5'in sonucu ARTIK GEÇERSİZ

Turkuaz deneyi (§7.5) "çıkarımı düzeltir, bindirmeyi bozar" diye kapatılmıştı ve
o ölçüm doğruydu — **ama koşulları iki kez değişti:** gösterim base'i (§7.6)
sızıntının zeminde görünmesini bitirdi, Lab filtresi (§19) katmanın içindeki
sızıntıyı temizledi. Bugün aynı fikir çalışıyor.

§25.5'in dersi dördüncü kez: *bir ölçümün geçerliliği, ölçüldüğü koşulların
hâlâ geçerli olmasına bağlı.*

### 44.4 Yeni manken için ÖNERİLEN akış (uygulanmadı)

```
kullanıcı fotoğrafını yükler
   ├─ GÖSTERİM base'i  = fotoğrafın kendisi (gerçek, doğal)
   └─ ÇIKARIM base'i   = aynı fotoğrafın kıyafeti chroma yeşile boyanmış
                          (ücretsiz · geometri birebir aynı)
tüm VTON çağrıları çıkarım base'ine
tüm gösterim gerçek fotoğrafa
```

Kazanç: kullanıcı **ne giyerse giysin** kör nokta yok. Yeniden çekim gerekmiyor,
AI manken üretmek gerekmiyor (o yol yüz/vücut kaydırıyor ve §"Gemini ölçümü"nde
katman üretimi için elenmişti).

**Kısıt:** bir mankenin TÜM katmanları aynı base'den çıkarılmak zorunda
(mimarinin temel şartı, §2). Yani çıkarım base'i değişince o mankenin
katmanları yeniden üretilmeli — kıyafet başına 2 kredi.

Ayrıca: `base_conflict`'in kör nokta uyarısı bu akışta gereksizleşir.

> Boyamada küçük bir kusur: krom maskesi koyu sakalı da kıyafet sayıp boyuyor
> (çene bölgesinde renk lekesi). Çıkarım base'i kullanıcıya gösterilmediği için
> zararsız, ama VTON'a giden görüntüde duruyor — düzeltilmedi, ölçülmedi.

### 44.5 UYGULANDI (manken 2, 4 kredi)

`mannequin.build_extract_base()` + `extraction_image()` eklendi. Üç base'li
düzen:

| dosya | rengi | işi | kullanıcı görür mü |
|---|---|---|---|
| `base_{id}.png` | gerçek | Faz 4 zinciri · gösterim kaynağı | evet |
| **`base_{id}_extract.png`** | **chroma yeşil** | **VTON + fark** | **hayır** |
| `base_{id}_display.png` | nötr koyu | bindirme zemini | evet |

`build_layer` ve `reextract` artık `extraction_image()` kullanıyor; dosya yoksa
gerçek fotoğrafa düşüyor, yani bu özelliği kullanmayan mankende hat aynen
eskisi gibi. **`render.render_outfit` bilerek DOKUNULMADI** — o çıktı doğrudan
kullanıcıya gösteriliyor, gerçek fotoğraftan başlamalı.

Manken 2'nin üç katmanı yeşil base'den üretildi. #14, deneyin ham çıktısı
diskte olduğu için `--reextract` ile **bedava** kurtarıldı (2 kredi tasarruf);
#10 ve #16 için 2 çağrı = 4 kredi.

| kıyafet | eski kaplama | eski sızıntı | yeni kaplama | yeni sızıntı |
|---|---|---|---|---|
| #10 sarı | %8.28 | %0.0 | %8.51 | %0.0 |
| **#14 lacivert** | %5.71 | **%44.8** | **%8.71** | **%0.1** |
| #16 chino | %7.03 | %11.3 | %7.76 | **%2.7** |

Görsel: beldeki bej bant, uyluktaki şort deseni ve koyu lekeler tamamen gitti;
tişörtün kırmızı logosu bile düzgün çıkıyor. Eski katmanlar
`data/layer_surumleri/g*_m139_ESKI_lacivertbase.png` olarak duruyor.

Tarayıcıda doğrulandı · 359 test geçiyor.

> **Açık iş:** `base_conflict` hâlâ GERÇEK fotoğrafa bakıyor. Bu, zemin seçimi
> için DOĞRU (gösterim gerçek fotoğraftan geliyor) ama yükleme akışındaki
> "kör nokta" uyarısı için artık yanıltıcı: çıkarım base'i yeşil olduğu için
> kör nokta yok. Aynı fonksiyon iki ayrı soruya cevap veriyor; ayrılması
> gerekiyor. Ölçülmedi.
>
> **Açık iş 2:** krom maskesi koyu sakalı da boyuyor, yani VTON'a giden
> görüntüde çenede yeşil leke var. Sonuçları bozmadı ama temizlenmeli.

### 44.6 `base_conflict` ikiye ayrıldı

§44.5'te açık iş olarak bırakılmıştı: tek fonksiyon, tek sayı, iki soru — biri
için doğru, diğeri için yanlış. Ayrıldı.

| fonksiyon | neye bakar | hangi soru |
|---|---|---|
| `base_conflict` | **gerçek fotoğraf** | bindirmede hangi ZEMİN kullanılsın |
| `extraction_conflict` | **çıkarım base'i** | yükleme UYARISI: katman bozuk çıkar mı |

Aynı kıyafette zıt cevap verebiliyorlar ve ikisi de kendi sorusu için doğru
(manken 2, ölçüldü):

| kıyafet | gerçek fotoğrafa | yeşil çıkarım base'ine |
|---|---|---|
| #6 keten şort | 10.7 (zayıf) | 103.7 (uygun) |
| **#14 lacivert tişört** | **1.0 (zayıf)** | **107.0 (uygun)** |
| #10 sarı tişört | 174.7 (uygun) | 129.4 (uygun) |

Neden ikisi de doğru:

- **Zemin sorusu** gerçek fotoğrafa bakmalı, çünkü katmanın deliğinden görünen
  şey mankenin GERÇEK kıyafeti. Aynı renkse delikten çıkan şey zaten doğru
  renkte; nötrleme onu yanlış gösterir (17.3 vs 7.7).
- **Uyarı sorusu** çıkarım base'ine bakmalı, çünkü VTON ve fark ona karşı
  çalışıyor. Yeşil base'de kör nokta yok, yani uyarı hiç tetiklenmemeli.

Ortak hesap `_renk_catismasi()`'nde; iki fonksiyon ince sarmalayıcı. Çıkarım
base'i yoksa ikisi aynı sonucu veriyor, yani eski kurulumda davranış değişmiyor
(testi var). `web/app.py` yükleme akışı `extraction_conflict`'e, zemin seçimi
(`base_near`) `base_conflict`'e bağlandı.

361 test geçiyor.

### 44.7 Sakal sorunu çözüldü — bileşen eşiği

§44.5'in ikinci açık işi: krom ölçütü koyu SAKALI da kıyafet sayıp yeşile
boyuyordu (çıkarım base'inde çenede yeşil leke).

**Ölçüm:** manken 2'de kıyafet maskesi **64 bileşene** ayrılıyor. Ana bileşen
%98.5 (y %26-72, kıyafet); ikincisi **1.136 px, y %22-25** — sakal. Base'de
maske zaten tek parça (ikinci bileşen 1 piksel).

**Çözüm:** ana bileşenin %5'inden küçük bileşenler atılıyor
(`MIN_CLOTHING_COMPONENT`). İki parçalı kıyafet (üst + alt ayrık) korunuyor —
ikisi de eşiğin çok üstünde.

Maske kodu tek yere alındı (`_clothing_mask`): gösterim ve çıkarım base'i
aynı üç süzgeci kullanıyor — krom (§19.1) + kişi maskesi (§32) + bileşen eşiği.
Önce iki fonksiyonda kopyalanmıştı ve ayrışma riski taşıyordu.

**Sonuç (ücretsiz, `--reextract`):**

| | boyanan piksel | çene bölgesi (#14) |
|---|---|---|
| önce | %12.60 | 2.751 px |
| sonra | %12.27 | **1.881 px** |

| katman | önce kaplama | sonra kaplama |
|---|---|---|
| #10 | %8.51 | %8.44 |
| #14 | %8.71 | %8.60 |
| #16 | %7.76 | %7.78 |

Görsel: çenedeki yeşil leke gitti, geri kalan aynı. Kıyafet kaybı yok.

> **Beklenmedik bulgu:** ham çıktılar ESKİ base'e (yeşil sakallı) karşı
> üretilmişti, yani yeni base'le fark almanın sakalı katmana sokması
> beklenirdi. Tersi oldu — çene bölgesindeki piksel 2.751 → 1.881'e düştü.
> Anlaşılan model yeşil sakalı doğal renge çevirmiş, yani ham çıktı yeni
> base'le DAHA tutarlı. Ölçmeseydim base'i gereksiz yere geri alırdım.

363 test geçiyor.

### 44.8 Yeşilin bindirmede görünmesi ZORUNLU DEĞİL — `drop_extract_color`

Kullanıcı sordu: *"katmanla giydirirken yeşil görünmemesinin imkânı yok mu,
yoksa yeşil base kullanacaksak mecbur mu?"*

**Mecbur değil — aksine yeşil, temizlenmesi EN KOLAY renk**, çünkü rengi biz
seçtik ve hiçbir gerçek kıyafet ona yakın değil.

Sızıntı ölçüldü (chroma yeşil base, 3 katman): #10'da **51 px** (çenede,
ekranda yeşil nokta olarak görünüyordu), #16'da **205 px**, #14'te 6 px.

**Kalibrasyon — aralık geniş:**

| | yeşil paletine uzaklık |
|---|---|
| sızan yeşil pikseller | medyan **60.3** · %95'i 70.3 altında |
| dolaptaki kıyafetler | en yakın **107.0** (#14) · 117.4 · 129.4 |

`EXTRACT_COLOR_TOLERANCE = 78` aradan geçiyor: sızıntının ~%97'sini yakalıyor,
en yakın kıyafete 29 birim pay bırakıyor. Güvenlik kuralı (§7.6'nın simetrisi):
kıyafet çıkarım rengine 97.5'ten yakınsa filtre atlanıyor — gerçekten neon
yeşil bir kıyafet kendini koruyor.

| katman | önce yeşil | sonra yeşil | kaplama |
|---|---|---|---|
| #10 | 51 px | **0** | %8.44 → %8.42 |
| #14 | 6 px | 4 px | %8.60 → %8.58 |
| #16 | 205 px | **0** | %7.78 → %7.75 |

Görsel: çenedeki yeşil nokta tamamen gitti, kıyafet kaybı yok. Ücretsiz
(`--reextract`).

> ⚠ **İlk denemede sayı ölçmeden konmuştu (tolerans 90 → güvenlik eşiği 135) ve
> filtre HİÇ TETİKLENMEDİ:** kıyafetler yeşile 107-129 uzaklıkta olduğu için
> hepsi "kıyafete çok yakın" sayılıp atlanıyordu. Yeşil sayısı hiç değişmedi ve
> bu ancak ölçünce görüldü. *Etkisiz bir filtre, olmayan bir filtreden daha
> tehlikeli — çünkü sorun çözülmüş sanılıyor.*

**Sakalın kendisi çıkarım base'inde hâlâ yeşil** (1.382 px): sakal boyun
gölgesi üzerinden yakaya BAĞLI, yani maske tek bileşen ve §44.7'deki eleme
onu ayıramıyor. Ama artık önemi yok — katmana sızsa bile bu filtre siliyor.
Kullanıcı çıkarım base'ini zaten hiç görmüyor.

365 test geçiyor.

### 44.9 Slota özel yeşil varyantlar — DENENDİ, ÖLÇÜLDÜ, KULLANILMIYOR

Kullanıcının fikri: yeşil yalnızca giydirilecek bölgede işe yarıyor, o hâlde
üst giydirilirken sadece üst, alt giydirilirken sadece alt boyansın — manken
başına üç varyant. Mantık sağlamdı: dışarıda kalan yeşil yalnızca sızıntı
riski.

**Uygulandı.** `_kiyafet_bolumleri()` üst/alt giysiyi PARLAKLIK sıçramasıyla
ayırıyor ve bölme yalnızca güvenilirse yapılıyor:

| manken | üst-alt parlaklık farkı | bölme |
|---|---|---|
| manken 2 (koyu tişört + açık şort) | **110.8** | yapılıyor, sınır tam belde |
| base (mavi tişört + mavi şort) | 8.8 | YAPILMIYOR — tamamı boyanır |

Eşik 30. Yanlış yerden bölmek, bölmemekten kötü olurdu (üst giydirilirken
göğsün yarısı boyasız kalırdı).

Üç varyant üretildi: TAM 133.782 px yeşil · ÜST 87.613 (y%26-55) · ALT 46.816
(y%55-72). Görsel olarak bölme kusursuzdu.

**Ama ölçüm fikri desteklemedi** (3 çağrı, 6 kredi, tohum 42):

| katman | TAM kaplama | SLOT kaplama | TAM sızıntı | SLOT sızıntı |
|---|---|---|---|---|
| #10 | %8.42 | %8.44 | %0.0 | %0.0 |
| #14 | %8.58 | %9.13 | %0.1 | %0.7 |
| **#16 chino** | **%7.75** | **%6.71** | %2.7 | **%3.0** |

Gözle: slot varyantında chino'nun uyluğunda soluk bir yama çıktı, TAM'da yok.
#16 hem sayıca hem gözle kötüleşti; #14'te kaplama arttı ama sızıntı 7 kat.

**Karar: slot varyantları KULLANILMIYOR.** Varyant dosyaları silindi, yani
`extraction_image` tam varyanta düşüyor ve davranış ölçümle en iyi bulunan
hâlde. Mekanizma (`slot` parametresi, `_kiyafet_bolumleri`,
`slot_for_category`) kodda duruyor — üretmek tek çağrı, biri tekrar denemek
isterse ölçüm kaydıyla birlikte hazır.

Neden işe yaramadığı ÖLÇÜLMEDİ. Makul hipotez: kısmen boyanmış bir görüntü
modele daha "karışık" geliyor olabilir; ya da fark tohum sabit olsa bile
girdi değiştiği için difüzyonun farklı bir gerçeklemesine düşüyor. İkisi de
test edilmedi.

> Bu, oturumun beşinci "mantıklı fikir ölçümde çürüdü" vakası. Fikir yanlış
> değildi — dışarıdaki yeşil gerçekten gereksiz — ama kazancı, girdiyi
> değiştirmenin bedelinden küçük çıktı.

365 test geçiyor · katmanlar TAM yeşil sürümüne geri alındı.

---

## 45. Bu turun sonu — durum ve sıradaki iş

### 45.1 Mimarinin bugünkü hâli: ÜÇ base

| dosya | rengi | kim kullanıyor | kullanıcı görür mü |
|---|---|---|---|
| `base_{id}.png` | gerçek fotoğraf | Faz 4 zinciri · gösterim kaynağı · zemin | evet |
| `base_{id}_extract.png` | **chroma yeşil** | VTON + fark çıkarımı (§44) | **hayır** |
| `base_{id}_display.png` | nötr koyu | 2+ kıyafetli bindirmenin zemini | evet |

Sahnede ne gösterildiği (§38, §40, §43):

| seçim | görüntü |
|---|---|
| boş | gerçek fotoğraf |
| 1 kıyafet | **ham VTON çıktısı** — ücretsiz, zaten diskte, çıkarım kusuru yok |
| 2+ kıyafet, hepsi uzak renkte | nötr zemin + katmanlar |
| 2+ kıyafet, biri kör noktada | gerçek fotoğraf zemin + katmanlar |

### 45.2 Açık sorular / ölçülmemişler

1. **Base mankeninin (#1) çıkarım base'i YOK.** Orada kör nokta zaten yoktu
   (en yakın kıyafet 40.7) ama yeşile geçmek katman kalitesini artırabilir.
   12 katmanın yeniden üretimi = **24 kredi**. Ölçülmedi.
2. **Slot varyantları neden işe yaramadı** (§44.9) — iki hipotez var, ikisi de
   test edilmedi.
3. **Sakal çıkarım base'inde hâlâ yeşil** (1.382 px): boyun gölgesi üzerinden
   yakaya bağlı, bileşen elemesi ayıramıyor. `drop_extract_color` katmandan
   sildiği için pratikte zararsız.
4. **`data/layer_surumleri/` şişti** (~20 dosya) ve hangisinin canlı olduğu
   dosya adından anlaşılmıyor. Bir adlandırma kuralı ya da `AKTIF.txt` iyi olur.
5. §29'daki eski liste hâlâ geçerli: aksesuar ölçümü (2 kredi), ayakkabı için
   tam boy base, §18.2'nin üç yollu render karşılaştırması.
6. **`git init` yapılmış ama hâlâ hiç commit yok.** Bu turda ~15 dosya değişti.

### 45.3 Bu turun yöntem dersleri

Beş kez "mantıklı fikir ölçümde çürüdü" (§39 ×3, §42, §44.9), üç kez metriğin
kendisi yanıldı (§34.5). Kullanıcının koyduğu kural kayda geçti:

> **Hem sayı hem gözle ölç.** Görsel doğrulama metrik doğrulamanın yerine
> geçmez ama onun **veto hakkı** vardır.

İkinci kural (§44.8'den):

> **Etkisiz bir filtre, olmayan bir filtreden tehlikelidir** — sorun çözülmüş
> sanılır. Filtre eklerken tetiklendiğini de ölç.

Üçüncüsü, bu projede dördüncü kez geçerli oldu (§25.5):

> **Bir ölçümün geçerliliği, ölçüldüğü koşulların hâlâ geçerli olmasına
> bağlı.** Sağlayıcı, model ya da base değişince eski ölçüm yeniden yapılmalı.

---

## 46. Tek kıyafette ekranda YEŞİL görünüyordu ✅

§44 çıkarım base'ini chroma yeşile boyadı ve kör noktayı kapattı. Ama §38'deki
"tek kıyafette ham VTON çıktısını göster" kararı bununla birlikte sessizce
bozuldu: **ham çıktı artık yeşil base'e karşı üretiliyor**, yani kıyafetin
örtmediği her yer ekranda yeşil. Üst giydirilince şort, alt giydirilince
tişört; ayrıca çenede ve ayak bileklerinde yeşil lekeler.

İki karar tek tek doğruydu, birleşimleri yanlıştı — kimse ikisinin kesişimine
bakmamıştı.

### 46.1 Çözüm: yeşili gerçek fotoğrafla DOLDUR

`layers.restore_extract_color()` — `drop_extract_color`'ın simetriği. O, yeşili
katmandan siliyor; bu, ham çıktıda gerçek fotoğrafla değiştiriyor. Değiştirme
piksel piksel yapılabiliyor çünkü çıkarım base'i gerçek fotoğrafın yalnızca
yeniden renklendirilmiş hâli — poz ve kadraj birebir aynı (§44.1).

Güvenlik kuralı aynı: kıyafetin kendi paleti çıkarım rengine yakınsa (gerçekten
neon yeşil bir kıyafet) hiç dokunulmuyor.

Çıkarım base'i olmayan mankende `dressed_for_display` ham çıktıyı olduğu gibi
döndürüyor — yani bu özelliği kullanmayan kurulumda davranış birebir eskisi.

### 46.2 ⚠ İLK ÖLÇÜMÜM DAİRESELDİ

Tolerans 78 ile sildim, sonra **tolerans 78 ile ölçtüm** ve "0 yeşil piksel"
raporladım. Ekranda ise yeşil kontur duruyordu. §34.1'in hatasının aynısı.

Palete bakmayan bağımsız ölçüte geçildi — *yeşil kanal diğer ikisini 20'den
fazla geçiyor mu*; mankenin gerçek fotoğrafında bu sayı **0**, yani ölçüt
kalibre. Gerçek sayı ortaya çıktı: **1.267 px** kalıntı.

Sebep: yeşil bölgenin dış sınırındaki anti-alias pikselleri yeşille komşusunun
karışımı, o yüzden palete uzaklıkları eşiğin ÜSTÜNDE ve filtre onlara
dokunmuyor. Ekranda kıyafeti saran ince neon kontur olarak görünüyordu.

### 46.3 Maske genişletmesi — ölçülen takas

| genişletme | #14 | #16 | #10 | kaplama (#14) |
|---|---|---|---|---|
| 0 | 1.267 | 1.390 | 1.369 | 42.760 |
| 2 | 94 | 27 | 82 | 46.541 |
| **3** | **0** | **20** | **2** | 48.453 |
| 4 | 0 | 11 | 1 | 50.371 |

3 seçildi: sayıda tabana iniyor, bel hizasına yakın planla bakıldığında kontur
tamamen kayboluyor ve **kıyafetin kenarı yenmiyor**. Bedeli %13 daha fazla
piksel — hepsi gerçek fotoğraftan geldiği için görsel maliyeti yok.

Son durum (bağımsız ölçüt, gerçek fotoğraf tabanı 0):

| kıyafet | ham çıktı | düzeltilmiş |
|---|---|---|
| #14 lacivert tişört | 42.246 | **0** |
| #16 chino | 72.556 | **20** |
| #10 sarı tişört | 41.037 | **2** |

Gözle: yeşil şort kişinin gerçek desenli şortuna, yeşil tişört gerçek lacivert
tişörtüne döndü; çene ve ayak bilekleri temiz.

### 46.4 Önbellek ve sürüm damgası

Dönüşüm ilk çağrıda ~500 ms, sonra diskten 4 ms
(`g{id}_m{mid}_raw_display.png`). Önbellek kaynaklarından eskiyse yeniden
üretiliyor.

`dressed_rev` artık ham çıktı ile çıkarım base'inin **ikisinin** damgasından
türüyor: yalnızca ham çıktıya bakmak, çıkarım base'i yenilendiğinde URL'i
değiştirmez ve tarayıcı bayat görüntü servis ederdi (§25.7).

371 test geçiyor (6 yeni).

> **Ders:** bir mimari değişiklik, kendisinden ÖNCE alınmış ve hâlâ doğru
> görünen kararları geçersizleştirebilir. §44 kör noktayı kapattı ama §38'in
> dayandığı "ham çıktı gösterilebilir" varsayımını sessizce yıktı. Değişiklik
> sonrası "bu kararın dayanağı hâlâ duruyor mu?" diye taranmalı.

### 46.5 ⚠ Düzeltme ÇALIŞMIYOR göründü — kod doğruydu, DAMGA yanlıştı

Kullanıcı sunucuyu yeniden başlattı ve "sadece pantolon giydirince çalışıyor,
üst giydirince altlarda çalışmıyor" diye bildirdi. Kod tarafında böyle bir
ayrım yok — ve gerçekten de yoktu.

Sunucudaki dosyalar doğruydu (#14 yeşil=0, #10=2, #16=20). Sorun URL damgasıydı:

```
damga = max(ham_mtime, cikarim_mtime)
ham çıktı  18:01   >   çıkarım base'i  17:53   →   max = ham_mtime
```

yani damga **düzeltme öncesiyle birebir aynı sayı** çıkıyordu. `?v=` değişmeyince
tarayıcı eski YEŞİL görüntüyü belleğinden servis etti. "Pantolonda çalışıyor,
üstte çalışmıyor" bir kod farkı değil, hangi görselin tarayıcı önbelleğinde
kaldığıyla ilgili şanstı.

**Kök sebep:** damga yalnızca KAYNAK dosyaları izliyordu, ama gösterilen görüntü
üç şeyden türüyor — ham çıktı, çıkarım base'i ve **dönüşümün algoritması**.
Üçüncüsü atlanmıştı. Aynı açık diskteki önbellekte de vardı: saçak genişletmesi
eklendiğinde kopyaları elle silmek gerekmişti (o an fark edilmedi).

**Düzeltme:** `layers.RESTORE_VERSION` eklendi. Sürüm hem önbellek dosya adında
(`g14_m139_raw_display_v1.png` — eski kopyalar kendiliğinden devre dışı) hem de
damgada. Doğrulandı: damga 1787065294 → 1787065295.

İki testi var: sürüm artınca damga değişmeli, ve sürüm dosya adında olmalı.

373 test geçiyor.

> **Ders:** bir önbellek anahtarı, çıktıyı belirleyen HER girdiyi içermeli —
> kodun kendisi de bir girdidir. "Kaynak dosya değişmediyse çıktı da
> değişmemiştir" varsayımı, dönüşümü siz değiştirdiğinizde bozuluyor.
> Ve bu hata sinsi: sunucu doğru, testler yeşil, kullanıcı yanlış görüyor.

---

## 47. Aksesuarın alt türüne göre bölge bandı ✅

§29'un 5. maddesi açıktı: *"saat/aksesuarın gerçekten çalıştığını ölçmek —
tryon-max'in saati bileğe doğru yerleştirdiği DENENMEDİ."* Denendi. Model
doğru yapıyor; **hata çıkarımdaydı.**

### 47.1 Belirti

Kullanıcı saati kombine ekledi, ekranda hiçbir şey görünmedi. Ama saati TEK
başına seçince görünüyordu. İki görüntü farklı: tek kıyafette ham VTON çıktısı
gösteriliyor (§38), 2+ kıyafette katman bindiriliyor.

Katmanın içinde saat yoktu — 5.513 px, konum **y %1.5-9.2**, renk `[91 76 68]`.
Başın tepesi ve saç.

### 47.2 Kök sebep: `largest_component` küçük nesnede ters tepiyor

Fark saati DOĞRU buluyor, ama 4. sırada:

| px | y | bölge | renk |
|---|---|---|---|
| 3.498 | %0.0-2.4 | baş | tavan/arka plan |
| 3.486 | %0.6-10.5 | baş | saç |
| 2.537 | %8.8-23.1 | boyun | yüz |
| **1.894** | **%63.5-67.4** | **bilek** | **`[125 122 124]` — SAAT** |

`largest_component` en büyüğü tutup gerisini atıyor. Tişörtte doğru (kıyafet
zaten en büyük parça), saatte yanlış: difüzyonun saçta ve tavanda ürettiği
gürültü saatten büyük.

Bölge kapısı (§30) da koruyamıyor, çünkü aksesuarda bilinçli olarak kapalıydı:
*"şapka başta, kolye boyunda, saat bilekte; kapı burada tanım gereği anlamsız."*

### 47.3 ⚠ İlk fikir ÖLÇÜMDE ÇÜRÜDÜ

Önce "en büyük bileşen" yerine **kıyafetin kendi rengine en yakın bileşen**
önerildi. Saatte çalışıyordu (paletine uzaklık 23.5, en yakın bileşen saat).

Üçüncü örnekte çöktü. Bilekliğin paleti:

```
[248 253 252] · [6 7 8] · [81 86 83] · [230 250 250]
```

Neredeyse beyaz **ve** neredeyse siyah — metalin doğası: parlak yansıma +
koyu gölge. Palet nesnenin rengini değil parlaklık uçlarını temsil ediyor ve
hiçbir bileşenle anlamlı eşleşmiyor. İnce zincir ayrıca 15.840 parçaya
bölünmüş, tek bileşen olarak hiç durmuyor.

Saatte 23.5 (saat) ile 31.5 (saç) arasında yalnızca 8 birim vardı — tek
örnekle eşik koymanın klasik tuzağı (§20.1). *İyi ki üç örnek toplanmadan
uygulanmadı.*

### 47.4 Uygulanan: alt türe özel bant + kişi maskesi

Kategori "her yerde" derken **alt tür kesin konuşuyor**: saat bilekte, şapka
başta. VLM zaten `subcategory` çıkarıyor (`ACCESSORY_BANDS`, en uzun anahtar
kazanıyor — "kral zincir bileklik" hem `zincir` hem `bileklik` içeriyor ve
daha özgül olan doğru cevabı veriyor).

**Aksesuarda güvenlik freni YOK.** Fren "kapı çoğunu yiyorsa bant yanlıştır"
varsayımına dayanıyor; kıyafette doğru, aksesuarda tam ters — saat tuvalin
%0.2'si, kapının %95+ atması beklenen davranış. Fren çalışsaydı kapı her
seferinde devre dışı kalırdı (§44.8'in dersi).

Bant tek başına yetmedi: bilek bandında duvar da var. Kesişim `person_mask`
ile alındı — ölçüm ayrımı tartışmasız yaptı:

| | bandın içinde kalan, kişi maskesinin İÇİNDE |
|---|---|
| şapka | %98.4 |
| saat | %88.6 |
| **bileklik** | **%0.0** (kalan tek şey sağ kenardaki duvar, x %80.9-99.9) |

### 47.5 Sonuç (ücretsiz, `--reextract`)

| | önce | sonra |
|---|---|---|
| **saat** | 5.513 px · y %1.5-9.2 · saç | **1.267 px · y %64.1-67.1 · BİLEK** ✅ |
| **şapka** | 12.383 px · y %2.6-11.6 · baş | 12.171 px · aynı yer ✅ regresyon yok |
| bileklik | 5.433 px · y %1.5-8.4 · saç | 961 px · y %72.7-76.6 · el |

Gözle doğrulandı: saat bileğe oturdu — gümüş çelik kordon, lacivert kadran,
dolaptaki görselin aynısı. Şapka hiç değişmedi.

382 test geçiyor (9 yeni).

> **AÇIK İŞ — bileklik hâlâ yanlış.** Model zinciri **BOYNA** taktı, yani ham
> çıktıda bilekte zaten hiçbir şey yok. Çıkarım bunu düzeltemez; kalan 961 px
> el bölgesindeki gürültü ve kaplaması (%0.09) saatinkine (%0.11) çok yakın
> olduğu için boyutla ayırmak da mümkün değil. Denenmemiş çözüm: bilekliği
> bileğe sarılmış hâlde, bilek görünecek şekilde yeniden çekmek (§27'nin şablon
> fikri) — 2 kredi.
>
> **Ayrıca:** iki aksesuar hâlâ AYNI ANDA giyilemiyor. `slots` kategoriden
> geliyor ve aksesuarın tek slot'u var, yani şapka seçilince saat düşüyor.
> `ACCESSORY_BANDS`'in anahtarları bu slot'u da verebilir (`bas`/`bilek`/
> `boyun`/`bel`) ama bu şema değişikliği — yapılmadı.

### 47.6 Şapkanın ortası açıktı — Lab filtresi şapkayı yiyordu

Kullanıcı bildirdi: şapka kafaya oturmuyor ve **ortası açık**, altından saç
görünüyor. Katmanda 655 px'lik tek parça bir delik ölçüldü (tepede, y50-82).

Delik bölgesinde ham fark **115.3** (eşik 18), yani maske orayı yakalıyor —
sonradan bir adım siliyordu. Kişi maskesi %100 kapsıyordu, o değildi.

**Suçlu: `drop_base_leak_lab`.** Kapatınca şapka 12.171 → **20.701 px** ve
delik **655 → 0**. Yani filtre şapkanın **%41'ini** yiyordu.

Sebep, filtrenin kendi varsayımının çökmesi: iki yönlü test "piksel kıyafetin
paletine mi, aynı koordinattaki base pikseline mi yakın" diye soruyor. Şapka
`[61 106 154]`, base'in tişörtü `[67 96 144]` — Lab uzaklığı **4.0**. İki palet
çakışınca sorunun cevabı yok.

`min_keep` freni yakalayamadı: %58.8 kaldığı için eşiğin (0.55) üstünde. Fren
"çoğunu yerse" diyor; buradaki hasar "yarısına yakınını yerse".

**Çözüm:** `drop_base_clothing` ve `drop_extract_color`'da zaten olan güvenlik
kuralının aynısı — ayrım yapılamayacak durumda filtre kendini durdursun.
Eşik dolabın tamamında kalibre edildi:

```
şapka 4.0 │ 12.0  14.8  15.8  17.7  27.5  27.8 ... 87.8
          └─ BASE_LEAK_LAB_SAFE_DISTANCE = 8: yalnızca şapka atlıyor
```

12'deki lacivert tişört filtreyi kullanmaya devam ediyor — filtrenin varlık
sebebi zaten o (§19).

**Cerrahi olduğu ölçüldü.** `--reextract` sonrası 6 katman değişti, ama koruma
kapalıyken de aynı değerleri verdiler: beşi eski kodla üretilmiş oldukları için
değişti (bayat katmanlar), koruma yalnızca #18'i etkiledi.

| # | koruma kapalı | koruma açık |
|---|---|---|
| 7, 9, 12, 13, 16, 5 | değişmedi | değişmedi |
| **18 şapka** | 12.171 | **20.701** |

Gözle: logonun ortasındaki delik kapandı (aslan tam görünüyor), saç tepeden
geçmiyor. Şapka hâlâ biraz yüksek duruyor — o modelin yerleştirmesi, çıkarım
değil.

384 test geçiyor (2 yeni).

> **Yan bulgu:** dolapta 5 katman eski kodla üretilmiş hâlde duruyormuş
> (g7 -%22.6, g9 -%2.1, g12 -%3.2, g13 -%7.4, g16 +%26.5). `--reextract`
> hepsini güncel hatta çekti. Katmanların hangi kod sürümüyle üretildiği
> hiçbir yerde tutulmuyor — §46.5'teki `RESTORE_VERSION` fikrinin katman
> tarafında da karşılığı olmalı. Yapılmadı.

### 47.7 GERİ ALINDI — aksesuar dolaptan çıkarıldı

Şapka düzeltildikten sonra kullanıcı **çalışan kıyafetlerin bozulduğunu**
bildirdi: gri şortun ve beyaz tişörtün kenarlarında base'in lacivert kıyafeti
taşıyordu. Haklıydı.

**Sebep benim hatam.** `build-layers --reextract` komutunu tek bir kıyafete
değil **tüm dolaba** çalıştırdım. Bu, 5 katmanı (g7, g9, g12, g13, g16) yeniden
üretti — ve o katmanlar aslında BAYAT DEĞİL, ÇALIŞIR hâldeydi. Piksel
sayılarındaki değişimi gördüm (g7 -%22.6, g13 -%7.4) ama "güncel hatta çekildi"
diye yorumlayıp **gözle bakmadım.** Katman küçülünce altından base'in lacivert
kıyafeti göründü.

§25.5'in dersi bir kez daha, bu sefer bana: *bir sayının yönü (arttı/azaldı)
iyi mi kötü mü olduğunu söylemez.* Kaplamanın azalması "temizlendi" de olabilir
"delindi" de; ayıran tek şey göz.

**Kurtarma:** g7, g9, g12, g13 `data/layers_yedek_kapi_20260813_1655`'ten
birebir geri yüklendi (piksel sayıları reextract öncesiyle aynı). g16 için o
tarihli yedek DAHA KÖTÜYDÜ (yüzde hayalet yüz, boyunda mavi yaka — §30'un
vakası), o yüzden yeni sürümü bırakıldı; gözle karşılaştırıldı.

**Karar:** aksesuar kısmı tamamen çıkarıldı (kullanıcının teslim tarihi vardı
ve risk almaya değmezdi). #17 saat, #18 şapka, #19 bileklik dolaptan silindi;
`ACCESSORY_BANDS`, kişi maskesi kesişimi ve `BASE_LEAK_LAB_SAFE_DISTANCE`
kod tarafında geri alındı. Dolap 12 kıyafet, 373 test.

**Bilgi kayboldu mu:** hayır. §47.1-47.6 ölçümleriyle duruyor. Yeniden
denenecekse başlangıç noktası orası — özellikle *alt türe göre bant* fikri
çalışıyordu (saat saçtan bileğe taşındı, şapka regresyon vermedi).

> **Geri alınırken dikkat:** `--reextract`'i asla tüm dolaba çalıştırma.
> `--id N` ile tek tek, ve her birine GÖZLE bak. Katmanların hangi kod
> sürümüyle üretildiği hiçbir yerde tutulmuyor (§46.5'teki `RESTORE_VERSION`
> fikrinin katman tarafında karşılığı yok) — bu yüzden hangi katmanın
> yenilenmeye ihtiyacı olduğu bilinemiyor.

**Ek (§47.7):** aksesuar çekim şablonları da kaldırıldı (9 şablon: saat,
bileklik, kolye, şapka, kasket, bere, çanta, kemer, atkı). Yükleme formundaki
şablon listesi tamamen `/api/templates`'ten türediği için "Aksesuar" grubu
kendiliğinden kayboldu — arayüzde sabit kodlanmış hiçbir kategori adı yok,
o tasarım burada işe yaradı. Şablon sayısı 22 → 13.

`config.CATEGORIES`'teki `aksesuar` satırı **duruyor**: z-sırası ve slot kuralı
mimarinin parçası ve README'de belgeli, kaldırmak testlere ve dokümana yayılırdı.
Kullanılmıyor, zararsız. Kategori kapsama testi artık `ayakkabi` gibi onu da
bilerek dışarıda bırakıyor.

371 test geçiyor.

### 47.8 §47.7'deki g16 kararı YANLIŞTI — düzeltildi

§47.7'de reextract'in bozduğu 5 katmandan dördü yedekten geri yüklenmiş, g16
için "yeni sürüm daha iyi" denip bırakılmıştı. **Yanlış karardı.**

Hata yöntemdeydi: iki sürümü karşılaştırırken yalnızca YÜZ bölgesine baktım.
Yedekteki 247.079'luk sürümde yüze binen hayalet yüz apaçıktı, o yüzden
199.698'i seçtim. Ama 199.698'in kendi kusuru **bacaklarda ve kalçadaydı** ve
kadrajın o kısmına hiç bakmadım. Kullanıcı kombinde gördü ve bildirdi.

Kayıp sürüm aslında diskte duruyormuş: `layer_surumleri/g16_m1_v1_poligon-kirpik.png`,
tam 157.884 px. Ayırt edici işaret dikey aralıkta:

| sürüm | px | y aralığı | kusur |
|---|---|---|---|
| **v1 (doğru)** | 157.884 | **%52.7-99.9** | temiz |
| reextract | 199.698 | %46.0-99.9 | kalçada hayalet kontur |
| yedek_kapi | 247.079 | %1.9-99.9 | yüzde hayalet yüz |

Pantolon katmanının bele kadar (%46) çıkması zaten şüpheli: `REGION_BANDS`
"alt" için %46'dan başlıyor, yani katman bandın en üst sınırına dayanmış.
**Bant sınırına dayanan bir katman, kapının onu kurtaramadığının işareti.**

g10 da 470 px farkla (188.308 → 187.838) reextract'ten kalmıştı; iki ayrı yedek
188.308'de hemfikir olduğu için o da geri alındı. Artık 11 katmanın tamamı
çalışan durumla **birebir aynı** ve altı kombin gözle tarandı.

> **Ders:** bir görüntüyü "daha iyi" diye seçerken kadrajın TAMAMINA bakmak
> gerekiyor. Bir bölgedeki apaçık kusur, başka bölgedeki kusuru görmene engel
> oluyor — dikkat kötüye gidiyor, iyiye değil. §47.7'de sayıya güvenip gözle
> bakmamıştım; burada gözle baktım ama **yanlış yere** baktım. İkisi ayrı hata.
