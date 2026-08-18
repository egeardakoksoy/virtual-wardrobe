"""SQLite katmanı — şema, CRUD ve savunmacı davranışlar."""
from __future__ import annotations

from db import (
    connect,
    count_by_category,
    delete_garment,
    get_garment,
    init_db,
    insert_garment,
    list_garments,
)


def _attrs(**over) -> dict:
    base = {
        "category": "ust", "subcategory": "tişört", "color_name": "beyaz",
        "color_hex": "#FFFFFF", "secondary_color_hex": "", "pattern": "düz",
        "style": "gunluk", "seasons": ["yaz", "ilkbahar"], "fabric": "pamuk",
        "warmth": 3, "formality": 2, "notes": "", "raw_path": "data/raw/a.jpg",
        "cutout_path": "data/cutout/a.png", "cutout_method": "flood",
        "attr_source": "mock",
    }
    return base | over


def test_init_idempotent(tmp_path):
    """İki kez kurmak hata vermemeli, mükerrer manken üretmemeli."""
    path = tmp_path / "x.db"
    init_db(path)
    init_db(path)
    with connect(path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM mannequins").fetchone()[0]
    assert n == 1


def test_varsayilan_manken_olusur(db_path):
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM mannequins WHERE name='base'").fetchone()
    assert row["kind"] == "base"


def test_ekle_ve_oku(db_path):
    gid = insert_garment(_attrs(), db_path=db_path)
    row = get_garment(gid, db_path=db_path)
    assert row["subcategory"] == "tişört"
    assert row["warmth"] == 3


def test_mevsim_listesi_virgullu_metne_cevrilir(db_path):
    gid = insert_garment(_attrs(seasons=["yaz", "ilkbahar"]), db_path=db_path)
    assert get_garment(gid, db_path=db_path)["seasons"] == "yaz,ilkbahar"


def test_bilinmeyen_alanlar_yoksayilir(db_path):
    """VLM şemaya sadık ama ileride alan eklenirse INSERT patlamamalı."""
    gid = insert_garment(_attrs(marka="Zara", fiyat=499), db_path=db_path)
    assert get_garment(gid, db_path=db_path) is not None


def test_eksik_alanlar_varsayilana_duser(db_path):
    gid = insert_garment({"raw_path": "a.jpg", "category": "alt"}, db_path=db_path)
    row = get_garment(gid, db_path=db_path)
    assert row["warmth"] == 5 and row["formality"] == 5


def test_kategoriye_gore_listeleme(db_path):
    insert_garment(_attrs(category="ust"), db_path=db_path)
    insert_garment(_attrs(category="alt"), db_path=db_path)
    insert_garment(_attrs(category="alt"), db_path=db_path)

    assert len(list_garments(db_path=db_path)) == 3
    assert len(list_garments(category="alt", db_path=db_path)) == 2


def test_sayim(db_path):
    insert_garment(_attrs(category="ust"), db_path=db_path)
    insert_garment(_attrs(category="ayakkabi"), db_path=db_path)
    assert count_by_category(db_path=db_path) == {"ust": 1, "ayakkabi": 1}


def test_silme(db_path):
    gid = insert_garment(_attrs(), db_path=db_path)
    assert delete_garment(gid, db_path=db_path)
    assert get_garment(gid, db_path=db_path) is None
    assert not delete_garment(gid, db_path=db_path)


def test_olmayan_kayit_none_doner(db_path):
    assert get_garment(9999, db_path=db_path) is None


def test_katman_silinen_kiyafetle_birlikte_gider(db_path):
    """ON DELETE CASCADE + PRAGMA foreign_keys açık mı?"""
    gid = insert_garment(_attrs(), db_path=db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO layers (garment_id, mannequin_id, z_index) VALUES (?, 1, 30)",
            (gid,),
        )
    delete_garment(gid, db_path=db_path)
    with connect(db_path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM layers").fetchone()[0]
    assert n == 0
