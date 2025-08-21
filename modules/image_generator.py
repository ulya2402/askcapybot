import os
import itertools
import requests
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command, CommandObject
from supabase import Client

from modules.translator import Translator
from modules.limit_handler import check_and_handle_limit, increment_chat_count

# --- Konfigurasi Rotasi Kunci API ---
glif_api_keys_str = os.environ.get("GLIF_API_KEYS", "")
glif_api_keys = [key.strip() for key in glif_api_keys_str.split(',') if key.strip()]
glif_key_cycler = itertools.cycle(glif_api_keys)

router = Router()

def generate_image_with_glif(prompt: str):
    """Memanggil Glif Simple API untuk membuat gambar."""
    if not glif_api_keys:
        return {"error": "API keys for Glif are not configured."}

    model_id = os.getenv("GLIF_MODEL_ID", "clp8c7f990000i808yt28rhx1") # Default SDXL
    api_key = next(glif_key_cycler)
    
    api_url = "https://simple-api.glif.app"
    headers = {"Authorization": f"Bearer {api_key}"}
    json_data = {
        "id": model_id,
        "inputs": [prompt]
    }
    
    try:
        response = requests.post(api_url, json=json_data, headers=headers, timeout=120)
        response.raise_for_status()
        
        data = response.json()
        if "error" in data:
            return {"error": data["error"]}
        
        image_url = data.get("output")
        if not image_url:
            return {"error": "No image URL found in the API response."}
        
        return {"url": image_url}
        
    except requests.RequestException as e:
        print(f"Error calling Glif API: {e}")
        return {"error": "Failed to connect to the image generation service."}
    except Exception as e:
        print(f"An unexpected error occurred in generate_image_with_glif: {e}")
        return {"error": "An unexpected error occurred."}

@router.message(Command("img", "imagine"))
async def handle_image_generation(message: Message, command: CommandObject, supabase: Client, translator: Translator, lang_code: str):
    if not command.args:
        await message.reply(translator.get_text("img_prompt_required", lang_code))
        return

    prompt = command.args
    user_id = message.from_user.id
    
    is_limited = await check_and_handle_limit(supabase, user_id)
    if is_limited:
        try: limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
        except (ValueError, TypeError): limit = 20
        await message.answer(translator.get_text("limit_reached", lang_code).format(limit=limit))
        return

    thinking_message = await message.reply(translator.get_text("img_generating", lang_code))

    result = generate_image_with_glif(prompt)
    
    if "error" in result:
        error_text = translator.get_text("img_error_prefix", lang_code).format(error=result['error'])
        await thinking_message.edit_text(error_text)
        return
        
    image_url = result.get("url")

    try:
        caption_text = translator.get_text("img_success_caption", lang_code).format(prompt=prompt)
        await message.reply_photo(photo=image_url, caption=caption_text)
        await thinking_message.delete()
        await increment_chat_count(supabase, user_id)
    except Exception as e:
        print(f"Error sending photo: {e}")
        await thinking_message.edit_text(translator.get_text("img_send_error", lang_code))