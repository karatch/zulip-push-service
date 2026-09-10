import logging
from aiogram import Dispatcher, types, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder

import database

dp = Dispatcher()


class Registration(StatesGroup):
    waiting_for_zulip_id = State()


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
    logging.info(f"[Bot] Пользователь {message.from_user.id} (@{message.from_user.username}) вызвал /start")
    await message.answer(
        f"Привет, {message.from_user.full_name}! 👋\nНастроим интеграцию с Zulip?",
        reply_markup=get_main_keyboard()
    )


@dp.message(StateFilter(Registration.waiting_for_zulip_id), F.text == "🚫 Отмена")
async def cancel_registration(message: types.Message, state: FSMContext):
    logging.info(f"[Bot] Пользователь {message.from_user.id} отменил процесс регистрации.")
    await state.clear()
    await message.answer("Регистрация отменена.", reply_markup=get_main_keyboard())


@dp.message(F.text == "📋 Мой статус")
async def check_status(message: types.Message):
    tg_id = str(message.from_user.id)
    logging.info(f"[Bot] Пользователь {tg_id} запросил статус привязки.")

    associated_zulip_id = database.get_zulip_id_by_tg(tg_id)
    if associated_zulip_id:
        logging.info(f"[Bot] Статус {tg_id}: Активен (Связан с Zulip ID {associated_zulip_id})")
        await message.answer(
            f"✅ <b>Ваш аккаунт активен!</b>\n• TG ID: <code>{tg_id}</code>\n• Zulip ID: <code>{associated_zulip_id}</code>",
            parse_mode="HTML"
        )
    else:
        logging.info(f"[Bot] Статус {tg_id}: Не привязан.")
        await message.answer("⚠️ <b>Аккаунт не привязан.</b> Нажмите «🔐 Привязать Zulip ID».", parse_mode="HTML")


@dp.message(F.text == "🔐 Привязать Zulip ID")
async def ask_for_id(message: types.Message, state: FSMContext):
    logging.info(f"[Bot] Пользователь {message.from_user.id} инициировал привязку аккаунта. Перевод в состояние FSM.")
    await state.set_state(Registration.waiting_for_zulip_id)
    await message.answer("Пожалуйста, введите ваш Zulip ID (только цифры):", reply_markup=get_cancel_keyboard())


@dp.message(Registration.waiting_for_zulip_id)
async def process_zulip_id(message: types.Message, state: FSMContext):
    zulip_id = message.text.strip()
    tg_id = str(message.from_user.id)
    logging.info(f"[Bot] Пользователь {tg_id} ввел потенциальный Zulip ID: '{zulip_id}'")

    if not zulip_id.isdigit():
        logging.warning(f"[Bot] Ошибка валидации! Ввод пользователя {tg_id} не является числом.")
        await message.answer("❌ Ошибка! Введите только цифры или нажмите «🚫 Отмена».")
        return

    try:
        logging.info(f"[Bot] Запись связи в БД: Zulip ID {zulip_id} <-> TG ID {tg_id}")
        database.add_user(zulip_id, tg_id)
        logging.info(f"[Bot] Успешная привязка для пользователя {tg_id}.")
        await message.answer(
            f"🎉 <b>Успешно!</b>\nZulip ID <code>{zulip_id}</code> привязан.",
            parse_mode="HTML", reply_markup=get_main_keyboard()
        )
        await state.clear()
    except Exception as e:
        logging.error(f"[Bot] Критическая ошибка записи привязки в БД для {tg_id}: {e}")
        await message.answer("❌ Ошибка при записи в базу данных.", reply_markup=get_main_keyboard())
        await state.clear()


@dp.message(F.text == "❌ Отвязать аккаунт")
async def unregister_user(message: types.Message):
    tg_id = str(message.from_user.id)
    logging.info(f"[Bot] Пользователь {tg_id} запросил удаление аккаунта.")

    if database.remove_user_by_tg(tg_id):
        logging.info(f"[Bot] Аккаунт {tg_id} успешно удален из БД.")
        await message.answer("📴 Связь разорвана, уведомления отключены.", reply_markup=get_main_keyboard())
    else:
        logging.warning(f"[Bot] Не удалось удалить аккаунт {tg_id}: запись отсутствует в БД.")
        await message.answer("Ваш Telegram ID не найден в базе данных.")
