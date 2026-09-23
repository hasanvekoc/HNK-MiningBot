# HNK Mining Telegram Bot — V1

Bu sürüm Telegram üzerinde çalışan bir HNK mining prototipidir.

## Özellikler
- 24 saatte bir HNK kazımı
- Başlangıç bonusu
- SQLite kullanıcı/bakiye veritabanı
- Referans bağlantısı
- Bakiye görüntüleme
- İstatistik
- Liderlik tablosu
- Cüzdan menüsü (V1'de gerçek blockchain çekimi kapalı)

## Kurulum

Python 3.11+ önerilir.

```bash
python -m venv .venv
```

Windows:
```bash
.venv\Scripts\activate
```

macOS/Linux:
```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

`.env.example` dosyasını `.env` olarak kopyalayın ve BotFather'dan aldığınız
YENİ tokenı `BOT_TOKEN=` satırına yazın.

Ardından:

```bash
python bot.py
```

Bot Telegram'da:
https://t.me/HNK_MiningBot

## Güvenlik
Bot tokenını kimseyle paylaşmayın ve GitHub'a yüklemeyin.

## Sonraki sürüm
Gerçek HNK BEP-20 çekimleri, BSC cüzdan doğrulama, minimum çekim,
admin paneli, anti-bot/anti-abuse ve blockchain transaction takibi
eklenebilir.
