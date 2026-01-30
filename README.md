# Telegram Claude Bot

Telegram bot powered by Claude API. Supports private chats, group Q&A, and channel publishing.

## Features

- **Private chat** — send messages and get Claude responses with conversation history
- **Group Q&A** — `/q <question>` for anyone in a group to ask Claude
- **Channel posts** — `/post <topic>` and `/news <topic>` to publish AI-generated content (admin-only)
- **System prompt** — `/system <prompt>` to customize Claude's behavior
- **History management** — `/reset` to clear conversation history

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/87Albert87/telegram-claude-bot.git
   cd telegram-claude-bot
   ```

2. Install dependencies:
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

4. Run:
   ```bash
   python bot.py
   ```

## Commands

| Command | Context | Description |
|---------|---------|-------------|
| `/start` | Any | Show help |
| `/q <question>` | Group/Private | Ask Claude a question |
| `/reset` | Any | Clear conversation history |
| `/system <prompt>` | Any | Set custom system prompt |
| `/post <topic>` | Admin | Generate and publish a post to the channel |
| `/news <topic>` | Admin | Generate and publish a news post to the channel |

## Notes

- The bot must be added as an **admin** to your channel for publishing to work.
- In groups, only `/q` triggers Claude. Free-text messages are ignored to avoid noise.
- Conversation history is per-chat and capped at 50 messages (configurable via `MAX_HISTORY`).
