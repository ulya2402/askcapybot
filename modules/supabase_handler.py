import os
from datetime import date
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

def init_supabase_client():
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Error: Supabase URL or Key not found in .env file.")
        return None
    return create_client(url, key)

async def get_or_create_user(supabase: Client, user_id: int, username: str):
    try:
        response = supabase.table('users').select('id').eq('id', user_id).execute()
        if not response.data:
            user_data = {
                'id': user_id,
                'username': username,
                'language_code': 'en',
                'active_model': 'llama3-8b-8192',
                'chat_count': 0,
                'last_chat_date': str(date.today())
            }
            supabase.table('users').insert(user_data).execute()
            print(f"New user created: {username} ({user_id})")
        return user_id
    except Exception as e:
        print(f"Error in get_or_create_user: {e}")
        return None

# ... (fungsi-fungsi lain tetap sama) ...
async def get_user_messages(supabase: Client, user_id: int):
    try:
        response = supabase.table('messages').select('role, content').eq('user_id', user_id).order('created_at', desc=False).execute()
        return response.data
    except Exception as e:
        print(f"Error fetching messages for user {user_id}: {e}")
        return []

async def save_message(supabase: Client, user_id: int, role: str, content: str, reasoning: str = None):
    try:
        message_data = {
            'user_id': user_id,
            'role': role,
            'content': content,
            'reasoning_text': reasoning
        }
        response = supabase.table('messages').insert(message_data).execute()
        if response.data:
            return response.data[0]['id']
    except Exception as e:
        print(f"Error saving message for user {user_id}: {e}")
    return None

async def get_reasoning_text(supabase: Client, message_id: str):
    try:
        response = supabase.table('messages').select('reasoning_text').eq('id', message_id).single().execute()
        if response.data:
            return response.data.get('reasoning_text')
    except Exception as e:
        print(f"Error fetching reasoning for message {message_id}: {e}")
    return None

async def delete_user_messages(supabase: Client, user_id: int):
    try:
        supabase.table('messages').delete().eq('user_id', user_id).execute()
        print(f"Message history deleted for user {user_id}")
        return True
    except Exception as e:
        print(f"Error deleting messages for user {user_id}: {e}")
        return False

async def update_user_language(supabase: Client, user_id: int, lang_code: str):
    try:
        supabase.table('users').update({'language_code': lang_code}).eq('id', user_id).execute()
        print(f"Language for user {user_id} updated to {lang_code}")
        return True
    except Exception as e:
        print(f"Error updating language for user {user_id}: {e}")
        return False

async def get_user_language(supabase: Client, user_id: int):
    try:
        response = supabase.table('users').select('language_code').eq('id', user_id).single().execute()
        if response.data:
            return response.data.get('language_code')
    except Exception as e:
        print(f"Error fetching language for user {user_id}: {e}")
    return 'en'

async def get_user_model(supabase: Client, user_id: int):
    try:
        response = supabase.table('users').select('active_model').eq('id', user_id).single().execute()
        if response.data and response.data.get('active_model'):
            return response.data.get('active_model')
    except Exception as e:
        print(f"Error fetching model for user {user_id}: {e}")
    return 'llama3-8b-8192'

async def update_user_model(supabase: Client, user_id: int, model_value: str):
    try:
        supabase.table('users').update({'active_model': model_value}).eq('id', user_id).execute()
        print(f"Model for user {user_id} updated to {model_value}")
        return True
    except Exception as e:
        print(f"Error updating model for user {user_id}: {e}")
        return False

# --- FUNGSI BARU UNTUK LIMIT ---
async def get_user_chat_info(supabase: Client, user_id: int):
    try:
        response = supabase.table('users').select('chat_count, last_chat_date').eq('id', user_id).single().execute()
        return response.data
    except Exception as e:
        print(f"Error fetching chat info for user {user_id}: {e}")
        return None

async def reset_user_chat_count(supabase: Client, user_id: int, today_date: date):
    try:
        supabase.table('users').update({'chat_count': 0, 'last_chat_date': str(today_date)}).eq('id', user_id).execute()
    except Exception as e:
        print(f"Error resetting chat count for user {user_id}: {e}")

async def increment_user_chat_count(supabase: Client, user_id: int):
    try:
        response = supabase.table('users').select('chat_count').eq('id', user_id).single().execute()
        if response.data:
            current_count = response.data.get('chat_count', 0)
            new_count = current_count + 1
            supabase.table('users').update({'chat_count': new_count}).eq('id', user_id).execute()
    except Exception as e:
        print(f"Error incrementing chat count for user {user_id}: {e}")
