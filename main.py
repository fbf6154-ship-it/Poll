import os
import threading
from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# ----------------- CONFIGURATION ----------------- #
# আপনার Bot Token ও Admin User ID এখানে দিন
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789")) # আপনার টেলিগ্রাম নিউমেরিক আইডি

# Flask Server for Render (UptimeRobot ping)
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running perfectly 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# In-memory Database
polls_db = {}
user_states = {}

# Conversation States
GET_CHANNEL, GET_TITLE, GET_OPTIONS = range(3)

# ----------------- HELPER FUNCTIONS ----------------- #
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Create Poll"), KeyboardButton("📊 My Polls")]
    ], resize_keyboard=True)

def generate_poll_markup(poll_id, poll_data):
    keyboard = []
    row = []
    for idx, opt in enumerate(poll_data["options"]):
        votes = poll_data["votes"].get(opt, 0)
        btn_text = f"{opt} ({votes})"
        callback = f"vote_{poll_id}_{idx}"
        row.append(InlineKeyboardButton(btn_text, callback_data=callback))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# ----------------- BOT HANDLERS ----------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 **স্বাগতম Poll Maker Bot-এ!**\n\n"
        "এখানে খুব সহজে আকর্ষণীয় ও সুন্দর বাটন পোল তৈরি করতে পারবেন।\n"
        "পোল তৈরি করতে নিচের **➕ Create Poll** বাটনে চাপ দিন।"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- CREATE POLL CONVERSATION --- #
async def create_poll_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📢 **ধাপ ১:** পোলটি যে চ্যানেলে পোস্ট করবেন, সেই চ্যানেলের User Name দিন (যেমন: `@MyChannel`)。\n\n"
        "⚠️ *মনে রাখবেন: বটকে ওই চ্যানেলে অবশ্যই অ্যাডমিন (Post Message পারমিশন সহ) বানাতে হবে।*",
        parse_mode="Markdown"
    )
    return GET_CHANNEL

async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = update.message.text.strip()
    if not channel.startswith("@") and not channel.startswith("-100"):
        channel = "@" + channel

    # Admin check
    try:
        bot_member = await context.bot.get_chat_member(chat_id=channel, user_id=context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await update.message.reply_text("❌ বট এই চ্যানেলে অ্যাডমিন নয়! দয়া করে অ্যাডমিন বানিয়ে আবার ইউজারনেম দিন:")
            return GET_CHANNEL
    except Exception as e:
        await update.message.reply_text(f"❌ চ্যানেল খুঁজে পাওয়া যায়নি অথবা বট অ্যাডমিন নয়। এরর: {str(e)}\n\nসঠিক ইউজারনেম আবার দিন:")
        return GET_CHANNEL

    context.user_data["temp_channel"] = channel
    await update.message.reply_text("✅ চ্যানেল সফলভাবে ভেরিফাই হয়েছে!\n\n📝 **ধাপ ২:** এখন পোলের **Title / বিষয়** লিখে পাঠান:")
    return GET_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["temp_title"] = update.message.text
    context.user_data["temp_options"] = []
    await update.message.reply_text("✅ টাইটেল সেট হয়েছে!\n\n👥 **ধাপ ৩:** এবার পোলের ১ম অপশনের নাম লিখে পাঠান:")
    return GET_OPTIONS

async def receive_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opt_name = update.message.text.strip()
    context.user_data["temp_options"].append(opt_name)

    total_added = len(context.user_data["temp_options"])
    all_opts = "\n".join([f"{i+1}. {name}" for i, name in enumerate(context.user_data["temp_options"])])

    text = (
        f"📊 **পোলের প্রিভিউ:**\n"
        f"📌 বিষয়: {context.user_data['temp_title']}\n"
        f"🎯 অপশন সংখ্যা: {total_added} টি\n\n"
        f"{all_opts}\n\n"
        f"আরো নাম যোগ করতে চাইলে নিচে **➕ Add New Option** দিন অথবা তৈরি শেষ করতে **✅ Confirm & Publish** দিন।"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add New Option", callback_data="add_more_opt")],
        [InlineKeyboardButton("✅ Confirm & Publish", callback_data="confirm_publish")]
    ])

    await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    return GET_OPTIONS

async def add_more_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👉 পরবর্তী প্রার্থীর / অপশনের নাম লিখে মেসেজ পাঠান:")
    return GET_OPTIONS

async def confirm_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    channel = context.user_data.get("temp_channel")
    title = context.user_data.get("temp_title")
    options = context.user_data.get("temp_options", [])

    if len(options) < 1:
        await query.message.reply_text("❌ অন্তত ১টি অপশন থাকতে হবে!")
        return GET_OPTIONS

    poll_id = str(len(polls_db) + 101)
    polls_db[poll_id] = {
        "poll_id": poll_id,
        "owner_id": query.from_user.id,
        "channel": channel,
        "title": title,
        "options": options,
        "votes": {opt: 0 for opt in options},
        "voters": {},
        "status": "active",
        "message_id": None
    }

    # Send Poll to Channel
    poll_text = f"🗳️ **{title}**\n\n🤖 *Powered by Poll Bot*"
    markup = generate_poll_markup(poll_id, polls_db[poll_id])

    try:
        sent_msg = await context.bot.send_message(
            chat_id=channel,
            text=poll_text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        polls_db[poll_id]["message_id"] = sent_msg.message_id
        await query.edit_message_text(f"🎉 **অভিনন্দন!** পোলটি সফলভাবে {channel} চ্যানেলে পাবলিশ করা হয়েছে!\n\n🆔 পোল আইডি: `{poll_id}`", parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ চ্যানেলে পোস্ট করতে সমস্যা হয়েছে: {str(e)}")

    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=get_main_keyboard())
    return ConversationHandler.END

# --- VOTING CALLBACK HANDLER --- #
async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data.split("_")

    if len(data) != 3 or data[0] != "vote":
        return

    poll_id = data[1]
    opt_idx = int(data[2])

    if poll_id not in polls_db:
        await query.answer("❌ এই পোলটি পাওয়া যায়নি!", show_alert=True)
        return

    poll = polls_db[poll_id]

    if poll["status"] != "active":
        await query.answer("🛑 এই পোলটি বন্ধ হয়ে গিয়েছে!", show_alert=True)
        return

    # Check if user already voted
    if user_id in poll["voters"]:
        await query.answer("⚠️ আপনি ইতিমধ্যে ভোট দিয়েছেন!", show_alert=True)
        return

    selected_opt = poll["options"][opt_idx]
    poll["votes"][selected_opt] = poll["votes"].get(selected_opt, 0) + 1
    poll["voters"][user_id] = selected_opt

    await query.answer(f"✅ আপনার ভোট সফলভাবে {selected_opt} কে দেওয়া হয়েছে!", show_alert=False)

    # Update channel message
    markup = generate_poll_markup(poll_id, poll)
    try:
        await query.edit_message_reply_markup(reply_markup=markup)
    except Exception:
        pass

# --- MY POLLS & END POLL --- #
async def my_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_polls = [p for p in polls_db.values() if p["owner_id"] == user_id]

    if not user_polls:
        await update.message.reply_text("📭 আপনি এখনো কোনো পোল তৈরি করেননি।")
        return

    for p in user_polls:
        status_text = "🟢 চলমান" if p["status"] == "active" else "🔴 বন্ধ"
        summary = f"📊 **{p['title']}**\n🆔 আইডি: `{p['poll_id']}`\n📢 চ্যানেল: {p['channel']}\n📌 স্ট্যাটাস: {status_text}\n"
        
        btns = []
        if p["status"] == "active":
            btns.append([InlineKeyboardButton("🛑 End Poll (বন্ধ করুন)", callback_data=f"endpoll_{p['poll_id']}")])
        
        await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(btns) if btns else None, parse_mode="Markdown")

async def end_poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    poll_id = query.data.split("_")[1]

    if poll_id in polls_db:
        poll = polls_db[poll_id]
        if query.from_user.id == poll["owner_id"] or query.from_user.id == ADMIN_ID:
            poll["status"] = "closed"
            await query.answer("✅ পোলটি বন্ধ করা হয়েছে!")
            await query.edit_message_text(f"🛑 পোল `{poll_id}` এখন বন্ধ। আর কোনো ভোট দেওয়া যাবে না।", parse_mode="Markdown")
            
            # Channel message edit (optional disabled notice)
            try:
                await context.bot.edit_message_text(
                    chat_id=poll["channel"],
                    message_id=poll["message_id"],
                    text=f"🛑 **পোল বন্ধ করা হয়েছে!**\n\n🗳️ {poll['title']}\n\n🏆 ভোট প্রদান শেষ।",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            await query.answer("❌ শুধুমাত্র পোলের মালিক এটি বন্ধ করতে পারে!", show_alert=True)

# --- SUPER ADMIN FEATURES (ভোট ইচ্ছামতো বাড়ানো/কমানো) --- #
async def all_polls_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not polls_db:
        await update.message.reply_text("কোনো পোল নেই।")
        return

    msg = "👑 **সকল পোলের তালিকা:**\n\n"
    for p in polls_db.values():
        msg += f"🆔 ID: `{p['poll_id']}` | 📢 {p['channel']} | {p['title']} ({p['status']})\n"
        for i, opt in enumerate(p["options"]):
            msg += f"  - [{i}] {opt}: {p['votes'].get(opt, 0)} ভোট\n"
        msg += "\n"

    msg += "\n💡 **ভোট বাড়াতে লিখুন:**\n`/setvote <poll_id> <opt_index> <vote_amount>`\nউদাহরণ: `/setvote 101 0 50`"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def set_vote_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    # Command format: /setvote <poll_id> <opt_index> <votes>
    try:
        args = context.args
        poll_id = args[0]
        opt_idx = int(args[1])
        new_votes = int(args[2])

        if poll_id in polls_db:
            poll = polls_db[poll_id]
            target_opt = poll["options"][opt_idx]
            poll["votes"][target_opt] = new_votes

            # Update Channel UI
            markup = generate_poll_markup(poll_id, poll)
            await context.bot.edit_message_reply_markup(
                chat_id=poll["channel"],
                message_id=poll["message_id"],
                reply_markup=markup
            )
            await update.message.reply_text(f"✅ `{target_opt}` এর ভোট পরিবর্তন করে `{new_votes}` করা হয়েছে!")
        else:
            await update.message.reply_text("❌ Poll ID খুঁজে পাওয়া যায়নি!")
    except Exception as e:
        await update.message.reply_text(f"❌ কমান্ড ফরম্যাট ভুল!\nব্যবহার করুন: `/setvote <poll_id> <opt_index> <amount>`\nError: {e}")

# ----------------- MAIN APP ----------------- #
def main():
    # Start Flask thread for Render
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram Application
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Create Poll$"), create_poll_start),
            CommandHandler("create", create_poll_start)
        ],
        states={
            GET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel)],
            GET_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            GET_OPTIONS: [
                CallbackQueryHandler(add_more_callback, pattern="^add_more_opt$"),
                CallbackQueryHandler(confirm_publish_callback, pattern="^confirm_publish$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_options)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Regex("^📊 My Polls$"), my_polls))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern="^vote_"))
    app.add_handler(CallbackQueryHandler(end_poll_callback, pattern="^endpoll_"))
    
    # Admin Handlers
    app.add_handler(CommandHandler("allpolls", all_polls_admin))
    app.add_handler(CommandHandler("setvote", set_vote_admin))

    print("🤖 Poll Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
