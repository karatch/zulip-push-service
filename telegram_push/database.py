import sqlite3
import logging
import sys
from pathlib import Path
from typing import Optional

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "bridge.db"


def _get_connection() -> sqlite3.Connection:
    # Таймаут в 10 секунд не даст транзакции упасть сразу, если диск на секунду занят
    conn = sqlite3.connect(DB_PATH, timeout=10.0)

    try:
        # режим WAL (Write-Ahead Logging) для высокой конкурентности (чтение во время записи)
        conn.execute("PRAGMA journal_mode=WAL;")
    except sqlite3.Error as e:
        logging.warning(f"[DB] Не удалось активировать режим WAL: {e}")

    return conn


def init_db() -> None:
    logging.info(f"[DB] Инициализация базы данных. Путь к файлу: {DB_PATH}")
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    zulip_id TEXT PRIMARY KEY,
                    tg_id TEXT NOT NULL
                )
            """)
            conn.commit()
        logging.info("[DB] База данных успешно проверена/создана.")
    except sqlite3.Error as e:
        logging.critical(f"[DB] Критическая ошибка при инициализации базы данных: {e}")
        raise


def add_user(zulip_id: str, tg_id: str) -> None:
    logging.info(f"[DB] Попытка записи привязки: Zulip ID '{zulip_id}' <-> TG ID '{tg_id}'")

    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (zulip_id, tg_id) 
                VALUES (?, ?)
                ON CONFLICT(zulip_id) DO UPDATE SET tg_id = excluded.tg_id
            """, (zulip_id, tg_id))
            conn.commit()
        logging.info(f"[DB] Связка для Zulip ID '{zulip_id}' успешно сохранена.")
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка выполнения SQL при добавлении пользователя: {e}")
        raise


def get_tg_id_by_zulip(zulip_id: str) -> Optional[str]:
    logging.debug(f"[DB] Запрос TG ID для Zulip ID '{zulip_id}'...")

    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tg_id FROM users WHERE zulip_id = ?", (zulip_id,))
            row = cursor.fetchone()

            if row:
                logging.debug(f"[DB] Найдено совпадение: Zulip ID '{zulip_id}' -> TG ID '{row[0]}'")
                return row[0]

            logging.debug(f"[DB] Совпадений для Zulip ID '{zulip_id}' не найдено.")
            return None
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка SQL при поиске по Zulip ID '{zulip_id}': {e}")
        return None


def get_zulip_id_by_tg(tg_id: str) -> Optional[str]:
    logging.debug(f"[DB] Запрос Zulip ID для TG ID '{tg_id}'...")
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT zulip_id FROM users WHERE tg_id = ?", (tg_id,))
            row = cursor.fetchone()

            if row:
                logging.debug(f"[DB] Найдено совпадение: TG ID '{tg_id}' -> Zulip ID '{row[0]}'")
                return row[0]

            logging.debug(f"[DB] Совпадений для TG ID '{tg_id}' не найдено.")
            return None
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка SQL при поиске по TG ID '{tg_id}': {e}")
        return None


def remove_user_by_tg(tg_id: str) -> bool:
    logging.info(f"[DB] Попытка удаления привязок для TG ID '{tg_id}'...")
    try:
        with _get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE tg_id = ?", (tg_id,))
            conn.commit()
            deleted_rows = cursor.rowcount

        if deleted_rows > 0:
            logging.info(f"[DB] Успешно удалено привязок: {deleted_rows} для TG ID '{tg_id}'.")
            return True

        logging.warning(f"[DB] Записей для удаления по TG ID '{tg_id}' не обнаружено.")
        return False
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка SQL при удалении по TG ID '{tg_id}': {e}")
        return False