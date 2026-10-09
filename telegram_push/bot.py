import asyncio
import logging
import os
import random
from aiogram import Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import ReplyKeyboardBuilder

import database

dp = Dispatcher()


class Registration(StatesGroup):
    waiting_for_email = State()
    waiting_for_otp = State()


def get_main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🔐 Привязать Zulip ID"))
    builder.add(types.KeyboardButton(text="📋 Мой статус"))
    builder.add(types.KeyboardButton(text="❌ Отвязать аккаунт"))
    builder.add(types.KeyboardButton(text="❓ Помощь / Инструкция"))
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🚫 Отмена"))
    return builder.as_markup(resize_keyboard=True)


def get_help_text():
    return (
        "ℹ️ <b>Как работают Push-уведомления:</b>\n"
        "Бот пересылает вам сообщения из всех публичных каналов Zulip, "
        "на которые вы подписаны, если их написал кто-то другой.\n\n"
        "ℹ️ <b>Защищенная активация уведомлений:</b>\n"
        "1. Нажмите кнопку «🔐 Привязать Zulip ID».\n"
        "2. Введите ваш <b>корпоративный email</b>.\n"
        "3. Бот пришлет вам <b>секретный код верификации</b> прямо внутрь вашего аккаунта в Zulip.\n"
        "4. Введите полученный код здесь, чтобы завершить привязку."
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = (
        f"Привет, {message.from_user.full_name}! 👋\n\n"
        f"Я помогу настроить безопасную доставку уведомлений из Zulip в Telegram.\n\n"
        f"{get_help_text()}"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(F.text == "❓ Помощь / Инструкция")
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(get_help_text(), reply_markup=get_main_keyboard(), parse_mode="HTML")


@dp.message(StateFilter(Registration.waiting_for_email), F.text == "🚫 Отмена")
@dp.message(StateFilter(Registration.waiting_for_otp), F.text == "🚫 Отмена")
async def cancel_registration(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Ввод отменен. Возвращаем главное меню.", reply_markup=get_main_keyboard())


@dp.message(F.text == "🔐 Привязать Zulip ID")
@dp.message(Command("bind"))
async def ask_for_email(message: types.Message, state: FSMContext):
    await state.set_state(Registration.waiting_for_email)
    await message.answer(
        "📝 Пожалуйста, введите ваш <b>корпоративный email</b> (например, <code>user@company.com</code>):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(Registration.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext, zulip_bridge):
    email = message.text.strip().lower()
    if "@" not in email:
        await message.answer("❌ Неверный формат email!")
        return

    domain = email.split("@")[-1]
    allowed_domains = [d.strip() for d in os.getenv("ALLOWED_COMPANY_DOMAINS", "").split(",") if d.strip()]
    if allowed_domains and domain not in allowed_domains:
        logging.warning(f"[Security] Отклонен ввод email с недоверенным доменом: {email}")
        await message.answer("❌ Доступ запрещен.")
        return

    await message.answer("🔍 Проверяем ваш email в Zulip...")

    user_info = await asyncio.to_thread(zulip_bridge.get_user_id_by_email, email)
    if not user_info:
        await message.answer("❌ Пользователь с таким email не найден в Zulip!")
        return

    zulip_id = user_info["zulip_id"]
    full_name = user_info["full_name"]
    otp_code = str(random.randint(1000, 9999))

    msg_text = (
        f"🤖 **Запрос на привязку Telegram-уведомлений**\n\n"
        f"Уважаемый(ая) {full_name}, кто-то запросил подключение push-уведомлений для вашего аккаунта.\n"
        f"Ваш одноразовый код подтверждения: **{otp_code}**\n\n"
        f"Введите эти цифры в Telegram-боте."
    )

    if not zulip_bridge.send_zulip_private_message(int(zulip_id), msg_text):
        await message.answer("❌ Не удалось отправить код верификации в Zulip.")
        return

    await state.update_data(correct_otp=otp_code, target_zulip_id=zulip_id)
    await state.set_state(Registration.waiting_for_otp)
    await message.answer(
        f"📧 Код отправлен в ваши **личные сообщения Zulip**.\n\n"
        f"Введите полученный 4-значный код здесь:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )


@dp.message(Registration.waiting_for_otp)
async def process_otp(message: types.Message, state: FSMContext):
    input_otp = message.text.strip()
    user_data = await state.get_data()
    correct_otp = user_data.get("correct_otp")
    zulip_id = user_data.get("target_zulip_id")
    tg_id = str(message.from_user.id)

    if input_otp != correct_otp:
        logging.warning(f"[Security] Неверный OTP от TG ID {tg_id}")
        await message.answer("❌ Неверный код! Попробуйте еще раз или нажмите «🚫 Отмена».")
        return

    try:
        await asyncio.to_thread(database.add_user, zulip_id, tg_id)
        logging.info(f"[Bot] Безопасная привязка завершена: Zulip {zulip_id} <-> TG {tg_id}")
        await message.answer(
            f"🎉 <b>Интеграция успешно активирована!</b>\n\n"
            f"Ваш Telegram аккаунт связан с Zulip ID <code>{zulip_id}</code>.",
            parse_mode="HTML", reply_markup=get_main_keyboard()
        )
        await state.clear()
    except Exception as e:
        logging.error(f"[Bot] Ошибка записи в БД: {e}")
        await message.answer("❌ Ошибка при сохранении в базу данных.", reply_markup=get_main_keyboard())
        await state.clear()


@dp.message(F.text == "📋 Мой статус")
@dp.message(Command("status"))
async def check_status(message: types.Message):
    tg_id = str(message.from_user.id)
    associated_zulip_id = await asyncio.to_thread(database.get_zulip_id_by_tg, tg_id)

    if associated_zulip_id:
        await message.answer(
            f"✅ <b>Ваша интеграция активна!</b>\n\n"
            f"• TG ID: <code>{tg_id}</code>\n"
            f"• Zulip ID: <code>{associated_zulip_id}</code>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            "⚠️ <b>Аккаунт не привязан.</b>\n"
            "Нажмите кнопку «🔐 Привязать Zulip ID».",
            parse_mode="HTML"
        )


@dp.message(F.text == "❌ Отвязать аккаунт")
@dp.message(Command("unbind"))
async def unregister_user(message: types.Message):
    tg_id = str(message.from_user.id)
    success = await asyncio.to_thread(database.remove_user_by_tg, tg_id)
    if success:
        await message.answer("📴 <b>Интеграция отключена.</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")
    else:
        await message.answer("Ваш Telegram-аккаунт не был привязан к системе.")