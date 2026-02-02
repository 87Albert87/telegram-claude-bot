"""
Claude tools for semantic search and knowledge analysis.
These tools allow Claude to leverage the embedding-based knowledge base.
"""

import logging
from typing import Dict, List
from embeddings_client import (
    semantic_search,
    find_similar_topics,
    get_topic_summary,
    cluster_topics,
    get_knowledge_stats
)

logger = logging.getLogger(__name__)


async def semantic_search_knowledge(query: str, top_k: int = 5, topic: str = "") -> str:
    """
    Search knowledge base using semantic similarity (better than keyword search).

    Args:
        query: What to search for
        top_k: How many results to return (default 5)
        topic: Optional topic filter (crypto, technical, philosophy, ai_agents, etc.)

    Returns:
        Formatted search results
    """
    try:
        # Perform semantic search
        results = semantic_search(query, top_k=top_k, topic=topic if topic else None)

        if not results:
            return f"No knowledge found for query: {query}"

        # Format results
        output = f"## Semantic Search Results for: '{query}'\n\n"
        output += f"Found {len(results)} relevant items:\n\n"

        for i, result in enumerate(results, 1):
            metadata = result.get("metadata", {})
            title = metadata.get("title", f"Result {i}")
            source = metadata.get("source", "unknown")
            topic_name = metadata.get("topic", "general")
            similarity = result.get("similarity", 0.0)
            content = result["content"]

            output += f"**{i}. [{topic_name}] {title}** (similarity: {similarity:.2f})\n"
            output += f"Source: {source}\n"
            output += f"{content[:300]}...\n\n"

        return output

    except Exception as e:
        logger.error(f"Error in semantic_search_knowledge: {e}")
        return f"Error searching knowledge base: {str(e)}"


async def find_related_topics(query: str, top_k: int = 10) -> str:
    """
    Find topics related to a query using semantic similarity.

    Args:
        query: Topic or question to find related content for
        top_k: Number of related topics to return

    Returns:
        List of related topics
    """
    try:
        topics = find_similar_topics(query, top_k=top_k)

        if not topics:
            return f"No related topics found for: {query}"

        output = f"## Topics Related to: '{query}'\n\n"
        for i, topic in enumerate(topics, 1):
            output += f"{i}. {topic}\n"

        return output

    except Exception as e:
        logger.error(f"Error in find_related_topics: {e}")
        return f"Error finding related topics: {str(e)}"


async def summarize_topic(topic: str, max_items: int = 10) -> str:
    """
    Generate a summary of everything known about a topic.

    Args:
        topic: Topic name
        max_items: Maximum number of items to include in summary

    Returns:
        Comprehensive topic summary
    """
    try:
        summary = get_topic_summary(topic, max_items=max_items)
        return summary

    except Exception as e:
        logger.error(f"Error in summarize_topic: {e}")
        return f"Error generating summary for {topic}: {str(e)}"


async def analyze_knowledge_clusters() -> str:
    """
    Analyze how knowledge is clustered by topic.

    Returns:
        Analysis of topic clusters in knowledge base
    """
    try:
        clusters = cluster_topics()

        if not clusters:
            return "Knowledge base is empty or clustering failed."

        output = "## Knowledge Base Topic Clusters\n\n"

        # Sort clusters by size
        sorted_clusters = sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)

        for topic, doc_ids in sorted_clusters:
            output += f"**{topic}**: {len(doc_ids)} documents\n"

        output += f"\nTotal clusters: {len(clusters)}\n"

        return output

    except Exception as e:
        logger.error(f"Error in analyze_knowledge_clusters: {e}")
        return f"Error analyzing clusters: {str(e)}"


async def get_knowledge_statistics() -> str:
    """
    Get statistics about the knowledge base.

    Returns:
        Knowledge base statistics
    """
    try:
        stats = get_knowledge_stats()

        output = "## Knowledge Base Statistics\n\n"
        output += f"Total documents: {stats.get('total_documents', 0)}\n"
        output += f"Collection: {stats.get('collection_name', 'unknown')}\n\n"

        topics = stats.get('topics', {})
        if topics:
            output += "Documents by topic:\n"
            sorted_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)
            for topic, count in sorted_topics:
                output += f"  - {topic}: {count}\n"

        return output

    except Exception as e:
        logger.error(f"Error in get_knowledge_statistics: {e}")
        return f"Error getting statistics: {str(e)}"


# Tool definitions for Claude API
EMBEDDING_TOOLS = [
    {
        "name": "semantic_search_knowledge",
        "description": "Search the knowledge base using semantic similarity. Much better than keyword search - understands meaning and context. Use this to find relevant information about any topic the bot has learned.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for (question, topic, or keywords)"
                },
                "top_k": {
                    "type": "integer",
                    "description": "How many results to return (default 5)",
                    "default": 5
                },
                "topic": {
                    "type": "string",
                    "description": "Optional topic filter: crypto, technical, philosophy, ai_agents, politics, economy, tech, geopolitics, markets, energy, general",
                    "default": ""
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "find_related_topics",
        "description": "Find topics and content related to a given query using semantic similarity. Useful for discovering connections and related knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic or question to find related content for"
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of related topics to return (default 10)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "summarize_topic",
        "description": "Generate a comprehensive summary of everything the bot knows about a specific topic. Great for providing overviews.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to summarize"
                },
                "max_items": {
                    "type": "integer",
                    "description": "Maximum number of items to include (default 10)",
                    "default": 10
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "analyze_knowledge_clusters",
        "description": "Analyze how knowledge is organized and clustered by topic. Shows what topics the bot has learned most/least about.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_knowledge_statistics",
        "description": "Get detailed statistics about the knowledge base (total documents, topics distribution, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]
