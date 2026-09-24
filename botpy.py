import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
DB = os.getenv("HNK_DB", "hnk_mining.db")
ADMIN_ID = 8769533867
DAILY = 0.25
BONUS = 1.0
MIN_W = 10.0
def is_admin(user_id):
    return user_id == ADMIN_ID
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 0,
        last_claim TEXT,
        wallet TEXT,
        referral_count INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        amount REAL,
        wallet TEXT,
        status TEXT,
        created_at TEXT
    )""")
    c.commit()
    c.close()

def user(i):
    c = db()
    r = c.execute("SELECT * FROM users WHERE telegram_id=?", (i,)).fetchone()
    c.close()
    return r

def add(u, ref=None):
    if user(u.id):
        return
    c = db()
    c.execute(
        "INSERT INTO users VALUES(?,?,?,?,?,?,?,?)",
        (u.id, u.username, u.first_name, BONUS, None, None, 0,
         datetime.now(timezone.utc).isoformat())
    )
    if ref and ref != u.id:
        c.execute(
            "UPDATE users SET balance=balance+?, referral_count=referral_count+1 WHERE telegram_id=?",
            (1.0, ref)
        )
    c.commit()
    c.close()
def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Kullanıcılar", callback_data="adm_users"),
            InlineKeyboardButton("📊 İstatistik", callback_data="adm_stats")
        ],
        [
            InlineKeyboardButton("💰 Kazım Ayarları", callback_data="adm_mining"),
            InlineKeyboardButton("🎁 Bonus Ayarları", callback_data="adm_bonus")
        ],
        [
            InlineKeyboardButton("📢 Duyuru Gönder", callback_data="adm_broadcast"),
            InlineKeyboardButton("🚫 Kullanıcı Yönetimi", callback_data="adm_manage")
        ],
        [
            InlineKeyboardButton("⭐ Stars", callback_data="adm_stars"),
            InlineKeyboardButton("🔙 Ana Menü", callback_data="back")
        ]
    ])
def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⛏️ Madenciliği Başlat", callback_data="mine"),
            InlineKeyboardButton("💰 Bakiyem", callback_data="bal")
        ],
        [
            InlineKeyboardButton("👥 Arkadaşlarını Davet Et", callback_data="ref"),
            InlineKeyboardButton("👛 Cüzdanım", callback_data="wallet")
        ],
        [
            InlineKeyboardButton("⭐ HNK Stars", callback_data="stars"),
            InlineKeyboardButton("📊 İstatistik", callback_data="stats")
        ],
        [
            InlineKeyboardButton("👑 Liderlik", callback_data="lead"),
            InlineKeyboardButton("ℹ️ HNK Hakkında", callback_data="about")
        ]
    ])

START_TEXT = (
    "\U0001fa99 *Hyper Nexus Kingdom \u2014 HNK Mining V2*\n\n"
    "\U0001f381 Ba\u015flang\u0131\u00e7: *1 HNK*\n"
    "\u26cf\ufe0f G\u00fcnl\u00fck kaz\u0131m: *0.25 HNK*\n"
    "\U0001f4b8 Minimum \u00e7ekim: *10 HNK*\n\n"
    "Men\u00fcden devam et:"
)

ABOUT_TEXT = (
    "\U0001fa99 *HYPER NEXUS KINGDOM \u2014 HNK*\n\n"
    "\U0001f310 *Proje:* Topluluk odakl\u0131 dijital madencilik ekosistemi\n"
    "\U0001f4b0 *Toplam Arz:* 1,000,000,000 HNK\n"
    "\U0001f522 *Ondal\u0131k:* 18\n"
    "\U0001f4b8 *Minimum \u00c7ekim:* 10 HNK\n"
    "\U0001f465 *Referans Sistemi:* Aktif\n"
    "\U0001f45b *BSC/EVM C\u00fczdan:* Destekleniyor\n\n"
    "\U0001f3af *Projenin Amac\u0131*\n"
    "HNK; insanlar\u0131, teknolojiyi ve dijital f\u0131rsatlar\u0131 bir araya getiren "
    "topluluk odakl\u0131 bir ekosistem olu\u015fturmay\u0131 hedefler.\n\n"
    "\U0001f5fa\ufe0f *Yol Haritas\u0131*\n"
    "\u2705 Faz 1 \u2014 Mining botu ve topluluk\n"
    "\u2705 Faz 2 \u2014 C\u00fczdan ve referans sistemi\n"
    "\u25ab\ufe0f Faz 3 \u2014 Testnet, likidite ve teknik altyap\u0131\n"
    "\u25ab\ufe0f Faz 4 \u2014 Borsa ba\u015fvurular\u0131 ve ekosistem geli\u015ftirme\n\n"
    "\U0001f4cc *Token S\u00f6zle\u015fmesi*\n"
    "BSC s\u00f6zle\u015fme adresi yay\u0131na al\u0131nd\u0131\u011f\u0131nda bu b\u00f6l\u00fcme eklenecektir.\n\n"
    "\U0001f517 *HNK*\n"
    "People \u2022 Technology \u2022 Opportunity\n\n"
    "_A Stronger Tomorrow Together_\n\n"
    "\u00a9 2026 Hyper Nexus Kingdom"
)

async def safe_edit(q, text, **kwargs):
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise

async def start(u, x):
    ref = None
    if x.args and x.args[0].startswith("ref_"):
        try:
            ref = int(x.args[0][4:])
        except Exception:
            pass

    add(u.effective_user, ref)

    # HNK_logo.png must be in the repository root.
    try:
        with open("HNK_logo.png", "rb") as f:
            await u.message.reply_photo(photo=f)
    except Exception:
        pass

    await u.message.reply_text(START_TEXT, parse_mode="Markdown", reply_markup=menu())

async def buttons(u, x):
    q = u.callback_query
    await q.answer()
    i = q.from_user.id

    if not user(i):
        add(q.from_user)

    r = user(i)
    s = q.data
  if s == "admin":
        if not is_admin(i):
            await q.message.reply_text("⛔ Bu bölüm sadece yöneticiye açıktır.")
            return

        await q.message.reply_text(
            "🛠 *HNK ADMIN PANELİ*\n\n"
            "👑 Yönetici: Hasan\n"
            "🔐 Yönetici yetkileri aktif.",
            parse_mode="Markdown"
        )
        return
    if s == "stars":
        await safe_edit(
            q,
            "⭐ *HNK Stars*\n\n"
            "🌟 HNK Stars sistemi aktif!\n\n"
            "⭐ Stars: 0\n"
            "🎁 Stars ile özel ödüller ve avantajlar yakında aktif olacak.\n\n"
            "🚀 HNK Mining V2",
            parse_mode="Markdown",
            reply_markup=menu()
        )
        return

    if s == "mine":
        now = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)

        if r["last_claim"] and now - datetime.fromisoformat(r["last_claim"]) < timedelta(hours=24):
            left = timedelta(hours=24) - (now - datetime.fromisoformat(r["last_claim"]))
            await safe_edit(
                q,
                f"\u23f3 Sonraki kaz\u0131m: {int(left.total_seconds() // 3600)} saat "
                f"{int(left.total_seconds() % 3600 // 60)} dakika",
                reply_markup=menu()
            )
            return

        c = db()
        c.execute(
            "UPDATE users SET balance=balance+?, last_claim=? WHERE telegram_id=?",
            (DAILY, now.isoformat(), i)
        )
        c.commit()
        c.close()

        await safe_edit(
            q,
            f"\u26cf\ufe0f *Kaz\u0131m ba\u015far\u0131l\u0131!*\n"
            f"+0.25 HNK\n"
            f"\U0001f4b0 Bakiye: *{user(i)['balance']:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    elif s == "bal":
        await safe_edit(
            q,
            f"\U0001f4b0 Bakiye: *{r['balance']:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    elif s == "wallet":
        x.user_data["state"] = "wallet"
        await safe_edit(q, "\U0001f45b BSC/EVM c\u00fczdan adresini g\u00f6nder.\n\u00d6rnek: `0x...`", parse_mode="Markdown")

    elif s == "with":
        if not r["wallet"]:
            x.user_data["state"] = "wallet_then_with"
            await safe_edit(q, "\u00d6nce BSC c\u00fczdan adresini g\u00f6nder.")
        else:
            x.user_data["state"] = "with"
            await safe_edit(
                q,
                f"\U0001f4b8 Miktar\u0131 yaz. Minimum *{MIN_W:g} HNK*. "
                f"Bakiye: *{r['balance']:.2f} HNK*",
                parse_mode="Markdown"
            )

    elif s == "ref":
        m = await x.bot.get_me()
        await safe_edit(
            q,
            f"\U0001f465 Davet: {r['referral_count']}\n"
            f"\U0001f517 `https://t.me/{m.username}?start=ref_{i}`",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    elif s == "stats":
        c = db()
        n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        c.close()
        await safe_edit(q, f"\U0001f4ca Kullan\u0131c\u0131: *{n}*", parse_mode="Markdown", reply_markup=menu())

    elif s == "lead":
        c = db()
        rows = c.execute(
            "SELECT first_name, balance FROM users ORDER BY balance DESC LIMIT 10"
        ).fetchall()
        c.close()
        text = "\n".join(
            f"{n}. {z['first_name'] or 'Kullan\u0131c\u0131'} \u2014 {z['balance']:.2f} HNK"
            for n, z in enumerate(rows, 1)
        ) or "Hen\u00fcz kullan\u0131c\u0131 yok."
        await safe_edit(q, text, reply_markup=menu())

    elif s == "about":
        await safe_edit(
            q,
            ABOUT_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u2b05\ufe0f Ana Men\u00fc", callback_data="menu")]
            ])
        )

    elif s == "menu":
        await safe_edit(q, START_TEXT, parse_mode="Markdown", reply_markup=menu())

async def text(u, x):
    st = x.user_data.get("state")
    i = u.effective_user.id
    if not st:
        return

    t = u.message.text.strip()

    if st.startswith("wallet"):
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", t):
            await u.message.reply_text("\u274c Ge\u00e7erli BSC/EVM adresi gir.")
            return

        c = db()
        c.execute("UPDATE users SET wallet=? WHERE telegram_id=?", (t, i))
        c.commit()
        c.close()

        x.user_data["state"] = "with" if st == "wallet_then_with" else None
        await u.message.reply_text(
            "\u2705 C\u00fczdan kaydedildi." +
            ("\n\u015eimdi \u00e7ekim miktar\u0131n\u0131 yaz." if st == "wallet_then_with" else ""),
            reply_markup=menu()
        )

    elif st == "with":
        try:
            a = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text("\u274c Miktar\u0131 say\u0131 olarak yaz.")
            return

        r = user(i)
        if a < MIN_W or a > r["balance"]:
            await u.message.reply_text("\u274c Miktar ge\u00e7ersiz veya bakiye yetersiz.")
            return

        c = db()
        c.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?", (a, i))
        c.execute(
            "INSERT INTO withdrawals(telegram_id,amount,wallet,status,created_at) VALUES(?,?,?,?,?)",
            (i, a, r["wallet"], "pending", datetime.now(timezone.utc).isoformat())
        )
        c.commit()
        c.close()
        x.user_data["state"] = None

        await u.message.reply_text(
            f"\U0001f4b8 \u00c7ekim talebi olu\u015fturuldu: *{a:g} HNK*\nDurum: Bekliyor",
            parse_mode="Markdown",
            reply_markup=menu()
        )

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"HNK Mining Bot OK")

    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
async def admin(u, x):
    if not is_admin(u.effective_user.id):
        await u.message.reply_text("⛔ Bu bölüm sadece yöneticiye açıktır.")
        return

    await u.message.reply_text(
        "🛠 *HNK ADMIN PANELİ*\n\n"
        "👑 Yönetici: Hasan\n"
        "🆔 Admin ID: 8769533867\n\n"
        "🔐 Yönetici yetkileri aktif.\n\n"
        "Aşağıdaki menüden işlem seç:",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )
    )
def run():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN bulunamad\u0131")
    init()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.run_polling()

if __name__ == "__main__":
    run()
