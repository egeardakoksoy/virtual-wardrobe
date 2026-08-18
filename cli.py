"""Komut dağıtıcı — Faz 0 (dolap altyapısı).

    python cli.py init                      # veritabanını kur
    python cli.py add foto.jpg              # tek kıyafet ekle
    python cli.py add-folder ./fotograflar  # klasördeki her şeyi ekle
    python cli.py list [--category ust]     # dolabı listele
    python cli.py show 3                    # tek kıyafetin detayı
    python cli.py rm 3                      # kıyafeti sil
    python cli.py stats                     # özet
    python cli.py doctor                    # kurulum/anahtar kontrolü

Faz 1 — manken ve katmanlar:
    python cli.py mannequin                 # base mankeni oluştur
    python cli.py build-layers              # tüm kıyafetler için katman üret
    python cli.py preview 1 2 3             # katmanları birleştirip PNG yaz
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import CATEGORIES, CATEGORY_KEYS, DB_PATH, PROJECT_ROOT
from db import count_by_category, delete_garment, get_garment, init_db, list_garments
from wardrobe import layers, mannequin, secrets, vton
from wardrobe.cutout import METHODS as CUTOUT_METHODS, has_rembg
from wardrobe.ingest import IngestError, add_folder, add_garment
from wardrobe.vision import MODEL, has_api_key


def _source_banner() -> str:
    vlm = f"Claude ({MODEL})" if has_api_key() else "MOCK (ANTHROPIC_API_KEY yok)"
    seg = "rembg" if has_rembg() else "flood (yedek)"
    return f"Öznitelik: {vlm} | Arka plan: {seg}"


def _print_garment(g: dict, warnings: list[str] | None = None) -> None:
    cat = CATEGORIES.get(g["category"], {}).get("label", g["category"])
    print(f"\n#{g['id']}  {g['subcategory'] or cat}  [{cat}]")
    print(f"   Renk      : {g['color_name']} {g['color_hex']}"
          + (f" + {g['secondary_color_hex']}" if g["secondary_color_hex"] else ""))
    print(f"   Desen/Stil: {g['pattern']} · {g['style']} · {g['fabric']}")
    print(f"   Sıcaklık  : {g['warmth']}/10   Resmiyet: {g['formality']}/10")
    print(f"   Mevsim    : {g['seasons']}")
    print(f"   Kaynak    : {g['attr_source']} | kırpma: {g['cutout_method']}")
    if g["notes"]:
        print(f"   Not       : {g['notes']}")
    for w in warnings or []:
        print(f"   ⚠  {w}")


# --- Komutlar ---

def cmd_init(args) -> int:
    init_db()
    print(f"Veritabanı hazır: {DB_PATH}")
    print(_source_banner())
    return 0


def cmd_add(args) -> int:
    init_db()
    print(_source_banner())
    try:
        result = add_garment(
            args.path, use_vlm=not args.no_vlm, cutout_method=args.cutout
        )
    except IngestError as exc:
        print(f"Hata: {exc}")
        return 1
    _print_garment(result, result["warnings"])
    return 0


def cmd_add_folder(args) -> int:
    init_db()
    print(_source_banner())
    try:
        results = add_folder(
            args.folder, use_vlm=not args.no_vlm, cutout_method=args.cutout
        )
    except IngestError as exc:
        print(f"Hata: {exc}")
        return 1

    if not results:
        print("Klasörde desteklenen görsel bulunamadı.")
        return 1

    ok = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    for r in ok:
        _print_garment(r, r["warnings"])
    for r in failed:
        print(f"\n✗ {r['raw_path']}: {r['error']}")

    print(f"\n{len(ok)} kıyafet eklendi, {len(failed)} başarısız.")
    return 0 if ok else 1


def cmd_list(args) -> int:
    init_db()
    rows = list_garments(category=args.category)
    if not rows:
        print("Dolap boş. Önce: python cli.py add <foto>")
        return 1

    header = f"{'ID':>4}  {'KATEGORI':<11} {'PARÇA':<24} {'RENK':<12} {'ISI':>4} {'RES':>4}"
    print(header)
    print("-" * len(header))
    for g in rows:
        cat = CATEGORIES.get(g["category"], {}).get("label", g["category"])
        print(f"{g['id']:>4}  {cat:<11} {g['subcategory'][:24]:<24} "
              f"{g['color_name'][:12]:<12} {g['warmth']:>4} {g['formality']:>4}")
    print(f"\nToplam {len(rows)} kıyafet.")
    return 0


def cmd_show(args) -> int:
    g = get_garment(args.id)
    if not g:
        print(f"#{args.id} bulunamadı.")
        return 1
    _print_garment(g)
    print(f"   Orijinal  : {g['raw_path']}")
    print(f"   Kırpılmış : {g['cutout_path']}")
    return 0


def cmd_rm(args) -> int:
    if delete_garment(args.id):
        print(f"#{args.id} silindi. (Dosyalar data/ altında duruyor.)")
        return 0
    print(f"#{args.id} bulunamadı.")
    return 1


def cmd_stats(args) -> int:
    init_db()
    counts = count_by_category()
    total = sum(counts.values())
    print(_source_banner())
    print(f"\nDolapta {total} kıyafet:\n")
    for key in CATEGORY_KEYS:
        label = CATEGORIES[key]["label"]
        n = counts.get(key, 0)
        bar = "█" * n
        print(f"  {label:<11} {n:>3}  {bar}")

    missing = [CATEGORIES[k]["label"] for k in CATEGORY_KEYS if not counts.get(k)]
    if missing and total:
        print(f"\nHenüz hiç yok: {', '.join(missing)}")
    return 0


def cmd_doctor(args) -> int:
    """Kurulumu ve anahtarları kontrol eder — anahtar DEĞERİ asla yazdırılmaz."""
    ok = True
    print("Kurulum kontrolü\n" + "=" * 52)

    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        print(f"✓ .env bulundu ({env_file})")
    else:
        print("✗ .env yok. Kur:  cp .env.example .env   (sonra düzenle)")
        ok = False

    print("\nAnahtarlar (değerler maskeli — kopyalanamaz):")
    for name, purpose, fallback in secrets.KNOWN_KEYS:
        info = secrets.describe(name)
        if not info["present"]:
            print(f"  ○ {name:<20} yok → {fallback}")
            continue

        print(f"  ✓ {name:<20} {info['masked']}  ({info['length']} karakter)")
        if info["looks_quoted"]:
            print(f"      ⚠ Tırnak içinde görünüyor. .env'de tırnak KULLANMA: "
                  f"{name}=deger")
            ok = False
        if info["has_whitespace"]:
            print("      ⚠ Boşluk içeriyor. Yapıştırırken fazladan boşluk/satır "
                  "sonu kalmış olabilir.")
            ok = False
        print(f"      {purpose}")

    print("\nBağımlılıklar:")
    if has_rembg():
        print("  ✓ rembg   kurulu (iyi kırpma)")
    else:
        # Sade `pip install rembg` motor kurmuyor: paket import edilirken
        # sys.exit(1) çağırıyor. Doğru komut [cpu] ekiyle olan.
        print('  ○ rembg   yok/eksik → flood yedeği kullanılıyor')
        print('            Düzeltmek için:  pip install "rembg[cpu]"')

    print("\nVeri:")
    print(f"  {'✓' if Path(DB_PATH).is_file() else '○'} {DB_PATH}")

    print("\n" + "=" * 52)
    if ok:
        print("Kurulum sağlam görünüyor.")
    else:
        print("Yukarıdaki ⚠/✗ maddelerini düzelt.")
    return 0 if ok else 1


def cmd_mannequin(args) -> int:
    """Manken oluşturur, listeler, aralarında geçiş yapar, siler (§28).

    Ücret sınırı: bu komutun HİÇBİR alt işlemi katman üretmiyor. Manken
    eklemek ve geçiş yapmak bedava; yeni mankende dolabı görmek için ayrıca
    `build-layers` çalıştırmak gerekiyor ve o ücretli.
    """
    init_db()

    if args.list:
        return _manken_listele()
    if args.use is not None:
        return _manken_gec(args.use)
    if args.rm is not None:
        return _manken_sil(args.rm, args.yes)

    if args.from_photo:
        try:
            info = mannequin.from_photo(args.from_photo, name=args.name)
        except ValueError as exc:
            print(f"Hata: {exc}")
            return 1
    elif args.name:
        print("--name yalnızca --from-photo ile kullanılır "
              "(yeni manken bir fotoğraftan açılıyor).")
        return 1
    elif args.placeholder:
        info = mannequin.placeholder(reason="--placeholder ile istendi")
    else:
        info = mannequin.generate(style=args.style)

    etiket = "Yeni manken eklendi" if info.get("created") else "Manken hazır"
    print(f"{etiket}: {info['image_path']}")
    print(f"   Ad     : {info.get('name', '?')}  (#{info.get('mannequin_id', '?')})")
    print(f"   Tip    : {info['kind']}")
    print(f"   Boyut  : {info['size'][0]}x{info['size'][1]}")
    if info.get("created"):
        print("   Bu manken artık AKTİF. Diğer mankenlerin katmanları duruyor.")
        print("   Bu mankende dolabı görmek için (ÜCRETLİ):  python cli.py build-layers")
    if info.get("invalidated_layers"):
        print(f"   ⚠  {info['invalidated_layers']} katman geçersiz kılındı — bu "
              "mankenin FOTOĞRAFI değişti, yeniden üretilmeleri gerekiyor:")
        print("      python cli.py build-layers")
    if info.get("reason"):
        print(f"   ⚠  Gerçek üretim yapılamadı → {info['reason']}")
        print("      Placeholder ile hattı test edebilirsin ama sonuç gerçekçi olmaz.")
    return 0


def _manken_listele() -> int:
    mankenler = mannequin.list_all()
    if not mankenler:
        print("Hiç manken yok. Kur: python cli.py mannequin --from-photo <foto>")
        return 1

    print(f"{'':2} {'ID':>3}  {'AD':<18} {'TİP':<12} {'KATMAN':>7}  DOSYA")
    print("-" * 64)
    for m in mankenler:
        isaret = "▶" if m["is_active"] else " "
        durum = "" if m["has_image"] else "  ⚠ görseli yok"
        print(f"{isaret:2} {m['id']:>3}  {m['name'][:18]:<18} {m['kind'][:12]:<12} "
              f"{m['layer_count']:>7}  {Path(m['image_path']).name}{durum}")
    print("\n▶ = aktif. Geçiş ÜCRETSİZ ve hiçbir katmanı silmez:")
    print("   python cli.py mannequin --use <id>")
    return 0


def _manken_gec(mannequin_id: int) -> int:
    try:
        mannequin.set_active(mannequin_id)
    except ValueError as exc:
        print(f"Hata: {exc}")
        return 1
    m = mannequin.active()
    hazir = next((x["layer_count"] for x in mannequin.list_all()
                  if x["id"] == mannequin_id), 0)
    print(f"Aktif manken: #{m['id']} {m['name']} — {hazir} katman hazır.")
    if not hazir:
        print("   Bu mankenin hiç katmanı yok. Üretmek ÜCRETLİ:")
        print("      python cli.py build-layers")
    return 0


def _manken_sil(mannequin_id: int, yes: bool) -> int:
    """Silme GERİ ALINAMAZ ve ücretle üretilmiş veriyi yok eder (§28.4 #3)."""
    hedef = next((m for m in mannequin.list_all() if m["id"] == mannequin_id), None)
    if not hedef:
        print(f"#{mannequin_id} bulunamadı.")
        return 1

    kayip = mannequin.usage(mannequin_id)
    print(f"#{mannequin_id} {hedef['name']} silinecek. GERİ ALINAMAZ.")
    print(f"   {kayip['layers']} katman · {kayip['renders']} render · "
          f"{kayip['edits']} düzenleme adımı gidecek.")
    print("   (Hepsi ücretle üretildi; yeniden üretmek yeniden ödemek demek.)")

    if not yes:
        try:
            if input("Devam? [e/H] ").strip().lower() not in ("e", "evet", "y", "yes"):
                print("İptal edildi.")
                return 1
        except EOFError:
            print("stdin yok — betikten çalıştırıyorsan --yes ekle.")
            return 1

    sonuc = mannequin.delete(mannequin_id)
    print(f"Silindi. Aktif manken artık #{sonuc['active_id']}.")
    return 0


def cmd_build_layers(args) -> int:
    init_db()

    if args.reextract:
        results = layers.reextract(args.id)
        if not results:
            print("Yeniden çıkarılacak katman yok.")
            return 1
        print("Saklanmış ham çıktılardan yeniden çıkarıldı (API çağrısı yok, $0):")
        for r in results:
            icon = "✓" if r["status"] == "ready" else "—"
            line = f"  {icon} #{r['garment_id']:<3} {r['status']}"
            if r.get("coverage") is not None:
                line += f"  kaplama %{r['coverage'] * 100:.1f}"
            print(line)
            if r.get("error"):
                print(f"      {r['error']}")
        return 0

    provider = vton.get_provider(args.provider)

    # TOHUM — karşılaştırma yapan her üretim için ŞART.
    #
    # ⚠ Bu bir yöntem hatasının düzeltmesi. Bir kıyafetin katmanı, kırpığı
    # düzeltildikten sonra tohumsuz yeniden üretildi ve sonuç eskisinden kötü
    # çıktı. Ama difüzyon stokastik: aynı girdiyle iki çağrı zaten farklı
    # sonuç verir. Yani "kırpık düzeldi ama katman kötüleşti" gözlemi
    # ATFEDİLEMEZ — iki değişken aynı anda oynadı ve 2 kredi kontrolsüz bir
    # karşılaştırmaya gitti.
    #
    # §20.1'de aynı kural zaten yazılıydı ("AYNI TOHUM: yoksa iki kare hem
    # modelden hem difüzyonun rastgeleliğinden farklı çıkar") ama yalnızca
    # `tryon-ab`de vardı; asıl üretim komutunda yoktu.
    if args.seed is not None:
        if hasattr(provider, "seed"):
            provider.seed = args.seed
        else:
            print(f"⚠ '{provider.name}' tohum kabul etmiyor — --seed yok sayıldı.")

    print(f"Sağlayıcı: {provider.name}"
          + (f"  · tohum {args.seed}" if args.seed is not None else "")
          + ("  (sahte katman — FAL_KEY yok ya da fal-client kurulu değil)"
             if provider.name == "mock" else ""))

    if args.id:
        results = [layers.build_layer(args.id, provider=provider, force=args.force)]
    else:
        results = layers.build_all(
            provider=provider, force=args.force, category=args.category,
            exclude=args.exclude,
        )

    if not results:
        print("Dolap boş. Önce: python cli.py add <foto>")
        return 1

    icons = {"ready": "✓", "failed": "✗", "unsupported": "—"}
    for r in results:
        icon = icons.get(r["status"], "?")
        note = " (atlandı, zaten hazır)" if r.get("skipped") else ""
        line = f"  {icon} #{r['garment_id']:<3} {r['status']}{note}"
        if r.get("coverage") is not None:
            line += f"  kaplama %{r['coverage'] * 100:.1f}"
        print(line)
        if r.get("error"):
            print(f"      {r['error']}")
        for w in r.get("warnings", []):
            print(f"      ⚠ {w}")

    counts = layers.status_counts()
    print(f"\nDurum: {counts}")
    if counts.get("unsupported"):
        print("Not: ayakkabı ve aksesuar için sanal deneme modeli yok — "
              "bu bilinen bir sınır (bkz. README).")
    return 0 if counts.get("ready") else 1


def cmd_preview(args) -> int:
    init_db()
    image = layers.compose(args.ids)
    out = Path(args.output)
    image.convert("RGB").save(out)
    print(f"Kombin yazıldı: {out.resolve()}")
    print(f"   Kıyafetler: {', '.join('#' + str(i) for i in args.ids)}")
    return 0


def cmd_render(args) -> int:
    """Kombini zincirleme giydirir — Faz 4 (ÜCRETLİ)."""
    from wardrobe import render

    provider = vton.get_provider(args.provider)
    p = render.plan(args.ids, provider=provider)
    for atlanan in p["skipped"]:
        print(f"   ⚠  #{atlanan['id']} atlandı: {atlanan['neden']}")

    if render.cached(args.ids, provider_name=provider.name) and not args.force:
        print("Önbellekte var (ücret yok): "
              f"{render.cache_path(args.ids, provider_name=provider.name)}")
        return 0

    if p["calls"] == 0:
        print("Uygulanabilir kıyafet yok.")
        return 1

    print(f"Sağlayıcı: {provider.name} · {p['calls']} çağrı, tahmini ~${p['cost_usd']}.")
    sonuc = render.render_outfit(
        args.ids, provider=provider, force=args.force,
        progress=lambda i, n, gid: print(f"   [{i}/{n}] #{gid} giydiriliyor…"),
    )
    if sonuc["status"] == "failed":
        print(f"Başarısız: {sonuc['error']}")
        return 1

    print(f"Hazır: {sonuc['path']}")
    return 0


def cmd_tryon_ab(args) -> int:
    """Aynı kıyafeti farklı VTON ayarlarıyla üretip yan yana koyar — ÜCRETLİ.

    §16'daki #12 beyaz tişört sorununun kaynağı hipotez halinde duruyor:
    `segmentation_free` açıkken model yeni kıyafeti base'in tişörtünün ÜZERİNE
    harmanlıyor ve onun sınırlarını miras alıyor olabilir. Bunu ölçmenin tek
    yolu iki ayarı aynı girdiyle çalıştırıp bakmak.

    Çıktı katman olarak KAYDEDİLMİYOR, sadece karşılaştırma dosyası yazılıyor —
    yani dolabı bozmadan deneme yapılabiliyor.
    """
    from PIL import Image

    init_db()
    garment = get_garment(args.id)
    if not garment:
        print(f"#{args.id} bulunamadı.")
        return 1

    base_row = mannequin.ensure()
    ayarlar = [
        ("segfree=False", vton.FalProvider(segmentation_free=False, seed=args.seed)),
        ("segfree=True", vton.FalProvider(segmentation_free=True, seed=args.seed)),
    ]
    if args.gemini:
        ayarlar.append(("gemini", vton.GeminiEditProvider(seed=args.seed)))

    print(f"#{args.id} {garment['subcategory']} — {len(ayarlar)} ÜCRETLİ çağrı, "
          f"~${len(ayarlar) * 0.075:.2f}")

    # Onay varsayılan olarak İNTERAKTİF. --yes yalnızca betikten/otomasyondan
    # çalıştırmak için: stdin bağlı değilken input() EOF alıyor ve komut
    # "iptal" sanıp sessizce çıkıyordu.
    if not args.yes:
        try:
            cevap = input("Devam? [e/H] ").strip().lower()
        except EOFError:
            print("stdin yok — betikten çalıştırıyorsan --yes ekle.")
            return 1
        if cevap not in ("e", "evet", "y", "yes"):
            print("İptal edildi — çağrı yapılmadı.")
            return 1

    kareler = []
    for ad, provider in ayarlar:
        print(f"   {ad} çalışıyor…")
        try:
            img = provider.try_on(
                Path(base_row["image_path"]), Path(garment["cutout_path"]),
                garment["category"],
            )
        except Exception as exc:
            print(f"   ✗ {ad}: {type(exc).__name__}: {exc}")
            continue
        yol = Path(f"ab_{args.id}_{ad.replace('=', '').replace(' ', '')}.png")
        img.save(yol, "PNG")
        kareler.append((ad, img))
        print(f"   ✓ {ad} → {yol}")

    if len(kareler) < 2:
        return 1

    en, boy = kareler[0][1].size
    olcek = 700 / boy
    kucuk = [(ad, im.resize((int(en * olcek), 700), Image.LANCZOS))
             for ad, im in kareler]
    tuval = Image.new("RGB", (sum(im.width for _, im in kucuk), 700), "white")
    x = 0
    for _, im in kucuk:
        tuval.paste(im, (x, 0))
        x += im.width
    out = Path(f"ab_{args.id}_karsilastirma.png")
    tuval.save(out)
    print(f"\nYan yana: {out.resolve()}")
    print("Sıra: " + " | ".join(ad for ad, _ in kucuk))
    print("\nKazananı vton.FASHN_SEGMENTATION_FREE'ye yaz, sonra:")
    print("   python cli.py build-layers --id %d --force" % args.id)
    return 0


def cmd_layer_ab(args) -> int:
    """"Daha iyi model katman mimarisini kurtarır mı?" — ÖLÇER. (ÜCRETLİ)

    Soru şu: mavi çizgilerin sebebi modelin kıyafet dışını bozması mı, yoksa
    fark tabanlı çıkarımın kendisi mi?

    İkisi farklı şeyler ve ölçüm ikisini ayırıyor. Aynı kıyafet iki modelle
    giydiriliyor, ikisinden de AYNI boru hattıyla katman çıkarılıyor ve şu
    ölçülüyor:

      · SIZINTI  — katman pikselinin, aynı koordinattaki base pikseliyle
        neredeyse aynı olduğu piksel sayısı (yani base sızmış)
      · DIŞ FARK — kıyafet bölgesinin DIŞINDA modelin değiştirdiği piksel
        oranı. Asıl ayrım burada: model kıyafet dışını hiç kurcalamıyorsa bu
        sayı sıfıra yakın olur ve mimarinin suçu kalmaz.

    Yani "model mi suçlu, mimari mi" sorusunu sayıyla cevaplıyor.
    """
    import numpy as np
    from PIL import Image

    from wardrobe.imageutil import load_any, rgb_distance
    from wardrobe.layers import (
        base_clothing_palette, extract_layer, layer_coverage,
    )

    init_db()
    garment = get_garment(args.id)
    if not garment:
        print(f"#{args.id} bulunamadı.")
        return 1

    base_row = mannequin.ensure()
    base_img = load_any(base_row["image_path"]).convert("RGB")
    base_arr = np.asarray(base_img).astype(np.float32)
    base_pal = base_clothing_palette(np.asarray(base_img))

    # AYNI TOHUM: yoksa iki kare hem modelden hem difüzyonun rastgeleliğinden
    # farklı çıkar ve farkın hangisinden geldiği ayrılamaz.
    adaylar = [
        ("fal/v1.6 (mevcut)", vton.FalProvider(seed=args.seed)),
        ("fashn/tryon-max", vton.FashnProvider(
            model_name="tryon-max", resolution=args.resolution,
            generation_mode=args.mode, seed=args.seed, allow_layers=True)),
    ]
    eksik = [ad for ad, p in adaylar if not p.available()]
    if eksik:
        print(f"Sağlayıcı hazır değil: {', '.join(eksik)}")
        print("   FASHN için .env'e FASHN_API_KEY ekle (bkz. python cli.py doctor)")
        return 1

    print(f"#{args.id} {garment['subcategory']} — {len(adaylar)} ÜCRETLİ çağrı")
    if not args.yes:
        try:
            if input("Devam? [e/H] ").strip().lower() not in ("e", "evet", "y", "yes"):
                print("İptal edildi — çağrı yapılmadı.")
                return 1
        except EOFError:
            print("stdin yok — betikten çalıştırıyorsan --yes ekle.")
            return 1

    print(f"\n{'model':<20} {'kaplama':>9} {'sızıntı px':>11} {'dış fark':>9}")
    print("-" * 54)

    for ad, provider in adaylar:
        try:
            dressed = provider.try_on(
                Path(base_row["image_path"]), Path(garment["cutout_path"]),
                garment["category"],
            )
        except Exception as exc:
            print(f"{ad:<20} ✗ {type(exc).__name__}: {exc}")
            continue

        if dressed.size != base_img.size:
            dressed = dressed.resize(base_img.size, Image.LANCZOS)
        etiket = ad.split("/")[0]
        dressed.save(f"layerab_{args.id}_{etiket}_ham.png", "PNG")

        layer = extract_layer(base_img, dressed, category=garment["category"],
                              cutout_path=garment["cutout_path"] or None)
        layer.save(f"layerab_{args.id}_{etiket}_katman.png", "PNG")

        arr = np.asarray(layer.convert("RGBA"))
        opak = arr[..., 3] > 128
        sizinti = 0
        if opak.any():
            px = arr[..., :3][opak].astype(np.float32)
            sizinti = int((rgb_distance(px, base_arr[opak]) < 25).sum())

        # Kıyafet bölgesinin DIŞINDA model ne kadarını değiştirmiş?
        # Mimarinin suçu mu, modelin suçu mu — ayrım tam burada.
        degisen = rgb_distance(np.asarray(dressed.convert("RGB")), base_arr) > 18
        dis_fark = float((degisen & ~opak).mean())

        print(f"{ad:<20} {layer_coverage(layer) * 100:8.1f}% {sizinti:11d} "
              f"{dis_fark * 100:8.2f}%")

    print("\nDosyalar: layerab_%d_*_ham.png (giydirilmiş) ve _katman.png" % args.id)
    print("\nOkuma kılavuzu:")
    print("  · 'dış fark' düşük + sızıntı düşük  → model iyi, KATMAN MİMARİSİ YAŞAR")
    print("  · 'dış fark' düşük ama sızıntı yüksek → suç mimaride, model değiştirmek çözmez")
    print("  · ikisi de yüksek                    → model kıyafet dışını kurcalıyor")
    return 0


def cmd_web(args) -> int:
    """Giydirme arayüzünü başlatır (Faz 2)."""
    try:
        from web.app import run
    except ImportError:
        print("FastAPI kurulu değil:  pip install -r requirements.txt")
        return 1

    from wardrobe.layers import status_counts

    hazir = status_counts().get("ready", 0)
    if hazir == 0:
        print("⚠  Hazır katman yok — arayüz boş görünecek.")
        print("   Önce: python cli.py build-layers")
    else:
        print(f"{hazir} katman hazır.")

    print(f"Arayüz: http://{args.host}:{args.port}   (durdurmak için Ctrl+C)")
    run(host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="AI Sanal Dolap — Faz 0 (dolap altyapısı)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="veritabanını kur").set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="tek kıyafet ekle")
    p_add.add_argument("path", help="kıyafet fotoğrafı")
    p_add.add_argument("--no-vlm", action="store_true",
                       help="VLM çağırma, yedek çıkarımı kullan")
    p_add.add_argument("--cutout", choices=CUTOUT_METHODS,
                       help="kırpma yöntemi (varsayılan: auto)")
    p_add.set_defaults(func=cmd_add)

    p_folder = sub.add_parser("add-folder", help="klasördeki tüm görselleri ekle")
    p_folder.add_argument("folder")
    p_folder.add_argument("--no-vlm", action="store_true")
    p_folder.add_argument("--cutout", choices=CUTOUT_METHODS)
    p_folder.set_defaults(func=cmd_add_folder)

    p_list = sub.add_parser("list", help="dolabı listele")
    p_list.add_argument("--category", choices=CATEGORY_KEYS)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="tek kıyafetin detayı")
    p_show.add_argument("id", type=int)
    p_show.set_defaults(func=cmd_show)

    p_rm = sub.add_parser("rm", help="kıyafeti sil")
    p_rm.add_argument("id", type=int)
    p_rm.set_defaults(func=cmd_rm)

    sub.add_parser("stats", help="özet").set_defaults(func=cmd_stats)
    sub.add_parser("doctor", help="kurulum ve anahtar kontrolü").set_defaults(
        func=cmd_doctor
    )

    p_man = sub.add_parser("mannequin", help="manken oluştur / listele / geç / sil")
    p_man.add_argument("--from-photo", help="kendi fotoğrafını manken yap")
    p_man.add_argument("--name", help="YENİ manken olarak ekle (mevcutlar korunur). "
                                      "Verilmezse aktif mankenin fotoğrafı değişir "
                                      "ve YALNIZCA onun katmanları geçersiz olur.")
    p_man.add_argument("--list", action="store_true", help="mankenleri listele")
    p_man.add_argument("--use", type=int, metavar="ID",
                       help="aktif mankeni değiştir (ÜCRETSİZ, hiçbir şey silmez)")
    p_man.add_argument("--rm", type=int, metavar="ID",
                       help="mankeni ve katmanlarını sil (GERİ ALINAMAZ)")
    p_man.add_argument("--yes", action="store_true",
                       help="silme onayını sorma (betikten çalıştırmak için)")
    p_man.add_argument("--placeholder", action="store_true",
                       help="çizilmiş basit figür kullan (bedava)")
    p_man.add_argument("--style", default=mannequin.DEFAULT_STYLE,
                       choices=tuple(mannequin.GENERATION_PROMPTS),
                       help="person: insan (önerilen) | mannequin: vitrin mankeni")
    p_man.set_defaults(func=cmd_mannequin)

    p_layers = sub.add_parser("build-layers", help="katmanları üret")
    p_layers.add_argument("--id", type=int, help="sadece bu kıyafet")
    p_layers.add_argument("--category", choices=CATEGORY_KEYS)
    p_layers.add_argument("--provider", choices=("fal", "fashn", "mock"),
                          help="fashn: tryon-max (ÖNERİLEN, §25) | "
                               "fal: v1.6 | varsayılan: anahtara göre")
    p_layers.add_argument("--exclude", type=int, nargs="+", metavar="ID",
                          help="bu kıyafetleri atla (ör: elden çıkarılanlar)")
    p_layers.add_argument("--seed", type=int,
                          help="difüzyon tohumu — bir değişikliğin etkisini "
                               "ölçmek için ŞART, yoksa fark modelden mi "
                               "rastgelelikten mi geldiği ayrılamaz")
    p_layers.add_argument("--force", action="store_true",
                          help="hazır katmanları da yeniden üret (ÜCRETLİ)")
    p_layers.add_argument("--reextract", action="store_true",
                          help="saklanmış ham çıktılardan yeniden çıkar (BEDAVA)")
    p_layers.set_defaults(func=cmd_build_layers)

    p_prev = sub.add_parser("preview", help="katmanları birleştirip PNG yaz")
    p_prev.add_argument("ids", type=int, nargs="+", help="kıyafet id'leri")
    p_prev.add_argument("-o", "--output", default="kombin.png")
    p_prev.set_defaults(func=cmd_preview)

    p_render = sub.add_parser(
        "render", help="kombini zincirleme giydir — gerçekçi (Faz 2, ÜCRETLİ)")
    p_render.add_argument("ids", type=int, nargs="+", help="kıyafet id'leri")
    p_render.add_argument("--force", action="store_true",
                          help="önbellektekini yok say, yeniden üret")
    p_render.add_argument("--provider",
                          choices=("fal", "fashn", "gemini", "mock"),
                          help="fashn: tryon-max (ayakkabı/takı dahil, 4K'ya "
                               "kadar) | fal: v1.6 | gemini: genel düzenleyici")
    p_render.set_defaults(func=cmd_render)

    p_ab = sub.add_parser(
        "tryon-ab", help="aynı kıyafeti farklı VTON ayarlarıyla üret (ÜCRETLİ)")
    p_ab.add_argument("id", type=int, help="kıyafet id")
    p_ab.add_argument("--seed", type=int,
                      help="difüzyon tohumu — ayarlar arası tek fark ayar olsun")
    p_ab.add_argument("--gemini", action="store_true",
                      help="karşılaştırmaya gemini düzenleyicisini de ekle")
    p_ab.add_argument("--yes", action="store_true",
                      help="ücret onayını sorma (betikten çalıştırmak için)")
    p_ab.set_defaults(func=cmd_tryon_ab)

    p_lab = sub.add_parser(
        "layer-ab",
        help="katman mimarisi daha iyi modelle kurtulur mu? — ölçer (ÜCRETLİ)")
    p_lab.add_argument("id", type=int, help="kıyafet id")
    p_lab.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    p_lab.add_argument("--mode", default="balanced",
                       choices=("fast", "balanced", "quality"))
    p_lab.add_argument("--seed", type=int, default=42)
    p_lab.add_argument("--yes", action="store_true")
    p_lab.set_defaults(func=cmd_layer_ab)

    p_web = sub.add_parser("web", help="giydirme arayüzünü başlat (Faz 2)")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8000)
    p_web.add_argument("--reload", action="store_true",
                       help="kod değişince sunucuyu yeniden başlat (geliştirme)")
    p_web.set_defaults(func=cmd_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
