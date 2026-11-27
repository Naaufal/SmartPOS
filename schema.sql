-- MATERI 2: CREATE TABLE dan constraint
-- MATERI 9: PRIMARY KEY dan FOREIGN KEY
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS kategori (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_kategori TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS produk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kode_produk TEXT NOT NULL UNIQUE,
    nama_produk TEXT NOT NULL,
    kategori_id INTEGER NOT NULL,
    harga INTEGER NOT NULL CHECK (harga >= 0),
    stok INTEGER NOT NULL CHECK (stok >= 0),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (kategori_id) REFERENCES kategori(id) ON DELETE RESTRICT ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS transaksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kode_transaksi TEXT NOT NULL UNIQUE,
    tanggal_transaksi TEXT NOT NULL,
    diskon INTEGER NOT NULL DEFAULT 0 CHECK (diskon >= 0),
    total_harga INTEGER NOT NULL CHECK (total_harga >= 0),
    jumlah_bayar INTEGER NOT NULL CHECK (jumlah_bayar >= total_harga),
    kembalian INTEGER NOT NULL CHECK (kembalian >= 0)
);

CREATE TABLE IF NOT EXISTS detail_transaksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaksi_id INTEGER NOT NULL,
    produk_id INTEGER NOT NULL,
    nama_produk TEXT NOT NULL,
    harga_satuan INTEGER NOT NULL CHECK (harga_satuan >= 0),
    jumlah INTEGER NOT NULL CHECK (jumlah > 0),
    subtotal INTEGER NOT NULL CHECK (subtotal >= 0),
    FOREIGN KEY (transaksi_id) REFERENCES transaksi(id) ON DELETE RESTRICT,
    FOREIGN KEY (produk_id) REFERENCES produk(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_transaksi_tanggal ON transaksi(tanggal_transaksi);
CREATE INDEX IF NOT EXISTS idx_produk_kategori ON produk(kategori_id);
CREATE INDEX IF NOT EXISTS idx_detail_transaksi ON detail_transaksi(transaksi_id);
CREATE INDEX IF NOT EXISTS idx_detail_produk ON detail_transaksi(produk_id);
