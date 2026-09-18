import os
import threading
import html
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
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TOKEN")
ADMIN_ID = 8468523960  # আপনার টেলিগ্রাম আইডি

# ----------------- FLASK SERVER (24/7 Uptime) ----------------- #
server = Flask(__name__)

@server.route('/')
def home():
    return "✅ Advance Poll Bot is active and running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# Database
polls_db = {}
config_db = {
    "force_channel": None  # এডমিন /setforce দিয়ে সেট করবে
}

# Conversation States
GET_CHANNEL, GET_TITLE, GET_OPTIONS = range(3)
EDIT_MENU, EDIT_TITLE_INPUT, CHOOSE_OPT, EDIT_OPT_INPUT = range(3, 7)

# ----------------- HELPER FUNCTIONS ----------------- #
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Create Poll"), KeyboardButton("📊 My Polls")]
    ], resize_keyboard=True)

def generate_poll_text(poll_data, bot_username):
    title = html.escape(poll_data["title"])
    total_votes = sum(poll_data["votes"].values())
    
    text = (
        f"🗳️ <b>{title}</b>\n\n"
        f"📊 <b>মোট ভোট:</b> {total_votes} টি\n"
        f"🤖 <b>Powered by</b> <a href='https://t.me/{bot_username}'>@{bot_username}</a>"
    )
    return text

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

def get_progress_bar(percentage):
    filled = int(percentage / 10)
    bar = "█" * filled + "─" * (10 - filled)
    return bar

def build_end_poll_result(poll, bot_username):
    total_votes = sum(poll["votes"].values())
    
    winner = max(poll["votes"], key=poll["votes"].get) if total_votes > 0 else "N/A"
    winner_votes = poll["votes"].get(winner, 0)

    emojis = ["🔥", "❤️", "⭐", "💎", "⚡", "🚀", "🏆", "🎯", "🎮", "🌟", "✨", "👑"]

    res = f"📋 <b>পোল: {html.escape(poll['title'])}</b>\n"
    res += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for idx, opt in enumerate(poll["options"]):
        c_votes = poll["votes"].get(opt, 0)
        pct = int((c_votes / total_votes * 100)) if total_votes > 0 else 0
        p_bar = get_progress_bar(pct)
        emoji = emojis[idx % len(emojis)]

        res += f"{emoji} <b>{html.escape(opt)}</b> ➔ {c_votes} ভোট\n"
        res += f"➯ {p_bar} {pct}%\n\n"

    res += "━━━━━━━━━━━━━━━━━━━━\n"
    res += f"👑 <b>বিজয়ী ➔</b> ⚡ <b>{html.escape(winner)}</b> ({winner_votes} ভোট)\n\n"
    res += f"📈 <b>মোট ভোট ➔</b> {total_votes} জন\n\n"
    res += f"🛑 <b>পোল এখন বন্ধ করা হয়েছে।</b>\n"
    res += f"➡️ বিজয়ীকে উপরে বেছে নেওয়া হয়েছে।\n\n"
    res += f"⚡ <i>Poll Create :- @{bot_username}</i>"

    return res

async def analyze_poll_voters(context: ContextTypes.DEFAULT_TYPE, poll):
    """ভোটারদের মেম্বারশিপ যাচাই ও বিস্তারিত পরিসংখ্যান তৈরির ফাংশন"""
    channel = poll["channel"]
    voters = poll.get("voters", {})
    options = poll.get("options", [])
    
    # গ্রুপের বর্তমান মেম্বার সংখ্যা সংগ্রহ
    try:
        group_total_members = await context.bot.get_chat_member_count(chat_id=channel)
    except Exception:
        group_total_members = "অজানা"

    opt_stats = {opt: {"total": 0, "active": 0, "left": 0} for opt in options}
    total_active = 0
    total_left = 0

    for user_id, opt in voters.items():
        if opt not in opt_stats:
            opt_stats[opt] = {"total": 0, "active": 0, "left": 0}
        opt_stats[opt]["total"] += 1
        
        try:
            m = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if m.status in ["member", "administrator", "creator", "restricted"]:
                opt_stats[opt]["active"] += 1
                total_active += 1
            else:
                opt_stats[opt]["left"] += 1
                total_left += 1
        except Exception:
            opt_stats[opt]["left"] += 1
            total_left += 1

    return {
        "group_members": group_total_members,
        "opt_stats": opt_stats,
        "total_voters": len(voters),
        "total_active": total_active,
        "total_left": total_left
    }

async def update_poll_in_channel(context: ContextTypes.DEFAULT_TYPE, poll):
    """চ্যানেলের লাইভ মেসেজ আপডেট করার ফাংশন"""
    try:
        bot_user = await context.bot.get_me()
        updated_text = generate_poll_text(poll, bot_user.username)
        markup = generate_poll_markup(poll["poll_id"], poll)
        await context.bot.edit_message_text(
            chat_id=poll["channel"],
            message_id=poll["message_id"],
            text=updated_text,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return True
    except Exception as e:
        print(f"Update channel error: {e}")
        return False

async def is_user_member_of_force_channel(user_id, context: ContextTypes.DEFAULT_TYPE):
    channel = config_db.get("force_channel")
    if not channel:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception:
        return True

# ----------------- BOT HANDLERS ----------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID and not await is_user_member_of_force_channel(user_id, context):
        channel = config_db["force_channel"]
        clean_ch = channel.replace("@", "")
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 চ্যানেলে জয়েন করুন", url=f"https://t.me/{clean_ch}")],
            [InlineKeyboardButton("🔄 চেক করুন", callback_data="check_joined")]
        ])
        await update.message.reply_text(
            f"⚠️ <b>বটটি ব্যবহার করতে হলে আপনাকে আমাদের চ্যানেলে জয়েন করতে হবে!</b>\n\n"
            f"দয়া করে নিচের চ্যানেলে জয়েন করে <b>'🔄 চেক করুন'</b> বাটনে চাপ দিন:\n👉 {channel}",
            reply_markup=markup,
            parse_mode="HTML"
        )
        return

    msg = (
        "👋 <b>স্বাগতম Poll Maker Bot-এ!</b>\n\n"
        "এখানে খুব সহজে আকর্ষণীয় বাটন পোল তৈরি, এডিট এবং ফুল অডিট রিপোর্ট দেখতে পারবেন।\n"
        "পোল তৈরি করতে নিচের <b>➕ Create Poll</b> বাটনে চাপ দিন।"
    )
    if user_id == ADMIN_ID:
        msg += "\n\n👑 <b>অ্যাডমিন কন্ট্রোল:</b>\n" \
               "• <code>/allpolls</code> - সব পোল দেখা\n" \
               "• <code>/setvote &lt;poll_id&gt; &lt;index&gt; &lt;votes&gt;</code> - ভোট বাড়ানো\n" \
               "• <code>/setforce @ChannelUsername</code> - Force Join সেট করা\n" \
               "• <code>/setforce off</code> - Force Join বন্ধ করা"
        
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_keyboard())

async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if await is_user_member_of_force_channel(user_id, context):
        await query.answer("✅ ধন্যবাদ! চ্যানেল জয়েন কনফার্ম হয়েছে।", show_alert=True)
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text="👋 স্বাগতম! এখন আপনি সহজে পোল তৈরি করতে পারবেন।\nনিচের <b>➕ Create Poll</b> বাটনে চাপ দিন।",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    else:
        await query.answer("❌ আপনি এখনো চ্যানেলে জয়েন করেননি! দয়া করে আগে জয়েন করুন।", show_alert=True)

# --- CREATE POLL CONVERSATION --- #
async def create_poll_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID and not await is_user_member_of_force_channel(user_id, context):
        channel = config_db["force_channel"]
        clean_ch = channel.replace("@", "")
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 চ্যানেলে জয়েন করুন", url=f"https://t.me/{clean_ch}")],
            [InlineKeyboardButton("🔄 চেক করুন", callback_data="check_joined")]
        ])
        await update.message.reply_text(
            f"⚠️ <b>পোল তৈরি করতে হলে আগে চ্যানেলে জয়েন করতে হবে!</b>\n\n👉 {channel}",
            reply_markup=markup,
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📢 <b>ধাপ ১:</b> পোলটি যে চ্যানেল বা গ্রুপে পোস্ট করবেন, সেটির User Name দিন (যেমন: <code>@MyChannel</code>)।\n\n"
        "⚠️ <i>বটকে ওই চ্যানেল/গ্রুপে অবশ্যই অ্যাডমিন (Post Messages পারমিশন সহ) রাখতে হবে।</i>",
        parse_mode="HTML"
    )
    return GET_CHANNEL

async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = update.message.text.strip()
    if not channel.startswith("@") and not channel.startswith("-100"):
        channel = "@" + channel

    try:
        bot_member = await context.bot.get_chat_member(chat_id=channel, user_id=context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            await update.message.reply_text("❌ বট এই চ্যানেল/গ্রুপে অ্যাডমিন নয়! দয়া করে অ্যাডমিন বানিয়ে আবার ইউজারনেম দিন:")
            return GET_CHANNEL
    except Exception:
        await update.message.reply_text("❌ চ্যানেল খুঁজে পাওয়া যায়নি অথবা বট অ্যাডমিন নয়। সঠিক ইউজারনেম আবার দিন:")
        return GET_CHANNEL

    context.user_data["temp_channel"] = channel
    await update.message.reply_text("✅ চ্যানেল/গ্রুপ ভেরিফাই হয়েছে!\n\n📝 <b>ধাপ ২:</b> এখন পোলের <b>Title / বিষয়</b> লিখে পাঠান:", parse_mode="HTML")
    return GET_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["temp_title"] = update.message.text
    context.user_data["temp_options"] = []
    await update.message.reply_text("✅ টাইটেল সেট হয়েছে!\n\n🔘 <b>ধাপ ৩:</b> এবার পোলের ১ম অপশনের নাম লিখে পাঠান:", parse_mode="HTML")
    return GET_OPTIONS

async def receive_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opt_name = update.message.text.strip()
    context.user_data["temp_options"].append(opt_name)

    total_added = len(context.user_data["temp_options"])
    all_opts = "\n".join([f"{i+1}. {html.escape(name)}" for i, name in enumerate(context.user_data["temp_options"])])

    text = (
        f"📊 <b>পোলের প্রিভিউ:</b>\n"
        f"📌 বিষয়: {html.escape(context.user_data['temp_title'])}\n"
        f"🎯 মোট অপশন: {total_added} টি\n\n"
        f"{all_opts}\n\n"
        f"আরো অপশন যোগ করতে <b>➕ Add New Option</b> চাপুন অথবা তৈরি সম্পন্ন করতে <b>✅ Confirm & Publish</b> দিন।"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add New Option", callback_data="add_more_opt")],
        [InlineKeyboardButton("✅ Confirm & Publish", callback_data="confirm_publish")]
    ])

    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return GET_OPTIONS

async def add_more_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👉 পরবর্তী অপশনের নাম লিখে মেসেজ পাঠান:")
    return GET_OPTIONS

async def confirm_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    channel = context.user_data.get("temp_channel")
    title = context.user_data.get("temp_title")
    options = context.user_data.get("temp_options", [])

    if not options:
        await query.message.reply_text("❌ কোনো অপশন নেই!")
        return GET_OPTIONS

    bot_user = await context.bot.get_me()
    poll_id = str(len(polls_db) + 101)
    
    poll_data = {
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
    polls_db[poll_id] = poll_data

    poll_text = generate_poll_text(poll_data, bot_user.username)
    markup = generate_poll_markup(poll_id, poll_data)

    try:
        sent_msg = await context.bot.send_message(
            chat_id=channel,
            text=poll_text,
            reply_markup=markup,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        polls_db[poll_id]["message_id"] = sent_msg.message_id
        await query.edit_message_text(
            f"🎉 <b>অভিনন্দন!</b> পোলটি সফলভাবে {channel} চ্যানেলে পাবলিশ করা হয়েছে!\n\n🆔 পোল আইডি: <code>{poll_id}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        await query.edit_message_text(f"❌ চ্যানেলে পোস্ট করতে সমস্যা হয়েছে: {html.escape(str(e))}")

    return ConversationHandler.END

# --- EDIT POLL CONVERSATION --- #
async def edit_poll_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    poll_id = query.data.split("_")[1]

    if poll_id not in polls_db:
        await query.answer("❌ পোলটি খুঁজে পাওয়া যায়নি!", show_alert=True)
        return ConversationHandler.END

    poll = polls_db[poll_id]
    if poll["owner_id"] != user_id and user_id != ADMIN_ID:
        await query.answer("❌ শুধুমাত্র পোলের মালিক এটি এডিট করতে পারবে!", show_alert=True)
        return ConversationHandler.END

    if poll["status"] != "active":
        await query.answer("🛑 সমাপ্ত করা পোল এডিট করা যাবে না!", show_alert=True)
        return ConversationHandler.END

    context.user_data["editing_poll_id"] = poll_id

    opts_preview = "\n".join([f"  {i+1}. {html.escape(opt)}" for i, opt in enumerate(poll["options"])])
    msg = (
        f"✏️ <b>পোল এডিট প্যানেল</b>\n\n"
        f"🆔 পোল আইডি: <code>{poll_id}</code>\n"
        f"📌 <b>বর্তমান টাইটেল:</b> {html.escape(poll['title'])}\n\n"
        f"🔘 <b>বর্তমান অপশনসমূহ:</b>\n{opts_preview}\n\n"
        f"👉 আপনি কোনটি পরিবর্তন করতে চান? নিচের বাটনে চাপ দিন:"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 বিষয়/টাইটেল পরিবর্তন", callback_data=f"edittitle_{poll_id}")],
        [InlineKeyboardButton("🔘 অপশনের নাম পরিবর্তন", callback_data=f"editoptmenu_{poll_id}")],
        [InlineKeyboardButton("❌ বাতিল", callback_data="cancel_edit")]
    ])

    await query.answer()
    await query.edit_message_text(msg, reply_markup=markup, parse_mode="HTML")
    return EDIT_MENU

async def edit_title_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 পোলের <b>নতুন টাইটেল / বিষয়</b> লিখে রিপ্লাই পাঠান:", parse_mode="HTML")
    return EDIT_TITLE_INPUT

async def save_new_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_id = context.user_data.get("editing_poll_id")
    new_title = update.message.text.strip()

    if poll_id in polls_db:
        poll = polls_db[poll_id]
        poll["title"] = new_title
        await update_poll_in_channel(context, poll)
        await update.message.reply_text(
            f"✅ <b>টাইটেল সফলভাবে পরিবর্তন হয়েছে!</b>\n\nনতুন বিষয়: <b>{html.escape(new_title)}</b>\nএবং চ্যানেলে আপডেট করে দেওয়া হয়েছে।",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    return ConversationHandler.END

async def edit_options_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    poll_id = context.user_data.get("editing_poll_id")
    poll = polls_db.get(poll_id)

    if not poll:
        await query.answer("❌ পোল পাওয়া যায়নি!", show_alert=True)
        return ConversationHandler.END

    keyboard = []
    for idx, opt in enumerate(poll["options"]):
        keyboard.append([InlineKeyboardButton(f"✏️ {idx+1}. {opt}", callback_data=f"pickopt_{idx}")])
    keyboard.append([InlineKeyboardButton("❌ বাতিল", callback_data="cancel_edit")])

    await query.answer()
    await query.edit_message_text("👉 <b>যে অপশনটি পরিবর্তন করতে চান সেটি সিলেক্ট করুন:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return CHOOSE_OPT

async def option_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    opt_idx = int(query.data.split("_")[1])
    poll_id = context.user_data.get("editing_poll_id")
    poll = polls_db.get(poll_id)

    current_opt = poll["options"][opt_idx]
    context.user_data["editing_opt_idx"] = opt_idx
    context.user_data["editing_opt_old_name"] = current_opt

    await query.answer()
    await query.edit_message_text(
        f"🔘 আপনি <b>'{html.escape(current_opt)}'</b> অপশনটি পরিবর্তন করছেন।\n\n"
        f"👉 এই অপশনের <b>নতুন নাম</b> লিখে রিপ্লাই পাঠান:",
        parse_mode="HTML"
    )
    return EDIT_OPT_INPUT

async def save_new_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_id = context.user_data.get("editing_poll_id")
    opt_idx = context.user_data.get("editing_opt_idx")
    old_name = context.user_data.get("editing_opt_old_name")
    new_name = update.message.text.strip()

    if poll_id in polls_db and opt_idx is not None:
        poll = polls_db[poll_id]
        
        # অপশন নাম রিপ্লেস এবং ভোটের হিসাব অক্ষুণ্ণ রাখা
        poll["options"][opt_idx] = new_name
        current_votes = poll["votes"].pop(old_name, 0)
        poll["votes"][new_name] = current_votes

        # ভোটারদের ডাটাতেও আপডেট
        for voter_id, voted_opt in list(poll["voters"].items()):
            if voted_opt == old_name:
                poll["voters"][voter_id] = new_name

        await update_poll_in_channel(context, poll)
        await update.message.reply_text(
            f"✅ <b>অপশন সফলভাবে পরিবর্তন করা হয়েছে!</b>\n\n"
            f"পুরাতন নাম: <s>{html.escape(old_name)}</s>\n"
            f"নতুন নাম: <b>{html.escape(new_name)}</b>\n\n"
            f"চ্যানেলে লাইভ আপডেট হয়ে গিয়েছে।",
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )
    return ConversationHandler.END

async def cancel_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("এডিট বাতিল করা হয়েছে।")
    await query.edit_message_text("❌ পোল এডিট বাতিল করা হয়েছে।")
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=get_main_keyboard())
    return ConversationHandler.END

# --- VOTING HANDLER --- #
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

    try:
        member = await context.bot.get_chat_member(chat_id=poll["channel"], user_id=user_id)
        if member.status in ["left", "kicked", "restricted"]:
            await query.answer("⚠️ ভোট দিতে হলে আগে আপনাকে এই চ্যানেল/গ্রুপে জয়েন করতে হবে!", show_alert=True)
            return
    except Exception:
        pass

    if user_id in poll["voters"]:
        await query.answer("⚠️ আপনি ইতিমধ্যে ভোট দিয়েছেন!", show_alert=True)
        return

    selected_opt = poll["options"][opt_idx]
    poll["votes"][selected_opt] = poll["votes"].get(selected_opt, 0) + 1
    poll["voters"][user_id] = selected_opt

    await query.answer(f"✅ আপনার ভোট সফলভাবে {selected_opt} এ দেওয়া হয়েছে!", show_alert=False)
    await update_poll_in_channel(context, poll)

# --- MY POLLS & END POLL (WITH RETENTION AUDIT) --- #
async def my_polls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_polls = [p for p in polls_db.values() if p["owner_id"] == user_id]

    if not user_polls:
        await update.message.reply_text("📭 আপনি এখনো কোনো পোল তৈরি করেননি।")
        return

    for p in user_polls:
        status_text = "🟢 চলমান" if p["status"] == "active" else "🔴 বন্ধ"
        summary = (
            f"📊 <b>{html.escape(p['title'])}</b>\n"
            f"🆔 আইডি: <code>{p['poll_id']}</code>\n"
            f"📢 চ্যানেল/গ্রুপ: {p['channel']}\n"
            f"📌 স্ট্যাটাস: {status_text}\n"
            f"🗳️ মোট ভোট: {sum(p['votes'].values())} জন"
        )
        
        btns = []
        if p["status"] == "active":
            btns.append([
                InlineKeyboardButton("✏️ Edit Poll", callback_data=f"editpoll_{p['poll_id']}"),
                InlineKeyboardButton("🛑 End Poll", callback_data=f"endpoll_{p['poll_id']}")
            ])
        
        await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(btns) if btns else None, parse_mode="HTML")

async def end_poll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    poll_id = query.data.split("_")[1]

    if poll_id not in polls_db:
        await query.answer("❌ পোল পাওয়া যায়নি!", show_alert=True)
        return

    poll = polls_db[poll_id]
    if query.from_user.id != poll["owner_id"] and query.from_user.id != ADMIN_ID:
        await query.answer("❌ শুধুমাত্র পোলের মালিক এটি বন্ধ করতে পারবে!", show_alert=True)
        return

    poll["status"] = "closed"
    await query.answer("⏳ পোল বন্ধ হচ্ছে এবং গ্রুপের মেম্বারদের যাচাই করা হচ্ছে...", show_alert=False)
    await query.edit_message_text("⏳ <b>পোলের ফলাফল ও মেম্বার অডিট তৈরি করা হচ্ছে... অনুগ্রহ করে একটু অপেক্ষা করুন।</b>", parse_mode="HTML")

    # ভোটার ও গ্রুপের মেম্বারশিপ অডিট অ্যানালাইসিস
    analysis = await analyze_poll_voters(context, poll)
    bot_user = await context.bot.get_me()

    total_votes = sum(poll["votes"].values())
    winner = max(poll["votes"], key=poll["votes"].get) if total_votes > 0 else "N/A"
    winner_votes = poll["votes"].get(winner, 0)

    # ওনারের জন্য বিস্তারিত রিপোর্ট তৈরি
    owner_report = (
        f"🏆 <b>পোল ফলাফল ও মেম্বার অডিট রিপোর্ট</b> 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>বিষয়:</b> {html.escape(poll['title'])}\n"
        f"🆔 <b>পোল আইডি:</b> <code>{poll_id}</code>\n"
        f"📢 <b>চ্যানেল/গ্রুপ:</b> {poll['channel']}\n"
        f"👥 <b>গ্রুপের বর্তমান মোট সদস্য:</b> <code>{analysis['group_members']}</code> জন\n\n"
        f"👑 <b>বিজয়ী অপশন ➔</b> ⚡ <b>{html.escape(winner)}</b> ({winner_votes} ভোট)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>অপশন ভিত্তিক মেম্বার উপস্থিতি বিশ্লেষণ:</b>\n\n"
    )

    for idx, opt in enumerate(poll["options"]):
        stat = analysis["opt_stats"].get(opt, {"total": 0, "active": 0, "left": 0})
        owner_report += (
            f"🔹 <b>{idx+1}. {html.escape(opt)}</b>\n"
            f"   • মোট ভোট: {stat['total']} টি\n"
            f"   • বর্তমানে গ্রুপে আছে: <b>{stat['active']} জন</b> ✅\n"
            f"   • গ্রুপ ত্যাগ করেছে: <b>{stat['left']} জন</b> ❌\n\n"
        )

    retention_rate = int((analysis['total_active'] / analysis['total_voters'] * 100)) if analysis['total_voters'] > 0 else 0

    owner_report += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>সারসংক্ষেপ:</b>\n"
        f"🗳️ সর্বমোট অংশগ্রহণকারী: {analysis['total_voters']} জন\n"
        f"✅ গ্রুপে উপস্থিত ভোটার: {analysis['total_active']} জন ({retention_rate}%)\n"
        f"❌ গ্রুপ ত্যাগকারী ভোটার: {analysis['total_left']} জন\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛑 <i>পোলটি সফলভাবে বন্ধ এবং চ্যানেলে ফলাফল পোস্ট করা হয়েছে।</i>"
    )

    await query.edit_message_text(owner_report, parse_mode="HTML")

    # চ্যানেলে চূড়ান্ত ফলাফল পোস্ট করা
    try:
        result_text = build_end_poll_result(poll, bot_user.username)
        result_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧊 বিনামূল্যে পোল তৈরি করুন", url=f"https://t.me/{bot_user.username}")]
        ])
        
        await context.bot.edit_message_text(
            chat_id=poll["channel"],
            message_id=poll["message_id"],
            text=result_text,
            reply_markup=result_btn,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"End poll error in channel: {e}")

# --- SUPER ADMIN FEATURES --- #
async def all_polls_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not polls_db:
        await update.message.reply_text("📭 কোনো পোল তৈরি করা হয়নি।")
        return

    msg = "👑 <b>সকল পোলের তালিকা:</b>\n\n"
    for p in polls_db.values():
        msg += f"🆔 <b>ID:</b> <code>{p['poll_id']}</code> | 📢 {p['channel']} | {p['status']}\n"
        msg += f"📌 <b>টাইটেল:</b> {html.escape(p['title'])}\n"
        for i, opt in enumerate(p["options"]):
            msg += f"   ➡️ Index [{i}] : {opt} 👉 <code>{p['votes'].get(opt, 0)}</code> ভোট\n"
        msg += "-------------------------\n"

    msg += "\n💡 <b>ভোট বাড়াতে লিখুন:</b>\n<code>/setvote &lt;poll_id&gt; &lt;index&gt; &lt;votes&gt;</code>\nযেমন: <code>/setvote 101 0 50</code>"
    await update.message.reply_text(msg, parse_mode="HTML")

async def set_vote_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        args = context.args
        poll_id = args[0]
        opt_idx = int(args[1])
        new_votes = int(args[2])

        if poll_id in polls_db:
            poll = polls_db[poll_id]
            target_opt = poll["options"][opt_idx]
            poll["votes"][target_opt] = new_votes

            await update_poll_in_channel(context, poll)
            await update.message.reply_text(f"✅ <code>{target_opt}</code> এর ভোট পরিবর্তন করে <code>{new_votes}</code> করা হয়েছে!", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Poll ID পাওয়া যায়নি!")
    except Exception as e:
        await update.message.reply_text(f"❌ এরর: {str(e)}\nব্যবহার: <code>/setvote 101 0 50</code>", parse_mode="HTML")

async def set_force_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        channel = context.args[0]
        if channel.lower() == "off":
            config_db["force_channel"] = None
            await update.message.reply_text("✅ Force Join বন্ধ করা হয়েছে।")
        else:
            if not channel.startswith("@"):
                channel = "@" + channel
            config_db["force_channel"] = channel
            await update.message.reply_text(f"✅ বট ব্যবহারের জন্য Force Join সেট করা হয়েছে: <b>{channel}</b>\n\nএখন যে কেউ বট দিয়ে পোল বানাতে চাইলে তাকে আগে এই চ্যানেলে জয়েন করতে হবে।", parse_mode="HTML")
    except Exception:
        await update.message.reply_text("❌ ব্যবহার করুন:\n• <code>/setforce @ChannelUsername</code>\n• <code>/setforce off</code>", parse_mode="HTML")

# ----------------- MAIN RUNNER ----------------- #
def main():
    if not BOT_TOKEN:
        print("❌ ERROR: Token not found!")
        return

    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Create Poll Conversation
    create_conv = ConversationHandler(
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

    # Edit Poll Conversation
    edit_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_poll_start, pattern="^editpoll_")
        ],
        states={
            EDIT_MENU: [
                CallbackQueryHandler(edit_title_chosen, pattern="^edittitle_"),
                CallbackQueryHandler(edit_options_menu, pattern="^editoptmenu_"),
                CallbackQueryHandler(cancel_edit_callback, pattern="^cancel_edit$")
            ],
            EDIT_TITLE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_title)
            ],
            CHOOSE_OPT: [
                CallbackQueryHandler(option_picked, pattern="^pickopt_"),
                CallbackQueryHandler(cancel_edit_callback, pattern="^cancel_edit$")
            ],
            EDIT_OPT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_new_option)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            CallbackQueryHandler(cancel_edit_callback, pattern="^cancel_edit$")
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="^check_joined$"))
    app.add_handler(create_conv)
    app.add_handler(edit_conv)
    app.add_handler(MessageHandler(filters.Regex("^📊 My Polls$"), my_polls))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern="^vote_"))
    app.add_handler(CallbackQueryHandler(end_poll_callback, pattern="^endpoll_"))
    
    # Admin Handlers
    app.add_handler(CommandHandler("allpolls", all_polls_admin))
    app.add_handler(CommandHandler("setvote", set_vote_admin))
    app.add_handler(CommandHandler("setforce", set_force_channel))

    print("🤖 Advance Poll Bot is running perfectly...")
    app.run_polling()

if __name__ == "__main__":
    main()
