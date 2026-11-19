"""Instant Telegram channel & group delivery for GoldSignal."""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx

from .store import transaction

log = logging.getLogger(__name__)
MY = ZoneInfo("Asia/Kuala_Lumpur")


def _config():
    with transaction() as store:
        saved = store.get("settings", "telegram") or {}
    token = saved.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = saved.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")
    enabled = saved.get("enabled", True) if (token and chat_id) else False
    return token, chat_id, enabled


def send_telegram(text: str, token: str = None, chat_id: str = None) -> bool:
    cfg_token, cfg_chat, enabled = _config()
    tok = token or cfg_token
    cid = chat_id or cfg_chat
    if not tok or not cid:
        return False
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        res = httpx.post(url, json=payload, timeout=8)
        if res.status_code == 200:
            return True
        log.warning("Telegram send failed: HTTP %s: %s", res.status_code, res.text[:200])
        return False
    except Exception as exc:
        log.warning("Telegram request exception: %s", exc)
        return False


def format_entry(signal: dict, now: float) -> str:
    direction = signal["direction"]
    symbol = signal.get("symbol", "XAUUSD")
    entry = signal["entry"]
    stop = signal.get("stop", signal.get("initial_stop", 0))
    targets = signal.get("targets", [])
    lane = signal.get("lane", "B")
    strategy = signal.get("strategy", "Liquidity Scalp")
    time_str = datetime.fromtimestamp(now, MY).strftime("%d %b, %H:%M:%S")

    icon = "🔴" if direction == "SELL" else "🟢"
    tp_str = " · ".join(f"TP{i+1} <b>{p:.2f}</b>" for i, p in enumerate(targets[:2]))

    return (
        f"{icon} <b>GOLDSIGNAL · {symbol}</b>\n"
        f"⚡ <b>{direction} · ENTRY SIGNAL</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Entry Zone:</b> <code>{entry[0]:.2f} – {entry[1]:.2f}</code>\n"
        f"🛑 <b>Stop Loss:</b> <code>{stop:.2f}</code>\n"
        f"🏁 <b>Targets:</b> {tp_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Lane:</b> Strategy {lane} · {strategy}\n"
        f"🕒 <b>Time:</b> {time_str} MYT\n"
        f"⚠️ <i>Verify spread & execute within entry zone.</i>"
    )


def format_headsup(direction: str, zone: dict, rejection: dict, now: float) -> str:
    time_str = datetime.fromtimestamp(now, MY).strftime("%d %b, %H:%M:%S")
    icon = "🔻" if direction == "SELL" else "🔺"
    return (
        f"⚠️ <b>GOLDSIGNAL · HEADS-UP (SETUP FORMING)</b>\n"
        f"{icon} <b>XAUUSD · M5 Rejection at M15 Zone</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Watch Zone:</b> <code>{zone.get('bottom', 0):.2f} – {zone.get('top', 0):.2f}</code>\n"
        f"🕯️ <b>M5 Candle Close:</b> <code>{rejection.get('close', 0):.2f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>Status:</b> Waiting for M1 confirmation break.\n"
        f"🕒 <b>Time:</b> {time_str} MYT\n"
        f"👉 <i>Open your MT5 / broker terminal now to get ready.</i>"
    )


def format_event(signal: dict, name: str, ts: float) -> str:
    symbol = signal.get("symbol", "XAUUSD")
    direction = signal["direction"]
    fill = signal.get("fill")
    stop = signal.get("stop")
    time_str = datetime.fromtimestamp(ts, MY).strftime("%d %b, %H:%M:%S")
    status_icon = "🎯" if "TP" in name else "🛑" if "SL" in name or name == "STOPPED" else "⚡"
    fill_info = f" (Fill: <code>{fill:.2f}</code>)" if fill else ""
    return (
        f"{status_icon} <b>GOLDSIGNAL · {name}</b>\n"
        f"<b>{symbol} {direction}</b>{fill_info}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Current Stop:</b> <code>{stop:.2f}</code>\n"
        f"🕒 <b>Time:</b> {time_str} MYT"
    )
