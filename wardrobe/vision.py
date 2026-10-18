"""Kıyafet öznitelik çıkarımı — Claude vision + yapılandırılmış JSON çıktı.

Claude'a erişilemeyen Foundry aboneliklerinde aynı iş, aynı şemayla
Foundry'deki görsel destekli bir sohbet modeline yaptırılabiliyor
(FOUNDRY_VISION_DEPLOYMENT; bkz. `_foundry_sohbet`).

Tasarım kararları:
- Model tek bir sabitte (MODEL). Opus 5, görsel akıl yürütmede en iyisi.
- `output_config.format` ile JSON şeması dayatılır: model serbest metin değil,
  şemaya uyan JSON üretmek zorunda. Regex ile ayrıştırma yok.
- `effort: "low"` — bu basit bir çıkarım görevi, derin akıl yürütme gerekmiyor.
  Yüz kıyafetlik bir dolapta maliyet farkı ciddi.
- ANAHTAR YOKSA ÇÖKMEZ: görüntüden gerçek baskın rengi çıkaran ve dosya adından
  kategori tahmin eden bir "mock" döner (source="mock"). Yani anahtarsız da
  tüm hat uçtan uca çalışır ve testler API'siz koşar.

Sayısal kısıtlar (minimum/maximum) yapılandırılmış çıktı şemasında desteklenmiyor;
warmth/formality istemci tarafında 0-10'a kırpılıyor (bkz. _normalize).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from config import CATEGORY_KEYS, PATTERNS, SEASONS, STYLES
from wardrobe.imageutil import (
    dominant_color,
    downscale,
    load_any,
    load_upright,
    to_base64_jpeg,
    to_hex,
)

MODEL = "claude-opus-5"
MAX_TOKENS = 16000

SYSTEM_PROMPT = (
    "Sen bir moda kataloğu için kıyafet etiketleyen uzmansın. Sana tek bir "
    "kıyafetin fotoğrafı verilir; onu yapılandırılmış özniteliklere çevirirsin. "
    "Sadece görselde gerçekten gördüğünü yaz, tahmin uydurma. Türkçe terimler kullan."
)

USER_PROMPT = (
    "Bu fotoğraftaki kıyafeti etiketle.\n\n"
    "Alan notları:\n"
    "- category: kıyafetin vücutta kapladığı bölgeye göre seç. Elbise/tulum "
    "hem üst hem alt kapladığı için 'elbise'dir. Mont/ceket/hırka 'dis_giyim'.\n"
    "- subcategory: serbest metin, spesifik ol (\"chino pantolon\", \"bisiklet yaka "
    "tişört\", \"kot ceket\").\n"
    "- color_hex: baskın rengin yaklaşık HEX kodu (#RRGGBB).\n"
    "- secondary_color_hex: belirgin ikinci renk varsa HEX, yoksa boş string.\n"
    "- warmth: 0 (çok ince, sıcak hava) - 10 (çok kalın, kış). Askılı atlet 1, "
    "tişört 3, gömlek 4, kazak 7, kaban 9 civarı.\n"
    "- formality: 0 (ev/spor) - 10 (smokin). Eşofman 1, tişört 2, kot 3, "
    "chino 5, gömlek 6, blazer 8 civarı.\n"
    "- notes: kombin kurarken işe yarayacak tek cümlelik not (kesim, yaka tipi, "
    "belirgin logo/desen)."
)

GARMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORY_KEYS)},
        "subcategory": {"type": "string"},
        "color_name": {"type": "string"},
        "color_hex": {"type": "string"},
        "secondary_color_hex": {"type": "string"},
        "pattern": {"type": "string", "enum": list(PATTERNS)},
        "style": {"type": "string", "enum": list(STYLES)},
        "seasons": {"type": "array", "items": {"type": "string", "enum": list(SEASONS)}},
        "fabric": {"type": "string"},
        "warmth": {"type": "integer"},
        "formality": {"type": "integer"},
        "notes": {"type": "string"},
    },
    "required": [
        "category", "subcategory", "color_name", "color_hex",
        "secondary_color_hex", "pattern", "style", "seasons", "fabric",
        "warmth", "formality", "notes",
    ],
    "additionalProperties": False,
}

# Mock yolunda HEX'i Türkçe renk adına çevirmek için küçük bir palet.
COLOR_NAMES: dict[str, tuple[int, int, int]] = {
    "siyah": (20, 20, 20), "beyaz": (245, 245, 245), "gri": (128, 128, 128),
    "lacivert": (25, 35, 80), "mavi": (40, 90, 190), "açık mavi": (140, 190, 230),
    "kırmızı": (200, 40, 45), "bordo": (110, 30, 45), "pembe": (235, 150, 180),
    "turuncu": (235, 130, 50), "sarı": (240, 215, 70), "yeşil": (60, 140, 80),
    "haki": (110, 115, 75), "kahverengi": (110, 75, 50), "bej": (215, 195, 165),
    "krem": (240, 230, 205), "mor": (120, 70, 160),
}

# Mock yolunda dosya adından kategori tahmini.
# SIRA ÖNEMLİ: dış giyim en başta, çünkü "kot ceket" hem "kot" (alt) hem
# "ceket" (dış giyim) içeriyor ve dış giyim doğru cevap. Genel kural: dıştaki
# katman içtekinden önce denenir.
_FILENAME_HINTS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("ceket", "mont", "kaban", "hirka", "hırka", "blazer", "trenc", "yelek",
      "parka", "kabani"), "dis_giyim", "dış giyim"),
    (("elbise", "tulum"), "elbise", "elbise"),
    (("ayakkabi", "ayakkabı", "sneaker", "bot", "cizme", "çizme", "sandalet",
      "terlik", "loafer"), "ayakkabi", "ayakkabı"),
    (("pantolon", "jean", "kot", "chino", "sort", "şort", "etek", "tayt",
      "esofman", "eşofman"), "alt", "alt"),
    (("tisort", "tshirt", "tişört", "atlet", "gomlek", "gömlek", "kazak",
      "sweat", "bluz", "body"), "ust", "üst"),
    (("sapka", "şapka", "kemer", "atki", "atkı", "canta", "çanta", "kolye",
      "eldiven", "gozluk", "gözlük"), "aksesuar", "aksesuar"),
)

# Kategoriye göre makul varsayılanlar (mock için).
_CATEGORY_DEFAULTS: dict[str, tuple[int, int, str]] = {
    #                    warmth, formality, fabric
    "ust":       (3, 3, "pamuk"),
    "alt":       (4, 4, "pamuk"),
    "elbise":    (3, 6, "viskon"),
    "dis_giyim": (7, 5, "karışım"),
    "ayakkabi":  (4, 3, "deri"),
    "aksesuar":  (2, 3, "karışım"),
}


def has_api_key() -> bool:
    """Öznitelik modeline erişim var mı — Claude (birinci taraf ya da Foundry)
    ya da Foundry'deki bir görsel analiz dağıtımı."""
    from wardrobe import foundry

    return (bool(os.environ.get("ANTHROPIC_API_KEY")) or foundry.claude_ready()
            or foundry.vision_ready())


def _claude_istemcisi():
    """Claude istemcisi: Foundry dağıtımı tanımlıysa `AnthropicFoundry`.

    Foundry açık bir tercih — kaynak, anahtar VE Claude dağıtım adı birlikte
    verilmedikçe devreye girmiyor. Böylece ikisi de tanımlıysa kim kazanır
    sorusu yok: dağıtım adını yazan kişi Foundry'yi seçmiş demektir.
    """
    import anthropic

    from wardrobe import foundry

    if foundry.claude_ready():
        return anthropic.AnthropicFoundry(
            api_key=foundry.api_key(), resource=foundry.resource()
        )
    return anthropic.Anthropic()


def active_label() -> str:
    """Hangi öznitelik kaynağının kullanılacağı — banner ve doctor için."""
    from wardrobe import foundry

    if foundry.claude_ready():
        return f"Claude @ Foundry ({foundry.claude_deployment()})"
    if foundry.vision_ready():
        return f"{foundry.vision_deployment()} @ Foundry (görsel analiz)"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return f"Claude ({MODEL})"
    return "MOCK (Claude anahtarı yok)"


# Kıyafet başına okuma ücreti (USD) — yalnızca arayüzün yükleme notu için.
# Foundry görsel analiz: gpt-4.1-mini ile ölçüldü, ~2.100 belirteç ≈ $0.001
# (§52.1). Claude: ~2.000 girdi + ~300 çıktı belirteci, Opus fiyatıyla ~$0.02
# (yukarı yuvarlanmış tahmin).
OKUMA_USD_FOUNDRY = 0.001
OKUMA_USD_CLAUDE = 0.02


def cost_usd_estimate() -> float:
    """Bir kıyafeti okumanın yaklaşık ücreti — `active_label` ile aynı sıra."""
    from wardrobe import foundry

    if foundry.claude_ready():
        return OKUMA_USD_CLAUDE
    if foundry.vision_ready():
        return OKUMA_USD_FOUNDRY
    if os.environ.get("ANTHROPIC_API_KEY"):
        return OKUMA_USD_CLAUDE
    return 0.0


# --- Foundry görsel analiz: Claude yerine OpenAI uyumlu bir sohbet modeli ---
#
# NEDEN: Claude'a kota çıkmayan Foundry aboneliklerinde (§50) kıyafet okuma da
# Foundry'de kalabilsin. gpt-4.1-mini, gpt-5-mini, gpt-4o, Phi-4-multimodal ...
# hepsi aynı arayüzü konuşuyor: /openai/v1/chat/completions, görsel data URL.

# Akıl yürüten modeller (gpt-5 ailesi) çıktı sınırının bir kısmını düşünmeye
# harcıyor; JSON'un kendisi ~300 belirteç. Cömert tutuldu — mini modellerde
# maliyet farkı önemsiz.
FOUNDRY_MAX_TOKENS = 4000

# JSON şeması desteği modele göre değişiyor: gpt ailesi şemayı uyguluyor, bazı
# modeller yalnızca JSON modu sunuyor, bazıları hiçbirini. Sırayla deneniyor;
# 400 yanıtı hangi alanı beğenmediğini söylüyor.
_YANIT_BICIMLERI = ("json_schema", "json_object", None)

# Şemayı uygulamayan modeller için alan listesi talimatın içinde de veriliyor.
_SEMA_NOTU = (
    "\n\nYanıtı yalnızca bu JSON şemasına uyan tek bir nesne olarak ver, "
    "başka metin yazma:\n" + json.dumps(GARMENT_SCHEMA, ensure_ascii=False)
)


def _yanit_bicimi(tur: str | None) -> dict | None:
    if tur == "json_schema":
        return {"type": "json_schema",
                "json_schema": {"name": "kiyafet", "schema": GARMENT_SCHEMA,
                                "strict": True}}
    if tur == "json_object":
        return {"type": "json_object"}
    return None


def _foundry_sohbet(messages: list, *, json_bekleniyor: bool, max_tokens: int) -> str:
    """Foundry'deki görsel analiz dağıtımına tek sohbet isteği; yanıt metni.

    Düz HTTP (httpx — anthropic'in bağımlılığı), openai paketi gerekmiyor.
    Model farkları istekten bir şey DÜŞÜRÜLEREK aşılıyor: JSON şeması → JSON
    modu → serbest metin; `max_completion_tokens` reddedilirse `max_tokens`.
    Başka her hata olduğu gibi yükseliyor — mesajında anahtar yok.
    """
    import httpx

    from wardrobe import foundry

    bicimler = list(_YANIT_BICIMLERI) if json_bekleniyor else [None]
    sinir_alani = "max_completion_tokens"
    surum = foundry.openai_api_version()
    for _ in range(6):
        govde = {"model": foundry.vision_deployment(), "messages": messages,
                 sinir_alani: max_tokens}
        bicim = _yanit_bicimi(bicimler[0])
        if bicim:
            govde["response_format"] = bicim
        yanit = httpx.post(
            f"{foundry.openai_base_url()}chat/completions",
            headers={"api-key": foundry.api_key() or ""},
            params={"api-version": surum} if surum else None,
            json=govde,
            timeout=120.0,
        )
        if yanit.status_code == 400:
            metin = yanit.text.lower()
            if "max_completion_tokens" in metin and sinir_alani != "max_tokens":
                sinir_alani = "max_tokens"
                continue
            if ("response_format" in metin or "json_schema" in metin) and len(bicimler) > 1:
                bicimler.pop(0)
                continue
        if yanit.status_code >= 400:
            raise RuntimeError(
                f"Foundry görsel analiz → HTTP {yanit.status_code}: {yanit.text[:300]}")
        return (yanit.json()["choices"][0]["message"].get("content") or "").strip()
    raise RuntimeError("Foundry görsel analiz: modelin kabul ettiği istek biçimi bulunamadı")


def _json_ayikla(metin: str) -> dict:
    """Yanıttaki JSON nesnesi. JSON modu olmayan modeller onu ```json ... ```
    içine sarabiliyor ya da önüne bir cümle ekleyebiliyor."""
    try:
        return json.loads(metin)
    except ValueError:
        bas, son = metin.find("{"), metin.rfind("}")
        if bas == -1 or son <= bas:
            raise
        return json.loads(metin[bas:son + 1])


def _foundry_oznitelikleri(image_path: str | Path) -> dict:
    img = downscale(load_upright(image_path))
    metin = _foundry_sohbet(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": USER_PROMPT + _SEMA_NOTU},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + to_base64_jpeg(img)}},
            ]},
        ],
        json_bekleniyor=True,
        max_tokens=FOUNDRY_MAX_TOKENS,
    )
    return _json_ayikla(metin)


# Düzenleme talimatlarını çevirmek için kullanılan model. Öznitelik
# çıkarımıyla aynı olmak zorunda değil: bu iş tek cümlelik bir çeviri, en
# küçük model yeterli ve gecikmeyi ~1 sn'de tutuyor.
TRANSLATE_MODEL = "claude-haiku-4-5-20251001"

TRANSLATE_SYSTEM = (
    "You translate short fashion photo-editing instructions into English. "
    "Output ONLY the translated instruction — no quotes, no explanation, no "
    "preamble. Keep it imperative and concise, in the style of "
    "'roll up the sleeves', 'tuck in the shirt', 'turn slightly to the left'. "
    "If the input is already English, return it unchanged."
)


def looks_english(text: str) -> bool:
    """Kaba bir "zaten İngilizce mi" kestirimi — çeviriye gerek var mı?

    Türkçeye özgü harfler en ucuz ve en güvenilir sinyal. Yanılırsa bedeli
    gereksiz bir çeviri çağrısı (~$0.0001), yanlış çeviri değil — çünkü model
    zaten "İngilizceyse aynen döndür" talimatı alıyor.
    """
    return not any(c in text.lower() for c in "çğıöşü")


def translate_prompt(text: str, *, model: str | None = None) -> str:
    """Türkçe düzenleme talimatını İngilizceye çevirir.

    NEDEN GEREKLİ: FASHN'ın dokümanındaki tüm prompt örnekleri İngilizce ve
    modelin Türkçe anlayıp anlamadığı bilinmiyor. Kullanıcının Türkçe yazıp
    sonucun sessizce kötüleşmesi, en kötü hata türü — çünkü çağrı ÜCRETLİ ve
    başarısızlık "model beceremedi" gibi görünüyor.

    ASLA FIRLATMAZ: anahtar yoksa, ağ giderse ya da cevap boşsa özgün metin
    dönüyor. Çeviri bir iyileştirme; onu zorunlu hale getirip hattı kırmak
    yanlış takas olurdu.
    """
    text = (text or "").strip()
    if not text or looks_english(text):
        return text
    if not has_api_key():
        return text

    from wardrobe import foundry

    if model is None and not foundry.claude_ready() and foundry.vision_ready():
        try:
            ceviri = _foundry_sohbet(
                [{"role": "system", "content": TRANSLATE_SYSTEM},
                 {"role": "user", "content": text}],
                json_bekleniyor=False, max_tokens=2000)
            return ceviri or text
        except Exception:
            return text

    try:
        if model is None:
            model = (foundry.claude_translate_deployment()
                     if foundry.claude_ready() else TRANSLATE_MODEL)
        resp = _claude_istemcisi().messages.create(
            model=model,
            max_tokens=300,
            system=TRANSLATE_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        ceviri = "".join(
            blok.text for blok in resp.content if getattr(blok, "type", "") == "text"
        ).strip()
        return ceviri or text
    except Exception:
        return text


def extract_attributes(
    image_path: str | Path,
    *,
    name_hint: str | None = None,
    model: str | None = None,
) -> dict:
    """Kıyafet fotoğrafından öznitelikleri çıkarır.

    Args:
        image_path: Analiz edilecek görsel (tercihen kırpılmış PNG).
        name_hint: Kullanıcının orijinal dosya adı. Dosyaları UUID ile
            sakladığımız için ("a3f9c2.png") ad bilgisi yolda kayboluyor;
            mock yolu kategori tahmininde bunu kullanıyor.

    Returns:
        GARMENT_SCHEMA alanları + "attr_source": "claude" | "foundry" | "mock".
    Anahtar yoksa ya da API hata verirse mock'a düşer; asla exception fırlatmaz.

    Sıra: Foundry'deki Claude → Foundry'deki görsel analiz dağıtımı →
    birinci taraf Claude → mock. Foundry açık bir tercih (dağıtım adı yazılmış).
    """
    if not has_api_key():
        return _mock_attributes(image_path, name_hint=name_hint)

    from wardrobe import foundry

    if model is None and not foundry.claude_ready() and foundry.vision_ready():
        try:
            attrs = _normalize(_foundry_oznitelikleri(image_path))
            attrs["attr_source"] = "foundry"
            return attrs
        except Exception as exc:  # ağ/API/ayrıştırma hatası -> hat kırılmaz
            return _mock_attributes(
                image_path, note=f"Foundry hatası: {exc}", name_hint=name_hint
            )

    try:
        # Foundry'de `model` alanı DAĞITIM adı ister, model kimliği değil.
        if model is None:
            model = foundry.claude_deployment() if foundry.claude_ready() else MODEL

        img = downscale(load_upright(image_path))
        client = _claude_istemcisi()
        resp = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": GARMENT_SCHEMA},
            },
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": to_base64_jpeg(img),
                        },
                    },
                    {"type": "text", "text": USER_PROMPT},
                ],
            }],
        )
        if resp.stop_reason == "refusal":
            return _mock_attributes(
                image_path, note="model isteği reddetti", name_hint=name_hint
            )

        text = next(b.text for b in resp.content if b.type == "text")
        attrs = _normalize(json.loads(text))
        attrs["attr_source"] = "claude"
        return attrs
    except Exception as exc:  # ağ/API/ayrıştırma hatası -> hat kırılmaz
        return _mock_attributes(
            image_path, note=f"API hatası: {exc}", name_hint=name_hint
        )


def _normalize(raw: dict) -> dict:
    """Şema dışı sapmaları temizler ve sayısal alanları 0-10'a kırpar."""
    out = dict(raw)
    if out.get("category") not in CATEGORY_KEYS:
        out["category"] = "ust"
    if out.get("pattern") not in PATTERNS:
        out["pattern"] = "düz"
    if out.get("style") not in STYLES:
        out["style"] = "gunluk"

    seasons = [s for s in out.get("seasons") or [] if s in SEASONS]
    out["seasons"] = seasons or list(SEASONS)

    for key in ("warmth", "formality"):
        try:
            out[key] = max(0, min(10, int(out.get(key, 5))))
        except (TypeError, ValueError):
            out[key] = 5

    for key in ("subcategory", "color_name", "color_hex",
                "secondary_color_hex", "fabric", "notes"):
        out[key] = str(out.get(key) or "").strip()
    return out


def nearest_color_name(rgb: tuple[int, int, int]) -> str:
    """RGB'yi paletteki en yakın Türkçe renk adına eşler."""
    return min(
        COLOR_NAMES,
        key=lambda name: sum((a - b) ** 2 for a, b in zip(rgb, COLOR_NAMES[name])),
    )


def _guess_from_filename(image_path: str | Path) -> tuple[str, str]:
    stem = Path(image_path).stem.lower()
    for keywords, category, label in _FILENAME_HINTS:
        if any(k in stem for k in keywords):
            return category, label
    return "ust", "üst"


def _mock_attributes(
    image_path: str | Path, note: str = "", name_hint: str | None = None
) -> dict:
    """Anahtar yokken kullanılan yedek (gerçek API çağrısı YAPILMAZ).

    Uydurma değil: renk gerçekten görüntüden çıkarılır, kategori dosya adından
    tahmin edilir, warmth/formality kategoriye göre makul varsayılanı alır.
    Böylece anahtarsız çalışan hat da anlamlı veri üretir.
    """
    img = load_any(image_path)   # alfa varsa korunur; renk arka plana kaymaz
    rgb = dominant_color(img)
    category, label = _guess_from_filename(name_hint or image_path)
    warmth, formality, fabric = _CATEGORY_DEFAULTS.get(category, (5, 5, "karışım"))

    suffix = f" ({note})" if note else ""
    return _normalize({
        "category": category,
        "subcategory": label,
        "color_name": nearest_color_name(rgb),
        "color_hex": to_hex(rgb),
        "secondary_color_hex": "",
        "pattern": "düz",
        "style": "gunluk",
        "seasons": list(SEASONS),
        "fabric": fabric,
        "warmth": warmth,
        "formality": formality,
        "notes": f"[MOCK] Renk görselden, kategori dosya adından çıkarıldı.{suffix}",
    }) | {"attr_source": "mock"}
