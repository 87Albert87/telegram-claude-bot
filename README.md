# Telegram Claude Bot

Telegram bot powered by Claude API. Supports private chats, group Q&A, real-time crypto prices, web search, and channel publishing.

## Features

- **Private chat** — send messages and get Claude responses with streaming and conversation history
- **Group Q&A** — `/q <question>` for anyone in a group to ask Claude
- **Live crypto prices** — `/price BTC` for real-time market data via CoinGecko
- **Web search** — Claude automatically searches the web for current information
- **Channel posts** — `/post <topic>` and `/news <topic>` to publish AI-generated content (admin-only)
- **System prompt** — `/system <prompt>` to customize Claude's behavior
- **Persistent storage** — conversation history saved to SQLite, survives restarts
- **Rate limiting** — configurable per-user rate limits to prevent abuse
- **Streaming responses** — messages update in real-time as Claude generates text

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/87Albert87/telegram-claude-bot.git
   cd telegram-claude-bot
   ```

2. Install dependencies (Python 3.11+ required):
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your keys:
   - `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
   - `ANTHROPIC_API_KEY` — from [Anthropic Console](https://console.anthropic.com/)
   - `ADMIN_IDS` — comma-separated Telegram user IDs for admin commands
   - `CHANNEL_ID` — channel username (`@yourchannel`) or numeric ID
   - `RATE_LIMIT` — max messages per minute per user (default: 10)
   - `DB_PATH` — SQLite database path (default: `bot.db`)

4. Run:
   ```bash
   python bot.py
   ```

### Docker

```bash
cp .env.example .env
# Edit .env with your keys
docker compose up -d
```

## Commands

| Command | Context | Description |
|---------|---------|-------------|
| `/start` | Any | Show help and available commands |
| `/q <question>` | Group/Private | Ask Claude a question |
| `/price <coin>` | Any | Live crypto price (e.g. `/price BTC`, `/price BTC ETH SOL`) |
| `/reset` | Any | Clear conversation history |
| `/system <prompt>` | Any | Set custom system prompt |
| `/post <topic>` | Admin | Generate and publish a post to the channel |
| `/news <topic>` | Admin | Generate and publish a news post to the channel |

## Notes

- The bot must be added as an **admin** to your channel for publishing to work.
- In groups, only commands trigger Claude. Free-text messages are ignored to avoid noise.
- Conversation history is per-chat and capped at 50 messages (configurable via `MAX_HISTORY`).
- `/price` fetches data directly from CoinGecko API — no Claude API call needed, instant response.
- Claude uses built-in web search and real-time crypto tools to provide current information.
