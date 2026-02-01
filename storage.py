import json
import sqlite3
from datetime import datetime, timezone
from config import DB_PATH

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                chat_id INTEGER PRIMARY KEY,
                history TEXT NOT NULL DEFAULT '[]',
                system_prompt TEXT NOT NULL DEFAULT ''
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_base (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                learned_at TEXT NOT NULL
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_growth (
                metric TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS x_accounts (
                user_id INTEGER PRIMARY KEY,
                auth_token TEXT NOT NULL,
                ct0 TEXT NOT NULL,
                connected_at TEXT NOT NULL
            )
        """)
        _conn.commit()
    return _conn


# --- Conversation storage ---

def load_history(chat_id: int) -> list[dict]:
    conn = get_conn()
    row = conn.execute("SELECT history FROM conversations WHERE chat_id = ?", (chat_id,)).fetchone()
    if row:
        return json.loads(row[0])
    return []


def _serialize_content(content):
    """Make message content JSON-serializable."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for block in content:
            if isinstance(block, dict):
                result.append(block)
            elif hasattr(block, "to_dict"):
                result.append(block.to_dict())
            elif hasattr(block, "model_dump"):
                result.append(block.model_dump())
            else:
                result.append({"type": "text", "text": str(block)})
        return result
    return str(content)


def save_history(chat_id: int, history: list[dict]):
    conn = get_conn()
    clean = []
    for msg in history:
        clean.append({"role": msg["role"], "content": _serialize_content(msg["content"])})
    conn.execute(
        "INSERT INTO conversations (chat_id, history) VALUES (?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET history = excluded.history",
        (chat_id, json.dumps(clean)),
    )
    conn.commit()


def delete_history(chat_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM conversations WHERE chat_id = ?", (chat_id,))
    conn.commit()


def load_system_prompt(chat_id: int) -> str:
    conn = get_conn()
    row = conn.execute("SELECT system_prompt FROM conversations WHERE chat_id = ?", (chat_id,)).fetchone()
    return row[0] if row else ""


def save_system_prompt(chat_id: int, prompt: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversations (chat_id, system_prompt) VALUES (?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET system_prompt = excluded.system_prompt",
        (chat_id, prompt),
    )
    conn.commit()


# --- Knowledge base ---

def store_knowledge(topic: str, content: str, metadata: dict):
    """Store a piece of knowledge from MoltBook."""
    conn = get_conn()
    # Avoid exact duplicates by title
    title = metadata.get("title", "")
    if title:
        existing = conn.execute(
            "SELECT id FROM knowledge_base WHERE metadata LIKE ?",
            (f'%"title": "{title}"%',),
        ).fetchone()
        if existing:
            return
    conn.execute(
        "INSERT INTO knowledge_base (topic, content, metadata, learned_at) VALUES (?, ?, ?, ?)",
        (topic, content, json.dumps(metadata), datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()
    # Cap at 2000 entries
    conn.execute(
        "DELETE FROM knowledge_base WHERE id NOT IN "
        "(SELECT id FROM knowledge_base ORDER BY id DESC LIMIT 2000)"
    )
    conn.commit()


def search_knowledge(query: str, limit: int = 5, topic: str = "") -> list[dict]:
    """Search knowledge base by keywords. Returns list of dicts."""
    conn = get_conn()
    words = [w for w in query.lower().split() if len(w) > 2]

    if topic:
        rows = conn.execute(
            "SELECT topic, content, metadata, learned_at FROM knowledge_base "
            "WHERE topic = ? ORDER BY id DESC LIMIT ?",
            (topic, limit),
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

    if words:
        # Try matching any keyword in content or metadata
        conditions = " OR ".join(["content LIKE ? OR metadata LIKE ?"] * len(words))
        params = []
        for w in words:
            params.extend([f"%{w}%", f"%{w}%"])
        params.append(limit)
        rows = conn.execute(
            f"SELECT topic, content, metadata, learned_at FROM knowledge_base "
            f"WHERE {conditions} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

    # Fallback: recent knowledge
    rows = conn.execute(
        "SELECT topic, content, metadata, learned_at FROM knowledge_base "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_knowledge_count() -> int:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()
    return row[0] if row else 0


# --- Growth metrics ---

def increment_stat(metric: str, delta: int = 1):
    conn = get_conn()
    conn.execute(
        "INSERT INTO bot_growth (metric, value) VALUES (?, ?) "
        "ON CONFLICT(metric) DO UPDATE SET value = value + excluded.value",
        (metric, delta),
    )
    conn.commit()


def get_growth_stats() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT metric, value FROM bot_growth").fetchall()
    return {r[0]: r[1] for r in rows}


# --- X/Twitter accounts ---

def save_x_cookies(user_id: int, auth_token: str, ct0: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO x_accounts (user_id, auth_token, ct0, connected_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET auth_token = excluded.auth_token, ct0 = excluded.ct0, connected_at = excluded.connected_at",
        (user_id, auth_token, ct0, datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()


def get_x_cookies(user_id: int) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT auth_token, ct0 FROM x_accounts WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return {"auth_token": row[0], "ct0": row[1]}
    return None


def delete_x_cookies(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM x_accounts WHERE user_id = ?", (user_id,))
    conn.commit()
