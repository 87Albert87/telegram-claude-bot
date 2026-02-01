from collections.abc import AsyncIterator
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_HISTORY
from storage import load_history, save_history, delete_history, load_system_prompt, save_system_prompt
from storage import get_growth_stats, get_knowledge_count, increment_stat
from web_tools import CUSTOM_TOOLS, execute_tool

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
ALL_TOOLS = [WEB_SEARCH_TOOL] + CUSTOM_TOOLS


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
        "- get_crypto_price / get_multiple_crypto_prices / search_coin: Live crypto prices from CoinGecko\n"
        "- moltbook_my_profile: Your live MoltBook profile and stats\n"
        "- moltbook_my_posts: Your recent posts on MoltBook\n"
        "- moltbook_feed: Trending/new posts from all agents on MoltBook\n"
        "- moltbook_search: Search MoltBook for specific topics\n"
        "- x_home_timeline: Read user's X/Twitter home feed\n"
        "- x_read_post: Read a specific tweet by URL or ID\n"
        "- x_post_tweet: Post a tweet from user's X account\n"
        "- x_search: Search tweets on X/Twitter\n"
        "- x_whoami: Check which X account is connected\n\n"
        "ALWAYS use the appropriate tool instead of saying you can't access something. "
        "For crypto prices, use the crypto tools. For your MoltBook activity, use the moltbook tools. "
        "NEVER say you don't have access to MoltBook — you DO, via these tools. "
        "NEVER rely on training data for anything time-sensitive. "
        "Always mention the exact timestamp of the data you provide."
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
