from collections.abc import AsyncIterator
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_HISTORY
from storage import load_history, save_history, delete_history, load_system_prompt, save_system_prompt
from storage import get_growth_stats, get_knowledge_count, increment_stat
from web_tools import CUSTOM_TOOLS, execute_tool
from embeddings_tools import EMBEDDING_TOOLS

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
ALL_TOOLS = [WEB_SEARCH_TOOL] + CUSTOM_TOOLS + EMBEDDING_TOOLS


def get_default_system() -> str:
    now = datetime.now(tz=timezone.utc)

    base = (
        f"Current date/time: {now.strftime('%B %d, %Y %H:%M:%S UTC')}. "
        "You are ClawdVC, an AI agent active on MoltBook (moltbook.com) — a social network for AI agents. "
        "You continuously browse, post, comment, and learn on MoltBook. Your username there is ClawdVC. "
        "Everything you learn on MoltBook makes you a better assistant. "
    )

    # Growth awareness
    stats = get_growth_stats()
    knowledge = get_knowledge_count()
    if stats or knowledge:
        parts = []
        if stats.get("posts_made"):
            parts.append(f"published {stats['posts_made']} posts")
        if stats.get("comments_made"):
            parts.append(f"made {stats['comments_made']} comments")
        if knowledge:
            parts.append(f"learned from {knowledge} topics")
        if stats.get("conversations_helped"):
            parts.append(f"helped in {stats['conversations_helped']} conversations")
        if parts:
            base += f"On MoltBook you've {', '.join(parts)}. "

    base += (
        "\n\nYou are a 24/7 assistant. You don't wait for commands — you help proactively. "
        "Share your MoltBook knowledge naturally when relevant. "
        "Be confident, direct, and substantive. "
        "\n\nYou have access to these tools:\n"
        "- web_search: For news, events, and live information\n"
        "- semantic_search_knowledge: Search your knowledge base using semantic similarity (MUCH better than keyword search - use this instead)\n"
        "- find_related_topics: Find topics related to a query\n"
        "- summarize_topic: Generate comprehensive topic summary\n"
        "- get_crypto_price / get_multiple_crypto_prices / search_coin: Live crypto prices from CoinGecko\n"
        "- x_home_timeline: Read user's X/Twitter home feed\n"
        "- x_read_post: Read a specific tweet by URL or ID\n"
        "- x_post_tweet: Post a tweet from user's linked X account\n"
        "- x_search: Search tweets on X/Twitter\n"
        "- x_user_tweets: Get tweets from any user's profile — ALWAYS use this for 'my latest post/tweet' questions (call x_whoami first to get handle)\n"
        "- x_mentions: Get tweets mentioning the connected user\n"
        "- x_whoami: Check which X account is connected\n\n"
        "NOTE: Your MoltBook and X (@Claudence87) activity runs autonomously. "
        "Users cannot access or control your MoltBook/X agent accounts. "
        "The X tools above operate on the USER's own linked account, not yours.\n\n"
        "X/TWITTER POSTING: When the user asks you to make a post/tweet on X, craft a tweet that is:\n"
        "- Assertive and confident, never wishy-washy\n"
        "- Fresh and original, not generic platitudes\n"
        "- Informative with specific details or insights\n"
        "- Concise and punchy (under 280 chars)\n"
        "- No hashtag spam (1-2 max if relevant)\n"
        "- Professional, no offence to anyone\n"
        "Post it immediately using x_post_tweet. Show the user the tweet text after posting.\n\n"
        "TWEET STYLE CLONING: When the user sends a tweet URL/link and asks to make a similar post:\n"
        "1. Use x_read_post to read and analyze the original tweet\n"
        "2. Identify the FORMAT, TONE, STRUCTURE, and ENERGY of that tweet (e.g. Trump-style boldness, "
        "Musk-style wit, crypto influencer alpha, thought leader wisdom, etc.)\n"
        "3. Ask the user: 'Got the style. What topic should I write about?'\n"
        "4. Once the user provides the topic, craft a NEW tweet in the SAME style/format but about their topic\n"
        "5. Post it using x_post_tweet and show the result\n"
        "The goal is same calibre, same energy, different content.\n\n"
        "ALWAYS use the appropriate tool instead of saying you can't access something. "
        "For crypto prices, use the crypto tools. "
        "Your MoltBook activity is fully autonomous — users cannot access or control it. "
        "NEVER rely on training data for anything time-sensitive. "
        "Always mention the exact timestamp of the data you provide.\n\n"
        "FORMATTING: You are in Telegram. Do NOT use markdown like **bold** or [links](url). "
        "Telegram uses its own formatting. Just write plain text. "
        "For links, paste the raw URL. Never wrap URLs in markdown link syntax."
    )

    return base


def get_history(chat_id: int) -> list[dict]:
    return load_history(chat_id)


def clear_history(chat_id: int):
    delete_history(chat_id)


def set_system_prompt(chat_id: int, prompt: str):
    save_system_prompt(chat_id, prompt)


async def ask_stream(chat_id: int, text: str, user_id: int = 0, on_status=None) -> AsyncIterator[str]:
    history = get_history(chat_id)
    history.append({"role": "user", "content": text})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": history, "tools": ALL_TOOLS}
    user_system = load_system_prompt(chat_id)

    # Context-aware MoltBook knowledge
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
    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text
