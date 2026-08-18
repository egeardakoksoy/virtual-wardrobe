"""Görüntü yardımcıları — telefon fotoğrafını hattın beklediği hale getirir.

Telefondan gelen fotoğrafların iki bilinen tuzağı var:
1. EXIF döndürme bayrağı — piksel verisi yan, sadece etiket "dik" diyor. PIL
   bunu kendiliğinden uygulamıyor, elle çevirmezsek kıyafet yatık işleniyor.
2. Çözünürlük — 4000px+ geliyor. Öznitelik çıkarımı için 1024px yeterli;
   küçültmek VLM token maliyetini birkaç kat düşürüyor.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from config import VLM_JPEG_QUALITY, VLM_MAX_PX


def load_upright(path: str | Path) -> Image.Image:
    """Görüntüyü açar, EXIF döndürmesini uygular, RGB'ye çevirir."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def load_any(path: str | Path) -> Image.Image:
    """load_upright gibi, ama varsa alfa kanalını korur.

    Kırpılmış PNG'de alfa, "kıyafet nerede" sorusunun cevabı. RGB'ye çevirip
    atmak renk analizini arka plana kaydırıyor — bu yüzden ayrı bir yükleyici.
    """
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img if img.mode == "RGBA" else img.convert("RGB")


def edge_color(img: Image.Image) -> tuple[int, int, int]:
    """Kenar piksellerinin medyan rengi — dolgu için "zeminin rengi" tahmini."""
    arr = np.asarray(img.convert("RGB"))
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    return tuple(int(c) for c in np.median(border, axis=0))


# Hizalamanın kabul edilen sınırları. Kullanıcı arayüzden bunların dışına
# çıkamıyor; sunucu yine de kırpıyor, çünkü değerler istemciden geliyor.
ALIGN_LIMITS = {"dx": 0.45, "dy": 0.45, "scale": (0.4, 2.5), "rotate": 30.0}


def clamp_align(
    dx: float = 0.0, dy: float = 0.0,
    scale: float = 1.0, rotate: float = 0.0,
) -> dict:
    """Hizalama değerlerini güvenli aralığa çeker.

    Ölçek 0 ya da negatif gelirse afin matris tekilleşir ve PIL patlar; dönme
    360'ın katlarıyla gelirse anlamsız ama zararsızdır. Değerler istemciden
    geldiği için burada kısıtlanıyor — arayüzün doğru davranmasına güvenmiyoruz.
    """
    lo, hi = ALIGN_LIMITS["scale"]
    return {
        "dx": max(-ALIGN_LIMITS["dx"], min(ALIGN_LIMITS["dx"], float(dx))),
        "dy": max(-ALIGN_LIMITS["dy"], min(ALIGN_LIMITS["dy"], float(dy))),
        "scale": max(lo, min(hi, float(scale))),
        "rotate": max(-ALIGN_LIMITS["rotate"],
                      min(ALIGN_LIMITS["rotate"], float(rotate))),
    }


def is_identity_align(align: dict | None) -> bool:
    """Dönüşüm görüntüyü değiştirmiyor mu? (gereksiz yeniden örneklemeyi atla)"""
    if not align:
        return True
    a = clamp_align(align.get("dx", 0), align.get("dy", 0),
                    align.get("scale", 1), align.get("rotate", 0))
    return (abs(a["dx"]) < 1e-4 and abs(a["dy"]) < 1e-4
            and abs(a["scale"] - 1) < 1e-4 and abs(a["rotate"]) < 1e-3)


def apply_align(img: Image.Image, align: dict | None) -> Image.Image:
    """Kullanıcının arayüzde yaptığı taşı/ölçekle/döndür işlemini uygular.

    NEDEN GEREKLİ: kırpma modeli kıyafetin kadrajın ortasında, kenarlara boşluk
    bırakarak durduğunu varsayıyor. Öyle değilse zeminin bir parçası kıyafete
    katılıyor ve o bozuk görsel VTON'a gidince model uydurma detay çiziyor
    (§16'da ölçüldü: beyaz tişörtün göğsünde olmayan bir pat belirdi). Şablon
    önseli bunu kurtarıyor ama önselin kıyafete oturması gerekiyor — hizalama
    tam olarak bunu sağlıyor.

    KOORDİNAT SÖZLEŞMESİ, arayüzle birebir aynı olmak zorunda:

      · Tuval boyutu DEĞİŞMİYOR — şablon 0-1 normalize koordinatlarda ve aynı
        tuvale göre çiziliyor. Tuval değişseydi önsel kayardı.
      · dx, dy tuval genişliğinin/yüksekliğinin oranı.
      · Ölçek ve dönme tuvalin MERKEZİ etrafında.
      · Sıra: önce ölçekle, sonra döndür, sonra taşı. CSS'teki
        `translate(...) rotate(...) scale(...)` tam olarak bu sırayı veriyor,
        yani arayüzdeki önizleme ile sunucudaki sonuç aynı.

    Açığa çıkan kenarlar zeminin medyan rengiyle dolduruluyor: siyahla
    doldurmak flood yedeğinin arka plan referansını bozar ve rembg'e sahte bir
    kontrast kenarı verir.

    ⚠ RGBA GİRDİDE dolgu ŞEFFAF. Hizalama artık kırpmadan SONRA uygulanıyor
    (§31), yani buraya gelen görüntü genelde kırpılmış bir RGBA. Kenarı zemin
    rengiyle doldurmak orada kıyafetin etrafına opak bir çerçeve çizerdi —
    ve o çerçeve VTON'a "kıyafetin parçası" olarak giderdi.
    """
    if is_identity_align(align):
        return img

    import math

    a = clamp_align(align.get("dx", 0), align.get("dy", 0),
                    align.get("scale", 1), align.get("rotate", 0))
    w, h = img.size
    cx, cy = w / 2, h / 2
    tx, ty = a["dx"] * w, a["dy"] * h
    s = a["scale"]
    th = math.radians(a["rotate"])
    cos, sin = math.cos(th), math.sin(th)

    # PIL'in AFFINE matrisi ÇIKTIDAN GİRDİYE eşliyor, yani ileri dönüşümün
    # tersini vermek gerekiyor:
    #     ileri : p_out = merkez + s·R(θ)·(p_in − merkez) + t
    #     ters  : p_in  = merkez + R(−θ)·(p_out − t − merkez) / s
    matrix = (
        cos / s, sin / s, cx - (cos * (tx + cx) + sin * (ty + cy)) / s,
        -sin / s, cos / s, cy - (-sin * (tx + cx) + cos * (ty + cy)) / s,
    )
    dolgu = (0, 0, 0, 0) if img.mode == "RGBA" else edge_color(img)
    return img.transform(
        (w, h), Image.AFFINE, matrix,
        resample=Image.BICUBIC, fillcolor=dolgu,
    )


def downscale(img: Image.Image, max_px: int = VLM_MAX_PX) -> Image.Image:
    """Uzun kenarı max_px'e indirir. Zaten küçükse dokunmaz (büyütmez)."""
    if max(img.size) <= max_px:
        return img
    out = img.copy()
    out.thumbnail((max_px, max_px), Image.LANCZOS)
    return out


def to_base64_jpeg(img: Image.Image, quality: int = VLM_JPEG_QUALITY) -> str:
    """API'ye gönderilecek base64 JPEG (satır sonu içermez)."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def rgb_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """İki RGB dizisi arasındaki Öklid uzaklığı — tip yükseltmesi garantili.

    NEDEN AYRI BİR FONKSİYON: bu projede aynı hata dört kez tekrarlandı.
    Görüntü dizileri uint8/int16 gelir; 255² = 65025 her ikisinin de tavanını
    aşar, fark negatife döner, sqrt NaN üretir. NaN her karşılaştırmada False
    döndüğü için hata gürültüsüzdür — maske sessizce boşalır ve bu tam olarak
    EN YÜKSEK kontrastlı, yani ayırt edilmesi en kolay durumda olur.

    Elle `.astype()` yazmayı hatırlamaya güvenmek yerine tek kapı bırakıyoruz.
    """
    diff = a.astype(np.float32) - b.astype(np.float32)
    return np.sqrt((diff ** 2).sum(axis=-1))


# --- CIE Lab ---
#
# NEDEN GEREKLİ: RGB uzaklığı parlaklıkla rengi aynı sayıya karıştırıyor ve bu,
# base sızıntısı filtresini ölçülebilir biçimde çökertti (§18.1).
#
# Ölçüldü — base'in kıyafeti orta mavi (67,96,144):
#
#     mor tişört (#4A2F6B)          RGB uzaklığı 61.8   (a*,b*) uzaklığı 22.1
#     base mavisinin ×0.60 gölgesi  RGB uzaklığı 74.2   (a*,b*) uzaklığı 10.3
#
# RGB SIRALAMAYI TERS ÇEVİRİYOR: base'in kendi gölgesi, mor tişörtten daha uzak
# görünüyor. Yani gölgeli sızıntıyı yakalayacak hiçbir tolerans (≥74 gerekir)
# morun kendisini (61.8) yemeden çalışamaz. Sorun filtrenin mantığında değil,
# ölçtüğü uzayda. Lab'de sıralama düzeliyor ve ayrım mümkün oluyor.
#
# skimage'a bağımlılık eklenmedi: dönüşüm 10 satır ve projenin kalanı saf
# numpy/PIL üstünde duruyor.
_SRGB_TO_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                         [0.2126729, 0.7151522, 0.0721750],
                         [0.0193339, 0.1191920, 0.9503041]], dtype=np.float32)
_D65_WHITE = np.array([0.95047, 1.00000, 1.08883], dtype=np.float32)

# Ağırlıklı Lab uzaklığında L*'ın payı. 1.0 = standart ΔE.
#
# Neden 1'den küçük: gölgedeki sızıntıyı da yakalamamız gerekiyor, ve gölge
# yalnızca L*'ı değiştiriyor. L*'ı tamamen atmak (0.0) da yanlış — o zaman
# lacivert ile açık mavi ayırt edilemez hale geliyor. Taranarak seçildi
# (bkz. layers.drop_base_leak_lab tablosu).
LAB_LIGHTNESS_WEIGHT = 0.5


def to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255) → CIE L*a*b* (D65). Son eksen 3 olmalı; şekli korur.

    float32'ye yükseltme burada da garantili — rgb_distance ile aynı gerekçe.
    """
    a = np.asarray(rgb, dtype=np.float32) / 255.0
    linear = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    xyz = (linear @ _SRGB_TO_XYZ.T) / _D65_WHITE

    epsilon, kappa = 216 / 24389, 24389 / 27
    f = np.where(xyz > epsilon, np.cbrt(xyz), (kappa * xyz + 16) / 116)
    return np.stack([
        116 * f[..., 1] - 16,
        500 * (f[..., 0] - f[..., 1]),
        200 * (f[..., 1] - f[..., 2]),
    ], axis=-1)


def lab_distance(
    a: np.ndarray, b: np.ndarray, lightness_weight: float = LAB_LIGHTNESS_WEIGHT
) -> np.ndarray:
    """Lab uzayında ağırlıklı uzaklık — L* payı azaltılmış.

    Girdi zaten Lab olmalı (to_lab çıktısı). L*'ı kısmak "aynı renk, farklı
    aydınlatma"yı yakınlaştırıyor; gölgedeki sızıntının asıl sorunu buydu.
    """
    d = np.asarray(a, dtype=np.float32) - np.asarray(b, dtype=np.float32)
    return np.sqrt(
        (lightness_weight * d[..., 0]) ** 2 + d[..., 1] ** 2 + d[..., 2] ** 2
    )


def dominant_color(img: Image.Image) -> tuple[int, int, int]:
    """Baskın rengi bulur — kaba kuantalama + en kalabalık kovanın ortalaması.

    Arka planı ayıklamanın iki yolu var, hangisi mümkünse o kullanılır:
      RGBA ise → şeffaf pikseller tamamen atlanır (en isabetlisi).
      RGB ise  → merkezdeki %50 alınır. Kıyafet karenin ortasında, zemin
                 kenarlarda olur; tüm kareye bakmak "baskın renk"i duvarın
                 rengi yapar.
    """
    small = downscale(img, 128)

    if small.mode == "RGBA":
        arr = np.asarray(small)
        pixels = arr[arr[..., 3] > 128][:, :3]
    else:
        w, h = small.size
        cropped = small.convert("RGB").crop((w // 4, h // 4, w * 3 // 4, h * 3 // 4))
        pixels = np.asarray(cropped).reshape(-1, 3)

    if pixels.size == 0:
        return (128, 128, 128)

    # 32'lik kovalara indir, en kalabalık kovayı bul, o kovadaki gerçek
    # piksellerin ortalamasını dön (kova merkezi yerine — daha isabetli).
    buckets = pixels // 32
    keys = buckets[:, 0] * 64 + buckets[:, 1] * 8 + buckets[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    winner = values[counts.argmax()]
    mean = pixels[keys == winner].mean(axis=0)
    return tuple(int(round(c)) for c in mean)


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)
