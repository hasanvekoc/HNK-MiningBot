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

ADMIN_ID = 8769533867

DAILY = 0.25
BONUS = 1.0
REF_BONUS = 1.0
MIN_W = 10.0


# =========================================================
# DATABASE
# =========================================================

def db():
    c = sqlite3.connect(DB)
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

    # Eski database kullananlar için yeni alanlar
    if not column_exists(c, "users", "banned"):
        c.execute(
            "ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0"
        )

    # Varsayılan ayarlar
    defaults = {
        "daily": str(DAILY),
        "bonus": str(BONUS),
        "ref_bonus": str(REF_BONUS),
        "min_withdraw": str(MIN_W),
    }

    for key, value in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, value)
        )

    c.commit()
    c.close()


def get_setting(key, default):
    c = db()
    r = c.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    c.close()

    if not r:
        return default

    try:
        return float(r["value"])
    except Exception:
        return default


def set_setting(key, value):
    c = db()
    c.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
        (key, str(value))
    )
    c.commit()
    c.close()


def user(i):
    c = db()
    r = c.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (i,)
    ).fetchone()
    c.close()
    return r


def add(u, ref=None):
    if user(u.id):
        return

    starting_bonus = get_setting("bonus", BONUS)
    referral_bonus = get_setting("ref_bonus", REF_BONUS)

    c = db()

    c.execute(
        """
        INSERT INTO users
        (telegram_id, username, first_name, balance,
         last_claim, wallet, referral_count, created_at, banned)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            u.id,
            u.username,
            u.first_name,
            starting_bonus,
            None,
            None,
            0,
            datetime.now(timezone.utc).isoformat(),
            0,
        )
    )

    if ref and ref != u.id:
        c.execute(
            """
            UPDATE users
            SET balance=balance+?,
                referral_count=referral_count+1
            WHERE telegram_id=?
            """,
            (referral_bonus, ref)
        )

    c.commit()
    c.close()


# =========================================================
# HELPERS
# =========================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


def money(value):
    return f"{float(value):.2f}"


async def safe_edit(q, text, **kwargs):
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


# =========================================================
# USER MENU
# =========================================================

def menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⛏️ Madenciliği Başlat",
                callback_data="mine"
            ),
            InlineKeyboardButton(
                "💰 Bakiyem",
                callback_data="bal"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 Arkadaşlarını Davet Et",
                callback_data="ref"
            ),
            InlineKeyboardButton(
                "👛 Cüzdanım",
                callback_data="wallet"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 Çekim",
                callback_data="with"
            ),
            InlineKeyboardButton(
                "⭐ HNK Stars",
                callback_data="stars"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 İstatistik",
                callback_data="stats"
            ),
            InlineKeyboardButton(
                "👑 Liderlik",
                callback_data="lead"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ HNK Hakkında",
                callback_data="about"
            )
        ]
    ])


# =========================================================
# ADMIN MENU
# =========================================================

def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 Kullanıcılar",
                callback_data="adm_users"
            ),
            InlineKeyboardButton(
                "📊 İstatistik",
                callback_data="adm_stats"
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Kazım Ayarları",
                callback_data="adm_mining"
            ),
            InlineKeyboardButton(
                "🎁 Bonus Ayarları",
                callback_data="adm_bonus"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Duyuru Gönder",
                callback_data="adm_broadcast"
            ),
            InlineKeyboardButton(
                "🚫 Kullanıcı Yönetimi",
                callback_data="adm_manage"
            )
        ],
        [
            InlineKeyboardButton(
                "💸 Çekim Talepleri",
                callback_data="adm_withdrawals"
            ),
            InlineKeyboardButton(
                "⭐ Stars",
                callback_data="adm_stars"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Ana Menü",
                callback_data="back"
            )
        ]
    ])


# =========================================================
# TEXTS
# =========================================================

START_TEXT = (
    "🪙 *Hyper Nexus Kingdom — HNK Mining V2*\n\n"
    "🎁 Başlangıç: *{bonus:g} HNK*\n"
    "⛏️ Günlük kazım: *{daily:g} HNK*\n"
    "💸 Minimum çekim: *{minimum:g} HNK*\n\n"
    "Menüden devam et:"
)


ABOUT_TEXT = (
    "🪙 *HYPER NEXUS KINGDOM — HNK*\n\n"
    "🌐 *Proje:* Topluluk odaklı dijital madencilik ekosistemi\n"
    "💰 *Toplam Arz:* 1,000,000,000 HNK\n"
    "🔢 *Ondalık:* 18\n"
    "💸 *Minimum Çekim:* {minimum:g} HNK\n"
    "👥 *Referans Sistemi:* Aktif\n"
    "👛 *BSC/EVM Cüzdan:* Destekleniyor\n\n"
    "🎯 *Projenin Amacı*\n"
    "HNK; insanlar, teknoloji ve dijital fırsatları "
    "bir araya getiren topluluk odaklı bir ekosistem "
    "oluşturmayı hedefler.\n\n"
    "🗺️ *Yol Haritası*\n"
    "✅ Faz 1 — Mining botu ve topluluk\n"
    "✅ Faz 2 — Cüzdan ve referans sistemi\n"
    "▫️ Faz 3 — Testnet, likidite ve teknik altyapı\n"
    "▫️ Faz 4 — Borsa başvuruları ve ekosistem geliştirme\n\n"
    "📌 *Token Sözleşmesi*\n"
    "BSC sözleşme adresi yayına alındığında bu bölüme eklenecektir.\n\n"
    "🔗 *HNK*\n"
    "People • Technology • Opportunity\n\n"
    "_A Stronger Tomorrow Together_\n\n"
    "© 2026 Hyper Nexus Kingdom"
)


# =========================================================
# START
# =========================================================

async def start(u, x):
    ref = None

    if x.args and x.args[0].startswith("ref_"):
        try:
            ref = int(x.args[0][4:])
        except Exception:
            pass

    add(u.effective_user, ref)

    r = user(u.effective_user.id)

    if r and r["banned"]:
        await u.message.reply_text(
            "🚫 Hesabınız yönetici tarafından engellenmiştir."
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
        reply_markup=menu()
    )


# =========================================================
# ADMIN
# =========================================================

async def admin(u, x):
    if not is_admin(u.effective_user.id):
        await u.message.reply_text(
            "⛔ Bu bölüm sadece yöneticiye açıktır."
        )
        return

    await u.message.reply_text(
        "⚔️ *HNK ADMIN PANEL*\n\n"
        "👑 Yönetici: Hasan\n"
        "🆔 Admin ID: 8769533867\n\n"
        "🔐 Yönetici yetkileri aktif.\n\n"
        "Aşağıdaki menüden işlem seç:",
        parse_mode="Markdown",
        reply_markup=admin_menu()
    )


# =========================================================
# USER BUTTONS
# =========================================================

async def buttons(u, x):
    q = u.callback_query
    await q.answer()

    i = q.from_user.id
    s = q.data

    if not user(i):
        add(q.from_user)

    r = user(i)

    if r and r["banned"] and not is_admin(i):
        await q.message.reply_text(
            "🚫 Hesabınız yönetici tarafından engellenmiştir."
        )
        return

    # =====================================================
    # ADMIN SECURITY
    # =====================================================

    admin_callbacks = (
        "adm_",
        "wd_",
        "usr_",
        "admin"
    )

    if s.startswith(admin_callbacks):
        if not is_admin(i):
            await q.answer(
                "⛔ Yetkiniz yok.",
                show_alert=True
            )
            return

    # =====================================================
    # ADMIN MAIN
    # =====================================================

    if s == "admin":
        if not is_admin(i):
            await q.message.reply_text(
                "⛔ Bu bölüm sadece yöneticiye açıktır."
            )
            return

        await safe_edit(
            q,
            "⚔️ *HNK ADMIN PANELİ*\n\n"
            "👑 Yönetici: Hasan\n"
            "🔐 Yönetici yetkileri aktif.",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # STARS
    # =====================================================

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

    # =====================================================
    # MINING
    # =====================================================

    if s == "mine":
        now = datetime.now(timezone.utc)
        daily = get_setting("daily", DAILY)

        if r["last_claim"]:
            last = datetime.fromisoformat(r["last_claim"])

            if now - last < timedelta(hours=24):
                left = timedelta(hours=24) - (now - last)

                await safe_edit(
                    q,
                    f"⏳ Sonraki kazım: "
                    f"{int(left.total_seconds() // 3600)} saat "
                    f"{int(left.total_seconds() % 3600 // 60)} dakika",
                    reply_markup=menu()
                )
                return

        c = db()

        c.execute(
            """
            UPDATE users
            SET balance=balance+?,
                last_claim=?
            WHERE telegram_id=?
            """,
            (daily, now.isoformat(), i)
        )

        c.commit()
        c.close()

        new_balance = user(i)["balance"]

        await safe_edit(
            q,
            f"⛏️ *Kazım başarılı!*\n\n"
            f"+{daily:g} HNK\n"
            f"💰 Bakiye: *{new_balance:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    # =====================================================
    # BALANCE
    # =====================================================

    elif s == "bal":
        await safe_edit(
            q,
            f"💰 Bakiye: *{r['balance']:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    # =====================================================
    # WALLET
    # =====================================================

    elif s == "wallet":
        x.user_data["state"] = "wallet"

        await safe_edit(
            q,
            "👛 BSC/EVM cüzdan adresini gönder.\n\n"
            "Örnek:\n"
            "`0x1234...`",
            parse_mode="Markdown"
        )

    # =====================================================
    # WITHDRAW
    # =====================================================

    elif s == "with":
        minimum = get_setting("min_withdraw", MIN_W)

        if not r["wallet"]:
            x.user_data["state"] = "wallet_then_with"

            await safe_edit(
                q,
                "👛 Önce BSC cüzdan adresini gönder."
            )

        else:
            x.user_data["state"] = "with"

            await safe_edit(
                q,
                f"💸 Miktarı yaz.\n\n"
                f"Minimum: *{minimum:g} HNK*\n"
                f"Bakiye: *{r['balance']:.2f} HNK*",
                parse_mode="Markdown"
            )

    # =====================================================
    # REFERRAL
    # =====================================================

    elif s == "ref":
        m = await x.bot.get_me()

        await safe_edit(
            q,
            f"👥 Davet sayınız: *{r['referral_count']}*\n\n"
            f"🔗 Davet linkiniz:\n"
            f"`https://t.me/{m.username}?start=ref_{i}`",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    # =====================================================
    # USER STATS
    # =====================================================

    elif s == "stats":
        c = db()

        n = c.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        total_balance = c.execute(
            "SELECT COALESCE(SUM(balance),0) FROM users"
        ).fetchone()[0]

        total_ref = c.execute(
            "SELECT COALESCE(SUM(referral_count),0) FROM users"
        ).fetchone()[0]

        c.close()

        await safe_edit(
            q,
            f"📊 *HNK İstatistik*\n\n"
            f"👥 Kullanıcı: *{n}*\n"
            f"💰 Kullanıcı bakiyeleri: *{total_balance:.2f} HNK*\n"
            f"👥 Toplam referans: *{total_ref}*",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    # =====================================================
    # LEADERBOARD
    # =====================================================

    elif s == "lead":
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

        text_value = "\n".join(
            f"{n}. {z['first_name'] or 'Kullanıcı'} — "
            f"{z['balance']:.2f} HNK"
            for n, z in enumerate(rows, 1)
        )

        if not text_value:
            text_value = "Henüz kullanıcı yok."

        await safe_edit(
            q,
            f"👑 *HNK Liderlik*\n\n{text_value}",
            parse_mode="Markdown",
            reply_markup=menu()
        )

    # =====================================================
    # ABOUT
    # =====================================================

    elif s == "about":
        await safe_edit(
            q,
            ABOUT_TEXT.format(
                minimum=get_setting(
                    "min_withdraw",
                    MIN_W
                )
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Ana Menü",
                        callback_data="menu"
                    )
                ]
            ])
        )

    # =====================================================
    # BACK TO MENU
    # =====================================================

    elif s == "menu":
        await safe_edit(
            q,
            START_TEXT.format(
                bonus=get_setting("bonus", BONUS),
                daily=get_setting("daily", DAILY),
                minimum=get_setting("min_withdraw", MIN_W),
            ),
            parse_mode="Markdown",
            reply_markup=menu()
        )

    # =====================================================
    # ADMIN USERS
    # =====================================================

    elif s == "adm_users":
        c = db()

        total = c.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = c.execute(
            "SELECT COUNT(*) FROM users WHERE banned=0"
        ).fetchone()[0]

        banned = c.execute(
            "SELECT COUNT(*) FROM users WHERE banned=1"
        ).fetchone()[0]

        rows = c.execute(
            """
            SELECT telegram_id, first_name, username,
                   balance, referral_count
            FROM users
            ORDER BY created_at DESC
            LIMIT 15
            """
        ).fetchall()

        c.close()

        lines = []

        for z in rows:
            name = z["first_name"] or "Kullanıcı"

            if z["username"]:
                name += f" @{z['username']}"

            lines.append(
                f"👤 {name}\n"
                f"🆔 {z['telegram_id']}\n"
                f"💰 {z['balance']:.2f} HNK\n"
                f"👥 Ref: {z['referral_count']}"
            )

        users_text = "\n\n".join(lines)

        if not users_text:
            users_text = "Kullanıcı bulunamadı."

        await safe_edit(
            q,
            f"👥 *KULLANICILAR*\n\n"
            f"Toplam: *{total}*\n"
            f"Aktif: *{active}*\n"
            f"Engelli: *{banned}*\n\n"
            f"{users_text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 Yenile",
                        callback_data="adm_users"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    # =====================================================
    # ADMIN STATS
    # =====================================================

    elif s == "adm_stats":
        c = db()

        users = c.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        balance = c.execute(
            "SELECT COALESCE(SUM(balance),0) FROM users"
        ).fetchone()[0]

        withdrawals = c.execute(
            "SELECT COUNT(*) FROM withdrawals"
        ).fetchone()[0]

        pending = c.execute(
            """
            SELECT COUNT(*)
            FROM withdrawals
            WHERE status='pending'
            """
        ).fetchone()[0]

        pending_amount = c.execute(
            """
            SELECT COALESCE(SUM(amount),0)
            FROM withdrawals
            WHERE status='pending'
            """
        ).fetchone()[0]

        paid = c.execute(
            """
            SELECT COALESCE(SUM(amount),0)
            FROM withdrawals
            WHERE status='approved'
            """
        ).fetchone()[0]

        c.close()

        await safe_edit(
            q,
            f"📊 *HNK ADMIN İSTATİSTİK*\n\n"
            f"👥 Kullanıcı: *{users}*\n"
            f"💰 Toplam bakiye: *{balance:.2f} HNK*\n\n"
            f"💸 Toplam çekim: *{withdrawals}*\n"
            f"⏳ Bekleyen: *{pending}*\n"
            f"⏳ Bekleyen miktar: *{pending_amount:.2f} HNK*\n"
            f"✅ Onaylanan çekim: *{paid:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    # =====================================================
    # ADMIN MINING SETTINGS
    # =====================================================

    elif s == "adm_mining":
        daily = get_setting("daily", DAILY)

        await safe_edit(
            q,
            f"💰 *KAZIM AYARLARI*\n\n"
            f"⛏️ Günlük kazım: *{daily:g} HNK*\n\n"
            f"Yeni günlük miktarı yazmak için aşağıdaki butona bas.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✏️ Günlük Kazımı Değiştir",
                        callback_data="adm_set_daily"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    elif s == "adm_set_daily":
        x.user_data["state"] = "admin_daily"

        await safe_edit(
            q,
            "⛏️ Yeni günlük HNK miktarını yaz.\n\n"
            "Örnek: `0.25`",
            parse_mode="Markdown"
        )

    # =====================================================
    # ADMIN BONUS SETTINGS
    # =====================================================

    elif s == "adm_bonus":
        bonus = get_setting("bonus", BONUS)
        ref_bonus = get_setting("ref_bonus", REF_BONUS)
        minimum = get_setting("min_withdraw", MIN_W)

        await safe_edit(
            q,
            f"🎁 *BONUS AYARLARI*\n\n"
            f"🎁 Başlangıç bonusu: *{bonus:g} HNK*\n"
            f"👥 Referans bonusu: *{ref_bonus:g} HNK*\n"
            f"💸 Minimum çekim: *{minimum:g} HNK*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🎁 Başlangıç Bonusunu Değiştir",
                        callback_data="adm_set_bonus"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "👥 Referans Bonusunu Değiştir",
                        callback_data="adm_set_refbonus"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💸 Minimum Çekimi Değiştir",
                        callback_data="adm_set_min"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    elif s == "adm_set_bonus":
        x.user_data["state"] = "admin_bonus"

        await safe_edit(
            q,
            "🎁 Yeni başlangıç bonusunu yaz.\n\n"
            "Örnek: `1`",
            parse_mode="Markdown"
        )

    elif s == "adm_set_refbonus":
        x.user_data["state"] = "admin_refbonus"

        await safe_edit(
            q,
            "👥 Yeni referans bonusunu yaz.\n\n"
            "Örnek: `1`",
            parse_mode="Markdown"
        )

    elif s == "adm_set_min":
        x.user_data["state"] = "admin_min"

        await safe_edit(
            q,
            "💸 Yeni minimum çekim miktarını yaz.\n\n"
            "Örnek: `10`",
            parse_mode="Markdown"
        )

    # =====================================================
    # BROADCAST
    # =====================================================

    elif s == "adm_broadcast":
        x.user_data["state"] = "admin_broadcast"

        await safe_edit(
            q,
            "📢 *DUYURU MODU*\n\n"
            "Gönderilecek mesajı yaz.\n\n"
            "Mesaj aktif kullanıcılara gönderilecektir.",
            parse_mode="Markdown"
        )

    # =====================================================
    # USER MANAGEMENT
    # =====================================================

   elif s == "adm_manage":
        if not is_admin(i):
            await q.answer(
                "⛔ Yetkiniz yok.",
                show_alert=True
            )
            return

        x.user_data["state"] = "admin_manage"

        await safe_edit(
            q,
            "🚫 *KULLANICI YÖNETİMİ*\n\n"
            "Yönetmek istediğin kullanıcının Telegram ID'sini gönder.\n\n"
            "Örnek:\n"
            "`8769533867`\n\n"
            "ID'yi mesaj olarak gönder.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )
        return
    # =====================================================
    # WITHDRAWAL LIST
    # =====================================================

    elif s == "adm_withdrawals":
        c = db()

        rows = c.execute(
            """
            SELECT id, telegram_id, amount, wallet, created_at
            FROM withdrawals
            WHERE status='pending'
            ORDER BY id ASC
            LIMIT 10
            """
        ).fetchall()

        c.close()

        if not rows:
            await safe_edit(
                q,
                "💸 *ÇEKİM TALEPLERİ*\n\n"
                "⏳ Bekleyen çekim bulunmuyor.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⬅️ Admin",
                            callback_data="admin"
                        )
                    ]
                ])
            )
            return

        buttons_list = []

        text_value = "💸 *BEKLEYEN ÇEKİMLER*\n\n"

        for z in rows:
            text_value += (
                f"🆔 Talep: *#{z['id']}*\n"
                f"👤 Kullanıcı: `{z['telegram_id']}`\n"
                f"💰 Miktar: *{z['amount']:.2f} HNK*\n"
                f"👛 Cüzdan: `{z['wallet']}`\n\n"
            )

            buttons_list.append([
                InlineKeyboardButton(
                    f"#{z['id']} ✅",
                    callback_data=f"wd_approve_{z['id']}"
                ),
                InlineKeyboardButton(
                    f"#{z['id']} ❌",
                    callback_data=f"wd_reject_{z['id']}"
                )
            ])

        buttons_list.append([
            InlineKeyboardButton(
                "🔄 Yenile",
                callback_data="adm_withdrawals"
            )
        ])

        buttons_list.append([
            InlineKeyboardButton(
                "⬅️ Admin",
                callback_data="admin"
            )
        ])

        await safe_edit(
            q,
            text_value,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons_list)
        )

    # =====================================================
    # APPROVE WITHDRAWAL
    # =====================================================

    elif s.startswith("wd_approve_"):
        wid = int(s.split("_")[-1])

        c = db()

        w = c.execute(
            """
            SELECT *
            FROM withdrawals
            WHERE id=? AND status='pending'
            """,
            (wid,)
        ).fetchone()

        if not w:
            c.close()

            await q.answer(
                "Talep bulunamadı veya zaten işlendi.",
                show_alert=True
            )
            return

        c.execute(
            """
            UPDATE withdrawals
            SET status='approved'
            WHERE id=?
            """,
            (wid,)
        )

        c.commit()
        c.close()

        try:
            await x.bot.send_message(
                chat_id=w["telegram_id"],
                text=(
                    f"✅ *Çekim talebiniz onaylandı!*\n\n"
                    f"💰 Miktar: *{w['amount']:.2f} HNK*\n"
                    f"👛 Cüzdan: `{w['wallet']}`\n\n"
                    f"Transfer işlemi yönetici tarafından "
                    f"gerçekleştirilecektir."
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass

        await safe_edit(
            q,
            f"✅ *#{wid} numaralı çekim onaylandı.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💸 Çekimlere Dön",
                        callback_data="adm_withdrawals"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    # =====================================================
    # REJECT WITHDRAWAL
    # =====================================================

    elif s.startswith("wd_reject_"):
        wid = int(s.split("_")[-1])

        c = db()

        w = c.execute(
            """
            SELECT *
            FROM withdrawals
            WHERE id=? AND status='pending'
            """,
            (wid,)
        ).fetchone()

        if not w:
            c.close()

            await q.answer(
                "Talep bulunamadı veya zaten işlendi.",
                show_alert=True
            )
            return

        c.execute(
            """
            UPDATE users
            SET balance=balance+?
            WHERE telegram_id=?
            """,
            (w["amount"], w["telegram_id"])
        )

        c.execute(
            """
            UPDATE withdrawals
            SET status='rejected'
            WHERE id=?
            """,
            (wid,)
        )

        c.commit()
        c.close()

        try:
            await x.bot.send_message(
                chat_id=w["telegram_id"],
                text=(
                    f"❌ *Çekim talebiniz reddedildi.*\n\n"
                    f"💰 Miktar: *{w['amount']:.2f} HNK*\n"
                    f"💰 Tutar hesabınıza iade edildi."
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass

        await safe_edit(
            q,
            f"❌ *#{wid} numaralı çekim reddedildi.*\n\n"
            f"💰 {w['amount']:.2f} HNK kullanıcıya iade edildi.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💸 Çekimlere Dön",
                        callback_data="adm_withdrawals"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    # =====================================================
    # ADMIN STARS
    # =====================================================

    elif s == "adm_stars":
        await safe_edit(
            q,
            "⭐ *HNK STARS ADMIN*\n\n"
            "🌟 Stars sistemi hazırlanıyor.\n\n"
            "Bu bölüm ileride Stars bakiyeleri, "
            "ödüller ve kampanyaları yönetmek için kullanılabilir.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )

    # =====================================================
    # BACK
    # =====================================================

    elif s == "back":
        await safe_edit(
            q,
            START_TEXT.format(
                bonus=get_setting("bonus", BONUS),
                daily=get_setting("daily", DAILY),
                minimum=get_setting("min_withdraw", MIN_W),
            ),
            parse_mode="Markdown",
            reply_markup=menu()
        )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text(u, x):
    st = x.user_data.get("state")
    i = u.effective_user.id

    if not st:
        return

    t = u.message.text.strip()

    # =====================================================
    # ADMIN DAILY
    # =====================================================

    if st == "admin_daily":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        try:
            value = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text(
                "❌ Geçerli bir sayı gir."
            )
            return

        if value <= 0:
            await u.message.reply_text(
                "❌ Değer 0'dan büyük olmalı."
            )
            return

        set_setting("daily", value)

        x.user_data["state"] = None

        await u.message.reply_text(
            f"✅ Günlük kazım güncellendi.\n\n"
            f"⛏️ Yeni değer: {value:g} HNK",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # ADMIN BONUS
    # =====================================================

    if st == "admin_bonus":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        try:
            value = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text(
                "❌ Geçerli bir sayı gir."
            )
            return

        if value < 0:
            await u.message.reply_text(
                "❌ Bonus negatif olamaz."
            )
            return

        set_setting("bonus", value)

        x.user_data["state"] = None

        await u.message.reply_text(
            f"✅ Başlangıç bonusu güncellendi.\n\n"
            f"🎁 Yeni bonus: {value:g} HNK",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # ADMIN REF BONUS
    # =====================================================

    if st == "admin_refbonus":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        try:
            value = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text(
                "❌ Geçerli bir sayı gir."
            )
            return

        if value < 0:
            await u.message.reply_text(
                "❌ Bonus negatif olamaz."
            )
            return

        set_setting("ref_bonus", value)

        x.user_data["state"] = None

        await u.message.reply_text(
            f"✅ Referans bonusu güncellendi.\n\n"
            f"👥 Yeni bonus: {value:g} HNK",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # ADMIN MINIMUM WITHDRAW
    # =====================================================

    if st == "admin_min":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        try:
            value = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text(
                "❌ Geçerli bir sayı gir."
            )
            return

        if value <= 0:
            await u.message.reply_text(
                "❌ Minimum çekim 0'dan büyük olmalı."
            )
            return

        set_setting("min_withdraw", value)

        x.user_data["state"] = None

        await u.message.reply_text(
            f"✅ Minimum çekim güncellendi.\n\n"
            f"💸 Yeni minimum: {value:g} HNK",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # ADMIN BROADCAST
    # =====================================================

    if st == "admin_broadcast":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        c = db()

        rows = c.execute(
            """
            SELECT telegram_id
            FROM users
            WHERE banned=0
            """
        ).fetchall()

        c.close()

        sent = 0
        failed = 0

        for z in rows:
            try:
                await x.bot.send_message(
                    chat_id=z["telegram_id"],
                    text=t
                )
                sent += 1
            except Exception:
                failed += 1

        x.user_data["state"] = None

        await u.message.reply_text(
            f"📢 *DUYURU TAMAMLANDI*\n\n"
            f"✅ Gönderildi: *{sent}*\n"
            f"❌ Başarısız: *{failed}*",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # ADMIN USER MANAGEMENT
    # =====================================================

    if st == "admin_manage":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        try:
            uid = int(t)
        except Exception:
            await u.message.reply_text(
                "❌ Geçerli Telegram ID gir."
            )
            return

        r = user(uid)

        if not r:
            x.user_data["state"] = None

            await u.message.reply_text(
                "❌ Kullanıcı bulunamadı.",
                reply_markup=admin_menu()
            )
            return

        status = "🚫 Engelli" if r["banned"] else "✅ Aktif"

        x.user_data["manage_user"] = uid
        x.user_data["state"] = "admin_user_action"

        await u.message.reply_text(
            f"👤 *KULLANICI*\n\n"
            f"🆔 `{uid}`\n"
            f"👤 {r['first_name'] or 'Kullanıcı'}\n"
            f"💰 Bakiye: *{r['balance']:.2f} HNK*\n"
            f"👥 Referans: *{r['referral_count']}*\n"
            f"📌 Durum: {status}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💰 Bakiye Değiştir",
                        callback_data="usr_balance"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚫 Engelle / Aç",
                        callback_data="usr_ban"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Admin",
                        callback_data="admin"
                    )
                ]
            ])
        )
        return

    # =====================================================
    # ADMIN BALANCE ACTION
    # =====================================================

    if st == "admin_balance":
        if not is_admin(i):
            x.user_data["state"] = None
            return

        uid = x.user_data.get("manage_user")

        if not uid:
            x.user_data["state"] = None
            return

        try:
            amount = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text(
                "❌ Örnek: `5` veya `-5`",
                parse_mode="Markdown"
            )
            return

        c = db()

        c.execute(
            """
            UPDATE users
            SET balance=balance+?
            WHERE telegram_id=?
            """,
            (amount, uid)
        )

        c.commit()
        c.close()

        x.user_data["state"] = None

        new_balance = user(uid)["balance"]

        await u.message.reply_text(
            f"✅ Bakiye güncellendi.\n\n"
            f"🆔 {uid}\n"
            f"💰 Yeni bakiye: *{new_balance:.2f} HNK*",
            parse_mode="Markdown",
            reply_markup=admin_menu()
        )
        return

    # =====================================================
    # NORMAL WALLET
    # =====================================================

    if st.startswith("wallet"):
        if not re.fullmatch(
            r"0x[a-fA-F0-9]{40}",
            t
        ):
            await u.message.reply_text(
                "❌ Geçerli BSC/EVM adresi gir."
            )
            return

        c = db()

        c.execute(
            """
            UPDATE users
            SET wallet=?
            WHERE telegram_id=?
            """,
            (t, i)
        )

        c.commit()
        c.close()

        x.user_data["state"] = (
            "with"
            if st == "wallet_then_with"
            else None
        )

        await u.message.reply_text(
            "✅ Cüzdan kaydedildi." +
            (
                "\nŞimdi çekim miktarını yaz."
                if st == "wallet_then_with"
                else ""
            ),
            reply_markup=menu()
        )
        return

    # =====================================================
    # NORMAL WITHDRAW
    # =====================================================

    if st == "with":
        try:
            amount = float(t.replace(",", "."))
        except Exception:
            await u.message.reply_text(
                "❌ Miktarı sayı olarak yaz."
            )
            return

        r = user(i)

        minimum = get_setting(
            "min_withdraw",
            MIN_W
        )

        if amount < minimum:
            await u.message.reply_text(
                f"❌ Minimum çekim: {minimum:g} HNK"
            )
            return

        if amount > r["balance"]:
            await u.message.reply_text(
                "❌ Bakiye yetersiz."
            )
            return

        c = db()

        c.execute(
            """
            UPDATE users
            SET balance=balance-?
            WHERE telegram_id=?
            """,
            (amount, i)
        )

        c.execute(
            """
            INSERT INTO withdrawals
            (telegram_id,amount,wallet,status,created_at)
            VALUES(?,?,?,?,?)
            """,
            (
                i,
                amount,
                r["wallet"],
                "pending",
                datetime.now(timezone.utc).isoformat()
            )
        )

        c.commit()
        c.close()

        x.user_data["state"] = None

        await u.message.reply_text(
            f"💸 *Çekim talebi oluşturuldu!*\n\n"
            f"💰 Miktar: *{amount:g} HNK*\n"
            f"👛 Cüzdan: `{r['wallet']}`\n"
            f"📌 Durum: *Bekliyor*",
            parse_mode="Markdown",
            reply_markup=menu()
        )
        return


# =========================================================
# ADMIN USER ACTION CALLBACKS
# =========================================================

async def admin_action_buttons(u, x):
    pass


# =========================================================
# HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            b"HNK Mining Bot OK"
        )

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    server.serve_forever()


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# =========================================================
# PATCH ADMIN USER ACTIONS INTO BUTTON HANDLER
# =========================================================

_original_buttons = buttons


async def buttons(u, x):
    q = u.callback_query
    s = q.data
    i = q.from_user.id

    # Admin-only user action buttons
    if s.startswith("usr_"):
        await q.answer()

        if not is_admin(i):
            await q.answer(
                "⛔ Yetkiniz yok.",
                show_alert=True
            )
            return

        uid = x.user_data.get("manage_user")

        if not uid:
            await q.message.reply_text(
                "❌ Kullanıcı seçilmedi."
            )
            return

        if s == "usr_balance":
            x.user_data["state"] = "admin_balance"

            await q.message.reply_text(
                "💰 Bakiye değişikliği yaz.\n\n"
                "Pozitif değer ekler:\n"
                "`10`\n\n"
                "Negatif değer düşer:\n"
                "`-10`",
                parse_mode="Markdown"
            )
            return

        if s == "usr_ban":
            c = db()

            r = c.execute(
                "SELECT banned FROM users WHERE telegram_id=?",
                (uid,)
            ).fetchone()

            if not r:
                c.close()

                await q.message.reply_text(
                    "❌ Kullanıcı bulunamadı."
                )
                return

            new_status = 0 if r["banned"] else 1

            c.execute(
                """
                UPDATE users
                SET banned=?
                WHERE telegram_id=?
                """,
                (new_status, uid)
            )

            c.commit()
            c.close()

            x.user_data["state"] = None

            status_text = (
                "🚫 Kullanıcı engellendi."
                if new_status
                else "✅ Kullanıcının engeli kaldırıldı."
            )

            await q.message.reply_text(
                f"{status_text}\n\n"
                f"🆔 {uid}",
                reply_markup=admin_menu()
            )
            return

    # Everything else uses main handler
    await _original_buttons(u, x)


# =========================================================
# RUN
# =========================================================

def run():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise RuntimeError(
            "BOT_TOKEN bulunamadı"
        )

    init()

    app = (
        Application
        .builder()
        .token(token)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buttons
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text
        )
    )

    print("HNK Mining Bot başlatılıyor...")
    print("Admin ID:", ADMIN_ID)

    app.run_polling()


if __name__ == "__main__":
    run()
