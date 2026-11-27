import asyncio
import logging
from pathlib import Path

import aiohttp
from pyrogram import Client, filters, types, enums, errors
from pyrogram.handlers import MessageHandler
from pytgcalls import PyTgCalls, types as call_types, exceptions

from anony import app, config, db, lang, logger, userbot, yt

class CloneManager:
    """Runs BotFather-created clone bots on the same Heroku worker."""

    def __init__(self):
        self.clients = {}
        self.calls = None
        self.active_chat = None
        self.pending = []
        self.current_client = None
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
        client.add_handler(MessageHandler(self.new_member_handler, filters.new_chat_members))
        client.add_handler(MessageHandler(self.play_handler, filters.command(["play", "vplay", "video"])))
        client.add_handler(MessageHandler(self.stop_handler, filters.command(["stop", "end"])))
        client.add_handler(MessageHandler(self.pause_handler, filters.command("pause")))
        client.add_handler(MessageHandler(self.resume_handler, filters.command("resume")))
        client.add_handler(MessageHandler(self.skip_handler, filters.command(["skip", "next"])))
        client.add_handler(MessageHandler(self.queue_handler, filters.command(["queue", "playing"])))
        client.clone_id = bot_id
        await client.start()
        client.clone_username = info.get("username")
        self.clients[bot_id] = client
        logger.info("Clone bot started: @%s", info.get("username"))
        return client

    async def boot(self):
        if config.SESSION2:
            self.calls = PyTgCalls(userbot.two, cache_duration=100)
            await self.calls.start()
            self.calls.on_update()(self.call_update)
        async for doc in self.collection.find({"enabled": True}):
            try:
                await self.start_one(doc["token"], {
                    "id": doc["_id"], "username": doc.get("username"),
                    "first_name": doc.get("first_name")
                })
            except Exception:
                logger.exception("Could not start clone bot %s", doc.get("username"))

    async def new_member_handler(self, client, message):
        if any(member.id == client.me.id for member in (message.new_chat_members or [])):
            await self.collection.database.clone_chats.update_one(
                {"bot_id": client.clone_id, "chat_id": message.chat.id},
                {"$set": {"bot_id": client.clone_id, "chat_id": message.chat.id}},
                upsert=True,
            )

    async def call_update(self, _, update):
        if isinstance(update, call_types.StreamEnded):
            if update.chat_id == self.active_chat:
                self.active_chat = None
                asyncio.create_task(self.play_next())
        elif isinstance(update, call_types.ChatUpdate):
            if update.chat_id == self.active_chat and update.status in (
                call_types.ChatUpdate.Status.KICKED,
                call_types.ChatUpdate.Status.LEFT_GROUP,
                call_types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
            ):
                self.active_chat = None

    async def start_handler(self, client, message):
        if not message.from_user:
            return

        main = f"https://t.me/{app.username}"
        clone_link = f"https://t.me/{client.me.username}"
        private = message.chat.type == enums.ChatType.PRIVATE

        if not private:
            await self.collection.database.clone_chats.update_one(
                {"bot_id": client.clone_id, "chat_id": message.chat.id},
                {"$set": {"bot_id": client.clone_id, "chat_id": message.chat.id}},
                upsert=True,
            )

        # Match the original bot's language, start image, caption and button layout.
        text = await lang.get_lang(message.chat.id)
        if len(message.command) > 1 and message.command[1] == "help":
            return await message.reply_text(
                "<b>Yardım / Komutlar</b>\\n\\n"
                "/play şarkı adı veya bağlantı - Müzik oynat\\n"
                "/vplay şarkı adı veya bağlantı - Video oynat\\n"
                "/pause - Duraklat\\n"
                "/resume - Devam ettir\\n"
                "/skip - Sonraki parça\\n"
                "/queue - Sırayı göster\\n"
                "/stop - Yayını durdur"
            )

        caption = (
            text["start_pm"].format(message.from_user.first_name, client.me.first_name)
            if private
            else text["start_gp"].format(client.me.first_name)
        )

        rows = [
            [types.InlineKeyboardButton(
                text=text["add_me"], url=f"{clone_link}?startgroup=true"
            )],
            [types.InlineKeyboardButton(text=text["help"], url=f"{clone_link}?start=help")],
            [types.InlineKeyboardButton(
                text="🤖 Clone Oluştur", url=f"{main}?start=clone"
            )],
            [
                types.InlineKeyboardButton(text=text["support"], url=config.SUPPORT_CHAT),
                types.InlineKeyboardButton(text=text["channel"], url=config.SUPPORT_CHANNEL),
            ],
        ]
        if private:
            rows.append([
                types.InlineKeyboardButton(
                    text=text["source"], url="https://t.me/ellendiniz"
                )
            ])
        else:
            rows.append([
                types.InlineKeyboardButton(
                    text=text["language"], url=f"{main}?start=help"
                )
            ])

        keyboard = types.InlineKeyboardMarkup(rows)
        await message.reply_photo(
            photo=config.START_IMG,
            caption=caption,
            reply_markup=keyboard,
            quote=not private,
        )

    async def play_handler(self, client, message):
        if not config.SESSION2 or not self.calls:
            return await message.reply_text("Klon asistanı henüz yapılandırılmadı.")
        if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
            return await message.reply_text("Bu komutu grupta kullan.")
        if len(message.command) < 2:
            return await message.reply_text("Kullanım: /play şarkı adı veya bağlantı")
        chat_id = message.chat.id
        if self.active_chat is not None and self.active_chat != chat_id:
            return await message.reply_text("Klon asistanı başka bir grupta yayında. Yayın bitince tekrar dene.")
        async with self.lock:
            if self.active_chat is not None and self.active_chat != chat_id:
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
            item = {"client": client, "chat_id": chat_id, "track": track,
                    "file_path": file_path, "video": video, "status": status}
            if self.active_chat == chat_id:
                self.pending.append(item)
                return await status.edit_text(
                    f"➕ Kuyruğa eklendi ({len(self.pending)}). <b>{track.title}</b>"
                )
            await self._play_item(item)

    async def _play_item(self, item):
        client = item["client"]
        chat_id = item["chat_id"]
        assistant = userbot.two
        try:
            # Resolve the group through the clone bot, then join the assistant
            # with a public username or invite link. Calling get_chat_member()
            # first can raise CHANNEL_INVALID because the assistant has no
            # cached InputChannel/access_hash for this group yet.
            chat = await client.get_chat(chat_id)
            invite = chat.username or chat.invite_link
            if not invite:
                try:
                    invite = await client.export_chat_invite_link(chat_id)
                except Exception as exc:
                    raise RuntimeError(
                        "Klon botu grupta yönetici yap ve davet bağlantısı oluşturma izni ver."
                    ) from exc

            try:
                await assistant.join_chat(invite)
            except errors.UserAlreadyParticipant:
                pass
            except errors.InviteHashExpired:
                raise RuntimeError("Grup davet bağlantısının süresi dolmuş. Yeni bağlantı oluştur.")
            except errors.InviteHashInvalid:
                raise RuntimeError("Grup davet bağlantısı geçersiz. Klon botun davet bağlantısını yenile.")

            stream = call_types.MediaStream(
                media_path=item["file_path"],
                audio_parameters=call_types.AudioQuality.HIGH,
                video_parameters=call_types.VideoQuality.HD_720p,
                audio_flags=call_types.MediaStream.Flags.REQUIRED,
                video_flags=(call_types.MediaStream.Flags.AUTO_DETECT if item["video"] else call_types.MediaStream.Flags.IGNORE),
            )
            await self.calls.play(
                chat_id=chat_id,
                stream=stream,
                config=call_types.GroupCallConfig(auto_start=False),
            )
            self.active_chat = chat_id
            self.current_client = client
            await item["status"].edit_text(
                f"▶️ <b>{item['track'].title}</b>\\nAsistan: @{assistant.username}"
            )
        except Exception as exc:
            self.active_chat = None
            logger.exception("Clone playback failed in chat %s", chat_id)
            await item["status"].edit_text(f"Yayın başlatılamadı: {str(exc)[:300]}")
            if self.pending:
                asyncio.create_task(self.play_next())

    async def play_next(self):
        if self.active_chat is not None or not self.pending:
            return
        item = self.pending.pop(0)
        async with self.lock:
            if self.active_chat is None:
                await self._play_item(item)
            else:
                self.pending.insert(0, item)

    async def skip_handler(self, client, message):
        if self.active_chat != message.chat.id:
            return await message.reply_text("Bu grupta yayın bulunmuyor.")
        try:
            await self.calls.leave_call(message.chat.id)
        except Exception:
            pass
        self.active_chat = None
        await message.reply_text("⏭ Sıradaki parçaya geçiliyor.")
        await self.play_next()

    async def queue_handler(self, client, message):
        items = [item for item in self.pending if item["chat_id"] == message.chat.id]
        if self.active_chat != message.chat.id and not items:
            return await message.reply_text("Bu grupta yayın veya kuyruk bulunmuyor.")
        lines = [f"{i}. {item['track'].title}" for i, item in enumerate(items, 1)]
        text = "<b>Klon bot kuyruğu</b>\n" + ("\n".join(lines) if lines else "Kuyruk boş.")
        await message.reply_text(text)

    async def stop_handler(self, client, message):
        if not self.calls or self.active_chat != message.chat.id:
            return await message.reply_text("Bu grupta klon yayını bulunmuyor.")
        try:
            await self.calls.leave_call(message.chat.id)
        finally:
            self.active_chat = None
            self.pending = [item for item in self.pending if item["chat_id"] != message.chat.id]
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
