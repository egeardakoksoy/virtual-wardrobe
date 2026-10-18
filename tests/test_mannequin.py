"""Base manken — en-boy oranı ve kaynak seçimi.

En kritik iddia: kullanıcının fotoğrafı tuvale oturtulurken **oranı bozulmuyor**.
Bozulursa kullanıcı kendini yanlış oranda görüyor ve tüm katmanlar o bozuk
orana göre üretiliyor — geri dönüşü olmayan bir hata.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from wardrobe import mannequin


# Manken/katman dizinlerinin izolasyonu artık conftest.isolated_env'de,
# tüm testler için. Yerel fixture kaldırıldı: eksik olduğu için testler
# kullanıcının gerçek base mankenini ezmişti.


def _photo_with_square(tmp_path, size, square=120) -> tuple:
    """Ortasında kare olan bir fotoğraf. Kare bozulursa oran bozulmuştur."""
    img = Image.new("RGB", size, (210, 210, 215))
    cx, cy = size[0] // 2, size[1] // 2
    img.paste(
        Image.new("RGB", (square, square), (200, 40, 45)),
        (cx - square // 2, cy - square // 2),
    )
    path = tmp_path / "ben.jpg"
    img.save(path, "JPEG", quality=95)
    return path, square / min(size)


def _square_dimensions(path) -> tuple[int, int]:
    arr = np.asarray(Image.open(path).convert("RGB"))
    red = (arr[:, :, 0] > 150) & (arr[:, :, 1] < 90)
    rows = np.where(red.any(axis=1))[0]
    cols = np.where(red.any(axis=0))[0]
    return len(cols), len(rows)


@pytest.mark.parametrize("size", [(1000, 1333), (1200, 1200), (1600, 900)])
def test_oran_korunur(tmp_path, db_path, size):
    """3:4 telefon fotoğrafı, kare, yatay — hiçbiri esnememeli.

    Doğrudan resize(864, 1296) çağırmak 3:4 bir fotoğrafı 2:3'e sıkıştırıp
    kişiyi inceltip uzatıyordu.
    """
    photo, _ = _photo_with_square(tmp_path, size)
    info = mannequin.from_photo(photo, db_path=db_path)

    w, h = _square_dimensions(info["image_path"])
    assert abs(w - h) <= max(3, w * 0.04), f"kare {w}x{h} oldu — oran bozulmuş"


def test_cikti_her_zaman_hedef_boyutta(tmp_path, db_path):
    """Katmanlar aynı tuvalde olmalı; oran korunuyor diye boyut değişemez."""
    photo, _ = _photo_with_square(tmp_path, (1600, 900))
    info = mannequin.from_photo(photo, db_path=db_path)
    assert Image.open(info["image_path"]).size == mannequin.MANNEQUIN_SIZE


def test_dolgu_bandi_kenar_renginde(tmp_path, db_path):
    """Bantlar göze batan siyah şeritler olmamalı."""
    photo, _ = _photo_with_square(tmp_path, (1600, 900))
    info = mannequin.from_photo(photo, db_path=db_path)

    arr = np.asarray(Image.open(info["image_path"]).convert("RGB"))
    top_band = arr[5, :, :].mean(axis=0)
    assert abs(top_band.mean() - 211) < 25, "dolgu rengi kenar rengine yakın değil"


def test_placeholder_uretilir(db_path):
    info = mannequin.placeholder(db_path=db_path, reason="test")
    assert info["kind"] == "placeholder"
    assert Image.open(info["image_path"]).size == mannequin.MANNEQUIN_SIZE


def test_ensure_varolani_dondurur(db_path):
    mannequin.placeholder(db_path=db_path)
    again = mannequin.ensure(db_path=db_path)
    assert again.get("existing") is True


def test_anahtar_yoksa_generate_placeholdera_duser(db_path, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    info = mannequin.generate(db_path=db_path)
    assert info["kind"] == "placeholder"
    assert "FAL_KEY yok" in info["reason"]


def test_manken_degisince_katmanlar_gecersiz_olur(tmp_path, db_path, monkeypatch):
    """Katman, o fotoğrafa özgü bir fark. FOTOĞRAF değişirse katman anlamsızlaşır.

    İşaretlenmezse eski katman yeni fotoğrafın üstüne bindirilir ve kayar —
    hem de sessizce, hata vermeden.

    ⚠ Bunun kardeşi `test_coklu_manken.py`'de: mankeni DEĞİŞTİRMEK (aktif
    olanı taşımak) hiçbir katmanı geçersizlememeli. İki işlem ayrı (§28.4 #2).
    """
    from db import connect, insert_garment
    monkeypatch.setattr("config.LAYER_DIR", tmp_path / "layers")
    (tmp_path / "layers").mkdir(exist_ok=True)

    mannequin.placeholder(db_path=db_path)
    gid = insert_garment({"category": "ust", "raw_path": "a.jpg"}, db_path=db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO layers (garment_id, mannequin_id, png_path, status) "
            "VALUES (?, 1, 'eski.png', 'ready')", (gid,)
        )

    photo, _ = _photo_with_square(tmp_path, (1000, 1333))
    info = mannequin.from_photo(photo, db_path=db_path)

    assert info["invalidated_layers"] == 1
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM layers WHERE garment_id = ?",
                           (gid,)).fetchone()
    assert row["status"] == "stale"
    assert "fotoğraf" in row["error"]


def test_gecersiz_katman_atlanmaz(tmp_path, db_path, monkeypatch):
    """stale katman 'zaten hazır' sayılıp atlanmamalı."""
    from db import connect, insert_garment
    from wardrobe import layers, vton
    monkeypatch.setattr("wardrobe.layers.LAYER_DIR", tmp_path / "l")
    (tmp_path / "l").mkdir(exist_ok=True)

    mannequin.placeholder(db_path=db_path)
    cutout = tmp_path / "c.png"
    Image.new("RGBA", (80, 80), (200, 40, 45, 255)).save(cutout)
    gid = insert_garment(
        {"category": "ust", "raw_path": "a.jpg", "cutout_path": str(cutout)},
        db_path=db_path,
    )
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO layers (garment_id, mannequin_id, status) "
            "VALUES (?, 1, 'stale')", (gid,)
        )

    result = layers.build_layer(gid, provider=vton.MockProvider(), db_path=db_path)
    assert not result.get("skipped")
    assert result["status"] == "ready"


def test_photo_db_ye_kaydedilir(tmp_path, db_path):
    photo, _ = _photo_with_square(tmp_path, (1000, 1333))
    mannequin.from_photo(photo, db_path=db_path)

    row = mannequin.get_base(db_path=db_path)
    assert row["kind"] == "photo"
    assert row["image_path"].endswith("base.png")


# --- Gösterim base'i ---
#
# İki base'in varlık sebebi ölçülmüş: base'in kıyafet renginin çıkarım ve
# bindirme için zıt gereksinimleri var (bkz. build_display_base docstring'i).

def test_gosterim_basei_kiyafeti_notrler(db_path, tmp_path):
    from PIL import Image
    import numpy as np

    # Gövdesi belirgin mavi, arka planı beyaz bir manken
    img = Image.new("RGB", (400, 600), (245, 245, 245))
    arr = np.asarray(img).copy()
    arr[200:440, 120:280] = (67, 96, 144)          # base'in "kıyafeti"
    foto = tmp_path / "m.png"
    Image.fromarray(arr).save(foto)
    mannequin.from_photo(foto, db_path=db_path)

    yol = mannequin.build_display_base(db_path=db_path)
    gos = np.asarray(Image.open(yol).convert("RGB"))
    ham = np.asarray(Image.open(mannequin.get_base(db_path=db_path)["image_path"]).convert("RGB"))

    h, w = gos.shape[:2]
    orta = (slice(int(0.45 * h), int(0.55 * h)), slice(int(0.45 * w), int(0.55 * w)))
    mavilik = lambda a: float(a[orta][..., 2].mean() - a[orta][..., 0].mean())

    assert mavilik(ham) > 40, "test kurulumu: ham base'in gövdesi mavi olmalı"
    assert mavilik(gos) < 15, "gösterim base'inde kıyafet nötrlenmeli"


def test_gosterim_basei_kisinin_disina_tasmiyor(db_path, tmp_path, monkeypatch):
    """Nötrleme KİŞİNİN dışına çıkmamalı — duvar, kapı, zemin boyanmamalı.

    ⚠ Ölçülmüş bir kusurun testi. Nötrleme "kıyafet" pikselini KROM (a*,b*)
    yakınlığıyla seçiyordu. Base'in kıyafeti doygun bir renkken ayrım kusursuz
    (kıyafet 1.2 · duvar 30.2 · ten 46.6), ama kıyafet neredeyse SİYAH olunca
    krom sıfıra yaklaşıyor — gri bir duvar da öyle — ve ayrım çöküyor
    (kıyafet 0.8 · duvar 8.7 · ten 15.2). Kullanıcının eklediği mankende
    tuvalin %43.7'si nötrlendi: arkadaki gri pano dev bir dikdörtgen oldu.

    Hiçbir eşik bunu kurtarmıyor; çözüm yapısal — base'in kıyafeti tanım
    gereği kişinin üstünde.
    """
    import numpy as np
    from PIL import Image

    from wardrobe import cutout

    # Gövdesi ve ARKASINDAKİ PANO aynı nötr tonda: krom ayrımı imkânsız.
    arr = np.full((600, 400, 3), 245, dtype=np.uint8)
    arr[150:500, 60:340] = (70, 72, 78)        # arka pano (kişinin DIŞI)
    arr[200:440, 140:260] = (40, 42, 48)       # base'in kıyafeti (kişinin ÜSTÜ)
    foto = tmp_path / "m.png"
    Image.fromarray(arr).save(foto)
    mannequin.from_photo(foto, db_path=db_path)

    # rembg testlerde kapalı (conftest flood'a sabitliyor); kişi maskesini
    # sentetik veriyoruz ki test hızlı ve deterministik kalsın.
    def sahte_kisi(img):
        m = np.zeros((img.size[1], img.size[0]), dtype=bool)
        h, w = m.shape
        m[int(0.30 * h):int(0.75 * h), int(0.33 * w):int(0.67 * w)] = True
        return m

    monkeypatch.setattr(cutout, "person_mask", sahte_kisi)

    yol = mannequin.build_display_base(db_path=db_path)
    ham = np.asarray(Image.open(
        mannequin.get_base(db_path=db_path)["image_path"]).convert("RGB")).astype(int)
    gos = np.asarray(Image.open(yol).convert("RGB")).astype(int)

    degisen = np.abs(ham - gos).sum(-1) > 18
    kisi = sahte_kisi(Image.open(yol))
    h, w = degisen.shape
    assert degisen.any(), "hiçbir şey nötrlenmemiş — test kurulumu bozuk"

    # Panonun kişiden UZAK kısmı: asıl kusur buydu (ekranı kaplayan gri
    # dikdörtgen). Kişinin hemen kenarındaki 1-2 piksel hariç tutuluyor —
    # maskeye bilerek 2 px Gaussian yumuşatma uygulanıyor (kenar sert
    # kalmasın diye), yani orada birkaç piksel taşması tasarımın parçası.
    pano = degisen[int(0.35 * h):int(0.70 * h), int(0.17 * w):int(0.30 * w)]
    assert not pano.any(), (
        "kişinin DIŞINDAKİ pano nötrlenmiş — duvar/zemin boyanıyor")

    # Taşma toplamda da ihmal edilebilir olmalı, yoksa "biraz taşıyor" diye
    # başlayan bir kusur sessizce büyür.
    disari = (degisen & ~kisi).sum() / degisen.sum()
    assert disari < 0.05, f"nötrlemenin %{disari*100:.1f}'i kişinin dışında"


def test_kisi_maskesi_yoksa_hat_kirilmiyor(db_path, tmp_path, monkeypatch):
    """rembg opsiyonel bir bağımlılık; yokken gösterim base'i yine üretilmeli."""
    from PIL import Image

    from wardrobe import cutout

    monkeypatch.setattr(cutout, "person_mask", lambda img: None)
    foto = tmp_path / "m.png"
    Image.new("RGB", (400, 600), (67, 96, 144)).save(foto)
    mannequin.from_photo(foto, db_path=db_path)

    assert mannequin.build_display_base(db_path=db_path).is_file()


def test_manken_degisince_gosterim_basei_silinir(db_path, tmp_path):
    from PIL import Image

    foto = tmp_path / "a.png"
    Image.new("RGB", (400, 600), (80, 110, 160)).save(foto)
    mannequin.from_photo(foto, db_path=db_path)
    mannequin.build_display_base(db_path=db_path)
    assert mannequin.display_base_path().is_file()

    foto2 = tmp_path / "b.png"
    Image.new("RGB", (400, 600), (200, 100, 100)).save(foto2)
    mannequin.from_photo(foto2, db_path=db_path)

    assert not mannequin.display_base_path().is_file(), (
        "eski gösterim base'i kalırsa katmanlar yeni mankene, zemin eskisine ait olur"
    )


# --- Çıkarım base'i (§44) ---

def test_cikarim_basei_ayri_dosya_ve_gercek_foto_bozulmuyor(db_path, tmp_path):
    """Kıyafet chroma yeşile boyanmış KOPYA üretilir; orijinal yerinde kalır.

    §44'ün çekirdeği: çıkarım base'inin gerçekçi görünmesi gerekmiyor çünkü
    kullanıcı onu hiç görmüyor. O yüzden kıyafeti dolaptaki her şeyden maksimum
    uzak bir renge boyanabiliyor ve kör nokta kapanıyor.
    Ölçüldü: base'e uzaklığı 1.0 olan tişörtte sızıntı %44.8 → %0.1.
    """
    import numpy as np
    from PIL import Image

    arr = np.full((600, 400, 3), 240, dtype=np.uint8)
    arr[200:420, 140:260] = (30, 34, 48)          # koyu "kıyafet"
    foto = tmp_path / "m.png"
    Image.fromarray(arr).save(foto)
    mannequin.from_photo(foto, db_path=db_path)

    once = Image.open(mannequin.active(db_path)["image_path"]).tobytes()
    yol = mannequin.build_extract_base(db_path=db_path)

    assert yol.is_file()
    assert str(yol) != mannequin.active(db_path)["image_path"]
    assert Image.open(mannequin.active(db_path)["image_path"]).tobytes() == once, (
        "gerçek fotoğraf değiştirilmiş — gösterim tarafı bozulur")

    # Boyanan bölge YEŞİL olmalı (G kanalı baskın)
    a = np.asarray(Image.open(yol).convert("RGB")).astype(int)
    h, w = a.shape[:2]
    orta = a[int(0.45 * h):int(0.55 * h), int(0.45 * w):int(0.55 * w)].reshape(-1, 3)
    assert orta[:, 1].mean() > orta[:, 0].mean() + 40, "kıyafet yeşile boyanmamış"


def test_cikarim_goruntusu_yoksa_gercek_fotoya_dusuyor(db_path, tmp_path):
    """Varyantı olmayan mankende (eski kayıt ya da kurulamadı) hat aynen
    eskisi gibi çalışmalı."""
    from PIL import Image

    Image.new("RGB", (400, 600), (70, 96, 150)).save(tmp_path / "m.png")
    mannequin.from_photo(tmp_path / "m.png", db_path=db_path)

    assert not mannequin.extract_base_path(db_path=db_path).is_file()
    assert (str(mannequin.extraction_image(db_path=db_path))
            == mannequin.active(db_path)["image_path"])


# --- Yeşil çıkarım base'i kendiliğinden (§53) ---

@pytest.fixture
def yesil_otomatik(monkeypatch):
    """conftest'in kapattığı otomatik kurulumu bu testler için açar."""
    monkeypatch.setattr(mannequin, "YESIL_TABAN_OTOMATIK", True)


def _koyu_kiyafetli_foto(tmp_path, ad="m.png", kutu=(200, 420, 140, 260)):
    """Açık zeminde koyu dikdörtgen "kıyafet" — §44 testlerindeki kurulum."""
    y0, y1, x0, x1 = kutu
    arr = np.full((600, 400, 3), 240, dtype=np.uint8)
    arr[y0:y1, x0:x1] = (30, 34, 48)
    yol = tmp_path / ad
    Image.fromarray(arr).save(yol)
    return yol


def test_yeni_mankende_yesil_taban_kendiliginden_kuruluyor(
        db_path, tmp_path, yesil_otomatik):
    """Sıfırdan kurulumda yeni manken eklenince elle adım gerekmemeli.

    Eksikken: yeşil base yalnızca elle kurulan mankenlerde vardı. Yeni
    mankende `drop_extract_color` gerçek kıyafetin paletini hedefliyor ve
    MAI katmanlarında delik açıyordu (§51.8).
    """
    info = mannequin.add_from_photo(_koyu_kiyafetli_foto(tmp_path),
                                    name="Yeni", db_path=db_path)

    yol = mannequin.extract_base_path(info["mannequin_id"], db_path)
    assert yol.is_file(), "yeni mankende yeşil çıkarım base'i kurulmadı"
    assert mannequin.extraction_image(info["mannequin_id"], db_path) == yol

    a = np.asarray(Image.open(yol).convert("RGB")).astype(int)
    h, w = a.shape[:2]
    orta = a[int(0.45 * h):int(0.55 * h), int(0.45 * w):int(0.55 * w)].reshape(-1, 3)
    assert orta[:, 1].mean() > orta[:, 0].mean() + 40, "kıyafet yeşile boyanmamış"


def test_foto_degisince_eski_yesil_taban_silinir(db_path, tmp_path):
    """Fotoğraf değişince eski varyant KALMAMALI — gösterim base'iyle aynı kural.

    Eksikti: bayat varyant duruyordu ve `extraction_image` onu seçiyordu, yani
    VTON'a eski fotoğrafın geometrisi gidiyordu. Otomatik kurulum burada
    kapalı: yalnızca silme test ediliyor.
    """
    mannequin.from_photo(_koyu_kiyafetli_foto(tmp_path, "a.png"), db_path=db_path)
    mannequin.build_extract_base(db_path=db_path)
    assert mannequin.extract_base_path(db_path=db_path).is_file()

    mannequin.from_photo(_koyu_kiyafetli_foto(tmp_path, "b.png"), db_path=db_path)

    assert not mannequin.extract_base_path(db_path=db_path).is_file(), (
        "eski fotoğrafın yeşil base'i duruyor — VTON'a eski geometri gider")
    assert (str(mannequin.extraction_image(db_path=db_path))
            == mannequin.active(db_path)["image_path"])


def test_foto_degisince_yesil_taban_yeniden_kurulur(db_path, tmp_path, yesil_otomatik):
    mannequin.from_photo(_koyu_kiyafetli_foto(tmp_path, "a.png"), db_path=db_path)
    yol = mannequin.extract_base_path(db_path=db_path)
    eski = yol.read_bytes()

    mannequin.from_photo(
        _koyu_kiyafetli_foto(tmp_path, "b.png", kutu=(80, 300, 100, 220)),
        db_path=db_path)

    assert yol.is_file(), "fotoğraf değişince yeşil base yeniden kurulmadı"
    assert yol.read_bytes() != eski, "yeşil base hâlâ eski fotoğrafa ait"


def test_placeholdera_yesil_taban_kurulmuyor(db_path, yesil_otomatik):
    info = mannequin.placeholder(db_path=db_path, name="Figür")
    assert not mannequin.extract_base_path(info["mannequin_id"], db_path).is_file()


def test_yesil_taban_kurulamazsa_manken_yine_eklenir(
        db_path, tmp_path, monkeypatch, yesil_otomatik):
    """Yeşil base bir iyileştirme; kurulamaması manken eklemeyi bozmamalı."""
    def patla(*args, **kwargs):
        raise RuntimeError("maske hesaplanamadı")

    monkeypatch.setattr(mannequin, "build_extract_base", patla)

    info = mannequin.add_from_photo(_koyu_kiyafetli_foto(tmp_path),
                                    name="Yeni", db_path=db_path)

    assert info["created"]
    assert not mannequin.extract_base_path(info["mannequin_id"], db_path).is_file()
    assert (str(mannequin.extraction_image(info["mannequin_id"], db_path))
            == info["image_path"])


def test_manken_silinince_yesil_taban_da_silinir(db_path, tmp_path):
    mannequin.from_photo(_koyu_kiyafetli_foto(tmp_path, "a.png"), db_path=db_path)
    info = mannequin.add_from_photo(_koyu_kiyafetli_foto(tmp_path, "b.png"),
                                    name="İkinci", db_path=db_path)
    yol = mannequin.build_extract_base(info["mannequin_id"], db_path)
    assert yol.is_file()

    mannequin.delete(info["mannequin_id"], db_path=db_path)

    assert not yol.is_file(), "silinen mankenin yeşil base'i diskte kaldı"


def test_kucuk_bilesenler_elenir_kiyafet_kalir():
    """Koyu SAKAL kıyafet sanılıyordu — küçük bileşenler atılmalı.

    Ölçüldü (manken 2): kıyafet maskesi 64 bileşene ayrılıyor, ana bileşen
    %98.5 ve ikincisi sakal (1.136 px, y %22-25 — çene). %5 eşiği sakalı ve iki
    küçük gölge lekesini atıyor, kıyafete dokunmuyor.

    İki parçalı kıyafet (üst + alt ayrık) korunmalı — ikisi de eşiğin üstünde.
    """
    m = np.zeros((400, 200), dtype=bool)
    m[100:200, 60:140] = True      # üst  (8000 px)
    m[250:330, 60:140] = True      # alt  (6400 px)
    m[40:52, 90:110] = True        # "sakal" (240 px = ana bileşenin %3'ü)

    out = mannequin._buyuk_bilesenler(m)

    assert out[150, 100], "üst silinmiş"
    assert out[280, 100], "alt silinmiş"
    assert not out[45, 100], "küçük bileşen (sakal) elenmedi"


def test_tek_bilesende_dokunulmuyor():
    """Ana kıyafet tek parçaysa eleme hiçbir şey yapmamalı."""
    m = np.zeros((300, 200), dtype=bool)
    m[80:220, 60:140] = True
    assert np.array_equal(mannequin._buyuk_bilesenler(m), m)
