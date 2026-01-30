import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "50"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "")
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "10"))
DB_PATH = os.getenv("DB_PATH", "bot.db")
