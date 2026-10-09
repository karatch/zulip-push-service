#!/usr/bin/env python3
import asyncio
import os
import configparser
import logging
import signal
import sys
import aiohttp
import urllib3
from aiogram import Bot
from pathlib import Path
from aiogram.types import BotCommand
from dotenv import load_dotenv

import database
from bot import dp
from bridge import ZulipTelegramBridge

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

ZULIPRC_PATH = BASE_DIR / "zuliprc"
DOTENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=DOTENV_PATH)

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
        zulip_site = config.get('api', 'site').rstrip('/')
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not tg_token:
            raise ValueError("Переменная TELEGRAM_BOT_TOKEN не найдена в файле .env!")

        logging.info("[Main] Конфигурация успешно загружена.")
        return {"tg_token": tg_token, "zulip_site": zulip_site}
    except Exception as e:
        raise KeyError(f"Ошибка чтения конфигурационных параметров: {e}")


async def main():
    stop_event = asyncio.Event()

    def handle_exit_signal():
        logging.info("[Система] Получен сигнал остановки. Ожидаем завершения фоновых задач...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, handle_exit_signal)
        loop.add_signal_handler(signal.SIGTERM, handle_exit_signal)
    except NotImplementedError:
        pass

    logging.info("[Main] Инициализация базы данных...")
    database.init_db()

    try:
        config = load_config()
    except Exception as e:
        logging.critical(f"[Main] Не удалось запустить приложение: {e}")
        return

    logging.info("[Main] Инициализация объектов Bot и ZulipTelegramBridge...")
    bot = Bot(token=config["tg_token"])
    bridge = ZulipTelegramBridge(
        tg_token=config["tg_token"],
        zulip_site=config["zulip_site"],
        loop=loop,
        zuliprc_path=ZULIPRC_PATH
    )
    dp["zulip_bridge"] = bridge

    try:
        await asyncio.wait_for(bot.delete_webhook(drop_pending_updates=True), timeout=5.0)
        main_commands = [
            BotCommand(command="start", description="Запустить бота / Показать меню"),
            BotCommand(command="bind", description="Привязать Zulip ID"),
            BotCommand(command="status", description="Проверить статус подписки"),
            BotCommand(command="unbind", description="Отвязать аккаунт и выключить пуши"),
            BotCommand(command="help", description="Показать подробную инструкцию")
        ]
        await bot.set_my_commands(main_commands)
    except Exception as e:
        logging.warning(f"[Main] Не удалось связаться с Telegram API: {e}. Продолжаем запуск...")

    try:
        async with aiohttp.ClientSession() as session:
            bridge_task = asyncio.create_task(bridge.start(session))
            polling_task = asyncio.create_task(dp.start_polling(bot))

            await stop_event.wait()

            bridge_task.cancel()
            polling_task.cancel()
            await asyncio.gather(bridge_task, polling_task, return_exceptions=True)

    finally:
        logging.info("[Main] Закрытие сессии бота Telegram...")
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())