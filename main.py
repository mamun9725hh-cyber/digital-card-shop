import logging
import asyncio
import os
import io
import psycopg2
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Dummy Web Server for Keeping Render Alive
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"24/7 Digital Card Shop Bot Server is Active!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    logging.info(f"Dummy HTTP server listening on port {port}")
    server.serve_forever()

# CONFIGURATION
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8685485545:AAGZEkOca5fQmO1SWrbzuhKy59eDUOY4EbM")
ADMIN_USERNAME = "Trusted_zone_1122"
ADMIN_ID = 7624991230

# Database Setup
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        import sqlite3
        return sqlite3.connect("bot_data.db")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            bin TEXT,
            card_details TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            bin TEXT,
            card_details TEXT,
            bought_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT INTO settings (key, value) VALUES ('price', '30.0') ON CONFLICT DO NOTHING")
    cursor.execute("INSERT INTO settings (key, value) VALUES ('bkash', 'নম্বর সেট করা হয়নি') ON CONFLICT DO NOTHING")
    cursor.execute("INSERT INTO settings (key, value) VALUES ('nagad', 'নম্বর সেট করা হয়নি') ON CONFLICT DO NOTHING")
    conn.commit()
    conn.close()

# Database Helpers
def get_user_balance(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (%s, 0.0)", (user_id,))
        conn.commit()
        bal = 0.0
    else:
        bal = row[0]
    conn.close()
    return bal

def update_user_balance(user_id, amount_change):
    current = get_user_balance(user_id)
    new_bal = current + amount_change
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = %s WHERE user_id = %s", (new_bal, user_id))
    conn.commit()
    conn.close()
    return new_bal

def get_all_user_ids():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_setting(key):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = %s WHERE key = %s", (str(value), key))
    conn.commit()
    conn.close()

def get_cards_by_bin(bin_num):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, card_details FROM cards WHERE bin = %s", (bin_num,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_stock_cards():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT bin, card_details FROM cards ORDER BY bin")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_bins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT bin, COUNT(*) FROM cards GROUP BY bin")
    rows = cursor.fetchall()
    conn.close()
    return rows

def add_single_card(bin_num, card_details):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO cards (bin, card_details) VALUES (%s, %s)", (bin_num, card_details))
    conn.commit()
    conn.close()

def pop_cards(user_id, bin_num, qty):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, card_details FROM cards WHERE bin = %s LIMIT %s", (bin_num, qty))
    rows = cursor.fetchall()
    
    delivered = []
    ids_to_delete = []
    for r in rows:
        ids_to_delete.append(r[0])
        delivered.append(r[1])
        cursor.execute("INSERT INTO orders (user_id, bin, card_details) VALUES (%s, %s, %s)", (user_id, bin_num, r[1]))
        
    if ids_to_delete:
        cursor.execute("DELETE FROM cards WHERE id = ANY(%s)", (ids_to_delete,))
        conn.commit()
    conn.close()
    return delivered

def delete_bin_stock(bin_num):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cards WHERE bin = %s", (bin_num,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def get_user_orders(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT bin, card_details FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 15", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows

user_states = {}

# USER HANDLERS
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    balance = get_user_balance(user_id)
    price = get_setting("price")

    keyboard = [
        [InlineKeyboardButton("🔍 Search BIN / Buy Card", callback_data="start_search_bin")],
        [InlineKeyboardButton("📦 All Available Stock", callback_data="show_all_stock")],
        [InlineKeyboardButton("💰 My Balance", callback_data="my_balance"), InlineKeyboardButton("➕ Add Balance", callback_data="add_balance_start")],
        [InlineKeyboardButton("📜 My Purchase History", callback_data="my_history")],
        [InlineKeyboardButton("👤 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"👋 **হ্যালো {user.first_name}!**\n\n"
        f"আমাদের অটোমেটেড ডিজিটাল কার্ড শপ বটে স্বাগতম।\n"
        f"ইনস্ট্যান্ট ডেলিভারিসহ BIN অনুযায়ী কার্ড কিনতে পারবেন।\n\n"
        f"📌 **প্রতি কার্ডের দাম:** {price} BDT\n"
        f"💳 **আপনার ব্যালেন্স:** {balance} BDT\n"
        f"🆔 **আপনার ইউজার আইডি:** `{user_id}`"
    )

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        query = update.callback_query
        await query.answer()
        await query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "my_balance":
        bal = get_user_balance(user_id)
        await query.message.reply_text(f"💰 **আপনার বর্তমান ব্যালেন্স:** {bal} BDT\n🆔 **আপনার আইডি:** `{user_id}`", parse_mode="Markdown")

    elif query.data == "my_history":
        orders = get_user_orders(user_id)
        if not orders:
            await query.message.reply_text("📜 আপনি এখনও কোনো কার্ড ক্রয় করেননি।")
            return
        history_text = "📜 **আপনার সাম্প্রতিক ক্রয় করা কার্ডসমূহ:**\n\n"
        for bin_num, details in orders:
            history_text += f"🔹 BIN: `{bin_num}` | `{details}`\n"
        await query.message.reply_text(history_text, parse_mode="Markdown")

    elif query.data == "add_balance_start":
        bkash = get_setting("bkash")
        nagad = get_setting("nagad")
        
        text = (
            f"➕ **ব্যালেন্স রিচার্জ নিয়ম:**\n\n"
            f"নিচের নম্বরে **Send Money** বা **Cash In** করুন:\n"
            f"📱 **বিকাশ:** `{bkash}`\n"
            f"📱 **নগদ:** `{nagad}`\n\n"
            f"পেমেন্ট শেষ করে বাটন সিলেক্ট করুন:"
        )
        keyboard = [
            [InlineKeyboardButton("বিকাশ (bKash)", callback_data="deposit_method_bKash"), InlineKeyboardButton("নগদ (Nagad)", callback_data="deposit_method_Nagad")]
        ]
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data.startswith("deposit_method_"):
        method = query.data.split("_")[2]
        user_states[user_id] = {"step": "WAITING_DEPOSIT_AMOUNT", "method": method}
        await query.message.reply_text(f"💵 **কত টাকা পাঠিয়েছেন লিখুন:**\n(যেমন: `100` বা `500`)", parse_mode="Markdown")

    elif query.data == "start_search_bin":
        user_states[user_id] = {"step": "WAITING_FOR_BIN"}
        await query.message.reply_text("🔍 **যে BIN সার্চ বা কিনতে চান তা লিখুন:**\n(যেমন: `414720`)", parse_mode="Markdown")

    elif query.data == "show_all_stock":
        bins = get_all_bins()
        if not bins:
            await query.message.reply_text("📦 বর্তমানে কোনো কার্ড স্টকে নেই।")
            return

        keyboard = []
        for bin_num, count in bins:
            if count > 0:
                keyboard.append([InlineKeyboardButton(f"🔹 BIN: {bin_num} (স্টক: {count} টি)", callback_data=f"checkbin_{bin_num}")])

        if not keyboard:
            await query.message.reply_text("📦 বর্তমানে সকল BIN-এর স্টক খালি।")
            return

        await query.message.reply_text("📦 **স্টকে থাকা সকল BIN এর তালিকা:**", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("checkbin_"):
        bin_num = query.data.split("_")[1]
        await process_bin_check(query.message, user_id, bin_num)

    elif query.data.startswith("buy_"):
        parts = query.data.split("_")
        bin_num = parts[1]
        qty = int(parts[2])

        cards = get_cards_by_bin(bin_num)
        if len(cards) < qty:
            await query.message.reply_text("❌ দুঃখিত, পর্যাপ্ত স্টক নেই।")
            return

        price_per_card = float(get_setting("price"))
        total_cost = price_per_card * qty
        current_bal = get_user_balance(user_id)

        if current_bal < total_cost:
            await query.message.reply_text(
                f"❌ **পর্যাপ্ত ব্যালেন্স নেই!**\n\n"
                f"📊 **প্রয়োজন:** {total_cost} BDT ({qty} টি)\n"
                f"💳 **আপনার ব্যালেন্স:** {current_bal} BDT\n\n"
                f"রিচার্জ করতে **Add Balance** ব্যবহার করুন।",
                parse_mode="Markdown"
            )
            return

        update_user_balance(user_id, -total_cost)
        delivered_cards = pop_cards(user_id, bin_num, qty)
        cards_text = "\n".join([f"`{c}`" for c in delivered_cards])
        rem_bal = get_user_balance(user_id)

        await query.message.reply_text(
            f"🎉 **কার্ড ক্রয় সফল হয়েছে! ({qty} টি)**\n\n"
            f"📌 **BIN:** `{bin_num}`\n"
            f"💳 **কার্ডসমূহ:**\n{cards_text}\n\n"
            f"💰 **মোট খরচ:** {total_cost} BDT\n"
            f"💳 **অবশিষ্ট ব্যালেন্স:** {rem_bal} BDT\n\n"
            f"ধন্যবাদ!",
            parse_mode="Markdown"
        )

    # Admin Callbacks
    elif query.data.startswith("approve_dep_"):
        if query.from_user.id != ADMIN_ID:
            return
        parts = query.data.split("_")
        target_user_id = int(parts[2])
        amount = float(parts[3])

        new_bal = update_user_balance(target_user_id, amount)
        await query.message.edit_text(f"{query.message.text}\n\n✅ **Approved!** ইউজার ব্যালেন্স যুক্ত হয়েছে।")
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 **আপনার ব্যালেন্স রিচার্জ সফল হয়েছে!**\n\n💰 **যোগ করা হয়েছে:** {amount} BDT\n💳 **বর্তমান ব্যালেন্স:** {new_bal} BDT",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    elif query.data.startswith("reject_dep_"):
        if query.from_user.id != ADMIN_ID:
            return
        parts = query.data.split("_")
        target_user_id = int(parts[2])

        await query.message.edit_text(f"{query.message.text}\n\n❌ **Rejected!**")
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"❌ **আপনার ব্যালেন্স রিচার্জ রিকোয়েস্টটি বাতিল করা হয়েছে!**",
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def handle_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text.strip() if update.message.text else ""

    state_info = user_states.get(user_id)

    if isinstance(state_info, dict):
        step = state_info.get("step")

        if step == "WAITING_FOR_BIN":
            user_states[user_id] = None
            bin_num = text.split()[0]
            await process_bin_check(update.message, user_id, bin_num)

        elif step == "WAITING_DEPOSIT_AMOUNT":
            try:
                amount = float(text)
                if amount <= 0:
                    raise ValueError()
                user_states[user_id] = {
                    "step": "WAITING_DEPOSIT_TRX",
                    "method": state_info.get("method"),
                    "amount": amount
                }
                await update.message.reply_text(f"📝 **আপনার পেমেন্টের TrxID টি পাঠান:**", parse_mode="Markdown")
            except ValueError:
                await update.message.reply_text("❌ ভুল পরিমাণ! সঠিক সংখ্যা লিখুন (যেমন: 200)।")

        elif step == "WAITING_DEPOSIT_TRX":
            trx_id = text
            method = state_info.get("method")
            amount = state_info.get("amount")
            user_states[user_id] = None

            await update.message.reply_text(
                f"✅ **রিকোয়েস্ট জমা নেওয়া হয়েছে!**\n\n"
                f"💳 **মেথড:** {method}\n"
                f"💵 **পরিমাণ:** {amount} BDT\n"
                f"🧾 **TrxID:** `{trx_id}`\n\n"
                f"এডমিন চেক করে যুক্ত করে দেবে।",
                parse_mode="Markdown"
            )

            admin_text = (
                f"📥 **নতুন ডিপোজিট রিকোয়েস্ট!**\n\n"
                f"👤 **ইউজার:** {user_name} (`{user_id}`)\n"
                f"💳 **মেথড:** {method}\n"
                f"💵 **পরিমাণ:** {amount} BDT\n"
                f"🧾 **TrxID:** `{trx_id}`"
            )
            admin_keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_dep_{user_id}_{amount}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_dep_{user_id}")
                ]
            ]
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                reply_markup=InlineKeyboardMarkup(admin_keyboard),
                parse_mode="Markdown"
            )

async def process_bin_check(message_obj, user_id, bin_num):
    cards = get_cards_by_bin(bin_num)
    if not cards:
        await message_obj.reply_text(f"❌ **দুঃখিত!** BIN `{bin_num}`-এর কোনো কার্ড স্টকে নেই।", parse_mode="Markdown")
        return

    available_qty = len(cards)
    price_per_card = float(get_setting("price"))

    qty_options = [1, 2, 3, 5, 10, 20, 50]
    keyboard = []
    row = []

    for q in qty_options:
        if q <= available_qty:
            row.append(InlineKeyboardButton(f"🛒 {q} টি ({q * price_per_card} BDT)", callback_data=f"buy_{bin_num}_{q}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
    if row:
        keyboard.append(row)

    await message_obj.reply_text(
        f"✅ **BIN `{bin_num}` এভেলেবেল আছে!**\n\n"
        f"📦 **স্টক:** {available_qty} টি\n"
        f"📌 **দাম:** {price_per_card} BDT\n\n"
        f"👇 **কয়টি কিনতে চান সিলেক্ট করুন:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ADMIN COMMANDS
def is_admin(user_id):
    return user_id == ADMIN_ID

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    users_count = len(get_all_user_ids())
    all_cards = get_all_stock_cards()
    all_bins = get_all_bins()

    stat_text = (
        f"📊 **বটের ওভারঅল স্ট্যাটিস্টিক্স:**\n\n"
        f"👥 **মোট ইউজার:** {users_count} জন\n"
        f"📦 **মোট কার্ড স্টক:** {len(all_cards)} টি\n"
        f"🔹 **অ্যাক্টিভ BIN সংখ্যা:** {len(all_bins)} টি"
    )
    await update.message.reply_text(stat_text, parse_mode="Markdown")

async def download_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    stock_cards = get_all_stock_cards()
    if not stock_cards:
        await update.message.reply_text("❌ স্টকে কোনো কার্ড নেই। ব্যাকআপ নেওয়ার কিছু পাওয়া যায়নি।")
        return

    file_content = ""
    current_bin = None
    for bin_num, card_details in stock_cards:
        if bin_num != current_bin:
            file_content += f"\n/addcards {bin_num}\n"
            current_bin = bin_num
        file_content += f"{card_details}\n"

    file_bytes = io.BytesIO(file_content.strip().encode('utf-8'))
    file_bytes.name = "remaining_stock_backup.txt"

    await update.message.reply_document(
        document=InputFile(file_bytes),
        caption=f"📦 **অবশিষ্ট স্টকের ব্যাকআপ ফাইল!**\n\nমোট কার্ড: {len(stock_cards)} টি।\nবট আপডেট করার পর এই টেক্সট ফাইল থেকে সরাসরি আবার কন্টেন্ট এড দিতে পারবেন।",
        parse_mode="Markdown"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    user_ids = get_all_user_ids()
    if not user_ids:
        await update.message.reply_text("❌ কোনো ইউজার পাওয়া যায়নি।")
        return

    await update.message.reply_text(f"⏳ **{len(user_ids)} জনের কাছে এনাউন্সমেন্ট পাঠানো হচ্ছে...**", parse_mode="Markdown")

    success = 0
    failed = 0

    for u_id in user_ids:
        try:
            if update.message.photo:
                photo_file = update.message.photo[-1].file_id
                caption_text = update.message.caption if update.message.caption else ""
                await context.bot.send_photo(chat_id=u_id, photo=photo_file, caption=caption_text, parse_mode="Markdown")
            elif context.args or update.message.text:
                msg_text = " ".join(context.args) if context.args else update.message.text.replace("/broadcast", "").strip()
                if msg_text:
                    await context.bot.send_message(chat_id=u_id, text=f"📢 **নোটিশ:**\n\n{msg_text}", parse_mode="Markdown")
            
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ **ব্রডকাস্ট শেষ!**\n\n📩 সফল: {success} | ❌ ব্যর্থ: {failed}", parse_mode="Markdown")

async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("⚠️ নিয়ম: `/addbalance <USER_ID> <AMOUNT>`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
        new_bal = update_user_balance(target_id, amount)
        await update.message.reply_text(f"✅ ইউজার `{target_id}` এর ব্যালেন্স যুক্ত হয়েছে। বর্তমান: {new_bal} BDT", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ ডাটা সঠিক নয়।")

async def add_cards_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    full_text = update.message.text.strip()
    lines = [line.strip() for line in full_text.split('\n') if line.strip()]
    
    first_line_parts = lines[0].split()
    if len(first_line_parts) < 2:
        await update.message.reply_text("⚠️ নিয়ম:\n`/addcards 414720`\n`4147200000|05|28|123`", parse_mode="Markdown")
        return
    
    bin_num = first_line_parts[1].strip()
    cards_to_add = lines[1:]
    
    if not cards_to_add:
        await update.message.reply_text("⚠️ কোনো কার্ড দেওয়া হয়নি।")
        return

    added_count = 0
    for card in cards_to_add:
        if card:
            add_single_card(bin_num, card)
            added_count += 1

    total_count = len(get_cards_by_bin(bin_num))
    await update.message.reply_text(f"✅ **{added_count} টি কার্ড যোগ হয়েছে!**\n📌 **BIN:** `{bin_num}` | 📦 **মোট স্টক:** {total_count} টি", parse_mode="Markdown")

async def clear_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ নিয়ম: `/clearstock <BIN>`", parse_mode="Markdown")
        return
    bin_num = context.args[0]
    count = delete_bin_stock(bin_num)
    await update.message.reply_text(f"🗑️ BIN `{bin_num}`-এর {count} টি কার্ড ডিলিট হয়েছে।", parse_mode="Markdown")

async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ নিয়ম: `/setprice <PRICE>`", parse_mode="Markdown")
        return
    try:
        new_price = float(context.args[0])
        set_setting("price", str(new_price))
        await update.message.reply_text(f"✅ কার্ডের দাম সেট হয়েছে: **{new_price} BDT**", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ সঠিক দাম লিখুন।")

async def set_bkash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ নিয়ম: `/setbkash <NUMBER>`", parse_mode="Markdown")
        return
    num = context.args[0]
    set_setting("bkash", num)
    await update.message.reply_text(f"✅ বিকাশ নম্বর সেট হয়েছে: `{num}`", parse_mode="Markdown")

async def set_nagad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 1:
        await update.message.reply_text("⚠️ নিয়ম: `/setnagad <NUMBER>`", parse_mode="Markdown")
        return
    num = context.args[0]
    set_setting("nagad", num)
    await update.message.reply_text(f"✅ নগদ নম্বর সেট হয়েছে: `{num}`", parse_mode="Markdown")

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    help_text = (
        "🛠️ **এডমিন কমান্ডসমূহ:**\n\n"
        "📊 `/stats` - স্ট্যাটস ও রিপোর্ট দেখার জন্য\n"
        "📥 `/downloadstock` - অবশিষ্ট সকল স্টকের ব্যাকআপ ফাইল পেতে\n"
        "📢 `/broadcast <মেসেজ>` (ছবি ও ক্যাপশনেও হবে)\n"
        "📱 `/setbkash <নম্বর>`\n"
        "📱 `/setnagad <নম্বর>`\n"
        "💰 `/addbalance <USER_ID> <AMOUNT>`\n"
        "📦 `/addcards <BIN>`\n`CARD_DETAILS`\n"
        "🗑️ `/clearstock <BIN>`\n"
        "🏷️ `/setprice <PRICE>`"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Main Runner
async def run_bot():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_user_text))
    
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"^/broadcast"), broadcast))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Admin Handlers
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("downloadstock", download_stock))
    app.add_handler(CommandHandler("addbalance", add_balance))
    app.add_handler(CommandHandler("addcards", add_cards_bulk))
    app.add_handler(CommandHandler("clearstock", clear_stock))
    app.add_handler(CommandHandler("setprice", set_price))
    app.add_handler(CommandHandler("setbkash", set_bkash))
    app.add_handler(CommandHandler("setnagad", set_nagad))
    app.add_handler(CommandHandler("adminhelp", admin_help))

    logging.info("Bot started successfully...")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()

def main():
    Thread(target=run_dummy_server, daemon=True).start()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
