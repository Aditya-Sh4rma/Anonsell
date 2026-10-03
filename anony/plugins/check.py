from pyrogram import filters, types

from anony import app


@app.on_message(filters.command("check") & filters.private)
async def check_func(_, m: types.Message):
    await m.reply_text("Bot is alive.")
