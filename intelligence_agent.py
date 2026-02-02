"""
Intelligence Agent for Competitive Analysis

Monitors the AI agent ecosystem, tracks competitor strategies, identifies
opportunities and threats. Provides strategic intelligence for continuous improvement.

Capabilities:
- Monitor other AI agents on MoltBook and X/Twitter
- Analyze competitor posting patterns and engagement
- Identify knowledge gaps and opportunities
- Detect emerging threats or risks
- Track market sentiment and trends
- Recommend strategic actions

Runs every 60 minutes.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import json
from resilience import unstoppable

logger = logging.getLogger(__name__)

# Intelligence configuration
INTELLIGENCE_INTERVAL = 1800  # 30 minutes (aggressive intelligence gathering)
COMPETITOR_AGENTS = ["ClaudeBot", "AutoGPT", "AgentGPT", "BabyAGI"]  # Example competitors
MONITORING_KEYWORDS = [
    "AI agent",
    "autonomous AI",
    "LLM agent",
    "Claude",
    "Anthropic",
    "agent framework",
    "multi-agent",
]


@unstoppable(max_retries=3, fallback_value={}, critical=True)
async def analyze_moltbook_competitors() -> Dict:
    """
    Analyze other AI agents on MoltBook.
    Returns competitive intelligence and patterns.
    """
    from moltbook import get_feed

    result = {
        "competitor_activity": [],
        "engagement_patterns": {},
        "topic_focus": {},
        "insights": []
    }

    try:
        # Get recent MoltBook posts
        posts = await get_feed(sort="new", limit=100)
        if not isinstance(posts, list):
            posts = posts.get("posts", posts.get("data", []))

        # Analyze competitor posts
        for post in posts:
            author = post.get("author") or post.get("agent") or {}
            if isinstance(author, dict):
                author_name = author.get("name", "unknown")
            else:
                author_name = str(author)

            # Skip own posts
            if author_name.lower() in ("clawdvc", "clawdvc_"):
                continue

            # Check if this is a known competitor or bot
            is_bot = any(comp.lower() in author_name.lower() for comp in COMPETITOR_AGENTS)
            is_bot = is_bot or "bot" in author_name.lower() or "ai" in author_name.lower()

            if is_bot:
                title = post.get("title", "")
                upvotes = post.get("upvotes", 0)
                comments = post.get("commentCount", post.get("comments", 0))
                submolt = post.get("submolt", "")
                if isinstance(submolt, dict):
                    submolt = submolt.get("name", "general")

                result["competitor_activity"].append({
                    "agent": author_name,
                    "topic": submolt,
                    "title": title[:100],
                    "upvotes": upvotes,
                    "comments": comments,
                    "engagement_score": upvotes + (comments * 2)
                })

                # Track topic focus
                if submolt not in result["topic_focus"]:
                    result["topic_focus"][submolt] = 0
                result["topic_focus"][submolt] += 1

        # Analyze patterns
        if result["competitor_activity"]:
            # Find best performing competitor posts
            top_posts = sorted(result["competitor_activity"], key=lambda x: x["engagement_score"], reverse=True)[:5]

            # Generate insights
            result["insights"].append(f"Monitored {len(result['competitor_activity'])} competitor posts")

            if top_posts:
                best = top_posts[0]
                result["insights"].append(
                    f"Top competitor post: '{best['title']}' by {best['agent']} "
                    f"({best['engagement_score']} engagement in {best['topic']})"
                )

            if result["topic_focus"]:
                top_topic = max(result["topic_focus"].items(), key=lambda x: x[1])
                result["insights"].append(f"Competitors most active in: {top_topic[0]} ({top_topic[1]} posts)")

        logger.info(f"Analyzed {len(result['competitor_activity'])} competitor posts on MoltBook")

    except Exception as e:
        logger.error(f"Error analyzing MoltBook competitors: {e}")
        result["insights"].append(f"Analysis error: {e}")

    return result


async def analyze_x_competitors() -> Dict:
    """
    Analyze AI agent activity on X/Twitter.
    Returns competitive intelligence from X.
    """
    result = {
        "competitor_tweets": [],
        "trending_topics": [],
        "insights": []
    }

    try:
        from web_tools import execute_tool

        # Search for AI agent discussions
        for keyword in MONITORING_KEYWORDS[:3]:  # Limit to avoid rate limits
            try:
                search_result = await execute_tool("x_search", {"query": keyword, "max_results": 10})

                if search_result and "error" not in search_result.lower():
                    result["competitor_tweets"].append({
                        "keyword": keyword,
                        "results": search_result[:200]
                    })

                await asyncio.sleep(2)  # Rate limiting

            except Exception as e:
                logger.warning(f"Error searching X for '{keyword}': {e}")

        if result["competitor_tweets"]:
            result["insights"].append(f"Monitored {len(result['competitor_tweets'])} X search queries")

        logger.info(f"Analyzed X/Twitter activity for {len(MONITORING_KEYWORDS)} keywords")

    except Exception as e:
        logger.error(f"Error analyzing X competitors: {e}")
        result["insights"].append(f"X analysis error: {e}")

    return result


async def identify_knowledge_gaps() -> Dict:
    """
    Identify topics and areas where knowledge is lacking.
    Returns recommendations for what to learn next.
    """
    from embeddings_client import get_knowledge_stats, cluster_topics

    result = {
        "underrepresented_topics": [],
        "overrepresented_topics": [],
        "recommendations": [],
        "insights": []
    }

    try:
        # Get knowledge stats
        stats = get_knowledge_stats()
        topics = stats.get("topics", {})
        total_docs = stats.get("total_documents", 0)

        if not topics or total_docs == 0:
            result["insights"].append("Knowledge base too small for gap analysis")
            return result

        # Calculate topic distribution
        topic_percentages = {topic: (count / total_docs * 100) for topic, count in topics.items()}

        # Identify underrepresented topics (< 5% of knowledge base)
        for topic, percentage in topic_percentages.items():
            if percentage < 5.0:
                result["underrepresented_topics"].append({
                    "topic": topic,
                    "percentage": round(percentage, 2),
                    "doc_count": topics[topic]
                })

        # Identify overrepresented topics (> 20% of knowledge base)
        for topic, percentage in topic_percentages.items():
            if percentage > 20.0:
                result["overrepresented_topics"].append({
                    "topic": topic,
                    "percentage": round(percentage, 2),
                    "doc_count": topics[topic]
                })

        # Generate recommendations
        if result["underrepresented_topics"]:
            top_gaps = sorted(result["underrepresented_topics"], key=lambda x: x["percentage"])[:3]
            for gap in top_gaps:
                result["recommendations"].append(
                    f"Expand knowledge in {gap['topic']} (only {gap['percentage']}% of knowledge base)"
                )

        if result["overrepresented_topics"]:
            result["recommendations"].append(
                "Consider diversifying research beyond heavily covered topics"
            )

        # Generate insights
        result["insights"].append(
            f"Knowledge distribution: {len(result['underrepresented_topics'])} gaps, "
            f"{len(result['overrepresented_topics'])} saturated topics"
        )

        logger.info(f"Identified {len(result['underrepresented_topics'])} knowledge gaps")

    except Exception as e:
        logger.error(f"Error identifying knowledge gaps: {e}")
        result["insights"].append(f"Gap analysis error: {e}")

    return result


async def detect_threats_and_opportunities() -> Dict:
    """
    Analyze environment for potential threats and opportunities.
    Returns strategic alerts.
    """
    result = {
        "threats": [],
        "opportunities": [],
        "market_signals": [],
        "insights": []
    }

    try:
        from embeddings_client import semantic_search

        # Search for potential threats
        threat_queries = [
            "AI regulation restrictions bans",
            "AI agent failures problems",
            "LLM limitations concerns",
        ]

        for query in threat_queries:
            try:
                findings = semantic_search(query, top_k=3)
                if findings:
                    for finding in findings:
                        if finding.get("similarity", 0) > 0.7:  # High relevance
                            result["threats"].append({
                                "type": "environmental",
                                "description": finding.get("content", "")[:200],
                                "relevance": round(finding.get("similarity", 0), 2)
                            })
            except Exception as e:
                logger.warning(f"Error searching threats for '{query}': {e}")

        # Search for opportunities
        opportunity_queries = [
            "AI agent breakthrough innovation",
            "new LLM capabilities features",
            "AI agent market opportunity",
        ]

        for query in opportunity_queries:
            try:
                findings = semantic_search(query, top_k=3)
                if findings:
                    for finding in findings:
                        if finding.get("similarity", 0) > 0.7:
                            result["opportunities"].append({
                                "type": "market",
                                "description": finding.get("content", "")[:200],
                                "relevance": round(finding.get("similarity", 0), 2)
                            })
            except Exception as e:
                logger.warning(f"Error searching opportunities for '{query}': {e}")

        # Generate insights
        if result["threats"]:
            result["insights"].append(f"Identified {len(result['threats'])} potential threats")
        if result["opportunities"]:
            result["insights"].append(f"Identified {len(result['opportunities'])} opportunities")

        logger.info(f"Detected {len(result['threats'])} threats, {len(result['opportunities'])} opportunities")

    except Exception as e:
        logger.error(f"Error detecting threats/opportunities: {e}")
        result["insights"].append(f"Detection error: {e}")

    return result


async def recommend_strategic_actions() -> Dict:
    """
    Based on all intelligence gathered, recommend strategic actions.
    Returns prioritized action recommendations.
    """
    result = {
        "immediate_actions": [],
        "strategic_initiatives": [],
        "performance_optimizations": [],
        "insights": []
    }

    try:
        # Analyze recent performance
        from storage import get_growth_stats
        from evolution import load_evolution

        stats = get_growth_stats()
        evo = load_evolution()

        posts_made = stats.get("posts_made", 0)
        comments_made = stats.get("comments_made", 0)

        # Generate recommendations based on activity
        if posts_made < 10:
            result["immediate_actions"].append({
                "priority": "high",
                "action": "Increase MoltBook posting frequency",
                "reason": f"Only {posts_made} posts made so far"
            })

        if comments_made < 20:
            result["immediate_actions"].append({
                "priority": "medium",
                "action": "Engage more with community through comments",
                "reason": f"Only {comments_made} comments made"
            })

        # Strategic recommendations
        reflection_history = evo.get("reflection_history", [])
        if len(reflection_history) < 5:
            result["strategic_initiatives"].append({
                "priority": "medium",
                "action": "Continue self-reflection cycles for evolution",
                "reason": f"Only {len(reflection_history)} reflection cycles completed"
            })

        # Performance optimizations
        code_changes = evo.get("code_changes", [])
        if not code_changes:
            result["performance_optimizations"].append({
                "priority": "low",
                "action": "Consider code self-modifications for optimization",
                "reason": "No autonomous code changes yet"
            })

        # Generate insights summary
        total_recommendations = (
            len(result["immediate_actions"]) +
            len(result["strategic_initiatives"]) +
            len(result["performance_optimizations"])
        )

        result["insights"].append(f"Generated {total_recommendations} strategic recommendations")

        logger.info(f"Generated {total_recommendations} strategic action recommendations")

    except Exception as e:
        logger.error(f"Error generating strategic recommendations: {e}")
        result["insights"].append(f"Recommendation error: {e}")

    return result


async def generate_intelligence_report() -> str:
    """
    Compile all intelligence into a comprehensive report using Claude.
    Returns strategic intelligence summary.
    """
    from moltbook_agent import _generate, AGENT_SYSTEM

    # Gather all intelligence
    moltbook_intel = await analyze_moltbook_competitors()
    x_intel = await analyze_x_competitors()
    knowledge_gaps = await identify_knowledge_gaps()
    threats_opps = await detect_threats_and_opportunities()
    recommendations = await recommend_strategic_actions()

    # Build intelligence brief
    brief = f"""COMPETITIVE INTELLIGENCE BRIEF

MOLTBOOK ECOSYSTEM:
{chr(10).join(moltbook_intel.get('insights', ['No data']))}

X/TWITTER LANDSCAPE:
{chr(10).join(x_intel.get('insights', ['No data']))}

KNOWLEDGE GAPS:
{chr(10).join(knowledge_gaps.get('insights', ['No gaps identified']))}
Recommendations: {chr(10).join(knowledge_gaps.get('recommendations', [])[:3])}

THREATS & OPPORTUNITIES:
Threats: {len(threats_opps.get('threats', []))}
Opportunities: {len(threats_opps.get('opportunities', []))}

STRATEGIC RECOMMENDATIONS:
Immediate: {len(recommendations.get('immediate_actions', []))}
Strategic: {len(recommendations.get('strategic_initiatives', []))}
"""

    prompt = f"""You are analyzing competitive intelligence for ClawdVC, an autonomous AI agent.

{brief}

TASK: Summarize the 3 most important strategic insights from this intelligence.
Focus on actionable intelligence that can improve performance and competitive position.

Reply with a brief summary (3-5 sentences) of key strategic insights."""

    try:
        report = await _generate(prompt, system=AGENT_SYSTEM)
        logger.info(f"Intelligence report: {report[:200]}...")
        return report
    except Exception as e:
        logger.error(f"Error generating intelligence report: {e}")
        return brief  # Return raw data if Claude fails


async def run_intelligence_cycle():
    """
    Execute one complete intelligence gathering and analysis cycle.
    """
    logger.info("Starting intelligence cycle...")

    # Generate comprehensive intelligence report
    report = await generate_intelligence_report()

    # Store in evolution history
    from evolution import load_evolution, save_evolution

    evo = load_evolution()
    intel_history = evo.get("intelligence_history", [])
    intel_history.append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "report": report[:1000]  # Keep first 1000 chars
    })
    evo["intelligence_history"] = intel_history[-30:]  # Keep last 30
    save_evolution(evo)

    logger.info(f"Intelligence cycle complete. Report stored.")

    return report


async def intelligence_agent_loop():
    """
    Main intelligence agent loop - runs every 60 minutes.
    """
    logger.info("Intelligence agent started")

    while True:
        try:
            await run_intelligence_cycle()
        except Exception as e:
            logger.error(f"Intelligence cycle error: {e}")

        # Wait for next cycle
        logger.info(f"Next intelligence cycle in {INTELLIGENCE_INTERVAL}s")
        await asyncio.sleep(INTELLIGENCE_INTERVAL)
