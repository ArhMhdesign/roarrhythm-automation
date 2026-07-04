"""Telegram reporter for RoarRhythm daily stats."""
import os, requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')


def send(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram not configured"); return
    try:
        requests.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'},
            timeout=15
        )
        print("Telegram report sent")
    except Exception as e:
        print(f"Telegram error: {e}")


def report_success(topic_name, main_url, short1_url, short2_url, channel_stats):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    subs = channel_stats.get('subscribers', 'N/A')
    total = channel_stats.get('total_views', 'N/A')
    count = channel_stats.get('video_count', 'N/A')

    subs_str = f"{subs:,}" if isinstance(subs, int) else str(subs)
    total_str = f"{total:,}" if isinstance(total, int) else str(total)

    lines = [
        "✅ <b>RoarRhythm — Daily Upload Done</b>",
        f"📅 {now}",
        "",
        f"🎬 <b>Today: {topic_name}</b>",
        "",
        f"▶️ Main Video: {main_url}",
        f"📱 Short #1: {short1_url}",
        f"📱 Short #2: {short2_url}",
        "",
        "📊 <b>Channel Stats:</b>",
        f"👥 Subscribers: {subs_str}",
        f"👁 Total Views: {total_str}",
        f"🎬 Total Videos: {count}",
    ]
    send('\n'.join(lines))


def report_error(error_msg):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    send(f"❌ <b>RoarRhythm — Upload Failed</b>\n📅 {now}\n\n🚨 Error:\n{str(error_msg)[:500]}")
