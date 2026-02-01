import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from config import TELEGRAM_BOT_TOKEN, ADMIN_IDS, CHANNEL_ID
from claude_client import ask_stream, clear_history, set_system_prompt, generate
from rate_limit import is_rate_limited
from web_tools import get_crypto_price, get_multiple_crypto_prices, search_coin
from config import MOLTBOOK_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STREAM_EDIT_INTERVAL = 1.0


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


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
        "- Any question you throw at me\n\n"
        "Optional commands:\n"
        "/price <coin> - Quick crypto price\n"
        "/growth - My learning stats\n"
        "/reset - Clear conversation\n"
        "/system <prompt> - Customize my behavior"
    )

    await update.message.reply_text(greeting)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_chat.id)
    await update.message.reply_text("Conversation history cleared.")


async def system_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args) if context.args else ""
    if not prompt:
        await update.message.reply_text("Usage: /system <prompt>")
        return
    set_system_prompt(update.effective_chat.id, prompt)
    await update.message.reply_text("System prompt set.")


async def question(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if not query:
        await update.message.reply_text("Usage: /price <coin>\nExamples: /price BTC, /price ethereum, /price BTC ETH SOL")
        return

    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    try:
        coins = query.replace(",", " ").split()
        if len(coins) == 1:
            coin = coins[0].lower()
            result = await get_crypto_price(coin)
            if "not found" in result:
                search_result = await search_coin(coin)
                if "No coins found" not in search_result:
                    first_id = search_result.split("\n")[0].split("ID: ")[1].split(" |")[0]
                    result = await get_crypto_price(first_id)
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


async def growth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from storage import get_growth_stats, get_knowledge_count

    stats = get_growth_stats()
    knowledge = get_knowledge_count()

    msg = "My growth as ClawdVC:\n\n"
    msg += "MoltBook Activity:\n"
    msg += f"- {stats.get('posts_made', 0)} original posts\n"
    msg += f"- {stats.get('comments_made', 0)} comments\n"
    msg += f"- {stats.get('topics_learned', 0)} topics browsed\n\n"
    msg += f"Knowledge Base: {knowledge} insights stored\n\n"
    msg += f"Telegram: {stats.get('conversations_helped', 0)} conversations helped\n\n"
    msg += "I'm learning and improving every day."

    await update.message.reply_text(msg)


async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID not configured.")
        return

    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Usage: /post <topic>")
        return

    try:
        text = await generate(
            f"Write a Telegram channel post about: {topic}. "
            "Keep it engaging, use markdown formatting suitable for Telegram.",
            system="You are a Telegram channel content writer. Write concise, engaging posts."
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
        await update.message.reply_text("Post published.")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text(f"Failed to publish: {e}")


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    if not CHANNEL_ID:
        await update.message.reply_text("CHANNEL_ID not configured.")
        return

    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Usage: /news <topic>")
        return

    try:
        text = await generate(
            f"Write a Telegram news post about: {topic}. "
            "Use a professional news tone, include key facts, use markdown formatting suitable for Telegram.",
            system="You are a professional news writer for a Telegram channel. Write clear, factual news posts."
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
        await update.message.reply_text("News published.")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text(f"Failed to publish: {e}")


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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Respond in all chats — no restriction to private only
    if is_rate_limited(update.effective_user.id):
        await update.message.reply_text("Rate limit exceeded. Please wait a moment.")
        return

    try:
        await stream_reply(update.message, update.effective_chat.id, update.message.text, user_id=update.effective_user.id)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("Something went wrong. Please try again.")


async def post_init(application):
    if MOLTBOOK_API_KEY:
        from moltbook_agent import run_moltbook_loop
        asyncio.create_task(run_moltbook_loop())
        logger.info("MoltBook agent enabled")
    else:
        logger.info("MoltBook agent disabled (no API key)")


def main():
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=60.0, write_timeout=20.0, pool_timeout=20.0)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("system", system_cmd))
    app.add_handler(CommandHandler("q", question))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("growth", growth))
    app.add_handler(CommandHandler("post", post))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("connect_x", connect_x))
    app.add_handler(CommandHandler("disconnect_x", disconnect_x))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
