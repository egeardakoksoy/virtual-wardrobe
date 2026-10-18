"""Giydirme arayüzünün sunucusu — Faz 2.

MİMARİ: sunucu görüntü BİRLEŞTİRMİYOR. Katmanları olduğu gibi servis ediyor,
tarayıcı üst üste bindiriyor (`<img>` + CSS `z-index`).

Neden: Faz 1'in tüm varlık sebebi buydu (§2). Katmanlar zaten aynı mankenden,
aynı çözünürlükte üretildiği için piksel piksel hizalı; tarayıcıda üst üste
koymak yeterli. Her tıklamada sunucuya gidip PNG birleştirmek gereksiz gecikme
demek olurdu — burada seçim anında görünüyor, ağ trafiği yok.

Çakışma kuralı da tek yerden geliyor: `config.CATEGORIES`. Sunucu bu tabloyu
istemciye veriyor, istemci aynı kuralla karar veriyor — kural iki yerde
tanımlanmıyor.
"""
from __future__ import annotations

import io
import re
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, Response,
)
from fastapi.staticfiles import StaticFiles
from PIL import Image

from config import CATEGORIES, PROJECT_ROOT
from db import connect, delete_garment, get_garment, list_garments
from wardrobe import edits, ingest, layers, mannequin, render
from wardrobe.imageutil import ALIGN_LIMITS, clamp_align
from wardrobe.layers import LOW_CONTRAST_DISTANCE
from wardrobe.templates import DEFAULT_SHAPE, SHAPES, shape_points

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="AI Sanal Dolap", docs_url="/api/docs")


def _rev(path: str | None) -> int:
    """Dosyanın değişme zamanı — önbellek kırıcı sürüm damgası (0 = dosya yok)."""
    try:
        return int(Path(path).stat().st_mtime) if path else 0
    except OSError:
        return 0


def _layers_by_garment(db_path=None) -> dict[int, dict]:
    """AKTİF mankenin katmanları.

    Eskiden `WHERE m.name = 'base'` idi. Çoklu mankende (§28) bu, kullanıcı
    hangi mankeni seçerse seçsin hep aynı katman setini göstermek olurdu —
    yani manken geçişi görünürde çalışıp gerçekte hiçbir şey değiştirmezdi.
    """
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT l.garment_id, l.png_path, l.z_index, l.status "
            "FROM layers l WHERE l.mannequin_id = ?",
            (mannequin.active_id(db_path),),
        ).fetchall()
    return {r["garment_id"]: dict(r) for r in rows}


@app.get("/api/wardrobe")
def wardrobe() -> JSONResponse:
    """Dolabın tamamı + kategori kuralları.

    `layer_ready` false olan kıyafetler arayüzde gösteriliyor ama giydirilemiyor
    — sessizce gizlemek yerine "katmanı yok" diyoruz, çünkü kullanıcı kıyafeti
    eklediğini biliyor ve kaybolmasını hata sanar.
    """
    layers = _layers_by_garment()
    garments = []
    for g in list_garments():
        layer = layers.get(g["id"])
        garments.append({
            # SÜRÜM DAMGASI — katman dosyasının değişme zamanı.
            #
            # Katmanlar yeniden üretilebiliyor (--reextract bedava, sağlayıcı
            # değişimi, filtre ayarı). URL sabit kalırsa tarayıcı ESKİ katmanı
            # bellekten servis ediyor ve kullanıcı "düzeltme işe yaramamış"
            # sanıyor. Zaman damgasını URL'ye koymak bunu kesin olarak çözüyor:
            # dosya değişmediyse URL de değişmiyor, yani önbellek yine çalışıyor.
            "layer_rev": _rev(layer["png_path"] if layer else ""),
            "cutout_rev": _rev(g["cutout_path"]),
            # Ham VTON çıktısının damgası. 0 ise o kıyafet için ham çıktı yok
            # ve istemci tek-kıyafet görünümünde bindirmeye düşüyor.
            "dressed_rev": _ham_rev(g["id"]),
            # Bu kıyafet mankenin kıyafetiyle AYNI RENK bandında mı?
            #
            # Bindirmede ZEMİN SEÇİMİNİ belirliyor ve ölçümle eklendi: kıyafet
            # mankenin kıyafetine yakınsa fark neredeyse boş çıkıyor (o bölgede
            # katman doluluğu %4 ölçüldü), yani ekranda görünen şeyin %96'sı
            # ZEMİN oluyor. O durumda nötrlenmiş zemin kıyafeti YANLIŞ renkte
            # gösteriyor — gerçek fotoğraf gösteriyor.
            #
            #     nötr zemin    : kıyafetin gerçek rengine uzaklık 17.3
            #     gerçek foto   : 7.7
            #
            # Kural sunucuda: eşik `layers.LOW_CONTRAST_DISTANCE` ve istemci
            # onu yeniden tanımlamıyor (§14 ilkesi).
            "base_near": (lambda d: d is not None
                          and d < LOW_CONTRAST_DISTANCE)(_base_mesafesi(g)),
            "id": g["id"],
            "category": g["category"],
            "subcategory": g["subcategory"],
            "color_name": g["color_name"],
            "color_hex": g["color_hex"],
            "pattern": g["pattern"],
            "style": g["style"],
            "warmth": g["warmth"],
            "formality": g["formality"],
            "z": layer["z_index"] if layer else CATEGORIES.get(
                g["category"], {}).get("z", 99),
            "layer_ready": bool(layer and layer["status"] == "ready"),
            "layer_status": layer["status"] if layer else "yok",
        })

    return JSONResponse({
        "garments": garments,
        "categories": {
            k: {"label": v["label"], "z": v["z"], "slots": list(v["slots"])}
            for k, v in CATEGORIES.items()
        },
        # Gösterim base'i de yeniden üretilebiliyor (manken değişimi, nötrleme
        # yönteminin güncellenmesi). Aynı bayatlama riski, aynı çözüm.
        #
        # ⚠ Manken GEÇİŞİNDE de değişmek zorunda: iki mankenin gösterim base'i
        # iki ayrı dosya ve mtime'ları farklı, yani damga kendiliğinden
        # farklılaşıyor. Tek bir "base.png" URL'si sabit damgayla kalsaydı
        # kullanıcı manken değiştirir, ekranda eskisini görürdü (§25.7).
        "base_rev": _rev(str(mannequin.display_base_path())),
        # Nötrlenmemiş fotoğrafın damgası — bindirme YAPILMAYAN durumlarda
        # (seçim boşken) zemin bu oluyor.
        "base_raw_rev": _rev((mannequin.active() or {}).get("image_path", "")),
        "mannequin": _manken_ozet(),
    })


_mesafe_cache: dict[tuple, float | None] = {}


def _base_mesafesi(garment: dict) -> float | None:
    """Kıyafetin mankenin GERÇEK kıyafetine renk uzaklığı — önbellekli.

    ZEMİN seçiminin sorusu bu, o yüzden `base_conflict` (gerçek fotoğraf).
    Yükleme uyarısı ise `extraction_conflict` kullanıyor — ayrı soru, ayrı
    referans, bkz. `layers.base_conflict` docstring'i.

    Zemin seçimi buna bağlı (bkz. `/api/wardrobe` içindeki `base_near`).
    Önbellek anahtarı (kırpık, manken görseli, ikisinin mtime'ı): dosya
    değişirse mesafe de yenileniyor.
    """
    from wardrobe.layers import base_conflict

    row = mannequin.active()
    if not row or not garment.get("cutout_path"):
        return None
    try:
        anahtar = (garment["cutout_path"], _rev(garment["cutout_path"]),
                   row["image_path"], _rev(row["image_path"]))
    except Exception:
        return None
    if anahtar not in _mesafe_cache:
        try:
            _mesafe_cache[anahtar] = base_conflict(garment["cutout_path"])["distance"]
        except Exception:
            _mesafe_cache[anahtar] = None
    return _mesafe_cache[anahtar]


def _ham_yol(garment_id: int):
    """Aktif mankendeki ham VTON çıktısının yolu (dosya olmayabilir)."""
    from wardrobe.layers import raw_path

    return raw_path(garment_id, mannequin.active_id())


def _ham_rev(garment_id: int) -> int:
    """Tek-kıyafet görünümünün önbellek damgası.

    ⚠ Bu bir TARİH DEĞİL, opak bir sürüm sayısı. Gösterilen görüntü ÜÇ şeyden
    türüyor ve üçü de damgaya girmek zorunda:

      1. ham VTON çıktısı      → katman yenilenince değişir
      2. çıkarım base'i        → yeşil base yenilenince değişir
      3. dönüşümün ALGORİTMASI → kod değişince değişir

    Üçüncüsü ilk sürümde atlanmıştı ve masrafı ölçüldü: sunucudaki dosya
    düzeltilmişti ama ham çıktı çıkarım base'inden yeni olduğu için
    `max()` eski değerin aynısını üretti, URL değişmedi ve tarayıcı YEŞİL
    görüntüyü belleğinden servis etmeye devam etti. Kullanıcı "düzelmedi"
    diye bildirdi; kod doğruydu, damga yanlıştı (§25.7'nin üçüncü tekrarı).
    """
    from wardrobe.layers import RESTORE_VERSION

    ham = _rev(str(_ham_yol(garment_id)))
    if not ham:
        return 0          # ham çıktı yok: istemci bindirmeye düşsün
    ext = _rev(str(mannequin.extract_base_path(mannequin.active_id())))
    return max(ham, ext) + RESTORE_VERSION


def _manken_ozet() -> dict:
    """Aktif mankenin kimliği — arayüz hangi zemin üzerinde olduğunu yazsın.

    Model ve ücret de burada (§54): katman üretiminin onay ekranı ve yükleme
    notu sabit FASHN fiyatı yazıyordu, MAI mankeninde de.
    """
    row = mannequin.active()
    ozet = ({"id": int(row["id"]), "name": row["name"],
             "count": len(mannequin.list_all())} if row
            else {"id": 0, "name": "", "count": 0})
    return ozet | _katman_ucreti()


def _katman_ucreti() -> dict:
    """Aktif mankende bir katmanın modeli ve yaklaşık ücreti. Ağa çıkmaz."""
    from wardrobe import vision, vton

    try:
        p = vton.get_provider()
    except ValueError:                       # bozuk VTON_PROVIDER
        return {}
    katman = p.cost_usd()
    return {"provider": p.name, "model": vton.model_label(p),
            "layer_cost_usd": round(katman, 3),
            # Yükleme = okuma + katman.
            "upload_cost_usd": round(katman + vision.cost_usd_estimate(), 3)}


@app.get("/api/base.png")
def base_image() -> FileResponse:
    """Bindirmenin zemini — GÖSTERİM base'i (kıyafeti nötrlenmiş).

    Çıkarım base'i değil: nedeni mannequin.build_display_base docstring'inde.
    """
    path = mannequin.display_base()
    if not Path(path).is_file():
        raise HTTPException(404, "base manken yok — python cli.py mannequin")
    return FileResponse(path, media_type="image/png")


# --------------------------------------------------------------------------
# Mankenler — §28
#
# ÜCRET SINIRI BURADA ÇİZİLİ ve bilerek çizili:
#   · manken eklemek, geçmek, listelemek  → ÜCRETSİZ (fotoğraf işleme)
#   · o mankene katman üretmek            → ÜCRETLİ, AYRI bir işlem
#
# İkisi tek düğmeye bağlansaydı "yeni manken ekle" ~30 kredilik bir işlem olur
# ve kullanıcı bunu ancak fatura gelince fark ederdi.
# --------------------------------------------------------------------------


@app.get("/api/mannequins")
def mannequin_list() -> JSONResponse:
    """Mankenler + her birinin hazır katman sayısı + silinecek varlık sayısı."""
    liste = []
    for m in mannequin.list_all():
        liste.append({
            "id": m["id"],
            "name": m["name"],
            "kind": m["kind"],
            "is_active": m["is_active"],
            "has_image": m["has_image"],
            "layer_count": m["layer_count"],
            "rev": _rev(m["image_path"]),
            # Silme onayında gösterilecek: ne kaybedileceğini söylemeden onay
            # istemek, onay değildir (§28.4 #3).
            "usage": mannequin.usage(m["id"]),
        })
    return JSONResponse({"mannequins": liste, "active_id": mannequin.active_id()})


@app.get("/api/mannequins/{mannequin_id}.png")
def mannequin_image(mannequin_id: int, w: int = 0):
    """Mankenin GÖSTERİM görseli (kıyafeti nötrlenmiş hâli).

    Çıkarım base'i değil: seçim şeridindeki küçük görsel, kullanıcının
    kombinlerde göreceği zeminle aynı olmalı — yoksa "mavi tişörtlü olan"
    diye hatırladığı manken, seçince koyu gri çıkar.
    """
    m = next((x for x in mannequin.list_all() if x["id"] == mannequin_id), None)
    if not m or not m["has_image"]:
        raise HTTPException(404, "manken görseli yok")

    path = mannequin.display_base(mannequin_id=mannequin_id)
    if not w:
        return FileResponse(path, media_type="image/png")

    # Şeritteki kareler ~90 px; tam boy 864×1296 PNG'yi her manken için
    # indirmek gereksiz (§27.2'deki film şeridiyle aynı gerekçe).
    w = max(32, min(int(w), 1024))
    with Image.open(path) as im:
        kucuk = im.convert("RGB")
        kucuk.thumbnail((w, w * 4), Image.LANCZOS)
        buf = io.BytesIO()
        kucuk.save(buf, "PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@app.post("/api/mannequins")
def mannequin_create(
    file: UploadFile = File(...),
    name: str = Form(""),
) -> JSONResponse:
    """Yeni manken ekler — ÜCRETSİZ, mevcutlara DOKUNMAZ.

    Katman üretimi bilinçli olarak dahil değil: yeni mankende dolabı görmek
    için `build-layers` (ya da kıyafet kartlarındaki tek tek üretim) gerekiyor
    ve o ücretli.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        raise HTTPException(400, f"desteklenmeyen dosya tipi: {suffix or '(yok)'}")

    tmp = Path(tempfile.gettempdir()) / f"manken_{uuid.uuid4().hex[:10]}{suffix}"
    tmp.write_bytes(file.file.read())
    try:
        info = mannequin.add_from_photo(tmp, name=name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    finally:
        tmp.unlink(missing_ok=True)

    return JSONResponse({
        "id": info["mannequin_id"], "name": info["name"],
        "active_id": mannequin.active_id(),
        "layer_count": 0,
    }, status_code=201)


@app.post("/api/mannequins/{mannequin_id}/aktif")
def mannequin_activate(mannequin_id: int) -> JSONResponse:
    """Aktif mankeni değiştirir — ÜCRETSİZ ve HİÇBİR ŞEY SİLMEZ."""
    try:
        sonuc = mannequin.set_active(mannequin_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    # Gösterim base'i yoksa şimdi üretiliyor: kullanıcı geçiş yaptıktan sonra
    # boş bir sahne görmesin. Ücretsiz (yalnızca yeniden renklendirme).
    try:
        mannequin.display_base(mannequin_id=mannequin_id)
    except Exception:
        pass                    # görseli olmayan manken — arayüz zaten uyarıyor
    return JSONResponse(sonuc | {"layers": len(_layers_by_garment())})


@app.delete("/api/mannequins/{mannequin_id}")
def mannequin_delete(mannequin_id: int) -> JSONResponse:
    """Mankeni ve ONA AİT katman/render/düzenlemeleri siler — GERİ ALINAMAZ."""
    try:
        return JSONResponse(mannequin.delete(mannequin_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/layer/{garment_id}.png")
def layer_image(garment_id: int) -> FileResponse:
    row = _layers_by_garment().get(garment_id)
    if not row or row["status"] != "ready":
        raise HTTPException(404, f"#{garment_id} için hazır katman yok")
    if not Path(row["png_path"]).is_file():
        raise HTTPException(404, "katman dosyası diskte bulunamadı")
    return FileResponse(row["png_path"], media_type="image/png")


@app.get("/api/base_raw.png")
def base_raw_image() -> FileResponse:
    """Mankenin GERÇEK fotoğrafı — nötrlenmemiş hâli.

    Nötrleme (gösterim base'i) yalnızca BİNDİRME için var: katmanın boşluk
    bıraktığı ya da base'in kıyafetinin yeni kıyafetin siluetinin dışına taştığı
    yerlerde, altından çıkan şey base'in gerçek kıyafeti yerine nötr koyu bir
    ton olsun diye (§7.5, §7.6 — turkuaz deneyi bunu ölçmüştü).

    Bindirme olmayan iki durumda gerekli DEĞİL:
      · hiç kıyafet seçili değilken  → burası
      · tek kıyafet seçiliyken       → ham VTON çıktısı (§38)

    Yani kullanıcı griliği yalnızca gerçekten bindirme yapılan yerde görüyor.
    """
    row = mannequin.active()
    if not row or not row["image_path"] or not Path(row["image_path"]).is_file():
        raise HTTPException(404, "manken görseli yok")
    return FileResponse(row["image_path"], media_type="image/png")


@app.get("/api/dressed/{garment_id}.png")
def dressed_image(garment_id: int) -> FileResponse:
    """VTON'un HAM çıktısı — mankenin o kıyafeti giymiş hâli.

    NEDEN VAR: tek kıyafet seçiliyken katman bindirmesine hiç gerek yok.
    Bindirme, birden çok kıyafeti birleştirebilmek için var; tek parçada
    getirdiği tek şey ÇIKARIM KUSURLARI oluyor (base sızıntısı, kenar
    halkası, kör nokta).

    Ölçülen fark, manken 2'de lacivert tişört:

        ham çıktı        : temiz — tişört giydirilmiş, kusur yok
        katman bindirmesi: katmanın **%44.8'i** base'in kendi tişörtü
                           (base lacivert giyiyor, kıyafet de lacivert)

    Dosya ZATEN DİSKTE: `build_layer` ham çıktıyı `--reextract` için saklıyor,
    yani bu görüntü için tek kuruş ödenmiyor — ücreti çoktan ödenmiş bir
    sonucu göstermiyorduk sadece.

    Bindirme çok kıyafette hâlâ tek yol: ham çıktılar ayrı ayrı üretildiği
    için birleştirilemezler (her biri base'in geri kalanını da içeriyor).

    ⚠ HAM ÇIKTI DOĞRUDAN SERVİS EDİLMİYOR: §44'ten beri ham çıktı YEŞİL
    çıkarım base'ine karşı üretiliyor, yani kıyafetin örtmediği her yerde
    base'in boyanmış kıyafeti duruyor. `dressed_for_display` o bölgeleri
    gerçek fotoğrafla dolduruyor — kullanıcı yeşil görmüyor, çıkarım hattı
    ise olduğu gibi yeşil base'le çalışmaya devam ediyor.
    """
    from wardrobe.layers import dressed_for_display

    path = dressed_for_display(garment_id, mannequin.active_id())
    if path is None or not path.is_file():
        raise HTTPException(404, f"#{garment_id} için ham çıktı yok")
    return FileResponse(path, media_type="image/png")


@app.get("/api/cutout/{garment_id}.png")
def cutout_image(garment_id: int) -> FileResponse:
    """Dolap listesindeki küçük görsel — kıyafetin kırpılmış fotoğrafı."""
    g = get_garment(garment_id)
    if not g or not g["cutout_path"] or not Path(g["cutout_path"]).is_file():
        raise HTTPException(404, f"#{garment_id} için kırpılmış görsel yok")
    return FileResponse(g["cutout_path"], media_type="image/png")


@app.get("/api/outfits")
def list_outfits() -> JSONResponse:
    with connect() as conn:
        outfits = [dict(r) for r in conn.execute(
            "SELECT * FROM outfits ORDER BY id DESC"
        )]
        items = conn.execute(
            "SELECT outfit_id, garment_id FROM outfit_items"
        ).fetchall()
    by_outfit: dict[int, list[int]] = {}
    for r in items:
        by_outfit.setdefault(r["outfit_id"], []).append(r["garment_id"])
    for o in outfits:
        o["garment_ids"] = by_outfit.get(o["id"], [])
    return JSONResponse(outfits)


@app.post("/api/outfits")
def save_outfit(payload: dict) -> JSONResponse:
    ids = [int(i) for i in payload.get("garment_ids", [])]
    if not ids:
        raise HTTPException(400, "kombin boş")

    name = str(payload.get("name", "")).strip()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO outfits (name, source, context) VALUES (?, 'manual', ?)",
            (name, str(payload.get("context", ""))),
        )
        outfit_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT OR IGNORE INTO outfit_items (outfit_id, garment_id) VALUES (?, ?)",
            [(outfit_id, gid) for gid in ids],
        )
    return JSONResponse({"id": outfit_id, "garment_ids": ids}, status_code=201)


@app.delete("/api/outfits/{outfit_id}")
def delete_outfit(outfit_id: int) -> JSONResponse:
    with connect() as conn:
        cur = conn.execute("DELETE FROM outfits WHERE id = ?", (outfit_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "kombin bulunamadı")
    return JSONResponse({"deleted": outfit_id})


# --------------------------------------------------------------------------
# Kıyafet yükleme — CLI'sız akış
#
# `add_garment()` ucuz (kırpma + Claude özniteliği, ~$0.025) ama katman üretimi
# ÜCRETLİ (~$0.075). Bu yüzden ikisinin arasına ücretsiz bir kapı konuyor:
# kıyafet base'in kıyafetiyle kör noktadaysa katman üretilmiyor, kullanıcıya
# sebebi söyleniyor. Para, sonucu baştan belli olan bir çağrıya gitmiyor.
# --------------------------------------------------------------------------

UPLOAD_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@app.get("/api/templates")
def templates() -> JSONResponse:
    """Çekim şablonları — arayüz bunları kıyafetin üstüne bindiriyor."""
    return JSONResponse({
        "default": DEFAULT_SHAPE,
        "shapes": {k: {"label": v["label"], "category": v["category"],
                       "points": shape_points(k)}
                   for k, v in SHAPES.items()},
        # Hizalama sınırları da sunucudan geliyor: istemci kendi sınırını
        # tanımlarsa iki yer birbirinden habersiz kayar ve önizleme sunucudaki
        # sonuçla tutmaz (§14'teki "kural tek yerde" ilkesi).
        "align_limits": ALIGN_LIMITS,
    })


@app.post("/api/garments")
def garment_upload(
    file: UploadFile = File(...),
    shape: str = Form(DEFAULT_SHAPE),
    # Hizalama paneli çıktısı. Varsayılanları birim dönüşüm, yani paneli hiç
    # kullanmayan bir istemci (ya da eski bir sürüm) aynen eskisi gibi çalışır.
    dx: float = Form(0.0),
    dy: float = Form(0.0),
    scale: float = Form(1.0),
    rotate: float = Form(0.0),
) -> JSONResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        raise HTTPException(
            400, f"desteklenmeyen dosya tipi: {suffix or '(yok)'}")

    # Değerler istemciden geliyor — sunucuda kırpılıyor (bkz. clamp_align).
    align = clamp_align(dx=dx, dy=dy, scale=scale, rotate=rotate)

    tmp = Path(tempfile.gettempdir()) / f"upload_{uuid.uuid4().hex[:10]}{suffix}"
    tmp.write_bytes(file.file.read())

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "pending", "step": 0, "total": 2,
                         "phase": "yükleniyor"}

    def calis() -> None:
        try:
            _job_update(job_id, status="running", step=1,
                        phase="kırpılıyor ve öznitelikler çıkarılıyor")
            kayit = ingest.add_garment(tmp, shape=shape, align=align)

            # UYARI sorusu → çıkarım base'ine bakan fonksiyon.
            # `base_conflict` ZEMİN seçimi içindir ve gerçek fotoğrafa
            # bakar; ikisi aynı kıyafette zıt cevap verebiliyor
            # (#14: gerçek fotoğrafa 1.0, yeşil çıkarım base'ine 107.0).
            kontrol = layers.extraction_conflict(kayit["cutout_path"])
            _job_update(job_id, garment_id=kayit["id"], conflict=kontrol)

            # ⚠ BURASI ESKİDEN ÜRETİMİ ENGELLİYORDU ve o karar ölçümle çürüdü.
            #
            # Eski kural: uzaklık < 25 ise "katmanı boş çıkar" deyip ücretli
            # çağrıyı hiç yapmıyordu. Eşik fal/v1.6 ile ölçülmüştü (uzaklık 9 →
            # kaplama %0.6, gerçekten boş). tryon-max'te aynı bantta katman
            # sorunsuz çıkıyor: uzaklık 1.0'daki lacivert tişört üretildi,
            # kaplama tipiğin ~%65'i ve görsel olarak temiz.
            #
            # Yani engel, ÇALIŞAN bir işlemi yanlış bir tahminle durduruyordu.
            # Artık üretim yapılıyor, zayıf sinyal yalnızca NOT olarak geçiyor.
            _job_update(job_id, step=2, phase="katman üretiliyor (ücretli)")
            sonuc = layers.build_layer(kayit["id"])
            _job_update(
                job_id, status="done", layer_built=sonuc["status"] == "ready",
                phase="hazır" if sonuc["status"] == "ready" else "katman başarısız",
                error=sonuc.get("error", ""),
                note=kontrol.get("note", ""),
            )
        except Exception as exc:
            _job_update(job_id, status="failed",
                        error=f"{type(exc).__name__}: {exc}")
        finally:
            tmp.unlink(missing_ok=True)

    _arka_planda(job_id, calis)
    return JSONResponse({"status": "started", "job_id": job_id}, status_code=202)


@app.post("/api/garments/{garment_id}/layer")
def garment_build_layer(garment_id: int) -> JSONResponse:
    """Kör nokta uyarısına rağmen katman üretmek isteyen için."""
    if not get_garment(garment_id):
        raise HTTPException(404, "kıyafet bulunamadı")

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "pending", "step": 1, "total": 1,
                         "phase": "katman üretiliyor (ücretli)"}

    def calis() -> None:
        _job_update(job_id, status="running")
        sonuc = layers.build_layer(garment_id)
        _job_update(job_id, status="done",
                    layer_built=sonuc["status"] == "ready",
                    phase="hazır" if sonuc["status"] == "ready" else "başarısız",
                    error=sonuc.get("error", ""))

    _arka_planda(job_id, calis)
    return JSONResponse({"status": "started", "job_id": job_id}, status_code=202)


@app.delete("/api/garments/{garment_id}")
def garment_delete(garment_id: int) -> JSONResponse:
    if not delete_garment(garment_id):
        raise HTTPException(404, "kıyafet bulunamadı")
    return JSONResponse({"deleted": garment_id})


# --------------------------------------------------------------------------
# Faz 4 — "Gerçekçi Göster"
#
# Zincir 30-80 saniye sürüyor. Senkron bir istek bu süre boyunca kullanıcıya
# hiçbir şey söyleyemezdi, o yüzden iş arka planda çalışıyor ve arayüz durumu
# yokluyor: "3 kıyafetten 2.si" diyebilmek için.
# --------------------------------------------------------------------------

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _job_update(job_id: str, **alanlar) -> None:
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(alanlar)


def _arka_planda(job_id: str, is_fn) -> None:
    """İşi ayrı bir iş parçacığında çalıştırır; ÇÖKERSE işi failed işaretler.

    Bu sarmalayıcı ölçülmüş bir arızadan sonra eklendi: iş parçacığı bir
    istisnayla ölürse iş sözlüğünde `status="running"` olarak kalıyor ve
    arayüz sonsuza kadar yokluyordu. Kullanıcı "çalışmıyor" diyor, sunucu
    kaydında ise hiçbir hata görünmüyor — çünkü istisna daemon thread'de
    sessizce kaybolmuş oluyor.

    Terminal durum GARANTİ: her yol ya done ya failed ile bitiyor.
    """
    def sar() -> None:
        try:
            is_fn()
        except BaseException as exc:       # SystemExit dahil: iş yine bitmeli
            _job_update(job_id, status="failed",
                        error=f"{type(exc).__name__}: {exc}")
            raise

    threading.Thread(target=sar, daemon=True).start()


RENDER_PROVIDERS = ("fal", "fashn", "gemini", "foundry")


def _render_provider(payload: dict):
    """İstekteki sağlayıcıyı NESNE olarak çözer; belirtilmemişse varsayılanı.

    ⚠ ÖNCE None DÖNÜYORDU ve bu para kaybettiren bir hataya yol açtı:
    çağıran taraf `None` görünce anahtarı `DEFAULT_RENDER_PROVIDER` ("fal")
    ile hesaplıyordu, ama `render_outfit` içeride `get_provider()` çağırıp
    fashn'a düşüyor ve dosyayı `..._fashn.png` olarak yazıyordu. Aynı istek
    iki farklı anahtar üretti; render üretildi, ÜCRETLENDİ, arayüz bulamadı.

    Çözüm: sağlayıcı TEK YERDE çözülüyor ve hem anahtar hem çağrı aynı
    nesneden türüyor. `get_provider()` ağa çıkmıyor (yalnızca anahtar
    varlığına bakıyor), yani plan()'ın ücretsizliği bozulmuyor.

    Beyaz liste şart: `payload` istemciden geliyor ve get_provider'a serbest
    metin geçirmek istemiyoruz.
    """
    from wardrobe import vton

    ad = payload.get("provider")
    if ad and ad not in RENDER_PROVIDERS:
        raise HTTPException(400, f"bilinmeyen sağlayıcı: {ad}")
    return vton.get_provider(ad) if ad else vton.get_provider()


@app.post("/api/render/plan")
def render_plan(payload: dict) -> JSONResponse:
    """Ne kadar süreceğini ve tutacağını çağrı YAPMADAN söyler."""
    from wardrobe import vton

    ids = [int(i) for i in payload.get("garment_ids", [])]
    if not ids:
        raise HTTPException(400, "kombin boş")
    provider = _render_provider(payload)
    ad = provider.name
    p = render.plan(ids, provider=provider)
    # Anahtar DİSKTEKİ dosyadan türüyor: varsa onun adı, yoksa bu sağlayıcının
    # yazacağı ad. Arayüzün gösterdiği adres ile bulunan dosya ayrışırsa
    # ödenmiş render "yok" görünüyor — bir kez oldu (bkz. render.cached_key).
    mevcut = render.cached_key(ids, provider_name=ad)
    p["cached"] = mevcut is not None
    p["provider"] = ad
    p["model"] = vton.model_label(provider)
    p["key"] = mevcut or render.cache_key(ids, provider_name=ad)
    return JSONResponse(p)


@app.post("/api/render")
def render_start(payload: dict) -> JSONResponse:
    ids = [int(i) for i in payload.get("garment_ids", [])]
    if not ids:
        raise HTTPException(400, "kombin boş")

    provider = _render_provider(payload)
    ad = provider.name

    mevcut = render.cached_key(ids, provider_name=ad)
    if not payload.get("force") and mevcut:
        return JSONResponse({"status": "cached", "key": mevcut})

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "pending", "step": 0,
                         "total": render.plan(ids, provider=provider)["calls"],
                         "garment_ids": ids}

    def calis() -> None:
        _job_update(job_id, status="running")
        sonuc = render.render_outfit(
            ids,
            provider=provider,
            force=bool(payload.get("force")),
            progress=lambda i, n, gid: _job_update(
                job_id, step=i, total=n, current_garment=gid),
        )
        _job_update(
            job_id,
            status="done" if sonuc["status"] in ("ok", "cached") else "failed",
            key=render.cached_key(ids, provider_name=ad)
                or render.cache_key(ids, provider_name=ad),
            error=sonuc.get("error", ""),
            calls=sonuc.get("calls", 0),
            cost_usd=sonuc.get("cost_usd", 0.0),
        )

    _arka_planda(job_id, calis)
    return JSONResponse({"status": "started", "job_id": job_id}, status_code=202)


@app.get("/api/render/job/{job_id}")
def render_status(job_id: str) -> JSONResponse:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "iş bulunamadı")
    return JSONResponse(job)


# --------------------------------------------------------------------------
# Düzenleme sohbeti — render'ın üzerine serbest metin talimatları
#
# "kolları kıvır", "hafifçe sola dön", "gömleği içine sok". Her talimat bir
# önceki sonucun üzerine uygulanıyor, yani konuşma gibi ilerliyor.
# --------------------------------------------------------------------------


@app.post("/api/edit/source")
def edit_source(payload: dict) -> JSONResponse:
    """Düzenlemenin başlayacağı kaynağı hazırlar ve anahtarını döner.

    İki kaynak var ve seçim KULLANICININ:
      · "layers" — katman bindirmesi. ÜCRETSİZ üretiliyor; düzenleme 2 kredi.
      · "render" — Faz 4'ün zincirleme render'ı. Temiz zemin ama önce
        üretilmiş olması gerekiyor (kıyafet başına ücretli).
    """
    from wardrobe import vton

    ids = [int(i) for i in payload.get("garment_ids", [])]
    if not ids:
        raise HTTPException(400, "kombin boş")
    mod = str(payload.get("mode", "layers"))
    # Ücret, düzenlemeyi GERÇEKTEN yapacak sağlayıcıdan (§54). Ağa çıkmıyor.
    duzenleyici = vton.get_edit_provider()

    if mod == "layers":
        try:
            key = edits.ensure_composite(ids)
        except Exception as exc:
            raise HTTPException(400, f"katman görüntüsü üretilemedi: {exc}")
        return JSONResponse(edits.plan(key, provider=duzenleyici) | {"mode": "layers"})

    key = render.cached_key(ids, provider_name=vton.get_provider().name)
    if not key:
        raise HTTPException(
            409, "bu kombinin gerçekçi render'ı yok — önce 'Gerçekçi Göster'")
    return JSONResponse(edits.plan(key, provider=duzenleyici) | {"mode": "render"})


@app.get("/api/edit/{key}")
def edit_state(key: str) -> JSONResponse:
    """Zincirin durumu — çağrı YAPMADAN (ücretsiz)."""
    from wardrobe import vton

    try:
        return JSONResponse(edits.plan(key, provider=vton.get_edit_provider()))
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/edit/{key}/current.png")
def edit_current(key: str) -> FileResponse:
    """Zincirin sonundaki görüntü — düzenleme yoksa render'ın kendisi."""
    try:
        yol = edits.current_path(key)
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))
    if not yol:
        raise HTTPException(404, "gösterilecek görüntü yok")
    return FileResponse(yol, media_type="image/png")


@app.post("/api/edit/{key}")
def edit_start(key: str, payload: dict) -> JSONResponse:
    prompt = str(payload.get("prompt", ""))
    try:
        edits.plan(key)                      # anahtarı doğrula
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))

    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "pending", "step": 0, "total": 1,
                         "phase": "düzenleniyor", "key": key}

    def calis() -> None:
        _job_update(job_id, status="running")
        try:
            sonuc = edits.apply_edit(key, prompt)
            _job_update(job_id, status="done", step=1,
                        count=sonuc["count"], applied=sonuc["step"]["prompt"])
        except Exception as exc:
            _job_update(job_id, status="failed",
                        error=f"{type(exc).__name__}: {exc}")

    _arka_planda(job_id, calis)
    return JSONResponse({"status": "started", "job_id": job_id}, status_code=202)


@app.get("/api/edit/{key}/step/{n}.png")
def edit_step_image(key: str, n: int, w: int = 0):
    """Tek bir düzenleme adımının görüntüsü — film şeridi bunu kullanıyor.

    Ayrı uç nokta ŞART: adım dosyaları `m1_6-8_e1.png` biçiminde ve render
    uç noktasının anahtar deseni (`m\\d+_[\\d\\-]+(_[a-z]+)?`) rakam içeren eki
    kabul etmiyor — oradan istenirse 404 döner.

    `w` verilirse görüntü o genişliğe küçültülüp döndürülüyor. Film şeridi
    62 px'lik kareler çiziyor ama tam boy dosyalar 1.2-1.4 MB; dört kare
    ~5 MB indirmek demekti. Telefondan (§17) bu fark hissediliyor.
    """
    try:
        yol = edits.base_path(key) if n == 0 else edits.step_path(key, n)
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))
    if n == 0 and not yol.is_file():
        yol = edits.materialize(key) or yol      # katman kaynağı tembel üretilir
    if not yol.is_file():
        raise HTTPException(404, "adım bulunamadı")

    if not w:
        return FileResponse(yol, media_type="image/png")

    w = max(32, min(int(w), 1024))
    with Image.open(yol) as im:
        kucuk = im.convert("RGB")
        kucuk.thumbnail((w, w * 4), Image.LANCZOS)
        buf = io.BytesIO()
        kucuk.save(buf, "PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@app.post("/api/edit/{key}/select")
def edit_select(key: str, payload: dict) -> JSONResponse:
    """Zinciri bir adıma geri sarar (film şeridinden seçim)."""
    try:
        return JSONResponse(edits.select(key, int(payload.get("n", 0))))
    except (edits.EditError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/edit/{key}/undo")
def edit_undo(key: str) -> JSONResponse:
    try:
        return JSONResponse(edits.undo(key))
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/edit/{key}/redo")
def edit_redo(key: str) -> JSONResponse:
    try:
        return JSONResponse(edits.redo(key))
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/edit/{key}/reset")
def edit_reset(key: str) -> JSONResponse:
    try:
        return JSONResponse(edits.reset(key))
    except edits.EditError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/render/{key}.png")
def render_image(key: str) -> FileResponse:
    path = render.RENDER_DIR / f"{key}.png"
    # Yol enjeksiyonuna kapalı olsun: anahtar sadece bizim ürettiğimiz biçimde.
    # Sondaki isteğe bağlı `_<sağlayıcı>` eki, varsayılan dışı bir sağlayıcıyla
    # üretilmiş renderlar için (bkz. render.cache_key).
    if not re.fullmatch(r"m\d+_[\d\-]+(_[a-z]+)?", key) or not path.is_file():
        raise HTTPException(404, "render bulunamadı")
    return FileResponse(path, media_type="image/png")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    """index.html'i, varlık URL'lerine SÜRÜM DAMGASI basarak servis eder.

    `no-cache` başlığı tek başına yetmiyor: tarayıcı dosyayı başlık eklenmeden
    ÖNCE önbelleğe aldıysa eski politikaya uymaya devam ediyor. Bu gerçekten
    yaşandı — sunucudaki app.js günceldi, başlık doğruydu, sayfa zorla
    yenilendi, tarayıcı yine eski kodu çalıştırdı.

    URL'nin kendisi değişince bu sınıf hata tamamen ortadan kalkıyor: farklı
    URL = farklı kaynak, önbellekte karşılığı yok. Damga dosyanın mtime'ı,
    yani dosya değişmediyse URL de değişmiyor.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    for varlik in ("app.js", "style.css"):
        html = html.replace(varlik, f"{varlik}?v={_rev(str(STATIC_DIR / varlik))}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


class _TazeStatik(StaticFiles):
    """Arayüz dosyalarını her seferinde DOĞRULATIR (no-cache).

    Neden gerekli: tarayıcı `app.js`'i bellekten servis edip **eski sürümü**
    çalıştırıyordu. Ölçüldü — sunucuda yeni satır (`?v=` sürüm damgası) vardı,
    tarayıcıdaki `guncelle` fonksiyonunda eski satır duruyordu. Yani görsellerin
    bayatlamasını düzeltmek için yazılan kodun kendisi bayat kaldığı için
    devreye girmiyordu.

    `no-cache` "önbelleğe alma" demek DEĞİL: "önbellekten kullanmadan önce
    sunucuya sor" demek. Dosya değişmediyse cevap 304 ve gövde inmiyor — yani
    yerel bir uygulamada bedeli ölçülemeyecek kadar küçük, karşılığı ise
    "kod güncellendi ama çalışmıyor" sınıfının tamamen ortadan kalkması.

    Görseller bu sınıfın dışında: onlar `/api/...` altından geliyor ve URL'de
    sürüm damgası taşıyor, yani uzun süre önbelleklenebilirler.
    """

    async def get_response(self, path: str, scope):
        cevap = await super().get_response(path, scope)
        cevap.headers["Cache-Control"] = "no-cache"
        return cevap


# Statik dosyalar en sona: "/" bunun içinden index.html olarak geliyor.
app.mount("/", _TazeStatik(directory=STATIC_DIR, html=True), name="static")


def run(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run(
        "web.app:app" if reload else app,
        host=host, port=port, reload=reload,
        app_dir=str(PROJECT_ROOT) if reload else None,
    )
