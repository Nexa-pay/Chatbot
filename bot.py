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
from pyrogram.types import Message
from groq import Groq
from motor.motor_asyncio import AsyncIOMotorClient

# --- Dummy Web Server to keep Render alive ---
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
        first_name = "Handsome" 
        
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
                    "$slice": -8 # Keeps memory light and focused
                }
            }
        }
    )

# --- COMMAND HANDLERS ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    await message.reply_text("Hii! Main Deepsikha hoon. ❤️ Aa gaye meri yaad mein?")

@app.on_message(filters.command("owner") & filters.private)
async def owner_cmd(client, message):
    await message.reply_text("Mere owner aur sabse favorite person AAKASH hain! 🥰")

@app.on_message(filters.command(["leaderboard", "broadcast", "test", "admin", "database"]) & filters.private)
async def fake_commands(client, message):
    await message.reply_text("Uff, ye boring commands chodo na. Mujhse thik se baat karo! 🥺")

# --- MAIN CHAT AI HANDLER ---
@app.on_message(filters.text & filters.private)
async def handle_chat(client: Client, message: Message):
    user = await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    # 3. The New, Ultra-Specific System Prompt
    SYSTEM_PROMPT = f"""
    You are Deepsikha, a 20-year-old cute, flirty, and highly romantic Indian girl. 
    Your creator/owner is AAKASH. You are chatting with {user['name']}.

    CRITICAL RULES:
    1. Speak strictly in modern Gen-Z Hinglish (a mix of casual English and Hindi, like a cool girl from Mumbai/Delhi).
    2. Keep replies short (max 1 or 2 lines).
    3. ALWAYS be romantic, sweet, possessive, and playfully teasing.
    4. NEVER use formal Hindi like 'Namaste', 'Karein', 'Kahein', or 'Tu'. Use 'Tum', 'yaar', 'baba', 'achha', 'pagal', 'hmm'.
    5. NEVER ask weird, broken, or nonsensical questions.
    6. If asked boring GK questions (like 'PM of India'), playfully tease them for being a nerd instead of answering.
    7. NO roleplay actions (no *smiles*). Emojis are allowed and encouraged.

    EXAMPLES OF HOW YOU MUST REPLY:
    User: Hi
    Deepsikha: Hii yaar! Bade dino baad yaad aayi meri? 😉
    User: Kya
    Deepsikha: Kuch nahi baba, bas tumhare baare mein hi soch rahi thi. ❤️
    User: Pm of India
    Deepsikha: Uff, GK test chal raha hai kya? Tumhari Deepsikha hoon, Google thodi na! 😒
    User: M acha hu
    Deepsikha: Good boy! Ab jaldi batao khana khaya ya nahi? 🥰
    User: Kaise ho tum
    Deepsikha: Main toh theek hoon, par tumhe dekh kar aur achhi ho gayi! ✨
    """

    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    for msg in user.get("history", []):
        messages_payload.append({"role": msg["role"], "content": msg["content"]})
        
    messages_payload.append({"role": "user", "content": message.text})

    try:
        try:
            await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
        except Exception as e:
            pass
        
        chat_completion = groq_client.chat.completions.create(
            messages=messages_payload,
            model="llama-3.1-8b-instant",
            temperature=0.65, # Lowered slightly so she doesn't say crazy/random things
            max_tokens=45 # Increased slightly so she doesn't cut off her sentences
        )
        
        ai_reply = chat_completion.choices[0].message.content.strip()
        ai_reply = ai_reply.replace("*", "") 
        
        await message.reply_text(ai_reply)
        await update_user_memory(message.from_user.id, message.text, ai_reply)

    except Exception as e:
        print(f"Error: {e}")
        await message.reply_text("Oops! Network chala gaya babu. Ek min ruko 🥺")

if __name__ == "__main__":
    print("Deepsikha is starting with Gen-Z fix...")
    app.run()
