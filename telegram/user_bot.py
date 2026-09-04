import os
import logging
import configparser
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from telegram import database

BASE_DIR = Path(__file__).resolve().parent
ZULIPRC_PATH = BASE_DIR / "zuliprc"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def get_tg_token() -> str:
    if not os.path.exists(ZULIPRC_PATH):
        raise FileNotFoundError(f"Критическая ошибка: Файл {ZULIPRC_PATH} не найден!")
    config = configparser.ConfigParser()
    config.read(ZULIPRC_PATH)
    return config.get('telegram', 'bot_token')


BOT_TOKEN = get_tg_token()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🔐 Привязать Zulip ID"))
    builder.add(types.KeyboardButton(text="📋 Мой статус"))
    builder.add(types.KeyboardButton(text="❌ Отвязать аккаунт"))
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n"
        f"Я бот-уведомитель. Настроим интеграцию с Zulip?",
        reply_markup=get_main_keyboard()
    )


@dp.message(F.text == "📋 Мой статус")
async def check_status(message: types.Message):
    tg_id = str(message.from_user.id)

    associated_zulip_id = database.get_zulip_id_by_tg(tg_id)

    if associated_zulip_id:
        await message.answer(
            f"✅ <b>Ваш аккаунт активен!</b>\n"
            f"• Ваш Telegram ID: <code>{tg_id}</code>\n"
            f"• Связан с Zulip ID: <code>{associated_zulip_id}</code>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "⚠️ <b>Аккаунт не привязан.</b>\nИспользуйте кнопку «🔐 Привязать Zulip ID».",
            parse_mode="HTML"
        )


@dp.message(F.text == "🔐 Привязать Zulip ID")
async def ask_for_id(message: types.Message):
    await message.answer(
        "Чтобы выполнить привязку, отправьте команду `/register` и ваш ID.\n\n"
        "👉 Пример:\n<code>/register 1042</code>",
        parse_mode="HTML"
    )


@dp.message(Command("register"))
async def register_user(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("❌ Ошибка! Укажите числовой ID.\nПример: <code>/register 1042</code>", parse_mode="HTML")
        return

    zulip_id = args[1]
    tg_id = str(message.from_user.id)

    try:
        database.add_user(zulip_id, tg_id)
        await message.answer(
            f"🎉 <b>Успешно сохранено в БД!</b>\n"
            f"Zulip ID <code>{zulip_id}</code> успешно привязан.",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка БД: {e}")
        await message.answer("❌ Ошибка при записи в базу данных.")


@dp.message(F.text == "❌ Отвязать аккаунт")
async def unregister_user(message: types.Message):
    tg_id = str(message.from_user.id)

    if database.remove_user_by_tg(tg_id):
        await message.answer("📴 <b>Готово.</b> Связь разорвана, уведомления отключены.", parse_mode="HTML")
    else:
        await message.answer("Ваш Telegram ID не был найден в базе данных.")


async def main():
    # на всякий случай инициализирую БД и тут (если Бот запущен раньше моста)
    database.init_db()
    print("Пользовательский бот (SQLite) запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
