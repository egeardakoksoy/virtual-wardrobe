"""Faz 4 — "Gerçekçi Göster": tam VTON zinciri + önbellek.

Faz 1'in katman mimarisi hızlı ve bedava ama bir yaklaşım: kıyafetler ayrı ayrı
üretilip üst üste bindiriliyor, birbirlerini bilmiyorlar. Bu yüzden bel çizgisi,
kumaşın diğerinin üstüne nasıl düştüğü, gölge geçişleri tam doğru olmuyor (§7).

Burada tersi yapılıyor: kıyafetler **zincirleme** giydiriliyor. Önce alt, sonra
üst — her adım bir öncekinin çıktısını girdi olarak alıyor, yani model üstü
giydirirken altı görüyor. Katman çıkarımı yok, bindirme yok, dolayısıyla
çıkarımın hiçbir kusuru da yok.

Bedeli: kıyafet başına bir VTON çağrısı. İki parçalı bir kombin ~30-80 saniye ve
~$0.15. Bu yüzden:

  · Sonuç MUTLAKA önbelleğe alınıyor (aynı kombin ikinci kez bedava).
  · Önbellek anahtarı mankeni de içeriyor — manken değişince eski render
    kendiliğinden geçersiz oluyor.
  · Arayüz çağrı sayısını ve tahmini ücreti düğmeye basmadan gösteriyor.

Yani katman mimarisinin yerine geçmiyor, YANINA geliyor: gezinme katmanlarla
(anında, bedava), "bu kombin gerçekte nasıl durur" sorusu bununla.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image

from config import DATA_DIR, z_index
from db import connect, get_garment
from wardrobe import mannequin, vton

RENDER_DIR = DATA_DIR / "renders"
RENDER_DIR.mkdir(parents=True, exist_ok=True)

# Sağlayıcı başına yaklaşık çağrı ücreti (USD). Kesin fiyat değil — arayüzde
# "ne kadara mal olacak" göstermek için. Yanlış tarafa yuvarlanmış olması,
# olduğundan ucuz göstermesinden iyidir.
CALL_COST_USD = 0.075


def _base_mannequin_id(db_path=None) -> int:
    """Önbellek anahtarındaki `m<id>` — AKTİF mankenin id'si.

    Tek yerden geliyor (`mannequin.active_id`): bu sayı hem dosya adına
    giriyor hem de arayüzün gösterdiği adrese. İki yerde hesaplanan bir anahtar
    §27.1-A'da ücretle üretilmiş bir render'ı "kayıp" gösterdi.
    """
    return mannequin.active_id(db_path)


def plan(garment_ids: list[int], db_path=None, provider=None) -> dict:
    """Zincirin ne yapacağını çağrı YAPMADAN döner.

    Arayüz bunu düğmenin yanında gösteriyor: kaç çağrı, ne kadar, hangi
    kıyafetler atlanacak. Kullanıcı ücretli bir işlemi ne olduğunu bilmeden
    başlatmamalı.

    provider VERİLMEZSE sağlayıcı seçilmiyor — `get_provider()` bile
    çağrılmıyor. Bu bilinçli: plan() ücretsiz olmak zorunda ve sağlayıcıya
    dokunmak (anahtar okuma, istemci kurma) o güvenceyi zayıflatır. Sağlayıcısız
    halde FASHN'ın kategori kuralı varsayılıyor, çünkü varsayılan o.
    """
    uygulanacak: list[dict] = []
    atlanan: list[dict] = []

    def destekliyor_mu(category: str) -> tuple[bool, str]:
        if provider is not None:
            if vton.supports_category(provider, category):
                return True, ""
            return False, f"'{category}' için {provider.name} sağlayıcısında model yok"
        try:
            vton.to_fashn_category(category)
            return True, ""
        except vton.UnsupportedCategory as exc:
            return False, str(exc)

    for gid in garment_ids:
        garment = get_garment(gid, db_path=db_path)
        if not garment:
            atlanan.append({"id": gid, "neden": "kıyafet bulunamadı"})
            continue
        tamam, neden = destekliyor_mu(garment["category"])
        if not tamam:
            atlanan.append({"id": gid, "neden": neden})
            continue
        uygulanacak.append({"id": gid, "category": garment["category"]})

    # Zincir sırası z'ye göre ARTAN: önce alt, sonra üst. Böylece üst
    # giydirilirken model altı zaten görüyor ve bel çizgisi doğru oluşuyor —
    # katman mimarisinin çözemediği şey tam olarak buydu.
    uygulanacak.sort(key=lambda g: z_index(g["category"]))

    return {
        "calls": len(uygulanacak),
        "cost_usd": round(len(uygulanacak) * CALL_COST_USD, 3),
        "order": [g["id"] for g in uygulanacak],
        "skipped": atlanan,
    }


# Anahtarda sağlayıcı adı YAZILMAYAN sağlayıcı. Birden çok sağlayıcı olunca
# anahtarın onu da içermesi şart (yoksa fal'ın renderı gemini'ninkiyle aynı
# dosyaya düşer), ama varsayılan için eski biçim korunuyor: aksi halde
# ÜCRETLE üretilmiş mevcut önbellek dosyaları bir anda bulunamaz olur ve
# kullanıcı aynı kombine ikinci kez öder.
DEFAULT_RENDER_PROVIDER = "fal"


def cache_key(
    garment_ids: list[int], db_path=None,
    provider_name: str = DEFAULT_RENDER_PROVIDER,
) -> str:
    mid = _base_mannequin_id(db_path)
    key = f"m{mid}_" + "-".join(str(i) for i in sorted(garment_ids))
    return key if provider_name == DEFAULT_RENDER_PROVIDER else f"{key}_{provider_name}"


def cache_path(
    garment_ids: list[int], db_path=None,
    provider_name: str = DEFAULT_RENDER_PROVIDER,
) -> Path:
    return RENDER_DIR / f"{cache_key(garment_ids, db_path, provider_name)}.png"


def cached_key(
    garment_ids: list[int], db_path=None,
    provider_name: str = DEFAULT_RENDER_PROVIDER,
) -> str | None:
    """Diskte GERÇEKTEN duran render'ın anahtarı; yoksa None.

    ⚠ Bu fonksiyon para kaybettiren bir hatadan sonra yazıldı.

    Varsayılan sağlayıcı fal'dan fashn'a çevrildiğinde (§25) `render_outfit`
    dosyayı `m1_7-10_fashn.png` olarak yazmaya başladı, ama web katmanı
    anahtarı hâlâ `DEFAULT_RENDER_PROVIDER` ("fal") ile hesaplıyordu:
    `m1_7-10.png`. Aynı istek iki farklı anahtar üretti — render ÜRETİLDİ,
    ÜCRETLENDİ ve arayüz onu bulamadığı için "yok" saydı.

    İki şeyi birden yapıyor:
      1. Sağlayıcıya özel adı arıyor.
      2. Bulamazsa ESKİ (eksiz) ada da bakıyor — o dosyalar da ücretle
         üretildi ve varsayılan değişti diye kaybolmamalı.

    Anahtarı DÖNDÜRÜYOR, sadece "var mı" demiyor: arayüzün göstereceği URL de
    bu anahtardan kuruluyor, yani bulunan dosyayla gösterilen adres aynı
    olmak zorunda. Ayrışmalarının bedeli tam olarak yukarıdaki hataydı.
    """
    for ad in dict.fromkeys([provider_name, DEFAULT_RENDER_PROVIDER]):
        anahtar = cache_key(garment_ids, db_path, ad)
        if (RENDER_DIR / f"{anahtar}.png").is_file():
            return anahtar
    return None


def cached(
    garment_ids: list[int], db_path=None,
    provider_name: str = DEFAULT_RENDER_PROVIDER,
) -> Path | None:
    anahtar = cached_key(garment_ids, db_path, provider_name)
    return (RENDER_DIR / f"{anahtar}.png") if anahtar else None


def clear_cache(mannequin_id: int | None = None) -> int:
    """Bir mankenin FOTOĞRAFI değişince çağrılır — renderları artık geçersiz.

    ⚠ KAPSAM. `mannequin_id` verilirse yalnızca o mankenin renderları
    (`m{id}_*.png`) siliniyor. Çoklu mankende (§28) kapsamsız silme, ilgisiz
    bir mankenin ÜCRETLE üretilmiş renderlarını yok etmek demekti: kullanıcı
    2 numaralı mankenin fotoğrafını değiştirdiğinde 1 numaranın 5 render'ı
    sessizce gidiyordu.

    `None` yalnızca "her şeyi temizle" bilinçli istendiğinde (test kurulumu,
    elle bakım) geçilmeli.

    Düzenleme zincirleri de siliniyor: zincir dosyaları kalırsa artık var
    olmayan bir görüntüye işaret eden bir geçmiş kalır ve arayüz onu
    göstermeye çalışır.
    """
    from wardrobe import edits          # döngüsel import olmasın diye içeride

    silinen = edits.clear_all(mannequin_id)
    desen = "*.png" if mannequin_id is None else f"m{mannequin_id}_*.png"
    for f in RENDER_DIR.glob(desen):
        try:
            f.unlink()
            silinen += 1
        except OSError:
            pass
    return silinen


def render_outfit(
    garment_ids: list[int],
    *,
    provider=None,
    db_path=None,
    force: bool = False,
    progress: Callable[[int, int, int], None] | None = None,
) -> dict:
    """Kombini zincirleme giydirip önbelleğe yazar.

    progress(adim, toplam, garment_id) her çağrıdan ÖNCE tetikleniyor —
    arayüzün "3 kıyafetten 2.si" diyebilmesi için.
    """
    if not garment_ids:
        return {"status": "failed", "error": "kombin boş"}

    # Sağlayıcı önce seçiliyor: hem önbellek anahtarı hem de plan artık ona
    # bağlı (gemini ayakkabı giydirebiliyor, fal giydiremiyor).
    provider = provider or vton.get_provider()
    ad = getattr(provider, "name", DEFAULT_RENDER_PROVIDER)

    onceki = cached(garment_ids, db_path, ad)
    if onceki and not force:
        return {"status": "cached", "path": str(onceki),
                "calls": 0, "cost_usd": 0.0}

    p = plan(garment_ids, db_path=db_path, provider=provider)
    if not p["order"]:
        return {"status": "failed",
                "error": "uygulanabilir kıyafet yok",
                "skipped": p["skipped"]}

    base_row = mannequin.ensure(db_path=db_path)
    current = Path(base_row["image_path"])

    ara_dosyalar: list[Path] = []
    try:
        for i, gid in enumerate(p["order"], start=1):
            if progress:
                progress(i, len(p["order"]), gid)

            garment = get_garment(gid, db_path=db_path)
            out = provider.try_on(
                current, Path(garment["cutout_path"]), garment["category"]
            )

            # Ara adımı diske yaz: bir sonraki çağrının GİRDİSİ bu.
            ara = RENDER_DIR / f".ara_{cache_key(garment_ids, db_path, ad)}_{i}.png"
            out.save(ara, "PNG")
            ara_dosyalar.append(ara)
            current = ara
    except Exception as exc:
        for f in ara_dosyalar:
            f.unlink(missing_ok=True)
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                "calls": len(ara_dosyalar), "skipped": p["skipped"]}

    hedef = cache_path(garment_ids, db_path, ad)
    Image.open(current).convert("RGB").save(hedef, "PNG")
    for f in ara_dosyalar:
        f.unlink(missing_ok=True)

    return {"status": "ok", "path": str(hedef), "calls": p["calls"],
            "cost_usd": p["cost_usd"], "skipped": p["skipped"]}
