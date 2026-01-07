import os
import time
import requests
import psycopg2
# from dotenv import load_dotenv
# load_dotenv()

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Job

# ==================================================
# 🔐 ENVIRONMENT VARIABLES (SET ON RENDER)
# ==================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")



if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or DATABASE_URL")

# ==================================================
# 📊 MEXC API
# ==================================================
MEXC_PRICE_URL = "https://api.mexc.com/api/v3/ticker/price"

# ==================================================
# 🗄 DATABASE CONNECTION
# ==================================================
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True

# Add this function outside main
async def job_wrapper(context):
    await price_checker(context.bot)

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
# 📈 PRICE FETCH
# ==================================================
def get_price(symbol: str) -> float:
    r = requests.get(MEXC_PRICE_URL, params={"symbol": symbol}, timeout=10)
    r.raise_for_status()
    return float(r.json()["price"])

# ==================================================
# 🤖 BOT COMMANDS
# ==================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            """
            INSERT INTO alerts (chat_id, symbol, target_price, direction)
            VALUES (%s, %s, %s, %s)
            """,
            (update.effective_chat.id, symbol, target, direction)
        )
        cur.close()

        await update.message.reply_text(
            f"✅ Alert set!\n\n"
            f"Symbol: {symbol}\n"
            f"Target: {target}\n"
            f"Direction: {direction}"
        )

    except Exception:
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
# 🔁 PRICE MONITOR LOOP
# ==================================================
# async def price_checker(app):
#     while True:
#         cur = get_cursor()
#         cur.execute("SELECT id, chat_id, symbol, target_price, direction FROM alerts")
#         alerts = cur.fetchall()
#         cur.close()

#         for alert_id, chat_id, symbol, target, direction in alerts:
#             try:
#                 price = get_price(symbol)

#                 hit_up = direction == "up" and price >= target
#                 hit_down = direction == "down" and price <= target

#                 if hit_up or hit_down:
#                     await app.bot.send_message(
#                         chat_id,
#                         f"🚨 *PRICE ALERT*\n\n"
#                         f"{symbol}\n"
#                         f"Target: {target}\n"
#                         f"Current: {price}",
#                         parse_mode="Markdown"
#                     )

#                     cur2 = get_cursor()
#                     cur2.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
#                     cur2.close()

#             except Exception:
#                 pass

#         time.sleep(10)

async def price_checker(bot):
    cur = get_cursor()
    cur.execute("SELECT id, chat_id, symbol, target_price, direction FROM alerts")
    alerts = cur.fetchall()
    cur.close()

    for alert_id, chat_id, symbol, target, direction in alerts:
        try:
            price = get_price(symbol)

            hit_up = direction == "up" and price >= target
            hit_down = direction == "down" and price <= target

            if hit_up or hit_down:
                await bot.send_message(
                    chat_id,
                    f"🚨 *PRICE ALERT*\n\n"
                    f"{symbol}\n"
                    f"Target: {target}\n"
                    f"Current: {price}",
                    parse_mode="Markdown"
                )

                cur2 = get_cursor()
                cur2.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
                cur2.close()
        except:
            pass



# ==================================================
# 🚀 MAIN
# ==================================================
def main():
    init_db()  # AUTO-CREATE TABLES

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_alert))
    app.add_handler(CommandHandler("list", list_alerts))
    app.add_handler(CommandHandler("delete", delete_alert))

    # app.job_queue.run_once(lambda ctx: price_checker(app), 1)
    app.job_queue.run_repeating(job_wrapper, interval=10, first=0)
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
