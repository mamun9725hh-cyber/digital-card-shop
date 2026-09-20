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
            FOREIGN KEY (product_id) REFERENCES products(id)
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
      "INSERT OR IGNORE INTO users (user_id, username, balance,"
      " has_claimed_trial) VALUES (?, ?, 0.0, 0)",
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
    member = await bot.get_chat_member(
        chat_id=CHANNEL_USERNAME, user_id=user_id
    )
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
      f"• `/start` — বটের মেইন মেনু চালু করতে\n"
      f"• `/buy` — দোকান খুলতে ও কার্ড কেনার লিস্ট দেখতে\n"
      f"• `/buycard <BIN>` — ১টি নির্দিষ্ট BIN এর কার্ড কিনতে (যেমন: `/buycard"
      f" 416598`)\n"
      f"• `/buycards <BIN> <সংখ্যার>` — নির্দিষ্ট BIN এর একাধিক কার্ড একসাথে"
      f" কিনতে (যেমন: `/buycards 416598 5`)\n"
      f"• `/stock` — স্টকে কোন কোন BIN এর কয়টি কার্ড আছে তা দেখতে\n"
      f"• `/balance` — আপনার বর্তমান ব্যালেন্স দেখতে\n"
      f"• `/commands` — সকল কমান্ডের লিস্ট দেখতে\n\n"
  )
  if is_admin(user):
    msg += (
        f"⚡ *ADMIN COMMANDS:*\n"
        f"• `/addcards <BIN> <Name> <Price>` — কার্ড আপলোড করতে\n"
        f"• `/removecards <BIN>` — কোনো BIN এর সব কার্ড রিমুভ/ডিলিট করতে\n"
        f"• `/addbalance <UserID> <Amount>` — ইউজারকে ব্যালেন্স যোগ করতে\n"
        f"• `/setbkash <Num>` — বিকাশ নম্বর সেট করতে\n"
        f"• `/setnagad <Num>` — নগদ নম্বর সেট করতে\n"
        f"• `/removebkash` — বিকাশ নম্বর রিমুভ করতে\n"
        f"• `/removenagad` — নগদ নম্বর রিমুভ করতে\n"
        f"• `/searchbin <BIN>` — নির্দিষ্ট BIN স্টক চেক করতে\n"
        f"• `/userhistory <UserID>` — ইউজারের হিস্টোরি দেখতে\n"
        f"• `/downloadcards` — স্টকের ব্যাকআপ ফাইল ডাউনলোড করতে\n"
        f"• `/downloaddb` — ডাটাবেজ ব্যাকআপ ডাউনলোড করতে\n"
        f"• `/broadcast <Message>` — ব্রডকাস্ট নোটিশ পাঠাতে\n"
    )
  return msg


def get_stock_text():
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN"
      " stock s ON p.id = s.product_id GROUP BY p.id"
  )
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
  msg += f"💡 _কার্ড কিনতে নিচে 🛍️ Browse Cards Shop অপশনে চাপুন।_"
  return msg


# ----------------------------------------------------
# 4. BOT HANDLERS & INTERFACE
# ----------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  add_or_update_user(user)
  bal = get_user_balance(user.id)

  keyboard = [
      [
          InlineKeyboardButton(
              "🛍️ Browse Cards Shop", callback_data="buy_menu"
          )
      ],
      [
          InlineKeyboardButton(
              "🎁 Free Trial (2 Cards)", callback_data="claim_trial"
          )
      ],
      [
          InlineKeyboardButton(
              "📊 Available Stock", callback_data="view_stock"
          ),
          InlineKeyboardButton("📜 All Commands", callback_data="all_commands"),
      ],
      [
          InlineKeyboardButton("💰 My Balance", callback_data="my_balance"),
          InlineKeyboardButton(
              "📜 Purchase History", callback_data="my_history"
          ),
      ],
      [InlineKeyboardButton("📢 Telegram Channel", url=CHANNEL_URL)],
      [
          InlineKeyboardButton(
              "👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}"
          )
      ],
  ]

  if is_admin(user):
    keyboard.append([
        InlineKeyboardButton(
            "⚡ Admin Control Panel", callback_data="admin_panel"
        )
    ])

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

  await update.message.reply_text(
      welcome_text, reply_markup=reply_markup, parse_mode="Markdown"
  )


async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  msg = get_commands_text(user)
  keyboard = [
      [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
  ]
  await update.message.reply_text(
      msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
  )


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  msg = get_stock_text()
  keyboard = [
      [InlineKeyboardButton("🛍️ Go To Shop", callback_data="buy_menu")],
      [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")],
  ]
  await update.message.reply_text(
      msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
  )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  bal = get_user_balance(user.id)
  msg = (
      f"💵 *Your Current Balance:* `${bal:.2f}`\n\n_To top up, contact Admin:"
      f" @{ADMIN_USERNAME}_"
  )
  keyboard = [
      [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
  ]
  await update.message.reply_text(
      msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
  )


# ----------------------------------------------------
# 5. DIRECT BUY COMMANDS
# ----------------------------------------------------
async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT p.id, p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT"
      " JOIN stock s ON p.id = s.product_id GROUP BY p.id"
  )
  products = cursor.fetchall()
  conn.close()

  if not products:
    msg = "⚠️ *STORE IS CURRENTLY EMPTY!*"
    await update.message.reply_text(msg, parse_mode="Markdown")
    return

  keyboard = []
  for p_id, p_bin, name, price, stock_count in products:
    btn_text = (
        f"💳 Buy {p_bin} - ${price:.2f} ({stock_count} Available)"
        if stock_count > 0
        else f"❌ {p_bin} - Out of Stock"
    )
    cb_data = f"buy_prod_{p_id}" if stock_count > 0 else "out_of_stock_alert"
    keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_data)])

  keyboard.append(
      [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
  )

  msg = (
      f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n"
      f"🔥 *AVAILABLE CARDS STORE*\n"
      f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n\n"
      f"👇 *যে কার্ডটি কিনতে চান সেটির ওপর ক্লিক করুন:*"
  )
  await update.message.reply_text(
      msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
  )


async def buycard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user = update.effective_user
  add_or_update_user(user)

  if not context.args:
    await update.message.reply_text(
        "❌ *নিয়ম:* `/buycard <BIN>`\n_উদাহরণ:_ `/buycard 416598`",
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
        "❌ *নিয়ম:* `/buycards <BIN> <Quantity>`\n_উদাহরণ:_ `/buycards 416598 5`",
        parse_mode="Markdown",
    )
    return

  target_bin = context.args[0].strip()
  try:
    qty = int(context.args[1])
    if qty <= 0:
      raise ValueError
  except ValueError:
    await update.message.reply_text(
        "❌ *ভুল পরিমাণ!* সংখ্যা সঠিকভাবে দিন।", parse_mode="Markdown"
    )
    return

  await process_card_purchase(update, user, target_bin, quantity=qty)


async def process_card_purchase(
    update: Update, user, target_bin: str, quantity: int
):
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, name, price FROM products WHERE bin = ?", (target_bin,)
  )
  prod = cursor.fetchone()

  is_callback = update.callback_query is not None

  async def send_msg(text, reply_markup=None):
    if is_callback:
      await update.callback_query.edit_message_text(
          text, reply_markup=reply_markup, parse_mode="Markdown"
      )
    else:
      await update.message.reply_text(
          text, reply_markup=reply_markup, parse_mode="Markdown"
      )

  if not prod:
    await send_msg(
        f"❌ *BIN `{target_bin}` বটের স্টকে খুঁজে পাওয়া যায়নি!*"
    )
    conn.close()
    return

  p_id, p_name, p_price = prod
  total_cost = p_price * quantity
  user_bal = get_user_balance(user.id)

  if user_bal < total_cost:
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]
    await send_msg(
        f"❌ *পর্যাপ্ত ব্যালেন্স নেই!*\n\n"
        f"💳 *BIN:* `{target_bin}`\n"
        f"📦 *কার্ড সংখ্যা:* `{quantity}` টি\n"
        f"🏷️ *মোট খরচ:* `${total_cost:.2f}`\n"
        f"💵 *আপনার ব্যালেন্স:* `${user_bal:.2f}`\n\n"
        f"📲 *এডমিন থেকে ব্যালেন্স রিচার্জ করুন:* @{ADMIN_USERNAME}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    conn.close()
    return

  cursor.execute(
      "SELECT id, card_data FROM stock WHERE product_id = ? LIMIT ?",
      (p_id, quantity),
  )
  stock_items = cursor.fetchall()

  if len(stock_items) < quantity:
    await send_msg(
        f"❌ *স্টক কম আছে!*\n\n`{target_bin}` BIN-এ বর্তমানে"
        f" `{len(stock_items)}` টি কার্ড স্টকে আছে। আপনি রিকোয়েস্ট করেছেন"
        f" `{quantity}` টি।"
    )
    conn.close()
    return

  purchased_cards = []
  for s_id, card_data in stock_items:
    cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
    purchased_cards.append(card_data)
    cursor.execute(
        "INSERT INTO history (user_id, product_name, card_data, price) VALUES"
        " (?, ?, ?, ?)",
        (
            user.id,
            f"{p_name} (BIN: {target_bin})",
            card_data,
            p_price,
        ),
    )

  cursor.execute(
      "UPDATE users SET balance = balance - ? WHERE user_id = ?",
      (total_cost, user.id),
  )
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
      f"💵 *Total Paid:* `${total_cost:.2f}`\n\n"
      f"🔑 *YOUR CARDS DETAILS:*\n"
      f"{cards_text}\n\n"
      f"⚡ _Tap on the card details to copy!_\n"
      f"❤️ *Thank you for shopping!*"
  )
  await send_msg(msg, reply_markup=InlineKeyboardMarkup(keyboard))


# ----------------------------------------------------
# 6. BUTTON HANDLERS
# ----------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
  query = update.callback_query
  await query.answer()
  user = query.from_user
  data = query.data

  if data == "start_menu":
    bal = get_user_balance(user.id)
    keyboard = [
        [
            InlineKeyboardButton(
                "🛍️ Browse Cards Shop", callback_data="buy_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "🎁 Free Trial (2 Cards)", callback_data="claim_trial"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Available Stock", callback_data="view_stock"
            ),
            InlineKeyboardButton("📜 All Commands", callback_data="all_commands"),
        ],
        [
            InlineKeyboardButton("💰 My Balance", callback_data="my_balance"),
            InlineKeyboardButton(
                "📜 Purchase History", callback_data="my_history"
            ),
        ],
        [InlineKeyboardButton("📢 Telegram Channel", url=CHANNEL_URL)],
        [
            InlineKeyboardButton(
                "👨‍💻 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME}"
            )
        ],
    ]
    if is_admin(user):
      keyboard.append([
          InlineKeyboardButton(
              "⚡ Admin Control Panel", callback_data="admin_panel"
          )
      ])

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
    await query.edit_message_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

  elif data == "all_commands":
    msg = get_commands_text(user)
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

  elif data == "view_stock":
    msg = get_stock_text()
    keyboard = [
        [InlineKeyboardButton("🛍️ Browse Cards Shop", callback_data="buy_menu")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")],
    ]
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

  elif data == "out_of_stock_alert":
    await query.answer("❌ এই কার্ডটি বর্তমানে স্টকে নেই!", show_alert=True)

  elif data == "buy_menu":
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT p.id, p.bin, p.name, p.price, COUNT(s.id) FROM products p LEFT"
        " JOIN stock s ON p.id = s.product_id GROUP BY p.id"
    )
    products = cursor.fetchall()
    conn.close()

    if not products:
      msg = "⚠️ *STORE IS CURRENTLY EMPTY!*"
      keyboard = [
          [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
      ]
      await query.edit_message_text(
          msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
      )
      return

    keyboard = []
    for p_id, p_bin, name, price, stock_count in products:
      if stock_count > 0:
        btn_text = f"🛒 Buy {p_bin} ({name}) — ${price:.2f} [{stock_count} Stock]"
        cb_data = f"buy_prod_{p_id}"
      else:
        btn_text = f"❌ {p_bin} ({name}) — Out of Stock"
        cb_data = "out_of_stock_alert"

      keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_data)])

    keyboard.append(
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    )

    msg = (
        f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"🔥 *SELECT CARD TO PURCHASE*\n"
        f"🛒 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"👇 *যে কার্ডটি কিনতে চান সেটির ওপর ক্লিক করুন:*"
    )
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

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
      msg = (
          f"⚠️ *MUST JOIN OUR TELEGRAM CHANNEL!*\n\n"
          f"ফ্রি ট্রায়াল ক্লেইম করতে হলে আপনাকে অবশ্যই আমাদের সিগন্যাল চ্যানেলে"
          f" জয়েন থাকতে হবে।"
      )
      keyboard = [
          [InlineKeyboardButton("📢 Join Telegram Channel", url=CHANNEL_URL)],
          [
              InlineKeyboardButton(
                  "🔄 Claim Trial Again", callback_data="claim_trial"
              )
          ],
          [
              InlineKeyboardButton(
                  "🔙 Back to Menu", callback_data="start_menu"
              )
          ],
      ]
      await query.edit_message_text(
          msg,
          reply_markup=InlineKeyboardMarkup(keyboard),
          parse_mode="Markdown",
      )
      return

    if has_claimed_trial(user.id):
      msg = (
          "❌ *TRIAL ALREADY CLAIMED!*\n\n_You have already used your 1-time Free"
          " Trial. Please buy cards from the shop!_"
      )
      keyboard = [
          [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
      ]
      await query.edit_message_text(
          msg,
          reply_markup=InlineKeyboardMarkup(keyboard),
          parse_mode="Markdown",
      )
      return

    context.user_data["awaiting_trial_bin"] = True
    msg = (
        f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n"
        f"🔍 *ENTER BIN FOR FREE TRIAL*\n"
        f"🎁 *━━━━━━━━━━━━━━━━━━━━*\n\n"
        f"আপনি যে BIN-এর ২টি ফ্রি ট্রায়াল কার্ড চান, সেই **6-Digit BIN** টি"
        f" এখানে মেসেজে লিখে পাঠান。\n\n"
        f"💡 *Example:* `416598`"
    )
    keyboard = [
        [InlineKeyboardButton("🔙 Cancel", callback_data="start_menu")]
    ]
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

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
      payment_info += (
          "\n⚠️ _টাকা পাঠানোর পর ট্রানজেকশন স্ক্রিনশট ও আপনার User ID সহ"
          " এডমিনকে পাঠান।_\n"
      )
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
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

  elif data == "my_history":
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_name, card_data, price, timestamp FROM history WHERE"
        " user_id = ? ORDER BY id DESC LIMIT 10",
        (user.id,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
      msg = "📜 *PURCHASE HISTORY*\n\n_You haven't bought any cards yet!_"
      keyboard = [
          [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
      ]
      await query.edit_message_text(
          msg,
          reply_markup=InlineKeyboardMarkup(keyboard),
          parse_mode="Markdown",
      )
      return

    msg = f"📜 *YOUR PURCHASE HISTORY*\n\n"
    for p_name, c_data, price, ts in rows:
      msg += f"📦 *{p_name}* — `${price:.2f}`\n"
      msg += f"💳 Details: `{c_data}`\n"
      msg += f"📅 Date: `{ts}`\n"
      msg += f"──────────────\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )

  elif data == "admin_panel":
    if not is_admin(user):
      await query.edit_message_text(
          "🚫 *Unauthorized Access!*", parse_mode="Markdown"
      )
      return

    msg = (
        f"⚡ *ADMIN CONTROL PANEL*\n\n"
        f"👉 `/addcards <BIN> <Name> <Price>`\n"
        f"👉 `/removecards <BIN>` (স্টক রিমুভ)\n"
        f"👉 `/addbalance <UserID> <Amount>`\n"
        f"👉 `/setbkash <Num>` | `/setnagad <Num>`\n"
        f"👉 `/userhistory <UserID>`\n"
        f"👉 `/broadcast <Message>`"
    )
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]
    await query.edit_message_text(
        msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )


# ----------------------------------------------------
# 7. TEXT MESSAGE HANDLER (FOR TRIAL BIN)
# ----------------------------------------------------
async def text_message_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  user = update.effective_user
  text = update.message.text.strip()

  if context.user_data.get("awaiting_trial_bin"):
    context.user_data["awaiting_trial_bin"] = False
    input_bin = text.split()[0]

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name FROM products WHERE bin = ?", (input_bin,)
    )
    prod = cursor.fetchone()

    if not prod:
      await update.message.reply_text(
          f"❌ *BIN `{input_bin}` স্টকে পাওয়া যায়নি।*", parse_mode="Markdown"
      )
      conn.close()
      return

    p_id, p_name = prod
    cursor.execute(
        "SELECT id, card_data FROM stock WHERE product_id = ? LIMIT 2", (p_id,)
    )
    stock_items = cursor.fetchall()

    if len(stock_items) < 2:
      await update.message.reply_text(
          f"⚠️ `{input_bin}` BIN-এ ট্রায়ালের জন্য যথেষ্ট কার্ড নেই।",
          parse_mode="Markdown",
      )
      conn.close()
      return

    card_texts = []
    for s_id, c_data in stock_items:
      cursor.execute("DELETE FROM stock WHERE id = ?", (s_id,))
      card_texts.append(c_data)
      cursor.execute(
          "INSERT INTO history (user_id, product_name, card_data, price)"
          " VALUES (?, ?, ?, ?)",
          (user.id, f"FREE TRIAL ({p_name})", c_data, 0.0),
      )

    set_claimed_trial(user.id)
    conn.commit()
    conn.close()

    msg = (
        f"🎉 *FREE TRIAL CLAIMED!*\n\n"
        f"1️⃣ `{card_texts[0]}`\n"
        f"2️⃣ `{card_texts[1]}`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ----------------------------------------------------
# 8. ADMIN COMMAND HANDLERS
# ----------------------------------------------------
async def remove_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  if not context.args:
    await update.message.reply_text(
        "❌ *Usage:* `/removecards <BIN>`", parse_mode="Markdown"
    )
    return

  bin_code = context.args[0].strip()
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute("SELECT id FROM products WHERE bin = ?", (bin_code,))
  prod = cursor.fetchone()

  if not prod:
    await update.message.reply_text(
        f"❌ *BIN `{bin_code}` পাওয়া যায়নি!*", parse_mode="Markdown"
    )
    conn.close()
    return

  p_id = prod[0]
  cursor.execute("DELETE FROM stock WHERE product_id = ?", (p_id,))
  cursor.execute("DELETE FROM products WHERE id = ?", (p_id,))
  conn.commit()
  conn.close()

  await update.message.reply_text(
      f"🗑️ *BIN `{bin_code}` এর সমস্ত কার্ড স্টক এবং ক্যাটাগরি সফলভাবে মুছে"
      " ফেলা হয়েছে!*",
      parse_mode="Markdown",
  )


async def set_bkash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  try:
    set_setting("bkash", context.args[0])
    await update.message.reply_text(
        f"✅ *bKash Updated:* `{context.args[0]}`", parse_mode="Markdown"
    )
  except:
    await update.message.reply_text(
        "❌ `/setbkash <Num>`", parse_mode="Markdown"
    )


async def remove_bkash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  set_setting("bkash", None)
  await update.message.reply_text("🗑️ *bKash Removed!*", parse_mode="Markdown")


async def set_nagad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  try:
    set_setting("nagad", context.args[0])
    await update.message.reply_text(
        f"✅ *Nagad Updated:* `{context.args[0]}`", parse_mode="Markdown"
    )
  except:
    await update.message.reply_text(
        "❌ `/setnagad <Num>`", parse_mode="Markdown"
    )


async def remove_nagad_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  set_setting("nagad", None)
  await update.message.reply_text("🗑️ *Nagad Removed!*", parse_mode="Markdown")


async def add_cards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  try:
    text_lines = update.message.text.split("\n")
    first_line_parts = text_lines[0].split()

    bin_code = first_line_parts[1]
    price = float(first_line_parts[-1])
    p_name = (
        " ".join(first_line_parts[2:-1])
        if len(first_line_parts) > 3
        else f"BIN {bin_code}"
    )
    cards = [line.strip() for line in text_lines[1:] if line.strip()]

    if not cards:
      await update.message.reply_text(
          "❌ *No cards added.*", parse_mode="Markdown"
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
      cursor.execute(
          "INSERT INTO stock (product_id, card_data) VALUES (?, ?)", (p_id, c)
      )

    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"🎉 *ADDED {len(cards)} CARDS FOR BIN `{bin_code}`!*",
        parse_mode="Markdown",
    )
  except Exception as e:
    await update.message.reply_text(
        "❌ *Format:* `/addcards <BIN> <Name> <Price>`\n`CardData1`",
        parse_mode="Markdown",
    )


async def user_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  try:
    t_id = int(context.args[0])
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT product_name, card_data, price, timestamp FROM history WHERE"
        " user_id = ? ORDER BY id DESC",
        (t_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
      await update.message.reply_text(
          "⚠️ No history found.", parse_mode="Markdown"
      )
      return

    msg = f"📜 *HISTORY FOR USER:* `{t_id}`\n\n"
    for p_name, c_data, price, ts in rows[:15]:
      msg += (
          f"📦 *{p_name}* — `${price:.2f}`\n`{c_data}`\n📅"
          f" `{ts}`\n──────────────\n"
      )
    await update.message.reply_text(msg, parse_mode="Markdown")
  except:
    await update.message.reply_text(
        "❌ `/userhistory <UserID>`", parse_mode="Markdown"
    )


async def download_cards_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  if not is_admin(update.effective_user):
    return
  conn = get_db()
  cursor = conn.cursor()
  cursor.execute(
      "SELECT p.bin, p.name, p.price, s.card_data FROM stock s JOIN products"
      " p ON s.product_id = p.id"
  )
  rows = cursor.fetchall()
  conn.close()

  if not rows:
    await update.message.reply_text("⚠️ No stock.", parse_mode="Markdown")
    return

  file_path = "cards_backup.txt"
  with open(file_path, "w", encoding="utf-8") as f:
    for p_bin, p_name, price, card in rows:
      f.write(f"BIN: {p_bin} | {p_name} | ${price:.2f} | Card: {card}\n")

  await update.message.reply_document(
      document=open(file_path, "rb"),
      caption="📦 *Stock Backup*",
      parse_mode="Markdown",
  )
  if os.path.exists(file_path):
    os.remove(file_path)


async def download_db_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  if os.path.exists(DB_NAME):
    await update.message.reply_document(
        document=open(DB_NAME, "rb"),
        caption="💾 *Database Backup*",
        parse_mode="Markdown",
    )


async def search_bin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  try:
    bin_code = context.args[0]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT p.name, p.price, COUNT(s.id) FROM products p LEFT JOIN stock s"
        " ON p.id = s.product_id WHERE p.bin = ? GROUP BY p.id",
        (bin_code,),
    )
    res = cursor.fetchone()
    conn.close()

    if not res:
      await update.message.reply_text(
          f"❌ BIN `{bin_code}` not found.", parse_mode="Markdown"
      )
      return

    name, price, stock = res
    await update.message.reply_text(
        f"🔎 *BIN:* `{bin_code}`\n📦 *Name:* `{name}`\n💵 *Price:*"
        f" `${price:.2f}`\n📊 *Stock:* `{stock}`",
        parse_mode="Markdown",
    )
  except:
    await update.message.reply_text(
        "❌ `/searchbin <BIN>`", parse_mode="Markdown"
    )


async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  try:
    t_id = int(context.args[0])
    amt = float(context.args[1])
    update_user_balance(t_id, amt)
    await update.message.reply_text(
        f"✅ *Balance Updated!* User: `{t_id}` | Added: `${amt:.2f}`",
        parse_mode="Markdown",
    )
  except:
    await update.message.reply_text(
        "❌ `/addbalance <UserID> <Amount>`", parse_mode="Markdown"
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
  if not is_admin(update.effective_user):
    return
  msg_text = " ".join(context.args)
  if not msg_text:
    await update.message.reply_text(
        "❌ `/broadcast <Message>`", parse_mode="Markdown"
    )
    return

  conn = get_db()
  cursor = conn.cursor()
  cursor.execute("SELECT user_id FROM users")
  users = cursor.fetchall()
  conn.close()

  count = 0
  for (u_id,) in users:
    try:
      await context.bot.send_message(
          chat_id=u_id,
          text=f"📢 *ANNOUNCEMENT*\n\n{msg_text}",
          parse_mode="Markdown",
      )
      count += 1
    except:
      pass
  await update.message.reply_text(
      f"📢 Broadcast sent to {count} users!", parse_mode="Markdown"
  )


# ----------------------------------------------------
# 9. MAIN FUNCTION
# ----------------------------------------------------
def main():
  server_thread = Thread(target=run_dummy_server, daemon=True)
  server_thread.start()

  token = os.environ.get("BOT_TOKEN")
  if not token:
    logging.error("No BOT_TOKEN provided!")
    return

  app = Application.builder().token(token).build()

  # User Handlers
  app.add_handler(CommandHandler("start", start_command))
  app.add_handler(CommandHandler("buy", buy_command))
  app.add_handler(CommandHandler("buycard", buycard_cmd))
  app.add_handler(CommandHandler("buycards", buycards_cmd))
  app.add_handler(CommandHandler("commands", commands_command))
  app.add_handler(CommandHandler("stock", stock_command))
  app.add_handler(CommandHandler("balance", balance_command))
  app.add_handler(CallbackQueryHandler(button_handler))
  app.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler)
  )

  # Admin Handlers
  app.add_handler(CommandHandler("removecards", remove_cards_cmd))
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

  logging.info("Bot started successfully...")
  app.run_polling()


if __name__ == "__main__":
  main()
