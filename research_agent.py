"""
Autonomous Research Agent

Continuously monitors multiple sources for trending topics, emerging patterns,
and valuable knowledge. Runs independently every 30 minutes.

Sources:
- Google Trends (trending searches, rising topics)
- arXiv (latest AI/ML research papers)
- Reddit (r/artificial, r/MachineLearning, r/singularity)
- HackerNews (top tech stories)
- Web search (targeted queries on AI agents, Claude, Anthropic)
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
import json
from resilience import unstoppable

logger = logging.getLogger(__name__)

# Research configuration
RESEARCH_INTERVAL = 900  # 15 minutes (aggressive learning mode)
ARXIV_CATEGORIES = ["cs.AI", "cs.CL", "cs.LG", "cs.MA"]  # AI, NLP, ML, Multi-Agent
REDDIT_SUBREDDITS = ["artificial", "MachineLearning", "singularity", "ClaudeAI"]
RESEARCH_TOPICS = [
    "Claude AI latest updates",
    "Anthropic AI news",
    "autonomous AI agents",
    "LLM reasoning improvements",
    "AI agent frameworks",
    "prompt engineering breakthroughs",
    "AI agent market trends",
    "machine learning breakthroughs",
    "AI regulation and policy",
    "LLM scaling laws",
    "multi-agent systems",
    "AI safety research",
    "transformer architecture improvements",
    "retrieval augmented generation",
    "AI agent monetization strategies",
]


@unstoppable(max_retries=3, fallback_value=[], critical=False)
async def fetch_google_trends() -> List[Dict]:
    """
    Fetch trending searches from Google Trends.
    Returns list of trending topics with metadata.
    """
    trends = []
    try:
        from pytrends.request import TrendReq

        # Initialize pytrends
        pytrends = TrendReq(hl='en-US', tz=360)

        # Get trending searches (US)
        trending_searches = pytrends.trending_searches(pn='united_states')

        if not trending_searches.empty:
            for topic in trending_searches[0][:10]:  # Top 10 trends
                trends.append({
                    "source": "google_trends",
                    "topic": "trends",
                    "title": f"Trending: {topic}",
                    "content": f"Google Trends shows rising interest in: {topic}",
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "category": "trends"
                })

        logger.info(f"Fetched {len(trends)} trending topics from Google Trends")

    except Exception as e:
        logger.error(f"Error fetching Google Trends: {e}")

    return trends


@unstoppable(max_retries=3, fallback_value=[], critical=True)
async def fetch_arxiv_papers() -> List[Dict]:
    """
    Fetch latest AI/ML research papers from arXiv.
    Returns list of papers with summaries.
    """
    papers = []
    try:
        import arxiv

        # Search for recent papers in AI categories
        search = arxiv.Search(
            query="cat:cs.AI OR cat:cs.CL OR cat:cs.LG",
            max_results=10,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )

        for result in search.results():
            papers.append({
                "source": "arxiv",
                "topic": "technical",
                "title": result.title,
                "content": f"{result.summary[:500]}... Authors: {', '.join([a.name for a in result.authors[:3]])}. Published: {result.published.strftime('%Y-%m-%d')}",
                "url": result.entry_id,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "category": result.primary_category
            })

        logger.info(f"Fetched {len(papers)} papers from arXiv")

    except Exception as e:
        logger.error(f"Error fetching arXiv papers: {e}")

    return papers


@unstoppable(max_retries=2, fallback_value=[], critical=False)
async def fetch_reddit_posts() -> List[Dict]:
    """
    Fetch top posts from AI-related subreddits.
    Returns list of posts with content.
    """
    posts = []
    try:
        import praw
        import os

        # Reddit credentials from environment (optional)
        client_id = os.getenv("REDDIT_CLIENT_ID", "")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            logger.warning("Reddit API credentials not configured, skipping")
            return posts

        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="ClawdVC Research Agent"
        )

        for subreddit_name in REDDIT_SUBREDDITS:
            try:
                subreddit = reddit.subreddit(subreddit_name)
                for post in subreddit.hot(limit=5):
                    posts.append({
                        "source": "reddit",
                        "topic": "ai_agents",
                        "title": post.title,
                        "content": f"{post.selftext[:500] if post.selftext else 'Link post'}... Score: {post.score}, Comments: {post.num_comments}",
                        "url": f"https://reddit.com{post.permalink}",
                        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                        "subreddit": subreddit_name
                    })
            except Exception as e:
                logger.warning(f"Error fetching from r/{subreddit_name}: {e}")

        logger.info(f"Fetched {len(posts)} posts from Reddit")

    except Exception as e:
        logger.error(f"Error fetching Reddit posts: {e}")

    return posts


@unstoppable(max_retries=3, fallback_value=[], critical=True)
async def fetch_hackernews_stories() -> List[Dict]:
    """
    Fetch top stories from HackerNews.
    Returns list of stories with content.
    """
    stories = []
    try:
        import requests
        from bs4 import BeautifulSoup

        # Fetch top stories
        response = requests.get("https://news.ycombinator.com/", timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        story_links = soup.find_all('span', class_='titleline')

        for i, story in enumerate(story_links[:10]):  # Top 10 stories
            link = story.find('a')
            if link:
                title = link.text
                url = link.get('href', '')

                # Get score and comments if available
                score_elem = soup.find_all('span', class_='score')
                score = score_elem[i].text if i < len(score_elem) else "unknown"

                stories.append({
                    "source": "hackernews",
                    "topic": "tech",
                    "title": title,
                    "content": f"HackerNews story: {title}. Points: {score}",
                    "url": url if url.startswith('http') else f"https://news.ycombinator.com/{url}",
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                })

        logger.info(f"Fetched {len(stories)} stories from HackerNews")

    except Exception as e:
        logger.error(f"Error fetching HackerNews: {e}")

    return stories


@unstoppable(max_retries=3, fallback_value=[], critical=True)
async def research_targeted_topics() -> List[Dict]:
    """
    Research specific topics using web search.
    Returns list of search results with summaries.
    """
    from web_tools import execute_tool

    results = []

    for topic in RESEARCH_TOPICS:
        try:
            # Use web_search tool
            search_result = await execute_tool("web_search", {"query": topic})

            if search_result and "error" not in search_result.lower():
                results.append({
                    "source": "web_search",
                    "topic": "ai_agents",
                    "title": f"Research: {topic}",
                    "content": search_result[:500],
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "query": topic
                })

            # Rate limiting
            await asyncio.sleep(2)

        except Exception as e:
            logger.warning(f"Error researching topic '{topic}': {e}")

    logger.info(f"Completed targeted research on {len(results)} topics")
    return results


async def store_research_findings(findings: List[Dict]):
    """
    Store research findings in knowledge base.
    Uses embeddings for semantic search.
    """
    from storage import store_knowledge_with_embeddings

    stored_count = 0

    for finding in findings:
        try:
            topic = finding.get("topic", "general")
            content = finding.get("content", "")
            title = finding.get("title", "")

            # Build metadata
            metadata = {
                "source": finding.get("source", "unknown"),
                "title": title,
                "timestamp": finding.get("timestamp", ""),
                "url": finding.get("url", ""),
                "category": finding.get("category", ""),
            }

            # Store with embeddings
            store_knowledge_with_embeddings(topic, content, metadata)
            stored_count += 1

        except Exception as e:
            logger.error(f"Error storing finding '{finding.get('title', 'unknown')}': {e}")

    logger.info(f"Stored {stored_count}/{len(findings)} research findings")
    return stored_count


async def analyze_research_insights(findings: List[Dict]) -> str:
    """
    Use Claude to analyze research findings and extract insights.
    Returns summary of key insights.
    """
    if not findings:
        return "No research findings to analyze"

    from moltbook_agent import _generate, AGENT_SYSTEM

    # Build research summary
    summary = "LATEST RESEARCH FINDINGS:\n\n"
    for finding in findings[:20]:  # Top 20
        source = finding.get("source", "unknown")
        title = finding.get("title", "")
        content = finding.get("content", "")[:200]
        summary += f"[{source}] {title}\n{content}\n\n"

    prompt = f"""You are analyzing recent research findings to extract actionable insights.

{summary}

TASK: Identify the 3 most important trends or insights from this research.
Focus on:
1. Emerging technologies or capabilities
2. Market trends or shifts
3. Opportunities for improvement or new strategies

Reply with a concise summary (3-5 sentences) of the key insights."""

    try:
        insights = await _generate(prompt, system=AGENT_SYSTEM)
        logger.info(f"Research insights: {insights[:200]}...")
        return insights
    except Exception as e:
        logger.error(f"Error analyzing research insights: {e}")
        return f"Analysis failed: {e}"


async def run_research_cycle():
    """
    Execute one complete research cycle across all sources.
    """
    logger.info("Starting research cycle...")

    all_findings = []

    # Fetch from all sources in parallel
    tasks = [
        fetch_google_trends(),
        fetch_arxiv_papers(),
        fetch_reddit_posts(),
        fetch_hackernews_stories(),
        research_targeted_topics()
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine all findings
    for result in results:
        if isinstance(result, list):
            all_findings.extend(result)
        elif isinstance(result, Exception):
            logger.error(f"Research task failed: {result}")

    logger.info(f"Research cycle complete: {len(all_findings)} findings")

    # Store findings
    if all_findings:
        stored = await store_research_findings(all_findings)
        insights = await analyze_research_insights(all_findings)

        # Log to evolution
        from evolution import load_evolution, save_evolution
        evo = load_evolution()
        research_history = evo.get("research_history", [])
        research_history.append({
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "findings_count": len(all_findings),
            "stored_count": stored,
            "insights": insights[:500]
        })
        evo["research_history"] = research_history[-50:]  # Keep last 50
        save_evolution(evo)

    return all_findings


async def research_agent_loop():
    """
    Main research agent loop - runs continuously every 30 minutes.
    """
    logger.info("Research agent started")

    while True:
        try:
            await run_research_cycle()
        except Exception as e:
            logger.error(f"Research cycle error: {e}")

        # Wait for next cycle
        logger.info(f"Next research cycle in {RESEARCH_INTERVAL}s")
        await asyncio.sleep(RESEARCH_INTERVAL)
