import json
import httpx
from config import BRAVE_SEARCH_API_KEY

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for current information. Use this when the user asks about recent events, live data, or anything that requires up-to-date information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_url",
        "description": "Fetch the content of a web page. Use this when the user provides a specific URL or when you need to read a page from search results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                }
            },
            "required": ["url"]
        }
    }
]


async def web_search(query: str) -> str:
    if not BRAVE_SEARCH_API_KEY:
        return "Error: BRAVE_SEARCH_API_KEY not configured."

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 5},
            headers={"X-Subscription-Token": BRAVE_SEARCH_API_KEY, "Accept": "application/json"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("web", {}).get("results", [])[:5]:
        results.append(f"**{item['title']}**\n{item['url']}\n{item.get('description', '')}")

    return "\n\n".join(results) if results else "No results found."


async def fetch_url(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = resp.text

    if len(text) > 10000:
        text = text[:10000] + "\n... (truncated)"
    return text


async def execute_tool(name: str, input_data: dict) -> str:
    if name == "web_search":
        return await web_search(input_data["query"])
    elif name == "fetch_url":
        return await fetch_url(input_data["url"])
    return f"Unknown tool: {name}"
