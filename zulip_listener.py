import zulip
import requests
import os
import configparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import urllib3
# глушу предупреждения InsecureRequestWarning (при тестировании)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ZULIPRC_PATH = "zuliprc"

BOT_EMAIL = None
NTFY_BASE_URL = "https://ntfy.sh"
STREAM_NAME = None
STREAM_ID = None
client = None

# переменная для пути к SSL-сертификату (если сервер ntfy корпоративный)
# True если используется публичный https://ntfy.sh
SSL_VERIFY_CONFIG = True

executor = ThreadPoolExecutor(max_workers=25)


def send_ntfy_push(user_id: int, title: str, message: str) -> None:
    try:
        headers = {
            "Title": title.encode('utf-8'),
            "Priority": "high",
            "Tags": "speech_balloon,bell"
        }
        user_topic = f"zulip_user_{user_id}"
        url = f"{NTFY_BASE_URL}/{user_topic}"

        # безопасный запрос с проверкой SSL-сертификата
        res = requests.post(
            url,
            data=message.encode('utf-8'),
            headers=headers,
            timeout=5,
            verify=SSL_VERIFY_CONFIG
        )
        dt = datetime.now().strftime("%Y-%m-%d %X")
        if res.status_code == 200:
            print(f"{dt}: отправлен пуш для пользователя ID {user_id}: {title}")
        else:
            print(f"{dt}: Ошибка ntfy для ID {user_id}: код {res.status_code}")
    except Exception as e:
        dt = datetime.now().strftime("%Y-%m-%d %X")
        print(f"{dt}: Не удалось отправить пуш в ntfy для ID {user_id}: {e}")


def get_stream_subscribers(stream_name: str) -> list:
    dt = datetime.now().strftime("%Y-%m-%d %X")
    try:
        result = client.get_subscribers(stream=stream_name)
        if result.get('result') == 'success':
            return result.get('subscribers', [])
        else:
            print(f"{dt}: Ошибка получения подписчиков: {result.get('msg')}")
            return []
    except Exception as e:
        print(f"{dt}: Ошибка при обращении к API получения подписчиков: {e}")
        return []


def process_event(event: dict) -> None:
    global BOT_EMAIL, STREAM_NAME, STREAM_ID

    if event.get('type') == 'message':
        msg = event['message']

        if msg['sender_email'] == BOT_EMAIL:
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg['content']

        push_title = f"Zulip [{STREAM_NAME}] -> {topic}"
        push_message = f"{sender_name}: {content}"

        subscribers = get_stream_subscribers(STREAM_NAME)

        for user_id in subscribers:
            if user_id == sender_id:
                continue
            executor.submit(send_ntfy_push, user_id, push_title, push_message)


def main():
    global BOT_EMAIL, NTFY_BASE_URL, STREAM_NAME, STREAM_ID, client, SSL_VERIFY_CONFIG

    dt = datetime.now().strftime("%Y-%m-%d %X")
    if not os.path.exists(ZULIPRC_PATH):
        print(f"{dt}: Ошибка: Файл конфигурации '{ZULIPRC_PATH}' не найден.")
        return

    try:
        config = configparser.ConfigParser()
        config.read(ZULIPRC_PATH)

        if not config.has_section('ntfy'):
            print(f"{dt}: Ошибка: В файле zuliprc отсутствует секция [ntfy]")
            return

        STREAM_NAME = config.get('ntfy', 'stream')

        if config.has_option('ntfy', 'base_url'):
            NTFY_BASE_URL = config.get('ntfy', 'base_url').rstrip('/')

        # опционально: чтение пути к CA-bundle из конфига для приватных серверов
        if config.has_option('ntfy', 'ssl_verify'):
            ssl_val = config.get('ntfy', 'ssl_verify')
            # если написано false/no, но лучше использовать путь к файлу .crt
            if ssl_val.lower() in ['true', 'yes']:
                SSL_VERIFY_CONFIG = True
            elif ssl_val.lower() in ['false', 'no']:
                SSL_VERIFY_CONFIG = False
            else:
                SSL_VERIFY_CONFIG = ssl_val  # путь к файлу сертификата

    except Exception as e:
        print(f"{dt}: Ошибка парсинга секции [ntfy] в zuliprc: {e}")
        return

    try:
        client = zulip.Client(config_file=ZULIPRC_PATH)
        BOT_EMAIL = client.email
        print(f"{dt}: Успешно авторизован бот: {BOT_EMAIL}")
    except Exception as e:
        print(f"{dt}: Ошибка инициализации клиента Zulip: {e}")
        return

    print(f"Сервис запущен. Слушаю канал '{STREAM_NAME}' и шлю персональные пуши...")

    try:
        client.call_on_each_event(
            callback=process_event,
            event_types=['message'],
            narrow=[['stream', STREAM_NAME]]
        )
    except Exception as e:
        dt = datetime.now().strftime("%Y-%m-%d %X")
        print(f"{dt}: критическая ошибка в цикле обработки событий: {e}")
    finally:
        executor.shutdown(wait=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        dt = datetime.now().strftime("%Y-%m-%d %X")
        print(f"\n{dt}: сервис остановлен пользователем")
        executor.shutdown(wait=False)
