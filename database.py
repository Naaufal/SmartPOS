"""Fungsi koneksi database SQLite untuk SmartPOS."""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "smartpos.db"


def get_db_connection():
    """Membuka koneksi dengan Row agar kolom dapat diakses memakai nama."""
    DATABASE_DIR.mkdir(exist_ok=True)
    # MATERI 1: Koneksi database SQLite
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
