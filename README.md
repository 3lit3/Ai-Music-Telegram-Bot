# AI Music Telegram Bot

A Telegram bot that generates music through ElevenLabs using an interactive conversation.

## Flow

1. `/start` → **Generate Music**
2. Enter prompt (genre, mood, instruments, vocals)
3. Enter song name
4. Enter lyrics line by line → **Done with lyrics**
5. Enter duration in seconds (10–600)
6. **Generate** → MP3 delivered in chat

## Environment variables

| Variable | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `ELEVENLABS_API_KEY` | ElevenLabs API key |
| `WEBHOOK_URL` | Public base URL of the deployed service, e.g. `https://your-service.onrender.com` |
| `PORT` | Listen port (Render sets this automatically; defaults to `10000`) |

## Local development (polling)

```bash
pip install -r requirements.txt
set TELEGRAM_BOT_TOKEN=your-token
set ELEVENLABS_API_KEY=your-key
python telegram_music_bot.py
```

Leave `WEBHOOK_URL` unset to use long polling.

## Deploy to Render

`render.yaml` is a Blueprint for a free Web Service.

1. Push this repo to GitHub.
2. In Render, choose **New → Blueprint** and connect the repo.
3. Fill in the three environment variables when prompted.
4. Render deploys and sets `WEBHOOK_URL` automatically if you use the blueprint value; otherwise set it manually to the service URL.

> On Render's free plan the service sleeps after 15 minutes of inactivity. The first Telegram message after sleep wakes it (about a minute), and Telegram retries webhook delivery while it starts up.
