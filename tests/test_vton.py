"""Sağlayıcı seçimi ve kategori eşlemesi.

Bu testler ağa çıkmaz. FalProvider'ın gerçek çağrısı test edilmiyor (para ve
ağ gerektirir); test edilen şey ona kadar olan karar zinciri — hangi sağlayıcı,
hangi kategori, neyi reddediyoruz.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wardrobe import vton


def test_desteklenen_kategoriler_eslenir():
    assert vton.to_fashn_category("ust") == "tops"
    assert vton.to_fashn_category("alt") == "bottoms"
    assert vton.to_fashn_category("elbise") == "one-pieces"


def test_dis_giyim_tops_a_eslenir():
    """FASHN'da ayrı dış giyim sınıfı yok; üst beden en yakın karşılık."""
    assert vton.to_fashn_category("dis_giyim") == "tops"


@pytest.mark.parametrize("category", ["ayakkabi", "aksesuar"])
def test_desteklenmeyen_kategori_acikca_reddedilir(category):
    """Sessizce bozuk katman üretmektense açıkça reddet.

    VITON-HD / DressCode veri setlerinde ayakkabı sınıfı yok; zorlamak
    tanınmayan bir şeyi üst bedene giydirmeye çalışıyor.
    """
    with pytest.raises(vton.UnsupportedCategory):
        vton.to_fashn_category(category)


def test_anahtar_yokken_mock_secilir():
    """conftest tüm sağlayıcı anahtarlarını siliyor — hiçbiri kullanılamaz."""
    assert vton.get_provider().name == "mock"


def test_fashn_fal_dan_ONCE_geliyor(monkeypatch):
    """§25: tryon-max ölçümle daha iyi çıktı ve kredi başına fiyat aynı.

    Sıra önemli çünkü arayüzden kıyafet eklendiğinde de burası çalışıyor:
    fal önce gelseydi web'den eklenen her kıyafet sessizce ESKİ modelle
    üretilir ve dolabın geri kalanıyla tutarsız olurdu.
    """
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("FASHN_API_KEY", "y")
    monkeypatch.setattr(vton.FalProvider, "available", lambda self: True)

    assert vton.get_provider().name == "fashn"


def test_fashn_anahtari_yoksa_fal_a_dusuyor(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setattr(vton.FalProvider, "available", lambda self: True)

    assert vton.get_provider().name == "fal"


def test_ortam_degiskeni_saglayiciyi_secer(monkeypatch):
    monkeypatch.setenv("VTON_PROVIDER", "mock")
    assert vton.get_provider().name == "mock"


def test_bilinmeyen_saglayici_reddedilir():
    with pytest.raises(ValueError, match="Bilinmeyen sağlayıcı"):
        vton.get_provider("midjourney")


def test_mock_her_zaman_kullanilabilir():
    assert vton.MockProvider().available()


def test_fal_client_yoksa_fal_kullanilamaz(monkeypatch):
    """Anahtar var ama paket yoksa sessizce mock'a düşmeli."""
    monkeypatch.setenv("FAL_KEY", "sahte-anahtar")
    monkeypatch.setitem(__import__("sys").modules, "fal_client", None)
    assert vton.FalProvider().available() is False


def test_mock_kiyafeti_dogru_bolgeye_koyar(tmp_path):
    """Üst giyim gövdeye, alt giyim bacaklara — bant tablosuna göre."""
    from PIL import Image
    import numpy as np

    base = Image.new("RGB", (200, 400), (230, 230, 230))
    base_path = tmp_path / "manken.png"
    base.save(base_path)

    garment = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    garment_path = tmp_path / "kiyafet.png"
    garment.save(garment_path)

    provider = vton.MockProvider()
    ust = np.asarray(provider.try_on(base_path, garment_path, "ust"))
    alt = np.asarray(provider.try_on(base_path, garment_path, "alt"))

    def red_rows(arr):
        rows = np.where((arr[:, :, 0] > 200) & (arr[:, :, 1] < 60))[0]
        return rows.mean() if len(rows) else -1

    assert red_rows(ust) < red_rows(alt), "üst giyim alt giyimden yukarıda olmalı"


def test_mock_desteklenmeyen_kategoride_de_reddeder(tmp_path):
    """Sağlayıcı değişince kural değişmemeli."""
    from PIL import Image

    base = tmp_path / "m.png"
    Image.new("RGB", (100, 200)).save(base)
    garment = tmp_path / "g.png"
    Image.new("RGBA", (50, 50)).save(garment)

    with pytest.raises(vton.UnsupportedCategory):
        vton.MockProvider().try_on(base, garment, "ayakkabi")


# --- Ücretli çağrı öncesi indirme yolu kontrolü ---
#
# Bu testlerin varlık sebebi ölçülmüş bir kayıp: makinenin DNS'i *.fal.media'yı
# çözemezken fal.run çalışıyordu. inference tamamlandı, ÜCRETLENDİ, sonra
# indirme patladı ve çıktı çöpe gitti. İki çağrı böyle kayboldu.

def test_medya_sunucusu_cozulmezse_cagri_reddedilir(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: (_ for _ in ()).throw(socket.gaierror("çözülemedi")),
    )
    with pytest.raises(vton.ResultUnreachable):
        vton.require_media_host(vton.FAL_TRYON_ENDPOINT)


def test_medya_sunucusu_cozulurse_gecer(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [("x",)])
    vton.require_media_host(vton.FAL_TRYON_ENDPOINT)      # fırlatmamalı


def test_tryon_sonucu_fashn_cdn_inden_iniyor():
    """Ölçülmüş gerçek: 'fal olduğuna göre fal.media'dır' varsayımı yanlıştı.

    Yanlış sunucuya bakan bir ön kontrol geçer, çağrı gider, para yanar.
    """
    assert vton.RESULT_HOSTS[vton.FAL_TRYON_ENDPOINT] == ("cdn.fashn.ai",)


def test_ilgisiz_cdn_dusunce_hat_kilitlenmez(monkeypatch):
    """Metin→görsel CDN'i düşse bile sanal deneme çalışmaya devam etmeli."""
    import socket

    çalışan = vton.RESULT_HOSTS[vton.FAL_TRYON_ENDPOINT]

    def seçici(host, *a, **k):
        if host in çalışan:
            return [("x",)]
        raise socket.gaierror("çözülemedi")

    monkeypatch.setattr(socket, "getaddrinfo", seçici)

    vton.require_media_host(vton.FAL_TRYON_ENDPOINT)          # geçmeli
    with pytest.raises(vton.ResultUnreachable):
        vton.require_media_host(vton.FAL_TEXT_TO_IMAGE_ENDPOINT)


def test_on_kontrol_para_harcanmadan_once_calisir(monkeypatch):
    """En pahalı hata türü: ücretlendirilen ama indirilemeyen çağrı.

    Kontrol client'a DOKUNULMADAN önce olmalı — yoksa istek gider, para gider.
    """
    monkeypatch.setattr(vton, "media_host_resolves", lambda hosts: False)

    def patlasin(self):
        raise AssertionError("indirme yolu doğrulanmadan client'a dokunuldu")

    monkeypatch.setattr(vton.FalProvider, "_client", patlasin)

    with pytest.raises(vton.ResultUnreachable):
        vton.FalProvider().try_on(Path("m.png"), Path("g.png"), "ust")


def test_indirme_pes_ederken_url_yi_korur(monkeypatch):
    """İnference ücretlendirildiyse çıktı fal'da duruyor — URL'yi kaybetme."""
    import urllib.error
    import urllib.request

    def kirik(*a, **k):
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(urllib.request, "urlopen", kirik)

    url = "https://v3.fal.media/files/sonuc.png"
    with pytest.raises(vton.ResultUnreachable) as exc:
        vton._download_image(url, attempts=1)
    assert url in str(exc.value), "kurtarma için URL hata mesajında kalmalı"
