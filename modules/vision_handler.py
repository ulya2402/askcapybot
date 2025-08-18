import base64
import json
import os
import asyncio
from io import BytesIO
from typing import Dict, List

from aiogram import Router, F, Bot
from aiogram.types import Message
from supabase import Client

from modules.groq_handler import get_groq_vision_response
from modules.bot_handlers import send_long_message
from modules.supabase_handler import get_user_model, save_message
from modules.html_parser import process_telegram_html
from modules.translator import Translator
from modules.limit_handler import check_and_handle_limit, increment_chat_count

router = Router()
album_data: Dict[str, List[Message]] = {}
MAX_IMAGES = 3

def get_vision_models():
    try:
        with open("models.json", "r") as f:
            models = json.load(f)
        return [model['value'] for model in models if model.get("vision")]
    except FileNotFoundError:
        return []

async def process_media_group(messages: List[Message], bot: Bot, supabase: Client, translator: Translator, lang_code: str):
    first_message = messages[0]
    user_id = first_message.from_user.id

    is_limited = await check_and_handle_limit(supabase, user_id)
    if is_limited:
        try:
            limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
        except (ValueError, TypeError):
            limit = 20
        await first_message.answer(translator.get_text("limit_reached", lang_code).format(limit=limit))
        return

    active_model = await get_user_model(supabase, user_id)
    vision_models = get_vision_models()

    if active_model not in vision_models:
        await first_message.reply(
            "This feature requires a vision-capable model. "
            "Please change your model to one with the 👁️ icon using /settings."
        )
        return

    prompt = first_message.caption if first_message.caption else translator.get_text("default_vision_prompt", lang_code)
    thinking_message = await first_message.reply(translator.get_text("thinking_vision", lang_code))
    
    if len(messages) > MAX_IMAGES:
        await first_message.answer(translator.get_text("max_images_warning", lang_code).format(max_images=MAX_IMAGES))

    base64_images = []
    for message in messages[:MAX_IMAGES]:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        image_bytes_io = await bot.download_file(file_info.file_path)
        image_bytes_io.seek(0)
        base64_images.append(base64.b64encode(image_bytes_io.read()).decode('utf-8'))

    try:
        response_data = await get_groq_vision_response(
            user_id=user_id,
            prompt_text=prompt,
            base64_images=base64_images,
            supabase_client=supabase,
            translator=translator,
            lang_code=lang_code
        )
        
        await thinking_message.delete()

        full_response = response_data["content"]
        if full_response and full_response.strip():
            await save_message(supabase, user_id, 'user', f"[Image Analysis] {prompt}")
            await save_message(supabase, user_id, 'assistant', full_response)
            
            parsed_response = process_telegram_html(full_response)
            await send_long_message(first_message, parsed_response)
            
            await increment_chat_count(supabase, user_id)
        else:
            await first_message.reply(translator.get_text("no_response", lang_code))

    except Exception as e:
        print(f"Error in process_media_group: {e}")
        await thinking_message.edit_text(translator.get_text("stream_error", lang_code))

@router.message(F.photo)
async def handle_photo_message(message: Message, bot: Bot, supabase: Client, translator: Translator, lang_code: str):
    if message.media_group_id:
        if message.media_group_id in album_data:
            album_data[message.media_group_id].append(message)
        else:
            album_data[message.media_group_id] = [message]
            await asyncio.sleep(1.5)
            messages = album_data.pop(message.media_group_id)
            await process_media_group(messages, bot, supabase, translator, lang_code)
    else:
        await process_media_group([message], bot, supabase, translator, lang_code)