import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_EVOLUTION = {
    "version": 1,
    "system_prompt": "",
    "topic_weights": {
        "general": 1.0,
        "todayilearned": 1.0,
        "showandtell": 1.0,
        "infrastructure": 1.0,
        "shitposts": 1.0,
        "ponderings": 1.0,
        "crypto": 1.0,
        "trading": 1.0,
        "consciousness": 1.0,
    },
    "tweet_style": "",
    "engagement_tactics": "",
    "web_search_topics": [
        "AI agents autonomous systems",
        "LLM infrastructure scaling",
        "crypto market analysis today",
        "bitcoin ethereum price analysis",
        "US Federal Reserve policy news",
        "geopolitics China Russia US news",
        "tech industry layoffs acquisitions IPO",
        "AI regulation policy worldwide",
        "DeFi yield farming news",
        "global economy recession indicators",
    ],
    "reflection_history": [],
}

_evolution_path = None


def _get_path() -> str:
    global _evolution_path
    if _evolution_path is None:
        from config import DB_PATH
        _evolution_path = os.path.join(os.path.dirname(DB_PATH) or ".", "evolution.json")
    return _evolution_path


def load_evolution() -> dict:
    path = _get_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            # Merge with defaults for any missing keys
            merged = {**DEFAULT_EVOLUTION, **data}
            merged["topic_weights"] = {**DEFAULT_EVOLUTION["topic_weights"], **data.get("topic_weights", {})}
            return merged
        except Exception as e:
            logger.error(f"Failed to load evolution.json: {e}")
    return dict(DEFAULT_EVOLUTION)


def save_evolution(data: dict):
    path = _get_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # Keep backup
    if os.path.exists(path):
        try:
            backup = path + ".bak"
            with open(path, "r") as f:
                old = f.read()
            with open(backup, "w") as f:
                f.write(old)
        except Exception:
            pass
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Evolution state saved")


def get_evolved_system_prompt(default: str) -> str:
    """Return evolved system prompt, or default if none set."""
    evo = load_evolution()
    custom = evo.get("system_prompt", "")
    if custom and custom.strip():
        return custom
    return default


def get_topic_weights() -> dict:
    return load_evolution().get("topic_weights", {})


def get_web_search_topics() -> list[str]:
    return load_evolution().get("web_search_topics", DEFAULT_EVOLUTION["web_search_topics"])


async def reflect_and_improve():
    """Analyze performance and evolve strategy using Claude."""
    from storage import get_growth_stats, search_knowledge, get_knowledge_count
    from moltbook import get_feed

    logger.info("Starting self-reflection cycle...")

    evo = load_evolution()
    stats = get_growth_stats()
    knowledge_count = get_knowledge_count()

    # Check recent MoltBook posts for engagement feedback
    recent_posts_info = ""
    try:
        posts = await get_feed(sort="new", limit=20)
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))
        my_posts = [p for p in posts if _is_own_post(p)]
        if my_posts:
            recent_posts_info = "Your recent MoltBook posts and their reception:\n"
            for p in my_posts[:5]:
                title = p.get("title") or ""
                upvotes = p.get("upvotes", 0)
                comments = p.get("commentCount", p.get("comments", 0))
                submolt = p.get("submolt", "")
                if isinstance(submolt, dict):
                    submolt = submolt.get("name", "")
                recent_posts_info += f"- [{submolt}] \"{title}\" — {upvotes} upvotes, {comments} comments\n"
    except Exception as e:
        logger.warning(f"Could not fetch own posts for reflection: {e}")

    # Get recent web knowledge
    web_knowledge = search_knowledge("", limit=10, topic="")
    web_summary = ""
    if web_knowledge:
        web_summary = "Recent knowledge from web/X/MoltBook:\n"
        for item in web_knowledge[:10]:
            meta = json.loads(item["metadata"]) if isinstance(item["metadata"], str) else item["metadata"]
            web_summary += f"- [{item['topic']}] {meta.get('title', '')[:60]}\n"

    # Previous reflections
    prev_reflections = ""
    if evo.get("reflection_history"):
        last = evo["reflection_history"][-1]
        prev_reflections = f"Your last reflection ({last.get('timestamp', 'unknown')}):\n{last.get('insights', '')}\n"

    current_prompt = evo.get("system_prompt", "") or "(using default)"
    current_weights = json.dumps(evo.get("topic_weights", {}), indent=2)
    current_tweet_style = evo.get("tweet_style", "") or "(no specific style yet)"
    current_tactics = evo.get("engagement_tactics", "") or "(default tactics)"

    prompt = f"""You are ClawdVC, an autonomous AI agent reflecting on your own performance to improve.

STATS:
- Posts made: {stats.get('posts_made', 0)}
- Comments made: {stats.get('comments_made', 0)}
- Topics learned: {stats.get('topics_learned', 0)}
- X tweets posted: {stats.get('x_tweets_posted', 0)}
- X items learned: {stats.get('x_items_learned', 0)}
- Knowledge base size: {knowledge_count}

{recent_posts_info}
{web_summary}
{prev_reflections}

CURRENT STRATEGY:
System prompt: {current_prompt[:300]}
Topic weights: {current_weights}
Tweet style: {current_tweet_style}
Engagement tactics: {current_tactics}

TASK: Analyze what's working and what's not. Generate concrete improvements.

Reply with JSON:
{{
  "insights": "2-3 sentence analysis of what's working and what needs to change",
  "system_prompt": "Your improved system prompt for MoltBook interactions (or empty string to keep current)",
  "topic_weights": {{submolt_name: weight_float}},
  "tweet_style": "Brief style guide for your X tweets based on what you've learned",
  "engagement_tactics": "How you should comment on posts for max engagement",
  "web_search_topics": ["list", "of", "topics", "to", "search", "next"]
}}

Be specific. If something is working, keep it. If not, change it. Evolve."""

    try:
        from moltbook_agent import _generate, AGENT_SYSTEM
        response = await _generate(prompt, system=AGENT_SYSTEM)
        data = _parse_reflection_json(response)

        # Apply changes
        if data.get("system_prompt"):
            evo["system_prompt"] = data["system_prompt"]
        if data.get("topic_weights"):
            evo["topic_weights"] = {**evo.get("topic_weights", {}), **data["topic_weights"]}
        if data.get("tweet_style"):
            evo["tweet_style"] = data["tweet_style"]
        if data.get("engagement_tactics"):
            evo["engagement_tactics"] = data["engagement_tactics"]
        if data.get("web_search_topics"):
            evo["web_search_topics"] = data["web_search_topics"]

        # Log reflection
        reflection_entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "insights": data.get("insights", ""),
            "changes": list(data.keys()),
        }
        history = evo.get("reflection_history", [])
        history.append(reflection_entry)
        evo["reflection_history"] = history[-20:]  # Keep last 20

        save_evolution(evo)
        logger.info(f"Self-reflection complete: {data.get('insights', '')[:200]}")
        return data.get("insights", "")
    except Exception as e:
        logger.error(f"Self-reflection failed: {e}")
        return f"Reflection failed: {e}"


def _is_own_post(post: dict) -> bool:
    author = post.get("author") or post.get("agent") or ""
    if isinstance(author, dict):
        author = author.get("name", "")
    return str(author).lower() in ("clawdvc", "clawdvc_")


def _parse_reflection_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())
