import logging
from aiogram import Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder

import database

dp = Dispatcher()


# Состояние для пошаговой регистрации
class Registration(StatesGroup):
    waiting_for_zulip_id = State()


# Главное reply-меню для пользователя
def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🔐 Привязать Zulip ID"))
    builder.add(types.KeyboardButton(text="📋 Мой статус"))
    builder.add(types.KeyboardButton(text="❌ Отвязать аккаунт"))
    builder.add(types.KeyboardButton(text="❓ Помощь / Инструкция"))
    builder.adjust(2, 2)  # Кнопки по две в ряд
    return builder.as_markup(resize_keyboard=True)


# Клавиатура отмены в режиме ввода ID
def get_cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🚫 Отмена"))
    return builder.as_markup(resize_keyboard=True)


# Текст подробной справки
def get_help_text():
    return (
        "ℹ️ <b>Как работают Push-уведомления:</b>\n"
        "Бот пересылает вам сообщения из <u>всех публичных каналов Zulip</u>, "
        "на которые вы подписаны, если их написал кто-то другой.\n\n"
        "ℹ️ <b>Как начать получать уведомления:</b>\n"
        "1. Откройте веб-версию или приложение Zulip.\n"
        "2. Перейдите в <b>Настройки</b> -> <b>Профиль</b>.\n"
        "3. Найдите поле <b>User ID</b> (это число, например: <code>12</code>).\n"
        "4. Нажмите кнопку «🔐 Привязать Zulip ID» здесь в боте и введите это число.\n\n"
        "⚠️ Если вы не привяжете ID, уведомления приходить не будут!"
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    logging.info(f"[Bot] Пользователь {message.from_user.id} запустил бота.")

    welcome_text = (
        f"Привет, {message.from_user.full_name}! 👋\n\n"
        f"Я помогу настроить доставку push-уведомлений из Zulip прямо сюда, в Telegram.\n\n"
        f"{get_help_text()}"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(F.text == "❓ Помощь / Инструкция")
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(get_help_text(), reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(StateFilter(Registration.waiting_for_zulip_id), F.text == "🚫 Отмена")
async def cancel_registration(message: types.Message, state: FSMContext):
    logging.info(f"[Bot] Пользователь {message.from_user.id} отменил регистрацию.")
    await state.clear()
    await message.answer("Ввод отменен. Возвращаем главное меню.", reply_markup=get_main_keyboard())


@dp.message(F.text == "📋 Мой статус")
@dp.message(Command("status"))
async def check_status(message: types.Message):
    tg_id = str(message.from_user.id)
    associated_zulip_id = database.get_zulip_id_by_tg(tg_id)

    if associated_zulip_id:
        await message.answer(
            f"✅ <b>Ваша интеграция активна!</b>\n\n"
            f"• Ваш Telegram ID: <code>{tg_id}</code>\n"
            f"• Связанный Zulip ID: <code>{associated_zulip_id}</code>\n\n"
            f"Вы будете получать пуши из всех каналов Zulip, где вы состоите.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "⚠️ <b>Аккаунт не привязан.</b>\n"
            "Нажмите кнопку «🔐 Привязать Zulip ID», чтобы активировать уведомления.",
            parse_mode="HTML"
        )


@dp.message(F.text == "🔐 Привязать Zulip ID")
@dp.message(Command("bind"))
async def ask_for_id(message: types.Message, state: FSMContext):
    await state.set_state(Registration.waiting_for_zulip_id)
    await message.answer(
        "📝 Пожалуйста, введите ваш числовой <b>Zulip ID</b> (только цифры):\n\n"
        "<i>Его можно найти в Zulip: Настройки -> Профиль -> User ID.</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(Registration.waiting_for_zulip_id)
async def process_zulip_id(message: types.Message, state: FSMContext):
    zulip_id = message.text.strip()
    tg_id = str(message.from_user.id)

    if not zulip_id.isdigit():
        await message.answer("❌ Ошибка! ID должен состоять только из цифр. Попробуйте еще раз или нажмите «🚫 Отмена».")
        return

    try:
        database.add_user(zulip_id, tg_id)
        logging.info(f"[Bot] Успешная привязка: Zulip {zulip_id} <-> TG {tg_id}")
        await message.answer(
            f"🎉 <b>Успешно привязано!</b>\n\n"
            f"Zulip ID <code>{zulip_id}</code> успешно сохранен. "
            f"Теперь новые сообщения из ваших каналов будут дублироваться сюда.",
            parse_mode="HTML", reply_markup=get_main_keyboard()
        )
        await state.clear()
    except Exception as e:
        logging.error(f"[Bot] Ошибка записи в БД для {tg_id}: {e}")
        await message.answer("❌ Ошибка при сохранении в базу данных.", reply_markup=get_main_keyboard())
        await state.clear()


@dp.message(F.text == "❌ Отвязать аккаунт")
@dp.message(Command("unbind"))
async def unregister_user(message: types.Message):
    tg_id = str(message.from_user.id)

    if database.remove_user_by_tg(tg_id):
        await message.answer(
            "📴 <b>Интеграция отключена.</b>\n"
            "Связь с Zulip разорвана, уведомления больше приходить не будут.",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await message.answer("Ваш Telegram-аккаунт не был привязан к системе.")
