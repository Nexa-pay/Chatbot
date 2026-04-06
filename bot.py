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
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient

# --- Dummy Web Server ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Deepsikha is running with Advanced Panel!"

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
            "welcome_text": "😊 Hieeeee\n😉 You're Talking To Deepsikha, A Sassy Cutie Girl.\n\n💕 Choose An Option Below :",
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
                    "$slice": -6
                }
            }
        }
    )

# Track Groups in Background
@app.on_message(filters.group, group=-1)
async def group_tracker(client, message):
    await groups_col.update_one(
        {"chat_id": message.chat.id},
        {"$set": {"title": message.chat.title}},
        upsert=True
    )

# ====================================================================
# START MENU & INLINE BUTTONS
# ====================================================================

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    settings = await get_settings()
    
    bot = await client.get_me()
    add_link = f"https://t.me/{bot.username}?startgroup=true"
    
    # Building the beautiful inline keyboard based on your image
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Groups", url=settings['link_groups']),
         InlineKeyboardButton("🥀 Owner", url=settings['link_owner'])],
        [InlineKeyboardButton("🧸 Friends", url=settings['link_friends']),
         InlineKeyboardButton("🎮 Games", url=settings['link_games'])],
        [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP 👥", url=add_link)]
    ])
    
    try:
        if settings.get("welcome_media"):
            if settings["welcome_media_type"] == "photo":
                await message.reply_photo(settings["welcome_media"], caption=settings["welcome_text"], reply_markup=keyboard)
            elif settings["welcome_media_type"] == "video":
                await message.reply_video(settings["welcome_media"], caption=settings["welcome_text"], reply_markup=keyboard)
        else:
            await message.reply_text(settings["welcome_text"], reply_markup=keyboard)
    except Exception as e:
        # Fallback if media gets deleted from Telegram servers
        await message.reply_text(settings["welcome_text"], reply_markup=keyboard)


# ====================================================================
# ADMIN & OWNER PANEL
# ====================================================================

@app.on_message(filters.command("panel") & filters.private)
async def panel_cmd(client, message):
    user_id = message.from_user.id
    settings = await get_settings()
    is_owner = (user_id == OWNER_ID)
    is_admin = (user_id in settings.get("admins", []))
    
    if not (is_owner or is_admin):
        return # Ignore normal users
        
    buttons = [
        [InlineKeyboardButton("📊 Stats", callback_data="pnl_stats"),
         InlineKeyboardButton("📢 Broadcast", callback_data="pnl_broadcast")]
    ]
    
    if is_owner:
        buttons.append([InlineKeyboardButton("👑 Owner Panel", callback_data="pnl_owner")])
        
    await message.reply_text("⚙️ **Bot Control Panel**\nSelect an option below:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query(filters.regex("^pnl_"))
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
        await callback_query.edit_message_text("📢 **How to Broadcast:**\nReply to ANY message (Text, Photo, or Video) and type `/broadcast`.\nBoth Admins and Owner can do this.")
        
    elif data == "pnl_owner":
        if not is_owner:
            await callback_query.answer("Only the Bot Owner can access this!", show_alert=True)
            return
            
        owner_text = """
👑 **OWNER PANEL INSTRUCTIONS** 👑

**1. Edit Welcome Message (Supports Media):**
Send a Photo, Video, or Text. Reply to it with: `/setwelcome`

**2. Manage Admins:**
`/addadmin <user_id>`
`/deladmin <user_id>`

**3. Edit Button Links:**
`/setlink groups <url>`
`/setlink owner <url>`
`/setlink friends <url>`
`/setlink games <url>`
`/setlink support <url>`

**4. Database Logs:**
`/dblogs` (Shows all Groups & IDs)
"""
        await callback_query.edit_message_text(owner_text)

# ====================================================================
# OWNER COMMANDS (SETTINGS & CONFIG)
# ====================================================================

@app.on_message(filters.command("setwelcome") & filters.private)
async def set_welcome_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a message (Text, Photo, or Video) with /setwelcome")
        return
        
    rep = message.reply_to_message
    media_type = None
    media_id = None
    text = rep.text or rep.caption or ""
    
    if rep.photo:
        media_type = "photo"
        media_id = rep.photo.file_id
    elif rep.video:
        media_type = "video"
        media_id = rep.video.file_id
        
    await settings_col.update_one(
        {"_id": "bot_config"},
        {"$set": {"welcome_text": text, "welcome_media": media_id, "welcome_media_type": media_type}},
        upsert=True
    )
    await message.reply("✅ New Welcome Message Saved!")

@app.on_message(filters.command("setlink") & filters.private)
async def set_link_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Usage: `/setlink <groups/owner/friends/games/support> <url>`")
        return
        
    button_target = args[1].lower()
    new_url = args[2]
    
    valid_targets = ["groups", "owner", "friends", "games", "support"]
    if button_target not in valid_targets:
        await message.reply(f"Invalid target. Choose from: {', '.join(valid_targets)}")
        return
        
    await settings_col.update_one(
        {"_id": "bot_config"},
        {"$set": {f"link_{button_target}": new_url}}
    )
    await message.reply(f"✅ {button_target.capitalize()} link updated to:\n{new_url}")

@app.on_message(filters.command("addadmin") & filters.private)
async def add_admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        new_admin = int(message.text.split()[1])
        await settings_col.update_one({"_id": "bot_config"}, {"$addToSet": {"admins": new_admin}})
        await message.reply(f"✅ Admin {new_admin} added successfully.")
    except:
        await message.reply("Usage: `/addadmin <user_id>`")

@app.on_message(filters.command("deladmin") & filters.private)
async def del_admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        old_admin = int(message.text.split()[1])
        await settings_col.update_one({"_id": "bot_config"}, {"$pull": {"admins": old_admin}})
        await message.reply(f"✅ Admin {old_admin} removed.")
    except:
        await message.reply("Usage: `/deladmin <user_id>`")

@app.on_message(filters.command("dblogs") & filters.private)
async def dblogs_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    groups = await groups_col.find().to_list(length=None)
    total_u = await users_col.count_documents({})
    
    log_text = f"📂 **DATABASE LOGS**\n\nTotal Users: {total_u}\nTotal Groups: {len(groups)}\n\n**Groups List:**\n"
    for g in groups:
        log_text += f"▪️ {g.get('title', 'Unknown')} (ID: `{g['chat_id']}`)\n"
        
    # Telegram allows max 4096 chars per message
    if len(log_text) > 4000:
        log_text = log_text[:4000] + "...\n[Message too long, truncated]"
        
    await message.reply(log_text)

# ====================================================================
# BROADCAST COMMAND (ADMINS & OWNER - SUPPORTS MEDIA)
# ====================================================================

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client, message):
    settings = await get_settings()
    user_id = message.from_user.id
    if user_id != OWNER_ID and user_id not in settings.get("admins", []):
        return
        
    if not message.reply_to_message:
        await message.reply("⚠️ Reply to a message (Text, Photo, or Video) to broadcast it.")
        return
        
    users = await users_col.find().to_list(length=None)
    sent = 0
    msg = await message.reply_text("🚀 Broadcasting...")
    
    for u in users:
        try:
            # .copy() ensures photos/videos are sent flawlessly
            await message.reply_to_message.copy(u['user_id'])
            sent += 1
            await asyncio.sleep(0.1) 
        except Exception:
            pass # Skips users who blocked the bot
            
    await msg.edit_text(f"✅ Broadcast complete!\nSent to {sent} users.")


# ====================================================================
# BAKA-STYLE CHAT AI HANDLER (UNCHANGED)
# ====================================================================
@app.on_message(filters.text & ~filters.command(["start", "panel", "broadcast", "setwelcome", "setlink", "addadmin", "deladmin", "dblogs"]))
async def handle_chat(client: Client, message: Message):
    
    is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    
    if is_group:
        bot_me = await client.get_me()
        text_lower = message.text.lower()
        is_reply_to_me = message.reply_to_message and message.reply_to_message.from_user.id == bot_me.id
        
        if "deepsikha" not in text_lower and not is_reply_to_me:
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
        try:
            await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
        except Exception:
            pass
        
        chat_completion = groq_client.chat.completions.create(
            messages=messages_payload,
            model="llama-3.1-8b-instant", 
            temperature=0.3,
            max_tokens=20 
        )
        
        ai_reply = chat_completion.choices[0].message.content.strip()
        ai_reply = ai_reply.replace("*", "") 
        
        await message.reply_text(ai_reply)
        await update_user_memory(message.from_user.id, message.text, ai_reply)

    except Exception as e:
        pass

if __name__ == "__main__":
    print("Deepsikha is running with Baka AI & Full Control Panel...")
    app.run()
