import os
from datetime import datetime
import pytz
from supabase import Client
from modules.supabase_handler import get_user_chat_info, reset_user_chat_count, increment_user_chat_count

async def check_and_handle_limit(supabase: Client, user_id: int) -> bool:
    """
    Checks if the user is over their daily limit.
    Resets the count if it's a new day.
    Returns True if the user is over the limit, False otherwise.
    """
    try:
        limit = int(os.environ.get("DAILY_CHAT_LIMIT", 20))
    except (ValueError, TypeError):
        limit = 20

    user_info = await get_user_chat_info(supabase, user_id)
    if not user_info:
        return False

    today_utc = datetime.now(pytz.utc).date()
    last_chat_date_str = user_info.get('last_chat_date')
    
    last_chat_date = None
    if last_chat_date_str:
        try:
            last_chat_date = datetime.strptime(last_chat_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass 

    if last_chat_date is None or last_chat_date < today_utc:
        await reset_user_chat_count(supabase, user_id, today_utc)
        return False

    chat_count = user_info.get('chat_count', 0)
    return chat_count >= limit

async def increment_chat_count(supabase: Client, user_id: int):
    """Increments the user's chat count for the day."""
    await increment_user_chat_count(supabase, user_id)
