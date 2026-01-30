# import os
# import requests
# import psycopg2
# import asyncio
# from contextlib import asynccontextmanager
# from fastapi import FastAPI
# import uvicorn

# from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.ext import (
#     ApplicationBuilder,
#     CommandHandler,
#     ContextTypes,
#     CallbackQueryHandler,
#     ConversationHandler,
#     MessageHandler,
#     filters
# )
# from dotenv import load_dotenv

# load_dotenv()

# # ==================================================
# # 🔐 CONFIG
# # ==================================================
# BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# DATABASE_URL = os.getenv("DATABASE_URL")

# if not BOT_TOKEN or not DATABASE_URL:
#     raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or DATABASE_URL")

# # States for Conversation Handler
# ASK_SYMBOL, ASK_PRICE = range(2)

# # ==================================================
# # 🗄️ DATABASE
# # ==================================================
# conn = psycopg2.connect(DATABASE_URL)
# conn.autocommit = True

# def get_cursor():
#     return conn.cursor()

# def init_db():
#     cur = get_cursor()
#     cur.execute("""
#         CREATE TABLE IF NOT EXISTS alerts (
#             id SERIAL PRIMARY KEY,
#             chat_id BIGINT NOT NULL,
#             symbol TEXT NOT NULL,
#             target_price NUMERIC NOT NULL,
#             direction TEXT NOT NULL,
#             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#         );
#     """)
#     cur.close()

# # ==================================================
# # 📈 MEXC API
# # ==================================================
# MEXC_PRICE_URL = "https://api.mexc.com/api/v3/ticker/price"

# def get_price(symbol: str) -> float:
#     try:
#         r = requests.get(MEXC_PRICE_URL, params={"symbol": symbol}, timeout=5)
#         r.raise_for_status()
#         return float(r.json()["price"])
#     except Exception:
#         return None

# # ==================================================
# # 🤖 BOT INTERFACE (MENUS & BUTTONS)
# # ==================================================

# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Sends the main menu."""
#     keyboard = [
#         [InlineKeyboardButton("🔔 Add New Alert", callback_data="add_start")],
#         [InlineKeyboardButton("📋 My Alerts (Delete)", callback_data="list_alerts")],
#     ]
#     reply_markup = InlineKeyboardMarkup(keyboard)
    
#     text = "🤖 Crypto Alert Bot*\nSelect an option below:"
    
#     # Check if this is a callback (button click) or a command (/start)
#     if update.callback_query:
#         await update.callback_query.answer()
#         await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
#     else:
#         await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# # --------------------------------------------------
# # FLOW: ADD ALERT (Conversation)
# # --------------------------------------------------
# async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Step 1: Ask for the symbol."""
#     query = update.callback_query
#     await query.answer()
#     await query.edit_message_text(
#         "📝 *Enter the crypto symbol* (e.g., BTCUSDT):", 
#         parse_mode="Markdown"
#     )
#     return ASK_SYMBOL

# async def receive_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Step 2: Save symbol and ask for price."""
#     symbol = update.message.text.upper().strip()
    
#     # Verify symbol exists
#     price = get_price(symbol)
#     if price is None:
#         await update.message.reply_text("❌ Invalid symbol. Please try again (e.g., ETHUSDT).")
#         return ASK_SYMBOL

#     context.user_data['symbol'] = symbol
#     context.user_data['current_price'] = price
    
#     await update.message.reply_text(
#         f"✅ Found **{symbol}** at **${price}**.\n\n"
#         "🔢 Now enter your **Target Price**:",
#         parse_mode="Markdown"
#     )
#     return ASK_PRICE

# async def receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Step 3: Save alert to DB."""
#     try:
#         target = float(update.message.text.strip())
#         symbol = context.user_data['symbol']
#         current_price = context.user_data['current_price']
        
#         direction = "up" if target > current_price else "down"

#         # Save to DB
#         cur = get_cursor()
#         cur.execute(
#             "INSERT INTO alerts (chat_id, symbol, target_price, direction) VALUES (%s, %s, %s, %s)",
#             (update.effective_chat.id, symbol, target, direction)
#         )
#         cur.close()

#         # Success message with "Back to Menu" button
#         keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
#         reply_markup = InlineKeyboardMarkup(keyboard)

#         await update.message.reply_text(
#             f"🎯 **Alert Set!**\n\nSymbol: {symbol}\nTarget: {target}\nCondition: Price goes {direction}",
#             parse_mode="Markdown",
#             reply_markup=reply_markup
#         )
#         return ConversationHandler.END
        
#     except ValueError:
#         await update.message.reply_text("❌ Please enter a valid number (e.g., 0.50 or 42000).")
#         return ASK_PRICE

# async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Cancels the conversation."""
#     await start(update, context)
#     return ConversationHandler.END

# # --------------------------------------------------
# # FLOW: LIST & DELETE
# # --------------------------------------------------
# async def list_alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()

#     cur = get_cursor()
#     cur.execute("SELECT id, symbol, target_price, direction FROM alerts WHERE chat_id = %s", (update.effective_chat.id,))
#     rows = cur.fetchall()
#     cur.close()

#     if not rows:
#         keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
#         await query.edit_message_text("📭 You have no active alerts.", reply_markup=InlineKeyboardMarkup(keyboard))
#         return

#     # Build a list of buttons
#     keyboard = []
#     for r in rows:
#         alert_id, sym, price, direction = r
#         arrow = "📈" if direction == "up" else "📉"
#         # Button Text: "BTC 42000 📈" | Button Data: "del_123"
#         btn_text = f"{sym} {price} {arrow}"
#         # Using a specific prefix 'del_' to identify delete actions
#         keyboard.append([
#             InlineKeyboardButton(text=btn_text, callback_data="noop"), # Just text
#             InlineKeyboardButton(text="❌ Delete", callback_data=f"del_{alert_id}")
#         ])
    
#     keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
#     reply_markup = InlineKeyboardMarkup(keyboard)
    
#     await query.edit_message_text("👇 **Your Active Alerts** (Tap ❌ to delete):", reply_markup=reply_markup, parse_mode="Markdown")

# async def delete_alert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer("Deleting...")
    
#     # Extract ID from "del_123"
#     alert_id = int(query.data.split("_")[1])
    
#     cur = get_cursor()
#     cur.execute("DELETE FROM alerts WHERE id = %s AND chat_id = %s", (alert_id, update.effective_chat.id))
#     cur.close()
    
#     # Refresh the list
#     await list_alerts_handler(update, context)

# async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Does nothing when clicking the info part of the button."""
#     await update.callback_query.answer()

# # ==================================================
# # 🔄 BACKGROUND JOB
# # ==================================================
# async def check_prices(bot):
#     try:
#         cur = get_cursor()
#         cur.execute("SELECT id, chat_id, symbol, target_price, direction FROM alerts")
#         alerts = cur.fetchall()
#         cur.close()

#         if not alerts: return

#         for alert_id, chat_id, symbol, target, direction in alerts:
#             price = get_price(symbol)
#             if price is None: continue

#             hit_up = direction == "up" and price >= target
#             hit_down = direction == "down" and price <= target

#             if hit_up or hit_down:
#                 await bot.send_message(
#                     chat_id, 
#                     f"🚨 **PRICE HIT!**\n\nSymbol: {symbol}\nTarget: {target}\nCurrent: {price}",
#                     parse_mode="Markdown"
#                 )
#                 cur2 = get_cursor()
#                 cur2.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
#                 cur2.close()
#     except Exception as e:
#         print(f"Check Error: {e}")

# async def job_scheduler(context: ContextTypes.DEFAULT_TYPE):
#     await check_prices(context.bot)

# # ==================================================
# # 🏗️ FASTAPI & LIFESPAN
# # ==================================================
# ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()

# # 1. Main Menu & Navigation Handlers
# ptb_app.add_handler(CommandHandler("start", start))
# ptb_app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
# ptb_app.add_handler(CallbackQueryHandler(list_alerts_handler, pattern="^list_alerts$"))
# ptb_app.add_handler(CallbackQueryHandler(delete_alert_handler, pattern="^del_"))
# ptb_app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

# # 2. Add Alert Conversation Handler
# conv_handler = ConversationHandler(
#     entry_points=[CallbackQueryHandler(add_start, pattern="^add_start$")],
#     states={
#         ASK_SYMBOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_symbol)],
#         ASK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price)],
#     },
#     fallbacks=[CommandHandler("cancel", cancel_add)]
# )
# ptb_app.add_handler(conv_handler)

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     print("🚀 Starting Bot System...")
#     init_db()
#     await ptb_app.initialize()
#     await ptb_app.start()
#     ptb_app.job_queue.run_repeating(job_scheduler, interval=20, first=5)
#     await ptb_app.updater.start_polling()
    
#     yield
    
#     print("🛑 Stopping System...")
#     await ptb_app.updater.stop()
#     await ptb_app.stop()
#     await ptb_app.shutdown()

# api = FastAPI(lifespan=lifespan)

# # @api.get("/")
# # def root():
# #     return {"status": "running"}

# # @api.head("/")
# # async def status_head():
# #     return Response(status_code=200)

# # from fastapi import FastAPI, Response

# api = FastAPI(lifespan=lifespan)

# @api.api_route("/", methods=["GET", "HEAD"])
# async def root():
#     return {"status": "running"}


# if __name__ == "__main__":
#     port = int(os.environ.get("PORT", 8000))
#     # Important: Ensure reload is FALSE to avoid conflict errors
#     uvicorn.run(api, host="0.0.0.0", port=port)



import os
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import List, Dict, Optional

import aiohttp
from aiohttp import ClientSession, ClientTimeout
import asyncpg
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
from telegram.error import BadRequest
from dotenv import load_dotenv

load_dotenv()

# ==================================================
# 🔧 CONFIGURATION
# ==================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ALERTS_PER_PAGE = 5  # Max alerts to show per message
API_TIMEOUT = 10

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or DATABASE_URL")

# States for Conversation Handler
ASK_SYMBOL, ASK_PRICE = range(2)

# ==================================================
# 📊 LOGGING SETUP
# ==================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================================================
# 🗄️ DATABASE SETUP (Async)
# ==================================================
pool: Optional[asyncpg.Pool] = None

async def init_db():
    """Initialize database connection pool and create tables"""
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
        command_timeout=60
    )
    
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                symbol TEXT NOT NULL,
                target_price NUMERIC NOT NULL,
                direction TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            -- Add indexes for performance
            CREATE INDEX IF NOT EXISTS idx_alerts_chat_id ON alerts(chat_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
            CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
        """)
    logger.info("Database initialized")

async def get_connection():
    """Get a database connection from pool"""
    return await pool.acquire()

# ==================================================
# 📈 API CLIENT
# ==================================================
class MEXCClient:
    """Async client for MEXC API"""
    
    BASE_URL = "https://api.mexc.com/api/v3"
    
    def __init__(self):
        self.session: Optional[ClientSession] = None
        
    async def __aenter__(self):
        self.session = ClientSession(
            timeout=ClientTimeout(total=API_TIMEOUT)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        try:
            url = f"{self.BASE_URL}/ticker/price"
            params = {"symbol": symbol.upper()}
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return float(data.get("price", 0))
                else:
                    logger.error(f"API error for {symbol}: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            return None
    
    async def get_prices_batch(self, symbols: List[str]) -> Dict[str, float]:
        """Get prices for multiple symbols"""
        if not symbols:
            return {}
        
        results = {}
        tasks = []
        
        for symbol in symbols:
            task = self.get_price(symbol)
            tasks.append((symbol, task))
        
        for symbol, task in tasks:
            try:
                price = await task
                if price is not None:
                    results[symbol] = price
            except Exception as e:
                logger.error(f"Failed to get price for {symbol}: {e}")
        
        return results

# ==================================================
# 🤖 BOT HANDLERS
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu handler"""
    try:
        keyboard = [
            [InlineKeyboardButton("🔔 Add Alert", callback_data="add_start")],
            [InlineKeyboardButton("📋 My Alerts", callback_data="list_alerts_0")],
            [InlineKeyboardButton("🗑️ Clear All Alerts", callback_data="clear_all")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🤖 *Crypto Alert Bot*\n\n"
            "Track cryptocurrency prices and get notified when they hit your targets.\n\n"
            "• Add alerts for any trading pair (e.g., BTCUSDT)\n"
            "• Get instant notifications\n"
            "• Manage your active alerts"
        )
        
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode="Markdown"
            )
    except BadRequest as e:
        logger.error(f"Markdown error in start: {e}")
        # Fallback without markdown
        text = "🤖 Crypto Alert Bot\n\nTrack cryptocurrency prices and get notified when they hit your targets."
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        if update.message:
            await update.message.reply_text("❌ An error occurred. Please try /start again.")

# ==================================================
# 🔔 ADD ALERT FLOW
# ==================================================

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the add alert conversation"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Clear previous conversation data
        context.user_data.clear()
        
        await query.edit_message_text(
            "📝 *Enter crypto symbol*\n\nExample: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`",
            parse_mode="Markdown"
        )
        return ASK_SYMBOL
    except Exception as e:
        logger.error(f"Error in add_start: {e}")
        return ConversationHandler.END

async def receive_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and validate symbol"""
    symbol = update.message.text.upper().strip()
    
    # Basic validation
    if not symbol or len(symbol) < 4:
        await update.message.reply_text(
            "❌ Invalid symbol. Please enter a valid trading pair (e.g., BTCUSDT)."
        )
        return ASK_SYMBOL
    
    # Check symbol exists
    async with MEXCClient() as client:
        price = await client.get_price(symbol)
    
    if price is None:
        await update.message.reply_text(
            f"❌ Could not find symbol *{symbol}*.\n\n"
            "Please check:\n"
            "• Symbol format (e.g., BTCUSDT not BTC-USD)\n"
            "• Trading pair exists on MEXC\n"
            "• Try again with correct symbol:",
            parse_mode="Markdown"
        )
        return ASK_SYMBOL
    
    context.user_data['symbol'] = symbol
    context.user_data['current_price'] = price
    
    # Show price info
    direction_keyboard = [
        [
            InlineKeyboardButton("📈 Above Price", callback_data="direction_up"),
            InlineKeyboardButton("📉 Below Price", callback_data="direction_down")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(direction_keyboard)
    
    await update.message.reply_text(
        f"✅ *{symbol}*: ${price:,.4f}\n\n"
        "Choose alert condition:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return ASK_PRICE

async def set_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set alert direction from button"""
    query = update.callback_query
    await query.answer()
    
    direction = "up" if query.data == "direction_up" else "down"
    context.user_data['direction'] = direction
    
    current_price = context.user_data.get('current_price', 0)
    
    if direction == "up":
        prompt = f"📈 Set *above* price (current: ${current_price:,.4f}):"
    else:
        prompt = f"📉 Set *below* price (current: ${current_price:,.4f}):"
    
    await query.edit_message_text(
        prompt,
        parse_mode="Markdown"
    )

async def receive_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive target price and save alert"""
    try:
        # Parse price
        price_text = update.message.text.strip()
        try:
            target_price = float(price_text.replace(',', ''))
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid price. Please enter a number (e.g., 50000 or 0.005)."
            )
            return ASK_PRICE
        
        # Get data from context
        symbol = context.user_data.get('symbol')
        current_price = context.user_data.get('current_price')
        direction = context.user_data.get('direction')
        
        if not all([symbol, current_price, direction]):
            await update.message.reply_text("❌ Session expired. Please start over with /start")
            return ConversationHandler.END
        
        # Validate price logic
        if direction == "up" and target_price <= current_price:
            await update.message.reply_text(
                f"⚠️ For 'Above' alerts, target must be *higher* than current price (${current_price:,.4f}).\n"
                "Please enter a higher price:",
                parse_mode="Markdown"
            )
            return ASK_PRICE
            
        if direction == "down" and target_price >= current_price:
            await update.message.reply_text(
                f"⚠️ For 'Below' alerts, target must be *lower* than current price (${current_price:,.4f}).\n"
                "Please enter a lower price:",
                parse_mode="Markdown"
            )
            return ASK_PRICE
        
        # Save to database
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO alerts (chat_id, symbol, target_price, direction)
                VALUES ($1, $2, $3, $4)
            """, update.effective_chat.id, symbol, target_price, direction)
        
        # Success message
        keyboard = [
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
            [InlineKeyboardButton("➕ Add Another", callback_data="add_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        direction_text = "above" if direction == "up" else "below"
        await update.message.reply_text(
            f"✅ *Alert Set Successfully!*\n\n"
            f"• Symbol: `{symbol}`\n"
            f"• Target: ${target_price:,.4f}\n"
            f"• Condition: Price goes *{direction_text}* target\n"
            f"• Current: ${current_price:,.4f}\n\n"
            f"_You'll be notified when the price is reached._",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in receive_price: {e}")
        await update.message.reply_text("❌ Failed to save alert. Please try again.")
        return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await start(update, context)
    return ConversationHandler.END

# ==================================================
# 📋 ALERTS MANAGEMENT (Pagination)
# ==================================================

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's alerts with pagination"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Parse page number
        data_parts = query.data.split('_')
        page = int(data_parts[-1]) if len(data_parts) > 2 else 0
        
        # Get alerts for this user
        async with pool.acquire() as conn:
            # Get total count
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM alerts WHERE chat_id = $1",
                query.from_user.id
            )
            
            if total == 0:
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
                await query.edit_message_text(
                    "📭 You have no active alerts.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # Calculate pagination
            total_pages = (total + ALERTS_PER_PAGE - 1) // ALERTS_PER_PAGE
            if page >= total_pages:
                page = total_pages - 1
            
            offset = page * ALERTS_PER_PAGE
            
            # Get alerts for this page
            alerts = await conn.fetch("""
                SELECT id, symbol, target_price, direction, created_at
                FROM alerts 
                WHERE chat_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, query.from_user.id, ALERTS_PER_PAGE, offset)
        
        # Build message
        message_lines = [f"📋 *Your Alerts ({total} total)*\n"]
        
        for i, alert in enumerate(alerts, 1):
            index = offset + i
            direction_icon = "📈" if alert['direction'] == 'up' else "📉"
            direction_text = "above" if alert['direction'] == 'up' else "below"
            
            message_lines.append(
                f"{index}. `{alert['symbol']}` - ${alert['target_price']:.4f} {direction_icon}\n"
                f"   Alert when price goes *{direction_text}* this level"
            )
        
        # Build keyboard
        keyboard = []
        
        # Add delete buttons for each alert on this page
        for alert in alerts:
            delete_btn = InlineKeyboardButton(
                f"❌ {alert['symbol']}",
                callback_data=f"delete_{alert['id']}_{page}"
            )
            keyboard.append([delete_btn])
        
        # Add navigation buttons if needed
        nav_buttons = []
        
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("◀️ Previous", callback_data=f"list_alerts_{page-1}")
            )
        
        nav_buttons.append(
            InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop")
        )
        
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("Next ▶️", callback_data=f"list_alerts_{page+1}")
            )
        
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        # Add back button
        keyboard.append([
            InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "\n".join(message_lines),
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        logger.error(f"Error in list_alerts: {e}")
        await query.edit_message_text(
            "❌ Error loading alerts. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )

async def delete_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a specific alert"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Parse alert ID and page from callback data
        data_parts = query.data.split('_')
        if len(data_parts) < 3:
            await query.edit_message_text("❌ Invalid delete request.")
            return
            
        alert_id = int(data_parts[1])
        page = int(data_parts[2])
        
        # Delete from database
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM alerts WHERE id = $1 AND chat_id = $2",
                alert_id, query.from_user.id
            )
        
        if result == "DELETE 1":
            # Show success and go back to same page
            await query.edit_message_text(
                "✅ Alert deleted successfully.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Back to Alerts", callback_data=f"list_alerts_{page}")],
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
                ])
            )
        else:
            await query.edit_message_text(
                "⚠️ Alert not found or already deleted.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Back to Alerts", callback_data=f"list_alerts_{page}")],
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
                ])
            )
            
    except Exception as e:
        logger.error(f"Error in delete_alert: {e}")
        await query.edit_message_text(
            "❌ Failed to delete alert. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )

async def clear_all_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear all alerts with confirmation"""
    query = update.callback_query
    await query.answer()
    
    # Confirmation keyboard
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete All", callback_data="confirm_clear"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Get count
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM alerts WHERE chat_id = $1",
            query.from_user.id
        )
    
    await query.edit_message_text(
        f"⚠️ *Confirm Delete All*\n\n"
        f"You have {count} active alerts.\n"
        f"This action cannot be undone!\n\n"
        f"Are you sure you want to delete ALL alerts?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def confirm_clear_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and clear all alerts"""
    query = update.callback_query
    await query.answer()
    
    try:
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM alerts WHERE chat_id = $1",
                query.from_user.id
            )
            
            if count > 0:
                await conn.execute(
                    "DELETE FROM alerts WHERE chat_id = $1",
                    query.from_user.id
                )
        
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
        await query.edit_message_text(
            f"✅ Successfully deleted {count} alerts.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in confirm_clear_all: {e}")
        await query.edit_message_text(
            "❌ Failed to delete alerts. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle no-operation buttons (like page numbers)"""
    await update.callback_query.answer()

# ==================================================
# 🔄 BACKGROUND PRICE CHECKER
# ==================================================

async def check_prices(bot):
    """Background job to check prices and trigger alerts"""
    try:
        # Get all unique symbols from alerts
        async with pool.acquire() as conn:
            symbols_data = await conn.fetch(
                "SELECT DISTINCT symbol FROM alerts"
            )
        
        if not symbols_data:
            return
        
        symbols = [row['symbol'] for row in symbols_data]
        
        # Get current prices for all symbols
        async with MEXCClient() as client:
            prices = await client.get_prices_batch(symbols)
        
        if not prices:
            return
        
        # Check each symbol's alerts
        for symbol, current_price in prices.items():
            # Get all alerts for this symbol
            async with pool.acquire() as conn:
                alerts = await conn.fetch("""
                    SELECT id, chat_id, target_price, direction
                    FROM alerts 
                    WHERE symbol = $1
                """, symbol)
            
            for alert in alerts:
                alert_id = alert['id']
                chat_id = alert['chat_id']
                target = alert['target_price']
                direction = alert['direction']
                
                triggered = False
                if direction == 'up' and current_price >= target:
                    triggered = True
                    condition = "above"
                elif direction == 'down' and current_price <= target:
                    triggered = True
                    condition = "below"
                
                if triggered:
                    try:
                        # Send notification
                        await bot.send_message(
                            chat_id=chat_id,
                            text=(
                                f"🚨 *PRICE ALERT TRIGGERED!*\n\n"
                                f"Symbol: `{symbol}`\n"
                                f"Target: ${target:.4f}\n"
                                f"Current: ${current_price:.4f}\n"
                                f"Condition: Price went *{condition}* target\n\n"
                                f"_This alert has been removed._"
                            ),
                            parse_mode="Markdown"
                        )
                        
                        # Delete the triggered alert
                        async with pool.acquire() as conn2:
                            await conn2.execute(
                                "DELETE FROM alerts WHERE id = $1",
                                alert_id
                            )
                            
                        logger.info(f"Alert triggered: {symbol} for {chat_id}")
                        
                    except Exception as e:
                        logger.error(f"Failed to send alert to {chat_id}: {e}")
                        # Keep alert for retry if sending failed
                    
    except Exception as e:
        logger.error(f"Error in check_prices: {e}")

async def job_scheduler(context: ContextTypes.DEFAULT_TYPE):
    """Wrapper for background job"""
    await check_prices(context.bot)

# ==================================================
# 🏗️ APPLICATION SETUP
# ==================================================

# Create bot application
ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()

# Add error handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in bot handlers"""
    logger.error(f"Update {update} caused error: {context.error}")
    
    # Notify user about error
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again or use /start to restart."
            )
    except Exception as e:
        logger.error(f"Failed to send error message: {e}")

ptb_app.add_error_handler(error_handler)

# Add command handlers
ptb_app.add_handler(CommandHandler("start", start))

# Add callback handlers
ptb_app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
ptb_app.add_handler(CallbackQueryHandler(list_alerts, pattern="^list_alerts_"))
ptb_app.add_handler(CallbackQueryHandler(delete_alert, pattern="^delete_"))
ptb_app.add_handler(CallbackQueryHandler(clear_all_alerts, pattern="^clear_all$"))
ptb_app.add_handler(CallbackQueryHandler(confirm_clear_all, pattern="^confirm_clear$"))
ptb_app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

# Add direction selection handler
ptb_app.add_handler(CallbackQueryHandler(set_direction, pattern="^(direction_up|direction_down)$"))

# Add conversation handler for adding alerts
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(add_start, pattern="^add_start$")],
    states={
        ASK_SYMBOL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_symbol)
        ],
        ASK_PRICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_price)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_add)],
    allow_reentry=True
)
ptb_app.add_handler(conv_handler)

# ==================================================
# 🌐 FASTAPI LIFECYCLE
# ==================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager"""
    logger.info("🚀 Starting AlertBot System...")
    
    try:
        # Initialize database
        await init_db()
        
        # Start bot
        await ptb_app.initialize()
        await ptb_app.start()
        
        # Start background job (check every 30 seconds)
        ptb_app.job_queue.run_repeating(
            job_scheduler,
            interval=30,
            first=10,
            name="price_checker"
        )
        
        # Start polling
        await ptb_app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
        logger.info("✅ Bot started successfully")
        yield
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise
    finally:
        logger.info("🛑 Stopping AlertBot System...")
        try:
            # Clean shutdown
            if ptb_app.updater.running:
                await ptb_app.updater.stop()
            if ptb_app.running:
                await ptb_app.stop()
            await ptb_app.shutdown()
            
            # Close database pool
            if pool:
                await pool.close()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

# Create FastAPI app
api = FastAPI(title="AlertBot API", lifespan=lifespan)

@api.get("/")
async def root():
    return {"status": "running", "service": "Telegram AlertBot"}

@api.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        if pool:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# ==================================================
# 🚀 ENTRY POINT
# ==================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        api,
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False  # Important: Set to False for production/stability
    )