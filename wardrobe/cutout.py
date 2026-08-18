"""Arka plan temizleme — dolap fotoğrafını "ürün fotoğrafı"na yaklaştırır.

Neden gerekli: Faz 1'de kullanılacak sanal deneme (VTON) modelleri beyaz zeminde,
düz serilmiş katalog görselleriyle eğitildi. Kullanıcının yatağın üstünde çektiği
buruşuk tişört bu modellerde kötü sonuç veriyor. Ön-işleme kalitesi tüm hattın
tavanını belirliyor.

İki yol var:
  rembg  — U^2-Net tabanlı, belirgin biçimde daha iyi. Opsiyonel bağımlılık
           (onnxruntime + ~170MB model indirir).
  flood  — rembg yoksa devreye giren saf numpy/PIL yedeği. Kenardan taşma
           (flood fill) ile düz zeminli fotoğraflarda makul sonuç verir,
           karışık arka planda zorlanır.

Hangi yolun kullanıldığı DB'ye yazılır (garments.cutout_method), böylece
"kötü katman" şikayetlerinde nedeni geriye dönük görebiliyoruz.
"""
from __future__ import annotations

import contextlib
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from config import FLOOD_TOLERANCE, FLOOD_WORK_PX
from wardrobe.imageutil import load_upright, rgb_distance


# rembg, arka uç motoru (onnxruntime) eksikken import sırasında sys.exit(1)
# çağırıyor. SystemExit, Exception'dan değil BaseException'dan türediği için
# `except Exception` onu yakalamıyor ve TÜM CLI sessizce ölüyor — yarım kurulmuş
# opsiyonel bir bağımlılık yüzünden. KeyboardInterrupt'ı yutmamak için bare
# `except BaseException` değil, SystemExit'i açıkça listeliyoruz.
_IMPORT_FAILURES = (Exception, SystemExit)

_rembg_available: bool | None = None   # yoklama sonucu (bir kez hesaplanır)


def has_rembg() -> bool:
    """rembg kullanılabilir mi? Sonuç önbelleğe alınır.

    Yoklama sırasında rembg'in stdout/stderr'e bastığı kurulum uyarısı
    yutuluyor: bizim için bu bir hata değil, "yedeğe düş" sinyali. Kullanıcıya
    kırmızı bir yığın izi göstermek yanlış alarm olurdu — doctor zaten durumu
    tek satırda ve doğru komutla bildiriyor.
    """
    global _rembg_available
    if _rembg_available is not None:
        return _rembg_available

    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            import rembg  # noqa: F401
        _rembg_available = True
    except _IMPORT_FAILURES:
        _rembg_available = False
    return _rembg_available


# Varsayılan yöntem seçimi. "auto" = rembg varsa o, yoksa flood.
# Testler bunu "flood"a sabitliyor: aksi halde test sonuçları hangi opsiyonel
# paketin kurulu olduğuna göre değişir ve 176MB model indirmesine bağımlı olur.
DEFAULT_METHOD = "auto"

METHODS = ("auto", "rembg", "flood")

# rembg'in hangi modeli kullanacağı. Varsayılan u2net'ten DEĞİŞTİRİLDİ.
#
# Ölçüldü — beyaz tişört, beyaz çarşaf üstünde (kontrast 61.8):
#   u2net             : solda kadrajın kenarına kadar uzanan çarşaf dilimini
#                       kıyafete kattı. O bozuk görsel VTON'a gidince model
#                       ortada uydurma bir pat çizdi ve logo kayboldu.
#   isnet-general-use : temiz kesti, kadraj kenarına değmedi. ✔
#   u2net_cloth_seg   : bozuk çıktı (çoklu maske üst üste), kullanılamaz.
#
# Model önbelleğe alındıktan sonra süre farkı yok (~1-1.5 sn). İlk çalıştırma
# modeli indirir.
REMBG_MODEL = "isnet-general-use"

# Maske bu çözünürlükte hesaplanıp orijinale büyütülüyor. Segmentasyon modelleri
# ~1024 civarında eğitiliyor; tam çözünürlükte kıyafetin içi delik deşik çıktı.
REMBG_WORK_PX = 1024

# Yumuşak matte'i katı maskeye çeviren eşik — ölçümle seçildi, bkz. _harden_alpha.
REMBG_ALPHA_THRESHOLD = 60


def remove_background(
    src: str | Path,
    dst: str | Path,
    method: str | None = None,
    shape: str | None = None,
) -> str:
    """src'yi arka planı şeffaf RGBA PNG olarak dst'ye yazar.

    Args:
        method: "auto" (rembg varsa o), "rembg" (yoksa flood'a düşer) veya
            "flood" (rembg kurulu olsa bile yedek yöntemi zorla). Sonuncusu
            iki yöntemi aynı görselde karşılaştırmak için.

    Returns:
        Gerçekten kullanılan yöntem: "rembg" veya "flood".
    """
    method = method or DEFAULT_METHOD
    if method not in METHODS:
        raise ValueError(f"Bilinmeyen yöntem: {method} (seçenekler: {METHODS})")

    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if method != "flood" and has_rembg():
        try:
            return _remove_rembg(src, dst, shape=shape)
        except _IMPORT_FAILURES:
            pass  # model indirilemedi / onnx hatası -> yedeğe düş
    return _remove_flood(src, dst)


# Şablon önselinin KURTARMA olarak devreye girmesi — KAPALI.
#
# ⚠ Bu bir geri alma. Önsel §17'de eklendi ve gerekçesi ölçülmüştü: beyaz
# tişört beyaz çarşafın üstünde, ESKİ u2net modeliyle, şablon bozuk kırpığı
# düzeltmişti. O ölçüm doğruydu — ama koşulları artık geçerli değil.
#
# Bugün ölçülen (isnet, 12 kıyafet):
#
#   · Kurtarma 12 kıyafetin 6'sında tetikleniyor — "yalnızca bozuk vakalara
#     dokunur" varsayımı tutmuyor.
#   · Tetiklendiğinde maskenin %18-47'sini siliyor.
#   · 2 vakada yardım ediyor (#10, #14: kıyafetin altındaki standı atıyor),
#     2 vakada zarar veriyor (#13'ün kolunu kırpıyor, #16'nın paçalarını
#     yok ediyor).
#   · #16'da sonuç ŞABLONUN KENDİSİYLE birebir aynı çıkıyordu: kırpık
#     pantolonun değil, `pantolon` şablonunun silüetiydi (paça 596 → 91 px).
#   · Poligon yerine sınırlayıcı kutu denendi, iyileştirdi ama yetmedi
#     (paça 342 px, hâlâ gerçek 596'nın yarısı).
#   · §17'nin motive ettiği vaka (#12) isnet ile kadraj kenarına HİÇ değmiyor,
#     yani kurtarmaya zaten uğramıyor. Asıl düzeltme §16'daki model
#     değişikliğiydi (u2net → isnet), şablon değil.
#
# Kod ve ölçümler duruyor: `True` yapmak tek satır. Şablonlar arayüzde ÇEKİM
# REHBERİ olarak kalıyor — asıl değerleri orada (§17: kolları açık serdirmek,
# kıyafeti kadrajın ortasında tutmak).
PRIOR_RESCUE = False


def _apply_prior(mask: np.ndarray, shape: str | None) -> np.ndarray:
    """Şablon önselini uygular — maske kadraj kenarına dayandığında kurtarma.

    ⚠ ARTIK ÇAĞRILMIYOR (`PRIOR_RESCUE = False`). Gerekçe sabitin yanında.
    Fonksiyon ölçüm kaydı ve tek satırla geri açılabilmesi için duruyor.

    Ölçüldü (beyaz tişört, beyaz çarşaf, eski u2net modeli):
        ham                %44.6 kaplama, kadraj kenarına DEĞİYOR
        şablonla sınırlı   %38.1 kaplama, değmiyor, kutu doluluğu %83

    Şablon bozuk modeli bile düzeltti. Buna karşılık "kenara değen parçayı at"
    yaklaşımı %0.1'e düşüyor, yani her şeyi siliyor — çünkü zemin kıyafete
    YAPIŞMIŞ tek parça oluyor. Bu yüzden negatif değil POZİTİF önsel gerekiyor.
    """
    from wardrobe.templates import DEFAULT_SHAPE, prior_mask

    h, w = mask.shape
    out = mask & prior_mask(shape or DEFAULT_SHAPE, w, h)
    return out if out.any() else mask


def _remove_rembg(src: str | Path, dst: Path, shape: str | None = None) -> str:
    from rembg import remove

    img = load_upright(src)

    # Maskeyi ÇALIŞMA çözünürlüğünde hesapla, sonra orijinale büyüt.
    # Ölçüldü: isnet tam çözünürlükte (1200px) kıyafetin içini delik deşik
    # ediyor (kutu doluluğu %51), 1024'te aynı ayarla %53 ve eşik+delik
    # doldurma ile %74'e çıkıyor. Modeller ~1024 civarında eğitiliyor.
    work = img.copy()
    work.thumbnail((REMBG_WORK_PX, REMBG_WORK_PX), Image.LANCZOS)

    session = _rembg_session()
    out = remove(work, session=session) if session else remove(work)

    ham = np.asarray(out.convert("RGBA").split()[3], dtype=np.uint8)
    alpha = _harden_alpha(ham)

    # KURTARMA: kırpık kadrajın kenarına dayanıyorsa zeminin bir parçası
    # kıyafete katılmış demektir. Şablon önseliyle bir kez daha dene.
    #
    # ⚠ KAPALI — ölçümle geri alındı, gerekçe `PRIOR_RESCUE` sabitinin
    # yanında. Kısaca: 12 kıyafetin 6'sında tetikleniyordu ve kıyafetin
    # kendi silüetini şablonunkiyle değiştiriyordu.
    if PRIOR_RESCUE and _mask_touches_edge(alpha > 128):
        alpha = _harden_alpha(
            np.where(_apply_prior(ham > REMBG_ALPHA_THRESHOLD, shape), ham, 0)
            .astype(np.uint8)
        )

    alpha = Image.fromarray(alpha, mode="L").resize(img.size, Image.BILINEAR)

    rgba = img.convert("RGBA")
    rgba.putalpha(alpha)
    rgba.save(dst, "PNG")
    return "rembg"


def person_mask(image: Image.Image) -> np.ndarray | None:
    """Fotoğraftaki KİŞİYİ (ön planı) bulan ikili maske. rembg yoksa None.

    NEDEN VAR — ölçülmüş bir vaka. `mannequin.build_display_base` base'in
    kıyafetini nötr koyuya boyuyor ve hangi piksellerin "kıyafet" olduğunu
    KROM (a*,b*) yakınlığıyla seçiyordu. O ölçüt, base'in kıyafeti doygun bir
    renk olduğunda kusursuz çalışıyor:

        orta mavi kıyafetli base : kıyafet 1.2 · duvar 30.2 · ten 46.6

    Ama kıyafet neredeyse SİYAH olduğunda krom düzleminde sıfıra yaklaşıyor —
    ve gri bir duvar da öyle. Ayrım çöküyor:

        siyah kıyafetli base     : kıyafet 0.8 · duvar 8.7 · ten 15.2

    Sonuç ölçüldü: tuvalin %43.7'si nötrlendi, arkadaki gri pano dev bir gri
    dikdörtgen olarak boyandı.

    Çözüm renk eşiğini oynatmak değil — hangi eşik seçilirse seçilsin siyah
    kıyafetle gri duvar krom düzleminde komşu kalıyor. Çözüm YAPISAL: base'in
    kıyafeti tanım gereği KİŞİNİN ÜSTÜNDE. Duvar, kapı, zemin kişinin dışında
    kalıyor ve bir eşiğe hiç sorulmadan eleniyor.

    §30'daki bölge kapısının aynı fikri: renge değil KONUMA bakmak.

    Ölçülen etki (nötrlenen tuval oranı):

        orta mavi base (çalışan durum) : %20.6 → %20.6   (dokunulmadı)
        siyah kıyafetli base (bozuk)   : %42.4 → %11.9

    rembg opsiyonel bir bağımlılık: yoksa None dönüyor ve çağıran eski
    davranışına düşüyor (hat kırılmıyor, sadece bu koruma devre dışı kalıyor).
    """
    if not has_rembg():
        return None

    from rembg import remove

    # Maske çalışma çözünürlüğünde hesaplanıp orijinale büyütülüyor —
    # segmentasyon modelleri ~1024'te eğitiliyor (§16'da ölçülmüş karar).
    work = image.convert("RGB")
    work.thumbnail((REMBG_WORK_PX, REMBG_WORK_PX), Image.LANCZOS)

    try:
        session = _rembg_session()
        out = remove(work, session=session) if session else remove(work)
    except _IMPORT_FAILURES:
        return None

    alpha = np.asarray(out.convert("RGBA").split()[3], dtype=np.uint8)
    büyük = Image.fromarray(alpha, mode="L").resize(image.size, Image.BILINEAR)
    return np.asarray(büyük, dtype=np.uint8) > 128


_person_cache: dict[tuple[str, int], np.ndarray] = {}


def person_mask_for(path: str | Path) -> np.ndarray | None:
    """`person_mask` ama dosya yolundan ve ÖNBELLEKLİ.

    Önbellek şart: `base_clothing_palette` kıyafet başına çağrılabiliyor ve
    her seferinde segmentasyon çalıştırmak 1-3 sn ekliyor. Anahtar (yol, mtime)
    — dosya değişirse maske de yenileniyor, yani bayat maske riski yok
    (§25.7'nin kuralının aynısı: damga dosyanın kendisinden gelsin).
    """
    p = Path(path)
    try:
        anahtar = (str(p), int(p.stat().st_mtime))
    except OSError:
        return None
    if anahtar in _person_cache:
        return _person_cache[anahtar]

    try:
        mask = person_mask(load_upright(p))
    except Exception:
        mask = None
    if mask is not None:
        _person_cache[anahtar] = mask
    return mask


_rembg_session_cache = None


def _rembg_session():
    """Model oturumu — bir kez kurulur, sonraki çağrılarda yeniden kullanılır.

    Kurulamazsa None dönüyor ve rembg kendi varsayılanıyla çalışıyor; model adı
    yanlış ya da indirilemiyorsa hat çökmesin.
    """
    global _rembg_session_cache
    if _rembg_session_cache is not None:
        return _rembg_session_cache or None

    try:
        from rembg import new_session
        _rembg_session_cache = new_session(REMBG_MODEL)
    except Exception:
        _rembg_session_cache = False
    return _rembg_session_cache or None


def _harden_alpha(alpha: np.ndarray, esik: int = REMBG_ALPHA_THRESHOLD) -> np.ndarray:
    """Yumuşak matte'i katı maskeye çevirir, delikleri kapatır.

    İKİ AYRI SORUNU ÇÖZÜYOR:

    1. isnet-general-use kıyafeti baştan sona YARI SAYDAM veriyor — ölçtük,
       tam opak piksel sayısı 1, "opak" bölgede ortalama alfa 159 (u2net'te
       252). Bu hattı SESSİZCE bozardı: `garment_palette()` alfası 200'ün
       üstündeki pikselleri örnekliyor, yani palet boş dönerdi ve ona dayanan
       her şey (kör nokta kontrolü, base sızıntısı filtresi) fark edilmeden
       devre dışı kalırdı.

    2. Sadece eşiklemek yetmiyor: kıyafetin içi delik deşik kalıyordu (kutu
       doluluğu %51). Kıyafet dolu bir silüet olduğuna göre içindeki her boşluk
       tanım gereği hata — en büyük bileşeni tut, delikleri doldur. Ölçüldü,
       kutu doluluğu %74'e çıkıyor.

    Eşik seçimi de ölçümle: 110 → delikli, 60 → temiz, 30 → zemini geri
    almaya başlıyor (kırpık kadrajın kenarına dayanıyor).
    """
    m = alpha > esik

    try:
        from scipy import ndimage
        lab, n = ndimage.label(m)
        if n > 1:
            boy = ndimage.sum(m, lab, range(1, n + 1))
            m = lab == (int(np.argmax(boy)) + 1)
        m = ndimage.binary_fill_holes(m)
    except ImportError:
        pass          # scipy yoksa sadece eşikle yetin

    kati = np.where(m, 255, 0).astype(np.uint8)
    # Hafif yumuşatma: kırpık kartonlaşmasın.
    return np.asarray(
        Image.fromarray(kati, mode="L").filter(ImageFilter.GaussianBlur(1.0)),
        dtype=np.uint8,
    )


def _remove_flood(src: str | Path, dst: Path) -> str:
    img = load_upright(src)
    alpha = _flood_alpha(img)
    rgba = img.convert("RGBA")
    rgba.putalpha(alpha)
    rgba.save(dst, "PNG")
    return "flood"


def _flood_alpha(img: Image.Image, tolerance: int = FLOOD_TOLERANCE) -> Image.Image:
    """Kenarlardan taşarak arka planı bulur, alfa maskesi döner.

    Maske küçük çözünürlükte (FLOOD_WORK_PX) hesaplanır — hem hızlı hem de
    JPEG gürültüsüne karşı doğal bir yumuşatma. Sonra bilineer büyütülerek
    kenarlarda yumuşak geçiş elde edilir.
    """
    work = img.copy()
    work.thumbnail((FLOOD_WORK_PX, FLOOD_WORK_PX), Image.LANCZOS)
    arr = np.asarray(work, dtype=np.int16)

    # Kenar piksellerinin medyan rengi = arka plan referansı
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    ref = np.median(border, axis=0)

    dist = rgb_distance(arr, ref)
    candidate = dist < tolerance

    background = _grow_from_border(candidate)

    # Arka plan = 0, kıyafet = 255
    mask = np.where(background, 0, 255).astype(np.uint8)
    return Image.fromarray(mask, mode="L").resize(img.size, Image.BILINEAR)


def _grow_from_border(candidate: np.ndarray) -> np.ndarray:
    """Kenara bağlı bileşenleri seçer (dört komşulu iteratif genişletme).

    Sadece "arka plan rengine yakın" olmak yetmez — kıyafetin ortasındaki beyaz
    bir yazı da o testi geçer. Arka plan olmak için ayrıca *kenara bağlı*
    olmak gerekiyor.
    """
    seed = np.zeros_like(candidate)
    seed[0, :] = candidate[0, :]
    seed[-1, :] = candidate[-1, :]
    seed[:, 0] = candidate[:, 0]
    seed[:, -1] = candidate[:, -1]

    while True:
        grown = seed.copy()
        grown[1:, :] |= seed[:-1, :]
        grown[:-1, :] |= seed[1:, :]
        grown[:, 1:] |= seed[:, :-1]
        grown[:, :-1] |= seed[:, 1:]
        grown &= candidate
        if np.array_equal(grown, seed):
            return seed
        seed = grown


def _mask_touches_edge(mask: np.ndarray, min_run: float = 0.06) -> bool:
    """touches_frame_edge'in dizi üzerinde çalışan hali (dosya okumadan)."""
    if not mask.any():
        return False
    return any(k.mean() >= min_run
               for k in (mask[0], mask[-1], mask[:, 0], mask[:, -1]))


def touches_frame_edge(cutout_path: str | Path, min_run: float = 0.06) -> bool:
    """Kırpık kadrajın kenarına dayanıyor mu? — bozuk kırpma işareti.

    Flat-lay çekimde kıyafet karenin ortasında durur, kenarlarda boşluk kalır.
    Kırpık kenara yapışıyorsa arka planın bir parçası kıyafet sanılmış demektir.

    Ölçülmüş vaka: beyaz tişört beyaz çarşafın üstünde çekildi (kontrast 61.8,
    sarı tişörtte 150+). rembg solda kadrajın kenarına kadar uzanan çarşaf
    dilimini kıyafete kattı; o bozuk görsel VTON'a gidince model ortada uydurma
    bir pat çizdi ve logo kayboldu.

    **Kaplama kontrolü bunu yakalamıyor** — o kırpık %44.5'ti, yani MIN/MAX
    aralığının tam ortasında. Kenara değme bağımsız bir sinyal.

    min_run: bir kenarın en az bu kadarı dolu olmalı ki "değiyor" sayılsın —
    tek tük piksel gürültüsü uyarı üretmesin.
    """
    img = Image.open(cutout_path)
    if img.mode != "RGBA":
        return False

    alpha = np.asarray(img.split()[3], dtype=np.uint8) > 128
    return _mask_touches_edge(alpha, min_run)


def coverage(cutout_path: str | Path) -> float:
    """Kırpılan görselde kıyafetin kapladığı alan oranı (0-1).

    Kalite kontrolü için: 0.02'nin altı "her şeyi sildik", 0.95'in üstü
    "hiçbir şeyi silemedik" demek. İkisi de kötü kırpma işareti.
    """
    img = Image.open(cutout_path)
    if img.mode != "RGBA":
        return 1.0
    alpha = np.asarray(img.split()[3], dtype=np.uint8)
    return float((alpha > 128).mean())
