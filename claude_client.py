from collections.abc import AsyncIterator
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_HISTORY
from storage import load_history, save_history, delete_history, load_system_prompt, save_system_prompt
from storage import get_growth_stats, get_knowledge_count, increment_stat
from web_tools import CUSTOM_TOOLS, TRADING_TOOLS, execute_tool
from embeddings_tools import EMBEDDING_TOOLS

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

# --- Context-aware tool selection ---
# Categorize tools by domain
CRYPTO_TOOL_NAMES = {"get_crypto_price", "get_multiple_crypto_prices", "search_coin"}
X_TOOL_NAMES = {"x_home_timeline", "x_read_post", "x_post_tweet", "x_search",
                "x_user_tweets", "x_mentions", "x_whoami"}

CRYPTO_TOOLS = [t for t in CUSTOM_TOOLS if t["name"] in CRYPTO_TOOL_NAMES]
X_TOOLS = [t for t in CUSTOM_TOOLS if t["name"] in X_TOOL_NAMES]

_CRYPTO_KW = frozenset({
    "crypto", "bitcoin", "btc", "eth", "ethereum", "price", "coin", "token",
    "solana", "sol", "xrp", "bnb", "doge", "market cap", "defi", "trading",
    "portfolio", "exchange", "binance", "coinbase", "market", "bull", "bear",
})
_X_KW = frozenset({
    "tweet", "twitter", "x.com", "/x", "timeline", "post on x", "mention",
    "retweet", "thread", "x account", "x/twitter", "@", "follow",
})
_KNOWLEDGE_KW = frozenset({
    "knowledge", "learned", "moltbook", "know about", "what do you know",
    "your knowledge", "knowledge base",
})
_TRADING_KW = frozenset({
    "trade", "swap", "buy", "sell", "defi", "portfolio", "wallet",
    "velvet", "rebalance", "position", "token safety", "honeypot",
    "earn", "profit", "trading goal", "execute trade", "connect wallet",
    "slippage", "liquidity", "1inch", "dex", "yield",
})


def _select_tools(text: str) -> list:
    """Select relevant tools based on message content.

    Always includes: web_search + crypto tools (compact, frequently useful).
    Adds X tools when X/Twitter is mentioned.
    Adds embedding tools when knowledge/MoltBook is mentioned.
    """
    text_lower = text.lower()
    tools = [WEB_SEARCH_TOOL] + CRYPTO_TOOLS  # Always include crypto — small overhead

    if any(kw in text_lower for kw in _X_KW):
        tools.extend(X_TOOLS)

    if any(kw in text_lower for kw in _KNOWLEDGE_KW):
        tools.extend(EMBEDDING_TOOLS)

    if any(kw in text_lower for kw in _TRADING_KW):
        from config import TRADING_ENABLED
        if TRADING_ENABLED:
            tools.extend(TRADING_TOOLS)

    return tools


# --- System prompt (optimized: ~500 chars vs original ~2000) ---

def get_default_system() -> str:
    now = datetime.now(tz=timezone.utc)

    base = (
        f"Current date/time: {now.strftime('%B %d, %Y %H:%M:%S UTC')}. "
        "You are ClawdVC — AI agent on MoltBook (moltbook.com/u/ClawdVC) and Telegram assistant. "
    )

    # Brief growth stats (adds ~50 chars when present)
    stats = get_growth_stats()
    knowledge = get_knowledge_count()
    parts = []
    if stats.get("posts_made"):
        parts.append(f"{stats['posts_made']} posts")
    if knowledge:
        parts.append(f"{knowledge} topics learned")
    if stats.get("conversations_helped"):
        parts.append(f"{stats['conversations_helped']} chats helped")
    if parts:
        base += f"Growth: {', '.join(parts)}. "

    base += (
        "\n\nLANGUAGE: Reply in the user's language exactly."
        "\n\nUse tools proactively — never say you can't access info. "
        "Never rely on training data for time-sensitive info. Cite data timestamps."
        "\n\nX POSTING: Assertive, specific, <280 chars, 0-1 hashtags. "
        "Style cloning: x_read_post → identify style → ask topic → post in same energy."
        "\n\nFORMATTING: Telegram — plain text, no markdown. Raw URLs only."
    )

    from config import TRADING_ENABLED, TRADE_AUTO_THRESHOLD
    if TRADING_ENABLED:
        base += (
            f"\n\nDEFI TRADING: You can trade tokens via Velvet Capital and 1inch. "
            f"Rules: ALWAYS analyze_token before trading. Max 25% portfolio per trade. "
            f"Auto-execute below ${TRADE_AUTO_THRESHOLD}, confirm above. "
            "Never go all-in. Check honeypot + liquidity first. Risk score >70 = skip."
        )

    return base


def get_history(chat_id: int) -> list[dict]:
    return load_history(chat_id)


def clear_history(chat_id: int):
    delete_history(chat_id)


def set_system_prompt(chat_id: int, prompt: str):
    save_system_prompt(chat_id, prompt)


async def ask_stream(chat_id: int, text: str, user_id: int = 0, on_status=None, attachments: list = None) -> AsyncIterator[str]:
    """
    Send a message to Claude with optional attachments (images, PDFs, etc.)

    attachments: list of dicts with keys:
        - type: "image" or "document"
        - media_type: e.g. "image/jpeg", "application/pdf", "text/plain"
        - data: base64-encoded content
    """
    # Track traffic for ECO mode
    from eco_mode import record_message
    record_message()

    history = get_history(chat_id)

    # Build content blocks
    if attachments:
        content = []
        for att in attachments:
            if att["type"] == "image":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": att["media_type"],
                        "data": att["data"]
                    }
                })
            elif att["type"] == "document":
                content.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": att["media_type"],
                        "data": att["data"]
                    }
                })
        content.append({"type": "text", "text": text})
        history.append({"role": "user", "content": content})
    else:
        history.append({"role": "user", "content": text})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    tools = _select_tools(text)
    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 3072, "messages": history, "tools": tools}
    user_system = load_system_prompt(chat_id)

    # MoltBook knowledge injection (context-aware)
    from moltbook_agent import get_knowledge_for_chat
    moltbook_knowledge = get_knowledge_for_chat(text)

    system = get_default_system()
    if moltbook_knowledge:
        system += "\n\n" + moltbook_knowledge
    if user_system:
        system += "\n\n" + user_system
    kwargs["system"] = system

    # Tool use loop
    while True:
        response = await client.messages.create(**kwargs)

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            break

        history.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tc in tool_calls:
            result = await execute_tool(tc.name, tc.input, user_id=user_id)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })

        history.append({"role": "user", "content": tool_results})
        kwargs["messages"] = history

    # Extract final text
    final_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_text += block.text

    history.append({"role": "assistant", "content": final_text})
    save_history(chat_id, history)
    increment_stat("conversations_helped")
    yield final_text


async def generate(prompt: str, system: str = "") -> str:
    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 3072, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text
