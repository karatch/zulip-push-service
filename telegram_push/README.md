## Архитектура приложения для Telegram

```text
       +--------------------------------------------+

       |             База данных (SQLite)           |
       |     Таблица: users (zulip_id <-> tg_id)    |
       +---------------------+----------------------+
                             |
         +-------------------+-------------------+

         |                                       |
         v                                       v
+-----------------+                     +-----------------+

|   Компонент 1   |                     |   Компонент 2   |
|   Скрипт МОСТА  |                     |  Бот интеграции |
| (Bridge Service)|                     |  (Telegram Bot) |
+--------+--------+                     +--------+--------+

         |                                       |
   (Long Polling)                         (aiogram Polling)

         |                                       |
         v                                       v
+-----------------+                     +-----------------+

|   API Zulip     |                     |   Bot API TG    |
|  (Сервер Zulip) |                     | (api.telegram.org)
+-----------------+                     +-----------------+
```


------------------------------
Использование системного менеджера systemd для запуска приложения.

------------------------------
Чтобы успешно собрать асинхронное приложение на aiogram 3.x с помощью PyInstaller и развернуть его как службу, нужно учесть, что фреймворк использует динамические импорты (особенно механизмы фильтров magic-filter и контекстные переменные). Если их не указать, бинарник упадет сразу после запуска.
Ниже приведена точная команда для сборки и пошаговый гайд по развертыванию.

------------------------------
## Шаг 1: Установка PyInstaller и сборка
Компилировать проект нужно строго на той же операционной системе и архитектуре, где он будет работать (т.е. на целевом Linux-сервере или в идентичной виртуалке/Docker-контейнере).

   1. Активируйте ваше виртуальное окружение на сервере и установите PyInstaller:
   
   source venv/bin/bin/activate  # или ваш путь к venv
   pip install pyinstaller
   
   2. Выполните точную команду для сборки в один файл с учетом скрытых зависимостей aiogram:
   
   pyinstaller --onefile \
     --name=zulip-integration \
     --hidden-import=aiogram \
     --hidden-import=aiogram.dispatcher \
     --hidden-import=aiogram.filters \
     --hidden-import=aiogram.fsm.storage.memory \
     --hidden-import=magic_filter \
     --hidden-import=aiohttp \
     run.py
   
   
Что делают эти флаги:

* --onefile — собирает всё приложение, включая интерпретатор Python и библиотеки, в один единственный файл.
* --name — задает имя итоговому файлу (вместо дефолтного run получится красивое zulip-integration).
* --hidden-import — принудительно заставляет PyInstaller упаковать модули, которые aiogram и magic_filter загружают динамически во время работы программы.

После завершения сборки в папке проекта появится директория dist/, а внутри нее — готовый бинарный файл zulip-integration.
------------------------------
## Шаг 2: Перенос и подготовка бинарника

   1. Перенесите созданный файл в постоянную директорию (например, /home/user/zulip_bridge/):
   
   cp dist/zulip-integration /home/user/zulip_bridge/
   
   2. Убедитесь, что рядом с бинарником лежат файлы конфигурации zuliprc и база данных bridge.db.
   3. Сделайте файл исполняемым:
   
   chmod +x /home/user/zulip_bridge/zulip-integration
   
   4. Сделайте тестовый запуск вручную, чтобы убедиться в отсутствии ошибок импорта:
   
   /home/user/zulip_bridge/zulip-integration
   
   (Если всё запустилось без ошибок, прервите выполнение через Ctrl+C).

------------------------------
## Шаг 3: Создание системной службы systemd

   1. Создайте конфигурационный файл службы:
   
   sudo nano /etc/systemd/system/zulip-integration.service
   
   2. Вставьте в него следующую конфигурацию (замените user на имя вашего пользователя в Linux, а пути — на ваши реальные):
   
   [Unit]
   Description=Zulip Telegram Integration Service (Compiled Binary)
   After=network.target
   
   [Service]
   Type=simple
   User=user
   WorkingDirectory=/home/user/zulip_bridge
   
   # Запуск скомпилированного бинарника напрямую без вызова python
   ExecStart=/home/user/zulip_bridge/zulip-integration
   
   # Перезапуск в случае падения
   Restart=always
   RestartSec=5
   
   # Направление логов в системный журнал
   StandardOutput=journal
   StandardError=journal
   
   [Install]
   WantedBy=multi-user.target
   
   3. Сохраните файл (Ctrl+O, Enter) и выйдете из редактора (Ctrl+X).

Благодаря параметру Restart=always и RestartSec=5, если в коде моста или бота произойдет 
непредвиденное исключение (например, на секунду пропадет интернет или упадет база данных), 
systemd подождет 5 секунд и автоматически запустит скрипт заново, обеспечивая 
непрерывную работу интеграции.

------------------------------
## Шаг 4: Активация и управление службой
Зарегистрируйте новую службу в системе и запустите её:

# Перезагружаем менеджер конфигураций systemd
sudo systemctl daemon-reload
# Включаем автоматический запуск службы при старте сервера
sudo systemctl enable zulip-integration.service
# Запускаем службу прямо сейчас
sudo systemctl start zulip-integration.service

## Как проверять работу:

* Чтобы посмотреть текущий статус (работает/упал):

sudo systemctl status zulip-integration.service

* Чтобы смотреть живой поток логов вашего скомпилированного приложения:

sudo journalctl -u zulip-integration.service -f


## Полезные команды для управления
Стандартные команды для управления фоновыми процессами:

* Проверить статус работы (активен/упал):

sudo systemctl status zulip-telegram.service

* Перезапустить вручную (например, после обновления кода):

sudo systemctl restart zulip-telegram.service

* Остановить сервис:

sudo systemctl stop zulip-telegram.service


------------------------------
## Просмотр логов (живой поток)
Если бот не запускается или вы хотите посмотреть, какие ошибки сыплются в консоль, 
используйте утилиту journalctl:

* Посмотреть последние логи бота:

sudo journalctl -u zulip-bot.service -n 50 --no-pager

* Смотреть логи моста в реальном времени (вывод будет обновляться сам при появлении новых строк):

sudo journalctl -u zulip-bridge.service -f

