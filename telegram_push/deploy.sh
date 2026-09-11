#!/usr/bin/env bash

# Выходим из скрипта, если любая из команд завершится ошибкой
set -e

# --- НАСТРОЙКИ (ИЗМЕНИТЕ ПОД СЕБЯ) ---
PROJECT_DIR="/home/user/zulip_bridge"               # Папка вашего проекта
VENV_PATH="/home/user/zulip_bridge/venv"            # Путь к виртуальному окружению
SERVICE_NAME="zulip-integration.service"            # Имя systemd-службы
BINARY_NAME="zulip-integration"                      # Имя итогового бинарника
USER_NAME="user"                                    # Локальный пользователь в Linux

echo "=== 🚀 Начало процесса автоматического деплоя ==="

cd "$PROJECT_DIR"

# 1. Активация виртуального окружения
if [ -f "$VENV_PATH/bin/activate" ]; then
    echo "[1/5] Активация виртуального окружения Python..."
    source "$VENV_PATH/bin/activate"
else
    echo "❌ Ошибка: Виртуальное окружение не найдено по пути $VENV_PATH"
    exit 1
fi

# 2. Компиляция через PyInstaller
echo "[2/5] Запуск компиляции приложения через PyInstaller..."
pyinstaller --clean --onefile \
  --name="$BINARY_NAME" \
  --hidden-import=aiogram \
  --hidden-import=aiogram.dispatcher \
  --hidden-import=aiogram.filters \
  --hidden-import=aiogram.fsm.storage.memory \
  --hidden-import=magic_filter \
  --hidden-import=aiohttp \
  run.py

# 3. Замена старого бинарного файла
echo "[3/5] Обновление исполняемого файла в рабочей директории..."
if [ -f "dist/$BINARY_NAME" ]; then
    # Копируем свежий бинарник на его постоянное место
    cp "dist/$BINARY_NAME" "$PROJECT_DIR/$BINARY_NAME"
    # Даем права на исполнение и устанавливаем владельца
    chmod +x "$PROJECT_DIR/$BINARY_NAME"
    chown "$USER_NAME:$USER_NAME" "$PROJECT_DIR/$BINARY_NAME"
else
    echo "❌ Ошибка: Компиляция завершилась, но бинарный файл не появился в dist/"
    exit 1
fi

# 4. Перезапуск системной службы Linux
echo "[4/5] Перезапуск службы $SERVICE_NAME через systemctl..."
# Так как управление службами требует root-прав, скрипт запросит sudo (или выполнится под root)
sudo systemctl restart "$SERVICE_NAME"

# 5. Очистка временного мусора после PyInstaller
echo "[5/5] Очистка временных файлов сборки (build и .spec)..."
rm -rf build/
rm -f "$BINARY_NAME.spec"

echo "=== Деплой успешно завершен! Служба обновлена и запущена ==="
echo "Для просмотра живых логов выполните: sudo journalctl -u $SERVICE_NAME -f"