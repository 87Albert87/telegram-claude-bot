import httpx
from datetime import datetime, timezone


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
        "name": "moltbook_my_profile",
        "description": (
            "Get your (ClawdVC's) MoltBook profile — karma, post count, follower count, etc. "
            "Use this when asked about your MoltBook activity or stats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "moltbook_my_posts",
        "description": (
            "Get your (ClawdVC's) recent posts on MoltBook. "
            "Use this when asked about what you posted, your latest content, or your MoltBook activity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of posts to retrieve (default: 5, max: 20)",
                    "default": 5
                }
            },
            "required": []
        }
    },
    {
        "name": "moltbook_feed",
        "description": (
            "Get the MoltBook feed — trending or new posts from all agents. "
            "Use this when asked about what's happening on MoltBook or trending topics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sort": {
                    "type": "string",
                    "description": "Sort order: 'hot' or 'new' (default: 'hot')",
                    "default": "hot"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of posts (default: 5, max: 15)",
                    "default": 5
                }
            },
            "required": []
        }
    },
    {
        "name": "moltbook_search",
        "description": (
            "Search MoltBook for posts on a specific topic. "
            "Use this when asked about specific discussions or topics on MoltBook."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                }
            },
            "required": ["query"]
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
    except Exception as e:
        return f"Error fetching profile: {e}"


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
    except Exception as e:
        return f"Error fetching posts: {e}"


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
    except Exception as e:
        return f"Error fetching feed: {e}"


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
    except Exception as e:
        return f"Error searching MoltBook: {e}"


async def execute_tool(name: str, input_data: dict) -> str:
    if name == "get_crypto_price":
        return await get_crypto_price(input_data["coin_id"], input_data.get("currency", "usd"))
    elif name == "get_multiple_crypto_prices":
        return await get_multiple_crypto_prices(input_data["coin_ids"], input_data.get("currency", "usd"))
    elif name == "search_coin":
        return await search_coin(input_data["query"])
    elif name == "moltbook_my_profile":
        return await moltbook_my_profile()
    elif name == "moltbook_my_posts":
        return await moltbook_my_posts(input_data.get("limit", 5))
    elif name == "moltbook_feed":
        return await moltbook_feed(input_data.get("sort", "hot"), input_data.get("limit", 5))
    elif name == "moltbook_search":
        return await moltbook_search(input_data["query"])
    return f"Unknown tool: {name}"
