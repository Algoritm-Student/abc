from telegram import Update
from telegram.ext import ContextTypes
import sqlite3
from database import get_stats

ADMIN_ID = 7440949683  # 👈 O'zingizning Telegram ID ingizni qo'ying!

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Bu buyruq faqat admin uchun!")
        return

    stats = get_stats()  # database.py dan

    message = (
        "📊 *Admin Panel* 🛠️\n\n"
        f"👥 Jami rasm generatsiyalari: `{stats['total']}`\n\n"
        "🔝 Eng ko'p so'ralgan uslublar:\n"
    )
    for style, count in stats['top_styles']:
        message += f"   • {style}: `{count}`\n"

    message += "\n🔝 Eng ko'p so'ralgan promptlar:\n"
    for prompt, count in stats['top_prompts']:
        message += f"   • `{prompt[:30]}...`: `{count}`\n"

    await update.message.reply_text(message, parse_mode='Markdown')
