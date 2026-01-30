import json
import sqlite3
from config import DB_PATH

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                chat_id INTEGER PRIMARY KEY,
                history TEXT NOT NULL DEFAULT '[]',
                system_prompt TEXT NOT NULL DEFAULT ''
            )
        """)
        _conn.commit()
    return _conn


def load_history(chat_id: int) -> list[dict]:
    conn = get_conn()
    row = conn.execute("SELECT history FROM conversations WHERE chat_id = ?", (chat_id,)).fetchone()
    if row:
        return json.loads(row[0])
    return []


def save_history(chat_id: int, history: list[dict]):
    conn = get_conn()
    # Filter out non-serializable tool use entries (keep only simple text messages)
    clean = []
    for msg in history:
        if isinstance(msg.get("content"), str):
            clean.append(msg)
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
