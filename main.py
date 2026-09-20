import os
import logging
import sqlite3
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------------------------------------------
# 1. DUMMY HTTP SERVER (For Render Free Tier Keep-Alive)
# ----------------------------------------------------
class DummyHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running 24/7!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHTTPHandler)
    logging.info(f"Dummy HTTP server listening on port {port}")
    server.serve_forever()

# ----------------------------------------------------
# 2. DATABASE SETUP (SQLite)
# ----------------------------------------------------
DB_NAME = "shop.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0
        )
    ''')
    
    # Products table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL
        )
    ''')
    
    # Stock table (Cards/Digital Codes)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            card_data TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')
    
    # Purchase History
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_name TEXT,
            card_data TEXT,
            price REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------
# 3. HELPER FUNCTIONS
# ----------------------------------------------------
ADMIN_USERNAME = "Trusted_zone_1122"

def get_db():
    return sqlite3.connect(DB_NAME)

def is_admin(user) -> bool:
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        return True
    return False

def add_or_update_user(user):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, balance) VALUES (?, ?, 0.0)", (user.id, user.username))
    cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (user.username, user.id))
    conn.commit()
    conn.close()

def get_user_balance(user_id) -> float:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0.0

def update_user_balance(user_id, amount):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# ----------------------------------------------------
# 4. BOT HANDLERS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)
    
    keyboard = [
        [InlineKeyboardButton("🛒 Buy Cards", callback_data="buy_menu")],
        [InlineKeyboardButton("💳 My Balance", callback_data="my_balance"), InlineKeyboardButton("📜 Purchase History", callback_data="my_history")]
    ]
    
    if is_admin(user):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Welcome {user.first_name} to Digital Card Shop!\n\n"
        f"Choose an option below:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "my_balance":
        bal = get_user_balance(user.id)
        await query.edit_message_text(f"💳 Your current balance is: **${bal:.2f}**", parse_mode="Markdown")
        
    elif data == "buy_menu":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, price FROM products")
        products = cursor.fetchall()
        conn.close()
        
        if not products:
            await query.edit_message_text("❌ No products available in the shop currently.")
            return

        keyboard = []
        for p_id, name, price in products:
            keyboard.append([InlineKeyboardButton(f"{name} - ${price:.2f}", callback_data=f"buy_prod_{p_id}")])
            
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="start_menu")])
        await query.edit_message_text("🛒 Select a product to buy:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("buy_prod_"):
        p_id = int(data.split("_")[2])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, price FROM products WHERE id = ?", (p_id,))
        prod = cursor.fetchone()
        
        if not prod:
            await query.edit_message_text("❌ Product not found.")
            conn.close()
            return
            
        p_name, p_price = prod
        user_bal = get_user_balance(user.id)
        
        if user_bal < p_price:
            await query.edit_message_text(f"❌ Insufficient balance! Price: ${p_price:.2f}, Your balance:${user_bal:.2f}")
            conn.close()
            return

        cursor.execute("SELECT id, card_data FROM stock WHERE product_id = ? LIMIT 1", (p_id,))
        stock_item = cursor.fetchone()
        
        if not stock_item:
            await query.edit_message_text("❌ Out of stock! Please check back later.")
            conn.close()
            return
            
        s_id, card_data = stock_item
        
        # Process Purchase
        cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (p_price, user.id))
        cursor.execute("INSERT INTO history (user_id, product_name, card_data, price) VALUES (?, ?, ?, ?)",
                       (user.id, p_name, card_data, p_price))
        conn.commit()
        conn.close()
        
        await query.edit_message_text(
            f"🎉 **Purchase Successful!**\n\n"
            f"📦 **Product:** {p_name}\n"
            f"🔑 **Card Data / Code:** `{card_data}`\n\n"
            f"Thank you for buying!",
            parse_mode="Markdown"
        )

    elif data == "my_history":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, card_data, price, timestamp FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user.id,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await query.edit_message_text("📜 You have no purchase history yet.")
            return
            
        msg = "📜 **Your Last 5 Purchases:**\n\n"
        for p_name, c_data, price, ts in rows:
            msg += f"• **{p_name}** (${price:.2f})\n  Code: `{c_data}`\n  Date: {ts}\n\n"
            
        await query.edit_message_text(msg, parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_admin(user):
            await query.edit_message_text("❌ Unauthorized access!")
            return
            
        msg = (
            "⚙️ **Admin Commands Panel**\n\n"
            "• `/addproduct <Name> <Price>` - Add a new product\n"
            "• `/addstock <ProductID> <CardData>` - Add stock code/card\n"
            "• `/addbalance <UserID> <Amount>` - Add balance to a user\n"
            "• `/broadcast <Message>` - Send message to all users"
        )
        await query.edit_message_text(msg, parse_mode="Markdown")

# ----------------------------------------------------
# 5. ADMIN COMMAND HANDLERS
# ----------------------------------------------------
async def add_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        args = context.args
        price = float(args[-1])
        name = " ".join(args[:-1])
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
        p_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Product added successfully! ID: `{p_id}` | Name: {name} | Price: ${price:.2f}", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Usage: `/addproduct <Name> <Price>`\nExample: `/addproduct Netflix Premium 5.00`", parse_mode="Markdown")

async def add_stock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        p_id = int(context.args[0])
        card_data = " ".join(context.args[1:])
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO stock (product_id, card_data) VALUES (?, ?)", (p_id, card_data))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ Stock added successfully for Product ID `{p_id}`!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Usage: `/addstock <ProductID> <CardData>`\nExample: `/addstock 1 XXXX-YYYY-ZZZZ`", parse_mode="Markdown")

async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        target_user_id = int(context.args[0])
        amount = float(context.args[1])
        
        update_user_balance(target_user_id, amount)
        await update.message.reply_text(f"✅ Added ${amount:.2f} to user ID `{target_user_id}`!", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Usage: `/addbalance <UserID> <Amount>`\nExample: `/addbalance 123456789 10.00`", parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("❌ Usage: `/broadcast <Your Message>`")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    count = 0
    for (u_id,) in users:
        try:
            await context.bot.send_message(chat_id=u_id, text=f"📢 **Announcement:**\n\n{message_text}", parse_mode="Markdown")
            count += 1
        except Exception:
            pass
            
    await update.message.reply_text(f"📢 Broadcast sent to {count} users!")

# ----------------------------------------------------
# 6. MAIN FUNCTION
# ----------------------------------------------------
def main():
    # Start Dummy Server in a separate thread for Render
    server_thread = Thread(target=run_dummy_server, daemon=True)
    server_thread.start()
    
    token = os.environ.get("BOT_TOKEN")
    if not token:
        logging.error("No BOT_TOKEN provided in Environment Variables!")
        return

    app = Application.builder().token(token).build()

    # User Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Admin Handlers
    app.add_handler(CommandHandler("addproduct", add_product_cmd))
    app.add_handler(CommandHandler("addstock", add_stock_cmd))
    app.add_handler(CommandHandler("addbalance", add_balance_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    logging.info("Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()
