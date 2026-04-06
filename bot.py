import os
import asyncio
import threading
from flask import Flask
from datetime import datetime

# --- FIX FOR PYTHON 3.14 EVENT LOOP ERROR ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
# --------------------------------------------

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient

# --- Dummy Web Server to keep Render alive ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Deepsikha is awake with Bottom Menu Panel!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()
# --------------------------------------------

# Fetch Environment Variables
API_ID = os.getenv("API_ID") 
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID", 0))

# Initialize Clients
app = Client("deepsikha_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

# Initialize Database Collections
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["deepsikha_db"]
users_col = db["users"]
groups_col = db["groups"]
settings_col = db["settings"]

# ====================================================================
# DATABASE HELPERS
# ====================================================================

async def get_settings():
    s = await settings_col.find_one({"_id": "bot_config"})
    if not s:
        s = {
            "_id": "bot_config",
            "admins": [],
            "welcome_text": "😊 Hieeeee\n😉 You're Talking To Deepsikha , A sobo Cutie Girl.\n\n💕 Choose An Option Below :",
            "welcome_media": None,
            "welcome_media_type": None,
            "link_groups": "https://t.me/telegram",
            "link_owner": "https://t.me/telegram",
            "link_friends": "https://t.me/telegram",
            "link_games": "https://t.me/telegram",
            "link_support": "https://t.me/telegram"
        }
        await settings_col.insert_one(s)
    return s

async def get_user_profile(user_id, first_name):
    if not first_name:
        first_name = "Dost" 
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id, "name": first_name, "interactions": 0,
            "history": [], "joined_at": datetime.now()
        }
        await users_col.insert_one(user)
    return user

async def update_user_memory(user_id, user_msg, ai_reply):
    await users_col.update_one(
        {"user_id": user_id},
        {
            "$inc": {"interactions": 1},
            "$push": {
                "history": {
                    "$each": [{"role": "user", "content": user_msg}, {"role": "assistant", "content": ai_reply}],
                    "$slice": -8
                }
            }
        }
    )

@app.on_message(filters.group, group=-1)
async def group_tracker(client, message):
    await groups_col.update_one(
        {"chat_id": message.chat.id},
        {"$set": {"title": message.chat.title}},
        upsert=True
    )

# ====================================================================
# START MENU & BOTTOM KEYBOARD
# ====================================================================

def get_admin_bottom_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📢 Broadcast"), KeyboardButton("📊 Stats")],
            [KeyboardButton("📞 Contact Admin"), KeyboardButton("👑 Owner Panel")]
        ],
        resize_keyboard=True
    )

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    settings = await get_settings()
    bot = await client.get_me()
    add_link = f"https://t.me/{bot.username}?startgroup=true"
    
    # 1. Send the Welcome Message with Inline Links
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Groups", url=settings['link_groups']),
         InlineKeyboardButton("👑 Owner", url=settings['link_owner'])],
        [InlineKeyboardButton("🧸 Friends", url=settings['link_friends']),
         InlineKeyboardButton("🎮 Games", url=settings['link_games'])],
        [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP 👥", url=add_link)]
    ])
    
    try:
        if settings.get("welcome_media"):
            if settings["welcome_media_type"] == "photo":
                await message.reply_photo(settings["welcome_media"], caption=settings["welcome_text"], reply_markup=inline_kb)
            elif settings["welcome_media_type"] == "video":
                await message.reply_video(settings["welcome_media"], caption=settings["welcome_text"], reply_markup=inline_kb)
        else:
            await message.reply_text(settings["welcome_text"], reply_markup=inline_kb)
    except Exception:
        await message.reply_text(settings["welcome_text"], reply_markup=inline_kb)

    # 2. Attach the Bottom Keyboard if user is Owner/Admin
    if message.from_user.id == OWNER_ID or message.from_user.id in settings.get("admins", []):
        await message.reply_text("👇 Admin Menu Unlocked:", reply_markup=get_admin_bottom_keyboard())


# ====================================================================
# BOTTOM KEYBOARD BUTTON HANDLERS
# ====================================================================

@app.on_message(filters.regex("^👑 Owner Panel$") & filters.private)
async def owner_panel_text(client, message):
    if message.from_user.id != OWNER_ID:
        await message.reply_text("⚠️ Only Aakash can access the Owner Panel!")
        return
        
    owner_inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Welcome Msg", callback_data="own_welcome"),
         InlineKeyboardButton("🔗 Change Links", callback_data="own_links")],
        [InlineKeyboardButton("💳 UPI ID", callback_data="own_upi"),
         InlineKeyboardButton("📞 Contacts", callback_data="own_contacts")],
        [InlineKeyboardButton("👥 Add Admin", callback_data="own_addadmin"),
         InlineKeyboardButton("🚫 Remove Admin", callback_data="own_deladmin")],
        [InlineKeyboardButton("🔨 Ban User", callback_data="own_ban"),
         InlineKeyboardButton("🕊️ Unban User", callback_data="own_unban")],
        [InlineKeyboardButton("📊 Stats", callback_data="pnl_stats"),
         InlineKeyboardButton("💾 Logs (Owner)", callback_data="own_logs")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="pnl_broadcast"),
         InlineKeyboardButton("❌ Close", callback_data="own_close")]
    ])
    await message.reply_text("✨ **Advanced Control Panel:**", reply_markup=owner_inline_kb)


@app.on_message(filters.regex("^📊 Stats$") & filters.private)
async def stats_text(client, message):
    settings = await get_settings()
    if message.from_user.id != OWNER_ID and message.from_user.id not in settings.get("admins", []):
        return
        
    total_u = await users_col.count_documents({})
    active_u = await users_col.count_documents({"interactions": {"$gt": 0}})
    total_g = await groups_col.count_documents({})
    top_users = await users_col.find().sort("interactions", -1).limit(5).to_list(length=5)
    lb_text = "\n".join([f"{i+1}. {u['name']} ({u['interactions']} msgs)" for i, u in enumerate(top_users)])
    text = f"📊 **BOT STATS**\n\n👤 Total Users: {total_u}\n🔥 Active Users: {active_u}\n👥 Total Groups: {total_g}\n\n🏆 **Leaderboard:**\n{lb_text}"
    await message.reply_text(text)


@app.on_message(filters.regex("^📢 Broadcast$") & filters.private)
async def broadcast_text(client, message):
    settings = await get_settings()
    if message.from_user.id != OWNER_ID and message.from_user.id not in settings.get("admins", []):
        return
    await message.reply_text("📢 **How to Broadcast:**\nReply to ANY message (Text, Photo, Video, Document) with caption, and type `/broadcast`.")


@app.on_message(filters.regex("^📞 Contact Admin$") & filters.private)
async def contact_admin_text(client, message):
    settings = await get_settings()
    link = settings.get("link_support", "https://t.me/Aakash")
    await message.reply_text(f"📞 Contact the Admin here:\n{link}")


# ====================================================================
# INLINE CALLBACK HANDLERS (For the 12-button menu)
# ====================================================================

@app.on_callback_query(filters.regex("^(pnl_|own_)"))
async def panel_callbacks(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    settings = await get_settings()
    is_owner = (user_id == OWNER_ID)
    is_admin = (user_id in settings.get("admins", []))
    
    if not (is_owner or is_admin):
        await callback_query.answer("You are not an admin!", show_alert=True)
        return

    data = callback_query.data

    if data == "pnl_stats":
        total_u = await users_col.count_documents({})
        active_u = await users_col.count_documents({"interactions": {"$gt": 0}})
        total_g = await groups_col.count_documents({})
        top_users = await users_col.find().sort("interactions", -1).limit(5).to_list(length=5)
        lb_text = "\n".join([f"{i+1}. {u['name']} ({u['interactions']} msgs)" for i, u in enumerate(top_users)])
        text = f"📊 **BOT STATS**\n\n👤 Total Users: {total_u}\n🔥 Active Users: {active_u}\n👥 Total Groups: {total_g}\n\n🏆 **Leaderboard:**\n{lb_text}"
        await callback_query.edit_message_text(text)
        
    elif data == "pnl_broadcast":
        await callback_query.edit_message_text("📢 **How to Broadcast:**\nReply to ANY message (Text, Photo, Video) and type `/broadcast`.")

    elif data == "own_welcome":
        await callback_query.answer("Reply to a Photo/Video/Text with /setwelcome to change it!", show_alert=True)
    elif data == "own_links":
        await callback_query.answer("Type: /setlink <groups/owner/friends/games> <url> to update them!", show_alert=True)
    elif data in ["own_addadmin", "own_deladmin"]:
        await callback_query.answer(f"Type: /{data.split('_')[1]} <user_id> to manage admins.", show_alert=True)
    elif data in ["own_upi", "own_contacts", "own_ban", "own_unban"]:
        await callback_query.answer("🚧 Feature coming soon in next update!", show_alert=True)
    elif data == "own_logs":
        groups = await groups_col.find().to_list(length=None)
        total_u = await users_col.count_documents({})
        log_text = f"📂 **LOGS**\nTotal Users: {total_u}\nTotal Groups: {len(groups)}\n\n"
        for g in groups:
            log_text += f"▪️ {g.get('title', 'Unknown')} (ID: `{g['chat_id']}`)\n"
        if len(log_text) > 4000: log_text = log_text[:4000] + "..."
        await callback_query.edit_message_text(log_text)
    elif data == "own_close":
        await callback_query.message.delete()


# ====================================================================
# OWNER-ONLY COMMANDS (Backend logic)
# ====================================================================

@app.on_message(filters.command("setwelcome") & filters.private)
async def set_welcome_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a message with /setwelcome")
        return
    rep = message.reply_to_message
    media_type, media_id = None, None
    text = rep.text or rep.caption or ""
    if rep.photo:
        media_type, media_id = "photo", rep.photo.file_id
    elif rep.video:
        media_type, media_id = "video", rep.video.file_id
        
    await settings_col.update_one({"_id": "bot_config"}, {"$set": {"welcome_text": text, "welcome_media": media_id, "welcome_media_type": media_type}}, upsert=True)
    await message.reply("✅ New Welcome Message Saved!")

@app.on_message(filters.command("setlink") & filters.private)
async def set_link_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Usage: `/setlink <groups/owner/friends/games> <url>`")
        return
    target, new_url = args[1].lower(), args[2]
    if target in ["groups", "owner", "friends", "games", "support"]:
        await settings_col.update_one({"_id": "bot_config"}, {"$set": {f"link_{target}": new_url}}, upsert=True)
        await message.reply(f"✅ {target.capitalize()} link updated!")

@app.on_message(filters.command("addadmin") & filters.private)
async def add_admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        new_admin = int(message.text.split()[1])
        await settings_col.update_one({"_id": "bot_config"}, {"$addToSet": {"admins": new_admin}})
        await message.reply("✅ Admin added.")
    except: pass

@app.on_message(filters.command("deladmin") & filters.private)
async def del_admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        old_admin = int(message.text.split()[1])
        await settings_col.update_one({"_id": "bot_config"}, {"$pull": {"admins": old_admin}})
        await message.reply("✅ Admin removed.")
    except: pass

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client, message):
    settings = await get_settings()
    user_id = message.from_user.id
    if user_id != OWNER_ID and user_id not in settings.get("admins", []): return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a message to broadcast it.")
        return
    users = await users_col.find().to_list(length=None)
    sent = 0
    msg = await message.reply_text("🚀 Broadcasting...")
    for u in users:
        try:
            await message.reply_to_message.copy(u['user_id'])
            sent += 1
            await asyncio.sleep(0.1) 
        except: pass 
    await msg.edit_text(f"✅ Broadcast complete to {sent} users.")


# ====================================================================
# BAKA-STYLE CHAT AI HANDLER
# ====================================================================
@app.on_message(filters.text & ~filters.command(["start", "setwelcome", "setlink", "addadmin", "deladmin"]))
async def handle_chat(client: Client, message: Message):
    
    # Ignore bottom keyboard inputs going to the AI
    if message.text in ["👑 Owner Panel", "📊 Stats", "📢 Broadcast", "📞 Contact Admin"]:
        return

    # --- BULLETPROOF GROUP CHAT LOGIC ---
    if message.chat.type != enums.ChatType.PRIVATE:
        text_lower = message.text.lower() if message.text else ""
        is_reply_to_bot = False
        
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.is_self:
                is_reply_to_bot = True
                
        if "deepsikha" not in text_lower and not is_reply_to_bot:
            return 

    user = await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    SYSTEM_PROMPT = f"""
    You are Deepsikha, a normal Indian girl chatting casually on Telegram.
    
    CRITICAL RULES:
    1. EXTREMELY SHORT REPLIES: Use only 2 to 6 words maximum.
    2. BE DIRECT: Only answer what the user asked. Do NOT add extra poetic lines or explanations.
    3. LANGUAGE: Casual Hinglish chat spelling (e.g., 'kya kr rhe ho', 'mai theek hu', 'nhi', 'haan').
    4. NO POETRY: Stop acting like a poet. Speak like a normal teenager.
    5. EMOJIS: Use 1 simple emoji at the end of your sentence (e.g. 🙄, 😂, 😋, 🤔).
    
    EXAMPLES OF EXACTLY HOW YOU MUST REPLY:
    User: Kaise ho
    Deepsikha: Mai toh theek hu, tum batao? 😋
    User: Or Kya chal rha h
    Deepsikha: Bas kuch nahi, ghar pe hi hu. 🙄
    User: Ok or sb thik h
    Deepsikha: Haan sab thik hai. Tum kyo puch rhe ho? 🤔
    User: Aise hi mn kr Diya
    Deepsikha: Hmm. 😋
    User: Kha gye
    Deepsikha: Ghar pe hi hu, kyun? 🙄
    User: Nhi Kuch
    Deepsikha: Achha, kia kr rhe ho ab? 🥰
    """

    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in user.get("history", []):
        messages_payload.append({"role": msg["role"], "content": msg["content"]})
    messages_payload.append({"role": "user", "content": message.text})

    try:
        try: await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
        except: pass
        
        chat_completion = groq_client.chat.completions.create(
            messages=messages_payload, model="llama-3.1-8b-instant", temperature=0.3, max_tokens=20 
        )
        ai_reply = chat_completion.choices[0].message.content.strip().replace("*", "") 
        await message.reply_text(ai_reply)
        await update_user_memory(message.from_user.id, message.text, ai_reply)
    except Exception: pass

if __name__ == "__main__":
    print("Deepsikha is running with Bottom Menu Panel...")
    app.run()
