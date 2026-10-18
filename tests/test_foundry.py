"""Microsoft Foundry desteği — Claude ve görüntü modeli.

Buradaki testler GERÇEK Foundry'ye hiç çıkmıyor: istemciler sahte. Doğrulanan
şeyler (1) yapılandırmanın doğru okunması, (2) doğru istemcinin ve DAĞITIM
adının seçilmesi, (3) isteklerin şekli ve en önemlisi (4) `bolgeye_kisitla`:
genel amaçlı bir düzenleyici resmin tamamını yeniden çizse bile katman hattı
temiz girdi alıyor mu.

Doğrulanmayan şey modelin kendi kalitesi — o ancak gerçek çağrıyla ölçülür
(HANDOFF §48).
"""
from __future__ import annotations

import base64
import io
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from wardrobe import foundry, layers, mannequin, vision, vton

# Sentetik sahne: 2:3 oranında (gerçek manken tuvaliyle aynı), açık renk duvar
# önünde koyu bir "kişi" dikdörtgeni.
W, H = 200, 300
KISI = (slice(30, 290), slice(70, 130))
KIRMIZI = (200, 40, 45)


def _foundry_ortami(monkeypatch, *, claude=None, image=None):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "ornek-kaynak")
    monkeypatch.setenv("FOUNDRY_API_KEY", "test-anahtari")
    if claude:
        monkeypatch.setenv("FOUNDRY_CLAUDE_DEPLOYMENT", claude)
    if image:
        monkeypatch.setenv("FOUNDRY_IMAGE_DEPLOYMENT", image)


@pytest.fixture
def openai_var(monkeypatch):
    """`openai` kurulu olmasa da `available()` True dönebilsin diye.

    Test ortamında paketin kurulu olması gerekmiyor — istemci zaten sahte.
    Kuruluysa gerçeği gölgelenmiyor.
    """
    try:
        import openai  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "openai", types.ModuleType("openai"))


def _sahne(tmp_path: Path) -> Path:
    a = np.full((H, W, 3), 225, np.uint8)
    a[KISI] = (150, 120, 100)
    yol = tmp_path / "manken.png"
    Image.fromarray(a).save(yol)
    return yol


def _kisi_maskesi() -> np.ndarray:
    m = np.zeros((H, W), bool)
    m[KISI] = True
    return m


def _boyut(kw: dict) -> tuple[int, int]:
    w, h = (int(x) for x in kw["size"].split("x"))
    return w, h


def _ilk_girdi(kw: dict) -> Image.Image:
    gorsel = kw["image"]
    parca = gorsel[0] if isinstance(gorsel, list) else gorsel
    return Image.open(io.BytesIO(parca[1])).convert("RGB")


def _her_seyi_yeniden_ciz(kw: dict) -> Image.Image:
    """Genel amaçlı düzenleyicinin KÖTÜ senaryosu.

    HER piksel değişiyor — yüz, duvar, bacaklar (Gemini'yi katman üretiminden
    dışlatan kusurun abartılmış hâli) — ve gövdeye kırmızı bir kıyafet çiziliyor.
    """
    kisi = _ilk_girdi(kw)
    if kisi.size != (W, H):
        kisi = kisi.resize((W, H), Image.LANCZOS)
    a = np.clip(np.asarray(kisi, np.int16) + 40, 0, 255).astype(np.uint8)
    a[int(0.25 * H):int(0.55 * H), 70:130] = KIRMIZI
    out = Image.fromarray(a)
    return out if out.size == _boyut(kw) else out.resize(_boyut(kw), Image.LANCZOS)


def _b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class _SahteGoruntuler:
    def __init__(self, ciz):
        self.ciz, self.cagrilar = ciz, []

    def edit(self, **kw):
        self.cagrilar.append(("edit", kw))
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_b64(self.ciz(kw)))])

    def generate(self, **kw):
        self.cagrilar.append(("generate", kw))
        return SimpleNamespace(data=[SimpleNamespace(b64_json=_b64(self.ciz(kw)))])


def _saglayici(monkeypatch, ciz):
    p = vton.FoundryImageProvider()
    goruntuler = _SahteGoruntuler(ciz)
    monkeypatch.setattr(p, "_client", lambda: SimpleNamespace(images=goruntuler))
    return p, goruntuler


# --- Yapılandırma ---

def test_ayar_yokken_foundry_kapali():
    assert not foundry.claude_ready()
    assert not foundry.image_ready()
    assert not vton.FoundryImageProvider().available()


def test_kaynak_ve_anahtar_tek_basina_acmaz(monkeypatch):
    """Dağıtım adı açık bir tercih — onu yazmayan Foundry'yi seçmemiş demektir."""
    _foundry_ortami(monkeypatch)
    assert not foundry.claude_ready()
    assert not foundry.image_ready()


def test_goruntu_uc_noktasi_kaynaktan_turer(monkeypatch):
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    assert foundry.openai_base_url() == "https://ornek-kaynak.openai.azure.com/openai/v1/"


def test_uc_nokta_elle_ezilebilir(monkeypatch):
    """Bölgeye/kaynak türüne göre farklı ana makine gerekirse kod değişmeden."""
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    monkeypatch.setenv("FOUNDRY_OPENAI_BASE_URL", "https://baska.example.com/openai/v1")
    assert foundry.openai_base_url() == "https://baska.example.com/openai/v1/"


# --- Claude (öznitelik çıkarımı) ---

class _SahteMesajlar:
    def __init__(self, metin):
        self.metin, self.cagrilar = metin, []

    def create(self, **kw):
        self.cagrilar.append(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=self.metin)],
        )


_GECERLI_OZNITELIK = {
    "category": "ust", "subcategory": "oxford gömlek", "color_name": "açık mavi",
    "color_hex": "#8CBEE6", "secondary_color_hex": "", "pattern": "düz",
    "style": "klasik", "seasons": ["ilkbahar"], "fabric": "pamuk",
    "warmth": 4, "formality": 6, "notes": "düğmeli yaka",
}


def test_foundry_claude_istemcisi_secilir(monkeypatch):
    import anthropic

    _foundry_ortami(monkeypatch, claude="claude-opus-5-5")
    istemci = vision._claude_istemcisi()

    assert isinstance(istemci, anthropic.AnthropicFoundry)
    assert "ornek-kaynak.services.ai.azure.com/anthropic" in str(istemci.base_url)
    assert vision.has_api_key()
    assert "Foundry" in vision.active_label()
    assert "claude-opus-5-5" in vision.active_label()


def test_foundry_yokken_birinci_taraf_istemci(monkeypatch):
    """Mevcut kurulumun davranışı değişmemeli."""
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert type(vision._claude_istemcisi()) is anthropic.Anthropic


def test_oznitelik_cikarimi_dagitim_adini_kullanir(monkeypatch, photo):
    """Foundry'de `model` alanı model kimliği değil DAĞITIM adı istiyor."""
    _foundry_ortami(monkeypatch, claude="benim-claude-dagitimim")
    mesajlar = _SahteMesajlar(json.dumps(_GECERLI_OZNITELIK))
    monkeypatch.setattr(vision, "_claude_istemcisi",
                        lambda: SimpleNamespace(messages=mesajlar))

    attrs = vision.extract_attributes(photo)

    assert attrs["attr_source"] == "claude"
    assert mesajlar.cagrilar[0]["model"] == "benim-claude-dagitimim"
    # JSON şeması dayatması Foundry'de de gidiyor (orada destekleniyor).
    assert mesajlar.cagrilar[0]["output_config"]["format"]["type"] == "json_schema"


def test_ceviri_ayri_dagitim_yoksa_ana_dagitimi_kullanir(monkeypatch):
    """Tek bir Claude dağıtımı yetmeli — ikinci dağıtım zorunlu değil."""
    _foundry_ortami(monkeypatch, claude="ana-dagitim")
    mesajlar = _SahteMesajlar("roll up the sleeves")
    monkeypatch.setattr(vision, "_claude_istemcisi",
                        lambda: SimpleNamespace(messages=mesajlar))

    assert vision.translate_prompt("kolları kıvır") == "roll up the sleeves"
    assert mesajlar.cagrilar[0]["model"] == "ana-dagitim"


def test_ceviri_icin_ayri_dagitim_tanimlanabilir(monkeypatch):
    _foundry_ortami(monkeypatch, claude="ana-dagitim")
    monkeypatch.setenv("FOUNDRY_CLAUDE_TRANSLATE_DEPLOYMENT", "kucuk-dagitim")
    mesajlar = _SahteMesajlar("tuck in the shirt")
    monkeypatch.setattr(vision, "_claude_istemcisi",
                        lambda: SimpleNamespace(messages=mesajlar))

    vision.translate_prompt("gömleği içine sok")
    assert mesajlar.cagrilar[0]["model"] == "kucuk-dagitim"


# --- Sağlayıcı seçimi ---

def test_yalnizca_foundry_varsa_o_secilir(monkeypatch, openai_var):
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    assert vton.get_provider().name == "foundry"
    assert vton.get_edit_provider().name == "foundry"


def test_fashn_varsa_foundry_degil_fashn_secilir(monkeypatch, openai_var):
    """FASHN bu iş için eğitilmiş ve ölçülmüş; Foundry'nin katman kalitesi değil."""
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    monkeypatch.setenv("FASHN_API_KEY", "y")
    assert vton.get_provider().name == "fashn"
    assert vton.get_edit_provider().name == "fashn"


def test_openai_paketi_yoksa_foundry_kullanilamaz(monkeypatch):
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    monkeypatch.setitem(sys.modules, "openai", None)   # import → ImportError
    assert not vton.FoundryImageProvider().available()
    assert vton.get_provider().name == "mock"


def test_render_beyaz_listesinde_foundry_var():
    from web.app import RENDER_PROVIDERS

    assert "foundry" in RENDER_PROVIDERS


# --- İsteklerin şekli ---

def test_giydirme_istegi_dogru_sekilde(monkeypatch, tmp_path, openai_var):
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    monkeypatch.setattr("wardrobe.cutout.person_mask_for", lambda p: None)
    sahne = _sahne(tmp_path)
    kiyafet = tmp_path / "k.png"
    Image.new("RGBA", (80, 80), (*KIRMIZI, 255)).save(kiyafet)
    p, g = _saglayici(monkeypatch, _her_seyi_yeniden_ciz)

    out = p.try_on(sahne, kiyafet, "ust")

    tur, kw = g.cagrilar[0]
    assert tur == "edit"
    assert kw["model"] == "gpt-image-2"                 # DAĞITIM adı
    assert len(kw["image"]) == 2                        # kişi + kıyafet
    assert all(parca[2] == "image/png" for parca in kw["image"])
    assert kw["size"] == "1024x1536" and kw["quality"] == "high"
    assert "input_fidelity" not in kw                   # gpt-image-2.5'te 400
    assert out.size == (W, H)                           # base'in boyutuna döndü


def test_seffaf_kiyafet_beyaz_zemine_oturtulur(tmp_path):
    k = tmp_path / "k.png"
    a = np.zeros((40, 40, 4), np.uint8)
    a[10:30, 10:30] = (*KIRMIZI, 255)
    Image.fromarray(a, "RGBA").save(k)

    ad, veri, tur = vton._png_parcasi(k, "kiyafet.png")
    img = Image.open(io.BytesIO(veri))

    assert (ad, tur, img.mode) == ("kiyafet.png", "image/png", "RGB")
    assert img.getpixel((0, 0)) == (255, 255, 255)
    assert img.getpixel((20, 20)) == KIRMIZI


def test_duzenleme_tek_gorsel_ve_koruma_eki(monkeypatch, tmp_path, openai_var):
    """Düzenleme sohbetinde bölge kısıtlaması YOK — "sola dön" pozu değiştiriyor."""
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    p, g = _saglayici(monkeypatch, lambda kw: Image.new("RGB", _boyut(kw), (10, 20, 30)))

    out = p.edit(_sahne(tmp_path), "roll up the sleeves")

    tur, kw = g.cagrilar[0]
    assert tur == "edit"
    assert not isinstance(kw["image"], list)
    assert kw["prompt"].startswith("roll up the sleeves")
    assert "Keep the person's identity" in kw["prompt"]
    assert out.size == (W, H)


def test_manken_uretimi_generate_kullanir(monkeypatch, openai_var):
    _foundry_ortami(monkeypatch, image="gpt-image-2")
    p, g = _saglayici(monkeypatch, lambda kw: Image.new("RGB", _boyut(kw), (1, 2, 3)))

    out = p.text_to_image("a person standing", (864, 1296))

    assert g.cagrilar[0][0] == "generate"
    assert out.size == (864, 1296)


# --- Bölge kısıtlaması: asıl iddia ---

def test_bolge_disinda_base_aynen_korunur(monkeypatch, tmp_path):
    """Model yüzü ve duvarı değiştirse de çıktıda bölge dışı = base."""
    monkeypatch.setattr("wardrobe.cutout.person_mask_for", lambda p: _kisi_maskesi())
    sahne = _sahne(tmp_path)
    base = np.asarray(Image.open(sahne).convert("RGB"), np.int16)
    cikti = _her_seyi_yeniden_ciz(
        {"image": [("k.png", sahne.read_bytes(), "image/png")], "size": f"{W}x{H}"})

    # Kısıtlamadan ÖNCE yüz, katman hattının fark eşiğini aşacak kadar farklı:
    # filtre gerçekten bir şey yapıyor (Etkisiz bir filtre, olmayan bir
    # filtreden tehlikelidir — §44.8).
    assert np.abs(np.asarray(cikti, np.int16)[:20] - base[:20]).max() \
        > layers.DIFF_THRESHOLD

    out = np.asarray(vton.bolgeye_kisitla(cikti, sahne, "ust"), np.int16)

    assert np.abs(out[:20] - base[:20]).max() == 0, "yüz değişmiş"
    assert np.abs(out[-20:] - base[-20:]).max() == 0, "bacaklar değişmiş"
    assert np.abs(out[100:200, :15] - base[100:200, :15]).max() == 0, "duvar değişmiş"
    assert tuple(out[110, 100]) == KIRMIZI, "kıyafetin kendisi kaybolmuş"


def test_kisi_maskesi_yoksa_yalnizca_bant_korunur(monkeypatch, tmp_path):
    """rembg yoksa: yüz yine korunuyor, ama BANT İÇİNDEKİ duvar korunmuyor.

    Bu bir sınırın kaydı — Foundry yolu kişi maskesiyle (rembg) çok daha temiz.
    """
    monkeypatch.setattr("wardrobe.cutout.person_mask_for", lambda p: None)
    sahne = _sahne(tmp_path)
    base = np.asarray(Image.open(sahne).convert("RGB"), np.int16)
    cikti = _her_seyi_yeniden_ciz(
        {"image": [("k.png", sahne.read_bytes(), "image/png")], "size": f"{W}x{H}"})

    out = np.asarray(vton.bolgeye_kisitla(cikti, sahne, "ust"), np.int16)

    assert np.abs(out[:20] - base[:20]).max() == 0
    assert np.abs(out[100:200, :15] - base[100:200, :15]).max() > 0


def test_model_her_seyi_yeniden_cizse_de_katman_temiz(
        monkeypatch, tmp_path, db_path, openai_var):
    """Asıl iddia, uçtan uca: genel amaçlı düzenleyici katman üretiminde
    kullanılabiliyor — Gemini'yi dışlatan kusur bölge kısıtlamasıyla etkisiz.

    HANGİ İDDİA NEYİ KANITLIYOR — kontrol deneyiyle ölçüldü (kısıtlama
    kapatılıp aynı test koşuldu):

        kısıtlama KAPALI : kaplama %65.0, duvar 2.925 px, "katman çok geniş"
        kısıtlama AÇIK   : kaplama %38.3, duvar 0 px, uyarı yok

    Yüz ve bacaklar İKİ durumda da temiz: onları katman hattının mevcut bölge
    kapısı (§30) zaten koruyor. Bu kısıtlamanın ayırt edici katkısı BANT
    İÇİNDEKİ DUVAR — o yüzden asıl kanıt duvar iddiası. Yüz/bacak iddiaları
    yine duruyor: ikisinin birlikte çalıştığını kilitliyorlar.
    """
    monkeypatch.setattr("wardrobe.layers.LAYER_DIR", tmp_path / "layers")
    (tmp_path / "layers").mkdir(exist_ok=True)
    monkeypatch.setattr("wardrobe.mannequin.MANNEQUIN_DIR", tmp_path / "mannequins")
    (tmp_path / "mannequins").mkdir(exist_ok=True)
    monkeypatch.setattr("wardrobe.mannequin.MANNEQUIN_SIZE", (W, H))
    monkeypatch.setattr("wardrobe.cutout.person_mask_for", lambda p: _kisi_maskesi())
    _foundry_ortami(monkeypatch, image="gpt-image-2")

    mannequin.from_photo(_sahne(tmp_path), db_path=db_path)

    from db import insert_garment
    from tests.conftest import make_garment_photo
    from wardrobe.cutout import remove_background

    foto = make_garment_photo(tmp_path / "gomlek.jpg", color=KIRMIZI)
    kesim = tmp_path / "gomlek.png"
    remove_background(foto, kesim)
    gid = insert_garment(
        {"category": "ust", "subcategory": "gömlek",
         "raw_path": str(foto), "cutout_path": str(kesim)},
        db_path=db_path,
    )

    p, _ = _saglayici(monkeypatch, _her_seyi_yeniden_ciz)
    sonuc = layers.build_layer(gid, provider=p, db_path=db_path)
    assert sonuc["status"] == "ready", sonuc

    alfa = np.asarray(Image.open(sonuc["png_path"]).convert("RGBA"))[:, :, 3]
    assert alfa[:20].max() == 0, "yüz bölgesi katmana girdi"
    assert alfa[-20:].max() == 0, "bacaklar katmana girdi"
    assert alfa[:, :15].max() == 0, "duvar katmana girdi"
    assert alfa[110, 100] > 200, "kıyafetin kendisi katmanda yok"


# --- MAI: Microsoft'un kendi görüntü modelleri (ayrı API) ---

class _SahteMaiYaniti:
    def __init__(self, govde: dict, durum: int = 200):
        self.status_code, self._govde = durum, govde
        self.text = json.dumps(govde)

    def json(self):
        return self._govde


def _mai_sunucusu(monkeypatch, ciz, *, durum: int = 200) -> list:
    """`httpx.post`'u sahteler: çağrıları kaydeder, `ciz(url, kw)` ile görsel döner."""
    import httpx

    cagrilar = []

    def post(url, **kw):
        cagrilar.append((url, kw))
        if durum >= 400:
            return _SahteMaiYaniti({"error": {"message": "erişim reddedildi"}}, durum)
        return _SahteMaiYaniti({"data": [{"b64_json": _b64(ciz(url, kw))}]})

    monkeypatch.setattr(httpx, "post", post)
    return cagrilar


def _mai_kisiyi_ciz(url, kw) -> Image.Image:
    """MAI'nin multipart isteğini `_her_seyi_yeniden_ciz`'in beklediği şekle çevirir."""
    gorseller = [parca for alan, parca in kw["files"] if alan == "image"]
    return _her_seyi_yeniden_ciz({"image": gorseller, "size": f"{W}x{H}"})


def test_mai_dagitimi_adindan_taninir(monkeypatch):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6-Flash")
    assert foundry.image_api() == "mai"
    monkeypatch.setenv("FOUNDRY_IMAGE_DEPLOYMENT", "gpt-image-2")
    assert foundry.image_api() == "openai"
    # Dağıtıma özel ad verildiyse aile açıkça söyleniyor.
    monkeypatch.setenv("FOUNDRY_IMAGE_DEPLOYMENT", "benim-gorsel-modelim")
    monkeypatch.setenv("FOUNDRY_IMAGE_API", "mai")
    assert foundry.image_api() == "mai"


def test_mai_openai_paketi_gerektirmez(monkeypatch):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6-Flash")
    monkeypatch.setitem(sys.modules, "openai", None)   # import → ImportError
    assert vton.FoundryImageProvider().available()
    assert vton.get_provider().name == "foundry"


@pytest.mark.parametrize("dagitim, ayar, beklenen", [
    ("MAI-Image-2.6-Flash", None, True),
    ("MAI-Image-2.5-Flash", None, False),   # 2.5 bu alanı tanımıyor → 400
    ("MAI-Image-2.6", "false", False),
    ("ozel-ad", "true", True),
])
def test_mai_auto_aspect_ayari(monkeypatch, dagitim, ayar, beklenen):
    _foundry_ortami(monkeypatch, image=dagitim)
    if ayar:
        monkeypatch.setenv("FOUNDRY_MAI_AUTO_ASPECT", ayar)
    assert foundry.mai_auto_aspect() is beklenen


def test_mai_giydirme_istegi_dogru_sekilde(monkeypatch, tmp_path):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6-Flash")
    monkeypatch.setattr("wardrobe.cutout.person_mask_for", lambda p: _kisi_maskesi())
    sahne = _sahne(tmp_path)
    kiyafet = tmp_path / "k.png"
    Image.new("RGBA", (80, 80), (*KIRMIZI, 255)).save(kiyafet)
    cagrilar = _mai_sunucusu(monkeypatch, _mai_kisiyi_ciz)

    out = vton.FoundryImageProvider().try_on(sahne, kiyafet, "ust")

    url, kw = cagrilar[0]
    assert url == "https://ornek-kaynak.services.ai.azure.com/mai/v1/images/edits"
    assert kw["headers"] == {"api-key": "test-anahtari"}
    assert [alan for alan, _ in kw["files"]] == ["image", "image"]   # kişi + kıyafet
    assert kw["data"]["model"] == "MAI-Image-2.6-Flash"              # DAĞITIM adı
    assert kw["data"]["prompt"] == vton.giydirme_talimati("ust")
    assert kw["data"]["auto_aspect_ratio"] == "true"
    assert not {"size", "quality", "n", "output_format"} & set(kw["data"])

    # Bölge kısıtlaması MAI'de de devrede: model yüzü değiştirdi, çıktıda yüz
    # base'le birebir aynı.
    base = np.asarray(Image.open(sahne).convert("RGB"), np.int16)
    assert np.abs(np.asarray(out, np.int16)[:20] - base[:20]).max() == 0
    assert out.size == (W, H)


def test_mai_25_istegine_auto_aspect_eklenmez(monkeypatch, tmp_path):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.5-Flash")
    monkeypatch.setattr("wardrobe.cutout.person_mask_for", lambda p: None)
    cagrilar = _mai_sunucusu(monkeypatch, _mai_kisiyi_ciz)

    vton.FoundryImageProvider().try_on(_sahne(tmp_path), _sahne(tmp_path), "ust")

    assert "auto_aspect_ratio" not in cagrilar[0][1]["data"]


def test_mai_duzenleme_tek_gorsel_ve_koruma_eki(monkeypatch, tmp_path):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6")
    cagrilar = _mai_sunucusu(
        monkeypatch, lambda url, kw: Image.new("RGB", (512, 768), (10, 20, 30)))

    out = vton.FoundryImageProvider().edit(_sahne(tmp_path), "roll up the sleeves")

    url, kw = cagrilar[0]
    assert url.endswith("/mai/v1/images/edits")
    assert len(kw["files"]) == 1
    assert kw["data"]["prompt"].startswith("roll up the sleeves")
    assert "Keep the person's identity" in kw["data"]["prompt"]
    assert out.size == (W, H)


def test_mai_manken_uretimi_piksel_sinirina_sigar(monkeypatch):
    """864x1296 (1.12 MP) MAI-2.5'in 1 MP tavanını aşıyor: oran korunarak
    küçültülüp istenir, çıktı istenen boyuta geri ölçeklenir."""
    _foundry_ortami(monkeypatch, image="MAI-Image-2.5")
    cagrilar = _mai_sunucusu(monkeypatch, lambda url, kw: Image.new(
        "RGB", (kw["json"]["width"], kw["json"]["height"]), (1, 2, 3)))

    out = vton.FoundryImageProvider().text_to_image("a person standing", (864, 1296))

    url, kw = cagrilar[0]
    w, h = kw["json"]["width"], kw["json"]["height"]
    assert url.endswith("/mai/v1/images/generations")
    assert w * h <= 1024 * 1024 and min(w, h) >= 768
    assert abs(w / h - 864 / 1296) < 0.01
    assert out.size == (864, 1296)


def test_mai_hatasi_anahtari_sizdirmaz(monkeypatch, tmp_path):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6")
    _mai_sunucusu(monkeypatch, _mai_kisiyi_ciz, durum=401)

    with pytest.raises(RuntimeError) as hata:
        vton.FoundryImageProvider().edit(_sahne(tmp_path), "roll up the sleeves")

    assert "401" in str(hata.value)
    assert "test-anahtari" not in str(hata.value)


# --- doctor ---

def test_doctor_mai_modunu_gosterir(monkeypatch, capsys):
    import cli

    _foundry_ortami(monkeypatch, image="MAI-Image-2.6-Flash")
    cli._doctor_foundry()
    cikti = capsys.readouterr().out

    assert "MAI görüntü API'si" in cikti
    assert "openai paketi" not in cikti           # MAI'de gerekmiyor
    assert "test-anahtari" not in cikti


def test_doctor_foundry_bolumu_anahtari_yazmaz(monkeypatch, capsys):
    import cli

    _foundry_ortami(monkeypatch, claude="claude-opus-5-5", image="gpt-image-2")
    cli._doctor_foundry()
    cikti = capsys.readouterr().out

    assert "ornek-kaynak" in cikti and "gpt-image-2" in cikti
    assert "test-anahtari" not in cikti, "anahtar ekrana yazıldı"


def test_doctor_foundry_ayari_yoksa_sessiz(capsys):
    import cli

    cli._doctor_foundry()
    assert capsys.readouterr().out == ""


# --- komut satırı ---

def test_komut_satiri_foundry_saglayicisini_kabul_ediyor():
    """HANDOFF §48.5 `build-layers --provider foundry` öneriyordu ama argparse
    seçeneği tanımıyordu: belgedeki komut ilk denemede hata verirdi."""
    import cli

    parser = cli.build_parser()
    assert parser.parse_args(
        ["build-layers", "--id", "3", "--provider", "foundry"]).provider == "foundry"
    assert parser.parse_args(
        ["render", "3", "--provider", "foundry"]).provider == "foundry"


# --- Mankene bağlı sağlayıcı (§51.7) ---

def _iki_manken(monkeypatch, tmp_path, db_path) -> tuple[int, int]:
    """Aynı fotoğraftan iki manken: A (sağlayıcısız) ve MAI (foundry). MAI aktif."""
    monkeypatch.setattr("db.DB_PATH", db_path)
    monkeypatch.setattr("wardrobe.mannequin.MANNEQUIN_SIZE", (W, H))
    a = mannequin.from_photo(_sahne(tmp_path), name="A")["mannequin_id"]
    mai = mannequin.from_photo(_sahne(tmp_path), name="MAI")["mannequin_id"]
    mannequin.set_provider(mai, "foundry")
    return a, mai


def test_aktif_mankenin_saglayicisi_secilir(monkeypatch, tmp_path, db_path):
    """Hangi manken aktifse onun sağlayıcısı. Küresel bir ayar, FASHN mankenine
    geçip kıyafet ekleyenin katmanını sessizce MAI ile üretirdi."""
    monkeypatch.setenv("FASHN_API_KEY", "y")
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6")
    a, mai = _iki_manken(monkeypatch, tmp_path, db_path)

    assert vton.get_provider().name == "foundry"     # MAI aktif
    mannequin.set_active(a)
    assert vton.get_provider().name == "fashn"       # A: küresel sıra, FASHN önde


def test_acik_ad_ve_ortam_degiskeni_mankenin_onune_gecer(monkeypatch, tmp_path, db_path):
    _foundry_ortami(monkeypatch, image="MAI-Image-2.6")
    _iki_manken(monkeypatch, tmp_path, db_path)

    assert vton.get_provider("mock").name == "mock"
    monkeypatch.setenv("VTON_PROVIDER", "mock")
    assert vton.get_provider().name == "mock"


def test_manken_saglayicisi_dogrulanir_ve_kaldirilabilir(monkeypatch, tmp_path, db_path):
    _, mai = _iki_manken(monkeypatch, tmp_path, db_path)

    with pytest.raises(ValueError):
        mannequin.set_provider(mai, "olmayan-saglayici")
    assert mannequin.provider_for(mai) == "foundry"
    mannequin.set_provider(mai, None)
    assert mannequin.provider_for(mai) is None
    assert vton.get_provider().name == "mock"        # anahtar yok → küresel sıra
