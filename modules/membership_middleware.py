import os
from typing import Callable, Awaitable, Dict, Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, CallbackQuery, TelegramObject, User
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ChatMemberStatus

class MembershipMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Hanya periksa untuk pesan dan callback query
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user: User = data.get("event_from_user")
        bot: Bot = data.get("bot")

        # Jangan periksa jika event tidak memiliki user (misal: update channel)
        if not user:
            return await handler(event, data)

        channels_str = os.getenv("REQUIRED_CHANNELS")
        if not channels_str:
            return await handler(event, data) # Lanjutkan jika tidak ada channel yang diwajibkan

        required_channels = [ch.strip() for ch in channels_str.split(',') if ch.strip()]
        folder_link = os.getenv("FOLDER_LINK")

        not_joined_channels = []
        for channel in required_channels:
            try:
                member = await bot.get_chat_member(chat_id=channel, user_id=user.id)
                if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
                    not_joined_channels.append(channel)
            except Exception:
                # Jika bot tidak bisa mengakses channel (misal: bukan admin), anggap user belum join
                not_joined_channels.append(channel)
                print(f"Warning: Bot could not access channel '{channel}'. Make sure it is an admin.")

        if not_joined_channels:
            builder = InlineKeyboardBuilder()
            if folder_link:
                builder.button(text="➡️ Gabung Folder Obrolan", url=folder_link)

            # Tambahkan tombol refresh
            refresh_callback = "check_membership"
            if isinstance(event, Message) and event.text and event.text.startswith("/start"):
                # Jika dari perintah /start, tambahkan payload jika ada
                payload = event.text.split(" ", 1)
                if len(payload) > 1:
                    refresh_callback += f"_{payload[1]}"
            
            builder.button(text="🔄 Coba Lagi", callback_data=refresh_callback)
            builder.adjust(1)
            
            # Teks bisa ditambahkan ke file locale jika diinginkan
            text = "Untuk melanjutkan, Anda harus bergabung ke semua channel kami terlebih dahulu. Silakan bergabung menggunakan tombol di bawah ini, lalu klik 'Coba Lagi'."
            
            if isinstance(event, Message):
                await event.answer(text, reply_markup=builder.as_markup())
            elif isinstance(event, CallbackQuery):
                await event.message.answer(text, reply_markup=builder.as_markup())
                await event.answer() # Menutup notifikasi loading di tombol

            return # Hentikan proses lebih lanjut
            
        return await handler(event, data)