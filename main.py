from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import logging
from datetime import datetime
from flask import Flask
from threading import Thread

# ===== WEB SERVER =====
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Joyce Anonymous Bot is running! ✅"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# ===== CONFIGURATION =====
BOT_TOKEN = "8369427535:AAEER6sj5fvK7ODxk88PqB_31TAFHbsdY-U"
CHANNEL_ID = -1003636238775
CHANNEL_LINK = 'https://t.me/+_iRGCat--tk1MmNk'
ADMIN_ID = 8438801421

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

pending_posts = {}
post_counter = 0

# ===== USER TRACKING =====
def get_user_info(user):
    username = f"@{user.username}" if user.username else "No username"
    first_name = user.first_name or "Unknown"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    return {
        'user_id': user.id,
        'username': username,
        'full_name': full_name,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

def format_user_info(user_info):
    full_name = str(user_info.get('full_name', 'Unknown')).replace('_', '-').replace('*', '-').replace('[', '(').replace(']', ')').replace('`', "'")
    username = str(user_info.get('username', 'No username')).replace('_', '-').replace('*', '-').replace('`', "'")
    return f"""
👤 SUBMITTER INFO (ONLY YOU SEE THIS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📛 Name: {full_name}
🆔 User ID: {user_info.get('user_id', 'Unknown')}
📧 Username: {username}
🕐 Submitted: {user_info.get('timestamp', 'Unknown')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

def log_submission(user_info, content_type, approved=False):
    try:
        with open('submissions_log.txt', 'a', encoding='utf-8') as f:
            status = "✅ APPROVED & POSTED" if approved else "⏳ PENDING APPROVAL"
            f.write(f"\n{status} | {user_info.get('timestamp', 'Unknown')} | {content_type}\n")
            f.write(f"📛 Name: {user_info.get('full_name', 'Unknown')}\n")
            f.write(f"📧 Username: {user_info.get('username', 'Unknown')}\n")
            f.write(f"🆔 User ID: {user_info.get('user_id', 'Unknown')}\n")
            f.write("=" * 60 + "\n")
    except Exception as e:
        logger.error(f"Error writing to log: {e}")

# ===== START COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("❤️ Join Love Chat Group", url=CHANNEL_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = """
🎭 Share your fantasies, secrets & everything discreet.
🔒 100% Anonymous — No one will ever know it was you.
"""
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# ===== HELP COMMAND =====
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 How to use:
1️⃣ Send any photo, video, message, voice or file here
2️⃣ Admin reviews your submission
3️⃣ Once approved → posted in Love Chat ❤️ group
4️⃣ Shows as "Love Chat ❤️" — your identity is hidden 🔒
"""
    await update.message.reply_text(help_text)

# ===== STATS COMMAND (Admin only) =====
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Admin only.")
        return
    stats_text = f"""
📊 Admin Dashboard
━━━━━━━━━━━━━━━━━━
⏳ Pending: {len(pending_posts)}
📢 Group: {CHANNEL_LINK}
👑 Admin ID: {ADMIN_ID}
🤖 Bot: @Joyce8168bot
"""
    await update.message.reply_text(stats_text)

# ===== PHOTO HANDLER =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)
    photo = update.message.photo[-1]
    caption = update.message.caption

    # Admin posts directly as Love Chat ❤️
    if user.id == ADMIN_ID:
        try:
            await context.bot.send_photo(chat_id=CHANNEL_ID,
                                         photo=photo.file_id,
                                         caption=f"💬 Love Chat ❤️\n\n{caption or ''}")
            log_submission(user_info, "PHOTO (Admin)", approved=True)
            await update.message.reply_text("✅ Posted to group as Love Chat ❤️")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"photo_{post_counter}"
    pending_posts[post_id] = {'type': 'photo', 'file_id': photo.file_id, 'caption': caption, 'user_id': user.id, 'user_info': user_info}

    keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{post_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")]]

    admin_message = f"{format_user_info(user_info)}\n📸 NEW PHOTO"
    if caption:
        admin_message += f"\nCaption: {caption}"

    try:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=photo.file_id,
                                     caption=admin_message,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
        log_submission(user_info, "PHOTO", approved=False)
        await context.bot.send_message(chat_id=user.id, text="✅ Submitted! Waiting for admin approval.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ===== VIDEO HANDLER =====
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)
    video = update.message.video
    caption = update.message.caption

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_video(chat_id=CHANNEL_ID,
                                         video=video.file_id,
                                         caption=f"💬 Love Chat ❤️\n\n{caption or ''}")
            log_submission(user_info, "VIDEO (Admin)", approved=True)
            await update.message.reply_text("✅ Posted to group as Love Chat ❤️")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"video_{post_counter}"
    pending_posts[post_id] = {'type': 'video', 'file_id': video.file_id, 'caption': caption, 'user_id': user.id, 'user_info': user_info}

    keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{post_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")]]

    admin_message = f"{format_user_info(user_info)}\n🎥 NEW VIDEO"
    if caption:
        admin_message += f"\nCaption: {caption}"

    try:
        await context.bot.send_video(chat_id=ADMIN_ID, video=video.file_id,
                                     caption=admin_message,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
        log_submission(user_info, "VIDEO", approved=False)
        await context.bot.send_message(chat_id=user.id, text="✅ Submitted! Waiting for admin approval.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ===== TEXT HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)
    text = update.message.text

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID,
                                           text=f"💬 Love Chat ❤️\n\n{text}")
            log_submission(user_info, "TEXT (Admin)", approved=True)
            await update.message.reply_text("✅ Posted to group as Love Chat ❤️")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"text_{post_counter}"
    pending_posts[post_id] = {'type': 'text', 'content': text, 'user_id': user.id, 'user_info': user_info}

    keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{post_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")]]

    admin_message = f"{format_user_info(user_info)}\n💬 NEW TEXT:\n\n{text}"

    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message,
                                       reply_markup=InlineKeyboardMarkup(keyboard))
        log_submission(user_info, "TEXT", approved=False)
        await context.bot.send_message(chat_id=user.id, text="✅ Submitted! Waiting for admin approval.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ===== VOICE HANDLER =====
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)
    voice = update.message.voice

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_voice(chat_id=CHANNEL_ID, voice=voice.file_id,
                                         caption="💬 Love Chat ❤️")
            log_submission(user_info, "VOICE (Admin)", approved=True)
            await update.message.reply_text("✅ Posted to group as Love Chat ❤️")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"voice_{post_counter}"
    pending_posts[post_id] = {'type': 'voice', 'file_id': voice.file_id, 'user_id': user.id, 'user_info': user_info}

    keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{post_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")]]

    admin_message = f"{format_user_info(user_info)}\n🎤 NEW VOICE MESSAGE"

    try:
        await context.bot.send_voice(chat_id=ADMIN_ID, voice=voice.file_id,
                                     caption=admin_message,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
        log_submission(user_info, "VOICE", approved=False)
        await context.bot.send_message(chat_id=user.id, text="✅ Submitted! Waiting for admin approval.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ===== DOCUMENT HANDLER =====
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)
    document = update.message.document
    caption = update.message.caption

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_document(chat_id=CHANNEL_ID,
                                            document=document.file_id,
                                            caption=f"💬 Love Chat ❤️\n\n{caption or ''}")
            log_submission(user_info, "DOCUMENT (Admin)", approved=True)
            await update.message.reply_text("✅ Posted to group as Love Chat ❤️")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"document_{post_counter}"
    pending_posts[post_id] = {'type': 'document', 'file_id': document.file_id, 'caption': caption, 'user_id': user.id, 'user_info': user_info}

    keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{post_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")]]

    admin_message = f"{format_user_info(user_info)}\n📎 NEW DOCUMENT"
    if caption:
        admin_message += f"\nCaption: {caption}"

    try:
        await context.bot.send_document(chat_id=ADMIN_ID, document=document.file_id,
                                        caption=admin_message,
                                        reply_markup=InlineKeyboardMarkup(keyboard))
        log_submission(user_info, "DOCUMENT", approved=False)
        await context.bot.send_message(chat_id=user.id, text="✅ Submitted! Waiting for admin approval.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ===== APPROVE / REJECT =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, post_id = query.data.split('_', 1)

    if post_id not in pending_posts:
        await query.edit_message_caption(caption="⚠️ Submission no longer exists.")
        return

    post = pending_posts[post_id]
    user_info = post['user_info']
    header = "💬 Love Chat ❤️\n\n"

    if action == 'approve':
        try:
            if post['type'] == 'photo':
                await context.bot.send_photo(chat_id=CHANNEL_ID,
                                             photo=post['file_id'],
                                             caption=header + (post.get('caption') or ''))
            elif post['type'] == 'video':
                await context.bot.send_video(chat_id=CHANNEL_ID,
                                             video=post['file_id'],
                                             caption=header + (post.get('caption') or ''))
            elif post['type'] == 'voice':
                await context.bot.send_voice(chat_id=CHANNEL_ID,
                                             voice=post['file_id'],
                                             caption="💬 Love Chat ❤️")
            elif post['type'] == 'document':
                await context.bot.send_document(chat_id=CHANNEL_ID,
                                                document=post['file_id'],
                                                caption=header + (post.get('caption') or ''))
            elif post['type'] == 'text':
                await context.bot.send_message(chat_id=CHANNEL_ID,
                                               text=header + post['content'])

            log_submission(user_info, post['type'].upper(), approved=True)
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n✅ APPROVED & POSTED as Love Chat ❤️")

            try:
                await context.bot.send_message(chat_id=post['user_id'],
                                               text="✅ Your submission was approved and posted in Love Chat ❤️ group!")
            except:
                pass

            del pending_posts[post_id]
            logger.info(f"✅ Approved from {user_info['username']}")

        except Exception as e:
            await query.edit_message_caption(caption=f"❌ Error: {e}")
            logger.error(f"Approve error: {e}")

    elif action == 'reject':
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ REJECTED")
        try:
            await context.bot.send_message(chat_id=post['user_id'],
                                           text="❌ Your submission was not approved.")
        except:
            pass
        del pending_posts[post_id]
        logger.info(f"❌ Rejected from {user_info['username']}")

# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ===== MAIN =====
def main():
    print("🤖 JOYCE ANONYMOUS BOT STARTING...")
    print(f"📢 Group: {CHANNEL_LINK}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print("✅ Bot is running!")

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_video))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, handle_voice))
    application.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handle_document))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    logger.info("🚀 Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
