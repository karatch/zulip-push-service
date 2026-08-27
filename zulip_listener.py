import zulip
import requests
import os
import urllib3
import configparser

# без предупреждений о небезопасном SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ZULIPRC_PATH = "zuliprc"

BOT_EMAIL = None
NTFY_BASE_URL = "https://ntfy.sh"
STREAM_NAME = None
STREAM_ID = None
client = None  # глобальный клиент для запросов к API


def send_ntfy_push(user_id: int, title: str, message: str) -> None:
    try:
        headers = {
            "Title": title.encode('utf-8'),
            "Priority": "high",
            "Tags": "speech_balloon,bell"
        }
        # у каждого пользователя свой ulip_user_<id>
        user_topic = f"zulip_user_{user_id}"
        url = f"{NTFY_BASE_URL}/{user_topic}"

        res = requests.post(
            url,
            data=message.encode('utf-8'),
            headers=headers,
            timeout=5,
            verify=False  # игнорировать проверку SSL для ntfy
        )
        if res.status_code == 200:
            print(f"Отправлен пуш для пользователя ID {user_id}: {title}")
        else:
            print(f"Ошибка ntfy для ID {user_id}: код {res.status_code}")
    except Exception as e:
        print(f"Не удалось отправить пуш в ntfy для ID {user_id}: {e}")


# def get_stream_subscribers(stream_id):
#     try:
#         result = client.get_subscribers(stream_id=stream_id)
#         if result.get('result') == 'success':
#             return result.get('subscribers', [])
#         else:
#             print(f"Ошибка получения подписчиков: {result.get('msg')}")
#             return []
#     except Exception as e:
#         print(f"Ошибка при обращении к API получения подписчиков: {e}")
#         return []

def get_stream_subscribers(stream_name: str) -> list:
    try:
        result = client.get_subscribers(stream=stream_name)
        if result.get('result') == 'success':
            return result.get('subscribers', [])
        else:
            print(f"Ошибка получения подписчиков: {result.get('msg')}")
            return []
    except Exception as e:
        print(f"Ошибка при обращении к API получения подписчиков: {e}")
        return []


def process_event(event) -> None:
    global BOT_EMAIL, STREAM_NAME, STREAM_ID

    if event.get('type') == 'message':
        msg = event['message']

        # игнорирую сообщения от самого бота
        if msg['sender_email'] == BOT_EMAIL:
            return

        sender_id = msg['sender_id']
        sender_name = msg['sender_full_name']
        topic = msg.get('subject', 'Без темы')
        content = msg['content']

        push_title = f"Zulip [{STREAM_NAME}] -> {topic}"
        push_message = f"{sender_name}: {content}"

        subscribers = get_stream_subscribers(STREAM_NAME)

        # отправляю пуш всем, кроме автора сообщения
        for user_id in subscribers:
            if user_id == sender_id:
                continue
            send_ntfy_push(user_id, push_title, push_message)


def main():
    # инициализация
    global BOT_EMAIL, NTFY_BASE_URL, STREAM_NAME, STREAM_ID, client

    if not os.path.exists(ZULIPRC_PATH):
        print(f"Ошибка: Файл конфигурации '{ZULIPRC_PATH}' не найден.")
        return

    try:
        config = configparser.ConfigParser()
        config.read(ZULIPRC_PATH)

        if not config.has_section('ntfy'):
            print("Ошибка: В файле zuliprc отсутствует секция [ntfy]")
            return

        STREAM_NAME = config.get('ntfy', 'stream')
        # # Опционально: можно переопределить базовый URL ntfy, если есть свой сервер
        # if config.has_option('ntfy', 'base_url'):
        #     NTFY_BASE_URL = config.get('ntfy', 'base_url').rstrip('/')

    except Exception as e:
        print(f"Ошибка парсинга секции [ntfy] в zuliprc: {e}")
        return

    # инициализирую клиент Zulip
    try:
        client = zulip.Client(config_file=ZULIPRC_PATH)
        BOT_EMAIL = client.email
        print(f"Успешно авторизован бот: {BOT_EMAIL}")
    except Exception as e:
        print(f"Ошибка инициализации клиента Zulip: {e}")
        return

    # # получаю ID канала по его имени
    # try:
    #     stream_info = client.get_stream_id(STREAM_NAME)
    #     if stream_info.get('result') == 'success':
    #         STREAM_ID = stream_info.get('stream_id')
    #         print(f"ID канала '{STREAM_NAME}': {STREAM_ID}")
    #     else:
    #         print(f"Ошибка: Не удалось найти ID канала '{STREAM_NAME}': {stream_info.get('msg')}")
    #         return
    # except Exception as e:
    #     print(f"Ошибка при получении ID канала: {e}")
    #     return

    print(f"Сервис запущен. Слушаю канал '{STREAM_NAME}' и шлю персональные пуши...")

    # встроенный long-polling
    try:
        client.call_on_each_event(
            callback=process_event,
            event_types=['message'],
            narrow=[['stream', STREAM_NAME]]
        )
    except Exception as e:
        print(f"критическая ошибка в цикле обработки событий: {e}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nсервис остановлен пользователем")
