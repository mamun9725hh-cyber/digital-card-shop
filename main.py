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
# CONFIGURATION
# ----------------------------------------------------
ADMIN_USERNAME = "Trusted_zone_1122"
CHANNEL_USERNAME = "@help_centre_1122"  # Force join channel
CHANNEL_URL = "https://t.me/help_centre_1122"

# ----------------------------------------------------
# 1. DUMMY HTTP SERVER (For Render Free Tier)
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
            balance REAL DEFAULT 0.0,
            has_claimed_trial INTEGER DEFAULT 0
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------
# 3. HELPER FUNCTIONS
# ----------------------------------------------------
def get_db():
    return sqlite3.connect(DB_NAME)

def is_admin(user) -> bool:
    if user.username and user.username.lower() == ADMIN_USERNAME.lower():
        return True
    return False

def add_or_update_user(user):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, balance, has_claimed_trial) VALUES (?, ?, 0.0, 0)", (user.id, user.username))
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

def get_setting(key) -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()
    if value is None:
        cursor.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def has_claimed_trial(user_id) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT has_claimed_trial FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return True if row and row[0] == 1 else False

def set_claimed_trial(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET has_claimed_trial = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

async def is_user_joined(bot, user_id) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception as e:
        logging.error(f"Error checking channel membership: {e}")
        return True

# Helper to generate All Commands text
def get_commands_text(user):
    msg = (
        f"📖 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"📜 *ALL BOT COMMANDS GUIDE*\n"
        f"📖 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"👤 *USER COMMANDS:*\n"
        f"• `/start` — বটের মেইন মেনু চালু করতে\n"
        f"• `/commands` — সকল কমান্ডের লিস্ট দেখতে\n"
        f"• `/stock` — স্টকে কোন কোন BIN এর কয়টি কার্ড আছে তা দেখতে\n"
        f"• `/balance` — আপনার বর্তমান একাউন্ট ব্যালেন্স দেখতে\n\n"
    )
    if is_admin(user):
        msg += (
            f"⚡ *ADMIN COMMANDS:*\n"
            f"• `/addcards <BIN> <Name> <Price>` — স্টকে কার্ড আপলোড করতে\n"
            f"• `/addbalance <UserID> <Amount>` — ইউজারের একাউন্টে ব্যালেন্স যোগ করতে\n"
            f"• `/setbkash <Num>` — বিকাশ নম্বর সেট করতে\n"
            f"• `/setnagad <Num>` — নগদ নম্বর সেট করতে\n"
            f"• `/removebkash` — বিকাশ নম্বর রিমুভ করতে\n"
            f"• `/removenagad` — নগদ নম্বর রিমুভ করতে\n"
            f"• `/searchbin <BIN>` — কোনো নির্দিষ্ট BIN স্টক চেক করতে\n"
            f"• `/userhistory <UserID>` — ইউজারের কেনাকাটার হিস্টোরি দেখতে\n"
            f"• `/downloadcards` — স্টকের সব কার্ড টেক্সট ফাইলে ডাউনলোড করতে\n"
            f"• `/downloaddb` — ডাটাবেজ ব্যাকআপ ফাইল ডাউনলোড করতে\n"
            f"• `/broadcast <Message>` — সকল ইউজারকে নোটিশ পাঠাতে\n"
        )
    return msg

# Helper to generate Stock text
def get_stock_text():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s ON p.id = s.product_id GROUP BY p.id")
    products = cursor.fetchall()
    conn.close()

    if not products:
        return (
            f"📊 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"📦 *AVAILABLE CARD STOCK STATUS*\n"
            f"📊 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"⚠️ _বর্তমানে বটের স্টকে কোনো কার্ড নেই।_\n\n"
            f"📲 *কোনো BIN এর কার্ড প্রয়োজন হলে এডমিনকে জানান:*\n"
            f"👉 @{ADMIN_USERNAME}\n\n"
            f"📌 *Note:* কাস্টম BIN-এর জন্য শুধুমাত্র *Visa Card* BIN গ্রহণ করা হয়।"
        )

    msg = (
        f"📊 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"📦 *AVAILABLE CARD STOCK STATUS*\n"
        f"📊 *━━━━━━━━━━━━━━━━━━━━*\n\n"
    )
    total_cards = 0
    for idx, (p_bin, name, price, count) in enumerate(products, 1):
        total_cards += count
        status = f"`{count}` টি এভেলেবল" if count > 0 else "❌ Out of Stock"
        msg += f"{idx}️⃣ *BIN:* `{p_bin}` ({name})\n"
        msg += f"   🏷️ দাম: `${price:.2f}` | 📦 স্টক: {status}\n"
        msg += f"──────────────\n"

    msg += f"\n🔥 *মোট কার্ড স্টকে আছে:* `{total_cards}` টি\n"
    msg += f"💡 _কার্ড কিনতে বা ট্রায়াল নিতে নিচে দেওয়া মেনু বাটন ব্যবহার করুন!_"
    return msg

# ----------------------------------------------------
# 4. BOT HANDLERS & INTERFACE
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)
    bal = get_user_balance(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
        [InlineKeyboardButton("🎁 Free Trial (2 Cards)", callback_data="claim_trial")],
        [InlineKeyboardButton("📊 Available Stock", callback_data="view_stock"), InlineKeyboardButton("📜 All Commands", callback_data="all_commands")],
        [InlineKeyboardButton("💰 My Balance", callback_data="my_balance"), InlineKeyboardButton("📜 Purchase History", callback_data="my_history")],
        [InlineKeyboardButton("📢 Telegram Channel", url=CHANNEL_URL)],
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

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = get_commands_text(user)
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_stock_text()
    keyboard = [
        [InlineKeyboardButton("🛍️ Go To Shop", callback_data="buy_menu")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bal = get_user_balance(user.id)
    msg = f"💵 *Your Current Balance:* `${bal:.2f}`\n\n_To top up, contact Admin: @{ADMIN_USERNAME}_"
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "start_menu":
        bal = get_user_balance(user.id)
        keyboard = [
            [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
            [InlineKeyboardButton("🎁 Free Trial (2 Cards)", callback_data="claim_trial")],
            [InlineKeyboardButton("📊 Available Stock", callback_data="view_stock"), InlineKeyboardButton("📜 All Commands", callback_data="all_commands")],
            [InlineKeyboardButton("💰 My Balance", callback_data="my_balance"), InlineKeyboardButton("📜 Purchase History", callback_data="my_history")],
            [InlineKeyboardButton("📢 Telegram Channel", url=CHANNEL_URL)],
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

    elif data == "all_commands":
        msg = get_commands_text(user)
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "view_stock":
        msg = get_stock_text()
        keyboard = [
            [InlineKeyboardButton("🛍️ Go To Shop", callback_data="buy_menu")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "claim_trial":
        joined = await is_user_joined(context.bot, user.id)
        if not joined:
            msg = (
                f"⚠️ *MUST JOIN OUR TELEGRAM CHANNEL!*\n\n"
                f"ফ্রি ট্রায়াল ক্লেইম করতে হলে আপনাকে অবশ্যই আমাদের সিগন্যাল চ্যানেলে জয়েন থাকতে হবে।\n\n"
                f"👇 নিচের বাটন থেকে চ্যানেলে জয়েন করুন এবং তারপর *Claim Trial Again* এ চাপুন:"
            )
            keyboard = [
                [InlineKeyboardButton("📢 Join Telegram Channel", url=CHANNEL_URL)],
                [InlineKeyboardButton("🔄 Claim Trial Again", callback_data="claim_trial")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        if has_claimed_trial(user.id):
            msg = "❌ *TRIAL ALREADY CLAIMED!*\n\n_You have already used your 1-time Free Trial. Please buy cards from the shop!_"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        context.user_data["awaiting_trial_bin"] = True
        msg = (
            f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🔍 *ENTER BIN FOR FREE TRIAL*\n"
            f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"আপনি যে BIN-এর ২টি ফ্রি ট্রায়াল কার্ড চান, সেই **6-Digit BIN** টি এখানে মেসেজে লিখে পাঠান।\n\n"
            f"💡 *Example:* `411111`"
        )
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "my_balance":
        bal = get_user_balance(user.id)
        bkash_num = get_setting("bkash")
        nagad_num = get_setting("nagad")
        
        payment_info = ""
        if bkash_num or nagad_num:
            payment_info += "\n📲 *PAYMENT METHODS (TOP-UP):*\n"
            if bkash_num:
                payment_info += f"🌸 *bKash (Personal):* `{bkash_num}`\n"
            if nagad_num:
                payment_info += f"🟠 *Nagad (Personal):* `{nagad_num}`\n"
            payment_info += "\n⚠️ _টাকা পাঠানোর পর ট্রানজেকশন স্ক্রিনশট ও আপনার User ID সহ এডমিনকে পাঠান।_\n"
        else:
            payment_info += "\n💡 *To top-up your balance, contact Admin directly.*"

        msg = (
            f"💳 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"📊 *ACCOUNT BALANCE SUMMARY*\n"
            f"💳 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👤 *User:* `{user.first_name}`\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💎 *Current Balance:* `${bal:.2f}`\n"
            f"{payment_info}\n"
            f"👨‍💻 *Admin:* @{ADMIN_USERNAME}"
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
            msg = (
                f"⚠️ *STORE IS CURRENTLY EMPTY*\n\n"
                f"_বটে বর্তমানে কোনো কার্ড স্টকে নেই।_\n\n"
                f"📲 *আপনার কি কোনো নির্দিষ্ট BIN-এর কার্ড প্রয়োজন?*\n"
                f"অ্যাডমিনের সাথে যোগাযোগ করে আপনার প্রয়োজনীয় BIN-এর কার্ড বটের স্টকে যুক্ত করে নিন!\n\n"
                f"📌 *বিশেষ দ্রষ্টব্য (Note):*\n"
                f"কাস্টম BIN রিকোয়েস্টের জন্য **শুধুমাত্র Visa Card** BIN-এর ক্ষেত্রে যোগাযোগ করুন। MasterCard বর্তমানে কাজ করছে না।"
            )
            keyboard = [
                [InlineKeyboardButton("👨‍💻 Request BIN to Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        keyboard = []
        for p_id, p_bin, name, price, stock_count in products:
            keyboard.append([InlineKeyboardButton(f"💳 BIN: {p_bin} | {name} — ${price:.2f} [{stock_count} Stock]", callback_data=f"buy_prod_{p_id}")])
            
        keyboard.append([InlineKeyboardButton("👨‍💻 Need Custom BIN? Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")])
        
        msg = (
            f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🔥 *AVAILABLE CARDS BY BIN*\n"
            f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👇 *Select a card type/BIN to buy:*\n\n"
            f"💡 _আপনার কাঙ্ক্ষিত BIN যদি এখানে না থাকে, তবে এডমিনের সাথে যোগাযোগ করে এড করিয়ে নিন!_\n"
            f"📌 *Note:* কাস্টম BIN-এর জন্য শুধুমাত্র *Visa Card* BIN প্রযোজ্য (MasterCard সমস্যামুক্ত নয়)।"
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

        cursor.execute("SELECT id, card_data FROM stock WHERE product_id = ? LIMIT 1", (p_id,))
        stock_item = cursor.fetchone()
        
        if not stock_item:
            msg = (
                f"❌ *OUT OF STOCK!*\n\n"
                f"দুঃখিত, BIN `{p_bin}` ({p_name})-এর স্টক শেষ হয়ে গেছে।\n\n"
                f"📲 *কার্ড প্রয়োজন?*\n"
                f"অ্যাডমিনের সাথে সরাসরি যোগাযোগ করে বটের স্টকে কার্ড যুক্ত করে নিতে পারেন।\n\n"
                f"📌 *Note:* কাস্টম BIN রিকোয়েস্টের জন্য শুধুমাত্র *Visa Card* BIN-এর ক্ষেত্রে যোগাযোগ করুন।"
            )
            keyboard = [
                [InlineKeyboardButton("👨‍💻 Contact Admin for Stock", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("🔙 Back to Products", callback_data="buy_menu")]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            conn.close()
            return
            
        s_id, card_data = stock_item
        
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
            
        bkash_n = get_setting("bkash") or "Not Set"
        nagad_n = get_setting("nagad") or "Not Set"
        
        msg = (
            f"⚡ *━━━━━━━━━━━━━━━━━━━━*\n"
            f"⚙️ *ADMIN CONTROL PANEL*\n"
            f"⚡ *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"📲 *PAYMENT NUMBERS:*\n"
            f"• bKash: `{bkash_n}` | Nagad: `{nagad_n}`\n"
            f"👉 `/setbkash <Num>` | `/setnagad <Num>`\n"
            f"👉 `/removebkash` | `/removenagad`\n\n"
            f"📥 *BULK ADD CARDS BY BIN:*\n"
            f"`/addcards <BIN> <Name> <Price>`\n\n"
            f"🔎 *CHECK USER PURCHASE HISTORY:*\n"
            f"`/userhistory <UserID>`\n\n"
            f"📁 *BACKUP & DOWNLOAD:*\n"
            f"`/downloadcards` | `/downloaddb`\n\n"
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
# 5. USER BIN INPUT HANDLER (FOR TRIAL)
# ----------------------------------------------------
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    if context.user_data.get("awaiting_trial_bin"):
        context.user_data["awaiting_trial_bin"] = False
        
        joined = await is_user_joined(context.bot, user.id)
        if not joined:
            msg = (
                f"⚠️ *MUST JOIN OUR TELEGRAM CHANNEL!*\n\n"
                f"ফ্রি ট্রায়াল ক্লেইম করতে হলে আপনাকে অবশ্যই আমাদের চ্যানেলে জয়েন থাকতে হবে।"
            )
            keyboard = [
                [InlineKeyboardButton("📢 Join Telegram Channel", url=CHANNEL_URL)],
                [InlineKeyboardButton("🔄 Try Again", callback_data="claim_trial")]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        if has_claimed_trial(user.id):
            msg = "❌ *TRIAL ALREADY CLAIMED!*\n\n_You have already used your 1-time Free Trial._"
            keyboard = [[InlineKeyboardButton("🛍️ Browse Shop", callback_data="buy_menu")]]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        input_bin = text.split()[0]
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name FROM products WHERE bin = ?", (input_bin,))
        prod = cursor.fetchone()
        
        if not prod:
            msg = (
                f"❌ *BIN NOT FOUND IN STOCK!*\n\n"
                f"স্টকে `{input_bin}` BIN-এর কোনো কার্ড খুঁজে পাওয়া যায়নি।\n\n"
                f"📲 *আপনার কি এই BIN-এর কার্ড প্রয়োজন?*\n"
                f"অ্যাডমিনের সাথে সরাসরি যোগাযোগ করে আপনার কাঙ্ক্ষিত BIN-এর কার্ড বটের স্টকে যুক্ত করে নিতে পারেন!\n\n"
                f"📌 *বিশেষ দ্রষ্টব্য (Note):*\n"
                f"কাস্টম BIN রিকোয়েস্ট করার জন্য **শুধুমাত্র Visa Card (ভিসা)** BIN-এর জন্য যোগাযোগ করুন। MasterCard বর্তমানে সাপোর্ট করে না।"
            )
            keyboard = [
                [InlineKeyboardButton("👨‍💻 Contact Admin to Add BIN", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("🔄 Try Another BIN", callback_data="claim_trial")]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            conn.close()
            return
            
        p_id, p_name = prod
        cursor.execute("SELECT id, card_data FROM stock WHERE product_id = ? LIMIT 2", (p_id,))
        stock_items = cursor.fetchall()
        
        if len(stock_items) < 2:
            msg = (
                f"⚠️ *NOT ENOUGH TRIAL CARDS IN STOCK!*\n\n"
                f"`{input_bin}` BIN-এ বর্তমানে ট্রায়ালের জন্য ২ টি কার্ড স্টকে নেই।\n\n"
                f"📲 *কার্ড অ্যাড করতে অ্যাডমিনকে জানান:*\n"
                f"অ্যাডমিনের সাথে সরাসরি কথা বলে এই BIN-এর কার্ড স্টকে যুক্ত করে নিতে পারেন।\n\n"
                f"📌 *Note:* কাস্টম BIN রিকোয়েস্টের ক্ষেত্রে শুধুমাত্র *Visa Card* BIN গ্রহণ করা হয়।"
            )
            keyboard = [
                [InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
                [InlineKeyboardButton("🔄 Try Another BIN", callback_data="claim_trial")]
            ]
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            conn.close()
            return
            
        card_texts = []
        for s_id, c_data in stock_items:
            cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
            card_texts.append(c_data)
            cursor.execute("INSERT INTO history (user_id, product_name, card_data, price) VALUES (?, ?, ?, ?)",
                           (user.id, f"FREE TRIAL ({p_name})", c_data, 0.0))
            
        set_claimed_trial(user.id)
        conn.commit()
        conn.close()
        
        msg = (
            f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🎉 *FREE TRIAL CLAIMED SUCCESSFULLY!*\n"
            f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"📦 *Item:* `Free Trial ({p_name})`\n"
            f"💳 *BIN:* `{input_bin}`\n\n"
            f"🔑 *YOUR 2 FREE CARDS:*\n"
            f"1️⃣ `{card_texts[0]}`\n"
            f"2️⃣ `{card_texts[1]}`\n\n"
            f"⚡ _Tap on the card details above to copy!_\n"
            f"❤️ *Enjoy your free trial!*"
        )
        keyboard = [[InlineKeyboardButton("🛍️ Browse Shop", callback_data="buy_menu")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----------------------------------------------------
# 6. ADMIN COMMAND HANDLERS
# ----------------------------------------------------
async def set_bkash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    try:
        number = context.args[0]
        set_setting("bkash", number)
        await update.message.reply_text(f"✅ *bKash Number Updated to:* `{number}`", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ *Usage:* `/setbkash <Number>`", parse_mode="Markdown")

async def remove_bkash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    set_setting("bkash", None)
    await update.message.reply_text("🗑️ *bKash Number Removed Successfully!*", parse_mode="Markdown")

async def set_nagad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    try:
        number = context.args[0]
        set_setting("nagad", number)
        await update.message.reply_text(f"✅ *Nagad Number Updated to:* `{number}`", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ *Usage:* `/setnagad <Number>`", parse_mode="Markdown")

async def remove_nagad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    set_setting("nagad", None)
    await update.message.reply_text("🗑️ *Nagad Number Removed Successfully!*", parse_mode="Markdown")

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
        
        for p_name, c_data, price, ts in rows[:15]:
            msg += f"📦 *{p_name}* — `${price:.2f}`\n"
            msg += f"💳 Card: `{c_data}`\n"
            msg += f"📅 Date: `{ts}`\n"
            msg += f"──────────────\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ *Usage:* `/userhistory <UserID>`", parse_mode="Markdown")

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
# 7. MAIN FUNCTION
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
    app.add_handler(CommandHandler("commands", commands_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    # Admin Handlers
    app.add_handler(CommandHandler("setbkash", set_bkash_cmd))
    app.add_handler(CommandHandler("removebkash", remove_bkash_cmd))
    app.add_handler(CommandHandler("setnagad", set_nagad_cmd))
    app.add_handler(CommandHandler("removenagad", remove_nagad_cmd))
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
