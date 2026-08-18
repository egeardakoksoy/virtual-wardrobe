"""Sağlayıcı parametreleri ve alternatif sağlayıcı — Sorun B.

Buradaki testler ağa çıkmıyor: fal istemcisi sahteleniyor ve gönderilen
argümanlar inceleniyor. Amaç, ücretli çağrının NE gönderdiğini kayıt altına
almak — parametreler sessizce değişirse (§16'nın kök sebep hipotezi buna
dayanıyor) buradan görünsün.
"""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from wardrobe import vton


class SahteIstemci:
    """fal_client yerine geçer; gönderilen argümanları saklar.

    `subscribe` imzası gerçeğiyle aynı tutuluyor — sahte, gerçekte var olmayan
    bir çağrıyı kabul ederse test yeşil kalırken üretim patlar.
    """

    def __init__(self, patlat: Exception | None = None):
        self.cagrilar = []
        self.kwargs = []
        self.yuklenen = []
        self.patlat = patlat

    def upload_image(self, image, format="jpeg"):
        self.yuklenen.append((image.size, format))
        return f"https://ornek/{image.size[0]}x{image.size[1]}.{format}"

    def encode_image(self, image, format="jpeg"):
        self.yuklenen.append((image.size, format))
        return "data:image/png;base64,xxx"

    def subscribe(self, endpoint, arguments, *, on_enqueue=None,
                  start_timeout=None, client_timeout=None, **kw):
        self.cagrilar.append((endpoint, arguments))
        self.kwargs.append({"start_timeout": start_timeout,
                            "client_timeout": client_timeout})
        if on_enqueue is not None:
            on_enqueue("req-123")
        if self.patlat is not None:
            raise self.patlat
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, "PNG")
        veri = base64.b64encode(buf.getvalue()).decode()
        return {"images": [{"url": f"data:image/png;base64,{veri}"}]}


@pytest.fixture
def gorseller(tmp_path):
    model = tmp_path / "model.png"
    Image.new("RGB", (100, 150), (67, 96, 144)).save(model)
    garment = tmp_path / "garment.png"
    Image.new("RGBA", (60, 60), (200, 40, 40, 255)).save(garment)
    return model, garment


@pytest.fixture
def dev_gorseller(tmp_path):
    """Gerçek dolaptaki gibi: 20 MP kırpık + normal boy base."""
    model = tmp_path / "base.png"
    Image.new("RGB", (864, 1296), (67, 96, 144)).save(model)
    garment = tmp_path / "dev.png"
    Image.new("RGBA", (3840, 5120), (200, 40, 40, 255)).save(garment)
    return model, garment


def kur(provider, monkeypatch, patlat=None):
    istemci = SahteIstemci(patlat=patlat)
    monkeypatch.setattr(provider, "_client", lambda: istemci)
    monkeypatch.setattr(vton, "media_host_resolves", lambda hosts: True)
    return istemci


# --- zaman aşımı: ölçülmüş bir arızadan sonra eklendi ---
#
# Bir render işi fal'ın kuyruğunda takıldı, istemci 45 DAKİKA bekledi ve
# "Gerçekçi Göster" sonsuza kadar döndü. fal_client'ın belgesi açık:
# zaman aşımı verilmezse süresiz bekliyor.

def test_cagri_zaman_asimiyla_yapiliyor(gorseller, monkeypatch):
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    kw = istemci.kwargs[0]
    assert kw["client_timeout"] == vton.CALL_TIMEOUT
    assert kw["start_timeout"] == vton.QUEUE_TIMEOUT
    assert kw["client_timeout"] is not None, (
        "zaman aşımı yoksa takılan bir iş kullanıcıyı süresiz bekletir"
    )


def test_zaman_asiminda_request_id_hataya_giriyor(gorseller, monkeypatch):
    """Zaman aşımı 'iş çalışmadı' demek DEĞİL — ücretlenmiş olabilir.

    §6.1 #9'un dersi: ödenmiş bir sonucu geri almanın tek yolu ona işaret eden
    bir tutamak saklamak.
    """
    p = vton.FalProvider()
    kur(p, monkeypatch, patlat=TimeoutError("request timeout"))

    with pytest.raises(vton.CallTimeout) as exc:
        p.try_on(*gorseller, "ust")

    assert "req-123" in str(exc.value)


def test_zaman_asimi_disindaki_hata_oldugu_gibi_yukseliyor(gorseller, monkeypatch):
    """Her hatayı CallTimeout'a çevirmek teşhisi bozardı."""
    p = vton.FalProvider()
    kur(p, monkeypatch, patlat=ValueError("geçersiz kategori"))

    with pytest.raises(ValueError):
        p.try_on(*gorseller, "ust")


# --- gönderilen görselin boyutu ---

def test_dev_kirpik_kuculterek_gonderiliyor(dev_gorseller, monkeypatch):
    """20 MP kırpık olduğu gibi gitmemeli.

    Ölçüldü: 3840x5120'lik kırpıklarla bir render işi fal'ın kuyruğunda asılı
    kaldı; 1200x1600'lük bir kırpıkla aynı hat normal sürede döndü. Modelin
    çıktısı zaten 864x1296 — 20 megapiksel göndermenin karşılığı yok.
    """
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*dev_gorseller, "ust")

    boyutlar = [b for b, _ in istemci.yuklenen]
    assert all(max(b) <= vton.VTON_MAX_PX for b in boyutlar), boyutlar


def test_kucuk_gorsel_BUYUTULMUYOR(gorseller, monkeypatch):
    """downscale yalnızca küçültür; base manken (864x1296) bozulmamalı."""
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert [b for b, _ in istemci.yuklenen] == [(100, 150), (60, 60)]


def test_gorseller_PNG_olarak_gonderiliyor(gorseller, monkeypatch):
    """fal_client'ın varsayılanı jpeg — alfayı düşürür.

    Kırpığın alfası "kıyafet nerede" bilgisinin ta kendisi; JPEG'e çevirmek
    onu sessizce yok eder ve model arka planı kıyafet sanır.
    """
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert {f for _, f in istemci.yuklenen} == {"png"}


def test_gemini_de_zaman_asimiyla_cagriliyor(gorseller, monkeypatch):
    p = vton.GeminiEditProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert istemci.kwargs[0]["client_timeout"] == vton.CALL_TIMEOUT


# --- FASHN parametreleri ---

def test_segmentation_free_istege_ekleniyor(gorseller, monkeypatch):
    """§16'nın kök sebep hipotezi bu alanda: açıkken model yeni kıyafeti
    base'inkinin ÜZERİNE harmanlıyor ve onun sınırlarını miras alıyor."""
    p = vton.FalProvider(segmentation_free=False)
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    _, arg = istemci.cagrilar[0]
    assert arg["segmentation_free"] is False


def test_segmentation_free_varsayilani_modulden_geliyor(gorseller, monkeypatch):
    """Ayarı tek satırdan geri almak mümkün olmalı — hipotez henüz ölçülmedi."""
    monkeypatch.setattr(vton, "FASHN_SEGMENTATION_FREE", True)
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert istemci.cagrilar[0][1]["segmentation_free"] is True


def test_tohum_verilmezse_istege_KONULMUYOR(gorseller, monkeypatch):
    """Tohumsuz çağrı, sağlayıcının kendi rastgeleliğini kullanmalı.

    `seed: None` göndermek şemada geçerli ama niyeti gizler; alan hiç
    olmadığında "tohum belirtilmedi" açıkça okunuyor.
    """
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert "seed" not in istemci.cagrilar[0][1]


def test_tohum_verilirse_gonderiliyor(gorseller, monkeypatch):
    """Tohum olmadan zayıf bir çıktıyı yeniden denemek tekrarlanabilir değil."""
    p = vton.FalProvider(seed=1234)
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert istemci.cagrilar[0][1]["seed"] == 1234


def test_flat_lay_ve_png_korunuyor(gorseller, monkeypatch):
    """Bu ikisi ölçümle seçilmişti; yeni alanlar eklerken düşmesinler."""
    p = vton.FalProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    arg = istemci.cagrilar[0][1]
    assert arg["garment_photo_type"] == "flat-lay"
    assert arg["output_format"] == "png"
    assert arg["mode"] == "quality"


# --- data URI: CDN'e hiç dokunmayan sonuç yolu ---

def test_data_uri_sonucu_agsiz_okunuyor():
    """sync_mode ile sonuç yanıtın içinde geliyor — indirilecek bir şey yok.

    Bu, §6.1 #9'daki en pahalı başarısızlığın (ücret ödendi, sonuç inemedi)
    tamamen dışında kalmak demek.
    """
    buf = io.BytesIO()
    Image.new("RGB", (5, 7), (1, 2, 3)).save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    img = vton._download_image(uri)
    assert img.size == (5, 7)


# --- gemini sağlayıcısı ---

def test_gemini_katman_uretimine_uygun_degil():
    """Ölçüldü: düzenleyici kıyafet DIŞINDAKİ pikselleri de yeniden üretiyor.

    Fark tabanlı çıkarım tam olarak "kıyafet dışı sabit kalır" varsayımına
    dayandığı için katman baştan sona kirli çıkardı.
    """
    assert vton.supports_layers(vton.GeminiEditProvider()) is False
    assert vton.supports_layers(vton.FalProvider()) is True
    assert vton.supports_layers(vton.MockProvider()) is True


def test_gemini_ayakkabiyi_da_destekliyor():
    """'Ayakkabı olmaz' FASHN'ın sınırı (§10), evrensel bir kural değil."""
    gemini = vton.GeminiEditProvider()

    assert gemini.supports_category("ayakkabi")
    assert gemini.supports_category("aksesuar")
    assert not vton.FalProvider().supports_category("ayakkabi")


def test_gemini_prompt_kiyafet_disini_korumayi_soyluyor():
    """Düzenleyicinin bilinen kusurunu kısıtlayan tek kaldıraç prompt."""
    metin = vton.GeminiEditProvider().prompt_for("ust").lower()

    assert "do not change" in metin
    assert "background" in metin and "face" in metin


def test_gemini_sonucu_model_gorselinin_boyutuna_getiriyor(gorseller, monkeypatch):
    """Katman hattı ve önbellek sabit boyut varsayıyor."""
    p = vton.GeminiEditProvider()
    kur(p, monkeypatch)

    out = p.try_on(*gorseller, "ust")
    assert out.size == Image.open(gorseller[0]).size


def test_gemini_sync_mode_ile_cagriliyor(gorseller, monkeypatch):
    """CDN alan adını tahmin etmemek için bilinçli seçim (bkz. RESULT_HOSTS)."""
    p = vton.GeminiEditProvider()
    istemci = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    endpoint, arg = istemci.cagrilar[0]
    assert endpoint == vton.FAL_EDIT_ENDPOINT
    assert arg["sync_mode"] is True
    assert len(arg["image_urls"]) == 2


def test_edit_uc_noktasi_icin_tahmin_edilmis_cdn_yok():
    """Kural: RESULT_HOSTS'a yalnızca GÖZLENMİŞ alan adı yazılır.

    Bir kez tahminle yazıldı ('fal olduğuna göre fal.media'dır'), kontrol
    geçti, çağrı gitti, indirme yine patladı ve para yandı.
    """
    assert vton.FAL_EDIT_ENDPOINT not in vton.RESULT_HOSTS


def test_gemini_registry_de_kayitli():
    assert vton.get_provider("gemini").name == "gemini"


# --- katman hattının korunması ---

def test_katman_uretimi_uygunsuz_saglayiciyi_UCRETSIZ_reddediyor(db_path, tmp_path):
    """Reddin ÇAĞRIDAN ÖNCE olması şart — yoksa para bozuk katmana gider."""
    from tests.conftest import make_garment_photo
    from wardrobe import layers
    from wardrobe.ingest import add_garment

    foto = make_garment_photo(tmp_path / "t.jpg")
    kayit = add_garment(foto, use_vlm=False, db_path=db_path)

    class Gozetleyen(vton.GeminiEditProvider):
        cagrildi = False

        def try_on(self, *a, **k):
            type(self).cagrildi = True
            raise AssertionError("uygunsuz sağlayıcı ile ücretli çağrı yapıldı")

    sonuc = layers.build_layer(kayit["id"], provider=Gozetleyen(),
                               db_path=db_path)

    assert sonuc["status"] == "failed"
    assert "katman üretimine uygun değil" in sonuc["error"]
    assert Gozetleyen.cagrildi is False


def test_supports_category_tanimlamayan_saglayici_calisir():
    """Sağlayıcı arayüzü duck-typing — üç satırlık sahte sağlayıcılar da geçerli."""
    class Minimal:
        name = "minimal"

    assert vton.supports_category(Minimal(), "ust") is True
    assert vton.supports_category(Minimal(), "ayakkabi") is False
