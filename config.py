import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-5-20251101")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "50"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "10"))
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
EVOLUTION_PATH = os.getenv("EVOLUTION_PATH", "data/evolution.json")

# Payment
STRIPE_PROVIDER_TOKEN = os.getenv("STRIPE_PROVIDER_TOKEN", "")

# Telegram Stars prices
PRICE_PERSONAL_1W_STARS = int(os.getenv("PRICE_PERSONAL_1W_STARS", "50"))
PRICE_PERSONAL_1M_STARS = int(os.getenv("PRICE_PERSONAL_1M_STARS", "150"))
PRICE_PERSONAL_3M_STARS = int(os.getenv("PRICE_PERSONAL_3M_STARS", "400"))
PRICE_PERSONAL_6M_STARS = int(os.getenv("PRICE_PERSONAL_6M_STARS", "700"))
PRICE_GROUP_1W_STARS = int(os.getenv("PRICE_GROUP_1W_STARS", "100"))
PRICE_GROUP_1M_STARS = int(os.getenv("PRICE_GROUP_1M_STARS", "300"))
PRICE_GROUP_3M_STARS = int(os.getenv("PRICE_GROUP_3M_STARS", "800"))
PRICE_GROUP_6M_STARS = int(os.getenv("PRICE_GROUP_6M_STARS", "1400"))
PRICE_PACK_STARS = int(os.getenv("PRICE_PACK_STARS", "25"))

# Stripe USD prices (cents)
PRICE_PERSONAL_1W_USD = int(os.getenv("PRICE_PERSONAL_1W_USD", "299"))
PRICE_PERSONAL_1M_USD = int(os.getenv("PRICE_PERSONAL_1M_USD", "899"))
PRICE_PERSONAL_3M_USD = int(os.getenv("PRICE_PERSONAL_3M_USD", "2399"))
PRICE_PERSONAL_6M_USD = int(os.getenv("PRICE_PERSONAL_6M_USD", "4199"))
PRICE_GROUP_1W_USD = int(os.getenv("PRICE_GROUP_1W_USD", "599"))
PRICE_GROUP_1M_USD = int(os.getenv("PRICE_GROUP_1M_USD", "1799"))
PRICE_GROUP_3M_USD = int(os.getenv("PRICE_GROUP_3M_USD", "4799"))
PRICE_GROUP_6M_USD = int(os.getenv("PRICE_GROUP_6M_USD", "8399"))
PRICE_PACK_USD = int(os.getenv("PRICE_PACK_USD", "149"))

# Limits
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "5"))
PAID_DAILY_LIMIT = int(os.getenv("PAID_DAILY_LIMIT", "100"))
FREE_TRIAL_DAYS = int(os.getenv("FREE_TRIAL_DAYS", "7"))
MESSAGE_PACK_SIZE = int(os.getenv("MESSAGE_PACK_SIZE", "50"))

def get_cookie_key() -> bytes:
    """Get or generate Fernet key for encrypting X cookies."""
    from cryptography.fernet import Fernet
    key_path = os.path.join(os.path.dirname(DB_PATH) or ".", "cookie.key")
    env_key = os.getenv("X_COOKIE_SECRET")
    if env_key:
        return env_key.encode()
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(key)
    return key
