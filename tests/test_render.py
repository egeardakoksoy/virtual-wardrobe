"""Faz 4 — zincirleme giydirme ve önbellek.

Bu bölümdeki testler ÜCRETLİ yolun kararlarını doğruluyor: kaç çağrı yapılacak,
hangi sırayla, ne atlanacak, ne zaman önbellekten dönülecek. Gerçek API
çağrılmıyor — MockProvider kullanılıyor.

Önbellek burada kozmetik değil maliyet kalemi: her isabet ~$0.075 tasarruf.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from db import connect
from wardrobe import mannequin, render, vton


@pytest.fixture
def dolap(db_path, tmp_path):
    """Bir üst, bir alt, bir de desteklenmeyen ayakkabı."""
    from wardrobe.ingest import add_garment

    mannequin.placeholder(db_path=db_path)
    ids = []
    for renk, ad in (((200, 40, 45), "ust.png"), ((40, 60, 200), "alt.png"),
                     ((30, 30, 30), "ayakkabi.png")):
        foto = tmp_path / ad
        arr = np.full((300, 220, 3), 250, dtype=np.uint8)
        arr[80:230, 60:170] = renk
        Image.fromarray(arr).save(foto)
        ids.append(add_garment(foto, use_vlm=False, db_path=db_path)["id"])

    with connect(db_path) as conn:
        for gid, kat in zip(ids, ("ust", "alt", "ayakkabi")):
            conn.execute("UPDATE garments SET category=? WHERE id=?", (kat, gid))
    return {"ust": ids[0], "alt": ids[1], "ayakkabi": ids[2]}


# --- plan: ücretli çağrıdan ÖNCE ne olacağını söyler ---

def test_plan_cagri_sayisi_ve_ucreti_bildirir(dolap, db_path):
    p = render.plan([dolap["ust"], dolap["alt"]], db_path=db_path)

    assert p["calls"] == 2
    assert p["cost_usd"] == pytest.approx(2 * render.CALL_COST_USD)
    assert p["skipped"] == []


def test_plan_altligi_once_giydirir(dolap, db_path):
    """Zincir sırası z'ye göre artan olmalı.

    Üst giydirilirken model altı zaten görmeli — katman mimarisinin
    çözemediği bel çizgisi sorunu (§7) tam olarak bu yüzden burada yok.
    """
    p = render.plan([dolap["ust"], dolap["alt"]], db_path=db_path)
    assert p["order"] == [dolap["alt"], dolap["ust"]]

    # Giriş sırası değişse de sonuç aynı olmalı
    p2 = render.plan([dolap["alt"], dolap["ust"]], db_path=db_path)
    assert p2["order"] == p["order"]


def test_plan_desteklenmeyeni_atlar_ve_gerekcesini_yazar(dolap, db_path):
    p = render.plan([dolap["ust"], dolap["ayakkabi"]], db_path=db_path)

    assert p["calls"] == 1
    assert [s["id"] for s in p["skipped"]] == [dolap["ayakkabi"]]
    assert p["skipped"][0]["neden"]


def test_plan_cagri_yapmaz(dolap, db_path, monkeypatch):
    """plan() ücretsiz olmalı — sağlayıcıya dokunmamalı."""
    def patlasin(*a, **k):
        raise AssertionError("plan() sağlayıcıyı çağırdı — ücret riski")

    monkeypatch.setattr(vton, "get_provider", patlasin)
    render.plan([dolap["ust"], dolap["alt"]], db_path=db_path)


# --- render ve önbellek ---

def test_zincir_calisir_ve_onbellege_yazar(dolap, db_path):
    ids = [dolap["ust"], dolap["alt"]]
    sonuc = render.render_outfit(
        ids, provider=vton.MockProvider(), db_path=db_path)

    assert sonuc["status"] == "ok"
    assert sonuc["calls"] == 2
    assert render.cached(ids, db_path=db_path, provider_name="mock") is not None
    assert Image.open(sonuc["path"]).size == mannequin.MANNEQUIN_SIZE


def test_ikinci_kez_onbellekten_gelir_ve_ucret_yok(dolap, db_path):
    ids = [dolap["ust"], dolap["alt"]]
    render.render_outfit(ids, provider=vton.MockProvider(), db_path=db_path)

    def patlasin(*a, **k):
        raise AssertionError("önbellek varken sağlayıcı çağrıldı — para yanardı")

    sahte = vton.MockProvider()
    sahte.try_on = patlasin

    sonuc = render.render_outfit(ids, provider=sahte, db_path=db_path)
    assert sonuc["status"] == "cached"
    assert sonuc["calls"] == 0
    assert sonuc["cost_usd"] == 0


def test_onbellek_anahtari_siradan_bagimsiz(dolap, db_path):
    a = render.cache_key([dolap["ust"], dolap["alt"]], db_path=db_path)
    b = render.cache_key([dolap["alt"], dolap["ust"]], db_path=db_path)
    assert a == b, "aynı kombin iki kez üretilirse para iki kez gider"


def test_ara_dosyalar_temizlenir(dolap, db_path):
    render.render_outfit([dolap["ust"], dolap["alt"]],
                         provider=vton.MockProvider(), db_path=db_path)
    artik = list(render.RENDER_DIR.glob(".ara_*"))
    assert artik == [], f"ara dosyalar kaldı: {artik}"


def test_saglayici_patlarsa_temiz_hata(dolap, db_path):
    class Bozuk(vton.MockProvider):
        def try_on(self, *a, **k):
            raise RuntimeError("ağ gitti")

    sonuc = render.render_outfit([dolap["ust"]], provider=Bozuk(), db_path=db_path)

    assert sonuc["status"] == "failed"
    assert "ağ gitti" in sonuc["error"]
    assert render.cached([dolap["ust"]], db_path=db_path) is None, (
        "yarım kalan iş önbelleğe yazılmamalı"
    )
    assert list(render.RENDER_DIR.glob(".ara_*")) == []


def test_bos_kombin_reddedilir(dolap, db_path):
    assert render.render_outfit([], db_path=db_path)["status"] == "failed"


def test_manken_degisince_renderlar_silinir(dolap, db_path, tmp_path):
    ids = [dolap["ust"], dolap["alt"]]
    render.render_outfit(ids, provider=vton.MockProvider(), db_path=db_path)
    assert render.cached(ids, db_path=db_path, provider_name="mock") is not None

    yeni = tmp_path / "yeni_manken.png"
    Image.new("RGB", (200, 300), (90, 120, 170)).save(yeni)
    mannequin.from_photo(yeni, db_path=db_path)

    assert render.cached(ids, db_path=db_path, provider_name="mock") is None, (
        "eski render yeni mankene ait değil — sessizce yanlış görüntü gösterirdi"
    )


def test_URETILEN_dosya_ile_ARANAN_anahtar_AYNI(dolap, db_path, monkeypatch):
    """Para kaybettiren hata: render üretildi, ücretlendi, arayüz bulamadı.

    Varsayılan sağlayıcı fal→fashn çevrilince `render_outfit` dosyayı
    `..._fashn.png` yazmaya başladı ama çağıran taraf anahtarı hâlâ
    DEFAULT_RENDER_PROVIDER ile hesaplıyordu. İki ad ayrıştı.

    Bu test ayrışmayı yakalar: dosya hangi adla yazıldıysa, `cached_key` onu
    bulmak zorunda.
    """
    from pathlib import Path

    ids = [dolap["ust"], dolap["alt"]]
    sonuc = render.render_outfit(ids, provider=vton.MockProvider(), db_path=db_path)

    uretilen = Path(sonuc["path"]).stem
    bulunan = render.cached_key(ids, db_path=db_path, provider_name="mock")

    assert bulunan == uretilen, (
        f"üretilen {uretilen!r} ama aranan {bulunan!r} — ödenmiş render kaybolur"
    )


def test_ESKI_adla_uretilmis_render_KAYBOLMUYOR(dolap, db_path):
    """Varsayılan sağlayıcı değişince eski dosyalar bulunamaz olmamalı.

    `m1_1-2.png` fal döneminde ücretle üretildi. Artık varsayılan fashn olsa
    bile o dosya hâlâ o kombinin render'ı — bulunamazsa kullanıcı aynı
    kombine ikinci kez öder.
    """
    ids = [dolap["ust"], dolap["alt"]]
    eski = render.cache_path(ids, db_path=db_path)      # eksiz, varsayılan ad
    Image.new("RGB", (20, 30)).save(eski)

    assert render.cached_key(ids, db_path=db_path, provider_name="fashn") == eski.stem
    assert render.cached(ids, db_path=db_path, provider_name="fashn") == eski


def test_onbellek_anahtari_saglayiciyi_ayirir(dolap, db_path):
    """İki sağlayıcı aynı kombinde AYNI dosyaya yazmamalı.

    Yazsalardı fal'ın çıktısı gemini'ninkinin üstüne biner ve kullanıcı hangi
    modelin sonucuna baktığını bilemezdi — üstelik ikisi de ücretli.
    """
    ids = [dolap["ust"], dolap["alt"]]
    varsayilan = render.cache_key(ids, db_path=db_path)
    gemini = render.cache_key(ids, db_path=db_path, provider_name="gemini")

    assert varsayilan != gemini
    # Varsayılan sağlayıcının anahtarı DEĞİŞMEMELİ: değişse, ücretle üretilmiş
    # mevcut önbellek dosyaları bulunamaz olur ve aynı kombine ikinci kez ödenir.
    assert varsayilan == render.cache_key(
        ids, db_path=db_path, provider_name=render.DEFAULT_RENDER_PROVIDER)
