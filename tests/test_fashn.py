"""FASHN'ın kendi API'si — §24.

Testler ağa çıkmıyor: `_post` ve `_status` sahteleniyor ve gönderilen gövde
inceleniyor. Amaç, ücretli çağrının NE gönderdiğini kayıt altına almak —
şema dokümandan doğrulandı, tahmin değil.
"""
from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from wardrobe import vton


def sahte_cikti() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (12, 18), (10, 20, 30)).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class SahteFashn:
    """POST/GET'i taklit eder; gövdeyi ve yoklama sayısını saklar."""

    def __init__(self, durumlar=("completed",), hata=None, cikti=None):
        self.gonderilen = []
        self.durumlar = list(durumlar)
        self.hata = hata
        self.cikti = cikti if cikti is not None else [sahte_cikti()]
        self.yoklama = 0

    def post(self, payload):
        self.gonderilen.append(payload)
        return {"id": "pred-1", "error": self.hata}

    def status(self, pid):
        self.yoklama += 1
        durum = self.durumlar[min(self.yoklama - 1, len(self.durumlar) - 1)]
        if durum == "failed":
            return {"id": pid, "status": "failed",
                    "error": {"name": "PoseError", "message": "poz bulunamadı"}}
        if durum == "completed":
            return {"id": pid, "status": "completed", "output": self.cikti,
                    "error": None}
        return {"id": pid, "status": durum, "output": None, "error": None}


@pytest.fixture
def gorseller(tmp_path):
    model = tmp_path / "model.png"
    Image.new("RGB", (864, 1296), (67, 96, 144)).save(model)
    garment = tmp_path / "garment.png"
    Image.new("RGBA", (600, 800), (200, 40, 40, 255)).save(garment)
    return model, garment


def kur(provider, monkeypatch, sahte=None, hizli=True):
    sahte = sahte or SahteFashn()
    monkeypatch.setattr(provider, "_post", sahte.post)
    monkeypatch.setattr(provider, "_status", sahte.status)
    monkeypatch.setattr("wardrobe.secrets.get",
                        lambda ad: "anahtar" if ad == "FASHN_API_KEY" else None)
    if hizli:
        monkeypatch.setattr("time.sleep", lambda s: None)
    return sahte


# --- istek gövdesi (şema dokümandan doğrulandı) ---

def test_tryon_max_govdesi(gorseller, monkeypatch):
    p = vton.FashnProvider(model_name="tryon-max", resolution="2k",
                           generation_mode="quality", seed=7)
    sahte = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    govde = sahte.gonderilen[0]
    assert govde["model_name"] == "tryon-max"
    inputs = govde["inputs"]
    # Parametreler `inputs` İÇİNDE olmak zorunda — üst seviyede değil.
    assert set(govde) == {"model_name", "inputs"}
    assert inputs["product_image"].startswith("data:image/png;base64,")
    assert inputs["model_image"].startswith("data:image/png;base64,")
    assert inputs["resolution"] == "2k"
    assert inputs["generation_mode"] == "quality"
    assert inputs["seed"] == 7
    assert inputs["output_format"] == "png"
    # tryon-max'te bunlar YOK — göndermek InputValidationError üretir.
    assert "category" not in inputs
    assert "segmentation_free" not in inputs
    assert "garment_image" not in inputs


def test_v16_govdesi_farkli(gorseller, monkeypatch):
    """Aynı sağlayıcı v1.6'yı da konuşabiliyor — orada alan adları başka."""
    p = vton.FashnProvider(model_name="tryon-v1.6")
    sahte = kur(p, monkeypatch)

    p.try_on(*gorseller, "alt")

    inputs = sahte.gonderilen[0]["inputs"]
    assert sahte.gonderilen[0]["model_name"] == "tryon-v1.6"
    assert inputs["garment_image"].startswith("data:")
    assert inputs["category"] == "bottoms"
    assert inputs["garment_photo_type"] == "flat-lay"
    assert "product_image" not in inputs


def test_yaka_etiketi_talimati_VARSAYILAN(gorseller, monkeypatch):
    """Flat-lay'de arka yaka öne kıvrılınca ense etiketi render'a giriyor.

    Ölçüldü (#10 sarı tişört, aynı tohum, tek değişken prompt): etiket ve
    lacivert iç yaka tamamen kayboldu.
    """
    p = vton.FashnProvider()
    sahte = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert sahte.gonderilen[0]["inputs"]["prompt"] == vton.FASHN_TRYON_PROMPT


def test_talimat_KAPATILABILIYOR(gorseller, monkeypatch):
    """A/B ölçümü yapabilmek için varsayılanı susturmak mümkün olmalı."""
    p = vton.FashnProvider(prompt="")
    sahte = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert "prompt" not in sahte.gonderilen[0]["inputs"]


def test_sonuc_base64_isteniyor_CDN_e_dokunulmuyor(gorseller, monkeypatch):
    """§6.1 #9'un en pahalı hata türünü YAPISAL olarak imkânsız kılıyor.

    "inference ücretlendirildi, sonuç indirilemedi" ancak ayrı bir CDN'den
    indirme adımı varsa mümkün. return_base64 o adımı ortadan kaldırıyor.
    """
    p = vton.FashnProvider()
    sahte = kur(p, monkeypatch)

    p.try_on(*gorseller, "ust")

    assert sahte.gonderilen[0]["inputs"]["return_base64"] is True


def test_gorsel_kuculterek_gonderiliyor(gorseller, monkeypatch, tmp_path):
    """30 MiB sınırı var ve 20 MP kırpıklar hattı yavaşlatıyordu (§23.2)."""
    dev = tmp_path / "dev.png"
    Image.new("RGBA", (3840, 5120), (200, 40, 40, 255)).save(dev)
    p = vton.FashnProvider()
    sahte = kur(p, monkeypatch)

    p.try_on(gorseller[0], dev, "ust")

    uri = sahte.gonderilen[0]["inputs"]["product_image"]
    ham = base64.b64decode(uri.split(",", 1)[1])
    assert max(Image.open(io.BytesIO(ham)).size) <= vton.VTON_MAX_PX


# --- yoklama ---

def test_tamamlanana_kadar_yokluyor(gorseller, monkeypatch):
    p = vton.FashnProvider()
    sahte = kur(p, monkeypatch,
                SahteFashn(durumlar=("in_queue", "processing", "completed")))

    img = p.try_on(*gorseller, "ust")

    assert sahte.yoklama == 3
    assert img.size == (12, 18)


def test_cikti_KUCULTULMUYOR(gorseller, monkeypatch):
    """Sağlayıcı çıktıyı base'in boyutuna zorlamıyor — bu bilinçli.

    tryon-max'in 2K/4K seçeneği için para ödeniyor; onu 864x1296'ya indirmek
    tam olarak ödenen şeyi çöpe atmak olurdu. Hizalama gereken tek yer katman
    çıkarımı ve `extract_layer` zaten kendisi ölçekliyor. En-boy oranı korunuyor
    (FASHN çıktı oranını girdiden alıyor), yani ölçekleme silueti bozmuyor.
    """
    buf = io.BytesIO()
    Image.new("RGB", (1664, 2496), (5, 5, 5)).save(buf, "PNG")
    buyuk = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    p = vton.FashnProvider(resolution="2k")
    kur(p, monkeypatch, SahteFashn(cikti=[buyuk]))

    assert p.try_on(*gorseller, "ust").size == (1664, 2496)


def test_failed_durumu_gerekcesiyle_yukseliyor(gorseller, monkeypatch):
    p = vton.FashnProvider()
    kur(p, monkeypatch, SahteFashn(durumlar=("failed",)))

    with pytest.raises(RuntimeError) as exc:
        p.try_on(*gorseller, "ust")

    assert "PoseError" in str(exc.value)
    assert "poz bulunamadı" in str(exc.value)


def test_sonsuz_yoklama_YOK(gorseller, monkeypatch):
    """§23.1'in dersi: zaman aşımsız bekleme arayüzü sonsuza kadar döndürüyor.

    Burada iş hiç tamamlanmıyor; çağrı yine de bitmeli ve prediction id'yi
    taşımalı (ücretlenmiş olabilir).
    """
    import itertools

    p = vton.FashnProvider()
    kur(p, monkeypatch, SahteFashn(durumlar=("processing",)))
    # Saati ileri sar: gerçek zamanda beklemeden zaman aşımını tetikle.
    sayac = itertools.count(0, vton.CALL_TIMEOUT)
    monkeypatch.setattr("time.monotonic", lambda: next(sayac))

    with pytest.raises(vton.CallTimeout) as exc:
        p.try_on(*gorseller, "ust")

    assert "pred-1" in str(exc.value)


def test_istek_reddedilirse_yoklamaya_gecilmiyor(gorseller, monkeypatch):
    p = vton.FashnProvider()
    sahte = kur(p, monkeypatch, SahteFashn(hata="InputValidationError"))

    with pytest.raises(RuntimeError):
        p.try_on(*gorseller, "ust")

    assert sahte.yoklama == 0


def test_cikti_sozluk_semasini_da_kabul_ediyor(gorseller, monkeypatch):
    """Bazı uç noktalar {"images": [...]} döndürüyor, bazıları düz liste."""
    p = vton.FashnProvider()
    kur(p, monkeypatch, SahteFashn(cikti={"images": [sahte_cikti()]}))

    assert p.try_on(*gorseller, "ust").size == (12, 18)


# --- kategori ve katman uygunluğu ---

def test_tryon_max_AYAKKABIYI_da_destekliyor():
    """§10'daki sınır FASHN'ın v1.6 eğitim setinin sınırıydı, evrensel değil."""
    maxp = vton.FashnProvider(model_name="tryon-max")

    assert maxp.supports_category("ayakkabi")
    assert maxp.supports_category("aksesuar")
    assert not vton.FashnProvider(model_name="tryon-v1.6").supports_category("ayakkabi")


def test_tryon_max_katman_uretimine_ACIK_cunku_OLCULDU():
    """Başta kapalıydı (kanıt yoktu); §25'te ölçüldü ve açıldı.

    Ölçüm (#11 mor tişört): sızıntı 11.355 → 3.253, renk hatası 37.5 → 22.4,
    ve asıl sınav olan iki katmanın bindirilmesi (#11 + #7) temiz çıktı.
    """
    assert vton.supports_layers(vton.FashnProvider(model_name="tryon-max")) is True
    assert vton.supports_layers(vton.FashnProvider(model_name="tryon-v1.6")) is True


def test_kapi_elle_kapatilabiliyor():
    """Yeni bir model eklendiğinde ölçülene kadar kapatabilmek şart."""
    p = vton.FashnProvider(model_name="tryon-max", allow_layers=False)
    assert vton.supports_layers(p) is False


def test_desteklenmeyen_kategori_cagri_YAPILMADAN_reddediliyor(gorseller, monkeypatch):
    p = vton.FashnProvider(model_name="tryon-v1.6")
    sahte = kur(p, monkeypatch)

    with pytest.raises(vton.UnsupportedCategory):
        p.try_on(*gorseller, "ayakkabi")

    assert sahte.gonderilen == [], "desteklenmeyen kategoride para harcandı"


# --- kayıt ve anahtar ---

def test_saglayici_registry_de_kayitli():
    assert vton.get_provider("fashn").name == "fashn"


def test_anahtar_yoksa_available_false(monkeypatch):
    monkeypatch.setattr("wardrobe.secrets.get", lambda ad: None)
    assert vton.FashnProvider().available() is False


def test_bilinmeyen_model_reddediliyor():
    with pytest.raises(ValueError):
        vton.FashnProvider(model_name="tryon-v2")


def test_kredi_maliyeti_dokumandan():
    assert vton.FashnProvider(generation_mode="fast", resolution="1k").credits() == 1
    assert vton.FashnProvider(generation_mode="balanced", resolution="2k").credits() == 3
    assert vton.FashnProvider(generation_mode="quality", resolution="4k").credits() == 5


def test_ucret_kredi_basina_fiyattan():
    """FASHN KREDİ başına ücretliyor (help.fashn.ai): tryon-max balanced+1k =
    2 kredi = $0.15. Arayüz eskiden çağrı başına $0.075 yazıyordu (§54)."""
    assert vton.FashnProvider().cost_usd() == pytest.approx(0.15)
    assert vton.FashnProvider(generation_mode="fast",
                              resolution="1k").cost_usd() == pytest.approx(0.075)


def test_fashn_api_anahtari_doctor_da_listeleniyor():
    from wardrobe import secrets
    assert any(k[0] == "FASHN_API_KEY" for k in secrets.KNOWN_KEYS)


# --- HTTP başlıkları ---

def test_user_agent_gonderiliyor(monkeypatch):
    """urllib'in varsayılan UA'sı Cloudflare tarafından engelleniyor.

    Ölçüldü: UA yokken her istek (anahtarlı, anahtarsız, GET, POST fark
    etmiyor) `403 error code: 1010` dönüyordu — gövdesi JSON bile olmayan bir
    Cloudflare cevabı. Herhangi bir UA verilince API düzgün JSON dönüyor.
    UA düşerse hat sessizce ölür ve hata "anahtar bozuk" gibi görünür.
    """
    monkeypatch.setattr("wardrobe.secrets.get", lambda ad: "anahtar")
    basliklar = vton.FashnProvider()._headers()

    assert basliklar.get("User-Agent"), "User-Agent yok — Cloudflare 403 verir"
    assert "urllib" not in basliklar["User-Agent"].lower().split("/")[0]
    assert basliklar["Authorization"] == "Bearer anahtar"
    assert basliklar["Accept"] == "application/json"


def test_http_hatasinin_GOVDESI_mesaja_giriyor(gorseller, monkeypatch):
    """403'ün gövdesi okunmayınca teşhis 'anahtar bozuk'a saplanıyordu.

    Oysa gerekli bilgi cevabın içindeydi: `error code: 1010` = Cloudflare.
    """
    import urllib.error

    def patlat(*a, **k):
        raise urllib.error.HTTPError(
            "https://api.fashn.ai/v1/run", 403, "Forbidden", {},
            io.BytesIO(b"error code: 1010\n"))

    monkeypatch.setattr("urllib.request.urlopen", patlat)
    monkeypatch.setattr("wardrobe.secrets.get", lambda ad: "anahtar")

    with pytest.raises(RuntimeError) as exc:
        vton.FashnProvider().try_on(*gorseller, "ust")

    assert "403" in str(exc.value)
    assert "1010" in str(exc.value), "hata gövdesi yutulmuş"
