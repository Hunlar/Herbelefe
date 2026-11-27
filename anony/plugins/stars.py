from pyrogram import filters, types

from anony import app

DONATION_STARS = 10

async def send_donation(client, chat_id: int):
    await client.send_invoice(
        chat_id=chat_id,
        title="Sancak MAİN Destek",
        description="Sancak MAİN topluluğuna Stars ile destek ol.",
        payload="herbelefe-donation-v1",
        provider_token="",
        currency="XTR",
        prices=[types.LabeledPrice(label="Sancak MAİN destek", amount=DONATION_STARS)],
    )

@app.on_message(filters.command(["donate", "bagis"]) & filters.private)
async def donate_command(_, message: types.Message):
    await send_donation(app, message.chat.id)

@app.on_message(filters.successful_payment & filters.private)
async def donation_success(_, message: types.Message):
    payment = message.successful_payment
    if payment.invoice_payload != "herbelefe-donation-v1":
        return
    await message.reply_text(
        f"⭐ Desteğin için teşekkürler! {payment.total_amount} Stars, Sancak MAİN desteğine ulaştı."
    )
