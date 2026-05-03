import asyncio
import logging
import os
import random
import re
import sqlite3
import time
from datetime import datetime
from urllib.parse import quote

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
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
ADMIN_LOG_CHAT_ID = 8438801421

# Future-gated features
QR_WATERMARK_ENABLED = False  # Flip True at 10K members
IMAGE_MODERATION_ENABLED = False  # Flip True at 1K members

# Anti-spam
MIN_SEND_INTERVAL = 1.8
USER_SUBMIT_LIMIT = 5
USER_SUBMIT_WINDOW = 3600  # 1 hour
GROUP_REMINDER_COOLDOWN = 3600

# Autopilot timing
AUTOPOST_MIN_IDLE = 35 * 60
AUTOPOST_MAX_IDLE = 75 * 60
AUTOPOST_MIN_GAP = 25 * 60
AUTOPOST_MAX_GAP = 90 * 60
HUMAN_ACTIVITY_BUFFER = 15 * 60  # Skip bot drops if humans active in last 15 min

# Recycling
RECYCLE_MIN_AGE_HOURS = 24
RECYCLE_COOLDOWN_DAYS = 7
RECYCLE_MIN_INTERVAL = 2 * 3600
RECYCLE_MAX_INTERVAL = 4 * 3600

# Queen Battles
BATTLE_MIN_GAP = 90 * 60  # 90 min between battles
BATTLE_PHOTO_COOLDOWN_DAYS = 14
BATTLE_MIN_ARCHIVE = 10
BATTLE_DAILY_MIN = 2
BATTLE_DAILY_MAX = 4

# Reactions
MEDIA_COMMENT_CHANCE = 0.45
TEXT_COMMENT_CHANCE = 0.07
FOLLOWUP_CHANCE = 0.20

# Database
DB_PATH = "samadanam_bot.db"

# Link / banned content filters
LINK_REGEX = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+|"
    r"\b[a-zA-Z0-9-]+\.(com|net|org|io|me|in|co|app|ai|gg|ly|to|tv|info|biz|xyz|site|online|store|shop|cc|pk|uk|us|de|ru)\b)",
    re.IGNORECASE,
)

BANNED_TERMS = [
    "child", "child porn", "childporn", "cp",
    "kid sex", "underage", "minor sex", "minor nude",
    "schoolgirl sex", "teen sex", "13yo", "14yo", "15yo", "loli",
    "young girl nude", "kid nudes",
    "drugs for sale", "selling mdma", "buy cocaine",
    "free money click", "double your money", "send btc to",
]

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row

# Global state
SEND_LOCK = asyncio.Lock()
LAST_SEND_TIME = 0.0
LAST_GROUP_ACTIVITY_TS = time.time()
LAST_AUTOPILOT_POST_TS = 0.0
LAST_RECYCLE_TS = 0.0
LAST_BATTLE_TS = 0.0
TODAYS_BATTLES_PLANNED = 0
TODAYS_BATTLES_DONE = 0
TODAYS_BATTLE_DATE = None

AUTO_PILOT_ENABLED = True
RECYCLER_ENABLED = True
BATTLES_ENABLED = True

NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
NEXT_GAP_TARGET = random.randint(AUTOPOST_MIN_GAP, AUTOPOST_MAX_GAP)
NEXT_RECYCLE_TARGET = random.randint(RECYCLE_MIN_INTERVAL, RECYCLE_MAX_INTERVAL)


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
                referrals_count INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'new',
                joined_group INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
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
        db.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                media_type TEXT NOT NULL,
                original_caption TEXT,
                submitter_id INTEGER,
                submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_recycled_at TEXT,
                last_battle_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                user_id INTEGER NOT NULL,
                submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)


def upsert_user(user, referrer_id=None):
    with db:
        existing = db.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,)).fetchone()
        if not existing:
            db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, referrer_id)
                VALUES (?, ?, ?, ?, ?)
            """, (user.id, user.username or "", user.first_name or "", user.last_name or "", referrer_id))
            if referrer_id and referrer_id != user.id:
                already = db.execute("SELECT 1 FROM referrals WHERE referred_user_id=?", (user.id,)).fetchone()
                if not already:
                    db.execute("INSERT INTO referrals (referrer_id, referred_user_id) VALUES (?, ?)",
                               (referrer_id, user.id))
                    db.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id=?",
                               (referrer_id,))
        else:
            db.execute("""
                UPDATE users SET username=?, first_name=?, last_name=? WHERE user_id=?
            """, (user.username or "", user.first_name or "", user.last_name or "", user.id))


def is_banned(user_id):
    row = db.execute("SELECT 1 FROM bans WHERE user_id=?", (user_id,)).fetchone()
    return bool(row)


def can_submit(user_id):
    """Rate limit: USER_SUBMIT_LIMIT per USER_SUBMIT_WINDOW seconds."""
    cutoff = datetime.utcnow().timestamp() - USER_SUBMIT_WINDOW
    count = db.execute(
        "SELECT COUNT(*) FROM submissions WHERE user_id=? AND submitted_at >= datetime(?, 'unixepoch')",
        (user_id, cutoff)
    ).fetchone()[0]
    return count < USER_SUBMIT_LIMIT


def log_submission(user_id):
    with db:
        db.execute("INSERT INTO submissions (user_id) VALUES (?)", (user_id,))


def get_user_referrals(user_id):
    row = db.execute("SELECT referrals_count FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["referrals_count"] if row else 0


def get_tier(referrals):
    if referrals >= 100: return ("🏆", "Hall of Fame")
    if referrals >= 50:  return ("👑", "Legend")
    if referrals >= 25:  return ("💎", "VIP")
    if referrals >= 10:  return ("🔥", "Promoter")
    if referrals >= 5:   return ("⭐", "Active")
    if referrals >= 1:   return ("🌱", "Member")
    return ("🫥", "New")


def update_tier_if_changed(user_id, app):
    row = db.execute("SELECT referrals_count, tier FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return None
    refs = row["referrals_count"]
    emoji, tier_name = get_tier(refs)
    if row["tier"] != tier_name:
        with db:
            db.execute("UPDATE users SET tier=? WHERE user_id=?", (tier_name, user_id))
        return (emoji, tier_name, refs)
    return None


# ================== HELPERS ==================

def get_referral_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


def get_share_link(user_id):
    use_ml = random.random() < 0.5
    ref_link = get_referral_link(user_id)
    if use_ml:
        text = (
            f"🫥 ഒരു new anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
            f"Confessions, queens, secrets, fantasies — പേര് കാണിക്കാതെ share ചെയ്യാം.\n\n"
            f"👉 {ref_link}"
        )
    else:
        text = (
            f"🫥 found this anonymous Malayalam group...\n"
            f"people share secrets, queens, fantasies here.\n\n"
            f"👉 {ref_link}"
        )
    return f"https://t.me/share/url?url={quote(ref_link)}&text={quote(text)}"


def contains_link(text):
    if not text:
        return False
    return bool(LINK_REGEX.search(text))


def contains_banned(text):
    if not text:
        return False
    low = text.lower()
    return any(term in low for term in BANNED_TERMS)


def is_late_night():
    h = datetime.now().hour
    return h >= 22 or h < 4


def is_morning():
    h = datetime.now().hour
    return 6 <= h < 11


def is_dawn():
    h = datetime.now().hour
    return 4 <= h < 8


def mark_group_activity():
    global LAST_GROUP_ACTIVITY_TS
    LAST_GROUP_ACTIVITY_TS = time.time()


def reset_idle_targets():
    global NEXT_IDLE_TARGET, NEXT_GAP_TARGET
    NEXT_IDLE_TARGET = random.randint(AUTOPOST_MIN_IDLE, AUTOPOST_MAX_IDLE)
    NEXT_GAP_TARGET = random.randint(AUTOPOST_MIN_GAP, AUTOPOST_MAX_GAP)


def reset_recycle_target():
    global NEXT_RECYCLE_TARGET
    NEXT_RECYCLE_TARGET = random.randint(RECYCLE_MIN_INTERVAL, RECYCLE_MAX_INTERVAL)


# ================== PROMPT POOLS ==================

ENGAGEMENT_ML = [
    "👀 നിശബ്ദമായി നോക്കിയിരിക്കുന്നവർ... ഇന്നത്തെ രഹസ്യം ആരാ ആദ്യം വിടുന്നത്?",
    "🫥 ഒരിക്കലും തുറന്ന് പറയാത്ത ഒരു ആഗ്രഹം ഉണ്ടെങ്കിൽ ബോട്ടിൽ ഇടൂ.",
    "❤️ ഒരാൾക്ക് അയക്കണം എന്ന് തോന്നി അയക്കാത്ത സന്ദേശം എന്താണ്?",
    "💭 ഇപ്പോഴും മനസ്സിൽ നിൽക്കുന്ന ഒരാൾ ഉണ്ടോ?",
    "👀 ആദ്യം ആകർഷിക്കുന്നത് എന്താണ് — കണ്ണ്, vibe, ശബ്ദം, അതോ വാക്കുകളോ?",
    "🎭 സത്യം പറയൂ — ഇന്ന് ഏത് mood ആണ്?",
    "💭 നിങ്ങളുടെ ഒരു unpopular opinion എന്താണ്?",
    "👑 നിങ്ങളുടെ റാണികളെ കാണിക്കൂ...",
    "🔥 റാണികളെ കുറിച്ച് നിങ്ങൾ പറയാത്തത് എന്താണ്? @samadanambot ലേക്ക് ഇടൂ.",
    "🫥 ഇന്നു ഒരാൾക്കു അയക്കാൻ പറ്റാത്ത സന്ദേശം ഉണ്ടോ? ഇവിടെ ഇടൂ.",
    "💌 പറയാത്ത സ്നേഹം, അയയ്ക്കാത്ത സന്ദേശം, റാണിയോടുള്ള മൗനം — ഇവിടെ ഇടൂ.",
    "🎯 ഒരു emoji മാത്രം reply ചെയ്യൂ. Mood നോക്കാം.",
    "💬 ഇവിടെ ഏത് തരം confessions കൂടുതൽ വായിക്കാൻ ആഗ്രഹിക്കുന്നു?",
    "👀 ഈ group-il silent aayi ഇരിക്കുന്നവർ ആണ് usually biggest stories ഉള്ളവർ.",
    "🫥 പേര് വേണ്ട. കഥ മതി. അവളെ ഇങ്ങ് ഇറക്കി വിടൂ.",
]

ENGAGEMENT_EN = [
    "👀 Silent readers... who's dropping the first secret tonight?",
    "🫥 One thought you've never said out loud — bot is open.",
    "❤️ A message you wanted to send but didn't. What was it?",
    "💭 Someone still living in your head rent-free?",
    "👀 What attracts first — eyes, voice, vibe, or words?",
    "🎭 Be honest — what vibe are you carrying tonight?",
    "💭 One unpopular opinion you hold strongly?",
    "👑 Show us your queens...",
    "🔥 What haven't you said about your queen? Bot keeps your name hidden.",
    "🫥 Got something to say anonymously? @samadanambot is open.",
    "💌 The message you couldn't send — bring it here.",
    "🎯 Reply using only one emoji. Let's see the mood.",
    "💬 What kind of confessions do you want more of?",
    "👀 Silent readers usually have the biggest stories.",
    "🫥 No name needed. Just the story. Drop her here.",
]

LATE_NIGHT_ML = [
    "🌃 ഇപ്പോഴാണ് യഥാർത്ഥ സമയം. പകലത്തെ മുഖംമൂടി ഇപ്പോൾ വേണ്ട.",
    "🫥 പേര് വേണ്ട. ഫീലിംഗ് മാത്രം മതി.",
    "💭 ഒരു വരി കുമ്പസാരം. വിശദീകരണം വേണ്ട.",
    "🌙 രാത്രി ആയി. നിങ്ങളുടെ റാണി ഇപ്പോഴും ഉറങ്ങാൻ വിടുന്നില്ല, അല്ലേ? അവളെ ഒന്ന് കാണിക്കൂ. നമുക്ക് പൊളിക്കാം 🔥",
    "🫥 ആ റാണിയെ കുറിച്ച് ഒരു ഫാന്റസി, ഒരു ഓർമ്മ, ഒരു ദേഷ്യം — ഒന്ന് വിട്ടാലോ? അവളെ ഇങ്ങ് ഇറക്കി വിടൂ.",
    "🌙 രാത്രി കൂടുമ്പോൾ സത്യവും ധൈര്യവും കൂടും. ആരാ തുടങ്ങുന്നത്? എന്തും പറയാം — രഹസ്യം, ആഗ്രഹം, ദേഷ്യം, സ്നേഹം. ബോട്ടിൽ ഇടൂ → @samadanambot",
    "🌃 ഉറങ്ങാൻ പറ്റാത്ത രാത്രിയിൽ ആ റാണിയെ കുറിച്ച് ഒരു വരി. ബാക്കി ഞങ്ങൾ നോക്കാം 😌",
    "👀 ഉറങ്ങാതെ ഇരിക്കുന്നവർക്കു ഒരു കാര്യം പറയാനുണ്ടാകും.",
    "🔥 ഇന്നു രാത്രി പൊളിക്കാൻ ഒരു റാണിയുടെ കഥ മതി. ആരാ ആദ്യം?",
    "🫥 ഇന്നു രാത്രി എന്തു പറയാനും സ്ഥലമുണ്ട്. ബോട്ടിൽ ഇടൂ. ബാക്കി ഞങ്ങൾ നോക്കാം.",
    "🌙 ഫാന്റസി ആയാലും ഓർമ്മ ആയാലും ദേഷ്യം ആയാലും — ഇറക്കി വിടൂ. നമുക്ക് രാത്രി കത്തിക്കാം.",
    "💭 ഉറക്കം വരാത്ത മനസ്സിൽ ഒരു റാണി ഉണ്ടോ? ഒരു വരി മതി. ബോട്ടിൽ ഇടൂ → @samadanambot",
]

LATE_NIGHT_EN = [
    "🌃 This is the real hour. Daytime masks off.",
    "🫥 No name needed. Just the feeling.",
    "💭 One line. No explanation.",
    "🌙 Late night. Your queen still won't let you sleep, will she? Show her to us. Let's burn this night down 🔥",
    "🫥 A fantasy, a memory, a rage — about that queen. Just drop her here.",
    "🌙 Late night brings out truth. Share anything — secret, desire, anger, love → @samadanambot",
    "🔥 One queen's story is all we need to set tonight on fire. Who's first?",
    "👀 If you're awake, you have something to say.",
    "🫥 Tonight there's space for everything. Drop it in the bot. We've got the rest.",
    "💭 Whatever's keeping you awake — drop it. One line or a whole story.",
]

MORNING_ML = [
    "☀️ Good morning സമാദാനം. ഇന്നത്തെ ദിവസത്തേക്ക് കൊണ്ടുപോകുന്ന ഒരു കാര്യം ഏത്?",
    "🌸 രാവിലെ vibe ഒറ്റ വാക്കിൽ പറയൂ.",
    "☕ ഉണർന്നപ്പോൾ മനസ്സിൽ വന്ന ഒരു ചിന്ത?",
    "🌅 ഇന്നു ആരെയാണ് ആദ്യം ഓർത്തത്?",
]

MORNING_EN = [
    "☀️ Good morning Samadanam. One thing you're carrying into today?",
    "🌸 Drop one word for your morning vibe.",
    "☕ One thought you woke up with?",
    "🌅 Who came to mind first this morning?",
]

BOT_REMINDERS_ML = [
    "📩 ഓർമ്മിപ്പിക്കുന്നു: ഗ്രൂപ്പിൽ നേരിട്ട് ഇട്ടാൽ പേര് കാണും. പേര് മറയ്ക്കണോ? @samadanambot ലേക്ക് ഇടൂ.",
    "🫥 anonymous ആയി പറയണം എന്നുണ്ടോ? @samadanambot ഉണ്ടല്ലോ. പേര് വേണ്ട, കഥ മതി.",
    "👀 silent reader ആണോ? ഒരു ദിവസം @samadanambot ലേക്ക് ഒരു വരി ഇടൂ. ആരും അറിയില്ല.",
    "💭 പറയാൻ തോന്നിയത് bot-il ഇടൂ → @samadanambot. ഞങ്ങൾ ബാക്കി നോക്കാം.",
    "🔥 confession, fantasy, secret — എന്തായാലും @samadanambot ലേക്ക് send ചെയ്യൂ. പേര് hidden.",
    "📩 group-il directly post cheyyalle. പേര് കാണിക്കാതെ വേണ്ടത് @samadanambot വഴി.",
    "💌 ആ പറയാൻ പറ്റാത്ത കാര്യം — @samadanambot ലേക്ക് അയക്കൂ. നമ്മൾ കാത്തിരിക്കുന്നു.",
    "👑 റാണിയെ കുറിച്ച് @samadanambot ലേക്ക് ഒരു വരി. ഞങ്ങൾ scene set ചെയ്യാം.",
]

BOT_REMINDERS_EN = [
    "📩 Reminder: direct posts in the group show your name. Want to stay hidden? Send it to @samadanambot.",
    "🫥 Got something to say anonymously? @samadanambot is the way.",
    "👀 Silent reader? Drop one line into @samadanambot. Nobody will know.",
    "💭 Whatever's on your mind — send it to @samadanambot. We handle the rest.",
    "🔥 Confession, fantasy, secret — anything. @samadanambot keeps your name hidden.",
    "📩 Don't post directly in the group. For anonymity, use @samadanambot.",
    "💌 The thing you couldn't say out loud — send it to @samadanambot.",
    "👑 One line about your queen. Send it to @samadanambot. We'll do the rest.",
]

MEDIA_REACTIONS_ML = [
    "👀 ഇതിൽ ഒരു കഥയുണ്ട്",
    "🔥 scene undu ithil",
    "🫥 dangerous drop",
    "ayyo ee vibe aaru handle cheyyum 😭",
    "ee drop nu oru confession pair വേണം",
    "👀 ithu kazhinju silent aayi pokalle",
    "ithinte behind story bot-il വരണം 👀",
    "🔥 group-il temperature കൂടി",
    "scene heavy aanu",
    "🫥 anonymous version varatte ithinte",
    "ithu kandittu mind il oraal vannu pole 😌",
    "okay ithu noted aanu",
]

MEDIA_REACTIONS_EN = [
    "🔥 this one has presence",
    "👀 dangerous drop",
    "🫥 the energy is real",
    "this needs a confession pair",
    "scene heavy",
    "👀 don't drop and run",
    "noted. very noted.",
    "the vibe is criminal 😌",
    "🔥 group temperature went up",
    "this one stays in the head",
    "behind story please. anonymous fine.",
    "🫥 wild drop. respect.",
]

TEXT_REACTIONS_ML = [
    "👀 ithu half story pole undu",
    "baaki para 😌",
    "aara ithinte behind?",
    "ithrem പറഞ്ഞിട്ട് പോകല്ലേ",
    "scene undu… continue",
    "🫥 anonymous part 2 varatte",
    "more context വേണം",
]

TEXT_REACTIONS_EN = [
    "👀 sounds like half the story",
    "go on 😌",
    "don't drop and run",
    "context required",
    "🫥 anonymous version next",
    "this hits different",
]

FOLLOWUP_ML = [
    "👀 aarengilum thudangu",
    "silent aayi read ചെയ്ത് പോകല്ലേ",
    "oru line mathi",
    "🫥 peru illathe paranjaal real aakum",
    "bot-il vannal kooduthal nannayirikkum",
]

FOLLOWUP_EN = [
    "👀 don't be shy.",
    "🫥 anonymous version → @samadanambot",
    "💭 someone start...",
    "🔥 first one always breaks the ice",
    "❤️ readers, your turn",
]

POLLS = [
    ("ഇന്നത്തെ vibe entha?", ["സ്നേഹം ❤️", "Missing 🌙", "Risky 👀", "Just watching 🫥"]),
    ("Samadanam-il ningalkku ishtam?", ["Confessions", "രഹസ്യങ്ങൾ", "Late drops", "എല്ലാം"]),
    ("First attraction entha?", ["Eyes", "Voice", "Vibe", "Way of talking"]),
    ("Tonight's mood?", ["Love ❤️", "Lust 🔥", "Lonely 🌙", "Chaos 🫥"]),
    ("How do you use Samadanam?", ["Read", "React", "Anonymous post", "All three"]),
    ("Midnight-il mind പോകുന്നത് evide?", ["Old crush", "Present scene", "Fantasy", "No peace 😭"]),
    ("Honesty test:", ["Open book 📖", "Walls up 🧱", "Depends 🤷", "Mystery 🫥"]),
]


def pick_engagement_text():
    use_ml = random.random() < 0.5

    # 20% chance: bot reminder
    if random.random() < 0.20:
        return random.choice(BOT_REMINDERS_ML if use_ml else BOT_REMINDERS_EN)

    if is_late_night():
        return random.choice(LATE_NIGHT_ML if use_ml else LATE_NIGHT_EN)
    if is_morning():
        return random.choice(MORNING_ML if use_ml else MORNING_EN)
    return random.choice(ENGAGEMENT_ML if use_ml else ENGAGEMENT_EN)


def pick_media_reaction():
    use_ml = random.random() < 0.5
    return random.choice(MEDIA_REACTIONS_ML if use_ml else MEDIA_REACTIONS_EN)


def pick_text_reaction():
    use_ml = random.random() < 0.5
    return random.choice(TEXT_REACTIONS_ML if use_ml else TEXT_REACTIONS_EN)


def pick_followup():
    use_ml = random.random() < 0.5
    return random.choice(FOLLOWUP_ML if use_ml else FOLLOWUP_EN)


# ================== POSTING (flood-control safe) ==================

async def safe_send(coro):
    """Wrap a send call with flood-control retry."""
    global LAST_SEND_TIME
    async with SEND_LOCK:
        elapsed = time.time() - LAST_SEND_TIME
        if elapsed < MIN_SEND_INTERVAL:
            await asyncio.sleep(MIN_SEND_INTERVAL - elapsed)
        try:
            result = await coro
            LAST_SEND_TIME = time.time()
            return result
        except RetryAfter as e:
            wait = e.retry_after + 1
            logger.warning(f"Flood control: waiting {wait}s")
            await asyncio.sleep(wait)
            try:
                result = await coro
                LAST_SEND_TIME = time.time()
                return result
            except Exception as e2:
                logger.warning(f"Retry failed: {e2}")
                return None
        except Exception as e:
            logger.warning(f"Send failed: {e}")
            return None


# ================== ADMIN LOG ==================

async def send_admin_log(context, user, post_type, text=None, file_id=None, caption=None):
    try:
        username = f"@{user.username}" if user.username else "No username"
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "No name"
        header = (
            f"🫥 New anonymous post\n"
            f"👤 Name: {full_name}\n"
            f"📧 Username: {username}\n"
            f"🆔 User ID: {user.id}\n"
            f"📦 Type: {post_type}\n"
            "─────────────"
        )
        await context.bot.send_message(chat_id=ADMIN_LOG_CHAT_ID, text=header)
        if post_type == "text":
            await context.bot.send_message(chat_id=ADMIN_LOG_CHAT_ID, text=text or "")
        elif post_type == "photo":
            await context.bot.send_photo(chat_id=ADMIN_LOG_CHAT_ID, photo=file_id, caption=caption or "")
        elif post_type == "video":
            await context.bot.send_video(chat_id=ADMIN_LOG_CHAT_ID, video=file_id, caption=caption or "")
        elif post_type == "voice":
            await context.bot.send_voice(chat_id=ADMIN_LOG_CHAT_ID, voice=file_id)
        elif post_type == "document":
            await context.bot.send_document(chat_id=ADMIN_LOG_CHAT_ID, document=file_id, caption=caption or "")
    except Exception as e:
        logger.warning(f"Admin log failed: {e}")


# ================== COMMANDS ==================

WELCOME_ML = """🫥 സമാദാനത്തിലേക്ക് സ്വാഗതം.

📩 Anonymous ആയി ഇടാം. പേര് മറയ്ക്കും.
👥 ഇഷ്ടപ്പെട്ടോ? ഒരു friend നെ invite ചെയ്യൂ. നമുക്ക് ഇത് massive ആക്കാം 🔥

🚫 Links allowed alla
📩 Direct group post-il പേര് കാണും. Anonymous വേണമെങ്കിൽ bot വഴി."""

WELCOME_EN = """🫥 Welcome to Samadanam.

📩 Post anonymously. Your name stays hidden.
👥 Liked it? Bring one friend. Let's make this massive 🔥

🚫 No links allowed
📩 Direct group posts show your name. Bot posts stay anonymous."""


def start_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Join Love Chat Group", url=GROUP_LINK)],
        [InlineKeyboardButton("📨 Invite Friends", url=get_share_link(user_id))],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return

    referrer_id = None
    args = context.args
    if args and args[0].startswith("ref_"):
        try:
            rid = int(args[0][4:])
            if rid != user.id:
                referrer_id = rid
        except Exception:
            pass

    upsert_user(user, referrer_id)

    refs = get_user_referrals(user.id)
    emoji, tier = get_tier(refs)

    welcome = WELCOME_ML + "\n\n" + WELCOME_EN
    welcome += f"\n\n{emoji} Tier: {tier}  |  👥 Referrals: {refs}"

    await update.message.reply_text(welcome, reply_markup=start_keyboard(user.id))

    # Notify referrer if applicable
    if referrer_id:
        upgrade = update_tier_if_changed(referrer_id, context.application)
        if upgrade:
            try:
                e, t, n = upgrade
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"{e} New tier unlocked: {t}\n👥 Total referrals: {n}\n\nSamadanam grows because of you. Respect 🙌"
                )
            except Exception:
                pass


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_banned(update.effective_user.id):
        return
    text = (
        "🫥 സമാദാനം — How to use\n\n"
        "📩 Send any text, photo, video, voice, or file to me.\n"
        "✅ It posts anonymously to Love Chat ❤️\n"
        "🔒 Your name stays hidden.\n\n"
        "Commands:\n"
        "/start — Welcome + your stats\n"
        "/invite — Get share messages\n"
        "/share — One-tap share to any chat\n"
        "/mystats — Your referral stats\n"
        "/help — This message\n\n"
        "🚫 No links\n"
        "🚫 No minors / illegal content\n\n"
        "📩 ഏതും anonymous ആയി ഇടാം — text, photo, video, voice, file."
    )
    await update.message.reply_text(text)


async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return
    refs = get_user_referrals(user.id)
    emoji, tier = get_tier(refs)
    next_tier_at = next((n for n in [1, 5, 10, 25, 50, 100] if n > refs), None)
    next_line = f"\n🎯 Next tier at: {next_tier_at} invites" if next_tier_at else "\n🏆 Max tier reached!"
    await update.message.reply_text(
        f"📊 Your Samadanam Stats\n\n"
        f"{emoji} Tier: {tier}\n"
        f"👥 Referrals: {refs}"
        f"{next_line}\n\n"
        f"📨 /invite — get share messages"
    )


async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return
    upsert_user(user)
    ref_link = get_referral_link(user.id)
    text = (
        "📨 Share Samadanam — pick one and forward:\n\n"
        "──────────────\n"
        "1️⃣ Malayalam (casual)\n\n"
        "ഒരു new anonymous group കണ്ടു — സമാദാനം.\n"
        "Confessions, secrets, queens, fantasies — anonymous ആയി share ചെയ്യാം. പേര് കാണിക്കില്ല.\n\n"
        f"👉 {ref_link}\n"
        "──────────────\n"
        "2️⃣ Malayalam (curious)\n\n"
        "ithu kandirunnoo? 👀\n"
        "പേര് കാണിക്കാതെ എന്തും പറയാൻ പറ്റുന്ന group.\n\n"
        f"👉 {ref_link}\n"
        "──────────────\n"
        "3️⃣ English (short)\n\n"
        "🫥 found this anonymous Malayalam group...\n"
        "people share secrets, queens, fantasies here.\n\n"
        f"👉 {ref_link}\n"
        "──────────────\n\n"
        "📋 Copy any one, send to friends or WhatsApp groups.\n"
        "🏆 Top inviters get featured + custom titles."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share to any chat", switch_inline_query=f"🫥 Samadanam — anonymous Malayalam group\n👉 {ref_link}")],
    ])
    await update.message.reply_text(text, reply_markup=keyboard)


async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_banned(user.id):
        return
    upsert_user(user)
    ref_link = get_referral_link(user.id)
    use_ml = random.random() < 0.5
    if use_ml:
        share_text = (
            f"🫥 ഒരു anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
            f"പേര് കാണിക്കാതെ എന്തും share ചെയ്യാം.\n\n"
            f"👉 {ref_link}"
        )
    else:
        share_text = (
            f"🫥 found this anonymous Malayalam group...\n"
            f"people share secrets, queens, fantasies here.\n\n"
            f"👉 {ref_link}"
        )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Share to any chat", switch_inline_query=share_text)],
        [InlineKeyboardButton("📋 Copy referral link", url=ref_link)],
    ])
    await update.message.reply_text(
        "📨 Tap below — share Samadanam anywhere.",
        reply_markup=keyboard
    )


# ================== ADMIN COMMANDS ==================

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in ADMIN_IDS:
            return
        return await func(update, context)
    return wrapper


@admin_only
async def autopilot_on(update, context):
    global AUTO_PILOT_ENABLED
    AUTO_PILOT_ENABLED = True
    await update.message.reply_text("✅ Autopilot ENABLED.")


@admin_only
async def autopilot_off(update, context):
    global AUTO_PILOT_ENABLED
    AUTO_PILOT_ENABLED = False
    await update.message.reply_text("🛑 Autopilot DISABLED.")


@admin_only
async def autopilot_status(update, context):
    idle = int(time.time() - LAST_GROUP_ACTIVITY_TS)
    last_post = int(time.time() - LAST_AUTOPILOT_POST_TS) if LAST_AUTOPILOT_POST_TS else -1
    arc_count = db.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    await update.message.reply_text(
        f"🤖 Samadanam Autopilot Status\n\n"
        f"Engine 1 (Engagement): {'ON ✅' if AUTO_PILOT_ENABLED else 'OFF 🛑'}\n"
        f"Engine 2 (Recycle): {'ON ✅' if RECYCLER_ENABLED else 'OFF 🛑'}\n"
        f"Engine 3 (Battles): {'ON ✅' if BATTLES_ENABLED else 'OFF 🛑'}\n\n"
        f"Idle for: {idle}s\n"
        f"Last bot post: {last_post}s ago\n"
        f"Archive size: {arc_count}\n"
        f"Users tracked: {user_count}\n"
        f"Today's battles: {TODAYS_BATTLES_DONE}/{TODAYS_BATTLES_PLANNED}"
    )


@admin_only
async def postnow(update, context):
    await send_engagement_post(context.application)
    await update.message.reply_text("📣 Engagement post sent.")


@admin_only
async def recycle_now(update, context):
    ok = await do_recycle(context.application)
    await update.message.reply_text("♻️ Recycle done." if ok else "⚠️ No eligible archive item.")


@admin_only
async def battle_now(update, context):
    ok = await do_battle(context.application)
    await update.message.reply_text("👑 Battle posted." if ok else "⚠️ Not enough eligible photos for battle.")


@admin_only
async def ban_user(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /ban USERID [reason]")
        return
    try:
        uid = int(context.args[0])
        reason = " ".join(context.args[1:]) or "no reason"
        with db:
            db.execute("INSERT OR REPLACE INTO bans (user_id, reason) VALUES (?, ?)", (uid, reason))
        await update.message.reply_text(f"🚫 User {uid} banned. Reason: {reason}")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")


@admin_only
async def unban_user(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /unban USERID")
        return
    try:
        uid = int(context.args[0])
        with db:
            db.execute("DELETE FROM bans WHERE user_id=?", (uid,))
        await update.message.reply_text(f"✅ User {uid} unbanned.")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")


@admin_only
async def backup_db(update, context):
    try:
        with open(DB_PATH, "rb") as f:
            await context.bot.send_document(
                chat_id=ADMIN_LOG_CHAT_ID,
                document=f,
                caption=f"🗄️ Samadanam DB backup — {datetime.now().isoformat()}"
            )
        await update.message.reply_text("✅ Backup sent to admin log.")
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")


@admin_only
async def stats(update, context):
    user_count = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    arc_count = db.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
    refs = db.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
    bans_count = db.execute("SELECT COUNT(*) FROM bans").fetchone()[0]
    top = db.execute("""
        SELECT first_name, referrals_count, tier 
        FROM users 
        WHERE referrals_count > 0 
        ORDER BY referrals_count DESC LIMIT 5
    """).fetchall()
    text = (
        f"📊 Admin Stats\n\n"
        f"Users: {user_count}\n"
        f"Archive: {arc_count}\n"
        f"Referrals: {refs}\n"
        f"Banned: {bans_count}\n\n"
        f"🏆 Top Inviters:\n"
    )
    for i, r in enumerate(top, 1):
        text += f"{i}. {r['first_name'] or 'Anon'} — {r['referrals_count']} ({r['tier']})\n"
    await update.message.reply_text(text)


# ================== GROUP POSTING ==================

async def post_to_group_text(application, text):
    return await safe_send(application.bot.send_message(chat_id=GROUP_ID, text=POST_HEADER + text))


async def post_to_group_photo(application, file_id, caption=None):
    full = POST_HEADER + (caption or "")
    return await safe_send(application.bot.send_photo(chat_id=GROUP_ID, photo=file_id, caption=full.strip()))


async def post_to_group_video(application, file_id, caption=None):
    full = POST_HEADER + (caption or "")
    return await safe_send(application.bot.send_video(chat_id=GROUP_ID, video=file_id, caption=full.strip()))


async def post_to_group_voice(application, file_id):
    return await safe_send(application.bot.send_voice(chat_id=GROUP_ID, voice=file_id, caption=POST_HEADER.strip()))


async def post_to_group_doc(application, file_id, caption=None):
    full = POST_HEADER + (caption or "")
    return await safe_send(application.bot.send_document(chat_id=GROUP_ID, document=file_id, caption=full.strip()))


# ================== PRIVATE SUBMISSIONS ==================

async def submit_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    if is_banned(user.id):
        return
    if not msg or update.effective_chat.type != "private":
        return

    upsert_user(user)

    # Rate limit
    if not can_submit(user.id):
        await msg.reply_text("⏳ Slow down — too many posts. Try again later.")
        return

    text = msg.text or msg.caption or ""

    # Link block
    if contains_link(text):
        await msg.reply_text("🚫 Links not allowed.")
        return

    # Banned content
    if contains_banned(text):
        with db:
            db.execute("INSERT OR REPLACE INTO bans (user_id, reason) VALUES (?, ?)",
                       (user.id, "banned content auto-detected"))
        await msg.reply_text("🚫 Content not allowed. You've been blocked from posting.")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_LOG_CHAT_ID,
                text=f"🚨 Auto-banned user {user.id} (@{user.username})\nReason: banned terms in submission\nText: {text[:200]}"
            )
        except Exception:
            pass
        return

    # Determine type and post
    posted = False
    file_id = None
    media_type = "text"
    caption = msg.caption or ""

    try:
        if msg.text:
            await post_to_group_text(context.application, msg.text)
            posted = True
        elif msg.photo:
            file_id = msg.photo[-1].file_id
            media_type = "photo"
            await post_to_group_photo(context.application, file_id, caption)
            posted = True
        elif msg.video:
            file_id = msg.video.file_id
            media_type = "video"
            await post_to_group_video(context.application, file_id, caption)
            posted = True
        elif msg.animation:
            file_id = msg.animation.file_id
            media_type = "animation"
            await safe_send(context.application.bot.send_animation(
                chat_id=GROUP_ID, animation=file_id,
                caption=(POST_HEADER + caption).strip()
            ))
            posted = True
        elif msg.voice:
            file_id = msg.voice.file_id
            media_type = "voice"
            await post_to_group_voice(context.application, file_id)
            posted = True
        elif msg.video_note:
            file_id = msg.video_note.file_id
            media_type = "video_note"
            await safe_send(context.application.bot.send_video_note(chat_id=GROUP_ID, video_note=file_id))
            posted = True
        elif msg.document:
            file_id = msg.document.file_id
            media_type = "document"
            await post_to_group_doc(context.application, file_id, caption)
            posted = True
        elif msg.audio:
            file_id = msg.audio.file_id
            media_type = "audio"
            await safe_send(context.application.bot.send_audio(
                chat_id=GROUP_ID, audio=file_id,
                caption=(POST_HEADER + caption).strip()
            ))
            posted = True
    except Exception as e:
        logger.warning(f"Submit failed: {e}")

    if posted:
        log_submission(user.id)
        # Save to archive (photo/video only — what battles + recycling use)
        if media_type in ("photo", "video", "animation"):
            with db:
                db.execute("""
                    INSERT INTO archive (file_id, media_type, original_caption, submitter_id)
                    VALUES (?, ?, ?, ?)
                """, (file_id, media_type, caption, user.id))

        await msg.reply_text("✅ Posted anonymously in Love Chat ❤️")
        await send_admin_log(context, user, media_type, text=msg.text, file_id=file_id, caption=caption)
    else:
        await msg.reply_text("⚠️ Couldn't post — try again or send a different format.")


# ================== GROUP MONITOR ==================

async def group_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Watch group messages — delete links, react randomly."""
    try:
        if not update.effective_chat or update.effective_chat.id != GROUP_ID:
            return
        msg = update.message
        if not msg or not msg.from_user:
            return

        # Skip bot's own messages
        if msg.from_user.is_bot:
            return

        mark_group_activity()

        text = msg.text or msg.caption or ""

        # Block links from non-admins
        if contains_link(text) and msg.from_user.id not in ADMIN_IDS:
            try:
                await msg.delete()
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=f"🚫 Links not allowed.\n📩 Anonymous post via @{BOT_USERNAME}"
                )
            except Exception:
                pass
            return

        # Block banned content
        if contains_banned(text):
            try:
                await msg.delete()
                await context.bot.ban_chat_member(GROUP_ID, msg.from_user.id)
                with db:
                    db.execute("INSERT OR REPLACE INTO bans (user_id, reason) VALUES (?, ?)",
                               (msg.from_user.id, "banned terms in group"))
            except Exception:
                pass
            return

        # Random media reaction
        if (msg.photo or msg.video or msg.animation) and random.random() < MEDIA_COMMENT_CHANCE:
            await asyncio.sleep(random.randint(4, 18))
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=pick_media_reaction(),
                    reply_to_message_id=msg.message_id,
                )
            except Exception:
                pass
            # Plus a media reminder to use bot
            if random.random() < 0.4:
                await asyncio.sleep(random.randint(20, 60))
                try:
                    await context.bot.send_message(
                        chat_id=GROUP_ID,
                        text=f"📩 Anonymous version next time? → @{BOT_USERNAME}"
                    )
                except Exception:
                    pass
            return

        # Random text reaction
        if msg.text and len(msg.text) > 10 and random.random() < TEXT_COMMENT_CHANCE:
            await asyncio.sleep(random.randint(3, 12))
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=pick_text_reaction(),
                    reply_to_message_id=msg.message_id,
                )
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Group monitor error: {e}")


# ================== SILENT GROUP MODE ==================

async def auto_delete_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete service messages — joins, leaves, adds, etc."""
    try:
        if not update.effective_chat or update.effective_chat.id != GROUP_ID:
            return
        msg = update.message
        if not msg:
            return

        is_service = (
            msg.new_chat_members or msg.left_chat_member or
            msg.new_chat_title or msg.new_chat_photo or
            msg.delete_chat_photo or msg.group_chat_created or
            msg.supergroup_chat_created or msg.channel_chat_created or
            msg.migrate_to_chat_id or msg.migrate_from_chat_id or
            msg.pinned_message
        )

        if is_service:
            try:
                await context.bot.delete_message(chat_id=GROUP_ID, message_id=msg.message_id)
            except Exception:
                pass
    except Exception:
        pass


# ================== AUTOPILOT ENGINES ==================

async def send_engagement_post(application):
    global LAST_AUTOPILOT_POST_TS

    # Skip dawn 4-8 AM (recycle-only mode)
    if is_dawn():
        return

    use_poll = random.random() < 0.15

    try:
        if use_poll:
            q, options = random.choice(POLLS)
            await safe_send(application.bot.send_poll(
                chat_id=GROUP_ID, question=q, options=options,
                is_anonymous=False, allows_multiple_answers=False
            ))
        else:
            text = pick_engagement_text()
            await safe_send(application.bot.send_message(chat_id=GROUP_ID, text=text))

            if random.random() < FOLLOWUP_CHANCE:
                await asyncio.sleep(random.randint(8, 30))
                try:
                    await safe_send(application.bot.send_message(chat_id=GROUP_ID, text=pick_followup()))
                except Exception:
                    pass

        LAST_AUTOPILOT_POST_TS = time.time()
        reset_idle_targets()
    except Exception as e:
        logger.warning(f"Engagement post failed: {e}")


async def do_recycle(application):
    """Engine 2 — recycle a random old archive item with original caption only."""
    global LAST_RECYCLE_TS

    cutoff = datetime.utcnow().timestamp() - (RECYCLE_MIN_AGE_HOURS * 3600)
    cooldown_cutoff = datetime.utcnow().timestamp() - (RECYCLE_COOLDOWN_DAYS * 86400)

    row = db.execute("""
        SELECT id, file_id, media_type, original_caption
        FROM archive
        WHERE submitted_at < datetime(?, 'unixepoch')
          AND (last_recycled_at IS NULL OR last_recycled_at < datetime(?, 'unixepoch'))
        ORDER BY RANDOM()
        LIMIT 1
    """, (cutoff, cooldown_cutoff)).fetchone()

    if not row:
        return False

    try:
        cap = row["original_caption"] or ""
        full_cap = (POST_HEADER + cap).strip() if cap else POST_HEADER.strip()

        if row["media_type"] == "photo":
            await safe_send(application.bot.send_photo(chat_id=GROUP_ID, photo=row["file_id"], caption=full_cap))
        elif row["media_type"] == "video":
            await safe_send(application.bot.send_video(chat_id=GROUP_ID, video=row["file_id"], caption=full_cap))
        elif row["media_type"] == "animation":
            await safe_send(application.bot.send_animation(chat_id=GROUP_ID, animation=row["file_id"], caption=full_cap))
        else:
            return False

        with db:
            db.execute("UPDATE archive SET last_recycled_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))

        LAST_RECYCLE_TS = time.time()
        reset_recycle_target()
        return True
    except Exception as e:
        logger.warning(f"Recycle failed: {e}")
        return False


async def do_battle(application):
    """Engine 3 — Queen Battle. 2 random archive photos + locked header + poll."""
    global LAST_BATTLE_TS, TODAYS_BATTLES_DONE

    cooldown_cutoff = datetime.utcnow().timestamp() - (BATTLE_PHOTO_COOLDOWN_DAYS * 86400)

    rows = db.execute("""
        SELECT id, file_id, original_caption
        FROM archive
        WHERE media_type = 'photo'
          AND (last_battle_at IS NULL OR last_battle_at < datetime(?, 'unixepoch'))
        ORDER BY RANDOM()
        LIMIT 2
    """, (cooldown_cutoff,)).fetchall()

    if len(rows) < 2:
        return False

    use_ml = random.random() < 0.5
    if use_ml:
        header = "👑💦 റാണി പോര് 👑\nഇന്നത്തെ duel. ആരാ winner?"
    else:
        header = "👑💦 Queen Battle 👑\nTonight's duel. Pick your side."

    try:
        # Send header
        await safe_send(application.bot.send_message(chat_id=GROUP_ID, text=header))

        # Send photos as media group
        from telegram import InputMediaPhoto
        media = [
            InputMediaPhoto(media=rows[0]["file_id"], caption="👈 Left"),
            InputMediaPhoto(media=rows[1]["file_id"], caption="👉 Right"),
        ]
        await safe_send(application.bot.send_media_group(chat_id=GROUP_ID, media=media))

        # Send poll
        await safe_send(application.bot.send_poll(
            chat_id=GROUP_ID,
            question="ആരാ winner? / Who wins?",
            options=["👈 Left", "👉 Right", "🤝 Both fire", "🫥 Pass"],
            is_anonymous=False,
            allows_multiple_answers=False,
        ))

        # Mark both as used
        with db:
            for r in rows:
                db.execute("UPDATE archive SET last_battle_at=CURRENT_TIMESTAMP WHERE id=?", (r["id"],))

        LAST_BATTLE_TS = time.time()
        TODAYS_BATTLES_DONE += 1
        return True
    except Exception as e:
        logger.warning(f"Battle failed: {e}")
        return False


def plan_today_battles():
    """Plan how many battles today based on archive size."""
    global TODAYS_BATTLES_PLANNED, TODAYS_BATTLES_DONE, TODAYS_BATTLE_DATE

    today = datetime.now().strftime("%Y-%m-%d")
    if TODAYS_BATTLE_DATE != today:
        TODAYS_BATTLE_DATE = today
        TODAYS_BATTLES_DONE = 0

        cooldown_cutoff = datetime.utcnow().timestamp() - (BATTLE_PHOTO_COOLDOWN_DAYS * 86400)
        eligible = db.execute("""
            SELECT COUNT(*) FROM archive
            WHERE media_type = 'photo'
              AND (last_battle_at IS NULL OR last_battle_at < datetime(?, 'unixepoch'))
        """, (cooldown_cutoff,)).fetchone()[0]

        if eligible >= 30:
            TODAYS_BATTLES_PLANNED = random.randint(3, BATTLE_DAILY_MAX)
        elif eligible >= 20:
            TODAYS_BATTLES_PLANNED = random.randint(2, 3)
        elif eligible >= BATTLE_MIN_ARCHIVE:
            TODAYS_BATTLES_PLANNED = random.randint(BATTLE_DAILY_MIN, 2)
        else:
            TODAYS_BATTLES_PLANNED = 0


async def autopilot_loop(application):
    """Master loop — runs all 3 engines."""
    global LAST_GROUP_ACTIVITY_TS, LAST_AUTOPILOT_POST_TS, LAST_RECYCLE_TS, LAST_BATTLE_TS

    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            human_idle = now - LAST_GROUP_ACTIVITY_TS

            # Engine 1 — Engagement
            if AUTO_PILOT_ENABLED and not is_dawn():
                since_last_engage = now - LAST_AUTOPILOT_POST_TS
                if human_idle >= NEXT_IDLE_TARGET and since_last_engage >= NEXT_GAP_TARGET:
                    await send_engagement_post(application)

            # Engine 2 — Recycle (runs even in dawn, lighter)
            if RECYCLER_ENABLED:
                since_last_recycle = now - LAST_RECYCLE_TS
                target = NEXT_RECYCLE_TARGET * (2 if is_dawn() else 1)
                if since_last_recycle >= target and human_idle >= 600:  # 10 min human-idle minimum
                    await do_recycle(application)

            # Engine 3 — Queen Battles
            if BATTLES_ENABLED:
                plan_today_battles()
                since_last_battle = now - LAST_BATTLE_TS
                if (TODAYS_BATTLES_DONE < TODAYS_BATTLES_PLANNED
                    and since_last_battle >= BATTLE_MIN_GAP
                    and human_idle >= HUMAN_ACTIVITY_BUFFER
                    and 10 <= datetime.now().hour or datetime.now().hour < 2):
                    # Random chance to fire each minute (spreads battles across day)
                    hours_left = max(1, (26 - datetime.now().hour) % 26)
                    battles_left = TODAYS_BATTLES_PLANNED - TODAYS_BATTLES_DONE
                    fire_chance = battles_left / (hours_left * 60)
                    if random.random() < fire_chance:
                        await do_battle(application)

        except Exception as e:
            logger.warning(f"Autopilot loop error: {e}")
            await asyncio.sleep(30)


# ================== INLINE MODE ==================

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.inline_query.from_user
    upsert_user(user)
    ref_link = get_referral_link(user.id)

    results = [
        InlineQueryResultArticle(
            id="ml",
            title="🫥 Share Samadanam (Malayalam)",
            description="Anonymous Malayalam group",
            input_message_content=InputTextMessageContent(
                f"🫥 ഒരു new anonymous Malayalam group കണ്ടു — സമാദാനം.\n"
                f"പേര് കാണിക്കാതെ എന്തും share ചെയ്യാം.\n\n👉 {ref_link}"
            ),
        ),
        InlineQueryResultArticle(
            id="en",
            title="🫥 Share Samadanam (English)",
            description="Anonymous Malayalam group",
            input_message_content=InputTextMessageContent(
                f"🫥 found this anonymous Malayalam group...\n"
                f"people share secrets, queens, fantasies here.\n\n👉 {ref_link}"
            ),
        ),
        InlineQueryResultArticle(
            id="curious",
            title="👀 Curious teaser",
            description="Soft, mysterious share",
            input_message_content=InputTextMessageContent(
                f"ithu kandirunnoo? 👀\nപേര് കാണിക്കാതെ എന്തും പറയാൻ പറ്റുന്ന group.\n\n👉 {ref_link}"
            ),
        ),
    ]
    await update.inline_query.answer(results, cache_time=10)


# ================== ERROR HANDLER ==================

async def error_handler(update, context):
    logger.error(f"Update error: {context.error}")


# ================== WEEKLY LEADERBOARD ==================

async def weekly_leaderboard_loop(application):
    """Posts leaderboard every Sunday 9 PM."""
    while True:
        try:
            now = datetime.now()
            # Sunday = 6, target hour 21
            if now.weekday() == 6 and now.hour == 21 and now.minute < 5:
                top = db.execute("""
                    SELECT first_name, referrals_count, tier
                    FROM users
                    WHERE referrals_count > 0
                    ORDER BY referrals_count DESC LIMIT 5
                """).fetchall()
                if top:
                    text_ml = "🏆 ഈ ആഴ്ച്ചയിലെ Top Inviters\n\n"
                    text_en = "🏆 Top Inviters This Week\n\n"
                    icons = ["👑", "🔥", "⭐", "✨", "💫"]
                    for i, r in enumerate(top):
                        ic = icons[i] if i < len(icons) else "🌱"
                        name = (r["first_name"] or "Anonymous")[:15]
                        text_ml += f"{i+1}. {ic} {name} — {r['referrals_count']}\n"
                        text_en += f"{i+1}. {ic} {name} — {r['referrals_count']}\n"
                    text_ml += "\nനിങ്ങളും ലിസ്റ്റിൽ വരണോ? /invite type ചെയ്യൂ."
                    text_en += "\nWant in? Type /invite to start."
                    final = (text_ml if random.random() < 0.5 else text_en)
                    try:
                        await safe_send(application.bot.send_message(chat_id=GROUP_ID, text=final))
                    except Exception:
                        pass
                    await asyncio.sleep(3600)  # don't repost same hour
            await asyncio.sleep(120)
        except Exception as e:
            logger.warning(f"Leaderboard loop error: {e}")
            await asyncio.sleep(300)


# ================== MAIN ==================

async def post_init(app):
    init_db()
    asyncio.create_task(autopilot_loop(app))
    asyncio.create_task(weekly_leaderboard_loop(app))
    logger.info("🚀 Samadanam autopilot launched.")


def main():
    if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN at the top of main.py")

    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Public commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("invite", invite_command))
    app.add_handler(CommandHandler("share", share_command))

    # Admin commands
    app.add_handler(CommandHandler("autopilot_on", autopilot_on))
    app.add_handler(CommandHandler("autopilot_off", autopilot_off))
    app.add_handler(CommandHandler("autopilot_status", autopilot_status))
    app.add_handler(CommandHandler("postnow", postnow))
    app.add_handler(CommandHandler("recycle_now", recycle_now))
    app.add_handler(CommandHandler("battle_now", battle_now))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("backup_db", backup_db))
    app.add_handler(CommandHandler("stats", stats))

    # Inline mode
    app.add_handler(InlineQueryHandler(inline_query))

    # Silent group mode (delete service messages)
    app.add_handler(MessageHandler(
        filters.StatusUpdate.ALL & filters.Chat(GROUP_ID),
        auto_delete_service
    ))

    # Group monitor (links + reactions)
    app.add_handler(MessageHandler(
        filters.Chat(GROUP_ID) & ~filters.StatusUpdate.ALL,
        group_monitor
    ))

    # Private submissions
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        submit_private
    ))

    app.add_error_handler(error_handler)

    logger.info(f"🤖 Starting {BOT_NAME} ({BOT_USERNAME})...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
