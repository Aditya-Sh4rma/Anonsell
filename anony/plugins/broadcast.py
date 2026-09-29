# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic
#
# ONE-TIME broadcast + DB cleanup version.
# Sirf permanent failures (blocked / deleted / kicked / banned) Mongo se delete hoti hain.
# Baaki har failure (flood, network, media forbidden, message issue...) me ID DB me SAFE rehti hai.


import os
import time
import html
import asyncio
from collections import Counter

from pyrogram import errors, filters, types

from anony import app, db, lang


broadcasting = asyncio.Lock()

# Ye errors = chat/user ab reachable nahi hai -> DB se delete
DEAD = {
    "UserIsBlocked", "InputUserDeactivated", "UserIsBot", "UserIdInvalid",
    "PeerIdInvalid", "ChatIdInvalid", "ChannelInvalid", "ChannelPrivate",
    "ChatWriteForbidden", "ChatRestricted", "UserBannedInChannel",
    "UserNotParticipant",
}
BATCH = 100        # itni dead IDs jama hone par ek saath Mongo se delete
MAX_UNKNOWN = 100  # lagataar itne unknown errors -> broadcast rok do (kuch gadbad hai)


async def _send(msg, target, copy):
    """Returns (status, error_name, error_text). status: ok / dead / keep"""
    for _ in range(3):
        try:
            if copy:
                await msg.copy(target, reply_markup=msg.reply_markup)
            else:
                await msg.forward(target)
            return "ok", "", ""
        except errors.FloodWait as fw:
            await asyncio.sleep(fw.value + 5)  # wait karke SAME target dobara try
        except Exception as ex:
            name = type(ex).__name__
            text = str(ex).replace("\n", " ")
            return ("dead" if name in DEAD else "keep"), name, text
    return "keep", "FloodWait", "still flood-waited after 3 retries"


def _new(label, total):
    return {
        "label": label, "total": total, "done": 0, "sent": 0, "removed": 0,
        "kept": 0, "stuck": 0, "abort": None, "why": Counter(),
    }


def _report(stats):
    return "\n".join(
        f"{s['label']}: {s['done']}/{s['total']} | sent {s['sent']} | "
        f"removed {s['removed']} | kept {s['kept']}"
        for s in stats
    )


async def _sweep(msg, copy, targets, coll, cache, st, kept, tick):
    pending, limit, streak = [], BATCH, 0

    async def flush():
        nonlocal limit
        if not pending:
            return
        batch = pending[:]
        try:
            await coll.delete_many({"_id": {"$in": batch}})
        except Exception:
            limit = len(pending) + BATCH  # Mongo error: IDs pending me rahengi, baad me phir try
            return
        limit = BATCH
        gone = set(batch)
        cache[:] = [i for i in cache if i not in gone]  # memory list bhi sync
        del pending[: len(batch)]
        st["removed"] += len(batch)

    try:
        for target in targets:
            status, name, text = await _send(msg, target, copy)
            st["done"] += 1
            if status == "ok":
                st["sent"] += 1
                streak = 0
                await asyncio.sleep(0.1)
            elif status == "dead":
                st["why"][name] += 1
                pending.append(target)
                streak = 0
                if len(pending) >= limit:
                    await flush()
            else:  # unknown / temporary -> DB se kuch delete NAHI hoga
                st["kept"] += 1
                kept.append(f"{target} - {name}: {text}")
                streak += 1
                if streak >= MAX_UNKNOWN:
                    st["abort"] = f"{name}: {text}"
                    return
            await tick()
    finally:
        await flush()
        st["stuck"] = len(pending)


@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text(message.lang["gcast_usage"])

    if broadcasting.locked():
        return await message.reply_text(message.lang["gcast_active"])

    msg = message.reply_to_message
    copy = "-copy" in message.command
    sent = await message.reply_text(message.lang["gcast_start"])
    kept, stats, crash = [], [], None
    last = time.monotonic()

    async def tick():  # har 60s me progress
        nonlocal last
        if time.monotonic() - last < 60:
            return
        last = time.monotonic()
        try:
            await sent.edit_text("Broadcast + cleanup running...\n\n" + _report(stats))
        except Exception:
            pass

    async with broadcasting:
        try:
            phases = []
            if "-nochat" not in message.command:
                phases.append(("Chats", await db.get_chats(), db.chatsdb))
            if "-user" in message.command:
                phases.append(("Users", await db.get_users(), db.usersdb))

            for label, cache, coll in phases:
                st = _new(label, len(cache))
                stats.append(st)
                await _sweep(msg, copy, list(cache), coll, cache, st, kept, tick)
                if st["abort"]:
                    break
        except Exception as ex:
            crash = f"{type(ex).__name__}: {ex}"

    bad = crash or any(s["abort"] for s in stats)
    text = "Broadcast STOPPED early." if bad else "Broadcast + cleanup done."
    text += "\n\n" + _report(stats)

    why = sum((s["why"] for s in stats), Counter())
    if why:
        text += "\n\nRemoved from DB:\n" + "\n".join(
            f"{k}: {v}" for k, v in why.most_common(10)
        )
    for s in stats:
        if s["abort"]:
            text += (
                f"\n\n{s['label']} stopped: {MAX_UNKNOWN} unknown errors in a row."
                f"\nLast: {html.escape(s['abort'][:200])}"
            )
        if s["stuck"]:
            text += f"\n\n{s['label']}: {s['stuck']} dead IDs could not be deleted (Mongo error)."
    if crash:
        text += f"\n\nCrash: {html.escape(crash[:300])}"

    try:
        await sent.edit_text(text)
    except Exception:
        await message.reply_text(text)

    if kept:
        try:
            with open("kept_errors.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(kept))
            await message.reply_document(
                document="kept_errors.txt",
                caption="Ye IDs DB me SAFE hain (delete nahi hui) - error list",
            )
        except Exception:
            pass
        try:
            os.remove("kept_errors.txt")
        except Exception:
            pass
