## Архитектура приложения

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



------------------------------
Чтобы скрипты работали стабильно 24/7, автоматически запускались при старте сервера и поднимались сами в случае критических ошибок, в Linux используется системный менеджер systemd.
Вам понадобятся два независимых сервиса - по одному на каждый скрипт (один для моста, второй для бота). Они будут работать параллельно, используя один и тот же файл базы данных.
Ниже приведена пошаговая инструкция по настройке.
------------------------------
## Шаг 1: Подготовка окружения на сервере
Предположим, что ваш проект лежит на сервере в папке /home/user/zulip_bridge/, а файлы называются bridge.py, bot.py и database.py.
Убедитесь, что внутри ваших скриптов зависимости импортируются корректно. Если вы используете виртуальное окружение (venv), путь к нему будет /home/user/zulip_bridge/venv/bin/python. Если используете глобальный Python, то обычно это /usr/bin/python3.
------------------------------
## Шаг 2: Создание сервиса для БОТА
Откройте терминал сервера и создайте файл конфигурации сервиса для бота с помощью текстового редактора (например, nano):

sudo nano /etc/systemd/system/zulip-bot.service

Вставьте в него следующее содержимое (замените /home/user/zulip_bridge на реальный путь к вашей папке, а user — на имя вашего пользователя в Linux):

[Unit]
Description=Zulip Telegram Bot Service
After=network.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/zulip_bridge

# Укажите путь к вашему Python (из venv или глобальный)
ExecStart=/home/user/zulip_bridge/venv/bin/python bot.py

# Настройки автоперезапуска при сбоях
Restart=always
RestartSec=5

# Логирование вывода в системный журнал
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

Нажмите Ctrl+O, затем Enter для сохранения, и Ctrl+X для выхода из редактора.
------------------------------
## Шаг 3: Создание сервиса для МОСТА
Теперь создаем аналогичный файл для скрипта моста:

sudo nano /etc/systemd/system/zulip-bridge.service

Вставьте в него конфигурацию:

[Unit]
Description=Zulip Telegram Bridge Service
After=network.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/zulip_bridge

# Укажите путь к вашему Python (из venv или глобальный)
ExecStart=/home/user/zulip_bridge/venv/bin/python bridge.py

# Настройки автоперезапуска при сбоях
Restart=always
RestartSec=5

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target

Сохраните файл и выйдите (Ctrl+O, Enter, Ctrl+X).
------------------------------
## Шаг 4: Регистрация и запуск сервисов
Чтобы система увидела новые конфигурационные файлы и запустила их в фоновом режиме, выполните по очереди следующие команды:

# 1. Перезагружаем конфигурацию systemd, чтобы применить изменения
sudo systemctl daemon-reload
# 2. Включаем автозапуск сервисов при старте операционной системы
sudo systemctl enable zulip-bot.service
sudo systemctl enable zulip-bridge.service
# 3. Запускаем сервисы прямо сейчас
sudo systemctl start zulip-bot.service
sudo systemctl start zulip-bridge.service

------------------------------
## Шаг 5: Полезные команды для управления
Теперь вы можете управлять вашими фоновыми процессами с помощью стандартных команд:

* Проверить статус работы (активен/упал):

sudo systemctl status zulip-bot.service
sudo systemctl status zulip-bridge.service

* Перезапустить вручную (например, после обновления кода):

sudo systemctl restart zulip-bot.service
sudo systemctl restart zulip-bridge.service

* Остановить сервисы:

sudo systemctl stop zulip-bot.service
sudo systemctl stop zulip-bridge.service


------------------------------
## Шаг 6: Просмотр логов (живой поток)
Если бот не запускается или вы хотите посмотреть, какие ошибки сыплются в консоль, используйте утилиту journalctl:

* Посмотреть последние логи бота:

sudo journalctl -u zulip-bot.service -n 50 --no-pager

* Смотреть логи моста в реальном времени (вывод будет обновляться сам при появлении новых строк):

sudo journalctl -u zulip-bridge.service -f


Благодаря параметру Restart=always и RestartSec=5, если в коде моста или бота произойдет непредвиденное исключение (например, на секунду пропадет интернет или упадет база данных), systemd подождет 5 секунд и автоматически запустит скрипт заново, обеспечивая непрерывную работу интеграции.
```