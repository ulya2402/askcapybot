import asyncio
import os
import logging
import sys
from typing import Callable, Awaitable, Any, Dict
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage # <-- Impor baru
from aiogram.types import TelegramObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from modules.bot_handlers import router as main_router
from modules.vision_handler import router as vision_router
from modules.supabase_handler import init_supabase_client, get_user_language
from modules.translator import translator_instance
from modules.group_handler import router as group_router # <-- PERUBAHAN: Impor baru
from modules.inline_handler import router as inline_router
from modules.membership_middleware import MembershipMiddleware # <-- PERUBAHAN 1: Impor baru





class LanguageMiddleware:
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        supabase_client = data.get('supabase')
        user = data.get('event_from_user')

        lang_code = "en"
        if supabase_client and user:
            lang_code = await get_user_language(supabase_client, user.id)

        data["lang_code"] = lang_code
        data["translator"] = translator_instance
        return await handler(event, data)

async def main():
    load_dotenv()
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logging.error("TELEGRAM_BOT_TOKEN not found in .env file. Bot cannot start.")
        return

    supabase_client = init_supabase_client()
    if not supabase_client:
        logging.error("Failed to initialize Supabase client. Bot cannot start.")
        return

    storage = MemoryStorage()
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)
    
    membership_checker = MembershipMiddleware()
    dp.message.outer_middleware.register(membership_checker)
    dp.callback_query.outer_middleware.register(membership_checker)


    dp.update.middleware.register(LanguageMiddleware())
    
    dp.include_router(main_router)
    dp.include_router(vision_router)
    dp.include_router(inline_router)
    dp.include_router(group_router) 




    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, supabase=supabase_client)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
