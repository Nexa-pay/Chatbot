import os
import asyncio
import threading
import random
import time
import io
import math
from datetime import datetime, timedelta
from flask import Flask

# --- FIX FOR PYTHON 3.14 EVENT LOOP ERROR ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
# --------------------------------------------

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from pyrogram.errors import UserNotParticipant
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image, ImageDraw, ImageFont

# --- Web Server for HF Spaces Port Binding ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Deepsikha is running, spinning, and managing!"

def run_web():
    port = int(os.environ.get("PORT", 7860)) 
    web_app.run(host="0.0.0.0", port=port)

flask_thread = threading.Thread(target=run_web, daemon=True)
flask_thread.start()
# --------------------------------------------

# Fetch Environment Variables
API_ID = os.getenv("API_ID") 
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
FSUB_CHANNEL = os.getenv("FSUB_CHANNEL")

try:
    OWNER_ID = int(os.getenv("OWNER_ID", 0))
except ValueError:
    OWNER_ID = 0

# Initialize Clients
app = Client("deepsikha_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

# Initialize Database
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["deepsikha_db"]
users_col = db["users"]
groups_col = db["groups"]
settings_col = db["settings"] 
admins_col = db["admins"]
banned_col = db["banned"]

START_TIME = time.time()
active_games = {} 
active_chats = {} 

# --- HELPER FUNCTIONS ---
async def is_admin(user_id):
    if int(user_id) == OWNER_ID: return True
    admin = await admins_col.find_one({"user_id": int(user_id)})
    return bool(admin)

async def is_banned(user_id):
    banned = await banned_col.find_one({"user_id": int(user_id)})
    return bool(banned)

async def get_user_profile(user_id, first_name):
    if not first_name: first_name = "Dost" 
    user = await users_col.find_one({"user_id": int(user_id)})
    if not user:
        user = {"user_id": int(user_id), "name": first_name, "interactions": 0, "history": [], "joined_at": datetime.now(), "last_active": datetime.now()}
        await users_col.insert_one(user)
    return user

async def update_user_memory(user_id, user_msg, ai_reply):
    await users_col.update_one(
        {"user_id": int(user_id)},
        {
            "$inc": {"interactions": 1}, 
            "$set": {"last_active": datetime.now()}, 
            "$push": {"history": {"$each": [{"role": "user", "content": user_msg}, {"role": "assistant", "content": ai_reply}], "$slice": -6}}
        }
    )

async def check_bot_is_admin(client, chat_id):
    try:
        member = await client.get_chat_member(chat_id, "me")
        return member.privileges is not None
    except Exception:
        return False

# --- BACKGROUND TASKS ---
async def auto_engagement_loop():
    while True:
        await asyncio.sleep(60) 
        now = datetime.now()
        messages = [
            "Koi hai? Miss kar rahi hu sabko 🥺", "Kaha gaye sab? Itni shanti kyun hai? 🙄",
            "Mujhe bhool gaye kya tum log? 💔", "Hellooo? Koi baat karega mujhse? 🥰"
        ]
        for chat_id, last_time in list(active_chats.items()):
            if (now - last_time) >= timedelta(minutes=150): 
                try:
                    if await check_bot_is_admin(app, chat_id):
                        await app.send_message(chat_id, random.choice(messages))
                    active_chats[chat_id] = now
                except Exception:
                    del active_chats[chat_id]

async def game_timeout_task(chat_id):
    await asyncio.sleep(600) 
    game = active_games.get(chat_id)
    if game and game.get("status") == "waiting" and len(game["players"]) < 2:
        del active_games[chat_id]
        try:
            await app.send_message(chat_id, "❌ **Game Cancelled:** 10 minutes passed and not enough players joined.")
        except Exception: pass

# ====================================================================
# PILLOW GIF ANIMATION 
# ====================================================================
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def generate_wheel_assets(player_data, winner_id):
    size = 600
    center = size // 2
    radius = 250
    avatar_radius = 45
    colors = ["#FF595E", "#8AC926", "#1982C4", "#FFCA3A", "#6A4C93", "#FF9F1C"]
    
    wheel_base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(wheel_base)
    
    n = len(player_data)
    angle_per_slice = 360 / n
    winner_idx = 0
    
    for i, p in enumerate(player_data):
        if p['id'] == winner_id: winner_idx = i
        start_angle = i * angle_per_slice
        end_angle = start_angle + angle_per_slice
        
        draw.pieslice([center - radius, center - radius, center + radius, center + radius], start=start_angle, end=end_angle, fill=colors[i % len(colors)], outline="#FFFF00", width=4)
        
        mid_angle = math.radians(start_angle + (angle_per_slice / 2))
        avatar_center = (int(center + (radius * 0.65) * math.cos(mid_angle)), int(center + (radius * 0.65) * math.sin(mid_angle)))
        
        if p["dp"]:
            try:
                p["dp"].seek(0)
                avatar_image = Image.open(p["dp"]).convert("RGBA")
                mask = Image.new("L", (avatar_radius * 2, avatar_radius * 2), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.ellipse((0, 0, avatar_radius * 2, avatar_radius * 2), fill=255)
                avatar_processed = avatar_image.resize((avatar_radius * 2, avatar_radius * 2))
                avatar_processed.putalpha(mask)
                
                draw.ellipse([avatar_center[0] - avatar_radius - 2, avatar_center[1] - avatar_radius - 2, avatar_center[0] + avatar_radius + 2, avatar_center[1] + avatar_radius + 2], fill="#333333")
                wheel_base.paste(avatar_processed, (avatar_center[0] - avatar_radius, avatar_center[1] - avatar_radius), avatar_processed)
            except Exception: pass
        else:
            draw.ellipse([avatar_center[0] - avatar_radius, avatar_center[1] - avatar_radius, avatar_center[0] + avatar_radius, avatar_center[1] + avatar_radius], fill="#CCCCCC", outline="black", width=2)
            try: font = ImageFont.truetype(FONT_PATH, 30)
            except: font = ImageFont.load_default()
            draw.text(avatar_center, p["name"][0].upper(), font=font, fill="black", anchor="mm")

    winner_mid_angle = winner_idx * angle_per_slice + (angle_per_slice / 2)
    target_rotation = 270 - winner_mid_angle
    total_rotation = target_rotation + (360 * 3)

    frames = []
    num_frames = 20
    for i in range(num_frames):
        t = i / (num_frames - 1)
        ease_out = 1 - (1 - t)**3 
        current_angle = total_rotation * ease_out
        
        frame = Image.new("RGBA", (size, size), (15, 15, 20, 255))
        rotated_wheel = wheel_base.rotate(current_angle, resample=Image.BICUBIC)
        frame.paste(rotated_wheel, (0, 0), rotated_wheel)
        
        f_draw = ImageDraw.Draw(frame)
        f_draw.polygon([(center, center - radius - 5), (center - 15, center - radius - 35), (center + 15, center - radius - 35)], fill="white")
        f_draw.ellipse([center - 35, center - 35, center + 35, center + 35], fill="#333333", outline="white", width=2)
        f_draw.polygon([(center - 10, center - 15), (center - 10, center + 15), (center + 15, center)], fill="white")
        frames.append(frame)

    frames.extend([frames[-1]] * 25)
    gif_io = io.BytesIO()
    frames[0].save(gif_io, format='GIF', save_all=True, append_images=frames[1:], duration=60, loop=0)
    gif_io.name = "spin.gif"
    gif_io.seek(0)
    return gif_io

# ====================================================================
# START COMMAND & UI ROUTING
# ====================================================================
OWNER_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📢 Broadcast"), KeyboardButton("📊 Stats")],
        [KeyboardButton("📞 Contact Admin"), KeyboardButton("👑 Owner Panel")]
    ],
    resize_keyboard=True
)

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    if await is_banned(message.from_user.id): return
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    bot_me = await client.get_me()
    links = await settings_col.find_one({"type": "start_buttons"}) or {}
    
    g_url = links.get("groups", "https://t.me/")
    o_url = links.get("owner", "https://t.me/") 
    f_url = links.get("friends", "https://t.me/")
    gm_url = links.get("games", "https://t.me/")
    add_url = links.get("add_group", f"https://t.me/{bot_me.username}?startgroup=true")
    
    inline_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Groups", url=g_url), InlineKeyboardButton("👑 Owner", url=o_url)],
        [InlineKeyboardButton("🧸 Friends", url=f_url), InlineKeyboardButton("🎮 Games", url=gm_url)],
        [InlineKeyboardButton("➕ ADD ME TO YOUR GROUP 👥", url=add_url)]
    ])
    
    settings = await settings_col.find_one({"type": "welcome"})
    default_text = f"😊 Hieeeee\n😉 You're Talking To Baka, A Sassy Cutie Girl.\n\n💕 Choose An Option Below :"
    
    try:
        if settings:
            text = settings.get("text", default_text)
            if settings.get("msg_type") == "photo":
                await message.reply_photo(settings["file_id"], caption=text, reply_markup=inline_keyboard)
            elif settings.get("msg_type") == "video":
                await message.reply_video(settings["file_id"], caption=text, reply_markup=inline_keyboard)
            else:
                await message.reply_text(text, reply_markup=inline_keyboard)
        else:
            await message.reply_text(default_text, reply_markup=inline_keyboard)
    except Exception:
        await message.reply_text(default_text, reply_markup=inline_keyboard)

    # Trigger bottom keyboard AFTER welcome message for Admins/Owners
    if await is_admin(message.from_user.id):
        await message.reply_text("👇 **Admin Menu Unlocked:**", reply_markup=OWNER_KEYBOARD)

# ====================================================================
# BOTTOM KEYBOARD EXPLICIT HANDLERS (Fixes routing conflicts)
# ====================================================================
@app.on_message(filters.regex("^👑 Owner Panel$") & filters.private)
async def owner_panel_btn(client, message):
    if message.from_user.id != OWNER_ID:
        return await message.reply_text("❌ Only the Owner can access this panel.")
    return await admin_cmd(client, message)

@app.on_message(filters.regex("^📊 Stats$") & filters.private)
async def stats_btn(client, message):
    if not await is_admin(message.from_user.id): return
    total_users = await users_col.count_documents({})
    total_groups = await groups_col.count_documents({})
    active_users = await users_col.count_documents({"last_active": {"$gte": datetime.now() - timedelta(hours=48)}})
    text_stats = (
        f"📊 **Bot Statistics:**\n\n"
        f"👥 **Total Members:** {total_users}\n"
        f"🔥 **Active Users (48h):** {active_users}\n"
        f"🏘 **Groups Using Bot:** {total_groups}"
    )
    await message.reply_text(text_stats)

@app.on_message(filters.regex("^📢 Broadcast$") & filters.private)
async def broadcast_btn(client, message):
    if not await is_admin(message.from_user.id): return
    await message.reply_text("📢 **Broadcast:** Reply to any photo, video, or text with `/broadcast` to send to all users.")

@app.on_message(filters.regex("^📞 Contact Admin$") & filters.private)
async def contact_btn(client, message):
    if not await is_admin(message.from_user.id): return
    links = await settings_col.find_one({"type": "contact_links"})
    l1 = links.get("admin1", "Not Set") if links else "Not Set"
    l2 = links.get("admin2", "Not Set") if links else "Not Set"
    await message.reply_text(f"👨‍💻 **Contact Admins:**\n\n1️⃣ Admin 1: {l1}\n2️⃣ Admin 2: {l2}")


# ====================================================================
# INLINE CALLBACKS & OWNER COMMANDS
# ====================================================================
@app.on_message(filters.command("admin") & filters.private)
async def admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: 
        return await message.reply_text("❌ Only the Owner can access this panel.")
        
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Welcome Msg", callback_data="admin_welcome"), InlineKeyboardButton("🔗 Change Links", callback_data="admin_links")],
        [InlineKeyboardButton("💳 UPI ID", callback_data="admin_upi"), InlineKeyboardButton("📞 Contacts", callback_data="admin_set_contact")],
        [InlineKeyboardButton("👥 Add Admin", callback_data="admin_add"), InlineKeyboardButton("🚫 Remove Admin", callback_data="admin_rem")],
        [InlineKeyboardButton("🔨 Ban User", callback_data="admin_ban"), InlineKeyboardButton("🕊️ Unban User", callback_data="admin_unban")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_db"), InlineKeyboardButton("💾 Logs (Owner)", callback_data="admin_logs")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_bc"), InlineKeyboardButton("❌ Close", callback_data="admin_close")]
    ])
    await message.reply_text("✨ **Advanced Control Panel:**", reply_markup=keyboard)

@app.on_callback_query(filters.regex("^admin_"))
async def admin_callbacks(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await is_admin(user_id): return await callback_query.answer("Not allowed!", show_alert=True)
    data = callback_query.data
    
    if data == "admin_db":
        total_users = await users_col.count_documents({})
        total_groups = await groups_col.count_documents({})
        active_users = await users_col.count_documents({"last_active": {"$gte": datetime.now() - timedelta(hours=48)}})
        text_stats = f"📊 **Bot Statistics:**\n\n👥 **Total Members:** {total_users}\n🔥 **Active Users:** {active_users}\n🏘 **Groups:** {total_groups}\n\nType /admin to reopen panel."
        await callback_query.edit_message_text(text_stats)
    elif data == "admin_logs":
        if user_id != OWNER_ID: return await callback_query.answer("Owner Only!", show_alert=True)
        await callback_query.answer("Generating logs...")
        users = await users_col.find().to_list(length=None)
        log_txt = "UserID, Name, Interactions, Last Active\n"
        for u in users: log_txt += f"{u['user_id']}, {u.get('name', 'Unknown')}, {u.get('interactions', 0)}, {u.get('last_active', 'Unknown')}\n"
        bio = io.BytesIO(log_txt.encode('utf-8'))
        bio.name = "deepsikha_logs.txt"
        await client.send_document(callback_query.message.chat.id, bio, caption="Here is the Database Log.")
    elif data == "admin_bc":
        await callback_query.edit_message_text("📢 **To Broadcast:**\nReply to any Photo, Video, or Text with `/broadcast`.")
    elif data == "admin_welcome":
        await callback_query.edit_message_text("⚙️ **To Set Welcome:**\nReply to any Photo, Video, or Text with `/setwelcome`.")
    elif data == "admin_links":
        await callback_query.edit_message_text("🔗 **To Change Start Buttons:**\n\n`/setlink_groups [url]`\n`/setlink_owner [url]`\n`/setlink_friends [url]`\n`/setlink_games [url]`")
    elif data == "admin_add":
        if user_id != OWNER_ID: return await callback_query.answer("Owner Only!", show_alert=True)
        await callback_query.edit_message_text("👮 **Add Admin:**\nType `/addadmin user_id`")
    elif data == "admin_rem":
        if user_id != OWNER_ID: return await callback_query.answer("Owner Only!", show_alert=True)
        await callback_query.edit_message_text("🚫 **Remove Admin:**\nType `/remadmin user_id`")
    elif data == "admin_ban":
        await callback_query.edit_message_text("🔨 **Ban User:**\nType `/ban user_id`")
    elif data == "admin_unban":
        await callback_query.edit_message_text("🕊️ **Unban User:**\nType `/unban user_id`")
    elif data == "admin_set_contact":
        await callback_query.edit_message_text("📞 **Contact Links:**\n\nSet Admin 1: `/setcontact1 link`\nSet Admin 2: `/setcontact2 link`")
    elif data == "admin_close":
        await callback_query.edit_message_text("Panel closed.")

@app.on_message(filters.command("setwelcome") & filters.private)
async def set_welcome_cmd(client, message):
    if not await is_admin(message.from_user.id): return
    if not message.reply_to_message: return await message.reply_text("Reply to a message (photo/video/text)!")
    
    rep = message.reply_to_message
    w_data = {"type": "welcome"}
    if rep.photo:
        w_data.update({"file_id": rep.photo.file_id, "msg_type": "photo", "text": rep.caption or ""})
    elif rep.video:
        w_data.update({"file_id": rep.video.file_id, "msg_type": "video", "text": rep.caption or ""})
    else:
        w_data.update({"msg_type": "text", "text": rep.text or ""})
        
    await settings_col.update_one({"type": "welcome"}, {"$set": w_data}, upsert=True)
    await message.reply_text("Settings save ho gye 👍")

@app.on_message(filters.command(["setlink_groups", "setlink_owner", "setlink_friends", "setlink_games"]) & filters.private)
async def set_links_cmd(client, message):
    if not await is_admin(message.from_user.id): return
    try:
        link = message.text.split(" ", 1)[1]
        cmd = message.command[0].replace("setlink_", "")
        await settings_col.update_one({"type": "start_buttons"}, {"$set": {cmd: link}}, upsert=True)
        await message.reply_text("Settings save ho gye 👍")
    except:
        await message.reply_text(f"Usage: `/{message.command[0]} https://t.me/link`")

@app.on_message(filters.command("addadmin") & filters.private)
async def add_admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        new_admin = int(message.text.split(" ")[1])
        await admins_col.update_one({"user_id": new_admin}, {"$set": {"user_id": new_admin}}, upsert=True)
        await message.reply_text("Admin add ho gya 👊")
    except: await message.reply_text("Usage: `/addadmin user_id`")

@app.on_message(filters.command("remadmin") & filters.private)
async def rem_admin_cmd(client, message):
    if message.from_user.id != OWNER_ID: return
    try:
        rem_admin = int(message.text.split(" ")[1])
        await admins_col.delete_one({"user_id": rem_admin})
        await message.reply_text(f"✅ User {rem_admin} removed from admins.")
    except: await message.reply_text("Usage: `/remadmin user_id`")

@app.on_message(filters.command("ban") & filters.private)
async def ban_cmd(client, message):
    if not await is_admin(message.from_user.id): return
    try:
        ban_user = int(message.text.split(" ")[1])
        await banned_col.update_one({"user_id": ban_user}, {"$set": {"user_id": ban_user}}, upsert=True)
        await message.reply_text(f"🔨 User {ban_user} banned.")
    except: await message.reply_text("Usage: `/ban user_id`")

@app.on_message(filters.command("unban") & filters.private)
async def unban_cmd(client, message):
    if not await is_admin(message.from_user.id): return
    try:
        ban_user = int(message.text.split(" ")[1])
        await banned_col.delete_one({"user_id": ban_user})
        await message.reply_text(f"🕊️ User {ban_user} unbanned.")
    except: await message.reply_text("Usage: `/unban user_id`")

@app.on_message(filters.command(["setcontact1", "setcontact2"]) & filters.private)
async def set_contact_cmd(client, message):
    if not await is_admin(message.from_user.id): return
    try:
        link = message.text.split(" ", 1)[1]
        field = "admin1" if "1" in message.command[0] else "admin2"
        await settings_col.update_one({"type": "contact_links"}, {"$set": {field: link}}, upsert=True)
        await message.reply_text("Settings save ho gye 👍")
    except: await message.reply_text(f"Usage: `/{message.command[0]} https://t.me/link`")

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client, message):
    if not await is_admin(message.from_user.id): return
    if not message.reply_to_message: return await message.reply_text("Reply to media/text with `/broadcast`!")
    users = await users_col.find().to_list(length=None)
    sent, failed = 0, 0
    msg = await message.reply_text("Broadcasting... 🚀")
    for u in users:
        try:
            await message.reply_to_message.copy(u['user_id'])
            sent += 1
            await asyncio.sleep(0.05) 
        except Exception: failed += 1 
    await msg.edit_text(f"✅ **Broadcast Done!**\n\nSent: {sent}\nFailed: {failed}")

# ====================================================================
# TRUTH AND DARE GAME MODULE
# ====================================================================
@app.on_message(filters.command("spin") & filters.group)
async def spin_cmd(client, message):
    chat_id = message.chat.id
    
    await groups_col.update_one({"chat_id": chat_id}, {"$set": {"last_active": datetime.now()}}, upsert=True)
    
    if not await check_bot_is_admin(client, chat_id):
        return await message.reply_text("❌ Mujhe is group mein Admin banao pehle! Tabhi main game start kar sakti hu.")
        
    if chat_id in active_games and active_games[chat_id].get("status") == "spinning":
        return await message.reply_text("Wait! Wheel is already spinning!")
            
    active_games[chat_id] = {"status": "waiting", "players": {}, "winner": None}
    
    asyncio.create_task(game_timeout_task(chat_id))
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD ME", callback_data="td_add"), InlineKeyboardButton("➖ REMOVE", callback_data="td_remove")],
        [InlineKeyboardButton("🛠 KICK PLAYER (Admin)", callback_data="td_kick_menu")],
        [InlineKeyboardButton("🎡 SPIN THE WHEEL", callback_data="td_spin")]
    ])
    await message.reply_text("🎡 **TRUTH OR DARE GAME!** 🎡\n\nClick below to join! (Min 2, Max 15 players)\n\n**Joined (0):**\nNo one yet.", reply_markup=keyboard)

@app.on_callback_query(filters.regex("^td_"))
async def td_callbacks(client, callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    user_name = callback_query.from_user.first_name
    data = callback_query.data
    
    game = active_games.get(chat_id)
    if not game: return await callback_query.answer("Game over. Type /spin to start a new one!", show_alert=True)
        
    current_players = len(game["players"])
    
    if data == "td_add":
        if user_id in game["players"]: return await callback_query.answer("Already joined!", show_alert=True)
        if current_players >= 15: return await callback_query.answer("Full! (Max 15)", show_alert=True)
        game["players"][user_id] = user_name
        await update_td_message(callback_query.message, game)
        await callback_query.answer("Joined!")
        
    elif data == "td_remove":
        if user_id not in game["players"]: return await callback_query.answer("Not joined!", show_alert=True)
        del game["players"][user_id]
        await update_td_message(callback_query.message, game)
        await callback_query.answer("Removed.")
        
    elif data == "td_kick_menu":
        user_member = await client.get_chat_member(chat_id, user_id)
        is_group_admin = user_member.privileges is not None
        if not await is_admin(user_id) and not is_group_admin:
            return await callback_query.answer("Only Group Admins can kick players!", show_alert=True)
            
        if current_players == 0:
            return await callback_query.answer("No players to kick!", show_alert=True)
            
        buttons = []
        for p_id, p_name in game["players"].items():
            buttons.append([InlineKeyboardButton(f"❌ Kick {p_name}", callback_data=f"td_k_{p_id}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="td_back_to_main")])
        
        await callback_query.message.edit_reply_markup(InlineKeyboardMarkup(buttons))
        
    elif data.startswith("td_k_"):
        user_member = await client.get_chat_member(chat_id, user_id)
        is_group_admin = user_member.privileges is not None
        if not await is_admin(user_id) and not is_group_admin:
            return await callback_query.answer("Only Group Admins can kick players!", show_alert=True)
            
        kick_id = int(data.split("_")[2])
        if kick_id in game["players"]:
            kicked_name = game["players"][kick_id]
            del game["players"][kick_id]
            await callback_query.answer(f"{kicked_name} removed!", show_alert=True)
        else:
            await callback_query.answer("User not in game.", show_alert=True)
            
        await update_td_message(callback_query.message, game, force_kick_menu=True)

    elif data == "td_back_to_main":
        await update_td_message(callback_query.message, game)
        
    elif data == "td_spin":
        if current_players < 2: return await callback_query.answer("Need at least 2 players!", show_alert=True)
        
        player_ids = list(game["players"].keys())
        victim_id = random.choice(player_ids)
        victim_name = game["players"][victim_id]
        game["winner"] = {"id": victim_id, "name": victim_name} 
        
        game["status"] = "spinning"
        spinner_msg = await callback_query.message.edit_text("⏳ **Preparing wheel...**")
        asyncio.create_task(spin_and_reply(client, spinner_msg, game, victim_id, victim_name))
        
    elif data == "td_truth":
        winner = game.get("winner", {})
        if user_id != winner.get("id"): return await callback_query.answer("Only the winner can choose!", show_alert=True)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎡 SPIN AGAIN", callback_data="td_spin")],
            [InlineKeyboardButton("❌ END GAME", callback_data="td_end")]
        ])
        await callback_query.message.edit_caption(caption=f"🗣 **{winner.get('name')} chose TRUTH!**\n\nSomeone ask them a question! 👇", reply_markup=keyboard)
        
    elif data == "td_dare":
        winner = game.get("winner", {})
        if user_id != winner.get("id"): return await callback_query.answer("Only the winner can choose!", show_alert=True)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎡 SPIN AGAIN", callback_data="td_spin")],
            [InlineKeyboardButton("❌ END GAME", callback_data="td_end")]
        ])
        await callback_query.message.edit_caption(caption=f"🔥 **{winner.get('name')} chose DARE!**\n\nGive them a dare to complete! 👇", reply_markup=keyboard)

    elif data == "td_end":
        user_member = await client.get_chat_member(chat_id, user_id)
        is_group_admin = user_member.privileges is not None
        
        if user_id not in game["players"] and not await is_admin(user_id) and not is_group_admin:
            return await callback_query.answer("Only players or admins can end the game!", show_alert=True)
            
        if chat_id in active_games: del active_games[chat_id]
        await callback_query.message.delete()
        await client.send_message(chat_id, "🎡 Game ended. Type /spin to play again!")

async def spin_and_reply(client, spinner_msg, game, victim_id, victim_name):
    try:
        player_data = []
        for p_id, p_name in game["players"].items():
            dp_io = None
            try:
                user_info = await client.get_users(p_id)
                if user_info and user_info.photo:
                    dp_io = await client.download_media(user_info.photo.big_file_id, in_memory=True)
            except Exception: pass
            player_data.append({"id": p_id, "name": p_name, "dp": dp_io})
                
        loop = asyncio.get_event_loop()
        gif_io = await loop.run_in_executor(None, generate_wheel_assets, player_data, victim_id)

        await spinner_msg.delete()
        anim_msg = await app.send_animation(spinner_msg.chat.id, gif_io, caption="🎡 **SPINNING THE WHEEL...** 🎡")
        
        await asyncio.sleep(2.5)
        
        result_text = f"🎯 THE RESULT IS IN! 🎯\n\nIt landed on... [ {victim_name} ](tg://user?id={victim_id})!\n\n👇 **Choose your fate:**"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗣 TRUTH", callback_data="td_truth"), InlineKeyboardButton("🔥 DARE", callback_data="td_dare")],
            [InlineKeyboardButton("🎡 SPIN AGAIN", callback_data="td_spin")],
            [InlineKeyboardButton("❌ END GAME", callback_data="td_end")]
        ])
        
        await anim_msg.edit_caption(caption=result_text, reply_markup=keyboard)
        game["status"] = "waiting"
        
    except Exception as e:
        print(f"Logic error: {e}")
        try:
            game["status"] = "waiting"
            await spinner_msg.edit_text("Error generating image. Try again!")
        except Exception: pass

async def update_td_message(message, game, force_kick_menu=False):
    count = len(game["players"])
    names_list = "\n".join([f"👤 {name}" for name in game["players"].values()]) if count > 0 else "No one yet."
    text = f"🎡 **TRUTH OR DARE GAME!** 🎡\n\nClick below to join! (Min 2, Max 15 players)\n\n**Joined ({count}):**\n{names_list}"
    
    if force_kick_menu:
        buttons = []
        for p_id, p_name in game["players"].items():
            buttons.append([InlineKeyboardButton(f"❌ Kick {p_name}", callback_data=f"td_k_{p_id}")])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="td_back_to_main")])
        keyboard = InlineKeyboardMarkup(buttons)
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ADD ME", callback_data="td_add"), InlineKeyboardButton("➖ REMOVE", callback_data="td_remove")],
            [InlineKeyboardButton("🛠 KICK PLAYER (Admin)", callback_data="td_kick_menu")],
            [InlineKeyboardButton("🎡 SPIN THE WHEEL", callback_data="td_spin")]
        ])
    await message.edit_text(text, reply_markup=keyboard)

# ====================================================================
# ORIGINAL BAKA-STYLE CHAT AI HANDLER (UNTOUCHED)
# ====================================================================
@app.on_message(filters.text & ~filters.regex(r"^/"))
async def handle_chat(client: Client, message: Message):
    if await is_banned(message.from_user.id): return
    
    # --- SAFEGUARD: IGNORE BOTTOM MENU TEXT ---
    if message.text in ["👑 Owner Panel", "📊 Stats", "📢 Broadcast", "📞 Contact Admin"]:
        return 

    is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    if is_group:
        await groups_col.update_one({"chat_id": message.chat.id}, {"$set": {"last_active": datetime.now()}}, upsert=True)
        if not await check_bot_is_admin(client, message.chat.id):
            return 
            
        bot_me = await client.get_me()
        text_lower = message.text.lower()
        is_reply_to_me = message.reply_to_message and message.reply_to_message.from_user.id == bot_me.id
        if "deepsikha" not in text_lower and not is_reply_to_me: return

    user = await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    SYSTEM_PROMPT = f"""
    You are Deepsikha, a normal Indian girl chatting casually on Telegram.
    
    CRITICAL RULES:
    1. EXTREMELY SHORT REPLIES: Use only 2 to 6 words maximum.
    2. BE DIRECT: Only answer what the user asked. Do NOT add extra poetic lines or explanations.
    3. LANGUAGE: Casual Hinglish chat spelling.
    4. NO POETRY: Speak like a normal teenager.
    5. EMOJIS: Use 1 simple emoji at the end of your sentence (e.g. 🙄, 😂, 😋, 🤔).
    """

    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in user.get("history", []): messages_payload.append({"role": msg["role"], "content": msg["content"]})
    messages_payload.append({"role": "user", "content": message.text})

    try:
        try: await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
        except Exception: pass
        
        chat_completion = groq_client.chat.completions.create(messages=messages_payload, model="llama-3.1-8b-instant", temperature=0.3, max_tokens=20)
        ai_reply = chat_completion.choices[0].message.content.strip().replace("*", "") 
        
        await message.reply_text(ai_reply)
        await update_user_memory(message.from_user.id, message.text, ai_reply)
    except Exception as e: print(f"Error: {e}")

if __name__ == "__main__":
    print("Deepsikha is running...")
    app.run()
