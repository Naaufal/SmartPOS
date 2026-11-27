import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from database import get_db_connection, DATABASE_PATH, BASE_DIR

app = Flask(__name__)
app.secret_key = os.environ.get("SMARTPOS_SECRET_KEY", "smartpos-development-key")
EXPORT_DIR = BASE_DIR / "exports"
BACKUP_DIR = BASE_DIR / "backups"
EXPORT_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)


def rupiah(value):
    return f"Rp{int(value or 0):,}".replace(",", ".")


def format_ts(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%d %b %Y, %H:%M")


app.jinja_env.filters["rupiah"] = rupiah
app.jinja_env.filters["format_ts"] = format_ts


def read_int(form, field, label, minimum=0):
    try:
        value = int(form.get(field, ""))
        if value < minimum:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ValueError(f"{label} harus berupa angka minimal {minimum}.")


@app.route("/")
def dashboard():
    db = get_db_connection()
    # Menghitung total jenis produk dan akumulasi seluruh stok yang tersedia
    stats = db.execute(
        "SELECT COUNT(*) AS total_produk, COALESCE(SUM(stok), 0) AS total_stok FROM produk"
    ).fetchone()
    today = datetime.now().strftime("%Y-%m-%d")
    # Menghitung jumlah transaksi dan total pendapatan khusus hari ini menggunakan parameterized query
    today_stats = db.execute(
        "SELECT COUNT(*) AS jumlah, COALESCE(SUM(total_harga), 0) AS pendapatan "
        "FROM transaksi WHERE date(tanggal_transaksi) = ?",
        (today,),
    ).fetchone()
    # Mengambil daftar produk dengan stok menipis (<= 5) beserta nama kategorinya via INNER JOIN
    low_stock = db.execute(
        "SELECT p.*, k.nama_kategori FROM produk p "
        "INNER JOIN kategori k ON k.id = p.kategori_id "
        "WHERE p.stok <= 5 ORDER BY p.stok, p.nama_produk"
    ).fetchall()
    # Mengambil 5 transaksi paling baru berdasarkan tanggal dan id terbaru
    latest = db.execute(
        "SELECT * FROM transaksi ORDER BY tanggal_transaksi DESC, id DESC LIMIT 5"
    ).fetchall()
    # Mengambil 5 produk terlaris berdasarkan total kuantitas terjual di detail_transaksi
    top_products = db.execute(
        "SELECT d.produk_id, d.nama_produk, "
        "SUM(d.jumlah) AS total_terjual, "
        "SUM(d.subtotal) AS total_pendapatan "
        "FROM detail_transaksi d "
        "GROUP BY d.produk_id, d.nama_produk "
        "ORDER BY total_terjual DESC, total_pendapatan DESC "
        "LIMIT 5"
    ).fetchall()
    db.close()
    return render_template(
        "dashboard.html",
        stats=stats,
        today_stats=today_stats,
        low_stock=low_stock,
        latest=latest,
        top_products=top_products,
    )


@app.route("/kategori")
def kategori():
    db = get_db_connection()
    rows = db.execute("SELECT k.*, COUNT(p.id) AS jumlah_produk FROM kategori k LEFT JOIN produk p ON p.kategori_id = k.id GROUP BY k.id ORDER BY k.nama_kategori").fetchall()
    db.close()
    return render_template("kategori.html", categories=rows)


@app.post("/kategori/tambah")
def kategori_tambah():
    name = request.form.get("nama_kategori", "").strip()
    if not name:
        flash("Nama kategori wajib diisi.", "danger")
    else:
        db = get_db_connection()
        try:
            db.execute("INSERT INTO kategori (nama_kategori) VALUES (?)", (name,)); db.commit(); flash("Kategori berhasil ditambahkan.", "success")
        except sqlite3.IntegrityError: flash("Nama kategori sudah digunakan.", "danger")
        finally: db.close()
    return redirect(url_for("kategori"))


@app.post("/kategori/edit/<int:category_id>")
def kategori_edit(category_id):
    name = request.form.get("nama_kategori", "").strip()
    db = get_db_connection()
    try:
        db.execute("UPDATE kategori SET nama_kategori = ? WHERE id = ?", (name, category_id)); db.commit(); flash("Kategori berhasil diubah.", "success")
    except sqlite3.IntegrityError: flash("Nama kategori kosong atau sudah digunakan.", "danger")
    finally: db.close()
    return redirect(url_for("kategori"))


@app.post("/kategori/hapus/<int:category_id>")
def kategori_hapus(category_id):
    db = get_db_connection()
    used = db.execute("SELECT COUNT(*) AS jumlah FROM produk WHERE kategori_id = ?", (category_id,)).fetchone()["jumlah"]
    if used:
        flash("Kategori tidak dapat dihapus karena masih digunakan produk.", "danger")
    else:
        db.execute("DELETE FROM kategori WHERE id = ?", (category_id,)); db.commit(); flash("Kategori berhasil dihapus.", "success")
    db.close(); return redirect(url_for("kategori"))


def product_form(product=None):
    db = get_db_connection(); categories = db.execute("SELECT * FROM kategori ORDER BY nama_kategori").fetchall(); db.close()
    return render_template("produk_form.html", product=product, categories=categories)


@app.route("/produk")
def produk():
    keyword = request.args.get("q", "").strip(); category = request.args.get("kategori", ""); low = request.args.get("stok_rendah", ""); sort = request.args.get("sort", "nama")
    allowed = {"nama": "p.nama_produk ASC", "harga_asc": "p.harga ASC", "harga_desc": "p.harga DESC", "stok": "p.stok ASC"}
    clauses, params = [], []
    if keyword: clauses.append("(p.kode_produk LIKE ? OR p.nama_produk LIKE ?)"); params += [f"%{keyword}%", f"%{keyword}%"]
    if category.isdigit(): clauses.append("p.kategori_id = ?"); params.append(int(category))
    if low: clauses.append("p.stok <= 5")
    sql = "SELECT p.*, k.nama_kategori FROM produk p INNER JOIN kategori k ON p.kategori_id = k.id"
    if clauses: sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY " + allowed.get(sort, allowed["nama"])
    db = get_db_connection(); products = db.execute(sql, params).fetchall(); categories = db.execute("SELECT * FROM kategori ORDER BY nama_kategori").fetchall(); db.close()
    return render_template("produk.html", products=products, categories=categories, q=keyword, selected_category=category, low=low, sort=sort)


@app.route("/produk/tambah", methods=["GET", "POST"])
def produk_tambah():
    if request.method == "GET": return product_form()
    try:
        code, name = request.form.get("kode_produk", "").strip(), request.form.get("nama_produk", "").strip()
        category = read_int(request.form, "kategori_id", "Kategori", 1); price = read_int(request.form, "harga", "Harga"); stock = read_int(request.form, "stok", "Stok")
        if not code or not name: raise ValueError("Kode dan nama produk wajib diisi.")
        db = get_db_connection(); db.execute("INSERT INTO produk (kode_produk, nama_produk, kategori_id, harga, stok) VALUES (?, ?, ?, ?, ?)", (code, name, category, price, stock)); db.commit(); db.close(); flash("Produk berhasil ditambahkan.", "success"); return redirect(url_for("produk"))
    except (ValueError, sqlite3.IntegrityError) as error: flash("Gagal menambah produk: " + ("Kode duplikat atau kategori tidak valid." if isinstance(error, sqlite3.IntegrityError) else str(error)), "danger"); return product_form()


@app.route("/produk/edit/<int:product_id>", methods=["GET", "POST"])
def produk_edit(product_id):
    db = get_db_connection(); product = db.execute("SELECT * FROM produk WHERE id = ?", (product_id,)).fetchone(); db.close()
    if not product: flash("Produk tidak ditemukan.", "danger"); return redirect(url_for("produk"))
    if request.method == "GET": return product_form(product)
    try:
        name = request.form.get("nama_produk", "").strip(); category = read_int(request.form, "kategori_id", "Kategori", 1); price = read_int(request.form, "harga", "Harga"); stock = read_int(request.form, "stok", "Stok")
        if not name: raise ValueError("Nama produk wajib diisi.")
        db = get_db_connection(); db.execute("UPDATE produk SET nama_produk = ?, kategori_id = ?, harga = ?, stok = ? WHERE id = ?", (name, category, price, stock, product_id)); db.commit(); db.close(); flash("Produk berhasil diubah.", "success"); return redirect(url_for("produk"))
    except (ValueError, sqlite3.IntegrityError) as error: flash("Gagal mengubah produk: " + str(error), "danger"); return product_form(product)


@app.post("/produk/hapus/<int:product_id>")
def produk_hapus(product_id):
    db = get_db_connection()
    try: db.execute("DELETE FROM produk WHERE id = ?", (product_id,)); db.commit(); flash("Produk berhasil dihapus.", "success")
    except sqlite3.IntegrityError: flash("Produk tidak dapat dihapus karena memiliki riwayat transaksi.", "danger")
    finally: db.close()
    return redirect(url_for("produk"))


@app.route("/kasir")
def kasir():
    db = get_db_connection()
    # Mengambil produk yang stoknya masih tersedia (> 0) beserta nama kategorinya untuk ditampilkan di kasir
    products = db.execute(
        "SELECT p.*, k.nama_kategori FROM produk p "
        "INNER JOIN kategori k ON k.id = p.kategori_id "
        "WHERE p.stok > 0 ORDER BY p.nama_produk"
    ).fetchall()
    db.close()
    return render_template("kasir.html", products=products)


@app.post("/kasir/checkout")
def checkout():
    try:
        items = request.form.get("items", "")
        raw_discount = request.form.get("diskon", "").strip()
        try:
            discount = int(raw_discount) if raw_discount != "" else 0
        except (TypeError, ValueError):
            raise ValueError("Diskon harus berupa angka bulat.")
        if discount < 0:
            raise ValueError("Diskon tidak boleh bernilai negatif.")

        try:
            payment = int(request.form.get("jumlah_bayar", "0"))
        except (TypeError, ValueError):
            raise ValueError("Jumlah bayar harus berupa angka bulat.")

        requested = {}
        for part in items.split(","):
            if part:
                pid, qty = part.split(":")
                requested[int(pid)] = requested.get(int(pid), 0) + int(qty)
        if not requested:
            raise ValueError("Keranjang masih kosong.")
        if any(qty <= 0 for qty in requested.values()):
            raise ValueError("Jumlah pembelian tidak valid.")

        db = get_db_connection()
        # Memulai transaksi database eksklusif agar pengecekan dan pengurangan stok bersifat atomik
        db.execute("BEGIN IMMEDIATE")
        verified = []
        for pid, qty in requested.items():
            # Mengambil data harga dan stok terbaru langsung dari database (bukan dari browser)
            product = db.execute("SELECT * FROM produk WHERE id = ?", (pid,)).fetchone()
            if not product:
                raise ValueError("Produk tidak tersedia.")
            if product["stok"] < qty:
                raise ValueError(f"Stok {product['nama_produk']} tidak mencukupi.")
            verified.append((product, qty))

        # Menghitung ulang subtotal, validasi diskon, total akhir, dan kembalian di server
        subtotal = sum(product["harga"] * qty for product, qty in verified)
        if discount > subtotal:
            raise ValueError("Diskon tidak boleh melebihi subtotal belanja.")
        total = subtotal - discount
        if payment < total:
            raise ValueError("Uang pembayaran kurang dari total transaksi.")
        kembalian = payment - total

        code = "TRX-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
        # Menyimpan header transaksi termasuk nilai diskon yang sudah tervalidasi
        cursor = db.execute(
            "INSERT INTO transaksi (kode_transaksi, tanggal_transaksi, diskon, total_harga, jumlah_bayar, kembalian) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (code, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), discount, total, payment, kembalian),
        )
        transaction_id = cursor.lastrowid
        for product, qty in verified:
            # Menyimpan snapshot nama_produk dan harga_satuan ke detail_transaksi agar riwayat tetap akurat
            db.execute(
                "INSERT INTO detail_transaksi (transaksi_id, produk_id, nama_produk, harga_satuan, jumlah, subtotal) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (transaction_id, product["id"], product["nama_produk"], product["harga"], qty, product["harga"] * qty),
            )
            # Mengurangi stok secara aman dengan syarat stok >= qty
            updated = db.execute(
                "UPDATE produk SET stok = stok - ? WHERE id = ? AND stok >= ?",
                (qty, product["id"], qty),
            )
            if updated.rowcount != 1:
                raise ValueError("Stok berubah dan tidak mencukupi.")

        # COMMIT menyimpan seluruh perubahan secara permanen jika semua langkah berhasil
        db.commit()
        db.close()
        flash("Transaksi berhasil disimpan.", "success")
        return redirect(url_for("transaksi_detail", transaction_id=transaction_id))
    except Exception as error:
        # ROLLBACK membatalkan semua perubahan jika terjadi kesalahan di tengah proses
        if "db" in locals():
            db.rollback()
            db.close()
        flash("Transaksi gagal: " + str(error), "danger")
        return redirect(url_for("kasir"))


def transaction_filters(prefix=""):
    code = request.args.get("kode", "").strip()
    start = request.args.get("mulai", "")
    end = request.args.get("sampai", "")
    clauses, params = [], []
    if code:
        clauses.append(f"{prefix}kode_transaksi LIKE ?")
        params.append(f"%{code}%")
    if start:
        clauses.append(f"date({prefix}tanggal_transaksi) >= ?")
        params.append(start)
    if end:
        clauses.append(f"date({prefix}tanggal_transaksi) <= ?")
        params.append(end)
    return code, start, end, clauses, params


@app.route("/transaksi")
def transaksi():
    code, start, end, clauses, params = transaction_filters()
    sql = (
        "SELECT * FROM transaksi"
        + ((" WHERE " + " AND ".join(clauses)) if clauses else "")
        + " ORDER BY tanggal_transaksi DESC, id DESC"
    )
    db = get_db_connection()
    rows = db.execute(sql, params).fetchall()
    db.close()
    return render_template("transaksi.html", transactions=rows, code=code, start=start, end=end)


@app.route("/transaksi/<int:transaction_id>")
def transaksi_detail(transaction_id):
    db = get_db_connection()
    transaction = db.execute("SELECT * FROM transaksi WHERE id = ?", (transaction_id,)).fetchone()
    # Mengambil detail item transaksi digabungkan dengan kode_produk dari tabel produk menggunakan INNER JOIN
    details = db.execute(
        "SELECT d.*, p.kode_produk FROM detail_transaksi d "
        "INNER JOIN produk p ON p.id = d.produk_id "
        "WHERE d.transaksi_id = ?",
        (transaction_id,),
    ).fetchall()
    db.close()
    if not transaction:
        flash("Transaksi tidak ditemukan.", "danger")
        return redirect(url_for("transaksi"))
    return render_template("transaksi_detail.html", transaction=transaction, details=details)


def make_excel(rows, details, product_recap):
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Ringkasan Transaksi"
    detail_sheet = workbook.create_sheet("Detail Penjualan")
    recap_sheet = workbook.create_sheet("Rekap per Produk")

    # Sheet 1: Ringkasan Transaksi (menyertakan Subtotal dan Diskon)
    headers = ["Nomor", "Kode transaksi", "Tanggal", "Subtotal", "Diskon", "Total harga", "Jumlah bayar", "Kembalian"]
    summary.append(headers)
    for number, row in enumerate(rows, 1):
        subtotal_val = row["total_harga"] + row["diskon"]
        summary.append([
            number,
            row["kode_transaksi"],
            row["tanggal_transaksi"],
            subtotal_val,
            row["diskon"],
            row["total_harga"],
            row["jumlah_bayar"],
            row["kembalian"],
        ])

    # Sheet 2: Detail Penjualan
    detail_sheet.append(["Kode transaksi", "Tanggal", "Nama produk", "Harga satuan", "Jumlah", "Subtotal"])
    for row in details:
        detail_sheet.append(list(row))

    # Sheet 3: Rekap per Produk
    recap_sheet.append(["Nomor", "Nama produk", "Jumlah terjual", "Total pendapatan"])
    for number, row in enumerate(product_recap, 1):
        recap_sheet.append([number, row["nama_produk"], row["jumlah_terjual"], row["total_pendapatan"]])

    # Styling seragam dengan tema warm espresso (#4A2E1B)
    header_fill = PatternFill("solid", fgColor="4A2E1B")
    thin = Side(style="thin", color="D6C7B9")
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.border = Border(bottom=thin)
        for column in sheet.columns:
            sheet.column_dimensions[get_column_letter(column[0].column)].width = min(
                max(max(len(str(c.value or "")) for c in column) + 3, 14), 32
            )
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.border = Border(bottom=thin)

    # Format angka Rupiah di masing-masing sheet
    for row in summary.iter_rows(min_row=2, min_col=4, max_col=8):
        for cell in row:
            cell.number_format = '"Rp"#,##0'
    for row in detail_sheet.iter_rows(min_row=2, min_col=4, max_col=4):
        row[0].number_format = '"Rp"#,##0'
    for row in detail_sheet.iter_rows(min_row=2, min_col=6, max_col=6):
        row[0].number_format = '"Rp"#,##0'
    for row in recap_sheet.iter_rows(min_row=2, min_col=4, max_col=4):
        row[0].number_format = '"Rp"#,##0'

    # Baris total pada Ringkasan Transaksi
    if rows:
        last_summary_row = summary.max_row
        total_row = last_summary_row + 2
        summary.cell(total_row, 3, "Total").font = Font(bold=True)
        for col_idx, col_letter in [(4, "D"), (5, "E"), (6, "F")]:
            c = summary.cell(total_row, col_idx, f"=SUM({col_letter}2:{col_letter}{last_summary_row})")
            c.font = Font(bold=True)
            c.number_format = '"Rp"#,##0'

    # Baris total pada Rekap per Produk
    if product_recap:
        last_recap_row = recap_sheet.max_row
        recap_total_row = last_recap_row + 2
        recap_sheet.cell(recap_total_row, 2, "Total Keseluruhan").font = Font(bold=True)
        qty_cell = recap_sheet.cell(recap_total_row, 3, f"=SUM(C2:C{last_recap_row})")
        qty_cell.font = Font(bold=True)
        rev_cell = recap_sheet.cell(recap_total_row, 4, f"=SUM(D2:D{last_recap_row})")
        rev_cell.font = Font(bold=True)
        rev_cell.number_format = '"Rp"#,##0'

    filename = "laporan_penjualan_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
    path = EXPORT_DIR / filename
    workbook.save(path)
    return filename


@app.route("/transaksi/export")
def export_excel():
    code, start, end, clauses, params = transaction_filters()
    sql = (
        "SELECT * FROM transaksi"
        + ((" WHERE " + " AND ".join(clauses)) if clauses else "")
        + " ORDER BY tanggal_transaksi DESC"
    )
    db = get_db_connection()
    rows = db.execute(sql, params).fetchall()
    ids = [row["id"] for row in rows]
    details = []
    if ids:
        placeholders = ",".join("?" * len(ids))
        # Mengambil rincian produk dari setiap transaksi yang lolos filter
        details = db.execute(
            f"SELECT t.kode_transaksi, t.tanggal_transaksi, d.nama_produk, d.harga_satuan, d.jumlah, d.subtotal "
            f"FROM detail_transaksi d INNER JOIN transaksi t ON t.id = d.transaksi_id "
            f"WHERE t.id IN ({placeholders}) ORDER BY t.tanggal_transaksi DESC",
            ids,
        ).fetchall()

    # Query rekapitulasi penjualan per produk berdasarkan filter tanggal/kode transaksi aktif
    _, _, _, t_clauses, t_params = transaction_filters(prefix="t.")
    recap_sql = (
        "SELECT d.nama_produk, SUM(d.jumlah) AS jumlah_terjual, SUM(d.subtotal) AS total_pendapatan "
        "FROM detail_transaksi d INNER JOIN transaksi t ON t.id = d.transaksi_id"
        + ((" WHERE " + " AND ".join(t_clauses)) if t_clauses else "")
        + " GROUP BY d.produk_id, d.nama_produk ORDER BY jumlah_terjual DESC, total_pendapatan DESC"
    )
    product_recap = db.execute(recap_sql, t_params).fetchall()
    db.close()

    filename = make_excel(rows, details, product_recap)
    return send_from_directory(EXPORT_DIR, filename, as_attachment=True)


@app.route("/backup")
def backup():
    files = sorted([p for p in BACKUP_DIR.iterdir() if p.is_file() and p.suffix == ".db"], key=lambda p: p.stat().st_mtime, reverse=True); return render_template("backup.html", files=files)


@app.post("/backup/create")
def backup_create():
    filename = "smartpos_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".db"; target = BACKUP_DIR / filename
    source = get_db_connection(); destination = sqlite3.connect(target)
    try: source.backup(destination); flash("Backup berhasil dibuat.", "success")
    finally: destination.close(); source.close()
    return redirect(url_for("backup"))


@app.get("/backup/download/<path:filename>")
def backup_download(filename):
    if Path(filename).name != filename or not filename.endswith(".db"): return "Nama file tidak valid", 400
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
