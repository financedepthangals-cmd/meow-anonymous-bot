from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import logging
from datetime import datetime
from flask import Flask
from threading import Thread

# ===== WEB SERVER FOR REPLIT (Keeps bot online 24/7) =====
app = Flask(__name__)


@app.route('/')
def home():
    return "🤖 Meow Anonymous Bot is running! ✅"


def run_flask():
    app.run(host='0.0.0.0', port=8080)


# ===== CONFIGURATION =====
BOT_TOKEN = "8405092073:AAHVL8dmJfAxdrv9IeXlXAs9ew2DshvXezo"
CHANNEL_ID = -1003579781880
CHANNEL_LINK = 'https://t.me/+wPf8782Yybw1YTQ0'
ADMIN_ID = 8352264928

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Store pending submissions
pending_posts = {}
post_counter = 0


# ===== USER TRACKING FUNCTIONS =====
def get_user_info(user):
    """Extract user information for admin tracking"""
    username = f"@{user.username}" if user.username else "No username"
    user_id = user.id
    first_name = user.first_name or "Unknown"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()

    return {
        'user_id': user_id,
        'username': username,
        'full_name': full_name,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }


def format_user_info(user_info):
    """Format user info for admin to see WHO posted - SAFE VERSION"""
    # Escape special characters that break formatting
    full_name = str(user_info.get('full_name', 'Unknown')).replace(
        '_', '-').replace('*',
                          '-').replace('[',
                                       '(').replace(']',
                                                    ')').replace('`', "'")
    username = str(user_info.get('username',
                                 'No username')).replace('_', '-').replace(
                                     '*', '-').replace('`', "'")

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
    """Log all submissions to file with user details"""
    try:
        with open('submissions_log.txt', 'a', encoding='utf-8') as f:
            status = "✅ APPROVED & POSTED" if approved else "⏳ PENDING APPROVAL"
            f.write(
                f"\n{status} | {user_info.get('timestamp', 'Unknown')} | {content_type}\n"
            )
            f.write(f"📛 Name: {user_info.get('full_name', 'Unknown')}\n")
            f.write(f"📧 Username: {user_info.get('username', 'Unknown')}\n")
            f.write(f"🆔 User ID: {user_info.get('user_id', 'Unknown')}\n")
            f.write("=" * 60 + "\n")
    except Exception as e:
        logger.error(f"Error writing to log: {e}")


# ===== COMMAND HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    keyboard = [[
        InlineKeyboardButton("📢 View Anonymous Channel", url=CHANNEL_LINK)
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = """
👋 Welcome to Meow Anonymous Bot!

🔒 Share anything anonymously! Your identity is 100% protected.

What you can send:
📸 Photos
💬 Messages  
🎥 Videos
🎤 Voice messages
📎 Documents

How it works:
1️⃣ Send your content here
2️⃣ Admin reviews it (without revealing your identity to others)
3️⃣ Once approved, it posts anonymously to the channel
4️⃣ No one in the channel knows who posted

👇 Click to view the anonymous channel:
"""

    await update.message.reply_text(welcome_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help message"""
    help_text = """
📖 How to use this bot:

1️⃣ Send any photo, video, message, voice, or document
2️⃣ Your submission goes to admin for review
3️⃣ Admin approves → Posts anonymously to channel
4️⃣ Your identity stays private in the channel

🔒 Privacy:
• Channel posts show NO username, NO name
• Only admin can see who submitted (for moderation)
• Other users CANNOT see who posted

Send anything now to get started! 🚀
"""
    await update.message.reply_text(help_text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: View pending submissions and stats"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ This command is admin-only.")
        return

    stats_text = f"""
📊 Admin Dashboard
━━━━━━━━━━━━━━━━━━━━━━━━
⏳ Pending submissions: {len(pending_posts)}
📢 Channel: {CHANNEL_LINK}
👑 Admin: You ({ADMIN_ID})
🤖 Bot: @rand8168bot
━━━━━━━━━━━━━━━━━━━━━━━━

📝 View submission history:
Check submissions_log.txt file for complete logs with user details

🔍 You can see who posted
✅ Channel stays anonymous
"""
    await update.message.reply_text(stats_text)


# ===== PHOTO HANDLER =====
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo submissions with user tracking"""
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)

    photo = update.message.photo[-1]
    caption = update.message.caption

    # ADMIN POSTS DIRECTLY (no approval needed)
    if user.id == ADMIN_ID:
        try:
            await context.bot.send_photo(chat_id=CHANNEL_ID,
                                         photo=photo.file_id,
                                         caption=caption)
            log_submission(user_info,
                           "PHOTO (Admin Direct Post)",
                           approved=True)
            await update.message.reply_text(
                "✅ Posted anonymously to channel! 📸")
            logger.info(f"✅ Admin direct post: PHOTO")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error posting to channel: {e}")
            logger.error(f"Error posting photo: {e}")
            return

    # REGULAR USERS: Send for approval WITH USER INFO
    post_counter += 1
    post_id = f"photo_{post_counter}"

    pending_posts[post_id] = {
        'type': 'photo',
        'file_id': photo.file_id,
        'caption': caption,
        'user_id': user.id,
        'user_info': user_info
    }

    # Send to ADMIN with user details visible
    keyboard = [[
        InlineKeyboardButton("✅ Approve & Post",
                             callback_data=f"approve_{post_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Admin sees WHO posted
    admin_message = f"{format_user_info(user_info)}\n📸 NEW PHOTO SUBMISSION"
    if caption:
        admin_message += f"\n\nCaption: {caption}"

    try:
        await context.bot.send_photo(chat_id=ADMIN_ID,
                                     photo=photo.file_id,
                                     caption=admin_message,
                                     reply_markup=reply_markup)
        log_submission(user_info, "PHOTO", approved=False)
        await update.message.reply_text(
            "✅ Submitted for review!\n\nYour photo will be posted anonymously once approved by admin."
        )
        logger.info(
            f"📸 New submission from {user_info['username']} (ID: {user_info['user_id']})"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error submitting: {e}")
        logger.error(f"Error in handle_photo: {e}")


# ===== VIDEO HANDLER =====
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video submissions with user tracking"""
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)

    video = update.message.video
    caption = update.message.caption

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_video(chat_id=CHANNEL_ID,
                                         video=video.file_id,
                                         caption=caption)
            log_submission(user_info,
                           "VIDEO (Admin Direct Post)",
                           approved=True)
            await update.message.reply_text(
                "✅ Posted anonymously to channel! 🎥")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"video_{post_counter}"

    pending_posts[post_id] = {
        'type': 'video',
        'file_id': video.file_id,
        'caption': caption,
        'user_id': user.id,
        'user_info': user_info
    }

    keyboard = [[
        InlineKeyboardButton("✅ Approve & Post",
                             callback_data=f"approve_{post_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_message = f"{format_user_info(user_info)}\n🎥 NEW VIDEO SUBMISSION"
    if caption:
        admin_message += f"\n\nCaption: {caption}"

    try:
        await context.bot.send_video(chat_id=ADMIN_ID,
                                     video=video.file_id,
                                     caption=admin_message,
                                     reply_markup=reply_markup)
        log_submission(user_info, "VIDEO", approved=False)
        await update.message.reply_text("✅ Submitted for review!")
        logger.info(f"🎥 New video from {user_info['username']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ===== TEXT HANDLER =====
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages with user tracking"""
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)

    text = update.message.text

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
            log_submission(user_info,
                           "TEXT (Admin Direct Post)",
                           approved=True)
            await update.message.reply_text(
                "✅ Posted anonymously to channel! 💬")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"text_{post_counter}"

    pending_posts[post_id] = {
        'type': 'text',
        'content': text,
        'user_id': user.id,
        'user_info': user_info
    }

    keyboard = [[
        InlineKeyboardButton("✅ Approve & Post",
                             callback_data=f"approve_{post_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_message = f"{format_user_info(user_info)}\n💬 NEW TEXT SUBMISSION:\n\n{text}"

    try:
        await context.bot.send_message(chat_id=ADMIN_ID,
                                       text=admin_message,
                                       reply_markup=reply_markup)
        log_submission(user_info, "TEXT", approved=False)
        await update.message.reply_text("✅ Submitted for review!")
        logger.info(f"💬 New text from {user_info['username']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ===== VOICE HANDLER =====
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages with user tracking"""
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)

    voice = update.message.voice

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_voice(chat_id=CHANNEL_ID,
                                         voice=voice.file_id)
            log_submission(user_info,
                           "VOICE (Admin Direct Post)",
                           approved=True)
            await update.message.reply_text(
                "✅ Posted anonymously to channel! 🎤")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"voice_{post_counter}"

    pending_posts[post_id] = {
        'type': 'voice',
        'file_id': voice.file_id,
        'user_id': user.id,
        'user_info': user_info
    }

    keyboard = [[
        InlineKeyboardButton("✅ Approve & Post",
                             callback_data=f"approve_{post_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_message = f"{format_user_info(user_info)}\n🎤 NEW VOICE MESSAGE"

    try:
        await context.bot.send_voice(chat_id=ADMIN_ID,
                                     voice=voice.file_id,
                                     caption=admin_message,
                                     reply_markup=reply_markup)
        log_submission(user_info, "VOICE", approved=False)
        await update.message.reply_text("✅ Submitted for review!")
        logger.info(f"🎤 New voice from {user_info['username']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ===== DOCUMENT HANDLER =====
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document submissions with user tracking"""
    global post_counter
    user = update.effective_user
    user_info = get_user_info(user)

    document = update.message.document
    caption = update.message.caption

    if user.id == ADMIN_ID:
        try:
            await context.bot.send_document(chat_id=CHANNEL_ID,
                                            document=document.file_id,
                                            caption=caption)
            log_submission(user_info,
                           "DOCUMENT (Admin Direct Post)",
                           approved=True)
            await update.message.reply_text(
                "✅ Posted anonymously to channel! 📎")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return

    post_counter += 1
    post_id = f"document_{post_counter}"

    pending_posts[post_id] = {
        'type': 'document',
        'file_id': document.file_id,
        'caption': caption,
        'user_id': user.id,
        'user_info': user_info
    }

    keyboard = [[
        InlineKeyboardButton("✅ Approve & Post",
                             callback_data=f"approve_{post_id}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{post_id}")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_message = f"{format_user_info(user_info)}\n📎 NEW DOCUMENT"
    if caption:
        admin_message += f"\n\nCaption: {caption}"

    try:
        await context.bot.send_document(chat_id=ADMIN_ID,
                                        document=document.file_id,
                                        caption=admin_message,
                                        reply_markup=reply_markup)
        log_submission(user_info, "DOCUMENT", approved=False)
        await update.message.reply_text("✅ Submitted for review!")
        logger.info(f"📎 New document from {user_info['username']}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ===== APPROVE/REJECT HANDLER =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle approve/reject button clicks from admin"""
    query = update.callback_query
    await query.answer()

    action, post_id = query.data.split('_', 1)

    if post_id not in pending_posts:
        await query.edit_message_caption(
            caption="⚠️ This submission no longer exists.")
        return

    post = pending_posts[post_id]
    user_info = post['user_info']

    if action == 'approve':
        try:
            # Post to channel ANONYMOUSLY (no user info)
            if post['type'] == 'photo':
                await context.bot.send_photo(chat_id=CHANNEL_ID,
                                             photo=post['file_id'],
                                             caption=post.get('caption'))
            elif post['type'] == 'video':
                await context.bot.send_video(chat_id=CHANNEL_ID,
                                             video=post['file_id'],
                                             caption=post.get('caption'))
            elif post['type'] == 'voice':
                await context.bot.send_voice(chat_id=CHANNEL_ID,
                                             voice=post['file_id'])
            elif post['type'] == 'document':
                await context.bot.send_document(chat_id=CHANNEL_ID,
                                                document=post['file_id'],
                                                caption=post.get('caption'))
            elif post['type'] == 'text':
                await context.bot.send_message(chat_id=CHANNEL_ID,
                                               text=post['content'])

            # Log approval with user details
            log_submission(user_info, post['type'].upper(), approved=True)

            # Update admin message
            await query.edit_message_caption(
                caption=
                f"{query.message.caption}\n\n✅ APPROVED & POSTED ANONYMOUSLY")

            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=post['user_id'],
                    text=
                    "✅ Your submission was approved!\n\nIt has been posted anonymously to the channel. 🎉"
                )
            except:
                pass

            del pending_posts[post_id]
            logger.info(
                f"✅ Approved and posted from {user_info['username']} (ID: {user_info['user_id']})"
            )

        except Exception as e:
            await query.edit_message_caption(
                caption=f"❌ Error posting to channel: {e}")
            logger.error(f"Error approving post: {e}")

    elif action == 'reject':
        # Reject submission
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ REJECTED")

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=post['user_id'],
                text="❌ Your submission was not approved.")
        except:
            pass

        del pending_posts[post_id]
        logger.info(
            f"❌ Rejected submission from {user_info['username']} (ID: {user_info['user_id']})"
        )


# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")


# ===== MAIN FUNCTION =====
def main():
    """Start the bot with web server"""
    print("=" * 80)
    print("🤖 MEOW ANONYMOUS BOT - FRESH START WITH USER TRACKING")
    print("=" * 80)
    print(f"📢 Channel: {CHANNEL_LINK}")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"🤖 Bot: @rand8168bot")
    print("=" * 80)
    print("✅ Bot is now running!")
    print("")
    print("📊 FEATURES:")
    print("  ✅ Users can submit content anonymously")
    print("  ✅ YOU (admin) can see WHO posted each submission")
    print("  ✅ Channel posts remain ANONYMOUS (no user info shown)")
    print("  ✅ Approval system with ✅/❌ buttons")
    print("  ✅ All submissions logged in submissions_log.txt")
    print("")
    print(
        "📝 LOG FILE: submissions_log.txt will contain full history with names")
    print("=" * 80)

    # Start Flask web server in background (keeps Replit alive)
    # Commented out to avoid conflicts - uncomment if you want 24/7 hosting
    # Thread(target=run_flask, daemon=True).start()
    # logger.info("🌐 Web server started on port 8080")

    # Build bot application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats))

    # Register message handlers
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))
    application.add_handler(
        MessageHandler(filters.Document.ALL, handle_document))

    # Register callback handler for approve/reject buttons
    application.add_handler(CallbackQueryHandler(button_callback))

    # Register error handler
    application.add_error_handler(error_handler)

    # Start bot
    logger.info("🚀 Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
