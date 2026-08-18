# 👕 AI Sanal Dolap

Kullanıcının kendi kıyafetlerini fotoğraflayıp dijital dolabına eklediği, sonra
bu kıyafetleri bir manken üzerinde **manuel giydirebildiği** ve AI'dan kombin
önerisi alabildiği bir araç.

```
Fotoğraf → Arka plan temizleme → Öznitelik çıkarımı → Dolap
                                                        ↓
                          Katman üretimi (VTON, 1 kez/kıyafet)
                                                        ↓
                    Manuel giydirme  ·  AI kombin önerisi
```

**Durum: Faz 0 tamamlandı** (dolap altyapısı). Faz 1-5 yol haritasında.

---

## Hızlı başlangıç

```bash
python -m venv venv && venv\Scripts\activate     # Windows
pip install -r requirements.txt

python cli.py init                               # veritabanını kur
python cli.py add fotograflar/mavi_gomlek.jpg    # tek kıyafet
python cli.py add-folder ./fotograflar           # klasördeki her şey
python cli.py list                               # dolabı gör
python cli.py stats                              # özet
```

Gerçek Claude öznitelik çıkarımı için `.env.example`'ı `.env` olarak kopyalayıp
`ANTHROPIC_API_KEY` gir. **Anahtar yoksa sistem çökmez:** renk gerçekten
görselden çıkarılır, kategori dosya adından tahmin edilir, kayıt
`attr_source="mock"` ile düşer. Yani tüm hat anahtarsız da uçtan uca çalışır.

### Tüm komutlar

| Komut | Ne yapar |
|---|---|
| `python cli.py init` | Şemayı kurar, varsayılan mankeni ekler |
| `python cli.py add <foto> [--no-vlm]` | Bir kıyafeti dolaba ekler |
| `python cli.py add-folder <klasör> [--no-vlm]` | Klasördeki tüm görselleri ekler |
| `python cli.py list [--category ust]` | Dolabı listeler |
| `python cli.py show <id>` | Tek kıyafetin detayı + dosya yolları |
| `python cli.py rm <id>` | Kıyafeti siler |
| `python cli.py stats` | Kategori dağılımı |
| `python cli.py doctor` | Kurulum/anahtar kontrolü (anahtarı maskeli gösterir) |
| `python cli.py mannequin [--from-photo X \| --placeholder]` | Base mankeni oluşturur |
| `python cli.py build-layers [--id N] [--force] [--provider mock\|fal]` | Katmanları üretir |
| `python cli.py preview 1 2 3 -o kombin.png` | Katmanları birleştirir |
| `pytest` | 104 test |

---

## Mimari kararlar

### 1. Her kombinde VTON çalıştırılamaz — katman bir kez üretilir

Kullanıcı manuel deneme yaparken 20-30 kombin dener. Her seçimde difüzyon
modeli çalıştırmak **her tıklamada 15-40 saniye + her tıklamada para** demek.
Kullanılamaz.

Bunun yerine:

```
YÜKLEME ANINDA (kıyafet başına 1 kez):
  fotoğraf → arka plan temizle → VTON(sabit_manken, kıyafet)
           → sonuçtan kıyafet bölgesini kes → şeffaf PNG katmanı kaydet

GİYDİRME ANINDA (her tıklamada):
  katmanları z-sırasına göre üst üste bindir → anında (<50ms), bedava
```

Bütün katmanlar **aynı manken, aynı poz** üzerinden üretildiği için piksel
piksel hizalı; üst üste bindirme birebir tutuyor.

- **Maliyet:** 100 kıyafet × ~$0.03 = tek seferlik ~$3. Sonra sınırsız kombin.
- **Faz 5 bonusu:** kullanıcıya özel manken geldiğinde aynı çağrılar yeni
  mankende tekrarlanır; mimari değişmiyor.

### 2. Kategori tablosu = katman sırası + çakışma kuralı

`config.CATEGORIES` sadece etiket listesi değil. İki alan taşıyor:

| Kategori | `z` (katman sırası) | `slots` (kapladığı bölge) |
|---|---|---|
| Ayakkabı | 10 | `ayak` |
| Alt giyim | 20 | `alt` |
| Elbise | 25 | `ust`, `alt` |
| Üst giyim | 30 | `ust` |
| Dış giyim | 40 | `dis` |
| Aksesuar | 50 | `aksesuar` |

`z` çizim sırasını, `slots` de "hangi ikisi aynı anda giyilemez"i belirliyor.
Elbise hem `ust` hem `alt` kapladığı için tişört seçilince otomatik düşer.
Faz 2'nin giydirme mantığı tamamen bu tabloya dayanacak.

### 3. Arka plan temizleme neden kritik

Faz 1'de kullanılacak VTON modelleri (IDM-VTON, CatVTON, Kolors…) beyaz zeminde,
düz serilmiş **katalog görselleriyle** eğitildi. Kullanıcının yatağın üstünde
çektiği buruşuk tişört bu modellerde kötü sonuç veriyor. Ön-işleme kalitesi tüm
hattın tavanını belirliyor.

İki yol var, hangisinin kullanıldığı DB'ye yazılıyor (`garments.cutout_method`):

| Yöntem | Ne zaman | Kalite |
|---|---|---|
| `rembg` | Kuruluysa (opsiyonel, ~170MB model indirir) | İyi |
| `flood` | rembg yoksa — saf numpy/PIL yedeği | Düz zeminde makul |

`flood` yedeği kenarlardan taşarak (flood fill) arka planı buluyor. Kritik
ayrıntı: bir pikselin arka plan sayılması için sadece **arka plan rengine yakın**
olması yetmiyor, ayrıca **kenara bağlı** olması gerekiyor — yoksa beyaz tişörtün
üstündeki beyaz baskı da silinip kıyafette delik açılıyor.

Daha iyi kırpma için:

```bash
pip install rembg
```

### 4. Öznitelik çıkarımı: yapılandırılmış çıktı, serbest metin değil

`wardrobe/vision.py` Claude'a JSON şeması dayatıyor (`output_config.format`), yani
model serbest metin değil şemaya uyan JSON üretmek zorunda — regex ile ayrıştırma
yok. Çıkarılan alanlar:

`category` · `subcategory` · `color_name` · `color_hex` · `secondary_color_hex` ·
`pattern` · `style` · `seasons` · `fabric` · **`warmth` (0-10)** ·
**`formality` (0-10)** · `notes`

Son iki alan sadece etiket değil, **Faz 3'ün kural filtresinin girdisi**:
"18 derece" → warmth aralığı, "mülakat" → formality aralığı.

Üç mühendislik ayrıntısı:

- **Görsel 1024px'e küçültülüyor.** Telefon fotoğrafı 4000px+ geliyor; kıyafet
  özniteliği için 1024 fazlasıyla yeterli ve token maliyetini birkaç kat düşürüyor.
- **EXIF döndürme elle uygulanıyor.** Telefon fotoğraflarında piksel verisi yan,
  sadece etiket "dik" diyor. PIL bunu kendiliğinden yapmıyor.
- **VLM'e kırpılmış görsel gidiyor**, orijinal değil — arka plan gürültüsü
  olmadan renk ve desen belirgin biçimde daha isabetli.

### 5. Katmanı segmentasyonla değil, **farkla** çıkarıyoruz

Manken sabit olduğuna göre, giydirme sonrasında **değişen pikseller kıyafetin
ta kendisidir.** Yani katmanı ayıklamak için ayrı bir segmentasyon modeline
gerek yok:

```
base (çıplak manken)  ─┐
                       ├─►  |fark| > eşik  ─►  temizle  ─►  RGBA katman
dressed (giydirilmiş) ─┘
```

Ham fark yetmiyor, iki temizlik adımı şart:

| Sorun | Çözüm |
|---|---|
| Difüzyon mankenin geri kalanını da milimetrik oynatıyor → serpinti | **Açma** (aşındır→genişlet) |
| Kıyafet rengi tene yakın olduğu yerde fark zayıf → katmanda delik | **Kapama** (genişlet→aşındır) |

> ⚠️ **`int32` kullanmak zorunlu.** `int16`'da `255² = 65025` taşıyor (tavan
> 32767), fark negatife dönüp `sqrt` NaN üretiyor, `NaN > eşik` her zaman
> `False` — katman sessizce boşalıyor. Üstelik bu tam olarak ayırt edilmesi en
> kolay durumda oluyor (beyaz mankene siyah pantolon). Regresyon testi:
> `test_layers.py::test_yuksek_kontrast_katmani_yakalar`.

### 6. VTON sağlayıcısı değiştirilebilir

`wardrobe/vton.py` tek bir arayüz sunuyor: `try_on(model, garment, category)`.
Arkasında `fal` (FASHN v1.6) ve `mock` var; sağlayıcı değiştirmek tek satır:

```bash
python cli.py build-layers --provider mock   # bedava, sahte katman
python cli.py build-layers --provider fal    # gerçek
```

Bu, modelleri A/B karşılaştırmayı kod değişikliği olmaktan çıkarıyor.

FASHN'ın parametreleri fal'ın OpenAPI şemasından doğrulandı (tahmin değil):
`category ∈ {tops, bottoms, one-pieces}`, `garment_photo_type=flat-lay`
(cutout hattımızın ürettiği tam olarak bu).

**Bilinen sınır:** FASHN'ın kategori listesinde **ayakkabı ve aksesuar yok.**
Zorlamak bozuk katman üretiyor, o yüzden bu kategoriler `status="unsupported"`
olarak işaretlenip atlanıyor — sessizce başarısız olmuyor.

### 7. Dosyalar UUID ile saklanıyor, orijinal ad ipucu olarak taşınıyor

`beyaz_gomlek.jpg` → `data/raw/a3f9c2d81e40.jpg`. Aynı adlı iki fotoğraf
çakışmıyor. Ama orijinal ad boşa gitmiyor: yedek çıkarım yolunda kategori
tahmini için `name_hint` olarak geçiliyor.

---

## Veri modeli

Şema Faz 0'da kuruluyor ama sonraki fazların tablolarını da içeriyor — ilerledikçe
migration yazmak gerekmiyor.

```
garments   ─┬─ dolaptaki kıyafetler + öznitelikler + dosya yolları
            │
mannequins ─┼─ base manken (Faz 5'te kullanıcıya özel manken buraya)
            │
layers     ─┤  (kıyafet × manken) → şeffaf PNG + z_index + status
            │   status: pending | ready | failed
outfits    ─┤  kaydedilmiş kombinler (manual | ai)
outfit_items┘  kombin ↔ kıyafet
```

`layers.status` alanı Faz 1'in kuyruğu için: 100 kıyafetlik yüklemede bazı
katmanlar başarısız olacak, kullanıcıya "bu kıyafet render edilemedi" demek
gerekiyor.

---

## Yol haritası

| Faz | İçerik | Durum |
|---|---|---|
| **0** | Dolap altyapısı: yükleme, kırpma, öznitelik çıkarımı, DB, CLI | ✅ Bitti |
| **1** | Katman üretim hattı: base manken + VTON + fark tabanlı katman çıkarımı | ✅ Bitti |
| **2** | Manuel giydirme arayüzü (FastAPI + düz HTML/JS, CSS `z-index`) | ⬜ Sırada |
| **3** | AI kombin önerisi: kural filtresi → renk uyumu → LLM seçimi | ⬜ |
| **4** | "Gerçekçi göster": tam VTON zinciri + cache | ⬜ |
| **5** | Kişiselleştirilmiş manken (boy/kilo/vücut tipi) | ⬜ |

### Faz 1'in bilinen riskleri

- **Zincirleme bozulması.** VTON modelleri tek parça için eğitilmiş. Üst + alt +
  dış giyim zincirlendiğinde her geçişte önceki adımın detayı eriyor. Faz 4'te
  ölçülecek: *x ekseni = giydirilen parça sayısı, y ekseni = LPIPS.*
- **Ayakkabı desteklenmiyor.** VITON-HD / DressCode veri setlerinde ayakkabı
  sınıfı yok. Ayrı yol gerekecek (sabit ayak bölgesine kompozisyon).
- **Gömlek içeride mi dışarıda mı** — katman sisteminde çözülemez. Kabul edilen
  sınır.

---

## Proje yapısı

```
config.py              yollar, kategori/katman tablosu, VLM ayarları
db.py                  SQLite şema + CRUD (stdlib sqlite3, ORM yok)
cli.py                 komut dağıtıcı
wardrobe/
  imageutil.py         EXIF düzeltme, küçültme, base64, baskın renk
  cutout.py            arka plan temizleme (rembg | flood yedeği)
  vision.py            Claude vision + JSON şema (+ mock yedeği)
  ingest.py            yükleme hattı — tek giriş noktası: add_garment()
tests/                 66 test, API anahtarı gerektirmez
data/                  raw/ cutout/ layers/ + wardrobe.db  (git'e girmez)
```

## Testler

```bash
pytest
```

66 test, **hiçbiri gerçek API çağırmıyor** — `conftest.py` her testte
`ANTHROPIC_API_KEY`'i siliyor, varsayılan veritabanını ve veri dizinlerini
`tmp_path`'e yönlendiriyor. Geliştiricinin `.env`'i yüklü olsa bile testler
fatura üretmiyor ve gerçek dolabı kirletmiyor.
