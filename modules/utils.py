import json
import re
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
import asyncio

from modules.html_parser import escape_html

def load_models():
    try:
        with open("models.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

async def send_long_message(message: Message, text: str, parse_mode: str = ParseMode.HTML, reply_markup: InlineKeyboardMarkup = None):
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        try:
            if message.from_user.id == message.chat.id:
                 await message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True)
            else:
                 await message.reply(text, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=True)
        except TelegramBadRequest:
            await message.reply(escape_html(text), parse_mode=None, reply_markup=reply_markup, disable_web_page_preview=True)
        return

    parts, open_tags = [], []
    while len(text) > 0:
        if len(text) <= MAX_LENGTH:
            parts.append(text)
            break
        part = text[:MAX_LENGTH]
        last_newline = part.rfind('\n')
        split_pos = last_newline if last_newline != -1 else MAX_LENGTH
        part_to_send = text[:split_pos]
        
        for tag_match in re.finditer(r"<(/)?([a-zA-Z0-9_-]+)[^>]*>", part_to_send):
            is_closing, tag_name = tag_match.groups()
            tag_name = tag_name.lower()
            if is_closing:
                if open_tags and open_tags[-1] == tag_name: open_tags.pop()
            elif not tag_match.group(0).endswith("/>"):
                open_tags.append(tag_name)
        
        closing_tags = "".join([f"</{tag}>" for tag in reversed(open_tags)])
        part_to_send += closing_tags
        parts.append(part_to_send)
        
        opening_tags = "".join([f"<{tag}>" for tag in open_tags])
        text = opening_tags + text[split_pos:].lstrip()

    for i, part in enumerate(parts):
        is_last_part = (i == len(parts) - 1)
        current_markup = reply_markup if is_last_part else None
        try:
            if i == 0 and message.chat.type != 'private':
                 await message.reply(part, parse_mode=parse_mode, reply_markup=current_markup, disable_web_page_preview=True)
            else:
                 await message.answer(part, parse_mode=parse_mode, reply_markup=current_markup, disable_web_page_preview=True)
        except TelegramBadRequest:
            safe_part = escape_html(part)
            if i == 0 and message.chat.type != 'private':
                await message.reply(safe_part, parse_mode=None, reply_markup=current_markup, disable_web_page_preview=True)
            else:
                await message.answer(safe_part, parse_mode=None, reply_markup=current_markup, disable_web_page_preview=True)
        await asyncio.sleep(0.5)