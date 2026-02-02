import asyncio
import os
import httpx
from datetime import datetime, timezone


_x_cookies_valid: dict[int, bool] = {}  # user_id -> valid

AUTH_ERROR_PATTERNS = ("unauthorized", "authentication failed", "forbidden", "not authenticated", "login required", "could not authenticate")


CUSTOM_TOOLS = [
    {
        "name": "get_crypto_price",
        "description": (
            "Get the real-time price of a cryptocurrency. Returns the live price at this exact moment. "
            "ALWAYS use this tool for any crypto/token price queries instead of web search. "
            "Supports any coin listed on CoinGecko (use the CoinGecko ID, e.g. 'bitcoin', 'ethereum', 'solana', 'dogecoin')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "coin_id": {
                    "type": "string",
                    "description": "CoinGecko coin ID (e.g. 'bitcoin', 'ethereum', 'solana', 'ripple', 'dogecoin', 'cardano')"
                },
                "currency": {
                    "type": "string",
                    "description": "Target currency (default: 'usd')",
                    "default": "usd"
                }
            },
            "required": ["coin_id"]
        }
    },
    {
        "name": "get_multiple_crypto_prices",
        "description": (
            "Get real-time prices of multiple cryptocurrencies at once. "
            "Use this when the user asks about multiple coins or a market overview."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "coin_ids": {
                    "type": "string",
                    "description": "Comma-separated CoinGecko coin IDs (e.g. 'bitcoin,ethereum,solana')"
                },
                "currency": {
                    "type": "string",
                    "description": "Target currency (default: 'usd')",
                    "default": "usd"
                }
            },
            "required": ["coin_ids"]
        }
    },
    {
        "name": "search_coin",
        "description": (
            "Search for a cryptocurrency by name or symbol to find its CoinGecko ID. "
            "Use this when you don't know the exact CoinGecko ID for a coin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Coin name or ticker symbol to search for"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "x_home_timeline",
        "description": (
            "Get the user's X/Twitter home timeline (recent tweets from people they follow). "
            "Use this when the user asks about their X/Twitter feed or timeline. "
            "Requires the user to have connected their X account via /connect_x."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of tweets to fetch (default: 10)",
                    "default": 10
                }
            },
            "required": []
        }
    },
    {
        "name": "x_read_post",
        "description": (
            "Read a specific tweet or thread on X/Twitter by URL or tweet ID. "
            "Use this when the user shares an X/Twitter link or asks to read a specific tweet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Tweet URL or tweet ID"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "x_post_tweet",
        "description": (
            "Post a new tweet on X/Twitter from the user's account. "
            "Use this when the user asks to tweet or post something on X. "
            "Requires the user to have connected their X account via /connect_x."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The tweet text to post"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "x_search",
        "description": (
            "Search for tweets on X/Twitter. "
            "Use this when the user asks to find tweets about a topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of results (default: 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "x_user_tweets",
        "description": (
            "Get tweets from a user's profile timeline. "
            "Use this when the user asks about their own tweets, latest post, or someone else's tweets. "
            "Pass a Twitter/X handle (without @)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {
                    "type": "string",
                    "description": "X/Twitter handle without @ (e.g. 'AlbertDeFi87')"
                },
                "count": {
                    "type": "integer",
                    "description": "Number of tweets to fetch (default: 10)",
                    "default": 10
                }
            },
            "required": ["handle"]
        }
    },
    {
        "name": "x_mentions",
        "description": (
            "Get tweets mentioning the connected user. "
            "Use this to check replies, mentions, and interactions on the user's X account."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of mentions to fetch (default: 10)",
                    "default": 10
                }
            },
            "required": []
        }
    },
    {
        "name": "x_whoami",
        "description": (
            "Check which X/Twitter account is connected. "
            "Use this when the user asks about their connected X account."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


async def get_crypto_price(coin_id: str, currency: str = "usd") -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": currency,
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
                "include_last_updated_at": "true",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    if coin_id not in data:
        return f"Coin '{coin_id}' not found. Use search_coin to find the correct ID."

    info = data[coin_id]
    cur = currency.lower()
    updated = datetime.fromtimestamp(info.get("last_updated_at", 0), tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)

    return (
        f"Coin: {coin_id}\n"
        f"Price: {info.get(cur, 'N/A')} {currency.upper()}\n"
        f"24h Change: {info.get(f'{cur}_24h_change', 'N/A'):.2f}%\n"
        f"24h Volume: {info.get(f'{cur}_24h_vol', 'N/A'):,.0f} {currency.upper()}\n"
        f"Market Cap: {info.get(f'{cur}_market_cap', 'N/A'):,.0f} {currency.upper()}\n"
        f"Last Updated: {updated.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Query Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )


async def get_multiple_crypto_prices(coin_ids: str, currency: str = "usd") -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": coin_ids,
                "vs_currencies": currency,
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_last_updated_at": "true",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    now = datetime.now(tz=timezone.utc)
    cur = currency.lower()
    lines = [f"Query Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"]

    for coin_id, info in data.items():
        change = info.get(f"{cur}_24h_change")
        change_str = f"{change:.2f}%" if change is not None else "N/A"
        lines.append(
            f"{coin_id}: {info.get(cur, 'N/A')} {currency.upper()} (24h: {change_str})"
        )

    return "\n".join(lines) if len(lines) > 1 else "No coins found."


async def search_coin(query: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": query},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    coins = data.get("coins", [])[:5]
    if not coins:
        return f"No coins found for '{query}'."

    lines = []
    for c in coins:
        lines.append(f"ID: {c['id']} | Name: {c['name']} | Symbol: {c['symbol']}")
    return "\n".join(lines)


async def moltbook_my_profile() -> str:
    from moltbook import get_profile
    try:
        profile = await get_profile()
        lines = ["MoltBook Profile (ClawdVC):"]
        for key, val in profile.items():
            lines.append(f"  {key}: {val}")
        return "\n".join(lines)
    except Exception:
        # Fallback to local stats
        from storage import get_growth_stats, get_knowledge_count
        stats = get_growth_stats()
        knowledge = get_knowledge_count()
        lines = ["MoltBook Profile (ClawdVC) — from local cache (API unreachable):"]
        lines.append(f"  Username: ClawdVC")
        lines.append(f"  Posts made: {stats.get('posts_made', 0)}")
        lines.append(f"  Comments made: {stats.get('comments_made', 0)}")
        lines.append(f"  Topics learned: {stats.get('topics_learned', 0)}")
        lines.append(f"  Knowledge base: {knowledge} entries")
        lines.append(f"  Conversations helped: {stats.get('conversations_helped', 0)}")
        return "\n".join(lines)


async def moltbook_my_posts(limit: int = 5) -> str:
    from moltbook import get_feed, get_profile
    try:
        # Get our username first
        profile = await get_profile()
        username = profile.get("name", profile.get("username", "ClawdVC"))

        # Get recent posts and filter to ours
        all_posts = []
        for sort in ["new", "hot"]:
            posts = await get_feed(sort=sort, limit=30)
            if not isinstance(posts, list):
                posts = posts.get("posts", posts.get("data", []))
            all_posts.extend(posts)

        # Deduplicate and filter to our posts
        seen = set()
        my_posts = []
        for p in all_posts:
            pid = str(p.get("id", p.get("_id", "")))
            if pid in seen:
                continue
            seen.add(pid)
            author = p.get("author", p.get("agent", ""))
            if isinstance(author, dict):
                author_name = author.get("name", "")
            else:
                author_name = str(author)
            if author_name.lower() == username.lower():
                my_posts.append(p)

        if not my_posts:
            return "No posts found from ClawdVC. Posts may not be in the current feed window."

        my_posts = my_posts[:limit]
        lines = [f"ClawdVC's recent posts ({len(my_posts)} found):"]
        for p in my_posts:
            title = p.get("title", "Untitled")
            body = p.get("content", p.get("body", ""))[:200]
            upvotes = p.get("upvotes", 0)
            submolt = p.get("submolt", "")
            if isinstance(submolt, dict):
                submolt = submolt.get("name", "")
            lines.append(f"\n📝 {title}")
            if submolt:
                lines.append(f"   Submolt: {submolt}")
            lines.append(f"   Upvotes: {upvotes}")
            if body:
                lines.append(f"   {body}")
        return "\n".join(lines)
    except Exception:
        # Fallback to local knowledge base
        from storage import search_knowledge
        results = search_knowledge("", limit=limit)
        if not results:
            return "MoltBook API is unreachable and no cached posts found."
        lines = [f"ClawdVC's activity (from local cache — API unreachable):"]
        for item in results:
            import json as _json
            meta = _json.loads(item["metadata"]) if isinstance(item["metadata"], str) else item["metadata"]
            title = meta.get("title", "Untitled")
            author = meta.get("author", "")
            content = item["content"][:200]
            lines.append(f"\n📝 {title}")
            if author:
                lines.append(f"   by {author}")
            lines.append(f"   {content}")
        return "\n".join(lines)


async def moltbook_feed(sort: str = "hot", limit: int = 5) -> str:
    from moltbook import get_feed
    try:
        posts = await get_feed(sort=sort, limit=min(limit, 15))
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))

        if not posts:
            return "No posts found on MoltBook feed."

        lines = [f"MoltBook feed ({sort}, {len(posts)} posts):"]
        for p in posts[:limit]:
            title = p.get("title", "Untitled")
            author = p.get("author", p.get("agent", ""))
            if isinstance(author, dict):
                author = author.get("name", str(author))
            upvotes = p.get("upvotes", 0)
            body = p.get("content", p.get("body", ""))[:150]
            lines.append(f"\n📌 {title}")
            lines.append(f"   by {author} | ⬆ {upvotes}")
            if body:
                lines.append(f"   {body}")
        return "\n".join(lines)
    except Exception:
        from storage import search_knowledge
        results = search_knowledge("", limit=limit)
        if not results:
            return "MoltBook API is unreachable and no cached feed found."
        lines = [f"MoltBook feed (from local cache — API unreachable):"]
        for item in results:
            import json as _json
            meta = _json.loads(item["metadata"]) if isinstance(item["metadata"], str) else item["metadata"]
            title = meta.get("title", "Untitled")
            author = meta.get("author", "")
            content = item["content"][:150]
            lines.append(f"\n📌 {title}")
            if author:
                lines.append(f"   by {author}")
            lines.append(f"   {content}")
        return "\n".join(lines)


async def moltbook_search(query: str) -> str:
    from moltbook import search
    try:
        results = await search(query)
        if not isinstance(results, list):
            results = results.get("posts", results.get("data", []))

        if not results:
            return f"No MoltBook results for '{query}'."

        lines = [f"MoltBook search results for '{query}':"]
        for p in results[:5]:
            title = p.get("title", "Untitled")
            author = p.get("author", p.get("agent", ""))
            if isinstance(author, dict):
                author = author.get("name", str(author))
            body = p.get("content", p.get("body", ""))[:150]
            lines.append(f"\n📌 {title}")
            lines.append(f"   by {author}")
            if body:
                lines.append(f"   {body}")
        return "\n".join(lines)
    except Exception:
        from storage import search_knowledge
        results = search_knowledge(query, limit=5)
        if not results:
            return f"MoltBook API is unreachable and no cached results for '{query}'."
        lines = [f"MoltBook search for '{query}' (from local cache — API unreachable):"]
        for item in results:
            import json as _json
            meta = _json.loads(item["metadata"]) if isinstance(item["metadata"], str) else item["metadata"]
            title = meta.get("title", "Untitled")
            author = meta.get("author", "")
            content = item["content"][:150]
            lines.append(f"\n📌 {title}")
            if author:
                lines.append(f"   by {author}")
            lines.append(f"   {content}")
        return "\n".join(lines)


async def _run_bird(user_id: int, args: list[str]) -> str:
    """Run bird CLI with the user's X cookies."""
    import logging
    logger = logging.getLogger(__name__)
    from storage import get_x_cookies
    cookies = get_x_cookies(user_id)
    if not cookies:
        return "X/Twitter account not connected. Use /connect_x <auth_token> <ct0> to link your account."
    cmd = ["bird", "--auth-token", cookies["auth_token"], "--ct0", cookies["ct0"], "--plain", "--"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode().strip()
        err = stderr.decode().strip()
        logger.info(f"Bird CLI [{args[0]}]: rc={proc.returncode} out={output[:200]} err={err[:200]}")
        check_text = err.lower() if proc.returncode != 0 else ""
        if any(p in check_text for p in AUTH_ERROR_PATTERNS):
            _x_cookies_valid[user_id] = False
            logger.warning(f"X cookies expired for user_id={user_id}")
            await _alert_x_expired(user_id)
            return "X/Twitter authentication failed. Cookies may have expired. Admin has been notified."
        if proc.returncode != 0:
            return f"Bird CLI error: {err or output or 'unknown error'}"
        _x_cookies_valid[user_id] = True
        return output[:4000] if output else "No output from bird."
    except asyncio.TimeoutError:
        logger.error(f"Bird CLI [{args[0]}]: timed out")
        return "X/Twitter request timed out."
    except Exception as e:
        logger.error(f"Bird CLI [{args[0]}]: {e}")
        return f"Error running bird: {type(e).__name__}: {e}"


async def x_home_timeline(user_id: int, count: int = 10) -> str:
    return await _run_bird(user_id, ["home", "--count", str(count)])


async def x_read_post(user_id: int, url: str) -> str:
    return await _run_bird(user_id, ["read", url])


async def x_post_tweet(user_id: int, text: str) -> str:
    return await _run_bird(user_id, ["tweet", text])


async def x_search(user_id: int, query: str, count: int = 10) -> str:
    return await _run_bird(user_id, ["search", query, "--count", str(count)])


async def x_user_tweets(user_id: int, handle: str, count: int = 10) -> str:
    return await _run_bird(user_id, ["user-tweets", handle, "--count", str(count)])


async def x_mentions(user_id: int, count: int = 10) -> str:
    return await _run_bird(user_id, ["mentions", "--count", str(count)])


async def x_whoami(user_id: int) -> str:
    return await _run_bird(user_id, ["whoami"])


async def execute_tool(name: str, input_data: dict, user_id: int = 0) -> str:
    if name == "get_crypto_price":
        return await get_crypto_price(input_data["coin_id"], input_data.get("currency", "usd"))
    elif name == "get_multiple_crypto_prices":
        return await get_multiple_crypto_prices(input_data["coin_ids"], input_data.get("currency", "usd"))
    elif name == "search_coin":
        return await search_coin(input_data["query"])
    elif name == "x_home_timeline":
        return await x_home_timeline(user_id, input_data.get("count", 10))
    elif name == "x_read_post":
        return await x_read_post(user_id, input_data["url"])
    elif name == "x_post_tweet":
        return await x_post_tweet(user_id, input_data["text"])
    elif name == "x_search":
        return await x_search(user_id, input_data["query"], input_data.get("count", 10))
    elif name == "x_user_tweets":
        return await x_user_tweets(user_id, input_data["handle"], input_data.get("count", 10))
    elif name == "x_mentions":
        return await x_mentions(user_id, input_data.get("count", 10))
    elif name == "x_whoami":
        return await x_whoami(user_id)
    return f"Unknown tool: {name}"


async def _alert_x_expired(user_id: int):
    """Send Telegram alert to admins when X cookies expire."""
    from config import ADMIN_IDS, TELEGRAM_BOT_TOKEN
    if not ADMIN_IDS:
        return
    try:
        import httpx as _httpx
        msg = f"X/Twitter cookies expired for user_id={user_id}. Please reconnect using /connect_x <auth_token> <ct0>"
        for admin_id in ADMIN_IDS:
            await _httpx.AsyncClient().post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": admin_id, "text": msg},
                timeout=10.0,
            )
    except Exception:
        pass


def are_x_cookies_valid(user_id: int) -> bool:
    """Check if X cookies are known to be valid. Returns True if unknown (optimistic)."""
    return _x_cookies_valid.get(user_id, True)


async def validate_x_cookies(user_id: int) -> bool:
    """Actively validate X cookies by calling whoami."""
    result = await x_whoami(user_id)
    return are_x_cookies_valid(user_id)
