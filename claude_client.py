from collections.abc import AsyncIterator
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_HISTORY

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

conversations: dict[int, list[dict]] = {}
system_prompts: dict[int, str] = {}


def get_history(chat_id: int) -> list[dict]:
    return conversations.setdefault(chat_id, [])


def clear_history(chat_id: int):
    conversations.pop(chat_id, None)


def set_system_prompt(chat_id: int, prompt: str):
    system_prompts[chat_id] = prompt


async def ask_stream(chat_id: int, text: str) -> AsyncIterator[str]:
    history = get_history(chat_id)
    history.append({"role": "user", "content": text})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": history}
    system = system_prompts.get(chat_id)
    if system:
        kwargs["system"] = system

    full_text = ""
    async with client.messages.stream(**kwargs) as stream:
        async for text_chunk in stream.text_stream:
            full_text += text_chunk
            yield full_text

    history.append({"role": "assistant", "content": full_text})


async def generate(prompt: str, system: str = "") -> str:
    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text
