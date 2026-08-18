"""Katman üretimi ve birleştirme — Faz 1'in kalbi.

Fikir: manken sabit olduğuna göre, giydirme sonrasında **değişen pikseller
kıyafetin ta kendisidir**. Yani katmanı ayıklamak için ayrı bir segmentasyon
modeline gerek yok; iki görüntünün farkını almak yetiyor.

    base (çıplak manken)  ─┐
                           ├─►  |fark| > eşik  ─►  temizle  ─►  RGBA katman
    dressed (giydirilmiş) ─┘

Sonra giydirme anında katmanlar z-sırasına göre üst üste bindiriliyor: anında,
bedava, sınırsız kombin.

Fark almanın iki tuzağı var, ikisi de burada ele alınıyor:
  1. Difüzyon çıktısı mankenin geri kalanını da milimetrik oynatıyor → eşik
     ve gürültü temizliği (açma) gerekiyor.
  2. Kıyafetin rengi mankenin tenine yakın olduğu yerlerde fark zayıf kalıyor,
     katmanda delik açılıyor → delik doldurma (kapama) gerekiyor.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from config import LAYER_DIR, z_index
from db import connect, get_garment, list_garments
from wardrobe import mannequin, vton
from wardrobe.imageutil import load_any, rgb_distance

# Fark eşiği (0-255 RGB uzaklığı).
#
# 30'da ölçtük: gölgedeki koyu bordo polo ile altındaki koyu lacivert tişört
# arasındaki fark eşiği aşamıyor ve katmanda DELİK açılıyor — altındaki eski
# kıyafet sızıyor. Eşiği düşürmenin bedeli gürültü, ama gürültüyü zaten
# largest_component + delik doldurma temizliyor. O yüzden düşük eşik + güçlü
# temizlik, yüksek eşikten daha iyi bir takas.
DIFF_THRESHOLD = 18

# Katmanın tuvalde kaplaması beklenen makul aralık. Dışına çıkarsa katman
# şüpheli sayılıp işaretleniyor.
MIN_LAYER_COVERAGE = 0.008
MAX_LAYER_COVERAGE = 0.60

# Kıyafetin rengi mankenin kıyafetine bu kadar yakınsa "sinyal zayıflıyor"
# uyarısı veriliyor — ama üretim ENGELLENMİYOR (bkz. base_conflict).
#
# Sayı ölçülen tek düşük noktanın (uzaklık 1.0 → kaplama tipiğin ~%65'i)
# etrafına konmuş ihtiyatlı bir sınır. 2 ile 40 arası ÖLÇÜLMEDİ; buradaki
# iddia "çalışmaz" değil, "zayıflar".
LOW_CONTRAST_DISTANCE = 15

# KATEGORİYE GÖRE aralık — tek eşik aksesuarlarda ters tepiyor.
#
# Bir saat 864x1296'lık tuvalin ~%0.2'sini kaplıyor. Tek eşikle (%0.8) katman
# doğru üretilmiş olsa bile "neredeyse boş — giydirilememiş olabilir" uyarısı
# alınıyordu: sayı doğru, yorumu yanlış. Kıyafet için %0.8 anlamlı bir taban,
# aksesuar için değil.
#
# Üst sınır da kategoriye bağlı: bir saat tuvalin %15'ini kaplıyorsa o katman
# saat değil, başka bir şey.
COVERAGE_RANGE: dict[str, tuple[float, float]] = {
    "aksesuar": (0.0004, 0.15),
    "ayakkabi": (0.001, 0.20),
}


def coverage_range(category: str | None) -> tuple[float, float]:
    return COVERAGE_RANGE.get(
        category or "", (MIN_LAYER_COVERAGE, MAX_LAYER_COVERAGE))

# Kontur pürüzsüzleştirme: bulanıklaştır→yeniden eşikle. Büyütmek kenardaki
# tırtığı daha çok siler ama gerçek detayı da (kol ağzı, etek ucu) yuvarlar.
CONTOUR_SMOOTH = 2.0

# Siluetin 1 px genişletilmesi (§6.1 #10). Ayarlanabilir yapıldı çünkü
# ölçülebilir bir TAKAS taşıyor: genişletmek kenardan base sızmasını önlüyor
# ama maskeyi gerçek kenarın dışına taşırıyor — yakada bu, boynun üstüne
# taşan ince bir halka olarak görünüyor.
EXTRA_DILATE = True
# Kenar yumuşatma (anti-alias) yarıçapı.
EDGE_SOFTEN = 1.0

# Kenar rengi tazelemesinin derinliği. Maske olarak alfanın tamamı veriliyor ve
# yumuşatma rampası gerçek siluetin ~2 px dışına taşıyor; bu yüzden derinlik o
# kadar artırıldı, yoksa kıyafetin ASIL kenar sırası "iç bölge" sayılıp
# tazelenmeden kalıyor (bir test tam bunu yakaladı).
EDGE_DECONTAM_DEPTH = 5


def has_scipy() -> bool:
    """Bağlı bileşen etiketleme kullanılabilir mi?

    scipy zorunlu bağımlılık değil; yoksa daha kaba olan bant yedeğine
    düşüyoruz. Ayrı bir fonksiyon çünkü "scipy yok" ile "zaten tek bileşen
    vardı" farklı durumlar ve farklı davranış gerektiriyor.
    """
    try:
        import scipy.ndimage  # noqa: F401
        return True
    except ImportError:
        return False


def largest_component(mask: np.ndarray) -> np.ndarray:
    """En büyük bağlı bileşeni döner; diğer her şeyi atar.

    Neden gerekli: VTON modeli tüm görüntüyü yeniden üretiyor, sadece kıyafet
    bölgesini değil. Tayt/pantolon dokusu milimetrik değiştiği için bacaklarda
    da fark eşiğini aşan piksel öbekleri oluşuyor. Ölçtük: bir tişört
    katmanının %5'i bacak bölgesindeydi, alfa 255'e kadar.

    Bu Faz 2'de sessizce patlıyor: tişört (z=30) şortun (z=20) üstüne
    çizildiği için o lekeler şortu deliyor. Kullanıcı "şortumda gri lekeler
    var" diyor, sebebini bulmak saatler alıyor.

    Kıyafet tek parça bir nesne olduğuna göre çözüm basit: en büyük bağlı
    bileşeni tut, gerisini at. scipy yoksa bileşen etiketleme yapılamıyor,
    o durumda mask olduğu gibi dönüyor (bkz. _band_mask yedeği).
    """
    if not has_scipy():
        return mask

    from scipy import ndimage

    labeled, count = ndimage.label(mask)
    if count <= 1:
        return mask
    sizes = ndimage.sum(mask, labeled, range(1, count + 1))
    return labeled == (int(np.argmax(sizes)) + 1)


def garment_palette(cutout_path: str | Path, colors: int = 8) -> np.ndarray:
    """Kıyafetin kendi renk paletini kırpılmış fotoğrafından çıkarır.

    Şeffaf pikseller atlanır — palet sadece kıyafetin gerçek renklerini içerir.
    Desenli kıyafetlerde de çalışıyor, çünkü tek renk varsaymıyoruz: paleti
    görselden öğreniyoruz.
    """
    img = Image.open(cutout_path).convert("RGBA")
    arr = np.asarray(img)
    pixels = arr[arr[..., 3] > 200][:, :3]
    if len(pixels) == 0:
        return np.empty((0, 3), dtype=np.int16)

    # Kaba kuantalama + en kalabalık kovaların ortalaması ≈ ucuz k-means.
    # int32'ye yükseltmek ZORUNLU: pixels uint8 ve kova*1024 tavanı aşıyor.
    # (Bu projede üçüncü taşma; NumPy'de çarpmadan önce tip yükselt.)
    buckets = (pixels // 24).astype(np.int32)
    keys = buckets[:, 0] * 1024 + buckets[:, 1] * 32 + buckets[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    top = values[np.argsort(counts)[::-1][:colors]]
    return np.array(
        [pixels[keys == v].mean(axis=0) for v in top], dtype=np.int16
    )


def color_filter(
    mask: np.ndarray,
    rgb: np.ndarray,
    palette: np.ndarray,
    tolerance: int = 100,
    min_keep: float = 0.30,
) -> np.ndarray:
    """Kıyafetin renk dağılımına uymayan pikselleri katmandan çıkarır.

    Neden gerekli: VTON modeli bir kıyafeti üretirken komşu bölgeleri de
    yeniden çiziyor. Ölçtük — bordo polo üretilirken altındaki şortun beli de
    yeniden çizildi, fark bunu "polo" sanıp katmana aldı ve bindirmede
    poloyla şort arasında beyaz bir bant çıktı.

    Fark algoritması "ne değişti"yi biliyor ama "bu kıyafet neye benziyor"u
    bilmiyor. Oysa biliyoruz: elimizde kıyafetin kırpılmış fotoğrafı var.

    Aydınlatma farkını yutmak için palet parlaklık ölçekleriyle genişletiliyor;
    ton ayrımı korunuyor ama gölge/parlama tolere ediliyor.

    min_keep güvenlik freni: filtre maskenin çoğunu yiyorsa varsayımımız
    yanlıştır (ör. renk profili çok kaydı), o zaman uygulanmaz.
    """
    if palette.size == 0 or not mask.any():
        return mask

    scales = np.array([0.45, 0.65, 0.85, 1.0, 1.2, 1.45], dtype=np.float32)
    expanded = np.clip(
        (palette[None, :, :] * scales[:, None, None]).reshape(-1, 3), 0, 255
    ).astype(np.int16)

    # (piksel, palet) uzaklık matrisi -> her piksel için en yakın palet rengi
    candidate = rgb[mask]
    d = rgb_distance(candidate[:, None, :], expanded[None, :, :]).min(axis=1)

    keep_flat = d < tolerance
    if keep_flat.mean() < min_keep:
        return mask                       # güvenlik freni

    out = np.zeros_like(mask)
    out[mask] = keep_flat
    return out


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Kıyafet siluetinin içinde kalan delikleri kapatır.

    Delik neden oluşuyor: giydirilen kıyafetin rengi, altındaki eski kıyafete
    yakınsa fark eşiği aşılamıyor. Ölçtük: gölgede koyu bordo polo ile koyu
    lacivert tişört arasında fark 18-30 bandında kalıyor.

    Sonuç sinsi: katmanda delik açılıyor ve bindirmede ALTTAKİ eski kıyafet
    sızıyor. Kullanıcı "polomun omzunda lacivert leke var" diyor.

    Kıyafet dolu bir silüet olduğuna göre, silüetin içinde kalan her boşluk
    tanım gereği hatadır — doldur.
    """
    if not has_scipy():
        return mask
    from scipy import ndimage
    return ndimage.binary_fill_holes(mask)


def base_clothing_palette(
    base_rgb: np.ndarray, colors: int = 5, person: np.ndarray | None = None
) -> np.ndarray:
    """Base mankenin ÜZERİNDEKİ kıyafetin renk paleti.

    Gövde ve kalça bandından örnekleniyor — orası base'in kıyafetinin olduğu
    yer. Duvar ve zemin bandın dışında kalıyor.

    ⚠ "Bandın dışında kalıyor" varsayımı TUVALE GÖRE sabit kutulara dayanıyor
    ve figür kadrajı doldurmadığında bozuluyor. Ölçüldü:

        base (figür tuvalin %32.2'si)     : kutunun %100.0'ı kişinin içinde
        manken 2 (figür %18.3)            : %92.8 — kalan **4.180 px duvar/zemin**
                                            (renk [109,99,86])

    `person` verilirse örnekleme kişi maskesiyle KESİŞİYOR ve duvar örnekleri
    eleniyor. Verilmezse eski davranış (kutu) — rembg opsiyonel olduğu için
    zorunlu kılınamıyor.

    §32'deki fikrin aynısı, bir katman daha aşağıda: renge değil KONUMA bakmak.
    """
    h, w = base_rgb.shape[:2]
    if person is not None and person.shape == (h, w):
        kutu = np.zeros((h, w), dtype=bool)
        kutu[int(0.36 * h):int(0.52 * h), int(0.42 * w):int(0.62 * w)] = True
        kutu[int(0.64 * h):int(0.74 * h), int(0.42 * w):int(0.62 * w)] = True
        secili = kutu & person
        # Güvenlik freni: maske kutuyu neredeyse tamamen yerse (yanlış maske,
        # kadrajda görünmeyen figür) kutuya geri dön. Boş palet, ona dayanan
        # her şeyi — kör nokta kontrolü, sızıntı filtresi — sessizce devre dışı
        # bırakır (§16'daki `_harden_alpha` dersinin aynısı).
        box = base_rgb[secili] if secili.sum() > 0.2 * kutu.sum() else None
        if box is not None:
            return _palet(box.reshape(-1, 3), colors)

    box = np.concatenate([
        base_rgb[int(0.36 * h):int(0.52 * h), int(0.42 * w):int(0.62 * w)].reshape(-1, 3),
        base_rgb[int(0.64 * h):int(0.74 * h), int(0.42 * w):int(0.62 * w)].reshape(-1, 3),
    ])
    return _palet(box, colors)


def _palet(box: np.ndarray, colors: int) -> np.ndarray:
    """Kaba kuantalama + en kalabalık kovaların ortalaması ≈ ucuz k-means."""
    buckets = (box // 20).astype(np.int32)
    keys = buckets[:, 0] * 4096 + buckets[:, 1] * 64 + buckets[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    top = values[np.argsort(counts)[::-1][:colors]]
    return np.array([box[keys == v].mean(axis=0) for v in top], dtype=np.int16)


# Base'in kıyafet rengine bu kadar yakın piksel, kıyafet değil sızıntı sayılır.
#
# 35'ti, 55'e çıkarıldı: sarı tişörtün etek ucundaki mavi bandın base'e uzaklığı
# tam 35 ölçüldü ve kılpayı eşiğin dışında kalıp temizlenmiyordu. Yükseltmek
# güvenli, çünkü repaint_base_leak toleransı kıyafet-base mesafesinin yarısıyla
# sınırlıyor — yani base'e yakın kıyafetlerde kendiliğinden daralıyor.
BASE_LEAK_TOLERANCE = 55

# Filtre yalnızca kıyafetin kendi rengi base'in renginden bu kadar uzaksa
# uygulanır. Aksi halde gerçek kıyafet pikselleri silinir.
BASE_LEAK_SAFE_MARGIN = 2.0


def repaint_base_leak(
    rgb: np.ndarray,
    keep: np.ndarray,
    base_palette: np.ndarray,
    garment_palette_: np.ndarray | None = None,
    tolerance: int = BASE_LEAK_TOLERANCE,
) -> np.ndarray:
    """Base'in kıyafetinin sızdığı pikselleri SİLMEZ — yeniden boyar.

    Önce silen bir sürüm yazıldı (`drop_base_clothing`) ve beldeki lekeyi
    gerçekten kaldırdı, ama yerine daha kötüsünü koydu: base'in mavi tişörtü
    yeni kıyafetin arkasında kaldığı için siluet kenarındaki pikseller de
    maviye çalıyor, onlar da silinince kenar boyunca **tırtıklı delikler**
    açıldı ve altından zemin göründü. Bir kusuru başka bir kusurla değiştirmek.

    Oysa o pikseller siluetin parçası; yanlış olan şekilleri değil RENKLERİ.
    Bu yüzden alfaya dokunmadan rengi en yakın temiz kıyafet pikselinden
    kopyalıyoruz — decontaminate_edges ile aynı ilke.

    YAN FAYDASI, güvenlik kuralını gereksiz kılıyor: silen sürümde kıyafet
    base'in rengine yakınsa (lacivert tişört, mesafe 41) filtre gerçek kıyafeti
    yer diye atlanmak zorundaydı. Boyayan sürümde yanlış pozitif zararsız —
    laciverti laciverte boyar. Yani filtre artık HER kıyafette çalışabiliyor,
    en çok ihtiyaç duyan #5 dahil.
    """
    if base_palette.size == 0 or not keep.any() or not has_scipy():
        return rgb

    from scipy import ndimage

    # UYARLANIR TOLERANS: kıyafetin kendi rengi base'inkine ne kadar yakınsa
    # tolerans o kadar dar olmalı. Aksi halde kıyafetin KENDİ renk bölgesine
    # girip gerçek pikselleri "sızıntı" sayarız.
    #
    # Ölçüldü: sabit 55 toleransla lacivert tişörtün (base'e uzaklığı 41)
    # %49.7'si sızıntı işaretleniyordu — yarısını komşularından yeniden
    # boyamak kıvrımları ve baskıyı silerdi. Yarı mesafe kuralıyla o kıyafette
    # tolerans ~20'ye iniyor, uzak olanlarda (sarı tişört, uzaklık 165) tam
    # değerde kalıyor.
    if garment_palette_ is not None and garment_palette_.size:
        guven = float(
            rgb_distance(base_palette[:, None, :], garment_palette_[None, :, :]).min()
        )
        tolerance = int(min(tolerance, guven / 2))

    d_base = rgb_distance(rgb[:, :, None, :], base_palette[None, None, :, :]).min(axis=-1)
    kirli = keep & (d_base < tolerance)
    temiz = keep & ~kirli

    # Kaynak yoksa (katmanın neredeyse tamamı base rengine yakın) dokunma —
    # o durumda kıyafetin kendisi zaten base rengindedir.
    if not kirli.any() or temiz.sum() < keep.sum() * 0.25:
        return rgb

    _, idx = ndimage.distance_transform_edt(~temiz, return_indices=True)
    out = rgb.copy()
    out[kirli] = rgb[idx[0][kirli], idx[1][kirli]]
    return out


def base_conflict(cutout_path: str | Path, db_path=None) -> dict:
    """Kıyafet, mankenin GERÇEK kıyafetiyle aynı renk mi? — ZEMİN seçimi için.

    ⚠ İKİ AYRI SORU, İKİ AYRI FONKSİYON. Bu ikisi bir zamanlar tek fonksiyondu
    ve çıkarım base'i eklenince (§44) bir cevabı yanlışa döndü:

      · `base_conflict`       → GERÇEK fotoğrafa bakar → **zemin seçimi**
      · `extraction_conflict` → ÇIKARIM base'ine bakar → **yükleme uyarısı**

    Aynı kıyafette ikisi zıt cevap verebiliyor. Ölçüldü (manken 2, #14
    lacivert tişört): gerçek fotoğrafa uzaklık **1.0**, yeşil çıkarım base'ine
    **107.0**. İkisi de kendi sorusu için doğru.

    BURADAKİ SORU: bindirmede katmanın deliğinden ne görünecek? Zemin gerçek
    fotoğraf (ya da onun nötrlenmiş hâli) olduğu için karşılaştırma gerçek
    fotoğrafla yapılmalı. Kıyafet mankenin kıyafetiyle aynı renkse delikten
    çıkan şey zaten "doğru" renkte — o durumda nötrleme kıyafeti YANLIŞ renkte
    gösteriyor (ölçüldü: gerçek renge uzaklık nötr zeminde 17.3, gerçek
    fotoğrafta 7.7).

    ⚠ EŞİKLER 2026-08 TURUNDA YENİDEN KALİBRE EDİLDİ — eskileri fal/v1.6 ile
    ölçülmüştü ve tryon-max'te ÇÜRÜDÜ.

    Eski eşikler (v1.6, siyah base): uzaklık 9 → kaplama %0.6, yani katman
    gerçekten boş çıkıyordu ve "engel" demek doğruydu. tryon-max görüntünün
    tamamını yeniden ürettiği için aynı renkte bile kullanılabilir bir fark
    bırakıyor. 15 (kıyafet × manken) ölçümü, kaplama KİŞİ ALANINA normalize
    edilerek (kategoriler ve mankenler arası karşılaştırılabilsin diye):

        uzaklık   1.0 → 0.312     uzaklık 101.8 → 0.539
        uzaklık  40.7 → 0.458     uzaklık 116.4 → 0.704
        uzaklık  45.8 → 0.542     uzaklık 126.6 → 0.503
        uzaklık  69.3 → 0.492     uzaklık 164.6 → 0.523
        uzaklık  93.1 → 0.521     uzaklık 174.7 → 0.452

    İki sonuç:

    1. **40'ın üstünde uzaklığın ölçülebilir etkisi YOK** (0.45-0.70 arası,
       eğilim yok). Eski "riskli 25-45" bandının dayanağı kalmadı.
    2. **En uç noktada bile çökme yok:** uzaklık 1.0'da kaplama tipik değerin
       ~%65'i — zayıf ama kullanılabilir, görselle de doğrulandı.

    Bu yüzden `ok` artık HER ZAMAN True: eski hâli, ölçümle çalıştığı
    kanıtlanmış bir vakayı (uzaklık 1.0) "boş çıkar" diye engelliyordu.
    Seviye bilgilendirme olarak duruyor.

    **2 ile 40 arası ÖLÇÜLMEDİ.** `LOW_CONTRAST_DISTANCE = 15` bir tahmin
    değil, ölçülen tek düşük noktanın (1.0) etrafına konmuş ihtiyatlı bir
    uyarı sınırı — "burada sinyal zayıflıyor" demek için, "burası çalışmaz"
    demek için değil.
    """
    from wardrobe import mannequin

    base_row = mannequin.get_base(db_path=db_path)
    if not base_row or not Path(base_row["image_path"]).is_file():
        return {"ok": True, "distance": None, "reason": "base manken yok"}
    return _renk_catismasi(cutout_path, Path(base_row["image_path"]))


def extraction_conflict(cutout_path: str | Path, db_path=None) -> dict:
    """Kıyafet, ÇIKARIM base'inin kıyafetiyle aynı renk mi? — UYARI için.

    Yükleme akışındaki "bu katman bozuk çıkabilir" uyarısını besleyen soru bu.
    VTON ve fark hesabı `mannequin.extraction_image()`e karşı çalışıyor, yani
    karşılaştırma da onunla yapılmalı.

    §44'ten sonra çıkarım base'inin kıyafeti chroma yeşile boyanıyor; dolaptaki
    hiçbir kıyafet ona yakın olmadığı için bu uyarı pratikte hiç tetiklenmiyor
    — kör nokta kapandı. Fonksiyon yine de duruyor: çıkarım base'i üretilmemiş
    bir mankende (eski kurulum, rembg yok) gerçek fotoğrafa düşüyor ve uyarı
    eskisi gibi anlamlı oluyor.
    """
    from wardrobe import mannequin

    yol = mannequin.extraction_image(db_path=db_path)
    if not Path(yol).is_file():
        return {"ok": True, "distance": None, "reason": "base manken yok"}
    return _renk_catismasi(cutout_path, Path(yol))


def _renk_catismasi(cutout_path: str | Path, base_image: Path) -> dict:
    """Kıyafetin paletiyle verilen base görüntüsünün kıyafet paleti arasındaki
    en küçük uzaklık + seviye. İki genel sorunun ortak hesabı.
    """
    from wardrobe.imageutil import load_any

    # ⚠ Buraya kişi maskesi EKLENMEDİ ve bu bilinçli — ölçüldü, etkisi YOK.
    #
    # Sabit örnekleme kutusu manken 2'de örneklerin %7.2'sini duvardan alıyor
    # (4.180 px). Kişi maskesiyle kesiştirmek denendi: palet İKİ MANKENDE DE
    # birebir aynı kaldı (kayma 0.0) ve buradaki uzaklıkların hiçbiri
    # değişmedi. Sebep, `_palet`in en kalabalık kovaları seçmesi — 54.121
    # pikselli kıyafetin yanında %7'lik azınlık ilk 5'e giremiyor.
    #
    # Yani kirlilik gerçek ama propagasyonu yok. Bu fonksiyona rembg
    # bağımlılığı eklemek (yükleme akışında 1-3 sn) karşılıksız maliyet olurdu:
    # §20.1'de `segmentation_free` tam bu gerekçeyle geri alınmıştı — etkisi
    # ölçülmemiş/olmayan bir sapmayı taşımak, taşımamaktan kötü.
    #
    # `base_clothing_palette` yine de `person` parametresini kabul ediyor;
    # maskeyi ZATEN hesaplayan `build_display_base` onu geçiyor (orada §32'de
    # ölçülmüş gerçek bir etkisi var).
    base_pal = base_clothing_palette(
        np.asarray(load_any(base_image).convert("RGB"))
    )
    garment_pal = garment_palette(cutout_path, colors=4)
    if base_pal.size == 0 or garment_pal.size == 0:
        return {"ok": True, "distance": None, "reason": "palet çıkarılamadı"}

    d = float(rgb_distance(base_pal[:, None, :], garment_pal[None, :, :]).min())

    if d < LOW_CONTRAST_DISTANCE:
        seviye = "zayıf"
        # ⚠ METİN BİR KEZ DÜZELTİLDİ. Önce "tipik değerin ~%65'i kadar çıkıyor
        # — zayıf ama kullanılabilir" diyordu. O cümle KAPLAMA metriğine
        # dayanıyordu ve yanlış soruyu cevaplıyordu: kaplama makul çıkıyor ama
        # katmanın İÇERİĞİ base oluyor. Ölçüldü — mankenin kıyafetiyle aynı
        # renkteki tişörtte (uzaklık 1.0) katmanın **%44.8'i** base'in kendi
        # kıyafetiydi (uzak kıyafetlerde bu oran %0.0-4.5).
        not_ = ("Bu kıyafetin rengi mankenin kıyafetiyle neredeyse aynı. "
                "Katman üretilir ama içeriğinin yarısına kadarı mankenin kendi "
                "kıyafeti olabilir; kombinde leke ve yama olarak görünür. "
                "Temiz sonuç için 'Gerçekçi Göster' ya da mankeni farklı renk "
                "bir üstle yeniden çekmek gerekiyor.")
    else:
        seviye, not_ = "uygun", ""

    # `ok` HER ZAMAN True. Eski hâli uzaklık < 25'te ücretli çağrıyı
    # engelliyordu; o kural fal/v1.6 ile ölçülmüştü ve tryon-max'te çürüdü
    # (uzaklık 1.0'daki kıyafet sorunsuz üretildi). Yanlış bir tahminle
    # kullanıcının çalışacak bir işlemi yapmasını engellemek, ücretli çağrıyı
    # boşa harcamaktan daha kötü.
    return {"ok": True, "distance": round(d, 1), "level": seviye, "note": not_}



# Sentetik çıkarım base'inin (chroma yeşil) katmana sızan pikselleri için
# tolerans. ÖLÇÜMLE seçildi — sızan yeşilin yeşil paletine uzaklık dağılımı ve
# kıyafetlerin aynı palete uzaklığı:
#
#     sızan yeşil : medyan 60.3 · %95'i 70.3'ün altında · azami 112
#     kıyafetler  : en yakın 107.0 (#14) · 117.4 (#16) · 129.4 (#10)
#
# 78 aralığın ortasında: sızıntının ~%97'sini yakalıyor ve en yakın kıyafete
# 29 birim pay bırakıyor. İlk denemede 90 konmuş ve güvenlik kuralı 135'e
# çıktığı için filtre HİÇ TETİKLENMEMİŞTİ — ölçmeden konan sayı sessizce
# etkisiz kalmıştı.
EXTRACT_COLOR_TOLERANCE = 78

# Kıyafetin çıkarım rengine uzaklığı bunun altındaysa filtre atlanıyor.
# 1.25 × 78 = 97.5; en yakın kıyafet 107 ile bunun üstünde, yani gerçek
# dolapta filtre çalışıyor ama neon yeşil bir kıyafet gelirse kendini koruyor.
EXTRACT_COLOR_SAFE = 1.25


def drop_extract_color(keep, rgb, extract_palette, garment_palette_):
    """Sentetik çıkarım base'inin rengini katmandan siler.

    NEDEN AYRI BİR FİLTRE: §44'te çıkarım base'inin kıyafeti chroma yeşile
    boyanıyor ve kullanıcı o görüntüyü hiç görmüyor — ama modelin bıraktığı
    birkaç yüz yeşil piksel KATMANA girip bindirmede görünüyor. Ölçüldü:
    #10'da 51 px (çenede), #16'da 205 px.

    Bu filtre öncekilerden farklı olarak RİSKSİZ, çünkü aradığı renk GERÇEK
    DEĞİL — biz koyduk. Kıyafetin o renge yakın olma ihtimali yok denecek
    kadar düşük, ve o durum için güvenlik kuralı zaten var:

        Filtre yalnızca kıyafetin kendi paleti çıkarım renginden UZAKSA
        uygulanır. Yakınsa (gerçekten neon yeşil bir kıyafet) atlanıyor —
        ama o zaman zaten sızıntı kıyafetten ayırt edilemez.

    §7.6'daki `drop_base_clothing`'in simetrisinin aynısı, ama burada
    "uzaklık" garanti altında: rengi biz seçtik.
    """
    if not keep.any() or extract_palette is None or len(extract_palette) == 0:
        return keep

    ep = np.asarray(extract_palette, dtype=np.float32)
    if garment_palette_ is not None and len(garment_palette_):
        gp = np.asarray(garment_palette_, dtype=np.float32)
        en_yakin = float(rgb_distance(ep[:, None, :], gp[None, :, :]).min())
        if en_yakin < EXTRACT_COLOR_TOLERANCE * EXTRACT_COLOR_SAFE:
            return keep          # kıyafet o renge yakın — dokunma

    px = rgb[keep].astype(np.float32)
    yakin = rgb_distance(px[:, None, :], ep[None, :, :]).min(axis=1) <         EXTRACT_COLOR_TOLERANCE
    out = keep.copy()
    out[keep] = ~yakin
    return out if out.any() else keep


# Yeşilin gerçek fotoğrafla değiştirildiği yerde kenarın yumuşatılma yarıçapı.
# Sert bir ikili maske, kıyafetin kenarında testere dişi bırakıyor: yeşil ile
# kıyafet arasındaki ara piksel ikisinin karışımı ve hiçbir tarafa tam ait
# değil. Küçük bir geçiş bandı bunu görünmez yapıyor.
EXTRACT_RESTORE_FEATHER = 1.5

# Maskenin değiştirmeden ÖNCE genişletileceği yarıçap.
#
# Eşiğin tam kendisi yetmiyor: yeşil bölgenin dış sınırındaki anti-alias
# pikselleri yeşille komşusunun karışımı olduğu için palete uzaklıkları eşiğin
# ÜSTÜNDE kalıyor ve yerinde duruyorlar. Ekranda bu, kıyafetin çevresini saran
# ince neon bir kontur olarak görünüyordu.
#
# Ölçüldü (palete BAKMAYAN ölçüt — yeşil kanalın diğer ikisini 20'den fazla
# geçmesi; gerçek fotoğrafta bu sayı 0):
#
#   genişletme   #14      #16      #10     kaplama (#14)
#        0      1.267    1.390    1.369       42.760
#        2         94       27       82       46.541
#        3          0       20        2       48.453
#
# 3 seçildi: sayıda tabana iniyor, gözle kontur tamamen kayboluyor ve kıyafetin
# kenarı yenmiyor (bel hizasında yakın planla doğrulandı). Bedeli %13 daha
# fazla piksel — hepsi zaten gerçek fotoğraftan geldiği için görsel maliyeti yok.
EXTRACT_RESTORE_DILATE = 3


def restore_extract_color(
    dressed: Image.Image,
    real_base: Image.Image,
    extract_base: Image.Image,
    garment_palette_: np.ndarray | None = None,
) -> Image.Image:
    """Ham VTON çıktısındaki sentetik çıkarım rengini GERÇEK fotoğrafla değiştirir.

    NEDEN GEREKLİ: §38'de tek kıyafet seçiliyken ham VTON çıktısı gösteriliyor
    — katman bindirmesinin çıkarım kusurlarını taşımadığı için doğru karar. Ama
    §44'te çıkarım base'inin kıyafeti chroma yeşile boyandı ve ham çıktı ARTIK
    O BASE'E karşı üretiliyor. Sonuç: kıyafetin örtmediği her yerde kullanıcı
    yeşil görüyor (üst giydirilince şort, alt giydirilince tişört).

    `drop_extract_color`'ın simetriği: o, yeşili KATMANDAN siliyor; bu, yeşili
    ham çıktıda gerçek fotoğrafla DOLDURUYOR. İkisinin de dayandığı güvence
    aynı — aranan renk gerçek değil, biz koyduk.

    Değiştirme piksel piksel yapılabiliyor çünkü iki görüntünün geometrisi
    birebir aynı: çıkarım base'i gerçek fotoğrafın yalnızca yeniden
    renklendirilmiş hâli, poz ve kadraj değişmedi (§44.1).

    Güvenlik kuralı `drop_extract_color`'la aynı: kıyafetin kendi paleti
    çıkarım rengine yakınsa (gerçekten neon yeşil bir kıyafet) hiç dokunulmuyor,
    yoksa kıyafetin kendisi silinirdi.
    """
    if dressed.size != real_base.size:
        dressed = dressed.resize(real_base.size, Image.LANCZOS)
    if extract_base.size != real_base.size:
        extract_base = extract_base.resize(real_base.size, Image.LANCZOS)

    d_rgb = np.asarray(dressed.convert("RGB"))
    r_rgb = np.asarray(real_base.convert("RGB"))
    pal = base_clothing_palette(np.asarray(extract_base.convert("RGB")))
    if pal is None or not len(pal):
        return dressed

    pal = np.asarray(pal, dtype=np.float32)
    if garment_palette_ is not None and len(garment_palette_):
        gp = np.asarray(garment_palette_, dtype=np.float32)
        en_yakin = float(rgb_distance(pal[:, None, :], gp[None, :, :]).min())
        if en_yakin < EXTRACT_COLOR_TOLERANCE * EXTRACT_COLOR_SAFE:
            return dressed          # kıyafet o renge yakın — dokunma

    h, w = d_rgb.shape[:2]
    mesafe = rgb_distance(
        d_rgb.reshape(-1, 1, 3).astype(np.float32), pal[None, :, :]
    ).min(axis=1).reshape(h, w)
    yesil = mesafe < EXTRACT_COLOR_TOLERANCE
    if not yesil.any():
        return dressed

    alfa = Image.fromarray((yesil * 255).astype(np.uint8), mode="L")
    if EXTRACT_RESTORE_DILATE > 0:
        alfa = alfa.filter(ImageFilter.MaxFilter(2 * EXTRACT_RESTORE_DILATE + 1))
    if EXTRACT_RESTORE_FEATHER > 0:
        alfa = alfa.filter(ImageFilter.GaussianBlur(EXTRACT_RESTORE_FEATHER))
    a = (np.asarray(alfa, dtype=np.float32) / 255.0)[:, :, None]
    karisim = (d_rgb * (1.0 - a) + r_rgb * a).round().clip(0, 255)
    return Image.fromarray(karisim.astype(np.uint8), mode="RGB")


def display_raw_path(garment_id: int, mannequin_id: int) -> Path:
    """`restore_extract_color` uygulanmış ham çıktının önbellek yolu."""
    return LAYER_DIR / f"g{garment_id}_m{mannequin_id}_raw_display.png"


def dressed_for_display(
    garment_id: int, mannequin_id: int, db_path=None
) -> Path | None:
    """Tek kıyafet seçiliyken KULLANICIYA gösterilecek ham çıktının yolu.

    Çıkarım base'i yoksa ham çıktının kendisi dönüyor — yani yeşil base
    kullanmayan bir mankende bu özellik hiç devreye girmiyor ve davranış
    eskisiyle birebir aynı kalıyor.

    Sonuç diske önbellekleniyor: dönüşüm saniyenin altında ama her sahne
    değişiminde yeniden hesaplamanın anlamı yok. Önbellek, kaynaklarından
    (ham çıktı ve çıkarım base'i) eskiyse yeniden üretiliyor — §25.7'nin
    dersi: bayat önbellek, olmayan önbellekten kötüdür.
    """
    ham = raw_path(garment_id, mannequin_id)
    if not ham.is_file():
        return None

    cikarim = mannequin.extract_base_path(mannequin_id, db_path)
    gercek = mannequin.photo_path(mannequin_id, db_path)
    if not cikarim.is_file() or gercek is None:
        return ham

    onbellek = display_raw_path(garment_id, mannequin_id)
    kaynak_zamani = max(ham.stat().st_mtime, cikarim.stat().st_mtime)
    if onbellek.is_file() and onbellek.stat().st_mtime >= kaynak_zamani:
        return onbellek

    garment = get_garment(garment_id, db_path=db_path)
    pal = None
    if garment and garment["cutout_path"] and Path(garment["cutout_path"]).is_file():
        pal = garment_palette(garment["cutout_path"], colors=4)

    sonuc = restore_extract_color(
        load_any(ham), load_any(gercek), load_any(cikarim), pal
    )
    onbellek.parent.mkdir(parents=True, exist_ok=True)
    sonuc.save(onbellek)
    return onbellek


def drop_base_clothing(
    mask: np.ndarray,
    dressed_rgb: np.ndarray,
    base_palette: np.ndarray,
    garment_palette_: np.ndarray,
    tolerance: int = BASE_LEAK_TOLERANCE,
) -> np.ndarray:
    """Base'in KENDİ kıyafetinin katmana sızdığı pikselleri atar.

    VTON, giydirdiği kıyafetin komşusunu da yeniden çiziyor: base'in şort belini
    yeniden çizip fark bunu üst katmana ait sanıyor. Sonuç, bindirmede belde
    base'in renginde bir leke.

    Bu filtrenin, daha önce başarısız olan iki denemeden (§6.2 color_filter,
    drop_base_leak) farkı şu: **base'in kıyafet rengi artık dolaptaki her
    kıyafetten uzak seçiliyor.** Siyah base'de bu imkânsızdı — siyah, koyu
    kıyafetlerden ayırt edilemiyordu. Orta mavi base'de en yakın kıyafet 85
    birim uzakta, tolerans ise 35.

    GÜVENLİK KURALI ve içindeki güzel simetri: filtre yalnızca kıyafetin rengi
    base'inkinden yeterince uzaksa uygulanır. Yakınsa uygulanmaz — ama zaten o
    durumda sızıntı da görünmez, çünkü sızan renk kıyafetin rengine benziyordur.
    Yani filtre **tam olarak ihtiyaç duyulduğu durumlarda güvenlidir.**

    Ölçüldü (orta mavi base): #5 lacivert tişört base'e 41 birim uzakta →
    atlanıyor (uygulansa katmanın %28'ini yerdi). Diğer beşi 85-165 arasında →
    uygulanıyor, sildikleri %0.0-3.6.
    """
    if base_palette.size == 0 or garment_palette_.size == 0 or not mask.any():
        return mask

    # UYARLANIR TOLERANS: kıyafetin rengi base'inkine ne kadar yakınsa tolerans
    # o kadar dar. Yarı mesafeyi geçerse kıyafetin KENDİ renk bölgesine girip
    # gerçek pikselleri sızıntı sayarız.
    #
    # Önce "çok yakınsa hiç uygulama" diye ikili bir kural vardı; uyarlanır
    # sürüm daha iyi, çünkü yakın kıyafetlerde de en bariz sızıntıyı yakalıyor.
    # Ölçüldü: lacivert tişört base'e 41 uzakta → tolerans 20; sarı tişört 165
    # uzakta → tolerans tam değerde (55).
    guvenli = float(
        rgb_distance(base_palette[:, None, :], garment_palette_[None, :, :]).min()
    )
    tolerance = int(min(tolerance, guvenli / 2))
    if tolerance < 8:                    # ayırt edilemeyecek kadar yakın
        return mask

    d = rgb_distance(
        dressed_rgb[mask][:, None, :], base_palette[None, :, :]
    ).min(axis=1)

    out = np.zeros_like(mask)
    out[mask] = d >= tolerance
    return out


# Lab filtresinin ayarları — hepsi tarama ile seçildi, bkz. drop_base_leak_lab.
BASE_LEAK_LAB_MARGIN = 1.0
BASE_LEAK_LAB_MIN_KEEP = 0.55

# Hangi sızıntı filtresi kullanılacak: "both" | "lab" | "rgb" | "none".
#
# "rgb" = drop_base_clothing (tek yönlü, palet), "lab" = drop_base_leak_lab
# (iki yönlü, piksel bazlı). Sabit bırakıldı ki karşılaştırma kod değiştirmeden
# `--reextract` ile yapılabilsin — ham çıktılar saklandığı için bedava.
#
# "lab" ÖLÇÜMLE seçildi — ve bu seçim SAĞLAYICI DEĞİŞİNCE DEĞİŞTİ.
#
# Önce "both" seçilmişti ve o ölçüm doğruydu: v1.6'nın çıktılarında iki filtre
# tamamlayıcıydı. Ama v1.6 renkleri yanlış üretiyordu (§25.1: mor tişörtte
# 37.5 birim hata) ve RGB filtresi aslında o renk hatasının koltuk değneğiydi.
#
# tryon-max renkleri doğru ürettiğinde ölçüm tersine döndü. Tüm dolap,
# tryon-max ham çıktıları üzerinde (11 kıyafet, toplam):
#
#     konfig   kaplama   sızıntı px
#     none      176.3%      63.633
#     rgb       172.8%      58.960
#     lab       164.7%      16.551      ← seçildi
#     both      162.3%      16.532
#
# RGB filtresinin Lab'ın ÜSTÜNE kattığı fayda: **19 piksel** (%0.1). Bedeli:
# kaplamada 2.4 puan. Ve bedel eşit dağılmıyor — base'in rengine yakın
# kıyafetlerde yıkıcı: #14 lacivert tişörtte (base'e uzaklık 69) uyarlanır
# tolerans 34'e çıkıyor ve laciverdin GÖLGELİ gerçek pikselleri o mesafenin
# içinde kalıyor. Sonuç omuzda ve yan tarafta gri yamalar; görsel olarak
# doğrulandı.
#
# DERS: doğru filtre, modele bağlı. Sağlayıcı değişince filtre seçimi yeniden
# ölçülmeli — "daha önce ölçmüştük" yetmiyor.
LEAK_FILTER = "lab"


def drop_base_leak_lab(
    mask: np.ndarray,
    dressed_rgb: np.ndarray,
    base_rgb: np.ndarray,
    garment_palette_: np.ndarray,
    margin: float = BASE_LEAK_LAB_MARGIN,
    min_keep: float = BASE_LEAK_LAB_MIN_KEEP,
    lightness_weight: float | None = None,
) -> np.ndarray:
    """Base'in kıyafetinin sızdığı pikselleri atar — Lab uzayında, iki yönlü.

    Bu, base sızıntısını piksel filtresiyle çözmenin ÜÇÜNCÜ denemesi. İlk ikisi
    (color_filter §6.2, drop_base_leak) başarısız oldu ve o başarısızlıkların
    sebebi ölçüldüğü için bu sürüm ikisinden de farklı:

    · color_filter TEK YÖNLÜYDÜ ("piksel kıyafetin paletine uzak mı") ve
      gölgedeki gerçek kıyafeti de kesiyordu.
    · drop_base_leak iki yönlüydü ama RGB'deydi ve paleti parlaklık
      ölçekleriyle (×0.45'e kadar) genişletiyordu — koyu bir kıyafetin paleti
      neredeyse siyahı da kapsıyor, ayrım çöküyordu.
    · drop_base_clothing çalışıyor ama TEK YÖNLÜ ve RGB'de: toleransı
      kıyafet-base mesafesinin yarısıyla sınırlamak zorunda, o yüzden base'e
      yakın renklerde (mor, lacivert) neredeyse kapanıyor.

    KÖK SEBEP, ölçüldü: RGB uzaklığı parlaklıkla rengi tek sayıya karıştırıyor.

        mor tişört → base            RGB 61.8    (a*,b*) 22.1
        base mavisinin ×0.60 gölgesi RGB 74.2    (a*,b*) 10.3

    RGB'de base'in KENDİ GÖLGESİ mordan daha uzak. Yani sızıntıyı yakalayan
    hiçbir RGB toleransı morun kendisini yemeden çalışamaz — mantık değil, uzay
    yanlış. Lab'de L*'ın payı kısılınca gölge yakınlaşıyor, ton ayrımı kalıyor.

    Karşılaştırma AYNI KOORDİNATTAKİ base pikseliyle yapılıyor, palet ortalaması
    ile değil: sızıntı tanım gereği base'in orada ne olduğuyla ilgili. Bunun yan
    faydası, ayrı bir konum kuralına gerek kalmaması — base'in duvar veya ten
    olduğu yerde uzaklık zaten büyük çıkıyor ve piksele dokunulmuyor.

    Ölçülen tarama (yer gerçeği: katman pikseli base pikseliyle RGB < 25 ise
    "sızıntı", kıyafet paletine RGB < 45 ve sızıntı değilse "kıyafet"):

        L* ağırlığı   #11 mor yakalama / yanlış pozitif
        0.0           %92.3 / %7.8
        0.3           %93.2 / %2.0
        0.5           %93.7 / %0.6      ← seçildi
        0.8           %94.7 / %0.4

    0.5 ile 0.8 arasında yakalama farkı yok; 0.5 seçildi çünkü L* payı arttıkça
    filtre gölgeli sızıntıya karşı körleşmeye başlıyor ve asıl derdimiz o.

    min_keep güvenlik freni: filtre maskenin çoğunu yiyorsa varsayım yanlıştır
    (§6.2'nin dersi, üç denemede de aynı fren duruyor).
    """
    if garment_palette_.size == 0 or not mask.any():
        return mask

    from wardrobe.imageutil import LAB_LIGHTNESS_WEIGHT, lab_distance, to_lab

    wl = LAB_LIGHTNESS_WEIGHT if lightness_weight is None else lightness_weight

    aday = to_lab(dressed_rgb[mask])
    lab_base = to_lab(base_rgb[mask])
    lab_palette = to_lab(garment_palette_)

    d_base = lab_distance(aday, lab_base, wl)
    d_garment = lab_distance(
        aday[:, None, :], lab_palette[None, :, :], wl
    ).min(axis=1)

    keep_flat = ~(d_base * margin < d_garment)
    if keep_flat.mean() < min_keep:
        return mask                       # güvenlik freni

    out = np.zeros_like(mask)
    out[mask] = keep_flat
    return out


def drop_base_leak(
    mask: np.ndarray,
    dressed_rgb: np.ndarray,
    base_rgb: np.ndarray,
    palette: np.ndarray,
    margin: float = 1.0,
    min_keep: float = 0.55,
) -> np.ndarray:
    """Base'in kendi kıyafetinin katmana sızdığı pikselleri atar.

    ⚠ DENENDI VE İŞE YARAMADI — çağrılmıyor, ölçüm kaydı olarak duruyor.

    Neden başarısız: ayrım, "piksel kıyafetin paletine mi base'e mi yakın"
    testine dayanıyor. Ama palet parlaklık ölçekleriyle (×0.45'e kadar)
    genişletildiği için KOYU bir kıyafetin paleti neredeyse siyahı da kapsıyor.
    Bordo polonun paletine siyah sızıntı "yakın" çıkıyor ve test ayrım yapamıyor.
    Ölçüldü: leke kalktı denemedi, üstelik kenarlar tırtıklandı ve #6'nın zaten
    zayıf olan kaplaması %0.6'dan %0.4'e düştü.

    Bu, base sızıntısını piksel filtresiyle çözme girişimlerinin İKİNCİSİ ve
    ikincisi de aynı yere çıktı (birincisi: color_filter, §6.2). Sonuç net —
    **base sızıntısı bir piksel problemi değil, veri problemi.** Çözümü base'in
    kıyafetinde (§7), çıkarım algoritmasında değil.

    --- özgün fikir (kayıt için) ---

    VTON, giydirdiği kıyafetin komşusunu da yeniden çiziyor. Bordo polo
    üretilirken base'in siyah şortunun beli de yeniden çizildi; fark bunu
    "değişti, demek ki polo" sanıp katmana aldı. Sonuç: açık renk bir şortla
    kombinlendiğinde belde SİYAH bir leke.

    §6.2'deki renk filtresi bunu çözmeye çalışıp başarısız olmuştu, çünkü tek
    yönlüydü: sadece "kıyafetin paletine uzak mı" diye bakıyordu ve gölgedeki
    gerçek kıyafet piksellerini de siliyordu.

    Buradaki test ÇİFT yönlü ve bu yüzden daha güvenli:

        pikselin rengi kıyafetin paletine mi yakın, yoksa AYNI KOORDİNATTAKİ
        base pikseline mi?

    Gölgedeki gerçek kıyafet pikseli koyudur ama yine de kıyafetin paletine
    base'den daha yakındır — çünkü base orada bambaşka bir şeydir. Buna karşılık
    base'in yeniden çizilmiş beli, base'in kendisine yakın kalır. Ayrım budur.

    min_keep güvenlik freni: filtre maskenin çoğunu yiyorsa varsayım yanlıştır,
    uygulanmaz (§6.2'nin dersi).
    """
    if palette.size == 0 or not mask.any():
        return mask

    scales = np.array([0.45, 0.65, 0.85, 1.0, 1.2, 1.45], dtype=np.float32)
    expanded = np.clip(
        (palette[None, :, :] * scales[:, None, None]).reshape(-1, 3), 0, 255
    ).astype(np.int16)

    cand = dressed_rgb[mask]
    d_garment = rgb_distance(cand[:, None, :], expanded[None, :, :]).min(axis=1)
    d_base = rgb_distance(cand, base_rgb[mask])

    keep_flat = d_garment <= d_base * margin
    if keep_flat.mean() < min_keep:
        return mask                       # güvenlik freni

    out = np.zeros_like(mask)
    out[mask] = keep_flat
    return out


def decontaminate_edges(
    rgb: np.ndarray, keep: np.ndarray, depth: int = 3
) -> np.ndarray:
    """Kenar piksellerinin RENGİNİ içeriden tazeler; ŞEKLİNİ değiştirmez.

    Sorun: VTON çıktısında kıyafetin kenarı yumuşak (anti-aliased). En dış
    piksel sırası saf kıyafet değil, kıyafetin **arkasındaki şeyle karışımı**.
    Sarı tişörtün etek ucunda arkasında base'in siyah şortu vardı; sarı+siyah
    karışımı koyu çıkıyor ve bindirmede etek ucunda koyu bir çizgi görünüyor.

    Ölçtük — kıyafetin kendi paletine uzaklık (iç kısım / en dış 1 px):

        gri şort  11.1 / 26.1     sarı tişört 17.5 / 77.1     bordo polo 10.2 / 47.0

    Maskeyi aşındırmak yanlış çözüm: siluet küçülür ve altından base sızar —
    yani bir kenar hatasını başka bir kenar hatasıyla değişiriz. Oysa kenar
    piksellerinin **alfası doğru** (şekil doğru), sadece rengi kirli. O yüzden
    şekle dokunmadan rengi en yakın "derin iç" pikselden kopyalıyoruz.

    depth küçük tutuldu (3 px): daha büyüğü desenli kıyafetlerde baskıyı
    kenara doğru yayar.
    """
    if not has_scipy() or not keep.any():
        return rgb

    from scipy import ndimage

    dist = ndimage.distance_transform_edt(keep)
    inner = keep & (dist > depth)
    if not inner.any():          # kıyafet zaten ince — tazelenecek "iç" yok
        return rgb

    # Her piksel için en yakın derin-iç pikselin koordinatı.
    _, idx = ndimage.distance_transform_edt(~inner, return_indices=True)

    out = rgb.copy()
    edge = keep & (dist <= depth)
    out[edge] = rgb[idx[0][edge], idx[1][edge]]
    return out


def _band_mask(shape: tuple[int, int], category: str) -> np.ndarray:
    """Kategorinin anatomik bandı — scipy yoksa kullanılan yedek.

    Bileşen etiketleme kadar isabetli değil (uzun bir montu kesebilir) ama
    bacaklardaki serpintiyi engellemeye yeter. Bantlar cömert tutuldu: burada
    amaç segmentasyon değil, güvenlik ağı.

    ⚠ `vton.SLOT_BANDS` kullanıyor — o tablo MOCK sağlayıcının kıyafeti
    yapıştıracağı KUTU, gerçek kıyafetin kaplayabileceği alan değil. Bu yüzden
    çıkarım kapısı (`region_gate`) ayrı ve ÖLÇÜLMÜŞ bir tablo kullanıyor.
    """
    from wardrobe.vton import SLOT_BANDS

    h, w = shape
    top, bottom = SLOT_BANDS.get(category, (0.0, 1.0))
    # Bandı %8 genişlet — uzun kesim kıyafetler kırpılmasın.
    top, bottom = max(0.0, top - 0.08), min(1.0, bottom + 0.08)

    mask = np.zeros(shape, dtype=bool)
    mask[int(top * h):int(bottom * h)] = True
    return mask


# Bir vücut bölgesinin (slot) tuvalde kaplayabileceği DİKEY aralık.
#
# ⚠ `vton.SLOT_BANDS` ile KARIŞTIRMA. O tablo mock sağlayıcının kıyafeti
# yapıştıracağı kutuyu tarif ediyor ve dar: `ust` için (0.20, 0.55). Gerçek üst
# katmanlar y %73'e kadar iniyor — o tabloyu kapı olarak kullanmak sağlam
# katmanları keserdi. İki tablo aynı isme benziyor ama iki ayrı soruya cevap
# veriyor: "nereye yapıştırayım" ve "nerede OLABİLİR".
#
# Bu tablodaki sayılar ÖLÇÜLDÜ — dolaptaki 11 sağlam katmanın gerçek dikey
# yayılımı (tuval yüksekliğinin oranı olarak):
#
#   8 üst giyim (tişört/polo/gömlek) : y %22-25 → %68-73   hepsi
#   3 alt giyim (şort)               : y %55    → %84      hepsi
#
# Tutarlılık dikkat çekici; bant yine de cömertçe genişletildi, çünkü buranın
# işi segmentasyon DEĞİL: fiziksel olarak imkânsız olanı elemek. Pantolon
# bileğe kadar iner (alt bandın altı 1.0), uzun bir hırka kalçayı geçer.
REGION_BANDS: dict[str, tuple[float, float]] = {
    "ust":      (0.15, 0.80),
    "alt":      (0.46, 1.00),
    "dis":      (0.12, 0.88),
    "ayak":     (0.72, 1.00),
    # Aksesuar vücudun HER yerinde olabilir (şapka baş, kolye boyun, saat
    # bilek, kemer bel). Kapı burada tanım gereği anlamsız — ve anlamsız bir
    # kuralı "yine de biraz uygula" demek, sessizce doğru katman kesmektir.
    "aksesuar": (0.00, 1.00),
}

# Kapı maskenin bu kadarından fazlasını yerse UYGULANMIYOR (güvenlik freni).
#
# §17'deki önselin freniyle aynı mantık: bant yanlış ayarlanmışsa ya da kıyafet
# beklenmedik bir kesimdeyse (yerlere kadar uzanan elbise), kapı katmanı yok
# eder. Fren olmadan bu sessiz olurdu — katman "üretildi" görünür, içi boştur.
# Ölçüm: #16'nın attığı %16.1, sağlam katmanların %0.0-0.3'ü. Eşik 0.40 ikisine
# de uzak, yani fren gerçek vakalara hiç dokunmuyor.
REGION_GATE_MAX_DROP = 0.40


def region_band(category: str) -> tuple[float, float]:
    """Kategorinin kaplayabileceği dikey aralık — `config.slots()` üzerinden.

    Bant kategoriye DEĞİL, kategorinin kapladığı vücut bölgelerine bağlı. Fayda
    elbisede görünüyor: `slots` zaten ("ust", "alt") diyor, yani elbisenin bandı
    ikisinin BİRLEŞİMİ olarak kendiliğinden çıkıyor — ayrı bir satır yazmaya ve
    o satırın `CATEGORIES` ile ayrışma riskine gerek yok (§14 ilkesi).
    """
    from config import slots

    aralıklar = [REGION_BANDS[s] for s in slots(category) if s in REGION_BANDS]
    if not aralıklar:
        return (0.0, 1.0)
    return (min(a for a, _ in aralıklar), max(b for _, b in aralıklar))


def region_gate(mask: np.ndarray, category: str | None) -> np.ndarray:
    """Kıyafetin fiziksel olarak olamayacağı bölgedeki pikselleri atar.

    NEDEN VAR — ölçülmüş bir vaka. Chino pantolon (#16) giydirilirken tryon-max
    bacakların tamamını yeniden çizmek zorunda kaldı (base ŞORT giyiyor) ve bu
    arada gövdeyi ve YÜZÜ de yeniden üretti. Ölçüm, base'e göre fark:
    gövdede %52.8, yüzde %48.5 (aynı hattan geçen şortta %5.2 ve %30.1).
    Fark tabanlı çıkarım bunu sadakatle "kıyafet" saydı ve katman mankenin
    yüzüne HAYALET BİR YÜZ çizmeye başladı.
    Katmanın dikey dağılımı: %69.3 bacakta, **%23.9 belden yukarıda**.

    Bu bilgi zaten elimizdeydi: `config.CATEGORIES` her kıyafetin hangi vücut
    bölgesini kapladığını söylüyor. Pantolon yüzde olamaz.

    NEDEN BU FİLTRE, ÖNCEKİ ÜÇÜNÜN AKSİNE, ÇALIŞIYOR: §6.2 ve §19'daki üç
    deneme de RENGE bakıyordu ("bu piksel kıyafete mi base'e mi benziyor") ve
    üçü de gölgedeki gerçek kıyafet piksellerini yiyordu. Bu filtre renge hiç
    bakmıyor, KONUMA bakıyor — ve konum, rengin aksine, gölgeden etkilenmiyor.

    §17'nin dersinin aynısı: algoritmaya "nerede olmadığını" değil **nerede
    olabileceğini** söylemek. Orada şablon önseli bozuk bir kırpma modelini bile
    düzeltmişti.

    Ölçülen etki (11 sağlam katman + #16, aynı hattan):

        sağlam katmanların 11'i : silinen %0.0 - %0.3
        #16 chino pantolon      : silinen %16.1

    Yani filtre tam olarak ihtiyaç duyulduğu yerde çalışıyor, diğerlerine
    dokunmuyor.
    """
    if not category or not mask.any():
        return mask

    ust, alt = region_band(category)
    if (ust, alt) == (0.0, 1.0):          # aksesuar / bilinmeyen: kapı yok
        return mask

    h = mask.shape[0]
    kapi = np.zeros_like(mask)
    kapi[int(ust * h):int(np.ceil(alt * h))] = True
    yeni = mask & kapi

    # Güvenlik freni: kapı maskenin çoğunu yiyorsa bant bu kıyafet için yanlış.
    # Sessizce boş katman üretmektense hiç uygulanmaması iyi.
    if not yeni.any() or (mask.sum() - yeni.sum()) / mask.sum() > REGION_GATE_MAX_DROP:
        return mask
    return yeni


def extract_layer(
    base: Image.Image,
    dressed: Image.Image,
    threshold: int = DIFF_THRESHOLD,
    category: str | None = None,
    cutout_path: str | Path | None = None,
    use_color_filter: bool = False,
) -> Image.Image:
    """Giydirilmiş görüntüden sadece kıyafeti içeren RGBA katmanı çıkarır.

    cutout_path verilirse kıyafetin kendi renk paleti kullanılarak, farkın
    yakaladığı ama kıyafete ait olmayan bölgeler ayıklanır (bkz. color_filter).
    """
    if dressed.size != base.size:
        dressed = dressed.resize(base.size, Image.LANCZOS)

    # int32 şart: int16'da 255² = 65025 taşar (tavan 32767), fark negatife
    # dönüp sqrt NaN üretir. NaN > threshold her zaman False olduğu için
    # katman sessizce boşalır — ve bu tam olarak EN YÜKSEK kontrastlı
    # kıyafetlerde olur (beyaz mankene siyah pantolon).
    distance = rgb_distance(
        np.asarray(dressed.convert("RGB")), np.asarray(base.convert("RGB"))
    )

    mask = Image.fromarray(
        np.where(distance > threshold, 255, 0).astype(np.uint8), mode="L"
    )

    # Açma (aşındır→genişlet): tek tük gürültü piksellerini siler.
    # Kapama (genişlet→aşındır): kıyafetin içindeki delikleri doldurur.
    #
    # ÇEKİRDEKLER EŞİT OLMAK ZORUNDA. Önce Min(3)+Max(5) ve Max(5)+Min(3)
    # yazılmıştı; isimleri doğru ama aritmetiği değil: Min(3) 1 px aşındırır,
    # Max(5) 2 px genişletir — yani her "çift" net +1 px, ikisi birlikte
    # **silueti her kenardan 2 px şişiriyordu.**
    #
    # Sonuç sinsi: katmanın en dış piksel sırası kıyafet değil, kıyafetin
    # arkasındaki şeyle (duvar / ten / base'in kıyafeti) karışımı oluyordu ve
    # bindirmede kenarda renkli bir halka olarak görünüyordu. Ölçtük — kıyafetin
    # kendi paletine uzaklık, iç kısımda / en dış 1 px'te:
    #
    #   gri şort     12.1 / 34.2      sarı tişört  18.9 / 88.3
    #   bordo polo   11.0 / 52.9
    #
    # Kapama açmadan büyük çekirdek kullanıyor çünkü işleri farklı: açma tek
    # piksellik gürültüyü siler (küçük yeter), kapama gerçek delikleri doldurur.
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))

    # Tek adım genişletme — bu SEÇİM, artık kaza değil.
    #
    # Fark eşiği (18) kıyafetin yumuşak kenarında aşılamıyor: orada piksel
    # kıyafetle arkasının karışımı olduğu için fark zayıf. Yani eşik sınırı
    # gerçek kıyafet kenarının ~1 px İÇİNDE kalıyor ve genişletmezsek
    # bindirmede kenardan base sızıyor (ölçüldü: siluet kenarında 1-2 px'lik
    # base şeridi görünüyor).
    #
    # 1 px yetiyor. Eski kod 2 px genişletiyordu — ama bilerek değil, açma ve
    # kapamanın çekirdekleri eşit olmadığı için; fazladan gelen piksel sırası
    # kıyafete ait olmayan renkler taşıyordu. Şimdi genişletme kadarı kadar,
    # rengi de decontaminate_edges tazeliyor.
    if EXTRA_DILATE:
        mask = mask.filter(ImageFilter.MaxFilter(3))
    # Yumuşak kenar — üst üste bindirmede testere dişi görünmesin.
    mask = mask.filter(ImageFilter.GaussianBlur(1.2))

    # Kıyafet dışındaki serpintiyi at (bkz. largest_component).
    alpha = np.asarray(mask, dtype=np.uint8)
    solid = alpha > 128

    # Renk filtresi VARSAYILAN OLARAK KAPALI (use_color_filter=False).
    #
    # Temiz veriyle ölçüldü — hedef metriği düzeltiyor ama bütünü bozuyor:
    #
    #   filtresiz      : bel bandı %72 | polo kaplama %10.9 | şort %7.5
    #   tolerans 70    : bel bandı % 0 | polo kaplama % 9.8 | şort %5.7
    #   tolerans 100   : bel bandı % 0 | polo kaplama % 9.9 | şort %6.6
    #
    # Bel bandı gidiyor, ama gölgedeki gerçek kıyafet pikselleri de gidiyor;
    # yerlerine delik açılıyor ve alttaki eski kıyafet sızıyor. Yani bir
    # kusuru iki kusurla değişiyoruz.
    #
    # DAHA ÖNEMLİSİ: asıl sorun çıkarım algoritmasında değil, VERİDE. Her
    # kıyafet, üzerinde BAŞKA kıyafetler olan bir base'e karşı bağımsız
    # üretiliyor; iki katman birbirinden habersiz olduğu için bel çizgisi
    # tutmuyor. Bunu hiçbir piksel filtresi çözemez — base mankenin dar ve
    # sade giyinmiş olması çözer.
    if use_color_filter and cutout_path is not None:
        solid = color_filter(
            solid, np.asarray(dressed.convert("RGB")),
            garment_palette(cutout_path),
        )

    # Kıyafetin fiziksel olarak olamayacağı bölgeyi at (bkz. region_gate).
    #
    # SIRA — en büyük bileşenden önce, ama bu turda ÖLÇÜLDÜ ve etkisi küçük.
    # Beklenti şuydu: çöp (yeniden çizilmiş yüz ve gövde) pantolona BAĞLI
    # olduğu için `largest_component` onu "en büyük parçanın kendisi" sayıp
    # koruyor; kapı önce gelirse bağlantı kopar ve doğru parça seçilir.
    # Mekanizma doğru ama baskın değil — #16'nın gerçek verisiyle ölçüm:
    #
    #     kapı yok    : kaplama %22.06 · y %2-100 · 33 bağlı parça
    #     kapı SONDA  : kaplama %18.72 · y %46-100 · 12 parça
    #     kapı ÖNCE   : kaplama %18.71 · y %46-100 · 12 parça
    #
    # İki yerleşim arasındaki fark **46 piksel** (kapının kestiği köprünün
    # bant içinde kalan güdüğü). Yani "sonraya koymak işe yaramaz" DEĞİL;
    # önce koymak yalnızca biraz daha temiz. Buradaki asıl kazanç kapının
    # kendisi (%22.06 → %18.71), yerleşimi değil.
    #
    # §25'in dersi: doğru bir mekanizma açıklaması, o mekanizmanın baskın sebep
    # olduğunu kanıtlamaz. İkisi ayrı iddia ve ikincisi ölçüm ister.
    #
    # `fill_holes` bundan sonra geliyor ve kapının açtığı boşluğu geri
    # doldurmuyor: boşluk siluetin dışında, yani "içeride kalmış delik" değil.
    # (§6.1 #12'de ters sıra bir filtreyi tamamen etkisiz bırakmıştı.)
    solid = region_gate(solid, category)

    if has_scipy():
        keep = fill_holes(largest_component(solid))
    elif category is not None:
        keep = solid & _band_mask(alpha.shape, category)
    else:
        keep = solid

    if not keep.any():        # temizlik her şeyi sildiyse ham maskeye dön
        keep = solid

    # Base'in kıyafetinin sızdığı bölgeyi maskeden ÇIKAR.
    #
    # SIRA HER ŞEY — bu adım kontur pürüzsüzleştirmesinden ÖNCE olmalı, ikisi
    # birlikte çalışıyor:
    #   · Silmek bel bandındaki sızıntıyı kaldırır (altından nötr gösterim
    #     base'i görünür, göze batmaz).
    #   · Silmenin kenarda açtığı 1-2 px'lik tırtıklı çentikleri hemen ardından
    #     gelen pürüzsüzleştirme kapatır.
    # Tek başına silmek denendi: bant gitti ama kenar tırtıklandı. Tek başına
    # boyamak denendi (repaint_base_leak): kenar düzgün kaldı ama toleransın
    # dışındaki mavi pikseller katmanda kalıp KESİK KESİK bir bant yaptı.
    # İkisinin sırası doğru olunca iki kusur da yok oluyor.
    if cutout_path is not None:
        dressed_rgb = np.asarray(dressed.convert("RGB"))
        base_rgb_arr = np.asarray(base.convert("RGB"))

        if LEAK_FILTER in ("rgb", "both"):
            keep = drop_base_clothing(
                keep, dressed_rgb,
                base_clothing_palette(base_rgb_arr),
                garment_palette(cutout_path, colors=4),
            )
        if LEAK_FILTER in ("lab", "both"):
            # Palet 6 renk: Lab filtresi kıyafetin paletine YAKINLIK arıyor,
            # dar bir palet desenli kıyafette gerçek pikselleri sızıntı sayar.
            keep = drop_base_leak_lab(
                keep, dressed_rgb, base_rgb_arr,
                garment_palette(cutout_path, colors=6),
            )
        # Sentetik çıkarım base'inin rengi (chroma yeşil) katmana sızmışsa sil.
        # Ölçüldü: filtresiz #10'da 51 px çenede, #16'da 205 px kalıyordu ve
        # bindirmede yeşil noktalar olarak görünüyordu. Risksiz, çünkü aranan
        # renk gerçek değil — biz koyduk (bkz. drop_extract_color).
        keep = drop_extract_color(
            keep, dressed_rgb, base_clothing_palette(base_rgb_arr),
            garment_palette(cutout_path, colors=4),
        )
        if not keep.any():
            keep = solid

    # --- Kenar kalitesi: konturu pürüzsüzleştir, sonra yumuşat ---
    #
    # Önceki hâlde alfa 0'dan bir anda ~129'a sıçrıyordu (maske ikili, sınır
    # sert) ve maskenin sınırı piksel piksel gürültülüydü. Bindirmede sonuç
    # merdiven basamağı gibi tırtıklı kenarlar oluyordu.
    #
    # Bulanıklaştır→yeniden eşikle: konturu pürüzsüzleştirir, küçük çıkıntı ve
    # çentikleri siler (kenardaki tırtıkların asıl kaynağı buydu).
    # Ardından hafif bulanıklık: gerçek kenar yumuşatma. Alfa artık dışarıda 0,
    # içeride 255 ve arada düzgün bir rampa — kırpılmadığı için basamak yok.
    smooth = Image.fromarray((keep * 255).astype(np.uint8), mode="L")
    smooth = smooth.filter(ImageFilter.GaussianBlur(CONTOUR_SMOOTH))
    smooth = smooth.point(lambda v: 255 if v > 128 else 0)
    keep = np.asarray(smooth, dtype=np.uint8) > 128
    alpha = np.asarray(
        smooth.filter(ImageFilter.GaussianBlur(EDGE_SOFTEN)), dtype=np.uint8
    )
    if not keep.any():
        return Image.new("RGBA", base.size, (0, 0, 0, 0))

    rgb = np.asarray(dressed.convert("RGB"))

    # (repaint_base_leak ÇAĞRILMIYOR — silme+pürüzsüzleştirme ikilisi onun
    # yerini aldı; nedeni yukarıdaki "SIRA HER ŞEY" notunda.)

    # Kenar renklerini tazele — şekil aynı kalır (bkz. decontaminate_edges).
    # Maske olarak alfanın tamamı veriliyor: yumuşatma rampası maskenin biraz
    # dışına taşıyor ve o pikseller de kıyafetin rengini almalı, yoksa yarı
    # saydam bir karışım halkası kalır.
    clean = decontaminate_edges(rgb, alpha > 0, depth=EDGE_DECONTAM_DEPTH)

    layer = Image.fromarray(clean, mode="RGB").convert("RGBA")
    layer.putalpha(Image.fromarray(alpha, mode="L"))
    return layer


def layer_coverage(layer: Image.Image) -> float:
    alpha = np.asarray(layer.split()[3], dtype=np.uint8)
    return float((alpha > 128).mean())


def build_layer(
    garment_id: int,
    *,
    provider=None,
    force: bool = False,
    db_path=None,
) -> dict:
    """Tek bir kıyafet için katman üretir ve DB'ye işler.

    Asla exception fırlatmaz — başarısızlık `status="failed"` olarak kaydedilir,
    çünkü 100 kıyafetlik bir toplu üretimde 7. kıyafet yüzünden durmak istemiyoruz.
    """
    garment = get_garment(garment_id, db_path=db_path)
    if not garment:
        return {"garment_id": garment_id, "status": "failed",
                "error": "kıyafet bulunamadı"}

    base_row = mannequin.ensure(db_path=db_path)
    mannequin_id = _base_mannequin_id(db_path)

    existing = _get_layer(garment_id, mannequin_id, db_path)
    if existing and existing["status"] == "ready" and not force:
        return dict(existing) | {"skipped": True}

    provider = provider or vton.get_provider()
    category = garment["category"]

    # Katman çıkarımı "kıyafet dışı sabit kalır" varsayımına dayanıyor. Bunu
    # sağlamayan bir sağlayıcı sessizce baştan sona kirli bir katman üretirdi —
    # ölçülmesi saatler alan, hiçbir testin yakalamadığı türden bir hata.
    # O yüzden ücretli çağrıdan ÖNCE reddediliyor.
    if not vton.supports_layers(provider):
        return _record(
            garment_id, mannequin_id, category, "failed",
            error=(
                f"'{provider.name}' sağlayıcısı katman üretimine uygun değil: "
                "kıyafet dışındaki pikselleri de yeniden üretiyor, fark tabanlı "
                "çıkarım bozulur. Faz 4 render'ında kullanılabilir "
                "(python cli.py render ... --provider gemini)."
            ),
            db_path=db_path,
        )

    # Desteklenmeyen kategori sağlayıcıya sorulur: "ayakkabı olmaz" FASHN'ın
    # sınırı, evrensel bir kural değil.
    if not vton.supports_category(provider, category):
        return _record(
            garment_id, mannequin_id, category, "unsupported",
            error=(
                f"'{category}' için {provider.name} sağlayıcısında sanal deneme "
                f"modeli yok (desteklenen: {', '.join(sorted(vton.CATEGORY_MAP))})"
            ),
            db_path=db_path,
        )

    # ÇIKARIM GÖRÜNTÜSÜ — gerçek fotoğraf değil, `extraction_image()`.
    #
    # Varsa kıyafeti chroma yeşile boyanmış kopya kullanılıyor (§44): kullanıcı
    # ne giyerse giysin fark maksimum sinyalle çalışıyor. Ölçüldü — base'e
    # uzaklığı 1.0 olan lacivert tişörtte base sızıntısı %44.8 → %0.1.
    #
    # Yoksa fotoğrafın kendisi, yani bu özelliği kullanmayan mankende hat
    # aynen eskisi gibi. Gösterim TARAFI bundan etkilenmiyor: gösterim base'i
    # ve Faz 4 zinciri gerçek fotoğraftan geliyor.
    # Kategorinin bölgesine özel çıkarım base'i: üst giydirilirken yalnızca
    # üst yeşile boyanmış varyant kullanılıyor (yoksa tam varyanta düşer).
    cikarim = mannequin.extraction_image(
        mannequin_id, db_path, slot=mannequin.slot_for_category(category))
    try:
        base = load_any(cikarim).convert("RGB")
        dressed = provider.try_on(
            Path(cikarim), Path(garment["cutout_path"]), category
        )
        # Ham çıktıyı sakla: çıkarım eşiklerini her ayarladığımızda API'ye
        # tekrar para ödemek anlamsız. `reextract` bunu kullanarak katmanı
        # bedava yeniden üretiyor.
        dressed.save(raw_path(garment_id, mannequin_id), "PNG")
        layer = extract_layer(base, dressed, category=category,
                              cutout_path=garment['cutout_path'] or None)
    except Exception as exc:
        return _record(garment_id, mannequin_id, category, "failed",
                       error=f"{type(exc).__name__}: {exc}", db_path=db_path)

    ratio = layer_coverage(layer)
    alt_sinir, ust_sinir = coverage_range(category)
    warnings = []
    if ratio < alt_sinir:
        warnings.append(
            f"Katman neredeyse boş (%{ratio * 100:.2f}) — kıyafet mankene "
            "giydirilememiş olabilir."
        )
    elif ratio > ust_sinir:
        warnings.append(
            f"Katman çok geniş (%{ratio * 100:.1f}) — mankenin tamamı değişmiş, "
            "fark eşiği düşük kalmış olabilir."
        )

    path = LAYER_DIR / f"g{garment_id}_m{mannequin_id}.png"
    layer.save(path, "PNG")

    result = _record(garment_id, mannequin_id, category, "ready",
                     png_path=str(path), db_path=db_path)
    return result | {"coverage": ratio, "warnings": warnings,
                     "provider": provider.name}


def raw_path(garment_id: int, mannequin_id: int) -> Path:
    """Sağlayıcının ham çıktısı (giydirilmiş manken, kırpılmamış)."""
    return LAYER_DIR / f"g{garment_id}_m{mannequin_id}_raw.png"


def reextract(
    garment_id: int | None = None, *, db_path=None
) -> list[dict]:
    """Saklanmış ham çıktılardan katmanları yeniden çıkarır — BEDAVA.

    Eşik/temizlik parametrelerini ayarlarken kullanılır: API'ye tek kuruş
    ödemeden tüm dolabın katmanları yeniden üretilir.
    """
    base_row = mannequin.ensure(db_path=db_path)
    mannequin_id = _base_mannequin_id(db_path)
    # Ham çıktılar ÇIKARIM base'ine karşı üretildi; fark da ona karşı
    # alınmalı. Gerçek fotoğrafı kullanmak sessizce saçma bir katman üretirdi.
    # Base kıyafet başına çözülüyor: her kıyafetin ham çıktısı KENDİ slot
    # varyantına karşı üretildi, farkın da onunla alınması gerekiyor.
    def _base_for(kategori):
        return load_any(mannequin.extraction_image(
            mannequin_id, db_path,
            slot=mannequin.slot_for_category(kategori))).convert("RGB")

    garments = (
        [get_garment(garment_id, db_path=db_path)] if garment_id
        else list_garments(db_path=db_path)
    )

    results = []
    for garment in filter(None, garments):
        raw = raw_path(garment["id"], mannequin_id)
        if not raw.is_file():
            results.append({"garment_id": garment["id"], "status": "no_raw",
                            "error": "ham çıktı yok — önce build-layers çalıştır"})
            continue

        layer = extract_layer(
            _base_for(garment["category"]), Image.open(raw).convert("RGB"),
            category=garment["category"],
            cutout_path=garment["cutout_path"] or None,
        )
        path = LAYER_DIR / f"g{garment['id']}_m{mannequin_id}.png"
        layer.save(path, "PNG")

        record = _record(garment["id"], mannequin_id, garment["category"],
                         "ready", png_path=str(path), db_path=db_path)
        results.append(record | {"coverage": layer_coverage(layer)})
    return results


def build_all(
    *,
    provider=None,
    force: bool = False,
    category: str | None = None,
    exclude: list[int] | None = None,
    db_path=None,
) -> list[dict]:
    """Dolaptaki tüm kıyafetler için katman üretir.

    exclude: atlanacak kıyafet id'leri. Her çağrı ÜCRETLİ olduğu için gerekli —
    elden çıkarılan ya da yeniden çekilecek bir kıyafete para harcamamak
    tek satırla mümkün olmalı.
    """
    provider = provider or vton.get_provider()
    mannequin.ensure(db_path=db_path)
    atlanacak = set(exclude or ())

    results = []
    for garment in list_garments(category=category, db_path=db_path):
        if garment["id"] in atlanacak:
            continue
        results.append(
            build_layer(garment["id"], provider=provider, force=force,
                        db_path=db_path)
        )
    return results


def compose(garment_ids: list[int], db_path=None) -> Image.Image:
    """Katmanları z-sırasına göre mankenin üstüne bindirir.

    Faz 2'nin giydirme arayüzü tam olarak bunu yapacak — ama tarayıcıda CSS
    z-index ile. Buradaki sunucu tarafı sürüm doğrulama ve "gerçekçi göster"
    çıktısını dosyaya yazmak için.
    """
    mannequin.ensure(db_path=db_path)
    # Çıkarım base'i değil GÖSTERİM base'i: base'in kıyafeti nötrlenmiş hâli.
    # Nedeni mannequin.build_display_base'in docstring'inde.
    canvas = load_any(mannequin.display_base(db_path=db_path)).convert("RGBA")

    layers = []
    for gid in garment_ids:
        garment = get_garment(gid, db_path=db_path)
        row = _get_layer(gid, _base_mannequin_id(db_path), db_path)
        if not garment or not row or row["status"] != "ready":
            continue
        if not Path(row["png_path"]).is_file():
            continue
        layers.append((row["z_index"], row["png_path"]))

    for _, png_path in sorted(layers, key=lambda x: x[0]):
        layer = Image.open(png_path).convert("RGBA")
        canvas = Image.alpha_composite(canvas, layer)
    return canvas


def status_counts(db_path=None) -> dict[str, int]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM layers GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


# --- iç yardımcılar ---

def _base_mannequin_id(db_path=None) -> int:
    """Katmanın ait olacağı manken — AKTİF olan.

    `layers` tablosunun anahtarı (garment_id, mannequin_id); yani katmanlar
    zaten manken başına ayrı duruyor. Buranın aktif mankeni döndürmesi, çoklu
    mankende (§28) her mankenin kendi katman setini kazanmasına yetiyor —
    şema değişmiyor.
    """
    return mannequin.active_id(db_path)


def _get_layer(garment_id: int, mannequin_id: int, db_path=None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM layers WHERE garment_id = ? AND mannequin_id = ?",
            (garment_id, mannequin_id),
        ).fetchone()
    return dict(row) if row else None


def _record(
    garment_id: int,
    mannequin_id: int,
    category: str,
    status: str,
    *,
    png_path: str = "",
    error: str = "",
    db_path=None,
) -> dict:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO layers (garment_id, mannequin_id, png_path, z_index, "
            "status, error) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(garment_id, mannequin_id) DO UPDATE SET "
            "png_path = excluded.png_path, z_index = excluded.z_index, "
            "status = excluded.status, error = excluded.error",
            (garment_id, mannequin_id, png_path, z_index(category), status, error),
        )
    return {"garment_id": garment_id, "mannequin_id": mannequin_id,
            "png_path": png_path, "z_index": z_index(category),
            "status": status, "error": error}
