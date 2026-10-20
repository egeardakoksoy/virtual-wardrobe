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


# --- Sıfırdan kurulum (§55) ---

def _yalnizca_foundry(monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "ornek-kaynak")
    monkeypatch.setenv("FOUNDRY_API_KEY", "test-anahtari")
    monkeypatch.setenv("FOUNDRY_IMAGE_DEPLOYMENT", "MAI-Image-2.6")
    monkeypatch.setenv("FOUNDRY_VISION_DEPLOYMENT", "gpt-4.1-mini")


def test_doctor_foundry_kurulumunda_yanlis_yonlendirmiyor(monkeypatch, capsys):
    """FAL/FASHN/Anthropic yokken "sahte katman üretilir" yazıyordu; oysa
    katmanları ve okumayı Foundry yapıyor. Sıfırdan kuran kişi bunu görüp
    kurulumun bozuk olduğunu sanardı."""
    _yalnizca_foundry(monkeypatch)
    main(["doctor"])
    cikti = capsys.readouterr().out

    assert "görüntü işleri Foundry'de (MAI-Image-2.6)" in cikti
    assert "kıyafet okuma Foundry'de (gpt-4.1-mini)" in cikti
    assert "sahte katman üretilir" not in cikti
    assert "test-anahtari" not in cikti


def test_doctor_python_multipart_yoksa_hata_verir(monkeypatch, capsys):
    """Paket yoksa arayüz hiç açılmıyor (FastAPI form/dosya yüklemesi)."""
    import cli

    monkeypatch.setattr(cli, "_multipart_var", lambda: False)
    assert main(["doctor"]) == 1
    assert "python-multipart  yok" in capsys.readouterr().out


def test_requirements_python_multipart_iceriyor():
    """Temiz makinede `pip install -r requirements.txt` arayüzü açabilmeli.
    fastapi bu paketi kendisi kurmuyor; eksikti ve geliştirme makinesinde
    başka bir paketle geldiği için fark edilmemişti."""
    from config import PROJECT_ROOT

    satirlar = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(s.strip().startswith("python-multipart") for s in satirlar)


def test_web_sifirdan_kurulumda_veritabanini_kurar(monkeypatch, capsys):
    """Veritabanı yokken `Dolabi Ac.bat` "no such table: layers" ile hemen
    kapanıyordu: web komutu tabloları kurmuyordu (§56)."""
    import web.app
    import db

    monkeypatch.setattr(web.app, "run", lambda **kw: None)   # sunucu açılmasın
    assert not db.DB_PATH.exists()

    assert main(["web"]) == 0
    assert "Yeni manken" in capsys.readouterr().out
    assert db.DB_PATH.exists()


def test_doctor_rembg_yoksa_hata_verir(monkeypatch, capsys):
    """rembg yokken doctor "opsiyonel" deyip "sağlam" diyordu; dış denemede
    kırpıklar arka planıyla kaldı ve pantolon katmanı delikli çıktı (§57)."""
    import cli

    monkeypatch.setattr(cli, "has_rembg", lambda: False)
    assert main(["doctor"]) == 1
    cikti = capsys.readouterr().out
    assert "✗ rembg" in cikti and 'pip install "rembg[cpu]"' in cikti


def test_doctor_scipy_yoksa_hata_verir(monkeypatch, capsys):
    """scipy yoksa katmanlar delikli kalıyor ve serpinti silinmiyor; eskiden
    yalnızca rembg ile dolaylı geliyordu (§57)."""
    monkeypatch.setattr("wardrobe.layers.has_scipy", lambda: False)
    assert main(["doctor"]) == 1
    assert "✗ scipy" in capsys.readouterr().out


def test_requirements_scipy_iceriyor():
    from config import PROJECT_ROOT

    satirlar = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert any(s.strip().startswith("scipy") for s in satirlar)
