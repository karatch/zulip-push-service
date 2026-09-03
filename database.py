import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "bridge.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                zulip_id TEXT PRIMARY KEY,
                tg_id TEXT NOT NULL
            )
        """)
        conn.commit()

def add_user(zulip_id: str, tg_id: str):
    """аналог INSERT OR REPLACE"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (zulip_id, tg_id) 
            VALUES (?, ?)
            ON CONFLICT(zulip_id) DO UPDATE SET tg_id = excluded.tg_id
        """, (str(zulip_id), str(tg_id)))
        conn.commit()

def get_tg_id_by_zulip(zulip_id: str) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tg_id FROM users WHERE zulip_id = ?", (str(zulip_id),))
        row = cursor.fetchone()
        return row[0] if row else None

def get_zulip_id_by_tg(tg_id: str) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT zulip_id FROM users WHERE tg_id = ?", (str(tg_id),))
        row = cursor.fetchone()
        return row[0] if row else None

def remove_user_by_tg(tg_id: str) -> bool:
    """удаляет все привязки для конкретного Telegram ID."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE tg_id = ?", (str(tg_id),))
        conn.commit()
        return cursor.rowcount > 0
