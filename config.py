import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-5-20251101")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "50"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "")
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "10"))
DB_PATH = os.getenv("DB_PATH", "data/bot.db")
EVOLUTION_PATH = os.getenv("EVOLUTION_PATH", "data/evolution.json")

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
