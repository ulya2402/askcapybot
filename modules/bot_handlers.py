from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from supabase import Client
from modules.supabase_handler import (
    get_or_create_user, save_message, delete_user_messages, 
    update_user_language, update_user_model, get_reasoning_text
)
from modules.groq_handler import get_groq_response
from modules.translator import Translator
from modules.html_parser import process_telegram_html, escape_html
import asyncio
import json

router = Router()

def load_models():
    try:
        with open("models.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

@router.message(CommandStart())
async def handle_start(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    username = message.from_user.username or "N/A"
    await get_or_create_user(supabase, user_id, username)
    await message.answer(translator.get_text("start_message", lang_code).format(username=username))

@router.message(Command("newchat"))
async def handle_newchat(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    success = await delete_user_messages(supabase, user_id)
    if success:
        await message.answer(translator.get_text("newchat_success", lang_code))
    else:
        await message.answer(translator.get_text("newchat_fail", lang_code))

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
async def handle_settings(message: Message, translator: Translator, lang_code: str):
    builder = InlineKeyboardBuilder()
    builder.button(text=translator.get_text("change_model_button", lang_code), callback_data="show_models")
    await message.answer(translator.get_text("settings_menu", lang_code), reply_markup=builder.as_markup())

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
    
    if reasoning_text:
        current_text_html = callback.message.html_text
        reasoning_title = translator.get_text("reasoning_title", lang_code)
        parsed_reasoning = process_telegram_html(reasoning_text)
        
        new_text = current_text_html + reasoning_title + parsed_reasoning
        
        try:
            await callback.message.edit_text(new_text, reply_markup=None)
        except TelegramBadRequest:
            # Fallback for reasoning if it also has bad HTML
            fallback_text = current_text_html + reasoning_title + escape_html(reasoning_text)
            await callback.message.edit_text(fallback_text, reply_markup=None, parse_mode=None)
    else:
        await callback.answer("Reasoning not found.", show_alert=True)
    
    await callback.answer()

@router.message(F.text & ~F.text.startswith('/'))
async def handle_message(message: Message, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    user_message_text = message.text

    await save_message(supabase, user_id, 'user', user_message_text)
    
    sent_message = await message.answer(translator.get_text("thinking", lang_code))
    
    try:
        response_data = await get_groq_response(user_id, user_message_text, supabase, translator, lang_code)
        full_response = response_data["content"]
        reasoning_text = response_data["reasoning"]

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

            try:
                await sent_message.edit_text(parsed_response, reply_markup=reply_markup)
            except TelegramBadRequest as e:
                print(f"HTML parse error, falling back to plain text. Error: {e}")
                plain_text_response = escape_html(full_response)
                await sent_message.edit_text(plain_text_response, reply_markup=reply_markup, parse_mode=None)
        else:
            await sent_message.edit_text(translator.get_text("no_response", lang_code))
            
    except Exception as e:
        print(f"Error in handle_message processing: {e}")
        await sent_message.edit_text(translator.get_text("stream_error", lang_code))
