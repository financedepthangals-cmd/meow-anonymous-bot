# ================================================================
# SAMADANAM BOT — Full Production Code
# Features: Anti-spam, Autopilot, Unlimited posting, Queen Battles
# ================================================================

import os
import re
import sqlite3
import random
import asyncio
import logging
import time
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ChatPermissions, InputMediaPhoto
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
ADMIN_LOG_CHAT_ID = 8438801421

POST_HEADER = "💬 Love Chat ❤️\n🫥 Anonymous via Samadanam\n\n"

# Feature flags
QR_WATERMARK_ENABLED = False        # activate at 10K members
IMAGE_MODERATION_ENABLED = False    # activate at 1K members

# Anti-spam
MIN_SEND_INTERVAL = 1.8
USER_SUBMIT_LIMIT = 0   # 0 = unlimited
USER_SUBMIT_WINDOW = 3600
NEW_MEMBER_RESTRICTION_HOURS = 24

# Autopilot timing
AUTOPOST_MIN_IDLE = 35 * 60
AUTOPOST_MAX_IDLE = 75 * 60
AUTOPOST_MIN_GAP = 25 * 60
AUTOPOST_MAX_GAP = 90 * 60

# Recycling
RECYCLE_MIN_GAP = 2 * 3600
RECYCLE_MAX_GAP = 4 * 3600
RECYCLE_COOLDOWN_DAYS = 7

# Queen Battles
BATTLE_MIN_GAP = 90 * 60
BATTLE_PHOTO_COOLDOWN_DAYS = 14
BATTLE_DAILY_MIN = 2
BATTLE_DAILY_MAX = 4

# Invite reminders
INVITE_REMINDER_CHANCE = 0.33

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
        tier TEXT DEFAULT 'Member',
        joined_at REAL, banned INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS submissions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, ts REAL
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

# ================ PROMPT POOLS ================
ENGAGEMENT_TEXTS_ML = [
    "🫥 ഒരു വരി മതി. ഇപ്പോൾ മനസ്സിൽ ഉള്ളത് എന്താണ്? @samadanambot ലേക്ക് ഇടൂ.",
    "👀 silent readers, എവിടെയാണ്? ഒരാൾ തുടങ്ങൂ.",
    "💭 പറയാത്ത ഒരു കാര്യം ഇപ്പോൾ പറയാം. പേര് വേണ്ട. @samadanambot",
    "🌙 ഈ നേരം എന്തിനെ കുറിച്ച് ചിന്തിക്കുന്നു?",
    "🫥 ഒരു secret drop ചെയ്യാം. ബാക്കി ഞങ്ങൾ വായിക്കും.",
    "👑 നിങ്ങളുടെ റാണികളെ കാണിക്കൂ... ആരാ ആ മനസ്സിൽ ഇപ്പോഴും രാജ്യം ഭരിക്കുന്നത്?",
    "💌 പറയാത്ത സ്നേഹം, അയയ്ക്കാത്ത സന്ദേശം — ഇവിടെ ഇടൂ.",
    "🔥 ഇന്നു രാത്രി എന്തു പറയാനും സ്ഥലമുണ്ട്. ബോട്ടിൽ ഇടൂ.",
]

ENGAGEMENT_TEXTS_EN = [
    "🫥 One line is enough. What's on your mind right now? Drop it in @samadanambot",
    "👀 Silent readers, where you at? Someone start.",
    "💭 Say the thing you've never said. Name stays hidden. @samadanambot",
    "🌙 What's keeping you up tonight?",
    "🫥 Drop one secret. We'll read the rest.",
    "👑 Show us your queens... who's still ruling that mind of yours?",
    "💌 The message you didn't send, the words you didn't say — bring them here.",
    "🔥 Tonight, anything goes. Drop it in the bot.",
]

LATE_NIGHT_ML = [
    "🌙 രാത്രി ആയി. നിങ്ങളുടെ റാണി ഇപ്പോഴും ഉറങ്ങാൻ വിട്ടിട്ടില്ല, അല്ലേ?",
    "🫥 ഉറങ്ങാത്ത മനസ്സിൽ ഉള്ളത് എന്തായാലും ബോട്ടിൽ ഇടൂ.",
    "🔥 പകൽ കാണുമ്പോൾ മാന്യത. രാത്രി മനസ്സിൽ വരുന്നത് വേറെയാണ്. പറയൂ.",
    "🌃 ഉറക്കം വരാത്ത മനസ്സ് — ഒരു വരി മതി. @samadanambot",
]

LATE_NIGHT_EN = [
    "🌙 Late night. Your queen still won't let you sleep, will she?",
    "🫥 Whatever's keeping you awake — drop it in the bot.",
    "🔥 Daytime decent. Night-time different. Say it.",
    "🌃 Restless mind — one line is enough. @samadanambot",
]

BOT_REMINDERS_ML = [
    "📩 ഓർമ്മിപ്പിക്കുന്നു: ഗ്രൂപ്പിൽ നേരിട്ട് ഇട്ടാൽ പേര് കാണും. @samadanambot ലേക്ക് ഇടൂ.",
    "🫥 പേര് മറയ്ക്കാൻ ബോട്ട് ഉണ്ടല്ലോ → @samadanambot",
    "💋 Anonymous post വേണോ? @samadanambot ലേക്ക് അയക്കൂ.",
]

BOT_REMINDERS_EN = [
    "📩 Reminder: direct posts show your name. Stay hidden via @samadanambot",
    "🫥 The bot keeps your name hidden → @samadanambot",
    "💋 Want to post anonymously? Send it to @samadanambot",
]

MEDIA_REACTIONS_ML = [
    "🔥 scene undu ithil",
    "👀 ee drop kandittu silent aayi pokan pattilla",
    "🫥 dangerous post aanu",
    "ayyo ee vibe aaru handle cheyyum 😭",
]

MEDIA_REACTIONS_EN = [
    "🔥 this one has presence",
    "👀 dangerous drop",
    "🫥 the energy is real",
    "okay this changed the mood",
]

POLLS = [
    ("🌙 Tonight's vibe?", ["Love 💗", "Lust 🔥", "Lonely 🥺", "Chaos 🌪️"]),
    ("👀 Pick your mood", ["Soft 🫧", "Bold 🔥", "Sad 💭", "Wild 🌪️"]),
    ("🫥 ഇപ്പോൾ?", ["സ്നേഹം 💗", "ദേഷ്യം 🔥", "ഒറ്റപ്പെടൽ 🥺", "ചാവി പോയി 🌪️"]),
]

BATTLE_HEADER_ML = "👑💦 റാണി പോര് 👑\nഇന്നത്തെ duel. ആരാ winner?"
BATTLE_HEADER_EN = "👑💦 Queen Battle 👑\nTonight's duel. Pick your side."

# ================ ANTI-SPAM ================
SPAM_KEYWORDS = [
    "onlyfans", "only fans", "free video", "free videos",
    "hot video", "hot girl", "leaked", "click here",
    "watch now", "watch fast", "100% free", "$0",
    "no pay", "no money", "unlocked", "real girl home",
    "best xxx", "xxxx", "porn", "premium free",
    "telegram.me/+", "t.me/+", "t.me/joinchat",
    "bit.ly", "tinyurl", "shorturl", "cutt.ly",
    "👇👇👇", "👆👆👆"
]

SPAM_PATTERNS = [
    r"https?://", r"www\.", r"t\.me/", r"telegram\.me/", r"@\w+bot"
]

BANNED_TERMS = [
    "child", "minor", "underage", "school girl", "kid",
    "rape", "force", "drug", "cocaine", "weed sell",
    "gun", "weapon", "scam"
]

async def anti_spam_filter(update, context):
    """Auto-delete spam links and ban repeat offenders"""
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

    text = (msg.text or msg.caption or "").lower()
    if not text:
        return

    is_spam = False

    # Check banned terms first (always blocked)
    for kw in BANNED_TERMS:
        if kw in text:
            is_spam = True
            break

    # Check spam keywords
    if not is_spam:
        for kw in SPAM_KEYWORDS:
            if kw in text:
                is_spam = True
                break

    # Check links (allow only samadanambot)
    if not is_spam:
        for pattern in SPAM_PATTERNS:
            if re.search(pattern, text):
                if "samadanambot" not in text:
                    is_spam = True
                    break

    if not is_spam:
        return

    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id
        )

        # Track strikes
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
            except Exception as e:
                logger.error(f"Ban failed: {e}")

            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🚫 BANNED SPAMMER\n"
                        f"User: {user.first_name} (@{user.username})\n"
                        f"ID: {user.id}\n"
                        f"Strikes: {strikes}\n"
                        f"Text: {text[:150]}"
                    )
                except:
                    pass
        else:
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"⚠️ Spam deleted (strike 1)\n"
                        f"User: {user.first_name} (@{user.username})\n"
                        f"ID: {user.id}\n"
                        f"Text: {text[:150]}"
                    )
                except:
                    pass
    except Exception as e:
        logger.error(f"Anti-spam error: {e}")

async def restrict_new_members(update, context):
    """Restrict new members from sending media for 24h"""
    if not update.message or not update.message.new_chat_members:
        return
    if update.effective_chat.id != GROUP_ID:
        return

    until = datetime.utcnow() + timedelta(hours=NEW_MEMBER_RESTRICTION_HOURS)

    for new_member in update.message.new_chat_members:
        if new_member.is_bot:
            continue
        try:
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=new_member.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                ),
                until_date=until
            )
        except Exception as e:
            logger.error(f"Restrict error: {e}")

async def auto_delete_service_messages(update, context):
    """Hide join/leave/promote service messages"""
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
        except Exception as e:
            logger.warning(f"Couldn't delete service msg: {e}")

# ================ AUTOPILOT STATE ================
AUTO_PILOT_ENABLED = True
LAST_GROUP_ACTIVITY_TS = time.time()
LAST_AUTOPILOT_POST_TS = 0
LAST_RECYCLE_TS = 0
LAST_BATTLE_TS = 0
BATTLES_TODAY = 0
BATTLE_DAY = datetime.utcnow().date()
NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
NEXT_GAP_TARGET = random.randint(AUTOPOST_MIN_GAP, AUTOPOST_MAX_GAP)
NEXT_RECYCLE_GAP = random.randint(RECYCLE_MIN_GAP, RECYCLE_MAX_GAP)

def mark_group_activity():
    global LAST_GROUP_ACTIVITY_TS
    LAST_GROUP_ACTIVITY_TS = time.time()

def reset_idle_target():
    global NEXT_IDLE_TARGET, NEXT_GAP_TARGET
    NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
    NEXT_GAP_TARGET = random.randint(AUTOPOST_MIN_GAP, AUTOPOST_MAX_GAP)

def is_late_night():
    h = datetime.utcnow().hour + 5  # IST approx
    h = h % 24
    return h >= 22 or h < 4

def is_dawn():
    h = (datetime.utcnow().hour + 5) % 24
    return 4 <= h < 8

def pick_prompt():
    """Choose random prompt with weighted mix"""
    r = random.random()
    use_ml = random.random() < 0.5

    if r < 0.20:  # 20% bot reminders
        return random.choice(BOT_REMINDERS_ML if use_ml else BOT_REMINDERS_EN)
    elif r < 0.30 and is_late_night():  # 10% late night
        return random.choice(LATE_NIGHT_ML if use_ml else LATE_NIGHT_EN)
    else:
        return random.choice(ENGAGEMENT_TEXTS_ML if use_ml else ENGAGEMENT_TEXTS_EN)

# ================ AUTOPILOT ENGINES ================
async def send_engagement(app):
    if is_dawn():
        return
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
        logger.error(f"Engagement post error: {e}")

async def recycle_archive(app):
    try:
        conn = db()
        c = conn.cursor()
        cutoff_recycle = time.time() - (RECYCLE_COOLDOWN_DAYS * 86400)
        cutoff_age = time.time() - 86400  # at least 1 day old
        c.execute("""SELECT id, file_id, media_type, caption FROM archive
                     WHERE last_recycled < ? AND ts < ?
                     ORDER BY RANDOM() LIMIT 1""", (cutoff_recycle, cutoff_age))
        row = c.fetchone()
        if not row:
            conn.close()
            return
        aid, file_id, media_type, caption = row
        cap = POST_HEADER + (caption or "")
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
        gap = now - LAST_AUTOPILOT_POST_TS

        # Engagement engine
        if idle >= NEXT_IDLE_TARGET and gap >= NEXT_GAP_TARGET and not is_dawn():
            await send_engagement(app)

        # Recycle engine
        if (now - LAST_RECYCLE_TS) >= NEXT_RECYCLE_GAP:
            await recycle_archive(app)

        # Battle engine
        if (BATTLES_TODAY < target_battles
            and (now - LAST_BATTLE_TS) >= BATTLE_MIN_GAP
            and idle >= 15 * 60
            and not is_dawn()):
            await queen_battle(app)

# ================ USER HANDLERS ================
async def start(update, context):
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
        f"🫥 Send me anything (text, photo, video) and I'll post it anonymously in the group.\n"
        f"📩 Your name stays hidden.\n\n"
        f"👉 Join: {GROUP_LINK}\n\n"
        f"Commands:\n"
        f"/invite — get your invite link\n"
        f"/share — share Samadanam\n"
        f"/mystats — your stats"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")

async def submit_private(update, context):
    """Handle DMs to bot — post anonymously to group"""
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    msg = update.message
    if not msg:
        return

    text = (msg.text or msg.caption or "").lower()

    # Block banned terms in submissions too
    for term in BANNED_TERMS:
        if term in text:
            await msg.reply_text("🚫 Content blocked. Try a different message.")
            return

    try:
        if msg.text:
            await context.bot.send_message(chat_id=GROUP_ID, text=POST_HEADER + msg.text)
        elif msg.photo:
            file_id = msg.photo[-1].file_id
            cap = POST_HEADER + (msg.caption or "")
            await context.bot.send_photo(chat_id=GROUP_ID, photo=file_id, caption=cap)
            # Save to archive
            conn = db()
            c = conn.cursor()
            c.execute("""INSERT INTO archive(file_id, media_type, caption, ts)
                         VALUES(?, ?, ?, ?)""",
                      (file_id, "photo", msg.caption or "", time.time()))
            conn.commit()
            conn.close()
        elif msg.video:
            file_id = msg.video.file_id
            cap = POST_HEADER + (msg.caption or "")
            await context.bot.send_video(chat_id=GROUP_ID, video=file_id, caption=cap)
            conn = db()
            c = conn.cursor()
            c.execute("""INSERT INTO archive(file_id, media_type, caption, ts)
                         VALUES(?, ?, ?, ?)""",
                      (file_id, "video", msg.caption or "", time.time()))
            conn.commit()
            conn.close()
        elif msg.animation:
            file_id = msg.animation.file_id
            cap = POST_HEADER + (msg.caption or "")
            await context.bot.send_animation(chat_id=GROUP_ID, animation=file_id, caption=cap)
        else:
            await msg.reply_text("📩 Send text, photo, video or GIF.")
            return

        # Confirmation + occasional invite reminder
        if random.random() < INVITE_REMINDER_CHANCE:
            ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
            use_ml = random.random() < 0.5
            if use_ml:
                reply = (f"✅ Posted anonymously in Love Chat ❤️\n\n"
                         f"🚀 സമാദാനം massive ആക്കാം!\n"
                         f"ഒരാളെ invite ചെയ്യൂ:\n{ref_link}")
            else:
                reply = (f"✅ Posted anonymously in Love Chat ❤️\n\n"
                         f"🚀 Help Samadanam grow!\n"
                         f"Invite a friend:\n{ref_link}")
            await msg.reply_text(reply)
        else:
            await msg.reply_text("✅ Posted anonymously in Love Chat ❤️")
    except Exception as e:
        logger.error(f"Submit error: {e}")
        await msg.reply_text("⚠️ Couldn't post. Try again.")

async def invite_cmd(update, context):
    user = update.effective_user
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    text = (
        f"📩 *Your invite link:*\n`{ref_link}`\n\n"
        f"Forward any of these to friends:\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🫥 ഒരു new anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
        f"Confessions, queens, secrets — പേര് കാണിക്കാതെ share ചെയ്യാം.\n"
        f"👉 {ref_link}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🫥 found this anonymous Malayalam group...\n"
        f"people share secrets, queens, fantasies here.\n"
        f"👉 {ref_link}\n"
        f"━━━━━━━━━━━━━━━"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share anywhere", switch_inline_query=f"🫥 Anonymous Malayalam group → {ref_link}")],
        [InlineKeyboardButton("📋 Open Group", url=GROUP_LINK)]
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def share_cmd(update, context):
    user = update.effective_user
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    share_text = f"🫥 found this anonymous Malayalam group... people share secrets here 👉 {ref_link}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share to any chat", switch_inline_query=share_text)],
        [InlineKeyboardButton("📋 Copy link", url=ref_link)]
    ])
    await update.message.reply_text("📨 Tap below to share Samadanam anywhere.", reply_markup=keyboard)

async def mystats_cmd(update, context):
    user = update.effective_user
    conn = db()
    c = conn.cursor()
    c.execute("SELECT referral_count, tier FROM users WHERE user_id=?", (user.id,))
    row = c.fetchone()
    conn.close()
    if not row:
        await update.message.reply_text("No stats yet. Send /start first.")
        return
    refs, tier = row
    await update.message.reply_text(
        f"📊 *Your Samadanam Stats*\n\n"
        f"Invites: {refs}\n"
        f"Tier: {tier}",
        parse_mode="Markdown"
    )

async def inline_share(update, context):
    user = update.inline_query.from_user
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    results = [
        InlineQueryResultArticle(
            id="ml",
            title="Share in Malayalam",
            input_message_content=InputTextMessageContent(
                f"🫥 ഒരു new anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
                f"Confessions, queens, secrets — പേര് കാണിക്കാതെ share ചെയ്യാം.\n"
                f"👉 {ref_link}"
            )
        ),
        InlineQueryResultArticle(
            id="en",
            title="Share in English",
            input_message_content=InputTextMessageContent(
                f"🫥 found this anonymous Malayalam group...\n"
                f"people share secrets, queens, fantasies here.\n"
                f"👉 {ref_link}"
            )
        )
    ]
    await update.inline_query.answer(results, cache_time=10)

# ================ GROUP MESSAGE TRACKER ================
async def track_group_activity(update, context):
    """Mark activity when humans post (not bot)"""
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.id != GROUP_ID:
        return
    user = update.message.from_user
    if not user or user.is_bot:
        return
    mark_group_activity()

    # Random media reaction (~25% chance)
    if (update.message.photo or update.message.video) and random.random() < 0.25:
        await asyncio.sleep(random.randint(5, 18))
        use_ml = random.random() < 0.5
        reply = random.choice(MEDIA_REACTIONS_ML if use_ml else MEDIA_REACTIONS_EN)
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=reply,
                reply_to_message_id=update.message.message_id
            )
        except:
            pass

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
        f"🤖 *Samadanam Autopilot*\n\n"
        f"Status: {'✅ ON' if AUTO_PILOT_ENABLED else '⏸ OFF'}\n"
        f"Idle: {idle//60} min\n"
        f"Next idle target: {NEXT_IDLE_TARGET//60} min\n"
        f"Battles today: {BATTLES_TODAY}\n"
        f"Archive size: {archive_count}\n"
        f"Total users: {user_count}\n"
    )
    await update.message.reply_text(status, parse_mode="Markdown")

async def postnow_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    await send_engagement(context.application)
    await update.message.reply_text("✅ Sent.")

async def recycle_now_cmd(update, context):
    if not is_admin(update.effective_user.id): return
    await recycle_archive(context.application)
    await update.message.reply_text("✅ Recycled.")

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

    # Anti-spam (HIGHEST priority — runs first)
    application.add_handler(
        MessageHandler(
            filters.Chat(GROUP_ID) & (filters.TEXT | filters.CAPTION),
            anti_spam_filter
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

    # New member restriction
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS & filters.Chat(GROUP_ID),
            restrict_new_members
        ),
        group=-1
    )

    # Group activity tracker (after anti-spam)
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

    # Private DMs to bot (anonymous submissions)
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

    # Start autopilot
    async def post_init(app):
        asyncio.create_task(autopilot_loop(app))
    application.post_init = post_init

    logger.info("🚀 Samadanam Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
