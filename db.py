"""SQLite kalıcılık katmanı (stdlib sqlite3, ORM yok).

Şema Faz 0'da kurulur ama Faz 1-3'ün tablolarını da içerir — böylece ilerledikçe
migration yazmak gerekmiyor:

  garments   : dolaptaki kıyafetler + VLM'in çıkardığı öznitelikler
  mannequins : base manken(ler). Faz 5'te kullanıcıya özel manken buraya eklenir.
  layers     : (kıyafet, manken) çifti için üretilmiş şeffaf PNG katmanı
  outfits    : kaydedilmiş kombinler
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS garments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    category            TEXT    NOT NULL,
    subcategory         TEXT    NOT NULL DEFAULT '',
    color_name          TEXT    NOT NULL DEFAULT '',
    color_hex           TEXT    NOT NULL DEFAULT '',
    secondary_color_hex TEXT    NOT NULL DEFAULT '',
    pattern             TEXT    NOT NULL DEFAULT 'düz',
    style               TEXT    NOT NULL DEFAULT 'gunluk',
    seasons             TEXT    NOT NULL DEFAULT '',   -- virgülle ayrık
    fabric              TEXT    NOT NULL DEFAULT '',
    warmth              INTEGER NOT NULL DEFAULT 5,    -- 0-10
    formality           INTEGER NOT NULL DEFAULT 5,    -- 0-10
    notes               TEXT    NOT NULL DEFAULT '',
    raw_path            TEXT    NOT NULL,
    cutout_path         TEXT    NOT NULL DEFAULT '',
    cutout_method       TEXT    NOT NULL DEFAULT '',
    attr_source         TEXT    NOT NULL DEFAULT '',   -- claude | mock
    align_json          TEXT    NOT NULL DEFAULT '',   -- hizalama: dx,dy,scale,rotate
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mannequins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL DEFAULT 'base',   -- base | personal
    image_path  TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',     -- boy/kilo/vücut tipi (Faz 5)
    -- Hangi manken üzerinde çalışılıyor. Birden çok manken yan yana yaşıyor
    -- (§28) ve aralarında geçiş HİÇBİR ŞEY SİLMİYOR — her mankenin kendi
    -- katman seti `layers` tablosunda zaten (garment_id, mannequin_id)
    -- anahtarıyla duruyor.
    is_active   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS layers (
    garment_id   INTEGER NOT NULL REFERENCES garments(id)   ON DELETE CASCADE,
    mannequin_id INTEGER NOT NULL REFERENCES mannequins(id) ON DELETE CASCADE,
    png_path     TEXT    NOT NULL DEFAULT '',
    z_index      INTEGER NOT NULL DEFAULT 0,
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|ready|failed
    error        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (garment_id, mannequin_id)
);

CREATE TABLE IF NOT EXISTS outfits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'manual',  -- manual | ai
    context    TEXT NOT NULL DEFAULT '',        -- "18 derece", "mülakat"...
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outfit_items (
    outfit_id  INTEGER NOT NULL REFERENCES outfits(id)  ON DELETE CASCADE,
    garment_id INTEGER NOT NULL REFERENCES garments(id) ON DELETE CASCADE,
    PRIMARY KEY (outfit_id, garment_id)
);

CREATE INDEX IF NOT EXISTS idx_garments_category ON garments(category);
CREATE INDEX IF NOT EXISTS idx_layers_status     ON layers(status);
"""

GARMENT_FIELDS = (
    "category", "subcategory", "color_name", "color_hex", "secondary_color_hex",
    "pattern", "style", "seasons", "fabric", "warmth", "formality", "notes",
    "raw_path", "cutout_path", "cutout_method", "attr_source", "align_json",
)

# Şema sonradan büyüdüğünde eklenen sütunlar. `CREATE TABLE IF NOT EXISTS`
# mevcut bir tabloya sütun EKLEMİYOR — yani bunlar olmadan, şemayı güncellemek
# yeni kurulumları düzeltirken var olan veritabanını sessizce eski bırakırdı.
MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("garments", "align_json", "TEXT NOT NULL DEFAULT ''"),
    ("mannequins", "is_active", "INTEGER NOT NULL DEFAULT 0"),
)


@contextmanager
def connect(db_path=None) -> Iterator[sqlite3.Connection]:
    """Row factory'li bağlantı; foreign key'ler açık, çıkışta commit."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path=None) -> None:
    """Şemayı kurar (idempotent), eksik sütunları ekler, varsayılan mankeni yazar."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _apply_migrations(conn)
        conn.execute(
            "INSERT OR IGNORE INTO mannequins (name, kind) VALUES ('base', 'base')"
        )
        _ensure_active_mannequin(conn)


def _ensure_active_mannequin(conn: sqlite3.Connection) -> int:
    """Tam olarak bir mankenin aktif olmasını garanti eder; aktif id'yi döner.

    ⚠ MEVCUT VERİYİ KORUMAK İÇİN VAR. `is_active` sonradan eklenen bir sütun ve
    varsayılanı 0 — yani migration'dan sonra var olan veritabanında HİÇBİR
    manken aktif olmaz. O durumda `get_base()` None döner, arayüz "manken yok"
    der ve ücretle üretilmiş 11 katman bir anda erişilemez görünür. Dosyalar
    yerinde duruyor olurdu; kaybolan sadece "hangisi aktif" bilgisi.

    En eskiyi (en küçük id) seçiyor: tek manken varsa o zaten mevcut base,
    yani eski kurulum aynen çalışmaya devam ediyor.
    """
    row = conn.execute(
        "SELECT id FROM mannequins WHERE is_active = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if row:
        # Birden fazla aktif kalmışsa (elle müdahale, yarım kalan geçiş)
        # tekile indir — "aktif manken" tanım gereği tek olmalı.
        conn.execute("UPDATE mannequins SET is_active = 0 WHERE id != ?", (row["id"],))
        return int(row["id"])

    ilk = conn.execute("SELECT id FROM mannequins ORDER BY id LIMIT 1").fetchone()
    if not ilk:
        return 0
    conn.execute("UPDATE mannequins SET is_active = 1 WHERE id = ?", (ilk["id"],))
    return int(ilk["id"])


def _apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Eksik sütunları ekler. Idempotent — her açılışta çalışabilir.

    Ayrı bir migration aracı yok ve gerekmiyor: SQLite'ta sütun eklemek tek
    ifade, mevcut satırlar varsayılan değeri alıyor ve işlem geri alınabilir bir
    şey silmiyor. Kural: bu listeye yalnızca DEFAULT'u olan sütunlar girer.
    """
    eklenen = []
    for table, column, ddl in MIGRATIONS:
        mevcut = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in mevcut:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            eklenen.append(f"{table}.{column}")
    return eklenen


def insert_garment(attrs: dict[str, Any], db_path=None) -> int:
    """Kıyafeti yazar, yeni id'yi döner. Bilinmeyen anahtarlar yok sayılır."""
    row = {k: attrs.get(k, "") for k in GARMENT_FIELDS}
    row["warmth"] = int(attrs.get("warmth", 5))
    row["formality"] = int(attrs.get("formality", 5))
    if isinstance(attrs.get("seasons"), (list, tuple)):
        row["seasons"] = ",".join(attrs["seasons"])

    cols = ", ".join(GARMENT_FIELDS)
    marks = ", ".join("?" for _ in GARMENT_FIELDS)
    with connect(db_path) as conn:
        cur = conn.execute(
            f"INSERT INTO garments ({cols}) VALUES ({marks})",
            [row[k] for k in GARMENT_FIELDS],
        )
        return int(cur.lastrowid)


def get_garment(garment_id: int, db_path=None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM garments WHERE id = ?", (garment_id,)
        ).fetchone()
    return dict(row) if row else None


def list_garments(category: str | None = None, db_path=None) -> list[dict]:
    """Dolabı listeler; katman sırasına (z) göre, sonra id'ye göre sıralı."""
    query = "SELECT * FROM garments"
    params: list[Any] = []
    if category:
        query += " WHERE category = ?"
        params.append(category)
    query += " ORDER BY category, id"
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def delete_garment(garment_id: int, db_path=None) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM garments WHERE id = ?", (garment_id,))
        return cur.rowcount > 0


def count_by_category(db_path=None) -> dict[str, int]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS n FROM garments GROUP BY category"
        ).fetchall()
    return {r["category"]: r["n"] for r in rows}
