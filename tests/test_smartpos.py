import io
import sqlite3
import sys
from pathlib import Path
import pytest
from openpyxl import load_workbook

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import app as smartpos_app
import database
import init_db


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Menyiapkan database, folder exports, dan backups terisolasi untuk setiap pengujian."""
    db_dir = tmp_path / "database"
    db_path = db_dir / "smartpos.db"
    export_dir = tmp_path / "exports"
    backup_dir = tmp_path / "backups"
    export_dir.mkdir(exist_ok=True)
    backup_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(database, "DATABASE_DIR", db_dir)
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    monkeypatch.setattr(init_db, "DATABASE_DIR", db_dir)
    monkeypatch.setattr(init_db, "DATABASE_PATH", db_path)
    monkeypatch.setattr(smartpos_app, "DATABASE_PATH", db_path)
    monkeypatch.setattr(smartpos_app, "EXPORT_DIR", export_dir)
    monkeypatch.setattr(smartpos_app, "BACKUP_DIR", backup_dir)

    init_db.initialize_database()
    smartpos_app.app.config["TESTING"] = True
    client = smartpos_app.app.test_client()
    return client, db_path, export_dir, backup_dir


def test_01_db_created_from_scratch(isolated_env):
    """(1) Database berhasil dibuat dari awal beserta tabel dan kolom diskon."""
    _, db_path, _, _ = isolated_env
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"kategori", "produk", "transaksi", "detail_transaksi"}.issubset(tables)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transaksi)").fetchall()}
    assert "diskon" in cols
    conn.close()


def test_02_seed_idempotent(isolated_env):
    """(2) Seed dijalankan berulang tanpa duplikasi data."""
    _, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    count_cat_1 = conn.execute("SELECT COUNT(*) FROM kategori").fetchone()[0]
    count_prod_1 = conn.execute("SELECT COUNT(*) FROM produk").fetchone()[0]
    conn.close()

    init_db.initialize_database()
    init_db.initialize_database()

    conn = sqlite3.connect(db_path)
    count_cat_2 = conn.execute("SELECT COUNT(*) FROM kategori").fetchone()[0]
    count_prod_2 = conn.execute("SELECT COUNT(*) FROM produk").fetchone()[0]
    conn.close()

    assert count_cat_1 == count_cat_2 == len(init_db.CATEGORIES)
    assert count_prod_1 == count_prod_2 == len(init_db.PRODUCTS)


def test_03_product_crud(isolated_env):
    """(3) Produk bisa tambah, tampil, ubah, dan hapus."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    cat_id = conn.execute("SELECT id FROM kategori LIMIT 1").fetchone()[0]
    conn.close()

    # Tambah
    res_add = client.post(
        "/produk/tambah",
        data={"kode_produk": "PRD901", "nama_produk": "Espresso Tonic", "kategori_id": cat_id, "harga": 22000, "stok": 15},
        follow_redirects=True,
    )
    assert res_add.status_code == 200
    assert b"Espresso Tonic" in res_add.data

    conn = sqlite3.connect(db_path)
    prod_id = conn.execute("SELECT id FROM produk WHERE kode_produk='PRD901'").fetchone()[0]
    conn.close()

    # Ubah
    res_edit = client.post(
        f"/produk/edit/{prod_id}",
        data={"nama_produk": "Espresso Tonic Mint", "kategori_id": cat_id, "harga": 25000, "stok": 18},
        follow_redirects=True,
    )
    assert res_edit.status_code == 200
    assert b"Espresso Tonic Mint" in res_edit.data

    # Hapus
    res_del = client.post(f"/produk/hapus/{prod_id}", follow_redirects=True)
    assert res_del.status_code == 200
    conn = sqlite3.connect(db_path)
    exists = conn.execute("SELECT COUNT(*) FROM produk WHERE id=?", (prod_id,)).fetchone()[0]
    conn.close()
    assert exists == 0


def test_04_duplicate_product_code_rejected(isolated_env):
    """(4) Kode produk duplikat ditolak."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    cat_id = conn.execute("SELECT id FROM kategori LIMIT 1").fetchone()[0]
    conn.close()

    res = client.post(
        "/produk/tambah",
        data={"kode_produk": "PRD001", "nama_produk": "Kopi Duplikat", "kategori_id": cat_id, "harga": 10000, "stok": 5},
        follow_redirects=True,
    )
    assert b"Kode duplikat" in res.data


def test_05_search_and_filter_work(isolated_env):
    """(5) Pencarian dan filter produk bekerja."""
    client, db_path, _, _ = isolated_env
    res_q = client.get("/produk?q=Kopi")
    assert res_q.status_code == 200
    assert b"Kopi Susu" in res_q.data
    assert b"Pulpen" not in res_q.data

    res_low = client.get("/produk?stok_rendah=on")
    assert res_low.status_code == 200
    assert b"Keripik Kentang" in res_low.data  # stok awal 5


def test_06_multi_product_transaction_and_discount(isolated_env):
    """(6) Transaksi >1 produk berhasil dan validasi diskon backend berjalan."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    p1 = conn.execute("SELECT id, harga FROM produk WHERE kode_produk='PRD001'").fetchone()  # 15000
    p2 = conn.execute("SELECT id, harga FROM produk WHERE kode_produk='PRD004'").fetchone()  # 8000
    conn.close()

    # Subtotal: 15000*2 + 8000*1 = 38000, diskon 3000 -> total 35000, bayar 50000 -> kembalian 15000
    res = client.post(
        "/kasir/checkout",
        data={"items": f"{p1[0]}:2,{p2[0]}:1", "diskon": "3000", "jumlah_bayar": "50000"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Transaksi berhasil disimpan" in res.data

    conn = sqlite3.connect(db_path)
    trx = conn.execute("SELECT diskon, total_harga, jumlah_bayar, kembalian FROM transaksi ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert trx == (3000, 35000, 50000, 15000)

    # Diskon negatif ditolak
    res_neg = client.post(
        "/kasir/checkout",
        data={"items": f"{p1[0]}:1", "diskon": "-500", "jumlah_bayar": "20000"},
        follow_redirects=True,
    )
    assert b"Diskon tidak boleh bernilai negatif" in res_neg.data

    # Diskon melebihi subtotal ditolak
    res_over = client.post(
        "/kasir/checkout",
        data={"items": f"{p1[0]}:1", "diskon": "50000", "jumlah_bayar": "50000"},
        follow_redirects=True,
    )
    assert b"Diskon tidak boleh melebihi subtotal belanja" in res_over.data


def test_07_stock_decreases_after_purchase(isolated_env):
    """(7) Stok berkurang sesuai jumlah pembelian."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    pid, stok_awal = conn.execute("SELECT id, stok FROM produk WHERE kode_produk='PRD002'").fetchone()
    conn.close()

    client.post("/kasir/checkout", data={"items": f"{pid}:3", "diskon": "0", "jumlah_bayar": "50000"})
    conn = sqlite3.connect(db_path)
    stok_akhir = conn.execute("SELECT stok FROM produk WHERE id=?", (pid,)).fetchone()[0]
    conn.close()
    assert stok_akhir == stok_awal - 3


def test_08_insufficient_stock_rejected(isolated_env):
    """(8) Stok kurang menyebabkan transaksi ditolak."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    pid, stok_awal = conn.execute("SELECT id, stok FROM produk WHERE kode_produk='PRD015'").fetchone()  # stok 5
    conn.close()

    res = client.post(
        "/kasir/checkout",
        data={"items": f"{pid}:{stok_awal + 10}", "diskon": "0", "jumlah_bayar": "500000"},
        follow_redirects=True,
    )
    assert b"tidak mencukupi" in res.data


def test_09_insufficient_payment_rejected(isolated_env):
    """(9) Pembayaran kurang dari total transaksi ditolak."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    pid, harga = conn.execute("SELECT id, harga FROM produk WHERE kode_produk='PRD001'").fetchone()
    conn.close()

    res = client.post(
        "/kasir/checkout",
        data={"items": f"{pid}:1", "diskon": "0", "jumlah_bayar": str(harga - 1000)},
        follow_redirects=True,
    )
    assert b"Uang pembayaran kurang" in res.data


def test_10_rollback_cancels_all_changes_on_failure(isolated_env):
    """(10) Rollback membatalkan seluruh perubahan jika salah satu item gagal di tengah checkout."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    p1 = conn.execute("SELECT id, stok FROM produk WHERE kode_produk='PRD003'").fetchone()
    p2 = conn.execute("SELECT id, stok FROM produk WHERE kode_produk='PRD015'").fetchone()
    trx_before = conn.execute("SELECT COUNT(*) FROM transaksi").fetchone()[0]
    conn.close()

    # p1 valid (qty 2), p2 gagal (qty melebihi stok)
    client.post(
        "/kasir/checkout",
        data={"items": f"{p1[0]}:2,{p2[0]}:{p2[1] + 5}", "diskon": "0", "jumlah_bayar": "500000"},
    )

    conn = sqlite3.connect(db_path)
    p1_after = conn.execute("SELECT stok FROM produk WHERE id=?", (p1[0],)).fetchone()[0]
    trx_after = conn.execute("SELECT COUNT(*) FROM transaksi").fetchone()[0]
    conn.close()
    assert p1_after == p1[1]
    assert trx_after == trx_before


def test_11_history_preserves_snapshot_after_product_edit(isolated_env):
    """(11) Riwayat transaksi tetap menyimpan nama dan harga lama meski produk diedit."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    p = conn.execute("SELECT id, kategori_id, nama_produk, harga FROM produk WHERE kode_produk='PRD005'").fetchone()
    conn.close()

    client.post("/kasir/checkout", data={"items": f"{p[0]}:2", "diskon": "0", "jumlah_bayar": "10000"})
    conn = sqlite3.connect(db_path)
    trx_id = conn.execute("SELECT id FROM transaksi ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()

    # Edit nama dan harga produk
    client.post(
        f"/produk/edit/{p[0]}",
        data={"nama_produk": "Pulpen Gel Premium", "kategori_id": p[1], "harga": p[3] + 5000, "stok": 50},
    )

    res = client.get(f"/transaksi/{trx_id}")
    assert res.status_code == 200
    assert p[2].encode() in res.data  # Nama lama tetap tampil
    assert b"Rp3.000" in res.data      # Harga lama tetap tampil


def test_12_export_excel_valid_with_product_recap(isolated_env):
    """(12) Export Excel menghasilkan file valid dengan sheet Rekap per Produk dan kolom Diskon."""
    client, db_path, _, _ = isolated_env
    conn = sqlite3.connect(db_path)
    pid = conn.execute("SELECT id FROM produk WHERE kode_produk='PRD001'").fetchone()[0]
    conn.close()

    client.post("/kasir/checkout", data={"items": f"{pid}:2", "diskon": "2000", "jumlah_bayar": "30000"})

    res = client.get("/transaksi/export")
    assert res.status_code == 200
    wb = load_workbook(io.BytesIO(res.data))
    assert "Ringkasan Transaksi" in wb.sheetnames
    assert "Detail Penjualan" in wb.sheetnames
    assert "Rekap per Produk" in wb.sheetnames

    summary_headers = [c.value for c in wb["Ringkasan Transaksi"][1]]
    assert "Diskon" in summary_headers
    recap_rows = list(wb["Rekap per Produk"].iter_rows(min_row=2, values_only=True))
    assert any(r[1] == "Kopi Susu" and r[2] == 2 for r in recap_rows if r[1])


def test_13_backup_created_and_downloadable(isolated_env):
    """(13) Backup database berhasil dibuat dengan Connection.backup() dan dapat diunduh."""
    client, _, _, backup_dir = isolated_env
    res_create = client.post("/backup/create", follow_redirects=True)
    assert res_create.status_code == 200
    assert b"Backup berhasil dibuat" in res_create.data

    files = list(backup_dir.glob("*.db"))
    assert len(files) == 1
    res_dl = client.get(f"/backup/download/{files[0].name}")
    assert res_dl.status_code == 200
    assert len(res_dl.data) > 0


def test_14_all_main_menus_accessible(isolated_env):
    """(14) Semua menu utama dapat diakses tanpa error (HTTP 200) termasuk dashboard 5 produk terlaris."""
    client, _, _, _ = isolated_env
    for route in ["/", "/kasir", "/produk", "/produk/tambah", "/kategori", "/transaksi", "/backup"]:
        res = client.get(route)
        assert res.status_code == 200, f"Route {route} gagal dengan status {res.status_code}"
