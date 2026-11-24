"""Helpers for the two requested Telegram custom-emoji packs."""
import random

from pyrogram import enums, types

PACKS = ("RestrictedEmoji", "ApplicationEmoji")
_fetched = False
_entities = []


async def random_pack_emoji():
    global _fetched, _entities
    if not _fetched:
        _fetched = True
        try:
            from anony import userbot
            clients = list(userbot.clients)
            for client in clients:
                for pack in PACKS:
                    try:
                        sticker_set = await client.get_sticker_set(pack)
                        for sticker in sticker_set.stickers:
                            emoji = getattr(sticker, "emoji", None) or "✨"
                            custom_id = getattr(sticker, "custom_emoji_id", None)
                            if custom_id:
                                _entities.append((emoji, int(custom_id)))
                    except Exception:
                        continue
                if _entities:
                    break
        except Exception:
            pass

    if not _entities:
        return random.choice(("🎵", "🎧", "🔥", "⚡")), None

    emoji, custom_id = random.choice(_entities)
    length = len(emoji.encode("utf-16-le")) // 2
    entity = types.MessageEntity(
        type=enums.MessageEntityType.CUSTOM_EMOJI,
        offset=0,
        length=length,
        custom_emoji_id=custom_id,
    )
    return emoji, entity


def pack_caption_entities(entity):
    return [entity] if entity else None
