from collections.abc import AsyncIterator
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_HISTORY
from storage import load_history, save_history, delete_history, load_system_prompt, save_system_prompt
from web_tools import CUSTOM_TOOLS, execute_tool

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
ALL_TOOLS = [WEB_SEARCH_TOOL] + CUSTOM_TOOLS


def get_default_system() -> str:
    now = datetime.now(tz=timezone.utc)
    return (
        f"Current date/time: {now.strftime('%B %d, %Y %H:%M:%S UTC')}. "
        "You have access to web search and real-time crypto price tools. "
        "For cryptocurrency prices, ALWAYS use get_crypto_price or get_multiple_crypto_prices — "
        "these return live market data accurate to the second. Use search_coin if you don't know the CoinGecko ID. "
        "For news, events, and other live information, use web_search. "
        "NEVER rely on training data for anything time-sensitive. "
        "Always mention the exact timestamp of the data you provide."
    )


def get_history(chat_id: int) -> list[dict]:
    return load_history(chat_id)


def clear_history(chat_id: int):
    delete_history(chat_id)


def set_system_prompt(chat_id: int, prompt: str):
    save_system_prompt(chat_id, prompt)


async def ask_stream(chat_id: int, text: str, on_status=None) -> AsyncIterator[str]:
    history = get_history(chat_id)
    history.append({"role": "user", "content": text})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": history, "tools": ALL_TOOLS}
    user_system = load_system_prompt(chat_id)
    system = get_default_system() + ("\n\n" + user_system if user_system else "")
    kwargs["system"] = system

    # Tool use loop
    while True:
        response = await client.messages.create(**kwargs)

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            break

        history.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tc in tool_calls:
            result = await execute_tool(tc.name, tc.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })

        history.append({"role": "user", "content": tool_results})
        kwargs["messages"] = history

    # Extract final text
    final_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_text += block.text

    history.append({"role": "assistant", "content": final_text})
    save_history(chat_id, history)
    yield final_text


async def generate(prompt: str, system: str = "") -> str:
    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text
