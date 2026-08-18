"""Test altyapısı — sentetik kıyafet görselleri ve izole veri dizinleri.

Üç güvenlik kuralı, üçü de autouse:
1. ANTHROPIC_API_KEY silinir. Testler asla gerçek API çağırmaz; geliştiricinin
   .env'i yüklü olsa bile fatura üretmez.
2. Varsayılan veritabanı tmp_path'e yönlendirilir.
3. Yükleme hattının yazdığı dizinler tmp_path'e yönlendirilir.

(2) ve (3) olmadan testler kullanıcının gerçek dolabına kayıt atardı.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Testleri gerçek API'den, gerçek DB'den ve gerçek data/ klasöründen ayırır."""
    # TÜM sağlayıcı anahtarları silinir, sadece Anthropic'inki değil.
    #
    # Eskiden yalnızca ANTHROPIC_API_KEY siliniyordu ve sonuç sinsiydi:
    # sağlayıcı seçimini test eden testler geliştiricinin .env'ine bağlı hale
    # geliyordu. `get_provider()` varsayılanı fal'dan fashn'a çevrildiğinde
    # bir test kırıldı — ama kırılma sebebi kod değil, testin FASHN_API_KEY'i
    # ortamdan görmesiydi. Anahtarı olmayan bir makinede aynı test geçerdi.
    # §6.1 #8'in aynısı: izolasyon eksikse testin ne ölçtüğünü bilemezsin.
    #
    # Anahtar gereken testler onu kendisi monkeypatch'liyor.
    for key in ("ANTHROPIC_API_KEY", "FAL_KEY", "FASHN_API_KEY",
                "REPLICATE_API_TOKEN", "VTON_PROVIDER"):
        monkeypatch.delenv(key, raising=False)

    raw = tmp_path / "raw"
    cutout = tmp_path / "cutout"
    raw.mkdir()
    cutout.mkdir()
    monkeypatch.setattr("wardrobe.ingest.RAW_DIR", raw)
    monkeypatch.setattr("wardrobe.ingest.CUTOUT_DIR", cutout)
    monkeypatch.setattr("db.DB_PATH", tmp_path / "wardrobe.db")

    # KRİTİK: manken ve katman dizinleri de yönlendirilmeli.
    # Bunlar eksikken testler kullanıcının GERÇEK base mankenini çubuk adam
    # placeholder'ıyla ezdi. Sonuç sinsi oldu: hiçbir test kırılmadı, ama
    # sonraki her katman çıkarımı gerçek fotoğrafı çubuk adamla karşılaştırdı
    # ve %99 fark üretti. İki ayrı algoritma denemesi bu bozuk veri yüzünden
    # "başarısız" göründü. Test izolasyonu eksikse ölçümlerine güvenemezsin.
    for name in ("mannequins", "layers", "renders"):
        (tmp_path / name).mkdir(exist_ok=True)
    monkeypatch.setattr("wardrobe.mannequin.MANNEQUIN_DIR", tmp_path / "mannequins")
    monkeypatch.setattr("wardrobe.layers.LAYER_DIR", tmp_path / "layers")
    monkeypatch.setattr("config.LAYER_DIR", tmp_path / "layers")
    # Faz 4 renderları da yönlendirilmeli — aksi halde testler kullanıcının
    # ÜCRETLİ üretilmiş renderlarını siler (clear_cache manken değişiminde
    # çalışıyor). Aynı hata iki kez yapıldı, bkz. §6.1 #8 ve #13.
    monkeypatch.setattr("wardrobe.render.RENDER_DIR", tmp_path / "renders")

    # has_rembg() sonucu önbelleğe alıyor; testler arasında sızmasın.
    monkeypatch.setattr("wardrobe.cutout._rembg_available", None)

    # Kırpmayı flood'a sabitle. Aksi halde test sonuçları geliştiricinin
    # makinesinde rembg kurulu olup olmamasına göre değişir (aynı test bir
    # makinede geçip diğerinde kalır) ve test süresi 4 sn'den 65 sn'ye çıkar.
    # rembg yolunun kendisi test_cutout.py'de ayrıca test ediliyor.
    monkeypatch.setattr("wardrobe.cutout.DEFAULT_METHOD", "flood")
    return raw, cutout


@pytest.fixture
def db_path(tmp_path) -> Path:
    """İzole, şeması kurulmuş boş veritabanı."""
    path = tmp_path / "test.db"
    init_db(path)
    return path


def make_garment_photo(
    path: Path,
    color: tuple[int, int, int] = (200, 40, 45),
    size: int = 200,
    background: tuple[int, int, int] = (250, 250, 250),
    hole: bool = False,
) -> Path:
    """Düz zemin üstünde tek renkli bir 'kıyafet' üretir.

    hole=True ise kıyafetin ortasına arka plan renginde bir leke koyar —
    flood fill'in "kenara bağlı olmayan" bölgeleri arka plan saymadığını
    doğrulamak için.
    """
    img = Image.new("RGB", (size, size), background)
    quarter, half = size // 4, size // 2
    for x in range(quarter, quarter + half):
        for y in range(quarter, quarter + half):
            img.putpixel((x, y), color)

    if hole:
        cx = cy = size // 2
        for x in range(cx - 8, cx + 8):
            for y in range(cy - 8, cy + 8):
                img.putpixel((x, y), background)

    img.save(path, "JPEG", quality=95)
    return path


@pytest.fixture
def photo(tmp_path) -> Path:
    return make_garment_photo(tmp_path / "kirmizi_tisort.jpg")
