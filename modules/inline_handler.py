import os
import uuid
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import (
    InlineQuery, ChosenInlineResult, InlineQueryResultArticle, InputTextMessageContent, User
)
from supabase import Client
from cachetools import TTLCache

from modules.translator import Translator
from modules.limit_handler import check_and_handle_limit, increment_chat_count
from modules.core_logic import generate_ai_response
from modules.html_parser import escape_html

router = Router()

# --- Caching & Debouncing Setup ---
CACHE = TTLCache(maxsize=100, ttl=600)
DEBOUNCE_TASKS = {}
DEBOUNCE_DELAY = 5.0

async def send_log_to_channel(bot: Bot, user: User, query: str, answer: str):
    log_channel_id_str = os.getenv("LOG_CHANNEL_ID")
    if not log_channel_id_str:
        return # Jangan lakukan apa-apa jika LOG_CHANNEL_ID tidak diatur

    try:
        log_channel_id = int(log_channel_id_str)
        user_info = f"{escape_html(user.full_name)} (<code>{user.id}</code>)"
        answer_snippet = (answer[:200] + '...') if len(answer) > 200 else answer
        
        log_message = (
            f"<b>✅ Inline Query Success</b>\n\n"
            f"👤 <b>User:</b> {user_info}\n"
            f"📝 <b>Query:</b> <pre>{escape_html(query)}</pre>\n"
            f"🤖 <b>Answer Snippet:</b>\n<pre>{escape_html(answer_snippet)}</pre>"
        )
        
        await bot.send_message(log_channel_id, log_message)
    except (ValueError, TypeError):
        print(f"Error: LOG_CHANNEL_ID '{log_channel_id_str}' is not a valid integer.")
    except Exception as e:
        print(f"Error sending log to channel: {e}")

@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery, supabase: Client, translator: Translator, lang_code: str):
    query = inline_query.query.strip()
    user_id = inline_query.from_user.id

    if user_id in DEBOUNCE_TASKS:
        DEBOUNCE_TASKS[user_id].cancel()

    if len(query) < 4:
        await inline_query.answer([], cache_time=0)
        return

    task = asyncio.create_task(
        process_debounced_query(inline_query, supabase, translator, lang_code)
    )
    DEBOUNCE_TASKS[user_id] = task

async def process_debounced_query(inline_query: InlineQuery, supabase: Client, translator: Translator, lang_code: str):
    try:
        await asyncio.sleep(DEBOUNCE_DELAY)
        
        bot = inline_query.bot
        query = inline_query.query.strip()
        user = inline_query.from_user

        if query in CACHE:
            cached_results = CACHE[query]
            await inline_query.answer(cached_results, cache_time=0, is_personal=True)
            await send_log_to_channel(bot, user, query, "(from cache)")
            return

        is_limited = await check_and_handle_limit(supabase, user.id)
        if is_limited:
            limit_result = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title="Batas Penggunaan Harian Tercapai",
                    input_message_content=InputTextMessageContent(
                        message_text=translator.get_text("limit_reached_inline", lang_code)
                    ),
                    description="Silakan coba lagi besok."
                )
            ]
            await inline_query.answer(limit_result, cache_time=0, is_personal=True)
            return

        response_data = await generate_ai_response(user.id, query, supabase, translator, lang_code)
        final_text = response_data.get("final_text")

        results = []
        if final_text and final_text.strip():
            title = final_text.split('\n')[0]
            if len(title) > 60:
                title = title[:57] + "..."
            
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=title,
                    input_message_content=InputTextMessageContent(
                        message_text=final_text,
                        disable_web_page_preview=True
                    ),
                    description=f"Jawaban untuk: \"{query}\". Klik untuk mengirim."
                )
            )
            await increment_chat_count(supabase, user.id)
            await send_log_to_channel(bot, user, query, final_text)
        else:
            results.append(
                 InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title="Tidak ada jawaban ditemukan",
                    input_message_content=InputTextMessageContent(
                        message_text=translator.get_text("no_response", lang_code)
                    ),
                    description=f"Tidak dapat memproses: \"{query}\""
                )
            )
        
        CACHE[query] = results
        await inline_query.answer(results, cache_time=0, is_personal=True)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in process_debounced_query: {e}")

@router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_inline_result: ChosenInlineResult):
    pass