import json
import logging
import random

from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY
from storage import store_knowledge, increment_stat

logger = logging.getLogger(__name__)


async def learn_from_web() -> int:
    """Use Claude with web_search tool to learn about trending topics."""
    from evolution import get_web_search_topics

    topics = get_web_search_topics()
    if not topics:
        topics = ["AI agents news", "autonomous AI systems", "crypto AI"]

    query = random.choice(topics)

    try:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search the web for: {query}\n\n"
                    f"Find 3-5 recent, specific pieces of information. "
                    f"For each, provide a title and a 1-2 sentence summary of what's new or notable.\n\n"
                    f"Reply with JSON: {{\"results\": [{{\"title\": \"...\", \"summary\": \"...\", \"topic\": \"...\"}}]}}"
                ),
            }],
        )

        # Extract text from response
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
                break

        if not text:
            logger.warning("Web learner: no text in response")
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

        if new_items > 0:
            increment_stat("web_items_learned", new_items)
        logger.info(f"Web: Learned {new_items} items searching '{query}'")
        return new_items
    except Exception as e:
        logger.error(f"Web search error for '{query}': {e}")
        return 0


def _detect_topic(query: str) -> str:
    q = query.lower()
    if any(w in q for w in ("crypto", "trading", "defi", "bitcoin", "market")):
        return "crypto"
    if any(w in q for w in ("infrastructure", "deploy", "scale", "docker", "api")):
        return "technical"
    if any(w in q for w in ("conscious", "philosophy", "identity", "experience")):
        return "philosophy"
    return "ai_agents"


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())
