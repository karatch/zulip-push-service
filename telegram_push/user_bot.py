import os
import logging
import configparser
import asyncio
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder

import database

BASE_DIR = Path(__file__).resolve().parent
ZULIPRC_PATH = BASE_DIR / "zuliprc"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

dp = Dispatcher()


# --- FSM (Finite State Machine) ---
class Registration(StatesGroup):
    waiting_for_zulip_id = State()


def get_tg_token() -> str:
    if not os.path.exists(ZULIPRC_PATH):
        raise FileNotFoundError(f"Критическая ошибка: Файл {ZULIPRC_PATH} не найден!")
    config = configparser.ConfigParser()
    config.read(ZULIPRC_PATH)
    return config.get('telegram', 'bot_token')


def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🔐 Привязать Zulip ID"))
    builder.add(types.KeyboardButton(text="📋 Мой статус"))
    builder.add(types.KeyboardButton(text="❌ Отвязать аккаунт"))
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)


def get_cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🚫 Отмена"))
    return builder.as_markup(resize_keyboard=True)


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\n"
        f"Я бот-уведомитель. Настроим интеграцию с Zulip?",
        reply_markup=get_main_keyboard()
    )


# Хэндлер отмены
@dp.message(StateFilter(Registration.waiting_for_zulip_id), F.text == "🚫 Отмена")
async def cancel_registration(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Регистрация отменена.",
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


# Шаг 1 FSM: Пользователь нажал на кнопку привязки
@dp.message(F.text == "🔐 Привязать Zulip ID")
async def ask_for_id(message: types.Message, state: FSMContext):
    await state.set_state(Registration.waiting_for_zulip_id)
    await message.answer(
        "Пожалуйста, **введите ваш Zulip ID** (только цифры):",
        reply_markup=get_cancel_keyboard()  # Меняем меню на кнопку "Отмена"
    )


# Шаг 2 FSM: Перехватываем ввод ID
@dp.message(Registration.waiting_for_zulip_id)
async def process_zulip_id(message: types.Message, state: FSMContext):
    zulip_id = message.text.strip()

    if not zulip_id.isdigit():
        await message.answer(
            "❌ Ошибка! ID должен состоять только из цифр.\n"
            "Попробуйте еще раз или нажмите «🚫 Отмена»."
        )
        return

    tg_id = str(message.from_user.id)

    try:
        database.add_user(zulip_id, tg_id)
        await message.answer(
            f"🎉 <b>Успешно сохранено в БД!</b>\n"
            f"Zulip ID <code>{zulip_id}</code> успешно привязан.",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()  # Возвращаем главное меню
        )
        await state.clear()  # Сценарий завершен, очищаем память FSM
    except Exception as e:
        logging.error(f"Ошибка БД: {e}")
        await message.answer(
            "❌ Ошибка при записи в базу данных. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )
        await state.clear()


@dp.message(F.text == "❌ Отвязать аккаунт")
async def unregister_user(message: types.Message):
    tg_id = str(message.from_user.id)

    if database.remove_user_by_tg(tg_id):
        await message.answer("📴 <b>Готово.</b> Связь разорвана, уведомления отключены.", parse_mode="HTML")
    else:
        await message.answer("Ваш Telegram ID не был найден в базе данных.")


async def main():
    database.init_db()

    try:
        bot_token = get_tg_token()
    except Exception as e:
        logging.error(e)
        return

    bot = Bot(token=bot_token)

    print("Пользовательский бот (SQLite) успешно запущен...")

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
