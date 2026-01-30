from collections.abc import AsyncIterator
from anthropic import AsyncAnthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_HISTORY
from web_tools import TOOLS, execute_tool

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

conversations: dict[int, list[dict]] = {}
system_prompts: dict[int, str] = {}


def get_history(chat_id: int) -> list[dict]:
    return conversations.setdefault(chat_id, [])


def clear_history(chat_id: int):
    conversations.pop(chat_id, None)


def set_system_prompt(chat_id: int, prompt: str):
    system_prompts[chat_id] = prompt


async def ask_stream(chat_id: int, text: str, on_status=None) -> AsyncIterator[str]:
    history = get_history(chat_id)
    history.append({"role": "user", "content": text})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    kwargs = {"model": CLAUDE_MODEL, "max_tokens": 4096, "messages": history, "tools": TOOLS}
    system = system_prompts.get(chat_id)
    if system:
        kwargs["system"] = system

    # Tool use loop: handle tool calls until we get a final text response
    while True:
        response = await client.messages.create(**kwargs)

        # Check if Claude wants to use tools
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            break

        # Add assistant response with tool calls to history
        history.append({"role": "assistant", "content": response.content})

        # Execute each tool and add results
        tool_results = []
        for tool_call in tool_calls:
            if on_status:
                await on_status(f"🔍 {tool_call.name}: {tool_call.input.get('query', tool_call.input.get('url', ''))}")
            result = await execute_tool(tool_call.name, tool_call.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result,
            })

        history.append({"role": "user", "content": tool_results})
        kwargs["messages"] = history

    # Now stream the final text response
    # Remove the non-streamed response from history and re-request with streaming
    # But if we already have the final response, just yield it
    if response.stop_reason == "end_turn":
        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        if tool_calls or not final_text:
            # We got here after tool use, response already contains final text
            history.append({"role": "assistant", "content": final_text})
            yield final_text
        else:
            # No tool use happened, re-do with streaming
            # Remove the last message we just got and stream instead
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
