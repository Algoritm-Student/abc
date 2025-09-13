import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from PIL import Image
import io
import os
from dotenv import load_dotenv
from database import init_db, save_image, get_last_style, get_stats
from admin import admin_panel

load_dotenv()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

HF_TOKEN = os.getenv("HF_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"}

async def generate_image(prompt: str) -> bytes:
    payload = {"inputs": prompt}
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=60)
            response.raise_for_status()
            return response.content
        except Exception as e:
            if attempt == max_retries - 1:
                raise Exception(f"❌ Rasm yaratishda xato: {str(e)}")
            await asyncio.sleep(2 ** attempt)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎨 Rasm yaratish", callback_data="generate")],
        [InlineKeyboardButton("📊 Statistika", callback_data="stats")],
        [InlineKeyboardButton("👨‍💻 Admin Panel", callback_data="admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 *Salom! Men AI Image Studio Pro!* 🤖✨\n\n"
        "Sizga chiroyli rasm yaratishga yordam beraman.\n\n"
        "👇 Quyidagi tugmalardan birini bosing:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def generate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🖼️ Realistik", callback_data="style_realistic")],
        [InlineKeyboardButton("🎨 Anime", callback_data="style_anime")],
        [InlineKeyboardButton(" Pixar", callback_data="style_pixar")],
        [InlineKeyboardButton("🌌 Sci-Fi", callback_data="style_scifi")],
        [InlineKeyboardButton("🌅 Fantastik", callback_data="style_fantasy")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🖼️ *Qanday uslubda rasm yarataylik?*\n\n"
        "🔹 *Realistik* — haqiqiy tasvirlar\n"
        "🔹 *Anime* — yapon animeleriga o'xshash\n"
        "🔹 *Pixar* — animatsion film uslubi\n"
        "🔹 *Sci-Fi* — kosmos va texnologiya\n"
        "🔹 *Fantastik* — jinnlar, qulflar, ajoyib dunyo",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def set_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    style_map = {
        "style_realistic": "realistic, 4K, ultra-detailed, cinematic lighting, photorealistic",
        "style_anime": "anime style, vibrant colors, detailed eyes, studio ghibli, cel shading",
        "style_pixar": "Pixar animation style, soft lighting, cartoon character, family friendly",
        "style_scifi": "science fiction, futuristic city, neon lights, cyberpunk, holograms, 8K",
        "style_fantasy": "fantasy art, magical forest, glowing runes, dragons, ethereal glow, epic fantasy"
    }

    selected_style = query.data
    context.user_data['selected_style'] = style_map.get(selected_style, "")

    last_style, last_prompt = get_last_style(update.effective_user.id)
    if last_style and last_prompt:
        button_text = f"🔁 {last_style} uslubida '{last_prompt[:20]}...' qayta yaratish"
        keyboard = [
            [InlineKeyboardButton(button_text, callback_data="repeat_last")],
            [InlineKeyboardButton("✏️ Yangi prompt kiriting", callback_data="enter_new_prompt")]
        ]
    else:
        keyboard = [[InlineKeyboardButton("✏️ Yangi prompt kiriting", callback_data="enter_new_prompt")]]

    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "✏️ *Endi rasm uchun matn kiriting!*",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def enter_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "✍️ *Iltimos, rasm uchun matn kiriting:* \n\nMisol:\n`kuchuk, qorli yerda, Pixar uslubida`\n\nYoki o'zingizning xohishingizni yozing..."
    )
    context.user_data['awaiting_prompt'] = True  # 👈 BU QATORDAN O'CHIRIB TASHLAMANG!

async def repeat_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    last_style, last_prompt = get_last_style(update.effective_user.id)
    if not last_prompt:
        await query.edit_message_text("❌ Hech qanday oldingi rasm topilmadi.")
        return

    style = context.user_data.get('selected_style', "")
    if style:
        prompt = f"{last_prompt}, {style}"
    else:
        prompt = last_prompt

    await query.edit_message_text("⏳ *Rasm yaratilmoqda...* 🎨✨", parse_mode='Markdown')

    try:
        image_data = await generate_image(prompt)
        image = Image.open(io.BytesIO(image_data))

        bio = io.BytesIO()
        image.save(bio, 'PNG')
        bio.seek(0)

        await query.message.reply_photo(
            photo=bio,
            caption=f"*🎨 Sizning so'rovingiz:* `{prompt}`\n\n✨ *AI Image Studio Pro tomonidan yaratildi*",
            parse_mode='Markdown'
        )

        save_image(update.effective_user.id, update.effective_user.username, prompt, style)
    except Exception as e:
        await query.edit_message_text(f"❌ Xatolik: {str(e)}")

async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_prompt'):
        return

    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("❌ Iltimos, matn kiriting!")
        return

    style = context.user_data.get('selected_style', "")
    if style:
        prompt = f"{prompt}, {style}"

    await update.message.reply_text("⏳ *Rasm yaratilmoqda...* 🎨✨", parse_mode='Markdown')

    try:
        image_data = await generate_image(prompt)
        image = Image.open(io.BytesIO(image_data))

        bio = io.BytesIO()
        image.save(bio, 'PNG')
        bio.seek(0)

        await update.message.reply_photo(
            photo=bio,
            caption=f"*🎨 Sizning so'rovingiz:* `{prompt}`\n\n✨ *AI Image Studio Pro tomonidan yaratildi*",
            parse_mode='Markdown'
        )

        save_image(update.effective_user.id, update.effective_user.username, prompt, style)
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {str(e)}")

    context.user_data['awaiting_prompt'] = False
    context.user_data['selected_style'] = ""

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    stats = get_stats()
    message = (
        "📊 *Umumiy statistika*\n\n"
        f"👥 Jami rasm generatsiyalari: `{stats['total']}`\n\n"
        "🔝 Eng ko'p so'ralgan uslublar:\n"
    )
    for style, count in stats['top_styles']:
        message += f"   • {style}: `{count}`\n"

    message += "\n🔝 Eng ko'p so'ralgan promptlar:\n"
    for prompt, count in stats['top_prompts']:
        message += f"   • `{prompt[:25]}...`: `{count}`\n"

    await query.edit_message_text(message, parse_mode='Markdown')

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🎨 Rasm yaratish", callback_data="generate")],
        [InlineKeyboardButton("📊 Statistika", callback_data="stats")],
        [InlineKeyboardButton("👨‍💻 Admin Panel", callback_data="admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👋 *Salom! Men AI Image Studio Pro!* 🤖✨\n\n"
        "Sizga chiroyli rasm yaratishga yordam beraman.\n\n"
        "👇 Quyidagi tugmalardan birini bosing:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

import asyncio

def main():
    init_db()  # Bazani yaratish

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # CallbackQueryHandler lar — AVVAL!
    application.add_handler(CallbackQueryHandler(generate_menu, pattern="^generate$"))
    application.add_handler(CallbackQueryHandler(set_style, pattern=r"^style_"))
    application.add_handler(CallbackQueryHandler(repeat_last, pattern="^repeat_last$"))
    application.add_handler(CallbackQueryHandler(enter_prompt, pattern="^enter_new_prompt$"))  # 👈 Tuzatildi!
    application.add_handler(CallbackQueryHandler(stats, pattern="^stats$"))
    application.add_handler(CallbackQueryHandler(admin, pattern="^admin$"))
    application.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))

    # MessageHandler — SO'NG!
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))

    print("🚀 AI Image Studio Pro ishga tushirildi! ✨")
    application.run_polling()

if __name__ == '__main__':
    main()
