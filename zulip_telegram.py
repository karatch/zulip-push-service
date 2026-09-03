import asyncio
import os
import configparser
import logging
from datetime import datetime
import aiohttp
import zulip

ZULIPRC_PATH = "zuliprc"

BOT_EMAIL = None
STREAM_NAME = None
client = None  # глобальный клиент Zulip

TELEGRAM_BOT_TOKEN = None
USER_MAPPING = {}  # {zulip_id: telegram_id}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

async_session = None
loop = None


async def send_telegram_push(tg_chat_id: int, stream_name: str, topic: str, sender_name: str,
                             message_content: str) -> None:
    pass


def get_stream_subscribers(stream_name: str) -> list:
    pass


def process_event(event: dict) -> None:
    global BOT_EMAIL, STREAM_NAME, USER_MAPPING, loop

    if event.get('type') == 'message':
        msg = event['message']

        if msg['sender_email'] == BOT_EMAIL:
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg['content']

        subscribers = get_stream_subscribers(STREAM_NAME)

        for user_id in subscribers:
            if user_id == sender_id:
                continue

            tg_id = USER_MAPPING.get(str(user_id))
            if tg_id:
                asyncio.run_coroutine_threadsafe(
                    send_telegram_push(int(tg_id), STREAM_NAME, topic, sender_name, content),
                    loop
                )
            else:
                logging.warning(f"Пользователь Zulip ID {user_id} не связан с Telegram в zuliprc")


def start_zulip_listener():
    logging.info(f"Слушаю канал '{STREAM_NAME}' и перенаправляю пуши в Telegram...")
    client.call_on_each_event(
        callback=process_event,
        event_types=['message'],
        narrow=[['stream', STREAM_NAME]]
    )


async def main():
    global BOT_EMAIL, STREAM_NAME, client, TELEGRAM_BOT_TOKEN, USER_MAPPING, async_session, loop

    loop = asyncio.get_running_loop()

    if not os.path.exists(ZULIPRC_PATH):
        logging.error(f"Файл конфигурации '{ZULIPRC_PATH}' не найден.")
        return

    try:
        config = configparser.ConfigParser()
        config.read(ZULIPRC_PATH)

        if not config.has_section('ntfy') or not config.has_section('telegram'):
            logging.error("В файле zuliprc отсутствуют необходимые секции [ntfy] или [telegram]")
            return

        STREAM_NAME = config.get('ntfy', 'stream')
        TELEGRAM_BOT_TOKEN = config.get('telegram', 'bot_token')
        USER_MAPPING = {key: config.get('telegram', key) for key in config.options('telegram') if key != 'bot_token'}
        logging.info(f"Успешно загружено аккаунтов Telegram: {len(USER_MAPPING)}")

    except Exception as e:
        logging.error(f"Ошибка парсинга файла конфигурации: {e}")
        return

    try:
        client = zulip.Client(config_file=ZULIPRC_PATH)
        BOT_EMAIL = client.email
        logging.info(f"Бот Zulip авторизован: {BOT_EMAIL}")
    except Exception as e:
        logging.error(f"Ошибка инициализации клиента Zulip: {e}")
        return

    async with aiohttp.ClientSession() as session:
        async_session = session
        try:
            await loop.run_in_executor(None, start_zulip_listener)
        except Exception as e:
            logging.critical(f"Критическая ошибка в цикле обработки событий: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Сервис остановлен пользователем")
