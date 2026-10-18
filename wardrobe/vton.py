"""Sanal deneme (VTON) — sağlayıcı-bağımsız katman üretimi.

Tek arayüz: `try_on(model_image, garment_image, category) -> PIL.Image`
Arkasında değiştirilebilir sağlayıcılar var:

  fal   — FASHN v1.6 (varsayılan). Şema fal'ın OpenAPI'sinden doğrulandı:
          zorunlu: model_image, garment_image
          category: tops | bottoms | one-pieces | auto
          garment_photo_type: auto | model | flat-lay  ← bizimkiler flat-lay
  mock  — anahtarsız yedek. Kıyafeti mankenin doğru bölgesine kabaca
          yapıştırır. Gerçekçi değil ama hattı uçtan uca test etmeye yeter.

Sağlayıcıyı değiştirmek tek satır (VTON_PROVIDER ortam değişkeni) — böylece
modelleri A/B karşılaştırmak kod değişikliği gerektirmiyor.

BİLİNEN SINIR: FASHN'ın category listesinde ayakkabı ve aksesuar yok. Bu
kategoriler `UNSUPPORTED_CATEGORIES` içinde ve katman üretimi onları atlıyor
(sessizce başarısız olmak yerine "desteklenmiyor" diye işaretleniyor).
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageFilter

from wardrobe import foundry, secrets
from wardrobe.imageutil import downscale, load_any

FAL_TRYON_ENDPOINT = "fal-ai/fashn/tryon/v1.6"
FAL_TEXT_TO_IMAGE_ENDPOINT = "fal-ai/flux/schnell"
FAL_EDIT_ENDPOINT = "fal-ai/gemini-25-flash-image/edit"

# FASHN'ın "kıyafeti mevcut kıyafeti bölütlemeden doğrudan giydir" anahtarı.
# Şemadan doğrulandı (fal OpenAPI, FashnTryonV16Input): varsayılanı True.
#
# ÖLÇÜLDÜ VE ETKİSİ YOK. Hipotez şuydu: açıkken model yeni kıyafeti mevcut
# olanın üzerine harmanlıyor ve onun sınırlarını miras alıyor olabilir; §16'daki
# "#12 fazla kısa render ediliyor" belirtisi buna uyuyordu. İki ayar aynı tohumla
# (42) yan yana üretildi (~$0.15):
#
#     iki çıktı arasındaki fark : medyan 0.00, ortalama 3.64,
#                                 eşiği (18) aşan piksel %3.5
#     etek ucu                  : ikisinde de y = 0.619
#     kaplama                   : %15.0 / %14.8
#
# Yani ayarın bu vakada ölçülebilir bir etkisi yok ve KUSUR İKİSİNDE DE AYNEN
# duruyor. Asıl sebep başka çıktı: kıyafetin fotoğrafı katlı çekilmiş (§20.1).
#
# Bu yüzden sağlayıcının kendi varsayılanına dönüldü. Etkisi ölçülmemiş bir
# sapmayı taşımak, sapmanın kendisinden daha kötü: sonraki her katman
# sağlayıcının test ettiği yapılandırmanın dışında üretilirdi. Alan yine de
# açıkça gönderiliyor — istek kendini anlatsın diye.
FASHN_SEGMENTATION_FREE = True

# Sonuç görseli inference uç noktasından (fal.run) BAŞKA bir alan adından
# iniyor ve ikisi bağımsız kırılabiliyor.
#
# Ölçtük: makinenin DNS'i bu CDN'leri çözemezken fal.run pekâlâ çalışıyordu.
# Sonuç: inference tamamlandı, ÜCRETLENDİ, sonra indirme patladı ve çıktı çöpe
# gitti. Üç çağrı böyle kayboldu.
#
# Bu yüzden para harcamadan ÖNCE indirme yoluna bakıyoruz: ücretli bir çağrının
# indirilemeyecek bir sonuç üretmesi, başarısızlık türlerinin en pahalısı.
#
# DİKKAT — hangi uç noktanın hangi CDN'i kullandığı ölçümle belirlendi.
# Önce "fal olduğuna göre fal.media'dır" diye yazdık; o kontrol geçti, çağrı
# gitti, indirme yine patladı — çünkü FASHN sonucu cdn.fashn.ai'dan veriyor.
# Buradaki her alan adı tahmin değil, gözlenmiş bir sonuç URL'sinden gelmeli.
#
# Uç nokta başına ayrı liste tutuyoruz: tek bir "hepsi çözülsün" listesi,
# ilgisiz bir CDN düştüğünde çalışan hattı gereksiz yere kilitler.
RESULT_HOSTS: dict[str, tuple[str, ...]] = {
    FAL_TRYON_ENDPOINT: ("cdn.fashn.ai",),
    FAL_TEXT_TO_IMAGE_ENDPOINT: ("v3.fal.media", "fal.media"),
    # FAL_EDIT_ENDPOINT BİLEREK YOK. Hangi CDN'den geldiği henüz GÖZLENMEDİ ve
    # yukarıdaki kural net: buraya tahminle alan adı yazılmaz — bir kez yazıldı
    # ("fal olduğuna göre fal.media'dır") ve tam olarak korunmak istenen parayı
    # yaktı. Bunun yerine bu uç nokta `sync_mode` ile çağrılıyor: sonuç yanıtın
    # içinde data URI olarak geliyor, hiçbir CDN'e dokunulmuyor. Yani kapı
    # eksik değil — gerekmiyor.
}

# Bizim kategorilerimiz → FASHN'ın category enum'u.
# dis_giyim "tops"a eşleniyor: FASHN'da ayrı bir dış giyim sınıfı yok, üst
# beden en yakın karşılık.
CATEGORY_MAP: dict[str, str] = {
    "ust": "tops",
    "dis_giyim": "tops",
    "alt": "bottoms",
    "elbise": "one-pieces",
}

# Sanal deneme modelleri bu kategoriler için eğitilmedi (VITON-HD / DressCode
# veri setlerinde sınıfları yok). Uydurmaya çalışmak bozuk katman üretiyor.
UNSUPPORTED_CATEGORIES = frozenset({"ayakkabi", "aksesuar"})


# Ücretli çağrının zaman aşımları (saniye).
#
# ⚠ VERİLMEZSE `subscribe` SONSUZA KADAR BEKLİYOR — fal_client'ın kendi
# belgesinde yazıyor: "If not set, waits indefinitely." Bu, arayüzde ölçülen
# bir arıza olarak ortaya çıktı: bir render işi fal'ın kuyruğunda takıldı,
# istemci 45 dakika bekledi, "Gerçekçi Göster" sonsuza kadar döndü ve
# kullanıcıya hiçbir şey söylenmedi. İş asla bitmediği için `except` bloğuna da
# düşmedi; yani hata TEŞHİS EDİLEBİLİR bile değildi.
#
# Değerler ölçülen sürelere göre: FASHN quality tek çağrıda 15-40 sn. 240 sn
# cömert bir tavan — normal bir çağrıyı asla kesmez, ama takılan bir işi
# süresiz bekletmez.
CALL_TIMEOUT = 240.0     # client_timeout: kuyruk + işlem, toplam
QUEUE_TIMEOUT = 120.0    # start_timeout: işleme BAŞLAYANA kadar geçen süre

# API'ye gönderilen görselin uzun kenarı. Gerekçesi FalProvider._image_ref'te.
VTON_MAX_PX = 1536


class ResultUnreachable(Exception):
    """Sonuç görseli indirilemiyor.

    Çağrıdan ÖNCE fırlatılırsa para harcanmadı. Çağrıdan SONRA fırlatılırsa
    inference ücretlendirildi ve mesaj sonucun URL'sini taşır — elle indirilip
    kurtarılabilsin diye.
    """


class UnsupportedCategory(Exception):
    """Kategori için sanal deneme modeli yok."""


class CallTimeout(Exception):
    """Ücretli çağrı zaman aşımına uğradı.

    Mesaj `request_id` taşır — çünkü zaman aşımı "iş çalışmadı" demek DEĞİL:
    fal tarafında tamamlanıp ücretlendirilmiş olabilir. Kimliği elde tutmak,
    §6.1 #9'daki dersin aynısı: ödenmiş bir sonucu geri alabilmenin tek yolu
    ona işaret eden bir tutamak saklamak.
    """


def _cagir(client, endpoint: str, arguments: dict) -> dict:
    """subscribe'ı zaman aşımıyla ve kimliği yakalayarak çağırır.

    Zaman aşımı olmadan `subscribe` süresiz bekliyor (bkz. CALL_TIMEOUT).
    Kimlik (`request_id`) `on_enqueue` ile yakalanıyor ki iş takılırsa ya da
    zaman aşarsa hata mesajı onu taşısın — sonuç fal'da duruyorsa elle
    indirilebilsin.
    """
    kimlik: list[str | None] = [None]

    try:
        return client.subscribe(
            endpoint,
            arguments=arguments,
            on_enqueue=lambda rid: kimlik.__setitem__(0, rid),
            start_timeout=QUEUE_TIMEOUT,
            client_timeout=CALL_TIMEOUT,
        )
    except Exception as exc:
        # Zaman aşımının tipi fal_client sürümüne göre değişiyor; mesaja
        # bakmak yerine "beklerken patladı" davranışını tek yerde topluyoruz.
        if "timeout" not in f"{type(exc).__name__} {exc}".lower():
            raise
        raise CallTimeout(
            f"çağrı {CALL_TIMEOUT:.0f} sn içinde tamamlanmadı "
            f"(request_id: {kimlik[0] or 'alınamadı'}). İş fal'da tamamlanıp "
            "ÜCRETLENDİRİLMİŞ olabilir — sonucu şuradan kontrol et: "
            f"https://fal.ai/dashboard/requests"
        ) from exc


class VtonProvider(Protocol):
    name: str
    # Manken üretebilir mi? Deneme yapabilmek görsel üretebilmek demek değil —
    # mock sağlayıcı kıyafet giydirebiliyor ama sıfırdan manken çizemiyor.
    supports_text_to_image: bool

    def available(self) -> bool: ...

    # Desteklenmeyen kategori artık sağlayıcıya sorulur, sabit bir listeye
    # değil: "ayakkabı yapılamaz" FASHN'ın sınırı, evrensel bir gerçek değil.
    # Genel amaçlı bir görüntü düzenleyici ayakkabıyı pekâlâ giydirebiliyor.
    def supports_category(self, category: str) -> bool: ...

    def try_on(
        self, model_image: Path, garment_image: Path, category: str
    ) -> Image.Image: ...

    def text_to_image(self, prompt: str, size: tuple[int, int]) -> Image.Image: ...

    # Çağrı başına yaklaşık ücret (USD) — arayüz düğmeye basmadan gösteriyor.
    # Kaynaklar ve yuvarlama kuralı: `FASHN_CREDIT_USD` bloğu.
    def cost_usd(self) -> float: ...


def to_fashn_category(category: str) -> str:
    if category in UNSUPPORTED_CATEGORIES:
        raise UnsupportedCategory(
            f"'{category}' için sanal deneme modeli yok "
            f"(desteklenen: {', '.join(sorted(CATEGORY_MAP))})"
        )
    return CATEGORY_MAP.get(category, "tops")


# --------------------------------------------------------------------------
# fal — FASHN v1.6
# --------------------------------------------------------------------------

class FalProvider:
    """fal.ai üzerinden FASHN v1.6.

    `mode` seçimi bilinçli: "quality", katman üretiminin tek seferlik olması
    sayesinde karşılanabilir bir maliyet — ve katman kalitesi sonraki her
    kombinde tekrar tekrar görüleceği için burada cimrilik etmek yanlış.
    """

    name = "fal"
    supports_text_to_image = True

    def __init__(
        self,
        mode: str = "quality",
        segmentation_free: bool | None = None,
        seed: int | None = None,
    ):
        self.mode = mode
        # None = modül varsayılanı. Açıkça verilmesi A/B ölçümü için.
        self.segmentation_free = (
            FASHN_SEGMENTATION_FREE if segmentation_free is None
            else segmentation_free
        )
        # Difüzyon stokastik: aynı girdi her çağrıda farklı çıktı veriyor.
        # Tohum verilmezse zayıf bir çıktıyı yeniden denemek de, iyi olanı geri
        # getirmek de mümkün olmuyor — §16'daki "tekrar dene" seçeneği bu yüzden
        # denenememişti. Tohum verilirse çağrı tekrarlanabilir hale geliyor.
        self.seed = seed

    def supports_category(self, category: str) -> bool:
        return category not in UNSUPPORTED_CATEGORIES

    def cost_usd(self) -> float:
        return FAL_TRYON_USD

    def available(self) -> bool:
        if not secrets.has("FAL_KEY"):
            return False
        try:
            import fal_client  # noqa: F401
            return True
        except ImportError:
            return False

    def _client(self):
        import fal_client
        # fal_client anahtarı ortamdan okur; .env'den yüklendiğinden emin ol.
        os.environ.setdefault("FAL_KEY", secrets.get("FAL_KEY") or "")
        return fal_client

    def _image_ref(self, path: Path) -> str:
        """Görseli API'ye geçirilebilir bir referansa çevirir.

        Önce fal'ın depolamasına yüklenir (küçük istek gövdesi, hızlı). Ama
        yükleme fal.media alan adına gidiyor ve inference uç noktasından
        (fal.run) AYRI çözümleniyor: ölçtük — fal.run çözülürken v3.fal.media
        DNS'te düşebiliyor ve tüm hat duruyor, oysa modelin kendisi ayakta.

        O yüzden yükleme başarısız olursa data URI'ye düşüyoruz: görsel isteğin
        içinde gider, depolama sunucusuna hiç dokunulmaz.

        KÜÇÜLTME — ölçülmüş bir arızadan sonra eklendi. Telefon fotoğraflarının
        kırpıkları 3840x5120 (20 MP) ve 3.8-9.1 MB geliyordu; data URI yoluna
        düşünce base64 bunu %34 daha şişiriyor, yani tek bir kıyafet için
        ~12 MB'lık istek gövdesi. Ölçüldü:

            #12  1.43 MB / 1200x1600  → çağrı normal sürede döndü
            #6   3.82 MB / 3840x5120  → iş kuyrukta ASILI KALDI
            #7   9.07 MB / 3840x5120  → en büyüğü

        Bunun hiçbir karşılığı yok: modelin çıktısı zaten 864x1296. 1536 uzun
        kenar, baskı ve doku detayını koruyup piksel sayısını ~8 kat düşürüyor.
        `downscale` yalnızca küçültüyor — base manken (864x1296) büyütülmüyor.
        (Aynı gerekçe VLM yolunda da var: config.VLM_MAX_PX.)
        """
        client = self._client()
        img = downscale(load_any(path), VTON_MAX_PX)

        # PNG şart: kırpıkların alfası "kıyafet nerede" bilgisini taşıyor ve
        # JPEG alfayı düşürür. fal_client'ın varsayılanı jpeg, o yüzden açıkça.
        try:
            return client.upload_image(img, format="png")
        except Exception:
            return client.encode_image(img, format="png")

    def try_on(
        self, model_image: Path, garment_image: Path, category: str
    ) -> Image.Image:
        fal_category = to_fashn_category(category)
        # Para harcamadan önce indirme yolunu doğrula.
        require_media_host(FAL_TRYON_ENDPOINT)
        client = self._client()

        arguments = {
            "model_image": self._image_ref(model_image),
            "garment_image": self._image_ref(garment_image),
            "category": fal_category,
            # Cutout hattımız serili (flat-lay) görsel üretiyor. "auto"ya
            # bırakmak bazen "model" sanıp yanlış hizalıyor.
            "garment_photo_type": "flat-lay",
            "mode": self.mode,
            "output_format": "png",
            "num_samples": 1,
            # Base'in kendi kıyafetini önce bölütle, üstüne harmanlama
            # (bkz. FASHN_SEGMENTATION_FREE).
            "segmentation_free": self.segmentation_free,
        }
        if self.seed is not None:
            arguments["seed"] = self.seed

        result = _cagir(client, FAL_TRYON_ENDPOINT, arguments)
        return _download_image(result["images"][0]["url"])

    def text_to_image(self, prompt: str, size: tuple[int, int]) -> Image.Image:
        # Para harcamadan önce indirme yolunu doğrula.
        require_media_host(FAL_TEXT_TO_IMAGE_ENDPOINT)
        client = self._client()
        result = _cagir(
            client,
            FAL_TEXT_TO_IMAGE_ENDPOINT,
            {
                "prompt": prompt,
                "image_size": {"width": size[0], "height": size[1]},
                "num_images": 1,
                # PNG şart: varsayılan JPEG. Sıkıştırma artefaktları base
                # mankene gürültü ekliyor ve katman çıkarımı fark tabanlı
                # olduğu için o gürültü doğrudan katmana sızıyor.
                "output_format": "png",
            },
        )
        return _download_image(result["images"][0]["url"])


def media_host_resolves(hosts: tuple[str, ...]) -> bool:
    """Verilen sonuç sunucularından en az biri DNS'te çözülüyor mu?

    "En az biri" doğru ölçüt çünkü aynı uç noktanın alternatif CDN'leri
    birbirinin yedeği; farklı uç noktalarınki değil (bkz. RESULT_HOSTS).
    """
    import socket

    for host in hosts:
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            continue
    return False


def require_media_host(endpoint: str) -> None:
    """Ücretli çağrı öncesi kapı: sonucu indiremeyeceksek hiç isteme."""
    hosts = RESULT_HOSTS.get(endpoint, ())
    if not hosts or media_host_resolves(hosts):
        return
    raise ResultUnreachable(
        f"sonuç sunucusu ({' / '.join(hosts)}) DNS'te çözülemiyor — sonuç "
        "görseli indirilemez. İstek GÖNDERİLMEDİ; gönderilseydi inference "
        "ücretlendirilir ve çıktı kaybolurdu. Bu makinenin DNS'i bu alan adını "
        "çözemiyor (8.8.8.8 ve 1.1.1.1 çözüyor) — DNS sunucusunu değiştirmek "
        "sorunu gideriyor."
    )


def _download_image(url: str, attempts: int = 3) -> Image.Image:
    """Sonucu indirir. Geçici ağ hatalarında yeniden dener.

    Buraya gelindiyse inference ÇALIŞTI ve ücretlendirildi. O yüzden pes
    ederken URL'yi hata mesajına koyuyoruz: çıktı hâlâ fal'da duruyor ve elle
    indirilebilir — para tamamen boşa gitmesin.
    """
    import time
    import urllib.error
    import urllib.request

    # sync_mode ile çağrılan uç noktalar sonucu yanıtın İÇİNDE data URI olarak
    # veriyor. O durumda indirilecek bir şey yok — ve bu, §6.1 #9'daki en pahalı
    # başarısızlığın (ücret ödendi, sonuç inemedi) tamamen dışında kalmak demek.
    if url.startswith("data:"):
        import base64
        _, _, veri = url.partition(",")
        return Image.open(io.BytesIO(base64.b64decode(veri))).convert("RGB")

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                return Image.open(io.BytesIO(resp.read())).convert("RGB")
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)

    raise ResultUnreachable(
        f"sonuç indirilemedi ({type(last).__name__}: {last}) — "
        f"inference ücretlendirildi, çıktı şu adreste: {url}"
    )


# --------------------------------------------------------------------------
# fashn — FASHN'ın KENDİ API'si (fal aracısı olmadan)
# --------------------------------------------------------------------------

FASHN_API_BASE = "https://api.fashn.ai/v1"

# FASHN'ın kendi uç noktaları. `tryon-max` FASHN'ın önerdiği model ve fal
# üzerinden erişilebilen v1.6'da OLMAYAN şeyler getiriyor:
#
#   · 4K'ya kadar çözünürlük (v1.6 girdiyi 864x1296'ya sabitliyor)
#   · AYAKKABI, ŞAPKA, TAKI, ÇANTA desteği — §10'daki sınırımızı kaldırıyor
#   · prompt ile düzeltme ("tuck in shirt", "roll up sleeves")
#
# Kategori parametresi YOK: tryon-max ürünü kendisi sınıflandırıyor.
FASHN_MODELS = ("tryon-max", "tryon-v1.6")
FASHN_DEFAULT_MODEL = "tryon-max"

# Giydirmeye eklenen sabit talimat — ÖLÇÜMLE eklendi.
#
# Sorun: flat-lay çekiminde tişörtün ARKA YAKASI öne kıvrılıyor ve ense
# etiketi fotoğrafın parçası oluyor. Model uydurmuyor, gördüğünü çiziyor —
# sonuç, boynunda "FENERIUM"/"ALLSAINTS" etiketi olan bir tişört.
#
# Ölçüldü (#10 sarı tişört, aynı base, aynı tohum 42, tek değişken prompt):
# etiket ve lacivert iç yaka TAMAMEN kayboldu, kıyafetin geri kalanı aynı.
#
# Kök sebep yine de fotoğrafta (§10'un yaka için genişlemiş hali); bu prompt
# semptomu kapatıyor, sebebi değil. Ama bedava ve ölçülmüş bir iyileştirme,
# yeniden çekim gerektirmiyor.
FASHN_TRYON_PROMPT = (
    "the garment's inner neck label and inner collar must not be visible; "
    "the collar sits flat and shows only its outer side"
)

# Kredi maliyeti (dokümandan): generation_mode x resolution.
FASHN_CREDITS = {
    ("fast", "1k"): 1, ("fast", "2k"): 2, ("fast", "4k"): 3,
    ("balanced", "1k"): 2, ("balanced", "2k"): 3, ("balanced", "4k"): 4,
    ("quality", "1k"): 3, ("quality", "2k"): 4, ("quality", "4k"): 5,
}

# --- Çağrı başına yaklaşık ücret (USD) — `cost_usd()` (§54) ---
#
# Kesin fatura değil; amaç düğmeye basmadan doğru büyüklüğü göstermek. Şüphede
# YUKARI yuvarlanıyor: olduğundan ucuz göstermek pahalı göstermekten kötü.
#
# FASHN (help.fashn.ai, API fiyatı, Ekim 2026): talep üzerine KREDİ başına
#   $0.075. tryon-max ve düzenleme balanced+1k = 2 kredi → çağrı $0.15.
#   ⚠ Arayüz eskiden çağrı başına $0.075 gösteriyordu — fal'daki v1.6'nın
#   fiyatı, tryon-max'in yarısı.
# MAI-Image-2.6 (Microsoft, belirteç fiyatı): görsel çıktı $38/M, görsel girdi
#   $8/M, metin $5/M. ~1 MP çıktı ≈ 1.024 belirteç ≈ $0.039 (üçüncü taraf
#   tahminleriyle aynı). Giydirmede İKİ görsel de giriyor; girdi belirteci
#   belgelenmemiş → $0.06'ya yuvarlandı. Flash'ın belirteç fiyatı yarı → $0.03.
#   Kesin rakam Azure Cost Management'ta (fatura ~1 gün gecikmeli).
# gpt-image: high + 1024x1536 liste fiyatı $0.25 (gpt-image-1); gpt-image-2
#   için doğrulanmadı, bu yol zaten ölçülmedi.
# fal: FASHN v1.6 çağrı $0.075; Gemini düzenleme ~$0.04 (doğrulanmadı).
FASHN_CREDIT_USD = 0.075
FAL_TRYON_USD = 0.075
GEMINI_EDIT_USD = 0.04
MAI_CALL_USD = 0.06
MAI_FLASH_CALL_USD = 0.03
GPT_IMAGE_CALL_USD = 0.25


class FashnProvider:
    """FASHN'ın kendi API'si — `tryon-max` dahil.

    NEDEN fal'ın YANINA, YERİNE DEĞİL: fal adaptörü çalışıyor ve FAL_KEY zaten
    var. Bu sağlayıcı ayrı bir anahtar (`FASHN_API_KEY`) istiyor; ikisini birden
    tutmak, anahtarı olmayanın hattı kırılmasın diye.

    ÜÇ MİMARİ KAZANIM:

    1. **Sonuç base64 olarak isteniyor** (`return_base64: true`). Yani CDN'den
       indirme adımı YOK. §6.1 #9'daki en pahalı başarısızlık türü — "inference
       ücretlendirildi, sonuç indirilemedi" — bu yolda yapısal olarak imkânsız.
       RESULT_HOSTS kapısına da gerek kalmıyor.
    2. **Kategori sınırı yok.** tryon-max ayakkabı, şapka, takı ve çanta
       destekliyor; ürünü kendisi sınıflandırıyor. §10'daki
       `UNSUPPORTED_CATEGORIES` bu sağlayıcıda geçerli değil.
    3. **Çözünürlük seçilebiliyor.** v1.6 girdiyi 864x1296'ya sabitliyordu.

    ⚠ KATMAN ÜRETİMİNE UYGUNLUĞU ÖLÇÜLMEDİ. tryon-max bir görüntü düzenleme
    modeli üzerine kurulu; kıyafet dışını Gemini gibi yeniden üretiyorsa fark
    tabanlı çıkarım bozulur. O yüzden `supports_layers` model adına bağlı:
    v1.6 kanıtlanmış (True), tryon-max ölçülene kadar False. Ölçmek için:
    `python cli.py tryon-ab <id> --fashn`.
    """

    name = "fashn"
    supports_text_to_image = False

    def __init__(
        self,
        model_name: str = FASHN_DEFAULT_MODEL,
        resolution: str = "1k",
        generation_mode: str = "balanced",
        seed: int | None = None,
        prompt: str | None = None,
        allow_layers: bool | None = None,
    ):
        if model_name not in FASHN_MODELS:
            raise ValueError(
                f"Bilinmeyen FASHN modeli: {model_name} "
                f"(seçenekler: {', '.join(FASHN_MODELS)})"
            )
        self.model_name = model_name
        self.resolution = resolution
        self.generation_mode = generation_mode
        self.seed = seed
        # None = ölçülmüş varsayılan talimat. "" vermek onu KAPATIYOR —
        # A/B ölçümü yapabilmek için gerekli.
        self.prompt = FASHN_TRYON_PROMPT if prompt is None else prompt
        self._allow_layers = allow_layers

    @property
    def supports_layers(self) -> bool:
        """Çıktısı fark tabanlı katman çıkarımına uygun mu? — İKİSİ DE EVET.

        tryon-max için başta `False` yazılmıştı (ölçülmemişti). ÖLÇÜLDÜ ve
        açıldı — §25. Özet, #11 mor tişört üzerinde:

            sızıntı px   11.355 → 3.253      renk hatası  37.5 → 22.4

        Ve asıl sınav olan İKİ KATMANIN BİNDİRİLMESİ (#11 + #7) temiz çıktı;
        bel geçişinde kusur yok.

        ⚠ Bilinen kısıt, kayıt için: tryon-max kıyafet dışını v1.6 kadar
        korumuyor (duvar farkı 0.0 → 7.6, yüz 3 px kayıyor). Kombinde sorun
        çıkarmadı ama üç-dört katmanlı kombinlerde tekrar bakılmalı.
        """
        if self._allow_layers is not None:
            return self._allow_layers
        return True

    def available(self) -> bool:
        return secrets.has("FASHN_API_KEY")

    def supports_category(self, category: str) -> bool:
        # tryon-max ayakkabı/takı/çanta da yapıyor; v1.6 yapmıyor.
        if self.model_name == "tryon-max":
            return True
        return category not in UNSUPPORTED_CATEGORIES

    def credits(self) -> int:
        return FASHN_CREDITS.get((self.generation_mode, self.resolution), 2)

    def cost_usd(self) -> float:
        # Giydirme ve düzenleme aynı tabloyla ücretleniyor (FASHN belgesi).
        return self.credits() * FASHN_CREDIT_USD

    # --- HTTP ---

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {secrets.get('FASHN_API_KEY') or ''}",
            # USER-AGENT ZORUNLU — ölçüldü.
            #
            # urllib varsayılan olarak "Python-urllib/3.13" gönderiyor ve
            # api.fashn.ai'nin önündeki Cloudflare bunu engelliyor: her istek
            # (anahtarlı, anahtarsız, GET, POST fark etmiyor) `403 error code:
            # 1010` dönüyordu — yani gövdesi JSON bile olmayan, "kimlik
            # doğrulama hatası" gibi görünen bir Cloudflare cevabı.
            #
            # Teşhis şuydu: ANAHTARSIZ istek de aynı 403'ü verdi. Kimlik
            # doğrulama sorunu olsaydı anahtarlı ve anahtarsız istekler farklı
            # sonuç verirdi; vermedi. Demek ki istek FASHN'a hiç ulaşmıyor.
            #
            # Herhangi bir UA yetiyor; tarayıcı taklidi gereksiz. Kendimizi
            # dürüstçe tanıtıyoruz.
            "User-Agent": "virtual-wardrobe/1.0 (+python-urllib)",
        }

    def _cagir_http(self, url: str, method: str, payload: dict | None) -> dict:
        """Tek HTTP kapısı — hata GÖVDESİNİ okuyup mesaja koyar.

        Neden önemli: ilk denemede `403 Forbidden` alındı ve gövde okunmadığı
        için hata "kimlik doğrulama sorunu" gibi göründü. Oysa gövdede
        `error code: 1010` yazıyordu — bu bir Cloudflare kodu, FASHN'ın değil.
        Yani teşhis için gereken bilgi cevabın İÇİNDEYDİ ve biz onu atıyorduk.
        """
        import json
        import urllib.error
        import urllib.request

        istek = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers=self._headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(istek, timeout=60) as cevap:
                return json.loads(cevap.read())
        except urllib.error.HTTPError as exc:
            govde = ""
            try:
                govde = exc.read().decode("utf-8", "replace").strip()[:400]
            except Exception:
                pass
            raise RuntimeError(
                f"FASHN {method} {url.rsplit('/', 2)[-2:][0]} → HTTP {exc.code}"
                + (f": {govde}" if govde else "")
            ) from exc

    def _post(self, payload: dict) -> dict:
        return self._cagir_http(f"{FASHN_API_BASE}/run", "POST", payload)

    def _status(self, prediction_id: str) -> dict:
        return self._cagir_http(
            f"{FASHN_API_BASE}/status/{prediction_id}", "GET", None)

    def _bekle(self, prediction_id: str) -> list[str]:
        """Sonuç gelene kadar yoklar. Zaman aşımı ZORUNLU (bkz. CALL_TIMEOUT).

        §23.1'in dersi: zaman aşımsız bekleme, arayüzü sonsuza kadar döndürüyor
        ve hata teşhis edilebilir bile olmuyor.
        """
        import time

        son = time.monotonic() + CALL_TIMEOUT
        durum = "starting"
        while time.monotonic() < son:
            veri = self._status(prediction_id)
            durum = veri.get("status", "")

            if durum == "completed":
                cikti = veri.get("output") or []
                # Şema uç noktaya göre değişiyor: kimi düz liste, kimi
                # {"images": [...]}. İkisini de kabul et.
                if isinstance(cikti, dict):
                    cikti = cikti.get("images") or []
                if not cikti:
                    raise ResultUnreachable(
                        f"iş tamamlandı ama çıktı boş (id: {prediction_id})")
                return list(cikti)

            if durum == "failed":
                hata = veri.get("error") or {}
                ad = hata.get("name", "?") if isinstance(hata, dict) else hata
                mesaj = hata.get("message", "") if isinstance(hata, dict) else ""
                raise RuntimeError(f"FASHN hatası [{ad}]: {mesaj}")

            time.sleep(2)

        raise CallTimeout(
            f"çağrı {CALL_TIMEOUT:.0f} sn içinde tamamlanmadı "
            f"(son durum: {durum}, prediction id: {prediction_id}). İş "
            "ücretlendirilmiş olabilir — https://app.fashn.ai üzerinden kontrol et."
        )

    def _data_uri(self, path: Path) -> str:
        """Görseli data URI'ye çevirir — küçültülmüş halde.

        Yükleme sunucusu YOK: görsel isteğin içinde gidiyor. 30 MiB sınırının
        çok altındayız (küçültülmüş PNG ~1 MB), yani ayrı bir depolama adımı
        eklemenin faydası yok — üstelik her ek alan adı yeni bir DNS riski
        (§13, §6.1 #9).
        """
        import base64
        import io

        img = downscale(load_any(path), VTON_MAX_PX)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return ("data:image/png;base64,"
                + base64.b64encode(buf.getvalue()).decode("ascii"))

    def _inputs(self, model_image: Path, garment_image: Path,
                category: str) -> dict:
        model_uri = self._data_uri(model_image)
        garment_uri = self._data_uri(garment_image)

        if self.model_name == "tryon-max":
            inputs = {
                "model_image": model_uri,
                "product_image": garment_uri,
                "resolution": self.resolution,
                "generation_mode": self.generation_mode,
                "output_format": "png",
                # CDN'e hiç dokunma — bkz. sınıf docstring'i, kazanım #1.
                "return_base64": True,
                "num_images": 1,
            }
            if self.prompt:
                inputs["prompt"] = self.prompt
        else:
            inputs = {
                "model_image": model_uri,
                "garment_image": garment_uri,
                "category": to_fashn_category(category),
                "garment_photo_type": "flat-lay",
                "mode": "quality",
                "segmentation_free": FASHN_SEGMENTATION_FREE,
                "output_format": "png",
                "return_base64": True,
                "num_samples": 1,
            }

        if self.seed is not None:
            inputs["seed"] = self.seed
        return inputs

    def try_on(
        self, model_image: Path, garment_image: Path, category: str
    ) -> Image.Image:
        if not self.supports_category(category):
            raise UnsupportedCategory(
                f"'{category}' için {self.model_name} modelinde destek yok"
            )

        cevap = self._post({
            "model_name": self.model_name,
            "inputs": self._inputs(model_image, garment_image, category),
        })
        if cevap.get("error"):
            raise RuntimeError(f"FASHN isteği reddedildi: {cevap['error']}")

        prediction_id = cevap.get("id")
        if not prediction_id:
            raise RuntimeError(f"FASHN yanıtında id yok: {cevap}")

        cikti = self._bekle(prediction_id)
        # return_base64 sayesinde bu bir data URI; _download_image ağa çıkmadan
        # çözüyor. Yine de URL dönerse aynı fonksiyon indiriyor.
        return _download_image(cikti[0])

    def edit(
        self,
        image: Path,
        prompt: str,
        *,
        seed: int | None = None,
        resolution: str | None = None,
        generation_mode: str | None = None,
    ) -> Image.Image:
        """Var olan bir görüntüyü serbest metin talimatıyla düzenler.

        FASHN'ın `edit` uç noktası (şema dokümandan doğrulandı). Kimliği ve
        ürün sadakatini koruyarak talimatı uyguluyor: "kolları kıvır",
        "hafifçe sola dön", "gömleği içine sok", "stüdyo ışığı".

        `try_on`'dan farkı, girdinin bir KIYAFET değil bir SAHNE olması —
        yani zincirleme render'ın (Faz 4) çıktısını alıp üzerinde çalışıyor.
        Bu yüzden katman hattıyla ilgisi yok: burada çıkarım yapılmıyor,
        sonuç doğrudan gösteriliyor.
        """
        if not prompt.strip():
            raise ValueError("düzenleme talimatı boş olamaz")

        inputs = {
            "image": self._data_uri(image),
            "prompt": prompt.strip(),
            "resolution": resolution or self.resolution,
            "generation_mode": generation_mode or self.generation_mode,
            "output_format": "png",
            "return_base64": True,
            "num_images": 1,
        }
        tohum = self.seed if seed is None else seed
        if tohum is not None:
            inputs["seed"] = tohum

        cevap = self._post({"model_name": "edit", "inputs": inputs})
        if cevap.get("error"):
            raise RuntimeError(f"FASHN isteği reddedildi: {cevap['error']}")
        prediction_id = cevap.get("id")
        if not prediction_id:
            raise RuntimeError(f"FASHN yanıtında id yok: {cevap}")

        return _download_image(self._bekle(prediction_id)[0])

    def text_to_image(self, prompt: str, size: tuple[int, int]) -> Image.Image:
        raise RuntimeError(
            "fashn sağlayıcısı manken üretmiyor — `--provider fal` kullan"
        )


# --------------------------------------------------------------------------
# gemini — genel amaçlı görüntü düzenleyici (Gemini 2.5 Flash Image, fal üzerinden)
# --------------------------------------------------------------------------

# Kategori → giydirme talimatı. FASHN'ın enum'unun aksine burada kategori bir
# API alanı değil, PROMPT'un parçası — o yüzden ayakkabı ve aksesuar da var.
EDIT_INSTRUCTIONS: dict[str, str] = {
    "ust": "the top / t-shirt the person is wearing",
    "dis_giyim": "outerwear worn over the person's top",
    "alt": "the trousers / shorts the person is wearing",
    "elbise": "the full outfit, as a one-piece dress",
    "ayakkabi": "the shoes on the person's feet",
    "aksesuar": "the accessory worn by the person",
}


def giydirme_talimati(category: str) -> str:
    """Genel amaçlı düzenleyiciler için giydirme talimatı (Gemini ve Foundry).

    Talimat "neyi değiştir"den çok "neyi DEĞİŞTİRME" üzerine kurulu.
    Düzenleyicinin bilinen kusuru kıyafet dışını da yeniden çizmesi; onu API
    tarafında kısıtlayan bir alan yok, elimizdeki kaldıraç prompt — ve
    Foundry'de ayrıca `bolgeye_kisitla`.

    ETİKET CÜMLESİ (§51.9): kıyafet önden çekildiğinde yaka açıklığından
    içerideki marka etiketi görünüyor. MAI bir üretimde onu tişörtün ÖNÜNE,
    yakanın altına yerleştirdi — model içle dışı ayırt edemiyor.
    """
    hedef = EDIT_INSTRUCTIONS.get(category, EDIT_INSTRUCTIONS["ust"])
    return (
        "Using the first image as the person and the second image as the "
        f"garment, replace {hedef} with the garment from the second image. "
        "Keep the garment's exact colour, print, texture and cut. "
        "Any brand or size label visible inside the neckline of the garment "
        "photo is sewn on the inside: do not show it on the outside. "
        "Do not change the person's face, hair, skin, body shape, pose, "
        "hands, the background or the lighting. "
        "Keep the framing and image dimensions identical. "
        "Photorealistic result, natural fabric folds and shadows."
    )


class GeminiEditProvider:
    """Genel amaçlı düzenleyici ile giydirme — FASHN'ın yetersiz kaldığı yerler için.

    ⚠ KATMAN ÜRETİMİNDE KULLANILAMAZ, bu ölçüldü: düzenleyici kıyafetin
    DIŞINDAKİ pikselleri de yeniden üretiyor (yüz, duvar, poz milimetrik
    kayıyor). Fark tabanlı çıkarım tam olarak "kıyafet dışı sabit kalır"
    varsayımına dayandığı için katman baştan sona kirli çıkıyor.

    Buna karşılık Faz 4'ün zincirleme render'ında ÇIKARIM YOK — sonuç doğrudan
    gösteriliyor. Orada bu sınır hiç devreye girmiyor, dolayısıyla sağlayıcı
    orada gerçekten kullanılabilir (§18.2'nin önerdiği karşılaştırma da tam
    olarak bunu sınamak içindi).

    Bu yüzden `supports_layers = False`: sağlayıcı, kendisinin nerede
    kullanılamayacağını söylüyor — çağıran tarafın hatırlamasına bırakılmıyor.

    İKİNCİ FARK — kategori sınırı yok. Ayakkabı ve aksesuarın desteklenmemesi
    FASHN'ın eğitim setinin sınırı (§10); genel amaçlı bir düzenleyici için
    böyle bir sınır yok. Dolapta ayakkabı biriktiğinde tek yol bu olacak.
    """

    name = "gemini"
    supports_text_to_image = False
    supports_layers = False

    def __init__(self, seed: int | None = None):
        self.seed = seed

    def available(self) -> bool:
        if not secrets.has("FAL_KEY"):
            return False
        try:
            import fal_client  # noqa: F401
            return True
        except ImportError:
            return False

    def supports_category(self, category: str) -> bool:
        return True

    def cost_usd(self) -> float:
        return GEMINI_EDIT_USD

    def _client(self):
        import fal_client
        os.environ.setdefault("FAL_KEY", secrets.get("FAL_KEY") or "")
        return fal_client

    def prompt_for(self, category: str) -> str:
        return giydirme_talimati(category)

    def try_on(
        self, model_image: Path, garment_image: Path, category: str
    ) -> Image.Image:
        client = self._client()

        def ref(path: Path) -> str:
            # Küçültme gerekçesi FalProvider._image_ref'te — burada da geçerli.
            img = downscale(load_any(path), VTON_MAX_PX)
            try:
                return client.upload_image(img, format="png")
            except Exception:
                return client.encode_image(img, format="png")

        arguments = {
            "prompt": self.prompt_for(category),
            "image_urls": [ref(model_image), ref(garment_image)],
            "num_images": 1,
            "output_format": "png",
            # sync_mode: sonuç yanıtın içinde data URI olarak dönüyor, ayrı bir
            # CDN'den indirilmiyor. Bu bilerek seçildi — RESULT_HOSTS'a tahminle
            # alan adı yazmamak için (bkz. oradaki not). Gecikme artıyor, ama
            # "ücret ödendi, sonuç inemedi" riski tamamen ortadan kalkıyor.
            "sync_mode": True,
        }
        if self.seed is not None:
            arguments["seed"] = self.seed

        require_media_host(FAL_EDIT_ENDPOINT)   # boş liste → kapı açık geçer
        result = _cagir(client, FAL_EDIT_ENDPOINT, arguments)

        # Girdi çözünürlüğü korunmayabilir; katman hattı ve önbellek sabit
        # boyut varsayıyor, o yüzden model görselinin boyutuna geri getiriyoruz.
        out = _download_image(result["images"][0]["url"])
        hedef = load_any(model_image).size
        return out if out.size == hedef else out.resize(hedef, Image.LANCZOS)

    def text_to_image(self, prompt: str, size: tuple[int, int]) -> Image.Image:
        raise RuntimeError(
            "gemini sağlayıcısı manken üretmiyor — `--provider fal` kullan"
        )


# --------------------------------------------------------------------------
# foundry — Microsoft Foundry'deki görüntü modeli (gpt-image ailesi)
# --------------------------------------------------------------------------

# Modelin değiştirmesine İZİN VERİLEN bölgenin kişinin silüetinden ne kadar
# taşabileceği (tuval genişliğinin oranı). Cömert tutuldu: yeni kıyafet
# base'in kıyafetinden geniş olabilir (bol ceket, uzun kol); dar bir pay
# kıyafetin kenarını keserdi. Duvarın değişmesini engellemek için yeterli.
FOUNDRY_KISI_PAYI = 0.06

# Bölge sınırının yumuşatma yarıçapı (px). Sert bir sınır, model çıktısıyla
# base arasında görünür bir dikiş bırakırdı.
FOUNDRY_YUMUSATMA_PX = 6.0

# Kişi maskesi bu oranda küçültülüp genişletiliyor (bkz. _genislet).
_GENISLETME_KUCULTME = 8

# Düzenleme sohbetinde (Faz 6) talimata eklenen koruma cümlesi. Bölge
# kısıtlaması burada YOK — "hafifçe sola dön" pozu bilerek değiştiriyor —
# o yüzden koruma yalnızca talimatla isteniyor.
DUZENLEME_KORUMA_EKI = (
    " Apply only this change. Keep the person's identity, face, hair, body "
    "shape, the garments' colours, prints and fit, the background and the "
    "framing unchanged."
)


def _genislet(maske: np.ndarray, r: int) -> np.ndarray:
    """İkili maskeyi ~r piksel genişletir — scipy gerektirmeden ve hızlı.

    Tam çözünürlükte büyük çekirdekli `MaxFilter` çok yavaş (maliyet çekirdek
    boyutunun karesiyle büyüyor). Maske küçültülüp genişletiliyor ve geri
    büyütülüyor. Burası cömert bir güvenlik payı; piksel hassasiyeti gerekmiyor.
    """
    if r <= 0:
        return maske
    h, w = maske.shape
    k = _GENISLETME_KUCULTME
    kucuk = Image.fromarray((maske * 255).astype(np.uint8), mode="L").resize(
        (max(1, w // k), max(1, h // k)), Image.BILINEAR)
    kucuk = kucuk.filter(ImageFilter.MaxFilter(2 * max(1, round(r / k)) + 1))
    return np.asarray(kucuk.resize((w, h), Image.BILINEAR)) > 0


def bolgeye_kisitla(cikti: Image.Image, base_path: Path, category: str) -> Image.Image:
    """Genel amaçlı düzenleyicinin çıktısını kıyafetin olabileceği bölgeyle sınırlar.

    NEDEN GEREKLİ — ölçülmüş bir kısıt (bkz. GeminiEditProvider): genel amaçlı
    düzenleyiciler kıyafetin DIŞINDAKİ pikselleri de yeniden üretiyor; yüz,
    duvar, poz milimetrik kayıyor. Fark tabanlı katman çıkarımı "kıyafet dışı
    sabit kalır" varsayımına dayandığı için Gemini bu yüzden katman
    üretiminden dışlanmıştı.

    Burada o varsayımı modelden BEKLEMİYORUZ, kendimiz SAĞLIYORUZ: kıyafetin
    fiziksel olarak bulunabileceği bölgenin (kategori bandı ∩ genişletilmiş
    kişi silüeti) dışında base'in kendi pikselleri geri konuyor. Fark orada
    tanım gereği sıfır.

    Yan fayda: tek kıyafet görünümünde (§38) kullanıcı ham çıktıyı görüyor;
    bölge dışı base olduğu için yüzü ve odası birebir kendi fotoğrafı.

    ⚠ ÇÖZMEDİĞİ ŞEY: model POZU kaydırırsa kıyafet bölge içinde de kaymış bir
    gövdeye çiziliyor; bindirmede birkaç piksellik hizasızlık olarak görünür.
    Bu yalnızca gerçek çağrılarla ölçülebilir — ölçülmedi.
    """
    from wardrobe.cutout import person_mask_for
    # İşlev içinde: layers modülü vton'u içe aktarıyor, üst düzeyde döngü olurdu.
    from wardrobe.layers import region_band

    base = load_any(base_path).convert("RGB")
    out = cikti.convert("RGB")
    if out.size != base.size:
        out = out.resize(base.size, Image.LANCZOS)
    w, h = base.size

    ust, alt = region_band(category)
    bolge = np.zeros((h, w), dtype=bool)
    bolge[int(ust * h):int(np.ceil(alt * h))] = True

    # Kişi maskesi rembg gerektiriyor; yoksa yalnızca dikey bant kalıyor —
    # yüz ve bacaklar yine korunuyor, bant içindeki duvar korunmuyor.
    kisi = person_mask_for(base_path)
    if kisi is not None and kisi.shape == (h, w) and kisi.any():
        genis = _genislet(kisi, int(FOUNDRY_KISI_PAYI * w))
        # Güvenlik freni: kesişim boşsa (yanlış maske) bandla yetin. Boş bölge,
        # base'i aynen döndürür ve katman sessizce boş çıkardı.
        if (bolge & genis).any():
            bolge &= genis

    alfa = Image.fromarray((bolge * 255).astype(np.uint8), mode="L")
    if FOUNDRY_YUMUSATMA_PX > 0:
        alfa = alfa.filter(ImageFilter.GaussianBlur(FOUNDRY_YUMUSATMA_PX))
    a = (np.asarray(alfa, dtype=np.float32) / 255.0)[:, :, None]
    karisim = (np.asarray(out, dtype=np.float32) * a
               + np.asarray(base, dtype=np.float32) * (1.0 - a))
    return Image.fromarray(karisim.round().clip(0, 255).astype(np.uint8), mode="RGB")


def _png_parcasi(path: str | Path, ad: str) -> tuple[str, bytes, str]:
    """Görseli multipart için (dosya adı, PNG baytları, tür) üçlüsüne çevirir.

    Şeffaf arka planlı kıyafet kesimi BEYAZ zemine oturtuluyor: ürün
    fotoğraflarının standardı bu, ve modelin şeffaflığı nasıl yorumlayacağını
    tahmin etmekten daha güvenli.
    """
    img = downscale(load_any(path), VTON_MAX_PX)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        zemin = Image.new("RGB", rgba.size, (255, 255, 255))
        zemin.paste(rgba, mask=rgba.split()[3])
        img = zemin
    else:
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return ad, buf.getvalue(), "image/png"


def _alan(nesne, ad: str):
    """SDK nesnesinden ya da düz JSON sözlüğünden alan okur (MAI yanıtı dict)."""
    return nesne.get(ad) if isinstance(nesne, dict) else getattr(nesne, ad, None)


def _cevaptan_gorsel(cevap) -> Image.Image:
    """Görüntü API yanıtından PIL görseli. gpt-image ve MAI yalnızca base64 dönüyor."""
    veriler = _alan(cevap, "data") or []
    if not veriler:
        raise RuntimeError("Foundry yanıtında görsel yok")
    veri = veriler[0]
    b64 = _alan(veri, "b64_json")
    if b64:
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    url = _alan(veri, "url")
    if url:
        return _download_image(url)
    raise RuntimeError("Foundry yanıtında ne base64 ne URL var")


def _mai_boyut(hedef: tuple[int, int]) -> tuple[int, int]:
    """Hedefin en-boy oranında, MAI'nin piksel sınırlarına sığan en büyük boyut.

    864x1296 (1.12 MP) MAI-Image-2.5'in 1 MP tavanını aşıyor; oran korunarak
    küçültülüyor, çıktı sonra hedefe geri ölçekleniyor — bozulma yok.
    """
    w, h = hedef
    olcek = min(1.0, (foundry.MAI_MAX_PIKSEL / (w * h)) ** 0.5)
    w, h = int(w * olcek), int(h * olcek)
    if min(w, h) < foundry.MAI_MIN_KENAR:
        olcek = foundry.MAI_MIN_KENAR / min(w, h)
        w, h = round(w * olcek), round(h * olcek)
    return w, h


class FoundryImageProvider:
    """Microsoft Foundry'deki bir görüntü modeliyle giydirme (gpt-image ailesi).

    NEDEN VAR: projeyi kendi Foundry ortamında uçtan uca çalıştırmak isteyen
    biri FASHN / fal / Anthropic anahtarlarına takılıyordu. Foundry'de doğrudan
    bir sanal deneme modeli yok; gpt-image ailesi ise birden fazla girdi
    görseliyle düzenleme yapabiliyor — kişi fotoğrafı + kıyafet + talimat.

    Bu, GeminiEditProvider ile AYNI türden bir model: genel amaçlı düzenleyici.
    Gemini katman üretiminden dışlanmıştı çünkü kıyafet dışını yeniden
    çiziyordu. Buradaki fark `bolgeye_kisitla`: kıyafet dışı model çıktısından
    değil base'den geliyor — o yüzden `supports_layers = True`.

    İKİ MODEL AİLESİ, TEK SAĞLAYICI: dağıtım bir MAI modeliyse (Microsoft'un
    kendi görüntü modelleri, MAI-Image-2.5/2.6) istekler MAI'nin ayrı API'sine
    gidiyor (`_mai_istegi`), değilse OpenAI uyumlu görüntü API'sine. Bölge
    kısıtlaması ikisinde de aynı — sorun modelin türünde değil, genel amaçlı
    olmasında.

    ÖLÇÜM DURUMU: MAI yolu gerçek çağrılarla ölçüldü — 12 kıyafette katman,
    FASHN düzeyinde (§51.6–§51.9). gpt-image yolu ve MAI ile düzenleme
    sohbeti/manken üretimi yalnızca sahte istemciyle test edildi. Mankene
    sağlayıcı bağlanmamışsa FASHN önce seçiliyor (bkz. get_provider).
    """

    name = "foundry"
    supports_text_to_image = True
    supports_layers = True

    def __init__(self, seed: int | None = None):
        # gpt-image ve MAI'nin tohum parametresi yok. Arayüz uyumu için kabul
        # ediliyor ama gönderilmiyor — sonuçlar bu yüzden tekrarlanabilir değil.
        self.seed = seed

    def available(self) -> bool:
        if not foundry.image_ready():
            return False
        # MAI düz HTTP: httpx zaten anthropic'in bağımlılığı. openai paketi
        # yalnızca gpt-image yolunda gerekiyor.
        paket = "httpx" if foundry.image_api() == "mai" else "openai"
        try:
            __import__(paket)
            return True
        except ImportError:
            return False

    def supports_category(self, category: str) -> bool:
        # Genel amaçlı düzenleyici: kategori bir API alanı değil, talimatın parçası.
        return True

    def credits(self) -> int:
        # Foundry kredi değil token üzerinden faturalıyor. Arayüz "kaç çağrı"
        # gösterebilsin diye çağrı başına 1. Ücret: `cost_usd`.
        return 1

    def cost_usd(self) -> float:
        if foundry.image_api() == "mai":
            ad = (foundry.image_deployment() or "").lower()
            return MAI_FLASH_CALL_USD if "flash" in ad else MAI_CALL_USD
        return GPT_IMAGE_CALL_USD

    def _client(self):
        from openai import OpenAI

        surum = foundry.openai_api_version()
        return OpenAI(
            api_key=foundry.api_key(),
            base_url=foundry.openai_base_url(),
            # v1 rotası standart Bearer başlığını kabul ediyor; `api-key` ise
            # Azure'un klasik başlığı. İkisini birden göndermek, ilk çağrının
            # kaynak türünden bağımsız çalışma ihtimalini artırıyor.
            default_headers={"api-key": foundry.api_key() or ""},
            default_query={"api-version": surum} if surum else None,
        )

    def _istek(self, **ek) -> dict:
        # `input_fidelity` BİLEREK yok: gpt-image-2.5 bu alanla 400 dönüyor
        # (belgelerdeki bir tutarsızlık) ve hangi modelin dağıtıldığını bilmiyoruz.
        return {
            "model": foundry.image_deployment(),
            "size": foundry.image_size(),
            "quality": foundry.image_quality(),
            "output_format": "png",
            "n": 1,
            **ek,
        }

    def _mai_istegi(self, yol: str, **istek) -> dict:
        """MAI görüntü API'sine düz HTTP isteği (`/mai/v1/images/...`).

        OpenAI SDK'sı burada kullanılamıyor: MAI'nin yolu, alan adları ve
        parametreleri farklı (boyut/kalite alanı yok; görseller tekrarlanan
        `image` alanıyla gidiyor). Hata mesajı durum kodunu ve yanıtın başını
        taşıyor — anahtarı değil.
        """
        import httpx

        yanit = httpx.post(
            f"{foundry.mai_base_url()}{yol}",
            headers={"api-key": foundry.api_key() or ""},
            timeout=CALL_TIMEOUT,
            **istek,
        )
        if yanit.status_code >= 400:
            raise RuntimeError(
                f"MAI {yol} → HTTP {yanit.status_code}: {yanit.text[:500]}")
        return yanit.json()

    def _duzenle(self, gorseller: list[tuple[str, bytes, str]], prompt: str):
        """Düzenleme isteği — dağıtımın API ailesine göre."""
        if foundry.image_api() == "mai":
            alanlar = {"model": foundry.image_deployment(), "prompt": prompt}
            if foundry.mai_auto_aspect():
                alanlar["auto_aspect_ratio"] = "true"
            return self._mai_istegi(
                "/mai/v1/images/edits", data=alanlar,
                files=[("image", g) for g in gorseller])
        return self._client().images.edit(**self._istek(
            image=gorseller if len(gorseller) > 1 else gorseller[0],
            prompt=prompt,
        ))

    def try_on(
        self, model_image: Path, garment_image: Path, category: str
    ) -> Image.Image:
        cevap = self._duzenle(
            [_png_parcasi(model_image, "kisi.png"),
             _png_parcasi(garment_image, "kiyafet.png")],
            giydirme_talimati(category),
        )
        return bolgeye_kisitla(_cevaptan_gorsel(cevap), Path(model_image), category)

    def edit(
        self, image: Path, prompt: str, *, seed: int | None = None
    ) -> Image.Image:
        """Düzenleme sohbeti (Faz 6): var olan sahneyi talimatla değiştirir."""
        if not prompt.strip():
            raise ValueError("düzenleme talimatı boş olamaz")
        cevap = self._duzenle([_png_parcasi(image, "sahne.png")],
                              prompt.strip() + DUZENLEME_KORUMA_EKI)
        out = _cevaptan_gorsel(cevap)
        hedef = load_any(image).size
        return out if out.size == hedef else out.resize(hedef, Image.LANCZOS)

    def text_to_image(self, prompt: str, size: tuple[int, int]) -> Image.Image:
        if foundry.image_api() == "mai":
            w, h = _mai_boyut(tuple(size))
            cevap = self._mai_istegi(
                "/mai/v1/images/generations",
                json={"model": foundry.image_deployment(), "prompt": prompt,
                      "width": w, "height": h})
        else:
            cevap = self._client().images.generate(**self._istek(prompt=prompt))
        out = _cevaptan_gorsel(cevap)
        return out if out.size == tuple(size) else out.resize(size, Image.LANCZOS)


# --------------------------------------------------------------------------
# mock — anahtarsız yedek
# --------------------------------------------------------------------------

# Kıyafetin manken üzerinde kaplayacağı dikey bölge (yükseklik oranı olarak).
SLOT_BANDS: dict[str, tuple[float, float]] = {
    "ust": (0.20, 0.55),
    "dis_giyim": (0.18, 0.60),
    "alt": (0.50, 0.88),
    "elbise": (0.20, 0.85),
    # Aksesuar vücudun her yerinde olabilir (şapka baş, kolye boyun, saat
    # bilek, kemer bel), o yüzden bant dar tutulamıyor. Burada amaç
    # segmentasyon değil, bacaklardaki serpintiyi engelleyen kaba güvenlik ağı
    # — ve o iş zaten `largest_component`'te yapılıyor; bu yalnızca scipy
    # yokken devreye giren yedek.
    "aksesuar": (0.05, 0.95),
    "ayakkabi": (0.78, 1.00),
}


class MockProvider:
    """Kıyafeti mankenin doğru bölgesine ölçekleyip yapıştırır.

    Gerçek bir deneme değil — ama gerçek bir katman üretiyor: doğru boyutta,
    doğru bölgede, şeffaflığı korunmuş. Faz 2'nin giydirme arayüzünü para
    harcamadan geliştirmeye yetiyor.
    """

    name = "mock"
    supports_text_to_image = False

    def available(self) -> bool:
        return True

    def supports_category(self, category: str) -> bool:
        return category not in UNSUPPORTED_CATEGORIES

    def cost_usd(self) -> float:
        return 0.0

    def try_on(
        self, model_image: Path, garment_image: Path, category: str
    ) -> Image.Image:
        to_fashn_category(category)  # desteklenmeyen kategoride aynı hatayı ver

        base = load_any(model_image).convert("RGB")
        garment = load_any(garment_image).convert("RGBA")
        w, h = base.size

        top, bottom = SLOT_BANDS.get(category, (0.20, 0.55))
        box_h = int((bottom - top) * h)
        box_w = int(w * 0.46)

        fitted = garment.copy()
        fitted.thumbnail((box_w, box_h), Image.LANCZOS)

        out = base.copy()
        out.paste(
            fitted,
            ((w - fitted.width) // 2, int(top * h)),
            fitted,
        )
        return out

    def text_to_image(self, prompt: str, size: tuple[int, int]) -> Image.Image:
        raise RuntimeError("mock sağlayıcı görsel üretemez (bkz. mannequin.placeholder)")


# --------------------------------------------------------------------------

_PROVIDERS = {"fal": FalProvider, "fashn": FashnProvider,
              "gemini": GeminiEditProvider, "foundry": FoundryImageProvider,
              "mock": MockProvider}


def supports_layers(provider) -> bool:
    """Sağlayıcının çıktısı fark tabanlı katman çıkarımına uygun mu?

    Varsayılan True: mevcut sağlayıcıların hepsi kıyafet dışını koruyor.
    Korumayan bir sağlayıcı (bkz. GeminiEditProvider) bunu kendisi bildiriyor,
    böylece kısıt çağıran tarafın hatırlamasına kalmıyor.
    """
    return bool(getattr(provider, "supports_layers", True))


def supports_category(provider, category: str) -> bool:
    """Sağlayıcı bu kategoriyi giydirebiliyor mu?

    Sağlayıcı `supports_category` tanımlamamışsa FASHN'ın kuralı varsayılıyor.
    Bu yalnızca geriye dönük uyumluluk değil: sağlayıcı arayüzü bilinçli olarak
    duck-typing — testlerdeki üç satırlık sahte sağlayıcılar ve ileride
    eklenecek üçüncü taraf sağlayıcılar, ilgilenmedikleri bir yeteneği
    bildirmek zorunda kalmasın.
    """
    fn = getattr(provider, "supports_category", None)
    if fn is not None:
        return bool(fn(category))
    return category not in UNSUPPORTED_CATEGORIES


def _manken_saglayicisi() -> str | None:
    """Aktif mankene bağlı sağlayıcı (bkz. mannequin.provider_for). Hata fırlatmaz."""
    try:
        from wardrobe import mannequin     # döngüsel import olmasın diye içeride

        ad = mannequin.provider_for()
    except Exception:
        return None
    return ad if ad in _PROVIDERS else None


def get_provider(name: str | None = None) -> VtonProvider:
    """Sağlayıcıyı seçer.

    Sıra: açık isim → VTON_PROVIDER → aktif mankenin sağlayıcısı (§51.7) →
    **fashn** (varsa) → fal (varsa) → foundry (varsa) → mock.

    FOUNDRY SONDAN BİR ÖNCE: o genel amaçlı bir düzenleyici ve katman
    kalitesi ölçülmedi; FASHN ise bu iş için eğitilmiş ve ölçülmüş. Yalnızca
    Foundry tanımlı bir ortamda (FASHN/fal anahtarı yok) otomatik seçiliyor.

    FASHN ÖNCE GELİYOR, ölçümle: §25'te tryon-max hem sızıntıyı 3.5 kat
    düşürdü hem rengi 1.7 kat daha doğru üretti, hem de v1.6'nın yapamadığı
    ayakkabı/takı/çantayı yapıyor. Kredi başına fiyat aynı.

    Bu satır göründüğünden önemli: arayüzden kıyafet eklendiğinde de burası
    çalışıyor. Sıra değişmeseydi kullanıcı web'den eklediği her kıyafet için
    sessizce ESKİ modeli kullanmaya devam ederdi — ve dolabın geri kalanı
    tryon-max ile üretilmişken tek bir kıyafetin v1.6 ile üretilmesi, katmanlar
    arasında görünür bir tutarsızlık demek.
    """
    name = name or os.environ.get("VTON_PROVIDER") or _manken_saglayicisi()
    if name:
        if name not in _PROVIDERS:
            raise ValueError(
                f"Bilinmeyen sağlayıcı: {name} "
                f"(seçenekler: {', '.join(_PROVIDERS)})"
            )
        return _PROVIDERS[name]()

    for aday in (FashnProvider(), FalProvider(), FoundryImageProvider()):
        if aday.available():
            return aday
    return MockProvider()


def get_edit_provider():
    """Düzenleme sohbeti (Faz 6) için sağlayıcı: FASHN, yoksa Foundry.

    AKTİF MANKENİN SAĞLAYICISI ÖNE ALINIYOR (§54): sıra eskiden sabitti ve
    MAI mankeninde "Gerçekçi göster" MAI ile, aynı render'ın düzenlemesi ise
    FASHN ile yapılıyordu — iki model, iki fatura, kullanıcıya görünmeden.
    `VTON_PROVIDER` de aynı yoldan geçiyor (get_provider'daki sırayla).
    Adaylar yine yalnızca düzenleme yapabilen ikisi.

    Hiçbiri kullanılamıyorsa FASHN dönüyor — çağıran taraf `available()`
    kontrolünde anlamlı bir hata veriyor ("hangi anahtar eksik").
    """
    sira = [FashnProvider, FoundryImageProvider]
    tercih = _PROVIDERS.get(os.environ.get("VTON_PROVIDER") or _manken_saglayicisi())
    if tercih in sira:
        sira.remove(tercih)
        sira.insert(0, tercih)
    for sinif in sira:
        aday = sinif()
        if aday.available():
            return aday
    return FashnProvider()


def model_label(provider) -> str:
    """Arayüzde gösterilen model adı — hangi modelin çağrılacağı görünsün.

    Foundry için dağıtımın kendi adı ("MAI-Image-2.6"): kullanıcının portalda
    gördüğü ad bu.
    """
    if provider.name == "fashn":
        return f"FASHN {provider.model_name}"
    if provider.name == "foundry":
        return foundry.image_deployment() or "Foundry"
    return {"fal": "FASHN v1.6 (fal)", "gemini": "Gemini (fal)"}.get(
        provider.name, provider.name)
