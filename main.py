import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# -------------------- CONFIG --------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PAY_LINK = os.getenv("PAY_LINK", "https://t.me/send?start=IVNYB5t7LJhJ").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in .env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
log = logging.getLogger("media-paywall-bot")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# -------------------- IN-MEMORY STATE (NO DB) --------------------
# Approved users (premium enabled) - resets when bot restarts
PREMIUM_USERS: set[int] = set()
BANNED_USERS: set[int] = set()

# Packages (editable in code; you can rename anytime)
# You said you will change the names yourself — just edit here.
PACKAGES = [
    {"id": 1, "title": "Unlimited Access", "price": "90 USDT", "pay_link": PAY_LINK},
    # add more if you want:
    # {"id": 2, "title": "VIP Package", "price": "99000 UZS", "pay_link": PAY_LINK},
]

DEMO_TEXT = """🎬 Demo Videos

🎬 Demo Video 1 (https://t.me/demo5video/2)
🎬 Demo Video 2 (https://t.me/demo5video/3)
🎬 Demo Video 3 (https://t.me/demo5video/4)
🎬 Demo Video 4 (https://t.me/demo5video/5)
🎬 Demo Video 5 (https://t.me/demo5video/6)

👆 Click any link above to watch demo videos

💰 Want unlimited access to all videos?
Purchase a package now!
"""

# -------------------- UI --------------------
def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Demo Videos"), KeyboardButton(text="💰 Packages")],
            [KeyboardButton(text="🔒 Get Videos (Premium)")],
        ],
        resize_keyboard=True
    )

def packages_kb() -> InlineKeyboardMarkup:
    rows = []
    for p in PACKAGES:
        rows.append([InlineKeyboardButton(
            text=f"{p['title']} — {p['price']}",
            callback_data=f"pack:{p['id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def paywall_kb(package_id: int) -> InlineKeyboardMarkup:
    pack = next((p for p in PACKAGES if p["id"] == package_id), PACKAGES[0])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pay Now", url=pack["pay_link"])],
        [InlineKeyboardButton(text="✅ I Paid", callback_data=f"paid:{package_id}")],
        [InlineKeyboardButton(text="🎬 Demo Videos", callback_data="demo")],
        [InlineKeyboardButton(text="⬅️ Menu", callback_data="menu")],
    ])

def premium_videos_kb() -> InlineKeyboardMarkup:
    # Replace these with your real premium video links or delivery logic
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Premium Video 1", url="https://t.me/demo5video/2")],
        [InlineKeyboardButton(text="🎬 Premium Video 2", url="https://t.me/demo5video/3")],
        [InlineKeyboardButton(text="⬅️ Menu", callback_data="menu")],
    ])

# -------------------- HELPERS --------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def guard(message: Message) -> bool:
    if not message.from_user:
        return False
    uid = message.from_user.id
    if uid in BANNED_USERS:
        await message.answer("🚫 You are banned from using this bot.")
        return False
    return True

async def show_paywall(call: CallbackQuery | None, msg: Message | None, package_id: int = 1):
    pack = next((p for p in PACKAGES if p["id"] == package_id), PACKAGES[0])
    text = (
        "🔒 Premium Required\n\n"
        f"📦 Package: {pack['title']}\n"
        f"💰 Price: {pack['price']}\n\n"
        "1) Tap **Pay Now**\n"
        "2) After payment, tap **I Paid**\n\n"
        "⚠️ Until admin approval, the bot will keep returning you to this payment screen."
    )
    if call:
        await call.message.edit_text(text, reply_markup=paywall_kb(package_id), parse_mode="Markdown")
        await call.answer()
    elif msg:
        await msg.answer(text, reply_markup=paywall_kb(package_id), parse_mode="Markdown")

# -------------------- USER FLOW --------------------
@dp.message(CommandStart())
async def start(message: Message):
    if not await guard(message):
        return
    await message.answer(
        "Welcome! 👋\n\n"
        "🎬 You can watch demo videos for free.\n"
        "🔒 To get full access, purchase a package.",
        reply_markup=main_menu()
    )

@dp.message(F.text == "🎬 Demo Videos")
async def demo_btn(message: Message):
    if not await guard(message):
        return
    await message.answer(DEMO_TEXT, disable_web_page_preview=True, reply_markup=main_menu())

@dp.message(F.text == "💰 Packages")
async def packages_btn(message: Message):
    if not await guard(message):
        return
    await message.answer("Choose a package:", reply_markup=packages_kb())

@dp.message(F.text == "🔒 Get Videos (Premium)")
async def get_videos(message: Message):
    if not await guard(message):
        return
    uid = message.from_user.id
    if uid in PREMIUM_USERS:
        await message.answer("✅ Premium active! Here are your videos:", reply_markup=premium_videos_kb())
    else:
        await show_paywall(None, message, package_id=1)

@dp.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery):
    if not call.from_user:
        return
    if call.from_user.id in BANNED_USERS:
        await call.answer("Banned", show_alert=True)
        return
    await call.message.edit_text("Menu:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Demo Videos", callback_data="demo")],
        [InlineKeyboardButton(text="💰 Packages", callback_data="packages")],
        [InlineKeyboardButton(text="🔒 Get Videos (Premium)", callback_data="premium")],
    ]))
    await call.answer()

@dp.callback_query(F.data == "demo")
async def cb_demo(call: CallbackQuery):
    if not call.from_user:
        return
    if call.from_user.id in BANNED_USERS:
        await call.answer("Banned", show_alert=True)
        return
    await call.message.edit_text(DEMO_TEXT, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Packages", callback_data="packages")],
        [InlineKeyboardButton(text="⬅️ Menu", callback_data="menu")],
    ]))
    await call.answer()

@dp.callback_query(F.data == "packages")
async def cb_packages(call: CallbackQuery):
    if not call.from_user:
        return
    if call.from_user.id in BANNED_USERS:
        await call.answer("Banned", show_alert=True)
        return
    await call.message.edit_text("Choose a package:", reply_markup=packages_kb())
    await call.answer()

@dp.callback_query(F.data.startswith("pack:"))
async def cb_pack(call: CallbackQuery):
    if not call.from_user:
        return
    uid = call.from_user.id
    if uid in BANNED_USERS:
        await call.answer("Banned", show_alert=True)
        return

    package_id = int(call.data.split(":")[1])
    await show_paywall(call, None, package_id=package_id)

@dp.callback_query(F.data == "premium")
async def cb_premium(call: CallbackQuery):
    if not call.from_user:
        return
    uid = call.from_user.id
    if uid in BANNED_USERS:
        await call.answer("Banned", show_alert=True)
        return
    if uid in PREMIUM_USERS:
        await call.message.edit_text("✅ Premium active! Here are your videos:", reply_markup=premium_videos_kb())
        await call.answer()
    else:
        await show_paywall(call, None, package_id=1)

@dp.callback_query(F.data.startswith("paid:"))
async def cb_paid(call: CallbackQuery):
    """
    Infinite loop:
    - If user is NOT premium yet, always show paywall again.
    - Also notify admins each time (you can throttle later).
    """
    if not call.from_user:
        return
    uid = call.from_user.id
    if uid in BANNED_USERS:
        await call.answer("Banned", show_alert=True)
        return

    package_id = int(call.data.split(":")[1])

    # If already approved -> show premium videos
    if uid in PREMIUM_USERS:
        await call.message.edit_text("✅ Premium active! Here are your videos:", reply_markup=premium_videos_kb())
        await call.answer()
        return

    # Notify admins
    pack = next((p for p in PACKAGES if p["id"] == package_id), PACKAGES[0])
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🧾 Payment claim\n"
                f"User: {uid}\n"
                f"Package: {pack['title']} ({pack['price']})\n\n"
                f"Approve: /approve {uid}\n"
                f"Reject: /ban {uid}  (optional)"
            )
        except Exception as e:
            log.warning(f"Admin notify failed: {admin_id} {e}")

    # LOOP: show paywall again
    await show_paywall(call, None, package_id=package_id)

# -------------------- ADMIN COMMANDS --------------------
@dp.message(Command("approve"))
async def cmd_approve(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Usage: /approve <user_id>")
    uid = int(parts[1])
    PREMIUM_USERS.add(uid)
    BANNED_USERS.discard(uid)
    await message.answer(f"✅ Approved user: {uid}")

    # ping user
    try:
        await bot.send_message(uid, "✅ Your payment is approved! Premium access is now active.\nGo to: 🔒 Get Videos (Premium)")
    except Exception:
        pass

@dp.message(Command("revoke"))
async def cmd_revoke(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Usage: /revoke <user_id>")
    uid = int(parts[1])
    PREMIUM_USERS.discard(uid)
    await message.answer(f"🗑 Premium revoked: {uid}")

@dp.message(Command("ban"))
async def cmd_ban(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Usage: /ban <user_id>")
    uid = int(parts[1])
    BANNED_USERS.add(uid)
    PREMIUM_USERS.discard(uid)
    await message.answer(f"🚫 Banned user: {uid}")

@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return await message.answer("Usage: /unban <user_id>")
    uid = int(parts[1])
    BANNED_USERS.discard(uid)
    await message.answer(f"🔓 Unbanned user: {uid}")

@dp.message(Command("admins"))
async def cmd_admins(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await message.answer(f"Admins: {', '.join(map(str, sorted(ADMIN_IDS))) or '(none)'}")

# -------------------- RUN --------------------
async def main():
    log.info("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
