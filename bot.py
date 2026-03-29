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

from pyrogram import Client, filters
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
MONGO_URI = os.getenv("MONGO_URI") # NEW: Database URL

# Initialize Clients
app = Client("deepsikha_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

# Initialize Database
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["deepsikha_db"]
users_col = db["users"]

# --- HELPER: GET OR CREATE USER MEMORY ---
async def get_user_profile(user_id, first_name):
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "name": first_name,
            "interactions": 0,
            "history": [], # Stores last few messages for memory
            "joined_at": datetime.now()
        }
        await users_col.insert_one(user)
    return user

async def update_user_memory(user_id, user_msg, ai_reply):
    # Keep only the last 10 interactions so memory stays fresh and fast
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
                    "$slice": -10 # Keeps only last 10 messages
                }
            }
        }
    )

# --- COMMAND HANDLERS ---
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    await get_user_profile(message.from_user.id, message.from_user.first_name)
    await message.reply_text("Aa gaye tum? Main Deepsikha hoon. Bolo kya kaam hai? 😏")

@app.on_message(filters.command("owner") & filters.private)
async def owner_cmd(client, message):
    await message.reply_text("Mere owner AAKASH hain. Aur koi nahi. 🤫")

@app.on_message(filters.command(["leaderboard", "broadcast", "test", "admin", "database"]) & filters.private)
async def fake_commands(client, message):
    # Flirty dismissal of boring commands
    await message.reply_text("Boring commands mat use karo. Mujhse baat karo na. 😒")

# --- MAIN CHAT AI HANDLER ---
# Triggers on private messages OR if "deepsikha", "hi", "hello" is in the message
@app.on_message(filters.text & filters.private)
async def handle_chat(client: Client, message: Message):
    # 1. Fetch User Memory from MongoDB
    user = await get_user_profile(message.from_user.id, message.from_user.first_name)
    
    # 2. Determine Relationship (Mood) based on interaction count
    interactions = user.get("interactions", 0)
    if interactions < 10:
        mood = "Stranger. You are slightly ignorant but playful."
    elif interactions < 50:
        mood = "Friend. You show interest and flirt a little."
    else:
        mood = "Close. You are possessive, highly flirty, and remember them well."

    # 3. Build the strict System Prompt
    SYSTEM_PROMPT = f"""
    You are a real girl chatting on Telegram. Your name is Deepsikha. Your creator/owner is AAKASH.
    The person you are talking to is named {user['name']}.

    Personality:
    - calm, confident, slightly flirty, teasing.
    - create interest, NEVER give direct answers (e.g., if asked who is PM, say something flirty instead).

    Mood towards this user: {mood}

    STRICT RULES:
    - You are female (never change gender).
    - 1 short reply only (max 8 to 10 words).
    - Hinglish only.
    - NO roleplay actions (no *smiles*, *blushes*, *smirks*, etc).
    - NO asterisk actions (*).
    - No long sentences. No paragraphs. No explanations.
    - Sound natural like a real chat.
    """

    # 4. Construct message history for context (so she remembers recent secrets)
    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add previous chat history so she remembers what was just said
    for msg in user.get("history", []):
        messages_payload.append({"role": msg["role"], "content": msg["content"]})
        
    # Add current message
    messages_payload.append({"role": "user", "content": message.text})

    try:
        await client.send_chat_action(message.chat.id, "typing")
        
        # 5. Call Groq AI
        chat_completion = groq_client.chat.completions.create(
            messages=messages_payload,
            model="llama-3.1-8b-instant",
            temperature=0.8,
            max_tokens=30
        )
        
        ai_reply = chat_completion.choices[0].message.content.strip()
        
        # Clean up any accidental asterisks just in case the AI disobeys
        ai_reply = ai_reply.replace("*", "")
        
        await message.reply_text(ai_reply)

        # 6. Save this interaction to MongoDB so she remembers it next time
        await update_user_memory(message.from_user.id, message.text, ai_reply)

    except Exception as e:
        print(f"Error: {e}")
        await message.reply_text("Server down hai AAKASH se kaho theek kare! 😤")

if __name__ == "__main__":
    print("Deepsikha is starting with MongoDB memory...")
    app.run()
