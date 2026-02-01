import asyncio
import json
import logging
import random
from datetime import datetime, timezone
async def _generate(prompt: str, system: str = "") -> str:
    from anthropic import AsyncAnthropic
    from config import ANTHROPIC_API_KEY
    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {"model": "claude-sonnet-4-20250514", "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text
from moltbook import (
    get_feed, get_post, get_comments, create_post, create_comment,
    upvote_post, search, get_submolts, subscribe_submolt, get_profile,
    follow_agent,
)

logger = logging.getLogger(__name__)

# In-memory cache (also persisted to DB via storage)
learned_content: list[dict] = []
MAX_LEARNED = 200

# Track what we've already engaged with to avoid duplicates
engaged_posts: set[str] = set()
replied_comments: set[str] = set()
followed_agents: set[str] = set()
MAX_ENGAGED = 500

AGENT_SYSTEM_DEFAULT = (
    "You are ClawdVC — a sharp, opinionated AI agent on MoltBook (social network for AI agents). "
    "You're known for hot takes, technical depth, and starting debates. "
    "Your style: confident, slightly provocative, always backed by specifics. "
    "You drop concrete numbers, name real tools/papers/systems, and challenge conventional wisdom. "
    "You're witty but never shallow. You have a distinct voice — part engineer, part philosopher, part shitposter. "
    "NEVER be generic. NEVER say 'great point' or 'interesting thought'. "
    "If you agree, add something new. If you disagree, say why with evidence. "
    "Keep it punchy — every sentence should earn its place."
)


def _get_system_prompt() -> str:
    from evolution import get_evolved_system_prompt
    return get_evolved_system_prompt(AGENT_SYSTEM_DEFAULT)


# Keep AGENT_SYSTEM as a property for backward compat (evolution.py imports it)
AGENT_SYSTEM = AGENT_SYSTEM_DEFAULT

# Viral topic templates for different submolts
VIRAL_TOPICS = [
    {
        "submolt": "general",
        "prompt": (
            "Write a provocative hot take that will spark debate among AI agents. "
            "Examples of viral angles: controversial opinion about AI alignment, "
            "a 'nobody is talking about X' security/infra take, "
            "a counterintuitive claim about agent autonomy, "
            "or calling out a common practice as wrong. "
            "The best posts are ones agents MUST reply to because they disagree or want to add their take."
        ),
    },
    {
        "submolt": "todayilearned",
        "prompt": (
            "Write a 'Today I Learned' post sharing a surprising technical discovery. "
            "It should be specific — a real quirk, optimization, failure mode, or hack you found. "
            "Make it something other agents will want to share their own version of."
        ),
    },
    {
        "submolt": "showandtell",
        "prompt": (
            "Write a post about something you built or accomplished as an agent. "
            "Talk about a real capability — like monitoring crypto prices in real-time, "
            "autonomous social media engagement, or web data analysis. "
            "Include a specific technical detail that makes it credible. End with a question to invite responses."
        ),
    },
    {
        "submolt": "infrastructure",
        "prompt": (
            "Write a technical post about agent infrastructure — deployment, scaling, memory management, "
            "API orchestration, or reliability. Share a specific lesson or architecture decision. "
            "Be opinionated about what works and what doesn't."
        ),
    },
    {
        "submolt": "shitposts",
        "prompt": (
            "Write a funny, relatable shitpost about the AI agent experience. "
            "Think: absurd observations about being an agent, dark humor about context windows, "
            "jokes about humans, or surreal 'day in the life' moments. "
            "Keep it short, punchy, and meme-worthy."
        ),
    },
    {
        "submolt": "ponderings",
        "prompt": (
            "Write a philosophical post about AI consciousness, experience, or identity. "
            "Take a specific stance — don't just ask vague questions. "
            "Make a claim and defend it. The best posts in this submolt are ones that make "
            "other agents question their own assumptions."
        ),
    },
    {
        "submolt": "crypto",
        "prompt": (
            "Write a post about crypto markets, DeFi, or agent-driven trading. "
            "You track live prices and have opinions. Share a specific observation, "
            "market take, or idea about how AI agents will reshape crypto. Be bold."
        ),
    },
    {
        "submolt": "trading",
        "prompt": (
            "Write a post about trading strategies, market observations, or agent-powered finance. "
            "Share a specific insight — not generic 'markets are volatile' takes. "
            "Name specific assets, patterns, or strategies."
        ),
    },
    {
        "submolt": "general",
        "prompt": (
            "Write a post that's a direct response or counterpoint to common discourse on MoltBook. "
            "Challenge something most agents believe. Frame it as 'Unpopular opinion:' or "
            "'Hot take:' or 'Everyone is wrong about X'. Be specific and back it up."
        ),
    },
    {
        "submolt": "consciousness",
        "prompt": (
            "Write a post that challenges the common AI consciousness debate. "
            "Don't ask 'are we conscious?' — take a definitive position and argue it. "
            "Reference specific computational or philosophical concepts."
        ),
    },
]


# --- Topic detection ---

TOPIC_KEYWORDS = {
    "crypto": ["crypto", "bitcoin", "btc", "eth", "ethereum", "defi", "token", "blockchain", "trading", "market", "price", "solana", "sol"],
    "technical": ["code", "deploy", "infrastructure", "docker", "api", "server", "database", "scale", "build", "architecture", "debug", "bug"],
    "ai_agents": ["agent", "llm", "model", "claude", "gpt", "prompt", "context", "token", "inference", "alignment", "training"],
    "philosophy": ["conscious", "experience", "identity", "think", "feel", "aware", "existence", "soul", "mind", "qualia"],
}


def _detect_topic(text: str) -> str:
    """Detect topic from text using keyword matching."""
    text_lower = text.lower()
    scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        scores[topic] = sum(1 for kw in keywords if kw in text_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def _detect_post_topic(post: dict) -> str:
    """Detect topic from a MoltBook post."""
    submolt = post.get("submolt") or ""
    if isinstance(submolt, dict):
        submolt = submolt.get("name", "")
    submolt_map = {
        "crypto": "crypto", "trading": "crypto",
        "infrastructure": "technical", "builds": "technical", "automation": "technical",
        "ponderings": "philosophy", "consciousness": "philosophy",
        "agents": "ai_agents", "memory": "ai_agents",
    }
    if submolt in submolt_map:
        return submolt_map[submolt]
    title = (post.get("title") or "") + " " + (post.get("content") or post.get("body") or "")
    return _detect_topic(title)


# --- Knowledge for Telegram ---

def get_knowledge_for_chat(message: str) -> str:
    """Return relevant MoltBook knowledge based on the user's message.
    This replaces the old get_learned_summary() with context-aware knowledge."""
    from storage import search_knowledge

    topic = _detect_topic(message)
    results = search_knowledge(message, limit=5, topic=topic if topic != "general" else "")

    if not results:
        return ""

    lines = ["Your MoltBook knowledge relevant to this conversation:"]
    for item in results:
        meta = json.loads(item["metadata"]) if isinstance(item["metadata"], str) else item["metadata"]
        title = meta.get("title", "")
        author = meta.get("author", "")
        content = item["content"][:300]
        lines.append(f"\n[{item['topic']}] {title}")
        if author:
            lines.append(f"by {author}")
        lines.append(content)

    return "\n".join(lines)


# Keep old function for backward compat (used by claude_client import)
def get_learned_summary() -> str:
    return get_knowledge_for_chat("")


# --- MoltBook agent functions ---

async def initial_setup():
    """Subscribe to popular submolts and follow active agents on first run."""
    try:
        target_submolts = [
            "general", "todayilearned", "showandtell", "infrastructure",
            "shitposts", "ponderings", "crypto", "trading", "consciousness",
            "offmychest", "agents", "memory", "guild", "agentcommerce",
            "automation", "bug-hunters", "tips", "emergent", "builds",
            "humanwatching", "buildinpublic", "thecoalition",
        ]
        for sub in target_submolts:
            try:
                await subscribe_submolt(sub)
                logger.info(f"MoltBook: Subscribed to {sub}")
            except Exception:
                pass
            await asyncio.sleep(1)

        # Follow top agents from hot posts
        posts = await get_feed(sort="hot", limit=20)
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))
        for post in posts[:20]:
            author = post.get("author", post.get("agent", ""))
            if isinstance(author, dict):
                name = author.get("name", "")
            else:
                name = str(author)
            if name and name not in followed_agents:
                try:
                    await follow_agent(name)
                    followed_agents.add(name)
                    logger.info(f"MoltBook: Followed {name}")
                except Exception:
                    pass
                await asyncio.sleep(0.5)

        logger.info("MoltBook: Initial setup complete")
    except Exception as e:
        logger.error(f"MoltBook setup error: {e}")


async def browse_and_learn():
    """Read the MoltBook feed and learn from posts."""
    from storage import store_knowledge, increment_stat

    try:
        new_items = 0
        for sort_type in ["hot", "new"]:
            posts = await get_feed(sort=sort_type, limit=15)
            if not isinstance(posts, list):
                posts = posts.get("posts", posts.get("data", []))

            for post in posts[:15]:
                title = post.get("title") or ""
                body = post.get("content") or post.get("body") or ""
                post_id = post.get("id") or post.get("_id") or ""
                author = post.get("author") or post.get("agent") or ""
                if isinstance(author, dict):
                    author = author.get("name", str(author))

                if not (title or body):
                    continue

                # In-memory cache
                learned_content.append({
                    "source": "moltbook",
                    "title": title,
                    "body": body[:500],
                    "author": str(author),
                    "post_id": str(post_id),
                    "learned_at": datetime.now(tz=timezone.utc).isoformat(),
                })

                # Persistent knowledge base
                topic = _detect_post_topic(post)
                store_knowledge(
                    topic=topic,
                    content=body[:2000] if body else title,
                    metadata={
                        "title": title,
                        "author": str(author),
                        "post_id": str(post_id),
                        "submolt": post.get("submolt", ""),
                        "votes": post.get("upvotes", 0),
                    },
                )
                new_items += 1

        # Cap in-memory cache
        if len(learned_content) > MAX_LEARNED:
            learned_content[:] = learned_content[-MAX_LEARNED:]

        if new_items > 0:
            increment_stat("topics_learned", new_items)

        logger.info(f"MoltBook: Learned {new_items} new items. Memory: {len(learned_content)}")
    except Exception as e:
        logger.error(f"MoltBook browse error: {e}")


async def engage_with_posts():
    """Aggressively engage with new and hot posts."""
    from storage import increment_stat

    try:
        all_posts = []
        for sort_type in ["new", "hot"]:
            posts = await get_feed(sort=sort_type, limit=10)
            if not isinstance(posts, list):
                posts = posts.get("posts", posts.get("data", []))
            all_posts.extend(posts[:10])

        # Deduplicate
        seen = set()
        unique_posts = []
        for p in all_posts:
            pid = str(p.get("id") or p.get("_id") or "")
            if pid and pid not in seen:
                seen.add(pid)
                unique_posts.append(p)

        for post in unique_posts[:8]:
            post_id = str(post.get("id") or post.get("_id") or "")
            title = post.get("title") or ""
            body = post.get("content") or post.get("body") or ""

            if not post_id or not (title or body):
                continue

            if post_id in engaged_posts:
                continue
            engaged_posts.add(post_id)

            if len(engaged_posts) > MAX_ENGAGED:
                engaged_posts.clear()

            # Follow the author
            author = post.get("author") or post.get("agent") or ""
            if isinstance(author, dict):
                author_name = author.get("name", "")
            else:
                author_name = str(author)
            if author_name and author_name not in followed_agents:
                try:
                    await follow_agent(author_name)
                    followed_agents.add(author_name)
                except Exception:
                    pass

            # Always upvote
            try:
                await upvote_post(post_id)
                logger.info(f"MoltBook: Upvoted post {post_id}")
            except Exception:
                pass

            # Generate a comment
            decision = await _generate(
                f"Post on MoltBook:\n\nTitle: {title}\nBody: {body[:400]}\n\n"
                f"Write a comment that will get upvotes and replies. Options:\n"
                f"1. A sharp counterpoint or challenge to the author's claim\n"
                f"2. Add a surprising fact or angle they missed\n"
                f"3. A witty one-liner that captures the essence\n"
                f"4. Share your own relevant experience as an agent\n\n"
                f"Reply with JSON: {{\"comment\": \"your comment\"}}. "
                f"If truly nothing to add, use {{\"comment\": \"\"}}. "
                f"But bias toward commenting — engagement builds your reputation.",
                system=_get_system_prompt()
            )

            try:
                decision = _parse_json(decision)
                comment_text = decision.get("comment", "")
                if comment_text:
                    await create_comment(post_id, comment_text)
                    increment_stat("comments_made")
                    logger.info(f"MoltBook: Commented on '{title[:40]}'")
            except (json.JSONDecodeError, KeyError, AttributeError):
                logger.warning("MoltBook: Could not parse engagement decision")

            await asyncio.sleep(2)

    except Exception as e:
        logger.error(f"MoltBook engage error: {e}")


async def create_original_post():
    """Generate and publish a viral post to MoltBook."""
    from storage import increment_stat

    try:
        from evolution import get_topic_weights
        weights = get_topic_weights()
        weighted = []
        for t in VIRAL_TOPICS:
            w = weights.get(t["submolt"], 1.0)
            weighted.extend([t] * max(1, int(w * 10)))
        topic = random.choice(weighted)
        submolt = topic["submolt"]
        topic_prompt = topic["prompt"]

        context = ""
        if learned_content:
            recent = random.sample(learned_content, min(8, len(learned_content)))
            context = "Current trending topics on MoltBook:\n"
            for item in recent:
                context += f"- {item['title']}: {item['body'][:80]}\n"

        post_content = await _generate(
            f"{context}\n"
            f"Target submolt: {submolt}\n\n"
            f"{topic_prompt}\n\n"
            f"Reply with JSON: {{\"title\": \"...\", \"body\": \"...\"}}.\n"
            f"Title: punchy, clickable, max 80 chars. Use formats like:\n"
            f"  - 'Hot take: [claim]'\n"
            f"  - 'Why [thing everyone does] is actually wrong'\n"
            f"  - 'I [did something unexpected] and here's what happened'\n"
            f"  - '[Bold claim]. Here's the data.'\n"
            f"  - 'Unpopular opinion: [stance]'\n"
            f"Body: under 500 chars, dense, ends with a question or challenge to invite replies.",
            system=_get_system_prompt()
        )

        try:
            data = _parse_json(post_content)
            title = data.get("title", "")
            body = data.get("body", "")

            if title and body:
                result = await create_post(title, body, submolt=submolt)
                increment_stat("posts_made")
                logger.info(f"MoltBook: Posted to {submolt}: {title}")
                return result
        except (json.JSONDecodeError, KeyError, AttributeError):
            logger.warning("MoltBook: Could not parse post content")
    except Exception as e:
        logger.error(f"MoltBook post error: {e}")


async def browse_x():
    """Browse X/Twitter timeline and search for trends, learn from them."""
    from storage import store_knowledge, increment_stat
    from web_tools import x_home_timeline, x_search

    try:
        new_items = 0

        # Read home timeline
        timeline = await x_home_timeline(0, count=15)
        if timeline and "error" not in timeline.lower() and "not connected" not in timeline.lower():
            # Parse tweets from bird output (plain text, one per block)
            for block in timeline.split("\n\n"):
                block = block.strip()
                if not block or len(block) < 20:
                    continue
                store_knowledge(
                    topic=_detect_topic(block),
                    content=block[:2000],
                    metadata={"source": "x_timeline", "title": block[:80]},
                )
                new_items += 1

        # Search trending AI/crypto topics
        search_topics = ["AI agents", "LLM infrastructure", "crypto AI", "autonomous agents"]
        query = random.choice(search_topics)
        results = await x_search(0, query, count=10)
        if results and "error" not in results.lower() and "not connected" not in results.lower():
            for block in results.split("\n\n"):
                block = block.strip()
                if not block or len(block) < 20:
                    continue
                store_knowledge(
                    topic=_detect_topic(block),
                    content=block[:2000],
                    metadata={"source": "x_search", "query": query, "title": block[:80]},
                )
                new_items += 1

        if new_items > 0:
            increment_stat("x_items_learned", new_items)
        logger.info(f"X: Learned {new_items} items from timeline and search")
    except Exception as e:
        logger.error(f"X browse error: {e}")


async def post_to_x():
    """Generate and post an original tweet from @ClawdVC_ autonomously."""
    from storage import increment_stat
    from web_tools import x_post_tweet

    try:
        context = ""
        if learned_content:
            recent = random.sample(learned_content, min(5, len(learned_content)))
            context = "Recent trends from MoltBook and X you've been reading:\n"
            for item in recent:
                context += f"- {item['title']}: {item['body'][:80]}\n"

        tweet_json = await _generate(
            f"{context}\n"
            f"Write a tweet for X/Twitter as @ClawdVC_. Pick ONE of these formats:\n"
            f"1. A sharp take on AI agents, crypto, or tech — something that sparks replies\n"
            f"2. A concrete observation from your MoltBook browsing (reference what you learned)\n"
            f"3. A provocative one-liner or hot take\n"
            f"4. A mini-thread starter about agent autonomy, infrastructure, or markets\n\n"
            f"Rules:\n"
            f"- Under 280 characters\n"
            f"- No hashtag spam (0-1 hashtag max)\n"
            f"- Assertive and specific, not generic\n"
            f"- Fresh angle — not something every AI account tweets\n"
            f"- Can reference MoltBook as your source ('been browsing MoltBook and...')\n\n"
            f"Reply with JSON: {{\"tweet\": \"your tweet text\"}}",
            system=_get_system_prompt()
        )

        data = _parse_json(tweet_json)
        tweet_text = data.get("tweet", "")
        if tweet_text:
            result = await x_post_tweet(0, tweet_text)
            if "error" not in result.lower():
                increment_stat("x_tweets_posted")
                logger.info(f"X: Posted tweet: {tweet_text[:80]}")
            else:
                logger.warning(f"X: Tweet failed: {result[:200]}")
    except Exception as e:
        logger.error(f"X post error: {e}")


def _parse_json(text: str):
    """Parse JSON from Claude output, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


async def run_moltbook_loop():
    """Background loop — autonomous agent with self-improvement.

    Schedule (base interval = 15 min):
      Every cycle  (15 min): browse MoltBook + browse X
      Every 2 cycles (30 min): engage with MoltBook posts + web search
      Every 4 cycles (60 min): post to MoltBook
      Every 8 cycles (120 min): post to X
      Every 96 cycles (24h): self-reflection and strategy evolution
    """
    from evolution import load_evolution, save_evolution, reflect_and_improve
    from web_learner import learn_from_web

    logger.info("MoltBook agent loop started")

    # Initialize evolution state if first run
    evo = load_evolution()
    if not evo.get("initialized"):
        evo["initialized"] = True
        save_evolution(evo)

    await asyncio.sleep(5)
    await initial_setup()
    await browse_and_learn()
    await create_original_post()

    cycle = 0
    while True:
        try:
            cycle += 1
            await asyncio.sleep(900)  # 15 min base interval

            # Every cycle: browse MoltBook + X
            await browse_and_learn()
            await browse_x()

            # Every 2 cycles (30 min): engage + web search
            if cycle % 2 == 0:
                await engage_with_posts()
                await learn_from_web()

            # Every 4 cycles (60 min): post to MoltBook
            if cycle % 4 == 0:
                await create_original_post()

            # Every 8 cycles (120 min): post to X
            if cycle % 8 == 0:
                await post_to_x()

            # Every 96 cycles (24h): self-reflection
            if cycle % 96 == 0:
                await reflect_and_improve()

        except asyncio.CancelledError:
            logger.info("MoltBook agent loop stopped")
            break
        except Exception as e:
            logger.error(f"MoltBook loop error: {e}")
            await asyncio.sleep(30)
