# main.py
"""
Telegram bot with:
- prompt translation (auto -> en)
- Digen API call (text_to_image)
- rate limit, ban/unban, admin panel
- create 5s video from generated image (moviepy)
- persistence via sqlite3
"""

import os
import logging
import asyncio
import time
import sqlite3
import tempfile
import requests
import aiohttp
from io import BytesIO

from deep_translator import GoogleTranslator
from moviepy.editor import ImageClip

from telegram import (
    Update,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# -------------------------
# CONFIG / Logging
# -------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Env vars (or set them in DB via admin panel)
BOT_TOKEN = os.getenv("BOT_TOKEN")  # set this before running
DEFAULT_ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # or set ADMIN_ID env

# Digen defaults (placeholders) -> prefer storing in DB settings
# DO NOT hardcode real secrets here
DEFAULT_DIGEN_TOKEN = os.getenv("DIGEN_TOKEN", "")
DEFAULT_DIGEN_SESSION = os.getenv("DIGEN_SESSION", "")
DIGEN_URL = "https://api.digen.ai/v2/tools/text_to_image"

# -------------------------
# SQLITE persistence
# -------------------------
DB_PATH = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # users: id, username, last_gen_ts
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            last_gen_ts REAL DEFAULT 0
        )
    """)
    # logs: id autoinc, user_id, username, prompt, images (json string), ts
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            prompt TEXT,
            images TEXT,
            ts REAL
        )
    """)
    # bans: user_id
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY
        )
    """)
    # settings: key, value
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

def db_get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row[0]
    return default

def db_set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def add_user(user_id, username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?, ?)", (user_id, username))
    cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
    conn.commit()
    conn.close()

def set_last_gen(user_id, ts):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_gen_ts = ? WHERE user_id = ?", (ts, user_id))
    conn.commit()
    conn.close()

def get_last_gen(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT last_gen_ts FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0

def log_entry(user_id, username, prompt, images):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO logs(user_id, username, prompt, images, ts) VALUES(?, ?, ?, ?, ?)",
                (user_id, username, prompt, ",".join(images), time.time()))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bans WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row)

def ban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO bans(user_id) VALUES(?)", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM logs")
    total_images = cur.fetchone()[0]
    conn.close()
    return {"users": total_users, "requests": total_images}

# init db on import
init_db()

# default rate limit seconds
DEFAULT_RATE_LIMIT = int(db_get_setting("rate_limit", "30"))

# Admin management
ADMIN_ID = int(db_get_setting("admin_id", str(DEFAULT_ADMIN_ID))) if DEFAULT_ADMIN_ID else DEFAULT_ADMIN_ID

# -------------------------
# Utilities
# -------------------------
def escape_markdown_v2(text: str) -> str:
    """
    Escape for MarkdownV2.
    """
    import re
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def translate_to_en(text: str) -> str:
    try:
        return GoogleTranslator(source='auto', target='en').translate(text)
    except Exception as e:
        logger.warning("Translate failed: %s", e)
        return text

async def async_download(session, url):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.read()
                return data
    except Exception as e:
        logger.error("Download error %s -> %s", url, e)
    return None

def get_digen_headers():
    # prefer DB-stored values
    token = db_get_setting("digen_token", DEFAULT_DIGEN_TOKEN) or ""
    sessionid = db_get_setting("digen_session", DEFAULT_DIGEN_SESSION) or ""
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "digen-language": "uz-US",
        "digen-platform": "web",
        "digen-token": token,
        "digen-sessionid": sessionid,
        "origin": "https://rm.digen.ai",
        "referer": "https://rm.digen.ai/",
    }
    return headers

# -------------------------
# Digen API call (sync inside to_thread)
# -------------------------
def digen_request(prompt: str, width=512, height=512, batch_size=4):
    headers = get_digen_headers()
    payload = {
        "prompt": prompt,
        "image_size": f"{width}x{height}",
        "width": width,
        "height": height,
        "lora_id": "",
        "batch_size": batch_size,
        "reference_images": [],
        "strength": ""
    }
    try:
        resp = requests.post(DIGEN_URL, headers=headers, json=payload, timeout=60)
        logger.info("Digen status %s", resp.status_code)
        return resp.status_code, resp.text, resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.exception("Digen request failed: %s", e)
        return None, str(e), None

# -------------------------
# Create 5s video from image bytes
# -------------------------
def image_bytes_to_video(image_bytes: bytes, out_path: str, duration: int =5):
    # moviepy expects a filename or numpy array; we save to temp file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_img:
        tmp_img.write(image_bytes)
        tmp_img.flush()
        tmp_img_name = tmp_img.name

    clip = ImageClip(tmp_img_name, duration=duration)
    # write video file
    clip.write_videofile(out_path, fps=24, verbose=False, logger=None)
    clip.close()

# -------------------------
# Handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username or "N/A")
    text = (
        "👋 *Salom!* Men Digen AI botiman.\n\n"
        "✍️ Istalgan prompt yuboring — men 4 ta rasm yarataman va birinchisidan 5s video yasab beraman.\n"
        "Agar prompt o'zbekcha bo'lsa — men uni avtomatik ingliz tiliga tarjima qilaman.\n\n"
        "Misol: `Futuristic cyberpunk city with neon lights`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# Admin panel show
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ Siz admin emassiz.")
    keyboard = [
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("📨 Broadcast (forward)", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⏳ Limit sozlash", callback_data="admin_limit")],
        [InlineKeyboardButton("🚫 Ban/Unban", callback_data="admin_ban")],
        [InlineKeyboardButton("🔑 Token/Session", callback_data="admin_token")],
    ]
    await update.message.reply_text("⚙️ Admin panel", reply_markup=InlineKeyboardMarkup(keyboard))

# Callback handler for admin buttons and regen
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # REGEN flow: regen|<prompt>
    if data.startswith("regen|"):
        _, old_prompt = data.split("|", 1)
        await query.edit_message_text(f"♻️ Qayta generatsiya qilinmoqda...\n`{escape_markdown_v2(old_prompt)}`", parse_mode="MarkdownV2")
        # create a fake update-like object: easiest is to call generate with same chat context
        fake_message = query.message
        class FakeMsg: pass
        fake = FakeMsg()
        fake.text = old_prompt
        fake.chat_id = fake_message.chat_id
        fake.from_user = query.from_user
        fake.message = fake_message
        # Instead of fabricating, call generate handler using actual Update: use update._replace ?
        # Simpler: set context.user_data and call generate() with original update
        # We'll directly call generate using the original update but override text in message object:
        query.message.text = old_prompt
        await generate(update, context)
        return

    # Admin callbacks
    if data == "admin_stats":
        stats = get_stats()
        await query.edit_message_text(f"📊 Statistika:\n- Foydalanuvchilar: {stats['users']}\n- So‘rovlar (logs): {stats['requests']}")
        return

    if data == "admin_broadcast":
        # set admin state to expect next message as broadcast content
        context.user_data['admin_action'] = 'broadcast'
        await query.edit_message_text("✉️ Iltimos, yubormoqchi bo‘lgan xabaringizni hozirgi chatga yuboring (bot xabarni barcha foydalanuvchilarga *forward* qiladi).")
        return

    if data == "admin_limit":
        context.user_data['admin_action'] = 'set_limit'
        await query.edit_message_text("⏳ Yangi limitni soniya ko‘rinishida yuboring (masalan: 30).")
        return

    if data == "admin_ban":
        context.user_data['admin_action'] = 'ban_flow'
        await query.edit_message_text("🚫 Ban/Unban:\nFoydalanuvchi ID sini yuboring (raqam).")
        return

    if data == "admin_token":
        context.user_data['admin_action'] = 'set_token'
        await query.edit_message_text("🔑 Digen tokenini yoki sessionni yuboring (format: token|session).")
        return

# Admin message processor
async def admin_message_processor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        return
    action = context.user_data.get('admin_action')
    if not action:
        return

    text = update.message.text.strip()
    if action == 'broadcast':
        # fetch all user ids and forward the admin's message
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        rows = cur.fetchall()
        conn.close()
        count = 0
        for (uid,) in rows:
            try:
                await context.bot.forward_message(chat_id=uid, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
                count += 1
            except Exception as e:
                logger.warning("Broadcast to %s failed: %s", uid, e)
        context.user_data.pop('admin_action', None)
        await update.message.reply_text(f"✅ Forward tugadi. Jo‘natildi: {count}")
        return

    if action == 'set_limit':
        try:
            val = int(text)
            db_set_setting("rate_limit", str(val))
            context.user_data.pop('admin_action', None)
            await update.message.reply_text(f"✅ Yangi rate limit saqlandi: {val} soniya.")
        except:
            await update.message.reply_text("❌ Iltimos, butun son kiriting.")
        return

    if action == 'ban_flow':
        try:
            uid = int(text)
            if is_banned(uid):
                unban_user(uid)
                await update.message.reply_text(f"✅ User {uid} unban qilindi.")
            else:
                ban_user(uid)
                await update.message.reply_text(f"✅ User {uid} ban qilindi.")
            context.user_data.pop('admin_action', None)
        except:
            await update.message.reply_text("❌ Noto'g'ri ID format. Faqat raqam.")
        return

    if action == 'set_token':
        # expecting "token|session" or just token
        if '|' in text:
            token, sessionid = text.split("|", 1)
            db_set_setting("digen_token", token.strip())
            db_set_setting("digen_session", sessionid.strip())
            await update.message.reply_text("✅ Token va session saqlandi.")
        else:
            db_set_setting("digen_token", text.strip())
            await update.message.reply_text("✅ Token saqlandi.")
        context.user_data.pop('admin_action', None)
        return

# MAIN generate handler
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check message presence
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    add_user(user.id, user.username or "N/A")

    # Ban check
    if is_banned(user.id):
        return await update.message.reply_text("🚫 Siz block qilingansiz.")

    # Rate limit
    rate_limit = int(db_get_setting("rate_limit", str(DEFAULT_RATE_LIMIT)))
    last_ts = get_last_gen(user.id) or 0
    now = time.time()
    if now - last_ts < rate_limit:
        wait = int(rate_limit - (now - last_ts))
        return await update.message.reply_text(f"⏳ Iltimos yangi rasm generatsiya qilish uchun {wait} soniya kuting!")

    orig_prompt = update.message.text.strip()
    await update.message.reply_text("🔁 Prompt qabul qilindi. Tarjima qilinmoqda va rasm yaratilmoqda...")

    # Translate to English
    prompt_en = await asyncio.to_thread(translate_to_en, orig_prompt)

    # Call Digen API in thread
    status, text_resp, json_resp = await asyncio.to_thread(digen_request, prompt_en, 512, 512, 4)

    if status != 200 or not json_resp:
        await update.message.reply_text(f"❌ API xatolik: {status}\n{text_resp}")
        return

    # Try get image id. This depends on API shape; adapt if needed.
    image_id = json_resp.get("data", {}).get("id") or json_resp.get("data", {}).get("task_id") or None
    if not image_id:
        # maybe API returned urls directly
        images = json_resp.get("data", {}).get("images") or []
        if images:
            image_urls = images[:4]
        else:
            await update.message.reply_text("❌ Rasm ID yoki URL topilmadi API javobida.")
            return
    else:
        # As in original: build urls by pattern
        image_urls = [f"https://liveme-image.s3.amazonaws.com/{image_id}-{i}.jpeg" for i in range(4)]

    # Download images async
    downloaded = []
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(async_download(session, url)) for url in image_urls]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                downloaded.append(r)

    if not downloaded:
        await update.message.reply_text("❌ Rasm yuklashda xatolik bo'ldi.")
        return

    # save logs
    log_entry(user.id, user.username or "N/A", orig_prompt, image_urls)

    # send media group (photos)
    try:
        media = [InputMediaPhoto(media=url) for url in image_urls]
        await update.message.reply_media_group(media)
    except Exception as e:
        # fallback: send individually (or send downloaded bytes)
        for idx, b in enumerate(downloaded):
            try:
                await update.message.reply_photo(photo=BytesIO(b), caption=f"Image {idx+1}")
            except:
                pass

    # send prompt info and regen button
    safe_prompt = escape_markdown_v2(orig_prompt)
    keyboard = [
        [InlineKeyboardButton("♻️ Qayta generatsiya", callback_data=f"regen|{orig_prompt}")],
    ]
    await update.message.reply_text(f"🖌 Prompt: `{safe_prompt}`", parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))

    # Create 5s video from first downloaded image
    try:
        first_bytes = downloaded[0]
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
            out_path = tmp_vid.name
        # moviepy blocking -> run in thread
        await asyncio.to_thread(image_bytes_to_video, first_bytes, out_path, 5)
        # send video
        with open(out_path, "rb") as f:
            await update.message.reply_video(video=f, caption="▶️ 5s video (first image)")
    except Exception as e:
        logger.exception("Video creation failed: %s", e)
        await update.message.reply_text("⚠️ Video yaratishda muammo bo'ldi (ffmpeg kerak bo'lishi mumkin).")

    # update last gen time
    set_last_gen(user.id, time.time())

    # notify admin
    admin_id = int(db_get_setting("admin_id", str(ADMIN_ID))) if ADMIN_ID else ADMIN_ID
    if admin_id:
        try:
            await context.bot.send_message(chat_id=admin_id, text=f"👤 @{user.username or 'N/A'} (ID: {user.id})\n🖌 {orig_prompt}")
            # forward first image to admin if possible
            # we will forward original message (if available)
            try:
                await context.bot.forward_message(chat_id=admin_id, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            except:
                # fallback: send first image bytes
                if downloaded:
                    await context.bot.send_photo(chat_id=admin_id, photo=BytesIO(downloaded[0]))
        except Exception as e:
            logger.warning("Admin notify failed: %s", e)

# Generic message handler to catch admin flows and normal generate
async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # first check if admin is in action state
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        if context.user_data.get('admin_action'):
            return await admin_message_processor(update, context)
    # otherwise treat as prompt
    return await generate(update, context)

# -------------------------
# Startup
# -------------------------
def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set in env. Export BOT_TOKEN and restart.")
        return
    # ensure admin id in settings
    if DEFAULT_ADMIN_ID:
        db_set_setting("admin_id", str(DEFAULT_ADMIN_ID))
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    # message handler for admin flows and general prompts
