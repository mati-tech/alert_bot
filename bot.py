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
ALERTS_PER_PAGE = 5
API_TIMEOUT = 10

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or DATABASE_URL")

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
            
            CREATE INDEX IF NOT EXISTS idx_alerts_chat_id ON alerts(chat_id);
            CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
            CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
        """)
    logger.info("Database initialized")

async def get_connection():
    return await pool.acquire()

# ==================================================
# 📈 API CLIENT
# ==================================================
class MEXCClient:
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
            [InlineKeyboardButton("➕ Add Alert", callback_data="add_instructions")],
            [InlineKeyboardButton("📋 My Alerts", callback_data="list_alerts_0")],
            [InlineKeyboardButton("🗑️ Clear All Alerts", callback_data="clear_all")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🤖 *Crypto Alert Bot*\n\n"
            "Track cryptocurrency prices and get notified when they hit your targets.\n\n"
            "• *To add an alert:* send a message with the symbol and target price\n"
            "  Example: `BTCUSDT 65000` or `ETHUSDT 3500`\n"
            "• The bot automatically detects if the target is above or below the current price.\n"
            "• Manage your alerts from the menu below."
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
        text = "🤖 Crypto Alert Bot\n\nTrack cryptocurrency prices and get notified when they hit your targets.\n\n• To add an alert: send 'SYMBOL PRICE' (e.g., BTCUSDT 65000)"
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        if update.message:
            await update.message.reply_text("❌ An error occurred. Please try /start again.")

async def add_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show instructions for adding an alert"""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📝 *How to Add an Alert*\n\n"
        "Simply send a message with the trading pair and target price.\n\n"
        "Examples:\n"
        "• `BTCUSDT 65000`\n"
        "• `ETHUSDT 3500.5`\n"
        "• `SOLUSDT 200`\n\n"
        "The bot will check the current price and set an alert for when the price goes *above* or *below* your target automatically.\n\n"
        "👉 Send your alert now!"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_add_alert_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parse a single message to create an alert"""
    user_text = update.message.text.strip()
    parts = user_text.split()
    
    # Expect exactly two parts: symbol and price
    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Invalid format. Please send: `SYMBOL PRICE`\n"
            "Example: `BTCUSDT 65000`",
            parse_mode="Markdown"
        )
        return
    
    symbol = parts[0].upper()
    price_str = parts[1].replace(',', '')
    
    # Validate price
    try:
        target_price = float(price_str)
        if target_price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid price. Please enter a positive number.\n"
            "Example: `BTCUSDT 65000`",
            parse_mode="Markdown"
        )
        return
    
    # Fetch current price
    async with MEXCClient() as client:
        current_price = await client.get_price(symbol)
    
    if current_price is None:
        await update.message.reply_text(
            f"❌ Could not find symbol `{symbol}` on MEXC.\n"
            "Please check the trading pair and try again.",
            parse_mode="Markdown"
        )
        return
    
    # Determine direction
    if target_price > current_price:
        direction = "up"
        direction_text = "above"
        direction_icon = "📈"
    elif target_price < current_price:
        direction = "down"
        direction_text = "below"
        direction_icon = "📉"
    else:
        # Target equals current price – treat as immediate trigger?
        # For simplicity, we'll set it as "up" but it will trigger immediately.
        direction = "up"
        direction_text = "at"
        direction_icon = "🎯"
    
    # Save to database
    try:
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO alerts (chat_id, symbol, target_price, direction)
                VALUES ($1, $2, $3, $4)
            """, update.effective_chat.id, symbol, target_price, direction)
    except Exception as e:
        logger.error(f"DB error saving alert: {e}")
        await update.message.reply_text("❌ Failed to save alert. Please try again later.")
        return
    
    # Success message
    keyboard = [
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
        [InlineKeyboardButton("📋 View Alerts", callback_data="list_alerts_0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ *Alert Set Successfully!*\n\n"
        f"• Symbol: `{symbol}`\n"
        f"• Target: ${target_price:,.4f}\n"
        f"• Condition: Price goes *{direction_text}* target {direction_icon}\n"
        f"• Current: ${current_price:,.4f}\n\n"
        f"_You'll be notified when the price is reached._",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    logger.info(f"Alert created: {symbol} {target_price} for chat {update.effective_chat.id}")

# ==================================================
# 📋 ALERTS MANAGEMENT (Pagination)
# ==================================================

async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's alerts with delete button on same line"""
    query = update.callback_query
    await query.answer()
    
    try:
        data_parts = query.data.split('_')
        page = int(data_parts[-1]) if len(data_parts) > 2 else 0
        
        async with pool.acquire() as conn:
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
            
            total_pages = (total + ALERTS_PER_PAGE - 1) // ALERTS_PER_PAGE
            if page >= total_pages:
                page = total_pages - 1
            
            offset = page * ALERTS_PER_PAGE
            
            alerts = await conn.fetch("""
                SELECT id, symbol, target_price, direction, created_at
                FROM alerts 
                WHERE chat_id = $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """, query.from_user.id, ALERTS_PER_PAGE, offset)
        
        message_lines = [f"📋 *Your Alerts ({total} total)*\n"]
        keyboard = []
        
        for i, alert in enumerate(alerts, 1):
            index = offset + i
            direction_icon = "📈" if alert['direction'] == 'up' else "📉"
            price_formatted = f"{alert['target_price']:,.4f}".rstrip('0').rstrip('.')
            
            message_lines.append(
                f"{index}. `{alert['symbol']}` - ${price_formatted} {direction_icon}"
            )
            
            alert_button_text = f"{alert['symbol']} ${price_formatted} {direction_icon}"
            delete_button = InlineKeyboardButton(
                "❌",
                callback_data=f"delete_{alert['id']}_{page}"
            )
            
            keyboard.append([
                InlineKeyboardButton(alert_button_text, callback_data=f"info_{alert['id']}"),
                delete_button
            ])
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("◀️ Previous", callback_data=f"list_alerts_{page-1}")
            )
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("Next ▶️", callback_data=f"list_alerts_{page+1}")
            )
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([
            InlineKeyboardButton("🗑️ Clear All", callback_data="clear_all"),
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
    query = update.callback_query
    await query.answer()
    
    try:
        data_parts = query.data.split('_')
        if len(data_parts) < 3:
            await query.edit_message_text("❌ Invalid delete request.")
            return
            
        alert_id = int(data_parts[1])
        page = int(data_parts[2])
        
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM alerts WHERE id = $1 AND chat_id = $2",
                alert_id, query.from_user.id
            )
        
        if result == "DELETE 1":
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
            "❌ Failed to delete alert.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )

async def clear_all_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Delete All", callback_data="confirm_clear"),
            InlineKeyboardButton("❌ Cancel", callback_data="main_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
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
            "❌ Failed to delete alerts.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
        )

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ==================================================
# 🔄 BACKGROUND PRICE CHECKER
# ==================================================

async def check_prices(bot):
    try:
        async with pool.acquire() as conn:
            symbols_data = await conn.fetch("SELECT DISTINCT symbol FROM alerts")
        if not symbols_data:
            return
        
        symbols = [row['symbol'] for row in symbols_data]
        
        async with MEXCClient() as client:
            prices = await client.get_prices_batch(symbols)
        
        if not prices:
            return
        
        for symbol, current_price in prices.items():
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
                condition = ""
                if direction == 'up' and current_price >= target:
                    triggered = True
                    condition = "above"
                elif direction == 'down' and current_price <= target:
                    triggered = True
                    condition = "below"
                
                if triggered:
                    try:
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
                        
                        async with pool.acquire() as conn2:
                            await conn2.execute(
                                "DELETE FROM alerts WHERE id = $1",
                                alert_id
                            )
                        logger.info(f"Alert triggered: {symbol} for {chat_id}")
                    except Exception as e:
                        logger.error(f"Failed to send alert to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Error in check_prices: {e}")

async def job_scheduler(context: ContextTypes.DEFAULT_TYPE):
    await check_prices(context.bot)

# ==================================================
# 🏗️ APPLICATION SETUP
# ==================================================

ptb_app = ApplicationBuilder().token(BOT_TOKEN).build()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again or use /start to restart."
            )
    except Exception as e:
        logger.error(f"Failed to send error message: {e}")

ptb_app.add_error_handler(error_handler)

# Handlers
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
ptb_app.add_handler(CallbackQueryHandler(add_instructions, pattern="^add_instructions$"))
ptb_app.add_handler(CallbackQueryHandler(list_alerts, pattern="^list_alerts_"))
ptb_app.add_handler(CallbackQueryHandler(delete_alert, pattern="^delete_"))
ptb_app.add_handler(CallbackQueryHandler(clear_all_alerts, pattern="^clear_all$"))
ptb_app.add_handler(CallbackQueryHandler(confirm_clear_all, pattern="^confirm_clear$"))
ptb_app.add_handler(CallbackQueryHandler(noop, pattern="^noop$"))

# Message handler for adding alerts (any text that is not a command)
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_alert_message))

# ==================================================
# 🌐 FASTAPI LIFECYCLE
# ==================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Starting AlertBot System...")
    try:
        await init_db()
        await ptb_app.initialize()
        await ptb_app.start()
        
        ptb_app.job_queue.run_repeating(
            job_scheduler,
            interval=5,
            first=5,
            name="price_checker"
        )
        
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
            if ptb_app.updater.running:
                await ptb_app.updater.stop()
            if ptb_app.running:
                await ptb_app.stop()
            await ptb_app.shutdown()
            if pool:
                await pool.close()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

api = FastAPI(title="AlertBot API", lifespan=lifespan)

@api.get("/")
async def root():
    return {"status": "running", "service": "Telegram AlertBot"}

@api.get("/health")
async def health_check():
    try:
        if pool:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(
        api,
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False
    )