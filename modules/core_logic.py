import os
import asyncio
import base64
from typing import List, Dict, Any

from aiogram import Bot
from aiogram.types import Message
from supabase import Client
from aiogram.utils.keyboard import InlineKeyboardBuilder

from modules.groq_handler import get_groq_response, get_groq_vision_response
from modules.utils import send_long_message, load_models
from modules.supabase_handler import save_message, get_user_model, get_user_prompt
from modules.html_parser import process_telegram_html, escape_html
from modules.translator import Translator
from modules.limit_handler import check_and_handle_limit, increment_chat_count

MAX_IMAGES = 3

async def generate_ai_response(user_id: int, text_prompt: str, supabase: Client, translator: Translator, lang_code: str) -> Dict[str, Any]:
    """Hanya mengambil dan memformat respons dari AI, tidak mengirim pesan."""
    response_data = await get_groq_response(user_id, text_prompt, supabase, translator, lang_code)
    
    full_response = response_data.get("content", "")
    reasoning_text = response_data.get("reasoning")
    sources = response_data.get("sources", [])
    
    final_text = ""
    if full_response and full_response.strip():
        parsed_response = process_telegram_html(full_response)
        
        if sources:
            sources_text = translator.get_text("sources_title", lang_code)
            for i, source in enumerate(sources[:5]):
                sources_text += f"{i+1}. <a href=\"{source.url}\">{escape_html(source.title)}</a>\n"
            parsed_response += sources_text
        final_text = parsed_response

    return {
        "final_text": final_text,
        "reasoning": reasoning_text,
        "sources_found": bool(sources)
    }


async def process_text_message(message: Message, text_prompt: str, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    is_limited = await check_and_handle_limit(supabase, user_id)
    if is_limited:
        try: limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
        except (ValueError, TypeError): limit = 20
        await message.answer(translator.get_text("limit_reached", lang_code).format(limit=limit))
        return

    await save_message(supabase, user_id, 'user', text_prompt)
    sent_message = await message.reply(translator.get_text("thinking", lang_code))
    
    try:
        response_data = await get_groq_response(user_id, text_prompt, supabase, translator, lang_code)
        
        if response_data.get("sources"):
            await sent_message.edit_text(translator.get_text("thinking_web_search", lang_code))

        full_response = response_data["content"]
        reasoning_text = response_data["reasoning"]
        sources = response_data.get("sources", [])

        await sent_message.delete()

        if full_response and full_response.strip():
            message_id = await save_message(supabase, user_id, 'assistant', full_response, reasoning_text)
            parsed_response = process_telegram_html(full_response)
            
            if sources:
                sources_text = translator.get_text("sources_title", lang_code)
                for i, source in enumerate(sources[:5]):
                    sources_text += f"{i+1}. <a href=\"{source.url}\">{escape_html(source.title)}</a>\n"
                parsed_response += sources_text

            reply_markup = None
            if reasoning_text and message_id:
                builder = InlineKeyboardBuilder()
                builder.button(text=translator.get_text("show_reasoning_button", lang_code), callback_data=f"show_reasoning_{message_id}")
                reply_markup = builder.as_markup()
            
            await send_long_message(message, parsed_response, reply_markup=reply_markup)
            await increment_chat_count(supabase, user_id)
        else:
            await message.reply(translator.get_text("no_response", lang_code))
            
    except Exception as e:
        print(f"Error in process_text_message: {e}")
        try: await sent_message.edit_text(translator.get_text("stream_error", lang_code))
        except Exception: await message.reply(translator.get_text("stream_error", lang_code))


async def process_photo_message(message: Message, photo_messages: List[Message], prompt_text: str, bot: Bot, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id
    is_limited = await check_and_handle_limit(supabase, user_id)
    if is_limited:
        try: limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
        except (ValueError, TypeError): limit = 20
        await message.answer(translator.get_text("limit_reached", lang_code).format(limit=limit))
        return

    models = load_models()
    vision_models = [model['value'] for model in models if model.get("vision")]
    active_model = await get_user_model(supabase, user_id)

    if active_model not in vision_models:
        await message.reply(translator.get_text("vision_model_required", lang_code))
        return

    prompt = prompt_text if prompt_text else translator.get_text("default_vision_prompt", lang_code)
    thinking_message = await message.reply(translator.get_text("thinking_vision", lang_code))
    
    if len(photo_messages) > MAX_IMAGES:
        await message.answer(translator.get_text("max_images_warning", lang_code).format(max_images=MAX_IMAGES))

    base64_images = []
    for msg in photo_messages[:MAX_IMAGES]:
        photo = msg.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        image_bytes_io = await bot.download_file(file_info.file_path)
        image_bytes_io.seek(0)
        base64_images.append(base64.b64encode(image_bytes_io.read()).decode('utf-8'))

    try:
        response_data = await get_groq_vision_response(user_id, prompt, base64_images, supabase, translator, lang_code)
        await thinking_message.delete()

        full_response = response_data["content"]
        if full_response and full_response.strip():
            await save_message(supabase, user_id, 'user', f"[Image Analysis] {prompt}")
            await save_message(supabase, user_id, 'assistant', full_response)
            parsed_response = process_telegram_html(full_response)
            await send_long_message(message, parsed_response)
            await increment_chat_count(supabase, user_id)
        else:
            await message.reply(translator.get_text("no_response", lang_code))
    except Exception as e:
        print(f"Error in process_photo_message: {e}")
        await thinking_message.edit_text(translator.get_text("stream_error", lang_code))
