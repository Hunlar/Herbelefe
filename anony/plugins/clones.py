from pyrogram import filters, types, errors

from anony import app, clones, db

@app.on_message(filters.command("clone") & app.sudoers)
async def add_clone(_, message: types.Message):
    if len(message.command) != 2:
        return await message.reply_text("Kullanım: /clone BOTFATHER_TOKEN")
    token = message.command[1].strip()
    status = await message.reply_text("Bot tokeni doğrulanıyor...")
    try:
        me = await clones.add(token, message.from_user.id)
        try:
            await message.delete()
        except Exception:
            pass
        await status.edit_text(
            f"✅ Klon bot eklendi: @{me.get('username') or me['id']}\n"
            "Komutlar: /play, /vplay, /pause, /resume, /stop"
        )
    except Exception as exc:
        await status.edit_text(f"Klon eklenemedi: {str(exc)[:300]}")

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
    for bot_id, client in list(clones.clients.items()):
        try:
            async for chat in clones.collection.find({"_id": bot_id}):
                # Broadcast only to chats where this clone has been started.
                async for target in clones.collection.database.clone_chats.find({"bot_id": bot_id}):
                    try:
                        await message.reply_to_message.copy(target["chat_id"], client=client)
                        sent += 1
                    except Exception:
                        failed += 1
        except Exception:
            failed += 1
    await message.reply_text(f"Duyuru tamamlandı. Gönderilen: {sent} | Hata: {failed}")
