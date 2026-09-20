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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bin TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            card_data TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')
    
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
# 4. BOT HANDLERS & INTERFACE
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)
    bal = get_user_balance(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
        [InlineKeyboardButton("💰 My Balance", callback_data="my_balance"), InlineKeyboardButton("📜 Purchase History", callback_data="my_history")],
        [InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    
    if is_admin(user):
        keyboard.append([InlineKeyboardButton("⚡ Admin Control Panel", callback_data="admin_panel")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"✨ *━━━━━━━━━━━━━━━━━━━━*\n"
        f"👑 *PREMIUM DIGITAL CARD STORE* 👑\n"
        f"✨ *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"👋 *Welcome,* `{user.first_name}`!\n"
        f"🆔 *User ID:* `{user.id}`\n"
        f"💵 *Your Balance:* `${bal:.2f}`\n\n"
        f"🚀 *Instant 24/7 Automated Card Delivery!*\n"
        f"👇 *Select an option below to get started:*"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "start_menu":
        bal = get_user_balance(user.id)
        keyboard = [
            [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
            [InlineKeyboardButton("💰 My Balance", callback_data="my_balance"), InlineKeyboardButton("📜 Purchase History", callback_data="my_history")],
            [InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")]
        ]
        if is_admin(user):
            keyboard.append([InlineKeyboardButton("⚡ Admin Control Panel", callback_data="admin_panel")])
            
        welcome_text = (
            f"✨ *━━━━━━━━━━━━━━━━━━━━*\n"
            f"👑 *PREMIUM DIGITAL CARD STORE* 👑\n"
            f"✨ *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👋 *Welcome,* `{user.first_name}`!\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💵 *Your Balance:* `${bal:.2f}`\n\n"
            f"🚀 *Instant 24/7 Automated Card Delivery!*\n"
            f"👇 *Select an option below to get started:*"
        )
        await query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "my_balance":
        bal = get_user_balance(user.id)
        msg = (
            f"💳 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"📊 *ACCOUNT BALANCE SUMMARY*\n"
            f"💳 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👤 *User:* `{user.first_name}`\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💎 *Current Balance:* `${bal:.2f}`\n\n"
            f"💡 *To top-up your balance, contact Admin:* @{ADMIN_USERNAME}"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
    elif data == "buy_menu":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT p.id, p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s ON p.id = s.product_id GROUP BY p.id")
        products = cursor.fetchall()
        conn.close()
        
        if not products:
            msg = "⚠️ *STORE IS CURRENTLY EMPTY*\n\n_No cards available right now. Please check back later!_"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        keyboard = []
        for p_id, p_bin, name, price, stock_count in products:
            keyboard.append([InlineKeyboardButton(f"💳 BIN: {p_bin} | {name} — ${price:.2f} [{stock_count} Stock]", callback_data=f"buy_prod_{p_id}")])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")])
        
        msg = (
            f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🔥 *AVAILABLE CARDS BY BIN*\n"
            f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👇 *Select a card type/BIN to buy:*"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("buy_prod_"):
        p_id = int(data.split("_")[2])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT name, bin, price FROM products WHERE id = ?", (p_id,))
        prod = cursor.fetchone()
        
        if not prod:
            await query.edit_message_text("❌ *Product not found.*", parse_mode="Markdown")
            conn.close()
            return
            
        p_name, p_bin, p_price = prod
        user_bal = get_user_balance(user.id)
        
        if user_bal < p_price:
            msg = (
                f"❌ *INSUFFICIENT BALANCE!*\n\n"
                f"💳 *BIN:* `{p_bin}` ({p_name})\n"
                f"🏷️ *Price:* `${p_price:.2f}`\n"
                f"💵 *Your Balance:* `${user_bal:.2f}`\n\n"
                f"⚠️ *Please top up your balance by contacting Admin (@{ADMIN_USERNAME}).*"
            )
            keyboard = [[InlineKeyboardButton("🔙 Back to Products", callback_data="buy_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            conn.close()
            return

        # Fetch 1 stock card
        cursor.execute("SELECT id, card_data FROM stock WHERE product_id = ? LIMIT 1", (p_id,))
        stock_item = cursor.fetchone()
        
        if not stock_item:
            msg = f"❌ *OUT OF STOCK!*\n\n_Sorry, BIN `{p_bin}` ({p_name}) is currently sold out. Check back soon!_"
            keyboard = [[InlineKeyboardButton("🔙 Back to Products", callback_data="buy_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            conn.close()
            return
            
        s_id, card_data = stock_item
        
        # ⚠️ STRICT PURCHASE PROCESS: REMOVE CARD FROM STOCK IMMEDIATELY
        cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (p_price, user.id))
        cursor.execute("INSERT INTO history (user_id, product_name, card_data, price) VALUES (?, ?, ?, ?)",
                       (user.id, f"{p_name} (BIN: {p_bin})", card_data, p_price))
        conn.commit()
        conn.close()
        
        success_msg = (
            f"🎉 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"✅ *PURCHASE SUCCESSFUL!*\n"
            f"🎉 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"📦 *Item:* `{p_name}`\n"
            f"💳 *BIN:* `{p_bin}`\n"
            f"💵 *Paid:* `${p_price:.2f}`\n\n"
            f"🔑 *YOUR CARD DATA:*\n"
            f"`{card_data}`\n\n"
            f"⚡ _Tap on the card details above to copy!_\n"
            f"❤️ *Thank you for shopping!*"
        )
        keyboard = [[InlineKeyboardButton("🛍️ Buy More Cards", callback_data="buy_menu")]]
        await query.edit_message_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "my_history":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, card_data, price, timestamp FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user.id,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            msg = "📜 *PURCHASE HISTORY*\n\n_You haven't bought any cards yet!_"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
            
        msg = f"📜 *━━━━━━━━━━━━━━━━━━━━*\n"
        msg += f"🛍️ *YOUR PURCHASE HISTORY*\n"
        msg += f"📜 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        
        for p_name, c_data, price, ts in rows:
            msg += f"📦 *{p_name}* — `${price:.2f}`\n"
            msg += f"💳 Details: `{c_data}`\n"
            msg += f"📅 Date: `{ts}`\n"
            msg += f"──────────────\n"
            
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_admin(user):
            await query.edit_message_text("🚫 *Unauthorized Access!*", parse_mode="Markdown")
            return
            
        msg = (
            f"⚡ *━━━━━━━━━━━━━━━━━━━━*\n"
            f"⚙️ *ADMIN CONTROL PANEL*\n"
            f"⚡ *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"📥 *BULK ADD CARDS BY BIN:*\n"
            f"`/addcards <BIN> <Name> <Price>`\n"
            f"_(Past cards line by line in same msg)_\n\n"
            f"🔎 *CHECK USER PURCHASE HISTORY:*\n"
            f"`/userhistory <UserID>`\n\n"
            f"📁 *BACKUP & DOWNLOAD:*\n"
            f"`/downloadcards` - _All stock in TXT_\n"
            f"`/downloaddb` - _Full Database_\n\n"
            f"🔎 *SEARCH BIN STOCK:*\n"
            f"`/searchbin <BIN>`\n\n"
            f"💰 *ADD USER BALANCE:*\n"
            f"`/addbalance <UserID> <Amount>`\n\n"
            f"📢 *BROADCAST MESSAGE:*\n"
            f"`/broadcast <Your Message>`"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----------------------------------------------------
# 5. ADMIN COMMAND HANDLERS
# ----------------------------------------------------
async def add_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        text_lines = update.message.text.split("\n")
        first_line_parts = text_lines[0].split()
        
        bin_code = first_line_parts[1]
        price = float(first_line_parts[-1])
        p_name = " ".join(first_line_parts[2:-1]) if len(first_line_parts) > 3 else f"BIN {bin_code}"
        
        cards = [line.strip() for line in text_lines[1:] if line.strip()]
        
        if not cards:
            await update.message.reply_text("❌ *No card data found under the command!*", parse_mode="Markdown")
            return
            
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("INSERT OR IGNORE INTO products (bin, name, price) VALUES (?, ?, ?)", (bin_code, p_name, price))
        cursor.execute("UPDATE products SET price = ?, name = ? WHERE bin = ?", (price, p_name, bin_code))
        
        cursor.execute("SELECT id FROM products WHERE bin = ?", (bin_code,))
        p_id = cursor.fetchone()[0]
        
        for c in cards:
            cursor.execute("INSERT INTO stock (product_id, card_data) VALUES (?, ?)", (p_id, c))
            
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"🎉 *CARDS ADDED SUCCESSFULLY!*\n\n"
            f"💳 *BIN:* `{bin_code}`\n"
            f"📦 *Category:* `{p_name}`\n"
            f"🏷️ *Price:* `${price:.2f}`\n"
            f"📥 *Total Cards Added:* `{len(cards)}`",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text(
            "❌ *Usage Format:*\n"
            "`/addcards <BIN> <Name> <Price>`\n"
            "`CardDetails1`\n"
            "`CardDetails2`",
            parse_mode="Markdown"
        )

async def user_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        target_user_id = int(context.args[0])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, card_data, price, timestamp FROM history WHERE user_id = ? ORDER BY id DESC", (target_user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await update.message.reply_text(f"⚠️ *No purchase history found for User ID:* `{target_user_id}`", parse_mode="Markdown")
            return
            
        msg = f"📜 *PURCHASE HISTORY FOR USER:* `{target_user_id}`\n"
        msg += f"📊 *Total Cards Bought:* `{len(rows)}`\n\n"
        
        for p_name, c_data, price, ts in rows[:15]: # Show max 15 items in text
            msg += f"📦 *{p_name}* — `${price:.2f}`\n"
            msg += f"💳 Card: `{c_data}`\n"
            msg += f"📅 Date: `{ts}`\n"
            msg += f"──────────────\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ *Usage:* `/userhistory <UserID>`\n*Example:* `/userhistory 123456789`", parse_mode="Markdown")

async def download_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT p.bin, p.name, p.price, s.card_data FROM stock s JOIN products p ON s.product_id = p.id")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("⚠️ *No stock cards found to backup!*", parse_mode="Markdown")
        return
        
    file_path = "cards_backup.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("=== CARDS STOCK BACKUP ===\n\n")
        for p_bin, p_name, price, card in rows:
            f.write(f"BIN: {p_bin} | Category: {p_name} | Price: ${price:.2f} | Card: {card}\n")
            
    await update.message.reply_document(document=open(file_path, "rb"), caption="📦 *Here is your full stock backup file!*", parse_mode="Markdown")
    if os.path.exists(file_path):
        os.remove(file_path)

async def download_db_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    if os.path.exists(DB_NAME):
        await update.message.reply_document(document=open(DB_NAME, "rb"), caption="💾 *Full SQLite Database File Backup!*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ *Database file not found!*", parse_mode="Markdown")

async def search_bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        bin_code = context.args[0]
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s ON p.id = s.product_id WHERE p.bin = ? GROUP BY p.id", (bin_code,))
        res = cursor.fetchone()
        conn.close()
        
        if not res:
            await update.message.reply_text(f"❌ *BIN `{bin_code}` not found in shop.*", parse_mode="Markdown")
            return
            
        name, price, stock = res
        await update.message.reply_text(
            f"🔎 *BIN SEARCH DETAILS:*\n\n"
            f"💳 *BIN:* `{bin_code}`\n"
            f"📦 *Name:* `{name}`\n"
            f"💵 *Price:* `${price:.2f}`\n"
            f"📊 *Available Stock:* `{stock}` cards",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("❌ *Usage:* `/searchbin <BIN>`", parse_mode="Markdown")

async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    try:
        target_user_id = int(context.args[0])
        amount = float(context.args[1])
        
        update_user_balance(target_user_id, amount)
        await update.message.reply_text(
            f"✅ *BALANCE UPDATED!*\n\n"
            f"👤 *Target User ID:* `{target_user_id}`\n"
            f"💰 *Added Amount:* `${amount:.2f}`",
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("❌ *Usage:* `/addbalance <UserID> <Amount>`", parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
        
    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("❌ *Usage:* `/broadcast <Your Message>`", parse_mode="Markdown")
        return
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    count = 0
    for (u_id,) in users:
        try:
            broadcast_msg = (
                f"📢 *━━━━━━━━━━━━━━━━━━━━*\n"
                f"🔔 *ANNOUNCEMENT FROM ADMIN*\n"
                f"📢 *━━━━━━━━━━━━━━━━━━━━*\n\n"
                f"{message_text}"
            )
            await context.bot.send_message(chat_id=u_id, text=broadcast_msg, parse_mode="Markdown")
            count += 1
        except Exception:
            pass
            
    await update.message.reply_text(f"📢 *Broadcast successfully sent to {count} users!*", parse_mode="Markdown")

# ----------------------------------------------------
# 6. MAIN FUNCTION
# ----------------------------------------------------
def main():
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
    app.add_handler(CommandHandler("addcards", add_cards_cmd))
    app.add_handler(CommandHandler("userhistory", user_history_cmd))
    app.add_handler(CommandHandler("downloadcards", download_cards_cmd))
    app.add_handler(CommandHandler("downloaddb", download_db_cmd))
    app.add_handler(CommandHandler("searchbin", search_bin_cmd))
    app.add_handler(CommandHandler("addbalance", add_balance_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    logging.info("Stylish Digital Card Shop Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()
