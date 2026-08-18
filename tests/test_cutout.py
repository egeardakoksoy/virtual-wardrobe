"""Arka plan temizleme — yedek (flood) yolunun doğruluğu."""
from __future__ import annotations

import builtins
import sys

import pytest
from PIL import Image

from tests.conftest import make_garment_photo
from wardrobe.cutout import coverage, has_rembg, remove_background


@pytest.fixture
def rembg_sys_exit(monkeypatch):
    """rembg'in import sırasında sys.exit(1) çağırdığı durumu taklit eder."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "rembg":
            raise SystemExit(1)
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "rembg", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_yarim_kurulmus_rembg_hatti_dusurmez(rembg_sys_exit):
    """Yarım kurulmuş opsiyonel bağımlılık tüm uygulamayı öldürmemeli.

    rembg, onnxruntime yokken import sırasında sys.exit(1) çağırıyor.
    SystemExit BaseException'dan türediği için `except Exception` onu
    kaçırıyor ve CLI'nin tamamı sessizce ölüyordu.
    """
    assert has_rembg() is False


def test_rembg_olmesine_ragmen_kirpma_calisir(rembg_sys_exit, photo, tmp_path):
    out = tmp_path / "cutout.png"
    assert remove_background(photo, out) == "flood"
    assert out.is_file()


def test_duz_zeminde_kiyafeti_ayirir(photo, tmp_path):
    out = tmp_path / "cutout.png"
    remove_background(photo, out)

    img = Image.open(out)
    assert img.mode == "RGBA"

    # Kıyafet karenin dörtte birini kaplıyor (200x200 içinde 100x100).
    assert 0.15 < coverage(out) < 0.35


def test_kose_seffaf_merkez_opak(photo, tmp_path):
    out = tmp_path / "cutout.png"
    remove_background(photo, out)

    alpha = Image.open(out).split()[3]
    assert alpha.getpixel((2, 2)) < 128           # köşe = arka plan
    assert alpha.getpixel((100, 100)) > 128       # merkez = kıyafet


def test_kiyafetin_icindeki_leke_silinmez(tmp_path):
    """Kenara bağlı olmayan arka plan rengi kıyafetin parçası sayılmalı.

    Gerçek karşılığı: beyaz tişörtün üstündeki beyaz baskı ya da lacivert
    ceketin lacivert düğmesi. Sadece renge bakan bir maske bunları deler.
    """
    src = make_garment_photo(tmp_path / "lekeli.jpg", hole=True)
    out = tmp_path / "cutout.png"
    remove_background(src, out)

    alpha = Image.open(out).split()[3]
    assert alpha.getpixel((100, 100)) > 128, "kıyafetin ortasında delik açıldı"


def test_yontem_adi_bildirilir(photo, tmp_path):
    method = remove_background(photo, tmp_path / "cutout.png")
    assert method in {"rembg", "flood"}


def test_flood_zorlanabilir(photo, tmp_path, monkeypatch):
    """rembg kurulu olsa bile yedek yöntem zorlanabilmeli.

    İki gerekçe: (1) testlerin hangi paketin kurulu olduğuna bağlı olmaması,
    (2) iki yöntemi aynı görselde karşılaştırabilmek.
    """
    monkeypatch.setattr("wardrobe.cutout._rembg_available", True)
    assert remove_background(photo, tmp_path / "c.png", method="flood") == "flood"


def test_rembg_yoksa_flooda_duser(photo, tmp_path, monkeypatch):
    monkeypatch.setattr("wardrobe.cutout._rembg_available", False)
    assert remove_background(photo, tmp_path / "c.png", method="rembg") == "flood"


def test_bilinmeyen_yontem_reddedilir(photo, tmp_path):
    with pytest.raises(ValueError, match="Bilinmeyen yöntem"):
        remove_background(photo, tmp_path / "c.png", method="photoshop")


def test_hedef_klasor_yoksa_olusturulur(photo, tmp_path):
    out = tmp_path / "yeni" / "alt" / "cutout.png"
    remove_background(photo, out)
    assert out.is_file()
