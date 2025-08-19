import os
from datetime import datetime, timedelta
import pytz

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, User
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from supabase import Client

from modules.supabase_handler import (
    get_or_create_user, delete_user_messages,
    update_user_language, update_user_model, get_reasoning_text,
    get_user_chat_info, get_user_model
)
from modules.translator import Translator
from modules.html_parser import process_telegram_html, escape_html
from modules.core_logic import process_text_message
from modules.utils import send_long_message, load_models
from modules.limit_handler import check_and_handle_limit



router = Router()


async def get_start_menu(user: User, supabase: Client, translator: Translator, lang_code: str):
    await get_or_create_user(supabase, user.id, user.username or "N/A")
    
    start_text = translator.get_text("start_message", lang_code).format(username=escape_html(user.username or user.first_name))

    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 Start New Chat", callback_data="start_newchat")
    builder.button(text="⚙️ Settings", callback_data="start_settings")
    builder.button(text="📊 Check Status", callback_data="start_status")
    builder.button(text="🌐 Change Language", callback_data="start_lang")
    builder.adjust(2)

    return start_text, builder.as_markup()

@router.message(CommandStart())
async def handle_start(message: Message, supabase: Client, translator: Translator, lang_code: str):
    start_text, start_markup = await get_start_menu(message.from_user, supabase, translator, lang_code)
    await message.answer(start_text, reply_markup=start_markup)

# --- HANDLER UNTUK TOMBOL-TOMBOL DARI MENU START ---
@router.callback_query(F.data == "start_newchat")
async def handle_start_newchat_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    await callback.answer()
    await handle_newchat(callback, supabase, translator, lang_code)

@router.callback_query(F.data == "start_settings")
async def handle_start_settings_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    await callback.answer()
    await handle_settings(callback, supabase, translator, lang_code)

@router.callback_query(F.data == "start_status")
async def handle_start_status_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    await callback.answer()
    await handle_status(callback, supabase, translator, lang_code)

@router.callback_query(F.data == "start_lang")
async def handle_start_lang_callback(callback: CallbackQuery, translator: Translator, lang_code: str):
    await callback.answer()
    await handle_lang(callback, translator, lang_code)

@router.callback_query(F.data == "back_to_start")
async def handle_back_to_start_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    start_text, start_markup = await get_start_menu(callback.from_user, supabase, translator, lang_code)
    await callback.message.edit_text(start_text, reply_markup=start_markup)
    await callback.answer()

# --- FUNGSI-FUNGSI UTAMA YANG TELAH DIPERBAIKI ---
@router.message(Command("newchat"))
async def handle_newchat(event: Message | CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    user_id = event.from_user.id
    success = await delete_user_messages(supabase, user_id)
    response_text = translator.get_text("newchat_success" if success else "newchat_fail", lang_code)
    
    if isinstance(event, Message):
        await event.answer(response_text)
    else: # Jika dari callback, edit pesan
        await event.message.edit_text(response_text)

@router.message(Command("status", "info"))
async def handle_status(event: Message | CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    user_id = event.from_user.id
    try: limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
    except (ValueError, TypeError): limit = 20
    await check_and_handle_limit(supabase, user_id)
    user_info = await get_user_chat_info(supabase, user_id)
    usage = user_info.get('chat_count', 0) if user_info else 0
    now_utc, tomorrow_utc = datetime.now(pytz.utc), datetime.now(pytz.utc).date() + timedelta(days=1)
    midnight_utc = datetime.combine(tomorrow_utc, datetime.min.time(), tzinfo=pytz.utc)
    time_left = midnight_utc - now_utc
    hours_left, minutes_left = time_left.seconds // 3600, (time_left.seconds % 3600) // 60
    status_text = translator.get_text("status_message", lang_code).format(user_id=user_id, usage=usage, limit=limit, hours=hours_left, minutes=minutes_left)
    
    if isinstance(event, Message):
        await event.answer(status_text)
    else:
        await event.message.edit_text(status_text, reply_markup=InlineKeyboardBuilder().button(text="⬅️ Back", callback_data="back_to_start").as_markup())

@router.message(Command("lang"))
async def handle_lang(event: Message | CallbackQuery, translator: Translator, lang_code: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="English 🇬🇧", callback_data="lang_en")
    builder.button(text="Indonesia 🇮🇩", callback_data="lang_id")
    builder.button(text="⬅️ Back", callback_data="back_to_start")
    builder.adjust(2, 1) # 2 tombol bahasa, 1 tombol back
    
    lang_text = translator.get_text("lang_select", lang_code)
    
    if isinstance(event, Message):
        await event.answer(lang_text, reply_markup=builder.as_markup())
    else:
        await event.message.edit_text(lang_text, reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("lang_"))
async def handle_lang_callback(callback: CallbackQuery, supabase: Client, translator: Translator):
    new_lang_code, user_id = callback.data.split("_")[1], callback.from_user.id
    await update_user_language(supabase, user_id, new_lang_code)
    confirmation_message = translator.get_text(f"lang_updated_{new_lang_code}", new_lang_code)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="back_to_start")
    await callback.message.edit_text(confirmation_message, reply_markup=builder.as_markup())
    await callback.answer()

@router.message(Command("settings"))
async def handle_settings(event: Message | CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    user_id = event.from_user.id
    active_model_id = await get_user_model(supabase, user_id)
    models = load_models()
    current_model_name = next((model['name'] for model in models if model['value'] == active_model_id), "Unknown")
    settings_text = translator.get_text("settings_menu", lang_code).format(current_model_name=escape_html(current_model_name))
    
    builder = InlineKeyboardBuilder()
    builder.button(text=translator.get_text("change_model_button", lang_code), callback_data="show_models")
    builder.button(text="⬅️ Back", callback_data="back_to_start")
    builder.adjust(1)
    
    if isinstance(event, Message):
        await event.answer(settings_text, reply_markup=builder.as_markup())
    else:
        await event.message.edit_text(settings_text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "show_models")
async def show_models_callback(callback: CallbackQuery, translator: Translator, lang_code: str):
    models = load_models()
    builder = InlineKeyboardBuilder()
    for model in models:
        builder.button(text=f"{model['name']} ({model['provider']})", callback_data=f"setmodel_{model['value']}")
    builder.button(text="⬅️ Back", callback_data="start_settings") # Kembali ke menu settings
    builder.adjust(1)
    
    await callback.message.edit_text(translator.get_text("select_model", lang_code), reply_markup=builder.as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith("setmodel_"))
async def set_model_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    model_value, user_id = callback.data.split("_")[1], callback.from_user.id
    await update_user_model(supabase, user_id, model_value)
    models = load_models()
    model_name = next((model['name'] for model in models if model['value'] == model_value), "Unknown")
    confirmation_message = translator.get_text("model_updated", lang_code).format(model_name=model_name)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="start_settings")
    await callback.message.edit_text(confirmation_message, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("show_reasoning_"))
async def show_reasoning_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    message_id = callback.data.split("_")[2]
    reasoning_text = await get_reasoning_text(supabase, message_id)
    
    await callback.message.edit_reply_markup(reply_markup=None)

    if reasoning_text:
        reasoning_title = translator.get_text("reasoning_title", lang_code)
        full_reasoning_text = reasoning_title + reasoning_text
        
        try:
            parsed_reasoning = process_telegram_html(full_reasoning_text)
            await send_long_message(callback.message, parsed_reasoning)
        except TelegramBadRequest:
            plain_text_reasoning = escape_html(full_reasoning_text)
            await send_long_message(callback.message, plain_text_reasoning, parse_mode=None)
    else:
        await callback.answer("Reasoning not found.", show_alert=True)
    
    await callback.answer()

@router.message(F.text & ~F.text.startswith('/'))
async def handle_message(message: Message, supabase: Client, translator: Translator, lang_code: str):
    # <-- PERUBAHAN: Seluruh isi fungsi diganti dengan satu baris panggilan ini
    await process_text_message(message, message.text, supabase, translator, lang_code)

@router.message(Command("ai", "chat", "ask"), F.photo == None)
async def handle_group_text_command(message: Message, command: CommandObject, supabase: Client, translator: Translator, lang_code: str):
    if command.args:
        await process_text_message(message, command.args, supabase, translator, lang_code)
    else:
        await message.reply(translator.get_text("group_command_usage", lang_code))