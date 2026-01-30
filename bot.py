import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import TELEGRAM_BOT_TOKEN, ADMIN_IDS, CHANNEL_ID
from claude_client import ask_stream, clear_history, set_system_prompt, generate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STREAM_EDIT_INTERVAL = 1.0


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def stream_reply(message, chat_id: int, text: str):
    sent = await message.reply_text("...")
    last_text = ""
    last_edit = 0.0

    async for current_text in ask_stream(chat_id, text):
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
    await update.message.reply_text(
        "Hi! I'm a bot powered by Claude.\n\n"
        "Commands:\n"
        "/q <question> - Ask a question\n"
        "/reset - Clear conversation history\n"
        "/system <prompt> - Set a custom system prompt\n"
        "/post <topic> - Generate and publish a post (admin)\n"
        "/news <topic> - Generate and publish news (admin)"
    )


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

    try:
        await stream_reply(update.message, update.effective_chat.id, text)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")


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
        logger.error(f"Error: {e}")
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
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"Failed to publish: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    try:
        await stream_reply(update.message, update.effective_chat.id, update.message.text)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Something went wrong. Please try again.")


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("system", system_cmd))
    app.add_handler(CommandHandler("q", question))
    app.add_handler(CommandHandler("post", post))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
