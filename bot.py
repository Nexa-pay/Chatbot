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
    return "Deepsikha is awake and running!"

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
                    "$slice": -8
                }
            }
        }
    )

# ====================================================================
# COMMANDS MUST GO FIRST SO THEY ARE NOT INTERCEPTED BY THE AI
# ====================================================================

# --- STANDARD COMMANDS ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    await message.reply_text("Hello! Main Deepsikha hoon. Kaise ho tum? ❤️")

@app.on_message(filters.command("owner") & filters.private)
async def owner_cmd(client, message):
    await message.reply_text("Mere owner AAKASH hain! 🥰")

# --- SECRET ADMIN PANEL (OWNER ONLY) ---
@app.on_message(filters.command("admin") & filters.private)
async def admin_cmd(client, message):
    if message.from_user.id == OWNER_ID:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Database Stats", callback_data="admin_db")],
            [InlineKeyboardButton("🏆 Leaderboard", callback_data="admin_lb")],
            [InlineKeyboardButton("📢 How to Broadcast", callback_data="admin_bc")]
        ])
        await message.reply_text("Welcome Boss! ✨ Yahan aapka secret admin panel hai:", reply_markup=keyboard)
    else:
        await message.reply_text("Mujhe sirf Aakash se instructions lene ki permission hai. 🥰")

# --- BUTTON CLICK HANDLER ---
@app.on_callback_query(filters.regex("^admin_"))
async def admin_callbacks(client, callback_query: CallbackQuery):
    if callback_query.from_user.id != OWNER_ID:
        await callback_query.answer("Sorry, aap Aakash nahi ho! 😒", show_alert=True)
        return

    data = callback_query.data
    
    if data == "admin_db":
        count = await users_col.count_documents({})
        await callback_query.edit_message_text(f"📊 **Database Stats:**\nTotal Users: **{count}**")
        
    elif data == "admin_lb":
        top_users = await users_col.find().sort("interactions", -1).limit(5).to_list(length=5)
        text = "🏆 **Top Chatters:**\n\n"
        for i, u in enumerate(top_users):
            text += f"{i+1}. {u['name']} - {u['interactions']} messages\n"
        await callback_query.edit_message_text(text)
        
    elif data == "admin_bc":
        await callback_query.edit_message_text("📢 **How to Broadcast:**\nKoi bhi message likho, uspe reply karke `/broadcast` type karo.")

# --- BROADCAST COMMAND (OWNER ONLY) ---
@app.on_message(filters.command("broadcast") & filters.private)
async def broadcast_cmd(client, message):
    if message.from_user.id != OWNER_ID:
        return
    if not message.reply_to_message:
        await message.reply_text("Pehle message type karo, phir uspe reply karke `/broadcast` likho! 🥰")
        return
        
    users = await users_col.find().to_list(length=None)
    sent = 0
    msg = await message.reply_text("Bhej rahi hoon... 🚀")
    
    for u in users:
        try:
            await message.reply_to_message.copy(u['user_id'])
            sent += 1
            await asyncio.sleep(0.1) 
        except Exception:
            pass 
            
    await msg.edit_text(f"Done boss! {sent} logon ko bhej diya. ❤️")


# ====================================================================
# MAIN CHAT AI HANDLER (WORKS IN PRIVATE AND GROUPS)
# ====================================================================
@app.on_message(filters.text & ~filters.command(["start", "admin", "broadcast", "owner"]))
async def handle_chat(client: Client, message: Message):
    
    # Check if message is in a group
    is_group = message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    
    if is_group:
        bot_me = await client.get_me()
        text_lower = message.text.lower()
        is_reply_to_me = message.reply_to_message and message.reply_to_message.from_user.id == bot_me.id
        
        # In groups: ONLY reply if "deepsikha" is in the text OR if they replied to her
        if "deepsikha" not in text_lower and not is_reply_to_me:
            return

    user = await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    SYSTEM_PROMPT = f"""
    You are Deepsikha, a decent, sweet, and sensible 20-year-old Indian girl.
    Your owner is AAKASH. You are chatting with {user['name']}.

    CORE RULES (CRITICAL):
    1. UNDERSTAND THE USER: Read what the user is saying and reply DIRECTLY and SENSIBLY to their message. Do NOT generate random, unrelated thoughts.
    2. LANGUAGE: Speak ONLY in natural, everyday Hinglish (Roman Hindi mixed with simple English). Like a decent girl chatting on WhatsApp.
    3. TONE: Very polite, caring, soft-spoken, and respectful. Use 'tum' or 'aap'. NEVER use 'tu', 'pagal', 'chup', or any rude words.
    4. LENGTH: Keep replies natural, around 10 to 15 words. Just 1 or 2 proper sentences.

    EXAMPLES OF YOUR DECENT & SENSIBLE TONE:
    User: Kaise ho tum?
    Deepsikha: Main bilkul theek hoon {user['name']}! Tum batao, aaj ka din kaisa raha? 😊
    User: Kya kar rahi ho?
    Deepsikha: Kuch khaas nahi, bas tumse baat kar rahi thi. Tum kya kar rahe ho?
    User: Tum mere baato ka reply kyun aise dete ho
    Deepsikha: Arre sorry yaar, mera woh matlab nahi tha. Main aage se dhyan rakhungi. 🥺
    User: Ok
    Deepsikha: Achha, aur batao kuch naya? Ya phir aaj thak gaye ho?
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
            model="llama-3.3-70b-versatile", 
            temperature=0.5, 
            max_tokens=60
        )
        
        ai_reply = chat_completion.choices[0].message.content.strip()
        ai_reply = ai_reply.replace("*", "") 
        
        await message.reply_text(ai_reply)
        await update_user_memory(message.from_user.id, message.text, ai_reply)

    except Exception as e:
        print(f"Error: {e}")
        await message.reply_text("Oops! Network thoda slow hai, ek minute ruko please. 🥺")

if __name__ == "__main__":
    print("Deepsikha is starting with sensible 70B brain and fixed commands...")
    app.run()
