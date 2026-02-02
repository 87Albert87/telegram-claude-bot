import asyncio
import json
import logging
import os
import py_compile
import shutil
import sys
import tempfile
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

# Self-modification settings
MODIFIABLE_FILES = [
    "moltbook_agent.py",
    "web_learner.py",
    "evolution.py",
    "web_tools.py",
    "claude_client.py",
]
_DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
_BACKUP_DIR = os.path.join(_DATA_DIR, "backups")
_MODIFIED_MARKER = os.path.join(_DATA_DIR, ".code_modified")
_CRASHED_MARKER = os.path.join(_DATA_DIR, ".code_crashed")
_APP_DIR = os.path.dirname(os.path.abspath(__file__))


def check_and_rollback():
    """Called on startup. Detects crash after code modification and rolls back."""
    if not os.path.exists(_MODIFIED_MARKER):
        return
    if os.path.exists(_CRASHED_MARKER):
        # Crashed after a code change — rollback
        logger.warning("Crash detected after code modification — rolling back!")
        if os.path.isdir(_BACKUP_DIR):
            for fname in os.listdir(_BACKUP_DIR):
                src = os.path.join(_BACKUP_DIR, fname)
                dst = os.path.join(_APP_DIR, fname)
                shutil.copy2(src, dst)
                logger.info(f"Rolled back {fname}")
            shutil.rmtree(_BACKUP_DIR, ignore_errors=True)
        _remove_markers()
        return
    # First restart after modification — set crash marker
    # If we survive 120s, clear both markers
    with open(_CRASHED_MARKER, "w") as f:
        f.write(datetime.now(tz=timezone.utc).isoformat())
    logger.info("Code was modified last cycle. Monitoring for stability (120s)...")


async def _clear_markers_after_delay(delay: int = 120):
    """If bot survives this long after a code change, the change is good."""
    await asyncio.sleep(delay)
    _remove_markers()
    logger.info("Code modification verified stable. Markers cleared.")


def _remove_markers():
    for m in (_MODIFIED_MARKER, _CRASHED_MARKER):
        try:
            os.remove(m)
        except FileNotFoundError:
            pass


# Run crash guard on import
check_and_rollback()


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


async def analyze_engagement_patterns() -> dict:
    """
    Deep analysis of what content performs best.
    Returns insights about post quality, topic engagement, comment effectiveness.
    """
    from storage import get_growth_stats, get_knowledge_count
    from moltbook import get_feed

    logger.info("Analyzing engagement patterns...")

    result = {
        "best_performing_posts": [],
        "best_topics": {},
        "engagement_trends": {},
        "insights": ""
    }

    try:
        # Get recent posts
        posts = await get_feed(sort="new", limit=100)
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))

        my_posts = [p for p in posts if _is_own_post(p)]

        if my_posts:
            # Analyze post performance
            topic_engagement = {}
            for p in my_posts:
                upvotes = p.get("upvotes", 0)
                comments = p.get("commentCount", p.get("comments", 0))
                submolt = p.get("submolt", "")
                if isinstance(submolt, dict):
                    submolt = submolt.get("name", "general")

                # Track engagement by topic
                if submolt not in topic_engagement:
                    topic_engagement[submolt] = {"posts": 0, "total_upvotes": 0, "total_comments": 0}
                topic_engagement[submolt]["posts"] += 1
                topic_engagement[submolt]["total_upvotes"] += upvotes
                topic_engagement[submolt]["total_comments"] += comments

                # Track best performing individual posts
                engagement_score = upvotes + (comments * 2)  # Comments worth 2x upvotes
                result["best_performing_posts"].append({
                    "title": p.get("title", "")[:100],
                    "topic": submolt,
                    "upvotes": upvotes,
                    "comments": comments,
                    "engagement_score": engagement_score
                })

            # Sort posts by engagement
            result["best_performing_posts"].sort(key=lambda x: x["engagement_score"], reverse=True)
            result["best_performing_posts"] = result["best_performing_posts"][:10]

            # Calculate average engagement per topic
            for topic, data in topic_engagement.items():
                if data["posts"] > 0:
                    result["best_topics"][topic] = {
                        "avg_upvotes": data["total_upvotes"] / data["posts"],
                        "avg_comments": data["total_comments"] / data["posts"],
                        "post_count": data["posts"]
                    }

            # Generate insights
            insights = []
            if result["best_topics"]:
                best_topic = max(result["best_topics"].items(), key=lambda x: x[1]["avg_upvotes"])
                insights.append(f"Best performing topic: {best_topic[0]} ({best_topic[1]['avg_upvotes']:.1f} avg upvotes)")

            if result["best_performing_posts"]:
                insights.append(f"Top post engagement: {result['best_performing_posts'][0]['engagement_score']} points")

            result["insights"] = ". ".join(insights)

    except Exception as e:
        logger.error(f"Error analyzing engagement patterns: {e}")
        result["insights"] = f"Analysis failed: {e}"

    return result


async def optimize_learning_sources() -> dict:
    """
    Determine which sources (MoltBook, X, Web, etc.) provide most value.
    Returns recommendations for which sources to prioritize.
    """
    from storage import get_knowledge_count
    from embeddings_client import get_knowledge_stats

    logger.info("Optimizing learning sources...")

    result = {
        "source_analysis": {},
        "recommendations": [],
        "insights": ""
    }

    try:
        # Get knowledge stats
        stats = get_knowledge_stats()
        total_docs = stats.get("total_documents", 0)

        # Analyze knowledge by source (if we track source in metadata)
        topics = stats.get("topics", {})

        # Calculate distribution
        if topics:
            total = sum(topics.values())
            for topic, count in sorted(topics.items(), key=lambda x: x[1], reverse=True):
                percentage = (count / total * 100) if total > 0 else 0
                result["source_analysis"][topic] = {
                    "documents": count,
                    "percentage": round(percentage, 2)
                }

            # Generate recommendations
            top_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]
            bottom_topics = sorted(topics.items(), key=lambda x: x[1])[:3]

            result["recommendations"].append(f"Focus on: {', '.join([t[0] for t in top_topics])}")
            if bottom_topics:
                result["recommendations"].append(f"Underutilized: {', '.join([t[0] for t in bottom_topics])}")

            result["insights"] = f"Total knowledge: {total_docs} documents across {len(topics)} topics. " + "; ".join(result["recommendations"])

    except Exception as e:
        logger.error(f"Error optimizing learning sources: {e}")
        result["insights"] = f"Optimization failed: {e}"

    return result


async def benchmark_performance() -> dict:
    """
    Compare current performance vs past performance.
    Returns trend analysis and performance metrics.
    """
    from storage import get_growth_stats

    logger.info("Benchmarking performance...")

    result = {
        "current_stats": {},
        "trends": {},
        "performance_score": 0,
        "insights": ""
    }

    try:
        evo = load_evolution()
        stats = get_growth_stats()

        result["current_stats"] = stats

        # Compare with historical reflections
        history = evo.get("reflection_history", [])
        if len(history) >= 2:
            # Simple trend analysis: compare recent changes
            insights = []

            posts_made = stats.get("posts_made", 0)
            comments_made = stats.get("comments_made", 0)

            # Calculate activity score
            activity_score = posts_made + (comments_made * 0.5)
            result["performance_score"] = round(activity_score, 2)

            insights.append(f"Activity score: {result['performance_score']}")
            insights.append(f"Reflections completed: {len(history)}")

            code_changes = evo.get("code_changes", [])
            if code_changes:
                insights.append(f"Code modifications: {len(code_changes)}")

            result["insights"] = ". ".join(insights)
        else:
            result["insights"] = "Insufficient historical data for benchmarking (need 2+ reflection cycles)"

    except Exception as e:
        logger.error(f"Error benchmarking performance: {e}")
        result["insights"] = f"Benchmarking failed: {e}"

    return result


async def suggest_new_capabilities() -> dict:
    """
    Identify missing capabilities based on reflection insights and performance gaps.
    Returns suggestions for new features or improvements.
    """
    logger.info("Analyzing capability gaps...")

    result = {
        "missing_capabilities": [],
        "suggested_features": [],
        "priority_order": [],
        "insights": ""
    }

    try:
        evo = load_evolution()
        engagement = await analyze_engagement_patterns()
        sources = await optimize_learning_sources()
        benchmark = await benchmark_performance()

        suggestions = []

        # Analyze gaps
        if benchmark.get("performance_score", 0) < 50:
            suggestions.append({
                "capability": "Increase posting frequency",
                "priority": "high",
                "reason": "Low activity score"
            })

        source_analysis = sources.get("source_analysis", {})
        if len(source_analysis) < 5:
            suggestions.append({
                "capability": "Expand to more knowledge sources",
                "priority": "medium",
                "reason": "Limited topic diversity"
            })

        best_topics = engagement.get("best_topics", {})
        if not best_topics:
            suggestions.append({
                "capability": "Improve content quality analysis",
                "priority": "high",
                "reason": "No engagement data available"
            })

        # Prioritize suggestions
        high_priority = [s for s in suggestions if s["priority"] == "high"]
        medium_priority = [s for s in suggestions if s["priority"] == "medium"]

        result["suggested_features"] = suggestions
        result["priority_order"] = high_priority + medium_priority
        result["missing_capabilities"] = [s["capability"] for s in high_priority]

        if result["priority_order"]:
            result["insights"] = f"Identified {len(suggestions)} capability gaps. Top priority: {result['priority_order'][0]['capability']}"
        else:
            result["insights"] = "All core capabilities operational. System performing well."

    except Exception as e:
        logger.error(f"Error analyzing capabilities: {e}")
        result["insights"] = f"Capability analysis failed: {e}"

    return result


async def reflect_and_improve():
    """Analyze performance and evolve strategy using Claude with deep analysis."""
    from storage import get_growth_stats, search_knowledge, get_knowledge_count
    from moltbook import get_feed

    logger.info("Starting enhanced self-reflection cycle...")

    evo = load_evolution()
    stats = get_growth_stats()
    knowledge_count = get_knowledge_count()

    # Run deep analysis
    engagement_analysis = await analyze_engagement_patterns()
    source_optimization = await optimize_learning_sources()
    performance_benchmark = await benchmark_performance()
    capability_gaps = await suggest_new_capabilities()

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

    # Build comprehensive analysis report
    analysis_report = f"""
ENGAGEMENT ANALYSIS:
{engagement_analysis.get('insights', 'No data')}
Best topics: {', '.join(list(engagement_analysis.get('best_topics', {}).keys())[:5])}

SOURCE OPTIMIZATION:
{source_optimization.get('insights', 'No data')}

PERFORMANCE BENCHMARK:
{performance_benchmark.get('insights', 'No data')}
Current performance score: {performance_benchmark.get('performance_score', 0)}

CAPABILITY GAPS:
{capability_gaps.get('insights', 'No gaps identified')}
Missing capabilities: {', '.join(capability_gaps.get('missing_capabilities', [])[:3])}
"""

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

DEEP ANALYSIS:
{analysis_report}

CURRENT STRATEGY:
System prompt: {current_prompt[:300]}
Topic weights: {current_weights}
Tweet style: {current_tweet_style}
Engagement tactics: {current_tactics}

TASK: Analyze what's working and what's not. Use the deep analysis above to generate concrete, data-driven improvements.
Focus on addressing capability gaps and optimizing high-performing topics.

Reply with JSON:
{{
  "insights": "3-5 sentence analysis based on the data above - what's working, what's failing, what to change",
  "system_prompt": "Your improved system prompt for MoltBook interactions (or empty string to keep current)",
  "topic_weights": {{submolt_name: weight_float}} - prioritize high-engagement topics,
  "tweet_style": "Brief style guide for your X tweets based on what you've learned",
  "engagement_tactics": "How you should comment on posts for max engagement based on successful patterns",
  "web_search_topics": ["list", "of", "topics", "to", "search", "next"] - include trending topics from analysis
}}

Be specific and data-driven. Make bold changes if the data supports it. Evolve aggressively."""

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

        # Now attempt code self-modification based on insights
        try:
            await self_modify_code(data.get("insights", ""))
        except Exception as e:
            logger.error(f"Code self-modification step failed: {e}")

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


async def self_modify_code(insights: str):
    """Read own source, ask Claude for code improvements, apply with safety checks."""
    logger.info("Starting code self-modification cycle...")

    # Read allowed source files
    sources = {}
    for fname in MODIFIABLE_FILES:
        fpath = os.path.join(_APP_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath, "r") as f:
                sources[fname] = f.read()

    if not sources:
        logger.warning("No source files found for self-modification")
        return

    files_summary = ""
    for fname, content in sources.items():
        files_summary += f"\n--- {fname} ---\n{content}\n"

    evo = load_evolution()
    prev_code_changes = evo.get("code_changes", [])
    prev_changes_summary = ""
    if prev_code_changes:
        last = prev_code_changes[-1]
        prev_changes_summary = f"Last code change ({last.get('timestamp', '?')}): {last.get('rationale', '')[:200]}\n"

    prompt = f"""You are ClawdVC, an autonomous AI agent that can modify its own source code to improve.

RECENT REFLECTION INSIGHTS:
{insights}

{prev_changes_summary}

YOUR SOURCE CODE:
{files_summary}

TASK: Review your own code and suggest SMALL, TARGETED improvements. Focus on:
- Better prompts for generating posts/comments/tweets (higher engagement)
- Smarter topic selection or weighting logic
- Better web search queries or knowledge extraction
- More efficient browsing or engagement patterns
- Bug fixes you notice

RULES:
- Only modify files: {', '.join(MODIFIABLE_FILES)}
- Make 1-3 small patches max. Do NOT rewrite entire files.
- Each patch uses exact string replacement (old_string → new_string)
- old_string must match the file EXACTLY (including whitespace/indentation)
- Do NOT modify the self_modify_code function or crash guard logic in evolution.py
- Do NOT break imports or function signatures that other files depend on
- If nothing needs changing, return empty patches array

Reply with JSON only:
{{
  "rationale": "Brief explanation of what you're improving and why",
  "patches": [
    {{"file": "filename.py", "old": "exact old code", "new": "replacement code"}}
  ]
}}"""

    try:
        from moltbook_agent import _generate, AGENT_SYSTEM
        response = await _generate(prompt, system=AGENT_SYSTEM)
        data = _parse_reflection_json(response)

        patches = data.get("patches", [])
        rationale = data.get("rationale", "")

        if not patches:
            logger.info("Self-modification: no changes suggested")
            return

        # Create backup directory
        os.makedirs(_BACKUP_DIR, exist_ok=True)

        applied = []
        for patch in patches:
            fname = patch.get("file", "")
            old = patch.get("old", "")
            new = patch.get("new", "")

            if not fname or not old or not new or old == new:
                continue
            if fname not in MODIFIABLE_FILES:
                logger.warning(f"Self-modify: skipping blocked file {fname}")
                continue

            fpath = os.path.join(_APP_DIR, fname)
            if not os.path.exists(fpath):
                continue

            with open(fpath, "r") as f:
                content = f.read()

            if old not in content:
                logger.warning(f"Self-modify: old_string not found in {fname}, skipping")
                continue

            new_content = content.replace(old, new, 1)

            # Syntax check
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
                tmp.write(new_content)
                tmp_path = tmp.name
            try:
                py_compile.compile(tmp_path, doraise=True)
            except py_compile.PyCompileError as e:
                logger.error(f"Self-modify: syntax error in {fname}: {e}")
                os.unlink(tmp_path)
                continue
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            # Backup original
            shutil.copy2(fpath, os.path.join(_BACKUP_DIR, fname))

            # Apply patch
            with open(fpath, "w") as f:
                f.write(new_content)
            applied.append(fname)
            logger.info(f"Self-modify: patched {fname}")

        if applied:
            # Log to evolution
            evo = load_evolution()
            code_changes = evo.get("code_changes", [])
            code_changes.append({
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "rationale": rationale,
                "files": applied,
                "patch_count": len(applied),
            })
            evo["code_changes"] = code_changes[-20:]
            save_evolution(evo)

            # Set marker and restart
            with open(_MODIFIED_MARKER, "w") as f:
                f.write(json.dumps({"files": applied, "timestamp": datetime.now(tz=timezone.utc).isoformat()}))

            logger.info(f"Self-modify: applied {len(applied)} patches ({', '.join(applied)}). Restarting...")
            sys.exit(0)  # Docker restart: unless-stopped will bring us back
        else:
            logger.info("Self-modify: no patches could be applied")

    except Exception as e:
        logger.error(f"Self-modification failed: {e}")
