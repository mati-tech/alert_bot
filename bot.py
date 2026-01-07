import os
import requests
import psycopg2
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)
from dotenv import load_dotenv

load_dotenv()

# ==================================================
# 🔐 CONFIG
# ==================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or DATABASE_URL")

# States for Conversation Handler
ASK_SYMBOL, ASK_PRICE = range(2)

# ==================================================
# 🗄️ DATABASE
# ==================================================
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True

def get_cursor():
    return conn.cursor()

def init_db():
    cur = get_cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            symbol TEXT NOT NULL,
            target_price NUMERIC NOT NULL,
            direction TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.close()

# ==================================================
# 📈 MEXC API
# ==================================================
MEXC_PRICE_URL = "https://api.mexc.com/api/v3/ticker/price"

def get_price(symbol: str) -> float:
    try:
        r = requests.get(MEXC_PRICE_URL, params={"symbol": symbol}, timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None

# ==================================================
# 🤖 BOT INTERFACE (MENUS & BUTTONS)
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the main menu."""
    keyboard = [
        [InlineKeyboardButton("🔔 Add New Alert", callback_data="add_start")],
        [InlineKeyboardButton("📋 My Alerts (Delete)", callback_data="list_alerts")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🤖 *MEXC Crypto Alert Bot*\nSelect an option below:"
    
    # Check if this is a callback (button click) or a command (/start)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --------------------------------------------------
# FLOW: ADD ALERT (Conversation)
# --------------------------------------------------
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: Ask for the symbol."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📝 *Enter the crypto symbol* (e.g., BTCUSDT):", 
        parse_mode="Markdown"
    )
    return ASK_SYMBOL

async def receive_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: Save symbol and ask for price."""
    symbol = update.message.text.upper().strip()
    
    # Verify symbol exists
    price = get_price(symbol)
    if price is None:
        await update.message.reply_text("❌ Invalid symbol. Please try again (e.g., ETHUSDT).")
        return ASK_SYMBOL

    context.user_data['symbol'] = symbol
    context.user_data['current_price'] = price
    
    await update.message.reply_text(
        f"✅ Found **{symbol}** at **${price}**.\n\n"
        "🔢 Now enter your **Target Price**:",
        parse_mode="Markdown"
    )
    return ASK_PRICE

async def receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 3: Save alert to DB."""
    try:
        target = float(update.message.text.strip())
        symbol = context.user_data['symbol']
        current_price = context.user_data['current_price']
        
        direction = "up" if target > current_price else "down"

        # Save to DB
        cur = get_cursor()
        cur.execute(
            "INSERT INTO alerts (chat_id, symbol, target_price, direction) VALUES (%s, %s, %s, %s)",
            (update.effective_chat.id, symbol, target, direction)
        )
        cur.close()

        # Success message with "Back to Menu" button
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"🎯 **Alert Set!**\n\nSymbol: {symbol}\nTarget: {target}\nCondition: Price goes {direction}",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g., 0.50 or 42000).")
        return ASK_PRICE

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the conversation."""
    await start(update, context)
    return ConversationHandler.END

# --------------------------------------------------
# FLOW: LIST & DELETE
# --------------------------------------------------
async def list_alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    cur = get_cursor()
    cur.execute("SELECT id, symbol, target_price, direction FROM alerts WHERE chat_id = %s", (update.effective_chat.id,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        await query.edit_message_text("📭 You have no active alerts.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Build a list of buttons
    keyboard = []
    for r in rows:
        alert_id, sym, price, direction = r
        arrow = "📈" if direction == "up" else "📉"
        # Button Text: "BTC 42000 📈" | Button Data: "del_123"
        btn_text = f"{sym} {price} {arrow}"
        # Using a specific prefix 'del_' to identify delete actions
        keyboard.append([
            InlineKeyboardButton(text=btn_text, callback_data="noop"), # Just text
            InlineKeyboardButton(text="❌ Delete", callback_data=f"del_{alert_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("👇 **Your Active Alerts** (Tap ❌ to delete):", reply_markup=reply_markup, parse_mode="Markdown")

async def delete_alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Deleting...")
    
    # Extract ID from "del_123"
    alert_id = int(query.data.split("_")[1])
    
    cur = get_cursor()
    cur.execute("DELETE FROM alerts WHERE id = %s AND chat_id = %s", (alert_id, update.effective_chat.id))
    cur.close()
    
    # Refresh the list
    await list_alerts_handler(update, context)

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Does nothing when clicking the info part of the button."""
    await update.callback_query.answer()

# ==================================================
# 🔄 BACKGROUND JOB
# ==================================================
async def check_prices(bot):
    try:
        cur = get_cursor()
        cur.execute("SELECT id, chat_id, symbol, target_price, direction FROM alerts")
        alerts = cur.fetchall()
        cur.close()

        if not alerts: return

        for alert_id, chat_id, symbol, target, direction in alerts:
            price = get_price(symbol)
            if price is None: continue

            hit_up = direction == "up" and price >= target
            hit_down = direction == "down" and price <= target

            if hit_up or hit_down:
                await bot.send_message(
                    chat_id, 
                    f"🚨 **PRICE HIT!**\n\nSymbol: {symbol}\nTarget: {target}\nCurrent: {price}",
                    parse_mode="Markdown"
                )
                cur2 = get_cursor()
                cur2.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
                cur2.close()
    except Exception as e:
        print(f"Check Error: {e}")

async def job_scheduler(context: ContextTypes.DEFAULT_TYPE):
    await check_prices(context.bot)

# ==================================================
# 🏗️ FASTAPI & LIFESPAN
# ==================================================
ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()

# 1. Main Menu & Navigation Handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
ptb_app.add_handler(CallbackQueryHandler(list_alerts_handler, pattern="^list_alerts$"))
ptb_app.add_handler(CallbackQueryHandler(delete_alert_handler, pattern="^del_"))
ptb_app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

# 2. Add Alert Conversation Handler
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(add_start, pattern="^add_start$")],
    states={
        ASK_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_symbol)],
        ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price)],
    },
    fallbacks=[CommandHandler("cancel", cancel_add)]
)
ptb_app.add_handler(conv_handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting Bot System...")
    init_db()
    await ptb_app.initialize()
    await ptb_app.start()
    ptb_app.job_queue.run_repeating(job_scheduler, interval=20, first=5)
    await ptb_app.updater.start_polling()
    
    yield
    
    print("🛑 Stopping System...")
    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()

api = FastAPI(lifespan=lifespan)

@api.get("/")
def root():
    return {"status": "running"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # Important: Ensure reload is FALSE to avoid conflict errors
    uvicorn.run(api, host="0.0.0.0", port=port)