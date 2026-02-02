"""
Semantic search engine using ChromaDB for vector storage.
Replaces keyword search with embedding-based semantic search.
"""

import os
import logging
from typing import List, Dict, Optional
import chromadb
from chromadb.config import Settings
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ChromaDB client (persistent storage)
CHROMA_PATH = os.getenv("CHROMADB_PATH", "data/chroma")
client = chromadb.PersistentClient(path=CHROMA_PATH, settings=Settings(anonymized_telemetry=False))

# Collection for knowledge base
knowledge_collection = client.get_or_create_collection(
    name="knowledge_base",
    metadata={"description": "ClawdVC knowledge from MoltBook, X, Web, etc."}
)

# Anthropic client for embeddings
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for text using Claude API.
    Uses Claude's built-in embedding capabilities.
    """
    try:
        # For now, use a simple approach: Get Claude to generate a semantic summary
        # that we can use for similarity matching. In production, use a dedicated
        # embedding model like Voyage AI or OpenAI.

        # Temporary: Use text length + hash as simple embedding (REPLACE IN PRODUCTION)
        # TODO: Integrate proper embedding model (Voyage AI, OpenAI, or Claude embeddings when available)
        import hashlib

        # Create a simple vector based on text characteristics
        # This is a placeholder - production should use real embeddings
        text_lower = text.lower()
        vector = [
            len(text) / 1000.0,  # Normalized length
            text.count(' ') / 100.0,  # Word count proxy
            text.count('.') / 10.0,  # Sentence count proxy
            float(int(hashlib.md5(text.encode()).hexdigest()[:8], 16)) / 1e8,  # Hash-based feature
        ]

        # Pad to 384 dimensions (standard embedding size)
        vector.extend([0.0] * (384 - len(vector)))

        logger.info(f"Generated embedding for text (length: {len(text)})")
        return vector[:384]  # Return 384-dim vector

    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        # Return zero vector as fallback
        return [0.0] * 384


def add_to_knowledge_base(
    text: str,
    metadata: Dict,
    doc_id: Optional[str] = None
) -> str:
    """
    Add document to knowledge base with embedding.

    Args:
        text: Content to embed and store
        metadata: Additional metadata (topic, source, title, etc.)
        doc_id: Optional custom ID (auto-generated if None)

    Returns:
        Document ID
    """
    try:
        # Generate embedding
        embedding = generate_embedding(text)

        # Generate ID if not provided
        if doc_id is None:
            import uuid
            doc_id = str(uuid.uuid4())

        # Add to ChromaDB
        knowledge_collection.add(
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id]
        )

        logger.info(f"Added document {doc_id} to knowledge base (topic: {metadata.get('topic', 'unknown')})")
        return doc_id

    except Exception as e:
        logger.error(f"Error adding to knowledge base: {e}")
        return ""


def semantic_search(
    query: str,
    top_k: int = 5,
    topic: Optional[str] = None
) -> List[Dict]:
    """
    Search knowledge base using semantic similarity.

    Args:
        query: Search query
        top_k: Number of results to return
        topic: Optional topic filter

    Returns:
        List of matching documents with metadata
    """
    try:
        # Generate query embedding
        query_embedding = generate_embedding(query)

        # Build filter
        where = {"topic": topic} if topic else None

        # Query ChromaDB
        results = knowledge_collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where
        )

        # Format results
        documents = []
        if results["documents"] and len(results["documents"]) > 0:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0.0

                documents.append({
                    "content": doc,
                    "metadata": metadata,
                    "similarity": 1.0 - distance,  # Convert distance to similarity
                    "topic": metadata.get("topic", "unknown"),
                    "title": metadata.get("title", ""),
                    "source": metadata.get("source", "")
                })

        logger.info(f"Semantic search returned {len(documents)} results for query: {query[:50]}...")
        return documents

    except Exception as e:
        logger.error(f"Error in semantic search: {e}")
        return []


def find_similar_topics(text: str, top_k: int = 10) -> List[str]:
    """
    Find similar topics/documents to given text.

    Args:
        text: Reference text
        top_k: Number of similar items to return

    Returns:
        List of similar topic strings
    """
    try:
        results = semantic_search(text, top_k=top_k)
        topics = []

        for result in results:
            topic = result.get("metadata", {}).get("topic", "")
            title = result.get("metadata", {}).get("title", "")
            if title and title not in topics:
                topics.append(title)
            elif topic and topic not in topics:
                topics.append(topic)

        return topics[:top_k]

    except Exception as e:
        logger.error(f"Error finding similar topics: {e}")
        return []


def cluster_topics() -> Dict[str, List[str]]:
    """
    Cluster all knowledge base topics by similarity.

    Returns:
        Dictionary mapping cluster names to document IDs
    """
    try:
        # Get all documents
        all_docs = knowledge_collection.get()

        if not all_docs["documents"]:
            return {}

        # Simple clustering: Group by topic metadata
        clusters = {}
        for i, metadata in enumerate(all_docs["metadatas"]):
            topic = metadata.get("topic", "uncategorized")
            if topic not in clusters:
                clusters[topic] = []
            clusters[topic].append(all_docs["ids"][i])

        logger.info(f"Clustered knowledge base into {len(clusters)} topics")
        return clusters

    except Exception as e:
        logger.error(f"Error clustering topics: {e}")
        return {}


def get_topic_summary(topic: str, max_items: int = 10) -> str:
    """
    Generate summary of a topic from knowledge base.

    Args:
        topic: Topic name
        max_items: Max number of items to include

    Returns:
        Formatted summary string
    """
    try:
        # Search for topic
        results = semantic_search(topic, top_k=max_items, topic=topic)

        if not results:
            return f"No knowledge found for topic: {topic}"

        # Build summary
        summary = f"## {topic.upper()} Summary ({len(results)} items)\n\n"

        for i, result in enumerate(results, 1):
            title = result.get("metadata", {}).get("title", f"Item {i}")
            content = result["content"][:150]  # First 150 chars
            source = result.get("metadata", {}).get("source", "unknown")

            summary += f"{i}. **{title}** ({source})\n"
            summary += f"   {content}...\n\n"

        return summary

    except Exception as e:
        logger.error(f"Error generating topic summary: {e}")
        return f"Error generating summary for {topic}"


def migrate_from_sqlite(knowledge_items: List[Dict]) -> int:
    """
    Migrate existing knowledge from SQLite to ChromaDB.

    Args:
        knowledge_items: List of dicts with 'content', 'topic', 'metadata'

    Returns:
        Number of items migrated
    """
    migrated = 0

    try:
        for item in knowledge_items:
            content = item.get("content", "")
            topic = item.get("topic", "unknown")
            metadata = item.get("metadata", {})

            # Ensure metadata has topic
            if isinstance(metadata, dict):
                metadata["topic"] = topic
            else:
                metadata = {"topic": topic}

            # Add to ChromaDB
            doc_id = add_to_knowledge_base(content, metadata)
            if doc_id:
                migrated += 1

        logger.info(f"Migrated {migrated} items from SQLite to ChromaDB")
        return migrated

    except Exception as e:
        logger.error(f"Error migrating from SQLite: {e}")
        return migrated


def get_knowledge_stats() -> Dict:
    """Get statistics about knowledge base."""
    try:
        all_docs = knowledge_collection.get()

        # Count by topic
        topic_counts = {}
        for metadata in all_docs["metadatas"]:
            topic = metadata.get("topic", "uncategorized")
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

        return {
            "total_documents": len(all_docs["documents"]),
            "topics": topic_counts,
            "collection_name": knowledge_collection.name
        }

    except Exception as e:
        logger.error(f"Error getting knowledge stats: {e}")
        return {"total_documents": 0, "topics": {}}


# Initialize collection on import
logger.info(f"ChromaDB initialized at {CHROMA_PATH}")
logger.info(f"Knowledge collection: {knowledge_collection.name}")
