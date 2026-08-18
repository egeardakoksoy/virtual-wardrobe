"""Öznitelik çıkarımı — mock yolu ve normalleştirme.

Testler API'siz koşar (bkz. conftest.no_api_key). Buradaki asıl iddia: anahtar
yokken de hat anlamlı veri üretiyor — renk gerçekten görselden çıkıyor.
"""
from __future__ import annotations

import pytest

from config import CATEGORY_KEYS, PATTERNS, SEASONS, STYLES
from tests.conftest import make_garment_photo
from wardrobe.vision import (
    GARMENT_SCHEMA,
    _normalize,
    extract_attributes,
    has_api_key,
    nearest_color_name,
)


def test_anahtar_yoksa_mocka_duser(photo):
    assert not has_api_key()
    attrs = extract_attributes(photo)
    assert attrs["attr_source"] == "mock"


def test_mock_rengi_gercekten_gorselden_cikarir(tmp_path):
    """Uydurulmuş sabit değil — kırmızı görsel kırmızı, yeşil görsel yeşil."""
    kirmizi = make_garment_photo(tmp_path / "a.jpg", color=(200, 40, 45))
    yesil = make_garment_photo(tmp_path / "b.jpg", color=(60, 140, 80))

    assert extract_attributes(kirmizi)["color_name"] == "kırmızı"
    assert extract_attributes(yesil)["color_name"] == "yeşil"


@pytest.mark.parametrize("filename,expected", [
    ("mavi_gomlek.jpg", "ust"),
    ("siyah_chino_pantolon.jpg", "alt"),
    ("kot_ceket.jpg", "dis_giyim"),
    ("beyaz_sneaker.jpg", "ayakkabi"),
    ("yazlik_elbise.jpg", "elbise"),
    ("deri_kemer.jpg", "aksesuar"),
])
def test_mock_kategoriyi_dosya_adindan_tahmin_eder(tmp_path, filename, expected):
    path = make_garment_photo(tmp_path / filename)
    assert extract_attributes(path)["category"] == expected


def test_mock_ciktisi_sema_alanlarinin_tamamini_doldurur(photo):
    attrs = extract_attributes(photo)
    for field in GARMENT_SCHEMA["required"]:
        assert field in attrs, f"eksik alan: {field}"


def test_normalize_gecersiz_enumlari_duzeltir():
    out = _normalize({
        "category": "uzay_giysisi",
        "pattern": "hologram",
        "style": "siberpunk",
        "seasons": ["yaz", "muson"],
    })
    assert out["category"] in CATEGORY_KEYS
    assert out["pattern"] in PATTERNS
    assert out["style"] in STYLES
    assert out["seasons"] == ["yaz"]


def test_normalize_bos_mevsimi_tum_yila_cevirir():
    assert _normalize({"seasons": []})["seasons"] == list(SEASONS)


@pytest.mark.parametrize("raw,expected", [(99, 10), (-4, 0), ("7", 7), (None, 5),
                                          ("kalın", 5)])
def test_normalize_sayisal_alanlari_0_10_arasina_kirpar(raw, expected):
    """Şemada minimum/maximum desteklenmiyor — kırpma istemci tarafında."""
    assert _normalize({"warmth": raw})["warmth"] == expected


def test_sema_yapilandirilmis_cikti_kurallarina_uyar():
    assert GARMENT_SCHEMA["additionalProperties"] is False
    assert set(GARMENT_SCHEMA["required"]) == set(GARMENT_SCHEMA["properties"])


@pytest.mark.parametrize("rgb,expected", [
    ((10, 10, 10), "siyah"),
    ((250, 250, 250), "beyaz"),
    ((30, 40, 85), "lacivert"),
])
def test_renk_adi_en_yakin_paleti_secer(rgb, expected):
    assert nearest_color_name(rgb) == expected
