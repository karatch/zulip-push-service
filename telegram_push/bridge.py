import asyncio
import logging
import html
import zulip
from pathlib import Path

import database


# Фоновый мост Zulip -> Telegram (Исправленный под вызов get_subscribers)

class ZulipTelegramBridge:
    def __init__(self, tg_token: str, loop: asyncio.AbstractEventLoop, zuliprc_path: Path):
        self.tg_token = tg_token
        self.loop = loop
        self.zuliprc_path = zuliprc_path
        self.bot_email = None
        self.zulip_client = None
        self.session = None
        self.semaphore = asyncio.Semaphore(10)

    async def send_telegram_push(self, tg_chat_id: int, stream_name: str, topic: str, sender_name: str,
                                 message_content: str) -> None:
        logging.info(f"[Bridge API] Попытка отправки пуша для TG ID: {tg_chat_id}")

        safe_stream = html.escape(stream_name)
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
                    else:
                        res_text = await response.text()
                        logging.error(
                            f"[Bridge API] Ошибка Telegram Bot API (Статус {response.status}) для чата {tg_chat_id}: {res_text}")
            except Exception as e:
                logging.error(f"[Bridge API] Исключение сети при отправке в чат {tg_chat_id}: {e}")

    # принимает stream_name, так как этого требует библиотека
    def get_stream_subscribers(self, stream_name: str, stream_id: int = None) -> list:
        try:
            logging.debug(f"[Bridge] Запрос списка подписчиков для стрима '{stream_name}'...")

            # Основная попытка запроса по имени стрима
            result = self.zulip_client.get_subscribers(stream=stream_name)

            # Резервный вариант, если API требует ID
            if result.get('result') != 'success' and stream_id is not None:
                logging.warning(f"[Bridge] Запрос по имени не удался, пробуем по stream_id={stream_id}...")
                result = self.zulip_client.get_subscribers(stream_id=stream_id)

            if result.get('result') == 'success':
                subscribers = result.get('subscribers', [])
                logging.info(f"[Bridge] В стриме '{stream_name}' найдено {len(subscribers)} подписчиков.")
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
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg['content']

        stream_name = msg.get('display_recipient', 'Неизвестный стрим')
        stream_id = msg.get('stream_id')

        if not isinstance(stream_name, str):
            logging.warning("[Bridge] Не удалось определить имя стрима, пропускаем событие.")
            return

        logging.info(f"--- [DEBUG START] ---")
        logging.info(f"[Bridge] Перехвачено сообщение из [{stream_name}] (ID: {stream_id})")
        logging.info(f"[Bridge] Автор сообщения Zulip ID: {sender_id} ({sender_name})")

        subscribers = self.get_stream_subscribers(stream_name, stream_id)
        logging.info(
            f"[DEBUG] Список подписчиков от Zulip API: {subscribers} (Тип элементов: {[type(x) for x in subscribers]})")

        sent_counter = 0

        for user_id in subscribers:
            if user_id == sender_id:
                logging.info(f"[DEBUG] Пропускаем Zulip ID {user_id}, так как это сам автор сообщения.")
                continue

            logging.info(f"[DEBUG] Ищем в БД Телеграм для Zulip ID: '{user_id}'")
            tg_id = database.get_tg_id_by_zulip(str(user_id))

            if tg_id:
                sent_counter += 1
                logging.info(f"[Bridge] Найдено совпадение! Zulip ID {user_id} -> TG ID {tg_id}")
                self.loop.call_soon_threadsafe(
                    lambda t=tg_id, sn=stream_name: asyncio.create_task(
                        self.send_telegram_push(int(t), sn, topic, sender_name, content)
                    )
                )
            else:
                logging.warning(f"[DEBUG] В БД нет записи для Zulip ID '{user_id}'")

        logging.info(f"[Bridge] Всего запланировано пушей: {sent_counter}")
        logging.info(f"--- [DEBUG END] ---")

    def start_zulip_listener(self):
        logging.info("[Bridge] Установка соединения и регистрация НОВОЙ очереди событий Zulip для ВСЕХ стримов...")
        try:
            # флаг all_public_streams=True
            # заставляет сервер слать администратору сообщения из ВСЕХ публичных каналов
            self.zulip_client.call_on_each_event(
                callback=self.process_event,
                event_types=['message'],
                all_public_streams=True
            )
        except Exception as e:
            logging.critical(f"[Bridge] Критическая ошибка потока прослушивания событий Zulip: {e}")


    async def start(self, session):
        self.session = session
        while True:
            logging.info("[Bridge] Попытка авторизации в Zulip Client...")
            try:
                self.zulip_client = await asyncio.wait_for(
                    self.loop.run_in_executor(None, lambda: zulip.Client(config_file=str(self.zuliprc_path))),
                    timeout=10.0
                )
                self.bot_email = self.zulip_client.email
                logging.info(f"[Bridge] Успешная авторизация. Email бота в Zulip: {self.bot_email}")
                break
            except (asyncio.TimeoutError, Exception) as e:
                logging.error(f"[Bridge] Ошибка или таймаут авторизации в Zulip: {e}. Повтор через 15 секунд...")
                await asyncio.sleep(15)

        async def safe_listener_loop():
            while True:
                logging.info("[Bridge] Запуск слушателя событий Zulip в отдельном системном потоке Executor...")
                try:
                    await self.loop.run_in_executor(None, self.start_zulip_listener)
                except Exception as e:
                    logging.error(f"[Bridge] Поток слушателя Zulip аварийно завершился: {e}")

                logging.info("[Bridge] Соединение с Zulip потеряно. Перезапуск слушателя через 15 секунд...")
                await asyncio.sleep(15)

        asyncio.create_task(safe_listener_loop())
