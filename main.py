import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from PIL import Image
import io
import os
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

# Logging sozlamalari
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Hugging Face API sozlamalari (Faqat bepul model!)
HF_TOKEN = os.getenv("HF_TOKEN")  # 👈 .env faylida saqlang!
API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"  # ✅ Tuzatildi!
HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"}

# Telegram bot tokeni
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# Rasm generatsiya funksiyasi (retry + timeout)
async def generate_image(prompt: str) -> bytes:
    """Hugging Face API orqali rasm yaratadi"""
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
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

# /start komandasi
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎨 Rasm yaratish", callback_data="generate")],
        [InlineKeyboardButton("💡 Yordam", callback_data="help")],
        [InlineKeyboardButton("🌐 English", callback_data="lang_en")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 *Salom! Men AI Image Studioman!* 🤖✨\n\n"
        "Sizga chiroyli rasm yaratishga yordam beraman.\n\n"
        "👇 Quyidagi tugmalardan birini bosing:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# Inline menu: uslub tanlash
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

# Uslubni tanlash → prompt qo'shish
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

    await query.edit_message_text(
        "✏️ *Endi rasm uchun matn kiriting!*\n\n"
        "Masalan:\n"
        "`kuchuk, qorli yerda, oq, kundalik hayot`\n"
        "`O'zbekiston terma jamoasi, stadionda, 4K, realistik`\n\n"
        "Yoki o'zingizning xohishingizni yozing...",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_prompt'] = True

# Matn qabul qilish
async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_prompt'):
        return

    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("❌ Iltimos, matn kiriting!")
        return

    # Agar uslub tanlangan bo'lsa, unga qo'shish
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
            caption=f"*🎨 Sizning so'rovingiz:* `{prompt}`\n\n✨ *AI Image Studio tomonidan yaratildi*",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {str(e)}\n\nIltimos, keyinroq qayta urinib ko'ring.")

    # Holatni tozalash
    context.user_data['awaiting_prompt'] = False
    context.user_data['selected_style'] = ""

# Yordam menyusi
async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "*💡 Qanday ishlash kerak?*\n\n"
        "1. 👉 *Rasm yaratish* tugmasini bosing\n"
        "2. 🎨 *Uslubni* tanlang (realistik, anime va h.k.)\n"
        "3. ✍️ *Matnni* kiriting (masalan: \"kuchuk, qorli yerda\")\n"
        "4. 🖼️ AI rasmni yaratadi!\n\n"
        "*Eslatma:* Agar rasm 10 soniyadan ortiq kutilsa — server sekin. Qayta urinib ko'ring.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="back_to_main")]])
    )

# Asosiy menyuga qaytish
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🎨 Rasm yaratish", callback_data="generate")],
        [InlineKeyboardButton("💡 Yordam", callback_data="help")],
        [InlineKeyboardButton("🌐 English", callback_data="lang_en")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👋 *Salom! Men AI Image Studioman!* 🤖✨\n\n"
        "Sizga chiroyli rasm yaratishga yordam beraman.\n\n"
        "👇 Quyidagi tugmalardan birini bosing:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# Tilni o'zgartirish (inprogress)
async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🇺🇸 English mode coming soon...\n\nMa'lumotlar saqlandi. O'zbek tiliga qaytish uchun /start ni bosing.")

# Asosiy dastur
import asyncio

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlerlar
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(generate_menu, pattern="^generate$"))
    application.add_handler(CallbackQueryHandler(help_menu, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))
    application.add_handler(CallbackQueryHandler(set_style, pattern=r"^style_"))
    application.add_handler(CallbackQueryHandler(change_language, pattern="^lang_en$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))

    print("🚀 AI Image Studio ishga tushirildi! ✨")
    application.run_polling()

if __name__ == '__main__':
    main()