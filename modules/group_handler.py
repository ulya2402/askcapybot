from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command, CommandObject
from supabase import Client

from modules.translator import Translator
from modules.core_logic import process_text_message, process_photo_message

router = Router()

@router.message(Command("ai", "chat", "ask"))
async def handle_group_command(message: Message, command: CommandObject, supabase: Client, translator: Translator, lang_code: str):
    
    # Menangani Teks
    if command.args:
        prompt = command.args
        await process_text_message(message, prompt, supabase, translator, lang_code)
        return

    # Menangani Gambar (jika perintah adalah balasan ke gambar)
    if message.reply_to_message and message.reply_to_message.photo:
        # Saat ini hanya mendukung 1 gambar via balasan, album belum didukung di mode ini
        photo_message = message.reply_to_message
        photo_message.caption = message.text # Gunakan perintah sebagai caption
        await process_photo_message(message, [photo_message], message.bot, supabase, translator, lang_code)
        return
    
    # Jika tidak ada teks atau balasan gambar
    await message.reply(translator.get_text("group_command_usage", lang_code))