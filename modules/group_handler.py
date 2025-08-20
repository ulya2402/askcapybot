from aiogram import Router, F, Bot
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

@router.message(
    F.reply_to_message, # Filter: Hanya aktif jika ini adalah balasan
    F.chat.type.in_({'group', 'supergroup'}) # Filter: Hanya di grup
)
async def handle_group_reply(message: Message, bot: Bot, supabase: Client, translator: Translator, lang_code: str):
    # Periksa apakah pesan yang dibalas adalah pesan dari bot itu sendiri
    if message.reply_to_message.from_user.id == bot.id:
        
        # Jika balasan berisi teks, proses sebagai pesan teks
        if message.text:
            prompt = message.text
            await process_text_message(message, prompt, supabase, translator, lang_code)
        
        # Jika balasan berisi foto, proses sebagai pesan gambar
        elif message.photo:
             # Gunakan caption foto sebagai prompt, atau prompt default jika kosong
            prompt_text = message.caption or ""
            await process_photo_message(message, [message], prompt_text, bot, supabase, translator, lang_code)