import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

SUPERADMIN_ID: int = int(os.getenv("SUPERADMIN_ID", "0"))

# Kept for backward-compatibility; first entry used as superadmin if SUPERADMIN_ID not set
DEFAULT_ADMIN_IDS: list[int] = [
    int(x.strip())
    for x in os.getenv("DEFAULT_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

DB_PATH: str = os.getenv("DB_PATH", "toza_hudud.db")
PHOTOS_DIR: str = os.getenv("PHOTOS_DIR", "photos")
REPORTS_CHANNEL_ID: str = os.getenv("REPORTS_CHANNEL_ID", "").strip()

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR: str = os.getenv("LOG_DIR", "logs")

# Reverse geocoding performance settings
GEOCODE_CACHE_TTL_SEC: int = int(os.getenv("GEOCODE_CACHE_TTL_SEC", "1800"))
GEOCODE_CACHE_ROUND_DIGITS: int = int(os.getenv("GEOCODE_CACHE_ROUND_DIGITS", "4"))
