import asyncio
import logging
import html
import zulip
from pathlib import Path

import database

# Фоновый мост Zulip -> Telegram

class ZulipTelegramBridge:
    def __init__(self, stream_name: str, tg_token: str, loop: asyncio.AbstractEventLoop, zuliprc_path: Path):
        self.stream_name = stream_name
        self.tg_token = tg_token
        self.loop = loop
        self.zuliprc_path = zuliprc_path
        self.bot_email = None
        self.zulip_client = None
        self.session = None
        self.semaphore = asyncio.Semaphore(10)

    async def send_telegram_push(self, tg_chat_id: int, topic: str, sender_name: str, message_content: str) -> None:
        logging.info(f"[Bridge API] Попытка отправки пуша для TG ID: {tg_chat_id}")

        safe_stream = html.escape(self.stream_name)
        safe_topic = html.escape(topic)
        safe_sender = html.escape(sender_name)
        safe_content = html.escape(message_content)

        text = (
            f"🔔 <b>Новое сообщение в Zulip [{safe_stream}]</b>\n"
            f"<b>Тема:</b> {safe_topic}\n"
            f"<b>От:</b> {safe_sender}\n\n"
            f"{safe_content}"
        )
        url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
        payload = {
            "chat_id": tg_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True}
        }

        async with self.semaphore:
            try:
                async with self.session.post(url, json=payload, timeout=5) as response:
                    if response.status == 200:
                        logging.info(f"[Bridge API] Пуш успешно доставлен адресату {tg_chat_id}")
                        # res_text = await response.text()
                        # logging.info(f"[DEBUG API] Ответ от серверов Telegram: {res_text}")
                    else:
                        res_text = await response.text()
                        logging.error(
                            f"[Bridge API] Ошибка Telegram Bot API (Статус {response.status}) для чата {tg_chat_id}: {res_text}")
            except Exception as e:
                logging.error(f"[Bridge API] Исключение сети при отправке в чат {tg_chat_id}: {e}")

    def get_stream_subscribers(self) -> list:
        try:
            logging.debug(f"[Bridge] Запрос списка подписчиков для стрима '{self.stream_name}'...")
            result = self.zulip_client.get_subscribers(stream=self.stream_name)
            if result.get('result') == 'success':
                subscribers = result.get('subscribers', [])
                logging.info(f"[Bridge] В стриме '{self.stream_name}' найдено {len(subscribers)} подписчиков.")
                return subscribers
            else:
                logging.error(f"[Bridge] Ошибка Zulip API при получении подписчиков: {result}")
                return []
        except Exception as e:
            logging.error(f"[Bridge] Исключение при получении подписчиков Zulip: {e}")
            return []

    def process_event(self, event: dict) -> None:
        if event.get('type') != 'message':
            return

        msg = event['message']
        if msg['sender_email'] == self.bot_email:
            return

        if msg['type'] == 'private':
            logging.debug("[Bridge] Пропущено приватное сообщение.")
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg['content']

        logging.info(
            f"[Bridge] Перехвачено новое сообщение в стриме! От: {sender_name} (Zulip ID: {sender_id}), Тема: '{topic}'")

        subscribers = self.get_stream_subscribers()
        sent_counter = 0

        for user_id in subscribers:
            if user_id == sender_id:
                continue
            tg_id = database.get_tg_id_by_zulip(str(user_id))
            if tg_id:
                sent_counter += 1
                logging.info(
                    f"[Bridge] Найдено совпадение в БД: Zulip ID {user_id} -> TG ID {tg_id}. Планируем отправку.")
                # передаю таску в главный Event Loop
                self.loop.call_soon_threadsafe(
                    lambda t=tg_id: asyncio.create_task(self.send_telegram_push(int(t), topic, sender_name, content))
                )
        logging.info(
            f"[Bridge] Обработка события завершена. Потенциальных получателей пушей запланировано: {sent_counter}")

    def start_zulip_listener(self):
        logging.info(f"[Bridge] Установка соединения и регистрация очереди событий Zulip для '{self.stream_name}'...")
        try:
            self.zulip_client.call_on_each_event(
                callback=self.process_event,
                event_types=['message'],
                narrow=[['stream', self.stream_name]]
            )
        except Exception as e:
            logging.critical(f"[Bridge] Критическая ошибка потока прослушивания событий Zulip: {e}")

    async def start(self, session):
        self.session = session
        logging.info("[Bridge] Авторизация в Zulip Client...")
        try:
            self.zulip_client = zulip.Client(config_file=str(self.zuliprc_path))
            self.bot_email = self.zulip_client.email
            logging.info(f"[Bridge] Успешная авторизация. Email бота в Zulip: {self.bot_email}")
        except Exception as e:
            logging.critical(f"[Bridge] Ошибка авторизации в Zulip: {e}")
            return

        # запускаю бесконечный блокирующий цикл прослушивания событий Zulip в фоновом ThreadPoolExecutor
        logging.info("[Bridge] Запуск слушателя событий Zulip в отдельном системном потоке Executor...")
        await self.loop.run_in_executor(None, self.start_zulip_listener)
