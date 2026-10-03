import asyncio
import html
import time
from collections import Counter
from dataclasses import dataclass, field

from pyrogram import enums, errors, filters, types

from anony import anon, app, config, db, logger, queue, userbot

ASK_CONFIRM = True
NOTIFY_CHATS = True
LEAVE_CHANNELS = True
KEEP_CHATS = {config.LOGGER_ID}
LEAVE_DELAY = 0.5
PROGRESS_EVERY = 8

NOTICE = (
    "Playback was stopped and the queue was cleared because the assistants "
    "are being reset.\nUse /play again, the assistant will rejoin automatically."
)

OWNER = filters.user(config.OWNER_ID)

_running = False
_tasks: set[asyncio.Task] = set()


@dataclass
class _Stat:
    label: str
    total: int = 0
    left: int = 0
    failed: Counter = field(default_factory=Counter)

    @property
    def done(self) -> int:
        return self.left + sum(self.failed.values())


def _label(client) -> str:
    return html.escape(f"@{client.username}" if client.username else str(client.name))


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _busy(chat_id: int) -> bool:
    return chat_id in db.active_calls or bool(queue.queues.get(chat_id))


async def _edit(msg: types.Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except Exception:
        pass


def _render(
    stats: list[_Stat], header: str, footer: str = "", final: bool = False
) -> str:
    lines = [f"<b>{header}</b>", ""]
    for i, s in enumerate(stats, start=1):
        line = f"Assistant {i} ({s.label}): "
        line += f"{s.left} left" if final else f"{s.done}/{s.total}"
        if s.failed:
            reasons = ", ".join(f"{k} x{v}" for k, v in s.failed.most_common(3))
            line += f", {sum(s.failed.values())} failed ({reasons})"
        lines.append(line)
    if footer:
        lines += ["", footer]
    return "\n".join(lines)


async def _reset(chat_id: int) -> None:
    try:
        await anon.stop(chat_id)
    except Exception as ex:
        logger.error(f"/leftall: anon.stop({chat_id}) failed: {type(ex).__name__}")
    queue.clear(chat_id)
    await db.remove_call(chat_id)
    await db.set_loop(chat_id, 0)


async def _notify(chat_id: int, msg_id: int) -> None:
    if msg_id:
        try:
            await app.delete_messages(chat_id, msg_id, revoke=True)
        except Exception:
            pass
    try:
        await app.send_message(chat_id, NOTICE)
    except Exception:
        pass


async def _stop_music() -> int:
    playing = list(db.active_calls)
    leftovers = [
        chat_id
        for chat_id, items in list(queue.queues.items())
        if items and chat_id not in db.active_calls
    ]

    for chat_id in playing:
        items = queue.queues.get(chat_id)
        msg_id = items[0].message_id if items else 0
        await _reset(chat_id)
        if NOTIFY_CHATS:
            await _notify(chat_id, msg_id)

    for chat_id in leftovers:
        await _reset(chat_id)
    return len(playing)


async def _collect(client) -> list[tuple[int, str]]:
    skip = {enums.ChatType.PRIVATE, enums.ChatType.BOT}
    if not LEAVE_CHANNELS:
        skip.add(enums.ChatType.CHANNEL)

    chats = []
    async for dialog in client.get_dialogs():
        chat = dialog.chat
        if chat.id in KEEP_CHATS or chat.type in skip:
            continue
        chats.append((chat.id, chat.title or str(chat.id)))
    return chats


async def _plan() -> list[list[tuple[int, str]]]:
    results = await asyncio.gather(
        *(_collect(client) for client in userbot.clients), return_exceptions=True
    )
    for res in results:
        if isinstance(res, BaseException):
            raise res
    return results


async def _leave(client, chat_id: int) -> str | None:
    for _ in range(3):
        try:
            await client.leave_chat(chat_id)
            return None
        except errors.FloodWait as ex:
            await asyncio.sleep(ex.value + 1)
        except Exception as ex:
            return type(ex).__name__
    return "FloodWait"


async def _worker(client, chats: list[tuple[int, str]], stat: _Stat) -> None:
    for chat_id, title in chats:
        if _busy(chat_id):
            await _reset(chat_id)

        err = await _leave(client, chat_id)
        if err:
            stat.failed[err] += 1
            logger.error(
                f"/leftall: {stat.label} could not leave {chat_id} ({title}): {err}"
            )
        else:
            stat.left += 1

        if _busy(chat_id):
            await _reset(chat_id)
        await asyncio.sleep(LEAVE_DELAY)


async def _ticker(msg: types.Message, stats: list[_Stat]) -> None:
    while True:
        await _edit(msg, _render(stats, "Leaving chats, please wait..."))
        await asyncio.sleep(PROGRESS_EVERY)


async def _run(msg: types.Message) -> None:
    global _running
    started = time.time()
    try:
        logger.info("/leftall started.")
        await _edit(msg, "Stopping music and clearing queues...")
        stopped = await _stop_music()

        await _edit(msg, "Reading the chat list of every assistant...")
        plans = await _plan()
        stats = [_Stat(_label(c), len(p)) for c, p in zip(userbot.clients, plans)]

        ticker = asyncio.create_task(_ticker(msg, stats))
        try:
            results = await asyncio.gather(
                *(
                    _worker(c, p, s)
                    for c, p, s in zip(userbot.clients, plans, stats)
                ),
                return_exceptions=True,
            )
        finally:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)

        for res in results:
            if isinstance(res, BaseException):
                logger.error(f"/leftall: worker crashed: {type(res).__name__}: {res}")

        footer = f"Playback stopped in {stopped} chat(s). Logger group was skipped."
        if any(s.failed for s in stats):
            footer += "\nFailed chats are listed in the bot log."
        took = _fmt(time.time() - started)
        await _edit(msg, _render(stats, f"Leftall finished in {took}", footer, True))
        logger.info(f"/leftall finished in {took}.")
    except Exception as ex:
        logger.error(f"/leftall crashed: {type(ex).__name__}: {ex}")
        await _edit(
            msg,
            f"Leftall stopped by an error: <code>{html.escape(type(ex).__name__)}</code>",
        )
    finally:
        _running = False


def _spawn(msg: types.Message) -> bool:
    global _running
    if _running:
        return False
    _running = True
    task = asyncio.create_task(_run(msg))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


@app.on_message(filters.command("leftall") & OWNER)
async def leftall_cmd(_, m: types.Message):
    if _running:
        return await m.reply_text("Leftall is already running.")
    if not userbot.clients:
        return await m.reply_text("No assistant is connected.")

    if not ASK_CONFIRM:
        sent = await m.reply_text("Starting leftall...")
        if not _spawn(sent):
            await _edit(sent, "Leftall is already running.")
        return

    sent = await m.reply_text("Checking assistants...")
    try:
        plans = await _plan()
    except Exception as ex:
        return await _edit(
            sent,
            f"Could not read the chat list: <code>{html.escape(type(ex).__name__)}</code>",
        )

    if not sum(len(p) for p in plans):
        return await _edit(
            sent, "Nothing to leave. The assistants are only in the logger group."
        )

    lines = ["<b>Leftall</b>", ""]
    for i, (c, p) in enumerate(zip(userbot.clients, plans), start=1):
        lines.append(f"Assistant {i} ({_label(c)}): {len(p)} chats")
    lines += [
        "",
        f"Music is playing in {len(db.active_calls)} chat(s); it will be stopped "
        "and the queues cleared.",
        f"Logger group <code>{config.LOGGER_ID}</code> will be skipped.",
        "",
        f"Every assistant will leave all its groups{' and channels' if LEAVE_CHANNELS else ''}. "
        "Continue?",
    ]
    buttons = types.InlineKeyboardMarkup(
        [
            [
                types.InlineKeyboardButton("Confirm", callback_data="leftall_yes"),
                types.InlineKeyboardButton("Cancel", callback_data="leftall_no"),
            ]
        ]
    )
    await sent.edit_text("\n".join(lines), reply_markup=buttons)


@app.on_callback_query(filters.regex(r"^leftall_(yes|no)$"))
async def leftall_cb(_, query: types.CallbackQuery):
    if query.from_user.id != config.OWNER_ID:
        return await query.answer("Only the owner can use this.", show_alert=True)

    if query.data == "leftall_no":
        return await query.message.edit_text("Leftall cancelled.")

    if not _spawn(query.message):
        return await query.answer("Leftall is already running.", show_alert=True)
    await query.answer("Started.")
