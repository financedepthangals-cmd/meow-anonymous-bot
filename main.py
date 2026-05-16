import os
import re
import time
import random
import sqlite3
import asyncio
import logging
from datetime import datetime

from telegram import (
    Update,
    ChatPermissions,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8736334059:AAG7dbGizKu33RwnnNd8Ejrzg7U08FZNGGI")
BOT_NAME = "സമാദാനം"
BOT_USERNAME = "samadanambot"

GROUP_ID = -1003636238775
GROUP_LINK = "https://t.me/+A93ERrKixbw5MTNk"

ADMIN_IDS = {8438801421}
ADMIN_LOG_CHAT_ID = 8438801421

# These users are silently ignored completely
BLOCKED_USERS = {7019834630, 8701708494}

# Bot rules
ALLOWED_BOTS = {BOT_USERNAME.lower()}
POST_HEADER = "💬 Love Chat ❤️\n🫥 Anonymous via Samadanam\n\n"

# Submission / queue
USER_SUBMIT_LIMIT = 0
SUBMISSION_QUEUE = asyncio.Queue()
QUEUE_RETRY_LIMIT = 8
QUEUE_RETRY_DELAY = 3

# Autopilot
AUTO_PILOT_ENABLED = True
AUTOPOST_MIN_IDLE = 35 * 60
AUTOPOST_MAX_IDLE = 75 * 60
AUTOPOST_MIN_GAP = 25 * 60
AUTOPOST_MAX_GAP = 90 * 60
RECYCLE_MIN_GAP = 2 * 3600
RECYCLE_MAX_GAP = 4 * 3600
RECYCLE_COOLDOWN_DAYS = 7
BATTLE_MIN_GAP = 90 * 60
BATTLE_PHOTO_COOLDOWN_DAYS = 14
BATTLE_DAILY_MIN = 2
BATTLE_DAILY_MAX = 4
INVITE_REMINDER_CHANCE = 0.33

# Group nudges
DIRECT_NUDGE_COOLDOWN = 30 * 60

# Rate limiting
MIN_SEND_INTERVAL = 1.2

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("samadanam")

DB_PATH = "samadanam_bot.db"

# =========================================================
# PATTERNS / FILTERS
# =========================================================

PHONE_PATTERN = re.compile(
    r'(\+?\d{1,3}[\s\-]?)?\(?\d{3,5}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5}'
)

EMAIL_PATTERN = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
UPI_PATTERN = re.compile(
    r'\b[\w\.-]+@(paytm|ybl|axl|okaxis|oksbi|okhdfcbank|okicici|ibl|upi|hdfcbank|sbi|axisbank|icici)\b',
    re.IGNORECASE
)
A_LINK_PATTERN = re.compile(r'(https?://|www\.|t\.me/|telegram\.me/)', re.IGNORECASE)
BOT_MENTION_PATTERN = re.compile(r'@([A-Za-z0-9_]+bot)\b', re.IGNORECASE)

SPAM_KEYWORDS = [
    "onlyfans", "free video", "watch now", "click here", "100% free",
    "bit.ly", "cutt.ly", "tinyurl", "telegram.me/+", "t.me/+",
    "join my group", "join our channel", "promo", "promotion", "dm for paid"
]

BANNED_TERMS = [
    "child", "minor", "underage", "school girl", "kid",
    "rape", "force", "scam", "fraud"
]

PERSONAL_INFO_TERMS = [
    "my number", "call me", "whatsapp me", "dm me",
    "insta id", "instagram id", "snap id", "snapchat id",
    "give number", "share number", "your number"
]

# =========================================================
# CONTENT POOLS
# =========================================================

ENGAGEMENT_TEXTS = [
    "🫥 One line is enough... say what you couldn't say outside.",
    "👀 Silent readers... today's your turn.",
    "💭 Drop one thought anonymously.",
    "🌙 Night mood check... what's on your mind?",
    "🫦 Confession time. Keep it anonymous.",
    "💌 Say the message you never sent.",
]

LATE_NIGHT_TEXTS = [
    "🌙 Late night confessions hit different.",
    "🖤 Someone is definitely thinking about someone right now...",
    "👀 Midnight energy is always dangerous here.",
    "💭 One honest line can change the whole vibe.",
]

RECYCLE_FOOTERS = [
    "\n\n🫥 Anonymous via @samadanambot",
    "\n\n💌 Share yours → @samadanambot",
    "\n\n👀 More anonymous drops at @samadanambot",
]

MEDIA_REACTIONS = [
    "🔥 This drop has energy.",
    "👀 Can't scroll past this one.",
    "🖤 Dangerous vibe.",
    "💭 Someone definitely has a story behind this.",
    "✨ Main character moment.",
]

QUEEN_BATTLE_INTROS = [
    "👑 Queen Battle time. Pick your side.",
    "⚡ Battle drop. Vote your queen.",
    "🔥 Tonight's Queen Battle is live.",
]

# =========================================================
# GLOBAL STATE
# =========================================================

LAST_GROUP_ACTIVITY_TS = time.time()
LAST_AUTOPILOT_POST_TS = 0
LAST_RECYCLE_TS = 0
LAST_BATTLE_TS = 0

NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
NEXT_GAP_TARGET = random.randint(AUTOPOST_MIN_GAP, AUTOPOST_MAX_GAP)
NEXT_RECYCLE_GAP = random.randint(RECYCLE_MIN_GAP, RECYCLE_MAX_GAP)

BATTLE_DAY = datetime.utcnow().date()
BATTLES_TODAY = 0
BATTLES_TODAY_TARGET = random.randint(BATTLE_DAILY_MIN, BATTLE_DAILY_MAX)

LAST_NUDGE_BY_USER = {}
LAST_SEND_TS = 0

# =========================================================
# DB
# =========================================================

def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            joined_at REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS archive(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            media_type TEXT,
            caption TEXT,
            ts REAL,
            last_recycled REAL DEFAULT 0,
            battle_used REAL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS spammer_strikes(
            user_id INTEGER PRIMARY KEY,
            strikes INTEGER DEFAULT 0,
            last_strike REAL
        )
    """)

    conn.commit()
    conn.close()

def register_user(user, referred_by=None):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    exists = c.fetchone()

    if not exists:
        c.execute("""
            INSERT INTO users(user_id, username, first_name, referred_by, referral_count, joined_at)
            VALUES(?, ?, ?, ?, 0, ?)
        """, (
            user.id,
            user.username,
            user.first_name,
            referred_by,
            time.time()
        ))

        if referred_by and referred_by != user.id:
            c.execute("""
                UPDATE users
                SET referral_count = referral_count + 1
                WHERE user_id=?
            """, (referred_by,))
    else:
        c.execute("""
            UPDATE users
            SET username=?, first_name=?
            WHERE user_id=?
        """, (user.username, user.first_name, user.id))

    conn.commit()
    conn.close()

def add_archive(file_id, media_type, caption):
    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO archive(file_id, media_type, caption, ts, last_recycled, battle_used)
        VALUES(?, ?, ?, ?, 0, 0)
    """, (file_id, media_type, caption or "", time.time()))
    conn.commit()
    conn.close()

def get_referral_count(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT referral_count FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_user_count():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    n = c.fetchone()[0]
    conn.close()
    return n

def get_archive_count():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM archive")
    n = c.fetchone()[0]
    conn.close()
    return n

def add_strike(user_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT strikes FROM spammer_strikes WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row:
        strikes = row[0] + 1
        c.execute("""
            UPDATE spammer_strikes
            SET strikes=?, last_strike=?
            WHERE user_id=?
        """, (strikes, time.time(), user_id))
    else:
        strikes = 1
        c.execute("""
            INSERT INTO spammer_strikes(user_id, strikes, last_strike)
            VALUES(?, 1, ?)
        """, (user_id, time.time()))
    conn.commit()
    conn.close()
    return strikes

# =========================================================
# HELPERS
# =========================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def mark_group_activity():
    global LAST_GROUP_ACTIVITY_TS
    LAST_GROUP_ACTIVITY_TS = time.time()

def reset_idle_targets():
    global NEXT_IDLE_TARGET, NEXT_GAP_TARGET
    NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
    NEXT_GAP_TARGET = random.randint(AUTOPOST_MIN_GAP, AUTOPOST_MAX_GAP)

def reset_recycle_gap():
    global NEXT_RECYCLE_GAP
    NEXT_RECYCLE_GAP = random.randint(RECYCLE_MIN_GAP, RECYCLE_MAX_GAP)

def maybe_reset_battle_day():
    global BATTLE_DAY, BATTLES_TODAY, BATTLES_TODAY_TARGET
    today = datetime.utcnow().date()
    if today != BATTLE_DAY:
        BATTLE_DAY = today
        BATTLES_TODAY = 0
        BATTLES_TODAY_TARGET = random.randint(BATTLE_DAILY_MIN, BATTLE_DAILY_MAX)

async def throttle_send():
    global LAST_SEND_TS
    now = time.time()
    delta = now - LAST_SEND_TS
    if delta < MIN_SEND_INTERVAL:
        await asyncio.sleep(MIN_SEND_INTERVAL - delta)
    LAST_SEND_TS = time.time()

async def safe_admin_message(bot, text):
    for admin_id in ADMIN_IDS:
        try:
            await throttle_send()
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.error(f"Admin notify failed for {admin_id}: {e}")

async def delete_later(bot, chat_id, message_id, delay=30):
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

def has_disallowed_link_or_promo(text: str, allow_bot_username=True) -> bool:
    if not text:
        return False

    lower = text.lower()

    if A_LINK_PATTERN.search(lower):
        return True

    if PHONE_PATTERN.search(text) or EMAIL_PATTERN.search(text) or UPI_PATTERN.search(lower):
        return True

    for kw in SPAM_KEYWORDS:
        if kw in lower:
            return True

    mentions = re.findall(r'@([A-Za-z0-9_]+)', text)
    for mention in mentions:
        mention_lower = mention.lower()
        if allow_bot_username and mention_lower == BOT_USERNAME.lower():
            continue
        return True

    bot_mentions = BOT_MENTION_PATTERN.findall(text)
    for bot_name in bot_mentions:
        if allow_bot_username and bot_name.lower() == BOT_USERNAME.lower():
            continue
        return True

    return False

def has_banned_content(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    for term in BANNED_TERMS:
        if term in lower:
            return True
    return False

def has_personal_info_request(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    for term in PERSONAL_INFO_TERMS:
        if term in lower:
            return True
    return False

def pick_prompt():
    hour = (datetime.utcnow().hour + 5) % 24  # light IST-ish feel
    if hour >= 22 or hour < 4:
        return random.choice(LATE_NIGHT_TEXTS)
    return random.choice(ENGAGEMENT_TEXTS)

async def send_admin_identity_copy(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    msg,
    source_label="anonymous"
):
    if not user or user.id in BLOCKED_USERS:
        return

    username_display = f"@{user.username}" if user.username else "no username"

    if msg.text:
        type_label = "text"
    elif msg.photo:
        type_label = "photo"
    elif msg.video:
        type_label = "video"
    elif msg.animation:
        type_label = "animation"
    elif msg.sticker:
        type_label = "sticker"
    elif msg.voice:
        type_label = "voice"
    elif msg.document:
        type_label = "document"
    else:
        type_label = "other"

    title = "😊 New anonymous post" if source_label == "anonymous" else "💬 Group post (DIRECT)"
    identity_card = (
        f"{title}\n"
        f"👤 Name: {user.first_name or 'No name'}\n"
        f"🆔 Username: {username_display}\n"
        f"📛 User ID: {user.id}\n"
        f"📦 Type: {type_label}\n"
        f"━━━━━━━━━━━━━━━"
    )

    for admin_id in ADMIN_IDS:
        try:
            await throttle_send()
            await context.bot.send_message(admin_id, identity_card)

            if msg.text:
                await throttle_send()
                await context.bot.send_message(admin_id, f"📝 {msg.text[:3500]}")

            elif msg.photo:
                await throttle_send()
                await context.bot.send_photo(
                    admin_id,
                    photo=msg.photo[-1].file_id,
                    caption=f"📷 Caption: {msg.caption or '(none)'}"
                )

            elif msg.video:
                await throttle_send()
                await context.bot.send_video(
                    admin_id,
                    video=msg.video.file_id,
                    caption=f"🎥 Caption: {msg.caption or '(none)'}"
                )

            elif msg.animation:
                await throttle_send()
                await context.bot.send_animation(
                    admin_id,
                    animation=msg.animation.file_id,
                    caption=f"🎞 Caption: {msg.caption or '(none)'}"
                )

            elif msg.sticker:
                await throttle_send()
                await context.bot.send_sticker(admin_id, sticker=msg.sticker.file_id)

            elif msg.voice:
                await throttle_send()
                await context.bot.send_voice(admin_id, voice=msg.voice.file_id)

            elif msg.document:
                await throttle_send()
                await context.bot.send_document(
                    admin_id,
                    document=msg.document.file_id,
                    caption=f"📄 Filename: {msg.document.file_name or 'unknown'}"
                )

        except Exception as e:
            logger.error(f"Admin copy failed: {e}")

def build_payload_from_message(msg, user_id: int):
    if msg.text:
        return {
            "user_id": user_id,
            "type": "text",
            "text": msg.text,
            "caption": "",
            "file_id": None,
            "ts": time.time(),
        }

    if msg.photo:
        return {
            "user_id": user_id,
            "type": "photo",
            "text": "",
            "caption": msg.caption or "",
            "file_id": msg.photo[-1].file_id,
            "ts": time.time(),
        }

    if msg.video:
        return {
            "user_id": user_id,
            "type": "video",
            "text": "",
            "caption": msg.caption or "",
            "file_id": msg.video.file_id,
            "ts": time.time(),
        }

    if msg.animation:
        return {
            "user_id": user_id,
            "type": "animation",
            "text": "",
            "caption": msg.caption or "",
            "file_id": msg.animation.file_id,
            "ts": time.time(),
        }

    return None

async def post_payload_to_group(bot, payload):
    msg_type = payload["type"]

    if msg_type == "text":
        await throttle_send()
        await bot.send_message(
            chat_id=GROUP_ID,
            text=POST_HEADER + payload["text"]
        )
        return

    if msg_type == "photo":
        await throttle_send()
        await bot.send_photo(
            chat_id=GROUP_ID,
            photo=payload["file_id"],
            caption=POST_HEADER + (payload["caption"] or "")
        )
        add_archive(payload["file_id"], "photo", payload["caption"])
        return

    if msg_type == "video":
        await throttle_send()
        await bot.send_video(
            chat_id=GROUP_ID,
            video=payload["file_id"],
            caption=POST_HEADER + (payload["caption"] or "")
        )
        add_archive(payload["file_id"], "video", payload["caption"])
        return

    if msg_type == "animation":
        await throttle_send()
        await bot.send_animation(
            chat_id=GROUP_ID,
            animation=payload["file_id"],
            caption=POST_HEADER + (payload["caption"] or "")
        )
        return

    raise ValueError(f"Unsupported payload type: {msg_type}")

# =========================================================
# WORKERS
# =========================================================

async def submission_worker(app: Application):
    logger.info("Submission worker started")
    while True:
        payload = await SUBMISSION_QUEUE.get()
        last_error = None

        try:
            success = False

            for attempt in range(1, QUEUE_RETRY_LIMIT + 1):
                try:
                    await post_payload_to_group(app.bot, payload)
                    mark_group_activity()
                    success = True
                    break
                except Exception as e:
                    last_error = e
                    logger.error(f"Queue attempt {attempt} failed: {e}")
                    await asyncio.sleep(QUEUE_RETRY_DELAY * attempt)

            if not success:
                await safe_admin_message(
                    app.bot,
                    f"🚨 Queue post failed after retries\n"
                    f"User ID: {payload.get('user_id')}\n"
                    f"Type: {payload.get('type')}\n"
                    f"Error: {str(last_error)[:500]}"
                )

        finally:
            SUBMISSION_QUEUE.task_done()

async def autopilot_loop(app: Application):
    global LAST_AUTOPILOT_POST_TS, LAST_RECYCLE_TS, LAST_BATTLE_TS, BATTLES_TODAY

    logger.info("Autopilot loop started")

    while True:
        try:
            maybe_reset_battle_day()

            if AUTO_PILOT_ENABLED:
                now = time.time()
                idle = now - LAST_GROUP_ACTIVITY_TS
                gap = now - LAST_AUTOPILOT_POST_TS
                recycle_gap = now - LAST_RECYCLE_TS
                battle_gap = now - LAST_BATTLE_TS
                hour = datetime.utcnow().hour

                # engagement
                if idle >= NEXT_IDLE_TARGET and gap >= NEXT_GAP_TARGET:
                    try:
                        await send_engagement(app)
                    except Exception as e:
                        logger.error(f"Engagement error: {e}")

                # recycle
                if recycle_gap >= NEXT_RECYCLE_GAP:
                    try:
                        await recycle_archive(app)
                    except Exception as e:
                        logger.error(f"Recycle error: {e}")

                # queen battle - mostly evening/night
                if (
                    BATTLES_TODAY < BATTLES_TODAY_TARGET
                    and battle_gap >= BATTLE_MIN_GAP
                    and (hour >= 15 or hour <= 1)
                ):
                    # small random chance every loop once conditions are valid
                    if random.random() < 0.08:
                        try:
                            ok = await queen_battle(app)
                            if ok:
                                BATTLES_TODAY += 1
                        except Exception as e:
                            logger.error(f"Battle error: {e}")

        except Exception as e:
            logger.error(f"Autopilot loop outer error: {e}")

        await asyncio.sleep(60)

# =========================================================
# USER COMMANDS
# =========================================================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    referred_by = None

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referred_by = int(arg.split("_", 1)[1])
            except Exception:
                referred_by = None

    register_user(user, referred_by=referred_by)

    text = (
        f"🫥 Welcome to {BOT_NAME}\n\n"
        f"Send me:\n"
        f"• text\n"
        f"• photo\n"
        f"• video\n"
        f"• GIF\n\n"
        f"I'll post it anonymously in the group.\n\n"
        f"Group: {GROUP_LINK}"
    )
    await update.message.reply_text(text)

async def invite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{update.effective_user.id}"
    await update.message.reply_text(
        f"🚀 Invite link:\n{ref_link}\n\n"
        f"Current referrals: {get_referral_count(update.effective_user.id)}"
    )

async def share_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{update.effective_user.id}"
    await update.message.reply_text(
        f"Share this with friends:\n\n"
        f"{ref_link}"
    )

async def mystats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    refs = get_referral_count(update.effective_user.id)
    await update.message.reply_text(
        f"📊 Your stats\n\n"
        f"Invites: {refs}"
    )

# =========================================================
# PRIVATE SUBMISSIONS
# =========================================================

async def submit_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    msg = update.message

    if not user or not msg:
        return

    # Hard ignore
    if user.id in BLOCKED_USERS:
        return

    register_user(user)

    text_content = msg.text or msg.caption or ""
    is_admin_user = is_admin(user.id)

    # Block bad content
    if has_banned_content(text_content):
        await msg.reply_text("🚫 Content blocked.")
        return

    if has_personal_info_request(text_content):
        await msg.reply_text("🚫 Personal contact sharing is not allowed.")
        return

    if not is_admin_user:
        if PHONE_PATTERN.search(text_content) or EMAIL_PATTERN.search(text_content) or UPI_PATTERN.search(text_content):
            await msg.reply_text("🚫 Personal info is not allowed.")
            return

        if has_disallowed_link_or_promo(text_content, allow_bot_username=True):
            await msg.reply_text("🚫 Links, promotions, and other bot mentions are not allowed.")
            return

    payload = build_payload_from_message(msg, user.id)
    if not payload:
        await msg.reply_text("📩 Send text, photo, video, or GIF only.")
        return

    # Admin sees identity + actual content
    await send_admin_identity_copy(context, user, msg, source_label="anonymous")

    # Queue for reliable posting
    await SUBMISSION_QUEUE.put(payload)

    # Always success-facing response
    if random.random() < INVITE_REMINDER_CHANCE:
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
        await msg.reply_text(
            "✅ Received and queued for anonymous posting.\n\n"
            f"🚀 Invite a friend:\n{ref_link}"
        )
    else:
        await msg.reply_text("✅ Received and queued for anonymous posting.")

# =========================================================
# GROUP TRACKING / NUDGE
# =========================================================

async def track_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.effective_chat:
            return

        if update.effective_chat.id != GROUP_ID:
            return

        user = update.message.from_user
        if not user or user.is_bot:
            return

        mark_group_activity()

        # Skip blocked users
        if user.id in BLOCKED_USERS:
            return

        # Admin feed for direct group posts
        await send_admin_identity_copy(context, user, update.message, source_label="direct")

        # Gentle anonymity nudge for non-admins
        if not is_admin(user.id):
            now = time.time()
            last = LAST_NUDGE_BY_USER.get(user.id, 0)

            # only nudge sometimes and not too often
            if now - last >= DIRECT_NUDGE_COOLDOWN:
                LAST_NUDGE_BY_USER[user.id] = now
                try:
                    sent = await update.message.reply_text(
                        f"🫥 Want to stay anonymous? Post via @{BOT_USERNAME} next time."
                    )
                    asyncio.create_task(
                        delete_later(context.bot, sent.chat_id, sent.message_id, delay=30)
                    )
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"track_group_activity error: {e}")

# =========================================================
# GROUP FILTERS
# =========================================================

async def anti_spam_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.id != GROUP_ID:
        return

    msg = update.message
    user = msg.from_user

    if not user or user.is_bot:
        return

    # Silently remove blocked users' messages if present
    if user.id in BLOCKED_USERS:
        try:
            await msg.delete()
        except Exception:
            pass
        return

    if is_admin(user.id):
        return

    text_content = msg.text or msg.caption or ""

    # Members can comment/post anything EXCEPT links/promos/bots/personal info
    should_delete = False
    reason = None

    if has_banned_content(text_content):
        should_delete = True
        reason = "banned content"

    elif has_personal_info_request(text_content):
        should_delete = True
        reason = "personal info request"

    elif has_disallowed_link_or_promo(text_content, allow_bot_username=True):
        should_delete = True
        reason = "links / promo / bot mention"

    if should_delete:
        try:
            await msg.delete()
        except Exception as e:
            logger.error(f"Delete spam failed: {e}")

        strikes = add_strike(user.id)

        try:
            await context.bot.send_message(
                user.id,
                f"🚫 Your message was removed.\nReason: {reason}\nStrikes: {strikes}"
            )
        except Exception:
            pass

        await safe_admin_message(
            context.bot,
            f"⚠️ Group message removed\n"
            f"User: {user.first_name} (@{user.username or 'no_username'})\n"
            f"ID: {user.id}\n"
            f"Reason: {reason}\n"
            f"Strikes: {strikes}\n"
            f"Content: {text_content[:500]}"
        )

        if strikes >= 2:
            try:
                await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=user.id)
                await safe_admin_message(
                    context.bot,
                    f"🚫 Auto-banned after repeated violations\n"
                    f"User ID: {user.id}"
                )
            except Exception as e:
                logger.error(f"Auto-ban failed: {e}")

async def auto_kick_foreign_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.id != GROUP_ID:
        return

    new_members = update.message.new_chat_members
    if not new_members:
        return

    adder = update.message.from_user

    for new_member in new_members:
        if not new_member.is_bot:
            continue

        username = (new_member.username or "").lower()

        # our own bot is allowed
        if username in ALLOWED_BOTS:
            continue

        # admin-added bots are allowed
        if adder and is_admin(adder.id):
            continue

        try:
            await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=new_member.id)
        except Exception as e:
            logger.error(f"Kick foreign bot failed: {e}")

        if adder and not is_admin(adder.id):
            strikes = add_strike(adder.id)
            await safe_admin_message(
                context.bot,
                f"🤖 Foreign bot auto-kicked\n"
                f"Bot: @{new_member.username or 'unknown'}\n"
                f"Added by: {adder.first_name} (@{adder.username or 'no_username'})\n"
                f"Adder ID: {adder.id}\n"
                f"Strikes: {strikes}"
            )

            if strikes >= 2:
                try:
                    await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=adder.id)
                except Exception:
                    pass

async def auto_delete_service_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if update.effective_chat.id != GROUP_ID:
        return

    msg = update.message

    service = (
        msg.new_chat_members
        or msg.left_chat_member
        or msg.new_chat_title
        or msg.new_chat_photo
        or msg.delete_chat_photo
        or msg.group_chat_created
        or msg.supergroup_chat_created
        or msg.channel_chat_created
        or msg.pinned_message
    )

    if service:
        try:
            await msg.delete()
        except Exception:
            pass

# =========================================================
# AUTOPILOT ACTIONS
# =========================================================

async def send_engagement(app: Application):
    global LAST_AUTOPILOT_POST_TS
    text = pick_prompt()
    await throttle_send()
    await app.bot.send_message(chat_id=GROUP_ID, text=text)
    LAST_AUTOPILOT_POST_TS = time.time()
    mark_group_activity()
    reset_idle_targets()

async def recycle_archive(app: Application):
    global LAST_RECYCLE_TS, LAST_AUTOPILOT_POST_TS

    cooldown_ts = time.time() - (RECYCLE_COOLDOWN_DAYS * 86400)

    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT id, file_id, media_type, caption
        FROM archive
        WHERE last_recycled < ?
        ORDER BY RANDOM()
        LIMIT 1
    """, (cooldown_ts,))
    row = c.fetchone()

    if not row:
        conn.close()
        reset_recycle_gap()
        return False

    row_id, file_id, media_type, caption = row
    footer = random.choice(RECYCLE_FOOTERS)
    final_caption = POST_HEADER + (caption or "") + footer

    try:
        if media_type == "photo":
            await throttle_send()
            await app.bot.send_photo(GROUP_ID, photo=file_id, caption=final_caption)
        elif media_type == "video":
            await throttle_send()
            await app.bot.send_video(GROUP_ID, video=file_id, caption=final_caption)
        else:
            conn.close()
            reset_recycle_gap()
            return False

        c.execute("UPDATE archive SET last_recycled=? WHERE id=?", (time.time(), row_id))
        conn.commit()
        LAST_RECYCLE_TS = time.time()
        LAST_AUTOPILOT_POST_TS = time.time()
        mark_group_activity()
        reset_recycle_gap()
        return True

    except Exception as e:
        logger.error(f"recycle_archive failed: {e}")
        return False
    finally:
        conn.close()

async def queen_battle(app: Application):
    global LAST_BATTLE_TS, LAST_AUTOPILOT_POST_TS

    cooldown_ts = time.time() - (BATTLE_PHOTO_COOLDOWN_DAYS * 86400)

    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT id, file_id, caption
        FROM archive
        WHERE media_type='photo' AND battle_used < ?
        ORDER BY RANDOM()
        LIMIT 2
    """, (cooldown_ts,))
    rows = c.fetchall()

    if len(rows) < 2:
        conn.close()
        return False

    a_id, a_file, a_caption = rows[0]
    b_id, b_file, b_caption = rows[1]

    try:
        await throttle_send()
        await app.bot.send_message(GROUP_ID, text=random.choice(QUEEN_BATTLE_INTROS))

        await throttle_send()
        await app.bot.send_photo(
            GROUP_ID,
            photo=a_file,
            caption=f"👑 Queen A\n{(a_caption or '').strip()[:600]}"
        )

        await throttle_send()
        await app.bot.send_photo(
            GROUP_ID,
            photo=b_file,
            caption=f"👑 Queen B\n{(b_caption or '').strip()[:600]}"
        )

        await throttle_send()
        await app.bot.send_poll(
            chat_id=GROUP_ID,
            question="👑 Queen Battle — who wins?",
            options=["Queen A", "Queen B"],
            is_anonymous=False,
            allows_multiple_answers=False
        )

        now_ts = time.time()
        c.execute("UPDATE archive SET battle_used=? WHERE id=?", (now_ts, a_id))
        c.execute("UPDATE archive SET battle_used=? WHERE id=?", (now_ts, b_id))
        conn.commit()

        LAST_BATTLE_TS = now_ts
        LAST_AUTOPILOT_POST_TS = now_ts
        mark_group_activity()
        return True

    except Exception as e:
        logger.error(f"queen_battle failed: {e}")
        return False
    finally:
        conn.close()

# =========================================================
# ADMIN COMMANDS
# =========================================================

async def autopilot_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        f"🤖 Autopilot: {'ON' if AUTO_PILOT_ENABLED else 'OFF'}\n"
        f"Users: {get_user_count()}\n"
        f"Archive: {get_archive_count()}\n"
        f"Queue size: {SUBMISSION_QUEUE.qsize()}\n"
        f"Battles today: {BATTLES_TODAY}/{BATTLES_TODAY_TARGET}"
    )

async def autopilot_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_PILOT_ENABLED
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    AUTO_PILOT_ENABLED = True
    await update.message.reply_text("✅ Autopilot ON")

async def autopilot_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_PILOT_ENABLED
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    AUTO_PILOT_ENABLED = False
    await update.message.reply_text("⏸ Autopilot OFF")

async def postnow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    await send_engagement(context.application)
    await update.message.reply_text("✅ Engagement posted")

async def recycle_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    ok = await recycle_archive(context.application)
    await update.message.reply_text("✅ Recycled" if ok else "⚠️ No eligible archive found")

async def battle_now_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BATTLES_TODAY
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    ok = await queen_battle(context.application)
    if ok:
        BATTLES_TODAY += 1
    await update.message.reply_text("✅ Battle posted" if ok else "⚠️ Need at least 2 archived photos")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        f"📊 Stats\n\n"
        f"Users: {get_user_count()}\n"
        f"Archive: {get_archive_count()}\n"
        f"Queue size: {SUBMISSION_QUEUE.qsize()}\n"
        f"Autopilot: {'ON' if AUTO_PILOT_ENABLED else 'OFF'}"
    )

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban USER_ID")
        return

    try:
        uid = int(context.args[0])
        await context.bot.ban_chat_member(chat_id=GROUP_ID, user_id=uid)
        await update.message.reply_text(f"🚫 Banned {uid}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban USER_ID")
        return

    try:
        uid = int(context.args[0])
        await context.bot.unban_chat_member(chat_id=GROUP_ID, user_id=uid)
        await update.message.reply_text(f"✅ Unbanned {uid}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def block_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /blockuser USER_ID")
        return

    try:
        uid = int(context.args[0])
        BLOCKED_USERS.add(uid)
        await update.message.reply_text(f"🚫 Blocked {uid} from bot processing")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unblock_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unblockuser USER_ID")
        return

    try:
        uid = int(context.args[0])
        BLOCKED_USERS.discard(uid)
        await update.message.reply_text(f"✅ Unblocked {uid}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def blocked_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not BLOCKED_USERS:
        await update.message.reply_text("No blocked users.")
        return

    text = "🚫 Blocked users:\n\n" + "\n".join(str(uid) for uid in sorted(BLOCKED_USERS))
    await update.message.reply_text(text)

# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        await safe_admin_message(
            context.bot,
            f"🚨 Bot error\n{str(context.error)[:1200]}"
        )
    except Exception:
        pass

# =========================================================
# STARTUP
# =========================================================

async def post_init(app: Application):
    app.create_task(submission_worker(app))
    app.create_task(autopilot_loop(app))
    logger.info("Post-init tasks started")

def main():
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Private commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("invite", invite_cmd))
    app.add_handler(CommandHandler("share", share_cmd))
    app.add_handler(CommandHandler("mystats", mystats_cmd))

    # Admin commands
    app.add_handler(CommandHandler("autopilot_status", autopilot_status_cmd))
    app.add_handler(CommandHandler("autopilot_on", autopilot_on_cmd))
    app.add_handler(CommandHandler("autopilot_off", autopilot_off_cmd))
    app.add_handler(CommandHandler("postnow", postnow_cmd))
    app.add_handler(CommandHandler("recycle_now", recycle_now_cmd))
    app.add_handler(CommandHandler("battle_now", battle_now_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("blockuser", block_user_cmd))
    app.add_handler(CommandHandler("unblockuser", unblock_user_cmd))
    app.add_handler(CommandHandler("blockedusers", blocked_users_cmd))

    # Group protection - high priority
    app.add_handler(
        MessageHandler(filters.Chat(GROUP_ID) & filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_kick_foreign_bots),
        group=-2
    )
    app.add_handler(
        MessageHandler(filters.Chat(GROUP_ID) & (filters.TEXT | filters.CAPTION), anti_spam_filter),
        group=-1
    )
    app.add_handler(
        MessageHandler(filters.Chat(GROUP_ID), auto_delete_service_messages),
        group=0
    )

    # Group feed / tracking
    app.add_handler(
        MessageHandler(
            filters.Chat(GROUP_ID) & (
                filters.TEXT |
                filters.PHOTO |
                filters.VIDEO |
                filters.ANIMATION |
                filters.Sticker.ALL |
                filters.VOICE |
                filters.Document.ALL
            ),
            track_group_activity
        ),
        group=1
    )

    # Private submissions
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (
                filters.TEXT |
                filters.PHOTO |
                filters.VIDEO |
                filters.ANIMATION
            ),
            submit_private
        )
    )

    app.add_error_handler(error_handler)

    logger.info("🚀 Samadanam bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
