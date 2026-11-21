# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.

import asyncio
import os
import time
from pathlib import Path

from pyrogram import types

from anony import config, db
from anony.helpers import Media, buttons, utils


class Telegram:
    def __init__(self):
        self.active = []
        self.events = {}
        self.last_edit = {}
        self.active_tasks = {}
        self.sleep = 5

    def get_media(self, msg: types.Message) -> bool:
        return any((msg.video, msg.audio, msg.document, msg.voice))

    async def cancel(self, query: types.CallbackQuery):
        event = self.events.get(query.message.id)
        task = self.active_tasks.pop(query.message.id, None)
        if event:
            event.set()
        if task and not task.done():
            task.cancel()
        if event or task:
            await query.edit_message_text(query.lang["dl_cancel"].format(query.from_user.mention))
        else:
            await query.answer(query.lang["dl_not_found"], show_alert=True)

    async def download(self, msg: types.Message, sent: types.Message) -> Media | None:
        msg_id = sent.id
        event = asyncio.Event()
        self.events[msg_id] = event
        self.last_edit[msg_id] = 0
        start_time = time.time()

        media = msg.audio or msg.voice or msg.video or msg.document
        if not media:
            await sent.edit_text(sent.lang["dl_limit"])
            return None

        file_id = getattr(media, "file_unique_id", None) or str(media.file_id)
        original_name = getattr(media, "file_name", None) or ""
        file_ext = Path(original_name).suffix.lstrip(".").lower()
        if not file_ext:
            mime = getattr(media, "mime_type", "") or ""
            file_ext = mime.split("/", 1)[-1].split(";", 1)[0] if "/" in mime else "bin"
            if file_ext == "mpeg":
                file_ext = "mp3"
        file_size = getattr(media, "file_size", 0) or 0
        file_title = getattr(media, "title", None) or Path(original_name).stem or "Telegram File"
        duration = getattr(media, "duration", 0) or 0
        video = bool(
            (getattr(media, "mime_type", "") or "").startswith("video/")
            or file_ext in {"mp4", "m4v", "mkv", "mov", "webm", "avi"}
        )

        if duration > config.DURATION_LIMIT:
            await sent.edit_text(sent.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60))
            return None

        if file_size > config.DOWNLOAD_LIMIT_BYTES:
            await sent.edit_text(
                f"Dosya çok büyük. İzin verilen üst sınır: {config.DOWNLOAD_LIMIT_MB} MB."
            )
            return None

        async def progress(current, total):
            if event.is_set() or not total:
                return
            now = time.time()
            if now - self.last_edit[msg_id] < self.sleep:
                return
            self.last_edit[msg_id] = now
            percent = current * 100 / total
            speed = current / max(now - start_time, 1e-6)
            eta = utils.format_eta(int((total - current) / max(speed, 1)))
            text = sent.lang["dl_progress"].format(
                utils.format_size(current), utils.format_size(total), percent,
                utils.format_size(speed), eta,
            )
            await sent.edit_text(text, reply_markup=buttons.cancel_dl(sent.lang["cancel"]))

        try:
            download_dir = Path("downloads")
            download_dir.mkdir(parents=True, exist_ok=True)
            file_path = download_dir / f"{file_id}.{file_ext}"

            if file_path.exists() and file_path.stat().st_size > 0:
                return Media(
                    id=file_id, duration=time.strftime("%M:%S", time.gmtime(duration)),
                    duration_sec=duration, file_path=str(file_path), message_id=sent.id,
                    url=msg.link, title=file_title[:25], video=video,
                )

            if file_id in self.active:
                await sent.edit_text(sent.lang["dl_active"])
                return None

            self.active.append(file_id)
            # Bot API downloads are size-limited; fetch the same message through
            # the already-joined assistant user account for large media files.
            client = await db.get_client(msg.chat.id)
            source_msg = await client.get_messages(msg.chat.id, msg.id)
            if not source_msg or not (source_msg.audio or source_msg.voice or source_msg.video or source_msg.document):
                raise RuntimeError("Asistan hesabı yanıtlanan medya mesajına erişemedi.")
            task = asyncio.create_task(
                source_msg.download(file_name=str(file_path), progress=progress)
            )
            self.active_tasks[msg_id] = task
            downloaded_path = await task
            actual_path = Path(downloaded_path) if downloaded_path else file_path
            if not actual_path.exists() or actual_path.stat().st_size == 0:
                raise RuntimeError("Telegram indirmesi tamamlandı ancak dosya bulunamadı.")

            await sent.edit_text(sent.lang["dl_complete"].format(round(time.time() - start_time, 2)))
            return Media(
                id=file_id, duration=time.strftime("%M:%S", time.gmtime(duration)),
                duration_sec=duration, file_path=str(actual_path), message_id=sent.id,
                url=msg.link, title=file_title[:25], video=video,
            )
        except asyncio.CancelledError:
            return None
        except Exception as ex:
            from anony import logger
            logger.exception("Telegram media download failed: %s", ex)
            await sent.edit_text(f"İndirme başarısız oldu: {str(ex)[:250]}")
            return None
        finally:
            self.events.pop(msg_id, None)
            self.last_edit.pop(msg_id, None)
            self.active_tasks.pop(msg_id, None)
            if file_id in self.active:
                self.active.remove(file_id)

    async def process_m3u8(self, url: str, msg_id: int, video: bool) -> Media:
        return Media(
            id=str(msg_id), file_path=url, message_id=msg_id, url=url,
            title="M3U8 Stream", video=video,
        )
