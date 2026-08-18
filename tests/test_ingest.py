"""Yükleme hattı — uçtan uca: fotoğraf → kırpma → öznitelik → DB."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from db import get_garment, list_garments
from tests.conftest import make_garment_photo
from wardrobe.ingest import IngestError, add_folder, add_garment


def test_uctan_uca_ekleme(photo, db_path):
    result = add_garment(photo, use_vlm=False, db_path=db_path)

    assert result["id"] > 0
    row = get_garment(result["id"], db_path=db_path)
    assert row["color_name"] == "kırmızı"
    assert row["cutout_method"] in {"rembg", "flood"}


def test_orijinal_ve_kirpilmis_dosya_yazilir(photo, db_path):
    result = add_garment(photo, use_vlm=False, db_path=db_path)

    assert Path(result["raw_path"]).is_file()
    assert Path(result["cutout_path"]).is_file()
    assert Image.open(result["cutout_path"]).mode == "RGBA"


def test_kaynak_dosya_silinmez(photo, db_path):
    """Kullanıcının fotoğrafını taşımıyoruz, kopyalıyoruz."""
    add_garment(photo, use_vlm=False, db_path=db_path)
    assert photo.is_file()


def test_ayni_foto_iki_kez_eklenirse_dosyalar_cakismaz(photo, db_path):
    a = add_garment(photo, use_vlm=False, db_path=db_path)
    b = add_garment(photo, use_vlm=False, db_path=db_path)
    assert a["raw_path"] != b["raw_path"]
    assert a["cutout_path"] != b["cutout_path"]


def test_olmayan_dosya_hata_verir(db_path):
    with pytest.raises(IngestError, match="bulunamadı"):
        add_garment("yok_boyle_bir_dosya.jpg", db_path=db_path)


def test_desteklenmeyen_tip_reddedilir(tmp_path, db_path):
    bad = tmp_path / "kiyafet.pdf"
    bad.write_bytes(b"%PDF-1.4")
    with pytest.raises(IngestError, match="Desteklenmeyen"):
        add_garment(bad, db_path=db_path)


def test_ayirt_edilemeyen_kiyafet_uyari_uretir(tmp_path, db_path):
    """Zemin ile kıyafet aynı renk → ayırt edilemez → sessizce geçilmemeli.

    Kullanıcı beyaz gömleği beyaz duvara asıp çektiğinde olan tam olarak bu.
    Kayıt yine de oluşur ama uyarı ile birlikte gelir.
    """
    src = make_garment_photo(
        tmp_path / "gorunmez.jpg", color=(250, 250, 250), background=(250, 250, 250)
    )
    result = add_garment(src, use_vlm=False, db_path=db_path)
    assert result["id"] > 0
    assert any("şüpheli" in w for w in result["warnings"]), result["warnings"]


def test_klasor_toplu_ekleme(tmp_path, db_path):
    folder = tmp_path / "dolap"
    folder.mkdir()
    make_garment_photo(folder / "mavi_gomlek.jpg", color=(40, 90, 190))
    make_garment_photo(folder / "siyah_pantolon.jpg", color=(20, 20, 20))
    make_garment_photo(folder / "beyaz_sneaker.jpg", color=(245, 245, 245))

    results = add_folder(folder, use_vlm=False, db_path=db_path)

    assert len(results) == 3
    assert all("error" not in r for r in results)
    assert {g["category"] for g in list_garments(db_path=db_path)} == {
        "ust", "alt", "ayakkabi"
    }


def test_bozuk_dosya_toplu_yuklemeyi_durdurmaz(tmp_path, db_path):
    """60 kıyafetlik yüklemede 3. dosya bozuk diye baştan başlamak istemiyoruz."""
    folder = tmp_path / "dolap"
    folder.mkdir()
    make_garment_photo(folder / "a_gomlek.jpg")
    (folder / "b_bozuk.jpg").write_bytes(b"bu bir jpeg degil")
    make_garment_photo(folder / "c_pantolon.jpg")

    results = add_folder(folder, use_vlm=False, db_path=db_path)

    assert len(results) == 3
    assert sum("error" in r for r in results) == 1
    assert len(list_garments(db_path=db_path)) == 2


def test_olmayan_klasor_hata_verir(db_path):
    with pytest.raises(IngestError, match="Klasör bulunamadı"):
        add_folder("yok_boyle_bir_klasor", db_path=db_path)
