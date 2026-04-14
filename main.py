import asyncio
import logging
import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions, ChatMemberUpdated, ContentType
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION

# ==============================
# ТОКЕН БОТА
# ==============================
BOT_TOKEN = "8574174287:AAGBQdko0QpRZSxb6J8PXVd1AYcz0GlgLwQ"

# ==============================
# РАЗРЕШЁННАЯ ГРУППА
# ==============================
ALLOWED_CHAT_ID = -1002320683005

# ==============================
# WHITELIST
# ==============================
ALLOWED_USERS = {2007585386, 5705359189}
ALLOWED_USERNAMES = {"Nikitasova01", "MrDakplease"}

# ==============================
# КУДА СЛАТЬ РЕПОРТЫ
# ==============================
REPORT_RECEIVERS = {2007585386, 5705359189}

# ==============================
# КАНАЛ ДЛЯ АНОНИМНЫХ СООБЩЕНИЙ
# ==============================
ANON_CHANNEL_ID = -1002320683005

# ==============================
# Антиспам
# ==============================
SPAM_MAX_MESSAGES = 5
SPAM_WINDOW = 5
MAX_MESSAGE_LENGTH = 350
spam_tracker: dict[int, list[float]] = defaultdict(list)
waiting_for_anon = set()

# ==============================
# Состояние чата (открыт/закрыт)
# ==============================
chat_locked = False

# ==============================
# Запретные слова
# ==============================
BANNED_WORDS = [
    "дс", "дискорд", "хохол",
    "гойда", "сво", "卐", "1488",
]

# ==============================
# ПРАВИЛА
# ==============================
RULES_TEXT = """
📜 <b>ПРАВИЛА!</b>

<b>1.0</b> Угозы — <i>1 день</i>
<b>1.1</b> Дофига матов — <i>5 часов</i>
<b>1.2</b> Оскорбелия — <i>12 часов</i>
<b>1.3</b> Оскорбление родителей — <i>1 день</i>
<b>1.4</b> Скам — <i>от 7 дней до БАН</i>
<b>1.5</b> Спам — <i>12 часов</i>
<b>1.6</b> Осудительные вещи — <i>1 день</i>
<b>1.7</b> Флуд — <i>12 часов</i>
<b>1.8</b> Капс — <i>1 час</i>
<b>1.9</b> Реклама — <i>от 7 дней до БАН</i>
<b>1.10</b> 18+ контент — <i>1 день</i>
<b>1.11</b> Токсичность, провокация — <i>1 день</i>
<b>1.12</b> Обход наказания — <i>от 12 дней до БАН</i>
<b>1.13</b> Доксинг — <i>БАН</i>
<b>1.14</b> Попрошайничество — <i>2 часа</i>
<b>1.15</b> Обижать Дака — <i>12 часов</i>
<b>1.16</b> Обижать Ульяну — <i>от 1 дня до 2 дней</i>
<b>1.17</b> Расизм — <i>12 часов</i>

Напишите /report причина, если кто-то нарушает правила
⚠️ Лимит букв в одном сообщении — 350
Соблюдайте правила, приятного общения! 😊
""".strip()

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ─────────────────────────────────────────────
# База данных SQLite
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("moderation.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            until INTEGER,
            reason TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            until INTEGER,
            reason TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            reason TEXT,
            created_at INTEGER
        )
    """)
    conn.commit()
    conn.close()


def db_add_mute(user_id: int, username: str, until: int | None, reason: str):
    conn = sqlite3.connect("moderation.db")
    conn.execute(
        "INSERT OR REPLACE INTO mutes (user_id, username, until, reason) VALUES (?, ?, ?, ?)",
        (user_id, username, until, reason)
    )
    conn.commit()
    conn.close()


def db_remove_mute(user_id: int):
    conn = sqlite3.connect("moderation.db")
    conn.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def db_get_mutes():
    conn = sqlite3.connect("moderation.db")
    rows = conn.execute("SELECT user_id, username, until, reason FROM mutes").fetchall()
    conn.close()
    return rows


def db_add_ban(user_id: int, username: str, until: int | None, reason: str):
    conn = sqlite3.connect("moderation.db")
    conn.execute(
        "INSERT OR REPLACE INTO bans (user_id, username, until, reason) VALUES (?, ?, ?, ?)",
        (user_id, username, until, reason)
    )
    conn.commit()
    conn.close()


def db_remove_ban(user_id: int):
    conn = sqlite3.connect("moderation.db")
    conn.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def db_get_bans():
    conn = sqlite3.connect("moderation.db")
    rows = conn.execute("SELECT user_id, username, until, reason FROM bans").fetchall()
    conn.close()
    return rows


def db_add_warn(user_id: int, username: str, reason: str):
    conn = sqlite3.connect("moderation.db")
    conn.execute(
        "INSERT INTO warns (user_id, username, reason, created_at) VALUES (?, ?, ?, ?)",
        (user_id, username, reason, int(time.time()))
    )
    conn.commit()
    conn.close()


def db_get_warns(user_id: int):
    conn = sqlite3.connect("moderation.db")
    rows = conn.execute(
        "SELECT reason, created_at FROM warns WHERE user_id = ? ORDER BY created_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


def db_get_warns_with_id(user_id: int):
    conn = sqlite3.connect("moderation.db")
    rows = conn.execute(
        "SELECT id, reason, created_at FROM warns WHERE user_id = ? ORDER BY created_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


def db_remove_warn_by_id(warn_id: int):
    conn = sqlite3.connect("moderation.db")
    conn.execute("DELETE FROM warns WHERE id = ?", (warn_id,))
    conn.commit()
    conn.close()


def fmt_time_left(until: int | None) -> str:
    if until is None:
        return "навсегда"
    now = int(time.time())
    left = until - now
    if left <= 0:
        return "истёк"
    h, rem = divmod(left, 3600)
    m = rem // 60
    if h > 0:
        return f"{h}ч {m}м"
    return f"{m}м"


# ─────────────────────────────────────────────
# Проверки
# ─────────────────────────────────────────────

def is_allowed(message: Message) -> bool:
    if message.sender_chat:
        return True
    if not message.from_user:
        return False
    if message.from_user.id in ALLOWED_USERS:
        return True
    if message.from_user.username and message.from_user.username in ALLOWED_USERNAMES:
        return True
    return False


def is_private(message: Message) -> bool:
    return message.chat.type == "private"


def is_allowed_chat(message: Message) -> bool:
    return message.chat.id == ALLOWED_CHAT_ID or is_private(message)


def format_display(name: str) -> str:
    return f"@{name}" if not name.lstrip('-').isdigit() else f"id{name}"


def format_duration(seconds: int) -> str:
    if seconds >= 86400:
        return f"{seconds // 86400} д"
    if seconds >= 3600:
        return f"{seconds // 3600} ч"
    return f"{seconds // 60} м"


async def notify_user(user_id: int, text: str):
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception:
        pass


# ─────────────────────────────────────────────
# Авто-выход из чужих групп
# ─────────────────────────────────────────────

@dp.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated):
    if event.chat.id != ALLOWED_CHAT_ID and event.chat.type in ("group", "supergroup", "channel"):
        if event.new_chat_member.status in ("member", "administrator"):
            try:
                await bot.send_message(event.chat.id, "❌ Я работаю только в одной группе. До свидания!")
            except Exception:
                pass
            await bot.leave_chat(event.chat.id)


# ─────────────────────────────────────────────
# Удаление системных сообщений
# ─────────────────────────────────────────────

@dp.message(F.content_type.in_({
    ContentType.NEW_CHAT_MEMBERS,
    ContentType.LEFT_CHAT_MEMBER,
    ContentType.NEW_CHAT_TITLE,
    ContentType.NEW_CHAT_PHOTO,
    ContentType.DELETE_CHAT_PHOTO,
    ContentType.GROUP_CHAT_CREATED,
    ContentType.PINNED_MESSAGE,
}))
async def delete_service_messages(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


# ─────────────────────────────────────────────
# Антиспам + фильтр слов + лимит букв
# ─────────────────────────────────────────────

NO_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)


@dp.message(F.chat.id == ALLOWED_CHAT_ID, F.text, ~F.text.startswith("/"))
async def auto_filter(message: Message):
    if not message.from_user:
        return
    if message.from_user.id in ALLOWED_USERS:
        return
    if message.from_user.username and message.from_user.username in ALLOWED_USERNAMES:
        return

    user_id = message.from_user.id
    username = message.from_user.username or str(user_id)
    name = f"@{username}" if message.from_user.username else message.from_user.full_name
    now = time.time()

    # Запретные слова — мут 5 часов
    text_lower = message.text.lower()
    if any(re.search(r'(?<![а-яёa-z])' + re.escape(word) + r'(?![а-яёa-z])', text_lower) for word in BANNED_WORDS):
        mute_5h = 5 * 3600
        until_5h = message.date + timedelta(seconds=mute_5h)
        try:
            await message.delete()
            await bot.restrict_chat_member(chat_id=message.chat.id, user_id=user_id, permissions=NO_PERMS, until_date=until_5h)
            db_add_mute(user_id, username, int(until_5h.timestamp()), "запрещённое слово")
            await message.answer(f"🔇 <b>{name}</b> замьючен на 5 ч\n📌 Причина: запрещённое слово", parse_mode="HTML")
            await notify_user(user_id, f"🔇 Тебя замьютили на <b>5 ч</b>\n📌 Причина: использование запрещённого слова")
        except Exception:
            pass
        return

    # Лимит символов — мут 1 час
    if len(message.text) > MAX_MESSAGE_LENGTH:
        until_1h = message.date + timedelta(hours=1)
        try:
            await message.delete()
            await bot.restrict_chat_member(chat_id=message.chat.id, user_id=user_id, permissions=NO_PERMS, until_date=until_1h)
            db_add_mute(user_id, username, int(until_1h.timestamp()), f"превышен лимит {MAX_MESSAGE_LENGTH} символов")
            await message.answer(f"🔇 <b>{name}</b> замьючен на 1 ч\n📌 Причина: сообщение превышает {MAX_MESSAGE_LENGTH} символов", parse_mode="HTML")
            await notify_user(user_id, f"🔇 Тебя замьютили на <b>1 ч</b>\n📌 Причина: сообщение превышает {MAX_MESSAGE_LENGTH} символов")
        except Exception:
            pass
        return

    # Спам — мут 1 час
    spam_tracker[user_id] = [t for t in spam_tracker[user_id] if now - t < SPAM_WINDOW]
    spam_tracker[user_id].append(now)
    if len(spam_tracker[user_id]) >= SPAM_MAX_MESSAGES:
        spam_tracker[user_id].clear()
        until_1h = message.date + timedelta(hours=1)
        try:
            await message.delete()
            await bot.restrict_chat_member(chat_id=message.chat.id, user_id=user_id, permissions=NO_PERMS, until_date=until_1h)
            db_add_mute(user_id, username, int(until_1h.timestamp()), "спам")
            await message.answer(f"🔇 <b>{name}</b> замьючен на 1 ч\n📌 Причина: спам", parse_mode="HTML")
            await notify_user(user_id, f"🔇 Тебя замьютили на <b>1 ч</b>\n📌 Причина: спам")
        except Exception:
            pass


# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def parse_args(text: str):
    parts = text.strip().split(maxsplit=3)
    if len(parts) < 3:
        return None
    target = parts[0].lstrip("@")
    try:
        amount = int(parts[1])
    except ValueError:
        return None
    unit = parts[2].lower()
    if unit in ("ч", "h", "час", "часов"):
        seconds = amount * 3600
    elif unit in ("м", "m", "мин", "минут"):
        seconds = amount * 60
    elif unit in ("д", "d", "день", "дней"):
        seconds = amount * 86400
    else:
        return None
    reason = parts[3] if len(parts) > 3 else "не указана"
    return target, seconds, reason


def parse_target_only(text: str):
    return text.strip().lstrip("@") or None


async def resolve_target(chat_id: int, target: str, reply_message: Message = None):
    if reply_message:
        u = reply_message.from_user
        if u:
            return u.id, u.username or str(u.id)
    if not target:
        return None, None
    if target.lstrip("-").isdigit():
        user_id = int(target)
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            name = member.user.username or str(user_id)
            return user_id, name
        except Exception:
            return user_id, str(user_id)
    try:
        member = await bot.get_chat_member(chat_id, f"@{target}")
        return member.user.id, target
    except Exception:
        return None, target


async def parse_mute_ban_args(message: Message):
    args_text = message.text.partition(" ")[2].strip()
    if message.reply_to_message:
        parts = args_text.split(maxsplit=2)
        if len(parts) < 2:
            return None, None, None, None
        try:
            amount = int(parts[0])
        except ValueError:
            return None, None, None, None
        unit = parts[1].lower()
        if unit in ("ч", "h", "час", "часов"):
            seconds = amount * 3600
        elif unit in ("м", "m", "мин", "минут"):
            seconds = amount * 60
        elif unit in ("д", "d", "день", "дней"):
            seconds = amount * 86400
        else:
            return None, None, None, None
        reason = parts[2] if len(parts) > 2 else "не указана"
        user_id, name = await resolve_target(message.chat.id, None, message.reply_to_message)
    else:
        parsed = parse_args(args_text)
        if not parsed:
            return None, None, None, None
        target, seconds, reason = parsed
        user_id, name = await resolve_target(message.chat.id, target)
    return user_id, name, seconds, reason


# ─────────────────────────────────────────────
# Приветствие
# ─────────────────────────────────────────────

@dp.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def welcome_new_member(event: ChatMemberUpdated):
    if event.chat.id != ALLOWED_CHAT_ID:
        return
    u = event.new_chat_member.user
    name = f"@{u.username}" if u.username else u.full_name
    await bot.send_message(
        event.chat.id,
        f"👋 Привет {name}! Добро пожаловать в группу!\n"
        f"Я брат Дака, соблюдай правила, приятного общения!\n\n"
        f"/rules — чтобы посмотреть правила\n"
        f"/report причина — чтобы сделать репорт",
        parse_mode="HTML",
    )


@dp.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def farewell_member(event: ChatMemberUpdated):
    if event.chat.id != ALLOWED_CHAT_ID:
        return
    u = event.old_chat_member.user
    # Не пишем если бота кикнули или это был бан
    if u.is_bot:
        return
    name = f"@{u.username}" if u.username else u.full_name
    await bot.send_message(
        event.chat.id,
        f"😭 {name} нам очень жаль что вам не понравилось общение с нами, прощайте!",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# /-чат и /+чат — закрыть/открыть чат
# ─────────────────────────────────────────────

@dp.message(Command("-чат"))
async def cmd_close_chat(message: Message):
    global chat_locked
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    chat_locked = True
    no_send = ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )
    try:
        await bot.set_chat_permissions(message.chat.id, no_send)
        await message.reply("🔒 Чат закрыт. Писать могут только администраторы.")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


@dp.message(Command("+чат"))
async def cmd_open_chat(message: Message):
    global chat_locked
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    chat_locked = False
    full_perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
    try:
        await bot.set_chat_permissions(message.chat.id, full_perms)
        await message.reply("🔓 Чат открыт. Все участники могут писать.")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /rules
# ─────────────────────────────────────────────

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    if not is_allowed_chat(message):
        return
    await message.reply(RULES_TEXT, parse_mode="HTML")


# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    await message.reply(
        "📋 <b>Список команд:</b>\n\n"
        "📜 <b>/rules</b> — правила чата\n"
        "🚨 <b>/report</b> текст — репорт модераторам\n"
        "👻 <b>/activ</b> — анонимно в канал (личка)\n\n"
        "🔇 <b>/mute</b> @ник 30 м [причина]\n"
        "🔊 <b>/unmute</b> @ник\n"
        "🔨 <b>/ban</b> @ник 24 ч [причина]\n"
        "🔨 <b>/ban</b> @ник perm [причина] — навсегда\n"
        "✅ <b>/unban</b> @ник\n"
        "👢 <b>/kick</b> @ник [причина]\n"
        "⚠️ <b>/warn</b> @ник [причина]\n"
        "🚫 <b>/ro</b> @ник [30 м] [причина]\n"
        "🆔 <b>/id</b> — узнать ID\n\n"
        "📊 <b>/activmute</b> — кто в муте\n"
        "📊 <b>/activban</b> — кто в бане\n"
        "📊 <b>/activwarns</b> @ник — варны пользователя\n\n"
        "💡 Все команды работают через ответ на сообщение",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# /activ
# ─────────────────────────────────────────────

@dp.message(Command("activ"))
async def cmd_activ(message: Message):
    if not is_private(message):
        return await message.reply("💡 Эта команда работает только в личке с ботом.")
    if not message.from_user or message.from_user.id not in ALLOWED_USERS:
        return
    waiting_for_anon.add(message.from_user.id)
    await message.answer("👻 Режим невидимки активирован!\nОтправь сообщение, стикер или голосовое — оно уйдёт в канал анонимно.")



# ─────────────────────────────────────────────
# /report
# ─────────────────────────────────────────────

@dp.message(Command("report"))
async def cmd_report(message: Message):
    if not is_allowed_chat(message):
        return
    report_text = message.text.partition(" ")[2].strip()
    if not report_text:
        return await message.reply("⚠️ Напиши причину репорта: /report <текст>")

    u = message.from_user
    sender_name = f"@{u.username}" if u and u.username else (u.full_name if u else "Аноним")
    sender_id = u.id if u else "неизвестен"
    chat_name = message.chat.title or str(message.chat.id)

    report_msg = (
        f"🚨 <b>Новый репорт!</b>\n\n"
        f"👤 От: <b>{sender_name}</b> (ID: <code>{sender_id}</code>)\n"
        f"💬 Чат: <b>{chat_name}</b>\n"
        f"📝 Причина: {report_text}"
    )

    if message.reply_to_message and message.reply_to_message.from_user:
        ru = message.reply_to_message.from_user
        reported_name = f"@{ru.username}" if ru.username else ru.full_name
        report_msg += f"\n\n🎯 Жалоба на: <b>{reported_name}</b> (ID: <code>{ru.id}</code>)"

    sent = False
    for mod_id in REPORT_RECEIVERS:
        try:
            await bot.send_message(mod_id, report_msg, parse_mode="HTML")
            if message.reply_to_message:
                await bot.forward_message(chat_id=mod_id, from_chat_id=message.chat.id, message_id=message.reply_to_message.message_id)
            sent = True
        except Exception:
            pass

    await message.reply("✅ Репорт отправлен модераторам!" if sent else "❌ Не удалось отправить репорт.")


# ─────────────────────────────────────────────
# /id
# ─────────────────────────────────────────────

@dp.message(Command("id"))
async def cmd_id(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        name = f"@{u.username}" if u.username else u.full_name
        await message.reply(f"👤 {name}\n🆔 ID: <code>{u.id}</code>", parse_mode="HTML")
    elif message.from_user:
        u = message.from_user
        name = f"@{u.username}" if u.username else u.full_name
        await message.reply(f"👤 Твой ID:\n🆔 <code>{u.id}</code>", parse_mode="HTML")


# ─────────────────────────────────────────────
# /mute
# ─────────────────────────────────────────────

@dp.message(Command("mute"))
async def cmd_mute(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    user_id, name, seconds, reason = await parse_mute_ban_args(message)
    if seconds is None:
        return await message.reply(
            "⚠️ Использование:\n"
            "• /mute @ник 30 м причина\n"
            "• /mute 123456789 30 м причина\n"
            "• Ответить на сообщение: /mute 30 м причина"
        )
    if not user_id:
        return await message.reply("❌ Пользователь не найден.")
    until = message.date + timedelta(seconds=seconds)
    try:
        await bot.restrict_chat_member(chat_id=message.chat.id, user_id=user_id, permissions=NO_PERMS, until_date=until)
        db_add_mute(user_id, name, int(until.timestamp()), reason)
        duration_text = format_duration(seconds)
        await message.reply(f"🔇 <b>{format_display(name)}</b> замьючен на <b>{duration_text}</b>\n📌 Причина: {reason}", parse_mode="HTML")
        chat_name = message.chat.title or str(message.chat.id)
        await notify_user(user_id, f"🔇 Тебя замьютили в чате <b>{chat_name}</b> на <b>{duration_text}</b>\n📌 Причина: {reason}")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /ban + /ban perm
# ─────────────────────────────────────────────

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return

    args_text = message.text.partition(" ")[2].strip()

    # Проверяем perm бан
    # Форматы: /ban @ник perm [причина] или reply + /ban perm [причина]
    perm = False
    user_id = None
    name = None
    reason = "не указана"

    if message.reply_to_message:
        parts = args_text.split(maxsplit=1)
        if parts and parts[0].lower() == "perm":
            perm = True
            reason = parts[1] if len(parts) > 1 else "не указана"
            user_id, name = await resolve_target(message.chat.id, None, message.reply_to_message)
        else:
            # обычный бан через reply — парсим время
            user_id, name, seconds, reason = await parse_mute_ban_args(message)
            if seconds is None:
                return await message.reply("⚠️ Укажи время: /ban 24 ч причина\nили /ban perm причина")
    else:
        parts = args_text.split(maxsplit=2)
        if len(parts) >= 2 and parts[1].lower() == "perm":
            perm = True
            target = parts[0].lstrip("@")
            reason = parts[2] if len(parts) > 2 else "не указана"
            user_id, name = await resolve_target(message.chat.id, target)
        else:
            user_id, name, seconds, reason = await parse_mute_ban_args(message)
            if seconds is None:
                return await message.reply(
                    "⚠️ Использование:\n"
                    "• /ban @ник 24 ч причина\n"
                    "• /ban @ник perm причина — навсегда\n"
                    "• Ответить на сообщение: /ban 24 ч причина\n"
                    "• Ответить на сообщение: /ban perm причина"
                )

    if not user_id:
        return await message.reply("❌ Пользователь не найден.")

    try:
        chat_name = message.chat.title or str(message.chat.id)
        if perm:
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id)
            db_add_ban(user_id, name, None, reason)
            await message.reply(f"🔨 <b>{format_display(name)}</b> забанен <b>навсегда</b>\n📌 Причина: {reason}", parse_mode="HTML")
            await notify_user(user_id, f"🔨 Тебя забанили в чате <b>{chat_name}</b> <b>навсегда</b>\n📌 Причина: {reason}")
        else:
            until = message.date + timedelta(seconds=seconds)
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id, until_date=until)
            db_add_ban(user_id, name, int(until.timestamp()), reason)
            duration_text = format_duration(seconds)
            await message.reply(f"🔨 <b>{format_display(name)}</b> забанен на <b>{duration_text}</b>\n📌 Причина: {reason}", parse_mode="HTML")
            await notify_user(user_id, f"🔨 Тебя забанили в чате <b>{chat_name}</b> на <b>{duration_text}</b>\n📌 Причина: {reason}")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /unmute
# ─────────────────────────────────────────────

@dp.message(Command("unmute"))
async def cmd_unmute(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    args_text = message.text.partition(" ")[2].strip()
    target = parse_target_only(args_text)
    user_id, name = await resolve_target(message.chat.id, target, message.reply_to_message)
    if not user_id:
        return await message.reply("❌ Пользователь не найден.")
    full_perms = ChatPermissions(
        can_send_messages=True, can_send_media_messages=True,
        can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True,
    )
    try:
        await bot.restrict_chat_member(chat_id=message.chat.id, user_id=user_id, permissions=full_perms)
        db_remove_mute(user_id)
        await message.reply(f"🔊 <b>{format_display(name)}</b> размьючен.", parse_mode="HTML")
        chat_name = message.chat.title or str(message.chat.id)
        await notify_user(user_id, f"🔊 Тебя размьютили в чате <b>{chat_name}</b>!")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /unban
# ─────────────────────────────────────────────

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    args_text = message.text.partition(" ")[2].strip()
    target = parse_target_only(args_text)
    user_id, name = await resolve_target(message.chat.id, target, message.reply_to_message)
    if not user_id:
        return await message.reply("❌ Пользователь не найден.")
    try:
        await bot.unban_chat_member(chat_id=message.chat.id, user_id=user_id, only_if_banned=True)
        db_remove_ban(user_id)
        await message.reply(f"✅ <b>{format_display(name)}</b> разбанен.", parse_mode="HTML")
        chat_name = message.chat.title or str(message.chat.id)
        await notify_user(user_id, f"✅ Тебя разбанили в чате <b>{chat_name}</b>!")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /kick
# ─────────────────────────────────────────────

@dp.message(Command("kick"))
async def cmd_kick(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    args_text = message.text.partition(" ")[2].strip()
    if message.reply_to_message:
        user_id, name = await resolve_target(message.chat.id, None, message.reply_to_message)
        reason = args_text or "не указана"
    else:
        parts = args_text.split(maxsplit=1)
        if not parts:
            return await message.reply("⚠️ Использование: /kick @ник [причина]")
        target = parts[0].lstrip("@")
        reason = parts[1] if len(parts) > 1 else "не указана"
        user_id, name = await resolve_target(message.chat.id, target)
    if not user_id:
        return await message.reply("❌ Пользователь не найден.")
    try:
        chat_name = message.chat.title or str(message.chat.id)
        await notify_user(user_id, f"👢 Тебя кикнули из чата <b>{chat_name}</b>\n📌 Причина: {reason}")
        await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_id)
        await bot.unban_chat_member(chat_id=message.chat.id, user_id=user_id, only_if_banned=True)
        await message.reply(f"👢 <b>{format_display(name)}</b> кикнут.\n📌 Причина: {reason}", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /warn
# ─────────────────────────────────────────────

@dp.message(Command("warn"))
async def cmd_warn(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    args_text = message.text.partition(" ")[2].strip()
    if message.reply_to_message:
        u = message.reply_to_message.from_user
        if not u:
            return await message.reply("❌ Не удалось получить данные пользователя.")
        user_id = u.id
        name = u.username or str(u.id)
        reason = args_text or "не указана"
    else:
        parts = args_text.split(maxsplit=1)
        if not parts:
            return await message.reply("⚠️ Использование: /warn @ник [причина]")
        target = parts[0].lstrip("@")
        reason = parts[1] if len(parts) > 1 else "не указана"
        user_id, name = await resolve_target(message.chat.id, target)
    if not user_id:
        return await message.reply("❌ Пользователь не найден.")
    db_add_warn(user_id, name, reason)
    warns = db_get_warns(user_id)
    await message.reply(
        f"⚠️ <b>{format_display(name)}</b>, ты получил предупреждение! (всего: {len(warns)})\n📌 Причина: {reason}",
        parse_mode="HTML",
    )
    chat_name = message.chat.title or str(message.chat.id)
    await notify_user(user_id, f"⚠️ Ты получил предупреждение в чате <b>{chat_name}</b>\n📌 Причина: {reason}\nВсего варнов: {len(warns)}")


# ─────────────────────────────────────────────
# /ro
# ─────────────────────────────────────────────

@dp.message(Command("ro"))
async def cmd_ro(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return
    user_id, name, seconds, reason = await parse_mute_ban_args(message)
    if seconds is None:
        args_text = message.text.partition(" ")[2].strip()
        if message.reply_to_message:
            user_id, name = await resolve_target(message.chat.id, None, message.reply_to_message)
            reason = args_text or "не указана"
            seconds = 0
        else:
            parts = args_text.split(maxsplit=1)
            if not parts:
                return await message.reply("⚠️ Использование: /ro @ник [время] [причина]")
            target = parts[0].lstrip("@")
            reason = parts[1] if len(parts) > 1 else "не указана"
            user_id, name = await resolve_target(message.chat.id, target)
            seconds = 0
    if not user_id:
        return await message.reply("❌ Пользователь не найден.")
    kwargs = dict(chat_id=message.chat.id, user_id=user_id, permissions=NO_PERMS)
    if seconds:
        kwargs["until_date"] = message.date + timedelta(seconds=seconds)
    try:
        await bot.restrict_chat_member(**kwargs)
        duration_text = f"на {format_duration(seconds)}" if seconds else "навсегда"
        await message.reply(f"🚫 <b>{format_display(name)}</b> переведён в режим чтения {duration_text}\n📌 Причина: {reason}", parse_mode="HTML")
        chat_name = message.chat.title or str(message.chat.id)
        await notify_user(user_id, f"🚫 Тебя перевели в режим чтения в чате <b>{chat_name}</b> {duration_text}\n📌 Причина: {reason}")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


# ─────────────────────────────────────────────
# /activmute
# ─────────────────────────────────────────────

@dp.message(Command("activmute"))
async def cmd_activmute(message: Message):
    if not is_allowed(message):
        return
    rows = db_get_mutes()
    now = int(time.time())
    active = [(uid, uname, until, reason) for uid, uname, until, reason in rows if until is None or until > now]
    if not active:
        return await message.reply("✅ Нет замьюченных пользователей.")
    text = f"🔇 <b>Замьюченные ({len(active)}):</b>\n\n"
    for uid, uname, until, reason in active:
        display = f"@{uname}" if uname and not uname.lstrip('-').isdigit() else f"id{uid}"
        left = fmt_time_left(until)
        text += f"• {display} — осталось: <b>{left}</b>\n  📌 {reason}\n"
    await message.reply(text, parse_mode="HTML")


# ─────────────────────────────────────────────
# /activban
# ─────────────────────────────────────────────

@dp.message(Command("activban"))
async def cmd_activban(message: Message):
    if not is_allowed(message):
        return
    rows = db_get_bans()
    now = int(time.time())
    active = [(uid, uname, until, reason) for uid, uname, until, reason in rows if until is None or until > now]
    if not active:
        return await message.reply("✅ Нет забаненных пользователей.")
    text = f"🔨 <b>Забаненные ({len(active)}):</b>\n\n"
    for uid, uname, until, reason in active:
        display = f"@{uname}" if uname and not uname.lstrip('-').isdigit() else f"id{uid}"
        left = fmt_time_left(until)
        text += f"• {display} — осталось: <b>{left}</b>\n  📌 {reason}\n"
    await message.reply(text, parse_mode="HTML")


# ─────────────────────────────────────────────
# /activwarns
# ─────────────────────────────────────────────

@dp.message(Command("activwarns"))
async def cmd_activwarns(message: Message):
    if not is_allowed(message):
        return
    args_text = message.text.partition(" ")[2].strip()
    target = parse_target_only(args_text)
    chat_id = message.chat.id if not is_private(message) else ALLOWED_CHAT_ID
    user_id, name = await resolve_target(chat_id, target, message.reply_to_message)
    if not user_id:
        if target and target.lstrip("-").isdigit():
            user_id = int(target)
            name = str(user_id)
        else:
            return await message.reply("❌ Укажи пользователя: /activwarns @ник или ID")
    warns = db_get_warns_with_id(user_id)
    if not warns:
        return await message.reply(f"✅ У {format_display(name)} нет варнов.")
    text = f"⚠️ <b>Варны {format_display(name)} ({len(warns)}):</b>\n\n"
    for i, (wid, reason, created_at) in enumerate(warns, 1):
        dt = datetime.fromtimestamp(created_at).strftime("%d.%m.%Y %H:%M")
        text += f"{i}. {reason} — <i>{dt}</i>\n"
    text += f"\n💡 Снять варн: /unwarn <номер> @ник"
    await message.reply(text, parse_mode="HTML")


# ─────────────────────────────────────────────
# /unwarn
# ─────────────────────────────────────────────

@dp.message(Command("unwarn"))
async def cmd_unwarn(message: Message):
    if not is_allowed_chat(message):
        return
    if not is_allowed(message):
        return

    args_text = message.text.partition(" ")[2].strip()
    parts = args_text.split(maxsplit=1)

    if len(parts) < 2:
        return await message.reply(
            "⚠️ Использование: /unwarn <номер> @ник\n"
            "Пример: /unwarn 2 @user\n"
            "Номера варнов смотри в /activwarns @ник"
        )

    try:
        warn_num = int(parts[0])
    except ValueError:
        return await message.reply("❌ Укажи номер варна числом. Пример: /unwarn 2 @user")

    target = parts[1].lstrip("@")
    chat_id = message.chat.id if not is_private(message) else ALLOWED_CHAT_ID
    user_id, name = await resolve_target(chat_id, target)
    if not user_id:
        if target.lstrip("-").isdigit():
            user_id = int(target)
            name = str(user_id)
        else:
            return await message.reply("❌ Пользователь не найден.")

    warns = db_get_warns_with_id(user_id)
    if not warns:
        return await message.reply(f"✅ У {format_display(name)} нет варнов.")

    if warn_num < 1 or warn_num > len(warns):
        return await message.reply(f"❌ Варн №{warn_num} не существует. У пользователя {len(warns)} варн(ов).")

    warn_id, reason, created_at = warns[warn_num - 1]
    db_remove_warn_by_id(warn_id)

    remaining = len(warns) - 1
    await message.reply(
        f"✅ Варн №{warn_num} снят у {format_display(name)}\n"
        f"📌 Был за: {reason}\n"
        f"Осталось варнов: {remaining}",
        parse_mode="HTML",
    )
    await notify_user(user_id, f"✅ С тебя сняли варн №{warn_num}\n📌 Был за: {reason}\nОсталось варнов: {remaining}")




# ─────────────────────────────────────────────
# Личка — анонимные сообщения (должен быть последним!)
# ─────────────────────────────────────────────

@dp.message(F.chat.type == "private")
async def handle_anon_message(message: Message):
    if not message.from_user:
        return
    if message.from_user.id not in waiting_for_anon:
        return
    if message.text and message.text.startswith("/"):
        return
    waiting_for_anon.discard(message.from_user.id)
    try:
        await bot.copy_message(chat_id=ANON_CHANNEL_ID, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.answer("✅ Сообщение анонимно отправлено в канал!")
    except Exception as e:
        await message.answer(f"❌ Ошибка при отправке: {e}")


# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────

async def check_expired():
    """Каждую минуту проверяет истёкшие муты и баны и уведомляет пользователей."""
    while True:
        await asyncio.sleep(60)
        now = int(time.time())

        # Проверяем муты
        mutes = db_get_mutes()
        for uid, uname, until, reason in mutes:
            if until is not None and until <= now:
                db_remove_mute(uid)
                name = f"@{uname}" if uname and not uname.lstrip("-").isdigit() else f"пользователь"
                await notify_user(uid, f"🔊 {name}, вы теперь можете свободно общаться, но лучше следите за языком!")

        # Проверяем баны
        bans = db_get_bans()
        for uid, uname, until, reason in bans:
            if until is not None and until <= now:
                db_remove_ban(uid)
                name = f"@{uname}" if uname and not uname.lstrip("-").isdigit() else f"пользователь"
                await notify_user(uid, f"✅ {name}, вы теперь можете свободно общаться, но лучше следите за языком!")


async def main():
    init_db()
    asyncio.create_task(check_expired())
    await dp.start_polling(bot, allowed_updates=["message", "chat_member", "my_chat_member"])

if __name__ == "__main__":
    asyncio.run(main())
