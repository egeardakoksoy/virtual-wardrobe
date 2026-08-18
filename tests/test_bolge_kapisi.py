"""Kategori bölge kapısı — kıyafetin olamayacağı yerdeki pikselleri atar.

NEDEN VAR (ölçülmüş vaka): chino pantolon (#16) giydirilirken tryon-max
bacakları yeniden çizerken GÖVDEYİ ve YÜZÜ de yeniden üretti. Fark tabanlı
çıkarım bunu sadakatle "kıyafet" saydı ve katman mankenin yüzüne hayalet bir
yüz çizmeye başladı. Katmanın %23.9'u belden yukarıdaydı.

Bu dosyanın asıl işi iki iddiayı kilitlemek:

1. **BAĞLI ÇÖP DE TEMİZLENİYOR.** Çöp kıyafete bağlıydı, yani `largest_component`
   ikisini tek parça görüp koruyordu — kapı olmadan katmanda kalıyor. Testin
   boşuna geçmediği ölçüldü: kapı kapatılınca yüzdeki piksel geri geliyor.

2. **ZARARSIZLIK** — sağlam katmanlara dokunmamalı. §6.2 ve §19'daki üç filtre
   denemesi tam burada çöktü: hedefi düzeltip gölgedeki gerçek kıyafet
   piksellerini yediler.

> ⚠ Bu testler kapının hattaki YERİNİ kilitlemiyor, çünkü ölçüm yerin baskın
> olmadığını gösterdi: #16'nın gerçek verisinde kapı "önce" ile "sonda" arasında
> yalnızca 46 piksel fark var (ayrıntı `extract_layer` içindeki notta). Asıl
> kazanç kapının kendisi.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from config import slots
from wardrobe.layers import (
    REGION_BANDS, extract_layer, region_band, region_gate,
)


def _mask(h=200, w=100, satirlar=None) -> np.ndarray:
    m = np.zeros((h, w), dtype=bool)
    for a, b in satirlar or []:
        m[a:b, 20:80] = True
    return m


# --- Bant tablosu ---

def test_bant_slotlardan_turuyor(tmp_path):
    """Bant kategoriye değil, `config.slots()`e bağlı olmalı.

    Ayrı bir kategori→bant tablosu yazılsaydı `CATEGORIES` ile ayrışabilirdi:
    yeni bir kategori eklenir, bant tablosuna eklenmesi unutulur ve o kategori
    sessizce kapısız kalırdı (§14 ilkesi).
    """
    assert slots("elbise") == ("ust", "alt")
    ust, alt = REGION_BANDS["ust"], REGION_BANDS["alt"]
    # Elbise iki bölgeyi de kaplıyor → bandı ikisinin BİRLEŞİMİ, ayrı satır yok
    assert region_band("elbise") == (min(ust[0], alt[0]), max(ust[1], alt[1]))


def test_aksesuar_kapisiz(tmp_path):
    """Şapka başta, saat bilekte, kemer belde — aksesuarda bant anlamsız.

    Anlamsız bir kuralı "yine de biraz uygula" demek, doğru katman kesmektir.
    """
    m = _mask(satirlar=[(0, 20), (180, 200)])
    assert np.array_equal(region_gate(m, "aksesuar"), m)


def test_bilinmeyen_kategori_dokunmuyor():
    m = _mask(satirlar=[(0, 200)])
    assert np.array_equal(region_gate(m, None), m)
    assert np.array_equal(region_gate(m, "yok_boyle_kategori"), m)


# --- Kapının kendisi ---

def test_alt_giyim_belden_yukarisini_atiyor():
    """Pantolon yüzde olamaz — ölçülen vakanın çekirdeği."""
    h = 200
    m = _mask(h=h, satirlar=[(10, 40), (100, 190)])   # yüz bölgesi + bacak
    yeni = region_gate(m, "alt")

    ust, _ = region_band("alt")
    assert not yeni[: int(ust * h)].any(), "belden yukarısı kalmış"
    assert yeni[150:190].any(), "bacaktaki gerçek kıyafet silinmiş"


def test_bandin_icindeki_maskeye_dokunmuyor():
    """Sağlam bir üst katman kapıdan değişmeden geçmeli.

    Dolaptaki 11 sağlam katmanda ölçülen de bu: silinen %0.0-0.3, dosyalar
    SHA-256 düzeyinde birebir aynı kaldı.
    """
    h = 200
    ust, alt = region_band("ust")
    m = _mask(h=h, satirlar=[(int(ust * h) + 5, int(alt * h) - 5)])
    assert np.array_equal(region_gate(m, "ust"), m)


def test_guvenlik_freni_maskeyi_kurtariyor():
    """Kapı maskenin çoğunu yiyorsa UYGULANMAMALI.

    Bant yanlış ayarlanmışsa ya da kıyafet beklenmedik bir kesimdeyse fren
    olmadan sonuç sessizce boş bir katman olurdu — "üretildi" görünür, içi
    boştur. §17'deki şablon önselinin freniyle aynı mantık.
    """
    h = 200
    # Kütlenin tamamı 'alt' bandının DIŞINDA: kapı her şeyi yerdi.
    m = _mask(h=h, satirlar=[(5, 80)])
    assert np.array_equal(region_gate(m, "alt"), m), "fren devreye girmedi"


def test_bos_maske_patlatmiyor():
    m = np.zeros((50, 50), dtype=bool)
    assert not region_gate(m, "alt").any()


# --- SIRA: en büyük bileşenden ÖNCE (asıl iddia) ---

def _sentetik(h=300, w=200, kopru=True):
    """Base + giydirilmiş çift üretir: bacakta gerçek kıyafet, yüzde ÇÖP.

    Çöp kıyafete ince bir köprüyle BAĞLI — gerçek vakadaki gibi. Bağlı olması
    şart: bağlı olmasaydı `largest_component` zaten temizlerdi ve test hiçbir
    şey kanıtlamazdı.
    """
    base = np.full((h, w, 3), 180, dtype=np.uint8)
    dressed = base.copy()
    dressed[int(0.55 * h):int(0.95 * h), 60:140] = (40, 60, 120)   # pantolon
    dressed[int(0.05 * h):int(0.20 * h), 80:120] = (30, 200, 90)   # yüzdeki çöp
    if kopru:
        dressed[int(0.20 * h):int(0.55 * h), 95:105] = (30, 200, 90)   # köprü
    return Image.fromarray(base), Image.fromarray(dressed)


def test_bagli_cop_temizleniyor():
    """ASIL TEST. Çöp kıyafete BAĞLIYKEN de gitmeli.

    Bağlılık şart: bağlı olmasaydı `largest_component` zaten temizlerdi ve bu
    test hiçbir şey kanıtlamazdı. Ölçüldü — kapı devre dışı bırakılınca yüzdeki
    pikseller katmanda kalıyor, yani testi geçiren şey gerçekten kapı.
    """
    base, dressed = _sentetik(kopru=True)
    layer = extract_layer(base, dressed, category="alt")

    a = np.asarray(layer.convert("RGBA"))[..., 3] > 128
    h = a.shape[0]
    assert a.any(), "katman tamamen boşaldı"
    ust, _ = region_band("alt")
    assert not a[: int(ust * h)].any(), "yüzdeki çöp katmanda kaldı"
    assert a[int(0.60 * h):int(0.90 * h)].any(), "gerçek kıyafet silinmiş"


def test_kategorisiz_cagri_kapiyi_atliyor():
    """Kategori bilinmiyorsa kapı uygulanmamalı — kural veriden geliyor."""
    base, dressed = _sentetik(kopru=True)
    layer = extract_layer(base, dressed, category=None)

    a = np.asarray(layer.convert("RGBA"))[..., 3] > 128
    h = a.shape[0]
    assert a[: int(0.25 * h)].any(), (
        "kategori yokken kapı uygulanmış — hangi bölge olduğunu bilmiyoruz")


@pytest.mark.parametrize("kategori", ["ust", "alt", "elbise", "dis_giyim"])
def test_saglam_katman_her_kategoride_hayatta(kategori):
    """Kapı, kendi bandının içindeki normal bir kıyafeti asla yok etmemeli."""
    h, w = 300, 200
    ust, alt = region_band(kategori)
    base = np.full((h, w, 3), 180, dtype=np.uint8)
    dressed = base.copy()
    dressed[int(ust * h) + 10:int(alt * h) - 10, 60:140] = (40, 60, 120)

    layer = extract_layer(Image.fromarray(base), Image.fromarray(dressed),
                          category=kategori)
    kaplama = (np.asarray(layer.convert("RGBA"))[..., 3] > 128).mean()
    assert kaplama > 0.05, f"{kategori}: kapı sağlam katmanı yedi (%{kaplama*100:.1f})"
