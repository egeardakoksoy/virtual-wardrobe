"""Düzenleme sohbeti — render üzerine serbest metin talimatları.

Ağa çıkılmıyor: sağlayıcının `edit`'i sahteleniyor. Testlerin çoğu para ve
veri kaybıyla ilgili, çünkü bu modülün taşıdığı iki risk bunlar.
"""
from __future__ import annotations

import json

import pytest
from PIL import Image

from wardrobe import edits, vton


@pytest.fixture
def render_png(tmp_path, monkeypatch):
    """İzole bir RENDER_DIR ve içinde tek bir render."""
    d = tmp_path / "renders"
    d.mkdir(exist_ok=True)   # conftest de olusturuyor olabilir
    # SADECE wardrobe.render yönlendiriliyor. `edits` yolu çağrı anında oradan
    # çözüyor — ikisini birden yamalamak, tam da bu düzeltmeyi test dışı
    # bırakırdı (bkz. test_render_dir_CAGRI_ANINDA_cozuluyor).
    monkeypatch.setattr("wardrobe.render.RENDER_DIR", d)
    Image.new("RGB", (40, 60), (10, 20, 30)).save(d / "m1_6-8.png")
    return "m1_6-8"


class SahteEditor:
    """provider.edit yerine geçer; çağrıları ve kaynak görüntüyü saklar."""

    name = "fashn"

    def __init__(self):
        self.cagrilar = []

    def available(self):
        return True

    def credits(self):
        return 2

    def edit(self, image, prompt, *, seed=None, **kw):
        self.cagrilar.append({"image": str(image), "prompt": prompt, "seed": seed})
        # Her adım farklı renk üretsin ki zincir izlenebilsin
        ton = 40 + 30 * len(self.cagrilar)
        return Image.new("RGB", (40, 60), (ton, ton, ton))


# --- anahtar doğrulama (yol enjeksiyonu) ---

@pytest.mark.parametrize("kotu", [
    "../../gizli", "m1_6-8/../../x", "m1_6-8;rm", "", "M1_6-8", "m1_6-8.png",
])
def test_gecersiz_anahtar_reddediliyor(kotu):
    with pytest.raises(edits.EditError):
        edits.chain_path(kotu)


def test_gecerli_anahtarlar_kabul(render_png):
    edits.chain_path("m1_6-8")
    edits.chain_path("m2_1-2-3")
    edits.chain_path("m1_6-8_gemini")


# --- zincir ---

def test_bos_zincirde_render_gosteriliyor(render_png):
    assert edits.chain(render_png) == []
    assert edits.current_path(render_png).name == "m1_6-8.png"


def test_duzenleme_zincire_ekleniyor(render_png):
    p = SahteEditor()
    sonuc = edits.apply_edit(render_png, "roll up the sleeves", provider=p)

    assert sonuc["count"] == 1
    zincir = edits.chain(render_png)
    assert zincir[0]["prompt"] == "roll up the sleeves"
    assert zincir[0]["credits"] == 2
    assert edits.current_path(render_png).name == "m1_6-8_e1.png"


def test_ikinci_talimat_BIRINCININ_SONUCUNA_uygulaniyor(render_png):
    """Konuşma gibi olmalı: 'kolları kıvır' sonra 'sola dön' ikisini birden taşır.

    Kaynak her seferinde render olsaydı ikinci talimat birinciyi iptal ederdi.
    """
    p = SahteEditor()
    edits.apply_edit(render_png, "roll up the sleeves", provider=p)
    edits.apply_edit(render_png, "turn slightly left", provider=p)

    assert p.cagrilar[0]["image"].endswith("m1_6-8.png")
    assert p.cagrilar[1]["image"].endswith("m1_6-8_e1.png")
    assert edits.current_path(render_png).name == "m1_6-8_e2.png"


def test_zincir_DISKTE_duruyor(render_png):
    """§23.4'ün dersi: bellekteki durum sunucu yeniden başlayınca kayboluyor.

    Ödenmiş bir görüntünün geçmişi bellekte tutulamaz.
    """
    edits.apply_edit(render_png, "tuck in the shirt", provider=SahteEditor())

    veri = json.loads(edits.chain_path(render_png).read_text(encoding="utf-8"))
    assert veri["steps"][0]["prompt"] == "tuck in the shirt"
    assert veri["selected"] == 1
    assert edits.step_path(render_png, 1).is_file()


# --- geri alma: ödenmiş görüntü SİLİNMEZ ---

def test_geri_alma_dosyayi_SILMIYOR(render_png):
    """Ödenmiş bir görüntüyü silmek, parayı çöpe atmanın en sessiz yolu."""
    p = SahteEditor()
    edits.apply_edit(render_png, "a", provider=p)
    dosya = edits.step_path(render_png, 1)

    edits.undo(render_png)

    assert edits.chain(render_png) == []
    assert dosya.is_file(), "geri alma ödenmiş görüntüyü sildi"
    assert edits.current_path(render_png).name == "m1_6-8.png"


def test_geri_alinan_adim_ileri_alinabiliyor(render_png):
    p = SahteEditor()
    edits.apply_edit(render_png, "a", provider=p)
    edits.undo(render_png)

    edits.redo(render_png)

    assert edits.current_path(render_png).name == "m1_6-8_e1.png"
    assert len(p.cagrilar) == 1, "redo yeni bir ÜCRETLİ çağrı yaptı"


def test_bos_zincirde_geri_alma_hata(render_png):
    with pytest.raises(edits.EditError):
        edits.undo(render_png)


def test_reset_zinciri_dusuruyor_dosyalari_birakiyor(render_png):
    p = SahteEditor()
    edits.apply_edit(render_png, "a", provider=p)
    edits.apply_edit(render_png, "b", provider=p)

    sonuc = edits.reset(render_png)

    assert sonuc["cleared"] == 2
    assert edits.chain(render_png) == []
    assert edits.step_path(render_png, 1).is_file()
    assert edits.step_path(render_png, 2).is_file()


# --- Türkçe talimat ---

def test_turkce_talimat_INGILIZCEYE_cevriliyor(render_png, monkeypatch):
    """FASHN'ın örneklerinin hepsi İngilizce; Türkçe gönderip sonucun sessizce
    kötüleşmesi en kötü hata türü — çağrı ÜCRETLİ ve hata 'model beceremedi'
    gibi görünüyor."""
    monkeypatch.setattr("wardrobe.vision.translate_prompt",
                        lambda t, **k: "roll up the sleeves")
    p = SahteEditor()

    edits.apply_edit(render_png, "kolları kıvır", provider=p)

    assert p.cagrilar[0]["prompt"] == "roll up the sleeves"


def test_GECMISTE_kullanicinin_YAZDIGI_duruyor(render_png, monkeypatch):
    """Geçmiş kullanıcının kendi cümlesini göstermeli, çeviriyi değil."""
    monkeypatch.setattr("wardrobe.vision.translate_prompt",
                        lambda t, **k: "roll up the sleeves")
    edits.apply_edit(render_png, "kolları kıvır", provider=SahteEditor())

    adim = edits.chain(render_png)[0]
    assert adim["prompt"] == "kolları kıvır"
    assert adim["sent"] == "roll up the sleeves"


def test_ingilizce_talimat_CEVIRIYE_gitmiyor():
    """Gereksiz çeviri çağrısı yapmasın (ücret + gecikme)."""
    from wardrobe import vision

    assert vision.looks_english("roll up the sleeves")
    assert not vision.looks_english("kolları kıvır")
    assert vision.translate_prompt("roll up the sleeves") == "roll up the sleeves"


def test_ceviri_ASLA_firlatmiyor(monkeypatch):
    """Çeviri bir iyileştirme; zorunlu kılıp hattı kırmak yanlış takas olurdu.

    Ağ giderse ya da anahtar bozuksa özgün metin gitmeli — düzenleme yine de
    çalışsın, sadece Türkçe olarak.
    """
    from wardrobe import vision

    def patlasin(*a, **k):
        raise RuntimeError("ağ gitti")

    monkeypatch.setattr("wardrobe.vision.has_api_key", lambda: True)
    monkeypatch.setattr("anthropic.Anthropic", patlasin)

    assert vision.translate_prompt("kolları kıvır") == "kolları kıvır"


def test_anahtar_yoksa_ceviri_DENENMIYOR(monkeypatch):
    """ANTHROPIC_API_KEY yoksa boşuna istemci kurulmasın."""
    from wardrobe import vision

    monkeypatch.setattr("wardrobe.vision.has_api_key", lambda: False)
    assert vision.translate_prompt("kolları kıvır") == "kolları kıvır"


# --- katman kaynağı TEMBEL üretiliyor ---

def test_kaynak_secmek_DOSYA_YAZMIYOR(tmp_path, monkeypatch, db_path):
    """Arayüz her kombin seçiminde bunu çağırıyor; her dosya ~1.5 MB.

    Ölçüldü: kullanıcı dolabı gezerken 18 gereksiz dosya / ~27 MB birikmişti.
    """
    d = tmp_path / "renders"
    d.mkdir(exist_ok=True)
    monkeypatch.setattr("wardrobe.render.RENDER_DIR", d)

    key = edits.ensure_composite([6, 8], db_path=db_path)

    assert key.endswith("_katman")
    assert list(d.glob("*.png")) == [], "seçim sırasında dosya yazıldı"
    # Yine de "düzenlenebilir" görünmeli — anahtar kombini taşıyor.
    assert edits.plan(key)["available"] is True
    assert list(d.glob("*.png")) == [], "plan() dosya yazdı"


def test_katman_anahtarindan_kombin_cozuluyor():
    assert edits._composite_ids("m1_6-8_katman") == [6, 8]
    assert edits._composite_ids("m2_1-2-3_katman") == [1, 2, 3]
    assert edits._composite_ids("m1_6-8") is None          # render anahtarı
    assert edits._composite_ids("m1_6-8_gemini") is None


# --- TEST İZOLASYONU (§6.1 #8 / #13'ün ÜÇÜNCÜ tekrarı) ---

def test_render_dir_CAGRI_ANINDA_cozuluyor(tmp_path, monkeypatch):
    """`edits` yalnızca `wardrobe.render.RENDER_DIR` yönlendirilince taşınmalı.

    Bu test bir VERİ KAYBINDAN sonra yazıldı. `edits.py` `RENDER_DIR`'i import
    anında kopyalıyordu; `conftest` yalnızca `wardrobe.render.RENDER_DIR`'i
    yönlendirdiği için `edits` GERÇEK `data/renders`'ı göstermeye devam etti.
    Sonuç: `render.clear_cache()` çağıran testler kullanıcının ÜCRETLE
    üretilmiş düzenleme zincirlerini sildi.

    Burada `wardrobe.edits.RENDER_DIR` KASITLI olarak yönlendirilmiyor —
    yönlendirseydik test, düzeltmeyi değil kendi kurulumunu doğrulardı.
    """
    yeni = tmp_path / "baska_renders"
    yeni.mkdir()
    monkeypatch.setattr("wardrobe.render.RENDER_DIR", yeni)

    assert edits.chain_path("m1_1-2").parent == yeni
    assert edits.step_path("m1_1-2", 1).parent == yeni
    assert edits.base_path("m1_1-2").parent == yeni


def test_clear_all_YALNIZCA_yonlendirilen_dizine_dokunuyor(tmp_path, monkeypatch):
    """clear_all gerçek data/renders'a uzanmamalı."""
    yeni = tmp_path / "izole"
    yeni.mkdir()
    monkeypatch.setattr("wardrobe.render.RENDER_DIR", yeni)
    (yeni / "m1_1-2_e1.png").write_bytes(b"x")
    (yeni / "m1_1-2.edits.json").write_text("[]", encoding="utf-8")

    silinen = edits.clear_all()

    assert silinen == 2
    assert not list(yeni.glob("*_e*.png"))


# --- film şeridi: sürüm seçimi ---

def test_ESKIYE_donup_TEKRAR_YENIYE_donulebiliyor(render_png):
    """Kullanıcının bildirdiği hata: eskiye basınca yeniye dönemiyordu.

    Sebep: seçim zinciri KESİYORDU ve sonraki adımların kaydı siliniyordu.
    Dosyalar duruyordu ama kayıt gitmişti, yani ileri gitmenin yolu yoktu.
    """
    p = SahteEditor()
    for t in ("a", "b", "c"):
        edits.apply_edit(render_png, t, provider=p)

    edits.select(render_png, 1)                       # geriye
    assert edits.selected(render_png) == 1

    edits.select(render_png, 3)                       # tekrar ileriye
    assert edits.selected(render_png) == 3
    assert edits.current_path(render_png).name == "m1_6-8_e3.png"


def test_gecmis_SECIMDEN_etkilenmiyor(render_png):
    """Film şeridi tüm sürümleri göstermeli — seçim geçmişi kısaltmamalı."""
    p = SahteEditor()
    for t in ("a", "b", "c"):
        edits.apply_edit(render_png, t, provider=p)

    edits.select(render_png, 0)

    assert [a["n"] for a in edits.history(render_png)] == [1, 2, 3]
    assert edits.chain(render_png) == []          # yol boş
    assert edits.plan(render_png)["can_redo"] is True


def test_reset_sonrasi_ileri_gidilebiliyor(render_png):
    p = SahteEditor()
    edits.apply_edit(render_png, "a", provider=p)
    edits.apply_edit(render_png, "b", provider=p)

    edits.reset(render_png)
    assert edits.selected(render_png) == 0

    edits.redo(render_png)
    assert edits.selected(render_png) == 1


def test_dallanmada_zincir_SOYAGACINI_izliyor(render_png):
    """1'e dönüp yeni talimat yazınca yol 1→4 olmalı, 2 ve 3 o dalda değil."""
    p = SahteEditor()
    for t in ("a", "b", "c"):
        edits.apply_edit(render_png, t, provider=p)
    edits.select(render_png, 1)
    edits.apply_edit(render_png, "yeni dal", provider=p)

    assert [a["n"] for a in edits.chain(render_png)] == [1, 4]
    # ama geçmişte hepsi duruyor
    assert [a["n"] for a in edits.history(render_png)] == [1, 2, 3, 4]


def test_ESKI_bicimli_zincir_dosyasi_okunuyor(render_png):
    """Biçim değişti diye ücretle üretilmiş geçmiş kaybolmamalı."""
    import json

    edits.chain_path(render_png).write_text(json.dumps([
        {"n": 1, "prompt": "a", "file": "x.png", "credits": 2},
        {"n": 2, "prompt": "b", "file": "y.png", "credits": 2},
    ]), encoding="utf-8")

    assert [a["n"] for a in edits.history(render_png)] == [1, 2]
    assert edits.selected(render_png) == 2
    assert [a["n"] for a in edits.chain(render_png)] == [1, 2]


def test_secim_zinciri_geri_sariyor(render_png):
    p = SahteEditor()
    for t in ("a", "b", "c"):
        edits.apply_edit(render_png, t, provider=p)

    edits.select(render_png, 1)

    assert [a["n"] for a in edits.chain(render_png)] == [1]
    assert edits.current_path(render_png).name == "m1_6-8_e1.png"


def test_secim_dosyalari_SILMIYOR(render_png):
    p = SahteEditor()
    for t in ("a", "b", "c"):
        edits.apply_edit(render_png, t, provider=p)

    edits.select(render_png, 1)

    for n in (1, 2, 3):
        assert edits.step_path(render_png, n).is_file(), f"e{n} silindi"


def test_sifir_secimi_orijinale_donuyor(render_png):
    edits.apply_edit(render_png, "a", provider=SahteEditor())
    edits.select(render_png, 0)

    assert edits.chain(render_png) == []
    assert edits.current_path(render_png).name == "m1_6-8.png"


def test_olmayan_adim_secilemiyor(render_png):
    with pytest.raises(edits.EditError):
        edits.select(render_png, 7)


def test_geri_sarip_YENI_duzenleme_ODENMIS_dosyayi_EZMIYOR(render_png):
    """En pahalı sessiz hata: geçmişe dönüp yeni talimat yazınca eski dosyanın
    üstüne yazmak.

    max(n)+1 deseydik: 3 adım var, 1'e dönülür (zincir [1]), yeni talimat n=2
    alır ve ÖDENMİŞ e2'nin üstüne yazar. Numaralandırma dosyalara da bakıyor.
    """
    p = SahteEditor()
    for t in ("a", "b", "c"):
        edits.apply_edit(render_png, t, provider=p)
    eski_e2 = edits.step_path(render_png, 2).read_bytes()

    edits.select(render_png, 1)
    edits.apply_edit(render_png, "yeni dal", provider=p)

    assert edits.step_path(render_png, 2).read_bytes() == eski_e2, \
        "ödenmiş e2 ezildi"
    assert edits.step_path(render_png, 4).is_file(), "yeni adım e4 olmalıydı"
    assert [a["n"] for a in edits.chain(render_png)] == [1, 4]


def test_yeni_dal_SECILEN_surumden_devam_ediyor(render_png):
    p = SahteEditor()
    for t in ("a", "b"):
        edits.apply_edit(render_png, t, provider=p)
    edits.select(render_png, 1)

    edits.apply_edit(render_png, "yeni dal", provider=p)

    assert p.cagrilar[-1]["image"].endswith("m1_6-8_e1.png")


# --- girdi doğrulama ve ücret koruması ---

def test_bos_talimat_CAGRI_YAPILMADAN_reddediliyor(render_png):
    p = SahteEditor()
    for kotu in ("", "   ", "\n"):
        with pytest.raises(edits.EditError):
            edits.apply_edit(render_png, kotu, provider=p)
    assert p.cagrilar == [], "boş talimatta ücretli çağrı yapıldı"


def test_cok_uzun_talimat_reddediliyor(render_png):
    p = SahteEditor()
    with pytest.raises(edits.EditError):
        edits.apply_edit(render_png, "x" * (edits.MAX_PROMPT + 1), provider=p)
    assert p.cagrilar == []


def test_render_yoksa_cagri_yapilmiyor(tmp_path, monkeypatch):
    d = tmp_path / "renders"
    d.mkdir(exist_ok=True)   # conftest de olusturuyor olabilir
    monkeypatch.setattr("wardrobe.render.RENDER_DIR", d)
    p = SahteEditor()

    with pytest.raises(edits.EditError, match="Gerçekçi Göster"):
        edits.apply_edit("m1_9-9", "a", provider=p)
    assert p.cagrilar == []


def test_duzenleme_yapamayan_saglayici_reddediliyor(render_png):
    class Duz:
        name = "fal"

        def available(self):
            return True

    with pytest.raises(edits.EditError, match="düzenleme yapmıyor"):
        edits.apply_edit(render_png, "a", provider=Duz())


def test_plan_UCRETSIZ_ve_saglayiciya_dokunmuyor(render_png, monkeypatch):
    def patlasin(*a, **k):
        raise AssertionError("plan() sağlayıcıyı çağırdı — ücret riski")

    monkeypatch.setattr(vton, "get_provider", patlasin)
    p = edits.plan(render_png)

    assert p["credits"] > 0
    assert p["available"] is True
    assert p["can_undo"] is False


# --- manken değişimi ---

def test_manken_degisince_zincirler_de_siliniyor(render_png):
    """Render silinip zincir kalırsa, olmayan görüntüye işaret eden geçmiş kalır."""
    from wardrobe import render as render_mod

    edits.apply_edit(render_png, "a", provider=SahteEditor())
    assert edits.chain(render_png)

    render_mod.clear_cache()

    assert edits.chain(render_png) == []
    assert not edits.step_path(render_png, 1).is_file()


# --- sağlayıcı tarafı ---

def test_fashn_edit_govdesi(tmp_path, monkeypatch):
    """Şema dokümandan doğrulandı: model_name 'edit', image + prompt zorunlu."""
    import base64
    import io

    gorsel = tmp_path / "kaynak.png"
    Image.new("RGB", (100, 150), (30, 30, 30)).save(gorsel)

    buf = io.BytesIO()
    Image.new("RGB", (10, 15), (1, 2, 3)).save(buf, "PNG")
    cikti = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    gonderilen = {}

    def sahte_post(payload):
        gonderilen.update(payload)
        return {"id": "pred-9", "error": None}

    p = vton.FashnProvider(seed=7)
    monkeypatch.setattr(p, "_post", sahte_post)
    monkeypatch.setattr(p, "_status", lambda pid: {
        "status": "completed", "output": [cikti], "error": None})
    monkeypatch.setattr("wardrobe.secrets.get", lambda ad: "anahtar")

    p.edit(gorsel, "  roll up the sleeves  ")

    assert gonderilen["model_name"] == "edit"
    inputs = gonderilen["inputs"]
    assert inputs["image"].startswith("data:image/png;base64,")
    assert inputs["prompt"] == "roll up the sleeves"     # kırpılmış
    assert inputs["return_base64"] is True
    assert inputs["seed"] == 7


def test_fashn_edit_bos_talimati_reddediyor(tmp_path):
    gorsel = tmp_path / "k.png"
    Image.new("RGB", (10, 10)).save(gorsel)
    with pytest.raises(ValueError):
        vton.FashnProvider().edit(gorsel, "   ")
