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
    return "Deepsikha is running!"

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

# Initialize Database
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["deepsikha_db"]
users_col = db["users"]

# --- HELPER: GET OR CREATE USER MEMORY ---
async def get_user_profile(user_id, first_name):
    if not first_name:
        first_name = "Dost" 
        
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "name": first_name,
            "interactions": 0,
            "history": [], 
            "joined_at": datetime.now()
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
                    "$each": [
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": ai_reply}
                    ],
                    "$slice": -6 # Keeping memory very short for casual chat
                }
            }
        }
    )

# ====================================================================
# COMMANDS MUST GO FIRST
# ====================================================================

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    await message.reply_text("Hey! kia kr rhe ho? 😋")

@app.on_message(filters.command("owner") & filters.private)
async def owner_cmd(client, message):
    await message.reply_text("Mera owner AAKASH hai. 🥰")

# --- GRID-STYLE ADMIN PANEL (OWNER ONLY) ---
@app.on_message(filters.command("admin") & filters.private)
async def admin_cmd(client, message):
    if message.from_user.id == OWNER_ID:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Stats", callback_data="admin_db"),
                InlineKeyboardButton("🏆 Leaderboard", callback_data="admin_lb")
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_bc"),
                InlineKeyboardButton("👑 Owner Panel", callback_data="admin_close")
            ]
        ])
        await message.reply_text("Welcome Boss! ✨ Yahan aapka panel hai:", reply_markup=keyboard)
    else:
        pass # Ignore non-owners completely

@app.on_callback_query(filters.regex("^admin_"))
async def admin_callbacks(client, callback_query: CallbackQuery):
    if callback_query.from_user.id != OWNER_ID:
        await callback_query.answer("Not allowed!", show_alert=True)
        return

    data = callback_query.data
    
    if data == "admin_db":
        count = await users_col.count_documents({})
        await callback_query.edit_message_text(f"📊 **Database Stats:**\nTotal Users: **{count}**")
        
    elif data == "admin_lb":
        top_users = await users_col.find().sort("interactions", -1).limit(5).to_list(length=5)
        text = "🏆 **Top Chatters:**\n\n"
        for i, u in enumerate(top_users):
            text += f"{i+1}. {u['name']} - {u['interactions']} msgs\n"
        await callback_query.edit_message_text(text)
        
    elif data == "admin_bc":
        await callback_query.edit_message_text("📢 **To Broadcast:**\nReply to any message with `/broadcast`.")
        
    elif data == "admin_close":
        await callback_query.edit_message_text("Panel closed.")

@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client, message):
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message:
        await message.reply_text("Reply to a message first!")
        return
        
    users = await users_col.find().to_list(length=None)
    sent = 0
    msg = await message.reply_text("Sending... 🚀")
    
    for u in users:
        try:
            await message.reply_to_message.copy(u['user_id'])
            sent += 1
            await asyncio.sleep(0.1) 
        except Exception:
            pass 
            
    await msg.edit_text(f"Done! Sent to {sent} users.")


# ====================================================================
# BAKA-STYLE CHAT AI HANDLER
# ====================================================================
@app.on_message(filters.text & ~filters.command(["start", "admin", "broadcast", "owner"]))
async def handle_chat(client: Client, message: Message):
    
    is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    
    if is_group:
        bot_me = await client.get_me()
        text_lower = message.text.lower()
        is_reply_to_me = message.reply_to_message and message.reply_to_message.from_user.id == bot_me.id
        
        if "deepsikha" not in text_lower and not is_reply_to_me:
            return

    user = await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    # THE NEW, ULTRA-DIRECT BAKA-STYLE PROMPT
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
        
        # Using the fast 8b model again, but with a strict prompt and low temperature
        chat_completion = groq_client.chat.completions.create(
            messages=messages_payload,
            model="llama-3.1-8b-instant", 
            temperature=0.3, # Very low temperature to stop her from writing poetry
            max_tokens=20 # Hard limit so she physically cannot write long sentences
        )
        
        ai_reply = chat_completion.choices[0].message.content.strip()
        ai_reply = ai_reply.replace("*", "") 
        
        await message.reply_text(ai_reply)
        await update_user_memory(message.from_user.id, message.text, ai_reply)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Deepsikha is running in Baka mode...")
    app.run()
