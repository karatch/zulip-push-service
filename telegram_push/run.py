#!/usr/bin/env python3
import asyncio
import os
import configparser
import logging
import sys
import aiohttp
from aiogram import Bot
from pathlib import Path

import database
from bot import dp
from bridge import ZulipTelegramBridge

# определение путей с учетом компиляции PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

ZULIPRC_PATH = BASE_DIR / "zuliprc"

# системное логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def load_config():
    logging.info(f"[Main] Чтение конфигурационного файла: {ZULIPRC_PATH}")
    if not os.path.exists(ZULIPRC_PATH):
        raise FileNotFoundError(f"Критическая ошибка: Файл {ZULIPRC_PATH} не найден!")

    config = configparser.ConfigParser()
    config.read(ZULIPRC_PATH)
    try:
        stream = config.get('ntfy', 'stream')
        token = config.get('telegram', 'bot_token')
        logging.info(f"[Main] Конфигурация успешно загружена. Целевой стрим Zulip: '{stream}'")
        return {"stream": stream, "token": token}
    except Exception as e:
        raise KeyError(f"Ошибка чтения секций в zuliprc: {e}")


async def main():
    loop = asyncio.get_running_loop()

    logging.info("[Main] Инициализация базы данных...")
    database.init_db()

    try:
        config = load_config()
    except Exception as e:
        logging.critical(f"[Main] Не удалось запустить приложение: {e}")
        return

    logging.info("[Main] Инициализация объектов Bot и ZulipTelegramBridge...")

    bot = Bot(token=config["token"])
    bridge = ZulipTelegramBridge(stream_name=config["stream"], tg_token=config["token"], loop=loop,
                                 zuliprc_path=ZULIPRC_PATH)

    try:
        logging.info("[Main] Сброс накопившихся обновлений Telegram (delete_webhook)...")
        await bot.delete_webhook(drop_pending_updates=True)

        async with aiohttp.ClientSession() as session:
            logging.info("[Main] Запуск параллельных процессов: polling бота и bridge...")
            await asyncio.gather(
                dp.start_polling(bot),
                bridge.start(session)
            )
    finally:
        logging.info("[Main] Закрытие сессии бота Telegram...")
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("[Main] Сервис остановлен пользователем через Ctrl+C.")
    except Exception as e:
        logging.exception(f"[Main] Непредвиденное критическое исключение: {e}")
