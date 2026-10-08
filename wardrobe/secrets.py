"""Anahtar okuma ve maskeli raporlama.

Kural: anahtarın kendisi hiçbir zaman ekrana, log'a ya da hata mesajına
yazılmaz. `describe()` sadece "var mı, hangi biçimde, kaç karakter" bilgisini
döner — bu, yanlış anahtar/eksik anahtar teşhisi için yeterli, sızdırmak için
yetersiz.
"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# (ortam değişkeni, ne işe yarar, yoksa ne olur)
KNOWN_KEYS: tuple[tuple[str, str, str], ...] = (
    ("FAL_KEY", "Sanal deneme / katman üretimi (Faz 1)",
     "sahte katman üretilir"),
    # FASHN'ın KENDİ API'si. fal'ınkinden ayrı bir anahtar; ikisi birbirinin
    # yerine geçmiyor. Yalnızca bununla erişilebilen tryon-max, ayakkabı/takı/
    # çanta da giydiriyor ve 4K'ya çıkıyor (§24).
    ("FASHN_API_KEY", "FASHN doğrudan API — tryon-max (§24)",
     "fal üzerinden v1.6 kullanılır"),
    ("ANTHROPIC_API_KEY", "Kıyafet öznitelik çıkarımı (Faz 0)",
     "renk görselden, kategori dosya adından çıkarılır"),
    ("REPLICATE_API_TOKEN", "Alternatif sanal deneme sağlayıcısı",
     "kullanılmaz (opsiyonel)"),
    # Microsoft Foundry: tek anahtar hem Claude hem görüntü dağıtımlarına
    # erişiyor. Kaynak adı ve dağıtım adları sır değil — `doctor` onları ayrı
    # bir bölümde açık gösteriyor (bkz. wardrobe/foundry.py).
    ("FOUNDRY_API_KEY", "Microsoft Foundry — Claude + görüntü modeli",
     "Foundry kullanılmaz (opsiyonel)"),
)


def _raw(name: str) -> str:
    """Ham değer — teşhis için. Kırpılmamış hali lazım (bkz. describe)."""
    return os.environ.get(name) or ""


def get(name: str) -> str | None:
    value = _raw(name).strip()
    return value or None


def has(name: str) -> bool:
    return get(name) is not None


def mask(value: str) -> str:
    """Anahtarı teşhis edilebilir ama kullanılamaz hale getirir.

    Baş ve sondan birkaç karakter, aradaki her şey gizli. Doğru anahtarı
    yapıştırdığını anlamana yeter, kopyalayıp kullanmaya yetmez.
    """
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}{'*' * 8}{value[-4:]}"


def describe(name: str) -> dict:
    """Anahtarın durumunu sızdırmadan raporlar.

    Teşhis ham değer üzerinden yapılır: .env'e tırnakla ya da sondaki boşlukla
    yapıştırmak en sık görülen iki hata ve ikisi de "anahtar yanlış" gibi
    görünen bir 401 üretiyor.
    """
    raw = _raw(name)
    value = raw.strip()
    if not value:
        return {"name": name, "present": False}
    return {
        "name": name,
        "present": True,
        "masked": mask(value),
        "length": len(value),
        "looks_quoted": value[0] in "\"'" or value[-1] in "\"'",
        "has_whitespace": raw != value or " " in value,
    }
