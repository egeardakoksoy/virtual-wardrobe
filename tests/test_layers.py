"""Katman çıkarımı ve birleştirme — Faz 1'in çekirdeği.

Buradaki asıl iddia: manken sabit olduğu için "değişen pikseller = kıyafet".
Bu doğruysa ayrı bir segmentasyon modeline gerek kalmıyor.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from wardrobe import layers, mannequin, vton


def _base(size=(200, 400), color=(200, 200, 205)) -> Image.Image:
    return Image.new("RGB", size, color)


def _dressed(base: Image.Image, box, color=(200, 40, 45)) -> Image.Image:
    out = base.copy()
    out.paste(Image.new("RGB", (box[2] - box[0], box[3] - box[1]), color), box[:2])
    return out


# --- extract_layer ---

def test_degisen_bolge_katman_olur():
    base = _base()
    dressed = _dressed(base, (60, 100, 140, 220))
    layer = layers.extract_layer(base, dressed)

    assert layer.mode == "RGBA"
    alpha = np.asarray(layer.split()[3])
    assert alpha[160, 100] > 128, "değişen bölge opak olmalı"
    assert alpha[20, 20] < 128, "değişmeyen bölge şeffaf olmalı"


def test_yuksek_kontrast_katmani_yakalar():
    """int16 taşması regresyonu.

    Beyaz manken + siyah kıyafet, kanal farkı 255. int16 aritmetiğinde
    255² = 65025 taşıp negatife dönüyor, sqrt NaN veriyor, NaN > eşik her
    zaman False — yani katman sessizce boşalıyordu. Üstelik bu tam olarak
    ayırt edilmesi EN KOLAY durumda oluyordu.
    """
    base = _base(color=(255, 255, 255))
    dressed = _dressed(base, (60, 100, 140, 260), color=(0, 0, 0))
    layer = layers.extract_layer(base, dressed)

    alpha = np.asarray(layer.split()[3])
    assert not np.isnan(alpha).any()
    assert alpha[180, 100] > 128, "en yüksek kontrastlı fark kaçırıldı"
    assert layers.layer_coverage(layer) > 0.15


def test_hic_degismezse_katman_bos_cikar():
    base = _base()
    layer = layers.extract_layer(base, base.copy())
    assert layers.layer_coverage(layer) < 0.01


def test_kaplama_orani_degisen_alanla_orantili():
    base = _base(size=(200, 400))
    dressed = _dressed(base, (50, 100, 150, 300))   # 100x200 = %25
    ratio = layers.layer_coverage(layers.extract_layer(base, dressed))
    assert 0.18 < ratio < 0.32


def test_kucuk_gurultu_temizlenir():
    """Difüzyon çıktısı mankenin geri kalanını milimetrik oynatıyor.

    Tek tük piksellik fark katmana girmemeli — yoksa katman kenarlarında
    serpinti oluyor.
    """
    base = _base()
    noisy = base.copy()
    for xy in [(10, 10), (30, 60), (150, 300), (90, 20)]:
        noisy.putpixel(xy, (255, 0, 0))

    assert layers.layer_coverage(layers.extract_layer(base, noisy)) < 0.005


def test_kiyafetin_icindeki_delik_doldurulur():
    """Kıyafetin rengi tene yakın olan noktada fark zayıflıyor → delik.

    Kapama (closing) bunu doldurmalı, yoksa katmanda mankenin teni görünüyor.
    """
    base = _base()
    dressed = _dressed(base, (60, 100, 140, 260))
    # Kıyafetin ortasına mankenin renginde küçük bir leke
    dressed.paste(Image.new("RGB", (6, 6), (200, 200, 205)), (98, 178))

    alpha = np.asarray(layers.extract_layer(base, dressed).split()[3])
    assert alpha[181, 101] > 128, "katmanda delik kaldı"


def test_kiyafet_disindaki_serpinti_atilir():
    """VTON modeli tüm görüntüyü yeniden üretiyor, sadece kıyafeti değil.

    Ölçtük (#5, gerçek fal çıktısı): bir tişört katmanının %5'i bacak
    bölgesindeydi ve alfa 255'e kadar çıkıyordu. Faz 2'de tişört (z=30)
    şortun (z=20) üstüne çizildiği için o lekeler şortu deliyor.
    """
    base = _base(size=(200, 400))
    dressed = _dressed(base, (60, 80, 140, 200))          # gövde: kıyafet
    dressed.paste(Image.new("RGB", (14, 14), (90, 90, 95)), (70, 330))   # bacak lekesi
    dressed.paste(Image.new("RGB", (14, 14), (90, 90, 95)), (120, 360))  # bacak lekesi

    alpha = np.asarray(layers.extract_layer(base, dressed, category="ust").split()[3])

    assert alpha[140, 100] > 128, "kıyafetin kendisi silinmiş"
    assert alpha[336, 77] < 128, "bacaktaki leke katmanda kaldı"
    assert alpha[366, 127] < 128, "bacaktaki leke katmanda kaldı"


def test_scipy_yoksa_bant_yedegi_devreye_girer(monkeypatch):
    """Bileşen etiketleme olmadan da bacak serpintisi engellenmeli."""
    monkeypatch.setattr("wardrobe.layers.has_scipy", lambda: False)

    base = _base(size=(200, 400))
    dressed = _dressed(base, (60, 80, 140, 200))
    dressed.paste(Image.new("RGB", (14, 14), (90, 90, 95)), (70, 360))

    alpha = np.asarray(layers.extract_layer(base, dressed, category="ust").split()[3])
    assert alpha[140, 100] > 128
    assert alpha[366, 77] < 128, "bant yedeği bacak bölgesini kesmedi"


def test_scipy_yoksa_pantolon_pacadan_kesilmez(monkeypatch):
    """Yedek bant eskiden mock'un kutusunu kullanıyordu (alt: %42–%96) ve
    pantolonu %96'da kesiyordu — dış denemede manken kapri giymiş gibiydi
    (§57). Ölçülmüş bant (alt: %46–%100) paçayı korumalı."""
    monkeypatch.setattr("wardrobe.layers.has_scipy", lambda: False)

    base = _base(size=(200, 400))
    dressed = _dressed(base, (60, 200, 140, 400), color=(120, 100, 80))   # pantolon

    alpha = np.asarray(layers.extract_layer(base, dressed, category="alt").split()[3])
    assert alpha[300, 100] > 128, "pantolonun kendisi silinmiş"
    assert alpha[392, 100] > 128, "paça kesildi (yedek bant %96'da bitiyor)"


def test_kategori_verilmezse_ham_maske_korunur():
    """Geriye dönük uyum: kategori bilinmiyorsa agresif kesme yapma."""
    base = _base(size=(200, 400))
    dressed = _dressed(base, (60, 80, 140, 200))
    layer = layers.extract_layer(base, dressed)
    assert layers.layer_coverage(layer) > 0.05


def test_farkli_boyuttaki_cikti_olceklenir():
    """Sağlayıcı farklı çözünürlük dönerse hizalama bozulmamalı."""
    base = _base(size=(200, 400))
    dressed = _dressed(_base(size=(400, 800)), (120, 200, 280, 440))
    layer = layers.extract_layer(base, dressed)
    assert layer.size == base.size


# --- build_layer / DB akışı ---

@pytest.fixture
def wardrobe(db_path, tmp_path, monkeypatch):
    """Küçük bir dolap + placeholder manken + izole katman dizini."""
    monkeypatch.setattr("wardrobe.layers.LAYER_DIR", tmp_path / "layers")
    (tmp_path / "layers").mkdir(exist_ok=True)
    monkeypatch.setattr("wardrobe.mannequin.MANNEQUIN_DIR", tmp_path / "mannequins")
    (tmp_path / "mannequins").mkdir(exist_ok=True)
    monkeypatch.setattr("wardrobe.mannequin.MANNEQUIN_SIZE", (200, 400))

    mannequin.placeholder(db_path=db_path)

    from db import insert_garment
    from tests.conftest import make_garment_photo
    from wardrobe.cutout import remove_background

    ids = {}
    for name, category in [("gomlek", "ust"), ("pantolon", "alt"),
                           ("sneaker", "ayakkabi")]:
        photo = make_garment_photo(tmp_path / f"{name}.jpg", color=(40, 90, 190))
        cutout = tmp_path / f"{name}.png"
        remove_background(photo, cutout)
        ids[category] = insert_garment(
            {"category": category, "subcategory": name, "raw_path": str(photo),
             "cutout_path": str(cutout)},
            db_path=db_path,
        )
    return ids


def test_katman_uretilir_ve_kaydedilir(wardrobe, db_path):
    from pathlib import Path

    result = layers.build_layer(
        wardrobe["ust"], provider=vton.MockProvider(), db_path=db_path
    )
    assert result["status"] == "ready"
    assert Path(result["png_path"]).is_file()
    assert Image.open(result["png_path"]).mode == "RGBA"


def test_z_index_kategoriden_gelir(wardrobe, db_path):
    ust = layers.build_layer(wardrobe["ust"], provider=vton.MockProvider(),
                             db_path=db_path)
    alt = layers.build_layer(wardrobe["alt"], provider=vton.MockProvider(),
                             db_path=db_path)
    assert alt["z_index"] < ust["z_index"], "alt giyim üstün altında çizilmeli"


def test_aksesuar_kaplama_esigi_AYRI(wardrobe, db_path):
    """Tek eşik aksesuarda ters tepiyor.

    Bir saat 864x1296'lık tuvalin ~%0.2'sini kaplıyor. Kıyafet eşiğiyle
    (%0.8) katman doğru üretilmiş olsa bile "neredeyse boş — giydirilememiş
    olabilir" uyarısı alınıyordu: sayı doğru, yorumu yanlış.
    """
    kiyafet_alt, kiyafet_ust = layers.coverage_range("ust")
    aksesuar_alt, aksesuar_ust = layers.coverage_range("aksesuar")

    assert aksesuar_alt < kiyafet_alt, "aksesuar tabanı daha düşük olmalı"
    assert aksesuar_ust < kiyafet_ust, "aksesuar tavanı daha düşük olmalı"
    # %0.2'lik bir saat katmanı uyarı ÜRETMEMELİ
    assert aksesuar_alt < 0.002 < aksesuar_ust
    # ama kıyafet eşiğine göre üretirdi — düzeltmenin sebebi bu
    assert 0.002 < kiyafet_alt


def test_bilinmeyen_kategori_varsayilan_araligi_alir():
    assert layers.coverage_range(None) == (layers.MIN_LAYER_COVERAGE,
                                           layers.MAX_LAYER_COVERAGE)
    assert layers.coverage_range("ust") == (layers.MIN_LAYER_COVERAGE,
                                            layers.MAX_LAYER_COVERAGE)


def test_ayakkabi_unsupported_olarak_isaretlenir(wardrobe, db_path):
    """Sessizce başarısız olmak yerine nedeni kayda geçmeli."""
    result = layers.build_layer(
        wardrobe["ayakkabi"], provider=vton.MockProvider(), db_path=db_path
    )
    assert result["status"] == "unsupported"
    assert "sanal deneme modeli yok" in result["error"]


def test_hazir_katman_tekrar_uretilmez(wardrobe, db_path):
    layers.build_layer(wardrobe["ust"], provider=vton.MockProvider(),
                       db_path=db_path)
    again = layers.build_layer(wardrobe["ust"], provider=vton.MockProvider(),
                               db_path=db_path)
    assert again.get("skipped") is True


def test_force_ile_yeniden_uretilir(wardrobe, db_path):
    layers.build_layer(wardrobe["ust"], provider=vton.MockProvider(),
                       db_path=db_path)
    again = layers.build_layer(wardrobe["ust"], provider=vton.MockProvider(),
                               force=True, db_path=db_path)
    assert not again.get("skipped")
    assert again["status"] == "ready"


def test_saglayici_patlarsa_failed_kaydedilir(wardrobe, db_path):
    """100 kıyafetlik üretimde 7. kıyafet yüzünden durmak istemiyoruz."""
    class Patlayan:
        name = "patlayan"

        def available(self):
            return True

        def try_on(self, *a, **k):
            raise RuntimeError("ağ koptu")

    result = layers.build_layer(wardrobe["ust"], provider=Patlayan(),
                                db_path=db_path)
    assert result["status"] == "failed"
    assert "ağ koptu" in result["error"]


def test_build_all_tum_dolabi_gezer(wardrobe, db_path):
    results = layers.build_all(provider=vton.MockProvider(), db_path=db_path)
    assert len(results) == 3
    counts = layers.status_counts(db_path=db_path)
    assert counts.get("ready") == 2      # üst + alt
    assert counts.get("unsupported") == 1  # ayakkabı


def test_olmayan_kiyafet_temiz_hata(db_path):
    result = layers.build_layer(9999, provider=vton.MockProvider(),
                                db_path=db_path)
    assert result["status"] == "failed"


# --- compose ---

def test_compose_katmanlari_bindirir(wardrobe, db_path):
    layers.build_all(provider=vton.MockProvider(), db_path=db_path)
    out = layers.compose([wardrobe["ust"], wardrobe["alt"]], db_path=db_path)
    assert out.size == (200, 400)
    assert out.mode == "RGBA"


def test_compose_hazir_olmayani_atlar(wardrobe, db_path):
    """Katmanı üretilmemiş kıyafet kombine sessizce girmemeli."""
    base = layers.compose([], db_path=db_path)
    only_missing = layers.compose([wardrobe["ayakkabi"]], db_path=db_path)
    assert np.array_equal(np.asarray(base), np.asarray(only_missing))


# --- Kenar davranışı ---
#
# Ölçülmüş bir kusurdan geliyor: katmanın en dış piksel sırası kıyafet değil,
# kıyafetin arkasındaki şeyle karışımıydı ve bindirmede renkli bir halka
# olarak görünüyordu (sarı tişörtün etek ucunda siyah çizgi).

def test_maske_silueti_asiri_sismiyor():
    """Açma/kapama çekirdekleri eşit olmalı; değilse siluet sessizce şişer.

    Eski kod Min(3)+Max(5) ve Max(5)+Min(3) kullanıyordu — isimleri "açma" ve
    "kapama" ama aritmetiği net +2 px. Fazladan gelen piksel sırası kıyafete
    ait olmayan renkler taşıyordu.
    """
    base = _base()
    box = (60, 100, 140, 220)
    layer = layers.extract_layer(base, _dressed(base, box))

    alpha = np.asarray(layer.split()[3])
    ys, xs = np.nonzero(alpha > 128)

    # Eşik, kıyafetin yumuşak kenarında aşılamadığı için 1 px genişletme
    # bilinçli. 2 px ve üstü regresyondur.
    assert box[0] - xs.min() <= 1, "siluet sola fazla taşmış"
    assert xs.max() - (box[2] - 1) <= 1, "siluet sağa fazla taşmış"
    assert box[1] - ys.min() <= 1, "siluet yukarı fazla taşmış"
    assert ys.max() - (box[3] - 1) <= 1, "siluet aşağı fazla taşmış"


def test_kenar_pikselleri_kiyafetin_rengini_alir():
    """decontaminate_edges: şekli bozmadan kenarın rengini içeriden tazeler."""
    base = _base(color=(240, 240, 240))
    box = (60, 100, 140, 220)
    dressed = _dressed(base, box, color=(200, 40, 45))

    # Kıyafetin kenarına, arkasıyla karışmış koyu bir sıra ekle (anti-aliasing
    # taklidi) — gerçek çıktıda VTON bunu kendisi üretiyor.
    px = dressed.load()
    for x in range(box[0], box[2]):
        px[x, box[3] - 1] = (20, 10, 10)

    layer = layers.extract_layer(base, dressed)
    rgb = np.asarray(layer.convert("RGB"))
    alpha = np.asarray(layer.split()[3])

    kenar = rgb[box[3] - 1, box[0] + 10:box[2] - 10]
    assert alpha[box[3] - 1, box[0] + 20] > 128, "kenar hâlâ katmanın parçası olmalı"
    assert kenar[:, 0].mean() > 120, (
        "kenar pikselleri kıyafetin kırmızısını almalı, karışımın koyusunu değil"
    )


def test_decontaminate_sekli_degistirmez():
    keep = np.zeros((60, 60), dtype=bool)
    keep[15:45, 15:45] = True
    rgb = np.full((60, 60, 3), 200, dtype=np.uint8)

    out = layers.decontaminate_edges(rgb, keep)

    assert out.shape == rgb.shape
    assert (out[~keep] == rgb[~keep]).all(), "maske dışına dokunmamalı"


def test_decontaminate_ince_kiyafette_geri_ceker():
    """Derin iç bölge yoksa (çok ince katman) renk tazelenecek kaynak yok."""
    keep = np.zeros((40, 40), dtype=bool)
    keep[20:22, 5:35] = True          # 2 px kalınlığında şerit
    rgb = np.full((40, 40, 3), 128, dtype=np.uint8)
    rgb[20:22, 5:35] = 77

    out = layers.decontaminate_edges(rgb, keep)

    assert (out == rgb).all(), "iç bölge yoksa görüntü olduğu gibi dönmeli"


# --- Base sızıntısı filtresi ---

def test_base_sizintisi_filtresi_uzak_kiyafette_calisir():
    """Base'in rengine yakın pikseller atılır."""
    import numpy as np

    base_pal = np.array([[67, 96, 144]], dtype=np.int16)
    kiyafet_pal = np.array([[200, 40, 45]], dtype=np.int16)   # base'den çok uzak

    mask = np.ones((10, 10), dtype=bool)
    rgb = np.full((10, 10, 3), (200, 40, 45), dtype=np.uint8)
    rgb[0:3] = (67, 96, 144)                                   # sızıntı bandı

    out = layers.drop_base_clothing(mask, rgb, base_pal, kiyafet_pal)

    assert not out[0:3].any(), "base rengindeki pikseller atılmalı"
    assert out[4:].all(), "kıyafet pikselleri korunmalı"


def test_base_sizintisi_filtresi_yakin_kiyafette_uygulanmaz():
    """Kıyafet base'in rengine yakınsa filtre gerçek kıyafeti yerdi.

    Ölçülmüş durum: lacivert tişört mavi base'e 41 birim uzakta; filtre
    uygulansa katmanın %28'ini siliyordu. Bu senaryoda sızıntı zaten
    görünmez, çünkü sızan renk kıyafetin rengine benziyor.
    """
    import numpy as np

    base_pal = np.array([[67, 96, 144]], dtype=np.int16)
    kiyafet_pal = np.array([[75, 100, 150]], dtype=np.int16)   # base'e çok yakın

    mask = np.ones((10, 10), dtype=bool)
    rgb = np.full((10, 10, 3), (70, 98, 146), dtype=np.uint8)

    out = layers.drop_base_clothing(mask, rgb, base_pal, kiyafet_pal)

    assert out.all(), "güvenlik kuralı devredeyken maske değişmemeli"


# --- Kenar kalitesi ---
#
# Kullanıcı kombinlerde iki kusur bildirdi: kenarların merdiven gibi tırtıklı
# olması ve siluet boyunca zeminin sızdığı ince şeritler. Aşağıdakiler o iki
# davranışı kilitliyor.

def test_kenar_yumusatilmis_olmali():
    """Alfa 0'dan 255'e bir anda sıçramamalı — yoksa kenar basamaklı görünür."""
    base = _base()
    layer = layers.extract_layer(base, _dressed(base, (60, 100, 140, 220)))

    alpha = np.asarray(layer.split()[3])
    yari = ((alpha > 0) & (alpha < 255)).sum()

    assert yari > 50, (
        f"yarı saydam kenar pikseli yok ({yari}) — anti-alias devre dışı kalmış"
    )


def test_kucuk_centikler_kapatilir():
    """Kontur pürüzsüzleştirme, kenardaki 1-2 px'lik çentikleri kapatmalı.

    Bu çentikler base sızıntısı silinirken oluşuyor; kapatılmazsa bindirmede
    siluet boyunca zeminin göründüğü tırtıklı şeritler olarak beliriyor.
    """
    base = _base()
    box = (60, 100, 140, 220)
    dressed = _dressed(base, box)

    # Kenara testere dişi aç: her iki pikselde bir 2 px içeri gir
    px = dressed.load()
    for y in range(box[1], box[3], 2):
        for x in range(box[2] - 2, box[2]):
            px[x, y] = base.getpixel((x, y))

    alpha = np.asarray(layers.extract_layer(base, dressed).split()[3])

    # Kenar sütunundaki opak piksel sayısı, dişlerin yarısını kaybetmemeli
    sutun = alpha[box[1] + 5:box[3] - 5, box[2] - 3]
    assert (sutun > 128).mean() > 0.8, "testere dişleri kapanmamış"


def test_base_sizintisi_puruzsuzlestirmeden_once_silinir():
    """Sıra kuralı: silme → pürüzsüzleştirme.

    Ters sırada silmenin açtığı çentikler kapanmadan kalıyor; silme
    pürüzsüzleştirmeden sonra yapılırsa da kenar tırtıklı çıkıyor. Bu test
    sızıntının gerçekten silindiğini ve kenarın yine de düzgün kaldığını
    birlikte doğruluyor.
    """
    base = Image.new("RGB", (200, 400), (250, 250, 250))
    # base'in "kıyafeti": gövde bandında belirgin mavi
    bp = base.load()
    for y in range(150, 300):
        for x in range(85, 125):
            bp[x, y] = (67, 96, 144)

    dressed = base.copy()
    dp = dressed.load()
    for y in range(100, 240):                 # sarı kıyafet
        for x in range(60, 140):
            dp[x, y] = (220, 200, 40)
    for y in range(232, 240):                 # altında base renginde sızıntı bandı
        for x in range(60, 140):
            dp[x, y] = (67, 96, 144)

    cut = Image.new("RGBA", (40, 40), (220, 200, 40, 255))
    yol = Path(__file__).parent / "_gecici_cutout.png"
    cut.save(yol)
    try:
        layer = layers.extract_layer(base, dressed, cutout_path=yol)
    finally:
        yol.unlink(missing_ok=True)

    arr = np.asarray(layer)
    opak = arr[..., 3] > 128
    mavi = opak & (arr[..., 2].astype(int) - arr[..., 0].astype(int) > 25)

    assert mavi.sum() < 60, f"sızıntı bandı katmanda kalmış ({mavi.sum()} piksel)"
    assert opak[150, 100], "kıyafetin gövdesi korunmalı"


# --- base_conflict: ücretli çağrı öncesi ücretsiz ön kontrol ---

def test_base_conflict_ayni_renkte_zayif_der_ama_ENGELLEMEZ(db_path, tmp_path):
    """Aynı renkte uyarı verir ama üretimi DURDURMAZ.

    ⚠ Bu test bir davranış değişikliğini kilitliyor. Eskiden `ok=False` dönüp
    ücretli çağrıyı hiç yaptırmıyordu ve gerekçesi ölçülmüştü — ama fal/v1.6
    ile: uzaklık 9 → kaplama %0.6, katman gerçekten boştu.

    tryon-max'te aynı bantta katman ÇIKIYOR: uzaklık 1.0'daki lacivert tişört
    üretildi, kaplama tipiğin ~%65'i ve görsel olarak temiz. Yani engel,
    çalışan bir işlemi yanlış bir tahminle durduruyordu.

    Eşiğin yeniden kalibre edilmesi §25.5'in dersi: bir ölçümün geçerliliği,
    ölçüldüğü koşulların hâlâ geçerli olmasına bağlı.
    """
    base = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 120)).save(base)
    mannequin.from_photo(base, db_path=db_path)

    cut = tmp_path / "c.png"
    Image.new("RGBA", (80, 80), (72, 92, 122, 255)).save(cut)

    sonuc = layers.base_conflict(cut, db_path=db_path)
    assert sonuc["ok"] is True, "aynı renk üretimi engellememeli"
    assert sonuc["level"] == "zayıf"
    assert sonuc["distance"] < layers.LOW_CONTRAST_DISTANCE
    assert sonuc["note"], "zayıf sinyalde kullanıcıya sebebi söylenmeli"


def test_base_conflict_hicbir_zaman_engellemiyor(db_path, tmp_path):
    """`ok` her koşulda True — ücretli çağrıyı durduran tek karar noktası yok.

    Ölçümde çökme gözlenmediği sürece tahmine dayanıp kullanıcıyı durdurmak,
    ücretli çağrıyı boşa harcamaktan daha kötü: kullanıcı çalışacak bir şeyi
    yapamıyor ve sebebi de yanlış.
    """
    base = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 120)).save(base)
    mannequin.from_photo(base, db_path=db_path)

    for renk in [(70, 90, 120), (75, 95, 125), (150, 150, 150), (230, 210, 40)]:
        cut = tmp_path / f"c{renk[0]}.png"
        Image.new("RGBA", (80, 80), renk + (255,)).save(cut)
        assert layers.base_conflict(cut, db_path=db_path)["ok"] is True


def test_base_conflict_uzak_renkte_uygun_der(db_path, tmp_path):
    base = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (70, 90, 120)).save(base)
    mannequin.from_photo(base, db_path=db_path)

    cut = tmp_path / "c.png"
    Image.new("RGBA", (80, 80), (230, 210, 40, 255)).save(cut)

    sonuc = layers.base_conflict(cut, db_path=db_path)
    assert sonuc["ok"] is True
    assert sonuc["level"] == "uygun"


def test_palet_kisi_maskesiyle_sinirlanabiliyor(tmp_path):
    """`person` verilince örnekleme kişiyle kesişiyor; verilmezse eski davranış.

    ⚠ Ölçüm notu: gerçek dolapta bu parametrenin PALETİ DEĞİŞTİRMEDİĞİ ölçüldü
    (iki mankende de kayma 0.0). Sabit örnekleme kutusu manken 2'de örneklerin
    %7.2'sini duvardan alıyor ama `_palet` en kalabalık kovaları seçtiği için
    %7'lik azınlık ilk 5'e giremiyor. Mekanizma yine de duruyor: figürün çok
    küçük kaldığı bir mankende kutu çoğunlukla duvara düşerse gerekli olacak.
    """
    from wardrobe.layers import base_clothing_palette

    # Kurulum: örnekleme kutuları y %36-52 ve %64-74'te. Kişi YALNIZCA üst
    # kutunun bulunduğu yerde ve orası tamamen kıyafet; alt kutu duvara düşüyor.
    arr = np.full((300, 200, 3), 210, dtype=np.uint8)     # her yer "duvar"
    kisi = np.zeros((300, 200), dtype=bool)
    kisi[100:165, 80:130] = True
    arr[kisi] = (30, 40, 90)                             # kişinin üstü = kıyafet

    maskesiz = base_clothing_palette(arr)
    maskeli = base_clothing_palette(arr, person=kisi)

    assert any(p.mean() > 180 for p in maskesiz), (
        "test kurulumu: maskesiz palet duvarı ALMALIYDI")
    assert maskeli.size, "palet boş"
    assert not any(p.mean() > 180 for p in maskeli), (
        "kişi maskesine rağmen duvar palete girmiş")


def test_palet_maske_kutuyu_yerse_kutuya_donuyor(tmp_path):
    """Güvenlik freni: maske örnekleme kutusunu neredeyse tamamen yerse
    kutuya dönülmeli.

    Boş palet, ona dayanan her şeyi — kör nokta kontrolü, sızıntı filtresi —
    SESSİZCE devre dışı bırakır. §16'daki `_harden_alpha` dersinin aynısı.
    """
    from wardrobe.layers import base_clothing_palette

    arr = np.full((300, 200, 3), 120, dtype=np.uint8)
    bos = np.zeros((300, 200), dtype=bool)                # kişi hiç yok
    assert base_clothing_palette(arr, person=bos).size, "fren devreye girmedi"


def test_iki_catisma_fonksiyonu_ayri_soruya_cevap_veriyor(db_path, tmp_path):
    """`base_conflict` GERÇEK fotoğrafa, `extraction_conflict` ÇIKARIM base'ine.

    ⚠ Bunlar bir zamanlar tek fonksiyondu ve çıkarım base'i eklenince (§44)
    bir cevabı yanlışa döndü. Aynı kıyafette zıt cevap verebiliyorlar ve
    ikisi de kendi sorusu için doğru:

      · zemin seçimi   → delikten mankenin GERÇEK kıyafeti görünüyor
      · yükleme uyarısı → VTON ve fark ÇIKARIM base'ine karşı çalışıyor

    Ölçüldü (manken 2, #14 lacivert tişört): gerçek fotoğrafa 1.0, yeşil
    çıkarım base'ine 107.0.
    """
    from wardrobe import mannequin

    # Mankenin kıyafeti KOYU MAVİ
    arr = np.full((600, 400, 3), 240, dtype=np.uint8)
    arr[200:420, 140:260] = (30, 40, 90)
    foto = tmp_path / "m.png"
    Image.fromarray(arr).save(foto)
    mannequin.from_photo(foto, db_path=db_path)

    # Kıyafet de KOYU MAVİ → gerçek fotoğrafa yakın
    cut = tmp_path / "c.png"
    Image.new("RGBA", (80, 80), (32, 42, 92, 255)).save(cut)

    yakin = layers.base_conflict(cut, db_path=db_path)
    assert yakin["level"] == "zayıf", "gerçek fotoğrafla karşılaştırma bozuk"

    # Çıkarım base'i üretilince aynı kıyafet UZAK olmalı (yeşile boyanıyor)
    mannequin.build_extract_base(db_path=db_path)
    uzak = layers.extraction_conflict(cut, db_path=db_path)

    assert uzak["distance"] > yakin["distance"] * 5, (
        "extraction_conflict hâlâ gerçek fotoğrafa bakıyor")
    assert uzak["level"] == "uygun"


def test_cikarim_basei_yoksa_iki_fonksiyon_ayni_cevabi_veriyor(db_path, tmp_path):
    """Eski kurulumda (çıkarım base'i yok) ikisi de gerçek fotoğrafa bakar."""
    from wardrobe import mannequin

    Image.new("RGB", (400, 600), (70, 96, 150)).save(tmp_path / "m.png")
    mannequin.from_photo(tmp_path / "m.png", db_path=db_path)
    cut = tmp_path / "c.png"
    Image.new("RGBA", (80, 80), (72, 98, 152, 255)).save(cut)

    assert (layers.base_conflict(cut, db_path=db_path)["distance"]
            == layers.extraction_conflict(cut, db_path=db_path)["distance"])


def test_cikarim_rengi_katmandan_siliniyor():
    """Sentetik çıkarım base'inin rengi bindirmede GÖRÜNMEMELİ.

    §44'te çıkarım base'inin kıyafeti chroma yeşile boyanıyor; modelin bıraktığı
    birkaç yüz yeşil piksel katmana girip ekranda nokta olarak görünüyordu
    (#10: 51 px çenede, #16: 205 px). Ölçüm sonrası temizlendi: 51→0, 205→0.

    Bu filtre öncekilerden farklı olarak RİSKSİZ — aradığı renk gerçek değil,
    biz koyduk. Sızan yeşilin palete uzaklığı medyan 60, kıyafetlerinki en az
    107; tolerans 78 aradan geçiyor.
    """
    yesil_palet = np.array([[6, 130, 6], [46, 189, 46]], dtype=np.int16)
    kiyafet_palet = np.array([[30, 40, 90], [40, 55, 110]], dtype=np.int16)

    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    rgb[:, :5] = (20, 112, 20)     # sızan yeşil (palete ~19 uzaklıkta)
    rgb[:, 5:] = (30, 40, 90)      # gerçek kıyafet
    keep = np.ones((10, 10), dtype=bool)

    out = layers.drop_extract_color(keep, rgb, yesil_palet, kiyafet_palet)

    assert not out[:, :5].any(), "sızan yeşil silinmedi"
    assert out[:, 5:].all(), "gerçek kıyafet silinmiş"


def test_yesil_kiyafette_filtre_kendini_durduruyor():
    """Gerçekten yeşil bir kıyafet gelirse filtre ATLANMALI.

    Aksi halde kıyafetin kendisini siler. Güvenlik kuralı §7.6'daki
    `drop_base_clothing` simetrisinin aynısı.
    """
    yesil_palet = np.array([[6, 130, 6]], dtype=np.int16)
    yesil_kiyafet = np.array([[20, 140, 20]], dtype=np.int16)

    rgb = np.full((10, 10, 3), (20, 140, 20), dtype=np.uint8)
    keep = np.ones((10, 10), dtype=bool)

    out = layers.drop_extract_color(keep, rgb, yesil_palet, yesil_kiyafet)
    assert out.all(), "yeşil kıyafette filtre kendini durdurmadı"


# --- Ham çıktının gösterime hazırlanması (§44'ün görünür yüzü) ---

def _uc_katmanli_sahne(kiyafet, ust=None, w=200, h=400):
    """Kıyafet bandı `base_clothing_palette`ın örneklediği kutuları kapsıyor."""
    a = np.full((h, w, 3), 235, dtype=np.uint8)
    a[120:320, 60:140] = kiyafet
    if ust is not None:
        a[120:220, 60:140] = ust
    return Image.fromarray(a)


def test_ham_ciktidaki_cikarim_rengi_gercek_fotoyla_degisiyor():
    """Tek kıyafet görünümünde kullanıcı YEŞİL GÖRMEMELİ.

    §38 tek kıyafette ham VTON çıktısını gösteriyor — katman bindirmesinin
    çıkarım kusurlarını taşımadığı için doğru karar. Ama §44'ten sonra ham
    çıktı YEŞİL çıkarım base'ine karşı üretiliyor, yani kıyafetin örtmediği
    her yerde base'in boyanmış kıyafeti duruyor: üst giydirilince şort,
    alt giydirilince tişört yeşil çıkıyordu.

    Geometri birebir aynı olduğu için (çıkarım base'i gerçek fotoğrafın
    yalnızca yeniden renklendirilmiş hâli) düzeltme piksel piksel yapılabiliyor.
    """
    extract = _uc_katmanli_sahne((20, 150, 20))                 # boyanmış base
    gercek = _uc_katmanli_sahne((180, 40, 40))                  # gerçek fotoğraf
    ham = _uc_katmanli_sahne((20, 150, 20), (30, 40, 120))      # VTON: üste mavi

    out = np.asarray(layers.restore_extract_color(
        ham, gercek, extract, np.array([[30, 40, 120]], dtype=np.int16)))

    alt = out[280, 100]
    assert int(alt[0]) > 140 and int(alt[1]) < 80, (
        f"yeşil gerçek fotoğrafla değişmedi: {alt}")
    ust_px = out[160, 100]
    assert int(ust_px[2]) > 95 and int(ust_px[0]) < 70, (
        f"giydirilen kıyafet bozuldu: {ust_px}")


def test_geri_yukleme_yesil_kiyafette_kendini_durduruyor():
    """Gerçekten yeşil bir kıyafet gelirse hiç dokunulmamalı.

    `drop_extract_color`'daki güvenlik kuralının aynısı: aksi halde kıyafetin
    kendisi gerçek fotoğrafla silinirdi.
    """
    extract = _uc_katmanli_sahne((20, 150, 20))
    gercek = _uc_katmanli_sahne((180, 40, 40))
    ham = _uc_katmanli_sahne((20, 150, 20))

    out = layers.restore_extract_color(
        ham, gercek, extract, np.array([[25, 155, 25]], dtype=np.int16))

    assert np.array_equal(np.asarray(out), np.asarray(ham)), (
        "yeşil kıyafette geri yükleme kendini durdurmadı")


def test_kenardaki_anti_alias_sacagi_da_temizleniyor():
    """Eşiğin tam kendisi yetmiyor — saçak genişletme ile kapanıyor.

    Yeşil bölgenin dış sınırındaki pikseller yeşille komşusunun karışımı
    olduğu için palete uzaklıkları eşiğin ÜSTÜNDE kalıyor ve yerinde
    duruyorlardı; ekranda kıyafeti saran ince neon bir kontur olarak
    görünüyordu. Ölçüldü: genişletmesiz 1.267 px, 3 px genişletmeyle 0.
    """
    def _yesillik(a):
        """Palete BAKMAYAN ölçüt: yeşil kanal diğer ikisini ne kadar geçiyor.

        Filtrenin kendi eşiğiyle ölçmek dairesel olurdu — 78 ile silip 78 ile
        ölçmek her zaman 0 verir (§34.1'in hatası). Bu ölçüt bağımsız.
        """
        b = a[118:120, 60:140].astype(int)
        return int((b[:, :, 1] - np.maximum(b[:, :, 0], b[:, :, 2])).max())

    extract = _uc_katmanli_sahne((20, 150, 20))
    gercek = _uc_katmanli_sahne((180, 40, 40))
    ham = np.asarray(_uc_katmanli_sahne((20, 150, 20))).copy()
    # Sınırdaki ara ton: yeşille duvarın karışımı, eşiğin DIŞINDA kalır.
    ham[118:120, 60:140] = (128, 193, 128)
    assert _yesillik(ham) == 65, "deney kurulumu bozuk"

    out = np.asarray(layers.restore_extract_color(
        Image.fromarray(ham), gercek, extract,
        np.array([[30, 40, 120]], dtype=np.int16)))

    # Tam 0 beklenmiyor: yumuşatma rampası sınırda alfayı 1.0'a çıkarmıyor,
    # orijinalden bir miktar kalıyor (65 → 11).
    #
    # Eşik 20, gerçek görüntülerdeki ölçümden geliyor: aynı ölçütle mankenin
    # GERÇEK fotoğrafında 20'yi aşan piksel sayısı 0, düzeltilmiş ham
    # çıktılarda 42.246→0, 72.556→20, 41.037→2. Yani 20'nin altı "gözle
    # yeşil değil" demek — üç görüntüde de yakın planla doğrulandı.
    assert _yesillik(out) < 20, f"anti-alias saçağı temizlenmedi: {_yesillik(out)}"


def test_cikarim_basei_yoksa_ham_cikti_aynen_donuyor(db_path, tmp_path):
    """Yeşil base kullanmayan mankende davranış eskisiyle birebir aynı."""
    Image.new("RGB", (200, 400), (180, 180, 185)).save(tmp_path / "m.png")
    mannequin.from_photo(tmp_path / "m.png", db_path=db_path)
    mid = mannequin.active_id(db_path=db_path)

    ham = layers.raw_path(7, mid)
    Image.new("RGB", (200, 400), (60, 60, 60)).save(ham)

    assert layers.dressed_for_display(7, mid, db_path=db_path) == ham


def test_ham_cikti_yoksa_gosterim_none_donuyor(db_path, tmp_path):
    """Ham çıktı yoksa istemci bindirmeye düşmeli — sessiz 500 değil."""
    Image.new("RGB", (200, 400), (180, 180, 185)).save(tmp_path / "m.png")
    mannequin.from_photo(tmp_path / "m.png", db_path=db_path)
    mid = mannequin.active_id(db_path=db_path)

    assert layers.dressed_for_display(99, mid, db_path=db_path) is None


def test_gosterim_onbellegi_kaynak_yenilenince_tazeleniyor(db_path, tmp_path):
    """Bayat önbellek, olmayan önbellekten kötüdür (§25.7).

    Ham çıktı yenilenince gösterim kopyası da yeniden üretilmeli, yoksa
    kullanıcı eski giydirmeyi görmeye devam eder.
    """
    import os

    _uc_katmanli_sahne((180, 40, 40)).save(tmp_path / "m.png")
    mannequin.from_photo(tmp_path / "m.png", db_path=db_path)
    mid = mannequin.active_id(db_path=db_path)
    _uc_katmanli_sahne((20, 150, 20)).save(
        mannequin.extract_base_path(mid, db_path))

    ham = layers.raw_path(7, mid)
    _uc_katmanli_sahne((20, 150, 20), (30, 40, 120)).save(ham)

    ilk = layers.dressed_for_display(7, mid, db_path=db_path)
    assert ilk == layers.display_raw_path(7, mid), "önbelleğe yazılmadı"
    ilk_icerik = np.asarray(Image.open(ilk).convert("RGB")).copy()

    # Ham çıktı değişti: giydirilen bölge maviden sarıya döndü.
    _uc_katmanli_sahne((20, 150, 20), (200, 190, 40)).save(ham)
    os.utime(ham, (ilk.stat().st_mtime + 10, ilk.stat().st_mtime + 10))

    yeni_icerik = np.asarray(Image.open(
        layers.dressed_for_display(7, mid, db_path=db_path)).convert("RGB"))
    assert not np.array_equal(ilk_icerik, yeni_icerik), (
        "önbellek bayat kaldı — kaynak yenilendiği hâlde yeniden üretilmedi")
