from aiogram import Router, F, Bot
from aiogram.types import Message, BusinessConnection
from supabase import Client

from modules.translator import Translator
from modules.core_logic import process_text_message
from modules.supabase_handler import save_message

router = Router()

# Handler untuk saat pengguna menautkan atau memutuskan tautan dengan bot
@router.business_connection()
async def handle_business_connection(connection: BusinessConnection, supabase: Client):
    user_id = connection.user.id
    connection_id = connection.id
    is_enabled = connection.is_enabled

    try:
        if is_enabled:
            print(f"User {user_id} has enabled business connection: {connection_id}")
            # Anda bisa menyimpan koneksi ini ke database jika perlu
            supabase.table('business_connections').upsert({
                'id': connection_id,
                'user_id': user_id,
                'is_active': True
            }).execute()
        else:
            print(f"User {user_id} has disabled business connection: {connection_id}")
            supabase.table('business_connections').update(
                {'is_active': False}
            ).eq('id', connection_id).execute()
    except Exception as e:
        print(f"Error handling business connection: {e}")

# Handler untuk pesan yang masuk ke akun pengguna Premium
@router.business_message(F.text)
async def handle_business_message(message: Message, supabase: Client, translator: Translator, lang_code: str):
    business_connection_id = message.business_connection_id
    user_id = message.chat.id # ID pengguna yang mengirim pesan ke akun Premium
    
    print(f"Received business message from {user_id} via connection {business_connection_id}")

    # Simpan pesan masuk ke database dengan konteks koneksi bisnis
    await save_message(supabase, user_id, 'user', message.text, business_connection_id)
    
    # Untuk saat ini, kita akan langsung membalas menggunakan logika AI standar.
    # Di masa depan, ini bisa dikembangkan dengan prompt atau model khusus bisnis.
    await process_text_message(message, message.text, supabase, translator, lang_code, is_business=True)