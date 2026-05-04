# Toza Hudud — Telegram Bot

Aholi tomonidan chiqindi to'plangan joylarni tezkor aniqlash va tegishli hududiy xizmatlarga yuborish uchun Telegram bot.

## Loyiha strukturasi

```
bot/
├── handlers/
│   ├── states.py       # FSM holatlari
│   ├── user.py         # Foydalanuvchi handlerlari
│   └── admin.py        # Admin handlerlari
├── services/
│   ├── location.py     # Reverse geocoding (Nominatim)
│   └── report.py       # Murojaat CRUD va statistika
├── database/
│   ├── models.py       # SQLAlchemy modellari
│   └── db.py           # Async SQLite ulanish
├── utils/
│   ├── export.py       # Excel va PDF eksport
│   └── relay.py        # Admin↔User relay haritasi
├── keyboards/
│   ├── user_kb.py
│   └── admin_kb.py
├── middlewares/
│   └── auth.py         # Admin tekshiruvi
├── main.py
├── config.py
└── requirements.txt
```

## O'rnatish

### 1. Virtual muhit yarating
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 2. Kutubxonalarni o'rnating
```bash
pip install -r requirements.txt
```

### 3. `.env` faylini sozlang
```bash
cp .env.example .env
```
`.env` faylini oching va to'ldiring:
```
BOT_TOKEN=your_bot_token_here
DEFAULT_ADMIN_IDS=123456789,987654321
DB_PATH=toza_hudud.db
PHOTOS_DIR=photos
```

### 4. Botni ishga tushiring
```bash
python main.py
```

## PM2 orqali deployment (Ubuntu)

```bash
pm2 start "python main.py" --name toza-hudud --interpreter none
pm2 save
pm2 startup
```

## Foydalanuvchi oqimi

1. `/start` — Botni boshlash
2. `📸 Muammo bildirish` → Rasm yuboring → Lokatsiya yuboring → Bot adminga forward qiladi
3. `💬 Admin bilan bog'lanish` → Xabar yozing → Admin javob beradi

## Admin buyruqlari

- `/admin` — Admin panelni ochish
- `📊 Statistika` — Kunlik va umumiy statistika
- `📥 Hisobot yuklash` — Excel yoki PDF export
- `🗺 Hudud qo'shish` — Yangi viloyat/tuman qo'shish
- `👥 Admin boshqaruvi` — Admin qo'shish/o'chirish/ro'yxat
- `📋 Murojaatlar ro'yxati` — So'nggi 20 murojaat

## Texnologiyalar

| Kutubxona | Maqsad |
|---|---|
| aiogram 3.x | Async Telegram bot framework |
| SQLAlchemy + aiosqlite | Async SQLite ORM |
| geopy (Nominatim) | Bepul reverse geocoding |
| openpyxl | Excel (.xlsx) export |
| reportlab | PDF export |
| python-dotenv | Muhit o'zgaruvchilari |
