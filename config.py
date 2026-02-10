import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "35"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "10"))
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
EVOLUTION_PATH = os.getenv("EVOLUTION_PATH", "data/evolution.json")

# Subscription settings
FREE_DAILY_MESSAGES = int(os.getenv("FREE_DAILY_MESSAGES", "5"))
STRIPE_PROVIDER_TOKEN = os.getenv("STRIPE_PROVIDER_TOKEN", "")
CRYPTOBOT_API_TOKEN = os.getenv("CRYPTOBOT_API_TOKEN", "")
CRYPTOBOT_API_URL = os.getenv("CRYPTOBOT_API_URL", "https://pay.crypt.bot/api")

# DeFi Trading
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "false").lower() == "true"
BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
BNB_RPC_URL = os.getenv("BNB_RPC_URL", "https://bsc-dataseed.binance.org")
WALLET_ENCRYPTION_KEY = os.getenv("WALLET_ENCRYPTION_KEY", "")
TRADE_AUTO_THRESHOLD = float(os.getenv("TRADE_AUTO_THRESHOLD", "50"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "25"))
MAX_SLIPPAGE_BPS = int(os.getenv("MAX_SLIPPAGE_BPS", "200"))

# Prices per plan: "stars_amount,stripe_cents,crypto_usdt"
SUB_PRICE_MONTHLY = os.getenv("SUB_PRICE_MONTHLY", "150,499,4.99")
SUB_PRICE_3MONTHS = os.getenv("SUB_PRICE_3MONTHS", "400,1299,12.99")
SUB_PRICE_6MONTHS = os.getenv("SUB_PRICE_6MONTHS", "700,2299,22.99")
SUB_PRICE_YEARLY = os.getenv("SUB_PRICE_YEARLY", "1200,3999,39.99")
SUB_PRICE_LIFETIME = os.getenv("SUB_PRICE_LIFETIME", "3000,9999,99.99")

PLAN_DURATIONS = {
    'monthly': 30, '3months': 90, '6months': 180,
    'yearly': 365, 'lifetime': None,
}

def get_plan_prices(plan: str) -> dict:
    mapping = {
        'monthly': SUB_PRICE_MONTHLY, '3months': SUB_PRICE_3MONTHS,
        '6months': SUB_PRICE_6MONTHS, 'yearly': SUB_PRICE_YEARLY,
        'lifetime': SUB_PRICE_LIFETIME,
    }
    parts = mapping.get(plan, SUB_PRICE_MONTHLY).split(",")
    return {'stars': int(parts[0]), 'stripe_cents': int(parts[1]), 'crypto_usdt': parts[2]}

def get_wallet_key() -> bytes:
    """Get or generate Fernet key for encrypting wallet private keys."""
    from cryptography.fernet import Fernet
    env_key = WALLET_ENCRYPTION_KEY
    if env_key:
        return env_key.encode()
    key_path = os.path.join(os.path.dirname(DB_PATH) or ".", "wallet.key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(key)
    return key


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
