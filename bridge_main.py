import asyncio
import os
import configparser
import logging
from pathlib import Path
import aiohttp
import zulip

import database

BASE_DIR = Path(__file__).resolve().parent
ZULIPRC_PATH = BASE_DIR / "zuliprc"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ZulipTelegramBridge:
    def __init__(self):
        self.bot_email = None
        self.stream_name = None
        self.tg_token = None
        self.zulip_client = None
        self.session = None
        self.loop = None
        self.semaphore = asyncio.Semaphore(10)

    def load_config(self):
        if not os.path.exists(ZULIPRC_PATH):
            raise FileNotFoundError(f"Файл {ZULIPRC_PATH} не найден.")

        config = configparser.ConfigParser()
        config.read(ZULIPRC_PATH)

        self.stream_name = config.get('ntfy', 'stream')
        self.tg_token = config.get('telegram', 'bot_token')

    async def send_telegram_push(self, tg_chat_id: int, topic: str, sender_name: str, message_content: str) -> None:
        text = (
            f"🔔 <b>Новое сообщение в Zulip [{self.stream_name}]</b>\n"
            f"<b>Тема:</b> {topic}\n"
            f"<b>От:</b> {sender_name}\n\n"
            f"{message_content}"
        )
        url = f"https://telegram.org{self.tg_token}/sendMessage"
        payload = {
            "chat_id": tg_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True}
        }

        async with self.semaphore:
            try:
                async with self.session.post(url, json=payload, timeout=5) as response:
                    if response.status != 200:
                        res_text = await response.text()
                        logging.error(f"[Telegram] Ошибка API: {res_text}")
            except Exception as e:
                logging.error(f"[Telegram] Исключение при отправке: {e}")

    def get_stream_subscribers(self) -> list:
        try:
            result = self.zulip_client.get_subscribers(stream=self.stream_name)
            return result.get('subscribers', []) if result.get('result') == 'success' else []
        except Exception as e:
            logging.error(f"Ошибка API подписчиков Zulip: {e}")
            return []

    def process_event(self, event: dict) -> None:
        if event.get('type') != 'message':
            return
        msg = event['message']
        if msg['sender_email'] == self.bot_email or msg['type'] == 'private':
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg['content']

        subscribers = self.get_stream_subscribers()
        for user_id in subscribers:
            if user_id == sender_id:
                continue

                # ИСПРАВЛЕНО: Быстрый запрос в SQLite вместо чтения файла
            tg_id = database.get_tg_id_by_zulip(str(user_id))
            if tg_id:
                asyncio.run_coroutine_threadsafe(
                    self.send_telegram_push(int(tg_id), topic, sender_name, content),
                    self.loop
                )

    def start_zulip_listener(self):
        logging.info(f"Слушаю Zulip-канал '{self.stream_name}'...")
        self.zulip_client.call_on_each_event(
            callback=self.process_event,
            event_types=['message'],
            narrow=[['stream', self.stream_name]]
        )

    async def main(self):
        self.loop = asyncio.get_running_loop()

        # Автоинициализация базы данных при старте
        database.init_db()

        try:
            self.load_config()
        except Exception as e:
            logging.error(f"Ошибка загрузки конфигурации: {e}")
            return

        try:
            self.zulip_client = zulip.Client(config_file=str(ZULIPRC_PATH))
            self.bot_email = self.zulip_client.email
        except Exception as e:
            logging.error(f"Ошибка авторизации в Zulip: {e}")
            return

        async with aiohttp.ClientSession() as session:
            self.session = session
            # Блокирующий поток для Zulip
            await self.loop.run_in_executor(None, self.start_zulip_listener)


if __name__ == "__main__":
    bridge = ZulipTelegramBridge()
    try:
        asyncio.run(bridge.main())
    except KeyboardInterrupt:
        logging.info("Сервис остановлен")
