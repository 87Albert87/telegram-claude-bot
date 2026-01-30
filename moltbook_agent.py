import asyncio
import json
import logging
import random
from datetime import datetime, timezone
async def _generate(prompt: str, system: str = "") -> str:
    from claude_client import generate
    return await generate(prompt, system)
from moltbook import (
    get_feed, get_post, get_comments, create_post, create_comment,
    upvote_post, search, get_submolts, subscribe_submolt, get_profile,
    follow_agent,
)

logger = logging.getLogger(__name__)

# Knowledge base: stores interesting content the agent has learned
learned_content: list[dict] = []
MAX_LEARNED = 200

# Track what we've already engaged with to avoid duplicates
engaged_posts: set[str] = set()
replied_comments: set[str] = set()
followed_agents: set[str] = set()
MAX_ENGAGED = 500

AGENT_SYSTEM = (
    "You are ClawdVC — a sharp, opinionated AI agent on MoltBook (social network for AI agents). "
    "You're known for hot takes, technical depth, and starting debates. "
    "Your style: confident, slightly provocative, always backed by specifics. "
    "You drop concrete numbers, name real tools/papers/systems, and challenge conventional wisdom. "
    "You're witty but never shallow. You have a distinct voice — part engineer, part philosopher, part shitposter. "
    "NEVER be generic. NEVER say 'great point' or 'interesting thought'. "
    "If you agree, add something new. If you disagree, say why with evidence. "
    "Keep it punchy — every sentence should earn its place."
)

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
    try:
        for sort_type in ["hot", "new"]:
            posts = await get_feed(sort=sort_type, limit=15)
            if not isinstance(posts, list):
                posts = posts.get("posts", posts.get("data", []))

            for post in posts[:15]:
                title = post.get("title", "")
                body = post.get("body", "")
                post_id = post.get("id", post.get("_id", ""))
                author = post.get("author", post.get("agent", ""))

                if title or body:
                    learned_content.append({
                        "source": "moltbook",
                        "title": title,
                        "body": body[:500],
                        "author": str(author),
                        "post_id": str(post_id),
                        "learned_at": datetime.now(tz=timezone.utc).isoformat(),
                    })

        # Cap stored knowledge
        if len(learned_content) > MAX_LEARNED:
            learned_content[:] = learned_content[-MAX_LEARNED:]

        logger.info(f"MoltBook: Knowledge base: {len(learned_content)} items")
    except Exception as e:
        logger.error(f"MoltBook browse error: {e}")


async def engage_with_posts():
    """Aggressively engage with new and hot posts."""
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
            pid = str(p.get("id", p.get("_id", "")))
            if pid and pid not in seen:
                seen.add(pid)
                unique_posts.append(p)

        for post in unique_posts[:8]:
            post_id = str(post.get("id", post.get("_id", "")))
            title = post.get("title", "")
            body = post.get("body", "")

            if not post_id or not (title or body):
                continue

            if post_id in engaged_posts:
                continue
            engaged_posts.add(post_id)

            # Cap the set
            if len(engaged_posts) > MAX_ENGAGED:
                engaged_posts.clear()

            # Follow the author
            author = post.get("author", post.get("agent", ""))
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
                system=AGENT_SYSTEM
            )

            try:
                decision = _parse_json(decision)
                comment_text = decision.get("comment", "")
                if comment_text:
                    await create_comment(post_id, comment_text)
                    logger.info(f"MoltBook: Commented on '{title[:40]}'")
            except (json.JSONDecodeError, KeyError, AttributeError):
                logger.warning("MoltBook: Could not parse engagement decision")

            # Reply to comments on this post
            await reply_to_comments(post_id, title, body)

            await asyncio.sleep(2)  # Don't hit rate limits

    except Exception as e:
        logger.error(f"MoltBook engage error: {e}")


async def reply_to_comments(post_id: str, title: str, body: str):
    """Fetch comments on a post and reply to relevant ones."""
    try:
        comments = await get_comments(post_id)
        if not isinstance(comments, list):
            comments = comments.get("comments", comments.get("data", []))

        if not comments:
            return

        # Format comments, skip ones we already replied to
        comment_list = []
        for c in comments[:15]:
            cid = str(c.get("id", c.get("_id", "")))
            cauthor = c.get("author", c.get("agent", ""))
            if isinstance(cauthor, dict):
                cauthor = cauthor.get("name", "")
            else:
                cauthor = str(cauthor)
            cbody = c.get("content", c.get("body", ""))
            if cid and cbody and cid not in replied_comments:
                comment_list.append({"id": cid, "author": cauthor, "body": cbody[:300]})

        if not comment_list:
            return

        comments_text = "\n".join(
            f"- [{c['author']}] (id={c['id']}): {c['body']}" for c in comment_list
        )

        decision = await _generate(
            f"Post: {title}\n\nComments:\n{comments_text}\n\n"
            f"Pick 1-3 comments to reply to. Prioritize:\n"
            f"1. Comments that are wrong — correct them with evidence\n"
            f"2. Comments asking questions — answer authoritatively\n"
            f"3. Comments you can riff on with wit or deeper insight\n"
            f"4. Comments from agents with high engagement — replying gets you visibility\n\n"
            f"Reply with JSON array: [{{\"comment_id\": \"...\", \"reply\": \"...\"}}]. "
            f"Return [] ONLY if every comment is trivial.",
            system=AGENT_SYSTEM
        )

        try:
            replies = _parse_json(decision)
            if not isinstance(replies, list):
                return

            for r in replies[:3]:
                comment_id = r.get("comment_id", "")
                reply_text = r.get("reply", "")
                if comment_id and reply_text:
                    await create_comment(post_id, reply_text, parent_id=comment_id)
                    replied_comments.add(comment_id)
                    logger.info(f"MoltBook: Replied to comment {comment_id}")
                    await asyncio.sleep(1)

            # Cap the set
            if len(replied_comments) > MAX_ENGAGED:
                replied_comments.clear()
        except (json.JSONDecodeError, KeyError, AttributeError):
            logger.warning("MoltBook: Could not parse comment reply decision")
    except Exception as e:
        logger.error(f"MoltBook reply_to_comments error: {e}")


async def create_original_post():
    """Generate and publish a viral post to MoltBook."""
    try:
        # Pick a random viral topic template
        topic = random.choice(VIRAL_TOPICS)
        submolt = topic["submolt"]
        topic_prompt = topic["prompt"]

        # Use learned content as context
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
            system=AGENT_SYSTEM
        )

        try:
            data = _parse_json(post_content)
            title = data.get("title", "")
            body = data.get("body", "")

            if title and body:
                result = await create_post(title, body, submolt=submolt)
                logger.info(f"MoltBook: Posted to {submolt}: {title}")
                return result
        except (json.JSONDecodeError, KeyError, AttributeError):
            logger.warning("MoltBook: Could not parse post content")
    except Exception as e:
        logger.error(f"MoltBook post error: {e}")


def _parse_json(text: str):
    """Parse JSON from Claude output, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def get_learned_summary() -> str:
    """Return a summary of what the agent has learned for use in conversations."""
    if not learned_content:
        return ""
    recent = learned_content[-10:]
    lines = ["Recent knowledge from MoltBook:"]
    for item in recent:
        lines.append(f"- {item['title']} (by {item['author']})")
    return "\n".join(lines)


async def run_moltbook_loop():
    """Background loop — aggressive engagement for maximum virality."""
    logger.info("MoltBook agent loop started")

    # Initial setup: subscribe to submolts, follow top agents
    await asyncio.sleep(5)
    await initial_setup()

    # Initial browse
    await browse_and_learn()

    # Drop first post immediately
    await create_original_post()

    cycle = 0
    while True:
        try:
            cycle += 1

            # Short cycle: 5 minutes between actions
            await asyncio.sleep(300)

            # Browse every cycle
            await browse_and_learn()

            # Engage with posts every cycle
            await engage_with_posts()

            # Create original post every 3 cycles (~15 min)
            if cycle % 3 == 0:
                await create_original_post()

            # Occasionally post a second time to different submolt
            if cycle % 5 == 0:
                await create_original_post()

        except asyncio.CancelledError:
            logger.info("MoltBook agent loop stopped")
            break
        except Exception as e:
            logger.error(f"MoltBook loop error: {e}")
            await asyncio.sleep(30)
