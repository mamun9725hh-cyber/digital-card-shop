import logging
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ----------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------
ADMIN_USERNAME = "Trusted_zone_1122"
CHANNEL_USERNAME = "@help_centre_1122"
CHANNEL_URL = "https://t.me/help_centre_1122"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ----------------------------------------------------
# 1. DUMMY HTTP SERVER (For 24/7 Hosting)
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
# 2. DATABASE SETUP
# ----------------------------------------------------
DB_NAME = "shop.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0.0,
            has_claimed_trial INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bin TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            card_data TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_name TEXT,
            card_data TEXT,
            price REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

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
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, balance, has_claimed_trial) VALUES (?, ?, 0.0, 0)",
        (user.id, user.username),
    )
    cursor.execute(
        "UPDATE users SET username = ? WHERE user_id = ?", (user.username, user.id)
    )
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
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id),
    )
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
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()

def has_claimed_trial(user_id) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT has_claimed_trial FROM users WHERE user_id = ?", (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return True if row and row[0] == 1 else False

def set_claimed_trial(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET has_claimed_trial = 1 WHERE user_id = ?", (user_id,)
    )
    conn.commit()
    conn.close()

async def is_user_joined(bot, user_id) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["creator", "administrator", "member"]:
            return True
        return False
    except Exception as e:
        logging.error(f"Error checking channel membership: {e}")
        return True

def get_commands_text(user):
    msg = (
        f"📖 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"📜 *ALL BOT COMMANDS GUIDE*\n"
        f"📖 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"👤 *USER COMMANDS:*\n"
        f"• `/start` — বটের মেইন মেনু ওপেন করতে\n"
        f"• `/buy` — শপ লিস্ট ও কার্ড কেনার ইন্টারফেস\n"
        f"• `/buycard <BIN>` — ১টি কার্ড কিনতে\n"
        f"• `/buycards <BIN> <Qty>` — একাধিক কার্ড কিনতে\n"
        f"• `/stock` — স্টকে কতগুলো কার্ড আছে দেখতে\n"
        f"• `/balance` — আপনার ব্যালেন্স ও রিচার্জ ইনফো দেখতে\n"
        f"• `/commands` — হেল্প গাইড দেখতে\n\n"
    )
    if is_admin(user):
        msg += (
            f"⚡ *ADMIN COMMANDS:*\n"
            f"• `/addcards <BIN> <Name> <Price>` — (ফাইলের রিপ্লাই দিয়ে কার্ড যোগ করতে)\n"
            f"• `/removecards <BIN>` — কোনো BIN ডিলিট করতে\n"
            f"• `/addbalance <UserID> <Amount>` — ইউজারের ব্যালেন্স যোগ করতে\n"
            f"• `/setbkash <Num>` — বিকাশ নম্বর সেট করতে\n"
            f"• `/setnagad <Num>` — নগদ নম্বর সেট করতে\n"
            f"• `/removebkash` — বিকাশ নম্বর ডিলিট করতে\n"
            f"• `/removenagad` — নগদ নম্বর ডিলিট করতে\n"
            f"• `/searchbin <BIN>` — BIN সার্চ করতে\n"
            f"• `/userhistory <UserID>` — ইউজার কেনাকাটার ইতিহাস\n"
            f"• `/downloadcards` — স্টকের ব্যাকআপ ফাইল পেতে\n"
            f"• `/downloaddb` — ডাটাবেজ ডাউনলোড করতে\n"
            f"• `/broadcast <Message>` — সবাইকে মেসেজ পাঠাতে\n"
        )
    return msg

def get_stock_text():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s ON p.id = s.product_id GROUP BY p.id"
    )
    products = cursor.fetchall()
    conn.close()

    if not products:
        return (
            f"📊 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"📦 *AVAILABLE CARD STOCK STATUS*\n"
            f"📊 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"⚠️ _বর্তমানে বটের স্টকে কোনো কার্ড নেই।_\n\n"
            f"📲 *যোগাযোগ করুন:* @{ADMIN_USERNAME}\n"
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
        msg += f"   🏷️ দাম: `৳{price:.2f}` | 📦 স্টক: {status}\n"
        msg += f"──────────────\n"

    msg += f"\n🔥 *মোট কার্ড স্টকে আছে:* `{total_cards}` টি\n"
    msg += f"💡 _কার্ড কিনতে 🛍️ Browse Cards Shop অপশনটি চাপুন।_"
    return msg

# ----------------------------------------------------
# 4. BOT MAIN COMMANDS
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)
    bal = get_user_balance(user.id)

    keyboard = [
        [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
        [InlineKeyboardButton("🎁 Free Trial (2 Cards)", callback_data="claim_trial")],
        [
            InlineKeyboardButton("📊 Available Stock", callback_data="view_stock"),
            InlineKeyboardButton("📜 All Commands", callback_data="all_commands"),
        ],
        [
            InlineKeyboardButton("💰 My Balance", callback_data="my_balance"),
            InlineKeyboardButton("📜 Purchase History", callback_data="my_history"),
        ],
        [InlineKeyboardButton("📢 Telegram Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
    ]

    if is_admin(user):
        keyboard.append([InlineKeyboardButton("⚡ Admin Control Panel", callback_data="admin_panel")])

    welcome_text = (
        f"✨ *━━━━━━━━━━━━━━━━━━━━*\n"
        f"👑 *PREMIUM DIGITAL CARD STORE* 👑\n"
        f"✨ *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"👋 *Welcome,* `{user.first_name}`!\n"
        f"🆔 *User ID:* `{user.id}`\n"
        f"💵 *Your Balance:* `৳{bal:.2f}`\n\n"
        f"🚀 *Instant Automated Delivery 24/7!*\n"
        f"👇 *নিচের অপশন থেকে বেছে নিন:*"
    )

    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = get_commands_text(user)
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_stock_text()
    keyboard = [
        [InlineKeyboardButton("🛍️ Go To Shop", callback_data="buy_menu")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")],
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bal = get_user_balance(user.id)
    bkash_num = get_setting("bkash")
    nagad_num = get_setting("nagad")

    payment_info = ""
    if bkash_num or nagad_num:
        payment_info += "\n\n📲 *PAYMENT METHODS (TOP-UP):*\n"
        if bkash_num:
            payment_info += f"🌸 *bKash (Personal):* `{bkash_num}`\n"
        if nagad_num:
            payment_info += f"🟠 *Nagad (Personal):* `{nagad_num}`\n"
        payment_info += "\n⚠️ _টাকা পাঠানোর পর Transaction ID ও আপনার User ID সহ এডমিনকে জানান।_\n"

    msg = f"💵 *Your Current Balance:* `৳{bal:.2f}`{payment_info}\n👨‍💻 *Admin:* @{ADMIN_USERNAME}"
    keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----------------------------------------------------
# 5. SHOP & CARD PURCHASE ENGINE
# ----------------------------------------------------
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT p.id, p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s ON p.id = s.product_id GROUP BY p.id"
    )
    products = cursor.fetchall()
    conn.close()

    if not products:
        await update.message.reply_text("⚠️ *বর্তমানে শপ সম্পূর্ণ খালি!*", parse_mode="Markdown")
        return

    keyboard = []
    for p_id, p_bin, name, price, stock_count in products:
        btn_text = f"🛒 Buy {p_bin} ({name}) — ৳{price:.2f} [{stock_count} Stock]" if stock_count > 0 else f"❌ {p_bin} - Out of Stock"
        cb_data = f"buy_prod_{p_id}" if stock_count > 0 else "out_of_stock_alert"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_data)])

    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")])

    msg = (
        f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"🔥 *AVAILABLE CARDS STORE*\n"
        f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"👇 *যে কার্ডটি কিনতে চান সেটির ওপর সিলেক্ট করুন:*"
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def buycard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)

    if not context.args:
        await update.message.reply_text(
            "❌ *সঠিক নিয়ম:* `/buycard <BIN>`\n_যেমন:_ `/buycard 416598`",
            parse_mode="Markdown",
        )
        return

    target_bin = context.args[0].strip()
    await process_card_purchase(update, user, target_bin, quantity=1)

async def buycards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_or_update_user(user)

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ *সঠিক নিয়ম:* `/buycards <BIN> <Quantity>`\n_যেমন:_ `/buycards 416598 5`",
            parse_mode="Markdown",
        )
        return

    target_bin = context.args[0].strip()
    try:
        qty = int(context.args[1])
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ *ভুল সংখ্যা দেওয়া হয়েছে!*", parse_mode="Markdown")
        return

    await process_card_purchase(update, user, target_bin, quantity=qty)

async def process_card_purchase(update: Update, user, target_bin: str, quantity: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, price FROM products WHERE bin = ?", (target_bin,))
    prod = cursor.fetchone()

    is_callback = update.callback_query is not None

    async def send_msg(text, reply_markup=None):
        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    if not prod:
        await send_msg(f"❌ *BIN `{target_bin}` স্টকে খুঁজে পাওয়া যায়নি!*")
        conn.close()
        return

    p_id, p_name, p_price = prod
    total_cost = p_price * quantity
    user_bal = get_user_balance(user.id)

    if user_bal < total_cost:
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await send_msg(
            f"❌ *পর্যাপ্ত ব্যালেন্স নেই!*\n\n"
            f"💳 *BIN:* `{target_bin}`\n"
            f"📦 *পরিমাণ:* `{quantity}` টি\n"
            f"🏷️ *মোট লাগবে:* `৳{total_cost:.2f}`\n"
            f"💵 *আপনার ব্যালেন্স:* `৳{user_bal:.2f}`\n\n"
            f"📲 *এডমিন থেকে ব্যালেন্স রিচার্জ করুন:* @{ADMIN_USERNAME}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        conn.close()
        return

    cursor.execute("SELECT id, card_data FROM stock WHERE product_id = ? LIMIT ?", (p_id, quantity))
    stock_items = cursor.fetchall()

    if len(stock_items) < quantity:
        await send_msg(f"❌ *স্টক কম আছে!*\n\n`{target_bin}` BIN-এ রয়েছে `{len(stock_items)}` টি কার্ড। আপনার প্রয়োজন `{quantity}` টি।")
        conn.close()
        return

    purchased_cards = []
    for s_id, card_data in stock_items:
        cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
        purchased_cards.append(card_data)
        cursor.execute(
            "INSERT INTO history (user_id, product_name, card_data, price) VALUES (?, ?, ?, ?)",
            (user.id, f"{p_name} (BIN: {target_bin})", card_data, p_price),
        )

    cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (total_cost, user.id))
    conn.commit()
    conn.close()

    cards_text = "\n".join([f"`{c}`" for c in purchased_cards])
    keyboard = [
        [InlineKeyboardButton("🛍️ Buy More Cards", callback_data="buy_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="start_menu")],
    ]
    msg = (
        f"🎉 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"✅ *PURCHASE SUCCESSFUL!*\n"
        f"🎉 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"📦 *Item:* `{p_name}`\n"
        f"💳 *BIN:* `{target_bin}`\n"
        f"📊 *Quantity:* `{quantity}` টি\n"
        f"💵 *Total Paid:* `৳{total_cost:.2f}`\n\n"
        f"🔑 *YOUR CARDS DETAILS:*\n"
        f"{cards_text}\n\n"
        f"⚡ _কপি করার জন্য কার্ডের ওপর আলতো চাপুন!_\n"
        f"❤️ *আমাদের সাথে থাকার জন্য ধন্যবাদ!*"
    )
    await send_msg(msg, reply_markup=InlineKeyboardMarkup(keyboard))

# ----------------------------------------------------
# 6. CALLBACK QUERY BUTTON HANDLERS
# ----------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data == "start_menu":
        context.user_data["awaiting_trial_bin"] = False
        bal = get_user_balance(user.id)
        keyboard = [
            [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
            [InlineKeyboardButton("🎁 Free Trial (2 Cards)", callback_data="claim_trial")],
            [
                InlineKeyboardButton("📊 Available Stock", callback_data="view_stock"),
                InlineKeyboardButton("📜 All Commands", callback_data="all_commands"),
            ],
            [
                InlineKeyboardButton("💰 My Balance", callback_data="my_balance"),
                InlineKeyboardButton("📜 Purchase History", callback_data="my_history"),
            ],
            [InlineKeyboardButton("📢 Telegram Channel", url=CHANNEL_URL)],
            [InlineKeyboardButton("👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")],
        ]
        if is_admin(user):
            keyboard.append([InlineKeyboardButton("⚡ Admin Control Panel", callback_data="admin_panel")])

        welcome_text = (
            f"✨ *━━━━━━━━━━━━━━━━━━━━*\n"
            f"👑 *PREMIUM DIGITAL CARD STORE* 👑\n"
            f"✨ *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👋 *Welcome,* `{user.first_name}`!\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💵 *Your Balance:* `৳{bal:.2f}`\n\n"
            f"🚀 *Instant Automated Delivery 24/7!*\n"
            f"👇 *নিচের অপশন থেকে আপনার পছন্দের অপশনটি বেছে নিন:*"
        )
        await query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "all_commands":
        msg = get_commands_text(user)
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "view_stock":
        msg = get_stock_text()
        keyboard = [
            [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")],
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "out_of_stock_alert":
        await query.answer("❌ এই কার্ডটি বর্তমানে স্টকে নেই!", show_alert=True)

    elif data == "buy_menu":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT p.id, p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s ON p.id = s.product_id GROUP BY p.id"
        )
        products = cursor.fetchall()
        conn.close()

        if not products:
            msg = "⚠️ *বর্তমানে স্টকে কোনো প্রোডাক্ট পাওয়া যায়নি!*"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        keyboard = []
        for p_id, p_bin, name, price, stock_count in products:
            if stock_count > 0:
                btn_text = f"🛒 Buy {p_bin} ({name}) — ৳{price:.2f} [{stock_count} Stock]"
                cb_data = f"buy_prod_{p_id}"
            else:
                btn_text = f"❌ {p_bin} ({name}) — Out of Stock"
                cb_data = "out_of_stock_alert"

            keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_data)])

        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")])

        msg = (
            f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🔥 *SELECT CARD TO PURCHASE*\n"
            f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👇 *যে কার্ডটি কিনতে চান সেটির ওপর ক্লিক করুন:*"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("buy_prod_"):
        p_id = int(data.split("_")[2])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT bin FROM products WHERE id = ?", (p_id,))
        prod = cursor.fetchone()
        conn.close()

        if prod:
            target_bin = prod[0]
            await process_card_purchase(update, user, target_bin, quantity=1)

    elif data == "claim_trial":
        joined = await is_user_joined(context.bot, user.id)
        if not joined:
            msg = f"⚠️ *MUST JOIN OUR TELEGRAM CHANNEL!*\n\nফ্রি ট্রায়াল নেওয়ার জন্য আপনাকে অবশ্যই চ্যানেলটিতে জয়েন করতে হবে।"
            keyboard = [
                [InlineKeyboardButton("📢 Join Telegram Channel", url=CHANNEL_URL)],
                [InlineKeyboardButton("🔄 Claim Trial Again", callback_data="claim_trial")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")],
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        if has_claimed_trial(user.id):
            msg = "❌ *TRIAL ALREADY CLAIMED!*\n\n_আপনি ইতোমধ্যেই ১-বারের ফ্রি ট্রায়াল ব্যবহার করেছেন। পরবর্তীতে কিনতে চাইলে শপ ব্যবহার করুন।_"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        context.user_data["awaiting_trial_bin"] = True
        msg = (
            f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🔍 *ENTER BIN FOR FREE TRIAL*\n"
            f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"আপনি যে BIN থেকে **২টি কার্ড** ফ্রি ট্রায়াল নিতে চান, সেটির **6-Digit BIN** লিখে পাঠান।\n\n"
            f"💡 *Example:* `416598`"
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
            payment_info += "\n⚠️ _টাকা পাঠানোর পর Transaction ID ও আপনার User ID সহ এডমিনকে জানান।_\n"

        msg = (
            f"💳 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"📊 *ACCOUNT BALANCE SUMMARY*\n"
            f"💳 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"👤 *User:* `{user.first_name}`\n"
            f"🆔 *User ID:* `{user.id}`\n"
            f"💎 *Current Balance:* `৳{bal:.2f}`\n"
            f"{payment_info}\n"
            f"👨‍💻 *Admin:* @{ADMIN_USERNAME}"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "my_history":
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT product_name, card_data, price, timestamp FROM history WHERE user_id = ? ORDER BY id DESC LIMIT 10",
            (user.id,),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            msg = "📜 *PURCHASE HISTORY*\n\n_আপনি এখনও কোনো কার্ড কেনেননি!_"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        msg = f"📜 *YOUR PURCHASE HISTORY*\n\n"
        for p_name, c_data, price, ts in rows:
            msg += f"📦 *{p_name}* — `৳{price:.2f}`\n"
            msg += f"💳 Details: `{c_data}`\n"
            msg += f"📅 Date: `{ts}`\n"
            msg += f"──────────────\n"

        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_panel":
        if not is_admin(user):
            return

        msg = (
            f"⚡ *ADMIN CONTROL PANEL*\n\n"
            f"👉 `/addcards <BIN> <Name> <Price>`\n"
            f"_(ফাইল বা টেক্সট মেসেজের ওপর Reply দিন)_\n"
            f"👉 `/removecards <BIN>`\n"
            f"👉 `/addbalance <UserID> <Amount>`\n"
            f"👉 `/setbkash <Num>` | `/setnagad <Num>`\n"
            f"👉 `/userhistory <UserID>`\n"
            f"👉 `/broadcast <Message>`"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----------------------------------------------------
# 7. TEXT HANDLER (FIXED FREE TRIAL ENGINE)
# ----------------------------------------------------
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # ১. ফ্রি ট্রায়াল চেক হ্যান্ডলার
    if context.user_data.get("awaiting_trial_bin"):
        context.user_data["awaiting_trial_bin"] = False
        input_bin = text.split()[0]

        if has_claimed_trial(user.id):
            await update.message.reply_text(
                "❌ *আপনি ইতোমধ্যেই ১-বারের ফ্রি ট্রায়াল ২টা কার্ড ক্লেইম করেছেন!*",
                parse_mode="Markdown",
            )
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM products WHERE bin = ?", (input_bin,))
        prod = cursor.fetchone()

        if not prod:
            await update.message.reply_text(
                f"❌ *BIN `{input_bin}` স্টকে পাওয়া যায়নি! অন্য BIN দিয়ে চেষ্টা করুন।*", parse_mode="Markdown"
            )
            conn.close()
            return

        p_id, p_name = prod
        cursor.execute("SELECT id, card_data FROM stock WHERE product_id = ? LIMIT 2", (p_id,))
        stock_items = cursor.fetchall()

        if len(stock_items) < 2:
            await update.message.reply_text(
                f"⚠️ `{input_bin}` BIN-এ ফ্রি ট্রায়াল দেওয়ার মতো পর্যাপ্ত (কমপক্ষে ২টা) কার্ড স্টকে নেই।",
                parse_mode="Markdown",
            )
            conn.close()
            return

        card_texts = []
        for s_id, c_data in stock_items:
            cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
            card_texts.append(c_data)
            cursor.execute(
                "INSERT INTO history (user_id, product_name, card_data, price) VALUES (?, ?, ?, ?)",
                (user.id, f"FREE TRIAL ({p_name})", c_data, 0.0),
            )

        set_claimed_trial(user.id)
        conn.commit()
        conn.close()

        cards_formatted = "\n".join([f"`{c}`" for c in card_texts])

        msg = (
            f"🎉 *━━━━━━━━━━━━━━━━━━━━*\n"
            f"🎁 *FREE TRIAL CLAIMED SUCCESS!*\n"
            f"🎉 *━━━━━━━━━━━━━━━━━━━━*\n\n"
            f"📦 *Item:* `{p_name}`\n"
            f"💳 *BIN:* `{input_bin}`\n"
            f"📊 *Quantity:* `2` টি (মেইন স্টক থেকে ডেলিভারি হয়েছে)\n\n"
            f"🔑 *YOUR FREE CARDS:*\n"
            f"{cards_formatted}\n\n"
            f"⚠️ _নোট: আপনি সফলভাবে ১-বারের ফ্রি ট্রায়াল ২টা কার্ড পেয়েছেন।_"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----------------------------------------------------
# 8. ADMIN COMMANDS
# ----------------------------------------------------
async def add_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return

    reply_msg = update.message.reply_to_message
    cards = []

    if reply_msg:
        if reply_msg.document:
            file = await context.bot.get_file(reply_msg.document.file_id)
            file_bytes = await file.download_as_bytearray()
            content = file_bytes.decode("utf-8", errors="ignore")
            cards = [line.strip() for line in content.split("\n") if line.strip()]
        elif reply_msg.text:
            cards = [line.strip() for line in reply_msg.text.split("\n") if line.strip()]
    else:
        text_lines = update.message.text.split("\n")
        cards = [line.strip() for line in text_lines[1:] if line.strip()]

    try:
        cmd_parts = update.message.text.split("\n")[0].split()
        bin_code = cmd_parts[1]
        price = float(cmd_parts[-1])
        p_name = " ".join(cmd_parts[2:-1]) if len(cmd_parts) > 3 else f"BIN {bin_code}"

        if not cards:
            await update.message.reply_text(
                "❌ *কোনো কার্ড ড্যাটা খুঁজে পাওয়া যায়নি!*",
                parse_mode="Markdown",
            )
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO products (bin, name, price) VALUES (?, ?, ?)",
            (bin_code, p_name, price),
        )
        cursor.execute(
            "UPDATE products SET price = ?, name = ? WHERE bin = ?",
            (price, p_name, bin_code),
        )
        cursor.execute("SELECT id FROM products WHERE bin = ?", (bin_code,))
        p_id = cursor.fetchone()[0]

        for c in cards:
            cursor.execute("INSERT INTO stock (product_id, card_data) VALUES (?, ?)", (p_id, c))

        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"🎉 *BIN `{bin_code}` ({p_name}) এর জন্য সফলভাবে `{len(cards)}` টি কার্ড যোগ হয়েছে!*\n🏷️ দাম: `৳{price:.2f}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ *সঠিক নিয়ম:*\n1. ফাইল/টেক্সটের **Reply** দিয়ে লিখুন: `/addcards 416598 Visa 50.50`",
            parse_mode="Markdown",
        )

async def remove_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    if not context.args:
        await update.message.reply_text("❌ *Usage:* `/removecards <BIN>`", parse_mode="Markdown")
        return

    bin_code = context.args[0].strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM products WHERE bin = ?", (bin_code,))
    prod = cursor.fetchone()

    if not prod:
        await update.message.reply_text(f"❌ *BIN `{bin_code}` পাওয়া যায়নি!*", parse_mode="Markdown")
        conn.close()
        return

    p_id = prod[0]
    cursor.execute("DELETE FROM stock WHERE product_id = ?", (p_id,))
    cursor.execute("DELETE FROM products WHERE id = ?", (p_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🗑️ *BIN `{bin_code}` এর সকল ডাটা ও স্টক রিমুভ হয়েছে!*",
        parse_mode="Markdown",
    )

async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    try:
        t_id = int(context.args[0])
        amt = float(context.args[1])
        update_user_balance(t_id, amt)
        await update.message.reply_text(
            f"✅ *ব্যালেন্স আপডেট সফল!*\n👤 User ID: `{t_id}`\n💵 Added: `৳{amt:.2f}`",
            parse_mode="Markdown",
        )
    except:
        await update.message.reply_text("❌ `/addbalance <UserID> <Amount>`", parse_mode="Markdown")

async def set_bkash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    try:
        set_setting("bkash", context.args[0])
        await update.message.reply_text(f"✅ *bKash নম্বর সেট করা হয়েছে:* `{context.args[0]}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ `/setbkash <Num>`", parse_mode="Markdown")

async def remove_bkash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    set_setting("bkash", None)
    await update.message.reply_text("🗑️ *bKash নম্বর রিমুভ করা হয়েছে!*", parse_mode="Markdown")

async def set_nagad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    try:
        set_setting("nagad", context.args[0])
        await update.message.reply_text(f"✅ *Nagad নম্বর সেট করা হয়েছে:* `{context.args[0]}`", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ `/setnagad <Num>`", parse_mode="Markdown")

async def remove_nagad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    set_setting("nagad", None)
    await update.message.reply_text("🗑️ *Nagad নম্বর রিমুভ করা হয়েছে!*", parse_mode="Markdown")

async def user_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    try:
        t_id = int(context.args[0])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, card_data, price, timestamp FROM history WHERE user_id = ? ORDER BY id DESC", (t_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("⚠️ এই ইউজারের কোনো হিস্ট্রি পাওয়া যায়নি।", parse_mode="Markdown")
            return

        msg = f"📜 *HISTORY FOR USER:* `{t_id}`\n\n"
        for p_name, c_data, price, ts in rows[:15]:
            msg += f"📦 *{p_name}* — `৳{price:.2f}`\n`{c_data}`\n📅 `{ts}`\n──────────────\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ `/userhistory <UserID>`", parse_mode="Markdown")

async def download_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT p.bin, p.name, p.price, s.card_data FROM stock s JOIN products p ON s.product_id = p.id")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("⚠️ স্টকে কোনো কার্ড নেই।", parse_mode="Markdown")
        return

    file_path = "cards_backup.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        for p_bin, p_name, price, card in rows:
            f.write(f"BIN: {p_bin} | {p_name} | ৳{price:.2f} | Card: {card}\n")

    await update.message.reply_document(document=open(file_path, "rb"), caption="📦 *Stock Backup File*", parse_mode="Markdown")
    if os.path.exists(file_path):
        os.remove(file_path)

async def download_db_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    if os.path.exists(DB_NAME):
        await update.message.reply_document(document=open(DB_NAME, "rb"), caption="💾 *SQLite Database Backup*", parse_mode="Markdown")

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
            await update.message.reply_text(f"❌ BIN `{bin_code}` খুঁজে পাওয়া যায়নি।", parse_mode="Markdown")
            return

        name, price, stock = res
        await update.message.reply_text(
            f"🔎 *BIN Info:*\n💳 BIN: `{bin_code}`\n📦 Name: `{name}`\n🏷️ Price: `৳{price:.2f}`\n📊 Available Stock: `{stock}`",
            parse_mode="Markdown",
        )
    except:
        await update.message.reply_text("❌ `/searchbin <BIN>`", parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        return
    msg_text = " ".join(context.args)
    if not msg_text:
        await update.message.reply_text("❌ `/broadcast <Your Message>`", parse_mode="Markdown")
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    count = 0
    for (u_id,) in users:
        try:
            await context.bot.send_message(chat_id=u_id, text=f"📢 *BROADCAST ANNOUNCEMENT*\n\n{msg_text}", parse_mode="Markdown")
            count += 1
        except:
            pass
    await update.message.reply_text(f"📢 সফলভাবে `{count}` জন ইউজারের কাছে মেসেজ পাঠানো হয়েছে!", parse_mode="Markdown")

# ----------------------------------------------------
# 9. MAIN RUNNER (CORRECTED HANDLER ORDER)
# ----------------------------------------------------
def main():
    server_thread = Thread(target=run_dummy_server, daemon=True)
    server_thread.start()

    token = os.environ.get("BOT_TOKEN")
    if not token:
        logging.error("BOT_TOKEN variable is missing in environment!")
        return

    app = Application.builder().token(token).build()

    # Admin Handlers
    app.add_handler(CommandHandler("addcards", add_cards_cmd))
    app.add_handler(CommandHandler("removecards", remove_cards_cmd))
    app.add_handler(CommandHandler("addbalance", add_balance_cmd))
    app.add_handler(CommandHandler("setbkash", set_bkash_cmd))
    app.add_handler(CommandHandler("removebkash", remove_bkash_cmd))
    app.add_handler(CommandHandler("setnagad", set_nagad_cmd))
    app.add_handler(CommandHandler("removenagad", remove_nagad_cmd))
    app.add_handler(CommandHandler("userhistory", user_history_cmd))
    app.add_handler(CommandHandler("downloadcards", download_cards_cmd))
    app.add_handler(CommandHandler("downloaddb", download_db_cmd))
    app.add_handler(CommandHandler("searchbin", search_bin_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    # User Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("buycard", buycard_cmd))
    app.add_handler(CommandHandler("buycards", buycards_cmd))
    app.add_handler(CommandHandler("commands", commands_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("balance", balance_command))

    # Callback Button Handler
    app.add_handler(CallbackQueryHandler(button_handler))

    # TEXT MESSAGE HANDLER (CRITICAL FIX FOR FREE TRIAL TEXT INPUT)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_message_handler))

    logging.info("Bot execution started...")
    app.run_polling()

if __name__ == "__main__":
    main()
