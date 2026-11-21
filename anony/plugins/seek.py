# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.

from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import can_manage_vc


def parse_timestamp(value: str) -> int:
    """Parse a target as minutes, MM:SS, or HH:MM:SS into seconds."""
    parts = value.strip().split(":")
    if len(parts) == 1:
        minutes = int(parts[0])
        if minutes < 0:
            raise ValueError
        return minutes * 60
    if len(parts) in (2, 3):
        numbers = [int(part) for part in parts]
        if any(number < 0 for number in numbers):
            raise ValueError
        if numbers[-1] >= 60 or (len(numbers) == 3 and numbers[-2] >= 60):
            raise ValueError
        if len(numbers) == 2:
            return numbers[0] * 60 + numbers[1]
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    raise ValueError


@app.on_message(filters.command(["seek", "seekback"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _seek(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(
            "Kullanım: /seek 5 (5. dakika) veya /seek 05:30"
        )

    try:
        target = parse_timestamp(m.command[1])
    except ValueError:
        return await m.reply_text("Zamanı dakika, MM:SS veya HH:MM:SS biçiminde yaz.")

    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])
    if not await db.playing(m.chat.id):
        return await m.reply_text(m.lang["play_already_paused"])

    media = queue.get_current(m.chat.id)
    if not media or not media.duration_sec:
        return await m.reply_text(m.lang["play_seek_no_dur"])

    if m.command[0].lower() == "seekback":
        target = max(1, media.time - target)
    else:
        target = max(1, target)

    if target >= media.duration_sec - 5:
        target = max(1, media.duration_sec - 5)

    sent = await m.reply_text(m.lang["play_seeking"])
    await anon.play_media(m.chat.id, sent, media, target)
    media.time = target
    await sent.edit_text(
        f"Yayın {target // 60:02d}:{target % 60:02d} konumuna alındı."
    )
