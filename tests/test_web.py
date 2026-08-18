"""Faz 2 arayüzünün sunucusu.

Buradaki testler HTTP katmanını doğruluyor: hangi veri dışarı veriliyor, hangi
dosya servis ediliyor, hazır olmayan katman ne yapıyor. Tarayıcı tarafındaki
bindirme (CSS z-index) test edilmiyor — asıl kural olan z ve slots zaten
config.py'de ve orada test ediliyor; arayüz onları sunucudan alıyor, yeniden
tanımlamıyor.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from config import CATEGORIES
from db import connect, insert_garment
from wardrobe import layers, mannequin, vton
from web.app import app


@pytest.fixture
def client(db_path, monkeypatch):
    """Sunucu varsayılan DB yolunu kullanır; testte o yolu izole DB'ye çevir.

    Tek tek fonksiyonları sarmalamak yerine yolu değiştiriyoruz — böylece
    sunucunun gerçekten varsayılan yoldan okuduğu da doğrulanmış oluyor.
    """
    monkeypatch.setattr("db.DB_PATH", db_path)
    return TestClient(app)


def _yukle(client, tmp_path, **form):
    """Yükleme uç noktasına bir görsel gönderir; ÜCRETLİ adımı sahteler.

    add_garment ucuz ama build_layer değil. Testin ilgilendiği şey formdaki
    hizalama alanlarının hatta ulaşıp ulaşmadığı, o yüzden ücretli kısım
    kesiliyor — aksi halde bu test her çalıştığında para yakardı.
    """
    foto = tmp_path / "yukle.png"
    arr = np.full((300, 220, 3), 250, dtype=np.uint8)
    arr[80:230, 60:170] = (200, 40, 45)
    Image.fromarray(arr).save(foto)

    with foto.open("rb") as f:
        cevap = client.post("/api/garments",
                            files={"file": ("yukle.png", f, "image/png")},
                            data=form)
    return cevap


def test_hizalama_alanlari_ingest_e_ulasiyor(client, tmp_path, monkeypatch):
    """Panelin gönderdiği değerler kırpmadan ÖNCE uygulanmalı.

    Ulaşmazsa hata sessiz olur: kullanıcı kıyafeti şablona oturtur, sunucu
    hizalanmamış fotoğrafı kırpar ve kimse farkı görmez.
    """
    import threading

    from wardrobe import ingest, layers as layers_mod

    gorulen = {}
    gercek = ingest.add_garment

    def yakala(path, **kw):
        gorulen.update(kw)
        return gercek(path, use_vlm=False, **{k: v for k, v in kw.items()
                                              if k != "use_vlm"})

    monkeypatch.setattr(ingest, "add_garment", yakala)
    monkeypatch.setattr(layers_mod, "build_layer",
                        lambda gid, **k: {"status": "ready", "garment_id": gid})

    cevap = _yukle(client, tmp_path, shape="tisort",
                   dx="0.1", dy="-0.05", scale="1.25", rotate="6")
    assert cevap.status_code == 202

    for t in threading.enumerate():        # arka plan işi bitsin
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=10)

    assert gorulen["shape"] == "tisort"
    assert gorulen["align"] == pytest.approx(
        {"dx": 0.1, "dy": -0.05, "scale": 1.25, "rotate": 6.0})


def test_hizalama_sinirlari_sunucuda_kirpiliyor(client, tmp_path, monkeypatch):
    """Değerler istemciden geliyor — arayüzün doğru davranmasına güvenilmiyor.

    scale=0 afin matrisi tekilleştirir ve isteği 500 ile düşürürdü.
    """
    import threading

    from wardrobe import ingest, layers as layers_mod

    gorulen = {}
    gercek = ingest.add_garment

    def yakala(path, **kw):
        gorulen.update(kw)
        return gercek(path, use_vlm=False, **{k: v for k, v in kw.items()
                                              if k != "use_vlm"})

    monkeypatch.setattr(ingest, "add_garment", yakala)
    monkeypatch.setattr(layers_mod, "build_layer",
                        lambda gid, **k: {"status": "ready", "garment_id": gid})

    assert _yukle(client, tmp_path, dx="99", dy="-99",
                  scale="0", rotate="720").status_code == 202

    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(timeout=10)

    a = gorulen["align"]
    assert 0.4 <= a["scale"] <= 2.5
    assert abs(a["dx"]) <= 0.45 and abs(a["dy"]) <= 0.45
    assert abs(a["rotate"]) <= 30


def test_katman_surum_damgasi_veriliyor(client, dolu_dolap, db_path):
    """Katman yeniden üretilince tarayıcı ESKİSİNİ göstermemeli.

    Katmanlar sık yeniden üretiliyor (--reextract bedava, sağlayıcı değişimi,
    filtre ayarı). URL sabit kalırsa tarayıcı önbellekten eski görseli veriyor
    ve kullanıcı "düzeltme işe yaramamış" sanıyor — gerçekten yaşandı.
    """
    veri = client.get("/api/wardrobe").json()

    assert "base_rev" in veri
    for g in veri["garments"]:
        assert "layer_rev" in g and "cutout_rev" in g
        if g["layer_ready"]:
            assert g["layer_rev"] > 0, "hazır katmanın sürüm damgası yok"


def test_surum_damgasi_dosya_degisince_degisiyor(client, dolu_dolap, db_path):
    """Damga sabit kalsaydı işe yaramazdı; dosya değişince artmalı."""
    import os
    import time

    from wardrobe import layers as layers_mod

    once = {g["id"]: g["layer_rev"] for g in client.get("/api/wardrobe").json()["garments"]}

    gid = dolu_dolap[0]
    with connect(db_path) as conn:
        yol = conn.execute(
            "SELECT png_path FROM layers WHERE garment_id = ?", (gid,)
        ).fetchone()["png_path"]
    yeni_zaman = time.time() + 10
    os.utime(yol, (yeni_zaman, yeni_zaman))

    sonra = {g["id"]: g["layer_rev"] for g in client.get("/api/wardrobe").json()["garments"]}
    assert sonra[gid] > once[gid]


def test_arayuz_dosyalari_bayatlamiyor(client):
    """app.js önbellekten çalışırsa kod güncellemesi hiç devreye girmiyor.

    Gerçekten yaşandı: görsellerin bayatlamasını düzelten kod yazıldı, ama
    tarayıcı eski app.js'i çalıştırdığı için düzeltme görünmedi.
    """
    for yol in ("/", "/app.js", "/style.css"):
        cevap = client.get(yol)
        assert cevap.status_code == 200, yol
        assert "no-cache" in cevap.headers.get("cache-control", ""), yol


def test_index_varlik_urlerine_surum_damgasi_basiyor(client):
    """no-cache TEK BAŞINA yetmiyor.

    Tarayıcı dosyayı başlık eklenmeden ÖNCE önbelleğe aldıysa eski politikaya
    uymaya devam ediyor — zorla yenilemek bile yetmedi. URL'nin kendisi
    değişince sorun tanım gereği ortadan kalkıyor.
    """
    html = client.get("/").text

    assert "app.js?v=" in html
    assert "style.css?v=" in html
    # Damga gerçek olmalı, sabit 0 değil.
    import re
    for m in re.findall(r"\.(?:js|css)\?v=(\d+)", html):
        assert int(m) > 0


def test_sablon_uc_noktasi_hizalama_sinirlarini_veriyor(client):
    """Sınır iki yerde tanımlanmamalı; istemci sunucudan alıyor (§14 ilkesi)."""
    v = client.get("/api/templates").json()

    assert "align_limits" in v
    assert v["align_limits"]["scale"] == [0.4, 2.5]


@pytest.fixture
def dolu_dolap(db_path, tmp_path):
    """İki kıyafet: biri katmanı hazır üst, biri katmanı hazır alt."""
    from wardrobe.ingest import add_garment

    mannequin.placeholder(db_path=db_path)
    sonuc = []
    for renk, ad in (((200, 40, 45), "ust.png"), ((40, 60, 200), "alt.png")):
        foto = tmp_path / ad
        arr = np.full((300, 220, 3), 250, dtype=np.uint8)
        arr[80:230, 60:170] = renk
        Image.fromarray(arr).save(foto)
        sonuc.append(add_garment(foto, use_vlm=False, db_path=db_path)["id"])

    with connect(db_path) as conn:
        conn.execute("UPDATE garments SET category='ust' WHERE id=?", (sonuc[0],))
        conn.execute("UPDATE garments SET category='alt' WHERE id=?", (sonuc[1],))

    for gid in sonuc:
        layers.build_layer(gid, provider=vton.MockProvider(), db_path=db_path)
    return sonuc


def test_dolap_kategori_kurallarini_da_verir(client, dolu_dolap):
    """Çakışma kuralı istemcide TANIMLANMAMALI — sunucudan gelmeli."""
    veri = client.get("/api/wardrobe").json()

    assert set(veri["categories"]) == set(CATEGORIES)
    assert veri["categories"]["elbise"]["slots"] == ["ust", "alt"], (
        "elbise iki slot kaplamalı; arayüzün tişört+pantolonu düşürmesi buna bağlı"
    )
    assert veri["categories"]["ust"]["z"] > veri["categories"]["alt"]["z"], (
        "üst giyim alt giyimden sonra çizilmeli"
    )


def test_dolap_katman_durumunu_bildirir(client, dolu_dolap, db_path):
    veri = client.get("/api/wardrobe").json()
    assert {g["id"] for g in veri["garments"]} == set(dolu_dolap)
    assert all(g["layer_ready"] for g in veri["garments"])


def test_katmani_olmayan_kiyafet_gizlenmez_isaretlenir(client, dolu_dolap, db_path):
    """Sessizce kaybolmak yerine 'katmanı yok' de.

    Kullanıcı kıyafeti eklediğini biliyor; listeden düşerse hata sanar.
    """
    with connect(db_path) as conn:
        conn.execute("UPDATE layers SET status='failed' WHERE garment_id=?",
                     (dolu_dolap[0],))

    veri = client.get("/api/wardrobe").json()
    hedef = next(g for g in veri["garments"] if g["id"] == dolu_dolap[0])

    assert hedef["layer_ready"] is False
    assert hedef["layer_status"] == "failed"
    assert client.get(f"/api/layer/{dolu_dolap[0]}.png").status_code == 404


def test_katman_ve_kirpik_gorsel_servis_edilir(client, dolu_dolap):
    for gid in dolu_dolap:
        for yol in (f"/api/layer/{gid}.png", f"/api/cutout/{gid}.png"):
            cevap = client.get(yol)
            assert cevap.status_code == 200, yol
            assert cevap.headers["content-type"] == "image/png"


def test_base_gosterim_baseidir(client, dolu_dolap):
    """Bindirmenin zemini çıkarım base'i DEĞİL, nötrlenmiş gösterim base'i."""
    cevap = client.get("/api/base.png")
    assert cevap.status_code == 200
    assert mannequin.display_base_path().is_file()


def test_kombin_kaydedilir_ve_okunur(client, dolu_dolap):
    cevap = client.post("/api/outfits",
                        json={"name": "yazlık", "garment_ids": dolu_dolap})
    assert cevap.status_code == 201

    kayitlar = client.get("/api/outfits").json()
    assert len(kayitlar) == 1
    assert kayitlar[0]["name"] == "yazlık"
    assert sorted(kayitlar[0]["garment_ids"]) == sorted(dolu_dolap)


def test_bos_kombin_reddedilir(client, dolu_dolap):
    assert client.post("/api/outfits", json={"garment_ids": []}).status_code == 400


def test_kombin_silinir(client, dolu_dolap):
    oid = client.post("/api/outfits", json={"garment_ids": dolu_dolap}).json()["id"]
    assert client.delete(f"/api/outfits/{oid}").status_code == 200
    assert client.get("/api/outfits").json() == []
    assert client.delete(f"/api/outfits/{oid}").status_code == 404


def test_olmayan_kiyafet_404(client, dolu_dolap):
    assert client.get("/api/layer/9999.png").status_code == 404
    assert client.get("/api/cutout/9999.png").status_code == 404


# --- Kıyafet yükleme (CLI'sız akış) ---

def _isi_bekle(client, job_id, saniye=25):
    import time
    son = time.time() + saniye
    while time.time() < son:
        j = client.get(f"/api/render/job/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.1)
    raise AssertionError(f"iş bitmedi: {j}")


def _foto(tmp_path, renk, ad="y.png"):
    yol = tmp_path / ad
    arr = np.full((300, 220, 3), 250, dtype=np.uint8)
    arr[80:230, 60:170] = renk
    Image.fromarray(arr).save(yol)
    return yol


def test_desteklenmeyen_dosya_reddedilir(client, db_path, tmp_path):
    kotu = tmp_path / "notlar.txt"
    kotu.write_text("kıyafet değil")
    with kotu.open("rb") as f:
        cevap = client.post("/api/garments", files={"file": ("notlar.txt", f, "text/plain")})
    assert cevap.status_code == 400


def test_yukleme_kiyafeti_ekler_ve_katmani_uretir(client, db_path, tmp_path, monkeypatch):
    monkeypatch.setenv("VTON_PROVIDER", "mock")
    mannequin.placeholder(db_path=db_path)

    foto = _foto(tmp_path, (200, 40, 45))          # base placeholder teni ile kontrastlı
    with foto.open("rb") as f:
        cevap = client.post("/api/garments", files={"file": ("kirmizi.png", f, "image/png")})
    assert cevap.status_code == 202

    j = _isi_bekle(client, cevap.json()["job_id"])
    assert j["status"] == "done", j
    assert j["layer_built"] is True
    assert j["garment_id"] in {g["id"] for g in client.get("/api/wardrobe").json()["garments"]}


def test_kor_noktada_URETILIYOR_ama_uyari_geciyor(client, db_path, tmp_path,
                                                  monkeypatch):
    """Aynı renkte katman ÜRETİLİR; zayıf sinyal yalnızca not olarak geçer.

    ⚠ BU TEST BİR DAVRANIŞ DEĞİŞİKLİĞİNİ KİLİTLİYOR ve eski hâlinin tersini
    söylüyor. Eskiden burası "kör noktada ücretli çağrı YAPILMAZ" diyordu ve
    gerekçesi ölçülmüştü — ama fal/v1.6 ile: base'in siyah şortuyla aynı
    renkteki şortun katmanı %0.6 kaplamayla gerçekten kullanılamaz çıkmıştı.

    tryon-max'te aynı bant çalışıyor. Ölçüldü (4 kredi): mankenin kıyafetine
    uzaklığı **1.0** olan lacivert tişört üretildi, kaplama tipik değerin
    ~%65'i ve görsel olarak temiz. Yani eski kapı, çalışan bir işlemi yanlış
    bir tahminle engelliyordu.

    §25.5'in dersi: bir ölçümün geçerliliği, ölçüldüğü koşulların hâlâ geçerli
    olmasına bağlı. Sağlayıcı değişti, eşik de değişmeli.
    """
    cagrildi = {}

    def sahte_build(gid, **k):
        cagrildi["gid"] = gid
        return {"status": "ready", "garment_id": gid}

    monkeypatch.setattr("wardrobe.layers.build_layer", sahte_build)

    # base'i tek renk yap; aynı renkte kıyafet yükle
    base_foto = tmp_path / "base.png"
    Image.new("RGB", (400, 600), (70, 90, 120)).save(base_foto)
    mannequin.from_photo(base_foto, db_path=db_path)

    foto = _foto(tmp_path, (72, 92, 122), "ayni.png")
    with foto.open("rb") as f:
        cevap = client.post("/api/garments", files={"file": ("ayni.png", f, "image/png")})

    j = _isi_bekle(client, cevap.json()["job_id"])
    assert j["status"] == "done", j
    assert cagrildi, "zayıf sinyal üretimi engelledi — eski davranışa dönülmüş"
    assert j["layer_built"] is True
    assert j["conflict"]["ok"] is True
    assert j["conflict"]["level"] == "zayıf"
    assert j["note"], "kullanıcıya sinyalin zayıf olduğu söylenmeli"


def test_kiyafet_silinir(client, dolu_dolap):
    gid = dolu_dolap[0]
    assert client.delete(f"/api/garments/{gid}").status_code == 200
    assert gid not in {g["id"] for g in client.get("/api/wardrobe").json()["garments"]}
    assert client.delete(f"/api/garments/{gid}").status_code == 404


# --- Tek kıyafet: ham VTON çıktısı (bindirme YOK) ---

def test_ham_cikti_ucnoktasi_servis_ediyor(client, db_path, tmp_path, monkeypatch):
    """Tek kıyafet seçiliyken bindirmeye gerek yok — ham çıktı zaten diskte.

    Bindirmenin varlık sebebi birden çok kıyafeti birleştirebilmek. Tek parçada
    hiçbir şey birleştirmiyor, yalnızca ÇIKARIM KUSURLARINI taşıyor. Ölçüldü
    (manken 2, lacivert tişört): ham çıktı temiz, katmanın **%44.8'i** base'in
    kendi tişörtüydü.

    Görüntü ücretsiz: `build_layer` ham çıktıyı `--reextract` için zaten
    saklıyor — ücreti ödenmiş bir sonucu göstermiyorduk sadece.
    """
    from wardrobe import layers as layers_mod
    from wardrobe import mannequin as man

    foto = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 160)).save(foto)
    man.from_photo(foto, db_path=db_path)
    mid = man.active_id(db_path)

    gid = insert_garment({"category": "ust", "raw_path": "a.jpg"}, db_path=db_path)
    Image.new("RGB", (60, 90), (200, 40, 45)).save(layers_mod.raw_path(gid, mid))

    cevap = client.get(f"/api/dressed/{gid}.png")
    assert cevap.status_code == 200
    assert cevap.headers["content-type"] == "image/png"


def test_ham_cikti_yoksa_404(client, db_path, tmp_path):
    """Ham çıktısı olmayan kıyafette istemci bindirmeye düşmeli."""
    foto = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 160)).save(foto)
    from wardrobe import mannequin as man
    man.from_photo(foto, db_path=db_path)

    gid = insert_garment({"category": "ust", "raw_path": "a.jpg"}, db_path=db_path)
    assert client.get(f"/api/dressed/{gid}.png").status_code == 404


def test_wardrobe_ham_cikti_damgasini_tasiyor(client, db_path, tmp_path):
    """İstemci ham çıktının VARLIĞINI cevaptan öğrenmeli.

    Öğrenemezse her seçimde 404 riskiyle istek atmak zorunda kalır ve
    kullanıcı bir anlık boş kare görür.
    """
    from wardrobe import layers as layers_mod
    from wardrobe import mannequin as man

    foto = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 160)).save(foto)
    man.from_photo(foto, db_path=db_path)
    mid = man.active_id(db_path)

    gid = insert_garment({"category": "ust", "raw_path": "a.jpg"}, db_path=db_path)
    assert client.get("/api/wardrobe").json()["garments"][0]["dressed_rev"] == 0

    Image.new("RGB", (60, 90), (200, 40, 45)).save(layers_mod.raw_path(gid, mid))
    assert client.get("/api/wardrobe").json()["garments"][0]["dressed_rev"] > 0


def test_zemin_notrlenmemis_hali_de_servis_ediliyor(client, db_path, tmp_path):
    """Nötrleme yalnızca BİNDİRME için gerekli.

    Seçim boşken ve tek kıyafette bindirme yok, dolayısıyla mankeni gri
    göstermenin bir gerekçesi de yok — kullanıcı bunu fark etti. Zemin artık
    yalnızca 2+ kıyafette nötrlenmiş sürüme geçiyor.
    """
    from wardrobe import mannequin as man

    foto = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 160)).save(foto)
    man.from_photo(foto, db_path=db_path)

    assert client.get("/api/base_raw.png").status_code == 200
    assert client.get("/api/wardrobe").json()["base_raw_rev"] > 0


def test_tek_kiyafet_damgasi_algoritma_surumunu_de_iceriyor(
        db_path, tmp_path, monkeypatch):
    """Önbellek damgası ALGORİTMA değişince de değişmeli.

    Gerçek bir hata bu testi doğurdu. Damga önce `max(ham, çıkarım)` idi;
    ham çıktı çıkarım base'inden yeni olduğu için sonuç, düzeltme öncesiyle
    BİREBİR aynı sayı çıktı. Sunucudaki dosya düzeltilmişti ama URL
    değişmediği için tarayıcı eski YEŞİL görüntüyü belleğinden servis etti ve
    kullanıcı "düzelmedi" diye bildirdi.

    Yani damganın kaynak dosyaları takip etmesi YETMİYOR: gösterilen görüntü
    koda da bağlı (§25.7'nin üçüncü tekrarı).
    """
    from web import app as web_app

    # `_ham_rev` aktif mankeni VARSAYILAN yoldan okuyor (sunucu öyle çalışıyor).
    monkeypatch.setattr("db.DB_PATH", db_path)

    Image.new("RGB", (200, 400), (180, 180, 185)).save(tmp_path / "m.png")
    mannequin.from_photo(tmp_path / "m.png", db_path=db_path)
    mid = mannequin.active_id(db_path=db_path)
    Image.new("RGB", (200, 400), (60, 60, 60)).save(layers.raw_path(3, mid))

    damga = web_app._ham_rev(3)
    assert damga > 0

    # Sürüm artınca damga DEĞİŞMELİ — kaynak dosyalara hiç dokunulmadan.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("wardrobe.layers.RESTORE_VERSION", layers.RESTORE_VERSION + 1)
        assert web_app._ham_rev(3) != damga, (
            "algoritma sürümü damgaya girmiyor — tarayıcı bayat görüntü servis eder")


def test_gosterim_onbellegi_surum_adini_tasiyor():
    """Sürüm dosya adında olmalı ki eski kopyalar kendiliğinden devre dışı kalsın."""
    yol = layers.display_raw_path(5, 9)
    assert f"v{layers.RESTORE_VERSION}" in yol.name, yol.name
    assert "g5_m9" in yol.name, yol.name
