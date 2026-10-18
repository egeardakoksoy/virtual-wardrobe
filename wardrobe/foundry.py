"""Microsoft Foundry yapılandırması — Claude ve görüntü modeli için tek kaynak.

NEDEN AYRI MODÜL: Foundry'yi iki ayrı yer kullanıyor — öznitelik çıkarımı
(Claude, `vision.py`) ve sanal deneme (görüntü modeli, `vton.py`). İkisi de
aynı kaynağa (resource) ve aynı API anahtarına bağlanıyor; ayar okumayı iki
yere dağıtmak, birinin güncellenip diğerinin unutulması demek.

Tek kaynak, tek anahtar; görüntü tarafında iki model ailesi:

    Claude          : https://{resource}.services.ai.azure.com/anthropic/v1/*
    Görsel analiz   : https://{resource}.openai.azure.com/openai/v1/chat/completions
    Görüntü (gpt)   : https://{resource}.openai.azure.com/openai/v1/*
    Görüntü (MAI)   : https://{resource}.services.ai.azure.com/mai/v1/images/*

Görsel analiz: Claude'a kota çıkmayan abonelikler için kıyafet okumayı
Foundry'deki herhangi bir görsel destekli sohbet modeline (gpt-4.1-mini,
gpt-5-mini, gpt-4o, Phi-4-multimodal ...) yaptırıyor — OpenAI uyumlu sohbet
arayüzü, aynı JSON şeması.

MAI, Microsoft'un kendi görüntü modelleri (MAI-Image-2.5 / 2.6). Ayrı bir API:
düzenleme multipart, 5 görsele kadar girdi, boyut alanı yok, yanıt base64 PNG.
Hangisinin kullanılacağı dağıtım adından anlaşılıyor (`image_api`).

Model adı her yerde DAĞITIM adı (deployment name), model kimliği değil.
Foundry portalında dağıtım oluşturulurken verilen ad bu; varsayılanı model
kimliğiyle aynı ama değiştirilebiliyor.

Parçalar birbirinden bağımsız açılıyor: yalnızca Claude dağıtımı tanımlıysa
öznitelik çıkarımı Foundry'den gelir, sanal deneme başka sağlayıcıda kalır —
ya da tersi. Hiçbiri tanımlı değilse bu modül hiçbir şeyi değiştirmiyor.
"""
from __future__ import annotations

from wardrobe import secrets

# gpt-image ailesinin TAMAMININ desteklediği tek dikey boyut. 2:3 oranı
# mankenin tuvaliyle (864x1296) birebir aynı, yani geri ölçeklerken bozulma
# yok. gpt-image-2 özel boyut da kabul ediyor ama 1.x modelleri etmiyor;
# hangisinin dağıtıldığını bilmediğimiz için varsayılan ortak payda.
DEFAULT_IMAGE_SIZE = "1024x1536"

# Katman kıyafet başına BİR KEZ üretiliyor; kalitede cimrilik yanlış takas
# (FASHN için de aynı karar verilmişti, bkz. FalProvider).
DEFAULT_IMAGE_QUALITY = "high"

# MAI üretim (generations) sınırları — Microsoft'un belgesi, Ekim 2026: her
# kenar en az 768 px; toplam piksel MAI-Image-2.5'te 1024x1024'ü, 2.6'da
# 1536x1536'yı geçemez. Hangi sürümün dağıtıldığını bilmediğimiz için ortak
# payda (2.5'in sınırı) kullanılıyor; çıktı zaten istenen boyuta ölçekleniyor.
MAI_MIN_KENAR = 768
MAI_MAX_PIKSEL = 1024 * 1024


def resource() -> str | None:
    return secrets.get("FOUNDRY_RESOURCE")


def api_key() -> str | None:
    return secrets.get("FOUNDRY_API_KEY")


def _baglanti_var() -> bool:
    return bool(resource() and api_key())


# --- Claude ---

def claude_deployment() -> str | None:
    return secrets.get("FOUNDRY_CLAUDE_DEPLOYMENT")


def claude_translate_deployment() -> str | None:
    """Düzenleme talimatı çevirisi için dağıtım — yoksa ana Claude dağıtımı.

    Ayrı bir dağıtım zorunlu değil: tek bir Claude dağıtımı her iki işi de
    yapabiliyor. Ayrı tanımlanırsa (örn. daha küçük bir model) o kullanılır.
    """
    return secrets.get("FOUNDRY_CLAUDE_TRANSLATE_DEPLOYMENT") or claude_deployment()


def claude_ready() -> bool:
    return _baglanti_var() and bool(claude_deployment())


# --- Görsel analiz (Claude yerine, OpenAI uyumlu sohbet modeli) ---

def vision_deployment() -> str | None:
    return secrets.get("FOUNDRY_VISION_DEPLOYMENT")


def vision_ready() -> bool:
    return _baglanti_var() and bool(vision_deployment())


# --- Görüntü modeli ---

def image_deployment() -> str | None:
    return secrets.get("FOUNDRY_IMAGE_DEPLOYMENT")


def image_ready() -> bool:
    return _baglanti_var() and bool(image_deployment())


def image_size() -> str:
    return secrets.get("FOUNDRY_IMAGE_SIZE") or DEFAULT_IMAGE_SIZE


def image_quality() -> str:
    return secrets.get("FOUNDRY_IMAGE_QUALITY") or DEFAULT_IMAGE_QUALITY


def openai_base_url() -> str | None:
    """Görüntü uç noktası — Azure OpenAI v1 rotası, istenirse elle ezilebilir.

    Ezme seçeneği bilerek var: v1 rotası Microsoft'un önerdiği güncel yol, ama
    bölgeye ya da kaynak türüne göre farklı bir ana makine gerekebiliyor.
    Kod değiştirmeden düzeltilebilsin diye.
    """
    ezme = secrets.get("FOUNDRY_OPENAI_BASE_URL")
    if ezme:
        return ezme if ezme.endswith("/") else ezme + "/"
    r = resource()
    return f"https://{r}.openai.azure.com/openai/v1/" if r else None


def openai_api_version() -> str | None:
    """İsteğe bağlı `api-version` sorgu parametresi.

    GA v1 rotası bunu istemiyor; önizleme özellikleri için "preview"
    gerekebiliyor. Tanımlı değilse hiç gönderilmiyor.
    """
    return secrets.get("FOUNDRY_OPENAI_API_VERSION")


def image_api() -> str:
    """Görüntü dağıtımının konuştuğu API: "mai" ya da "openai".

    Varsayılan dağıtım adından: Foundry'de dağıtım adının varsayılanı model
    kimliği ("MAI-Image-2.6-Flash"), yani çoğu kurulumda ayar gerekmiyor.
    Dağıtıma başka bir ad verildiyse FOUNDRY_IMAGE_API ile açıkça söylenir.
    """
    acik = (secrets.get("FOUNDRY_IMAGE_API") or "").strip().lower()
    if acik in ("mai", "openai"):
        return acik
    return ("mai" if (image_deployment() or "").lower().startswith("mai-image")
            else "openai")


def mai_base_url() -> str | None:
    r = resource()
    return f"https://{r}.services.ai.azure.com" if r else None


def mai_auto_aspect() -> bool:
    """MAI düzenlemesinde `auto_aspect_ratio` gönderilsin mi?

    Düzenleme API'sinde boyut alanı yok. Bu bayrak kapalıyken model "varsayılan
    en-boy oranını" kullanıyor; açıkken oranı girdilere bakarak kendisi seçiyor
    — 2:3 boy fotoğrafını koruması için açık olanı daha olası. Yalnızca 2.6
    ailesi kabul ediyor (2.5'e gönderilirse 400), o yüzden varsayılan dağıtım
    adında "2.6" geçiyorsa açık. ÖLÇÜLMEDİ — FOUNDRY_MAI_AUTO_ASPECT ile
    açılıp kapatılabiliyor.
    """
    deger = (secrets.get("FOUNDRY_MAI_AUTO_ASPECT") or "").strip().lower()
    if deger in ("true", "1", "yes", "evet"):
        return True
    if deger in ("false", "0", "no", "hayir", "hayır"):
        return False
    return "2.6" in (image_deployment() or "")


def summary() -> dict:
    """`doctor` için durum — SIR İÇERMEZ (anahtarın kendisi yok)."""
    return {
        "resource": resource(),
        "key_present": bool(api_key()),
        "claude_deployment": claude_deployment(),
        "claude_ready": claude_ready(),
        "vision_deployment": vision_deployment(),
        "vision_ready": vision_ready(),
        "image_deployment": image_deployment(),
        "image_ready": image_ready(),
        "image_api": image_api(),
        "image_size": image_size(),
        "image_quality": image_quality(),
        "openai_base_url": openai_base_url(),
        "mai_base_url": mai_base_url(),
        "mai_auto_aspect": mai_auto_aspect(),
    }
