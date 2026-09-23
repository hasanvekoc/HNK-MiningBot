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
DAILY = 0.25
BONUS = 1.0
MIN_W = 10.0

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

def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\u26cf\ufe0f Kaz\u0131maya Ba\u015fla", callback_data="mine"),
            InlineKeyboardButton("\U0001f4b0 Bakiyem", callback_data="bal")
        ],
        [
            InlineKeyboardButton("\U0001f465 Referans", callback_data="ref"),
            InlineKeyboardButton("\U0001f45b C\u00fczdan\u0131m", callback_data="wallet")
        ],
        [
            InlineKeyboardButton("\U0001f4b8 HNK \u00c7ek", callback_data="with"),
            InlineKeyboardButton("\U0001f4ca \u0130statistik", callback_data="stats")
        ],
        [
            InlineKeyboardButton("\U0001f3c6 Liderlik", callback_data="lead"),
            InlineKeyboardButton("\u2139\ufe0f HNK Hakk\u0131nda", callback_data="about")
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
    "\U0001f310 Dijital madencilik ve topluluk odakl\u0131 HNK projesi.\n\n"
    "\U0001f381 *Ba\u015flang\u0131\u00e7 Bonusu:* 1 HNK\n"
    "\u26cf\ufe0f *G\u00fcnl\u00fck Kaz\u0131m:* 0.25 HNK\n"
    "\U0001f4b8 *Minimum \u00c7ekim:* 10 HNK\n"
    "\U0001f465 *Referans Sistemi:* Aktif\n"
    "\U0001f45b *BSC/EVM C\u00fczdan:* Destekleniyor\n\n"
    "\U0001f3af *Vizyonumuz*\n"
    "\u0130nsanlar\u0131, teknolojiyi ve f\u0131rsatlar\u0131 bir araya getirerek "
    "k\u00fcresel bir dijital topluluk olu\u015fturmak.\n\n"
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

    if s == "mine":
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

def run():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN bulunamad\u0131")
    init()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))
    app.run_polling()

if __name__ == "__main__":
    run()
