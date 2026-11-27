"""
Telegram AI music generator bot.

Conversation flow:
    /start -> [Generate Music] -> Prompt -> Song name -> Lyrics (line by line,
    tap "Done with lyrics") -> Duration -> [Generate] -> MP3 delivered in chat.

Deploy modes:
    - Local / polling: set TELEGRAM_BOT_TOKEN and ELEVENLABS_API_KEY, then run.
    - Render Web Service (webhook): additionally set WEBHOOK_URL to the public
      service URL, e.g. https://ai-music-telegram-bot.onrender.com

Required environment variables:
    TELEGRAM_BOT_TOKEN   Telegram bot token from @BotFather
    ELEVENLABS_API_KEY   ElevenLabs API key
    WEBHOOK_URL          (optional) public base URL for webhook mode
    PORT                 (optional) port to listen on, defaults to 10000
"""

import asyncio
import html
import io
import logging
import os
import re

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ============================================================
# Configuration
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_PATH = "/telegram-webhook"

MUSIC_URL = "https://api.elevenlabs.io/v1/music"

PROMPT, TITLE, LYRICS, DURATION, CONFIRM = range(5)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ============================================================
# Music generation (adapted from generatewithmyvoice.py)
# ============================================================

def generate_song(prompt: str, title: str, lyrics: str, duration: int) -> bytes:
    """Call ElevenLabs and return the generated MP3 as bytes."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not set.")

    full_prompt = f"""
Create a complete song titled "{title}".
Style: {prompt}
Use these exact lyrics:
{lyrics}
Create a polished vocal performance with clear pronunciation, natural phrasing,
and a professional musical arrangement.
""".strip()

    payload = {
        "model_id": "music_v2",
        "prompt": full_prompt,
        "music_length_ms": duration * 1000,
        "force_instrumental": False,
    }
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    params = {"output_format": "mp3_48000_192"}

    response = requests.post(
        MUSIC_URL,
        headers=headers,
        params=params,
        json=payload,
        timeout=300,
    )
    if response.status_code != 200:
        raise RuntimeError(f"API error {response.status_code}: {response.text[:300]}")
    return response.content


# ============================================================
# Helpers
# ============================================================

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎵 Generate Music", callback_data="generate")]]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
    )


def lyrics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Done with lyrics", callback_data="lyrics_done")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ]
    )


def generate_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Generate", callback_data="generate_song")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ]
    )


def safe_filename(title: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")
    return f"{cleaned or 'song'}.mp3"


# ============================================================
# Handlers
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    text = (
        "Hello! I can turn your ideas into a song. 🎶\n\n"
        "Tap the button below to start."
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_keyboard())
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=main_keyboard())
    return ConversationHandler.END


async def ask_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Step 1/5 — Send me the <b>prompt</b>: genre, mood, instruments, vocals, etc.\n\n"
        "Example: <i>Upbeat indie pop, warm acoustic guitar, soft drums, hopeful female vocals</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    return PROMPT


async def got_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["prompt"] = update.message.text.strip()
    await update.message.reply_text(
        "Step 2/5 — Now send the <b>song name</b>.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    return TITLE


async def got_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["title"] = update.message.text.strip()
    context.user_data["lyrics"] = []
    status = await update.message.reply_text(
        "Step 3/5 — Send the <b>lyrics</b>, one line at a time.\n"
        "When you're finished, tap <b>Done with lyrics</b>.\n\n"
        "Lines received: 0",
        parse_mode="HTML",
        reply_markup=lyrics_keyboard(),
    )
    context.user_data["lyrics_status_id"] = status.message_id
    return LYRICS


async def got_lyrics_line(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["lyrics"].append(update.message.text)
    count = len(context.user_data["lyrics"])
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data["lyrics_status_id"],
            text=(
                "Step 3/5 — Send the <b>lyrics</b>, one line at a time.\n"
                "When you're finished, tap <b>Done with lyrics</b>.\n\n"
                f"Lines received: {count}"
            ),
            parse_mode="HTML",
            reply_markup=lyrics_keyboard(),
        )
    except Exception as exc:  # e.g. message not modified
        logger.debug("Could not update lyrics status: %s", exc)
    return LYRICS


async def lyrics_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    lines = context.user_data.get("lyrics", [])
    if not lines:
        await query.answer("Add at least one lyric line first.", show_alert=True)
        return LYRICS

    await query.answer()
    context.user_data["lyrics_text"] = "\n".join(lines)
    await query.edit_message_text(
        "Step 4/5 — Send the <b>duration in seconds</b> (10–600).\n\n"
        "Example: <i>120</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    return DURATION


async def got_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    if not raw.isdigit() or not 10 <= int(raw) <= 600:
        await update.message.reply_text(
            "Please send a whole number between 10 and 600 (seconds).",
            reply_markup=cancel_keyboard(),
        )
        return DURATION

    context.user_data["duration"] = int(raw)
    prompt = context.user_data["prompt"]
    title = context.user_data["title"]
    lyrics_text = context.user_data["lyrics_text"]
    preview = lyrics_text if len(lyrics_text) <= 300 else lyrics_text[:300] + "…"

    # User text is inserted into an HTML-mode message, so escape it.
    summary = (
        "Step 5/5 — Ready to generate? 🚀\n\n"
        f"<b>Title:</b> {html.escape(title)}\n"
        f"<b>Prompt:</b> {html.escape(prompt)}\n"
        f"<b>Duration:</b> {raw}s\n"
        f"<b>Lyrics:</b>\n{html.escape(preview)}\n\n"
        "Tap <b>Generate</b> when you're ready."
    )
    await update.message.reply_text(
        summary, parse_mode="HTML", reply_markup=generate_keyboard()
    )
    return CONFIRM


async def do_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()  # answer immediately; generation can take a while

    await query.edit_message_text("🎧 Generating your song… this may take a minute.")

    chat_id = update.effective_chat.id
    title = context.user_data["title"]
    prompt = context.user_data["prompt"]
    lyrics_text = context.user_data["lyrics_text"]
    duration = context.user_data["duration"]

    try:
        audio_bytes = await asyncio.to_thread(
            generate_song, prompt, title, lyrics_text, duration
        )
    except Exception as exc:
        logger.exception("Music generation failed")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Generation failed: {exc}\n\nSend /start to try again.",
        )
        return ConversationHandler.END

    await send_audio_with_retry(context.bot, chat_id, audio_bytes, title)
    await context.bot.send_message(
        chat_id=chat_id, text="✅ Done! Send /start to create another song."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    text = "Cancelled. Send /start when you want to try again."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text)
    elif update.message:
        await update.message.reply_text(text)
    return ConversationHandler.END


async def send_audio_with_retry(
    bot, chat_id: int, audio_bytes: bytes, title: str
) -> None:
    """Upload the MP3 to Telegram, retrying on slow uploads."""
    filename = safe_filename(title)
    for attempt in range(1, 4):
        try:
            audio = io.BytesIO(audio_bytes)
            audio.name = filename
            await bot.send_audio(
                chat_id=chat_id,
                audio=audio,
                title=title,
                performer="AI Music Bot",
                caption=f"🎵 {title}\nGenerated by ElevenLabs Music",
            )
            return
        except TimedOut:
            if attempt == 3:
                raise
            logger.warning("sendAudio timed out (attempt %s/3), retrying", attempt)
            await asyncio.sleep(3 * attempt)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch delivery failures so the user is not left waiting silently."""
    logger.exception("Error while handling update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "⚠️ Your song was generated but couldn't be delivered.\n"
                    "Please try /start again in a moment."
                ),
            )
        except Exception:
            logger.debug("Could not notify user about the delivery error")


# ============================================================
# App
# ============================================================

def build_app() -> Application:
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(ask_prompt, pattern="^generate$"),
        ],
        states={
            PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_prompt)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_title)],
            LYRICS: [
                CallbackQueryHandler(lyrics_done, pattern="^lyrics_done$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_lyrics_line),
            ],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_duration)],
            CONFIRM: [CallbackQueryHandler(do_generate, pattern="^generate_song$")],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        per_user=True,
        per_chat=True,
    )

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(60)
        .write_timeout(60)
        .media_write_timeout(180)
        .build()
    )
    app.add_handler(conv_handler)
    app.add_error_handler(on_error)
    return app


if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN first.")
    if not ELEVENLABS_API_KEY:
        raise SystemExit("Set ELEVENLABS_API_KEY first.")

    app = build_app()
    if WEBHOOK_URL:
        logger.info("Starting in webhook mode on port %s", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH.lstrip("/"),
            webhook_url=f"{WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}",
            drop_pending_updates=False,
        )
    else:
        logger.info("Starting in polling mode")
        app.run_polling(drop_pending_updates=True)
