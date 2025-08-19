import asyncio
from typing import Dict, List

from aiogram import Router, F, Bot
from aiogram.types import Message
from supabase import Client

from modules.translator import Translator
from modules.core_logic import process_photo_message

router = Router()
album_data: Dict[str, List[Message]] = {}

@router.message(F.photo)
async def handle_photo_message(message: Message, bot: Bot, supabase: Client, translator: Translator, lang_code: str):
    is_group = message.chat.type in ['group', 'supergroup']
    caption = message.caption or ""
    
    bot_info = await bot.get_me()
    valid_commands = ('/ai', '/chat', '/ask', f'@{bot_info.username}')
    has_command_in_caption = any(cmd in caption for cmd in valid_commands)

    should_process = not is_group or (is_group and has_command_in_caption)

    if not should_process:
        return

    prompt = caption
    for cmd in valid_commands:
        prompt = prompt.replace(cmd, "").strip()

    if message.media_group_id:
        if message.media_group_id not in album_data:
            album_data[message.media_group_id] = []
        
        if not any(m.message_id == message.message_id for m in album_data[message.media_group_id]):
            album_data[message.media_group_id].append(message)

        await asyncio.sleep(1.5)

        if message.media_group_id in album_data:
            messages = album_data.pop(message.media_group_id)
            messages.sort(key=lambda m: m.message_id)
            first_message = messages[0]
            
            # Gunakan caption asli dari pesan pertama jika prompt kosong setelah dibersihkan
            final_prompt = prompt or (first_message.caption or "")

            await process_photo_message(first_message, messages, final_prompt, bot, supabase, translator, lang_code)
    else:
        # Menangani foto tunggal
        await process_photo_message(message, [message], prompt, bot, supabase, translator, lang_code)