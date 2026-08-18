"""Hizalama dönüşümü — Sorun C.

Buradaki testlerin ortak derdi tek bir şey: **arayüzdeki önizleme ile sunucuda
uygulanan dönüşüm aynı olmalı.** Ayrışırlarsa hata sessiz olur — kullanıcı
kıyafeti şablona oturtur, sunucu başka bir yere taşır, kırpma bozulur ve
bunun sebebini kimse bulamaz. O yüzden sözleşmenin her parçası ayrı test
ediliyor: tuval boyutu, yön, sıra, sınırlar.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from wardrobe.imageutil import (
    ALIGN_LIMITS, apply_align, clamp_align, is_identity_align,
)


def isaretli_kare(size: int = 120) -> Image.Image:
    """Beyaz zeminde, MERKEZDEN KAÇIK küçük siyah bir kare.

    Kaçık olması şart: merkezde olsaydı taşıma ve dönme testleri simetri
    yüzünden yanlış pozitif verirdi.
    """
    img = Image.new("RGB", (size, size), (255, 255, 255))
    for x in range(20, 40):
        for y in range(20, 40):
            img.putpixel((x, y), (0, 0, 0))
    return img


def agirlik_merkezi(img: Image.Image) -> tuple[float, float]:
    arr = np.asarray(img.convert("L"))
    ys, xs = np.nonzero(arr < 128)
    return float(xs.mean()), float(ys.mean())


# --- birim dönüşüm ---

def test_birim_donusum_goruntuye_dokunmaz():
    img = isaretli_kare()
    assert apply_align(img, None) is img
    assert apply_align(img, {"dx": 0, "dy": 0, "scale": 1, "rotate": 0}) is img


@pytest.mark.parametrize("align,birim", [
    (None, True),
    ({}, True),
    ({"dx": 0, "dy": 0, "scale": 1, "rotate": 0}, True),
    ({"dx": 0.1, "dy": 0, "scale": 1, "rotate": 0}, False),
    ({"dx": 0, "dy": 0, "scale": 1.2, "rotate": 0}, False),
    ({"dx": 0, "dy": 0, "scale": 1, "rotate": 5}, False),
])
def test_birim_tespiti(align, birim):
    assert is_identity_align(align) is birim


# --- tuval ---

def test_tuval_boyutu_degismez():
    """Şablon 0-1 normalize; tuval değişirse önsel kayar ve kurtarma bozulur."""
    img = isaretli_kare(150)
    out = apply_align(img, {"dx": 0.2, "dy": -0.1, "scale": 1.6, "rotate": 12})
    assert out.size == img.size


# --- yön ve büyüklük ---

def test_tasima_yonu_ve_miktari_dogru():
    """dx pozitif → SAĞA. CSS translateX(+) ile aynı yön olmak zorunda."""
    img = isaretli_kare(100)
    x0, y0 = agirlik_merkezi(img)

    sag = agirlik_merkezi(apply_align(img, {"dx": 0.2, "dy": 0, "scale": 1, "rotate": 0}))
    assert sag[0] == pytest.approx(x0 + 20, abs=1.0)   # tuvalin %20'si = 20 px
    assert sag[1] == pytest.approx(y0, abs=1.0)

    asagi = agirlik_merkezi(apply_align(img, {"dx": 0, "dy": 0.1, "scale": 1, "rotate": 0}))
    assert asagi[1] == pytest.approx(y0 + 10, abs=1.0)
    assert asagi[0] == pytest.approx(x0, abs=1.0)


def test_olcek_merkez_etrafinda_ve_alani_buyutur():
    img = isaretli_kare(100)
    arr = lambda im: (np.asarray(im.convert("L")) < 128).sum()

    # 1.5 seçildi, 2.0 değil: ×2'de merkezden kaçık işaret tuvalin dışına
    # taşıp kırpılıyor ve alan karşılaştırması anlamını yitiriyor.
    buyuk = apply_align(img, {"dx": 0, "dy": 0, "scale": 1.5, "rotate": 0})
    assert arr(buyuk) == pytest.approx(2.25 * arr(img), rel=0.15)

    # Merkezden kaçık işaret, merkezden ölçeklendiği için merkezden UZAKLAŞIR.
    cx = 50
    assert abs(agirlik_merkezi(buyuk)[0] - cx) > abs(agirlik_merkezi(img)[0] - cx)


def test_donme_yonu_saat_yonu():
    """rotate pozitif → saat yönü (CSS rotate(+deg) ile aynı).

    Sol ÜST köşedeki işaret saat yönünde dönünce sağa kayar.
    """
    img = isaretli_kare(100)
    x0, _ = agirlik_merkezi(img)
    donmus = apply_align(img, {"dx": 0, "dy": 0, "scale": 1, "rotate": 25})
    assert agirlik_merkezi(donmus)[0] > x0


def test_sira_once_olcek_sonra_donme_sonra_tasima():
    """Sıra CSS'teki `translate(...) rotate(...) scale(...)` ile aynı olmalı.

    Sınama: dönme ve taşımayı birlikte uygula. Taşıma dönmeden SONRA
    geliyorsa, taşınan miktar dönmeden etkilenmez — yani sonuç, sadece dönmüş
    hâlin tam olarak (dx·W, dy·H) kadar ötelenmişidir. Taşıma dönmeden önce
    uygulansaydı öteleme de dönerdi ve dikey bileşen sıfır çıkmazdı.
    """
    img = isaretli_kare(100)
    sadece_donme = agirlik_merkezi(
        apply_align(img, {"dx": 0, "dy": 0, "scale": 1, "rotate": 20}))
    donme_ve_tasima = agirlik_merkezi(
        apply_align(img, {"dx": 0.25, "dy": 0, "scale": 1, "rotate": 20}))

    assert donme_ve_tasima[0] == pytest.approx(sadece_donme[0] + 25, abs=1.5)
    assert donme_ve_tasima[1] == pytest.approx(sadece_donme[1], abs=1.5)


# --- güvenlik: değerler istemciden geliyor ---

def test_olcek_sifir_kirpilir_matris_tekillesmez():
    """scale=0 afin matrisi tekilleştirir ve PIL patlar."""
    assert clamp_align(0, 0, 0, 0)["scale"] == ALIGN_LIMITS["scale"][0]
    assert clamp_align(0, 0, -3, 0)["scale"] == ALIGN_LIMITS["scale"][0]
    apply_align(isaretli_kare(), {"dx": 0, "dy": 0, "scale": 0, "rotate": 0})


def test_asiri_degerler_kirpilir():
    a = clamp_align(99, -99, 999, 720)
    assert a["dx"] == ALIGN_LIMITS["dx"]
    assert a["dy"] == -ALIGN_LIMITS["dy"]
    assert a["scale"] == ALIGN_LIMITS["scale"][1]
    assert a["rotate"] == ALIGN_LIMITS["rotate"]


def test_acilan_kenar_zemin_rengiyle_dolar():
    """Siyahla doldurmak flood yedeğinin arka plan referansını bozardı."""
    img = isaretli_kare(100)
    out = apply_align(img, {"dx": 0.3, "dy": 0, "scale": 1, "rotate": 0})
    sol_serit = np.asarray(out.convert("RGB"))[:, :5].reshape(-1, 3)
    assert sol_serit.mean() > 200, "açılan kenar koyu kalmış"


# --- yükleme hattına bağlanması ---

def test_add_garment_hizalamayi_uygular_ve_kaydeder(tmp_path, db_path):
    from tests.conftest import make_garment_photo
    from db import get_garment
    from wardrobe.ingest import add_garment

    foto = make_garment_photo(tmp_path / "t.jpg")
    align = {"dx": 0.1, "dy": 0.05, "scale": 1.2, "rotate": 3}
    kayit = add_garment(foto, use_vlm=False, align=align, db_path=db_path)

    saklanan = json.loads(get_garment(kayit["id"], db_path=db_path)["align_json"])
    assert saklanan == pytest.approx(clamp_align(**align))


def test_orijinal_foto_korunur(tmp_path, db_path):
    """Hizalama yanlış yapılırsa geri dönecek bir şey kalmalı.

    Hizalanmış görüntü orijinalin ÜSTÜNE yazılsaydı tek çare fotoğrafı
    telefondan yeniden yüklemek olurdu.
    """
    from pathlib import Path

    from tests.conftest import make_garment_photo
    from wardrobe.ingest import add_garment

    foto = make_garment_photo(tmp_path / "t.jpg")
    once = Path(foto).read_bytes()

    kayit = add_garment(foto, use_vlm=False, db_path=db_path,
                        align={"dx": 0.2, "dy": 0, "scale": 1.5, "rotate": 0})

    assert Path(kayit["raw_path"]).read_bytes() == once
    assert Path(kayit["raw_path"]).with_name(
        Path(kayit["raw_path"]).stem + "_aligned.png").is_file()


def test_hizalamasiz_yukleme_eskisi_gibi_calisir(tmp_path, db_path):
    """Panel kullanılmadığında hat hiç değişmemeli."""
    from pathlib import Path

    from tests.conftest import make_garment_photo
    from wardrobe.ingest import add_garment

    foto = make_garment_photo(tmp_path / "t.jpg")
    kayit = add_garment(foto, use_vlm=False, db_path=db_path)

    assert kayit["align_json"] == ""
    # Hizalama yoksa `_aligned.png` de yazılmamalı — boşuna dosya üretmek
    # kullanıcının diskinde birikiyor (§27.9'daki tembel üretim dersi).
    assert not list(Path(kayit["raw_path"]).parent.glob("*_aligned.png"))


# --- SIRA: önce kırp, sonra hizala (§31) ---
#
# Bu sıra bir kez terstiydi ve bir kıyafeti sessizce mahvetti: kullanıcı
# fotoğrafı şablona oturtmak için %53'e küçültmüş, küçültülmüş fotoğrafta
# segmentasyon modeli siluet yerine kaba bir DİKDÖRTGEN BLOK döndürmüş ve
# çizgili çarşaf "kıyafetin parçası" olarak kırpığa girmişti.
# Ölçüm: kutu doluluğu hizalanmışta %86.8, orijinalde %61.4.
#
# Sıra tekrar ters çevrilirse bu testler kırılır.

def _kutu_dolulugu(cutout_path) -> float:
    """Maskenin sınırlayıcı kutusunu ne kadar doldurduğu.

    Bozuk kırpığı yakalayan tek sinyal buydu: kaplama normaldi (%25.1) ve
    kırpık kadraj kenarına da değmiyordu, ama blok dikdörtgen olduğu için
    kutusunu neredeyse tamamen dolduruyordu.
    """
    a = np.asarray(Image.open(cutout_path).convert("RGBA"))[..., 3] > 128
    if not a.any():
        return 0.0
    ys, xs = np.where(a)
    kutu = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
    return float(a.sum()) / kutu


def test_kirpma_hizalamadan_etkilenmiyor(tmp_path, db_path):
    """ASIL TEST. Ağır küçültme kırpma KALİTESİNİ bozmamalı.

    Eski sırada küçültme doğrudan segmentasyona giriyordu; yeni sırada kırpma
    orijinalden yapılıyor, hizalama yalnızca kırpılmış RGBA'ya uygulanıyor.
    """
    from tests.conftest import make_garment_photo
    from wardrobe.ingest import add_garment

    foto = make_garment_photo(tmp_path / "t.jpg", size=400)

    duz = add_garment(foto, use_vlm=False, db_path=db_path)
    kucuk = add_garment(foto, use_vlm=False, db_path=db_path,
                        align={"dx": 0, "dy": 0, "scale": 0.5, "rotate": 0})

    assert _kutu_dolulugu(kucuk["cutout_path"]) == pytest.approx(
        _kutu_dolulugu(duz["cutout_path"]), abs=0.08), (
        "küçültme kırpığın şeklini değiştirdi — sıra ters çevrilmiş olabilir")


def test_hizalama_kirpiga_uygulaniyor(tmp_path, db_path):
    """Hizalama kayboluyor da olmamalı: kırpıkta görünür olmalı.

    Kırpma öne alınırken hizalamanın tamamen düşürülmesi sessiz bir gerileme
    olurdu — panel çalışıyormuş gibi görünür, hiçbir etkisi olmazdı.
    """
    from tests.conftest import make_garment_photo
    from wardrobe.ingest import add_garment

    foto = make_garment_photo(tmp_path / "t.jpg", size=400)

    duz = add_garment(foto, use_vlm=False, db_path=db_path)
    kucuk = add_garment(foto, use_vlm=False, db_path=db_path,
                        align={"dx": 0, "dy": 0, "scale": 0.5, "rotate": 0})

    def kaplama(p):
        return (np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 128).mean()

    assert kaplama(kucuk["cutout_path"]) < kaplama(duz["cutout_path"]) * 0.6, (
        "ölçek 0.5 kırpığa uygulanmamış")


def test_rgba_hizalamada_acilan_kenar_SEFFAF(tmp_path):
    """Kırpılmış RGBA'da açılan kenar zemin rengiyle DOLMAMALI.

    Dolsaydı kıyafetin etrafına opak bir çerçeve çizilirdi ve o çerçeve VTON'a
    "kıyafetin parçası" olarak giderdi. (RGB girdide dolgu hâlâ zemin rengi —
    orada flood yedeğinin arka plan referansı korunmalı.)
    """
    img = Image.new("RGBA", (100, 100), (200, 40, 45, 255))
    out = apply_align(img, {"dx": 0.3, "dy": 0, "scale": 1, "rotate": 0})
    sol = np.asarray(out)[:, :5, 3]
    assert sol.max() == 0, "açılan kenar opak doldurulmuş"
