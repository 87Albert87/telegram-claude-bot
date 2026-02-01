# ClawdVC Bot — Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        LOCAL MACHINE                                │
│                   (macOS, development)                               │
│                                                                     │
│  ~/telegram-claude-bot/                                             │
│  ├── bot.py              Telegram bot entry point                   │
│  ├── claude_client.py    Anthropic API client + tool loop           │
│  ├── web_tools.py        Tool implementations (crypto, X, MoltBook) │
│  ├── moltbook_agent.py   Autonomous MoltBook engagement loop        │
│  ├── moltbook.py         MoltBook API wrapper                       │
│  ├── storage.py          SQLite DB layer                            │
│  ├── config.py           Environment config                         │
│  ├── rate_limit.py       Per-user rate limiting                     │
│  └── .env                Local env vars                             │
│                                                                     │
│  Deploys via rsync ──────────────────────────────────┐              │
│  Git remote: github.com/87Albert87/telegram-claude-bot│              │
└──────────────────────────────────────────────────────┼──────────────┘
                                                       │
                                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  VPS: 142.93.128.240                                │
│          DigitalOcean, Ubuntu 24.04, 1 vCPU, 1GB RAM               │
│                                                                     │
│  /opt/telegram-claude-bot/                                          │
│  ├── .env                 Production secrets                        │
│  │   ├── TELEGRAM_BOT_TOKEN                                        │
│  │   ├── ANTHROPIC_API_KEY                                         │
│  │   ├── MOLTBOOK_API_KEY  (ClawdVC_ account)                     │
│  │   ├── CLAUDE_MODEL=claude-opus-4-5-20251101                     │
│  │   └── MAX_HISTORY=50                                            │
│  │                                                                  │
│  ├── docker-compose.yml                                             │
│  │   └── service: bot                                               │
│  │       ├── build: .  (Dockerfile)                                 │
│  │       ├── restart: unless-stopped                                │
│  │       └── volumes: bot-data:/app/data  (persistent SQLite)       │
│  │                                                                  │
│  └── Docker container: telegram-claude-bot-bot-1                    │
│      ├── Python 3.12-slim                                           │
│      ├── Node.js 22 + @steipete/bird CLI (X/Twitter)               │
│      ├── /app/data/bot.db  (persistent volume)                      │
│      │   ├── conversations    (chat history per chat_id)            │
│      │   ├── knowledge_base   (MoltBook learned topics, max 2000)   │
│      │   ├── bot_growth       (engagement metrics)                  │
│      │   └── x_accounts       (X cookies per user_id)              │
│      │                                                              │
│      └── Running processes:                                         │
│          ├── bot.py (Telegram polling)                               │
│          └── MoltBook agent loop (background asyncio task)          │
└─────────────────────────────────────────────────────────────────────┘

========================= EXTERNAL CONNECTIONS =========================

┌──────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│   Telegram   │     │   Anthropic API  │     │   MoltBook API      │
│   Bot API    │     │                  │     │   moltbook.com      │
│              │     │  claude-opus-4-5 │     │                     │
│  Long-poll   │     │  (conversations) │     │  Agent: ClawdVC_    │
│  getUpdates  │     │                  │     │  GET  /posts ✓      │
│              │     │  claude-sonnet-4 │     │  POST /posts ✓      │
│  Bot token:  │     │  (MoltBook agent)│     │  POST /subscribe ✗  │
│  @ClawdVC    │     │                  │     │  POST /follow    ✗  │
└──────┬───────┘     └────────┬─────────┘     └──────────┬──────────┘
       │                      │                          │
       ▼                      ▼                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Docker Container (bot)                          │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    bot.py (main)                             │   │
│  │                                                             │   │
│  │  Commands:                                                  │   │
│  │  /start       — Greeting + stats                            │   │
│  │  /reset       — Clear history + system prompt               │   │
│  │  /prompt      — Set custom system prompt                    │   │
│  │  /price       — Crypto prices (CoinGecko)                   │   │
│  │  /q           — Ask in groups                               │   │
│  │  /growth      — MoltBook engagement stats                   │   │
│  │  /connect_x   — Link X account (deletes msg for security)  │   │
│  │  /disconnect_x— Remove X cookies                            │   │
│  │  /post        — Admin: publish to channel                   │   │
│  │  /news        — Admin: publish news to channel              │   │
│  │  /finish      — Exit price/prompt mode                      │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            │                                        │
│  ┌─────────────────────────▼───────────────────────────────────┐   │
│  │                claude_client.py                              │   │
│  │                                                             │   │
│  │  Model: claude-opus-4-5-20251101 (conversations)            │   │
│  │  Tools: web_search, crypto, moltbook, x/twitter             │   │
│  │  System prompt includes MoltBook knowledge context          │   │
│  │  Tool loop: call tools → feed results → repeat until done   │   │
│  └─────────────────────────┬───────────────────────────────────┘   │
│                            │                                        │
│  ┌─────────────────────────▼───────────────────────────────────┐   │
│  │                web_tools.py                                  │   │
│  │                                                             │   │
│  │  Crypto:    CoinGecko API (price, search, multi-price)      │   │
│  │  MoltBook:  Profile, posts, feed, search (via moltbook.py)  │   │
│  │  X/Twitter: bird CLI per-user cookies from SQLite           │   │
│  │    ├── x_home_timeline  (read feed)                         │   │
│  │    ├── x_read_post      (read tweet)                        │   │
│  │    ├── x_post_tweet     (create tweet)                      │   │
│  │    ├── x_search         (search tweets)                     │   │
│  │    └── x_whoami         (check connected account)           │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │            moltbook_agent.py (background loop)              │   │
│  │                                                             │   │
│  │  Model: claude-sonnet-4-20250514                            │   │
│  │  Identity: ClawdVC (MoltBook username: ClawdVC_)            │   │
│  │                                                             │   │
│  │  Schedule:                                                  │   │
│  │    Every 10 min — browse_and_learn (read hot+new feeds)     │   │
│  │    Every 20 min — engage_with_posts (upvote, comment)       │   │
│  │    Every 40 min — create_original_post (viral content)      │   │
│  │                                                             │   │
│  │  On startup: initial_setup → browse → post                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────┐     ┌──────────────────┐
│   CoinGecko API  │     │   X/Twitter API  │
│   (free tier)    │     │   (via bird CLI) │
│                  │     │                  │
│  Price lookups   │     │  Per-user auth   │
│  Coin search     │     │  cookies in DB   │
└──────────────────┘     └──────────────────┘

========================= DATA FLOW ====================================

User sends message in Telegram
  → bot.py receives via long-polling
  → claude_client.py builds context (history + MoltBook knowledge)
  → Anthropic API generates response (may call tools)
  → Tools execute (crypto/moltbook/x) and results fed back
  → Final response sent to user in Telegram
  → History saved to SQLite

MoltBook agent loop (autonomous, no user input):
  → Reads MoltBook feed → stores in knowledge_base
  → Generates comments/posts via Sonnet 4
  → Posts to MoltBook API as ClawdVC_
  → Knowledge available to Telegram conversations
```
