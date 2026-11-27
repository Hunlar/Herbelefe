import asyncio
import logging
from pathlib import Path

import aiohttp
from pyrogram import Client, filters, types, enums, errors
from pyrogram.handlers import MessageHandler
from pytgcalls import PyTgCalls, types as call_types, exceptions

from anony import app, config, db, logger, userbot, yt

class CloneManager:
    """Runs BotFather-created clone bots on the same Heroku worker."""

    def __init__(self):
        self.clients = {}
        self.calls = None
        self.active_chat = None
        self.lock = asyncio.Lock()
        self.collection = db.db.clones

    async def validate_token(self, token):
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://api.telegram.org/bot{token}/getMe") as response:
                data = await response.json(content_type=None)
        if not data.get("ok") or not data.get("result", {}).get("is_bot"):
            raise ValueError("BotFather token geçersiz.")
        return data["result"]

    async def add(self, token, owner_id):
        me = await self.validate_token(token)
        await self.collection.update_one(
            {"_id": int(me["id"])},
            {"$set": {"token": token, "username": me.get("username"),
                      "first_name": me.get("first_name"), "owner_id": owner_id,
                      "enabled": True}},
            upsert=True,
        )
        await self.start_one(token, me)
        return me

    async def start_one(self, token, me=None):
        info = me or await self.validate_token(token)
        bot_id = int(info["id"])
        if bot_id in self.clients:
            return self.clients[bot_id]
        client = Client(
            name=f"clone_{bot_id}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=token,
            in_memory=True,
            max_concurrent_transmissions=7,
            parse_mode=enums.ParseMode.HTML,
        )
        client.add_handler(MessageHandler(self.start_handler, filters.command("start")))
        client.add_handler(MessageHandler(self.play_handler, filters.command(["play", "vplay", "video"])))
        client.add_handler(MessageHandler(self.stop_handler, filters.command(["stop", "end"])))
        client.add_handler(MessageHandler(self.pause_handler, filters.command("pause")))
        client.add_handler(MessageHandler(self.resume_handler, filters.command("resume")))
        await client.start()
        client.clone_id = bot_id
        client.clone_username = info.get("username")
        self.clients[bot_id] = client
        logger.info("Clone bot started: @%s", info.get("username"))
        return client

    async def boot(self):
        if config.SESSION2:
            self.calls = PyTgCalls(userbot.two, cache_duration=100)
            await self.calls.start()
            await self.calls.on_update()(self.call_update)
        async for doc in self.collection.find({"enabled": True}):
            try:
                await self.start_one(doc["token"], {
                    "id": doc["_id"], "username": doc.get("username"),
                    "first_name": doc.get("first_name")
                })
            except Exception:
                logger.exception("Could not start clone bot %s", doc.get("username"))

    async def call_update(self, _, update):
        if isinstance(update, call_types.StreamEnded):
            if update.chat_id == self.active_chat:
                self.active_chat = None
        elif isinstance(update, call_types.ChatUpdate):
            if update.chat_id == self.active_chat and update.status in (
                call_types.ChatUpdate.Status.KICKED,
                call_types.ChatUpdate.Status.LEFT_GROUP,
                call_types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
            ):
                self.active_chat = None

    async def start_handler(self, client, message):
        main = f"https://t.me/{app.username}"
        keyboard = types.InlineKeyboardMarkup([
            [types.InlineKeyboardButton("⭐ Destek / Bağış", url=main)],
            [types.InlineKeyboardButton("Ana Bot", url=main)]
        ])
        await message.reply_text(
            f"Merhaba! <b>{client.me.first_name}</b> müzik botuna hoş geldin.\n"
            "Komutlar: /play, /vplay, /pause, /resume, /stop",
            reply_markup=keyboard,
        )

    async def play_handler(self, client, message):
        if not config.SESSION2 or not self.calls:
            return await message.reply_text("Klon asistanı henüz yapılandırılmadı.")
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return await message.reply_text("Bu komutu grupta kullan.")
        if len(message.command) < 2:
            return await message.reply_text("Kullanım: /play şarkı adı veya bağlantı")
        if self.lock.locked() or self.active_chat is not None:
            return await message.reply_text("Klon asistanı şu anda başka bir grupta yayında. Yayın bitince tekrar dene.")
        async with self.lock:
            if self.active_chat is not None:
                return await message.reply_text("Klon asistanı şu anda meşgul.")
            status = await message.reply_text("⏬ İçerik aranıyor ve indiriliyor...")
            video = message.command[0].lower() in ("vplay", "video")
            query = " ".join(message.command[1:])
            track = await yt.search(query, status.id, video=video)
            if not track:
                return await status.edit_text("İçerik bulunamadı.")
            file_path = await yt.download(track.id, video=video)
            if not file_path or not Path(file_path).is_file():
                return await status.edit_text("İndirme başarısız. COOKIES_URL ayarını kontrol et.")
            assistant = userbot.two
            try:
                try:
                    await assistant.get_chat_member(message.chat.id, assistant.id)
                except errors.UserNotParticipant:
                    invite = message.chat.username
                    if not invite:
                        chat = await client.get_chat(message.chat.id)
                        invite = chat.invite_link or await client.export_chat_invite_link(message.chat.id)
                    await assistant.join_chat(invite)
                stream = call_types.MediaStream(
                    media_path=file_path,
                    audio_parameters=call_types.AudioQuality.HIGH,
                    video_parameters=call_types.VideoQuality.HD_720p,
                    audio_flags=call_types.MediaStream.Flags.REQUIRED,
                    video_flags=(call_types.MediaStream.Flags.AUTO_DETECT if video else call_types.MediaStream.Flags.IGNORE),
                )
                await self.calls.play(
                    chat_id=message.chat.id,
                    stream=stream,
                    config=call_types.GroupCallConfig(auto_start=False),
                )
                self.active_chat = message.chat.id
                await status.edit_text(f"▶️ <b>{track.title}</b>\nAsistan: @{assistant.username}")
            except Exception as exc:
                self.active_chat = None
                await status.edit_text(f"Yayın başlatılamadı: {str(exc)[:300]}")

    async def stop_handler(self, client, message):
        if not self.calls or self.active_chat != message.chat.id:
            return await message.reply_text("Bu grupta klon yayını bulunmuyor.")
        try:
            await self.calls.leave_call(message.chat.id)
        finally:
            self.active_chat = None
        await message.reply_text("⏹ Yayın durduruldu.")

    async def pause_handler(self, client, message):
        if not self.calls or self.active_chat != message.chat.id:
            return await message.reply_text("Bu grupta yayın bulunmuyor.")
        await self.calls.pause(message.chat.id)
        await message.reply_text("⏸ Yayın duraklatıldı.")

    async def resume_handler(self, client, message):
        if not self.calls or self.active_chat != message.chat.id:
            return await message.reply_text("Bu grupta yayın bulunmuyor.")
        await self.calls.resume(message.chat.id)
        await message.reply_text("▶️ Yayın devam ediyor.")

    async def shutdown(self):
        if self.calls:
            try:
                if self.active_chat is not None:
                    await self.calls.leave_call(self.active_chat)
            except Exception:
                pass
            await self.calls.stop()
        for client in list(self.clients.values()):
            try:
                await client.stop()
            except Exception:
                pass
        self.clients.clear()
