import os
from typing import Callable, Awaitable, Dict, Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery, TelegramObject, User
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus
from modules.translator import Translator # <-- Impor baru

class MembershipMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user: User = data.get("event_from_user")
        bot: Bot = data.get("bot")
        translator: Translator = data.get("translator") # <-- Ambil translator
        lang_code: str = data.get("lang_code", "en")  # <-- Ambil lang_code

        if not user or not translator:
            return await handler(event, data)

        channels_str = os.getenv("REQUIRED_CHANNELS")
        if not channels_str:
            return await handler(event, data)

        required_channels = [ch.strip() for ch in channels_str.split(',') if ch.strip()]
        folder_link = os.getenv("FOLDER_LINK")

        not_joined_channels = []
        for channel in required_channels:
            try:
                member = await bot.get_chat_member(chat_id=channel, user_id=user.id)
                if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                    not_joined_channels.append(channel)
            except Exception:
                not_joined_channels.append(channel)
                print(f"Warning: Bot could not access channel '{channel}'. Make sure it is an admin.")

        if not_joined_channels:
            builder = InlineKeyboardBuilder()
            if folder_link:
                builder.button(text=translator.get_text("join_folder_button", lang_code), url=folder_link)

            refresh_callback = "check_membership"
            if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                payload = event.text.split(" ", 1)
                if len(payload) > 1:
                    refresh_callback += f"_{payload[1]}"
            
            builder.button(text=translator.get_text("retry_button", lang_code), callback_data=refresh_callback)
            builder.adjust(1)
            
            text = translator.get_text("force_subscribe_text", lang_code)
            
            if isinstance(event, Message):
                await event.answer(text, reply_markup=builder.as_markup())
            elif isinstance(event, CallbackQuery):
                await event.message.answer(text, reply_markup=builder.as_markup())
                await event.answer()

            return
            
        return await handler(event, data)