"""Manken(ler) — katmanların üretildiği zemin.

Katman mimarisinin tek şartı var: **bir katman kümesinin tamamı aynı manken,
aynı poz, aynı çözünürlük** üzerinden üretilmiş olmalı. O zaman katmanlar
piksel piksel hizalı oluyor ve üst üste bindirme birebir tutuyor.

ÇOKLU MANKEN (§28): şart "tek manken" değil, "bir katmanın hangi mankene ait
olduğunun BİLİNMESİ". `layers` tablosunun birincil anahtarı zaten
(garment_id, mannequin_id) — yani veri modeli baştan beri manken başına
ayrılmış. Bu modülün eski hâli o imkânı kullanmıyordu: her şey
`WHERE name = 'base'` diye tek satıra bakıyor ve yeni manken ESKİSİNİN ÜSTÜNE
yazıyordu.

Şimdi birden çok manken yan yana yaşıyor ve aralarında geçiş **hiçbir şey
silmiyor**. İki işlemi ayırmak kritik:

  manken DEĞİŞTİRMEK     → sadece `is_active` taşınır. Bedava, geri dönülebilir,
                           hiçbir katman/render kaybolmaz. (Amaç bu.)
  fotoğrafını DEĞİŞTİRMEK → o mankenin katmanları geçersiz (eski vücut hattına
                           göre kesilmişler), renderları da öyle. Yalnızca O
                           MANKENİN verisi etkilenir, diğerlerine dokunulmaz.

Üç kaynak var:
  photo      — kullanıcının kendi fotoğrafı (en iyisi, Faz 5'in temeli)
  generated  — fal ile üretilmiş nötr manken (anahtar varsa)
  placeholder— PIL ile çizilmiş basit figür (anahtarsız; test ve geliştirme)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from config import DATA_DIR
from db import connect
from wardrobe.imageutil import load_upright

# FASHN v1.6'nın çıktı çözünürlüğü. Mankeni aynı boyutta tutuyoruz ki
# sonuç görselini yeniden ölçeklemek gerekmesin — her ölçekleme katman
# hizasını bozma riski.
MANNEQUIN_SIZE = (864, 1296)

MANNEQUIN_DIR = DATA_DIR / "mannequins"
MANNEQUIN_DIR.mkdir(parents=True, exist_ok=True)

# İki üretim stili. Fark önemli:
#
# "person"    — VTON modelleri (FASHN dahil) İNSAN fotoğraflarıyla eğitildi.
#               Vücut bölütleme, ten tonu, poz kestirimi hep insan varsayıyor.
#               Varsayılan bu.
# "mannequin" — vitrin mankeni. Görsel olarak temiz ama plastik gövde modelin
#               beklediği girdi değil; giydirme kalitesi düşebilir. Yine de
#               moda e-ticaretinde "ghost mannequin" çekimleri yaygın olduğu
#               için bazı modeller idare edebiliyor. Karşılaştırma için duruyor.
GENERATION_PROMPTS: dict[str, str] = {
    "person": (
        "full body photograph of a person standing straight facing the camera, "
        "arms relaxed slightly away from the body, wearing plain fitted white "
        "t-shirt and plain fitted gray leggings, neutral expression, "
        "plain light gray seamless studio background, even soft studio lighting, "
        "sharp focus, photorealistic, centered, entire figure visible from head "
        "to feet, no shadows on background"
    ),
    "mannequin": (
        "full body photo of a neutral fashion mannequin standing straight, "
        "arms slightly away from body, front view, plain light gray seamless "
        "studio background, even soft lighting, no clothing accessories, "
        "photorealistic, centered, full figure visible from head to feet"
    ),
}
DEFAULT_STYLE = "person"


# Varsayılan (ilk) mankenin adı. Dosya adları buna bağlı: 'base' → base.png,
# diğerleri → base_{id}.png. Bu ayrım nostalji değil VERİ KORUMASI — mevcut
# kurulumda `data/mannequins/base.png` ve ona ait 11 katman duruyor; adlandırma
# kuralını topluca değiştirmek onları bir anda "kayıp" yapardı (§28.4 #4).
DEFAULT_NAME = "base"


def image_path_for(mannequin_id: int, name: str = "") -> Path:
    """Bir mankenin görsel dosyası — SABİT DEĞİL, çağrı anında çözülür.

    Türetilmiş yolu modül seviyesinde sabitlemek bu projede üç kez veri
    kaybettirdi (§6.1 #8, #13, §27.1-B). MANNEQUIN_DIR'e her seferinde
    yeniden bakılıyor ki `conftest`'in tmp_path yönlendirmesi delinmesin.
    """
    if name == DEFAULT_NAME:
        return MANNEQUIN_DIR / "base.png"
    return MANNEQUIN_DIR / f"base_{mannequin_id}.png"


def photo_path(mannequin_id: int | None = None, db_path=None) -> Path | None:
    """Mankenin GERÇEK fotoğrafı — boyanmamış, nötrlenmemiş hâli.

    Üç base'in (gerçek / çıkarım / gösterim) diğer ikisinin yol erişimcisi
    zaten vardı; bu, üçüncüsünü de aynı hizaya getiriyor. Dosya yoksa None
    dönüyor, çünkü çağıranların hepsi "gerçek fotoğraf yoksa eski davranışa
    dön" diyebilmek istiyor — kayıt varken dosyanın silinmiş olması mümkün.
    """
    row = _row(mannequin_id, db_path)
    if not row or not row["image_path"]:
        return None
    yol = Path(row["image_path"])
    return yol if yol.is_file() else None


def display_base_path(mannequin_id: int | None = None, db_path=None) -> Path:
    """Gösterim base'inin yolu — SABİT DEĞİL, çağrı anında çözülür.

    Modül seviyesinde `DISPLAY_BASE = MANNEQUIN_DIR / ...` yazmak bug #8'i
    aynen tekrarlıyor: `conftest` MANNEQUIN_DIR'i `tmp_path`'e yönlendirdiğinde
    içe aktarma anında hesaplanmış sabit hâlâ GERÇEK klasörü gösteriyor ve
    testler canlı veriyi siliyor. Nitekim sildi de — bu fonksiyon o yüzden var.

    Ad, mankenin KENDİ görselinin adından türüyor (`base.png` →
    `base_display.png`, `base_2.png` → `base_2_display.png`). Böylece mevcut
    `base_display.png` yerinde kalıyor: çoklu mankene geçiş var olan tek bir
    dosyayı bile yeniden adlandırmıyor.
    """
    row = _row(mannequin_id, db_path)
    kok = Path(row["image_path"]).stem if row and row["image_path"] else "base"
    return MANNEQUIN_DIR / f"{kok}_display.png"

# Gösterim base'inde base'in kıyafetinin boyanacağı nötr aralık (koyu→açık).
# Gölge gibi okunması için koyu ve doygunluksuz.
NEUTRAL_DARK = np.array([40, 40, 44])
NEUTRAL_LIGHT = np.array([96, 96, 104])

# Base'in kıyafeti sayılmak için krom (a*,b*) düzleminde bu kadar yakın olmak
# gerekiyor. Ölçümle seçildi — bkz. build_display_base.
DISPLAY_NEUTRAL_CHROMA = 15.0



# Kıyafet maskesinde tutulacak en küçük bileşenin, en büyük bileşene oranı.
#
# ⚠ ÖLÇÜMLE EKLENDİ. Krom ölçütü koyu SAKALI da kıyafet sayıyordu: manken 2'de
# maske 64 bileşene ayrılıyor ve ikincisi (1.136 px, y %22-25 — çene) sakaldı.
# Ana kıyafet bileşeni %98.5 olduğu için %5'lik eşik sakalı ve iki küçük gölge
# lekesini atıyor (toplam %1.5), kıyafete dokunmuyor. Base'de eleme 1 piksel.
#
# İki parçalı bir kıyafet (üst + alt ayrık) hâlâ korunuyor — ikisi de eşiğin
# çok üstünde kalıyor.
MIN_CLOTHING_COMPONENT = 0.05



# Üst ve alt giysiyi ayırmak için gereken en küçük parlaklık farkı.
#
# ÖLÇÜLDÜ: manken 2 (koyu tişört + açık şort) fark **110.8**; base (mavi tişört
# + mavi şort, aynı ton) fark **8.8**. 30 ikisini rahatça ayırıyor.
#
# Fark yetersizse bölme YAPILMIYOR ve kıyafetin tamamı boyanıyor — yani eski
# davranış. Yanlış yerden bölmek, bölmemekten kötü: üst giydirilirken göğsün
# yarısı boyasız kalırdı.
SPLIT_MIN_LUMA_GAP = 30.0


def _kiyafet_bolumleri(img, mask):
    """Kıyafet maskesini ÜST ve ALT parçaya ayırır. Ayıramazsa (None, None).

    NEDEN: yeşile boyamak yalnızca GİYDİRİLECEK bölgede işe yarıyor. Üst
    giydirilirken şortun yeşil olması hiçbir şey kazandırmıyor, sadece o
    bölgeden yeşil sızma riski getiriyor (ölçüldü: ayak bileğinde ve boyunda
    yeşil noktalar çıkıyordu).

    Ayrım PARLAKLIK sıçramasıyla: üst ve alt giysi genelde farklı tonda. Aynı
    tondaysa (base: mavi üst + mavi alt) ayrım güvenilir değil ve yapılmıyor.
    """
    import numpy as np

    arr = np.asarray(img).astype(float)
    h = mask.shape[0]
    if not mask.any():
        return None, None
    ys, _ = np.where(mask)
    ust_y, alt_y = ys.min(), ys.max()

    lum = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    prof = np.array([lum[r][mask[r]].mean() if mask[r].sum() > 20 else np.nan
                     for r in range(h)])
    idx = np.where(~np.isnan(prof))[0]
    if len(idx) < 60:
        return None, None

    yum = np.convolve(prof[idx], np.ones(25) / 25, mode="same")
    fark = np.abs(np.diff(yum))
    ic = ((idx[:-1] > ust_y + 0.18 * (alt_y - ust_y))
          & (idx[:-1] < alt_y - 0.18 * (alt_y - ust_y)))
    if not ic.any():
        return None, None

    j = int(np.argmax(fark[ic]))
    sinir = int(idx[:-1][ic][j])
    kesme = int(np.where(idx == sinir)[0][0])
    if abs(yum[:kesme].mean() - yum[kesme:].mean()) < SPLIT_MIN_LUMA_GAP:
        return None, None      # aynı tonda — güvenilir bölme yok

    ust = mask.copy(); ust[sinir:] = False
    alt = mask.copy(); alt[:sinir] = False
    return ust, alt

def _clothing_mask(img, mannequin_id=None, db_path=None, person=None):
    """Base'in ÜZERİNDEKİ kıyafetin maskesi — gösterim ve çıkarım base'i ortak.

    Üç süzgeç, üçü de ayrı bir hatanın düzeltmesi:

      1. KROM yakınlığı (§19.1) — parlaklığa değil renge bakar, gölgeli
         bölgeleri kaçırmaz.
      2. KİŞİ maskesi (§32) — duvar/kapı/zemin eleniyor. Krom, kıyafet
         neredeyse akromatikken gri duvardan ayıramıyor; tuvalin %43.7'si
         boyanmıştı.
      3. BİLEŞEN eşiği — koyu sakal kıyafet sanılıyordu.

    Bant (2) ve (3)'ten sonra büyük ölçüde gereksiz ama güvenlik ağı olarak
    duruyor: kadraja giren, kişiye değen, kıyafet renginde bir nesne.
    """
    import numpy as np

    from wardrobe.imageutil import lab_distance, to_lab
    from wardrobe.layers import base_clothing_palette

    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]
    palette = base_clothing_palette(np.asarray(img), person=person)
    dist = lab_distance(
        to_lab(arr)[:, :, None, :], to_lab(palette)[None, None, :, :],
        lightness_weight=0.0,
    ).min(axis=-1)

    band = np.zeros((h, w), dtype=bool)
    band[int(0.20 * h):int(0.90 * h), int(0.16 * w):int(0.88 * w)] = True
    mask = (dist < DISPLAY_NEUTRAL_CHROMA) & band
    if person is not None and person.any():
        mask = mask & person
    return _buyuk_bilesenler(mask)


def _buyuk_bilesenler(mask):
    """Ana kıyafete göre çok küçük kalan bileşenleri atar (sakal, gölge lekesi).

    scipy yoksa maske olduğu gibi dönüyor — eleme bir iyileştirme, şart değil.
    """
    import numpy as np

    try:
        from scipy import ndimage
    except ImportError:
        return mask
    if not mask.any():
        return mask

    etiket, n = ndimage.label(mask)
    if n <= 1:
        return mask
    boy = ndimage.sum(mask, etiket, range(1, n + 1))
    esik = boy.max() * MIN_CLOTHING_COMPONENT
    tutulan = {i + 1 for i, b in enumerate(boy) if b >= esik}
    return np.isin(etiket, list(tutulan))

def build_display_base(db_path=None, mannequin_id: int | None = None) -> Path:
    """Bindirme için base'in kıyafeti nötr koyuya boyanmış kopyasını üretir.

    NEDEN İKİ BASE: base'in kıyafet renginin birbirine zıt iki işi var.

      Çıkarım için: dolaptaki her kıyafetten UZAK olmalı, yoksa fark
        zayıflar ve o renkteki kıyafetler kör noktada kalır (§7.4 — siyah
        base'de siyah şort çıkmıyordu).
      Bindirme için: sızdığında GÖZE BATMAMALI. Sızıntı kaçınılmaz, çünkü
        base'in kıyafeti yeni kıyafetin siluetinin dışına taştığı her yerde
        görünüyor (§7.1).

    Turkuaz denemesi (§7.5) birinci şartı sağlayıp ikincisinde çakıldı. Çözüm
    tek bir renk aramak değil, iki işi AYIRMAK:

      base.png          → orta mavi, çıkarım burada yapılır (kontrast yüksek)
      base_display.png  → aynı görüntü, kıyafeti nötr koyuya boyanmış

    Geometri birebir aynı olduğu için katmanlar ikisine de tıpatıp oturuyor.
    (Daha önce iki AYRI fotoğrafla denenmişti ve siluetleri farklı olduğu için
    çökmüştü — buradaki fark, tek görüntünün yeniden renklendirilmesi olması.)
    """
    from wardrobe.imageutil import lab_distance, to_lab
    from wardrobe.layers import base_clothing_palette

    # Hedef yol BAŞTA çözülüyor: `ensure()` aktif mankeni oluşturabilir, ama
    # `mannequin_id` verilmişse gösterim base'i O mankene ait olmalı — aktif
    # olana değil. İki farklı satırdan iki farklı ad çıkması, katmanın bir
    # mankene, zeminin başkasına ait olması demekti (§7.5'in çöküş biçimi).
    base_row = (_row(mannequin_id, db_path) if mannequin_id is not None
                else ensure(db_path=db_path))
    hedef = display_base_path(mannequin_id=mannequin_id, db_path=db_path)
    img = load_upright(base_row["image_path"])
    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]

    # Kişi maskesi BİR KEZ hesaplanıp iki yerde kullanılıyor: palet
    # örneklemesini kişiyle sınırlamak (sabit kutu duvar örneği alabiliyor) ve
    # nötrlemeyi kişiyle kesiştirmek (§32.1). İkisi de aynı fikrin uygulaması.
    from wardrobe.cutout import person_mask_for

    kisi = person_mask_for(base_row["image_path"])
    mask = _clothing_mask(img, person=kisi)

    if not mask.any():
        img.save(hedef, "PNG")
        return hedef

    # Parlaklığı koru (kıvrımlar ve gölgeler kalsın), rengi nötre çek.
    lum = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    lo, hi = np.percentile(lum[mask], [3, 97])
    norm = np.clip((lum - lo) / max(hi - lo, 1.0), 0, 1)
    neutral = (NEUTRAL_DARK + (NEUTRAL_LIGHT - NEUTRAL_DARK) * norm[..., None])

    soft = Image.fromarray((mask * 255).astype(np.uint8), mode="L").filter(
        ImageFilter.GaussianBlur(2)
    )
    alpha = (np.asarray(soft, dtype=np.float32) / 255)[..., None]

    out = (arr * (1 - alpha) + neutral * alpha).astype(np.uint8)
    Image.fromarray(out).save(hedef, "PNG")
    return hedef


# Çıkarım base'inin kıyafetinin boyanacağı renk aralığı (koyu→açık).
#
# Chroma yeşil ÖLÇÜMLE seçildi (§44): dolaptaki 12 kıyafete en yakın uzaklığı
# 196.0 (mevcut orta mavide 60.1) ve #14 lacivert tişörtte base sızıntısını
# %44.8'den %0.1'e düşürdü — magenta ve orta mavi de sızıntıyı bitirdi ama
# uylukta gözle görülür birer renkli nokta bıraktı, yeşil bırakmadı.
#
# Doğal olmayan bir renk olması SORUN DEĞİL: bu görüntü kullanıcıya hiç
# gösterilmiyor, yalnızca VTON'a girip fark hesabında kullanılıyor.
EXTRACT_DARK = np.array([0, 120, 0])
EXTRACT_LIGHT = np.array([90, 255, 90])


def extract_base_path(mannequin_id: int | None = None, db_path=None,
                      slot: str | None = None) -> Path:
    """Çıkarım base'inin yolu — SABİT DEĞİL, çağrı anında çözülür (§28.4 #1).

    `slot` verilirse o bölgeye özel varyant: `_extract_ust.png` / `_extract_alt.png`.
    Verilmezse kıyafetin tamamı boyanmış tam varyant (`_extract.png`).
    """
    row = _row(mannequin_id, db_path)
    kok = Path(row["image_path"]).stem if row and row["image_path"] else "base"
    ek = f"_{slot}" if slot else ""
    return MANNEQUIN_DIR / f"{kok}_extract{ek}.png"


def extraction_image(mannequin_id: int | None = None, db_path=None,
                     slot: str | None = None) -> Path:
    """VTON'a ve fark hesabına GİRECEK görüntü.

    GERİ DÜŞME ZİNCİRİ: slota özel varyant → tam varyant → gerçek fotoğraf.
    Böylece her aşama opsiyonel: varyant üretilmemişse tam varyant, o da yoksa
    fotoğrafın kendisi kullanılıyor ve hat eskisi gibi çalışıyor.

    `slot` neden var: yeşile boyamak yalnızca GİYDİRİLECEK bölgede işe yarıyor.
    Üst giydirilirken şortun da yeşil olması hiçbir şey kazandırmıyor, sadece
    oradan yeşil sızma riski getiriyor.

    ⚠ Faz 4 zinciri (`render.render_outfit`) buraya BAKMAMALI: o çıktı
    doğrudan kullanıcıya gösteriliyor, yani gerçek fotoğraftan başlamalı.
    """
    for aday in ([extract_base_path(mannequin_id, db_path, slot)] if slot else []) +             [extract_base_path(mannequin_id, db_path)]:
        if aday.is_file():
            return aday
    row = _row(mannequin_id, db_path)
    return (Path(row["image_path"]) if row and row["image_path"]
            else extract_base_path(mannequin_id, db_path))


def slot_for_category(category: str | None) -> str | None:
    """Kategorinin boyanacak bölgesi: 'ust', 'alt' ya da None (tamamı).

    Elbise gibi iki bölgeyi birden kaplayan kıyafetlerde None dönüyor — orada
    kıyafetin tamamının boyanması doğru.
    """
    if not category:
        return None
    from config import slots

    s = set(slots(category))
    if s == {"ust"}:
        return "ust"
    if s == {"alt"}:
        return "alt"
    return None


def build_extract_base(mannequin_id: int | None = None, db_path=None,
                       slot: str | None = None) -> Path:
    """Fotoğrafın kıyafetini chroma yeşile boyayıp ÇIKARIM base'ini üretir.

    NEDEN VAR — §7.4'ten beri açık olan en temel kısıtı kapatıyor: *"tek base
    her renkle kontrast yapamaz, o yüzden base'in kıyafet rengindeki kıyafetler
    kör noktada kalır."* Kullanıcı ne giyerse giysin çıkarım artık maksimum
    sinyalle çalışıyor.

    Ölçüldü (manken 2, #14 lacivert tişört, base'e uzaklık 1.0, tohum 42):

        orijinal lacivert base : kaplama %5.71 · base sızıntısı **%44.8**
        chroma yeşil base      : kaplama %8.71 · base sızıntısı **%0.1**

    §7.5'teki turkuaz denemesi bunun atası ve çökmüştü — ama iki AYRI fotoğraf
    kullandığı için: siluetler farklıydı, katmanlar oturmuyordu. Burada tek
    görüntünün yeniden renklendirilmiş hâli, yani **geometri birebir aynı.**

    Ücretsiz: API çağrısı yok, sadece maske + yeniden renklendirme.
    """
    from wardrobe.cutout import person_mask_for
    from wardrobe.imageutil import lab_distance, to_lab
    from wardrobe.layers import base_clothing_palette

    row = _row(mannequin_id, db_path) or ensure(db_path=db_path)
    kaynak = row["image_path"]
    img = load_upright(kaynak)
    arr = np.asarray(img).astype(np.int16)
    h, w = arr.shape[:2]

    kisi = person_mask_for(kaynak)
    mask = _clothing_mask(img, person=kisi)

    # SLOT: yalnızca giydirilecek bölgeyi boya. Bölme güvenilir değilse
    # (üst ve alt aynı tonda) tamamı boyanıyor — yanlış yerden bölmektense.
    if slot in ("ust", "alt"):
        ust_m, alt_m = _kiyafet_bolumleri(img, mask)
        if ust_m is not None:
            mask = ust_m if slot == "ust" else alt_m

    hedef = extract_base_path(mannequin_id, db_path, slot)
    if not mask.any():
        img.save(hedef, "PNG")
        return hedef

    # Parlaklığı taşı, rengi değiştir — kıvrımlar ve gölgeler korunuyor, yoksa
    # VTON düz bir renk lekesi görüp kumaşı yanlış yorumluyor.
    lum = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    lo, hi = np.percentile(lum[mask], [3, 97])
    norm = np.clip((lum - lo) / max(hi - lo, 1.0), 0, 1)
    hedef_renk = EXTRACT_DARK + (EXTRACT_LIGHT - EXTRACT_DARK) * norm[..., None]

    soft = Image.fromarray((mask * 255).astype(np.uint8), mode="L").filter(
        ImageFilter.GaussianBlur(2)
    )
    alpha = (np.asarray(soft, dtype=np.float32) / 255)[..., None]
    out = (arr * (1 - alpha) + hedef_renk * alpha).astype(np.uint8)
    Image.fromarray(out).save(hedef, "PNG")
    return hedef


def display_base(db_path=None, mannequin_id: int | None = None) -> Path:
    """Bindirmede kullanılacak base — yoksa üretir."""
    yol = display_base_path(mannequin_id=mannequin_id, db_path=db_path)
    if yol.is_file():
        return yol
    return build_display_base(db_path=db_path, mannequin_id=mannequin_id)


# --- Manken kaydı: aktif olan, listeleme, geçiş, ekleme, silme ---

def _row(mannequin_id: int | None = None, db_path=None) -> dict | None:
    """Manken satırı: id verilirse o, verilmezse AKTİF olan. Hata fırlatmaz.

    Veritabanı henüz kurulmamışsa (tablo yok) None dönüyor — bu fonksiyon yol
    hesaplamak için çağrılıyor ve yol hesabının şema kurulumuna bağımlı olması
    sürpriz bir çökme kaynağı olurdu.
    """
    try:
        with connect(db_path) as conn:
            if mannequin_id is not None:
                row = conn.execute(
                    "SELECT * FROM mannequins WHERE id = ?", (mannequin_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM mannequins WHERE is_active = 1 "
                    "ORDER BY id LIMIT 1"
                ).fetchone()
                # Aktif işaretlenmemişse (sütun sonradan eklendi, eski DB)
                # en eskiye düş. `db._ensure_active_mannequin` bunu kalıcı
                # olarak düzeltiyor; burası yalnızca okuma yolu.
                if not row:
                    row = conn.execute(
                        "SELECT * FROM mannequins ORDER BY id LIMIT 1"
                    ).fetchone()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def active(db_path=None) -> dict | None:
    """Üzerinde çalışılan manken (dosyası olmasa da kaydı döner)."""
    return _row(db_path=db_path)


def active_id(db_path=None) -> int:
    """Aktif mankenin id'si; hiç manken yoksa 0.

    Katman ve render anahtarlarının tamamı bundan türüyor. Tek bir yerden
    gelmesi şart: iki yerde hesaplanan bir anahtar §27.1-A'da ücretle üretilmiş
    bir render'ı "kayıp" gösterdi.
    """
    row = _row(db_path=db_path)
    return int(row["id"]) if row else 0


def get_base(db_path=None) -> dict | None:
    """AKTİF mankeni döner (görseli yoksa None).

    Adı tarihsel: eskiden `WHERE name = 'base'` diye tek bir satırı okuyordu.
    Artık aktif olanı okuyor — çağıranların hepsi için doğru davranış bu,
    çünkü hepsi "şu an üzerinde çalışılan zemin"i istiyor.
    """
    row = _row(db_path=db_path)
    if not row or not row["image_path"]:
        return None
    return dict(row)


def usage(mannequin_id: int, db_path=None) -> dict:
    """Bu mankene bağlı ÜCRETLE ÜRETİLMİŞ varlıkların sayısı.

    Silme onayında gösteriliyor. Bir mankenin ~30 kredilik katmanı olabiliyor
    ve silme geri alınamaz; "N katman ve M render silinecek" demeden onay
    istemek, kullanıcıya ne kaybedeceğini söylemeden onay almaktır (§28.4 #3).
    """
    from wardrobe import edits, render

    with connect(db_path) as conn:
        katman = conn.execute(
            "SELECT COUNT(*) AS n FROM layers "
            "WHERE mannequin_id = ? AND status = 'ready'",
            (mannequin_id,),
        ).fetchone()["n"]

    onek = f"m{mannequin_id}_"
    # Katman bindirmesi (`..._katman.png`) sayılmıyor: o ÜCRETSİZ üretiliyor
    # ve silinse anında geri gelir. Onay ekranındaki sayı "kaybedilecek PARA"
    # anlamına gelmeli — bedava bir dosyayı kayıp diye saymak, kullanıcının
    # sayıya olan güvenini asıl önemli olduğu yerde zayıflatır.
    renderlar = [p for p in render.RENDER_DIR.glob(f"{onek}*.png")
                 if "_e" not in p.stem[len(onek):]
                 and not p.stem.endswith(f"_{edits.COMPOSITE_SUFFIX}")]
    duzenleme = list(render.RENDER_DIR.glob(f"{onek}*_e*.png"))
    return {"layers": int(katman), "renders": len(renderlar),
            "edits": len(duzenleme)}


def list_all(db_path=None) -> list[dict]:
    """Tüm mankenler + her birinin hazır katman sayısı, id sırasıyla."""
    with connect(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM mannequins ORDER BY id"
        )]
        sayilar = {
            r["mannequin_id"]: r["n"] for r in conn.execute(
                "SELECT mannequin_id, COUNT(*) AS n FROM layers "
                "WHERE status = 'ready' GROUP BY mannequin_id"
            )
        }
    aktif = active_id(db_path)
    for r in rows:
        r["layer_count"] = int(sayilar.get(r["id"], 0))
        r["is_active"] = r["id"] == aktif
        r["has_image"] = bool(r["image_path"]) and Path(r["image_path"]).is_file()
    return rows


def set_active(mannequin_id: int, db_path=None) -> dict:
    """Aktif mankeni değiştirir — ÜCRETSİZ ve HİÇBİR ŞEY SİLMEZ.

    §28'in bütün amacı bu fonksiyonun ucuz olması: kullanıcı iki manken
    arasında gidip gelirken katmanların yeniden üretilmesi gerekseydi her
    geçiş ~30 kredi olurdu. Katmanlar `layers` tablosunda manken başına
    saklandığı için geçiş tek bir sütun güncellemesi.
    """
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM mannequins WHERE id = ?", (mannequin_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"manken bulunamadı: {mannequin_id}")
        conn.execute("UPDATE mannequins SET is_active = 0")
        conn.execute(
            "UPDATE mannequins SET is_active = 1 WHERE id = ?", (mannequin_id,)
        )
    return {"active_id": int(mannequin_id)}


def provider_for(mannequin_id: int | None = None, db_path=None) -> str | None:
    """Mankene bağlı sanal deneme sağlayıcısı (`params_json["provider"]`), yoksa None.

    NEDEN MANKENE BAĞLI: aynı fotoğraftan iki manken açılıp biri FASHN, biri
    MAI katmanlarıyla kullanılıyor (§51.7). Sağlayıcı yalnızca küresel bir ayar
    olsaydı (VTON_PROVIDER), FASHN mankenine geçip kıyafet ekleyenin katmanı
    sessizce MAI ile üretilir, iki dolap birbirine karışırdı. Hata fırlatmaz.
    """
    row = _row(mannequin_id, db_path)
    if not row:
        return None
    try:
        return (json.loads(row["params_json"] or "{}") or {}).get("provider")
    except (ValueError, TypeError, AttributeError):
        return None


def set_provider(mannequin_id: int, provider: str | None, db_path=None) -> dict:
    """Mankenin sağlayıcısını ayarlar; None küresel sıraya döndürür. HİÇBİR ŞEY SİLMEZ.

    Var olan katmanlar yeniden üretilmiyor — ayar yalnızca bundan sonra
    üretilecek katmanları ve "Gerçekçi Göster"i etkiliyor.
    """
    from wardrobe import vton

    if provider is not None and provider not in vton._PROVIDERS:
        raise ValueError(f"bilinmeyen sağlayıcı: {provider} "
                         f"(seçenekler: {', '.join(vton._PROVIDERS)})")
    row = _row(mannequin_id, db_path)
    if not row:
        raise ValueError(f"manken bulunamadı: {mannequin_id}")
    params = json.loads(row["params_json"] or "{}") or {}
    if provider is None:
        params.pop("provider", None)
    else:
        params["provider"] = provider
    with connect(db_path) as conn:
        conn.execute("UPDATE mannequins SET params_json = ? WHERE id = ?",
                     (json.dumps(params, ensure_ascii=False), mannequin_id))
    return {"mannequin_id": int(mannequin_id), "provider": provider}


def delete(mannequin_id: int, db_path=None) -> dict:
    """Mankeni ve ONA AİT her şeyi siler — GERİ ALINAMAZ.

    Katmanlar `ON DELETE CASCADE` ile gidiyor; dosyaları elle siliyoruz çünkü
    SQLite diskteki PNG'lerden habersiz.

    İki koruma var:
      · Son manken silinemez — sonuç "manken yok" durumu olurdu ve dolap
        bir anda kullanılamaz hale gelirdi.
      · Aktif manken silinirse başka biri otomatik aktif olur, "aktif yok"
        ara durumu hiç oluşmuyor.
    """
    from config import LAYER_DIR                # çağrı anında: tmp yönlendirmesi
    from wardrobe import render

    hepsi = list_all(db_path)
    if len(hepsi) <= 1:
        raise ValueError("son manken silinemez — dolap zeminsiz kalır")
    hedef = next((m for m in hepsi if m["id"] == mannequin_id), None)
    if not hedef:
        raise ValueError(f"manken bulunamadı: {mannequin_id}")

    kayip = usage(mannequin_id, db_path)

    with connect(db_path) as conn:
        katman_yollari = [r["png_path"] for r in conn.execute(
            "SELECT png_path FROM layers WHERE mannequin_id = ?", (mannequin_id,)
        )]
        conn.execute("DELETE FROM mannequins WHERE id = ?", (mannequin_id,))

    silinecek = [Path(p) for p in katman_yollari if p]
    silinecek += list(LAYER_DIR.glob(f"g*_m{mannequin_id}.png"))
    silinecek += list(LAYER_DIR.glob(f"g*_m{mannequin_id}_raw*.png"))
    silinecek += list(render.RENDER_DIR.glob(f"m{mannequin_id}_*"))
    if hedef["image_path"]:
        # Gösterim base'inin adı görselin adından türüyor; satır artık DB'de
        # olmadığı için `display_base_path` sorulamaz, aynı kural elle uygulanıyor.
        kok = Path(hedef["image_path"]).stem
        silinecek += [Path(hedef["image_path"]),
                      MANNEQUIN_DIR / f"{kok}_display.png"]

    for p in silinecek:
        try:
            p.unlink(missing_ok=True)
        except (OSError, TypeError):
            pass

    with connect(db_path) as conn:
        from db import _ensure_active_mannequin
        yeni_aktif = _ensure_active_mannequin(conn)

    return {"deleted": mannequin_id, "active_id": yeni_aktif, **kayip}


def _edge_color(image: Image.Image) -> tuple[int, int, int]:
    """Kenar piksellerinin medyan rengi — dolgu bandı için."""
    arr = np.asarray(image.convert("RGB"))
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    return tuple(int(c) for c in np.median(border, axis=0))


def fit_to_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """En-boy oranını KORUYARAK hedef tuvale oturtur.

    Doğrudan `resize(size)` çağırmak fotoğrafı hedef orana zorluyor: 3:4 çekilmiş
    bir telefon fotoğrafı 2:3'e sıkıştırıldığında kişi incelip uzuyor. Katman
    hattı için felaket — çünkü tüm kıyafetler o bozuk orana göre giydiriliyor
    ve kullanıcı kendini yanlış oranda görüyor.

    Bunun yerine: orantılı küçült, kalan boşluğu kenar renginde bantla doldur.
    Bantlar tüm katmanlarda aynı olduğu için fark tabanlı çıkarımı etkilemiyor.
    """
    scaled = image.copy()
    scaled.thumbnail(size, Image.LANCZOS)

    canvas = Image.new("RGB", size, _edge_color(image))
    canvas.paste(
        scaled, ((size[0] - scaled.width) // 2, (size[1] - scaled.height) // 2)
    )
    return canvas


def _yeni_ad(db_path=None) -> str:
    """Çakışmayan bir manken adı üretir: 'Manken 2', 'Manken 3'…

    `mannequins.name` UNIQUE. Ad çakışırsa INSERT patlar ve kullanıcı, kendi
    seçmediği bir alanın kısıtı yüzünden anlaşılmaz bir hata görür.
    """
    with connect(db_path) as conn:
        mevcut = {r["name"] for r in conn.execute("SELECT name FROM mannequins")}
    n = len(mevcut) + 1
    while f"Manken {n}" in mevcut:
        n += 1
    return f"Manken {n}"


def _save(
    image: Image.Image,
    kind: str,
    params: dict,
    db_path=None,
    *,
    name: str | None = None,
) -> dict:
    """Manken görselini diske, kaydını DB'ye yazar.

    İKİ AYRI İŞ, tek fonksiyonda ama net ayrılmış (§28.4 #2 — bu ayrım
    yapılmazsa "yeni manken ekle" sessizce "mevcut mankeni ez"e dönüşür):

      name VERİLİRSE  → YENİ manken kaydı açılır ve aktif olur. Hiçbir katman,
                        render ya da düzenleme silinmez. Diğer mankenler
                        olduğu gibi durur. Ücretsiz.
      name VERİLMEZSE → AKTİF mankenin fotoğrafı değişir. O mankenin katmanları
                        (eski vücut hattına göre kesilmişler) ve renderları
                        geçersiz — SADECE onunkiler.
    """
    image = fit_to_canvas(image.convert("RGB"), MANNEQUIN_SIZE)

    if name is not None:
        return _yeni_manken(image, kind, params, name, db_path)

    row = _row(db_path=db_path)
    if row is None:
        # Hiç manken kaydı yok (init_db çalışmamış): varsayılanı aç.
        return _yeni_manken(image, kind, params, DEFAULT_NAME, db_path)

    mannequin_id = int(row["id"])
    # Mevcut dosya adı korunuyor: `data/mannequins/base.png` ve ona ait
    # 11 katman yerinde duruyor, yeniden adlandırmak onları kaybetmek olurdu.
    path = (Path(row["image_path"]) if row["image_path"]
            else image_path_for(mannequin_id, row["name"]))
    image.save(path, "PNG")

    # Gösterim base'i artık eski fotoğraf için üretilmiş — sil, ilk ihtiyaçta
    # yenisi kurulur. Bırakılırsa katmanlar yeni fotoğrafa, zemin eskisine ait
    # olur ve bunu hiçbir test yakalamaz.
    display_base_path(mannequin_id=mannequin_id, db_path=db_path).unlink(
        missing_ok=True)

    # Faz 4 renderları da eski fotoğrafa ait — onlar da geçersiz. YALNIZCA bu
    # mankeninkiler: diğer mankenlerin renderları bu değişiklikten etkilenmiyor
    # ve onları silmek ücretle üretilmiş veriyi sebepsiz yok etmek olurdu.
    from wardrobe.render import clear_cache      # döngüsel import olmasın diye içeride
    clear_cache(mannequin_id)

    with connect(db_path) as conn:
        conn.execute(
            "UPDATE mannequins SET kind = ?, image_path = ?, params_json = ? "
            "WHERE id = ?",
            (kind, str(path), json.dumps(params, ensure_ascii=False), mannequin_id),
        )
    stale = _invalidate_layers(mannequin_id, db_path)
    return {"kind": kind, "image_path": str(path), "size": MANNEQUIN_SIZE,
            "mannequin_id": mannequin_id, "name": row["name"], "created": False,
            "invalidated_layers": stale}


def _yeni_manken(
    image: Image.Image, kind: str, params: dict, name: str, db_path=None
) -> dict:
    """Yeni manken satırı + görseli. HİÇBİR ŞEY SİLMEZ, aktif olur.

    Satır ÖNCE açılıyor çünkü dosya adı id'yi içeriyor (`base_3.png`) — id
    olmadan dosyayı nereye yazacağımızı bilmiyoruz. Yol sonradan UPDATE ile
    yazılıyor; arada bir hata olursa geriye görselsiz bir satır kalır ve o
    satır `has_image: False` olarak görünür (sessiz bozukluk değil).
    """
    with connect(db_path) as conn:
        var = conn.execute(
            "SELECT id FROM mannequins WHERE name = ?", (name,)
        ).fetchone()
        if var:
            raise ValueError(f"bu adda bir manken zaten var: {name}")
        cur = conn.execute(
            "INSERT INTO mannequins (name, kind, params_json) VALUES (?, ?, ?)",
            (name, kind, json.dumps(params, ensure_ascii=False)),
        )
        mannequin_id = int(cur.lastrowid)

    path = image_path_for(mannequin_id, name)
    image.save(path, "PNG")

    with connect(db_path) as conn:
        conn.execute("UPDATE mannequins SET image_path = ? WHERE id = ?",
                     (str(path), mannequin_id))
    set_active(mannequin_id, db_path)

    return {"kind": kind, "image_path": str(path), "size": MANNEQUIN_SIZE,
            "mannequin_id": mannequin_id, "name": name, "created": True,
            "invalidated_layers": 0}


def _invalidate_layers(mannequin_id: int | None = None, db_path=None) -> int:
    """Bir mankenin FOTOĞRAFI değişince onun katmanlarını geçersiz kılar.

    Katman = "bu manken bu kıyafeti giydiğinde değişen pikseller". Fotoğraf
    değişirse o fark artık anlamsız: eski katman eski vücut hattına göre
    kesilmiş, yeni fotoğrafın üstüne bindirince kayıyor.

    Ham çıktılar da geçersiz — eski fotoğrafı giydirilmiş halde gösteriyorlar,
    yeni base ile farkları saçmalık üretir. Bu yüzden dosyalar siliniyor;
    aksi halde `--reextract` sessizce bozuk katman üretirdi.

    ⚠ KAPSAM TEK MANKEN. Manken *değiştirmek* buraya hiç uğramamalı — §28'in
    tamamı bunun için: geçiş bedava ve kayıpsız olsun diye.
    """
    from config import LAYER_DIR

    if mannequin_id is None:
        mannequin_id = active_id(db_path)
    if not mannequin_id:
        return 0

    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT garment_id, png_path FROM layers "
            "WHERE mannequin_id = ? AND status != 'stale'",
            (mannequin_id,),
        ).fetchall()

        for r in rows:
            for p in (r["png_path"],
                      LAYER_DIR / f"g{r['garment_id']}_m{mannequin_id}_raw.png"):
                try:
                    Path(p).unlink(missing_ok=True)
                except (OSError, TypeError):
                    pass

        conn.execute(
            "UPDATE layers SET status = 'stale', png_path = '', "
            "error = 'mankenin fotoğrafı değişti — yeniden üretilmeli' "
            "WHERE mannequin_id = ?",
            (mannequin_id,),
        )
    return len(rows)


def from_photo(photo_path: str | Path, db_path=None, *, name: str | None = None) -> dict:
    """Kullanıcının kendi fotoğrafını manken yapar.

    `name` verilirse YENİ bir manken açılır (mevcutlar korunur, katmanları
    yerinde kalır). Verilmezse aktif mankenin fotoğrafı değişir ve YALNIZCA
    onun katmanları geçersiz olur.

    En iyi sonuç: tam boy, önden, düz duruş, sade zemin ve **dar, sade, tek
    renk** kıyafet.

    "Dar ve sade" bir tercih değil, ölçülmüş bir gereklilik. Katman, base ile
    giydirilmiş görüntünün FARKI. Base'in kendi kıyafeti yeni kıyafetten
    genişse, aradaki fark da katmana giriyor — yani base'in kıyafeti yeni
    kıyafetin içine sızıyor.

    Ölçtük (bkz. HANDOFF §7): bol lacivert tişört + desenli gri şort giyen bir
    base'de bordo polo katmanının %8.2'si poloya ait değildi ve o piksellerin
    %90'ı base'in gri şortuyla birebir aynı renkteydi (medyan uzaklık 6/441),
    tam bel çizgisinde toplanmıştı. Aynı polo, dar siyah polo + sade siyah şort
    giyen bir base'de üretilince kirlilik %4.3'e indi ve bel bandı kayboldu.
    """
    img = load_upright(photo_path)
    return _save(img, "photo", {"source": str(photo_path)}, db_path=db_path,
                 name=name)


def generate(db_path=None, *, provider=None, style: str = DEFAULT_STYLE,
             name: str | None = None) -> dict:
    """Görsel üretebilen sağlayıcıyla base manken üretir (fal ya da Foundry).

    Args:
        style: "person" (önerilen — VTON modelleri insan bekliyor) veya
            "mannequin" (vitrin mankeni; karşılaştırma için).

    Anahtar yoksa placeholder'a düşer — hat kırılmaz.
    """
    from wardrobe import secrets, vton

    if style not in GENERATION_PROMPTS:
        raise ValueError(
            f"Bilinmeyen stil: {style} "
            f"(seçenekler: {', '.join(GENERATION_PROMPTS)})"
        )

    provider = provider or vton.get_provider()

    # Teşhis doğru olmalı: "mock görsel üretemez" teknik olarak doğru ama
    # kullanıcının yapması gereken şeyi söylemiyor. Asıl eksiği raporla.
    if not provider.available() or not provider.supports_text_to_image:
        if not secrets.has("FAL_KEY"):
            reason = ("FAL_KEY yok — .env'e ekle (ya da Foundry görüntü "
                      "dağıtımı: FOUNDRY_IMAGE_DEPLOYMENT)")
        elif provider.name == "mock":
            reason = 'fal-client kurulu değil — pip install fal-client'
        else:
            reason = f"{provider.name} manken üretemiyor"
        return placeholder(db_path=db_path, reason=reason, name=name)

    prompt = GENERATION_PROMPTS[style]
    try:
        img = provider.text_to_image(prompt, MANNEQUIN_SIZE)
        return _save(img, "generated", {"style": style, "prompt": prompt},
                     db_path=db_path, name=name)
    except Exception as exc:
        return placeholder(db_path=db_path, reason=f"üretim hatası: {exc}",
                           name=name)


def placeholder(db_path=None, reason: str = "", *, name: str | None = None) -> dict:
    """PIL ile çizilmiş basit figür — anahtarsız geliştirme ve testler için.

    Gerçekçi değil ve olmasına gerek yok: amacı katman hattının uçtan uca
    çalıştığını para harcamadan doğrulamak.
    """
    w, h = MANNEQUIN_SIZE
    img = Image.new("RGB", (w, h), (232, 232, 236))
    d = ImageDraw.Draw(img)
    skin = (198, 176, 158)
    cx = w // 2

    d.ellipse([cx - 78, int(h * 0.055), cx + 78, int(h * 0.055) + 156], fill=skin)
    d.rectangle([cx - 34, int(h * 0.175), cx + 34, int(h * 0.215)], fill=skin)
    d.rounded_rectangle(
        [cx - 150, int(h * 0.205), cx + 150, int(h * 0.545)], radius=60, fill=skin
    )
    for side in (-1, 1):
        x = cx + side * 150
        d.rounded_rectangle(
            [min(x, x + side * 62), int(h * 0.215),
             max(x, x + side * 62), int(h * 0.525)], radius=30, fill=skin
        )
    for side in (-1, 1):
        x = cx + side * 46
        d.rounded_rectangle(
            [min(x - 34, x + 34), int(h * 0.53),
             max(x - 34, x + 34), int(h * 0.93)], radius=34, fill=skin
        )

    result = _save(img, "placeholder", {"reason": reason}, db_path=db_path,
                   name=name)
    result["reason"] = reason
    return result


def ensure(db_path=None) -> dict:
    """Aktif manken yoksa oluşturur, varsa mevcut kaydı döner."""
    existing = get_base(db_path=db_path)
    if existing and Path(existing["image_path"]).is_file():
        return {"kind": existing["kind"], "image_path": existing["image_path"],
                "size": MANNEQUIN_SIZE, "existing": True,
                "mannequin_id": int(existing["id"]), "name": existing["name"]}
    return generate(db_path=db_path)


def add_from_photo(photo_path: str | Path, name: str | None = None,
                   db_path=None) -> dict:
    """YENİ manken ekler (ücretsiz) ve aktif yapar — mevcutlara dokunmaz.

    Arayüzün "+ Yeni manken" akışının tek girişi. Katman üretimi buraya DAHİL
    DEĞİL ve olmamalı: manken eklemek bedava, katman üretmek ücretli. İkisini
    tek düğmeye bağlamak kullanıcıyı, ne kadar ödeyeceğini bilmeden ücretli bir
    işleme sokardı.
    """
    return from_photo(photo_path, db_path=db_path,
                      name=(name or "").strip() or _yeni_ad(db_path))
