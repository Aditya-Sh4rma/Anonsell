# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import os
import asyncio

from pyrogram import errors, filters, types

from anony import app, db, lang


broadcasting = asyncio.Lock()

@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text(message.lang["gcast_usage"])

    if broadcasting.locked():
        return await message.reply_text(message.lang["gcast_active"])

    msg = message.reply_to_message
    copy = "-copy" in message.command
    count, ucount = 0, 0
    failed_lines = []  

    sent = await message.reply_text(message.lang["gcast_start"])

    async with broadcasting:

        if "-nochat" not in message.command:
            groups = list(await db.get_chats())
            for chat in groups:
                try:
                    (
                        await msg.copy(chat, reply_markup=msg.reply_markup)
                        if copy
                        else await msg.forward(chat)
                    )
                    count += 1
                    await asyncio.sleep(0.1)
                except errors.FloodWait as fw:
                    await asyncio.sleep(fw.value + 10)
                except Exception as ex:
                    failed_lines.append(f"{chat} - {ex}")
                    continue

        if "-user" in message.command:
            users = list(await db.get_users())
            for user in users:
                try:
                    (
                        await msg.copy(user, reply_markup=msg.reply_markup)
                        if copy
                        else await msg.forward(user)
                    )
                    ucount += 1
                    await asyncio.sleep(0.1)
                except errors.FloodWait as fw:
                    await asyncio.sleep(fw.value + 10)
                except Exception as ex:
                    failed_lines.append(f"{user} - {ex}")
                    continue

    text = message.lang["gcast_end"].format(count, ucount)
    if failed_lines:
        try:
            with open("errors.txt", "w") as f:
                f.write("\n".join(failed_lines))
            await message.reply_document(
                document="errors.txt",
                caption=text,
            )
        except Exception:
            pass
        try:
            os.remove("errors.txt")
        except Exception:
            pass
    else:
        await sent.edit_text(text)
