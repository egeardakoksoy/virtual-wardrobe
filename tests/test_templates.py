"""Çekim şablonları ve segmentasyon önseli.

Şablonun iki işi var: kullanıcıya çekim rehberi olmak ve kırpma bozulduğunda
önsel olarak kurtarma yapmak. Buradaki testler ikincisini — ölçülebilir olanı —
kilitliyor.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from config import CATEGORIES
from wardrobe import cutout, templates


def test_tum_sablonlar_gecerli():
    for key, s in templates.SHAPES.items():
        assert s["label"], key
        # Kategori config.CATEGORIES'ten gelmeli — z sırası ve çakışma kuralı
        # oradan okunuyor.
        assert s["category"] in CATEGORIES, f"{key}: geçersiz kategori"
        # En az 4 nokta. Ölçümde (§17) düz bir dikdörtgen bile bozuk kırpmayı
        # düzeltmişti, yani silüetin hassas olması gerekmiyor.
        assert len(s["points"]) >= 4, f"{key}: silüet için en az 4 nokta gerekli"
        for x, y in s["points"]:
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0, f"{key}: normalize değil"


def test_HER_kategorinin_en_az_bir_sablonu_var():
    """Şablonsuz kategori sessiz bir tuzak.

    `elbise` ve `dis_giyim` kategorileri baştan beri tanımlıydı ama şablonları
    yoktu: elbise yükleyen kullanıcı "Tişört" seçmek zorunda kalıyor, kırpma
    kurtarması devreye girerse o yanlış önsel eteği kesiyordu.

    Ayakkabı bilerek dışarıda: base manken diz altından kesik, giydirecek yer
    yok (§10). Aksesuar da öyle — özellik geri alındı (§47.7), şablonları
    kaldırıldı; kategori tabloda duruyor ama kullanılmıyor.
    """
    kapsanan = {s["category"] for s in templates.SHAPES.values()}
    eksik = set(CATEGORIES) - kapsanan - {"ayakkabi", "aksesuar"}
    assert not eksik, f"şablonu olmayan kategori: {sorted(eksik)}"


def test_varsayilan_sablon_var():
    assert templates.DEFAULT_SHAPE in templates.SHAPES


def test_bilinmeyen_sablon_varsayilana_duser():
    assert templates.shape_points("boyle-bir-sey-yok") == \
           templates.shape_points(templates.DEFAULT_SHAPE)


def test_onsel_maskesi_ortada_ve_kenara_degmiyor():
    """Şablon, kadrajın ortasını kaplamalı; kenara dayanırsa işe yaramaz."""
    m = templates.prior_mask("tisort", 200, 300)

    assert m[150, 100], "merkez şablonun içinde olmalı"
    assert not m[0].any() and not m[-1].any(), "üst/alt kenara değmemeli"
    assert 0.2 < m.mean() < 0.9


def test_onsel_marj_ile_genisliyor():
    dar = templates.prior_mask("tisort", 200, 300, margin=0.0)
    genis = templates.prior_mask("tisort", 200, 300, margin=0.2)
    assert genis.sum() > dar.sum()


def test_onsel_zemin_dilimini_kesip_kiyafeti_birakiyor():
    """Ölçülmüş vakanın sentetik hali.

    Kadrajın soluna yapışık bir zemin dilimi + ortada kıyafet. Önsel dilimi
    kesmeli, kıyafeti bırakmalı.

    NOT: "kenara değen parçayı at" yaklaşımı burada işe YARAMAZ, çünkü gerçek
    vakada zemin kıyafete yapışıktı (tek bileşen) — ölçümde kaplama %0.1'e
    düşmüştü. Bu yüzden pozitif önsel kullanılıyor.
    """
    h, w = 300, 200
    maske = np.zeros((h, w), dtype=bool)
    maske[80:250, 60:140] = True      # kıyafet, ortada
    maske[100:200, 0:70] = True       # zemin dilimi, sol kenara yapışık

    assert cutout._mask_touches_edge(maske), "test kurulumu: kenara değmeli"

    temiz = cutout._apply_prior(maske, "tisort")

    assert not cutout._mask_touches_edge(temiz), "önsel kenardaki dilimi kesmeli"
    assert temiz[150, 100], "kıyafetin gövdesi korunmalı"
    assert temiz.sum() < maske.sum()


def test_onsel_her_seyi_silerse_dokunmuyor():
    """Güvenlik freni: önsel maskeyi tamamen yerse ham maskeye dön."""
    maske = np.zeros((300, 200), dtype=bool)
    maske[0:20, 0:20] = True          # şablonun tamamen dışında

    assert cutout._apply_prior(maske, "tisort").sum() == maske.sum()


def test_sablon_secimi_kirpmaya_geciyor(tmp_path, monkeypatch):
    """remove_background shape parametresini kabul etmeli (uçtan uca bağ)."""
    foto = tmp_path / "k.jpg"
    arr = np.full((300, 220, 3), 250, dtype=np.uint8)
    arr[80:230, 60:170] = (200, 40, 45)
    Image.fromarray(arr).save(foto)

    dst = tmp_path / "c.png"
    monkeypatch.setattr(cutout, "DEFAULT_METHOD", "flood")
    cutout.remove_background(foto, dst, shape="pantolon")
    assert dst.is_file()


# --- Önsel KUTU olmalı, poligon değil (§34) ---

def test_onsel_sinirlayici_kutu_kiyafet_siluetini_dayatmiyor():
    """Önsel maskeyle KESİŞİYOR, yani yalnızca silebiliyor.

    Poligon kullanıldığında kıyafet şablondan genişse fazlası kesiliyordu ve
    sonuç kıyafetin değil ŞABLONUN silüeti oluyordu. Ölçülen vaka: chino
    pantolonun paça genişliği 340 px → 91 px, ve çıkan maske şablonun
    kendisiyle birebir aynıydı.

    Dayanak §17'nin kendi ölçümü: "düz bir DİKDÖRTGEN bile sorunu çözdü".
    Önselin işi "kıyafet kabaca burada" demek, siluet dayatmak değil.
    """
    from wardrobe.templates import prior_mask

    m = prior_mask("pantolon", 200, 300)
    ys, xs = np.where(m)
    kutu = (ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)
    assert m.sum() == kutu, "önsel dikdörtgen değil — poligona geri dönülmüş"


def test_onsel_sablonun_disini_hala_eliyor():
    """Kutu olması onu etkisiz yapmamalı — kadrajın kenarındaki nesne gitmeli.

    Kurtarmanın asıl işi buydu: kıyafetin ALTINDAKİ yabancı nesneyi (sehpa,
    stand) atmak. Ölçümde kutu bunu hâlâ yapıyor (#10 ve #14'te stand gitti).
    """
    from wardrobe.templates import prior_mask

    m = prior_mask("tisort", 200, 300)
    assert not m[0, 0], "sol üst köşe önselin içinde — kutu çok geniş"
    assert m[150, 100], "tuvalin ortası önselin dışında — kutu çok dar"
    assert m.mean() < 0.95, "önsel neredeyse tüm tuval — hiçbir şey elemiyor"


def test_sablon_onseli_KAPALI():
    """Kurtarma önseli kapalı olmalı — açan, aşağıdaki ölçümleri çürütmeli.

    Önsel §17'de eklendi ve gerekçesi ölçülmüştü (beyaz tişört + beyaz çarşaf,
    ESKİ u2net): şablon bozuk kırpığı düzeltmişti. O ölçüm doğruydu ama
    koşulları geçti. Bugün isnet ile ölçülen, 12 kıyafet:

      · 6'sında tetikleniyor — "yalnızca bozuk vakalara dokunur" değil
      · tetiklendiğinde maskenin %18-47'sini siliyor
      · #16'da sonuç ŞABLONUN KENDİSİYLE birebir aynı: kırpık pantolonun
        değil, `pantolon` şablonunun silüetiydi (paça 596 → 91 px)
      · §17'yi motive eden vaka (#12) isnet ile kadraj kenarına hiç değmiyor,
        yani kurtarmaya zaten uğramıyor — asıl düzeltme §16'daki model
        değişikliğiydi (u2net → isnet), şablon değil

    Şablonlar ÇEKİM REHBERİ olarak duruyor; asıl değerleri orada.
    """
    assert cutout.PRIOR_RESCUE is False, (
        "şablon önseli açılmış — kıyafetin silüetini şablonunkiyle değiştiriyor")
