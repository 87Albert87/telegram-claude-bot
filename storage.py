import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict
from config import DB_PATH

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
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
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                first_seen TEXT NOT NULL,
                is_blocked INTEGER NOT NULL DEFAULT 0
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                payment_method TEXT NOT NULL,
                started_at TEXT NOT NULL,
                expires_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, status)")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                payment_id TEXT,
                plan TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
        """)
        # DeFi Trading tables
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chain TEXT NOT NULL,
                encrypted_key TEXT NOT NULL,
                address TEXT NOT NULL,
                label TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(user_id, chain)
            )
        """)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chain TEXT NOT NULL,
                token_in TEXT NOT NULL,
                token_in_symbol TEXT DEFAULT '',
                token_out TEXT NOT NULL,
                token_out_symbol TEXT DEFAULT '',
                amount_in TEXT NOT NULL,
                amount_out TEXT DEFAULT '',
                amount_usd TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                tx_hash TEXT DEFAULT '',
                slippage_bps INTEGER DEFAULT 0,
                risk_score INTEGER DEFAULT 0,
                safety_report TEXT DEFAULT '{}',
                goal_id INTEGER DEFAULT NULL,
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                executed_at TEXT DEFAULT '',
                FOREIGN KEY (goal_id) REFERENCES trading_goals(id)
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id, status)")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS trading_goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                target_amount REAL NOT NULL,
                current_progress REAL DEFAULT 0.0,
                strategy TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'active',
                chain TEXT DEFAULT 'base',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_goals_user ON trading_goals(user_id, status)")
        _conn.commit()
    return _conn


# --- Conversation storage ---

def load_history(chat_id: int) -> List[Dict]:
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


def save_history(chat_id: int, history: List[Dict]):
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


def search_knowledge(query: str, limit: int = 5, topic: str = "") -> List[Dict]:
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


# --- X/Twitter accounts (encrypted at rest) ---

def _get_fernet():
    from cryptography.fernet import Fernet
    from config import get_cookie_key
    return Fernet(get_cookie_key())


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _get_fernet().decrypt(value.encode()).decode()


def _is_encrypted(value: str) -> bool:
    """Check if a value looks like a Fernet token."""
    try:
        _get_fernet().decrypt(value.encode())
        return True
    except Exception:
        return False


def save_x_cookies(user_id: int, auth_token: str, ct0: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO x_accounts (user_id, auth_token, ct0, connected_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET auth_token = excluded.auth_token, ct0 = excluded.ct0, connected_at = excluded.connected_at",
        (user_id, _encrypt(auth_token), _encrypt(ct0), datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()


def get_x_cookies(user_id: int) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT auth_token, ct0 FROM x_accounts WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    auth_token, ct0 = row[0], row[1]
    # Auto-migrate plaintext cookies to encrypted
    if not _is_encrypted(auth_token):
        enc_auth = _encrypt(auth_token)
        enc_ct0 = _encrypt(ct0)
        conn.execute(
            "UPDATE x_accounts SET auth_token = ?, ct0 = ? WHERE user_id = ?",
            (enc_auth, enc_ct0, user_id),
        )
        conn.commit()
        return {"auth_token": auth_token, "ct0": ct0}
    return {"auth_token": _decrypt(auth_token), "ct0": _decrypt(ct0)}


def delete_x_cookies(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM x_accounts WHERE user_id = ?", (user_id,))
    conn.commit()


# --- ChromaDB Integration ---

def store_knowledge_with_embeddings(topic: str, content: str, metadata: dict):
    """
    Store knowledge in both SQLite and ChromaDB (semantic search).
    This is the preferred method for storing new knowledge.
    """
    # Store in SQLite (existing pattern)
    store_knowledge(topic, content, metadata)

    # Also store in ChromaDB for semantic search
    try:
        from embeddings_client import add_to_knowledge_base

        # Ensure metadata has topic
        metadata_copy = metadata.copy() if isinstance(metadata, dict) else {}
        metadata_copy["topic"] = topic

        # Add to vector DB
        add_to_knowledge_base(content, metadata_copy)
    except Exception as e:
        import logging
        logging.error(f"Error storing in ChromaDB: {e}")
        # Continue even if ChromaDB fails (SQLite still has it)


def migrate_knowledge_to_chromadb():
    """
    One-time migration: Move all existing SQLite knowledge to ChromaDB.
    Run this once after setting up ChromaDB.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT topic, content, metadata FROM knowledge_base ORDER BY id DESC"
    ).fetchall()

    knowledge_items = []
    for row in rows:
        topic = row[0]
        content = row[1]
        metadata_str = row[2]

        try:
            metadata = json.loads(metadata_str) if metadata_str else {}
        except:
            metadata = {}

        knowledge_items.append({
            "content": content,
            "topic": topic,
            "metadata": metadata
        })

    # Migrate to ChromaDB
    try:
        from embeddings_client import migrate_from_sqlite
        migrated_count = migrate_from_sqlite(knowledge_items)
        return migrated_count
    except Exception as e:
        import logging
        logging.error(f"Error migrating to ChromaDB: {e}")
        return 0


def get_all_knowledge_for_migration() -> List[Dict]:
    """Get all knowledge entries for migration purposes."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT topic, content, metadata FROM knowledge_base ORDER BY id DESC"
    ).fetchall()

    items = []
    for row in rows:
        try:
            metadata = json.loads(row[2]) if row[2] else {}
        except:
            metadata = {}

        items.append({
            "topic": row[0],
            "content": row[1],
            "metadata": metadata
        })

    return items


# --- DeFi Trading: Wallets ---

def _get_wallet_fernet():
    from cryptography.fernet import Fernet
    from config import get_wallet_key
    return Fernet(get_wallet_key())


def save_wallet(user_id: int, chain: str, private_key: str, address: str, label: str = ""):
    conn = get_conn()
    f = _get_wallet_fernet()
    encrypted = f.encrypt(private_key.encode()).decode()
    conn.execute(
        "INSERT INTO wallets (user_id, chain, encrypted_key, address, label, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, chain) DO UPDATE SET encrypted_key=excluded.encrypted_key, "
        "address=excluded.address, label=excluded.label",
        (user_id, chain, encrypted, address, label, datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()


def get_wallet(user_id: int, chain: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT encrypted_key, address, label FROM wallets WHERE user_id=? AND chain=?",
        (user_id, chain),
    ).fetchone()
    if not row:
        return None
    f = _get_wallet_fernet()
    return {
        "private_key": f.decrypt(row[0].encode()).decode(),
        "address": row[1],
        "label": row[2],
    }


def get_all_wallets(user_id: int) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT chain, address, label, created_at FROM wallets WHERE user_id=?",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_wallet(user_id: int, chain: str):
    conn = get_conn()
    conn.execute("DELETE FROM wallets WHERE user_id=? AND chain=?", (user_id, chain))
    conn.commit()


# --- DeFi Trading: Trades ---

def save_trade(user_id: int, chain: str, token_in: str, token_out: str,
               amount_in: str, status: str = "pending", **kwargs) -> int:
    conn = get_conn()
    cursor = conn.execute(
        "INSERT INTO trades (user_id, chain, token_in, token_out, amount_in, status, "
        "token_in_symbol, token_out_symbol, amount_usd, slippage_bps, risk_score, "
        "safety_report, goal_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, chain, token_in, token_out, amount_in, status,
         kwargs.get("token_in_symbol", ""), kwargs.get("token_out_symbol", ""),
         kwargs.get("amount_usd", ""), kwargs.get("slippage_bps", 0),
         kwargs.get("risk_score", 0), kwargs.get("safety_report", "{}"),
         kwargs.get("goal_id"), datetime.now(tz=timezone.utc).isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def update_trade(trade_id: int, **kwargs):
    conn = get_conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(v)
    if sets:
        vals.append(trade_id)
        conn.execute(f"UPDATE trades SET {', '.join(sets)} WHERE id=?", vals)
        conn.commit()


def get_trade(trade_id: int) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    return dict(row) if row else None


def get_trades(user_id: int, limit: int = 20) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_pending_trades(user_id: int) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE user_id=? AND status IN ('pending','confirmed') ORDER BY id",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- DeFi Trading: Goals ---

def save_trading_goal(user_id: int, target_amount: float, chain: str = "base",
                      strategy: str = "{}") -> int:
    now = datetime.now(tz=timezone.utc).isoformat()
    conn = get_conn()
    cursor = conn.execute(
        "INSERT INTO trading_goals (user_id, target_amount, strategy, chain, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, target_amount, strategy, chain, now, now),
    )
    conn.commit()
    return cursor.lastrowid


def get_active_goals(user_id: int) -> List[Dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trading_goals WHERE user_id=? AND status='active' ORDER BY id DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_goal(goal_id: int, **kwargs):
    conn = get_conn()
    sets = []
    vals = []
    for k, v in kwargs.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("updated_at=?")
    vals.append(datetime.now(tz=timezone.utc).isoformat())
    vals.append(goal_id)
    conn.execute(f"UPDATE trading_goals SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
