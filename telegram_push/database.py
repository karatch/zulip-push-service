import sys
import sqlite3
import logging
from pathlib import Path
from typing import Optional

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "bridge.db"


def init_db() -> None:
    logging.info(f"[DB] Инициализация базы данных. Путь к файлу: {DB_PATH}")
    try:
        with sqlite3.connect(DB_PATH) as conn:
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
    z_id = str(zulip_id)
    t_id = str(tg_id)
    logging.info(f"[DB] Попытка записи привязки: Zulip ID '{z_id}' <-> TG ID '{t_id}'")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (zulip_id, tg_id) 
                VALUES (?, ?)
                ON CONFLICT(zulip_id) DO UPDATE SET tg_id = excluded.tg_id
            """, (z_id, t_id))
            conn.commit()
        logging.info(f"[DB] Связка для Zulip ID '{z_id}' успешно сохранена.")
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка выполнения SQL при добавлении пользователя: {e}")
        raise


def get_tg_id_by_zulip(zulip_id: str) -> Optional[str]:
    z_id = str(zulip_id)
    logging.debug(f"[DB] Запрос TG ID для Zulip ID '{z_id}'...")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT tg_id FROM users WHERE zulip_id = ?", (z_id,))
            row = cursor.fetchone()

            if row:
                logging.debug(f"[DB] Найдено совпадение: Zulip ID '{z_id}' -> TG ID '{row[0]}'")
                return row[0]

            logging.debug(f"[DB] Совпадений для Zulip ID '{z_id}' не найдено.")
            return None
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка SQL при поиске по Zulip ID '{z_id}': {e}")
        return None


def get_zulip_id_by_tg(tg_id: str) -> Optional[str]:
    t_id = str(tg_id)
    logging.debug(f"[DB] Запрос Zulip ID для TG ID '{t_id}'...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT zulip_id FROM users WHERE tg_id = ?", (t_id,))
            row = cursor.fetchone()

            if row:
                logging.debug(f"[DB] Найдено совпадение: TG ID '{t_id}' -> Zulip ID '{row[0]}'")
                return row[0]

            logging.debug(f"[DB] Совпадений для TG ID '{t_id}' не найдено.")
            return None
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка SQL при поиске по TG ID '{t_id}': {e}")
        return None


def remove_user_by_tg(tg_id: str) -> bool:
    t_id = str(tg_id)
    logging.info(f"[DB] Попытка удаления привязок для TG ID '{t_id}'...")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE tg_id = ?", (t_id,))
            conn.commit()
            deleted_rows = cursor.rowcount

        if deleted_rows > 0:
            logging.info(f"[DB] Успешно удалено привязок: {deleted_rows} для TG ID '{t_id}'.")
            return True

        logging.warning(f"[DB] Записей для удаления по TG ID '{t_id}' не обнаружено.")
        return False
    except sqlite3.Error as e:
        logging.error(f"[DB] Ошибка SQL при удалении по TG ID '{t_id}': {e}")
        return False
