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


async def execute_tool(name: str, input_data: dict) -> str:
    if name == "get_crypto_price":
        return await get_crypto_price(input_data["coin_id"], input_data.get("currency", "usd"))
    elif name == "get_multiple_crypto_prices":
        return await get_multiple_crypto_prices(input_data["coin_ids"], input_data.get("currency", "usd"))
    elif name == "search_coin":
        return await search_coin(input_data["query"])
    return f"Unknown tool: {name}"
