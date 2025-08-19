import os
import asyncio
import json
import re
from datetime import datetime, timedelta
import pytz

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from supabase import Client

from modules.supabase_handler import (
    get_or_create_user, save_message, delete_user_messages,
    update_user_language, update_user_model, get_reasoning_text,
    get_user_chat_info, get_user_model
)
from modules.groq_handler import get_groq_response
from modules.translator import Translator
from modules.html_parser import process_telegram_html, escape_html
from modules.limit_handler import check_and_handle_limit, increment_chat_count


router = Router()

def load_models():
    try:
        with open("models.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

async def send_long_message(message: Message, text: str, parse_mode: str = ParseMode.HTML, reply_markup: InlineKeyboardMarkup = None):
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        try:
            if message.from_user.id == message.chat.id: # Private chat
                 await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
            else: # Group chat
                 await message.reply(text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest:
            await message.reply(escape_html(text), parse_mode=None, reply_markup=reply_markup)
        return

    parts = []
    open_tags = []
    
    while len(text) > 0:
        if len(text) <= MAX_LENGTH:
            parts.append(text)
            break

        part = text[:MAX_LENGTH]
        
        last_newline = part.rfind('\n')
        split_pos = last_newline if last_newline != -1 else MAX_LENGTH
        
        part_to_send = text[:split_pos]
        
        for tag_match in re.finditer(r"<(/)?([a-zA-Z0-9_-]+)[^>]*>", part_to_send):
            is_closing, tag_name = tag_match.groups()
            tag_name = tag_name.lower()
            if is_closing:
                if open_tags and open_tags[-1] == tag_name:
                    open_tags.pop()
            elif not tag_match.group(0).endswith("/>"):
                open_tags.append(tag_name)
        
        closing_tags = ""
        if open_tags:
            for tag in reversed(open_tags):
                closing_tags += f"</{tag}>"
        
        part_to_send += closing_tags
        parts.append(part_to_send)
        
        opening_tags = ""
        if open_tags:
            for tag in open_tags:
                opening_tags += f"<{tag}>"

        text = opening_tags + text[split_pos:].lstrip()

    for i, part in enumerate(parts):
        is_last_part = (i == len(parts) - 1)
        current_markup = reply_markup if is_last_part else None
        
        try:
            if i == 0 and message.chat.type != 'private':
                 await message.reply(part, parse_mode=parse_mode, reply_markup=current_markup)
            else:
                 await message.answer(part, parse_mode=parse_mode, reply_markup=current_markup)
        except TelegramBadRequest:
            safe_part = escape_html(part)
            if i == 0 and message.chat.type != 'private':
                await message.reply(safe_part, parse_mode=None, reply_markup=current_markup)
            else:
                await message.answer(safe_part, parse_mode=None, reply_markup=current_markup)

        await asyncio.sleep(0.5)


@router.message(CommandStart())
async def handle_start(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    username = message.from_user.username or "N/A"
    await get_or_create_user(supabase, user_id, username)
    await message.answer(translator.get_text("start_message", lang_code).format(username=username))

# ... (handler untuk /newchat, /lang, /settings, dan callback tetap sama) ...
@router.message(Command("newchat"))
async def handle_newchat(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    success = await delete_user_messages(supabase, user_id)
    if success:
        await message.answer(translator.get_text("newchat_success", lang_code))
    else:
        await message.answer(translator.get_text("newchat_fail", lang_code))

@router.message(Command("status", "info"))
async def handle_status(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    limit = os.environ.get("DAILY_CHAT_LIMIT", 20)
    
    # Ensure the count is up-to-date before displaying
    await check_and_handle_limit(supabase, user_id)
    
    user_info = await get_user_chat_info(supabase, user_id)
    usage = user_info.get('chat_count', 0) if user_info else 0

    # Calculate time until next 00:00 UTC
    now_utc = datetime.now(pytz.utc)
    tomorrow_utc = now_utc.date() + timedelta(days=1)
    midnight_utc = datetime.combine(tomorrow_utc, datetime.min.time(), tzinfo=pytz.utc)
    time_left = midnight_utc - now_utc
    
    hours_left = time_left.seconds // 3600
    minutes_left = (time_left.seconds % 3600) // 60

    status_text = translator.get_text("status_message", lang_code).format(
        user_id=user_id,
        usage=usage,
        limit=limit,
        hours=hours_left,
        minutes=minutes_left
    )
    await message.answer(status_text)


@router.message(Command("lang"))
async def handle_lang(message: Message, translator: Translator, lang_code: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="English 🇬🇧", callback_data="lang_en")
    builder.button(text="Indonesia 🇮🇩", callback_data="lang_id")
    builder.adjust(2)
    await message.answer(translator.get_text("lang_select", lang_code), reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("lang_"))
async def handle_lang_callback(callback: CallbackQuery, supabase: Client, translator: Translator):
    new_lang_code = callback.data.split("_")[1]
    user_id = callback.from_user.id
    await update_user_language(supabase, user_id, new_lang_code)
    confirmation_message = translator.get_text(f"lang_updated_{new_lang_code}", new_lang_code)
    await callback.message.edit_text(confirmation_message)
    await callback.answer()

@router.message(Command("settings"))
async def handle_settings(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    active_model_id = await get_user_model(supabase, user_id)

    models = load_models()
    current_model_name = "Unknown"
    for model in models:
        if model['value'] == active_model_id:
            current_model_name = model['name']
            break
            
    settings_text = translator.get_text("settings_menu", lang_code).format(
        current_model_name=escape_html(current_model_name)
    )

    builder = InlineKeyboardBuilder()
    builder.button(text=translator.get_text("change_model_button", lang_code), callback_data="show_models")
    await message.answer(settings_text, reply_markup=builder.as_markup())

@router.callback_query(F.data == "show_models")
async def show_models_callback(callback: CallbackQuery, translator: Translator, lang_code: str):
    models = load_models()
    builder = InlineKeyboardBuilder()
    for model in models:
        builder.button(text=f"{model['name']} ({model['provider']})", callback_data=f"setmodel_{model['value']}")
    builder.adjust(1)
    await callback.message.edit_text(translator.get_text("select_model", lang_code), reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("setmodel_"))
async def set_model_callback(callback: CallbackQuery, supabase: Client, translator: Translator, lang_code: str):
    model_value = callback.data.split("_")[1]
    user_id = callback.from_user.id
    await update_user_model(supabase, user_id, model_value)
    
    models = load_models()
    model_name = "Unknown"
    for model in models:
        if model['value'] == model_value:
            model_name = model['name']
            break
            
    confirmation_message = translator.get_text("model_updated", lang_code).format(model_name=model_name)
    await callback.message.edit_text(confirmation_message)
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
    user_id = message.from_user.id

    is_limited = await check_and_handle_limit(supabase, user_id)
    if is_limited:
        try:
            limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
        except (ValueError, TypeError):
            limit = 20
        await message.answer(translator.get_text("limit_reached", lang_code).format(limit=limit))
        return

    user_message_text = message.text
    await save_message(supabase, user_id, 'user', user_message_text)
    
    thinking_message = translator.get_text("thinking", lang_code)
    sent_message = await message.reply(thinking_message)
    
    try:
        response_data = await get_groq_response(user_id, user_message_text, supabase, translator, lang_code)
        full_response = response_data["content"]
        reasoning_text = response_data["reasoning"]

        await sent_message.delete()

        if full_response and full_response.strip():
            message_id = await save_message(supabase, user_id, 'assistant', full_response, reasoning_text)
            
            parsed_response = process_telegram_html(full_response)
            
            reply_markup = None
            if reasoning_text and message_id:
                builder = InlineKeyboardBuilder()
                builder.button(
                    text=translator.get_text("show_reasoning_button", lang_code),
                    callback_data=f"show_reasoning_{message_id}"
                )
                reply_markup = builder.as_markup()
            
            await send_long_message(message, parsed_response, reply_markup=reply_markup)
            
            await increment_chat_count(supabase, user_id)
        else:
            await message.reply(translator.get_text("no_response", lang_code))
            
    except Exception as e:
        print(f"Error in handle_message processing: {e}")
        try:
            await sent_message.edit_text(translator.get_text("stream_error", lang_code))
        except Exception:
            await message.reply(translator.get_text("stream_error", lang_code))
