import logging
import time
import os
import asyncio
import json
import uuid
import gc
from datetime import datetime, timedelta
from threading import Thread

# Flask Web Server
try:
    from flask import Flask
    app = Flask(__name__)
    
    @app.route('/')
    def home():
        return "Bot is running successfully!"
    
    def run_server():
        port = int(os.environ.get("PORT", 10000))
        app.run(host='0.0.0.0', port=port)
    
    def keep_alive():
        t = Thread(target=run_server)
        t.daemon = True
        t.start()
except ImportError:
    print("Warning: Flask not installed - running without web server")
    def keep_alive():
        pass

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    LabeledPrice,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)
from telegram.request import HTTPXRequest

# ---------------------------------------------------------
# Secure Configuration - Environment Variables Only
# ---------------------------------------------------------
# Bot Token - Required
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not configured in environment variables.")

# Admin User ID - Required
ADMIN_USER_ID_STR = os.getenv("ADMIN_USER_ID")
if not ADMIN_USER_ID_STR:
    raise RuntimeError("ADMIN_USER_ID is not configured in environment variables.")
ADMIN_USER_ID = int(ADMIN_USER_ID_STR)

# Notification Channel ID - Required
NOTIFICATION_CHANNEL_ID_STR = os.getenv("NOTIFICATION_CHANNEL_ID")
if not NOTIFICATION_CHANNEL_ID_STR:
    raise RuntimeError("NOTIFICATION_CHANNEL_ID is not configured in environment variables.")
NOTIFICATION_CHANNEL_ID = int(NOTIFICATION_CHANNEL_ID_STR)

# Non-sensitive Information
STORE_EMAIL = "Atpledgestore@Gmail.com"
WHATSAPP_NUMBER = "218925869198"
WHATSAPP_URL = f"https://wa.me/{WHATSAPP_NUMBER}"

TELEGRAM_URL = "https://t.me/ATPLEdge"
INSTAGRAM_URL = "https://www.instagram.com/capt.salem_albarghti"
TIKTOK_URL = "https://www.tiktok.com/@capt_salemalbarghti"
PINTEREST_URL = "https://pin.it/1izN38UZ8"

STARS_PER_USD = 50

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_carts = {}
user_cart_messages = {}
user_agreed_terms = set()
user_cart_timestamps = {}
completed_orders = {}
order_history = {}
user_last_message_id = {}
cart_creation_notified = set()

CART_EXPIRY_HOURS = 24
BACKUP_FILE = "orders_backup.json"


# ---------------------------------------------------------
# Backup System
# ---------------------------------------------------------
def save_order_backup(order_data):
    try:
        with open(BACKUP_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(order_data, ensure_ascii=False) + '\n')
        logger.info("Order backup saved")
    except Exception as e:
        logger.error(f"Failed to save backup: {e}")

def load_order_history():
    try:
        if os.path.exists(BACKUP_FILE):
            with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        order = json.loads(line)
                        order_history[order.get('order_id')] = order
                    except:
                        continue
            logger.info(f"Loaded {len(order_history)} orders")
    except Exception as e:
        logger.error(f"Failed to load backup: {e}")

# ---------------------------------------------------------
# Cart Management
# ---------------------------------------------------------
def cleanup_old_carts():
    now = datetime.now()
    expired_users = []
    
    for user_id, timestamp in user_cart_timestamps.items():
        if now - timestamp > timedelta(hours=CART_EXPIRY_HOURS):
            expired_users.append(user_id)
    
    for user_id in expired_users:
        user_carts.pop(user_id, None)
        user_cart_messages.pop(user_id, None)
        user_cart_timestamps.pop(user_id, None)
        logger.info(f"Cart deleted for user {user_id}")
    
    if expired_users:
        gc.collect()
    
    return expired_users

def update_cart_timestamp(user_id):
    user_cart_timestamps[user_id] = datetime.now()

def get_cart_remaining_time(user_id):
    if user_id in user_cart_timestamps:
        expiry = user_cart_timestamps[user_id] + timedelta(hours=CART_EXPIRY_HOURS)
        remaining = expiry - datetime.now()
        if remaining.total_seconds() > 0:
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return hours, minutes
    return 0, 0

# ---------------------------------------------------------
# Admin Notification System
# ---------------------------------------------------------
async def send_admin_notification(context, order_data, is_free_items=False):
    """Send purchase notification to private channel and admin DM"""
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    order_data['order_id'] = order_id
    
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    items_list = "\n".join([f"📚 {i+1}. {item['title']}" for i, item in enumerate(order_data['items'])])
    
    if is_free_items:
        order_type = "🎁 FREE ITEMS CLAIMED"
    else:
        order_type = "💰 NEW PURCHASE"
    
    admin_message = f"""
🔔 *{order_type}* 🔔

━━━━━━━━━━━━━━━━━━━━━
📋 *ORDER DETAILS:*
━━━━━━━━━━━━━━━━━━━━━

🆔 Order ID: `{order_id}`
👤 User ID: `{order_data['user_id']}`
📝 Username: @{order_data.get('user_name', 'Unknown')}
👨‍✈️ Full Name: {order_data.get('full_name', 'Unknown')}

━━━━━━━━━━━━━━━━━━━━━
📚 *ITEMS:*
━━━━━━━━━━━━━━━━━━━━━
{items_list}

━━━━━━━━━━━━━━━━━━━━━
💰 *PAYMENT DETAILS:*
━━━━━━━━━━━━━━━━━━━━━
💵 USD Amount: ${order_data['total_usd']:.2f}
⭐ Telegram Stars: {order_data['total_stars']} Stars
💳 Payment ID: `{order_data.get('charge_id', 'N/A')}`

━━━━━━━━━━━━━━━━━━━━━
📅 *DATE & TIME:*
━━━━━━━━━━━━━━━━━━━━━
📆 Date: {date_str}
⏰ Time: {time_str} UTC

━━━━━━━━━━━━━━━━━━━━━
📊 *SUMMARY:*
━━━━━━━━━━━━━━━━━━━━━
📦 Total Items: {len(order_data['items'])}
🎁 Free Items: {order_data.get('free_items', 0)}
💎 Paid Items: {order_data.get('paid_items', 0)}
🔥 Discount: {'Yes (10%)' if order_data.get('discount_applied') else 'No'}
"""

    if is_free_items:
        admin_message += "\n🎁 *FREE ITEMS - NO PAYMENT REQUIRED*\n"
    
    admin_message += "━━━━━━━━━━━━━━━━━━━━━"
    
    completed_orders[order_id] = order_data
    order_history[order_id] = order_data
    save_order_backup(order_data)
    
    channel_sent = False
    try:
        await context.bot.send_message(
            chat_id=NOTIFICATION_CHANNEL_ID,
            text=admin_message,
            parse_mode="Markdown"
        )
        logger.info(f"✅ Order notification sent to private channel for order {order_id}")
        channel_sent = True
    except Exception as e:
        logger.error(f"❌ Failed to send to channel: {e}")
    
    try:
        if channel_sent:
            short_notification = (
                f"📢 *New Order Received!*\n\n"
                f"🆔 Order ID: `{order_id}`\n"
                f"👤 User: @{order_data.get('user_name', 'Unknown')}\n"
                f"💰 Amount: ${order_data['total_usd']:.2f}\n"
                f"📅 Date: {date_str} {time_str}\n\n"
                f"📋 *Full details in private channel.*"
            )
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=short_notification,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=admin_message,
                parse_mode="Markdown"
            )
        logger.info(f"✅ Admin DM notification sent for order {order_id}")
    except Exception as e:
        logger.error(f"❌ Failed to send admin DM notification: {e}")
    
    return order_id

# ---------------------------------------------------------
# Cart Expiry Notifications
# ---------------------------------------------------------
async def send_cart_expiry_notice(user_id, context, hours_remaining):
    try:
        message = f"""
⏰ *CART EXPIRY WARNING*

Your shopping cart will expire soon!

⏳ Time Remaining: {hours_remaining} hours

⚠️ *IMPORTANT:*
Your cart will be automatically deleted after 24 hours.
Please complete your purchase before the time runs out.

💡 *TIP:* You can remove items manually using the "Remove" button.
"""
        await context.bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send expiry notice: {e}")

async def check_cart_expiry(context):
    now = datetime.now()
    
    for user_id, timestamp in list(user_cart_timestamps.items()):
        hours_passed = (now - timestamp).total_seconds() / 3600
        
        if hours_passed >= 18 and hours_passed < 19:
            await send_cart_expiry_notice(user_id, context, 6)
        
        elif hours_passed >= 23 and hours_passed < 24:
            await send_cart_expiry_notice(user_id, context, 1)
        
        elif hours_passed >= 24:
            user_carts.pop(user_id, None)
            user_cart_messages.pop(user_id, None)
            user_cart_timestamps.pop(user_id, None)
            
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🗑️ *Cart automatically deleted*\n\nYour cart has expired (24 hours).",
                    parse_mode="Markdown"
                )
            except:
                pass

# ---------------------------------------------------------
# Sales Report
# ---------------------------------------------------------
async def sales_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ This command is for admin only")
        return
    
    if not completed_orders:
        await update.message.reply_text("📊 No sales recorded yet")
        return
    
    total_orders = len(completed_orders)
    total_revenue = sum(order.get('total_usd', 0) for order in completed_orders.values())
    total_stars = sum(order.get('total_stars', 0) for order in completed_orders.values())
    
    today = datetime.now().date()
    today_orders = [o for o in completed_orders.values() if o.get('date') == today.strftime("%Y-%m-%d")]
    today_revenue = sum(o.get('total_usd', 0) for o in today_orders)
    
    report = f"""
📊 *SALES REPORT*

━━━━━━━━━━━━━━━━━━━━━
📦 Total Orders: {total_orders}
💰 Total Revenue: ${total_revenue:.2f}
⭐ Total Stars: {total_stars}

📅 Today's Orders: {len(today_orders)}
💵 Today's Revenue: ${today_revenue:.2f}
━━━━━━━━━━━━━━━━━━━━━
"""
    
    await update.message.reply_text(report, parse_mode="Markdown")

# ---------------------------------------------------------
# Order History
# ---------------------------------------------------------
async def orders_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    user_orders = [o for o in completed_orders.values() if o.get('user_id') == user_id]
    
    if not user_orders:
        text = "📋 *No Previous Orders Found*\n\nYou don't have any previous orders yet."
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
        ])
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
        return
    
    history_text = f"📋 *YOUR ORDER HISTORY* ({len(user_orders)} orders):\n\n"
    
    for i, order in enumerate(user_orders[-10:], 1):
        history_text += f"""
━━━━━━━━━━━━━━━━━━━━━
📦 *Order {i}:*
🆔 ID: `{order.get('order_id', 'N/A')}`
📅 Date: {order.get('date', 'N/A')} {order.get('time', '')}
💰 Amount: ${order.get('total_usd', 0):.2f}
📚 Items: {len(order.get('items', []))} items
━━━━━━━━━━━━━━━━━━━━━
"""
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
    ])
    await update.message.reply_text(history_text, parse_mode="Markdown", reply_markup=markup)

# ---------------------------------------------------------
# Books Database - PLACEHOLDER
# ---------------------------------------------------------
# ---------------------------------------------------------
# 2. Books & Videos Database (Including Free Aviation Books)
# ---------------------------------------------------------
BOOKS_DATABASE = {
    # ------------------ 1. CAE Oxford ATPL 2020 Collection ------------------
    "book_cae_bundle": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "🌟 COMPLETE CAE OXFORD ATPL SERIES (ALL 14 BOOKS BUNDLE)",
        "details": "Get the complete 14-Book CAE Oxford ATPL Ground Training Series at a special bundle price!",
        "price_usd": 169.99,
        "cover_url": "AgACAgQAAxkBAAPiapDOAqlpDHxv14CAXfu4XfbtnboAAmkRaxtZgIBQwVg_XJwGiYgBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/drive/folders/1pJPDz-2wzmQwb1RGT7WHBC-C-IbPwX7G?usp=sharing",
    },
    "book_cae_1": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Air Law (Book 1)",
        "details": "A foundational textbook for the EASA ATPL theoretical knowledge exams.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAO8apDDenQ14WTfzUXj0VNk_ScQm-UAAlMRaxtZgIBQE47JFX9794UBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1BgU09ppp50tnp9qYiAc8om4W91Ly4lkW/view?usp=sharing",
    },
    "book_cae_2": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Airframes and Systems (Book 2)",
        "details": "A core textbook for the EASA ATPL theoretical knowledge syllabus.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAO-apDD2KtYO_IxHwiJecEJXMd3HRsAAlQRaxtZgIBQgLt08rT2YW8BAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/1aYCYMVJz8FWDF0VR7lZd5kNXrV1h2ut6/view?usp=sharing",
    },
    "book_cae_3": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Electrics and Electronics (Book 3)",
        "details": "A core textbook for the EASA ATPL theoretical syllabus covering aircraft electrical systems.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPBapDD_0Peo-daMvUVI6aCmbdgKbQAAlURaxtZgIBQK8laNNUx_EkBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1Hk70YozTtOFeXcw1ImmI1pjuGXRqyLEu/view?usp=sharing",
    },
    "book_cae_4": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Powerplant (Book 4)",
        "details": "A core textbook covering principles and systems of piston and gas turbine engines.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPDapDFhjkTn78zsMjuSJWXNcfBYMEAAlkRaxtZgIBQs4G67U5wwmUBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1VudloRQD6DnLTriuKoXgL4TnYYYClYQv/view?usp=sharing",
    },
    "book_cae_5": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Instrumentation (Book 5)",
        "details": "A core textbook covering the complete range of aircraft instrumentation.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPFapDF1JUxpzYQ9Py0kiBVcAqyE_QAAloRaxtZgIBQljFFaG-EdoUBAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/14E4JvEGDqdSqYRKzjuWdy1gDi79OVPE3/view?usp=sharing",
    },
    "book_cae_6": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Mass and Balance (Book 6)",
        "details": "A core textbook covering aircraft weight and balance management.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPHapDGKGpJDodtIgE-OShODYSGzhoAAlsRaxtZgIBQREzzMQ-UBYQBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1B9-kAttiNbDq0xQ4o3KCTT_SQDGKby3Y/view?usp=sharing",
    },
    "book_cae_8": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Flight Planning and Monitoring (Book 8)",
        "details": "A core textbook covering essential knowledge and calculations for flight planning.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPJapDGobt45Lgj8ObPRndQbQUs_oUAAlwRaxtZgIBQKb7_jDaxC6MBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/122zaA2aE8cOYBEo58srwch80fHjpYXSm/view?usp=sharing",
    },
    "book_cae_9": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Human Performance and Limitations (Book 9)",
        "details": "A core textbook covering physiological and psychological factors affecting pilot performance.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPLapDG5-nxMGvlAW93L6HayYwO-C0AAl0RaxtZgIBQGgdx-d_BJYgBAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/1FElgozWqKWOfcpiCA0hZdP5gMgs5BKhy/view?usp=sharing",
    },
    "book_cae_10": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Meteorology (Book 10)",
        "details": "A core textbook covering essential meteorological knowledge for pilots.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPNapDHpCuzd8rmOb69XyhHbx7HnLYAAl4RaxtZgIBQk9ksAAGviJSPAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/14HXeXJ8nxFg66Vc5iJiYgwscWg5oM8T5/view?usp=sharing",
    },
    "book_cae_11": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "General Navigation (Book 11)",
        "details": "A core textbook covering navigation, map projections, dead reckoning, and wind triangles.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPPapDIMeW2Waz2ok5pmfmj5OHAt4IAAl8RaxtZgIBQJDlr6n5XKyABAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1655IZ4RSpZXzCvvZS5xFtjGVwAhHL_jC/view?usp=sharing",
    },
    "book_cae_12": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Radio Navigation (Book 12)",
        "details": "A core textbook covering radio-navigation theory and systems.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPRapDIhn1O0qk6_7kCRzTJByoV2McAAmARaxtZgIBQrokDoHVH-RQBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1p7HsEalhLnXL70wWjqIMzBUsXdUjAHz0/view?usp=sharing",
    },
    "book_cae_13": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Operational Procedures (Book 13)",
        "details": "A core textbook covering regulations for commercial flight operations.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPTapDJCAuX1hnVggwkJ1VRuLZQxp0AAmERaxtZgIBQhDoxLBbM5JMBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1WOXLk6UUhq9WB08pYHLJBnTCTUj501sd/view?usp=sharing",
    },
    "book_cae_14": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Principles of Flight (Book 14)",
        "details": "A core textbook covering aerodynamic principles and flight controls.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPVapDJxv_7lnmlJOy15PbmL95-Iz4AAmIRaxtZgIBQUqz75_LUyHYBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1toikJxKABy37-7Po3MSk-5W6Oc7aMKLv/view?usp=sharing",
    },
    "book_cae_15": {
        "category_id": "cat_cae_2020",
        "category_name": "📚 CAE Oxford ATPL 2020 Collection",
        "title": "Communications (Book 15)",
        "details": "A core textbook covering radiotelephony procedures and standard phraseology.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAPXapDKTjIRwT1aQtIQH-uV3aVwOTQAAmMRaxtZgIBQT9jHXmtAFoQBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/11nY9tR1vKa_kuSmuq-LDntZKNPJaTehY/view?usp=sharing",
    },

    # ------------------ 2. CAE Oxford ATPL 2014 Collection ------------------
    "book_cae2014_1": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Air Law",
        "details": "A foundational textbook for the EASA ATPL theoretical knowledge exams[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB6mqR1TeIxXhfa7C-XKSvd6ME357BAAKYD2sb8e6QUEC7uzjz6gNVAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1807g61SK-DwApBQXFo1GeLf1eWmzAxs7/view?usp=sharing",
    },
    "book_cae2014_2": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Airframes and Systems",
        "details": "A core EASA ATPL textbook comprehensively covering aircraft general knowledge[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB8GqR10rpA52dC2zxBc1YvVzvJKPFAAKZD2sb8e6QUOIpRmcqD4_PAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1ecUKXt6nJ1Zp_ugQS79xA4SS5_6vzacT/view?usp=sharing",
    },
    "book_cae2014_3": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Electrics and Electronics",
        "details": "A core EASA ATPL textbook covering aircraft electrical and electronic systems[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB8mqR13872CkpUj0mcxouF_Tmg6GjAAKbD2sb8e6QUGx6P0yNgV7iAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1SBWAITgfIceEwDKm5OJ_aQ2tJMxBHEDA/view?usp=sharing",
    },
    "book_cae2014_4": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Powerplant",
        "details": "A core EASA ATPL textbook covering the principles and systems of aircraft engines[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB9GqR18xR7E3n3Ci3pCuSI9tO7yyPAAKcD2sb8e6QUGntJb2kTHVoAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/10KcazEBvNcekZEqqxpmD1wzQtG-CZWDL/view?usp=sharing",
    },
    "book_cae2014_5": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Instrumentation",
        "details": "A core EASA ATPL textbook covering the full spectrum of aircraft instrumentation[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB9mqR2Aj8SIceTRhgdYfNyLQXTQGdAAKdD2sb8e6QUJxZon0Tc33tAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1d-ZtqbQaum8tpmUhIzQSUm-OVlXW1Gec/view?usp=sharing",
    },
    "book_cae2014_6": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Mass and Balance · Performance",
        "details": "A core EASA ATPL textbook covering mass, balance, and performance calculations[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB-GqR2EI_vAPimVmxOeSVgmchwC1HAAKeD2sb8e6QUCS7AuadGJarAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1z-FW_ercC0d2MVl0aY2aKwYuK59mbUbF/view?usp=sharing",
    },
    "book_cae2014_8": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Flight Planning and Monitoring",
        "details": "A core EASA ATPL textbook covering essential knowledge for flight planning[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB-mqR2MUipn9sB3qmSPdavF3t4HwFAAKfD2sb8e6QUEMbiEYEH6mVAQADAgADbQADPQQ",
        "file_url": "https://drive.google.com/file/d/1dn9zytYld-e3Omp7KLTLjH8xdznoSrsx/view?usp=sharing",
    },
    "book_cae2014_9": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Human Performance and Limitations",
        "details": "A core EASA ATPL textbook covering physiological and psychological factors[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB_GqR2Nz__578MQABrKru1q07x615LQACoA9rG_HukFB9IfQUhdi0RgEAAwIAA3kAAz0E",
        "file_url": "https://drive.google.com/file/d/1mydmsJDbSVFcBQ893PEflhxkUX9O2kRD/view?usp=sharing",
    },
    "book_cae2014_10": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Meteorology",
        "details": "A core EASA ATPL textbook covering essential meteorological knowledge[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIB_mqR2RM6_OfRyqdTR7og8QJh18VCAAKhD2sb8e6QUApCA3w37DZBAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1unQxLi6i9J_8fYy96qudbpk-i86kBy01/view?usp=sharing",
    },
    "book_cae2014_11": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "General Navigation",
        "details": "A core EASA ATPL textbook covering foundational principles of air navigation[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAICAAFqkdk_wj36-7ZjHJ7E5pwaVdee7QACog9rG_HukFAPt0BxxcFyaAEAAwIAA3kAAz0E",
        "file_url": "https://drive.google.com/file/d/1xa0Ggx9ug3NDXpYspCTOx5F1qB2WsLFg/view?usp=sharing",
    },
    "book_cae2014_12": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Radio Navigation",
        "details": "A core EASA ATPL textbook covering theory and application of radio navigation[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAICAmqR2Xm8y1PAhh3HkaPN-cJMBjyrAAKjD2sb8e6QUPqLu27u5BsuAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1bk_bC8eJMRrWYA60lraY6ZoDMwAKQ0sY/view?usp=sharing",
    },
    "book_cae2014_13": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Operational Procedures",
        "details": "A core EASA ATPL textbook covering regulatory and procedural requirements[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAICBGqR2adUx_FKPfR-rl3J1Y3n_qtjAAKkD2sb8e6QUJkEbRDqN1t8AQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1uQnHk6k6qwXTBMQUevCDlyalAs62RPGr/view?usp=sharing",
    },
    "book_cae2014_14": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Principles of Flight",
        "details": "A core EASA ATPL textbook building a strong foundation in aerodynamics[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAICBmqR2dzaroVen3RqklZayAShHccoAAKlD2sb8e6QUEa_Ev1v9BXUAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1N9i_GQpWJtKOXXs5sCl68MUJ33o5TWNT/view?usp=sharing",
    },
    "book_cae2014_15": {
        "category_id": "cat_cae_2014",
        "category_name": "📚 CAE Oxford ATPL 2014 Collection",
        "title": "Communications",
        "details": "A core EASA ATPL textbook covering radiotelephony procedures and phraseology[cite: 2].",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAICCGqR2xa8f-Slq_-9zRtqFyCep10MAAKnD2sb8e6QUETbfD8ardaKAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/1K24-dqh-v04K-YzH0sAek5E9FWP3w6DN/view?usp=sharing",
    },

    # ------------------ 3. FAA Books ------------------
    "book_faa_1": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aeronautical Chart User's Guide (12th Edition)",
        "details": "A comprehensive FAA guide to understanding all symbols and terms on U.S. aviation charts, covering VFR and IFR charts, terminal procedures, and airspace classifications. It is an essential reference for novice and experienced pilots alike.",
        "price_usd": 11.99,
        "cover_url": "AgACAgQAAxkBAAICI2qR_XKj3vDNLZTsHMXKKu4yrIm3AAIUEGsb8e6QUA_nX4P6UqcrAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1RoxMzn7AQo73FCaPXTbnCUUGeMeWa3gS/view?usp=sharing",
    },
    "book_faa_2": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Pilot's Handbook of Aeronautical Knowledge (FAA-H-8083-25)",
        "details": "An official FAA handbook that provides essential, foundational knowledge for all pilots, from students to those seeking advanced certification. It covers a broad spectrum of topics including aerodynamics, aircraft systems, flight instruments, weather theory, and airspace regulations, serving as a primary reference for pilot training.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICJ2qSAAFM4gqmhBOPls8iZfmzND4nKgACIhBrG_HukFD3f4cqvl6BLAEAAwIAA3gAAz0E",
        "file_url": "https://drive.google.com/file/d/1xQelM_6c1_SEi27n-tXPXtU89HWdEKn2/view?usp=sharing",
    },
    "book_faa_3": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aviation Maintenance Technician Handbook – Airframe, Volume 1 (FAA-H-8083-31)",
        "details": "The official FAA handbook for A&P mechanics covering airframe structures and systems. Volume 1 includes topics on construction, assembly, fabric covering, structural repairs, and welding. It supports preparation for the FAA Knowledge and O&P exams.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICL2qSAVNgjZ3_mGlqwkt_9u6qKESEAAIkEGsb8e6QUFrVWuimOuUrAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1uzU2EI1MzPaDMZmT_hDXCJfd3jJM0xI1/view?usp=sharing",
    },
    "book_faa_4": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aviation Maintenance Technician Handbook – Powerplant, Volume 2 (FAA-H-8083-32)",
        "details": "The official FAA handbook for A&P mechanics preparing for the Powerplant certification. Volume 2 covers critical engine systems and procedures, including lubrication and cooling systems, propellers, engine removal and replacement, engine fire protection systems, and engine maintenance and operation.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICOWqSAsUKSF9G0y8Rv7xlUIxQs_NsAAImEGsb8e6QUCNrRl4DypmYAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1Hdpe8dKg24QGAxf6h3COHxc789eHqYg8/view?usp=sharing",
    },
    "book_faa_5": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aviation Maintenance Technician Handbook – General (FAA-H-8083-30)",
        "details": "The official FAA handbook for A&P mechanic certification, covering foundational topics common to both Airframe and Powerplant ratings. It includes subjects such as mathematics, physics, aircraft drawings, weight and balance, materials and processes, electricity, inspection, ground operations, and regulations. This volume also includes a comprehensive glossary, which contains the definitions you provided.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICOWqSAxpm_Hr8u3AWhghj-5rCOAa0AAInEGsb8e6QUNUqL8IhbXt9AQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1YoPhT3tIgde3bncIlX1xPzaqdkB-aQeZ/view?usp=sharing",
    },
    "book_faa_6": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aviation Weather (Advisory Circular AC 00-6A)",
        "details": "The official FAA advisory circular providing essential weather knowledge for pilots and flight operations personnel. The book is divided into two parts: Part I covers weather facts every pilot should know, while Part II contains special topics on high altitude, Arctic, tropical, and soaring weather.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICP2qSA3DkmYkBF6aTOeQuueGbmCJrAAIpEGsb8e6QUNbC4ajjos59AQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1bDZUzjmpqOKMlnWnsdGBLHXKVGHa0rcr/view?usp=sharing",
    },
    "book_faa_7": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aircraft Weight and Balance Handbook (FAA-H-8083-1A)",
        "details": "The official FAA guide for pilots and mechanics on weight and balance principles. It includes methods for weighing aircraft, determining the center of gravity, and performing loading computations to ensure safe and efficient flight.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICQ2qSA-yX4UY7Mh9MNaYlgbLMUG5xAAIqEGsb8e6QUGPrRZSq0oHpAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1sbiAVuz1Es0PDYivyCUk6PnP2Fff6Z5j/view?usp=sharing",
    },
    "book_faa_8": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Risk Management Handbook (FAA-H-8083-2)",
        "details": "An official FAA handbook designed to help pilots recognize and manage risk through the application of practical tools and strategies. It covers essential topics such as identifying hazards, assessing and mitigating risk, aeronautical decision-making, threat and error management, and automation, all aimed at reducing the 85% of aviation accidents attributed to 'pilot error'.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICR2qSBD_ggmSbOYEd-7b9-OlK99RIAAIrEGsb8e6QUB-_suAGtGRhAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/17gGPVHSsduvC67DTbOaYedaRZu_0tv6v/view?usp=sharing",
    },
    "book_faa_9": {
    "category_id": "cat_faa_books",
    "category_name": "📘 FAA Books",
    "title": "Airplane Flying Handbook (FAA-H-8083-3B)",
    "details": "The official FAA guide for pilots, covering everything from ground operations and basic flight maneuvers to stalls, spins, takeoffs, landings, and emergency procedures. It is an essential reference for student pilots and those preparing for additional certificates.",
    "price_usd": 14.99,
    "cover_url": "AgACAgQAAxkBAAIC3mqS_Zpxc1NFeyA5-PnvN7-n9B8fAALIEGsbw7WYUDFrHXgwS8HVAQADAgADeAADPQQ",
    "file_url": "https://drive.google.com/file/d/1wvTHog8W85Ub_VXl51rLpYpAL_KVNOwt/view?usp=sharing",
        },
    "book_faa_10": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Weight-Shift Control Aircraft Flying Handbook (FAA-H-8083-5)",
        "details": "The official FAA handbook that introduces the basic knowledge and skills essential for piloting weight-shift control (WSC) aircraft. Flight control of these aircraft depends on the wing's ability to deform flexibly rather than on the use of control surfaces. This handbook is for student pilots, as well as those pursuing more advanced pilot certificates.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICT2qSBgTnzTX-bDcfAYHpdafGVO2vAAIvEGsb8e6QUL9OzPgUNZYwAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1-9FchobueyG1Ur0xYdff7mgDgE0Qt52a/view?usp=sharing",
    },
    "book_faa_11": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Advanced Avionics Handbook (FAA-H-8083-6)",
        "details": "The official FAA technical reference for pilots operating aircraft with advanced avionics, including integrated 'glass cockpit' systems. It covers Primary Flight Displays (PFD), Multi-Function Displays (MFD), moving maps, cockpit weather, terrain awareness, and traffic data.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICU2qSBmuqTJA3Qql6T3omVNKI9XD2AAIyEGsb8e6QUEswJ8SPk5_LAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1-auzW7h7G_yZhICCxjH6eWt1ErbQPlki/view?usp=sharing",
    },
    "book_faa_12": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Aviation Instructor's Handbook (FAA-H-8083-9A)",
        "details": "The official FAA guide for flight, ground, and aviation maintenance instructors. It covers the fundamentals of teaching and learning, focusing on aeronautical knowledge and skills to help educators effectively train the next generation of pilots and create a safety-focused learning environment.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICV2qSBqq-nWbHm3qNreDdf2YLJgAB8gACMxBrG_HukFDHE8lPyoVHewEAAwIAA3gAAz0E",
        "file_url": "https://drive.google.com/file/d/12FP13Cnh5PRvSk9ks9lH1RelLtrBJpMO/view?usp=sharing",
    },
    "book_faa_13": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Instrument Flying Handbook (FAA-H-8083-15A)",
        "details": "The official FAA guide for pilots training for an instrument rating, as well as instrument-rated pilots wishing to improve their knowledge and skills. The handbook covers the National Airspace System, ATC procedures, human factors, aerodynamics, instrument flight techniques, navigation systems, and IFR flight operations.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICW2qSBtzw8redc87MQPJtXL9UyHrYAAI0EGsb8e6QUPXZq62C0xxMAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1lVBsJhjZQxoY1LHWgpmHWq587rMUkfuq/view?usp=sharing",
    },
    "book_faa_14": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Flight Navigator Handbook (FAA-H-8083-18)",
        "details": "The official FAA reference for air navigation, covering how to measure and chart the earth, use flight instruments for navigation, and handle preflight planning and in-flight procedures, along with a celestial computation sheet.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICX2qSB0Nuo1CiFnLjo4SilOndsV6IAAI1EGsb8e6QUI6TmWUWLsjTAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1C3hbCEzbvi3ivirAVzj4HLJWRUOyPXyq/view?usp=sharing",
    },
    "book_faa_15": {
        "category_id": "cat_faa_books",
        "category_name": "📘 FAA Books",
        "title": "Pilot's Handbook of Aeronautical Knowledge (FAA-H-8083-25B)",
        "details": "An official FAA handbook providing essential, foundational knowledge for all pilots, from student pilots to those seeking advanced certification. It covers a broad spectrum of topics including principles of flight, aircraft systems, weather theory, airspace, navigation, and aeronautical decision-making.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAICY2qSB6lGIMs7tzpqb8o8QvO9GlDKAAI2EGsb8e6QUJA2wkfRM3EXAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/16RqKgJ-_Gbl4YEu5840k4j3sXt0O6X6z/view?usp=sharing",
    },

    # ------------------ 4. ASA Pilot Manuals & Guides ------------------
    "book_asa_1": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "The Pilot's Manual: Access to Flight",
        "details": "A comprehensive digital training manual for pilots pursuing Private Pilot and Instrument Rating certifications together.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAANsapCt3ZdeTD4_z50hoq1EYv9fsMIAAjsRaxtZgIBQVPSaNBspZdQBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1LB1glY3PPsp7k7AeiQWVMeZ0UvC5dG3N/view?usp=sharing",
    },
    "book_asa_2": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Aeronautical Chart User's Guide, 13th Edition",
        "details": "The definitive FAA reference for understanding all symbols and information on U.S. aviation charts.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAN5apC0IlyTB-BR4KDZ848RdCL5ZkgAAj4RaxtZgIBQbxJK3fEczukBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1hdUn_xLORCEO32bmGJip1Pb-rBFO40WV/view?usp=sharing",
    },
    "book_asa_3": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Aircraft Dispatcher Oral Exam Guide",
        "details": "An exam preparation guide for the FAA Aircraft Dispatcher certificate.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAN7apC0eylAt5u6D6Bn1ZGEBnYGN9IAAkARaxtZgIBQ4FqRCrT2G74BAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/1WY5ws-asrRMmhMzdgofCHC16XIhbkdet/view?usp=sharing",
    },
    "book_asa_4": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Airline Transport Pilot Test Prep 2020",
        "details": "A study guide for the FAA Airline Transport Pilot and Aircraft Dispatcher Knowledge Exams.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAN9apC02wmoBmK1iIBO5ItNx_YTEysAAkERaxtZgIBQ7cp8yI9LPZcBAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/1l91Gc2HiAQA5WC9kB7nulUMydaYM2TBH/view?usp=sharing",
    },
    "book_asa_5": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Checklist for Success: Airline Interview",
        "details": "A step-by-step interview preparation guide for aspiring airline pilots.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAN_apC1PdA0nMFhGRAih0Z9ivZeZNYAAkMRaxtZgIBQojwNT1OtvO4BAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/1cSW0DeEWrm1NMYcxTtJ6dwsqSHbVONzP/view?usp=sharing",
    },
    "book_asa_6": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Fly the Wing: Flight Training Handbook",
        "details": "A comprehensive textbook on operating transport-category airplanes.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAOBapC1kUcDnmb_bK8wDY6MoecOfQcAAkURaxtZgIBQ99O5fKbaaqwBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1Z7NAri8m7Aq_Kos6Q1ZOl5EHp98RWaNg/view?usp=sharing",
    },
    "book_asa_7": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Instrument Rating Test Prep 2017",
        "details": "An FAA exam study guide containing over 900 sample questions.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAODapC14oI0hwfmTmQ7WvSJrK1aZZ8AAkYRaxtZgIBQCZcezZNntc0BAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1u20ITt8yOxvzu1C058FoLVReshR17Sa1/view?usp=sharing",
    },
    "book_asa_8": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Practical Aviation & Aerospace Law",
        "details": "A comprehensive textbook providing foundational legal knowledge.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAOFapC2M_Bt8qcWjZk3J7OTECFIn6EAAkcRaxtZgIBQtV73oRA7-6EBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1YSu33WoyBlmN-FEwtXxzli9f4i1WdBzp/view?usp=sharing",
    },
    "book_asa_9": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Say Again, Please: Radio Communications",
        "details": "A practical guide to mastering aviation radio communications.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAOIapC2di9dOp3FM82PVa0C9bU68f4AAkgRaxtZgIBQqT8W8qa2wwoBAAMCAAN5AAM9BA",
        "file_url": "https://drive.google.com/file/d/14pKkDi8ilyOI5qxxGufe0XU7cM-AGPue/view?usp=sharing",
    },
    "book_asa_10": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "The Turbine Pilot's Flight Manual",
        "details": "A comprehensive guide for pilots transitioning to turbine-powered aircraft.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAOKapC2vLB6W4sOnCpNO0R_onP9v9cAAkkRaxtZgIBQ1fqPKtvVjxEBAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/1-c_4wkDYk1Ms2Zhzgh3e4QFUXFHIvHjc/view?usp=sharing",
    },
    "book_asa_11": {
        "category_id": "cat_asa_pilot",
        "category_name": "✈️ ASA Pilot Manuals & Guides",
        "title": "Pilots In Command: Your Best Trip, Every Trip",
        "details": "A leadership and professionalism guide for airline pilots.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAOoapDBM_Z3xp4kqufFDDhFshsppL4AAlIRaxtZgIBQ8PRaRVK_6Z8BAAMCAAN4AAM9BA",
        "file_url": "https://drive.google.com/file/d/103mOUIjSZVV_7snCi5CM5WLeSm6yCylS/view?usp=sharing",
    },

    # ------------------ 5. CAE Oxford ATPL CBT Videos ------------------
    "video_cbt_bundle": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "🔥 20% OFF - CAE Oxford ATPL CBT Complete Video Library (All 17 Subjects)",
        "details": "The complete collection of all 17 ATPL ground school subjects, featuring a total of 662 instructional videos covering all core aviation disciplines for comprehensive pilot training. (Special 20% Discount - Use code ATPL20)",
        "price_usd": 239.2,
        "cover_url": "AgACAgQAAxkBAAIC6GqTHhZGgXICROEQmWLO40fQV2zzAAIIEWsbw7WYUKAviCMjOI8KAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/drive/folders/bundle_link_placeholder"
    },
    "video_cbt_1": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Meteorology - CBT Video Course",
        "details": "Interactive visual instruction containing 60 videos on pressure systems, fronts, icing, and thunderstorm hazards.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIC7GqTHknOJmFDy6O-31mXC1-aZfzAAAIKEWsbw7WYUE5FVdsTvtE0AQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_met_link/view?usp=sharing"
    },
    "video_cbt_2": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Principles of Flight - CBT Video Course",
        "details": "Comprehensive computer-based training video series featuring 59 videos covering advanced aerodynamics and flight mechanics.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIC6mqTHi3v_0zr9_9GXhjmqHbS8-WgAAIJEWsbw7WYUPab9taoBOlmAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_pof_link/view?usp=sharing"
    },
    "video_cbt_3": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Airframes & Systems - CBT Video Course",
        "details": "Visual walkthrough containing 67 videos of hydraulic, pneumatic, landing gear, and flight control systems.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIC7mqTHmm5GPGcmdZJ8algOIFQXtVDAAILEWsbw7WYUJDYcS3BTwt5AQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_airframes_link/view?usp=sharing"
    },
    "video_cbt_4": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "AC Electrics - CBT Video Course",
        "details": "Detailed instructional series featuring 16 videos covering alternating current generation, distribution, and protection systems.",
        "price_usd": 19.99,
        "cover_url": "AgACAgQAAxkBAAIC8GqTHolj96rE-ECiKBcpiM5WX907AAIMEWsbw7WYUCoh0hsKxjoIAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_ac_electrics_link/view?usp=sharing"
    },
    "video_cbt_5": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Autoflight - CBT Video Course",
        "details": "Specialized training program consisting of 13 videos explaining flight directors, autopilot architectures, and autoland systems.",
        "price_usd": 19.99,
        "cover_url": "AgACAgQAAxkBAAIC8mqTHqNqlE0N0k7xCT7kPXAgW3jKAAIOEWsbw7WYUNdkIWZvp9tUAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_autoflight_link/view?usp=sharing"
    },
    "video_cbt_6": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Communication - CBT Video Course",
        "details": "Essential radiotelephony module featuring 19 videos covering VFR/IFR communication procedures and phraseology.",
        "price_usd": 19.99,
        "cover_url": "AgACAgQAAxkBAAIC9GqTHsXsYkJ-xTImZKbxu7lHhVCeAAIPEWsbw7WYUObKJT19aeZmAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_comm_link/view?usp=sharing"
    },
    "video_cbt_7": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "DC Electrics - CBT Video Course",
        "details": "Targeted instructional guide featuring 23 videos on direct current circuits, batteries, and aircraft electrical buses.",
        "price_usd": 19.99,
        "cover_url": "AgACAgQAAxkBAAIC9mqTHuHfVHpLc3wCeSzYVe5KYjFFAAIQEWsbw7WYUGDsoJXEuNowAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_dc_electrics_link/view?usp=sharing"
    },
    "video_cbt_8": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Flight Planning - CBT Video Course",
        "details": "Comprehensive operational training series containing 40 videos focused on fuel management, route planning, and CFP documentation.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIC-GqTHworzzU7_G4BSva_uE2wC-9bAAISEWsbw7WYUFeMpWu1UvFFAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_flight_planning_link/view?usp=sharing"
    },
    "video_cbt_9": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "General Navigation - CBT Video Course",
        "details": "In-depth navigational training program featuring 115 videos covering the Earth, magnetism, charts, time, and dead reckoning.",
        "price_usd": 29.99,
        "cover_url": "AgACAgQAAxkBAAIC-mqTHx0IcCoXKTfPX8hYYmpzi0cZAAITEWsbw7WYULU9m2HLfZ8xAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_gen_nav_link/view?usp=sharing"
    },
    "video_cbt_10": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Instruments - CBT Video Course",
        "details": "Technical instruction series comprising 46 videos explaining pitot-static instruments, gyros, IRS, and electronic flight instrument systems.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIC_GqTHzZOGj7YFNlm_11HeENrFhYcAAIUEWsbw7WYUCybkOVVAVzqAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_instruments_link/view?usp=sharing"
    },
    "video_cbt_11": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Mass & Balance - CBT Video Course",
        "details": "Structured curriculum featuring 16 videos covering loading criteria, center of gravity calculations, and structural limitations.",
        "price_usd": 19.99,
        "cover_url": "AgACAgQAAxkBAAIC_mqTH1Qam0mSmFxLP9ub2hMgOdqJAAIVEWsbw7WYULlkCKpLCBwSAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_mass_balance_link/view?usp=sharing"
    },
    "video_cbt_12": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Operational Procedures - CBT Video Course",
        "details": "Regulatory and operational guidelines featuring 38 videos covering emergency procedures, dangerous goods, and low visibility operations.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIDAAFqkx9lgR6gRwnic_65uCUyvFDHxAACFhFrG8O1mFALStJKTFZbVQEAAwIAA3kAAz0E",
        "file_url": "https://drive.google.com/file/d/sample_op_proced_link/view?usp=sharing"
    },
    "video_cbt_13": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Performance - CBT Video Course",
        "details": "Advanced performance analysis series consisting of 52 videos covering takeoff, climb, cruise, and landing performance calculations.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIDAmqTH388nknG7szBdFKsgq2ip0ADAAIXEWsbw7WYUPuCppXWs0UzAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_performance_link/view?usp=sharing"
    },
    "video_cbt_14": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Piston Engine - CBT Video Course",
        "details": "Mechanical breakdown series containing 33 videos detailing reciprocating engine construction, fuel systems, and ignition.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIDBGqTH5p6hcLT4b30qOKGqVYjV6LtAAIYEWsbw7WYUIsehKMr3fLSAQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_piston_engine_link/view?usp=sharing"
    },
    "video_cbt_15": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Radio Navigation - CBT Video Course",
        "details": "Electronic navigation training module featuring 28 videos covering VOR, ADF, DME, ILS, and radar principles.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIDBmqTH7O4lzG9KAkosQ1ltRCX11iHAAIZEWsbw7WYUNVGa5uEiRq8AQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_radio_nav_link/view?usp=sharing"
    },
    "video_cbt_16": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Turbine Engines - CBT Video Course",
        "details": "Comprehensive turbine theory guide consisting of 32 videos explaining gas turbine components, compressors, and thrust generation.",
        "price_usd": 24.99,
        "cover_url": "AgACAgQAAxkBAAIDCGqTH8p00rdQhbEMbWNZrEe0X8PRAAIaEWsbw7WYUNcPmzD87Fa7AQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_turbine_engines_link/view?usp=sharing"
    },
    "video_cbt_17": {
        "category_id": "cat_cbt_videos",
        "category_name": "🎬 CAE Oxford ATPL CBT Videos",
        "title": "Warning - CBT Video Course",
        "details": "Safety systems overview featuring 6 videos on stall warnings, GPWS, and TCAS alerts.",
        "price_usd": 14.99,
        "cover_url": "AgACAgQAAxkBAAIDCmqTH-Ed1TszHSVp1VpTf4m_6XDVAAIbEWsbw7WYUJldk_Yws_R-AQADAgADeQADPQQ",
        "file_url": "https://drive.google.com/file/d/sample_warning_link/view?usp=sharing"
    },

    # ------------------ 6. Free Aviation Books ------------------
    "book_free_1": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Procedures for Air Navigation Services – Air Traffic Management (Doc 4444)",
        "details": "The official ICAO manual specifying air traffic control procedures in detail. It is a fundamental reference for air traffic controllers and flight crews operating internationally, covering separation minima, ATS surveillance services, emergency procedures, and air traffic control clearances.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICdmqSEWSr2vUg5MI8ZgoXFUI2QmU6AAJDEGsb8e6QUKOKRSCLV_6BAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1eCHfTjCJWileQPnQ3MBMgmfK5wcJzbd3/view?usp=sharing"
    },
    "book_free_2": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Procedures for Air Navigation Services – Aircraft Operations – Volume II (Doc 8168 – 6th Ed, 2014)",
        "details": "The official ICAO technical manual providing the global specifications for designing instrument flight procedures. It is a fundamental reference for procedure designers and contains essential criteria for SIDs, STARs, and instrument approach operations.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICemqSEZI1GjyswtfLg75lh7aK7FzpAAJEEGsb8e6QUC2Gun-RoaHdAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1ENw8e0Ay0EfxhK9fAo9s5OA-KdF394gG/view?usp=sharing"
    },
    "book_free_3": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Procedures for Air Navigation Services - ICAO Abbreviations and Codes (Doc 8400)",
        "details": "The official ICAO document that specifies standardized abbreviations and codes for worldwide use in international aeronautical telecommunication and in aeronautical information documents.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICgGqSEcee8JGg5FFusNhwZZ1wL6XZAAJFEGsb8e6QUFBPbHkzPnd0AQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1DIyh6gHoXumJPQryz0_CL9m6glTh_p5a/view?usp=sharing"
    },
    "book_free_4": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Manual of Radiotelephony (Doc 9432)",
        "details": "The official ICAO manual that establishes the standard phraseology and communication procedures for aeronautical radiotelephony, detailing distress (MAYDAY) and urgency (PAN PAN) situations.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAIChGqSEidTL2WMTsxSP1wdkUzy-GLmAAJJEGsb8e6QUGUIAAGzRwZpqQEAAwIAA3gAAz0E",
        "file_url": "https://drive.google.com/file/d/14rSaSdEEvI8WxBb_rUps2UZB1_gfX8Hx/view?usp=sharing"
    },
    "book_free_5": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Manual of Air Traffic Services Data Link Applications (Doc 9694)",
        "details": "An ICAO guidance document introducing concepts of data link-based ATS like ADS, CPDLC, and DFIS.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICiGqSEnk5CvreOYIHBR74QD49Q0k1AAJNEGsb8e6QUAR4t6tzUjNmAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1dPlaydnWFPi1jKC1YuVKju9s8g1rCt9r/view?usp=sharing"
    },
    "book_free_6": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Manual of Aircraft Accident and Incident Investigation - Part I (Doc 9756)",
        "details": "The official ICAO manual providing the framework for establishing an independent accident investigation authority for prevention.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICjGqSErAoygHBOSSyIwUCX9yXWbXtAAJOEGsb8e6QUOkPuKq82YINAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/18yXDaemY1i3JZV_TiWabqwHSBieuKoPh/view?usp=sharing"
    },
    "book_free_7": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Global Navigation Satellite System (GNSS) Manual (Doc 9849)",
        "details": "The official ICAO manual providing guidance on the implementation and general overview of GNSS.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICkGqSEzjcrZHSO1Zlsgs2B4icDLAkAAJPEGsb8e6QUH_-4wmt4Kv5AQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/155xFWIg13GV-vtGYjIGKUpLUNo48FxNM/view?usp=sharing"
    },
    "book_free_8": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Performance-based Communication and Surveillance (PBCS) Manual (Doc 9869)",
        "details": "Provides the framework for managing communication and surveillance performance according to RCP and RSP specifications.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAIClGqSE_MHolkUTcynUJipjscMKbQYAAJQEGsb8e6QUB3y43eoSoQ7AQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1kerK4wjYrbL3V2I93vGnruDjbNRodmnE/view?usp=sharing"
    },
    "book_free_9": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "RNP AR Procedure Design Manual (Doc 9905)",
        "details": "Provides technical criteria for designing RNP AR instrument approach and departure procedures.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICmGqSFNvPwT-Wu-i9adAR_KG0UmQ_AAJSEGsb8e6QUKUduUaISB5EAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/13_xZzXu5GzZxQN-aPKGFMdLVFHlOKXNa/view?usp=sharing"
    },
    "book_free_10": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Procedures for Air Navigation Services – Aerodromes (Doc 9981)",
        "details": "Specifies detailed operational procedures for aerodrome operators, complementing Annex 14.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICnGqSFRzynlCsEhAG9efhofv0D7axAAJTEGsb8e6QUDJeaQSbbOEVAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1zM9q-b1k02vkNTIlRJDc1UmW9DsocjAt/view?usp=sharing"
    },
    "book_free_11": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Performance-based Navigation (PBN) Operational Approval Manual (Doc 9997)",
        "details": "Provides safety-related guidance on the operational approval process for PBN.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICoGqSFdBtDo1_7gk46g7OyWD_dG7yAAJUEGsb8e6QUEo39S3G7dJRAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/155xFWIg13GV-vtGYjIGKUpLUNo48FxNM/view?usp=sharing"
    },
    "book_free_12": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Manual on Remotely Piloted Aircraft Systems (RPAS) (Doc 10019)",
        "details": "Provides guidance for introducing RPAS into non-segregated airspace and at aerodromes.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICpGqSFqiUZswLWeYyfu2sTyfO8xgSAAJWEGsb8e6QUF1zvHnN2MFuAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/18PHENLvwL2KUW8Tcfz61WVDsbHfiz0u2/view?usp=sharing"
    },
    "book_free_13": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Procedures for Air Navigation Services – Aircraft Operations – Volume II (Doc 8168 – 5th Ed, 2006)",
        "details": "Provides detailed criteria for designing instrument flight procedures and obstacle clearances.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICqGqSFuoVs0yimKf4sZz2CHwhSnGOAAJXEGsb8e6QUH3kEfuX43HzAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1ENw8e0Ay0EfxhK9fAo9s5OA-KdF394gG/view?usp=sharing"
    },
    "book_free_14": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Cabin Crew Safety Training Manual (Doc 10002)",
        "details": "Provides competency-based training guidance for cabin crew members regarding safety and emergency procedures.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICrGqSFxdy8IMU3Kkk3RG9JVEdFeNzAAJYEGsb8e6QUO984Vs29daeAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1mddBZSKG0ueibECnakPUYMOKmotV8fQj/view?usp=sharing"
    },
    "book_free_15": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Check Your Aviation English",
        "details": "A self-study preparation book for pilots and ATCOs aiming to achieve ICAO Level 4 English proficiency.",
        "price_usd": 0.0,
        "cover_url": "AgACCagQAAxkBAAICsGqSGBGctEBN2Jyger35QdySYEfqAAJaEGsb8e6QUCarDeTQ6e8QAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1wZ7E4xXYlsRVn3UYesuDYqATyMNJkCwv/view?usp=sharing"
    },
    "book_free_16": {
        "category_id": "cat_free_books",
        "category_name": "🎁 Free Aviation Books",
        "title": "Flightpath: Aviation English for Pilots and ATCOs (Student's Book)",
        "details": "The definitive course for pilots and air traffic controllers needing ICAO Level 4 proficiency.",
        "price_usd": 0.0,
        "cover_url": "AgACAgQAAxkBAAICtGqSGMKZigjmPsiw9St7Rozw-L6eAAJbEGsb8e6QUCmrRSM6aQXAAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1AYX5gPPjesaujVkSTg-pDaoSw8cPlvA4/view?usp=sharing"
    },

    # ------------------ 7. Aviation Books ------------------
    "book_aviation_1": {
        "category_id": "cat_aviation_books",
        "category_name": "📖 Aviation Books",
        "title": "The Turbine Pilot's Flight Manual",
        "details": "General flight safety, jet systems, and turbine operations reference book.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAIDHWqTVXMpTDYwGjNBrQvH2wrfGd5kAAJZEWsbw7WYUDFeHRtco6omAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1-c_4wkDYk1Ms2Zhzgh3e4QFUXFHIvHjc/view?usp=sharing",
    },
    "book_aviation_2": {
        "category_id": "cat_aviation_books",
        "category_name": "📖 Aviation Books",
        "title": "Aerodynamics for Naval Aviators",
        "details": "The classic manual on aircraft aerodynamic performance, stability, and control.",
        "price_usd": 5.99,
        "cover_url": "AgACAgQAAxkBAAIDH2qTXrvgzP6x4x7tRiZB1irKWz5fAAJxEWsbw7WYUIWSQaVEWzIhAQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1LqE-Y4j84IxhITdULIU5VhKpD1cdp1Jj/view?usp=sharing",
    },
    "book_aviation_3": {
        "category_id": "cat_aviation_books",
        "category_name": "📖 Aviation Books",
        "title": "Weather Flying by Robert N. Buck",
        "details": "An essential pilot's guide to understanding weather patterns and flying safely in adverse conditions.",
        "price_usd": 12.99,
        "cover_url": "AgACAgQAAxkBAAIDImqTX9dK0o1hymjLD7tuhJbLtiHiAAJzEWsbw7WYUIHZL7P4GW79AQADAgADeAADPQQ",
        "file_url": "https://drive.google.com/file/d/1Ag4G9KehOkEF7WIcG006sU4K10O7Yqet/view?usp=sharing",
    },
}
# ---------------------------------------------------------
# Keyboards
# ---------------------------------------------------------
def get_terms_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I Agree to Terms & Conditions", callback_data="agree_terms")]
    ])

def get_whatsapp_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Connect via WhatsApp", url=WHATSAPP_URL)],
        [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
    ])

def get_socials_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Telegram Channel", url=TELEGRAM_URL),
            InlineKeyboardButton("📸 Instagram", url=INSTAGRAM_URL),
        ],
        [
            InlineKeyboardButton("🎵 TikTok", url=TIKTOK_URL),
            InlineKeyboardButton("📌 Pinterest", url=PINTEREST_URL),
        ],
        [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
    ])

def get_shop_categories_keyboard():
    keyboard = [
        [InlineKeyboardButton("🎁 Free Aviation Books", callback_data="cat_free_books")],
        [InlineKeyboardButton("📚 CAE Oxford ATPL 2020 Collection", callback_data="cat_cae_2020")],
        [InlineKeyboardButton("📚 CAE Oxford ATPL 2014 Collection", callback_data="cat_cae_2014")],
        [InlineKeyboardButton("📘 FAA Books", callback_data="cat_faa_books")],
        [InlineKeyboardButton("🎬 CAE Oxford ATPL CBT Videos", callback_data="cat_cbt_videos")],
        [InlineKeyboardButton("✈️ ASA Pilot Manuals & Guides", callback_data="cat_asa_pilot")],
        [InlineKeyboardButton("📖 Essential Aviation Books", callback_data="cat_aviation_books")],
        [InlineKeyboardButton("🛒 View Shopping Cart", callback_data="view_cart")],
        [InlineKeyboardButton("📋 Order History", callback_data="view_orders")],
        [InlineKeyboardButton("🌐 Connect on Social Media", callback_data="socials_menu")],
        [InlineKeyboardButton("💡 Suggestions & Book Requests", callback_data="suggestions_menu")],
        [InlineKeyboardButton("⭐ Support & Contribute (Custom Stars)", callback_data="donate_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# Core Handlers
# ---------------------------------------------------------
async def post_init(application):
    await application.bot.delete_my_commands()
    
    commands = [
        BotCommand("start", "🚀 Launch the bot"),
        BotCommand("shop", "🛒 Browse catalog"),
        BotCommand("cart", "🛒 View cart"),
        BotCommand("orders", "📋 Order history"),
        BotCommand("socials", "🌐 Social media"),
        BotCommand("donate", "⭐ Support development"),
        BotCommand("help", "❓ Get help"),
    ]
    await application.bot.set_my_commands(commands)
    
    load_order_history()
    
    if hasattr(application, 'job_queue') and application.job_queue:
        application.job_queue.run_repeating(
            check_cart_expiry,
            interval=3600,
            first=10
        )
        logger.info("Cart expiry check scheduled")

async def check_terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id not in user_agreed_terms:
        terms_text = (
            "⚖️ *TERMS AND CONDITIONS*\n\n"
            "Welcome to ATPL Edge Store. Before accessing our materials, you must accept our terms:\n\n"
            "1️⃣ All digital materials are for personal educational use only.\n"
            "2️⃣ Redistribution or commercial resale is strictly prohibited.\n"
            "3️⃣ Payments are final and non-refundable once content is delivered.\n\n"
            "Click the button below to accept:"
        )
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(terms_text, parse_mode="Markdown", reply_markup=get_terms_keyboard())
        elif update.message:
            await update.message.reply_text(terms_text, parse_mode="Markdown", reply_markup=get_terms_keyboard())
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_terms(update, context):
        return

    user_name = update.effective_user.first_name
    welcome_msg = (
        f"👨‍✈️ *Welcome aboard, Captain {user_name}!*\n\n"
        "✈️ Welcome to *ATPL Edge Store*, your destination for professional aviation training materials.\n\n"
        "📚 Select from the options below:"
    )
    if update.message:
        await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_shop_categories_keyboard())

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_terms(update, context):
        return

    shop_text = "🛒 *ATPL Edge Store Catalog*\n\n📚 Explore our library of aviation manuals. Select a category:"
    await update.message.reply_text(shop_text, parse_mode="Markdown", reply_markup=get_shop_categories_keyboard())

async def cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_terms(update, context):
        return

    user_id = update.effective_user.id
    await show_or_update_active_cart(update.effective_chat.id, user_id, context, update.message)

async def socials_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_terms(update, context):
        return

    text = "🌐 *Find us on the following platforms:*"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_socials_keyboard())

async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_terms(update, context):
        return

    user_id = update.effective_user.id
    text = (
        "⭐ *Support ATPL Edge Development*\n\n"
        "💙 You can support the ongoing maintenance and development of the aviation training platform by donating any number of Telegram Stars you prefer.\n\n"
        "📝 *Please send the number of stars you would like to donate as a message now.*\n\n"
        "Example: `50` or `100` or `500`"
    )
    
    user_expecting_donation[user_id] = True
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_terms(update, context):
        return

    help_text = (
        "✈️ *ATPL Edge Support Center*\n\n"
        "📧 For support, inquiries, or book requests:\n\n"
        f"📧 *Email:* {STORE_EMAIL}"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", reply_markup=get_whatsapp_keyboard())

# ---------------------------------------------------------
# Text Message Handler (For Manual Donation Input)
# ---------------------------------------------------------
async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for manual donation input"""
    user_id = update.effective_user.id
    
    if user_expecting_donation.get(user_id, False):
        text_val = update.message.text.strip()
        
        try:
            stars_val = int(text_val)
            if stars_val <= 0:
                raise ValueError()
            
            user_expecting_donation[user_id] = False
            
            usd_val = stars_val / STARS_PER_USD
            title_text = f"ATPL Edge Custom Contribution ({stars_val} Stars)"
            
            await start_telegram_donation_checkout_manual(update, context, usd_val, stars_val, title_text)
            
        except ValueError:
            await update.message.reply_text(
                "❌ *Invalid input!*\n\n"
                "Please enter a valid positive number for Telegram Stars.\n"
                "Example: `50` or `100`",
                parse_mode="Markdown"
            )
        return

# ---------------------------------------------------------
# Manual Donation Checkout
# ---------------------------------------------------------
async def start_telegram_donation_checkout_manual(update, context, usd_amount, stars_amount, title):
    """Create invoice for manual star donation"""
    user_id = update.effective_user.id
    payload = f"atpl_edge_donation_{user_id}_{int(time.time())}"
    currency = "XTR"
    
    description = f"Supporting ATPL Edge with {stars_amount} Stars (${usd_amount:.2f}) contribution."
    
    prices = [LabeledPrice(title, stars_amount)]
    chat_id = update.effective_chat.id
    
    try:
        await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency=currency,
            prices=prices,
            start_parameter="donation-payment",
        )
        logger.info(f"Manual donation invoice sent to user {user_id} for {stars_amount} stars")
    except Exception as e:
        logger.error(f"Error sending manual donation invoice: {e}")
        await update.message.reply_text(
            "❌ An error occurred while processing your donation. Please try again.",
            parse_mode="Markdown"
        )

# ---------------------------------------------------------
# Callback Handler
# ---------------------------------------------------------
async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    chat_id = query.message.chat_id
    data = query.data

    try:
        await query.message.delete()
    except:
        pass

    if data == "agree_terms":
        user_agreed_terms.add(user_id)
        text = "✅ *Terms Accepted!*\n\n👨‍✈️ Welcome to ATPL Edge Store. Select from the options below:"
        markup = get_shop_categories_keyboard()
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
        user_cart_messages[user_id] = sent.message_id
        return

    if data != "agree_terms" and not await check_terms(update, context):
        return

    cleanup_old_carts()

    if data == "back_to_categories":
        text = "🛒 *ATPL Edge Store Catalog*\n\n📚 Select a category:"
        markup = get_shop_categories_keyboard()
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
        user_cart_messages[user_id] = sent.message_id
        return

    elif data == "socials_menu":
        text = "🌐 *Find us on the following platforms:*"
        markup = get_socials_keyboard()
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
        user_cart_messages[user_id] = sent.message_id
        return

    elif data == "suggestions_menu":
        text = (
            "💡 *Suggestions & Book Requests*\n\n"
            "📧 For suggestions or book requests:\n\n"
            f"📧 *Email:* {STORE_EMAIL}"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 Contact via WhatsApp", url=WHATSAPP_URL)],
            [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
        ])
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
        user_cart_messages[user_id] = sent.message_id
        return

    elif data == "donate_menu":
        text = (
            "⭐ *Support ATPL Edge Development*\n\n"
            "💙 You can support the ongoing maintenance and development of the aviation training platform by donating any number of Telegram Stars you prefer.\n\n"
            "📝 *Please send the number of stars you would like to donate as a message now.*\n\n"
            "Example: `50` or `100` or `500`"
        )
        
        user_expecting_donation[user_id] = True

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
        ])
        
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="Markdown")
        user_cart_messages[user_id] = sent.message_id
        return

    elif data == "view_orders":
        user_orders = [o for o in completed_orders.values() if o.get('user_id') == user_id]
        
        if not user_orders:
            text = "📋 *No Previous Orders Found*\n\nYou don't have any previous orders yet."
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
            ])
            sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
            user_cart_messages[user_id] = sent.message_id
        else:
            history_text = f"📋 *YOUR ORDER HISTORY* ({len(user_orders)} orders):\n\n"
            for i, order in enumerate(user_orders[-10:], 1):
                history_text += f"""
━━━━━━━━━━━━━━━━━━━━━
📦 *Order {i}:*
🆔 ID: `{order.get('order_id', 'N/A')}`
📅 Date: {order.get('date', 'N/A')} {order.get('time', '')}
💰 Amount: ${order.get('total_usd', 0):.2f}
📚 Items: {len(order.get('items', []))} items
━━━━━━━━━━━━━━━━━━━━━
"""
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Return to Main Menu", callback_data="back_to_categories")]
            ])
            sent = await context.bot.send_message(chat_id=chat_id, text=history_text, reply_markup=markup, parse_mode="Markdown")
            user_cart_messages[user_id] = sent.message_id
        return

    elif data.startswith("remove_cart_"):
        try:
            item_index = int(data.replace("remove_cart_", ""))
            if user_id in user_carts and 0 <= item_index < len(user_carts[user_id]):
                removed_item = user_carts[user_id].pop(item_index)
                update_cart_timestamp(user_id)
                await query.answer(f"🗑️ Removed: {removed_item['title']}", show_alert=False)
        except Exception as e:
            logger.error(f"Error removing item: {e}")

        await show_or_update_active_cart(chat_id, user_id, context, query.message)
        return

    elif data.startswith("cat_"):
        buttons = []
        category_name = ""

        for book_id, book in BOOKS_DATABASE.items():
            if book.get("category_id") == data:
                category_name = book["category_name"]
                price_usd = book["price_usd"]
                stars_val = int(price_usd * STARS_PER_USD)
                if price_usd == 0.0:
                    buttons.append([InlineKeyboardButton(f"📖 {book['title']} (FREE)", callback_data=f"show_book_{book_id}")])
                else:
                    buttons.append([InlineKeyboardButton(f"📖 {book['title']} (${price_usd})", callback_data=f"show_book_{book_id}")])

        if buttons:
            buttons.append([InlineKeyboardButton("⬅️ Return to Categories", callback_data="back_to_categories")])
            reply_markup = InlineKeyboardMarkup(buttons)

            header_note = f"{category_name}\n\n📚 Select any publication to view details:"
            if data == "cat_free_books":
                header_note += "\n\n🎁 *All books in this section are 100% FREE!*"
            elif data == "cat_cae_2020":
                header_note += "\n\n💡 *Individual manuals are $12.99 each, or get the complete bundle for $169.99!*"
            elif data == "cat_cae_2014":
                header_note += "\n\n💡 *All items are $5.99 each!*"
            elif data == "cat_faa_books":
                header_note += "\n\n💡 *All FAA manuals are $14.99 each!*"
            elif data == "cat_aviation_books":
                header_note += "\n\n💡 *Essential aviation reference books!*"

            sent = await context.bot.send_message(chat_id=chat_id, text=header_note, reply_markup=reply_markup, parse_mode="Markdown")
            user_cart_messages[user_id] = sent.message_id
        return

    elif data.startswith("show_book_"):
        book_id = data.replace("show_book_", "")
        book = BOOKS_DATABASE.get(book_id)

        if book:
            price_usd = book["price_usd"]
            stars_val = int(price_usd * STARS_PER_USD)
            
            if price_usd == 0.0:
                price_display = "🎁 FREE"
            else:
                price_display = f"💵 ${price_usd:.2f} | ⭐ {stars_val} Stars"

            caption_text = (
                f"{book['category_name']}\n\n"
                f"📖 *Title:*\n{book['title']}\n\n"
                f"📝 *Overview:*\n{book['details']}\n\n"
                f"💰 *Price:* {price_display}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Add to Shopping Cart", callback_data=f"buy_{book_id}")],
                [InlineKeyboardButton("⬅️ Back to Catalog", callback_data=book["category_id"])],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_categories")],
            ])
            
            try:
                sent_photo = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=book["cover_url"],
                    caption=caption_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                user_cart_messages[user_id] = sent_photo.message_id
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
                sent = await context.bot.send_message(
                    chat_id=chat_id,
                    text=caption_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
                user_cart_messages[user_id] = sent.message_id

    elif data.startswith("buy_"):
        book_id = data.replace("buy_", "")
        book = BOOKS_DATABASE.get(book_id)

        if user_id not in user_carts:
            user_carts[user_id] = []

        user_carts[user_id].append(book)
        update_cart_timestamp(user_id)
        
        if book.get("price_usd", 0.0) == 0.0:
            await query.answer(f"🎁 Added Free Book: {book['title'][:20]}...")
        else:
            await query.answer(f"🛒 Added: {book['title'][:20]}...")

        await show_or_update_active_cart(chat_id, user_id, context, query.message)

    elif data == "view_cart":
        await show_or_update_active_cart(chat_id, user_id, context, query.message)

    elif data == "checkout_telegram_stars":
        await start_telegram_stars_checkout(query, user_id, context)

def generate_cart_content(user_id):
    cart_items = user_carts.get(user_id, [])

    if not cart_items:
        text = "🛒 *Your shopping cart is empty.*\n\n📚 Browse our catalog to add items."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Return to Catalog", callback_data="back_to_categories")]])
        return text, keyboard

    text = "🛒 *YOUR SHOPPING CART:*\n\n"
    total_price_usd = 0.0
    keyboard_rows = []

    for idx, item in enumerate(cart_items):
        price_usd = item.get("price_usd", 12.99)
        if price_usd > 0.0:
            total_price_usd += price_usd
            stars_val = int(price_usd * STARS_PER_USD)
            text += f"{idx + 1}. 📖 {item['title']} - (💵 ${price_usd:.2f} / ⭐ {stars_val} Stars)\n"
        else:
            text += f"{idx + 1}. 📖 {item['title']} - (🎁 FREE)\n"
        
        keyboard_rows.append([
            InlineKeyboardButton(f"🗑️ Remove: {item['title'][:25]}...", callback_data=f"remove_cart_{idx}")
        ])

    discount_applied = False
    final_price_usd = total_price_usd
    if total_price_usd >= 50.0:
        final_price_usd = total_price_usd * 0.90
        discount_applied = True

    total_stars = int(final_price_usd * STARS_PER_USD)

    text += f"\n📊 *Subtotal:* ${total_price_usd:.2f}"
    if discount_applied:
        text += f"\n🔥 *10% Discount Applied!*"
        text += f"\n💳 *Final Total:* ${final_price_usd:.2f} (⭐ {total_stars} Stars)\n\n"
    else:
        text += f"\n💳 *Total:* ${final_price_usd:.2f} (⭐ {total_stars} Stars)\n\n"

    hours, minutes = get_cart_remaining_time(user_id)
    text += f"⏰ *Cart expires in:* {hours}h {minutes}m\n\n"

    if total_stars > 0:
        text += "💳 *Select payment method:*"
        keyboard_rows.append([InlineKeyboardButton(f"⭐ Pay {total_stars} Stars", callback_data="checkout_telegram_stars")])
        keyboard_rows.append([InlineKeyboardButton("💬 Confirm via WhatsApp", url=WHATSAPP_URL)])
    else:
        text += "🎁 *Claim your free materials:*"
        keyboard_rows.append([InlineKeyboardButton("📥 Claim Free Books", callback_data="checkout_telegram_stars")])

    keyboard_rows.append([InlineKeyboardButton("⬅️ Continue Shopping", callback_data="back_to_categories")])

    keyboard = InlineKeyboardMarkup(keyboard_rows)
    return text, keyboard

async def show_or_update_active_cart(chat_id, user_id, context, message_obj):
    text, keyboard = generate_cart_content(user_id)
    
    try:
        if hasattr(message_obj, 'photo') and message_obj.photo:
            await message_obj.delete()
        else:
            await message_obj.delete()
    except:
        pass
    
    sent_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    user_cart_messages[user_id] = sent_msg.message_id

# ---------------------------------------------------------
# Payment Handlers
# ---------------------------------------------------------
async def start_telegram_stars_checkout(query, user_id, context):
    cart_items = user_carts.get(user_id, [])
    if not cart_items:
        await query.message.reply_text("🛒 Your cart is empty!")
        return

    total_price_usd = 0.0
    for item in cart_items:
        total_price_usd += item.get("price_usd", 0.0)

    if total_price_usd >= 50.0:
        total_price_usd *= 0.90

    total_stars = int(total_price_usd * STARS_PER_USD)

    if total_stars == 0:
        try:
            order_data = {
                'user_id': user_id,
                'user_name': query.from_user.username or 'Unknown',
                'full_name': f"{query.from_user.first_name} {query.from_user.last_name or ''}".strip(),
                'items': cart_items,
                'total_usd': 0.0,
                'total_stars': 0,
                'charge_id': 'FREE_ITEMS',
                'date': datetime.now().strftime("%Y-%m-%d"),
                'time': datetime.now().strftime("%H:%M:%S"),
                'discount_applied': False,
                'total_items': len(cart_items),
                'free_items': len(cart_items),
                'paid_items': 0,
            }
            
            order_id = await send_admin_notification(context, order_data, is_free_items=True)
            
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")
            
            items_list = "\n".join([f"📚 {i+1}. {item['title']}" for i, item in enumerate(cart_items)])
            
            receipt_message = f"""
🎁 *FREE MATERIALS CLAIMED!*

━━━━━━━━━━━━━━━━━━━━━
📋 *RECEIPT DETAILS:*
━━━━━━━━━━━━━━━━━━━━━

🆔 Order ID: `{order_id}`
📅 Date: {date_str}
⏰ Time: {time_str} UTC

━━━━━━━━━━━━━━━━━━━━━
📚 *CLAIMED ITEMS:*
━━━━━━━━━━━━━━━━━━━━━
{items_list}

━━━━━━━━━━━━━━━━━━━━━
💰 *PAYMENT:*
━━━━━━━━━━━━━━━━━━━━━
💵 Total: $0.00 (FREE)
⭐ Stars: 0

━━━━━━━━━━━━━━━━━━━━━
⚠️ *IMPORTANT NOTE:*
━━━━━━━━━━━━━━━━━━━━━
📌 Please keep this receipt until all downloads are complete.

📧 Use this receipt as reference when contacting support for any issues.
━━━━━━━━━━━━━━━━━━━━━
"""
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_categories")],
            ])
            
            await query.message.reply_text(
                receipt_message,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
            for item in cart_items:
                delivery_text = (
                    f"📥 *{item['title']}*\n\n"
                    f"🔗 *Download:* {item['file_url']}"
                )
                await query.message.reply_text(delivery_text, parse_mode="Markdown")

            user_carts[user_id] = []
            user_cart_messages.pop(user_id, None)
            user_cart_timestamps.pop(user_id, None)
            cart_creation_notified.discard(user_id)
        except Exception as e:
            logger.error(f"Error delivering free items: {e}")
        return

    title = "ATPL Edge Store Order"
    description = f"Purchase of {len(cart_items)} aviation manual(s)."
    payload = f"atpl_edge_stars_order_{user_id}_{int(time.time())}"
    currency = "XTR"

    prices = [LabeledPrice("ATPL Edge Store Order", total_stars)]
    chat_id = query.message.chat_id

    try:
        await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency=currency,
            prices=prices,
            start_parameter="stars-payment",
        )
    except Exception as e:
        logger.error(f"Error sending invoice: {e}")
        await query.message.reply_text("❌ An error occurred. Please try again.", parse_mode="Markdown")

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_info = update.message.successful_payment
    
    if payment_info.currency == "XTR":
        payload = payment_info.invoice_payload

        if "donation" in payload:
            donation_notification = f"""
💰 *NEW DONATION!*

━━━━━━━━━━━━━━━━━━━━━
📋 *DONATION DETAILS:*
━━━━━━━━━━━━━━━━━━━━━

👤 User ID: `{user_id}`
📝 Username: @{update.effective_user.username or 'Unknown'}
👨‍✈️ Full Name: {update.effective_user.first_name} {update.effective_user.last_name or ''}
⭐ Stars: {payment_info.total_amount}
💵 USD Equivalent: ${payment_info.total_amount / STARS_PER_USD:.2f}
💳 Payment ID: `{payment_info.provider_payment_charge_id}`
📅 Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} UTC

━━━━━━━━━━━━━━━━━━━━━
"""
            
            # 1. إرسال الإشعار الكامل إلى القناة الخاصة
            channel_sent = False
            try:
                await context.bot.send_message(
                    chat_id=NOTIFICATION_CHANNEL_ID,
                    text=donation_notification,
                    parse_mode="Markdown"
                )
                logger.info(f"✅ Donation notification sent to private channel")
                channel_sent = True
            except Exception as e:
                logger.error(f"❌ Failed to send donation to channel: {e}")
            
            # 2. إرسال إشعار مختصر للأدمن الشخصي
            try:
                if channel_sent:
                    short_notification = (
                        f"💰 *New Donation Received!*\n\n"
                        f"⭐ Stars: {payment_info.total_amount}\n"
                        f"👤 User: @{update.effective_user.username or 'Unknown'}\n"
                        f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"📋 *Full details in private channel.*"
                    )
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=short_notification,
                        parse_mode="Markdown"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=donation_notification,
                        parse_mode="Markdown"
                    )
                logger.info(f"✅ Admin DM donation notification sent")
            except Exception as e:
                logger.error(f"❌ Failed to send admin DM donation notification: {e}")
            
            await update.message.reply_text(
                "⭐ *THANK YOU FOR YOUR SUPPORT!*\n\n"
                "💙 Your contribution helps us expand our library.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_categories")]
                ])
            )
            return

        cart_items = user_carts.get(user_id, [])
        if not cart_items:
            await update.message.reply_text("❌ No items in cart")
            return
        
        total_price_usd = sum(item.get("price_usd", 0.0) for item in cart_items)
        discount_applied = False
        if total_price_usd >= 50.0:
            total_price_usd *= 0.90
            discount_applied = True

        purchase_time = datetime.now()
        
        order_data = {
            'user_id': user_id,
            'user_name': update.effective_user.username or 'Unknown',
            'full_name': f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip(),
            'items': cart_items,
            'total_usd': total_price_usd,
            'total_stars': payment_info.total_amount,
            'charge_id': payment_info.provider_payment_charge_id,
            'date': purchase_time.strftime("%Y-%m-%d"),
            'time': purchase_time.strftime("%H:%M:%S"),
            'discount_applied': discount_applied,
            'total_items': len(cart_items),
            'free_items': sum(1 for item in cart_items if item.get('price_usd', 0) == 0),
            'paid_items': sum(1 for item in cart_items if item.get('price_usd', 0) > 0),
        }
        
        order_id = await send_admin_notification(context, order_data)
        
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        
        items_list = "\n".join([f"📚 {i+1}. {item['title']}" for i, item in enumerate(cart_items)])
        
        receipt_message = f"""
✅ *PAYMENT CONFIRMED!*

━━━━━━━━━━━━━━━━━━━━━
📋 *RECEIPT DETAILS:*
━━━━━━━━━━━━━━━━━━━━━

🆔 Order ID: `{order_id}`
📅 Date: {date_str}
⏰ Time: {time_str} UTC

━━━━━━━━━━━━━━━━━━━━━
📚 *PURCHASED ITEMS:*
━━━━━━━━━━━━━━━━━━━━━
{items_list}

━━━━━━━━━━━━━━━━━━━━━
💰 *PAYMENT:*
━━━━━━━━━━━━━━━━━━━━━
💵 Total (USD): ${total_price_usd:.2f}
⭐ Stars Paid: {payment_info.total_amount} Stars
"""

        if discount_applied:
            receipt_message += "\n🔥 *10% Discount Applied*\n"
        
        receipt_message += """
━━━━━━━━━━━━━━━━━━━━━
⚠️ *IMPORTANT NOTE:*
━━━━━━━━━━━━━━━━━━━━━
📌 Please keep this receipt until all downloads are complete.

📧 Use this receipt as reference when contacting support for any issues.

💬 Contact: Atpledgestore@Gmail.com
━━━━━━━━━━━━━━━━━━━━━
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_categories")],
            [InlineKeyboardButton("🛒 Continue Shopping", callback_data="back_to_categories")],
        ])
        
        await update.message.reply_text(
            receipt_message,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        
        for item in cart_items:
            delivery_text = (
                f"📥 *{item['title']}*\n\n"
                f"🔗 *Download:* {item['file_url']}"
            )
            await update.message.reply_text(delivery_text, parse_mode="Markdown")
        
        user_carts[user_id] = []
        user_cart_messages.pop(user_id, None)
        user_cart_timestamps.pop(user_id, None)
        cart_creation_notified.discard(user_id)

# ---------------------------------------------------------
# File ID Extractor
# ---------------------------------------------------------
async def handle_incoming_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        return

    message = update.message
    file_id = None
    file_type = "File/Media"

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "Photo"
    elif message.document:
        file_id = message.document.file_id
        file_type = "Document"
    elif message.video:
        file_id = message.video.file_id
        file_type = "Video"

    if file_id:
        response_text = (
            f"📸 *FILE ID EXTRACTED*\n\n"
            f"Type: `{file_type}`\n\n"
            f"🆔 *File ID:*\n`{file_id}`\n\n"
            f"*(Use this ID as cover_url or file_url in database)*"
        )
        await message.reply_text(response_text, parse_mode="Markdown")

# ---------------------------------------------------------
# Main Application
# ---------------------------------------------------------
if __name__ == "__main__":
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .request(request)
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("cart", cart_command))
    application.add_handler(CommandHandler("orders", orders_history_command))
    application.add_handler(CommandHandler("sales", sales_report_command))
    application.add_handler(CommandHandler("socials", socials_command))
    application.add_handler(CommandHandler("donate", donate_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    application.add_handler(CallbackQueryHandler(shop_callback))
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL | filters.VIDEO, handle_incoming_file))

    print("🤖 ATPL Edge Bot is running...")
    
    keep_alive()
    
    try:
        application.run_polling()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise
