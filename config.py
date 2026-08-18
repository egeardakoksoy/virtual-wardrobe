"""Merkezi yapılandırma: yollar, kategori/katman tablosu, VLM ayarları.

Tüm modüller buradaki sabitleri kullanır; tek yerden değiştirilir.

Kategori tablosu sadece bir etiket listesi değil — projenin en kritik iki
kararını taşır:

  z    : katmanların üst üste binme sırası (küçük olan altta kalır)
  slots: kıyafetin vücutta kapladığı bölge(ler). Aynı slot'u kaplayan iki
         kıyafet aynı anda giyilemez; ikinci seçim birinciyi düşürür.
         Elbise hem "ust" hem "alt" kaplar — bu yüzden slot listesi, tek
         bir string değil.
"""
from __future__ import annotations

from pathlib import Path

# --- Yollar ---
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "wardrobe.db"

RAW_DIR = DATA_DIR / "raw"        # kullanıcının çektiği orijinal fotoğraf
CUTOUT_DIR = DATA_DIR / "cutout"  # arka planı temizlenmiş PNG (RGBA)
LAYER_DIR = DATA_DIR / "layers"   # Faz 1: manken üstüne giydirilmiş katman

for _d in (DATA_DIR, RAW_DIR, CUTOUT_DIR, LAYER_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Kategoriler, katman sırası ve vücut bölgeleri ---
CATEGORIES: dict[str, dict] = {
    "ayakkabi":  {"label": "Ayakkabı",   "z": 10, "slots": ("ayak",)},
    "alt":       {"label": "Alt giyim",  "z": 20, "slots": ("alt",)},
    "elbise":    {"label": "Elbise",     "z": 25, "slots": ("ust", "alt")},
    "ust":       {"label": "Üst giyim",  "z": 30, "slots": ("ust",)},
    "dis_giyim": {"label": "Dış giyim",  "z": 40, "slots": ("dis",)},
    "aksesuar":  {"label": "Aksesuar",   "z": 50, "slots": ("aksesuar",)},
}
CATEGORY_KEYS = tuple(CATEGORIES)

PATTERNS = ("düz", "çizgili", "kareli", "ekose", "çiçekli", "baskılı", "diğer")
STYLES = ("gunluk", "spor", "klasik", "resmi", "streetwear", "bohem")
SEASONS = ("ilkbahar", "yaz", "sonbahar", "kis")

# --- VLM (öznitelik çıkarımı) ---
# Telefon fotoğrafı 4000px+ gelebiliyor; kıyafet özniteliği için 1024px fazlasıyla
# yeterli. Küçültmek token maliyetini ~3-4 kat düşürüyor, doğruluğu düşürmüyor.
VLM_MAX_PX = 1024
VLM_JPEG_QUALITY = 88

# --- Arka plan temizleme (rembg yoksa kullanılan yedek) ---
FLOOD_WORK_PX = 256   # maske bu çözünürlükte hesaplanıp orijinale büyütülür
FLOOD_TOLERANCE = 42  # kenar rengine bu uzaklıktaki pikseller arka plan sayılır


def z_index(category: str) -> int:
    """Kategorinin katman sırası. Bilinmeyen kategori en üste konur."""
    return CATEGORIES.get(category, {}).get("z", 99)


def slots(category: str) -> tuple[str, ...]:
    """Kategorinin kapladığı vücut bölgeleri."""
    return CATEGORIES.get(category, {}).get("slots", ())


def conflicts(cat_a: str, cat_b: str) -> bool:
    """İki kategori aynı anda giyilebilir mi? (ortak slot varsa hayır)"""
    return bool(set(slots(cat_a)) & set(slots(cat_b)))
