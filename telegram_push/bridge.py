import asyncio
import logging
import html
import urllib.parse
import zulip
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time

import database


class ZulipTelegramBridge:
    def __init__(self, tg_token: str, zulip_site: str, loop: asyncio.AbstractEventLoop, zuliprc_path: Path):
        self.tg_token = tg_token
        self.zulip_site = zulip_site
        self.loop = loop
        self.zuliprc_path = zuliprc_path
        self.bot_email = None
        self.zulip_client = None
        self.session = None
        self.semaphore = asyncio.Semaphore(20)
        self.active_push_tasks = set()

        # один экземпляр Executor на весь цикл жизни
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ZulipListener")
        for thread in self.executor._threads:
            thread.daemon = True

        self._stop_listener_event = asyncio.Event()

        self.subscribers_cache = {}
        self.cache_ttl = 300  # 5 минут


    async def send_telegram_push(self, tg_chat_id: int, stream_name: str, topic: str, sender_name: str,
                                 message_content: str, msg_url: str) -> None:
        task = asyncio.current_task()
        self.active_push_tasks.add(task)

        logging.info(f"[Bridge API] Отправка пуша для TG ID: {tg_chat_id}")

        try:
            safe_stream = html.escape(stream_name)
            safe_topic = html.escape(topic)
            safe_sender = html.escape(sender_name)
            safe_content = html.escape(message_content)

            text = (
                f"🔔 <b>Новое сообщение в Zulip [{safe_stream}]</b>\n"
                f"<b>Тема:</b> {safe_topic}\n"
                f"<b>От:</b> {safe_sender}\n\n"
                f"{safe_content}\n\n"
                f"🔗 <a href='{msg_url}'>Открыть в чате Zulip</a>"
            )
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            payload = {
                "chat_id": tg_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True}
            }

            async with self.semaphore:
                async with self.session.post(url, json=payload, timeout=3) as response:
                    if response.status == 200:
                        logging.info(f"[Bridge API] Пуш успешно доставлен адресату {tg_chat_id}")
                    else:
                        res_text = await response.text()
                        logging.error(
                            f"[Bridge API] Ошибка Telegram Bot API (Статус {response.status}) для чата {tg_chat_id}: {res_text}")
        except Exception as e:
            logging.error(f"[Bridge API] Исключение сети при отправке в чат {tg_chat_id}: {e}")
        finally:
            self.active_push_tasks.discard(task)


    def _get_cached_subscribers(self, stream_id: int) -> list | None:
        data = self.subscribers_cache.get(stream_id)
        if data:
            subscribers, timestamp = data
            if (time.time() - timestamp) < self.cache_ttl:
                return subscribers
        return None


    def _update_cache(self, stream_id: int, subscribers: list):
        self.subscribers_cache[stream_id] = (subscribers, time.time())

    def get_stream_subscribers(self, stream_name: str, stream_id: int) -> list:
        # сначала кэш
        cached = self._get_cached_subscribers(stream_id)
        if cached is not None:
            return cached

        try:
            result = self.zulip_client.get_subscribers(stream=stream_name)
            if result.get('result') != 'success':
                logging.warning(f"[Bridge] Запрос по имени не удался, пробуем по stream_id={stream_id}...")
                result = self.zulip_client.get_subscribers(stream_id=stream_id)

            if result.get('result') == 'success':
                subscribers = result.get('subscribers', [])
                self._update_cache(stream_id, subscribers)
                logging.info(f"[Bridge] В стриме '{stream_name}' найдено {len(subscribers)} подписчиков.")
                return subscribers
            return []
        except Exception as e:
            logging.error(f"[Bridge] Исключение при получении подписчиков Zulip: {e}")
            return []


    def get_user_id_by_email(self, email: str) -> dict:
        try:
            result = self.zulip_client.get_users()
            if result.get('result') == 'success':
                members = result.get('members', [])
                search_email = email.strip().lower()
                for member in members:
                    actual_email = member.get('delivery_email', '').lower()
                    if actual_email == search_email:
                        if member.get('is_active') and not member.get('is_bot'):
                            return {"zulip_id": str(member.get('user_id')), "full_name": member.get('full_name')}
                logging.warning(f"[Bridge API] Пользователь с email {email} не найден.")
                return {}
            logging.error(f"[Bridge API] Сервер Zulip отклонил запрос get_users: {result}")
            return {}
        except Exception as e:
            logging.error(f"[Bridge API] Исключение при поиске пользователя по email {email}: {e}")
            return {}


    def send_zulip_private_message(self, zulip_id: int, text: str) -> bool:
        try:
            request = {"type": "private", "to": [int(zulip_id)], "content": text}
            result = self.zulip_client.send_message(request)
            if result.get('result') == 'success':
                logging.info(f"[Bridge API] OTP-код успешно отправлен в Zulip для ID {zulip_id}")
                return True
            logging.error(f"[Bridge API] Сервер Zulip отклонил отправку DM для ID {zulip_id}: {result}")
            return False
        except Exception as e:
            logging.error(f"[Bridge API] Исключение при отправке DM в Zulip для ID {zulip_id}: {e}")
            return False


    def process_event(self, event: dict) -> None:
        if event.get('type') != 'message':
            return
        msg = event['message']
        if msg['sender_email'] == self.bot_email or msg['type'] != 'stream':
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg.get('content_raw', msg.get('content', ''))

        stream_name = msg.get('display_recipient', 'Неизвестный стрим')
        stream_id = msg.get('stream_id')
        message_id = msg.get('id')

        logging.info(f"[Bridge] Перехвачено сообщение из [{stream_name}] (ID: {stream_id})")

        stream_slug = f"{stream_id}-{stream_name.lower().replace(' ', '-')}"
        encoded_topic = urllib.parse.quote(topic)
        msg_url = f"{self.zulip_site}/#narrow/channel/{stream_slug}/topic/{encoded_topic}/with/{message_id}"

        subscribers = self.get_stream_subscribers(stream_name, stream_id)

        sent_counter = 0
        for user_id in subscribers:
            if user_id == sender_id:
                continue

            tg_id = database.get_tg_id_by_zulip(str(user_id))
            if tg_id:
                sent_counter += 1
                self.loop.call_soon_threadsafe(
                    lambda t=tg_id: asyncio.create_task(
                        self.send_telegram_push(int(t), stream_name, topic, sender_name, content, msg_url)
                    )
                )
        logging.info(f"[Bridge] Всего запланировано пушей: {sent_counter}")


    def start_zulip_listener(self):
        logging.info("[Bridge] Запуск слушателя событий Zulip...")
        try:
            self.zulip_client.call_on_each_event(
                callback=self.process_event,
                event_types=['message'],
                all_public_streams=True
            )
        except Exception as e:
            logging.critical(f"[Bridge] Критическая ошибка потока прослушивания: {e}")


    async def start(self, session):
        self.session = session
        while True:
            try:
                self.zulip_client = await asyncio.wait_for(
                    self.loop.run_in_executor(None, lambda: zulip.Client(config_file=str(self.zuliprc_path))),
                    timeout=10.0
                )
                self.bot_email = self.zulip_client.email
                logging.info(f"[Bridge] Успешная авторизация. Email бота: {self.bot_email}")

                break
            except Exception as e:
                logging.error(f"[Bridge] Ошибка авторизации в Zulip: {e}. Повтор через 15 секунд...")
                await asyncio.sleep(15)

        async def safe_listener_loop():
            while True:
                try:
                    await self.loop.run_in_executor(self.executor, self.start_zulip_listener)
                except Exception as e:
                    logging.error(f"[Bridge] Поток слушателя Zulip аварийно завершился: {e}")
                finally:
                    self.executor.shutdown(wait=False)

                if not self._stop_listener_event.is_set():
                    logging.info("[Bridge] Соединение с Zulip потеряно. Перезапуск через 15 секунд...")
                    await asyncio.sleep(15)
                else:
                    break

        asyncio.create_task(safe_listener_loop())


    async def shutdown(self):
        logging.info("[Bridge] Инициализация завершения работы...")
        self._stop_listener_event.set()
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                logging.info("[Bridge] Задача слушателя Zulip отменена.")

        if self.active_push_tasks:
            logging.info(f"[Bridge] Ожидаем завершения {len(self.active_push_tasks)} активных отправок...")
            await asyncio.wait(self.active_push_tasks)

        if self.session:
            await self.session.close()

        self.executor.shutdown(wait=False)
        logging.info("[Bridge] Выполнено завершение работы моста.")