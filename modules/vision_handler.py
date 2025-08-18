import base64
import json
import os
from io import BytesIO

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

def get_vision_models():
    try:
        with open("models.json", "r") as f:
            models = json.load(f)
        return [model['value'] for model in models if model.get("vision")]
    except FileNotFoundError:
        return []

@router.message(F.photo)
async def handle_vision_message(message: Message, bot: Bot, supabase: Client, translator: Translator, lang_code: str):
    user_id = message.from_user.id

    is_limited = await check_and_handle_limit(supabase, user_id)
    if is_limited:
        try:
            limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
        except (ValueError, TypeError):
            limit = 20
        await message.answer(translator.get_text("limit_reached", lang_code).format(limit=limit))
        return

    active_model = await get_user_model(supabase, user_id)
    vision_models = get_vision_models()

    if active_model not in vision_models:
        await message.reply(
            "This feature requires a vision-capable model. "
            "Please change your model to one with the 👁️ icon using /settings."
        )
        return

    prompt = message.caption if message.caption else translator.get_text("default_vision_prompt", lang_code)
    thinking_message = await message.reply(translator.get_text("thinking_vision", lang_code))

    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        
        image_bytes_io = await bot.download_file(file_info.file_path)
        image_bytes_io.seek(0)
        base64_image = base64.b64encode(image_bytes_io.read()).decode('utf-8')

        response_data = await get_groq_vision_response(
            user_id=user_id,
            prompt_text=prompt,
            base64_images=[base64_image],
            supabase_client=supabase,
            translator=translator,
            lang_code=lang_code
        )
        
        await thinking_message.delete()

        full_response = response_data["content"]
        if full_response and full_response.strip():
            await save_message(supabase, user_id, 'user', prompt)
            await save_message(supabase, user_id, 'assistant', full_response)
            
            parsed_response = process_telegram_html(full_response)
            await send_long_message(message, parsed_response)
            
            await increment_chat_count(supabase, user_id)
        else:
            await message.reply(translator.get_text("no_response", lang_code))

    except Exception as e:
        print(f"Error in handle_vision_message: {e}")
        await thinking_message.edit_text(translator.get_text("stream_error", lang_code))