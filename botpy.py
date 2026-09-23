import os,re,sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from datetime import datetime,timezone,timedelta
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes,MessageHandler,filters
DB=os.getenv("HNK_DB","hnk_mining.db"); DAILY=.25; BONUS=1.; MIN_W=10.; ADMIN=int(os.getenv("ADMIN_ID","0"))
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 c=db(); c.execute("""CREATE TABLE IF NOT EXISTS users(telegram_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,balance REAL DEFAULT 0,last_claim TEXT,wallet TEXT,referral_count INTEGER DEFAULT 0,created_at TEXT)"""); c.execute("""CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT,telegram_id INTEGER,amount REAL,wallet TEXT,status TEXT,created_at TEXT)"""); c.commit(); c.close()
def user(i):
 c=db(); r=c.execute("SELECT * FROM users WHERE telegram_id=?",(i,)).fetchone(); c.close(); return r
def add(u,ref=None):
 if user(u.id): return
 c=db(); c.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)",(u.id,u.username,u.first_name,BONUS,None,None,0,datetime.now(timezone.utc).isoformat()))
 if ref and ref!=u.id: c.execute("UPDATE users SET balance=balance+?,referral_count=referral_count+1 WHERE telegram_id=?",(1.,ref))
 c.commit(); c.close()
def menu():
 return InlineKeyboardMarkup([[InlineKeyboardButton("⛏️ Kazımaya Başla",callback_data="mine"),InlineKeyboardButton("💰 Bakiyem",callback_data="bal")],[InlineKeyboardButton("👥 Referans",callback_data="ref"),InlineKeyboardButton("👛 Cüzdanım",callback_data="wallet")],[InlineKeyboardButton("💸 HNK Çek",callback_data="with"),InlineKeyboardButton("📊 İstatistik",callback_data="stats")],[InlineKeyboardButton("🏆 Liderlik",callback_data="lead"),InlineKeyboardButton("ℹ️ HNK Hakkında",callback_data="about")]])
async def start(u,x):
 ref=None
 if x.args and x.args[0].startswith("ref_"):
  try: ref=int(x.args[0][4:])
  except: pass
 add(u.effective_user,ref); await u.message.reply_text("🪙 *Hyper Nexus Kingdom — HNK Mining V2*\n\n🎁 Başlangıç: *1 HNK*\n⛏️ Günlük kazım: *0.25 HNK*\n💸 Minimum çekim: *10 HNK*\n\nMenüden devam et:",parse_mode="Markdown",reply_markup=menu())
async def buttons(u,x):
 q=u.callback_query; await q.answer(); i=q.from_user.id
 if not user(i): add(q.from_user)
 r=user(i); s=q.data
 if s=="mine":
  now=datetime.now(timezone.utc)
  if r["last_claim"] and now-datetime.fromisoformat(r["last_claim"])<timedelta(hours=24):
   left=timedelta(hours=24)-(now-datetime.fromisoformat(r["last_claim"])); await q.edit_message_text(f"⏳ Sonraki kazım: {int(left.total_seconds()//3600)} saat {int(left.total_seconds()%3600//60)} dakika",reply_markup=menu()); return
  c=db(); c.execute("UPDATE users SET balance=balance+?,last_claim=? WHERE telegram_id=?",(DAILY,now.isoformat(),i)); c.commit(); c.close(); await q.edit_message_text(f"⛏️ *Kazım başarılı!*\n+0.25 HNK\n💰 Bakiye: *{user(i)['balance']:.2f} HNK*",parse_mode="Markdown",reply_markup=menu())
 elif s=="bal": await q.edit_message_text(f"💰 Bakiye: *{r['balance']:.2f} HNK*",parse_mode="Markdown",reply_markup=menu())
 elif s=="wallet":
  x.user_data["state"]="wallet"; await q.edit_message_text("👛 BSC/EVM cüzdan adresini gönder.\nÖrnek: `0x...`",parse_mode="Markdown")
 elif s=="with":
  if not r["wallet"]: x.user_data["state"]="wallet_then_with"; await q.edit_message_text("Önce BSC cüzdan adresini gönder.")
  else: x.user_data["state"]="with"; await q.edit_message_text(f"💸 Miktarı yaz. Minimum *{MIN_W:g} HNK*. Bakiye: *{r['balance']:.2f} HNK*",parse_mode="Markdown")
 elif s=="ref":
  m=await x.bot.get_me(); await q.edit_message_text(f"👥 Davet: {r['referral_count']}\n🔗 `https://t.me/{m.username}?start=ref_{i}`",parse_mode="Markdown",reply_markup=menu())
 elif s=="stats":
  c=db(); n=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close(); await q.edit_message_text(f"📊 Kullanıcı: *{n}*",parse_mode="Markdown",reply_markup=menu())
 elif s=="lead":
  c=db(); rows=c.execute("SELECT first_name,balance FROM users ORDER BY balance DESC LIMIT 10").fetchall(); c.close(); await q.edit_message_text("\n".join([f"{n}. {z['first_name'] or 'Kullanıcı'} — {z['balance']:.2f} HNK" for n,z in enumerate(rows,1)]),reply_markup=menu())
 else: await q.edit_message_text("ℹ️ HNK Mining V2\n\nCüzdan bağlama ve çekim talebi sistemi aktif. Gerçek blockchain transferi henüz kapalıdır.",reply_markup=menu())
async def text(u,x):
 st=x.user_data.get("state"); i=u.effective_user.id
 if not st:return
 t=u.message.text.strip()
 if st.startswith("wallet"):
  if not re.fullmatch(r"0x[a-fA-F0-9]{40}",t): await u.message.reply_text("❌ Geçerli BSC/EVM adresi gir."); return
  c=db(); c.execute("UPDATE users SET wallet=? WHERE telegram_id=?",(t,i)); c.commit(); c.close(); x.user_data["state"]="with" if st=="wallet_then_with" else None
  await u.message.reply_text("✅ Cüzdan kaydedildi."+("\nŞimdi çekim miktarını yaz." if st=="wallet_then_with" else ""),reply_markup=menu())
 elif st=="with":
  try:a=float(t.replace(",",".")) 
  except: await u.message.reply_text("❌ Miktarı sayı olarak yaz."); return
  r=user(i)
  if a<MIN_W or a>r["balance"]: await u.message.reply_text("❌ Miktar geçersiz veya bakiye yetersiz."); return
  c=db(); c.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?",(a,i)); c.execute("INSERT INTO withdrawals(telegram_id,amount,wallet,status,created_at) VALUES(?,?,?,?,?)",(i,a,r["wallet"],"pending",datetime.now(timezone.utc).isoformat())); c.commit(); c.close(); x.user_data["state"]=None
  await u.message.reply_text(f"💸 Çekim talebi oluşturuldu: *{a:g} HNK*\nDurum: Bekliyor",parse_mode="Markdown",reply_markup=menu())
async def main():
    pass

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

 t=os.getenv("BOT_TOKEN")
 if not t: raise RuntimeError("BOT_TOKEN bulunamadı")
 init(); a=Application.builder().token(t).build(); a.add_handler(CommandHandler("start",start)); a.add_handler(CallbackQueryHandler(buttons)); a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text)); a.run_polling()
if __name__=="__main__": run()
