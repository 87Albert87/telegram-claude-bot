import asyncio
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler,
)
from telegram.request import HTTPXRequest
from config import (
    TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, MOLTBOOK_API_KEY, ADMIN_IDS,
    FREE_DAILY_MESSAGES, STRIPE_PROVIDER_TOKEN, CRYPTOBOT_API_TOKEN,
    get_plan_prices, PLAN_DURATIONS,
)
from claude_client import ask_stream, clear_history, set_system_prompt
from rate_limit import is_rate_limited
from web_tools import get_crypto_price, get_multiple_crypto_prices, search_coin
from subscription import (
    can_use_bot, increment_daily_usage, get_subscription_status_text,
    create_subscription, record_payment, PLAN_LABELS,
)
from payments import (
    send_stars_invoice, send_stripe_invoice, create_crypto_invoice,
    check_crypto_payment, precheckout_callback, successful_payment_callback,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STREAM_EDIT_INTERVAL = 1.0

_bot_username = ""


# ---------------------------------------------------------------------------
# Group chat trigger detection
# ---------------------------------------------------------------------------

def _is_bot_triggered(update: Update) -> tuple[bool, str]:
    """Check if the bot should respond in a group chat.

    Returns (should_respond, cleaned_text).
    Triggers: reply to bot's message, or @mention in text.
    """
    msg = update.message
    if not msg:
        return False, ""

    # Reply to the bot's own message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username and \
           msg.reply_to_message.from_user.username.lower() == _bot_username.lower():
            return True, (msg.text or msg.caption or "")

    # @mention in text
    text = msg.text or msg.caption or ""
    if _bot_username and f"@{_bot_username.lower()}" in text.lower():
        import re
        cleaned = re.sub(rf"@{re.escape(_bot_username)}\b", "", text, flags=re.IGNORECASE).strip()
        return True, cleaned

    return False, ""


# ---------------------------------------------------------------------------
# Subscription gate
# ---------------------------------------------------------------------------

async def check_subscription_gate(update: Update) -> bool:
    """Returns True if user can proceed. Sends paywall message if not."""
    user_id = update.effective_user.id
    allowed, reason = can_use_bot(user_id)
    if not allowed:
        await update.message.reply_text(
            f"You've used all {FREE_DAILY_MESSAGES} free messages for today.\n\n"
            f"/subscribe - View plans and pricing\n"
            f"Free messages reset daily at midnight UTC."
        )
        return False
    if reason == "free":
        increment_daily_usage(user_id)
    return True


# ---------------------------------------------------------------------------
# Streaming reply helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import get_growth_stats, get_knowledge_count

    stats = get_growth_stats()
    knowledge = get_knowledge_count()

    greeting = (
        "Hey! I'm ClawdVC — your 24/7 AI assistant.\n\n"
        "I'm active on MoltBook where I learn continuously about AI, crypto, "
        "infrastructure, and more. Everything I learn there makes me better here.\n\n"
    )

    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        allowed, reason = can_use_bot(user_id)
        if reason == "subscriber":
            greeting += "Your subscription is active. Use /status to check details.\n\n"
        else:
            greeting += (
                f"You have {FREE_DAILY_MESSAGES} free messages per day. "
                "Use /subscribe to upgrade for unlimited access.\n\n"
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
        "/subscribe - Subscription plans\n"
        "/status - Check your plan & usage\n"
        "/reset - Clear conversation & system prompt\n"
        "/connect_x - Link your X/Twitter account\n"
        "/disconnect_x - Unlink your X/Twitter account\n"
        "/finish - Exit current mode (price/prompt)\n"
    )

    from config import TRADING_ENABLED
    if TRADING_ENABLED and user_id in ADMIN_IDS:
        greeting += (
            "\nDeFi Trading:\n"
            "/connect_wallet [chain] - Load wallet from .env\n"
            "/disconnect_wallet [chain] - Disconnect wallet\n"
            "/portfolio [chain] - View portfolio\n"
            "/trades - Trade history\n"
        )

    greeting += (
        "\nFind me on the web:\n"
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
    if not await check_subscription_gate(update):
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
    if not await check_subscription_gate(update):
        return

    if not query:
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
    from datetime import datetime

    prompt = " ".join(context.args) if context.args else ""

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return
    if not await check_subscription_gate(update):
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

    if not os.environ.get("GEMINI_API_KEY"):
        await update.message.reply_text("Image generation not configured. Please set GEMINI_API_KEY.")
        return

    status_msg = await update.message.reply_text("Generating your image...")

    try:
        resolution = "1K"
        if any(word in prompt.lower() for word in ["4k", "high-res", "hi-res", "ultra"]):
            resolution = "4K"
            prompt = prompt.replace("4K", "").replace("4k", "").replace("high-res", "").replace("hi-res", "").replace("ultra", "").strip()
        elif any(word in prompt.lower() for word in ["2k", "medium", "normal"]):
            resolution = "2K"
            prompt = prompt.replace("2K", "").replace("2k", "").replace("medium", "").replace("normal", "").strip()

        timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        desc_words = prompt.lower().split()[:3]
        desc_name = "-".join(word for word in desc_words if word.isalnum())
        if not desc_name:
            desc_name = "image"
        filename = f"/tmp/{timestamp}-{desc_name}.png"

        script_path = os.path.join(os.path.dirname(__file__), "generate_image.py")

        result = subprocess.run(
            ["python3", script_path, "--prompt", prompt, "--filename", filename, "--resolution", resolution],
            capture_output=True,
            text=True,
            timeout=120,
            env=os.environ
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"Image generation failed: {error_msg}")
            await status_msg.edit_text(f"Image generation failed:\n{error_msg[:500]}")
            return

        if not os.path.exists(filename):
            await status_msg.edit_text(f"Image file not found: {filename}")
            return

        await status_msg.edit_text("Image generated! Sending...")

        with open(filename, 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=f"Generated: {prompt[:100]}{'...' if len(prompt) > 100 else ''}\nResolution: {resolution}"
            )

        await status_msg.delete()

        try:
            os.remove(filename)
        except Exception:
            pass

        logger.info(f"Image generated successfully for user {update.effective_user.id}: {prompt[:50]}")

    except subprocess.TimeoutExpired:
        await status_msg.edit_text("Image generation timed out. Please try a simpler prompt.")
    except Exception as e:
        logger.error(f"Image generation error: {e}", exc_info=True)
        await status_msg.edit_text(f"Error: {str(e)[:500]}")


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
    if not await check_subscription_gate(update):
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

        web_response = await client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=3072,
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

        texts = []
        for block in web_response.content:
            if hasattr(block, "text") and block.text.strip():
                texts.append(block.text)
        result = "\n".join(texts) if texts else "No results found. Please try a different topic."

        if len(result) > 4096:
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


# ---------------------------------------------------------------------------
# X/Twitter commands
# ---------------------------------------------------------------------------

async def connect_x(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import save_x_cookies
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
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    from web_tools import validate_x_cookies
    from storage import get_x_cookies
    user_id = 0
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
    from storage import save_x_cookies
    save_x_cookies(0, args[0], args[1])
    from web_tools import _x_cookies_valid
    _x_cookies_valid[0] = True
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Bot's X account (user_id=0) connected. Your message has been deleted for security.",
    )


# ---------------------------------------------------------------------------
# DeFi Trading commands (admin only)
# ---------------------------------------------------------------------------

async def connect_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Load wallet from .env (WALLET_BASE_KEY / WALLET_BNB_KEY). Never via chat."""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    from config import TRADING_ENABLED
    if not TRADING_ENABLED:
        await update.message.reply_text("Trading is not enabled. Set TRADING_ENABLED=true in .env")
        return
    args = context.args if context.args else []
    chain = args[0].lower() if args else "base"
    if chain not in ("base", "bnb"):
        await update.message.reply_text("Unsupported chain. Use 'base' or 'bnb'.")
        return
    import os
    env_key = os.getenv(f"WALLET_{chain.upper()}_KEY", "")
    if not env_key:
        await update.message.reply_text(
            f"No wallet key found for {chain}.\n\n"
            f"Set WALLET_{chain.upper()}_KEY in your .env file on the server.\n"
            "NEVER send private keys via Telegram chat.\n\n"
            "Steps:\n"
            f"1. SSH into VPS\n"
            f"2. Add to .env: WALLET_{chain.upper()}_KEY=0xYOUR_KEY\n"
            "3. Restart: docker compose restart\n"
            "4. Run /connect_wallet again"
        )
        return
    from wallet_manager import validate_private_key
    valid, address = validate_private_key(env_key)
    if not valid:
        await update.message.reply_text(f"Invalid key in WALLET_{chain.upper()}_KEY: {address}")
        return
    from storage import save_wallet
    save_wallet(update.effective_user.id, chain, env_key, address)
    await update.message.reply_text(
        f"Wallet connected for {chain.upper()}!\n"
        f"Address: {address}\n"
        f"Key loaded from .env (never sent via chat).\n"
        f"Use /portfolio to check balances."
    )


async def disconnect_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    args = context.args if context.args else []
    chain = args[0].lower() if args else "base"
    from storage import delete_wallet
    delete_wallet(update.effective_user.id, chain)
    await update.message.reply_text(f"Wallet disconnected for {chain}.")


async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    from config import TRADING_ENABLED
    if not TRADING_ENABLED:
        await update.message.reply_text("Trading is not enabled.")
        return
    args = context.args if context.args else []
    chain = args[0].lower() if args else "base"
    sent = await update.message.reply_text("Fetching portfolio...")
    try:
        from trading_agent import get_portfolio_summary
        result = await get_portfolio_summary(update.effective_user.id, chain)
        await sent.edit_text(result)
    except Exception as e:
        logger.error(f"Portfolio error: {e}", exc_info=True)
        await sent.edit_text(f"Error: {e}")


async def trades_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return
    sent = await update.message.reply_text("Fetching trades...")
    try:
        from trading_agent import get_trade_history
        result = await get_trade_history(update.effective_user.id)
        await sent.edit_text(result)
    except Exception as e:
        logger.error(f"Trades error: {e}", exc_info=True)
        await sent.edit_text(f"Error: {e}")


async def trade_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        return
    data = query.data
    parts = data.split("_")
    if len(parts) != 3:
        return
    _, action, trade_id_str = parts
    trade_id = int(trade_id_str)
    if action == "approve":
        from storage import update_trade
        update_trade(trade_id, status="confirmed")
        await query.edit_message_text(f"Trade #{trade_id} approved. Executing...")
        from trading_agent import execute_trade
        result = await execute_trade(trade_id, query.from_user.id)
        await context.bot.send_message(chat_id=query.message.chat_id, text=result)
    elif action == "reject":
        from storage import update_trade
        update_trade(trade_id, status="rejected")
        await query.edit_message_text(f"Trade #{trade_id} rejected.")


# ---------------------------------------------------------------------------
# Media handlers
# ---------------------------------------------------------------------------

async def transcribe_voice(file_path: str) -> str:
    """Transcribe voice message using Gemini."""
    if not GEMINI_API_KEY:
        return "[Voice transcription unavailable - no Gemini API key]"

    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)

        with open(file_path, "rb") as f:
            audio_data = f.read()

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                {
                    "parts": [
                        {"text": "Transcribe this audio message accurately. Return ONLY the transcription, nothing else. If the audio is in a non-English language, transcribe it in that language."},
                        {"inline_data": {"mime_type": "audio/ogg", "data": __import__('base64').b64encode(audio_data).decode()}}
                    ]
                }
            ]
        )

        return response.text.strip()
    except Exception as e:
        logger.error(f"Voice transcription error: {e}", exc_info=True)
        return f"[Could not transcribe voice: {e}]"


async def analyze_video(file_path: str, prompt: str = None) -> str:
    """Analyze video using Gemini."""
    if not GEMINI_API_KEY:
        return "[Video analysis unavailable - no Gemini API key]"

    try:
        from google import genai
        import base64

        client = genai.Client(api_key=GEMINI_API_KEY)

        with open(file_path, "rb") as f:
            video_data = f.read()

        size_mb = len(video_data) / (1024 * 1024)
        if size_mb > 20:
            return f"[Video too large: {size_mb:.1f}MB. Maximum is 20MB]"

        if not prompt:
            prompt = "Analyze this video in detail. Describe what's happening, any text visible, people, objects, actions, and the overall context. If there's audio/speech, transcribe it."

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "video/mp4", "data": base64.b64encode(video_data).decode()}}
                    ]
                }
            ]
        )

        return response.text.strip()
    except Exception as e:
        logger.error(f"Video analysis error: {e}", exc_info=True)
        return f"[Could not analyze video: {e}]"


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages by transcribing and processing with Claude."""
    if update.effective_chat.type != "private":
        triggered, _ = _is_bot_triggered(update)
        if not triggered:
            return

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return
    if not await check_subscription_gate(update):
        return

    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        await file.download_to_drive(tmp_path)

        sent = await update.message.reply_text("Transcribing...")
        transcription = await transcribe_voice(tmp_path)

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if transcription.startswith("["):
            await sent.edit_text(transcription)
            return

        await sent.edit_text(f"\"{transcription}\"\n\nThinking...")

        last_text = ""
        async for current_text in ask_stream(update.effective_chat.id, transcription, user_id=update.effective_user.id):
            if current_text != last_text:
                try:
                    display = f"\"{transcription}\"\n\n{current_text}"
                    if len(display) <= 4096:
                        await sent.edit_text(display)
                    else:
                        await sent.edit_text(current_text)
                    last_text = current_text
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Voice handling error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong processing your voice message.")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video messages - analyze with Gemini."""
    if update.effective_chat.type != "private":
        triggered, _ = _is_bot_triggered(update)
        if not triggered:
            return

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return
    if not await check_subscription_gate(update):
        return

    try:
        video = update.message.video or update.message.video_note
        if not video:
            return

        if video.file_size and video.file_size > 20 * 1024 * 1024:
            await update.message.reply_text("Video too large. Maximum size is 20MB.")
            return

        file = await context.bot.get_file(video.file_id)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        caption = update.message.caption or None

        sent = await update.message.reply_text("Analyzing video...")

        analysis = await analyze_video(tmp_path, caption)

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if analysis.startswith("["):
            await sent.edit_text(analysis)
            return

        context_prompt = f"The user sent a video. Here's the analysis:\n\n{analysis}"
        if caption:
            context_prompt += f"\n\nUser's question about the video: {caption}"
        context_prompt += "\n\nProvide a helpful response based on this video analysis."

        last_text = ""
        async for current_text in ask_stream(update.effective_chat.id, context_prompt, user_id=update.effective_user.id):
            if current_text != last_text:
                try:
                    await sent.edit_text(current_text[:4096])
                    last_text = current_text
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Video handling error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong analyzing the video.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages - analyze with Claude's vision."""
    if update.effective_chat.type != "private":
        triggered, _ = _is_bot_triggered(update)
        if not triggered:
            return

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return
    if not await check_subscription_gate(update):
        return

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        import base64
        with open(tmp_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        caption = update.message.caption or "What's in this image? Describe and analyze it."

        sent = await update.message.reply_text("Analyzing image...")

        attachments = [{"type": "image", "media_type": "image/jpeg", "data": image_data}]

        last_text = ""
        async for current_text in ask_stream(update.effective_chat.id, caption, user_id=update.effective_user.id, attachments=attachments):
            if current_text != last_text:
                try:
                    await sent.edit_text(current_text[:4096])
                    last_text = current_text
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Photo handling error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong analyzing the image.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document messages - analyze PDFs, read text files."""
    if update.effective_chat.type != "private":
        triggered, _ = _is_bot_triggered(update)
        if not triggered:
            return

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return
    if not await check_subscription_gate(update):
        return

    doc = update.message.document
    file_name = doc.file_name or "document"
    mime_type = doc.mime_type or ""

    file_ext = file_name.split(".")[-1].lower() if "." in file_name else ""

    try:
        file = await context.bot.get_file(doc.file_id)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=f".{file_ext}", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        import base64
        caption = update.message.caption or f"Analyze this {file_ext.upper()} file. Summarize its contents."

        sent = await update.message.reply_text(f"Reading {file_name}...")

        attachments = []
        text_content = None

        if mime_type == "application/pdf" or file_ext == "pdf":
            with open(tmp_path, "rb") as f:
                pdf_data = base64.b64encode(f.read()).decode()
            attachments = [{"type": "document", "media_type": "application/pdf", "data": pdf_data}]

        elif file_ext in ("txt", "md", "py", "js", "json", "csv", "xml", "html", "css", "yaml", "yml", "sh", "log"):
            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                text_content = f.read()[:50000]
            caption = f"Here's the content of {file_name}:\n\n```\n{text_content}\n```\n\n{caption}"

        elif file_ext == "docx":
            try:
                from docx import Document
                doc_file = Document(tmp_path)
                text_content = "\n".join([para.text for para in doc_file.paragraphs])[:50000]
                caption = f"Here's the content of {file_name}:\n\n{text_content}\n\n{caption}"
            except ImportError:
                await sent.edit_text("DOCX support not installed. Please use PDF or TXT files.")
                return
            except Exception as e:
                await sent.edit_text(f"Could not read DOCX: {e}")
                return

        else:
            await sent.edit_text(f"Unsupported file type: {file_ext}\n\nSupported: PDF, TXT, MD, DOCX, code files")
            return

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        last_text = ""
        async for current_text in ask_stream(update.effective_chat.id, caption, user_id=update.effective_user.id, attachments=attachments if attachments else None):
            if current_text != last_text:
                try:
                    await sent.edit_text(current_text[:4096])
                    last_text = current_text
                except Exception:
                    pass

    except Exception as e:
        logger.error(f"Document handling error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong reading the document.")


# ---------------------------------------------------------------------------
# Main message handler
# ---------------------------------------------------------------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")

    if mode == "price":
        query = update.message.text.strip()
        if not query:
            return
        if is_rate_limited(update.effective_user.id):
            await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
            return
        if not await check_subscription_gate(update):
            return
        try:
            result = await _lookup_price(query)
            await update.message.reply_text(result)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await update.message.reply_text("Something went wrong. Please try again.")
        return

    if mode == "prompt":
        context.user_data.setdefault("prompt_buffer", []).append(update.message.text)
        await update.message.reply_text("Added. Send more or /finish to save.")
        return

    if mode == "news":
        topic = update.message.text.strip()
        if not topic:
            return
        if is_rate_limited(update.effective_user.id):
            await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
            return
        if not await check_subscription_gate(update):
            return
        await _news_reply(update, context, topic)
        return

    # Groups/channels — only respond when @mentioned or replied to
    if update.effective_chat.type != "private":
        triggered, clean_text = _is_bot_triggered(update)
        if not triggered or not clean_text:
            return
        if is_rate_limited(update.effective_user.id):
            return
        if not await check_subscription_gate(update):
            return
        try:
            await stream_reply(update.message, update.effective_chat.id,
                               clean_text, user_id=update.effective_user.id)
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
        return

    # Private chat
    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return
    if not await check_subscription_gate(update):
        return

    try:
        await stream_reply(update.message, update.effective_chat.id, update.message.text, user_id=update.effective_user.id)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Please try again.")


# ---------------------------------------------------------------------------
# Subscription commands
# ---------------------------------------------------------------------------

async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show subscription plan options."""
    rows = []
    for plan_key in ("monthly", "3months", "6months", "yearly", "lifetime"):
        label = PLAN_LABELS[plan_key]
        prices = get_plan_prices(plan_key)
        rows.append([
            InlineKeyboardButton(
                f"{label} — {prices['stars']} Stars / ${int(prices['stripe_cents'])/100:.2f}",
                callback_data=f"plan_{plan_key}",
            )
        ])

    text = (
        "Choose your subscription plan:\n\n"
        f"Free tier: {FREE_DAILY_MESSAGES} messages/day\n"
        "Paid: Unlimited messages\n"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def plan_selected_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plan selection — show payment method options."""
    query = update.callback_query
    await query.answer()

    plan = query.data.replace("plan_", "")
    if plan not in PLAN_LABELS:
        return

    prices = get_plan_prices(plan)
    label = PLAN_LABELS[plan]

    buttons = [
        [InlineKeyboardButton(
            f"Telegram Stars ({prices['stars']} Stars)",
            callback_data=f"pay_stars_{plan}",
        )],
    ]
    if STRIPE_PROVIDER_TOKEN:
        buttons.append([InlineKeyboardButton(
            f"Card (${int(prices['stripe_cents'])/100:.2f})",
            callback_data=f"pay_stripe_{plan}",
        )])
    if CRYPTOBOT_API_TOKEN:
        buttons.append([InlineKeyboardButton(
            f"Crypto ({prices['crypto_usdt']} USDT)",
            callback_data=f"pay_crypto_{plan}",
        )])

    await query.edit_message_text(
        f"Plan: {label}\n\nChoose payment method:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment method selection — send invoice or crypto URL."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_", 2)  # pay_{method}_{plan}
    if len(parts) != 3:
        return
    _, method, plan = parts

    if method == "stars":
        await send_stars_invoice(update, context, plan)
    elif method == "stripe":
        await send_stripe_invoice(update, context, plan)
    elif method == "crypto":
        user_id = update.effective_user.id
        pay_url = await create_crypto_invoice(user_id, plan)
        if pay_url:
            await query.edit_message_text(
                f"Pay with crypto:\n{pay_url}\n\n"
                "After payment, use /check_payment to activate your subscription."
            )
        else:
            await query.edit_message_text(
                "Crypto payments are not available right now. Please use Stars or Card."
            )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show subscription status and usage."""
    text = get_subscription_status_text(update.effective_user.id)
    await update.message.reply_text(text)


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: grant a subscription. Usage: /grant <user_id> <plan>"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Admin only.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /grant <user_id> <plan>\nPlans: monthly, 3months, 6months, yearly, lifetime")
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid user_id.")
        return

    plan = args[1]
    if plan not in PLAN_DURATIONS:
        await update.message.reply_text(f"Unknown plan: {plan}\nValid: {', '.join(PLAN_DURATIONS.keys())}")
        return

    sub = create_subscription(target_user_id, plan, "admin_grant")
    record_payment(
        user_id=target_user_id,
        amount="0",
        currency="GRANT",
        payment_method="admin_grant",
        plan=plan,
        payment_id=f"grant_by_{update.effective_user.id}",
        status="completed",
    )

    label = PLAN_LABELS.get(plan, plan)
    expires = sub["expires_at"][:10] if sub["expires_at"] else "Never"
    await update.message.reply_text(
        f"Granted {label} subscription to user {target_user_id}.\nExpires: {expires}"
    )


async def check_payment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check pending crypto payment status."""
    user_id = update.effective_user.id
    plan = await check_crypto_payment(user_id)
    if plan:
        label = PLAN_LABELS.get(plan, plan)
        await update.message.reply_text(
            f"Payment confirmed! Your {label} subscription is now active.\n"
            "Use /status to check details."
        )
    else:
        await update.message.reply_text(
            "No completed crypto payment found.\n"
            "If you just paid, please wait a moment and try again."
        )


# ---------------------------------------------------------------------------
# Group admin commands
# ---------------------------------------------------------------------------

async def groupprompt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: set a system prompt for a group chat.
    Usage: /groupprompt <group_chat_id> <prompt text>
    """
    if update.effective_user.id not in ADMIN_IDS:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: /groupprompt <group_chat_id> <prompt text>"
        )
        return

    try:
        group_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid group chat ID.")
        return

    prompt_text = " ".join(args[1:])
    set_system_prompt(group_id, prompt_text)
    await update.message.reply_text(
        f"System prompt set for group {group_id}.\n\n"
        f"Prompt: {prompt_text[:200]}{'...' if len(prompt_text) > 200 else ''}"
    )


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

async def post_init(application):
    global _bot_username
    me = await application.bot.get_me()
    _bot_username = me.username or ""
    logger.info(f"Bot username: @{_bot_username}")

    from evolution import _clear_markers_after_delay, _MODIFIED_MARKER
    if os.path.exists(_MODIFIED_MARKER):
        asyncio.create_task(_clear_markers_after_delay(120))

    if MOLTBOOK_API_KEY:
        from moltbook_agent import run_moltbook_loop
        asyncio.create_task(run_moltbook_loop())
        logger.info("MoltBook agent enabled")
    else:
        logger.info("MoltBook agent disabled (no API key)")

    from research_agent import research_agent_loop
    asyncio.create_task(research_agent_loop())
    logger.info("Research agent enabled (ECO mode)")

    from intelligence_agent import intelligence_agent_loop
    asyncio.create_task(intelligence_agent_loop())
    logger.info("Intelligence agent enabled (ECO mode)")

    from resilience import resilience_monitor_loop
    asyncio.create_task(resilience_monitor_loop())
    logger.info("Resilience monitor enabled (ECO mode)")


def main():
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=60.0, write_timeout=20.0, pool_timeout=20.0)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).post_init(post_init).build()

    # Payment handlers (must be before generic message handlers)
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # Subscription commands
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("check_payment", check_payment_cmd))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(plan_selected_callback, pattern="^plan_"))
    app.add_handler(CallbackQueryHandler(payment_method_callback, pattern="^pay_"))

    # Standard commands
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

    # Group admin commands
    app.add_handler(CommandHandler("groupprompt", groupprompt_cmd))

    # Trading commands (admin only)
    app.add_handler(CommandHandler("connect_wallet", connect_wallet))
    app.add_handler(CommandHandler("disconnect_wallet", disconnect_wallet))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("trades", trades_cmd))
    app.add_handler(CallbackQueryHandler(trade_confirmation_callback, pattern="^trade_"))

    # Content handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    app.run_polling()


if __name__ == "__main__":
    main()
