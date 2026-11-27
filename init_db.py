"""Membuat schema dan mengisi data awal tanpa mengganggu data yang sudah ada."""
import sqlite3
from pathlib import Path
from database import DATABASE_PATH, DATABASE_DIR

CATEGORIES = ["Makanan", "Minuman", "Alat Tulis", "Elektronik", "Kebutuhan Harian"]
PRODUCTS = [
    ("PRD001", "Kopi Susu", "Minuman", 15000, 30),
    ("PRD002", "Americano", "Minuman", 12000, 25),
    ("PRD003", "Air Mineral", "Minuman", 5000, 50),
    ("PRD004", "Roti Cokelat", "Makanan", 8000, 20),
    ("PRD005", "Pulpen", "Alat Tulis", 3000, 100),
    ("PRD006", "Buku Tulis", "Alat Tulis", 7000, 60),
    ("PRD007", "Pensil 2B", "Alat Tulis", 2500, 80),
    ("PRD008", "Penghapus", "Alat Tulis", 2000, 70),
    ("PRD009", "Keyboard USB", "Elektronik", 85000, 12),
    ("PRD010", "Mouse Wireless", "Elektronik", 120000, 8),
    ("PRD011", "Flashdisk 32GB", "Elektronik", 75000, 15),
    ("PRD012", "Mi Instan", "Kebutuhan Harian", 3500, 45),
    ("PRD013", "Tisu Wajah", "Kebutuhan Harian", 11000, 18),
    ("PRD014", "Sabun Mandi", "Kebutuhan Harian", 6000, 35),
    ("PRD015", "Keripik Kentang", "Makanan", 10000, 5),
]


def initialize_database():
    DATABASE_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    # MATERI 3: INSERT data
    connection.executescript(schema)
    # Pastikan kolom diskon ada jika database lama sudah terbuat sebelumnya (idempotent)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(transaksi)").fetchall()]
    if "diskon" not in columns:
        connection.execute(
            "ALTER TABLE transaksi ADD COLUMN diskon INTEGER NOT NULL DEFAULT 0 CHECK (diskon >= 0)"
        )
    for category in CATEGORIES:
        connection.execute("INSERT OR IGNORE INTO kategori (nama_kategori) VALUES (?)", (category,))
    for code, name, category, price, stock in PRODUCTS:
        connection.execute(
            """INSERT OR IGNORE INTO produk
            (kode_produk, nama_produk, kategori_id, harga, stok)
            VALUES (?, ?, (SELECT id FROM kategori WHERE nama_kategori = ?), ?, ?)""",
            (code, name, category, price, stock),
        )
    # commit() menyimpan seluruh perubahan secara permanen.
    connection.commit()
    connection.close()
    print(f"Database siap: {DATABASE_PATH}")


if __name__ == "__main__":
    initialize_database()
