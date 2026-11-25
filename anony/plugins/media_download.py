"""Download replied Telegram media as video or extracted audio."""

import asyncio
import os
import subprocess
from pathlib import Path

from pyrogram import filters, types

from anony import app, config, lang, tg
from anony.helpers._custom_emoji import random_pack_emoji, pack_caption_entities

DOWNLOAD_DIR = Path("downloads")


def _media_kind(message: types.Message) -> tuple[bool, str]:
    """Return (is_video, description) for supported replied media."""
    media = message.video or message.audio or message.voice or message.document
    if not media:
        return False, ""
    mime = (getattr(media, "mime_type", "") or "").lower()
    is_video = bool(message.video) or mime.startswith("video/")
    is_audio = bool(message.audio) or bool(message.voice) or mime.startswith("audio/")
    return is_video, "video" if is_video else ("audio" if is_audio else "other")


async def _extract_audio(source: str, destination: str) -> None:
    """Extract an MP3 audio track with FFmpeg."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", source, "-vn", "-acodec", "libmp3lame",
        "-b:a", "128k", "-ar", "44100", destination,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0 or not Path(destination).is_file():
        detail = stderr.decode("utf-8", "ignore")[-1200:]
        raise RuntimeError(f"FFmpeg ses dönüştürme hatası: {detail}")


@app.on_message(filters.command(["video", "voice"]) & filters.group & ~app.bl_users)
@lang.language()
async def media_download_handler(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text(
            "Kullanım: Bir video veya ses mesajına yanıt verip /video ya da /voice yaz."
        )

    source_message = message.reply_to_message
    is_video, kind = _media_kind(source_message)
    command = message.command[0].lower()

    if kind == "":
        return await message.reply_text("Yanıtladığın mesajda indirilebilir video veya ses bulunamadı.")
    if command == "video" and not is_video:
        return await message.reply_text("/video için yanıtladığın mesajın video olması gerekiyor.")
    if command == "voice" and kind == "other":
        return await message.reply_text("/voice için video veya ses dosyasına yanıt vermelisin.")

    status = await message.reply_text("⏬ Dosya indiriliyor...")
    status.lang = message.lang
    downloaded = await tg.download(source_message, status)
    if not downloaded:
        return

    source_path = Path(downloaded.file_path)
    if not source_path.is_file():
        return await status.edit_text("İndirilen dosya bulunamadı.")

    output_path = source_path
    generated = False
    try:
        if command == "voice":
            output_path = source_path.with_name(f"{source_path.stem}_audio.mp3")
            await status.edit_text("🎧 Videonun sesi çıkarılıyor...")
            await _extract_audio(str(source_path), str(output_path))
            generated = True

        size_mb = output_path.stat().st_size / (1024 * 1024)
        if size_mb > config.DOWNLOAD_LIMIT_MB:
            return await status.edit_text(
                f"Dosya Telegram gönderim sınırını aşıyor: {size_mb:.1f} MB. "
                f"Ayarlanan sınır: {config.DOWNLOAD_LIMIT_MB} MB."
            )

        await status.edit_text("📤 Dosya Telegram'a gönderiliyor...")
        emoji, entity = await random_pack_emoji()
        caption = f"{emoji} {source_path.name if command == 'video' else 'Ses dosyası'}\nProd By @Sancakmain"
        if command == "video":
            await app.send_video(
                chat_id=message.chat.id,
                video=str(output_path),
                caption=caption,
                caption_entities=pack_caption_entities(entity),
                reply_to_message_id=source_message.id,
                supports_streaming=True,
            )
        else:
            await app.send_audio(
                chat_id=message.chat.id,
                audio=str(output_path),
                title=source_path.stem[:64],
                caption=caption,
                caption_entities=pack_caption_entities(entity),
                reply_to_message_id=source_message.id,
            )
        await status.delete()
    except Exception as exc:
        from anony import logger
        logger.exception("/%s media export failed", command)
        await status.edit_text(f"Dosya gönderilemedi: {str(exc)[:700]}")
    finally:
        if generated:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
