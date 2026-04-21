import asyncio
import logging
import re
import sqlite3
import time
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import RetryAfter
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================

BOT_TOKEN = "8736334059:AAFkOqb5Bl5phPwqkGrUADUq2_Mdet2QV70"

BOT_NAME = "സമാദാനം"
BOT_USERNAME = "samadanambot"

GROUP_ID = -1003636238775
GROUP_LINK = "https://t.me/+A93ERrKixbw5MTNk"

POST_HEADER = "💬 Love Chat ❤️\n🫥 Anonymous via Samadanam\n\n"

ADMIN_IDS = {8438801421}

MIN_SEND_INTERVAL = 1.8
GROUP_REMINDER_COOLDOWN = 3600
ALLOW_ADMIN_LINKS = False

DB_PATH = "samadanam_bot.db"

LINK_REGEX = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+|"
    r"\b[a-zA-Z0-9-]+\.(com|net|org|io|me|in|co|app|ai|gg|ly|to|tv|info|biz|xyz|site|online|store|shop|cc|pk|uk|us|de|ru)\b)",
    re.IGNORECASE,
)

BANNED_TERMS = [
    "child porn", "childporn", "child porno",
    "child abuse material", "underage sex", "minor sex",
    "child nudes", "kid nudes",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

SEND_LOCK = asyncio.Lock()
LAST_SEND_TIME = 0.0


# ================== DATABASE ==================

def init_db():
    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                referrer_id INTEGER,
                joined_group INTEGER DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                last_group_reminder_ts INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER NOT NULL,
                referred_user_id INTEGER NOT NULL UNIQUE,
                credited_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def ensure_user(user):
    with db:
        db.execute("""
            INSERT INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
        ))


def get_user_row(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()


def set_referrer_if_empty(user_id, referrer_id):
    if user_id == referrer_id:
        return
    row = get_user_row(user_id)
    if not row or row["referrer_id"]:
        return
    with db:
        db.execute(
            "UPDATE users SET referrer_id = ? WHERE user_id = ? AND referrer_id IS NULL",
            (referrer_id, user_id)
        )


def set_join_status(user_id, joined):
    with db:
        db.execute("UPDATE users SET joined_group = ? WHERE user_id = ?",
                   (1 if joined else 0, user_id))


def set_group_reminder_ts(user_id, ts):
    with db:
        db.execute("UPDATE users SET last_group_reminder_ts = ? WHERE user_id = ?",
                   (ts, user_id))


def get_referral_count(user_id):
    row = get_user_row(user_id)
    return int(row["referrals_count"]) if row else 0


def can_share_links(user_id):
    if user_id in ADMIN_IDS and ALLOW_ADMIN_LINKS:
        return True
    return False


def credit_referral_if_eligible(referred_user_id):
    row = get_user_row(referred_user_id)
    if not row:
        return
    referrer_id = row["referrer_id"]
    joined_group = row["joined_group"]
    if not referrer_id or not joined_group:
        return
    existing = db.execute(
        "SELECT 1 FROM referrals WHERE referred_user_id = ?",
        (referred_user_id,)
    ).fetchone()
    if existing:
        return
    with db:
        db.execute("INSERT INTO referrals (referrer_id, referred_user_id) VALUES (?, ?)",
                   (referrer_id, referred_user_id))
        db.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?",
                   (referrer_id,))


def get_referral_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


# ================== HELPERS ==================

def get_text_or_caption(message):
    return (message.text or message.caption or "").strip()


def contains_banned_terms(text):
    t = (text or "").lower()
    return any(term in t for term in BANNED_TERMS)


def message_has_link(message):
    if not message:
        return False
    for entity_list in [message.entities or [], message.caption_entities or []]:
        for entity in entity_list:
            if entity.type in ("url", "text_link"):
                return True
    content = get_text_or_caption(message)
    return bool(LINK_REGEX.search(content))


async def is_user_in_group(context, user_id):
    try:
        member = await context.bot.get_chat_member(GROUP_ID, user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


async def refresh_group_status(context, user_id):
    joined = await is_user_in_group(context, user_id)
    set_join_status(user_id, joined)
    if joined:
        credit_referral_if_eligible(user_id)
    return joined


async def delete_later(message, delay=20):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def start_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Join Love Chat Group", url=GROUP_LINK)],
        [InlineKeyboardButton("📨 Invite Friends", url=get_referral_link(user_id))]
    ])


# ================== POSTING ==================

async def post_to_group(context, post_type, file_id=None, text=None, caption=None):
    global LAST_SEND_TIME

    async with SEND_LOCK:
        wait_gap = MIN_SEND_INTERVAL - (time.monotonic() - LAST_SEND_TIME)
        if wait_gap > 0:
            await asyncio.sleep(wait_gap)

        while True:
            try:
                if post_type == "text":
                    await context.bot.send_message(
                        chat_id=GROUP_ID,
                        text=POST_HEADER + (text or "")
                    )
                elif post_type == "photo":
                    await context.bot.send_photo(
                        chat_id=GROUP_ID,
                        photo=file_id,
                        caption=(POST_HEADER + (caption or "")).strip()
                    )
                elif post_type == "video":
                    await context.bot.send_video(
                        chat_id=GROUP_ID,
                        video=file_id,
                        caption=(POST_HEADER + (caption or "")).strip()
                    )
                elif post_type == "voice":
                    await context.bot.send_voice(
                        chat_id=GROUP_ID,
                        voice=file_id,
                        caption="💬 Love Chat ❤️\n🫥 Anonymous via Samadanam"
                    )
                elif post_type == "document":
                    await context.bot.send_document(
                        chat_id=GROUP_ID,
                        document=file_id,
                        caption=(POST_HEADER + (caption or "")).strip()
                    )
                LAST_SEND_TIME = time.monotonic()
                return True
            except RetryAfter as e:
                retry_after = getattr(e, "retry_after", 5)
                if hasattr(retry_after, "total_seconds"):
                    retry_after = retry_after.total_seconds()
                retry_after = int(retry_after) + 1
                logger.warning(f"Flood control. Waiting {retry_after}s")
                await asyncio.sleep(retry_after)
            except Exception as e:
                logger.error(f"Failed to post to group: {e}")
                return False


# ================== COMMANDS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    ensure_user(user)

    if context.args:
        arg = context.args[0].strip()
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg.split("_", 1)[1])
                set_referrer_if_empty(user.id, referrer_id)
            except Exception:
                pass

    joined = await refresh_group_status(context, user.id)
    join_line = "✅ You are already in Love Chat." if joined else "❤️ Join Love Chat to see reactions and chat with members."

    welcome_text = (
        "സമാദാനത്തിലേക്ക് സ്വാഗതം.\n"
        "Girls, secrets and fantasies anonymous ആയി ഇവിടെ share ചെയ്യാം.\n"
        "🔒 നിങ്ങളുടെ identity ആരും അറിയില്ല.\n\n"
        f"{join_line}\n"
        "✅ Auto-approved anonymous posting\n"
        "🚫 Links are not allowed in the bot or group\n"
        "📩 If you post media directly in the group, your name will be visible"
    )

    await update.message.reply_text(welcome_text, reply_markup=start_keyboard(user.id))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    text = (
        "How Samadanam works:\n\n"
        "1. Send text, photos, videos, voice or files here in DM\n"
        "2. The bot auto-posts them anonymously in Love Chat ❤️\n"
        "3. No links are allowed in DM or in the group\n"
        "4. If you post photos/videos directly in the group, the bot reminds you to use the bot for anonymity"
    )
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin only.")
        return

    total_users = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    joined_users = db.execute("SELECT COUNT(*) AS c FROM users WHERE joined_group = 1").fetchone()["c"]
    total_refs = db.execute("SELECT COUNT(*) AS c FROM referrals").fetchone()["c"]

    await update.message.reply_text(
        f"📊 {BOT_NAME} Stats\n\n"
        f"👥 Users: {total_users}\n"
        f"❤️ Joined group: {joined_users}\n"
        f"🔗 Verified referrals: {total_refs}\n"
        f"🤖 Bot: https://t.me/{BOT_USERNAME}\n"
        f"💬 Group: {GROUP_LINK}"
    )


# ================== SUBMISSIONS (DM) ==================

async def submit_private(update, context, post_type):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    message = update.message
    if not user or not message:
        return

    ensure_user(user)
    joined = await refresh_group_status(context, user.id)

    if message_has_link(message) and not can_share_links(user.id):
        await message.reply_text("🚫 Links are not allowed here, including forwarded links.")
        return

    if contains_banned_terms(get_text_or_caption(message)):
        await message.reply_text("🚫 This content is not allowed.")
        return

    file_id = None
    text = None
    caption = None

    if post_type == "text":
        text = message.text or ""
    elif post_type == "photo":
        file_id = message.photo[-1].file_id
        caption = message.caption or ""
    elif post_type == "video":
        file_id = message.video.file_id
        caption = message.caption or ""
    elif post_type == "voice":
        file_id = message.voice.file_id
    elif post_type == "document":
        file_id = message.document.file_id
        caption = message.caption or ""

    await message.reply_text("✅ Received. Posting anonymously now...")

    success = await post_to_group(
        context=context,
        post_type=post_type,
        file_id=file_id,
        text=text,
        caption=caption
    )

    if success:
        if joined:
            await context.bot.send_message(chat_id=user.id, text="✅ Posted anonymously in Love Chat ❤️")
        else:
            await context.bot.send_message(
                chat_id=user.id,
                text="✅ Posted anonymously in Love Chat ❤️\n❤️ Join the group to see reactions and chat with members.",
                reply_markup=start_keyboard(user.id)
            )
    else:
        await context.bot.send_message(chat_id=user.id, text="❌ Could not post right now. Please try again later.")


async def handle_text(update, context): await submit_private(update, context, "text")
async def handle_photo(update, context): await submit_private(update, context, "photo")
async def handle_video(update, context): await submit_private(update, context, "video")
async def handle_voice(update, context): await submit_private(update, context, "voice")
async def handle_document(update, context): await submit_private(update, context, "document")


# ================== GROUP MONITOR ==================

async def handle_group_chat(update, context):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if not message or not chat or not user or user.is_bot:
        return

    ensure_user(user)
    await refresh_group_status(context, user.id)

    if message_has_link(message) and not can_share_links(user.id):
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"delete link failed: {e}")
        try:
            warn = await context.bot.send_message(chat_id=chat.id, text="🚫 Links are not allowed in Love Chat.")
            context.application.create_task(delete_later(warn, 12))
        except Exception:
            pass
        return

    if contains_banned_terms(get_text_or_caption(message)):
        try:
            await message.delete()
        except Exception:
            pass
        try:
            warn = await context.bot.send_message(chat_id=chat.id, text="🚫 This content is not allowed.")
            context.application.create_task(delete_later(warn, 12))
        except Exception:
            pass
        return

    is_media = bool(message.photo) or bool(message.video) or bool(message.document)
    if is_media:
        row = get_user_row(user.id)
        now_ts = int(time.time())
        last_ts = int(row["last_group_reminder_ts"]) if row else 0
        if now_ts - last_ts >= GROUP_REMINDER_COOLDOWN:
            set_group_reminder_ts(user.id, now_ts)
            try:
                reminder = await message.reply_text(
                    f"📩 Want this anonymous?\nSend it to @{BOT_USERNAME} instead.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Send via Samadanam", url=f"https://t.me/{BOT_USERNAME}")]
                    ])
                )
                context.application.create_task(delete_later(reminder, 25))
            except Exception as e:
                logger.warning(f"Reminder failed: {e}")


# ================== ERROR HANDLER ==================

async def error_handler(update, context):
    logger.error("Exception while handling update:", exc_info=context.error)


# ================== MAIN ==================

def main():
    init_db()

    print("=" * 70)
    print(f"🤖 {BOT_NAME} starting as @{BOT_USERNAME}")
    print("=" * 70)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(MessageHandler(filters.ChatType.GROUPS, handle_group_chat), group=0)

    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.VIDEO, handle_video), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.VOICE, handle_voice), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL, handle_document), group=1)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text), group=1)

    app.add_error_handler(error_handler)

    logger.info("🚀 Bot polling started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
