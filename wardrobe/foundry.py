"""Microsoft Foundry yapılandırması — Claude ve görüntü modeli için tek kaynak.

NEDEN AYRI MODÜL: Foundry'yi iki ayrı yer kullanıyor — öznitelik çıkarımı
(Claude, `vision.py`) ve sanal deneme (görüntü modeli, `vton.py`). İkisi de
aynı kaynağa (resource) ve aynı API anahtarına bağlanıyor; ayar okumayı iki
yere dağıtmak, birinin güncellenip diğerinin unutulması demek.

Tek kaynak, tek anahtar, iki uç nokta:

    Claude  : https://{resource}.services.ai.azure.com/anthropic/v1/*
    Görüntü : https://{resource}.openai.azure.com/openai/v1/*

Model adı iki tarafta da DAĞITIM adı (deployment name), model kimliği değil.
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


def summary() -> dict:
    """`doctor` için durum — SIR İÇERMEZ (anahtarın kendisi yok)."""
    return {
        "resource": resource(),
        "key_present": bool(api_key()),
        "claude_deployment": claude_deployment(),
        "claude_ready": claude_ready(),
        "image_deployment": image_deployment(),
        "image_ready": image_ready(),
        "image_size": image_size(),
        "image_quality": image_quality(),
        "openai_base_url": openai_base_url(),
    }
