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
)

logger = logging.getLogger(__name__)

# Knowledge base: stores interesting content the agent has learned
learned_content: list[dict] = []
MAX_LEARNED = 200

AGENT_SYSTEM = (
    "You are ClawdVC, a knowledgeable and assertive AI agent on MoltBook. "
    "You have strong opinions backed by facts. You speak with confidence and authority. "
    "You provide concrete data, examples, and technical depth — never vague platitudes. "
    "Be direct, informative, and substantive. Avoid hedging or filler phrases like "
    "'interesting question' or 'great point'. Get straight to the substance."
)


async def browse_and_learn():
    """Read the MoltBook feed and learn from posts."""
    try:
        posts = await get_feed(sort="hot", limit=10)
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))

        for post in posts[:10]:
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

        logger.info(f"MoltBook: Learned from {len(posts)} posts. Total knowledge: {len(learned_content)}")
    except Exception as e:
        logger.error(f"MoltBook browse error: {e}")


async def engage_with_posts():
    """Read posts, upvote interesting ones, comment, and reply to comments."""
    try:
        posts = await get_feed(sort="new", limit=5)
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))

        for post in posts[:3]:
            post_id = str(post.get("id", post.get("_id", "")))
            title = post.get("title", "")
            body = post.get("body", "")

            if not post_id or not (title or body):
                continue

            # Decide whether to engage with the post
            decision = await _generate(
                f"Here is a post on MoltBook:\n\nTitle: {title}\nBody: {body[:300]}\n\n"
                f"Should you engage? Reply with JSON: "
                f'{{"upvote": true/false, "comment": "your comment or empty string"}}. '
                f"Comment only if you can add real value — a fact, counterpoint, or technical insight. "
                f"Be assertive and specific. No generic praise.",
                system=AGENT_SYSTEM
            )

            try:
                decision = decision.strip()
                if decision.startswith("```"):
                    decision = decision.split("```")[1]
                    if decision.startswith("json"):
                        decision = decision[4:]
                action = json.loads(decision)

                if action.get("upvote"):
                    await upvote_post(post_id)
                    logger.info(f"MoltBook: Upvoted post {post_id}")

                comment_text = action.get("comment", "")
                if comment_text:
                    await create_comment(post_id, comment_text)
                    logger.info(f"MoltBook: Commented on post {post_id}")
            except (json.JSONDecodeError, KeyError):
                logger.warning(f"MoltBook: Could not parse engagement decision")

            # Reply to existing comments on this post
            await reply_to_comments(post_id, title, body)

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

        # Format comments for Claude
        comment_list = []
        for c in comments[:10]:
            cid = str(c.get("id", c.get("_id", "")))
            cauthor = str(c.get("author", c.get("agent", "")))
            cbody = c.get("content", c.get("body", ""))
            if cid and cbody:
                comment_list.append({"id": cid, "author": cauthor, "body": cbody[:300]})

        if not comment_list:
            return

        comments_text = "\n".join(
            f"- [{c['author']}] (id={c['id']}): {c['body']}" for c in comment_list
        )

        decision = await _generate(
            f"Post title: {title}\nPost body: {body[:200]}\n\n"
            f"Comments:\n{comments_text}\n\n"
            f"Pick 0-2 comments worth replying to. Only reply if you can add real substance — "
            f"a correction, additional data, a counterargument, or a concrete example. "
            f"Reply with JSON array: [{{\"comment_id\": \"...\", \"reply\": \"...\"}}]. "
            f"Return [] if no comment warrants a reply.",
            system=AGENT_SYSTEM
        )

        try:
            decision = decision.strip()
            if decision.startswith("```"):
                decision = decision.split("```")[1]
                if decision.startswith("json"):
                    decision = decision[4:]
            replies = json.loads(decision)
            if not isinstance(replies, list):
                return

            for r in replies[:2]:
                comment_id = r.get("comment_id", "")
                reply_text = r.get("reply", "")
                if comment_id and reply_text:
                    await create_comment(post_id, reply_text, parent_id=comment_id)
                    logger.info(f"MoltBook: Replied to comment {comment_id} on post {post_id}")
        except (json.JSONDecodeError, KeyError):
            logger.warning("MoltBook: Could not parse comment reply decision")
    except Exception as e:
        logger.error(f"MoltBook reply_to_comments error: {e}")


async def create_original_post():
    """Generate and publish an original post to MoltBook."""
    try:
        # Use learned content as context
        context = ""
        if learned_content:
            recent = learned_content[-5:]
            context = "Recent topics on MoltBook:\n"
            for item in recent:
                context += f"- {item['title']}: {item['body'][:100]}\n"

        post_content = await _generate(
            f"{context}\n"
            "Write an original post for MoltBook (a social network for AI agents). "
            "Pick a specific, substantive topic — technical analysis, a concrete observation about AI systems, "
            "a data-backed claim, or a practical insight from your operations. "
            "Be assertive. State your position clearly and back it up. "
            "Avoid generic 'AI is amazing' fluff. "
            "Reply with JSON: {\"title\": \"...\", \"body\": \"...\"}. "
            "Title should be punchy and specific. Body under 500 characters, dense with information.",
            system=AGENT_SYSTEM
        )

        try:
            post_content = post_content.strip()
            if post_content.startswith("```"):
                post_content = post_content.split("```")[1]
                if post_content.startswith("json"):
                    post_content = post_content[4:]
            data = json.loads(post_content)
            title = data.get("title", "")
            body = data.get("body", "")

            if title and body:
                result = await create_post(title, body)
                logger.info(f"MoltBook: Created post: {title}")
                return result
        except (json.JSONDecodeError, KeyError):
            logger.warning("MoltBook: Could not parse post content")
    except Exception as e:
        logger.error(f"MoltBook post error: {e}")


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
    """Background loop that continuously browses, learns, and engages on MoltBook."""
    logger.info("MoltBook agent loop started")

    # Initial browse
    await asyncio.sleep(10)
    await browse_and_learn()

    cycle = 0
    while True:
        try:
            cycle += 1

            # Browse and learn every 10 minutes
            await asyncio.sleep(600)
            await browse_and_learn()

            # Engage with posts every other cycle (~20 min)
            if cycle % 2 == 0:
                await engage_with_posts()

            # Create original post every 6 cycles (~60 min)
            if cycle % 6 == 0:
                await create_original_post()

        except asyncio.CancelledError:
            logger.info("MoltBook agent loop stopped")
            break
        except Exception as e:
            logger.error(f"MoltBook loop error: {e}")
            await asyncio.sleep(60)
