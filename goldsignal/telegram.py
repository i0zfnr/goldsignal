"""Instant Telegram channel & group delivery for Xeniex."""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx

from .diagnostics import record, record_in
from .grades import signal_grade
from .store import transaction

log = logging.getLogger(__name__)
MY = ZoneInfo("Asia/Kuala_Lumpur")

dispatch_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ryu-dispatcher")
_ryu_stats = {"count": 0, "last_at": 0.0}


def dispatch_telegram(text: str, category: str = "ADMIN", store=None):
    if not text:
        return None

    def policy_log(message, level):
        if store is not None:
            record_in(store, "Notification policy", message, level=level)
        else:
            record("Notification policy", message, level=level)

    if category not in ("SIGNAL", "PRICE_ENTRY_ZONE"):
        policy_log(f"Suppressed {category} Telegram delivery: {text.splitlines()[0][:160]}", "info")
        return None
    if category == "SIGNAL" and "ENTRY SIGNAL" in text and "[A" not in text:
        policy_log(f"Suppressed non-A/A+ entry signal: {text.splitlines()[0][:160]}", "warning")
        return None
    _ryu_stats["count"] += 1
    _ryu_stats["last_at"] = datetime.now().timestamp()
    try:
        return dispatch_pool.submit(send_telegram, text)
    except Exception as exc:
        log.warning("Ryu dispatch failed: %s", exc)
        return None


def ryu_telemetry():
    return _ryu_stats["count"], _ryu_stats["last_at"]


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
    strategy = signal.get("strategy", "M15 Trend Rejection")
    grade = signal_grade(signal) or "UNRATED"
    grade_stars = "⭐️⭐️⭐️⭐️ (Highest)" if grade == "A+" else "⭐️⭐️⭐️ (High)" if grade == "A" else "UNRATED"
    time_str = datetime.fromtimestamp(now, MY).strftime("%d %b, %H:%M:%S")

    icon = "🔴" if direction == "SELL" else "🟢"
    tp_str = " · ".join(f"TP{i+1} <b>{p:.2f}</b>" for i, p in enumerate(targets[:3]))

    return (
        f"{icon} <b>XENIEX · {symbol}</b>\n"
        f"⚡ <b>{direction} · ENTRY SIGNAL [{grade}]</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>Confidence Grade:</b> <code>{grade}</code> {grade_stars}\n"
        f"🎯 <b>Entry Zone:</b> <code>{entry[0]:.2f} – {entry[1]:.2f}</code>\n"
        f"🛑 <b>Stop Loss:</b> <code>{stop:.2f}</code>\n"
        f"🏁 <b>Targets:</b> {tp_str}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Lane:</b> Strategy {lane} · {strategy}\n"
        f"🕒 <b>Time:</b> {time_str} MYT\n"
        f"⚠️ <i>Verify spread & execute within entry zone.</i>"
    )


def format_zone_touch(direction: str, zone: dict, price: float, now: float) -> str:
    time_str = datetime.fromtimestamp(now, MY).strftime("%d %b, %H:%M:%S")
    is_sell = direction == "SELL"
    icon = "🔴" if is_sell else "🟢"
    zone_type = "SUPPLY ENTRY ZONE" if is_sell else "DEMAND ENTRY ZONE"
    return (
        f"🔔 <b>XENIEX · PRICE IN ENTRY ZONE</b>\n"
        f"{icon} <b>XAUUSD · M15 {zone_type}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Entry Zone:</b> <code>{zone.get('bottom', 0):.2f} – {zone.get('top', 0):.2f}</code>\n"
        f"💲 <b>Live Price:</b> <code>{price:.2f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <b>Time:</b> {time_str} MYT\n"
        f"⛔ <i>NOT A TRADE SIGNAL. DO NOT ENTER — no entry signal has been published.</i>"
    )


def format_event(signal: dict, name: str, ts: float) -> str:
    symbol = signal.get("symbol", "XAUUSD")
    direction = signal["direction"]
    fill = signal.get("fill")
    stop = signal.get("stop", 0)
    time_str = datetime.fromtimestamp(ts, MY).strftime("%d %b, %H:%M:%S")

    pips_str = ""
    if fill and "TP" in name:
        match = re.match(r"TP(\d+)", name)
        idx = int(match.group(1)) - 1 if match else 0
        targets = signal.get("targets", [])
        tp_price = targets[idx] if idx < len(targets) else fill
        pips = round(abs(tp_price - fill) / 0.10, 1)
        pips_str = f" (+{pips:.1f} pips)"

    hits = signal.get("hits", 0)
    if name == "TP1":
        action_note = "🛡️ <i>Stop Loss automatically moved to Break-Even (Entry Reference). Zero risk active!</i>"
    elif name == "TP2":
        action_note = "🔒 <i>Stop Loss trailed to TP1 level to lock in profit!</i>"
    elif name == "TP3":
        action_note = "🏆 <i>All profit targets reached! Full position closed in maximum gain!</i>"
    elif "SECURED" in name or (name == "STOPPED" and hits >= 1):
        action_note = f"🏆 <i>Price reached trailing stop. Profit on TP{hits} is locked and secured!</i>"
    elif name in ("STOPPED", "SL"):
        action_note = "🛑 <i>Position stopped out at protective stop loss.</i>"
    elif name == "FILLED":
        action_note = f"⚡ <i>Order filled at <code>{fill:.2f}</code>. Tracking active for TP1, TP2, TP3.</i>"
    else:
        action_note = ""

    is_win_exit = name in ("TP3", "TP1_SECURED", "TP2_SECURED") or (name == "STOPPED" and hits >= 1)
    status_icon = "🏆" if is_win_exit else "🎯" if "TP" in name else "🛑" if "SL" in name or name == "STOPPED" else "⚡"
    fill_info = f" (Fill: <code>{fill:.2f}</code>)" if fill else ""

    if name == "STOPPED" and hits >= 1:
        display_name = f"TP{hits} SECURED"
    else:
        display_name = name.replace("_", " ")

    lines = [
        f"{status_icon} <b>XENIEX · SIGNAL UPDATE · {display_name} HIT{pips_str}!</b>",
        f"<b>{symbol} {direction}</b>{fill_info}",
        f"━━━━━━━━━━━━━━━━━━",
        f"📌 <b>Trailing Stop:</b> <code>{stop:.2f}</code>",
        f"🕒 <b>Time:</b> {time_str} MYT",
    ]
    if action_note:
        lines.append(f"━━━━━━━━━━━━━━━━━━")
        lines.append(action_note)

    return "\n".join(lines)
