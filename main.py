# ================================================================
# SAMADANAM BOT — FINAL CLEAN VERSION
# Features:
#   - Anonymous posting via bot DM
#   - Admin identity feed (anonymous + direct group posts)
#   - Reliable submission queue (no "Couldn't post" errors)
#   - Admin-only links/bots in group + DM
#   - Foreign bot auto-kicker
#   - Spam + phone number blocker
#   - "Post anonymously" nudge for direct group posts
#   - Autopilot (engagement + recycling)
#   - Queen Battles (2-4/day random with bilingual headers)
#   - Vibe-focused media reactions
#   - Branded footer on recycled posts
#   - Strike system (warn → ban)
#   - Admin commands
# ================================================================

import os
import re
import sqlite3
import random
import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, ChatPermissions
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes,
    filters, InlineQueryHandler
)
from telegram import InlineQueryResultArticle, InputTextMessageContent

# ================ CONFIG ================
BOT_TOKEN = "8736334059:AAEKBKYBXh5ytsHHtERmuln8X79sQi1sK2Q"
BOT_NAME = "സമാദാനം"
BOT_USERNAME = "samadanambot"
GROUP_ID = -1003636238775
GROUP_LINK = "https://t.me/+A93ERrKixbw5MTNk"
ADMIN_IDS = {8438801421}

POST_HEADER = "💬 Love Chat ❤️\n🫥 Anonymous via Samadanam\n\n"

# Autopilot settings
AUTO_PILOT_ENABLED = True
AUTOPOST_MIN_IDLE = 35 * 60
AUTOPOST_MAX_IDLE = 75 * 60
AUTOPOST_MIN_GAP = 25 * 60

# Recycling
RECYCLE_MIN_GAP = 2 * 3600
RECYCLE_MAX_GAP = 4 * 3600
RECYCLE_COOLDOWN_DAYS = 7

# Queen Battles
BATTLE_MIN_GAP = 90 * 60
BATTLE_PHOTO_COOLDOWN_DAYS = 14
BATTLE_DAILY_MIN = 2
BATTLE_DAILY_MAX = 4

# Media reactions
MEDIA_REACTION_CHANCE = 0.30

# Other
INVITE_REMINDER_CHANCE = 0.33
ANON_NUDGE_COOLDOWN = 1800   # 30 min per user

# Reliable posting queue
QUEUE_RETRY_LIMIT = 8
QUEUE_RETRY_DELAY = 3

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================ DATABASE ================
DB_PATH = "samadanam_bot.db"

def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        username TEXT, first_name TEXT,
        referred_by INTEGER, referral_count INTEGER DEFAULT 0,
        joined_at REAL, banned INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS archive(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT, media_type TEXT,
        caption TEXT, ts REAL,
        last_recycled REAL DEFAULT 0,
        battle_used REAL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS spammer_strikes(
        user_id INTEGER PRIMARY KEY,
        strikes INTEGER DEFAULT 0,
        last_strike REAL
    )""")
    conn.commit()
    conn.close()

# ================ FILTERS ================
PHONE_PATTERN = re.compile(r'(\+?\d{1,3}[\s\-]?)?\(?\d{3,5}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,5}')

BANNED_TERMS = [
    "child", "minor", "underage", "kid sex", "school girl",
    "rape", "force sex",
    "drug sell", "cocaine sell", "weed sell"
]

SPAM_KEYWORDS = [
    "onlyfans", "free video", "free videos", "hot video",
    "click here to watch", "watch now free", "100% free",
    "no pay no money", "premium unlocked",
    "best xxx", "leaked nude",
    "bit.ly", "tinyurl", "cutt.ly"
]

ALLOWED_BOTS = {"samadanambot"}

# ================ PROMPTS ================
ENGAGEMENT_TEXTS_ML = [
    "🫥 ഒരു വരി മതി. ഇപ്പോൾ മനസ്സിൽ ഉള്ളത് എന്താണ്? @samadanambot ലേക്ക് ഇടൂ.",
    "👀 silent readers, എവിടെയാണ്? ഒരാൾ തുടങ്ങൂ.",
    "💭 പറയാത്ത ഒരു കാര്യം ഇപ്പോൾ പറയാം. പേര് വേണ്ട.",
    "🌙 ഈ നേരം എന്തിനെ കുറിച്ച് ചിന്തിക്കുന്നു?",
    "🫥 ഒരു secret drop ചെയ്യാം. ബാക്കി ഞങ്ങൾ വായിക്കും.",
    "👑 നിങ്ങളുടെ റാണികളെ കാണിക്കൂ...",
    "💌 പറയാത്ത സ്നേഹം, അയയ്ക്കാത്ത സന്ദേശം — ഇവിടെ ഇടൂ.",
    "🔥 ഇന്ന് എന്തു പറയാനും സ്ഥലമുണ്ട്. ബോട്ടിൽ ഇടൂ.",
    "🌃 ഉറക്കം വരാത്ത മനസ്സിൽ ഉള്ളത് ബോട്ടിൽ ഇടൂ.",
    "💋 ഇന്നത്തെ vibe എന്താണ്?"
]

ENGAGEMENT_TEXTS_EN = [
    "🫥 One line is enough. What's on your mind right now? Drop it in @samadanambot",
    "👀 Silent readers, where you at? Someone start.",
    "💭 Say the thing you've never said. Name stays hidden.",
    "🌙 What's keeping you up tonight?",
    "🫥 Drop one secret. We'll read the rest.",
    "👑 Show us your queens...",
    "💌 The message you didn't send — bring it here.",
    "🔥 Tonight, anything goes. Drop it in the bot.",
    "🌃 Whatever's on your mind — share it anonymously.",
    "💋 What's the vibe today?"
]

BOT_REMINDERS = [
    "📩 Reminder: direct posts show your name. Stay hidden via @samadanambot",
    "🫥 The bot keeps your name hidden → @samadanambot",
    "💋 Want to post anonymously? Send it to @samadanambot",
    "📩 ഓർമ്മിപ്പിക്കുന്നു: ഗ്രൂപ്പിൽ നേരിട്ട് ഇട്ടാൽ പേര് കാണും. @samadanambot",
    "🫥 പേര് മറയ്ക്കാൻ → @samadanambot"
]

RECYCLE_FOOTERS = [
    "\n\n🫥 Anonymous via @samadanambot",
    "\n\n💋 സമാദാനം — @samadanambot",
    "\n\n📩 Share yours → @samadanambot"
]

MEDIA_REACTIONS_ML = [
    "🔥 ee drop scene aanu",
    "👀 ithu kandittu silent aayi pokan pattilla",
    "🫥 dangerous energy",
    "ayyo ee vibe 😭",
    "🌙 night just got real",
    "💋 ithinte behind story bot il വരണം",
    "🔥 mood set aayi",
    "👑 റാണി arrived",
    "🫥 ee post-ne kurichu silent aayirikkan vayya",
    "🔥 ithu daily venam"
]

MEDIA_REACTIONS_EN = [
    "🔥 this one hits",
    "👀 can't scroll past this",
    "🫥 dangerous energy",
    "okay this changed the mood",
    "🌙 night just got real",
    "💋 need the story behind this",
    "🔥 mood set",
    "👑 queen energy",
    "🫥 silent ain't an option",
    "🔥 we need more like this"
]

POLLS = [
    ("🌙 Tonight's vibe?", ["Love 💗", "Lust 🔥", "Lonely 🥺", "Chaos 🌪️"]),
    ("👀 Pick your mood", ["Soft 🫧", "Bold 🔥", "Sad 💭", "Wild 🌪️"]),
    ("🫥 ഇപ്പോൾ?", ["സ്നേഹം 💗", "ദേഷ്യം 🔥", "ഒറ്റപ്പെടൽ 🥺", "ചാവി പോയി 🌪️"])
]

BATTLE_HEADER_ML = "👑💦 റാണി പോര് 👑\nഇന്നത്തെ duel. ആരാ winner?"
BATTLE_HEADER_EN = "👑💦 Queen Battle 👑\nTonight's duel. Pick your side."

# ================ STATE ================
LAST_GROUP_ACTIVITY_TS = time.time()
LAST_AUTOPILOT_POST_TS = 0
LAST_RECYCLE_TS = 0
LAST_BATTLE_TS = 0
BATTLES_TODAY = 0
BATTLE_DAY = datetime.utcnow().date()
NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
NEXT_RECYCLE_GAP = random.randint(RECYCLE_MIN_GAP, RECYCLE_MAX_GAP)

LAST_ANON_NUDGE_TS = {}

SUBMISSION_QUEUE = asyncio.Queue()

def mark_group_activity():
    global LAST_GROUP_ACTIVITY_TS
    LAST_GROUP_ACTIVITY_TS = time.time()

def reset_idle_target():
    global NEXT_IDLE_TARGET
    NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)

def pick_prompt():
    r = random.random()
    use_ml = random.random() < 0.5
    if r < 0.20:
        return random.choice(BOT_REMINDERS)
    else:
        return random.choice(ENGAGEMENT_TEXTS_ML if use_ml else ENGAGEMENT_TEXTS_EN)

# ================ ADMIN IDENTITY FEED ================
async def send_admin_identity_copy(context, user, msg, source_label="anonymous"):
    """Send identity card + exact content copy to admin DM only"""
    try:
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
        card = (
            f"{title}\n"
            f"👤 Name: {user.first_name or 'No name'}\n"
            f"🆔 Username: {username_display}\n"
            f"📛 User ID: `{user.id}`\n"
            f"📦 Type: {type_label}\n"
            f"━━━━━━━━━━━━━━━"
        )

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, card, parse_mode="Markdown")

                if msg.text:
                    await context.bot.send_message(admin_id, msg.text[:3500])
                elif msg.photo:
                    await context.bot.send_photo(
                        admin_id,
                        photo=msg.photo[-1].file_id,
                        caption=msg.caption or ""
                    )
                elif msg.video:
                    await context.bot.send_video(
                        admin_id,
                        video=msg.video.file_id,
                        caption=msg.caption or ""
                    )
                elif msg.animation:
                    await context.bot.send_animation(
                        admin_id,
                        animation=msg.animation.file_id,
                        caption=msg.caption or ""
                    )
                elif msg.sticker:
                    await context.bot.send_sticker(admin_id, msg.sticker.file_id)
                elif msg.voice:
                    await context.bot.send_voice(admin_id, msg.voice.file_id)
                elif msg.document:
                    await context.bot.send_document(
                        admin_id,
                        document=msg.document.file_id,
                        caption=msg.caption or ""
                    )
            except Exception as e:
                logger.error(f"Admin identity feed error: {e}")
    except Exception as e:
        logger.error(f"send_admin_identity_copy outer error: {e}")

# ================ POSTING QUEUE ================
async def post_payload_to_group(bot, payload):
    """Post queued content to group"""
    msg_type = payload["type"]
    caption = payload.get("caption", "") or ""
    text = payload.get("text", "") or ""
    file_id = payload.get("file_id")

    if msg_type == "text":
        await bot.send_message(chat_id=GROUP_ID, text=POST_HEADER + text)

    elif msg_type == "photo":
        await bot.send_photo(
            chat_id=GROUP_ID,
            photo=file_id,
            caption=POST_HEADER + caption
        )
        conn = db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO archive(file_id, media_type, caption, ts)
               VALUES(?, ?, ?, ?)""",
            (file_id, "photo", caption, time.time())
        )
        conn.commit()
        conn.close()

    elif msg_type == "video":
        await bot.send_video(
            chat_id=GROUP_ID,
            video=file_id,
            caption=POST_HEADER + caption
        )
        conn = db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO archive(file_id, media_type, caption, ts)
               VALUES(?, ?, ?, ?)""",
            (file_id, "video", caption, time.time())
        )
        conn.commit()
        conn.close()

    elif msg_type == "animation":
        await bot.send_animation(
            chat_id=GROUP_ID,
            animation=file_id,
            caption=POST_HEADER + caption
        )
    else:
        raise ValueError(f"Unsupported queued type: {msg_type}")

async def submission_worker(app):
    """Background worker — retries posts silently. Members never see 'try again'."""
    while True:
        payload = await SUBMISSION_QUEUE.get()
        try:
            success = False
            last_error = None

            for attempt in range(1, QUEUE_RETRY_LIMIT + 1):
                try:
                    await post_payload_to_group(app.bot, payload)
                    success = True
                    break
                except Exception as e:
                    last_error = e
                    logger.error(f"Queue post attempt {attempt} failed: {e}")
                    await asyncio.sleep(QUEUE_RETRY_DELAY * attempt)

            if not success:
                for admin_id in ADMIN_IDS:
                    try:
                        await app.bot.send_message(
                            admin_id,
                            f"🚨 Queue post failed after {QUEUE_RETRY_LIMIT} retries\n"
                            f"User ID: {payload.get('user_id', '?')}\n"
                            f"Type: {payload.get('type', '?')}\n"
                            f"Error: {str(last_error)[:300]}"
                        )
                    except:
                        pass
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            SUBMISSION_QUEUE.task_done()

# ================ ANTI-SPAM ================
async def anti_spam_filter(update, context):
    """Block links from non-admins. Strike system: warn → ban."""
    try:
        if not update.message or not update.effective_chat:
            return
        if update.effective_chat.id != GROUP_ID:
            return

        msg = update.message
        user = msg.from_user
        if not user or user.is_bot:
            return
        if user.id in ADMIN_IDS:
            return

        text = (msg.text or msg.caption or "")
        text_lower = text.lower()
        if not text:
            return

        is_spam = False
        reason = ""

        for kw in BANNED_TERMS:
            if kw in text_lower:
                is_spam = True
                reason = "banned content"
                break

        if not is_spam:
            for kw in SPAM_KEYWORDS:
                if kw in text_lower:
                    is_spam = True
                    reason = "spam keyword"
                    break

        if not is_spam:
            link_patterns = [
                r'https?://', r'www\.', r't\.me/', r'telegram\.me/'
            ]
            for pattern in link_patterns:
                if re.search(pattern, text_lower):
                    is_spam = True
                    reason = "external link"
                    break

            if not is_spam:
                mentions = re.findall(r'@(\w+)', text_lower)
                bad_mention = any(m != BOT_USERNAME.lower() for m in mentions if len(m) >= 4)
                if bad_mention:
                    is_spam = True
                    reason = "external mention"

        if not is_spam:
            return

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=msg.message_id
            )
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return

        conn = db()
        c = conn.cursor()
        c.execute("SELECT strikes FROM spammer_strikes WHERE user_id=?", (user.id,))
        row = c.fetchone()
        strikes = (row[0] if row else 0) + 1
        c.execute("""INSERT OR REPLACE INTO spammer_strikes(user_id, strikes, last_strike)
                     VALUES(?, ?, ?)""", (user.id, strikes, time.time()))
        conn.commit()
        conn.close()

        if strikes >= 2:
            try:
                await context.bot.ban_chat_member(
                    chat_id=update.effective_chat.id,
                    user_id=user.id
                )
            except:
                pass
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🚫 BANNED — {reason}\n"
                        f"User: {user.first_name} (@{user.username})\n"
                        f"ID: {user.id}\n"
                        f"Strikes: {strikes}\n"
                        f"Text: {text[:200]}"
                    )
                except:
                    pass
        else:
            try:
                await context.bot.send_message(
                    user.id,
                    f"⚠️ Warning — സമാദാനം\n\n"
                    f"🚫 Your message was deleted.\n"
                    f"Reason: {reason}\n\n"
                    f"📌 Rules:\n"
                    f"• No external links\n"
                    f"• No promo from other groups\n"
                    f"• No bot links except @{BOT_USERNAME}\n\n"
                    f"⚠️ Next violation = permanent ban.\n"
                    f"💋 Post anonymously via @{BOT_USERNAME}"
                )
            except:
                pass
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"⚠️ Strike 1 — {reason}\n"
                        f"User: {user.first_name} (@{user.username})\n"
                        f"ID: {user.id}\n"
                        f"Text: {text[:200]}"
                    )
                except:
                    pass
    except Exception as e:
        logger.error(f"Anti-spam outer error: {e}")

async def auto_kick_foreign_bots(update, context):
    """Kick bots added by non-admins"""
    try:
        if not update.message or not update.message.new_chat_members:
            return
        if update.effective_chat.id != GROUP_ID:
            return

        adder = update.message.from_user
        if adder and adder.id in ADMIN_IDS:
            return

        for new_member in update.message.new_chat_members:
            if not new_member.is_bot:
                continue
            username = (new_member.username or "").lower()
            if username in ALLOWED_BOTS:
                continue
            try:
                await context.bot.ban_chat_member(
                    chat_id=update.effective_chat.id,
                    user_id=new_member.id
                )
                if adder:
                    conn = db()
                    c = conn.cursor()
                    c.execute("SELECT strikes FROM spammer_strikes WHERE user_id=?", (adder.id,))
                    row = c.fetchone()
                    strikes = (row[0] if row else 0) + 1
                    c.execute("""INSERT OR REPLACE INTO spammer_strikes(user_id, strikes, last_strike)
                                 VALUES(?, ?, ?)""", (adder.id, strikes, time.time()))
                    conn.commit()
                    conn.close()
                    if strikes >= 2:
                        try:
                            await context.bot.ban_chat_member(
                                chat_id=update.effective_chat.id,
                                user_id=adder.id
                            )
                        except:
                            pass
                    else:
                        try:
                            await context.bot.send_message(
                                adder.id,
                                f"⚠️ Warning — സമാദാനം\n\n"
                                f"🚫 You added a bot to the group.\n"
                                f"Only admins can add bots.\n\n"
                                f"⚠️ Next violation = permanent ban."
                            )
                        except:
                            pass

                for admin_id in ADMIN_IDS:
                    try:
                        await context.bot.send_message(
                            admin_id,
                            f"⚠️ Foreign bot kicked\n"
                            f"Bot: @{new_member.username}\n"
                            f"Added by: {adder.first_name if adder else '?'} ID: {adder.id if adder else '?'}"
                        )
                    except:
                        pass
            except Exception as e:
                logger.error(f"Kick bot error: {e}")
    except Exception as e:
        logger.error(f"Auto-kick outer error: {e}")

async def auto_delete_service_messages(update, context):
    """Hide join/leave/promote service messages"""
    try:
        if not update.effective_chat or update.effective_chat.id != GROUP_ID:
            return
        msg = update.message
        if not msg:
            return
        if any([
            msg.new_chat_members, msg.left_chat_member,
            msg.new_chat_title, msg.new_chat_photo,
            msg.delete_chat_photo, msg.pinned_message
        ]):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=msg.message_id
                )
            except:
                pass
    except Exception as e:
        logger.error(f"Service msg delete error: {e}")

# ================ AUTOPILOT ENGINES ================
async def send_engagement(app):
    try:
        use_poll = random.random() < 0.15
        if use_poll:
            q, opts = random.choice(POLLS)
            await app.bot.send_poll(chat_id=GROUP_ID, question=q, options=opts, is_anonymous=True)
        else:
            await app.bot.send_message(chat_id=GROUP_ID, text=pick_prompt())
        global LAST_AUTOPILOT_POST_TS
        LAST_AUTOPILOT_POST_TS = time.time()
        reset_idle_target()
    except Exception as e:
        logger.error(f"Engagement error: {e}")

async def recycle_archive(app):
    try:
        conn = db()
        c = conn.cursor()
        cutoff_recycle = time.time() - (RECYCLE_COOLDOWN_DAYS * 86400)
        cutoff_age = time.time() - 86400
        c.execute("""SELECT id, file_id, media_type, caption FROM archive
                     WHERE last_recycled < ? AND ts < ?
                     ORDER BY RANDOM() LIMIT 1""", (cutoff_recycle, cutoff_age))
        row = c.fetchone()
        if not row:
            conn.close()
            return
        aid, file_id, media_type, caption = row
        footer = random.choice(RECYCLE_FOOTERS)
        cap = POST_HEADER + (caption or "") + footer

        if media_type == "photo":
            await app.bot.send_photo(chat_id=GROUP_ID, photo=file_id, caption=cap)
        elif media_type == "video":
            await app.bot.send_video(chat_id=GROUP_ID, video=file_id, caption=cap)
        elif media_type == "animation":
            await app.bot.send_animation(chat_id=GROUP_ID, animation=file_id, caption=cap)

        c.execute("UPDATE archive SET last_recycled=? WHERE id=?", (time.time(), aid))
        conn.commit()
        conn.close()

        global LAST_RECYCLE_TS, NEXT_RECYCLE_GAP
        LAST_RECYCLE_TS = time.time()
        NEXT_RECYCLE_GAP = random.randint(RECYCLE_MIN_GAP, RECYCLE_MAX_GAP)
    except Exception as e:
        logger.error(f"Recycle error: {e}")

async def queen_battle(app):
    """Pick 2 random archive photos, send as battle with poll"""
    try:
        conn = db()
        c = conn.cursor()
        cutoff = time.time() - (BATTLE_PHOTO_COOLDOWN_DAYS * 86400)
        c.execute("""SELECT id, file_id FROM archive
                     WHERE media_type='photo' AND battle_used < ?
                     ORDER BY RANDOM() LIMIT 2""", (cutoff,))
        rows = c.fetchall()
        if len(rows) < 2:
            conn.close()
            return False

        use_ml = random.random() < 0.5
        header = BATTLE_HEADER_ML if use_ml else BATTLE_HEADER_EN

        media = [
            InputMediaPhoto(media=rows[0][1], caption=header),
            InputMediaPhoto(media=rows[1][1])
        ]
        await app.bot.send_media_group(chat_id=GROUP_ID, media=media)
        await asyncio.sleep(2)
        await app.bot.send_poll(
            chat_id=GROUP_ID,
            question="👑 Pick your queen",
            options=["⬅️ Left", "➡️ Right", "🔥 Both fire", "🚫 Pass"],
            is_anonymous=True
        )

        for aid, _ in rows:
            c.execute("UPDATE archive SET battle_used=? WHERE id=?", (time.time(), aid))
        conn.commit()
        conn.close()

        global LAST_BATTLE_TS, BATTLES_TODAY
        LAST_BATTLE_TS = time.time()
        BATTLES_TODAY += 1
        return True
    except Exception as e:
        logger.error(f"Battle error: {e}")
        return False

async def autopilot_loop(app):
    global BATTLES_TODAY, BATTLE_DAY
    target_battles = random.randint(BATTLE_DAILY_MIN, BATTLE_DAILY_MAX)

    while True:
        try:
            await asyncio.sleep(60)
            if not AUTO_PILOT_ENABLED:
                continue

            now = time.time()
            today = datetime.utcnow().date()
            if today != BATTLE_DAY:
                BATTLE_DAY = today
                BATTLES_TODAY = 0
                target_battles = random.randint(BATTLE_DAILY_MIN, BATTLE_DAILY_MAX)

            idle = now - LAST_GROUP_ACTIVITY_TS

            if idle >= NEXT_IDLE_TARGET and (now - LAST_AUTOPILOT_POST_TS) >= AUTOPOST_MIN_GAP:
                await send_engagement(app)

            if (now - LAST_RECYCLE_TS) >= NEXT_RECYCLE_GAP:
                await recycle_archive(app)

            if (BATTLES_TODAY < target_battles
                and (now - LAST_BATTLE_TS) >= BATTLE_MIN_GAP
                and idle >= 15 * 60):
                await queen_battle(app)
        except Exception as e:
            logger.error(f"Autopilot loop error: {e}")

# ================ USER HANDLERS ================
async def start(update, context):
    try:
        user = update.effective_user
        args = context.args
        ref_by = None
        if args and args[0].startswith("ref_"):
            try:
                ref_by = int(args[0][4:])
                if ref_by == user.id:
                    ref_by = None
            except:
                ref_by = None

        conn = db()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,))
        if not c.fetchone():
            c.execute("""INSERT INTO users(user_id, username, first_name, referred_by, joined_at)
                         VALUES(?, ?, ?, ?, ?)""",
                      (user.id, user.username, user.first_name, ref_by, time.time()))
            if ref_by:
                c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?", (ref_by,))
        conn.commit()
        conn.close()

        welcome = (
            f"💋 *സമാദാനം — Anonymous Sharing Bot*\n\n"
            f"🫥 Send me text, photo, video or GIF — I'll post it anonymously.\n"
            f"📩 Your name stays hidden.\n\n"
            f"👉 Group: {GROUP_LINK}\n\n"
            f"Commands:\n"
            f"/invite — your invite link\n"
            f"/share — share Samadanam\n"
            f"/mystats — your stats"
        )
        await update.message.reply_text(welcome, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Start error: {e}")

async def submit_private(update, context):
    """DM handler: identity feed → admin, anonymous post → queue"""
    try:
        if update.effective_chat.type != "private":
            return

        user = update.effective_user
        msg = update.message
        if not msg:
            return

        text_content = msg.text or msg.caption or ""
        text_lower = text_content.lower()
        is_admin_user = user.id in ADMIN_IDS

        # Banned terms
        for term in BANNED_TERMS:
            if term in text_lower:
                await msg.reply_text("🚫 Content blocked.")
                return

        # Block links/phone for non-admins
        if not is_admin_user:
            if text_content and PHONE_PATTERN.search(text_content):
                await msg.reply_text("🚫 Phone numbers not allowed.")
                return
            link_check = re.search(r'(https?://|www\.|t\.me/|telegram\.me/)', text_lower)
            mention_check = re.findall(r'@(\w+)', text_lower)
            bad_mentions = [m for m in mention_check if m != BOT_USERNAME.lower() and len(m) >= 4]
            if link_check or bad_mentions:
                await msg.reply_text("🚫 Links not allowed. Admins only.")
                return

        # 1) Identity card + copy to admin
        await send_admin_identity_copy(context, user, msg, source_label="anonymous")

        # 2) Queue for reliable posting
        payload = {
            "user_id": user.id,
            "caption": msg.caption or "",
            "text": msg.text or "",
        }
        if msg.text:
            payload["type"] = "text"
        elif msg.photo:
            payload["type"] = "photo"
            payload["file_id"] = msg.photo[-1].file_id
        elif msg.video:
            payload["type"] = "video"
            payload["file_id"] = msg.video.file_id
        elif msg.animation:
            payload["type"] = "animation"
            payload["file_id"] = msg.animation.file_id
        else:
            await msg.reply_text("📩 Send text, photo, video or GIF.")
            return

        await SUBMISSION_QUEUE.put(payload)

        # 3) Reply to user
        if random.random() < INVITE_REMINDER_CHANCE:
            ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
            use_ml = random.random() < 0.5
            if use_ml:
                reply = (f"✅ Received and posting anonymously in Love Chat ❤️\n\n"
                         f"🚀 സമാദാനം massive ആക്കാം!\n"
                         f"ഒരാളെ invite ചെയ്യൂ:\n{ref_link}")
            else:
                reply = (f"✅ Received and posting anonymously in Love Chat ❤️\n\n"
                         f"🚀 Help Samadanam grow!\n"
                         f"Invite a friend:\n{ref_link}")
            await msg.reply_text(reply)
        else:
            await msg.reply_text("✅ Received and posting anonymously in Love Chat ❤️")

    except Exception as e:
        logger.error(f"submit_private error: {e}")
        logger.error(traceback.format_exc())
        try:
            await update.message.reply_text("⚠️ Something went wrong. Try again.")
        except:
            pass

async def invite_cmd(update, context):
    try:
        user = update.effective_user
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
        text = (
            f"📩 *Your invite link:*\n`{ref_link}`\n\n"
            f"Forward to friends:\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🫥 ഒരു new anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
            f"പേര് കാണിക്കാതെ share ചെയ്യാം.\n"
            f"👉 {ref_link}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🫥 found this anonymous Malayalam group...\n"
            f"people share secrets here.\n"
            f"👉 {ref_link}\n"
            f"━━━━━━━━━━━━━━━"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share anywhere", switch_inline_query=f"🫥 Anonymous Malayalam group → {ref_link}")],
            [InlineKeyboardButton("📋 Open Group", url=GROUP_LINK)]
        ])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Invite cmd error: {e}")

async def share_cmd(update, context):
    try:
        user = update.effective_user
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
        share_text = f"🫥 found this anonymous Malayalam group... 👉 {ref_link}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share to any chat", switch_inline_query=share_text)],
            [InlineKeyboardButton("📋 Copy link", url=ref_link)]
        ])
        await update.message.reply_text("📨 Tap to share Samadanam anywhere.", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Share cmd error: {e}")

async def mystats_cmd(update, context):
    try:
        user = update.effective_user
        conn = db()
        c = conn.cursor()
        c.execute("SELECT referral_count FROM users WHERE user_id=?", (user.id,))
        row = c.fetchone()
        conn.close()
        if not row:
            await update.message.reply_text("Send /start first.")
            return
        await update.message.reply_text(f"📊 Your invites: {row[0] or 0}")
    except Exception as e:
        logger.error(f"Stats error: {e}")

async def inline_share(update, context):
    try:
        user = update.inline_query.from_user
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
        results = [
            InlineQueryResultArticle(
                id="ml",
                title="Share in Malayalam",
                input_message_content=InputTextMessageContent(
                    f"🫥 ഒരു new anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
                    f"പേര് കാണിക്കാതെ share ചെയ്യാം.\n"
                    f"👉 {ref_link}"
                )
            ),
            InlineQueryResultArticle(
                id="en",
                title="Share in English",
                input_message_content=InputTextMessageContent(
                    f"🫥 found this anonymous Malayalam group...\n"
                    f"people share secrets here.\n"
                    f"👉 {ref_link}"
                )
            )
        ]
        await update.inline_query.answer(results, cache_time=10)
    except Exception as e:
        logger.error(f"Inline error: {e}")

# ================ GROUP TRACKER ================
async def track_group_activity(update, context):
    """Log direct group posts to admin + nudge to use bot"""
    try:
        if not update.message or not update.effective_chat:
            return
        if update.effective_chat.id != GROUP_ID:
            return

        msg = update.message
        user = msg.from_user
        if not user or user.is_bot:
            return

        mark_group_activity()

        # Skip logging admin's own messages
        if user.id not in ADMIN_IDS:
            await send_admin_identity_copy(context, user, msg, source_label="direct")

            # Nudge to use bot
            now = time.time()
            last_nudge = LAST_ANON_NUDGE_TS.get(user.id, 0)
            if now - last_nudge >= ANON_NUDGE_COOLDOWN:
                meaningful = bool(msg.text or msg.photo or msg.video or msg.animation)
                if meaningful:
                    try:
                        nudge = await context.bot.send_message(
                            chat_id=GROUP_ID,
                            reply_to_message_id=msg.message_id,
                            text="🫥 Want to stay anonymous? Post via @samadanambot next time."
                        )
                        LAST_ANON_NUDGE_TS[user.id] = now

                        async def delete_later():
                            await asyncio.sleep(25)
                            try:
                                await context.bot.delete_message(GROUP_ID, nudge.message_id)
                            except:
                                pass
                        asyncio.create_task(delete_later())
                    except Exception as e:
                        logger.error(f"Nudge error: {e}")

        # Vibe-focused media reactions
        if (msg.photo or msg.video) and random.random() < MEDIA_REACTION_CHANCE:
            await asyncio.sleep(random.randint(5, 18))
            use_ml = random.random() < 0.5
            reply = random.choice(MEDIA_REACTIONS_ML if use_ml else MEDIA_REACTIONS_EN)
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=reply,
                    reply_to_message_id=msg.message_id
                )
            except:
                pass

    except Exception as e:
        logger.error(f"Track error: {e}")

# ================ ADMIN COMMANDS ================
def is_admin(uid):
    return uid in ADMIN_IDS

async def autopilot_on(update, context):
    if not is_admin(update.effective_user.id): return
    global AUTO_PILOT_ENABLED
    AUTO_PILOT_ENABLED = True
    await update.message.reply_text("✅ Autopilot ON")

async def autopilot_off(update, context):
    if not is_admin(update.effective_user.id): return
    global AUTO_PILOT_ENABLED
    AUTO_PILOT_ENABLED = False
    await update.message.reply_text("⏸ Autopilot OFF")

async def autopilot_status(update, context):
    if not is_admin(update.effective_user.id): return
    idle = int(time.time() - LAST_GROUP_ACTIVITY_TS)
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM archive")
    archive_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users")
    user_count = c.fetchone()[0]
    conn.close()
    status = (
        f"🤖 *Samadanam Status*\n\n"
        f"Autopilot: {'✅ ON' if AUTO_PILOT_ENABLED else '⏸ OFF'}\n"
        f"Idle: {idle//60} min\n"
        f"Next idle target: {NEXT_IDLE_TARGET//60} min\n"
        f"Battles today: {BATTLES_TODAY}\n"
        f"Archive: {archive_count}\n"
        f"Users: {user_count}\n"
        f"Queue size: {SUBMISSION_QUEUE.qsize()}"
    )
    await update.message.reply_text(status, parse_mode="Markdown")

async def postnow_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    await send_engagement(context.application)
    await update.message.reply_text("✅ Sent.")

async def recycle_now_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    await recycle_archive(context.application)
    await update.message.reply_text("✅ Recycle attempted.")

async def battle_now_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    ok = await queen_battle(context.application)
    await update.message.reply_text("✅ Battle started." if ok else "⚠️ Need ≥2 photos in archive.")

async def ban_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: /ban USER_ID")
        return
    try:
        uid = int(context.args[0])
        await context.bot.ban_chat_member(GROUP_ID, uid)
        await update.message.reply_text(f"🚫 Banned {uid}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unban_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: /unban USER_ID")
        return
    try:
        uid = int(context.args[0])
        await context.bot.unban_chat_member(GROUP_ID, uid)
        await update.message.reply_text(f"✅ Unbanned {uid}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def stats_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM archive")
    archive = c.fetchone()[0]
    c.execute("SELECT user_id, first_name, referral_count FROM users ORDER BY referral_count DESC LIMIT 5")
    top = c.fetchall()
    conn.close()
    text = f"📊 *Stats*\n\nUsers: {users}\nArchive: {archive}\n\n*Top inviters:*\n"
    for uid, name, cnt in top:
        text += f"• {name or uid}: {cnt}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ================ ERROR HANDLER ================
async def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")

# ================ MAIN ================
def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    # Anti-spam (highest priority)
    application.add_handler(
        MessageHandler(
            filters.Chat(GROUP_ID) & (filters.TEXT | filters.CAPTION),
            anti_spam_filter
        ),
        group=-2
    )

    # Auto-kick foreign bots
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS & filters.Chat(GROUP_ID),
            auto_kick_foreign_bots
        ),
        group=-2
    )

    # Service messages cleanup
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.ALL & filters.Chat(GROUP_ID),
            auto_delete_service_messages
        ),
        group=-1
    )

    # Group activity tracker (logs to admin + nudges + reactions)
    application.add_handler(
        MessageHandler(
            filters.Chat(GROUP_ID) & ~filters.StatusUpdate.ALL,
            track_group_activity
        ),
        group=0
    )

    # User commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("invite", invite_cmd))
    application.add_handler(CommandHandler("share", share_cmd))
    application.add_handler(CommandHandler("mystats", mystats_cmd))

    # Admin commands
    application.add_handler(CommandHandler("autopilot_on", autopilot_on))
    application.add_handler(CommandHandler("autopilot_off", autopilot_off))
    application.add_handler(CommandHandler("autopilot_status", autopilot_status))
    application.add_handler(CommandHandler("postnow", postnow_cmd))
    application.add_handler(CommandHandler("recycle_now", recycle_now_cmd))
    application.add_handler(CommandHandler("battle_now", battle_now_cmd))
    application.add_handler(CommandHandler("ban", ban_cmd))
    application.add_handler(CommandHandler("unban", unban_cmd))
    application.add_handler(CommandHandler("stats", stats_cmd))

    # Private DMs
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            submit_private
        )
    )

    # Inline mode
    application.add_handler(InlineQueryHandler(inline_share))

    # Error handler
    application.add_error_handler(error_handler)

    # Start background workers
    async def post_init(app):
        asyncio.create_task(autopilot_loop(app))
        asyncio.create_task(submission_worker(app))
    application.post_init = post_init

    logger.info("🚀 Samadanam Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
