import os,re,sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from datetime import datetime,timezone,timedelta
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes,MessageHandler,filters

DB=os.getenv("HNK_DB","hnk_mining.db"); DAILY=.25; BONUS=1.; MIN_W=10.; ADMIN=int(os.getenv("ADMIN_ID","0"))

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(telegram_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,balance REAL DEFAULT 0,last_claim TEXT,wallet TEXT,referral_count INTEGER DEFAULT 0,created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER,amount REAL,wallet TEXT,status TEXT,created_at TEXT)""")
    c.commit(); c.close()

def user(i):
    c=db(); r=c.execute("SELECT * FROM users WHERE telegram_id=?",(i,)).fetchone(); c.close(); return r

def add(u,ref=None):
    if user(u.id): return
    c=db()
    c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)",(u.id,u.username,u.first_name,BONUS,None,None,0,datetime.now(timezone.utc).isoformat()))
    if ref and ref!=u.id:
        c.execute("UPDATE users SET balance=balance+?,referral_count=referral_count+1 WHERE telegram_id=?",(1.,ref))
    c.commit(); c.close()

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("âï¸ KazÄ±maya BaÅla",callback_data="mine"),InlineKeyboardButton("ð° Bakiyem",callback_data="bal")],
        [InlineKeyboardButton("ð¥ Referans",callback_data="ref"),InlineKeyboardButton("ð CÃ¼zdanÄ±m",callback_data="wallet")],
        [InlineKeyboardButton("ð¸ HNK Ãek",callback_data="with"),InlineKeyboardButton("ð Ä°statistik",callback_data="stats")],
        [InlineKeyboardButton("ð Liderlik",callback_data="lead"),InlineKeyboardButton("â¹ï¸ HNK HakkÄ±nda",callback_data="about")]
    ])

START_TEXT = (
    "ðª *Hyper Nexus Kingdom â HNK Mining V2*\n\n"
    "ð BaÅlangÄ±Ã§: *1 HNK*\n"
    "âï¸ GÃ¼nlÃ¼k kazÄ±m: *0.25 HNK*\n"
    "ð¸ Minimum Ã§ekim: *10 HNK*\n\n"
    "MenÃ¼den devam et:"
)

ABOUT_TEXT = (
    "ðª *HYPER NEXUS KINGDOM â HNK*\n\n"
    "ð Dijital madencilik ve topluluk odaklÄ± HNK projesi.\n\n"
    "ð *BaÅlangÄ±Ã§ Bonusu:* 1 HNK\n"
    "âï¸ *GÃ¼nlÃ¼k KazÄ±m:* 0.25 HNK\n"
    "ð¸ *Minimum Ãekim:* 10 HNK\n"
    "ð¥ *Referans Sistemi:* Aktif\n"
    "ð *BSC/EVM CÃ¼zdan:* Destekleniyor\n\n"
    "ð¯ *Vizyonumuz*\n"
    "Ä°nsanlarÄ±, teknolojiyi ve fÄ±rsatlarÄ± bir araya getirerek "
    "kÃ¼resel bir dijital topluluk oluÅturmak.\n\n"
    "ð *HNK*\n"
    "People â¢ Technology â¢ Opportunity\n\n"
    "_A Stronger Tomorrow Together_\n\n"
    "Â© 2026 Hyper Nexus Kingdom"
)

async def start(u,x):
    ref=None
    if x.args and x.args[0].startswith("ref_"):
        try: ref=int(x.args[0][4:])
        except: pass
    add(u.effective_user,ref)
    try:
        with open("HNK_logo.png","rb") as f:
            await u.message.reply_photo(photo=f)
    except Exception:
        pass
    await u.message.reply_text(START_TEXT,parse_mode="Markdown",reply_markup=menu())

async def safe_edit(q, text, **kwargs):
    try:
        await safe_edit(q, text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise

async def buttons(u,x):
    q=u.callback_query; await q.answer(); i=q.from_user.id
    if not user(i): add(q.from_user)
    r=user(i); s=q.data

    if s=="mine":
        now=datetime.now(timezone.utc)
        if r["last_claim"] and now-datetime.fromisoformat(r["last_claim"])<timedelta(hours=24):
            left=timedelta(hours=24)-(now-datetime.fromisoformat(r["last_claim"]))
            await safe_edit(q, 
                f"â³ Sonraki kazÄ±m: {int(left.total_seconds()//3600)} saat {int(left.total_seconds()%3600//60)} dakika",
                reply_markup=menu()
            )
            return
        c=db()
        c.execute("UPDATE users SET balance=balance+?,last_claim=? WHERE telegram_id=?",(DAILY,now.isoformat(),i))
        c.commit(); c.close()
        await safe_edit(q, 
            f"âï¸ *KazÄ±m baÅarÄ±lÄ±!*\n+0.25 HNK\nð° Bakiye: *{user(i)['balance']:.2f} HNK*",
            parse_mode="Markdown",reply_markup=menu()
        )

    elif s=="bal":
        await safe_edit(q, f"ð° Bakiye: *{r['balance']:.2f} HNK*",parse_mode="Markdown",reply_markup=menu())

    elif s=="wallet":
        x.user_data["state"]="wallet"
        await safe_edit(q, "ð BSC/EVM cÃ¼zdan adresini gÃ¶nder.\nÃrnek: `0x...`",parse_mode="Markdown")

    elif s=="with":
        if not r["wallet"]:
            x.user_data["state"]="wallet_then_with"
            await safe_edit(q, "Ãnce BSC cÃ¼zdan adresini gÃ¶nder.")
        else:
            x.user_data["state"]="with"
            await safe_edit(q, 
                f"ð¸ MiktarÄ± yaz. Minimum *{MIN_W:g} HNK*. Bakiye: *{r['balance']:.2f} HNK*",
                parse_mode="Markdown"
            )

    elif s=="ref":
        m=await x.bot.get_me()
        await safe_edit(q, 
            f"ð¥ Davet: {r['referral_count']}\nð `https://t.me/{m.username}?start=ref_{i}`",
            parse_mode="Markdown",reply_markup=menu()
        )

    elif s=="stats":
        c=db(); n=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close()
        await safe_edit(q, f"ð KullanÄ±cÄ±: *{n}*",parse_mode="Markdown",reply_markup=menu())

    elif s=="lead":
        c=db()
        rows=c.execute("SELECT first_name,balance FROM users ORDER BY balance DESC LIMIT 10").fetchall()
        c.close()
        await safe_edit(q, 
            "\n".join([f"{n}. {z['first_name'] or 'KullanÄ±cÄ±'} â {z['balance']:.2f} HNK" for n,z in enumerate(rows,1)]),
            reply_markup=menu()
        )

    elif s=="about":
        await safe_edit(q, 
            ABOUT_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("â¬ï¸ Ana MenÃ¼",callback_data="menu")]
            ])
        )

    elif s=="menu":
        await safe_edit(q, START_TEXT,parse_mode="Markdown",reply_markup=menu())

async def text(u,x):
    st=x.user_data.get("state"); i=u.effective_user.id
    if not st:return
    t=u.message.text.strip()

    if st.startswith("wallet"):
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}",t):
            await u.message.reply_text("â GeÃ§erli BSC/EVM adresi gir.")
            return
        c=db()
        c.execute("UPDATE users SET wallet=? WHERE telegram_id=?",(t,i))
        c.commit(); c.close()
        x.user_data["state"]="with" if st=="wallet_then_with" else None
        await u.message.reply_text(
            "â CÃ¼zdan kaydedildi."+("\nÅimdi Ã§ekim miktarÄ±nÄ± yaz." if st=="wallet_then_with" else ""),
            reply_markup=menu()
        )

    elif st=="with":
        try:a=float(t.replace(",","."))
        except:
            await u.message.reply_text("â MiktarÄ± sayÄ± olarak yaz.")
            return
        r=user(i)
        if a<MIN_W or a>r["balance"]:
            await u.message.reply_text("â Miktar geÃ§ersiz veya bakiye yetersiz.")
            return
        c=db()
        c.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?",(a,i))
        c.execute(
            "INSERT INTO withdrawals(telegram_id,amount,wallet,status,created_at) VALUES(?,?,?,?,?)",
            (i,a,r["wallet"],"pending",datetime.now(timezone.utc).isoformat())
        )
        c.commit(); c.close(); x.user_data["state"]=None
        await u.message.reply_text(
            f"ð¸ Ãekim talebi oluÅturuldu: *{a:g} HNK*\nDurum: Bekliyor",
            parse_mode="Markdown",reply_markup=menu()
        )

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"HNK Mining Bot OK")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port=int(os.environ.get("PORT","10000"))
    server=HTTPServer(("0.0.0.0",port),HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server,daemon=True).start()

def run():
    t=os.getenv("BOT_TOKEN")
    if not t: raise RuntimeError("BOT_TOKEN bulunamadÄ±")
    init()
    a=Application.builder().token(t).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CallbackQueryHandler(buttons))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text))
    a.run_polling()

if __
