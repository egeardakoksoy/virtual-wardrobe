"""Çekim şablonları — kıyafet siluetleri.

İKİ İŞİ VAR:

1. **Çekim rehberi.** Kullanıcı kıyafeti şablonun içine serer. Böylece kollar
   açık kalıyor (§10: kıvrık kollu flat-lay'de model "kolun şekli bu" sanıyor)
   ve kıyafet kadrajın ortasında, kenarlara boşluk bırakarak duruyor.

2. **Segmentasyon önseli.** Asıl teknik kazanç burada. Ölçüldü — beyaz tişört
   beyaz çarşafın üstünde, ESKİ ve başarısız `u2net` modeliyle:

       ham                        kaplama %44.6  kadraj kenarına değiyor ✗
       şablonla sınırlandırılmış  kaplama %38.1  değmiyor, kutu doluluğu %83 ✓

   Şablon bozuk modeli bile düzeltti.

   Aynı ölçümde "kadraj kenarına değen parçayı at" yaklaşımı %0.1'e düştü, yani
   her şeyi sildi: çarşaf kıyafete YAPIŞMIŞTI, ayrı bir leke değildi. Bu yüzden
   algoritmaya "nerede olmadığını" değil **"nerede olduğunu"** söylemek gerekiyor.

Şablonlar normalize koordinatlarda (0-1) çokgen olarak duruyor; çözünürlükten
bağımsızlar. Milimetrik hizalama beklenmiyor — ölçümde düz bir DİKDÖRTGEN bile
sorunu çözdü, o yüzden önsel cömert bir payla genişletiliyor.
"""
from __future__ import annotations

# Her şablon: (x, y) normalize köşe noktaları, saat yönünde.
SHAPES: dict[str, dict] = {
    "tisort": {
        "label": "Tişört (kısa kol)",
        "category": "ust",
        "points": [
            (0.42, 0.16), (0.50, 0.19), (0.58, 0.16),
            (0.70, 0.19), (0.88, 0.33), (0.80, 0.47),
            (0.71, 0.41), (0.71, 0.85), (0.29, 0.85),
            (0.29, 0.41), (0.20, 0.47), (0.12, 0.33),
            (0.30, 0.19),
        ],
    },
    "uzun_kollu": {
        "label": "Uzun kollu / sweatshirt",
        "category": "ust",
        "points": [
            (0.42, 0.13), (0.50, 0.16), (0.58, 0.13),
            (0.70, 0.16), (0.86, 0.30), (0.95, 0.66),
            (0.84, 0.70), (0.72, 0.40), (0.72, 0.88),
            (0.28, 0.88), (0.28, 0.40), (0.16, 0.70),
            (0.05, 0.66), (0.14, 0.30), (0.30, 0.16),
        ],
    },
    "gomlek": {
        "label": "Gömlek",
        "category": "ust",
        "points": [
            (0.43, 0.12), (0.50, 0.18), (0.57, 0.12),
            (0.68, 0.15), (0.86, 0.29), (0.94, 0.64),
            (0.83, 0.69), (0.73, 0.39), (0.73, 0.88),
            (0.27, 0.88), (0.27, 0.39), (0.17, 0.69),
            (0.06, 0.64), (0.14, 0.29), (0.32, 0.15),
        ],
    },
    "sort": {
        "label": "Şort",
        "category": "alt",
        "points": [
            (0.24, 0.22), (0.76, 0.22), (0.78, 0.50),
            (0.72, 0.78), (0.55, 0.78), (0.52, 0.52),
            (0.48, 0.52), (0.45, 0.78), (0.28, 0.78),
            (0.22, 0.50),
        ],
    },
    "pantolon": {
        "label": "Pantolon",
        "category": "alt",
        "points": [
            (0.28, 0.10), (0.72, 0.10), (0.74, 0.40),
            (0.68, 0.92), (0.55, 0.92), (0.52, 0.46),
            (0.48, 0.46), (0.45, 0.92), (0.32, 0.92),
            (0.26, 0.40),
        ],
    },

    "crop": {
        "label": "Crop üst",
        "category": "ust",
        "points": [
            (0.42, 0.22), (0.50, 0.25), (0.58, 0.22),
            (0.70, 0.25), (0.86, 0.38), (0.79, 0.50),
            (0.71, 0.45), (0.71, 0.72), (0.29, 0.72),
            (0.29, 0.45), (0.21, 0.50), (0.14, 0.38),
            (0.30, 0.25),
        ],
    },
    "askili": {
        "label": "Askılı / atlet",
        "category": "ust",
        "points": [
            (0.38, 0.14), (0.44, 0.12), (0.46, 0.22),
            (0.54, 0.22), (0.56, 0.12), (0.62, 0.14),
            (0.68, 0.30), (0.68, 0.86), (0.32, 0.86),
            (0.32, 0.30),
        ],
    },

    # --- Elbise / tulum (ust + alt slotlarını birlikte kaplar) ---
    #
    # `elbise` kategorisi baştan beri config.CATEGORIES'te vardı ama HİÇ
    # şablonu yoktu: elbise yükleyen kullanıcı "Tişört" seçmek zorunda
    # kalıyordu ve kurtarma önseli eteği kesiyordu.
    "elbise": {
        "label": "Elbise",
        "category": "elbise",
        "points": [
            (0.42, 0.08), (0.50, 0.11), (0.58, 0.08),
            (0.68, 0.11), (0.80, 0.22), (0.74, 0.31),
            (0.68, 0.27), (0.70, 0.46), (0.84, 0.92),
            (0.16, 0.92), (0.30, 0.46), (0.32, 0.27),
            (0.26, 0.31), (0.20, 0.22), (0.32, 0.11),
        ],
    },
    "tulum": {
        "label": "Tulum",
        "category": "elbise",
        "points": [
            (0.40, 0.06), (0.50, 0.09), (0.60, 0.06),
            (0.72, 0.10), (0.80, 0.24), (0.74, 0.30),
            (0.70, 0.24), (0.72, 0.48), (0.68, 0.94),
            (0.54, 0.94), (0.51, 0.55), (0.49, 0.55),
            (0.46, 0.94), (0.32, 0.94), (0.28, 0.48),
            (0.30, 0.24), (0.26, 0.30), (0.20, 0.24),
            (0.28, 0.10),
        ],
    },

    # --- Etek ve tayt ---
    "etek": {
        "label": "Etek",
        "category": "alt",
        "points": [
            (0.34, 0.14), (0.66, 0.14), (0.72, 0.34),
            (0.86, 0.86), (0.14, 0.86), (0.28, 0.34),
        ],
    },
    "tayt": {
        "label": "Tayt / legging",
        "category": "alt",
        "points": [
            (0.32, 0.08), (0.68, 0.08), (0.68, 0.34),
            (0.62, 0.94), (0.53, 0.94), (0.51, 0.44),
            (0.49, 0.44), (0.47, 0.94), (0.38, 0.94),
            (0.32, 0.34),
        ],
    },

    # --- Dış giyim ---
    #
    # `dis_giyim` de config.CATEGORIES'te vardı ama şablonsuzdu — aynı boşluk.
    "ceket": {
        "label": "Ceket / hırka",
        "category": "dis_giyim",
        "points": [
            (0.40, 0.10), (0.50, 0.14), (0.60, 0.10),
            (0.72, 0.14), (0.90, 0.30), (0.97, 0.68),
            (0.85, 0.73), (0.74, 0.40), (0.74, 0.90),
            (0.26, 0.90), (0.26, 0.40), (0.15, 0.73),
            (0.03, 0.68), (0.10, 0.30), (0.28, 0.14),
        ],
    },
    "mont": {
        "label": "Mont / kaban",
        "category": "dis_giyim",
        "points": [
            (0.40, 0.06), (0.50, 0.11), (0.60, 0.06),
            (0.72, 0.10), (0.91, 0.26), (0.98, 0.64),
            (0.86, 0.70), (0.76, 0.38), (0.78, 0.94),
            (0.22, 0.94), (0.24, 0.38), (0.14, 0.70),
            (0.02, 0.64), (0.09, 0.26), (0.28, 0.10),
        ],
    },
}

DEFAULT_SHAPE = "tisort"

# Önsel maskesi bu oranda genişletiliyor. Kullanıcının hizalaması kabaca olacak;
# dar bir önsel gerçek kıyafeti keser. Ölçümde düz dikdörtgen bile yettiği için
# cömert olmak bedava.
PRIOR_MARGIN = 0.12


def shape_points(key: str) -> list[tuple[float, float]]:
    return SHAPES.get(key, SHAPES[DEFAULT_SHAPE])["points"]


def as_polygon(key: str, width: int, height: int,
               margin: float = 0.0) -> list[tuple[float, float]]:
    """Normalize şablonu piksel koordinatlarına çevirir.

    margin > 0 ise çokgen merkezinden dışarı doğru ölçeklenir — önsel için.
    """
    pts = shape_points(key)
    if margin:
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        k = 1.0 + margin
        pts = [(cx + (x - cx) * k, cy + (y - cy) * k) for x, y in pts]
    return [(x * width, y * height) for x, y in pts]


def prior_mask(key: str, width: int, height: int, margin: float = PRIOR_MARGIN):
    """Segmentasyon önseli — şablonun POLİGONU değil, SINIRLAYICI KUTUSU.

    ⚠ Bu bir hata düzeltmesi. Önce poligonun kendisi kullanılıyordu ve önsel
    maskeyle KESİŞTİĞİ için yalnızca silebiliyordu: kıyafet şablondan genişse
    fazlası kesiliyordu. Ölçülen sonuç, kurtarmanın tetiklendiği 6 kıyafette:

        #16 chino  : paça genişliği 340 px → 91 px. Sonuç şablonun kendisiyle
                     BİREBİR aynı çıktı — yani kırpık pantolonun değil,
                     `pantolon` şablonunun silüetiydi.
        #8/#10/#13/#14 : kollar kırpıldı
        #15        : şort ikiye bölündü

    Kurtarma 12 kıyafetin 6'sında tetikleniyor, yani "yalnızca bozuk vakalara
    dokunur" varsayımı tutmuyordu.

    Kutuya geçmenin dayanağı §17'nin KENDİ ölçümü: *"düz bir DİKDÖRTGEN bile
    sorunu çözdü."* Önselin işi segmentasyon değil, "kıyafet kabaca burada"
    demek — kıyafetin siluetini dayatmak değil.

    Ölçüldü (kaplama; önselsiz / poligon / kutu):

        #8  %67.4 / %41.0 / %58.5      #14 %46.7 / %33.4 / %44.7
        #10 %61.2 / %37.8 / %52.7      #15 %34.0 / %18.1 / %22.2
        #13 %37.7 / %30.8 / %37.6      #16 %42.2 / %27.4 / %31.5

    Görsel: kutu, kolları ve paçaları koruyor ama kıyafetin ALTINDAKİ yabancı
    nesneyi (sehpa/stand) hâlâ atıyor — kurtarmanın asıl işi buydu.

    Poligonun kendisi arayüzdeki ÇEKİM REHBERİ olarak duruyor (`shape_points`);
    orada kıyafet şeklinde olması doğru, çünkü orada bir şey kesmiyor.
    """
    import numpy as np

    pts = as_polygon(key, width, height, margin)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mask = np.zeros((height, width), dtype=bool)
    mask[max(0, int(min(ys))):int(max(ys)),
         max(0, int(min(xs))):int(max(xs))] = True
    return mask
