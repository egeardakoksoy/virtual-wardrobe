"""CLI — komut dağıtımı ve çıkış kodları.

DB varsayılanı conftest'te tmp_path'e yönlendirildiği için bu testler
kullanıcının gerçek dolabına dokunmuyor.
"""
from __future__ import annotations

import pytest

from cli import main
from tests.conftest import make_garment_photo


def test_init(capsys):
    assert main(["init"]) == 0
    assert "Veritabanı hazır" in capsys.readouterr().out


def test_add_ve_list(tmp_path, capsys):
    photo = make_garment_photo(tmp_path / "mavi_gomlek.jpg", color=(40, 90, 190))

    assert main(["add", str(photo), "--no-vlm"]) == 0
    out = capsys.readouterr().out
    assert "mavi" in out

    assert main(["list"]) == 0
    assert "Toplam 1 kıyafet" in capsys.readouterr().out


def test_bos_dolapta_list_hata_kodu_doner(capsys):
    assert main(["list"]) == 1
    assert "Dolap boş" in capsys.readouterr().out


def test_olmayan_dosya_temiz_hata(capsys):
    assert main(["add", "yok.jpg"]) == 1
    assert "Hata:" in capsys.readouterr().out


def test_show_ve_rm(tmp_path, capsys):
    photo = make_garment_photo(tmp_path / "siyah_pantolon.jpg", color=(20, 20, 20))
    main(["add", str(photo), "--no-vlm"])
    capsys.readouterr()

    assert main(["show", "1"]) == 0
    assert "Orijinal" in capsys.readouterr().out

    assert main(["rm", "1"]) == 0
    assert main(["show", "1"]) == 1


def test_stats_bos_dolapta_calisir(capsys):
    assert main(["stats"]) == 0
    assert "Dolapta 0 kıyafet" in capsys.readouterr().out


def test_kategori_filtresi(tmp_path, capsys):
    main(["add", str(make_garment_photo(tmp_path / "gomlek.jpg")), "--no-vlm"])
    main(["add", str(make_garment_photo(tmp_path / "pantolon.jpg")), "--no-vlm"])
    capsys.readouterr()

    main(["list", "--category", "alt"])
    assert "Toplam 1 kıyafet" in capsys.readouterr().out


def test_gecersiz_kategori_reddedilir():
    with pytest.raises(SystemExit):
        main(["list", "--category", "uzay_giysisi"])


def test_komutsuz_cagri_reddedilir():
    with pytest.raises(SystemExit):
        main([])
