"""Yükleme hattı: fotoğraf → kalıcı kopya → arka plan temizleme → VLM → DB.

Tek giriş noktası: add_garment(). CLI de, ileride FastAPI uç noktası da bunu
çağırır — hat mantığı tek yerde durur.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from PIL import Image

from config import CUTOUT_DIR, RAW_DIR
from db import insert_garment
from wardrobe.cutout import coverage, remove_background, touches_frame_edge
from wardrobe.imageutil import (
    apply_align, clamp_align, is_identity_align, load_upright,
)
from wardrobe.vision import extract_attributes

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Kırpma kalite eşikleri — bu aralığın dışı "şüpheli kırpma" sayılır.
MIN_COVERAGE = 0.02   # neredeyse her şey silinmiş
MAX_COVERAGE = 0.97   # neredeyse hiçbir şey silinmemiş


class IngestError(Exception):
    """Yükleme öncesi doğrulama hatası (dosya yok, desteklenmeyen tip...)."""


def add_garment(
    photo_path: str | Path,
    *,
    use_vlm: bool = True,
    cutout_method: str | None = None,
    shape: str | None = None,
    align: dict | None = None,
    db_path=None,
) -> dict:
    """Bir kıyafet fotoğrafını dolaba ekler.

    Args:
        photo_path: Kullanıcının çektiği fotoğraf.
        use_vlm: False ise VLM çağrılmaz, kategori/renk yedek yolla doldurulur.
        cutout_method: "auto" | "rembg" | "flood". Varsayılan auto.
        shape: Çekim şablonu anahtarı (bkz. wardrobe.templates). Kırpma kadraj
            kenarına dayanırsa bu şablon önsel olarak kullanılıp kurtarma
            yapılıyor — ölçüldü, bozuk modeli bile düzeltiyor.
        align: Arayüzdeki hizalama paneli çıktısı — {dx, dy, scale, rotate}.
            Kırpmadan ÖNCE uygulanıyor: şablon önselinin kıyafete oturması
            için fotoğrafın şablona oturması gerekiyor, tersi değil.

    Returns:
        Eklenen kaydın alanları + "id" ve "warnings" (liste).

    Raises:
        IngestError: Dosya yoksa ya da tipi desteklenmiyorsa.
    """
    src = Path(photo_path)
    if not src.is_file():
        raise IngestError(f"Dosya bulunamadı: {src}")
    if src.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise IngestError(
            f"Desteklenmeyen dosya tipi: {src.suffix} "
            f"(desteklenen: {', '.join(sorted(SUPPORTED_SUFFIXES))})"
        )

    slug = uuid.uuid4().hex[:12]
    raw_path = RAW_DIR / f"{slug}{src.suffix.lower()}"
    cutout_path = CUTOUT_DIR / f"{slug}.png"
    shutil.copy2(src, raw_path)

    warnings: list[str] = []

    # SIRA: ÖNCE KIRP, SONRA HİZALA. (§31 — ölçümle değişti.)
    #
    # Eskiden tersiydi ve bir kıyafeti sessizce mahvetti. Kullanıcı chino
    # pantolonu şablona oturtmak için %53'e küçültmüştü; küçültülmüş fotoğrafta
    # kıyafet, segmentasyon modelinin çalışma çözünürlüğünde (1024 px) ~400 px'e
    # düşüyor ve model siluet yerine kaba bir DİKDÖRTGEN BLOK döndürüyor —
    # çizgili çarşaf ve çiçekli perde "kıyafetin parçası" olarak içeride kaldı.
    # Aynı fotoğraf, aynı model, hizalamasız:
    #
    #     hizalanmış (%53) : kutu doluluğu %86.8   → blok, zemin içeride
    #     orijinal         : kutu doluluğu %61.4   → düzgün pantolon silueti
    #
    # Hizalamanın amacı kırpmayı İYİLEŞTİRMEKTİ (şablon önseli kıyafete
    # otursun diye, §21); ölçüm tam tersini gösterdi. Kırpma önce yapılınca
    # küçültme segmentasyonu artık etkileyemiyor.
    #
    # Hizalama yine de uygulanıyor — sadece kırpılmış RGBA'nın üzerine. Şablon
    # önizlemesinin ve kadrajlamanın anlamı korunuyor, kırpma kalitesi ise
    # kullanıcının panelde ne yaptığından bağımsız hale geliyor.
    method = remove_background(raw_path, cutout_path,
                               method=cutout_method, shape=shape)

    align = clamp_align(**align) if align else None
    if align and not is_identity_align(align):
        # Hizalanmış görüntü AYRI bir dosyaya da yazılıyor, orijinalin üstüne
        # değil: kullanıcı hizalamayı yanlış yaparsa geri dönecek bir şey
        # kalmalı, yoksa tek çare fotoğrafı telefondan yeniden yüklemek olurdu.
        hizali = apply_align(Image.open(cutout_path).convert("RGBA"), align)
        hizali.save(cutout_path, "PNG")
        hizali.save(RAW_DIR / f"{slug}_aligned.png", "PNG")
    if method == "flood":
        warnings.append(
            "Arka plan yedek yöntemle (flood) temizlendi. Daha iyi sonuç için: "
            'pip install "rembg[cpu]"'
        )

    ratio = coverage(cutout_path)
    if ratio < MIN_COVERAGE:
        warnings.append(
            f"Kırpma şüpheli: kıyafet karenin sadece %{ratio * 100:.1f}'i. "
            "Fotoğrafı düz ve tek renk zeminde tekrar çekmeyi dene."
        )
    elif ratio > MAX_COVERAGE:
        warnings.append(
            f"Arka plan neredeyse hiç silinemedi (%{ratio * 100:.1f} dolu). "
            "Zemin kıyafete çok yakın renkte olabilir."
        )

    # Kaplama makul olsa bile kırpık kadraj kenarına dayanıyorsa arka planın bir
    # parçası kıyafete katılmış demektir (bkz. touches_frame_edge). Bu ayrı bir
    # sinyal: ölçülen vakada kaplama %44.5 ile tam normaldi ama kırpık solda
    # kadrajın kenarına kadar uzanıyordu ve VTON çıktısını bozdu.
    if touches_frame_edge(cutout_path):
        warnings.append(
            "Kırpma kadrajın kenarına dayanıyor — zeminin bir kısmı kıyafete "
            "katılmış olabilir. Kıyafetle ZIT renkte bir zeminde (açık kıyafet "
            "için koyu örtü) tekrar çekmek en güvenilir çözüm."
        )

    # VLM, renk analizini kırpılmış görselden yapabilsin diye cutout'u veriyoruz;
    # arka plan gürültüsü olmadan renk ve desen çok daha isabetli çıkıyor.
    # Dosyaları UUID ile sakladığımız için orijinal adı ayrıca ipucu olarak
    # geçiyoruz — yedek yolun kategori tahmini buna dayanıyor.
    if use_vlm:
        attrs = extract_attributes(cutout_path, name_hint=src.name)
    else:
        from wardrobe.vision import _mock_attributes
        attrs = _mock_attributes(
            cutout_path, note="VLM atlandı (--no-vlm)", name_hint=src.name
        )

    attrs |= {
        "raw_path": str(raw_path),
        "cutout_path": str(cutout_path),
        "cutout_method": method,
        # Hizalama kaydediliyor: "bu kırpma neden böyle çıktı" sorusunun cevabı
        # ve ileride fotoğrafı yeniden yüklemeden yeniden hizalamanın girdisi.
        "align_json": json.dumps(align, ensure_ascii=False) if align else "",
    }
    garment_id = insert_garment(attrs, db_path=db_path)

    return attrs | {"id": garment_id, "warnings": warnings, "coverage": ratio}


def add_folder(
    folder: str | Path,
    *,
    use_vlm: bool = True,
    cutout_method: str | None = None,
    db_path=None,
) -> list[dict]:
    """Bir klasördeki tüm desteklenen görselleri sırayla ekler.

    Tek tek başarısız olanlar hattı durdurmaz; sonuç listesinde "error" alanıyla
    döner — 60 kıyafetlik bir yüklemede 3. dosya bozuk diye baştan başlamak
    istemiyoruz.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise IngestError(f"Klasör bulunamadı: {folder}")

    results: list[dict] = []
    files = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    for path in files:
        try:
            results.append(add_garment(
                path, use_vlm=use_vlm, cutout_method=cutout_method, db_path=db_path
            ))
        except Exception as exc:
            results.append({"raw_path": str(path), "error": str(exc)})
    return results
