import os
import asyncio
import threading
from flask import Flask

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

# --- Dummy Web Server to keep Render alive ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running!"

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

# Initialize Clients
app = Client("flirty_hinglish_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
groq_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """
You are a friendly, girly, and slightly flirty AI assistant. 
You must always reply in conversational Hinglish. 
Keep every single response extremely short—strictly 1 line, maximum 8 to 10 words. 
Respond naturally and playfully to the user's input.
"""

@app.on_message(filters.text & filters.private)
async def handle_message(client: Client, message: Message):
    # Showing "typing..." status
    try:
        await client.send_chat_action(message.chat.id, "typing")
    except:
        pass
    
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message.text}
            ],
            model="llama3-8b-8192",
            temperature=0.7,
            max_tokens=30
        )
        
        ai_reply = chat_completion.choices[0].message.content
        await message.reply_text(ai_reply)

    except Exception as e:
        print(f"Error: {e}")
        await message.reply_text("Oops! Network thoda busy hai. 🥺")

if __name__ == "__main__":
    print("Bot starting with Python 3.14 fix...")
    app.run()
