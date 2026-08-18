"""Anahtar maskeleme — sızıntıya karşı en temel güvence.

Bu testlerin tek işi şu iddiayı korumak: anahtarın kendisi hiçbir çıktıya
girmiyor. `doctor` komutu ekrana bir şey basıyor, o çıktı ekran görüntüsü
alınıp paylaşılabiliyor; maskeleme bozulursa anahtar oradan sızar.
"""
from __future__ import annotations

from cli import main
from wardrobe import secrets

FAKE = "fal-abc123def456ghi789jkl012mno345"


def test_maskeleme_anahtari_ele_vermez():
    masked = secrets.mask(FAKE)
    assert FAKE not in masked
    assert masked.count("*") >= 8
    assert len(masked) < len(FAKE) + 5


def test_maskeleme_teshis_icin_yeterli_ipucu_birakir():
    """Doğru anahtarı yapıştırdığını anlayabilmelisin."""
    masked = secrets.mask(FAKE)
    assert masked.startswith(FAKE[:6])
    assert masked.endswith(FAKE[-4:])


def test_kisa_deger_tamamen_gizlenir():
    """Kısa anahtarda baş/son göstermek değerin yarısını açığa çıkarırdı."""
    assert secrets.mask("kisa") == "****"


def test_olmayan_anahtar_present_false(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert secrets.describe("FAL_KEY") == {"name": "FAL_KEY", "present": False}


def test_bos_string_yok_sayilir(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "   ")
    assert secrets.describe("FAL_KEY")["present"] is False


def test_tirnakli_yapistirma_yakalanir(monkeypatch):
    """.env'de FAL_KEY="abc" yazmak en sık yapılan hata."""
    monkeypatch.setenv("FAL_KEY", '"' + FAKE + '"')
    assert secrets.describe("FAL_KEY")["looks_quoted"] is True


def test_bosluklu_yapistirma_yakalanir(monkeypatch):
    monkeypatch.setenv("FAL_KEY", FAKE + "  ")
    assert secrets.describe("FAL_KEY")["has_whitespace"] is True


def test_temiz_anahtar_uyari_uretmez(monkeypatch):
    monkeypatch.setenv("FAL_KEY", FAKE)
    info = secrets.describe("FAL_KEY")
    assert info["present"] and not info["looks_quoted"]
    assert not info["has_whitespace"]


def test_doctor_anahtari_ekrana_basmaz(monkeypatch, capsys):
    """En kritik test: doctor çıktısı paylaşılabilir olmalı."""
    monkeypatch.setenv("FAL_KEY", FAKE)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "x" * 40)

    main(["doctor"])
    out = capsys.readouterr().out

    assert FAKE not in out
    assert "sk-ant-" + "x" * 40 not in out
    assert "FAL_KEY" in out          # ama var olduğunu söylemeli


def test_doctor_eksik_anahtarda_ne_olacagini_soyler(monkeypatch, capsys):
    monkeypatch.delenv("FAL_KEY", raising=False)
    main(["doctor"])
    assert "sahte katman" in capsys.readouterr().out
