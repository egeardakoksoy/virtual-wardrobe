/* Giydirme arayüzü — Faz 2.
 *
 * İki kural burada yaşıyor, ikisi de sunucudan gelen kategori tablosundan:
 *   z     → katmanların çizim sırası (CSS z-index)
 *   slots → aynı bölgeyi kaplayan iki kıyafet aynı anda giyilemez
 *
 * Kural istemcide TANIMLANMIYOR, sunucudan geliyor — tek kaynak config.py.
 */

let KATEGORI = {};                  // kategori adı -> {label, z, slots}
let KIYAFETLER = [];                // dolabın tamamı
let MANKEN = { id: 0, name: "" };   // aktif manken (§28)
let BASE_REV = 0;                   // gösterim base'i (nötrlenmiş) damgası
let BASE_HAM_REV = 0;               // gerçek fotoğraf damgası
const secili = new Map();           // id -> kıyafet

/* Zemin: NÖTRLENMİŞ mi, GERÇEK fotoğraf mı?
 *
 * Nötrleme yalnızca BİNDİRME için var — katmanın boşluk bıraktığı ya da base'in
 * kıyafetinin yeni kıyafetin siluetinin dışına taştığı yerde altından base'in
 * gerçek kıyafeti yerine nötr koyu bir ton çıksın diye (§7.5'te turkuaz base
 * bunu ölçmüştü: sızıntı görünürse felaket).
 *
 * Bindirme olmayan yerde gerekli değil ve kullanıcıya mankeni gereksiz yere
 * gri gösteriyordu:
 *   · seçim boş        → gerçek fotoğraf
 *   · tek kıyafet      → ham VTON çıktısı zaten üstünü kapatıyor (§38)
 *   · 2+ kıyafet       → nötrlenmiş (bindirme burada)
 */
function zeminiSec() {
  const bindirme = secili.size >= 2;

  /* KÖR NOKTA İSTİSNASI — ölçümle eklendi.
   *
   * Kıyafet mankenin kıyafetiyle aynı renk bandındaysa fark neredeyse boş
   * çıkıyor: o bölgede katman doluluğu %4 ölçüldü, yani ekranda görünenin
   * %96'sı ZEMİN. O durumda nötrlenmiş zemin kıyafeti YANLIŞ renkte gösteriyor
   * (lacivert tişört gri görünüyordu). Gerçek fotoğraf doğru gösteriyor:
   *
   *     nötr zemin  : kıyafetin gerçek rengine uzaklık 17.3
   *     gerçek foto : 7.7
   *
   * Nötrlemenin varlık sebebi tersi durum (§7.5): kıyafet base'den ÇOK farklı
   * renkteyse sızan base pikselleri göze batıyor, nötr olması iyi. Yani doğru
   * zemin duruma bağlı — kararı `base_near` veriyor ve eşik sunucuda. */
  const korNokta = [...secili.values()].some((g) => g.base_near);
  $("#base").src = (bindirme && !korNokta)
    ? `/api/base.png?m=${MANKEN.id}&v=${BASE_REV}`
    : `/api/base_raw.png?m=${MANKEN.id}&v=${BASE_HAM_REV}`;
}

const $ = (s) => document.querySelector(s);

async function baslat() {
  await dolabiYenile();
  kayitlariYukle();

  $("#temizle").onclick = () => { secili.clear(); guncelle(); };
  $("#kaydet").onclick = kombiniKaydet;
  $("#render").onclick = gercekciGoster;
  $("#katmana-don").onclick = katmanaDon;
  yuklemeyiKur();
  duzenlemeyiKur();
  mankenleriKur();
}

/* --- Mankenler (§28) ---
 *
 * Birden çok manken yan yana yaşıyor ve her birinin KENDİ katman seti var
 * (`layers` tablosunun anahtarı zaten (kıyafet, manken)). Geçiş ÜCRETSİZ ve
 * hiçbir şeyi silmiyor — bu özelliğin bütün amacı bu.
 *
 * Ücret sınırı burada çizili: manken eklemek bedava, o mankende katman üretmek
 * ücretli ve AYRI bir işlem. İkisi tek düğmeye bağlansaydı "yeni manken ekle"
 * sessizce ~30 kredilik bir işlem olurdu.
 */

let MANKENLER = [];

function mankenleriKur() {
  $("#manken-dosya").onchange = (ev) => {
    const f = ev.target.files[0];
    ev.target.value = "";
    if (f) mankenEkle(f);
  };
}

async function mankenleriYukle() {
  const veri = await (await fetch("/api/mannequins")).json();
  MANKENLER = veri.mannequins;
  mankenleriCiz();
}

function mankenleriCiz() {
  const kap = $("#manken-liste");
  kap.innerHTML = "";

  MANKENLER.forEach((m) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "mkart"
      + (m.is_active ? " aktif" : "")
      + (m.layer_count ? "" : " bos");
    el.title = m.is_active
      ? `${m.name} — şu an bu mankendesin`
      : `${m.name} — geç (ücretsiz, hiçbir katman silinmez)`;

    const img = document.createElement("img");
    // ?w= ile küçültülmüş: tam boy 864×1296 PNG'yi her manken için indirmek
    // gereksiz (film şeridiyle aynı gerekçe). ?v= damgası fotoğraf değişince
    // tarayıcının eskisini göstermesini engelliyor (§25.7).
    img.src = m.has_image
      ? `/api/mannequins/${m.id}.png?w=160&v=${m.rev || 0}`
      : "";
    img.alt = "";

    const ad = document.createElement("span");
    ad.className = "ad";
    ad.textContent = m.name;

    const sayi = document.createElement("span");
    sayi.className = "sayi";
    sayi.textContent = m.layer_count ? `${m.layer_count} katman` : "katman yok";

    el.append(img, ad, sayi);

    // Silme yalnızca birden fazla manken varken: son mankeni silmek dolabı
    // zeminsiz bırakırdı (sunucu da reddediyor, düğmeyi hiç göstermemek daha
    // dürüst).
    if (MANKENLER.length > 1) {
      const sil = document.createElement("span");
      sil.className = "sil";
      sil.textContent = "✕";
      sil.title = "Bu mankeni sil";
      sil.onclick = (e) => { e.stopPropagation(); mankenSil(m); };
      el.appendChild(sil);
    }

    el.onclick = () => { if (!m.is_active) mankeneGec(m); };
    kap.appendChild(el);
  });

  const yeni = document.createElement("button");
  yeni.type = "button";
  yeni.className = "yeni";
  yeni.textContent = "+ Yeni manken";
  yeni.title = "Tam boy fotoğraf yükle — ÜCRETSİZ. Katman üretimi ayrı ve ücretli.";
  yeni.onclick = () => $("#manken-dosya").click();
  kap.appendChild(yeni);

  const aktif = MANKENLER.find((m) => m.is_active);
  const not = $("#manken-not");
  if (!aktif) {
    not.className = "alt uyari";
    not.textContent = "Aktif manken yok — python cli.py mannequin --from-photo <foto>";
  } else if (!aktif.layer_count) {
    not.className = "alt uyari";
    not.textContent =
      `“${aktif.name}” için hiç katman yok. Kıyafet kartına tıklayarak tek tek `
      + "üretebilirsin (her biri ücretli) ya da: python cli.py build-layers";
  } else {
    not.className = "alt";
    not.textContent =
      `“${aktif.name}” · ${aktif.layer_count} katman hazır. `
      + "Mankenler arası geçiş ücretsiz, hiçbir katman silinmiyor.";
  }
}

async function mankeneGec(m) {
  const not = $("#manken-not");
  not.className = "alt calisiyor";
  not.textContent = `“${m.name}” mankenine geçiliyor…`;

  const c = await fetch(`/api/mannequins/${m.id}/aktif`, { method: "POST" });
  if (!c.ok) {
    not.className = "alt hata";
    not.textContent = (await c.json()).detail || "geçilemedi";
    return;
  }
  // Seçim korunuyor ama katmanı olmayanlar düşüyor: aynı kıyafet iki mankende
  // de olabilir, olmayabilir. `dolabiYenile` bunu zaten yapıyor.
  await dolabiYenile();
}

async function mankenEkle(dosya) {
  const not = $("#manken-not");
  const ad = (prompt("Yeni mankene ad ver (boş bırakırsan otomatik):", "") || "").trim();

  not.className = "alt calisiyor";
  not.textContent = `${dosya.name} yükleniyor…`;

  const form = new FormData();
  form.append("file", dosya);
  form.append("name", ad);

  const c = await fetch("/api/mannequins", { method: "POST", body: form });
  if (!c.ok) {
    not.className = "alt hata";
    not.textContent = (await c.json()).detail || "manken eklenemedi";
    return;
  }
  await dolabiYenile();
}

async function mankenSil(m) {
  const k = m.usage || { layers: 0, renders: 0, edits: 0 };
  // Kaç şeyin gideceği ONAY EKRANINDA yazıyor. Bir mankenin ~30 kredilik
  // katmanı olabiliyor ve silme geri alınamaz; ne kaybedileceğini söylemeden
  // alınan onay, onay değildir.
  if (!confirm(
    `“${m.name}” mankeni silinecek.\n\n`
    + `GERİ ALINAMAZ. Şunlar da gidecek:\n`
    + `  · ${k.layers} katman\n`
    + `  · ${k.renders} gerçekçi render\n`
    + `  · ${k.edits} düzenleme adımı\n\n`
    + `Hepsi ücretle üretildi — yeniden üretmek yeniden ödemek demek.`
  )) return;

  const c = await fetch(`/api/mannequins/${m.id}`, { method: "DELETE" });
  const not = $("#manken-not");
  if (!c.ok) {
    not.className = "alt hata";
    not.textContent = (await c.json()).detail || "silinemedi";
    return;
  }
  await dolabiYenile();
}

/* --- Kıyafet yükleme ---
 *
 * Akış iki adımlı ve arasında ÜCRETSİZ bir kapı var: kırpma + öznitelik
 * çıkarımı ucuz, katman üretimi ücretli. Kıyafetin rengi base mankenin
 * kıyafetine çok yakınsa katman zaten boş çıkacağı için sunucu ücretli çağrıyı
 * hiç yapmıyor ve sebebini söylüyor.
 */

let SABLONLAR = {};
let SINIRLAR = { dx: 0.45, dy: 0.45, scale: [0.4, 2.5], rotate: 30 };
let bekleyen = [];          // hizalama onayı bekleyen dosyalar

/* Hizalama durumu. Sunucudaki apply_align ile AYNI sözleşme:
 *   dx, dy  → çerçeve genişliğinin/yüksekliğinin oranı
 *   scale   → merkez etrafında ölçek
 *   rotate  → merkez etrafında derece (saat yönü)
 * Uygulama sırası: önce ölçek, sonra dönme, sonra taşıma. CSS'te bu sırayı
 * `translate(...) rotate(...) scale(...)` veriyor — soldaki en dışta uygulanır.
 * Sıra bozulursa önizleme ile sunucudaki sonuç sessizce ayrışır. */
const HIZ_BIRIM = { dx: 0, dy: 0, scale: 1, rotate: 0 };
let hiz = { ...HIZ_BIRIM };

const ADIM = 0.01;          // yön tuşu başına kayma (çerçeve oranı)

async function sablonlariYukle() {
  const v = await (await fetch("/api/templates")).json();
  SABLONLAR = v.shapes;
  if (v.align_limits) SINIRLAR = v.align_limits;

  // KATEGORİYE GÖRE GRUPLA. Şablon sayısı 5'ten 21'e çıkınca düz liste
  // kullanılamaz hale geldi; grup başlıkları hem aramayı kısaltıyor hem de
  // hangi şablonun hangi kategoriye düştüğünü görünür yapıyor (kategori
  // z-sırasını ve çakışma kuralını belirliyor, yani seçim önemli).
  const sec = $("#sablon");
  sec.innerHTML = "";
  const gruplar = {};
  for (const [k, s] of Object.entries(SABLONLAR)) {
    (gruplar[s.category] ||= []).push([k, s]);
  }
  // Sıra kategori tablosundan: üstte giyilen üstte listelensin
  const sirali = Object.keys(gruplar).sort(
    (a, b) => (KATEGORI[b]?.z ?? 99) - (KATEGORI[a]?.z ?? 99));

  for (const kat of sirali) {
    const grup = document.createElement("optgroup");
    grup.label = KATEGORI[kat]?.label || kat;
    for (const [k, s] of gruplar[kat]) {
      const o = document.createElement("option");
      o.value = k; o.textContent = s.label;
      grup.appendChild(o);
    }
    sec.appendChild(grup);
  }
  sec.value = v.default;
  sec.onchange = () => sablonuCiz();

  const [lo, hi] = SINIRLAR.scale;
  Object.assign($("#hiz-olcek"), { min: lo, max: hi, value: 1 });
  Object.assign($("#hiz-donme"),
                { min: -SINIRLAR.rotate, max: SINIRLAR.rotate, value: 0 });
}

function noktalar(s) {
  return s.points.map(([x, y]) => `${x * 100},${y * 100}`).join(" ");
}

function sablonuCiz() {
  const s = SABLONLAR[$("#sablon").value];
  if (!s) return;
  $("#hizalama-poly").setAttribute("points", noktalar(s));
  $("#sonuc-poly").setAttribute("points", noktalar(s));
}

/* --- Hizalama paneli ---
 *
 * Sunucu dönüşümü fotoğrafın KENDİ tuvaline uyguluyor ve tuval boyutu
 * değişmiyor. Önizlemenin bunu birebir yansıtması için çerçevenin en-boy oranı
 * fotoğrafınkine eşitleniyor; aksi halde `translate(%…)` başka bir genişliğe
 * göre hesaplanır ve kullanıcı gördüğünden farklı bir kırpma alır. */

function kis(deger, alt, ust) {
  return Math.max(alt, Math.min(ust, deger));
}

function hizUygula() {
  const [lo, hi] = SINIRLAR.scale;
  hiz.dx = kis(hiz.dx, -SINIRLAR.dx, SINIRLAR.dx);
  hiz.dy = kis(hiz.dy, -SINIRLAR.dy, SINIRLAR.dy);
  hiz.scale = kis(hiz.scale, lo, hi);
  hiz.rotate = kis(hiz.rotate, -SINIRLAR.rotate, SINIRLAR.rotate);

  $("#hizalama-foto").style.transform =
    `translate(${hiz.dx * 100}%, ${hiz.dy * 100}%) ` +
    `rotate(${hiz.rotate}deg) scale(${hiz.scale})`;

  $("#hiz-olcek").value = hiz.scale;
  $("#hiz-donme").value = hiz.rotate;
  $("#hiz-olcek-deger").textContent = `%${Math.round(hiz.scale * 100)}`;
  $("#hiz-donme-deger").textContent = `${hiz.rotate.toFixed(1)}°`;
}

function hizSifirla() {
  hiz = { ...HIZ_BIRIM };
  hizUygula();
}

function hizalamaGoster(dosyalar) {
  bekleyen = dosyalar;
  hizSifirla();

  const img = $("#hizalama-foto");
  img.onload = () => {
    // Çerçeve oranı = fotoğraf oranı. Sözleşmenin can damarı burası.
    $("#hizalama-tuval").style.aspectRatio =
      `${img.naturalWidth} / ${img.naturalHeight}`;
  };
  img.src = URL.createObjectURL(dosyalar[0]);

  sablonuCiz();
  $("#hizalama-not").textContent = dosyalar.length > 1
    ? `${dosyalar.length} fotoğraf — hizalama İLKİNE göre yapılıyor ve hepsine uygulanıyor. Farklı duruyorlarsa tek tek yükle.`
    : "Sürükle, yön tuşlarını ya da kaydırıcıları kullan. Kıyafeti çerçeveye oturt, kenarlara değdirme.";
  $("#hizalama").classList.remove("gizli");
  $("#sonuc").classList.add("gizli");
}

function hizalamaKapat() {
  $("#hizalama").classList.add("gizli");
  const img = $("#hizalama-foto");
  if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
  bekleyen = [];
}

/* Klavye yalnızca panel AÇIKKEN dinleniyor; aksi halde ok tuşları sayfayı
 * kaydırmak isteyen kullanıcıdan çalınırdı. */
function hizKlavye(ev) {
  if ($("#hizalama").classList.contains("gizli")) return;
  const tus = {
    ArrowUp: () => (hiz.dy -= ADIM), ArrowDown: () => (hiz.dy += ADIM),
    ArrowLeft: () => (hiz.dx -= ADIM), ArrowRight: () => (hiz.dx += ADIM),
    "+": () => (hiz.scale += 0.02), "=": () => (hiz.scale += 0.02),
    "-": () => (hiz.scale -= 0.02), _: () => (hiz.scale -= 0.02),
    "[": () => (hiz.rotate -= 0.5), "]": () => (hiz.rotate += 0.5),
    0: hizSifirla,
  }[ev.key];
  if (!tus) return;
  ev.preventDefault();
  tus();
  hizUygula();
}

function hizSuruklemeKur() {
  const tuval = $("#hizalama-tuval");
  let aktif = null;

  tuval.addEventListener("pointerdown", (ev) => {
    aktif = { x: ev.clientX, y: ev.clientY };
    tuval.setPointerCapture(ev.pointerId);
    tuval.classList.add("suruklerken");
  });
  tuval.addEventListener("pointermove", (ev) => {
    if (!aktif) return;
    const k = tuval.getBoundingClientRect();
    hiz.dx += (ev.clientX - aktif.x) / k.width;
    hiz.dy += (ev.clientY - aktif.y) / k.height;
    aktif = { x: ev.clientX, y: ev.clientY };
    hizUygula();
  });
  for (const e of ["pointerup", "pointercancel", "pointerleave"]) {
    tuval.addEventListener(e, () => {
      aktif = null;
      tuval.classList.remove("suruklerken");
    });
  }
  // Tekerlek = ölçek. Sayfanın kaymasını engellemek için passive:false şart.
  tuval.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    hiz.scale *= ev.deltaY < 0 ? 1.04 : 1 / 1.04;
    hizUygula();
  }, { passive: false });
}

function yuklemeyiKur() {
  const alan = $("#yukle-alan");
  const girdi = $("#dosya");

  sablonlariYukle();
  hizSuruklemeKur();
  document.addEventListener("keydown", hizKlavye);

  $("#hizalama-iptal").onclick = hizalamaKapat;
  $("#hizalama-onay").onclick = () => {
    const d = bekleyen;
    const uygulanan = { ...hiz };
    hizalamaKapat();
    kuyrugaAl(d, uygulanan);
  };
  $("#hiz-sifirla").onclick = hizSifirla;
  $("#sonuc-kapat").onclick = () => $("#sonuc").classList.add("gizli");

  document.querySelectorAll(".dpad [data-tasi]").forEach((b) => {
    const [ax, ay] = b.dataset.tasi.split(",").map(Number);
    b.onclick = () => {
      hiz.dx += ax * ADIM;
      hiz.dy += ay * ADIM;
      hizUygula();
    };
  });
  $("#hiz-olcek").oninput = (ev) => { hiz.scale = Number(ev.target.value); hizUygula(); };
  $("#hiz-donme").oninput = (ev) => { hiz.rotate = Number(ev.target.value); hizUygula(); };

  girdi.onchange = () => { if (girdi.files.length) hizalamaGoster([...girdi.files]); girdi.value = ""; };

  ["dragenter", "dragover"].forEach((e) =>
    alan.addEventListener(e, (ev) => { ev.preventDefault(); alan.classList.add("uzerinde"); }));
  ["dragleave", "drop"].forEach((e) =>
    alan.addEventListener(e, (ev) => { ev.preventDefault(); alan.classList.remove("uzerinde"); }));
  alan.addEventListener("drop", (ev) => {
    const f = [...(ev.dataTransfer?.files || [])].filter((x) => x.type.startsWith("image/"));
    if (f.length) hizalamaGoster(f);
  });
}

/* Kırpma bittikten sonra sonucu şablonla üst üste göster.
 * Hizalamanın gerçekten işe yarayıp yaramadığı ancak burada görülüyor —
 * panelde iyi duran bir hizalama, kırpma modelinin yine de zemini almasını
 * engellemeyebilir. */
function sonucGoster(garmentId, not) {
  $("#sonuc-foto").src = `/api/cutout/${garmentId}.png?t=${Date.now()}`;
  $("#sonuc-not").textContent = not;
  sablonuCiz();
  $("#sonuc").classList.remove("gizli");
}

async function kuyrugaAl(dosyalar, hizalama) {
  // Sırayla — paralel yüklemek aynı anda birden çok ücretli çağrı demek.
  for (let i = 0; i < dosyalar.length; i++) {
    await kiyafetYukle(dosyalar[i], i + 1, dosyalar.length, hizalama);
  }
  await dolabiYenile();
}

async function kiyafetYukle(dosya, sira, toplam, hizalama) {
  const durum = $("#yukle-durum");
  const onek = toplam > 1 ? `(${sira}/${toplam}) ` : "";
  durum.className = "alt calisiyor";
  durum.textContent = `${onek}${dosya.name} yükleniyor…`;

  const form = new FormData();
  form.append("file", dosya);
  form.append("shape", $("#sablon").value);
  const h = hizalama || HIZ_BIRIM;
  form.append("dx", h.dx);
  form.append("dy", h.dy);
  form.append("scale", h.scale);
  form.append("rotate", h.rotate);

  const cevap = await fetch("/api/garments", { method: "POST", body: form });
  if (!cevap.ok) {
    durum.className = "alt hata";
    durum.textContent = `${dosya.name}: ${(await cevap.json()).detail || "yüklenemedi"}`;
    return;
  }
  const { job_id } = await cevap.json();

  await new Promise((bitti) => {
    const bekle = setInterval(async () => {
      const j = await (await fetch(`/api/render/job/${job_id}`)).json();

      if (j.status === "running" || j.status === "pending") {
        durum.textContent = `${onek}${j.phase || "işleniyor"}…`;
        return;
      }
      clearInterval(bekle);

      if (j.status === "failed") {
        durum.className = "alt hata";
        durum.textContent = `${onek}${dosya.name}: ${j.error}`;
      } else if (j.warning) {
        durum.className = "alt uyari";
        durum.textContent = `${onek}${j.warning}`;
      } else if (!j.layer_built) {
        durum.className = "alt hata";
        durum.textContent = `${onek}Eklendi ama katman üretilemedi: ${j.error || "?"}`;
      } else if (j.note) {
        // Zayıf sinyal notu ÜRETİMİ ENGELLEMİYOR, sadece bilgilendiriyor.
        // Eskiden bu durumda katman hiç üretilmiyordu; o karar ölçümle çürüdü
        // (uzaklık 1.0'daki kıyafet sorunsuz üretildi).
        durum.className = "alt uyari";
        durum.textContent = `${onek}${dosya.name} eklendi, katmanı hazır. ${j.note}`;
      } else {
        durum.className = "alt";
        durum.textContent = `${onek}${dosya.name} eklendi ve katmanı hazır.`;
      }

      // Kırpma yapıldıysa sonucu şablonla göster — hizalamanın işe yarayıp
      // yaramadığı ancak burada anlaşılıyor. Son dosyada gösteriliyor ki
      // toplu yüklemede panel her seferinde yerinden oynamasın.
      if (j.garment_id && sira === toplam) {
        sonucGoster(
          j.garment_id,
          "Kırpma sonucu şablonun içinde kalıyorsa hizalama tuttu demektir. "
          + "Kıyafet şablonun dışına taşıyorsa yeniden hizalayıp tekrar yükle.",
        );
      }
      bitti();
    }, 1000);
  });
}

async function katmanUret(g) {
  const durum = $("#yukle-durum");
  const ad = g.subcategory || `#${g.id}`;

  if (!confirm(
    `"${ad}" için katman üretilecek.\n\n` +
    `Bu ÜCRETLİ bir çağrı (~$0.075) ve 15-40 sn sürer.\n` +
    `Kıyafet base mankenin kıyafetiyle aynı renkteyse katman boş çıkabilir.`
  )) return;

  durum.className = "alt calisiyor";
  durum.textContent = `${ad}: katman üretiliyor…`;

  const { job_id } = await (await fetch(`/api/garments/${g.id}/layer`,
                                        { method: "POST" })).json();

  const bekle = setInterval(async () => {
    const j = await (await fetch(`/api/render/job/${job_id}`)).json();
    if (j.status === "running" || j.status === "pending") return;

    clearInterval(bekle);
    if (j.layer_built) {
      durum.className = "alt";
      durum.textContent = `${ad}: katman hazır.`;
    } else {
      durum.className = "alt hata";
      durum.textContent = `${ad}: üretilemedi — ${j.error || "?"}`;
    }
    dolabiYenile();
  }, 1000);
}

/* Tek yenileme yolu: dolap + zemin + manken şeridi birlikte tazeleniyor.
 *
 * Ayrı yollar olsaydı manken geçişinden sonra katmanlar yeni mankene, zemin
 * eskisine ait olurdu — hem de sessizce, çünkü ikisi de "bir şey" gösterir.
 * Bu projede aynı sınıf hata (bir varlığın tazelenip diğerinin bayat kalması)
 * daha önce §25.7'de yaşandı. */
async function dolabiYenile() {
  const veri = await (await fetch("/api/wardrobe")).json();
  KATEGORI = veri.categories;
  KIYAFETLER = veri.garments;
  MANKEN = veri.mannequin || { id: 0, name: "" };

  // Zemin URL'si manken id'sini DE taşıyor. Sadece mtime damgası yetmezdi:
  // iki mankenin gösterim base'i aynı saniyede üretilmişse damgalar eşit
  // çıkar, URL değişmez ve tarayıcı eski mankeni göstermeye devam eder.
  // §25.7'nin kuralı — önbellek geçersizleştirmesi başlıkla değil URL ile.
  BASE_REV = veri.base_rev || 0;
  BASE_HAM_REV = veri.base_raw_rev || 0;
  zeminiSec();

  // Silinmiş ya da katmanı düşmüş olanları seçimden çıkar. Manken geçişinde
  // bu kritik: yeni mankende o kıyafetin katmanı üretilmemiş olabilir.
  for (const id of [...secili.keys()]) {
    const g = KIYAFETLER.find((x) => x.id === id);
    if (!g || !g.layer_ready) secili.delete(id);
    else secili.set(id, g);
  }
  dolabiCiz();
  guncelle();
  await mankenleriYukle();
}

/* --- Faz 4: gerçekçi görünüm ---
 *
 * Katman bindirme anında ve bedava; bu ise kıyafet başına bir VTON çağrısı,
 * yani yavaş ve ÜCRETLİ. O yüzden düğmeye basmadan önce kaç çağrı ve ne kadar
 * tutacağı yazıyor, sonuç da önbelleğe alınıyor (aynı kombin ikinci kez bedava).
 */

let renderKey = null;

function katmanaDon() {
  $("#render-img").classList.add("gizli");
  $("#katmana-don").classList.add("gizli");
  renderKey = null;
  document.querySelectorAll("#manken .katman").forEach((n) => n.classList.remove("gizli"));
}

/* Düzenleme paneli GİZLENMİYOR, kilitleniyor.
 * Gizleseydik özelliğin varlığı ancak render üretildikten sonra keşfedilirdi —
 * kullanıcı "nerede yazacağım" diye sorar. Panel duruyor, kontroller kapalı,
 * sebebi yazıyor. */
function duzenleKilitle(sebep) {
  duzenleKey = null;
  seritCiz(null);
  ["#duzenle-gonder", "#duzenle-geri", "#duzenle-ileri",
   "#duzenle-sifirla"].forEach((s) => ($(s).disabled = true));
  $("#duzenle-metin").disabled = true;
  const kap = $("#duzenle-gecmis");
  kap.className = "bos";
  kap.textContent = "Henüz düzenleme yok.";
  const bilgi = $("#duzenle-bilgi");
  bilgi.className = "alt";
  bilgi.textContent = sebep || "Önce kıyafet seç.";
}

function renderGoster(key) {
  renderKey = key;
  const img = $("#render-img");
  // Düzenleme zincirinin SONUNU göster, render'ın kendisini değil: kullanıcı
  // "kolları kıvır" dedikten sonra ekranda kıvrılmış hali kalmalı.
  img.src = `/api/edit/${key}/current.png?t=${Date.now()}`;
  img.classList.remove("gizli");
  $("#katmana-don").classList.remove("gizli");
  document.querySelectorAll("#manken .katman").forEach((n) => n.classList.add("gizli"));
  duzenleyiAc(key);
}

/* --- Düzenleme sohbeti ---
 *
 * Faz 4'ün render'ı bir FOTOĞRAF. Bu panel onun üzerinde konuşma gibi
 * çalışıyor: her talimat bir öncekinin sonucuna uygulanıyor, yani "kolları
 * kıvır" sonra "sola dön" demek ikisini birden taşıyor.
 *
 * Her adım ÜCRETLİ, o yüzden düğmenin yanında kredi yazıyor ve geri alma
 * dosyayı silmiyor — ödenmiş bir görüntüyü kaybetmek en pahalı hata türü.
 */

/* Düzenlemenin kaynağı — render'dan BAĞIMSIZ.
 *
 * "layers": katman bindirmesi, ÜCRETSİZ üretiliyor. Düzenlemek için önce
 *           ücretli bir render almak zorunlu değil (2 kredi vs 6).
 * "render":  Faz 4'ün zincirleme çıktısı. Temiz zemin, ama önce üretilmiş
 *           olması gerekiyor.
 * Takas kullanıcının; kod seçmiyor, ikisini de gösteriyor. */
let duzenleKaynak = "layers";
let duzenleKey = null;

async function duzenleKaynagiKur() {
  const bilgi = $("#duzenle-bilgi");
  if (!secili.size) {
    duzenleKilitle("Önce kıyafet seç.");
    return;
  }

  const cevap = await fetch("/api/edit/source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      garment_ids: [...secili.keys()], mode: duzenleKaynak,
    }),
  });

  if (!cevap.ok) {
    const j = await cevap.json().catch(() => ({}));
    duzenleKilitle(j.detail || "kaynak hazırlanamadı");
    return;
  }

  const d = await cevap.json();
  duzenleKey = d.key;
  $("#duzenle-metin").disabled = false;
  $("#duzenle-gonder").disabled = false;
  duzenleCiz(d);
  // Ekranda düzenlemenin uygulanacağı görüntüyü göster ki ne üzerinde
  // çalışıldığı belirsiz kalmasın.
  //
  // "render" kaynağında düzenleme olmasa DA gösteriliyor: kullanıcı açıkça
  // gerçekçi render'ı seçmişken ekranda katman bindirmesi kalması tutarsızdı.
  // "layers" kaynağında ise düzenleme yokken manken görünümü zaten doğru
  // olan — ve dosyayı boşuna ürettirmiyor (tembel üretim).
  if (d.count || duzenleKaynak === "render") duzenleGoruntuGoster();
}

function duzenleGoruntuGoster() {
  if (!duzenleKey) return;
  const img = $("#render-img");
  img.src = `/api/edit/${duzenleKey}/current.png?t=${Date.now()}`;
  img.classList.remove("gizli");
  $("#katmana-don").classList.remove("gizli");
  document.querySelectorAll("#manken .katman").forEach((n) => n.classList.add("gizli"));
}

async function duzenleyiAc(key) {
  // Render üretildi: kaynağı otomatik olarak ona çevir.
  duzenleKaynak = "render";
  document.querySelectorAll("#duzenle-kaynak button").forEach(
    (b) => b.classList.toggle("secili", b.dataset.mod === "render"));
  await duzenleKaynagiKur();
}

async function duzenleDurumYenile(key) {
  const cevap = await fetch(`/api/edit/${key}`);
  if (!cevap.ok) return;
  duzenleCiz(await cevap.json());
}

/* Film şeridi: orijinal + her düzenleme, küçük görsel olarak.
 *
 * Metin listesinden üstün olmasının sebebi para: her sürüm ÜCRETLİ üretildi.
 * Ne olduğunu GÖRMEK, prompt'u okuyup hayal etmekten iyi — ve zaten elde olan
 * bir sonucu yanlışlıkla yeniden üretmeyi engelliyor.
 *
 * Bir kareye tıklamak o sürüme DÖNÜYOR (zincir oraya sarılıyor). Sonraki
 * talimat oradan devam ediyor; düşen adımların dosyaları diskte kalıyor, yani
 * yanlış tıklamanın bedeli yok. */
function seritCiz(d) {
  const kap = $("#serit");
  if (!d || !duzenleKey) {
    kap.classList.add("gizli");
    kap.innerHTML = "";
    return;
  }

  // ÜRETİLMİŞ tüm sürümler çiziliyor (d.history), seçiliye giden yol değil.
  // Yolu çizseydik geçmişe dönen kullanıcı ileriyi göremez ve dönemezdi.
  const gecmis = d.history || d.steps || [];
  const kareler = [{ n: 0, etiket: "orijinal" },
                   ...gecmis.map((s) => ({ n: s.n, etiket: s.prompt }))];
  if (kareler.length < 2) {          // tek kare = gösterecek geçmiş yok
    kap.classList.add("gizli");
    kap.innerHTML = "";
    return;
  }

  kap.classList.remove("gizli");
  kap.innerHTML = "";
  const aktifN = d.selected ?? (d.steps.length ? d.steps[d.steps.length - 1].n : 0);

  kareler.forEach((k) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "kare" + (k.n === aktifN ? " aktif" : "");
    el.title = k.n === 0 ? "Düzenlenmemiş hâli" : k.etiket;

    const img = document.createElement("img");
    // ?w= ile küçültülmüş sürüm isteniyor: kare 62 px ama dosyalar 1.2-1.4 MB.
    // Tam boy istemek dört kare için ~5 MB indirmek demekti (telefonda §17).
    // `lazy` YOK: şerit zaten görünür alanda ve dört küçük görsel — geciktirmek
    // fayda değil, boş kare üretiyor.
    img.src = `/api/edit/${duzenleKey}/step/${k.n}.png?w=140`;
    img.alt = "";
    const et = document.createElement("span");
    et.className = "etiket";
    et.textContent = k.n === 0 ? "orijinal" : `${k.n}. ${k.etiket}`;

    el.append(img, et);
    el.onclick = () => seritSec(k.n);
    kap.appendChild(el);
  });
  kap.scrollLeft = kap.scrollWidth;
}

async function seritSec(n) {
  if (!duzenleKey) return;
  const c = await fetch(`/api/edit/${duzenleKey}/select`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ n }),
  });
  if (!c.ok) return;
  duzenleGoruntuGoster();
  duzenleDurumYenile(duzenleKey);
}

function duzenleCiz(d) {
  const key = d.key;
  seritCiz(d);

  const kap = $("#duzenle-gecmis");
  if (!d.steps.length) {
    kap.className = "bos";
    kap.textContent = "Henüz düzenleme yok.";
  } else {
    kap.className = "";
    kap.innerHTML = "";
    d.steps.forEach((s, i) => {
      const el = document.createElement("div");
      el.className = "satir" + (i === d.steps.length - 1 ? " aktif" : "");
      el.innerHTML = `<span class="sira">${s.n}.</span>`
        + `<span class="metin"></span>`;
      el.querySelector(".metin").textContent = s.prompt;
      el.title = "Bu sürüme dön";
      // Film şeridiyle AYNI davranış: tıklamak o sürüme döndürüyor.
      // (Eskiden /api/render/{key}_e1.png deniyordu ve o uç noktanın anahtar
      // deseni rakamlı eki kabul etmediği için sessizce 404 dönerdi.)
      el.onclick = () => seritSec(s.n);
      kap.appendChild(el);
    });
    kap.scrollTop = kap.scrollHeight;
  }

  $("#duzenle-geri").disabled = !d.can_undo;
  // İleri: seçili sürümün bir çocuğu varsa. Geçmişe dönüp geri gelebilmenin
  // yolu bu — eskiden geri gitmek sonraki adımların kaydını siliyordu ve
  // dönüş imkânsızdı.
  $("#duzenle-ileri").disabled = !d.can_redo;
  $("#duzenle-sifirla").disabled = !d.can_undo;
  const bilgi = $("#duzenle-bilgi");
  if (!bilgi.classList.contains("calisiyor")) {
    bilgi.className = "alt";
    const zemin = duzenleKaynak === "layers"
      ? "katman görüntüsü (zemin bedava)" : "gerçekçi render";
    bilgi.textContent =
      `${zemin} üzerine · her düzenleme ${d.credits} kredi · ~15-25 sn.`;
  }
}

async function duzenleUygula() {
  const key = duzenleKey;
  const metin = $("#duzenle-metin").value.trim();
  const bilgi = $("#duzenle-bilgi");
  if (!key || !metin) {
    bilgi.className = "alt hata";
    bilgi.textContent = "Ne değişsin, yaz.";
    return;
  }

  const dugme = $("#duzenle-gonder");
  dugme.disabled = true;
  bilgi.className = "alt calisiyor";
  bilgi.textContent = "Uygulanıyor…";

  const cevap = await fetch(`/api/edit/${key}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: metin }),
  });
  if (!cevap.ok) {
    bilgi.className = "alt hata";
    bilgi.textContent = (await cevap.json()).detail || "başlatılamadı";
    dugme.disabled = false;
    return;
  }
  const { job_id } = await cevap.json();

  let gecen = 0;
  const bekle = setInterval(async () => {
    gecen += 1.2;
    const c = await fetch(`/api/render/job/${job_id}`);
    if (c.status === 404) {         // sunucu yeniden başladı (§23.4)
      clearInterval(bekle);
      dugme.disabled = false;
      bilgi.className = "alt";
      bilgi.textContent = "Sunucu yeniden başlamış — sonuç üretildiyse ekranda.";
      duzenleGoruntuGoster();
      duzenleDurumYenile(key);
      return;
    }
    const j = await c.json();
    if (j.status === "running" || j.status === "pending") {
      bilgi.textContent = `Uygulanıyor… ${Math.round(gecen)} sn`;
      return;
    }
    clearInterval(bekle);
    dugme.disabled = false;

    if (j.status === "done") {
      $("#duzenle-metin").value = "";
      bilgi.className = "alt";
      bilgi.textContent = "Uygulandı.";
      duzenleGoruntuGoster();
      duzenleDurumYenile(key);
    } else {
      bilgi.className = "alt hata";
      bilgi.textContent = `Başarısız: ${j.error || "bilinmeyen hata"}`;
    }
  }, 1200);
}

async function duzenleKomut(yol, onay) {
  const key = duzenleKey;
  if (!key) return;
  if (onay && !confirm(onay)) return;
  const c = await fetch(`/api/edit/${key}/${yol}`, { method: "POST" });
  if (!c.ok) return;
  duzenleGoruntuGoster();
  duzenleDurumYenile(key);
}

function duzenlemeyiKur() {
  duzenleKilitle();          // seçim yokken kapalı başlasın

  document.querySelectorAll("#duzenle-kaynak button").forEach((b) => {
    b.onclick = () => {
      duzenleKaynak = b.dataset.mod;
      document.querySelectorAll("#duzenle-kaynak button").forEach(
        (x) => x.classList.toggle("secili", x === b));
      duzenleKaynagiKur();
    };
  });

  $("#duzenle-gonder").onclick = duzenleUygula;
  $("#duzenle-geri").onclick = () => duzenleKomut("undo");
  $("#duzenle-ileri").onclick = () => duzenleKomut("redo");
  $("#duzenle-sifirla").onclick = () => duzenleKomut("reset");

  document.querySelectorAll("#duzenle-oneri button").forEach((b) => {
    b.onclick = () => {
      const alan = $("#duzenle-metin");
      alan.value = alan.value.trim()
        ? `${alan.value.trim()}, ${b.dataset.p}` : b.dataset.p;
      alan.focus();
    };
  });

  // Ctrl+Enter gönderir — çok satırlı alanda Enter yeni satır olmalı.
  $("#duzenle-metin").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
      ev.preventDefault();
      duzenleUygula();
    }
  });
}

async function planiGoster() {
  const bilgi = $("#render-bilgi");
  bilgi.className = "alt";

  if (!secili.size) {
    bilgi.textContent = "Kıyafet seç.";
    $("#render").disabled = true;
    return;
  }

  const p = await (await fetch("/api/render/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ garment_ids: [...secili.keys()] }),
  })).json();

  $("#render").disabled = p.calls === 0;

  if (p.cached) {
    bilgi.textContent = "Bu kombin daha önce üretilmiş — göstermek bedava.";
    $("#render").textContent = "Gerçekçi Göster";
  } else {
    const atlanan = p.skipped.length ? `  ${p.skipped.length} kıyafet atlanacak.` : "";
    bilgi.textContent = `${p.calls} çağrı · ~$${p.cost_usd} · 30-80 sn.${atlanan}`;
    $("#render").textContent = "Gerçekçi Göster (ücretli)";
  }
}

async function gercekciGoster() {
  const bilgi = $("#render-bilgi");
  const dugme = $("#render");
  const ids = [...secili.keys()];

  dugme.disabled = true;
  bilgi.className = "alt calisiyor";
  bilgi.textContent = "Başlatılıyor…";

  const cevap = await (await fetch("/api/render", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ garment_ids: ids }),
  })).json();

  if (cevap.status === "cached") {
    renderGoster(cevap.key);
    bilgi.className = "alt";
    bilgi.textContent = "Önbellekten geldi — ücret yok.";
    dugme.disabled = false;
    return;
  }

  // İş arka planda; durumu yokla.
  let gecen = 0;
  const bekle = setInterval(async () => {
    gecen += 1.2;
    const cvp = await fetch(`/api/render/job/${cevap.job_id}`);

    // İŞ KAYBOLDU (404). İş kaydı sunucunun BELLEĞİNDE tutuluyor, yani sunucu
    // yeniden başlarsa kimlik yok oluyor. Bu gerçekten yaşandı: render sessizce
    // tamamlanmıştı ama arayüz "Başarısız" dedi, çünkü işi soramadı.
    //
    // Oysa asıl aradığımız iş değil SONUÇ — ve sonuç önbellekte olabilir.
    // Onu soruyoruz: varsa gösteriyoruz, çünkü zaten ödenmiş.
    if (cvp.status === 404) {
      clearInterval(bekle);
      dugme.disabled = false;
      const p = await (await fetch("/api/render/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ garment_ids: ids }),
      })).json();

      if (p.cached) {
        renderGoster(p.key);
        bilgi.className = "alt";
        bilgi.textContent = "Hazır — sonuç zaten üretilmişti, ücret yok.";
      } else {
        bilgi.className = "alt hata";
        bilgi.textContent =
          "Sunucu yeniden başlamış ve iş kaydı kaybolmuş. Sonuç üretilmediyse "
          + "tekrar dene.";
      }
      return;
    }

    const j = await cvp.json();

    if (j.status === "running" || j.status === "pending") {
      // Süreyi de yaz: 60 saniyedir "Giydiriliyor…" yazan bir ekran, donmuş
      // bir ekrandan ayırt edilemiyor.
      bilgi.textContent =
        `Giydiriliyor… ${j.step}/${j.total} · ${Math.round(gecen)} sn`;
      return;
    }
    clearInterval(bekle);
    dugme.disabled = false;

    if (j.status === "done") {
      renderGoster(j.key);
      bilgi.className = "alt";
      bilgi.textContent = `Hazır — ${j.calls} çağrı, ~$${j.cost_usd}.`;
    } else {
      bilgi.className = "alt hata";
      bilgi.textContent = `Başarısız: ${j.error || "bilinmeyen hata"}`;
    }
  }, 1200);
}

/* --- Dolap --- */

function dolabiCiz() {
  const kap = $("#dolap");
  kap.innerHTML = "";

  // Kategori sırası z'ye göre: üstte giyilen üstte listelensin
  const sirali = Object.keys(KATEGORI).sort((a, b) => KATEGORI[b].z - KATEGORI[a].z);

  for (const kat of sirali) {
    const grup = KIYAFETLER.filter((g) => g.category === kat);
    if (!grup.length) continue;

    const bolum = document.createElement("div");
    bolum.className = "kategori";
    bolum.innerHTML = `<h3>${KATEGORI[kat].label}</h3>`;

    const izgara = document.createElement("div");
    izgara.className = "kiyafetler";
    grup.forEach((g) => izgara.appendChild(kiyafetKarti(g)));

    bolum.appendChild(izgara);
    kap.appendChild(bolum);
  }
}

function kiyafetKarti(g) {
  const el = document.createElement("button");
  el.className = "kiyafet" + (g.layer_ready ? "" : " katmansiz");
  el.dataset.id = g.id;
  el.title = g.layer_ready
    ? `${g.subcategory} — ${g.color_name}`
    : `Katmanı yok (${g.layer_status}) — python cli.py build-layers`;

  el.innerHTML = `
    <img src="/api/cutout/${g.id}.png?v=${g.cutout_rev || 0}" alt="" loading="lazy">
    <div class="ad">${g.subcategory || KATEGORI[g.category]?.label || "?"}</div>
    <div class="renk">${g.color_name || ""}</div>
    ${g.layer_ready ? "" : '<span class="rozet">katman yok</span>'}
  `;

  el.onclick = g.layer_ready ? () => sec(g) : () => katmanUret(g);
  return el;
}

/* --- Seçim ve çakışma --- */

function cakisiyorMu(a, b) {
  const sa = KATEGORI[a]?.slots || [];
  const sb = KATEGORI[b]?.slots || [];
  return sa.some((s) => sb.includes(s));
}

function sec(g) {
  if (secili.has(g.id)) {          // ikinci tıklama çıkarır
    secili.delete(g.id);
  } else {
    // Aynı bölgeyi kaplayan seçili kıyafetler otomatik düşer.
    // Elbise hem "ust" hem "alt" kapladığı için tişört+pantolonu birlikte
    // düşürür — kural config.py'deki slots tablosundan geliyor.
    for (const [id, s] of [...secili]) {
      if (cakisiyorMu(g.category, s.category)) secili.delete(id);
    }
    secili.set(g.id, g);
  }
  guncelle();
}

/* --- Sahne --- */

/* TEK KIYAFET → HAM VTON ÇIKTISI, kombin → katman bindirmesi.
 *
 * Bindirmenin varlık sebebi birden çok kıyafeti birleştirebilmek. Tek parçada
 * hiçbir şey birleştirmiyor, sadece ÇIKARIM KUSURLARINI taşıyor: base
 * sızıntısı, kenar halkası, kör nokta. Ölçüldü — manken 2'de lacivert tişört:
 *
 *   ham çıktı        : temiz
 *   katman bindirmesi: katmanın %44.8'i base'in KENDİ tişörtü
 *
 * Ham çıktı zaten diskte (`--reextract` için saklanıyor), yani bu görünüm
 * BEDAVA: ücreti çoktan ödenmiş bir sonucu göstermiyorduk sadece.
 *
 * Kombinde ham çıktılar kullanılamaz: her biri ayrı çağrıda üretildi ve
 * base'in geri kalanını da içeriyor — üst üste konulamazlar. Orada bindirme
 * hâlâ tek ücretsiz yol. */
function hamGosterilebilir() {
  if (secili.size !== 1) return null;
  const g = [...secili.values()][0];
  return g.dressed_rev ? g : null;
}

function guncelle() {
  const manken = $("#manken");
  manken.querySelectorAll(".katman").forEach((n) => n.remove());
  zeminiSec();                 // seçim değişti → zemin de değişebilir

  const tek = hamGosterilebilir();
  if (tek) {
    const img = document.createElement("img");
    img.className = "katman ham";
    img.src = `/api/dressed/${tek.id}.png?v=${tek.dressed_rev}`;
    img.style.zIndex = "60";      // zeminin ÜSTÜNDE, tek başına
    img.alt = "";
    manken.appendChild(img);
  } else {
  // z'ye göre sırala: küçük z altta
  [...secili.values()].sort((a, b) => a.z - b.z).forEach((g) => {
    const img = document.createElement("img");
    img.className = "katman";
    // ?v= sürüm damgası: katman yeniden üretilince URL değişir ve tarayıcı
    // eski görseli bellekten servis edemez. Damga sunucudan geliyor (dosyanın
    // mtime'ı), yani dosya değişmediyse URL de değişmiyor — önbellek çalışmaya
    // devam ediyor, sadece bayatlamıyor.
    img.src = `/api/layer/${g.id}.png?v=${g.layer_rev || 0}`;
    img.style.zIndex = String(g.z);
    img.alt = "";
    manken.appendChild(img);
  });
  }

  document.querySelectorAll(".kiyafet").forEach((el) => {
    el.classList.toggle("secili", secili.has(Number(el.dataset.id)));
  });

  secimListesiCiz();

  const dolu = secili.size > 0;
  $("#kaydet").disabled = !dolu;
  $("#temizle").disabled = !dolu;

  // Kullanıcı NE GÖRDÜĞÜNÜ bilmeli: tek kıyafette ham giydirme çıktısı,
  // kombinde katman bindirmesi. İkisi farklı kalitede ve sebebi görünür olmalı,
  // yoksa "kombin yapınca neden bozuldu" sorusu cevapsız kalır.
  $("#olcum").textContent = !dolu ? ""
    : tek ? "Gerçek giydirme çıktısı — ücreti zaten ödenmişti, yeni istek yok."
    : `${secili.size} katman bindirildi — sunucuya istek gitmedi.`;

  // Seçim değişti: ekrandaki render artık başka bir kombine ait.
  katmanaDon();
  planiGoster();

  // Düzenleme kaynağı da yeni kombine göre kuruluyor. "layers"a dönülüyor
  // çünkü o her zaman var; yeni kombinin render'ı olmayabilir ve kullanıcıyı
  // kilitli bir panelle karşılamak yerine çalışan seçenekle karşılamak daha
  // iyi.
  duzenleKaynak = "layers";
  document.querySelectorAll("#duzenle-kaynak button").forEach(
    (b) => b.classList.toggle("secili", b.dataset.mod === "layers"));
  duzenleKaynagiKur();
}

function secimListesiCiz() {
  const kap = $("#secilenler");
  if (!secili.size) {
    kap.className = "bos";
    kap.textContent = "Henüz kıyafet seçmedin.";
    return;
  }
  kap.className = "";
  kap.innerHTML = "";

  [...secili.values()].sort((a, b) => b.z - a.z).forEach((g) => {
    const el = document.createElement("div");
    el.className = "secim";
    el.innerHTML = `
      <img src="/api/cutout/${g.id}.png?v=${g.cutout_rev || 0}" alt="">
      <div class="bilgi">
        <div>${g.subcategory || "?"}</div>
        <div>${KATEGORI[g.category]?.label || ""} · ${g.color_name || ""}</div>
      </div>
      <button title="Çıkar">✕</button>
    `;
    el.querySelector("button").onclick = () => { secili.delete(g.id); guncelle(); };
    kap.appendChild(el);
  });
}

/* --- Kayıtlı kombinler --- */

async function kombiniKaydet() {
  const ad = $("#ad").value.trim();
  const cevap = await fetch("/api/outfits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: ad, garment_ids: [...secili.keys()] }),
  });
  if (cevap.ok) {
    $("#ad").value = "";
    kayitlariYukle();
  }
}

async function kayitlariYukle() {
  const kayitlar = await (await fetch("/api/outfits")).json();
  const kap = $("#kayitlar");

  if (!kayitlar.length) {
    kap.className = "bos";
    kap.textContent = "Kayıtlı kombin yok.";
    return;
  }
  kap.className = "";
  kap.innerHTML = "";

  kayitlar.forEach((o) => {
    const parcalar = o.garment_ids
      .map((id) => KIYAFETLER.find((g) => g.id === id))
      .filter(Boolean);

    const el = document.createElement("div");
    el.className = "kayit";
    el.innerHTML = `
      <div class="bilgi">
        <div>${o.name || "(adsız)"}</div>
        <div>${parcalar.map((g) => g.subcategory).join(" + ") || "—"}</div>
      </div>
      <button class="ikincil" title="Sil">✕</button>
    `;
    el.onclick = () => {                       // kombini geri yükle
      secili.clear();
      parcalar.filter((g) => g.layer_ready).forEach((g) => secili.set(g.id, g));
      guncelle();
    };
    el.querySelector("button").onclick = async (e) => {
      e.stopPropagation();
      await fetch(`/api/outfits/${o.id}`, { method: "DELETE" });
      kayitlariYukle();
    };
    kap.appendChild(el);
  });
}

baslat();
