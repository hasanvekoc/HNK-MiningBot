import os
import sqlite3
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

DB = os.getenv("HNK_DB", "hnk_mining.db")
DAILY_REWARD = 0.25
START_BONUS = 1.0
REFERRAL_BONUS_INVITER = 1.0
REFERRAL_BONUS_INVITED = 0.5
CLAIM_HOURS = 24

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL NOT NULL DEFAULT 0,
        last_claim TEXT,
        referred_by INTEGER,
        referral_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    c.commit()
    c.close()

def get_user(uid):
    c = db()
    row = c.execute("SELECT * FROM users WHERE telegram_id=?", (uid,)).fetchone()
    c.close()
    return row

def create_user(tg_user, referrer=None):
    if get_user(tg_user.id):
        return False
    now = datetime.now(timezone.utc).isoformat()
    c = db()
    c.execute("""INSERT INTO users
        (telegram_id, username, first_name, balance, referred_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (tg_user.id, tg_user.username, tg_user.first_name, START_BONUS,
         referrer, now))
    if referrer and referrer != tg_user.id:
        c.execute("""UPDATE users SET balance=balance+?,
                  referral_count=referral_count+1 WHERE telegram_id=?""",
                 (REFERRAL_BONUS_INVITER, referrer))
    c.commit()
    c.close()
    return True

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⛏️ Kazımaya Başla", callback_data="mine"),
         InlineKeyboardButton("💰 Bakiyem", callback_data="balance")],
        [InlineKeyboardButton("👥 Referans", callback_data="ref"),
         InlineKeyboardButton("👛 Cüzdanım", callback_data="wallet")],
        [InlineKeyboardButton("📊 İstatistik", callback_data="stats"),
         InlineKeyboardButton("🏆 Liderlik", callback_data="leaderboard")],
        [InlineKeyboardButton("ℹ️ HNK Hakkında", callback_data="about")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = None
    if context.args:
        try:
            code = context.args[0]
            if code.startswith("ref_"):
                ref = int(code[4:])
        except ValueError:
            pass

    created = create_user(update.effective_user, ref)
    text = (
        "🪙 *Hyper Nexus Kingdom — HNK Mining*\n\n"
        "Telegram üzerinden HNK kazanma sistemine hoş geldin.\n\n"
        f"🎁 Başlangıç bonusu: *{START_BONUS:g} HNK*\n"
        f"⛏️ Günlük kazım: *{DAILY_REWARD:g} HNK*\n"
        "⏱️ Kazım hakkı: 24 saatte bir\n\n"
        "Aşağıdaki menüden devam et:"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=menu())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    user = get_user(uid)

    if not user:
        create_user(q.from_user)
        user = get_user(uid)

    if q.data == "mine":
        now = datetime.now(timezone.utc)
        if user["last_claim"]:
            last = datetime.fromisoformat(user["last_claim"])
            elapsed = now - last
            if elapsed < timedelta(hours=CLAIM_HOURS):
                remaining = timedelta(hours=CLAIM_HOURS) - elapsed
                h = int(remaining.total_seconds() // 3600)
                m = int((remaining.total_seconds() % 3600) // 60)
                await q.edit_message_text(
                    f"⏳ Henüz kazım zamanı gelmedi.\n\n"
                    f"Sonraki kazım: *{h} saat {m} dakika*",
                    parse_mode="Markdown", reply_markup=menu())
                return

        c = db()
        c.execute("""UPDATE users SET balance=balance+?, last_claim=?
                     WHERE telegram_id=?""",
                 (DAILY_REWARD, now.isoformat(), uid))
        c.commit()
        c.close()
        new_balance = get_user(uid)["balance"]
        await q.edit_message_text(
            f"⛏️ *Kazım başarılı!*\n\n"
            f"+{DAILY_REWARD:g} HNK kazandın.\n"
            f"💰 Yeni bakiye: *{new_balance:.2f} HNK*",
            parse_mode="Markdown", reply_markup=menu())

    elif q.data == "balance":
        await q.edit_message_text(
            f"💰 *HNK Bakiyen*\n\n`{user['balance']:.2f} HNK`",
            parse_mode="Markdown", reply_markup=menu())

    elif q.data == "ref":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{uid}"
        await q.edit_message_text(
            f"👥 *Referans Sistemi*\n\n"
            f"Davet sayın: *{user['referral_count']}*\n"
            f"Davet eden bonusu: *{REFERRAL_BONUS_INVITER:g} HNK*\n\n"
            f"🔗 Davet bağlantın:\n`{link}`",
            parse_mode="Markdown", reply_markup=menu())

    elif q.data == "wallet":
        await q.edit_message_text(
            "👛 *HNK Cüzdanı*\n\n"
            "V1 sürümünde blockchain çekimi kapalıdır.\n"
            "Bir sonraki sürümde BSC cüzdan adresi bağlama ve "
            "HNK çekim sistemi eklenebilir.",
            parse_mode="Markdown", reply_markup=menu())

    elif q.data == "stats":
        c = db()
        total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        supply = c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0]
        c.close()
        await q.edit_message_text(
            f"📊 *HNK Mining İstatistikleri*\n\n"
            f"👥 Kullanıcı: *{total}*\n"
            f"🪙 Dağıtılmış uygulama bakiyesi: *{supply:.2f} HNK*",
            parse_mode="Markdown", reply_markup=menu())

    elif q.data == "leaderboard":
        c = db()
        rows = c.execute(
            "SELECT first_name, username, balance FROM users "
            "ORDER BY balance DESC LIMIT 10").fetchall()
        c.close()
        lines = ["🏆 *HNK Liderlik Tablosu*\n"]
        for i, r in enumerate(rows, 1):
            name = r["first_name"] or r["username"] or "Kullanıcı"
            lines.append(f"{i}. {name} — {r['balance']:.2f} HNK")
        await q.edit_message_text("\n".join(lines),
                                  parse_mode="Markdown", reply_markup=menu())

    elif q.data == "about":
        await q.edit_message_text(
            "ℹ️ *Hyper Nexus Kingdom (HNK)*\n\n"
            "Bu bot, HNK topluluğu için uygulama içi kazım ve "
            "referans sisteminin V1 prototipidir.\n\n"
            "⚠️ V1 bakiyeleri blockchain üzerinde gerçek token transferi değildir.",
            parse_mode="Markdown", reply_markup=menu())

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — HNK Mining menüsü\n/help — Yardım",
        reply_markup=menu())

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN bulunamadı. .env veya ortam değişkenine ekleyin.")
    init_db()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button))
    print("HNK Mining Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
