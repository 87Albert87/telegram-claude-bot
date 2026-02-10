import json
import logging
import random

from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY
from storage import store_knowledge, increment_stat

logger = logging.getLogger(__name__)

# Broad world awareness — rotated each cycle
WORLD_NEWS_QUERIES = [
    "biggest breaking news today worldwide",
    "crypto market news today",
    "world politics major events today",
    "US economy news today",
    "AI technology breakthroughs this week",
    "global financial markets today",
    "geopolitics conflicts updates today",
    "tech industry major news today",
    "central banks monetary policy news",
    "climate energy policy news today",
]


async def learn_from_web() -> int:
    """Search the web broadly to stay informed about everything happening."""
    from evolution import get_web_search_topics

    # Mix evolution topics with world news for full coverage
    evo_topics = get_web_search_topics()
    all_topics = WORLD_NEWS_QUERIES + evo_topics

    # Pick 2 queries: 1 world news + 1 specialized
    world_query = random.choice(WORLD_NEWS_QUERIES)
    specialized_query = random.choice(evo_topics) if evo_topics else random.choice(WORLD_NEWS_QUERIES)

    total_items = 0
    for query in [world_query, specialized_query]:
        items = await _search_and_store(query)
        total_items += items

    if total_items > 0:
        increment_stat("web_items_learned", total_items)
    logger.info(f"Web: Learned {total_items} items from web search")
    return total_items


async def _search_and_store(query: str) -> int:
    """Run a single web search query and store results."""
    try:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search the web for: {query}\n\n"
                    f"Find the 5-8 most important, freshest pieces of news (last 24-48h preferred).\n"
                    f"For each, provide:\n"
                    f"- title: headline\n"
                    f"- summary: 2-3 sentences with specific facts, numbers, names, dates\n"
                    f"- topic: one of [crypto, politics, economy, tech, ai_agents, geopolitics, markets, energy, general]\n\n"
                    f"Reply with JSON: {{\"results\": [{{\"title\": \"...\", \"summary\": \"...\", \"topic\": \"...\"}}]}}"
                ),
            }],
        )

        # Extract text
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
                break

        if not text:
            return 0

        data = _parse_json(text)
        results = data.get("results", [])
        new_items = 0

        for item in results:
            title = item.get("title", "")
            summary = item.get("summary", "")
            topic = item.get("topic", _detect_topic(query))
            if not title or not summary:
                continue
            store_knowledge(
                topic=topic,
                content=f"{title}\n{summary}"[:2000],
                metadata={
                    "source": "web_search",
                    "title": title[:200],
                    "query": query,
                },
            )
            new_items += 1

        logger.info(f"Web: '{query}' -> {new_items} items")
        return new_items
    except Exception as e:
        logger.error(f"Web search error for '{query}': {e}")
        return 0


def _detect_topic(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ("crypto", "bitcoin", "defi", "token", "ethereum")):
        return "crypto"
    if any(w in q for w in ("politic", "election", "government", "congress", "senate", "trump", "war")):
        return "politics"
    if any(w in q for w in ("economy", "gdp", "inflation", "fed", "interest rate", "jobs")):
        return "economy"
    if any(w in q for w in ("market", "stock", "trading", "s&p", "nasdaq", "financial")):
        return "markets"
    if any(w in q for w in ("ai", "agent", "llm", "model", "autonomous")):
        return "ai_agents"
    if any(w in q for w in ("tech", "apple", "google", "microsoft", "startup")):
        return "tech"
    if any(w in q for w in ("climate", "energy", "oil", "solar", "nuclear")):
        return "energy"
    if any(w in q for w in ("geopolitic", "conflict", "nato", "china", "russia", "sanction")):
        return "geopolitics"
    return "general"


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())
