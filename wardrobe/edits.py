"""Render üzerinde serbest metin düzenlemeleri — "kolları kıvır", "sola dön".

Faz 4'ün zincirleme render'ı bir FOTOĞRAF üretiyor. Bu modül o fotoğrafın
üzerinde konuşma gibi çalışıyor: kullanıcı yazıyor, model uyguluyor, sonuç bir
sonraki talimatın girdisi oluyor.

    render (m1_6-8.png)
      └─ "kolları kıvır"        → m1_6-8_e1.png
           └─ "hafifçe sola dön" → m1_6-8_e2.png

ÜÇ TASARIM KARARI, üçü de bu projenin daha önce ödediği bedellerden:

1. **Zincir diske yazılıyor, belleğe değil.** §23.4'te iş kaydı bellekteydi ve
   sunucu yeniden başlayınca ÜCRETLE üretilmiş bir sonuç "kayboldu". Burada
   her adım hem PNG hem JSON olarak duruyor.

2. **Geri alma dosyayı SİLMİYOR.** Sadece zincirden düşürüyor. Kullanıcı
   "bu daha iyiydi" derse ödenmiş görüntü hâlâ diskte. Silmek, parayı çöpe
   atmanın en sessiz yolu olurdu.

3. **Anahtar doğrulanıyor.** Zincir dosya adına gömülü ve anahtar istemciden
   geliyor; yol enjeksiyonuna kapalı olmak zorunda (web/app.py'deki render
   uç noktasıyla aynı gerekçe).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from wardrobe import vton


def RENDER_DIR() -> Path:      # noqa: N802 — sabit gibi okunsun diye
    """Render dizini — SABİT DEĞİL, çağrı anında çözülüyor.

    ⚠ Bu fonksiyon bir hata düzeltmesi. Önce `from wardrobe.render import
    RENDER_DIR` yazıyordu ve sonuç §6.1 #8/#13'ün ÜÇÜNCÜ tekrarıydı:

    `conftest` testleri izole etmek için `wardrobe.render.RENDER_DIR`'i
    `tmp_path`'e yönlendiriyor. Ama import anında kopyalanan bu ad
    `wardrobe.edits` içinde GERÇEK dizini göstermeye devam ediyordu. Sonuç:
    `render.clear_cache()` çağıran her test — ki manken testleri çağırıyor —
    `edits.clear_all()` üzerinden kullanıcının GERÇEK düzenleme zincirlerini
    siliyordu. Ödenmiş görüntüler, testler yüzünden.

    Ölçüldü: elle kurulan üç adımlık bir zincir `pytest` sonrası yok olmuştu.

    DERS (üçüncü kez): türetilmiş yolu modül seviyesinde sabitleme.
    """
    from wardrobe import render
    return render.RENDER_DIR

# Render anahtarının biçimi: m<manken>_<id-id-...>[_<sağlayıcı>]
KEY_PATTERN = re.compile(r"m\d+_[\d\-]+(_[a-z]+)?")

# Bir düzenleme talimatının makul üst sınırı. Uzun metin daha iyi sonuç
# vermiyor, sadece isteği şişiriyor.
MAX_PROMPT = 400


class EditError(Exception):
    """Düzenleme yapılamadı (geçersiz anahtar, boş talimat, kaynak yok...)."""


def _dogrula(key: str) -> str:
    if not KEY_PATTERN.fullmatch(key):
        raise EditError(f"geçersiz render anahtarı: {key!r}")
    return key


# Katman bindirmesinden üretilen kaynağın anahtar eki.
#
# `m1_6-8_katman` — KEY_PATTERN'in sağlayıcı eki yuvasına oturuyor, yani ayrı
# bir doğrulama kuralı gerekmiyor. (Bir sağlayıcıya "katman" adı verilirse
# çakışır; verilmeyecek, ama not düşülüyor.)
COMPOSITE_SUFFIX = "katman"


def composite_key(garment_ids: list[int], db_path=None) -> str:
    from wardrobe.render import cache_key
    return f"{cache_key(garment_ids, db_path)}_{COMPOSITE_SUFFIX}"


def ensure_composite(garment_ids: list[int], db_path=None) -> str:
    """Katman bindirmesinin anahtarını döner — dosyayı YAZMAZ.

    NEDEN VAR: düzenleme, kaynağın nereden geldiğini umursamıyor — bir
    fotoğraf yetiyor. Katman bindirmesi ÜCRETSİZ üretiliyor, yani "kolları
    kıvır" demek için önce ücretli bir render almak zorunlu değil.

    Takas kullanıcıya bırakılıyor, kod seçmiyor:
      · katmandan düzenle  → 2 kredi, ama çıkarımın kusurlarını taşır
      · render'dan düzenle → 4+2 kredi, temiz zemin

    ⚠ ÖNCE HER ÇAĞRIDA DOSYA YAZIYORDU ve bu ölçülebilir bir israftı: arayüz
    bu fonksiyonu HER kombin seçiminde çağırıyor, her dosya ~1.5 MB. Kullanıcı
    dolabı gezerken 18 dosya / ~27 MB birikmişti — hiçbiri düzenlenmemişti.
    Artık dosya ancak gerçekten düzenleme yapılınca üretiliyor (bkz.
    materialize).
    """
    return composite_key(garment_ids, db_path)


def _composite_ids(key: str) -> list[int] | None:
    """`m1_6-8_katman` → [6, 8]. Katman anahtarı değilse None.

    Anahtarın kendisi kombini taşıdığı için kaynak dosya kaybolsa da (ya da
    hiç üretilmemiş olsa da) yeniden kurulabiliyor — bu, dosyayı tembel
    üretebilmenin şartı.
    """
    if not key.endswith(f"_{COMPOSITE_SUFFIX}"):
        return None
    govde = key[: -len(COMPOSITE_SUFFIX) - 1]
    try:
        return [int(x) for x in govde.split("_", 1)[1].split("-")]
    except (IndexError, ValueError):
        return None


def materialize(key: str, db_path=None) -> Path | None:
    """Katman kaynağı gerekiyorsa şimdi üretir. Render anahtarlarına dokunmaz."""
    from wardrobe.layers import compose

    hedef = base_path(key)
    if hedef.is_file():
        return hedef
    ids = _composite_ids(key)
    if not ids:
        return None
    compose(ids, db_path=db_path).convert("RGB").save(hedef, "PNG")
    return hedef


def chain_path(key: str) -> Path:
    return RENDER_DIR() / f"{_dogrula(key)}.edits.json"


def base_path(key: str) -> Path:
    """Zincirin başlangıcı — Faz 4'ün ürettiği render."""
    return RENDER_DIR() / f"{_dogrula(key)}.png"


def _oku(key: str) -> dict:
    """Ham kayıt: {"steps": [...], "selected": n}.

    ESKİ BİÇİM (düz liste) da okunuyor — o dosyalar ücretle üretilmiş
    geçmişler ve biçim değiştirdi diye kaybolmamalı.
    """
    yol = chain_path(key)
    if not yol.is_file():
        return {"steps": [], "selected": 0}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"steps": [], "selected": 0}

    if isinstance(veri, list):          # eski biçim: düz liste, seçim = sonu
        for i, a in enumerate(veri):
            a.setdefault("parent", veri[i - 1]["n"] if i else 0)
        return {"steps": veri, "selected": veri[-1]["n"] if veri else 0}

    veri.setdefault("steps", [])
    veri.setdefault("selected", 0)
    return veri


def _yaz(key: str, veri: dict) -> None:
    chain_path(key).write_text(
        json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")


def history(key: str) -> list[dict]:
    """ÜRETİLMİŞ tüm sürümler, numara sırasıyla — hiçbiri düşmüyor.

    ⚠ Bu, bir kullanılabilirlik hatasının düzeltmesi. Önce geçmişte bir
    sürüme tıklamak zinciri KESİYORDU ve sonraki adımların kaydı siliniyordu:
    kullanıcı eskiye dönüyor, sonra yeniye dönemiyordu. Film şeridinin
    geçmişi GÖSTERMESİ ama seçimin geçmişi SİLMESİ tutarsızdı.

    Dosyalar zaten hiç silinmiyordu (ödenmiş görüntü); eksik olan kayıttı.
    Artık kayıt da kalıcı, `selected` ayrı tutuluyor.
    """
    return sorted(_oku(key)["steps"], key=lambda a: a["n"])


def selected(key: str) -> int:
    """Şu an seçili sürüm (0 = düzenlenmemiş hâli)."""
    return int(_oku(key).get("selected", 0))


def chain(key: str) -> list[dict]:
    """Seçili sürüme GİDEN yol — kökten seçiliye, sırayla.

    Geçmişin tamamı değil: kullanıcı 1'e dönüp yeni bir talimat yazdıysa
    soyağacı 1 → 4 olur, 2 ve 3 o dalda değildir (ama geçmişte durur).
    """
    veri = _oku(key)
    numaraya = {a["n"]: a for a in veri["steps"]}
    yol, n, guvenlik = [], veri.get("selected", 0), 0
    while n and n in numaraya and guvenlik < 200:
        yol.append(numaraya[n])
        n = numaraya[n].get("parent", 0)
        guvenlik += 1
    return list(reversed(yol))


def step_path(key: str, n: int) -> Path:
    return RENDER_DIR() / f"{_dogrula(key)}_e{n}.png"


def _bos_numara_h(key: str) -> int:
    """Kullanılmamış ilk adım numarası — geçmişe VE dosyalara bakarak."""
    n = max((a["n"] for a in history(key)), default=0) + 1
    while step_path(key, n).is_file():
        n += 1
    return n


def _bos_numara(key: str, adimlar: list[dict]) -> int:
    """Kullanılmamış ilk adım numarası — DOSYALARA da bakarak.

    Neden sadece `max(n)+1` yetmiyor: kullanıcı geçmişte bir sürüme dönüp
    oradan yeni bir talimat yazabiliyor. O anda zincir kısalıyor ama düşen
    adımların DOSYALARI diskte duruyor (bilerek — ödenmiş görüntü silinmiyor).
    `max(n)+1` deseydik, düşmüş bir adımın dosyasının üstüne yazardık ve
    ödenmiş bir görüntüyü sessizce yok ederdik.
    """
    n = max((a["n"] for a in adimlar), default=0) + 1
    while step_path(key, n).is_file():
        n += 1
    return n


def select(key: str, n: int) -> dict:
    """Seçili sürümü değiştirir — GEÇMİŞE DOKUNMAZ, ileri geri serbest.

    n = 0 → düzenlenmemiş hâl. Her yöne gidilebiliyor: 3'ten 0'a, 0'dan
    tekrar 3'e. Önceki sürüm zinciri kesiyordu ve dönüş yolu kalmıyordu.

    Bundan sonra yazılan yeni talimat SEÇİLİ sürümden devam eder; sonraki
    adımlar geçmişte durmaya devam eder (dallanma).
    """
    if n < 0:
        raise EditError("geçersiz adım")
    veri = _oku(key)
    if n and not any(a["n"] == n for a in veri["steps"]):
        raise EditError(f"adım bulunamadı: {n}")
    if n and not step_path(key, n).is_file():
        raise EditError(f"adımın görüntüsü diskte yok: {n}")

    veri["selected"] = n
    _yaz(key, veri)
    return {"status": "ok", "count": len(chain(key)), "selected": n}


def current_path(key: str) -> Path | None:
    """Şu an gösterilmesi gereken görüntü — son adım, yoksa zeminin kendisi.

    Katman kaynağı tembel üretiliyor: dosya yoksa ve anahtar bir katman
    anahtarıysa burada kuruluyor (ücretsiz, sadece bindirme).
    """
    adimlar = chain(key)
    for adim in reversed(adimlar):
        p = step_path(key, adim["n"])
        if p.is_file():
            return p
    temel = base_path(key)
    if temel.is_file():
        return temel
    return materialize(key)


def editable(key: str) -> bool:
    """Bu anahtar üzerinde düzenleme yapılabilir mi? — DOSYA ÜRETMEDEN.

    `current_path` dosyayı üretebiliyor; sadece "mümkün mü" diye soran yerler
    (plan) bunu kullanmalı, yoksa ücretsiz bir sorgu diske yazmaya başlar.
    """
    return (base_path(key).is_file()
            or any(step_path(key, a["n"]).is_file() for a in chain(key))
            or _composite_ids(key) is not None)


def plan(key: str, provider=None) -> dict:
    """Bir düzenlemenin ne tutacağını çağrı YAPMADAN söyler.

    plan() ücretsiz olmalı; sağlayıcı verilmezse varsayılan ayarların kredisi
    bildiriliyor ve `get_provider()` bile çağrılmıyor (render.plan ile aynı
    gerekçe: anahtar okuma / istemci kurma bile ücretsizlik güvencesini
    zayıflatır).
    """
    adimlar = chain(key)
    tumu = history(key)
    su_an = selected(key)
    kredi = provider.credits() if provider is not None else \
        vton.FASHN_CREDITS[("balanced", "1k")]
    return {
        "key": key,
        "steps": adimlar,
        # ÜRETİLMİŞ tüm sürümler — film şeridi bunu çiziyor. `steps` yalnızca
        # seçiliye giden yol; onu çizseydik geçmişe dönen kullanıcı ileriyi
        # göremez ve geri dönemezdi (yaşandı).
        "history": tumu,
        "selected": su_an,
        "can_redo": any(a.get("parent", 0) == su_an
                        and step_path(key, a["n"]).is_file() for a in tumu),
        "count": len(adimlar),
        "credits": kredi,
        "can_undo": bool(adimlar),
        # `editable` DOSYA ÜRETMİYOR — `current_path` üretebiliyor. plan()
        # ücretsiz ve yan etkisiz kalmalı.
        "available": editable(key),
    }


def apply_edit(key: str, prompt: str, *, provider=None, seed: int | None = None) -> dict:
    """Talimatı ŞU ANKİ görüntüye uygular ve zincire ekler — ÜCRETLİ.

    Kaynak her zaman zincirin sonu: böylece "kolları kıvır" dedikten sonra
    "sola dön" demek ikisini birden taşıyor, birincisini iptal etmiyor.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise EditError("talimat boş")
    if len(prompt) > MAX_PROMPT:
        raise EditError(f"talimat çok uzun (en fazla {MAX_PROMPT} karakter)")

    kaynak = current_path(key)
    if kaynak is None:
        raise EditError(
            "düzenlenecek görüntü yok — önce kombini 'Gerçekçi Göster' ile üret")

    provider = provider or vton.get_provider("fashn")
    if not hasattr(provider, "edit"):
        raise EditError(
            f"'{getattr(provider, 'name', '?')}' sağlayıcısı düzenleme yapmıyor "
            "— FASHN_API_KEY gerekiyor (bkz. python cli.py doctor)"
        )
    if not provider.available():
        raise EditError("FASHN_API_KEY yok — .env'e ekle")

    ebeveyn = selected(key)
    n = _bos_numara_h(key)

    # Türkçe yazılmışsa İngilizceye çevir. FASHN'ın örneklerinin hepsi
    # İngilizce ve Türkçe anlayıp anlamadığı bilinmiyor; kullanıcının Türkçe
    # yazıp sonucun sessizce kötüleşmesi en kötü hata türü, çünkü çağrı
    # ÜCRETLİ ve başarısızlık "model beceremedi" gibi görünüyor.
    #
    # Zaten İngilizceyse ya da çeviri yapılamazsa özgün metin gidiyor —
    # `translate_prompt` asla fırlatmıyor. GEÇMİŞE kullanıcının YAZDIĞI metin
    # yazılıyor, çeviri değil: geçmiş kullanıcının kendi cümlesini göstermeli.
    from wardrobe.vision import translate_prompt

    gonderilen = translate_prompt(prompt)
    sonuc = provider.edit(kaynak, gonderilen, seed=seed)
    hedef = step_path(key, n)
    sonuc.convert("RGB").save(hedef, "PNG")

    adim = {
        "n": n,
        "parent": ebeveyn,                 # hangi sürümden türedi
        "prompt": prompt,                  # kullanıcının YAZDIĞI
        "file": hedef.name,
        "credits": provider.credits(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if gonderilen != prompt:
        adim["sent"] = gonderilen          # modele GİDEN (çeviri)

    veri = _oku(key)
    veri["steps"].append(adim)
    veri["selected"] = n
    _yaz(key, veri)
    return {"status": "ok", "step": adim, "count": len(chain(key))}


def undo(key: str) -> dict:
    """Bir sürüm geriye — seçiliyi ebeveynine taşır. Hiçbir şey SİLMEZ."""
    adimlar = chain(key)
    if not adimlar:
        raise EditError("geri alınacak düzenleme yok")
    dusen = adimlar[-1]
    return {"status": "ok", "undone": dusen,
            **select(key, int(dusen.get("parent", 0)))}


def redo(key: str) -> dict:
    """Bir sürüm ileriye — seçilinin ÇOCUĞUNA geçer.

    Birden çok çocuk varsa (dallanma) en son üretilen seçiliyor: kullanıcının
    son niyeti o.
    """
    su_an = selected(key)
    cocuklar = [a for a in history(key)
                if a.get("parent", 0) == su_an and step_path(key, a["n"]).is_file()]
    if not cocuklar:
        raise EditError("ileri alınacak düzenleme yok")
    return {"status": "ok", **select(key, max(a["n"] for a in cocuklar))}


def reset(key: str) -> dict:
    """Düzenlenmemiş hâle döner. Geçmiş ve dosyalar KALIR — geri dönülebilir."""
    sayi = len(chain(key))
    select(key, 0)
    return {"status": "ok", "cleared": sayi}


def clear_for(key: str) -> int:
    """Bir render silinince/geçersizleşince zincirini de temizler.

    Manken değişince renderlar siliniyor (§15); zincir dosyaları kalırsa
    olmayan bir görüntüye işaret eden geçmiş kalır.
    """
    silinen = 0
    for p in RENDER_DIR().glob(f"{key}_e*.png"):
        p.unlink(missing_ok=True)
        silinen += 1
    chain_path(key).unlink(missing_ok=True)
    return silinen


def clear_all(mannequin_id: int | None = None) -> int:
    """Düzenleme zincirlerini siler — bir mankenin fotoğrafı değişince.

    ⚠ KAPSAM. `mannequin_id` verilirse yalnızca o mankenin zincirleri
    (`m{id}_...`) siliniyor. Çoklu mankende kapsamsız silme, ilgisiz bir
    mankenin ÜCRETLE üretilmiş düzenleme geçmişini yok ederdi — ve zincirin
    her adımı ayrı bir ödeme (2 kredi).
    """
    onek = "*" if mannequin_id is None else f"m{mannequin_id}_*"
    silinen = 0
    for p in (list(RENDER_DIR().glob(f"{onek}_e*.png"))
              + list(RENDER_DIR().glob(f"{onek}.edits.json"))):
        try:
            p.unlink()
            silinen += 1
        except OSError:
            pass
    return silinen


def open_current(key: str) -> Image.Image | None:
    p = current_path(key)
    return Image.open(p) if p else None
