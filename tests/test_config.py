"""Kategori tablosu — katman sırası ve slot çakışması.

Bu tablo projenin en kritik kararını taşıyor: hangi kıyafet hangisinin üstüne
biner ve hangi ikili aynı anda giyilemez. Bozulursa manken saçmalar.
"""
from __future__ import annotations

import pytest

from config import CATEGORY_KEYS, conflicts, slots, z_index


def test_katman_sirasi_beklenen_duzende():
    """Ayakkabı < alt < üst < dış giyim: giyinme sırasının ta kendisi."""
    assert z_index("ayakkabi") < z_index("alt") < z_index("ust") < z_index("dis_giyim")


def test_bilinmeyen_kategori_en_uste_gider():
    assert z_index("uzay_giysisi") > max(z_index(k) for k in CATEGORY_KEYS)


def test_elbise_hem_ust_hem_alt_kaplar():
    assert set(slots("elbise")) == {"ust", "alt"}


@pytest.mark.parametrize("a,b", [("ust", "elbise"), ("alt", "elbise"), ("ust", "ust")])
def test_ayni_bolgeyi_kaplayanlar_cakisir(a, b):
    assert conflicts(a, b)


@pytest.mark.parametrize("a,b", [("ust", "alt"), ("ust", "ayakkabi"),
                                 ("elbise", "dis_giyim"), ("alt", "ayakkabi")])
def test_farkli_bolgeler_birlikte_giyilebilir(a, b):
    assert not conflicts(a, b)


def test_elbise_ustun_altinda_kalir():
    """Elbise üst giyimden önce, dış giyimden önce çizilmeli."""
    assert z_index("alt") < z_index("elbise") <= z_index("ust") < z_index("dis_giyim")
