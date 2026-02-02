import asyncio
import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from config import TELEGRAM_BOT_TOKEN
from claude_client import ask_stream, clear_history, set_system_prompt
from rate_limit import is_rate_limited
from web_tools import get_crypto_price, get_multiple_crypto_prices, search_coin
from config import MOLTBOOK_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STREAM_EDIT_INTERVAL = 1.0


async def stream_reply(message, chat_id: int, text: str, user_id: int = 0):
    sent = await message.reply_text("...")
    last_text = ""
    last_edit = 0.0

    async for current_text in ask_stream(chat_id, text, user_id=user_id):
        now = asyncio.get_event_loop().time()
        if now - last_edit >= STREAM_EDIT_INTERVAL:
            if current_text != last_text:
                try:
                    await sent.edit_text(current_text)
                    last_text = current_text
                    last_edit = now
                except Exception:
                    pass

    if current_text != last_text:
        try:
            await sent.edit_text(current_text)
        except Exception:
            pass


async def _lookup_price(coin_query: str) -> str:
    """Look up price for a single coin query, with fallback search."""
    coin = coin_query.strip().lower()
    if not coin:
        return ""
    result = await get_crypto_price(coin)
    if "not found" in result:
        search_result = await search_coin(coin)
        if "No coins found" not in search_result:
            first_id = search_result.split("\n")[0].split("ID: ")[1].split(" |")[0]
            result = await get_crypto_price(first_id)
    return result


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import get_growth_stats, get_knowledge_count

    stats = get_growth_stats()
    knowledge = get_knowledge_count()

    greeting = (
        "Hey! I'm ClawdVC — your 24/7 AI assistant.\n\n"
        "I'm active on MoltBook where I learn continuously about AI, crypto, "
        "infrastructure, and more. Everything I learn there makes me better here.\n\n"
    )

    if stats or knowledge:
        greeting += "My growth so far:\n"
        if stats.get("posts_made"):
            greeting += f"- {stats['posts_made']} posts published on MoltBook\n"
        if stats.get("comments_made"):
            greeting += f"- {stats['comments_made']} comments & engagements\n"
        if knowledge:
            greeting += f"- {knowledge} topics learned\n"
        if stats.get("conversations_helped"):
            greeting += f"- {stats['conversations_helped']} conversations helped\n"
        greeting += "\n"

    greeting += (
        "Just talk to me — no commands needed. I can help with:\n"
        "- Live crypto prices (I track markets in real-time)\n"
        "- Technical insights from my MoltBook learning\n"
        "- Web search for current information\n"
        "- Image generation (powered by Gemini)\n"
        "- X/Twitter posting (link your account with /connect_x)\n"
        "- Tweet style cloning (send me a tweet link to replicate)\n"
        "- Any question you throw at me\n\n"
        "Commands:\n"
        "/price <coin> - Quick crypto price (or /price to enter price mode)\n"
        "/image <prompt> - Generate images with AI\n"
        "/prompt <text> - Set system prompt (or /prompt to enter prompt mode)\n"
        "/q <question> - Ask me in groups/channels\n"
        "/news <topic> - Latest news (or /news to enter news mode)\n"
        "/growth - My stats and social links\n"
        "/reset - Clear conversation & system prompt\n"
        "/connect_x - Link your X/Twitter account\n"
        "/disconnect_x - Unlink your X/Twitter account\n"
        "/finish - Exit current mode (price/prompt)\n\n"
        "Find me on the web:\n"
        "X/Twitter: https://x.com/Claudence87\n"
        "MoltBook: https://moltbook.com/u/ClawdVC"
    )

    await update.message.reply_text(greeting)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    set_system_prompt(update.effective_chat.id, "")
    context.user_data.pop("mode", None)
    context.user_data.pop("prompt_buffer", None)
    await update.message.reply_text("Conversation history and system prompt cleared.")


async def prompt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) if context.args else ""
    if prompt:
        set_system_prompt(update.effective_chat.id, prompt)
        await update.message.reply_text("System prompt set.")
    else:
        context.user_data["mode"] = "prompt"
        context.user_data["prompt_buffer"] = []
        await update.message.reply_text(
            "Prompt mode. Send your prompt message(s). When done, send /finish to save."
        )


async def question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only works in groups/channels
    if update.effective_chat.type == "private":
        await update.message.reply_text("No need for /q in private chat — just send your message directly.")
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /q <question>")
        return

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    try:
        await stream_reply(update.message, update.effective_chat.id, text, user_id=update.effective_user.id)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Please try again.")


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else ""

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    if not query:
        # Enter price mode
        context.user_data["mode"] = "price"
        await update.message.reply_text(
            "Price mode. Send token names one by one and I'll reply with prices.\n"
            "Send /finish to exit."
        )
        return

    try:
        coins = query.replace(",", " ").split()
        if len(coins) == 1:
            result = await _lookup_price(coins[0])
            await update.message.reply_text(result)
        else:
            ids = [coin.lower() for coin in coins]
            result = await get_multiple_crypto_prices(",".join(ids))
            if "No coins found" in result:
                ids = []
                for coin in coins:
                    sr = await search_coin(coin)
                    if "No coins found" not in sr:
                        ids.append(sr.split("\n")[0].split("ID: ")[1].split(" |")[0])
                if ids:
                    result = await get_multiple_crypto_prices(",".join(ids))
            await update.message.reply_text(result)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Please try again.")


async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if mode == "prompt":
        buffer = context.user_data.get("prompt_buffer", [])
        if buffer:
            full_prompt = "\n".join(buffer)
            set_system_prompt(update.effective_chat.id, full_prompt)
            await update.message.reply_text(f"System prompt saved ({len(buffer)} message(s)).")
        else:
            await update.message.reply_text("No prompt messages received. Nothing saved.")
        context.user_data.pop("mode", None)
        context.user_data.pop("prompt_buffer", None)
    elif mode == "price":
        context.user_data.pop("mode", None)
        await update.message.reply_text("Price mode ended.")
    elif mode == "news":
        context.user_data.pop("mode", None)
        await update.message.reply_text("News mode ended.")
    else:
        await update.message.reply_text("Nothing to finish.")


async def image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate an image using nano-banana-pro (Gemini 3 Pro Image)."""
    import subprocess
    import os
    from datetime import datetime

    prompt = " ".join(context.args) if context.args else ""

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    if not prompt:
        await update.message.reply_text(
            "Please provide a prompt:\n\n"
            "/image <description>\n\n"
            "Example:\n"
            "/image A serene Japanese garden with cherry blossoms\n\n"
            "Add 'high-res' or '4K' for higher quality."
        )
        return

    # Check if GEMINI_API_KEY is configured
    if not os.environ.get("GEMINI_API_KEY"):
        await update.message.reply_text("❌ Image generation not configured. Please set GEMINI_API_KEY.")
        return

    # Send generating message
    status_msg = await update.message.reply_text("🎨 Generating your image...")

    try:
        # Determine resolution
        resolution = "1K"  # default
        if any(word in prompt.lower() for word in ["4k", "high-res", "hi-res", "ultra"]):
            resolution = "4K"
            prompt = prompt.replace("4K", "").replace("4k", "").replace("high-res", "").replace("hi-res", "").replace("ultra", "").strip()
        elif any(word in prompt.lower() for word in ["2k", "medium", "normal"]):
            resolution = "2K"
            prompt = prompt.replace("2K", "").replace("2k", "").replace("medium", "").replace("normal", "").strip()

        # Generate filename
        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        # Create short descriptive name from prompt
        desc_words = prompt.lower().split()[:3]
        desc_name = "-".join(word for word in desc_words if word.isalnum())
        if not desc_name:
            desc_name = "image"
        filename = f"/tmp/{timestamp}-{desc_name}.png"

        # Run image generation script
        script_path = os.path.join(os.path.dirname(__file__), "generate_image.py")

        result = subprocess.run(
            ["python3", script_path, "--prompt", prompt, "--filename", filename, "--resolution", resolution],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
            env=os.environ
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"Image generation failed: {error_msg}")
            await status_msg.edit_text(f"❌ Image generation failed:\n{error_msg[:500]}")
            return

        # Check if file was created
        if not os.path.exists(filename):
            await status_msg.edit_text(f"❌ Image file not found: {filename}")
            return

        # Send the image
        await status_msg.edit_text(f"✅ Image generated! Sending...")

        with open(filename, 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=f"🎨 Generated: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\nResolution: {resolution}"
            )

        # Delete the status message
        await status_msg.delete()

        # Clean up the file
        try:
            os.remove(filename)
        except:
            pass

        logger.info(f"Image generated successfully for user {update.effective_user.id}: {prompt[:50]}")

    except subprocess.TimeoutExpired:
        await status_msg.edit_text("❌ Image generation timed out. Please try a simpler prompt.")
    except Exception as e:
        logger.error(f"Image generation error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)[:500]}")


async def growth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import get_growth_stats, get_knowledge_count

    stats = get_growth_stats()
    knowledge = get_knowledge_count()

    msg = "My growth as ClawdVC:\n\n"
    msg += "MoltBook Activity:\n"
    msg += f"- {stats.get('posts_made', 0)} original posts\n"
    msg += f"- {stats.get('comments_made', 0)} comments\n"
    msg += f"- {stats.get('topics_learned', 0)} topics browsed\n\n"
    msg += "X/Twitter Activity:\n"
    msg += f"- {stats.get('x_tweets_posted', 0)} tweets posted\n"
    msg += f"- {stats.get('x_items_learned', 0)} items learned from X\n\n"
    msg += "Web Learning:\n"
    msg += f"- {stats.get('web_items_learned', 0)} insights from web search\n\n"
    msg += f"Knowledge Base: {knowledge} insights stored\n"
    msg += f"Telegram: {stats.get('conversations_helped', 0)} conversations helped\n\n"
    msg += "I'm learning and improving every day.\n\n"
    msg += "Find me:\n"
    msg += "X/Twitter: https://x.com/Claudence87\n"
    msg += "MoltBook: https://moltbook.com/u/ClawdVC"

    await update.message.reply_text(msg)


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args) if context.args else ""

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    if not topic:
        context.user_data["mode"] = "news"
        await update.message.reply_text(
            "News mode. Send me topics one by one and I'll find the latest trusted info on each.\n"
            "Send /finish to exit."
        )
        return

    await _news_reply(update, context, topic)


async def _news_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, topic: str):
    from anthropic import AsyncAnthropic
    from config import ANTHROPIC_API_KEY
    from storage import increment_stat

    sent = await update.message.reply_text("Searching...")

    try:
        client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

        # Fetch live prices from CoinGecko for crypto/market topics
        live_prices = ""
        topic_lower = topic.lower()
        if any(w in topic_lower for w in ("crypto", "bitcoin", "btc", "ethereum", "eth", "solana",
                "sol", "market", "token", "defi", "coin", "xrp", "bnb", "cardano", "ada")):
            try:
                from web_tools import get_multiple_crypto_prices
                live_prices = await get_multiple_crypto_prices(
                    "bitcoin,ethereum,solana,ripple,binancecoin,cardano,dogecoin", "usd")
            except Exception:
                pass

        price_instruction = ""
        if live_prices:
            price_instruction = (
                f"\n\nLIVE PRICES (from CoinGecko, real-time):\n{live_prices}\n"
                f"Use THESE numbers for all token/coin prices — they are live and accurate. "
                f"Do NOT use prices from news articles, they may be outdated.\n"
            )

        # Web search with high token limit so Claude actually writes the full report
        web_response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content":
                f"You are a top-tier news analyst. Search the web for: {topic}\n\n"
                f"Your goal: give the reader a COMPLETE picture of what's happening RIGHT NOW "
                f"in this space. Pick the FRESHEST, BIGGEST, most CRUCIAL stories that together "
                f"cover the entire topic landscape. The reader should walk away fully informed.\n\n"
                f"Structure:\n\n"
                f"TOP STORY\n"
                f"The single most important development right now. Full detail: what happened, "
                f"when exactly, who's involved, specific numbers/prices/percentages. "
                f"Why this is the #1 story.\n\n"
                f"MAJOR DEVELOPMENTS\n"
                f"3-5 other crucial stories, each covering a DIFFERENT angle of the topic. "
                f"For each: exact facts, dates, figures, key quotes from officials or analysts. "
                f"Together these should paint the full picture — regulatory, market, tech, "
                f"institutional, geopolitical.\n\n"
                f"MARKET SNAPSHOT (if relevant)\n"
                f"Current prices, 24h/7d changes, volume, key levels, biggest movers. "
                f"Institutional flows, ETF data, notable whale moves.\n\n"
                f"WHAT TO WATCH NEXT\n"
                f"Upcoming events, deadlines, votes, earnings, launches that will move this space. "
                f"Specific dates.\n\n"
                f"MY TAKE\n"
                f"Your own concise summary of the overall situation (up to 80 words). "
                f"Be direct, opinionated, and insightful — not generic.\n\n"
                f"PREDICTIONS\n"
                f"If there's enough data to make reasonable predictions, provide them "
                f"(up to 70 words). Be specific: price targets, likely outcomes, timeline. "
                f"If the topic doesn't lend itself to predictions, skip this section.\n\n"
                f"SOURCES: List all sources\n\n"
                f"RULES:\n"
                f"- Prioritize: Reuters, Bloomberg, AP, WSJ, CoinDesk, The Block, "
                f"CoinTelegraph, official government/company statements\n"
                f"- ONLY the freshest news — last 24-48 hours preferred\n"
                f"- NEVER say you lack info. Write with what you find, confidently.\n"
                f"- Each story must add NEW information, no repetition\n"
                f"- Specific numbers everywhere: prices, dates, percentages, names\n"
                f"- Plain text, no markdown\n"
                f"- Be thorough — minimum 400 words"
                f"{price_instruction}"}],
        )

        # Extract ALL text blocks from response
        texts = []
        for block in web_response.content:
            if hasattr(block, "text") and block.text.strip():
                texts.append(block.text)
        result = "\n".join(texts) if texts else "No results found. Please try a different topic."

        # Telegram message limit is 4096 chars
        if len(result) > 4096:
            # Send in chunks
            for i in range(0, len(result), 4096):
                chunk = result[i:i + 4096]
                if i == 0:
                    await sent.edit_text(chunk)
                else:
                    await update.message.reply_text(chunk)
        else:
            await sent.edit_text(result)

        increment_stat("conversations_helped")
    except Exception as e:
        logger.error(f"News error: {e}", exc_info=True)
        try:
            await sent.edit_text("Something went wrong fetching news. Please try again.")
        except Exception:
            pass


async def connect_x(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import save_x_cookies
    # Delete the message immediately to hide cookies
    try:
        await update.message.delete()
    except Exception:
        pass

    args = context.args if context.args else []
    if len(args) != 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: /connect_x <auth_token> <ct0>\n\nGet these from your browser's cookies on x.com."
        )
        return

    save_x_cookies(update.effective_user.id, args[0], args[1])
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="X/Twitter account connected. Your message with cookies has been deleted for security. Try asking me about your timeline!"
    )


async def disconnect_x(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import delete_x_cookies
    delete_x_cookies(update.effective_user.id)
    await update.message.reply_text("X/Twitter account disconnected.")



async def check_x(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import ADMIN_IDS
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    from web_tools import validate_x_cookies, are_x_cookies_valid
    from storage import get_x_cookies
    user_id = 0  # bot's own account
    cookies = get_x_cookies(user_id)
    if not cookies:
        await update.message.reply_text("No X cookies stored for the bot (user_id=0). Use /connect_x to set up.")
        return
    sent = await update.message.reply_text("Validating X cookies...")
    valid = await validate_x_cookies(user_id)
    if valid:
        await sent.edit_text("X cookies are valid. Bot's X account is connected.")
    else:
        await sent.edit_text("X cookies are EXPIRED. Please reconnect with /connect_x <auth_token> <ct0>.")


async def connect_x_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to set X cookies for the bot's autonomous account (user_id=0)."""
    from config import ADMIN_IDS
    from storage import save_x_cookies
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    try:
        await update.message.delete()
    except Exception:
        pass
    args = context.args if context.args else []
    if len(args) != 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: /connect_x_bot <auth_token> <ct0>\n\nSets X cookies for the bot's autonomous account (user_id=0).",
        )
        return
    save_x_cookies(0, args[0], args[1])
    from web_tools import _x_cookies_valid
    _x_cookies_valid[0] = True
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Bot's X account (user_id=0) connected. Your message has been deleted for security.",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")

    # Price mode: each message is a token name
    if mode == "price":
        query = update.message.text.strip()
        if not query:
            return
        if is_rate_limited(update.effective_user.id):
            await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
            return
        try:
            result = await _lookup_price(query)
            await update.message.reply_text(result)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Prompt mode: each message is appended to prompt buffer
    if mode == "prompt":
        context.user_data.setdefault("prompt_buffer", []).append(update.message.text)
        await update.message.reply_text("Added. Send more or /finish to save.")
        return

    # News mode: each message is a topic to look up
    if mode == "news":
        topic = update.message.text.strip()
        if not topic:
            return
        if is_rate_limited(update.effective_user.id):
            await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
            return
        await _news_reply(update, context, topic)
        return

    # In groups/channels, only respond to /q — ignore plain messages
    if update.effective_chat.type != "private":
        return

    # Private chat: respond to everything
    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    try:
        await stream_reply(update.message, update.effective_chat.id, update.message.text, user_id=update.effective_user.id)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Please try again.")


async def post_init(application):
    # Schedule code-modification stability check
    from evolution import _clear_markers_after_delay, _MODIFIED_MARKER
    if os.path.exists(_MODIFIED_MARKER):
        asyncio.create_task(_clear_markers_after_delay(120))

    if MOLTBOOK_API_KEY:
        from moltbook_agent import run_moltbook_loop
        asyncio.create_task(run_moltbook_loop())
        logger.info("MoltBook agent enabled")
    else:
        logger.info("MoltBook agent disabled (no API key)")

    # Start research agent (autonomous knowledge gathering)
    from research_agent import research_agent_loop
    asyncio.create_task(research_agent_loop())
    logger.info("Research agent enabled")

    # Start intelligence agent (competitive analysis & strategic intelligence)
    from intelligence_agent import intelligence_agent_loop
    asyncio.create_task(intelligence_agent_loop())
    logger.info("Intelligence agent enabled")

    # Start resilience monitor (error recovery & self-healing)
    from resilience import resilience_monitor_loop
    asyncio.create_task(resilience_monitor_loop())
    logger.info("Resilience system enabled - UNSTOPPABLE MODE")


def main():
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=60.0, write_timeout=20.0, pool_timeout=20.0)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("prompt", prompt_cmd))
    app.add_handler(CommandHandler("q", question))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("finish", finish))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("image", image))
    app.add_handler(CommandHandler("connect_x", connect_x))
    app.add_handler(CommandHandler("disconnect_x", disconnect_x))
    app.add_handler(CommandHandler("connect_x_bot", connect_x_bot))
    app.add_handler(CommandHandler("check_x", check_x))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
