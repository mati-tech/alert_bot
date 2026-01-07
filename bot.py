import os
import requests
import psycopg2
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
# from dotenv import load_dotenv

# load_dotenv()

# ==================================================
# 🔐 ENVIRONMENT VARIABLES
# ==================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or DATABASE_URL")

# ==================================================
# Database Connection (Synchronous)
# ==================================================
# Note: For high-traffic production, consider using 'asyncpg' instead of 'psycopg2'
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
# MEXC API
# ==================================================
MEXC_PRICE_URL = "https://api.mexc.com/api/v3/ticker/price"

def get_price(symbol: str) -> float:
    # Note: 'requests' is blocking. In heavy load, use 'aiohttp'.
    r = requests.get(MEXC_PRICE_URL, params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

# ==================================================
# Telegram Logic
# ==================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *MEXC Crypto Alert Bot*\n\n"
        "Commands:\n"
        "/set BTCUSDT 42000\n"
        "/list\n"
        "/delete ID\n",
        parse_mode="Markdown"
    )

async def set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        symbol = context.args[0].upper()
        target = float(context.args[1])

        current_price = get_price(symbol)
        direction = "up" if target > current_price else "down"

        cur = get_cursor()
        cur.execute(
            "INSERT INTO alerts (chat_id, symbol, target_price, direction) VALUES (%s, %s, %s, %s)",
            (update.effective_chat.id, symbol, target, direction)
        )
        cur.close()

        await update.message.reply_text(
            f"✅ Alert set!\n\nSymbol: {symbol}\nTarget: {target}\nDirection: {direction}"
        )
    except Exception as e:
        print(f"Error setting alert: {e}")
        await update.message.reply_text("❌ Usage: /set BTCUSDT 42000")

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur = get_cursor()
    cur.execute(
        "SELECT id, symbol, target_price, direction FROM alerts WHERE chat_id = %s",
        (update.effective_chat.id,)
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        await update.message.reply_text("No active alerts.")
        return

    msg = "📌 *Your alerts:*\n"
    for r in rows:
        msg += f"ID `{r[0]}` → {r[1]} @ {r[2]} ({r[3]})\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def delete_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        alert_id = int(context.args[0])
        cur = get_cursor()
        cur.execute(
            "DELETE FROM alerts WHERE id = %s AND chat_id = %s",
            (alert_id, update.effective_chat.id)
        )
        cur.close()

        await update.message.reply_text("🗑 Alert deleted.")
    except Exception:
        await update.message.reply_text("❌ Usage: /delete ID")

# ==================================================
# Background Job Logic
# ==================================================
async def price_checker(bot):
    """Checks prices and triggers alerts. Accepts the raw bot instance."""
    try:
        cur = get_cursor()
        cur.execute("SELECT id, chat_id, symbol, target_price, direction FROM alerts")
        alerts = cur.fetchall()
        cur.close()

        if not alerts:
            return

        for alert_id, chat_id, symbol, target, direction in alerts:
            try:
                price = get_price(symbol)
                hit_up = direction == "up" and price >= target
                hit_down = direction == "down" and price <= target

                if hit_up or hit_down:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🚨 *PRICE ALERT*\n\n{symbol}\nTarget: {target}\nCurrent: {price}",
                        parse_mode="Markdown"
                    )

                    cur2 = get_cursor()
                    cur2.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
                    cur2.close()
            except Exception as e:
                print(f"Error checking {symbol}: {e}")
                
    except Exception as e:
        print(f"Database error in checker: {e}")

async def job_wrapper(context: ContextTypes.DEFAULT_TYPE):
    # Pass the bot instance from context to the checker
    await price_checker(context.bot)

# ==================================================
# Lifecycle & FastAPI
# ==================================================

# 1. Create the Bot Application (but don't run it yet)
ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()
ptb_app.add_handler(CommandHandler("start", start_command))
ptb_app.add_handler(CommandHandler("set", set_alert))
ptb_app.add_handler(CommandHandler("list", list_alerts))
ptb_app.add_handler(CommandHandler("delete", delete_alert))

# 2. Define Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("🚀 Starting Bot...")
    init_db()
    
    # Manually initialize the bot
    await ptb_app.initialize()
    await ptb_app.start()
    
    # Add the repeating job to the bot's job queue
    ptb_app.job_queue.run_repeating(job_wrapper, interval=10, first=1)
    
    # Start polling updates (non-blocking method)
    await ptb_app.updater.start_polling()
    
    yield  # FastAPI runs here
    
    # --- SHUTDOWN ---
    print("🛑 Stopping Bot...")
    await ptb_app.updater.stop()
    await ptb_app.stop()
    await ptb_app.shutdown()

# 3. Initialize FastAPI with lifespan
api = FastAPI(lifespan=lifespan)

@api.get("/")
def root():
    return {"status": "Bot and API are running together!"}

# ==================================================
# Entry point
# ==================================================
if __name__ == "__main__":
    # Uvicorn now drives the main loop. 
    # The bot runs as a background task via the lifespan event.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(api, host="0.0.0.0", port=port)