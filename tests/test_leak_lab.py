"""Base sızıntısının Lab filtresi — Sorun A (§18.1).

Bu dosyanın çekirdek testi `test_rgb_siralamayi_ters_ceviriyor`. Filtrenin
varlık sebebi orada: RGB uzaklığında base'in KENDİ GÖLGESİ, base'e komşu bir
kıyafet renginden daha uzak çıkıyor. Yani hiçbir RGB toleransı sızıntıyı
kıyafetten ayıramıyor — sorun eşikte değil, uzayda.

Sayılar gerçek verinin ölçümünden geliyor: base'in kıyafeti #436090, mor
tişört #4A2F6B.
"""
from __future__ import annotations

import numpy as np
import pytest

from wardrobe.imageutil import lab_distance, rgb_distance, to_lab
from wardrobe.layers import drop_base_leak_lab

BASE_MAVI = np.array([[67, 96, 144]], dtype=np.int16)      # #436090
MOR = np.array([[74, 47, 107]], dtype=np.int16)            # #4A2F6B


def krom(a, b):
    """Sadece (a*,b*) — parlaklık payı sıfır."""
    return float(lab_distance(to_lab(a), to_lab(b), lightness_weight=0.0).item())


# --- kök sebep ---

def test_rgb_siralamayi_ters_ceviriyor():
    """Filtrenin niye RGB'de yazılamayacağının kanıtı.

    Base mavisinin gölgesi RGB'de mordan DAHA UZAK görünüyor. Sızıntıyı
    yakalayacak bir tolerans (≥74) morun kendisini (61.8) de yerdi.
    """
    golge = (BASE_MAVI.astype(np.float32) * 0.60)

    d_mor = rgb_distance(MOR.astype(np.float32), BASE_MAVI.astype(np.float32)).item()
    d_golge = rgb_distance(golge, BASE_MAVI.astype(np.float32)).item()

    assert d_golge > d_mor, (
        f"ölçüm değişti: gölge {d_golge:.1f}, mor {d_mor:.1f} — "
        "RGB artık sıralamayı ters çevirmiyorsa bu filtrenin gerekçesi de yok"
    )


def test_lab_kromu_siralamayi_duzeltiyor():
    """Aynı iki renk, krom düzleminde doğru sırada."""
    golge = (BASE_MAVI.astype(np.float32) * 0.60).astype(np.int16)

    assert krom(golge, BASE_MAVI) < krom(MOR, BASE_MAVI)
    assert krom(golge, BASE_MAVI) < 12      # gölge = aynı renk
    assert krom(MOR, BASE_MAVI) > 18        # mor = başka renk


def test_lab_donusumu_bilinen_degerleri_veriyor():
    """Referans noktaları — dönüşüm sessizce bozulursa buradan görünür."""
    beyaz = to_lab(np.array([255, 255, 255], dtype=np.uint8))
    siyah = to_lab(np.array([0, 0, 0], dtype=np.uint8))
    kirmizi = to_lab(np.array([255, 0, 0], dtype=np.uint8))

    assert beyaz[0] == pytest.approx(100.0, abs=0.1)
    assert beyaz[1] == pytest.approx(0.0, abs=0.1)
    assert siyah[0] == pytest.approx(0.0, abs=0.1)
    assert kirmizi[0] == pytest.approx(53.24, abs=0.2)
    assert kirmizi[1] == pytest.approx(80.09, abs=0.2)


def test_lab_donusumu_sekli_korur():
    arr = np.zeros((7, 5, 3), dtype=np.uint8)
    assert to_lab(arr).shape == (7, 5, 3)
    assert to_lab(np.zeros((4, 3), dtype=np.uint8)).shape == (4, 3)


# --- filtre davranışı ---

SIZINTI_SUTUNU = 16     # 20 sütunun son 4'ü = %20 sızıntı


def sahne(kiyafet_rgb, sizinti_rgb=None):
    """Base'i mavi olan 20x20 sahne: çoğunluk kıyafet, sağ şerit sızıntı.

    Sızıntı oranı bilerek %20: gerçek katmanlarda ölçülen oran %0-5 bandında
    ve filtrenin güvenlik freni maskenin %45'inden fazlası gidecekse devreye
    giriyor. Yarı yarıya bir sahne freni tetikler ve test, filtreyi değil
    freni ölçerdi.
    """
    base = np.full((20, 20, 3), BASE_MAVI[0], dtype=np.uint8)

    dressed = np.full((20, 20, 3), kiyafet_rgb, dtype=np.uint8)
    dressed[:, SIZINTI_SUTUNU:] = (
        sizinti_rgb if sizinti_rgb is not None else BASE_MAVI[0])

    mask = np.ones((20, 20), dtype=bool)
    return mask, dressed, base


def test_base_rengindeki_pikselleri_atar_kiyafeti_birakir():
    mask, dressed, base = sahne(MOR[0])
    out = drop_base_leak_lab(mask, dressed, base, MOR)

    assert out[:, :SIZINTI_SUTUNU].all(), "kıyafetin kendi pikselleri silinmiş"
    assert not out[:, SIZINTI_SUTUNU:].any(), "base sızıntısı kalmış"


def test_golgeli_sizintiyi_da_atar():
    """Asıl kazanç burada: sızıntı gölgede olsa bile yakalanıyor.

    RGB tabanlı filtre bu vakada çaresiz — gölgeli mavi ile mor arasındaki
    RGB uzaklığı farkı ayırt etmeye yetmiyor.
    """
    golge = (BASE_MAVI[0].astype(np.float32) * 0.6).astype(np.uint8)
    mask, dressed, base = sahne(MOR[0], sizinti_rgb=golge)

    out = drop_base_leak_lab(mask, dressed, base, MOR)

    assert out[:, :SIZINTI_SUTUNU].all()
    assert not out[:, SIZINTI_SUTUNU:].any(), "gölgeli sızıntı kaldı"


def test_guvenlik_freni_maskenin_cogu_gidecekse_uygulanmaz():
    """§6.2'nin dersi: filtre maskenin çoğunu yiyorsa varsayım yanlıştır.

    Kıyafetin kendisi base rengindeyse (tanım gereği ayırt edilemez) filtre
    her şeyi silerdi. O durumda hiç uygulanmıyor.
    """
    mask, dressed, base = sahne(BASE_MAVI[0])
    out = drop_base_leak_lab(mask, dressed, base, BASE_MAVI)

    assert out.all(), "güvenlik freni tutmadı — katman boşalırdı"


def test_bos_palet_ve_bos_maske_zararsiz():
    mask, dressed, base = sahne(MOR[0])
    bos_palet = np.empty((0, 3), dtype=np.int16)

    assert drop_base_leak_lab(mask, dressed, base, bos_palet) is mask
    bos = np.zeros_like(mask)
    assert drop_base_leak_lab(bos, dressed, base, MOR) is bos


def test_uzak_renkli_kiyafete_dokunmaz():
    """Sarı tişört base'den çok uzak — filtre hiçbir şey silmemeli."""
    sari = np.array([[242, 203, 27]], dtype=np.int16)
    mask = np.ones((20, 20), dtype=bool)
    dressed = np.full((20, 20, 3), sari[0], dtype=np.uint8)
    base = np.full((20, 20, 3), BASE_MAVI[0], dtype=np.uint8)

    assert drop_base_leak_lab(mask, dressed, base, sari).all()


def test_ayni_koordinattaki_base_ile_karsilastiriyor():
    """Karar palet ortalamasıyla değil, base'in O NOKTADAKİ pikseliyle veriliyor.

    Sınama: AYNI renkteki pikseller, altlarındaki base farklı olduğu için
    farklı sınıflandırılmalı. Palet tabanlı bir filtre ikisini de aynı sayardı.

    Yan faydası şu: base'in duvar ya da ten olduğu yerde uzaklık zaten büyük
    çıkıyor — yani "sadece gövde bölgesine bak" diye ayrı bir konum kuralı
    yazmak gerekmiyor, konum bilgisi karşılaştırmanın içinde geliyor.
    """
    mor_tonu = np.array([88, 60, 120], dtype=np.uint8)     # kıyafete yakın bir mor
    mask = np.ones((20, 20), dtype=bool)
    dressed = np.full((20, 20, 3), mor_tonu, dtype=np.uint8)

    base = np.full((20, 20, 3), (199, 190, 177), dtype=np.uint8)   # duvar
    base[:, SIZINTI_SUTUNU:] = mor_tonu     # burada base'in kendisi o renkte

    out = drop_base_leak_lab(mask, dressed, base, MOR)

    assert out[:, :SIZINTI_SUTUNU].all(), (
        "base'in duvar olduğu yerde piksel kıyafete ait — korunmalıydı"
    )
    assert not out[:, SIZINTI_SUTUNU:].any(), (
        "base'in tam o renkte olduğu yer sızıntı — atılmalıydı"
    )
