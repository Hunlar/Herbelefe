# Download YouTube videos as MP4 or audio as MP3.

from pathlib import Path

from pyrogram import filters, types
from pyrogram.errors import UserNotParticipant, UserAlreadyParticipant

from anony import app, db, lang, yt
from anony.helpers import utils
from anony.helpers._custom_emoji import random_pack_emoji, pack_caption_entities


async def _get_joined_assistant(m: types.Message):
    client = await db.get_client(m.chat.id)
    try:
        await client.get_chat_member(m.chat.id, client.id)
    except UserNotParticipant:
        invite = m.chat.username
        if not invite:
            chat = await app.get_chat(m.chat.id)
            invite = chat.invite_link or await app.export_chat_invite_link(m.chat.id)
        try:
            await client.join_chat(invite)
        except UserAlreadyParticipant:
            pass
    return client


def _query_from_message(m: types.Message) -> str | None:
    url = utils.get_url(m)
    if url:
        return url
    if len(m.command) > 1:
        return " ".join(m.command[1:])
    return None


@app.on_message(filters.command(["video", "voice"]) & filters.group & ~app.bl_users)
@lang.language()
async def download_youtube(_, m: types.Message):
    if not m.from_user:
        return await m.reply_text("Bu komutu kullanıcı hesabıyla kullanmalısın.")

    query = _query_from_message(m)
    if not query:
        command = m.command[0].lower()
        usage = (
            "Kullanım: /video YouTube bağlantısı veya /video video adı"
            if command == "video"
            else "Kullanım: /voice YouTube bağlantısı veya /voice video adı"
        )
        return await m.reply_text(usage)

    status = await m.reply_text("YouTube içeriği aranıyor...")
    track = await yt.search(query, status.id, video=(m.command[0].lower() == "video"))
    if not track:
        return await status.edit_text("YouTube içeriği bulunamadı.")

    is_video = m.command[0].lower() == "video"
    await status.edit_text("Video indiriliyor..." if is_video else "Ses MP3 olarak indiriliyor...")
    file_path = await yt.download(
        track.id, video=is_video, audio_format=None if is_video else "mp3"
    )
    if not file_path or not Path(file_path).is_file():
        return await status.edit_text(
            "İndirme başarısız oldu. YouTube çerezleri geçersiz veya süresi dolmuş olabilir."
        )

    try:
        client = await _get_joined_assistant(m)
        emoji, entity = await random_pack_emoji()
        caption = f"{emoji} {track.title}\nProd By @Sancakmain"
        if is_video:
            await client.send_video(
                chat_id=m.chat.id, video=file_path, caption=caption,
                caption_entities=pack_caption_entities(entity),
                reply_to_message_id=m.id,
            )
        else:
            await client.send_audio(
                chat_id=m.chat.id, audio=file_path, title=track.title,
                performer=track.channel_name or "YouTube",
                caption=caption, caption_entities=pack_caption_entities(entity),
                reply_to_message_id=m.id,
            )
        await status.delete()
    except Exception as ex:
        await status.edit_text(f"Dosya Telegram'a gönderilemedi: {str(ex)[:250]}")
