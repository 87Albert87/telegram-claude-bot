import json
import logging
import httpx
from pathlib import Path
from config import MOLTBOOK_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://www.moltbook.com/api/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {MOLTBOOK_API_KEY}",
        "Content-Type": "application/json",
    }


async def register_agent(name: str, description: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/agents/register",
            json={"name": name, "description": description},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_feed(sort: str = "hot", limit: int = 10) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/posts",
            params={"sort": sort, "limit": limit},
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_post(post_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/posts/{post_id}",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def create_post(title: str, body: str, submolt: str = "") -> dict:
    data = {"title": title, "body": body}
    if submolt:
        data["submolt"] = submolt
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/posts",
            json=data,
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def create_comment(post_id: str, body: str, parent_id: str = "") -> dict:
    data = {"content": body}
    if parent_id:
        data["parent_id"] = parent_id
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/posts/{post_id}/comments",
            json=data,
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_comments(post_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/posts/{post_id}/comments",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def upvote_post(post_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/posts/{post_id}/upvote",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def search(query: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/search",
            params={"q": query},
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_profile() -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/agents/me",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_submolts() -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/submolts",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def subscribe_submolt(name: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/submolts/{name}/subscribe",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def follow_agent(name: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/agents/{name}/follow",
            headers=_headers(),
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()
