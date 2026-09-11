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


## Руководство (Telegram)

### 1. Сборка бинарного файла через PyInstaller

Приложение компилируется в один исполняемый файл, который содержит интерпретатор Python и все необходимые зависимости. Сборку необходимо проводить **строго на той же операционной системе** (и архитектуре), где планируется запуск приложения (например, на целевом Linux-сервере).

1. Перейдите в каталог проекта, активируйте ваше виртуальное окружение и установите необходимые зависимости:
   ```bash
   pip install aiogram aiohttp zulip pyinstaller magic-filter
   ```
2. Выполните команду для сборки проекта в один файл с учетом скрытых импортов `aiogram`:
   ```bash
   pyinstaller --clean --onefile \
     --name=tg-integration \
     --hidden-import=aiogram \
     --hidden-import=aiogram.dispatcher \
     --hidden-import=aiogram.filters \
     --hidden-import=aiogram.fsm.storage.memory \
     --hidden-import=magic_filter \
     --hidden-import=aiohttp \
     run.py
   ```
   *После успешного завершения сборки готовый бинарник появится в директории `dist/tg-integration`.*

---

### 2. Структура конфигурационного файла `zuliprc`

Файл конфигурации должен находиться в той же директории, что и исполняемый файл. Он содержит доступы к API серверов Zulip и Telegram.

Создайте файл `zuliprc` со следующим содержимым:

```ini
[api]
# Параметры подключения к вашему корпоративному серверу Zulip
email = bot-name@your-domain.ru
key = abc123xyz456secretkeyzulip
site = https://your-domain.ru

[ntfy]
# Имя канала (Stream) в Zulip, сообщения из которого нужно дублировать
stream = Разработка

[telegram]
# Токен бота, полученный от @BotFather в Telegram
bot_token = 1234567890:ABCdefGhIJKlmNoPQRsTUVwXyZ
```

> **Важно:** Ограничьте права доступа к файлу конфигурации в Linux, чтобы сторонние пользователи не могли прочитать секретные ключи и токены: 
> ```bash
> chmod 600 zuliprc
> ```

---

### 3. Развертывание службы через systemd

1. Создайте рабочую директорию проекта и перенесите туда файлы:
   ```bash
   mkdir -p /home/user/zulip_bridge
   cp dist/tg-integration /home/user/zulip_bridge/
   # Перенесите файл zuliprc в эту же папку
   ```
2. Дайте бинарному файлу права на исполнение:
   ```bash
   chmod +x /home/user/zulip_bridge/tg-integration
   ```
3. Создайте конфигурационный файл службы:
   ```bash
   sudo nano /etc/systemd/system/zulip-integration.service
   ```
4. Вставьте в него следующую конфигурацию (замените `user` и пути на ваши реальные):
   ```ini
   [Unit]
   Description=Zulip to Telegram Integration Service
   After=network.target

   [Service]
   Type=simple
   User=user
   WorkingDirectory=/home/user/zulip_bridge
   ExecStart=/home/user/zulip_bridge/tg-integration
   Restart=always
   RestartSec=5
   StandardOutput=journal
   StandardError=journal

   [Install]
   WantedBy=multi-user.target
   ```
5. Зарегистрируйте и запустите службу:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable zulip-integration.service
   sudo systemctl start zulip-integration.service
   ```

---

### 4. Настройка ротации и очистки логов journald

По умолчанию системный журнал `journald` может занимать значительный объем диска. Чтобы логи приложения не переполнили сервер, необходимо настроить их ротацию по размеру.

#### Автоматическая ротация (Рекомендуется)
1. Откройте файл конфигурации системного журнала:
   ```bash
   sudo nano /etc/systemd/journald.conf
   ```
2. Раскомментируйте или добавьте в секцию `[Journal]` следующие параметры для жесткого ограничения логов (например, до 500 МБ):
   ```ini
   [Journal]
   SystemMaxUse=500M
   SystemMaxFileSize=50M
   SystemKeepFree=1G
   ```
3. Перезапустите службу логирования для применения настроек:
   ```bash
   sudo systemctl restart systemd-journald
   ```

#### Ручная очистка логов (Прямо сейчас)
Если на сервере скопилось много старых логов и вам нужно принудительно освободить место, оставив только последние 500 МБ данных, выполните команду:
```bash
sudo journalctl --vacuum-size=500M
```

---

### 5. Полезные команды для администрирования

* **Просмотр логов в реальном времени ("живой поток"):**
  ```bash
  sudo journalctl -u zulip-integration.service -f
  ```
* **Проверить текущий статус работы процесса (Active/Running):**
  ```bash
  sudo systemctl status zulip-integration.service
  ```
* **Перезапустить сервис (например, после изменения `zuliprc`):**
  ```bash
  sudo systemctl restart zulip-integration.service
  ```
* **Остановить службу (выключить процесс прямо сейчас):**
  ```bash
  sudo systemctl stop zulip-integration.service
  ```
* **Отключить автозапуск (дезактивировать запуск вместе с ОС):**
  ```bash
  sudo systemctl disable zulip-integration.service
  ```
  *Примечание: Команда `disable` не останавливает уже запущенный процесс, она лишь отменяет его автоматический старт при следующей перезагрузке сервера.*
* **Полное отключение (и остановить, и убрать из автозапуска):**
  ```bash
  sudo systemctl stop zulip-integration.service && sudo systemctl disable zulip-integration.service
  ```


