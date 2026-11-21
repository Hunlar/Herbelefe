"""Film and series catalogue search using The Movie Database (TMDB).

This module searches catalogue metadata only. Playback must use a direct stream
URL that the user owns or is authorized to distribute, supplied to /vplay.
"""

import aiohttp
from pyrogram import filters, types
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from anony import app, config

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w500"


def _year(item, media_type):
    value = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
    return value[:4] if value else "Yıl bilinmiyor"


async def _tmdb(path, params):
    if not config.TMDB_API_KEY:
        return None
    params = {**params, "api_key": config.TMDB_API_KEY, "language": "tr-TR"}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{TMDB_API}{path}", params=params) as response:
            if response.status != 200:
                return None
            return await response.json()


async def _search(message: types.Message, media_type: str):
    if len(message.command) < 2:
        usage = "/film film adı" if media_type == "movie" else "/dizi dizi adı"
        return await message.reply_text(f"Kullanım: <code>{usage}</code>")

    if not config.TMDB_API_KEY:
        return await message.reply_text(
            "Film/dizi araması için Heroku Config Vars bölümüne "
            "<code>TMDB_API_KEY</code> eklenmeli. API anahtarı: themoviedb.org"
        )

    query = " ".join(message.command[1:]).strip()
    status = await message.reply_text("🔎 Katalogda aranıyor...")
    endpoint = "/search/movie" if media_type == "movie" else "/search/tv"
    data = await _tmdb(endpoint, {"query": query, "page": 1, "include_adult": "false"})
    results = (data or {}).get("results", [])[:8]
    if not results:
        return await status.edit_text("Sonuç bulunamadı. Başka bir isim deneyin.")

    buttons = []
    for item in results:
        title = item.get("title") if media_type == "movie" else item.get("name")
        title = title or "İsimsiz içerik"
        label = f"{title[:38]} · {_year(item, media_type)}"
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=f"catalog:{media_type}:{item['id']}"
        )])
    await status.edit_text(
        "Bulunan içerikler (katalog bilgisi):\n\nBirini seç:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@app.on_message(filters.command(["film"]) & filters.group & ~app.bl_users)
async def film_search(_, message: types.Message):
    await _search(message, "movie")


@app.on_message(filters.command(["dizi"]) & filters.group & ~app.bl_users)
async def series_search(_, message: types.Message):
    await _search(message, "tv")


@app.on_callback_query(filters.regex(r"^catalog:(movie|tv):\d+$") & ~app.bl_users)
async def catalog_select(_, query: types.CallbackQuery):
    try:
        _, media_type, item_id = query.data.split(":", 2)
    except ValueError:
        return await query.answer("Geçersiz seçim.", show_alert=True)

    await query.answer("İçerik bilgisi alınıyor...")
    endpoint = f"/{'movie' if media_type == 'movie' else 'tv'}/{item_id}"
    data = await _tmdb(endpoint, {})
    if not data:
        return await query.message.edit_text("İçerik bilgisi alınamadı.")

    title = data.get("title") if media_type == "movie" else data.get("name")
    title = title or "İsimsiz içerik"
    date = _year(data, media_type)
    overview = data.get("overview") or "Açıklama bulunmuyor."
    if len(overview) > 900:
        overview = overview[:897] + "..."

    poster = data.get("poster_path")
    caption = (
        f"<b>{title}</b> ({date})\n\n{overview}\n\n"
        "<b>Oynatma:</b> Bu katalog kaydı doğrudan video içermez. "
        "Sahip olduğun veya yayınlama iznin bulunan doğrudan MP4/HLS (.m3u8) "
        "yayın bağlantısını şu komutla başlatabilirsin:\n"
        "<code>/vplay https://.../stream.m3u8</code>\n\n"
        "Web sayfası adresi değil, doğrudan ve yetkili yayın bağlantısı gerekir."
    )
    if poster:
        try:
            return await query.message.edit_media(
                media=types.InputMediaPhoto(f"{TMDB_IMAGE}{poster}", caption=caption)
            )
        except Exception:
            pass
    await query.message.edit_text(caption, disable_web_page_preview=True)
