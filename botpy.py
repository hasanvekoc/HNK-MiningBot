import os
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

DB = os.getenv("HNK_DB", "hnk_mining.db")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8769533867"))

DAILY = 0.25
BONUS = 1.0
REF_BONUS = 1.0
MIN_W = 10.0


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def column_exists(c, table, column):
    rows = c.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init():
    c = db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            last_claim TEXT,
            wallet TEXT,
            referral_count INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            amount REAL,
            wallet TEXT,
            status TEXT,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    if not column_exists(c, "users", "banned"):
        c.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")

    defaults = {
        "daily": DAILY,
        "bonus": BONUS,
        "ref_bonus": REF_BONUS,
        "min_withdraw": MIN_W,
    }
    for key, value in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, str(value)),
        )
    c.commit()
    c.close()


def get_setting(key, default):
    c = db()
    r = c.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ).fetchone()
    c.close()
    if not r:
        return default
    try:
        return float(r["value"])
    except (TypeError, ValueError):
        return default


def set_setting(key, value):
    c = db()
    c.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
        (key, str(value)),
    )
    c.commit()
    c.close()


def user(i):
    c = db()
    r = c.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (i,),
    ).fetchone()
    c.close()
    return r


def add(tg_user, ref=None):
    if user(tg_user.id):
        return

    starting_bonus = get_setting("bonus", BONUS)
    referral_bonus = get_setting("ref_bonus", REF_BONUS)
    now = datetime.now(timezone.utc).isoformat()

    c = db()
    c.execute(
        """
        INSERT INTO users
        (telegram_id, username, first_name, balance, last_claim,
         wallet, referral_count, created_at, banned)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            tg_user.id,
            tg_user.username,
            tg_user.first_name,
            starting_bonus,
            None,
            None,
            0,
            now,
            0,
        ),
    )

    if ref and ref != tg_user.id:
        ref_user = c.execute(
            "SELECT telegram_id,banned FROM users WHERE telegram_id=?",
            (ref,),
        ).fetchone()
        if ref_user and not ref_user["banned"]:
            c.execute(
                """
                UPDATE users
                SET balance=balance+?, referral_count=referral_count+1
                WHERE telegram_id=?
                """,
                (referral_bonus, ref),
            )

    c.commit()
    c.close()


def is_admin(user_id):
    return user_id == ADMIN_ID


async def safe_edit(q, text, **kwargs):
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("âï¸ MadenciliÄi BaÅlat", callback_data="mine"),
            InlineKeyboardButton("ð° Bakiyem", callback_data="bal"),
        ],
        [
            InlineKeyboardButton("ð¥ ArkadaÅlarÄ±nÄ± Davet Et", callback_data="ref"),
            InlineKeyboardButton("ð CÃ¼zdanÄ±m", callback_data="wallet"),
        ],
        [
            InlineKeyboardButton("ð¸ Ãekim", callback_data="with"),
            InlineKeyboardButton("â­ HNK Stars", callback_data="stars"),
        ],
        [
            InlineKeyboardButton("ð Ä°statistik", callback_data="stats"),
            InlineKeyboardButton("ð Liderlik", callback_data="lead"),
        ],
        [
            InlineKeyboardButton("â¹ï¸ HNK HakkÄ±nda", callback_data="about"),
        ],
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ð¥ KullanÄ±cÄ±lar", callback_data="adm_users"),
            InlineKeyboardButton("ð Ä°statistik", callback_data="adm_stats"),
        ],
        [
            InlineKeyboardButton("ð° KazÄ±m AyarlarÄ±", callback_data="adm_mining"),
            InlineKeyboardButton("ð Bonus AyarlarÄ±", callback_data="adm_bonus"),
        ],
        [
            InlineKeyboardButton("ð¢ Duyuru GÃ¶nder", callback_data="adm_broadcast"),
            InlineKeyboardButton("ð« KullanÄ±cÄ± YÃ¶netimi", callback_data="adm_manage"),
        ],
        [
            InlineKeyboardButton("ð¸ Ãekim Talepleri", callback_data="adm_withdrawals"),
            InlineKeyboardButton("â­ Stars", callback_data="adm_stars"),
        ],
        [
            InlineKeyboardButton("ð Ana MenÃ¼", callback_data="back"),
        ],
    ])


START_TEXT = (
    "ðª *Hyper Nexus Kingdom â HNK Mining V2*\n\n"
    "ð BaÅlangÄ±Ã§: *{bonus:g} HNK*\n"
    "âï¸ GÃ¼nlÃ¼k kazÄ±m: *{daily:g} HNK*\n"
    "ð¸ Minimum Ã§ekim: *{minimum:g} HNK*\n\n"
    "MenÃ¼den devam et:"
)

ABOUT_TEXT = (
    "ðª *HYPER NEXUS KINGDOM â HNK*\n\n"
    "ð *Proje:* Topluluk odaklÄ± dijital madencilik ekosistemi\n"
    "ð° *Toplam Arz:* 1,000,000,000 HNK\n"
    "ð¢ *OndalÄ±k:* 18\n"
    "ð¸ *Minimum Ãekim:* {minimum:g} HNK\n"
    "ð¥ *Referans Sistemi:* Aktif\n"
    "ð *BSC/EVM CÃ¼zdan:* Destekleniyor\n\n"
    "ð¯ *Projenin AmacÄ±*\n"
    "HNK; insanlar, teknoloji ve dijital fÄ±rsatlarÄ± "
    "bir araya getiren topluluk odaklÄ± bir ekosistem "
    "oluÅturmayÄ± hedefler.\n\n"
    "ðºï¸ *Yol HaritasÄ±*\n"
    "â Faz 1 â Mining botu ve topluluk\n"
    "â Faz 2 â CÃ¼zdan ve referans sistemi\n"
    "â«ï¸ Faz 3 â Testnet, likidite ve teknik altyapÄ±\n"
    "â«ï¸ Faz 4 â Borsa baÅvurularÄ± ve ekosistem geliÅtirme\n\n"
    "ð *Token SÃ¶zleÅmesi*\n"
    "BSC sÃ¶zleÅme adresi yayÄ±na alÄ±ndÄ±ÄÄ±nda bu bÃ¶lÃ¼me eklenecektir.\n\n"
    "ð *HNK*\n"
    "People â¢ Technology â¢ Opportunity\n\n"
    "_A Stronger Tomorrow Together_\n\n"
    "Â©ï¸ 2026 Hyper Nexus Kingdom"
)


async def start(u, x):
    tg_user = u.effective_user
    ref = None

    if x.args and x.args[0].startswith("ref_"):
        try:
            ref = int(x.args[0][4:])
        except (ValueError, TypeError):
            ref = None

    add(tg_user, ref)
    r = user(tg_user.id)

    if r and r["banned"] and not is_admin(tg_user.id):
        await u.message.reply_text(
            "ð« HesabÄ±nÄ±z yÃ¶netici tarafÄ±ndan engellenmiÅtir."
        )
        return

    try:
        with open("HNK_logo.png", "rb") as f:
            await u.message.reply_photo(photo=f)
    except Exception:
        pass

    await u.message.reply_text(
        START_TEXT.format(
            bonus=get_setting("bonus", BONUS),
            daily=get_setting("daily", DAILY),
            minimum=get_setting("min_withdraw", MIN_W),
        ),
        parse_mode="Markdown",
        reply_markup=menu(),
    )


async def admin(u, x):
    if not is_admin(u.effective_user.id):
        await u.message.reply_text("â Bu bÃ¶lÃ¼m sadece yÃ¶neticiye aÃ§Ä±ktÄ±r.")
        return

    await u.message.reply_text(
        "âï¸ *HNK ADMIN PANEL*\n\n"
        "ð YÃ¶netici: Hasan\n"
        f"ð Admin ID: {ADMIN_ID}\n\n"
        "ð YÃ¶netici yetkileri aktif.\n\n"
        "AÅaÄÄ±daki menÃ¼den iÅlem seÃ§:",
        parse_mode="Markdown",
        reply_markup=admin_menu(),
    )


async def buttons(u, x):
    q = u.callback_query
    await q.answer()
    s = q.data or ""
    i = q.from_user.id

    if not user(i):
        add(q.from_user)

    r = user(i)

    if r and r["banned"] and not is_admin(i):
        await q.message.reply_text("ð« HesabÄ±nÄ±z yÃ¶netici tarafÄ±ndan engellenmiÅtir.")
        return

    admin_only = (
        s == "admin"
        or s.startswith("adm_")
        or s.startswith("wd_")
        or s.startswith("usr_")
    )
    if admin_only and not is_admin(i):
        await q.answer("â Yetkiniz yok.", show_alert=True)
        return

    # ADMIN MAIN
    if s == "admin":
        await safe_edit(
            q,
            "âï¸ *HNK ADMIN PANELÄ°*\n\n"
            "ð YÃ¶netici: Hasan\n"
            f"ð Admin ID: {ADMIN_ID}\n"
            "ð YÃ¶netici yetkileri aktif.",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )
        return

    # USER MENU
    if s == "mine":
        now = datetime.now(timezone.utc)
        daily = get_setting("daily", DAILY)

        if r["last_claim"]:
            try:
                last = datetime.fromisoformat(r["last_claim"])
            except ValueError:
                last = None

            if last and now - last < timedelta(hours=24):
                left = timedelta(hours=24) - (now - last)
                await safe_edit(
                    q,
                    f"â³ Sonraki kazÄ±m: "
                    f"{int(left.total_seconds() // 3600)} saat "
                    f"{int(left.total_seconds() % 3600 // 60)} dakika",
                    reply_markup=menu(),
                )
                return

        c = db()
        c.execute(
            """
            UPDATE users
            SET balance=balance+?, last_claim=?
            WHERE telegram_id=?
            """,
            (daily, now.isoformat(), i),
        )
        c.commit()
        c.close()

        new_balance = user(i)["balance"]
        await safe_edit(
            q,
            f"âï¸ *KazÄ±m baÅarÄ±lÄ±!*\n\n"
            f"+{daily:g} HNK\n"
            f"ð° Bakiye: *{new_balance:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    if s == "bal":
        await safe_edit(
            q,
            f"ð° Bakiye: *{r['balance']:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    if s == "wallet":
        x.user_data["state"] = "wallet"
        await safe_edit(
            q,
            "ð BSC/EVM cÃ¼zdan adresini gÃ¶nder.\n\nÃrnek:\n`0x1234...`",
            parse_mode="Markdown",
        )
        return

    if s == "with":
        minimum = get_setting("min_withdraw", MIN_W)
        if not r["wallet"]:
            x.user_data["state"] = "wallet_then_with"
            await safe_edit(q, "ð Ãnce BSC cÃ¼zdan adresini gÃ¶nder.")
        else:
            x.user_data["state"] = "with"
            await safe_edit(
                q,
                f"ð¸ MiktarÄ± yaz.\n\n"
                f"Minimum: *{minimum:g} HNK*\n"
                f"Bakiye: *{r['balance']:.2f} HNK*",
                parse_mode="Markdown",
            )
        return

    if s == "ref":
        m = await x.bot.get_me()
        await safe_edit(
            q,
            f"ð¥ Davet sayÄ±nÄ±z: *{r['referral_count']}*\n\n"
            f"ð Davet linkiniz:\n`https://t.me/{m.username}?start=ref_{i}`",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    if s == "stats":
        c = db()
        n = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_balance = c.execute(
            "SELECT COALESCE(SUM(balance),0) FROM users"
        ).fetchone()[0]
        total_ref = c.execute(
            "SELECT COALESCE(SUM(referral_count),0) FROM users"
        ).fetchone()[0]
        c.close()

        await safe_edit(
            q,
            f"ð *HNK Ä°statistik*\n\n"
            f"ð¥ KullanÄ±cÄ±: *{n}*\n"
            f"ð° KullanÄ±cÄ± bakiyeleri: *{total_balance:.2f} HNK*\n"
            f"ð¥ Toplam referans: *{total_ref}*",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    if s == "lead":
        c = db()
        rows = c.execute(
            """
            SELECT first_name, balance
            FROM users
            WHERE banned=0
            ORDER BY balance DESC
            LIMIT 10
            """
        ).fetchall()
        c.close()

        lines = []
        for n, z in enumerate(rows, 1):
            name = z["first_name"] or "KullanÄ±cÄ±"
            lines.append(f"{n}. {name} â {z['balance']:.2f} HNK")
        text_value = "\n".join(lines) or "HenÃ¼z kullanÄ±cÄ± yok."

        await safe_edit(
            q,
            f"ð *HNK Liderlik*\n\n{text_value}",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    if s == "about":
        await safe_edit(
            q,
            ABOUT_TEXT.format(
                minimum=get_setting("min_withdraw", MIN_W)
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("â¬ï¸ Ana MenÃ¼", callback_data="menu")]
            ]),
        )
        return

    if s in ("menu", "back"):
        await safe_edit(
            q,
            START_TEXT.format(
                bonus=get_setting("bonus", BONUS),
                daily=get_setting("daily", DAILY),
                minimum=get_setting("min_withdraw", MIN_W),
            ),
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    if s == "stars":
        await safe_edit(
            q,
            "â­ *HNK Stars*\n\n"
            "ð HNK Stars sistemi aktif!\n\n"
            "â­ Stars: 0\n"
            "ð Stars ile Ã¶zel Ã¶dÃ¼ller ve avantajlar yakÄ±nda aktif olacak.\n\n"
            "ð HNK Mining V2",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return

    # ADMIN USERS
    if s == "adm_users":
        c = db()
        total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = c.execute(
            "SELECT COUNT(*) FROM users WHERE banned=0"
        ).fetchone()[0]
        banned = c.execute(
            "SELECT COUNT(*) FROM users WHERE banned=1"
        ).fetchone()[0]
        rows = c.execute(
            """
            SELECT telegram_id, first_name, username, balance, referral_count
            FROM users ORDER BY created_at DESC LIMIT 15
            """
        ).fetchall()
        c.close()

        lines = []
        for z in rows:
            name = z["first_name"] or "KullanÄ±cÄ±"
            username = f" @{z['username']}" if z["username"] else ""
            lines.append(
                f"ð¤ {name}{username}\n"
                f"ð {z['telegram_id']}\n"
                f"ð° {z['balance']:.2f} HNK\n"
                f"ð¥ Ref: {z['referral_count']}"
            )
        users_text = "\n\n".join(lines) or "KullanÄ±cÄ± bulunamadÄ±."

        await safe_edit(
            q,
            f"ð¥ KULLANICILAR\n\n"
            f"Toplam: {total}\n"
            f"Aktif: {active}\n"
            f"Engelli: {banned}\n\n"
            f"{users_text}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ð Yenile", callback_data="adm_users")],
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
            ]),
        )
        return

    if s == "adm_stats":
        c = db()
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        balance = c.execute(
            "SELECT COALESCE(SUM(balance),0) FROM users"
        ).fetchone()[0]
        withdrawals = c.execute(
            "SELECT COUNT(*) FROM withdrawals"
        ).fetchone()[0]
        pending = c.execute(
            "SELECT COUNT(*) FROM withdrawals WHERE status='pending'"
        ).fetchone()[0]
        pending_amount = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='pending'"
        ).fetchone()[0]
        paid = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='approved'"
        ).fetchone()[0]
        c.close()

        await safe_edit(
            q,
            f"ð *HNK ADMIN Ä°STATÄ°STÄ°K*\n\n"
            f"ð¥ KullanÄ±cÄ±: *{users}*\n"
            f"ð° Toplam bakiye: *{balance:.2f} HNK*\n\n"
            f"ð¸ Toplam Ã§ekim: *{withdrawals}*\n"
            f"â³ Bekleyen: *{pending}*\n"
            f"â³ Bekleyen miktar: *{pending_amount:.2f} HNK*\n"
            f"â Onaylanan Ã§ekim: *{paid:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")]
            ]),
        )
        return

    if s == "adm_mining":
        daily = get_setting("daily", DAILY)
        await safe_edit(
            q,
            f"ð° *KAZIM AYARLARI*\n\n"
            f"âï¸ GÃ¼nlÃ¼k kazÄ±m: *{daily:g} HNK*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("âï¸ GÃ¼nlÃ¼k KazÄ±mÄ± DeÄiÅtir", callback_data="adm_set_daily")],
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
            ]),
        )
        return

    if s == "adm_set_daily":
        x.user_data["state"] = "admin_daily"
        await safe_edit(q, "âï¸ Yeni gÃ¼nlÃ¼k HNK miktarÄ±nÄ± yaz.\n\nÃrnek: `0.25`", parse_mode="Markdown")
        return

    if s == "adm_bonus":
        bonus = get_setting("bonus", BONUS)
        ref_bonus = get_setting("ref_bonus", REF_BONUS)
        minimum = get_setting("min_withdraw", MIN_W)
        await safe_edit(
            q,
            f"ð *BONUS AYARLARI*\n\n"
            f"ð BaÅlangÄ±Ã§ bonusu: *{bonus:g} HNK*\n"
            f"ð¥ Referans bonusu: *{ref_bonus:g} HNK*\n"
            f"ð¸ Minimum Ã§ekim: *{minimum:g} HNK*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ð BaÅlangÄ±Ã§ Bonusunu DeÄiÅtir", callback_data="adm_set_bonus")],
                [InlineKeyboardButton("ð¥ Referans Bonusunu DeÄiÅtir", callback_data="adm_set_refbonus")],
                [InlineKeyboardButton("ð¸ Minimum Ãekimi DeÄiÅtir", callback_data="adm_set_min")],
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
            ]),
        )
        return

    if s == "adm_set_bonus":
        x.user_data["state"] = "admin_bonus"
        await safe_edit(q, "ð Yeni baÅlangÄ±Ã§ bonusunu yaz.\n\nÃrnek: `1`", parse_mode="Markdown")
        return

    if s == "adm_set_refbonus":
        x.user_data["state"] = "admin_refbonus"
        await safe_edit(q, "ð¥ Yeni referans bonusunu yaz.\n\nÃrnek: `1`", parse_mode="Markdown")
        return

    if s == "adm_set_min":
        x.user_data["state"] = "admin_min"
        await safe_edit(q, "ð¸ Yeni minimum Ã§ekim miktarÄ±nÄ± yaz.\n\nÃrnek: `10`", parse_mode="Markdown")
        return

    if s == "adm_broadcast":
        x.user_data["state"] = "admin_broadcast"
        await safe_edit(
            q,
            "ð¢ *DUYURU MODU*\n\nGÃ¶nderilecek mesajÄ± yaz.\n\nMesaj aktif kullanÄ±cÄ±lara gÃ¶nderilecektir.",
            parse_mode="Markdown",
        )
        return

    if s == "adm_manage":
        x.user_data["state"] = "admin_manage"
        await safe_edit(
            q,
            "ð« *KULLANICI YÃNETÄ°MÄ°*\n\n"
            "YÃ¶netmek istediÄin kullanÄ±cÄ±nÄ±n Telegram ID'sini gÃ¶nder.\n\n"
            "Ãrnek:\n`8769533867`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")]
            ]),
        )
        return

    # WITHDRAWALS
    if s == "adm_withdrawals":
        c = db()
        rows = c.execute(
            """
            SELECT id, telegram_id, amount, wallet, created_at
            FROM withdrawals
            WHERE status='pending'
            ORDER BY id ASC LIMIT 10
            """
        ).fetchall()
        c.close()

        if not rows:
            await safe_edit(
                q,
                "ð¸ *ÃEKÄ°M TALEPLERÄ°*\n\nâ³ Bekleyen Ã§ekim bulunmuyor.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")]
                ]),
            )
            return

        text_value = "ð¸ *BEKLEYEN ÃEKÄ°MLER*\n\n"
        button_rows = []
        for z in rows:
            text_value += (
                f"ð Talep: *#{z['id']}*\n"
                f"ð¤ KullanÄ±cÄ±: `{z['telegram_id']}`\n"
                f"ð° Miktar: *{z['amount']:.2f} HNK*\n"
                f"ð CÃ¼zdan: `{z['wallet']}`\n\n"
            )
            button_rows.append([
                InlineKeyboardButton(f"#{z['id']} â", callback_data=f"wd_approve_{z['id']}"),
                InlineKeyboardButton(f"#{z['id']} â", callback_data=f"wd_reject_{z['id']}"),
            ])
        button_rows += [
            [InlineKeyboardButton("ð Yenile", callback_data="adm_withdrawals")],
            [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
        ]
        await safe_edit(
            q,
            text_value,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(button_rows),
        )
        return

    if s.startswith("wd_approve_"):
        try:
            wid = int(s.rsplit("_", 1)[1])
        except ValueError:
            await q.answer("GeÃ§ersiz talep.", show_alert=True)
            return

        c = db()
        w = c.execute(
            "SELECT * FROM withdrawals WHERE id=? AND status='pending'",
            (wid,),
        ).fetchone()
        if not w:
            c.close()
            await q.answer("Talep bulunamadÄ± veya zaten iÅlendi.", show_alert=True)
            return

        c.execute(
            "UPDATE withdrawals SET status='approved' WHERE id=? AND status='pending'",
            (wid,),
        )
        c.commit()
        c.close()

        try:
            await x.bot.send_message(
                chat_id=w["telegram_id"],
                text=(
                    "â *Ãekim talebiniz onaylandÄ±!*\n\n"
                    f"ð° Miktar: *{w['amount']:.2f} HNK*\n"
                    f"ð CÃ¼zdan: `{w['wallet']}`\n\n"
                    "Transfer iÅlemi yÃ¶netici tarafÄ±ndan gerÃ§ekleÅtirilecektir."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

        await safe_edit(
            q,
            f"â *#{wid} numaralÄ± Ã§ekim onaylandÄ±.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ð¸ Ãekimlere DÃ¶n", callback_data="adm_withdrawals")],
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
            ]),
        )
        return

    if s.startswith("wd_reject_"):
        try:
            wid = int(s.rsplit("_", 1)[1])
        except ValueError:
            await q.answer("GeÃ§ersiz talep.", show_alert=True)
            return

        c = db()
        w = c.execute(
            "SELECT * FROM withdrawals WHERE id=? AND status='pending'",
            (wid,),
        ).fetchone()
        if not w:
            c.close()
            await q.answer("Talep bulunamadÄ± veya zaten iÅlendi.", show_alert=True)
            return

        c.execute(
            "UPDATE users SET balance=balance+? WHERE telegram_id=?",
            (w["amount"], w["telegram_id"]),
        )
        c.execute(
            "UPDATE withdrawals SET status='rejected' WHERE id=? AND status='pending'",
            (wid,),
        )
        c.commit()
        c.close()

        try:
            await x.bot.send_message(
                chat_id=w["telegram_id"],
                text=(
                    "â *Ãekim talebiniz reddedildi.*\n\n"
                    f"ð° Miktar: *{w['amount']:.2f} HNK*\n"
                    "ð° Tutar hesabÄ±nÄ±za iade edildi."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

        await safe_edit(
            q,
            f"â *#{wid} numaralÄ± Ã§ekim reddedildi.*\n\n"
            f"ð° {w['amount']:.2f} HNK kullanÄ±cÄ±ya iade edildi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ð¸ Ãekimlere DÃ¶n", callback_data="adm_withdrawals")],
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
            ]),
        )
        return

    if s == "adm_stars":
        await safe_edit(
            q,
            "â­ *HNK STARS ADMIN*\n\n"
            "ð Stars sistemi hazÄ±rlanÄ±yor.\n\n"
            "Bu bÃ¶lÃ¼m ileride Stars bakiyeleri, Ã¶dÃ¼ller ve kampanyalarÄ± yÃ¶netmek iÃ§in kullanÄ±labilir.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")]
            ]),
        )
        return

    # USER MANAGEMENT ACTIONS
    if s in ("usr_balance", "usr_ban"):
        uid = x.user_data.get("manage_user")
        if not uid:
            await q.answer("Ãnce kullanÄ±cÄ± seÃ§in.", show_alert=True)
            return

        if uid == ADMIN_ID and s == "usr_ban":
            await q.answer("Ana yÃ¶netici engellenemez.", show_alert=True)
            return

        if s == "usr_balance":
            x.user_data["state"] = "admin_balance"
            await q.message.reply_text(
                "ð° Bakiye deÄiÅikliÄini yaz.\n\n"
                "Pozitif deÄer ekler: `10`\n"
                "Negatif deÄer dÃ¼Åer: `-10`",
                parse_mode="Markdown",
            )
            return

        c = db()
        row = c.execute(
            "SELECT banned FROM users WHERE telegram_id=?",
            (uid,),
        ).fetchone()
        if not row:
            c.close()
            await q.answer("KullanÄ±cÄ± bulunamadÄ±.", show_alert=True)
            return

        new_status = 0 if row["banned"] else 1
        c.execute(
            "UPDATE users SET banned=? WHERE telegram_id=?",
            (new_status, uid),
        )
        c.commit()
        c.close()

        x.user_data["state"] = None
        await q.message.reply_text(
            ("ð« KullanÄ±cÄ± engellendi." if new_status else "â KullanÄ±cÄ±nÄ±n engeli kaldÄ±rÄ±ldÄ±.")
            + f"\n\nð {uid}",
            reply_markup=admin_menu(),
        )
        return


async def text(u, x):
    i = u.effective_user.id
    st = x.user_data.get("state")
    if not st:
        return

    r = user(i)
    if not r:
        add(u.effective_user)
        r = user(i)

    if r and r["banned"] and not is_admin(i):
        x.user_data["state"] = None
        await u.message.reply_text("ð« HesabÄ±nÄ±z yÃ¶netici tarafÄ±ndan engellenmiÅtir.")
        return

    t = u.message.text.strip()

    if st.startswith("admin_") and not is_admin(i):
        x.user_data["state"] = None
        return

    if st == "admin_daily":
        try:
            value = float(t.replace(",", "."))
        except ValueError:
            await u.message.reply_text("â GeÃ§erli bir sayÄ± gir.")
            return
        if value <= 0:
            await u.message.reply_text("â DeÄer 0'dan bÃ¼yÃ¼k olmalÄ±.")
            return
        set_setting("daily", value)
        x.user_data["state"] = None
        await u.message.reply_text(
            f"â GÃ¼nlÃ¼k kazÄ±m gÃ¼ncellendi.\n\nâï¸ Yeni deÄer: {value:g} HNK",
            reply_markup=admin_menu(),
        )
        return

    if st == "admin_bonus":
        try:
            value = float(t.replace(",", "."))
        except ValueError:
            await u.message.reply_text("â GeÃ§erli bir sayÄ± gir.")
            return
        if value < 0:
            await u.message.reply_text("â Bonus negatif olamaz.")
            return
        set_setting("bonus", value)
        x.user_data["state"] = None
        await u.message.reply_text(
            f"â BaÅlangÄ±Ã§ bonusu gÃ¼ncellendi.\n\nð Yeni bonus: {value:g} HNK",
            reply_markup=admin_menu(),
        )
        return

    if st == "admin_refbonus":
        try:
            value = float(t.replace(",", "."))
        except ValueError:
            await u.message.reply_text("â GeÃ§erli bir sayÄ± gir.")
            return
        if value < 0:
            await u.message.reply_text("â Bonus negatif olamaz.")
            return
        set_setting("ref_bonus", value)
        x.user_data["state"] = None
        await u.message.reply_text(
            f"â Referans bonusu gÃ¼ncellendi.\n\nð¥ Yeni bonus: {value:g} HNK",
            reply_markup=admin_menu(),
        )
        return

    if st == "admin_min":
        try:
            value = float(t.replace(",", "."))
        except ValueError:
            await u.message.reply_text("â GeÃ§erli bir sayÄ± gir.")
            return
        if value <= 0:
            await u.message.reply_text("â Minimum Ã§ekim 0'dan bÃ¼yÃ¼k olmalÄ±.")
            return
        set_setting("min_withdraw", value)
        x.user_data["state"] = None
        await u.message.reply_text(
            f"â Minimum Ã§ekim gÃ¼ncellendi.\n\nð¸ Yeni minimum: {value:g} HNK",
            reply_markup=admin_menu(),
        )
        return

    if st == "admin_broadcast":
        c = db()
        rows = c.execute("SELECT telegram_id FROM users WHERE banned=0").fetchall()
        c.close()

        sent = 0
        failed = 0
        for z in rows:
            try:
                await x.bot.send_message(chat_id=z["telegram_id"], text=t)
                sent += 1
            except Exception:
                failed += 1

        x.user_data["state"] = None
        await u.message.reply_text(
            f"ð¢ *DUYURU TAMAMLANDI*\n\n"
            f"â GÃ¶nderildi: *{sent}*\n"
            f"â BaÅarÄ±sÄ±z: *{failed}*",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )
        return

    if st == "admin_manage":
        try:
            uid = int(t)
        except ValueError:
            await u.message.reply_text("â GeÃ§erli Telegram ID gir.")
            return

        r = user(uid)
        if not r:
            x.user_data["state"] = None
            await u.message.reply_text("â KullanÄ±cÄ± bulunamadÄ±.", reply_markup=admin_menu())
            return

        x.user_data["manage_user"] = uid
        x.user_data["state"] = "admin_user_action"
        status = "ð« Engelli" if r["banned"] else "â Aktif"

        await u.message.reply_text(
            f"ð¤ KULLANICI\n\n"
            f"ð {uid}\n"
            f"ð¤ {r['first_name'] or 'KullanÄ±cÄ±'}\n"
            f"ð° Bakiye: {r['balance']:.2f} HNK\n"
            f"ð¥ Referans: {r['referral_count']}\n"
            f"ð Durum: {status}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ð° Bakiye DeÄiÅtir", callback_data="usr_balance")],
                [InlineKeyboardButton("ð« Engelle / AÃ§", callback_data="usr_ban")],
                [InlineKeyboardButton("â¬ï¸ Admin", callback_data="admin")],
            ]),
        )
        return

    if st == "admin_balance":
        uid = x.user_data.get("manage_user")
        if not uid:
            x.user_data["state"] = None
            return

        if uid == ADMIN_ID:
            x.user_data["state"] = None
            await u.message.reply_text("â Ana yÃ¶netici bakiyesi bu menÃ¼den deÄiÅtirilemez.", reply_markup=admin_menu())
            return

        try:
            amount = float(t.replace(",", "."))
        except ValueError:
            await u.message.reply_text("â Ãrnek: `5` veya `-5`", parse_mode="Markdown")
            return

        c = db()
        row = c.execute(
            "SELECT balance FROM users WHERE telegram_id=?",
            (uid,),
        ).fetchone()
        if not row:
            c.close()
            x.user_data["state"] = None
            await u.message.reply_text("â KullanÄ±cÄ± bulunamadÄ±.", reply_markup=admin_menu())
            return

        new_balance = row["balance"] + amount
        if new_balance < 0:
            c.close()
            await u.message.reply_text("â Bakiye 0'Ä±n altÄ±na inemez.")
            return

        c.execute(
            "UPDATE users SET balance=? WHERE telegram_id=?",
            (new_balance, uid),
        )
        c.commit()
        c.close()

        x.user_data["state"] = None
        await u.message.reply_text(
            f"â Bakiye gÃ¼ncellendi.\n\n"
            f"ð {uid}\n"
            f"ð° Yeni bakiye: *{new_balance:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )
        return

    if st in ("wallet", "wallet_then_with"):
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", t):
            await u.message.reply_text("â GeÃ§erli BSC/EVM adresi gir.")
            return

        c = db()
        c.execute(
            "UPDATE users SET wallet=? WHERE telegram_id=?",
            (t, i),
        )
        c.commit()
        c.close()

        next_state = "with" if st == "wallet_then_with" else None
        x.user_data["state"] = next_state

        await u.message.reply_text(
            "â CÃ¼zdan kaydedildi."
            + ("\nÅimdi Ã§ekim miktarÄ±nÄ± yaz." if next_state == "with" else ""),
            reply_markup=menu() if not next_state else None,
        )
        return

    if st == "with":
        try:
            amount = float(t.replace(",", "."))
        except ValueError:
            await u.message.reply_text("â MiktarÄ± sayÄ± olarak yaz.")
            return

        if amount <= 0:
            await u.message.reply_text("â Miktar 0'dan bÃ¼yÃ¼k olmalÄ±.")
            return

        minimum = get_setting("min_withdraw", MIN_W)
        if amount < minimum:
            await u.message.reply_text(f"â Minimum Ã§ekim: {minimum:g} HNK")
            return

        c = db()
        c.execute("BEGIN IMMEDIATE")
        row = c.execute(
            "SELECT balance,wallet FROM users WHERE telegram_id=?",
            (i,),
        ).fetchone()

        if not row or not row["wallet"]:
            c.rollback()
            c.close()
            x.user_data["state"] = None
            await u.message.reply_text("â CÃ¼zdan bulunamadÄ±.", reply_markup=menu())
            return

        if amount > row["balance"]:
            c.rollback()
            c.close()
            await u.message.reply_text("â Bakiye yetersiz.")
            return

        c.execute(
            """
            UPDATE users SET balance=balance-?
            WHERE telegram_id=? AND balance>=?
            """,
            (amount, i, amount),
        )

        if c.execute("SELECT changes()").fetchone()[0] != 1:
            c.rollback()
            c.close()
            await u.message.reply_text("â Ä°Ålem sÄ±rasÄ±nda bakiye deÄiÅti. Tekrar deneyin.")
            return

        c.execute(
            """
            INSERT INTO withdrawals
            (telegram_id, amount, wallet, status, created_at)
            VALUES(?,?,?,?,?)
            """,
            (
                i,
                amount,
                row["wallet"],
                "pending",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        c.commit()
        c.close()

        x.user_data["state"] = None
        await u.message.reply_text(
            f"ð¸ *Ãekim talebi oluÅturuldu!*\n\n"
            f"ð° Miktar: *{amount:g} HNK*\n"
            f"ð CÃ¼zdan: `{row['wallet']}`\n"
            f"ð Durum: *Bekliyor*",
            parse_mode="Markdown",
            reply_markup=menu(),
        )
        return


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"HNK Mining Bot OK")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def run():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN bulunamadÄ±")

    init()

    threading.Thread(
        target=run_health_server,
        daemon=True,
    ).start()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text))

    print("HNK Mining Bot baÅlatÄ±lÄ±yor...")
    print("Admin ID:", ADMIN_ID)

    app.run_polling()


if __name__ == "__main__":
    run()
