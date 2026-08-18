"""Çoklu manken (§28) — asıl iddia: GEÇİŞ HİÇBİR ŞEY SİLMEZ.

Bu dosyanın ağırlığı doğruluk değil **veri kaybı**. Bir mankenin katman seti
~30 kredi, renderları kıyafet başına ~4 kredi. Yanlış kapsamlı tek bir
`unlink()` bunu sessizce yok eder ve hiçbir şey hata vermez — kullanıcı sadece
bir gün "katmanlarım nerede" der.

Bu yüzden testlerin çoğu "X çalışıyor mu" değil **"X çalışırken Y'ye
dokunmadı mı"** diye soruyor. Projenin en pahalı hata sınıfı bu (§6.1 #8, #13,
§27.1-B: aynı hata üç kez tekrarladı).
"""
from __future__ import annotations

import sqlite3

import pytest
from PIL import Image

from db import connect, init_db, insert_garment
from wardrobe import edits, layers, mannequin, render


def _foto(tmp_path, ad="m.jpg", renk=(120, 130, 190)) -> str:
    """Manken fotoğrafı yerine geçecek sade bir görsel."""
    yol = tmp_path / ad
    img = Image.new("RGB", (900, 1200), (215, 215, 218))
    img.paste(Image.new("RGB", (300, 500), renk), (300, 350))
    img.save(yol, "JPEG", quality=92)
    return str(yol)


def _katman_yaz(garment_id: int, mannequin_id: int, db_path, layer_dir) -> dict:
    """Diskte GERÇEK dosyası olan, DB'de 'ready' bir katman kurar.

    Dosyayı da yazmak şart: testlerin ölçtüğü şey satırın değil DOSYANIN
    hayatta kalması. Sadece satıra bakan bir test, dosyaları silen bir hatayı
    kaçırırdı.
    """
    png = layer_dir / f"g{garment_id}_m{mannequin_id}.png"
    ham = layer_dir / f"g{garment_id}_m{mannequin_id}_raw.png"
    Image.new("RGBA", (40, 40), (200, 40, 45, 255)).save(png)
    Image.new("RGB", (40, 40), (200, 40, 45)).save(ham)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO layers (garment_id, mannequin_id, png_path, z_index, "
            "status) VALUES (?, ?, ?, 30, 'ready')",
            (garment_id, mannequin_id, str(png)),
        )
    return {"png": png, "raw": ham}


@pytest.fixture
def iki_manken(tmp_path, db_path, monkeypatch):
    """İki manken, ikisinin de katmanı ve render'ı olan bir kurulum."""
    layer_dir = tmp_path / "layers"
    layer_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("config.LAYER_DIR", layer_dir)
    monkeypatch.setattr("wardrobe.layers.LAYER_DIR", layer_dir)

    gid = insert_garment({"category": "ust", "raw_path": "a.jpg"}, db_path=db_path)

    # 1: varsayılan 'base' satırı — mevcut kurulumun aynısı
    mannequin.from_photo(_foto(tmp_path, "bir.jpg"), db_path=db_path)
    m1 = mannequin.active_id(db_path)
    d1 = _katman_yaz(gid, m1, db_path, layer_dir)

    # 2: yeni manken. from_photo(name=...) yolu — ekleme, ezme DEĞİL.
    mannequin.from_photo(_foto(tmp_path, "iki.jpg", (190, 130, 120)),
                         db_path=db_path, name="İkinci")
    m2 = mannequin.active_id(db_path)
    d2 = _katman_yaz(gid, m2, db_path, layer_dir)

    r1 = render.RENDER_DIR / f"m{m1}_{gid}.png"
    r2 = render.RENDER_DIR / f"m{m2}_{gid}.png"
    for r in (r1, r2):
        Image.new("RGB", (20, 20), (10, 10, 10)).save(r)

    return {"gid": gid, "m1": m1, "m2": m2, "d1": d1, "d2": d2,
            "r1": r1, "r2": r2, "db": db_path, "layer_dir": layer_dir}


# --- §28.5 kabul ölçütü 1: geçiş hiçbir katmanı silmiyor ---

def test_gecis_hicbir_katmani_silmiyor(iki_manken):
    """ASIL İDDİA. İki manken arasında gidip gelmek bedava ve kayıpsız olmalı.

    Bu tutmazsa özelliğin varlık sebebi kalmıyor: her geçiş katmanları
    geçersizleseydi manken değiştirmek ~30 kredilik bir işlem olurdu ve kimse
    ikinci mankeni kullanmazdı.
    """
    v = iki_manken
    for _ in range(3):                       # ileri geri, birden çok kez
        mannequin.set_active(v["m1"], v["db"])
        mannequin.set_active(v["m2"], v["db"])

    for d in (v["d1"], v["d2"]):
        assert d["png"].is_file(), "katman dosyası geçişte silindi"
        assert d["raw"].is_file(), "ham çıktı geçişte silindi — reextract ölür"
    assert v["r1"].is_file() and v["r2"].is_file(), "render geçişte silindi"

    with connect(v["db"]) as conn:
        durumlar = [r["status"] for r in conn.execute(
            "SELECT status FROM layers ORDER BY mannequin_id")]
    assert durumlar == ["ready", "ready"], "geçiş katmanları geçersizledi"


def test_gecis_dogru_katman_setini_gosteriyor(iki_manken):
    """Geçiş sessizce ETKİSİZ de olmamalı — aktif mankenin katmanı gelmeli."""
    v = iki_manken
    mannequin.set_active(v["m1"], v["db"])
    assert layers._base_mannequin_id(v["db"]) == v["m1"]
    satir = layers._get_layer(v["gid"], v["m1"], v["db"])
    assert satir["png_path"] == str(v["d1"]["png"])

    mannequin.set_active(v["m2"], v["db"])
    assert layers._base_mannequin_id(v["db"]) == v["m2"]
    satir = layers._get_layer(v["gid"], v["m2"], v["db"])
    assert satir["png_path"] == str(v["d2"]["png"])


def test_yeni_manken_eklemek_eskiyi_bozmuyor(tmp_path, db_path, monkeypatch):
    """§28.4 #2'nin birinci yarısı: EKLEMEK ezmek değil.

    Eski `_save` her çağrıda `WHERE name='base'` satırının üstüne yazıyordu —
    yani "yeni manken" demek "eskisini yok et" demekti.
    """
    layer_dir = tmp_path / "layers"
    layer_dir.mkdir(exist_ok=True)
    monkeypatch.setattr("config.LAYER_DIR", layer_dir)

    gid = insert_garment({"category": "ust", "raw_path": "a.jpg"}, db_path=db_path)
    mannequin.from_photo(_foto(tmp_path, "bir.jpg"), db_path=db_path)
    m1 = mannequin.active_id(db_path)
    eski_yol = mannequin.active(db_path)["image_path"]
    d1 = _katman_yaz(gid, m1, db_path, layer_dir)

    yeni = mannequin.add_from_photo(_foto(tmp_path, "iki.jpg"), db_path=db_path)

    assert yeni["created"] is True
    assert yeni["mannequin_id"] != m1
    assert yeni["invalidated_layers"] == 0
    assert yeni["image_path"] != eski_yol, "yeni manken eskisinin dosyasını ezdi"
    assert d1["png"].is_file(), "yeni manken eklemek eski katmanı sildi"

    with connect(db_path) as conn:
        satir = conn.execute("SELECT status FROM layers WHERE mannequin_id = ?",
                             (m1,)).fetchone()
    assert satir["status"] == "ready"
    assert len(mannequin.list_all(db_path)) == 2


def test_fotograf_degistirmek_yalnizca_o_mankeni_vuruyor(iki_manken):
    """§28.4 #2'nin ikinci yarısı: DEĞİŞTİRMEK ezmek DEMEK — ama tek mankeni.

    Aktif mankenin fotoğrafı değişince onun katmanları geçersiz (doğru), ama
    diğer mankeninkilere dokunulmamalı: onlar hâlâ kendi fotoğraflarına ait.
    """
    v = iki_manken
    mannequin.set_active(v["m2"], v["db"])
    sonuc = mannequin.from_photo(_foto(v["layer_dir"].parent, "yeni.jpg",
                                       (90, 200, 120)), db_path=v["db"])

    assert sonuc["created"] is False
    assert sonuc["invalidated_layers"] == 1

    with connect(v["db"]) as conn:
        durum = {r["mannequin_id"]: r["status"] for r in conn.execute(
            "SELECT mannequin_id, status FROM layers")}
    assert durum[v["m2"]] == "stale", "fotoğraf değişti ama katman geçersiz olmadı"
    assert durum[v["m1"]] == "ready", "başka mankenin katmanı geçersiz kılındı"

    assert not v["d2"]["png"].is_file()      # geçersiz olan silindi (doğru)
    assert v["d1"]["png"].is_file(), "başka mankenin katman DOSYASI silindi"
    assert v["r1"].is_file(), "başka mankenin ÜCRETLİ render'ı silindi"
    assert not v["r2"].is_file()             # kendi render'ı geçersiz (doğru)


# --- Kapsam: silme fonksiyonları nereye kadar uzanıyor ---

def test_clear_cache_yalnizca_verilen_mankeni_siliyor(iki_manken):
    """`clear_cache()` kapsamsızken ilgisiz mankenin renderlarını yiyordu."""
    v = iki_manken
    render.clear_cache(v["m2"])
    assert v["r1"].is_file(), "clear_cache(m2) m1'in render'ını sildi"
    assert not v["r2"].is_file()


def test_clear_cache_kapsamsiz_cagri_hepsini_siliyor(iki_manken):
    """Kapsamsız çağrı hâlâ mümkün olmalı (bakım/test kurulumu) — ama bilinçli."""
    v = iki_manken
    render.clear_cache()
    assert not v["r1"].is_file() and not v["r2"].is_file()


def test_duzenleme_zinciri_kapsami(iki_manken):
    """Düzenleme adımlarının her biri ayrı bir ödeme (2 kredi) — kapsam şart."""
    v = iki_manken
    for mid in (v["m1"], v["m2"]):
        (render.RENDER_DIR / f"m{mid}_{v['gid']}.edits.json").write_text(
            '{"steps": [], "selected": 0}', encoding="utf-8")
        Image.new("RGB", (10, 10)).save(
            render.RENDER_DIR / f"m{mid}_{v['gid']}_e1.png")

    edits.clear_all(v["m2"])

    assert (render.RENDER_DIR / f"m{v['m1']}_{v['gid']}.edits.json").is_file()
    assert (render.RENDER_DIR / f"m{v['m1']}_{v['gid']}_e1.png").is_file()
    assert not (render.RENDER_DIR / f"m{v['m2']}_{v['gid']}_e1.png").is_file()


# --- Anahtarlar ve yollar manken başına ayrılıyor mu ---

def test_render_anahtari_mankene_gore_degisiyor(iki_manken):
    """Anahtar ayrılmazsa iki mankenin render'ı AYNI dosyaya düşer.

    Sonuç: kullanıcı 2. mankende "Gerçekçi Göster"e basar, 1. mankenin ücretli
    render'ını görür — ve bunu fark etmesi neredeyse imkânsızdır.
    """
    v = iki_manken
    mannequin.set_active(v["m1"], v["db"])
    a1 = render.cache_key([v["gid"]], v["db"])
    mannequin.set_active(v["m2"], v["db"])
    a2 = render.cache_key([v["gid"]], v["db"])
    assert a1 != a2
    assert a1.startswith(f"m{v['m1']}_") and a2.startswith(f"m{v['m2']}_")


def test_gosterim_basei_manken_basina_ayri(iki_manken):
    """İki manken → iki ayrı gösterim base'i. Aynı ada düşerlerse zemin
    bir mankenin, katmanlar diğerinin olur (§7.5'in çöküş biçimi)."""
    v = iki_manken
    y1 = mannequin.display_base_path(mannequin_id=v["m1"], db_path=v["db"])
    y2 = mannequin.display_base_path(mannequin_id=v["m2"], db_path=v["db"])
    assert y1 != y2

    mannequin.set_active(v["m1"], v["db"])
    assert mannequin.display_base_path(db_path=v["db"]) == y1
    mannequin.set_active(v["m2"], v["db"])
    assert mannequin.display_base_path(db_path=v["db"]) == y2


def test_ilk_manken_eski_dosya_adini_koruyor(tmp_path, db_path):
    """§28.4 #4: mevcut `base.png` yeniden adlandırılmamalı.

    Adlandırma kuralını topluca değiştirmek, diskteki ücretli veriyi
    "kayıp" yapmanın en sessiz yoludur.
    """
    mannequin.from_photo(_foto(tmp_path), db_path=db_path)
    assert mannequin.active(db_path)["image_path"].endswith("base.png")
    assert mannequin.display_base_path(db_path=db_path).name == "base_display.png"


def test_yeni_manken_yollari_izole_dizinde(tmp_path, db_path):
    """§28.4 #5: yeni dosya deseni conftest'in yönlendirmesini delmemeli.

    Delerse testler kullanıcının GERÇEK data/ klasörüne yazar — bu projede
    aynı hata üç kez oldu ve her seferinde ücretli veri kaybettirdi.
    """
    bilgi = mannequin.add_from_photo(_foto(tmp_path), db_path=db_path)
    assert str(tmp_path) in bilgi["image_path"], (
        "yeni manken gerçek data/ klasörüne yazıldı")


# --- Silme ---

def test_son_manken_silinemez(tmp_path, db_path):
    """Silinirse dolap zeminsiz kalır; sistem o duruma hiç girmemeli."""
    mannequin.from_photo(_foto(tmp_path), db_path=db_path)
    with pytest.raises(ValueError, match="son manken"):
        mannequin.delete(mannequin.active_id(db_path), db_path=db_path)


def test_silme_kendi_verisini_siler_digerine_dokunmaz(iki_manken):
    v = iki_manken
    sonuc = mannequin.delete(v["m2"], db_path=v["db"])

    assert sonuc["layers"] == 1                # onay ekranında bu sayı yazıyor
    assert not v["d2"]["png"].is_file()
    assert not v["r2"].is_file()
    assert v["d1"]["png"].is_file(), "silme başka mankenin katmanını yedi"
    assert v["r1"].is_file(), "silme başka mankenin render'ını yedi"

    kalan = mannequin.list_all(v["db"])
    assert [m["id"] for m in kalan] == [v["m1"]]
    assert sonuc["active_id"] == v["m1"], "aktif manken silindi ama yerine geçen yok"


def test_aktif_silinince_baskasi_aktif_oluyor(iki_manken):
    """'Aktif manken yok' ara durumu hiç oluşmamalı."""
    v = iki_manken
    assert mannequin.active_id(v["db"]) == v["m2"]
    mannequin.delete(v["m2"], db_path=v["db"])
    assert mannequin.active_id(v["db"]) == v["m1"]
    assert mannequin.active(v["db"])["is_active"] == 1


def test_usage_silinecekleri_dogru_sayiyor(iki_manken):
    """Onay ekranındaki sayı yanlışsa onay da yanlış (§28.4 #3).

    Katman bindirmesi (`_katman.png`) sayılmamalı: ÜCRETSİZ üretiliyor, yani
    kaybı para kaybı değil. Sayı "ne kadar para gidiyor"u anlatmalı.
    """
    v = iki_manken
    Image.new("RGB", (10, 10)).save(
        render.RENDER_DIR / f"m{v['m1']}_{v['gid']}_e1.png")
    Image.new("RGB", (10, 10)).save(
        render.RENDER_DIR / f"m{v['m1']}_{v['gid']}_katman.png")

    k = mannequin.usage(v["m1"], v["db"])
    assert k == {"layers": 1, "renders": 1, "edits": 1}


# --- Migration: var olan veritabanı ---

def test_eski_veritabani_migrationdan_sonra_calisiyor(tmp_path):
    """§28.4 #4: `is_active` sonradan eklendi, varsayılanı 0.

    Migration'dan sonra hiçbir manken aktif olmazsa `get_base()` None döner ve
    ücretle üretilmiş 11 katman bir anda erişilemez görünür. Dosyalar yerinde
    olurdu; kaybolan sadece "hangisi aktif" bilgisi — ama sonuç aynı.
    """
    yol = tmp_path / "eski.db"
    conn = sqlite3.connect(yol)
    conn.executescript(
        "CREATE TABLE mannequins (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'base', "
        "image_path TEXT NOT NULL DEFAULT '', "
        "params_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')));"
        "INSERT INTO mannequins (name, kind, image_path) "
        "VALUES ('base', 'photo', 'C:/x/base.png');"
    )
    conn.commit()
    conn.close()

    init_db(yol)

    row = mannequin.active(db_path=yol)
    assert row is not None and row["name"] == "base"
    assert row["is_active"] == 1
    assert mannequin.active_id(db_path=yol) == 1


def test_tek_aktif_manken_kaliyor(iki_manken):
    """İki satır birden aktif kalırsa 'aktif manken' tanımsızlaşır."""
    v = iki_manken
    with connect(v["db"]) as conn:
        conn.execute("UPDATE mannequins SET is_active = 1")
    init_db(v["db"])

    with connect(v["db"]) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM mannequins WHERE is_active = 1"
        ).fetchone()["n"]
    assert n == 1


def test_ad_cakismasi_anlasilir_hata_veriyor(tmp_path, db_path):
    """`name` UNIQUE. Ham sqlite hatası kullanıcıya hiçbir şey anlatmaz."""
    mannequin.from_photo(_foto(tmp_path), db_path=db_path)
    mannequin.add_from_photo(_foto(tmp_path), name="Yaz", db_path=db_path)
    with pytest.raises(ValueError, match="zaten var"):
        mannequin.add_from_photo(_foto(tmp_path), name="Yaz", db_path=db_path)


# --- HTTP katmanı ---
#
# Arayüzün gördüğü şey bu. Modül testleri geçse bile uç nokta yanlış mankene
# bakıyorsa geçiş görünürde çalışır, gerçekte hiçbir şey değişmez.

@pytest.fixture
def client(db_path, monkeypatch):
    from fastapi.testclient import TestClient

    from web.app import app
    monkeypatch.setattr("db.DB_PATH", db_path)
    return TestClient(app)


def test_api_mankenleri_listeliyor(client, iki_manken):
    v = iki_manken
    d = client.get("/api/mannequins").json()

    assert d["active_id"] == v["m2"]
    assert [m["id"] for m in d["mannequins"]] == [v["m1"], v["m2"]]
    assert [m["layer_count"] for m in d["mannequins"]] == [1, 1]
    # Silme onayında gösterilecek sayılar cevapta gelmeli — istemci kendi
    # saymaya kalkarsa iki yer birbirinden habersiz kayar (§14 ilkesi).
    assert d["mannequins"][0]["usage"]["renders"] == 1


def test_api_gecis_gosterilen_katman_setini_degistiriyor(client, iki_manken):
    """Uç nokta hâlâ `name='base'`e bakıyorsa bu test kırılır — geçiş
    görünürde çalışıp gerçekte etkisiz kalırdı."""
    v = iki_manken
    client.post(f"/api/mannequins/{v['m1']}/aktif")

    d = client.get("/api/wardrobe").json()
    assert d["mannequin"]["id"] == v["m1"]
    assert d["garments"][0]["layer_ready"] is True

    # m1'in katmanını sil: aynı kıyafet m2'de hâlâ hazır olmalı, m1'de değil.
    v["d1"]["png"].unlink()
    with connect(v["db"]) as conn:
        conn.execute("UPDATE layers SET status='stale' WHERE mannequin_id=?",
                     (v["m1"],))

    assert client.get("/api/wardrobe").json()["garments"][0]["layer_ready"] is False
    client.post(f"/api/mannequins/{v['m2']}/aktif")
    assert client.get("/api/wardrobe").json()["garments"][0]["layer_ready"] is True


def test_api_son_manken_silinmiyor(client, tmp_path, db_path):
    mannequin.from_photo(_foto(tmp_path), db_path=db_path)
    mid = mannequin.active_id(db_path)
    cevap = client.delete(f"/api/mannequins/{mid}")
    assert cevap.status_code == 400
    assert mannequin.active(db_path) is not None


def test_api_yeni_manken_ucretsiz_ve_katmansiz(client, tmp_path, db_path,
                                               monkeypatch):
    """Manken eklemek katman ÜRETMEMELİ. Üretseydi 'ekle' düğmesi sessizce
    ~30 kredilik bir işlem olurdu."""
    from wardrobe import layers as layers_mod

    def patlar(*a, **k):                     # ücretli yol çağrılırsa test kırılsın
        raise AssertionError("manken eklerken katman üretilmeye çalışıldı")

    monkeypatch.setattr(layers_mod, "build_layer", patlar)
    mannequin.from_photo(_foto(tmp_path), db_path=db_path)

    foto = tmp_path / "yeni_manken.png"
    Image.new("RGB", (600, 900), (200, 200, 205)).save(foto)
    with foto.open("rb") as f:
        cevap = client.post("/api/mannequins",
                            files={"file": ("yeni_manken.png", f, "image/png")},
                            data={"name": "Kış"})

    assert cevap.status_code == 201
    assert cevap.json()["layer_count"] == 0
    assert cevap.json()["name"] == "Kış"
    assert len(mannequin.list_all(db_path)) == 2
